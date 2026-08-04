import asyncio
from inspect import iscoroutinefunction

import pytest
from fastapi.routing import APIRoute

from backend.llm.llm_service import ChatProviderUnavailable, DeepSeekChatProvider
from backend.core.config import Settings
from backend.main import app
from backend.models.schemas import EvidenceRef, ExperimentPlan, GapItem, NoteCreateRequest, PaperChunk
from backend.rag.vector_store import ChromaVectorStore, InMemoryVectorStore
from backend.repositories.sqlite_store import SQLiteStore


def test_all_api_v1_routes_are_async() -> None:
    """All public API endpoints under /api/v1 must be async functions."""
    api_routes = [route for route in app.routes if isinstance(route, APIRoute) and route.path.startswith("/api/v1")]

    assert api_routes
    assert all(iscoroutinefunction(route.endpoint) for route in api_routes)


def test_sqlite_store_covers_foundation_metadata_crud(tmp_path) -> None:
    """SQLite stores papers, gap history, experiment history, favorites, notes, and tags."""
    store = SQLiteStore(tmp_path / "app.db")
    chunk = PaperChunk(chunk_id="chunk-1", doc_id="doc-1", page=1, text="retrieval augmented generation")

    paper = store.add_paper("doc-1", "RAG Paper", [chunk], tags=["rag"], is_favorite=True)
    evidence = EvidenceRef(
        source="local",
        id="local:doc-1:chunk-1",
        title="RAG Paper",
        canonical_url="/api/v1/knowledge/papers/doc-1#chunk-chunk-1",
        doc_id="doc-1",
        chunk_id="chunk-1",
        page=1,
    )
    gap = store.save_gap(
        GapItem(
            gap_id="gap-1",
            title="Missing robustness",
            value_level="high",
            description="Need broader tests.",
            evidence_papers=[evidence.id],
            evidence_refs=[evidence],
            trust_status="local_only",
        )
    )
    experiment = store.save_experiment(
        ExperimentPlan(
            experiment_id="exp-1",
            gap_id=gap.gap_id,
            objective="Evaluate robustness",
            datasets=["NQ"],
            metrics=["F1"],
            baselines=["BM25"],
            steps=["Run benchmark"],
            risks=["Small sample"],
            support_papers=[evidence.id],
            support_refs=[evidence],
            trust_status="local_only",
        )
    )
    note = store.add_note(NoteCreateRequest(title="Robustness note", content="Use cross-domain tags.", tags=["rag"], related_doc_id=paper.doc_id))

    assert store.list_papers()[0].is_favorite is True
    assert store.list_papers()[0].tags == ["rag"]
    assert store.list_gaps()[0].gap_id == gap.gap_id
    assert store.list_experiments()[0].experiment_id == experiment.experiment_id
    assert store.list_notes("Robustness")[0].note_id == note.note_id


def test_vector_store_filters_by_doc_id_tags_and_module_source(tmp_path) -> None:
    """The Chroma wrapper supports doc_id, tag, and module_source filtering semantics."""
    store = ChromaVectorStore(persist_directory=tmp_path / "chroma")
    chunks = [
        PaperChunk(chunk_id="a", doc_id="doc-a", page=1, text="rag retrieval"),
        PaperChunk(chunk_id="b", doc_id="doc-b", page=1, text="vision transformer"),
    ]
    vectors = [[1.0, 0.0], [0.0, 1.0]]

    store.add_chunks(chunks, vectors, tags_by_chunk={"a": ["rag"], "b": ["vision"]}, module_source="foundation-test")

    results = store.search([1.0, 0.0], doc_ids=["doc-a"], tags=["rag"], module_source="foundation-test", top_k=3)

    assert [chunk.chunk_id for chunk in results] == ["a"]


def test_in_memory_vector_store_keeps_filter_semantics() -> None:
    """The fallback vector store mirrors the filtering contract used by the Chroma wrapper."""
    store = InMemoryVectorStore()
    chunks = [
        PaperChunk(chunk_id="a", doc_id="doc-a", page=1, text="rag retrieval"),
        PaperChunk(chunk_id="b", doc_id="doc-b", page=1, text="vision transformer"),
    ]
    store.add_chunks(chunks, [[1.0, 0.0], [0.0, 1.0]], tags_by_chunk={"a": ["rag"], "b": ["vision"]}, module_source="upload")

    assert store.search([1.0, 0.0], tags=["rag"], module_source="upload")[0].chunk_id == "a"
    assert store.all_chunks(doc_ids=["doc-b"], tags=["vision"], module_source="upload")[0].chunk_id == "b"


def test_deepseek_provider_fails_closed_without_api_key() -> None:
    """Missing DEEPSEEK_API_KEY must not create implicit mock output."""
    provider = DeepSeekChatProvider(Settings(deepseek_api_key=None))

    with pytest.raises(ChatProviderUnavailable, match="DEEPSEEK_API_KEY missing"):
        asyncio.run(provider.generate("hello", "deepseek-v4-pro"))
