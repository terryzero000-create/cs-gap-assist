import asyncio
import json
import sqlite3
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from backend.core.config import Settings, get_settings
from backend.llm.chains import gap_chain, qa_chain
from backend.main import app
from backend.models.schemas import EvidenceRef, GapAnalysisRequest, GapItem, PaperChunk, ReadingQARequest
from backend.rag.embedder import EmbeddingProfile
from backend.rag.vector_store import ChromaVectorStore
from backend.repositories.sqlite_store import SQLiteStore
from backend.scripts.clean_untrusted_evidence import clean_database
from backend.services.arxiv_search import ArxivSearchClient
from backend.services.citation_graph import OpenAlexCitationClient
from backend.services.external_paper import ExternalPaper


def test_arxiv_failures_never_create_fallback_papers() -> None:
    disabled, disabled_warnings = asyncio.run(ArxivSearchClient(enabled=False).search("rag", limit=5))

    def failing_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="unavailable")

    failed, failed_warnings = asyncio.run(
        ArxivSearchClient(transport=httpx.MockTransport(failing_handler)).search("rag", limit=5)
    )

    assert disabled == []
    assert failed == []
    assert "unavailable" in disabled_warnings[0]
    assert "failed" in failed_warnings[0]


def test_arxiv_empty_and_rate_limited_responses_stay_empty() -> None:
    empty_feed = '<feed xmlns="http://www.w3.org/2005/Atom"></feed>'
    empty, empty_warnings = asyncio.run(
        ArxivSearchClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, text=empty_feed))
        ).search("rag", limit=5)
    )
    attempts = 0

    def limited_handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(429, headers={"Retry-After": "0"})

    limited, limited_warnings = asyncio.run(
        ArxivSearchClient(transport=httpx.MockTransport(limited_handler)).search("rag", limit=5)
    )

    assert empty == []
    assert empty_warnings == ["arXiv returned no results."]
    assert limited == []
    assert attempts == 3
    assert "429" in limited_warnings[0]


def test_openalex_rate_limit_never_creates_demo_graph_data() -> None:
    attempts = 0

    def limited_handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(429, headers={"Retry-After": "0"})

    papers, warnings = asyncio.run(
        OpenAlexCitationClient(
            api_key="test-key",
            transport=httpx.MockTransport(limited_handler),
        ).search("rag", limit=5)
    )

    assert papers == []
    assert attempts == 3
    assert "429" in warnings[0]


def test_gap_rejects_model_invented_evidence(monkeypatch, tmp_path) -> None:
    class TrustedArxiv:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def search(self, query: str, limit: int = 5):
            return [
                ExternalPaper(
                    paper_id="arxiv-2501.00001",
                    title="Trusted evidence",
                    abstract="A real response fixture.",
                    canonical_url="https://arxiv.org/abs/2501.00001",
                )
            ], []

    class InventingProvider:
        async def generate(self, prompt: str, model: str | None = None):
            return json.dumps(
                {
                    "gaps": [
                        {
                            "title": "Invented gap",
                            "value_level": "high",
                            "description": "This item cites an unknown paper.",
                            "evidence_papers": ["arxiv-9999.99999"],
                        }
                    ]
                }
            ), []

    monkeypatch.setattr(gap_chain, "ArxivSearchClient", TrustedArxiv)
    monkeypatch.setattr(gap_chain, "get_chat_provider", lambda settings, provider=None: InventingProvider())
    settings = Settings(sqlite_url=str(tmp_path / "gap.db"), external_network_enabled=True)

    response = asyncio.run(
        gap_chain.analyze_research_gaps(
            GapAnalysisRequest(topic="trusted retrieval", doc_ids=[]),
            settings,
        )
    )

    assert response.gaps == []
    assert response.evidence_status == "insufficient_evidence"
    assert SQLiteStore(settings.sqlite_path).list_gaps(include_unverified=True) == []


def test_irrelevant_question_does_not_call_chat_provider(monkeypatch, tmp_path) -> None:
    store = SQLiteStore(tmp_path / "qa.db")
    store.add_paper(
        "doc-1",
        "Vision Paper",
        [PaperChunk(chunk_id="chunk-1", doc_id="doc-1", page=1, text="Convolutional image segmentation.")],
    )
    monkeypatch.setattr(
        qa_chain,
        "get_chat_provider",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("chat provider must not be called")),
    )
    settings = Settings(
        sqlite_url=str(tmp_path / "qa.db"),
        chroma_dir=str(tmp_path / "chroma"),
        default_embedding_provider="xfyun-spark",
        xfyun_spark_app_id=None,
        xfyun_spark_api_key=None,
        xfyun_spark_api_secret=None,
    )

    response = asyncio.run(
        qa_chain.answer_question(
            ReadingQARequest(question="quantum compiler verification", doc_ids=["doc-1"]),
            settings,
        )
    )

    assert response.sources == []
    assert response.evidence_status == "insufficient_evidence"


def test_gap_retrieves_relevant_non_first_chunk_and_respects_doc_ids(monkeypatch, tmp_path) -> None:
    store = SQLiteStore(tmp_path / "gap.db")
    chunks = [
        PaperChunk(chunk_id=f"chunk-{index}", doc_id="selected", page=index, text=f"Unrelated introduction {index}.")
        for index in range(1, 6)
    ]
    chunks.append(
        PaperChunk(
            chunk_id="chunk-6",
            doc_id="selected",
            page=6,
            text="Production drift evaluation reveals long-term RAG robustness failures.",
        )
    )
    store.add_paper("selected", "Selected Paper", chunks)
    store.add_paper(
        "excluded",
        "Excluded Paper",
        [PaperChunk(chunk_id="excluded-1", doc_id="excluded", page=1, text="Production drift evaluation secret.")],
    )

    class NoArxiv:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def search(self, query: str, limit: int = 5):
            return [], ["arXiv unavailable in test."]

    class GroundedProvider:
        async def generate(self, prompt: str, model: str | None = None):
            assert "chunk-6" in prompt
            assert "excluded-1" not in prompt
            return json.dumps(
                {
                    "gaps": [
                        {
                            "title": "Long-term drift evidence is incomplete",
                            "value_level": "high",
                            "description": "Existing work reports production drift without long-term controls.",
                            "evidence_papers": ["local:selected:chunk-6"],
                        }
                    ]
                }
            ), []

    monkeypatch.setattr(gap_chain, "ArxivSearchClient", NoArxiv)
    monkeypatch.setattr(gap_chain, "get_chat_provider", lambda settings, provider=None: GroundedProvider())
    settings = Settings(
        sqlite_url=str(tmp_path / "gap.db"),
        chroma_dir=str(tmp_path / "chroma"),
        default_embedding_provider="xfyun-spark",
        xfyun_spark_app_id=None,
        xfyun_spark_api_key=None,
        xfyun_spark_api_secret=None,
    )

    response = asyncio.run(
        gap_chain.analyze_research_gaps(
            GapAnalysisRequest(topic="production drift evaluation", doc_ids=["selected"]),
            settings,
        )
    )

    assert response.evidence_status == "local_only"
    assert response.gaps[0].evidence_refs[0].chunk_id == "chunk-6"
    assert SQLiteStore(settings.sqlite_path).list_gaps()[0].gap_id == response.gaps[0].gap_id


def test_real_chat_failure_preserves_sources_but_generates_no_conclusion(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "qa.db")
    store.add_paper(
        "doc-1",
        "RAG Paper",
        [PaperChunk(chunk_id="chunk-1", doc_id="doc-1", page=1, text="RAG production drift evaluation.")],
    )
    settings = Settings(
        sqlite_url=str(tmp_path / "qa.db"),
        chroma_dir=str(tmp_path / "chroma"),
        default_chat_provider="deepseek",
        deepseek_api_key=None,
        default_embedding_provider="xfyun-spark",
        xfyun_spark_app_id=None,
        xfyun_spark_api_key=None,
        xfyun_spark_api_secret=None,
    )

    response = asyncio.run(
        qa_chain.answer_question(
            ReadingQARequest(question="RAG production drift evaluation", doc_ids=["doc-1"]),
            settings,
        )
    )

    assert response.sources
    assert response.evidence_status == "provider_unavailable"
    assert "未生成研究结论" in response.answer


def test_mock_experiment_response_is_never_persisted() -> None:
    store = SQLiteStore(get_settings().sqlite_path)
    store.add_paper(
        "doc-1",
        "Local Evidence",
        [PaperChunk(chunk_id="chunk-1", doc_id="doc-1", page=1, text="RAG robustness evidence.")],
    )
    evidence = EvidenceRef(
        source="local",
        id="local:doc-1:chunk-1",
        title="Local Evidence",
        canonical_url="/api/v1/knowledge/papers/doc-1#chunk-chunk-1",
        doc_id="doc-1",
        chunk_id="chunk-1",
        page=1,
    )
    store.save_gap(
        GapItem(
            gap_id="trusted-gap",
            title="Trusted gap",
            value_level="high",
            description="A locally supported gap.",
            evidence_papers=[evidence.id],
            evidence_refs=[evidence],
            trust_status="local_only",
        )
    )

    response = TestClient(app).post("/api/v1/experiments/suggest", json={"gap_id": "trusted-gap"})

    assert response.status_code == 200
    assert response.json()["evidence_status"] == "synthetic"
    assert SQLiteStore(get_settings().sqlite_path).list_experiments(gap_id="trusted-gap") == []


def test_cleanup_backs_up_deletes_known_fake_rows_and_hides_ambiguous_legacy(tmp_path) -> None:
    database = tmp_path / "app.db"
    store = SQLiteStore(database)
    store.add_paper(
        "doc-1",
        "Preserved Paper",
        [PaperChunk(chunk_id="chunk-1", doc_id="doc-1", page=1, text="Preserve this evidence.")],
    )
    with sqlite3.connect(database) as conn:
        conn.execute(
            """
            INSERT INTO gaps
                (gap_id, title, value_level, description, evidence_papers, evidence_refs, trust_status, created_at)
            VALUES (?, ?, ?, ?, ?, '[]', 'legacy_unverified', ?)
            """,
            ("fake-gap", "Fake", "mid", "Fake gap", json.dumps(["arxiv-1"]), "2025-01-01T00:00:00Z"),
        )
        conn.execute(
            """
            INSERT INTO experiments
                (experiment_id, gap_id, objective, datasets, metrics, baselines, steps, risks,
                 support_papers, support_refs, trust_status)
            VALUES (?, ?, ?, '[]', '[]', '[]', '[]', '[]', ?, '[]', 'legacy_unverified')
            """,
            ("fake-experiment", "fake-gap", "Fake plan", json.dumps(["fallback-support-paper-1"])),
        )
        conn.execute(
            """
            INSERT INTO gaps
                (gap_id, title, value_level, description, evidence_papers, evidence_refs, trust_status, created_at)
            VALUES (?, ?, ?, ?, ?, '[]', 'legacy_unverified', ?)
            """,
            ("ambiguous-gap", "Ambiguous", "mid", "Unknown provenance", json.dumps(["paper-x"]), "2025-01-01T00:00:00Z"),
        )

    report = clean_database(database, apply=True)

    assert Path(report["backup"]).exists()
    assert Path(report["report"]).exists()
    assert report["deleted_gaps"] == {"fake-gap": "arxiv-1"}
    assert "fake-experiment" in report["deleted_experiments"]
    assert SQLiteStore(database).get_paper("doc-1") is not None
    assert SQLiteStore(database).list_gaps() == []
    assert [gap.gap_id for gap in SQLiteStore(database).list_gaps(include_unverified=True)] == ["ambiguous-gap"]


def test_cosine_index_schema_and_production_sources_have_no_fake_generators(tmp_path) -> None:
    profile = EmbeddingProfile(provider="xfyun-spark", model="spark-embedding", dimension=2560)
    metadata = ChromaVectorStore._profile_metadata(profile)
    backend_root = Path(__file__).resolve().parents[1]
    production_paths = [
        *backend_root.joinpath("llm").rglob("*.py"),
        *backend_root.joinpath("services").rglob("*.py"),
    ]

    assert metadata["hnsw:space"] == "cosine"
    assert profile.schema_version == 3
    assert all("fallback-support-paper-" not in path.read_text(encoding="utf-8") for path in production_paths)
    assert all("arXiv study on" not in path.read_text(encoding="utf-8") for path in production_paths)
    assert all("OpenAIEmbeddingProvider" not in path.read_text(encoding="utf-8") for path in production_paths)
