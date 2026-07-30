import pytest
from fastapi.testclient import TestClient

from backend.core.config import get_settings
from backend.main import app
from backend.models.schemas import EvidenceRef, ExperimentPlan, GapItem, PaperChunk
from backend.repositories.sqlite_store import SQLiteStore


@pytest.fixture(autouse=True)
def isolated_sqlite(monkeypatch, tmp_path):
    monkeypatch.setenv("SQLITE_URL", str(tmp_path / "knowledge.db"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_knowledge_base_lists_papers_and_manages_notes() -> None:
    client = TestClient(app)
    upload = client.post(
        "/api/v1/papers/upload",
        files={"file": ("knowledge.pdf", b"Knowledge bases store notes, tags, and research history.", "application/pdf")},
    )
    doc_id = upload.json()["doc_id"]

    papers = client.get("/api/v1/knowledge/papers")
    assert papers.status_code == 200
    assert any(paper["doc_id"] == doc_id for paper in papers.json())

    note = client.post(
        "/api/v1/knowledge/notes",
        json={"title": "RAG note", "content": "Track robustness gaps", "tags": ["rag"], "related_doc_id": doc_id},
    )
    assert note.status_code == 200
    assert note.json()["note_id"]

    search = client.get("/api/v1/knowledge/search", params={"query": "robustness"})
    assert search.status_code == 200
    body = search.json()
    assert body["papers"]
    assert body["notes"]
    assert body["chunks"]


def test_knowledge_base_updates_paper_collection_metadata() -> None:
    client = TestClient(app)
    upload = client.post(
        "/api/v1/papers/upload",
        files={"file": ("tagged.pdf", b"Tagged knowledge base paper for favorite collection.", "application/pdf")},
    )
    doc_id = upload.json()["doc_id"]

    update = client.patch(
        f"/api/v1/knowledge/papers/{doc_id}",
        json={"tags": ["retrieval", "survey"], "is_favorite": True},
    )

    assert update.status_code == 200
    assert update.json()["tags"] == ["retrieval", "survey"]
    assert update.json()["is_favorite"] is True

    papers = client.get("/api/v1/knowledge/papers", params={"tag": "retrieval", "favorites_only": "true"})
    assert papers.status_code == 200
    assert any(paper["doc_id"] == doc_id for paper in papers.json())


def test_knowledge_search_includes_gap_and_experiment_history() -> None:
    client = TestClient(app)
    store = SQLiteStore(get_settings().sqlite_path)
    store.add_paper(
        "doc-robustness",
        "Robustness Evidence",
        [PaperChunk(chunk_id="chunk-robustness", doc_id="doc-robustness", page=1, text="cross-domain evidence")],
    )
    evidence = EvidenceRef(
        source="local",
        id="local:doc-robustness:chunk-robustness",
        title="Robustness Evidence",
        canonical_url="/api/v1/knowledge/papers/doc-robustness#chunk-chunk-robustness",
        doc_id="doc-robustness",
        chunk_id="chunk-robustness",
        page=1,
    )
    gap = store.save_gap(
        GapItem(
            gap_id="kb-gap-robustness",
            title="Robustness gap",
            value_level="high",
            description="Evaluate retrieval robustness with cross-domain evidence.",
            evidence_papers=[evidence.id],
            evidence_refs=[evidence],
            trust_status="local_only",
        )
    )
    experiment = store.save_experiment(
        ExperimentPlan(
            experiment_id="kb-exp-robustness",
            gap_id=gap.gap_id,
            objective="Benchmark robustness on cross-domain datasets",
            datasets=["Natural Questions"],
            metrics=["F1"],
            baselines=["BM25"],
            steps=["Run retrieval benchmark"],
            risks=["Dataset bias"],
            support_papers=[evidence.id],
            support_refs=[evidence],
            trust_status="local_only",
        )
    )

    search = client.get("/api/v1/knowledge/search", params={"query": "cross-domain"})

    assert search.status_code == 200
    body = search.json()
    assert any(item["gap_id"] == gap.gap_id for item in body["gaps"])
    assert any(item["experiment_id"] == experiment.experiment_id for item in body["experiments"])
