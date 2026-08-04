import pytest
from fastapi.testclient import TestClient

from backend.core.config import get_settings
from backend.main import app
from backend.models.schemas import EvidenceRef, ExperimentPlan, GapItem, NoteCreateRequest, PaperChunk
from backend.repositories.sqlite_store import SQLiteStore, get_sqlite_store
from backend.services.vector_index import VectorIndexManager


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
        files={"file": ("knowledge.pdf", b"Knowledge bases store robustness notes, tags, and research history.", "application/pdf")},
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


def test_knowledge_base_deletes_paper_artifacts_and_detaches_notes() -> None:
    settings = get_settings()
    store = get_sqlite_store(settings.sqlite_path)
    doc_id = "delete-doc"
    revision_id = "delete-revision"
    upload_id = "delete-upload"
    source_path = settings.documents_path / doc_id / f"{revision_id}.pdf"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(b"%PDF-1.7 deletion fixture")
    store.create_upload(
        upload_id=upload_id,
        idempotency_key="delete-idempotency-key",
        doc_id=doc_id,
        revision_id=revision_id,
        title="delete-me.pdf",
        content_sha256="delete-sha",
        source_path=str(source_path),
        mime_type="application/pdf",
        size_bytes=source_path.stat().st_size,
    )
    store.update_upload_status(upload_id, "validating")
    store.update_upload_status(
        upload_id,
        "failed",
        retryable=True,
        error_code="TEST_FAILURE",
    )
    chunk = PaperChunk(
        chunk_id="delete-chunk",
        doc_id=doc_id,
        page=1,
        text="delete this indexed evidence",
    )
    store.add_paper(doc_id, "delete-me.pdf", [chunk])
    note = store.add_note(
        NoteCreateRequest(
            title="Keep this note",
            content="The note survives paper deletion.",
            related_doc_id=doc_id,
        )
    )
    vector_manager = VectorIndexManager(settings)
    vector_manager.add_chunks(
        [chunk],
        [[0.25] * vector_manager.profile.dimension],
    )
    evidence = EvidenceRef(
        source="local",
        id=f"local:{doc_id}:{chunk.chunk_id}",
        title="delete-me.pdf",
        canonical_url=f"/api/v1/knowledge/papers/{doc_id}#chunk-{chunk.chunk_id}",
        doc_id=doc_id,
        chunk_id=chunk.chunk_id,
        page=1,
    )
    gap = store.save_gap(
        GapItem(
            gap_id="delete-gap",
            title="Historical gap",
            value_level="high",
            description="Keep this result after its source is deleted.",
            evidence_papers=[evidence.id],
            evidence_refs=[evidence],
            trust_status="local_only",
        )
    )
    experiment = store.save_experiment(
        ExperimentPlan(
            experiment_id="delete-experiment",
            gap_id=gap.gap_id,
            objective="Keep this experiment history",
            datasets=["dataset"],
            metrics=["metric"],
            baselines=["baseline"],
            steps=["run"],
            risks=["source lifecycle"],
            support_papers=[evidence.id],
            support_refs=[evidence],
            trust_status="local_only",
        )
    )

    client = TestClient(app)
    response = client.delete(f"/api/v1/knowledge/papers/{doc_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["doc_id"] == doc_id
    assert body["deleted_chunk_count"] == 1
    assert body["deleted_revision_count"] == 1
    assert body["deleted_upload_count"] == 1
    assert body["deleted_file_count"] == 1
    assert body["detached_note_count"] == 1
    assert body["unavailable_gap_ref_count"] == 1
    assert body["unavailable_experiment_ref_count"] == 1
    assert store.get_paper(doc_id) is None
    assert store.get_upload(upload_id) is None
    assert store.list_chunks([doc_id]) == []
    assert not source_path.exists()
    stored_note = next(item for item in store.list_notes() if item.note_id == note.note_id)
    assert stored_note.related_doc_id is None
    assert "delete-chunk" not in vector_manager.store(create_if_missing=False).ids()
    stored_gap = next(item for item in store.list_gaps() if item.gap_id == gap.gap_id)
    stored_experiment = next(
        item for item in store.list_experiments() if item.experiment_id == experiment.experiment_id
    )
    assert stored_gap.evidence_refs[0].is_available is False
    assert stored_gap.evidence_refs[0].unavailable_reason == "source_deleted"
    assert stored_experiment.support_refs[0].is_available is False
    assert stored_experiment.support_refs[0].unavailable_reason == "source_deleted"
    assert store.trusted_evidence_refs(stored_gap.evidence_refs) == []

    gap_history = client.get("/api/v1/gaps/history").json()
    experiment_history = client.get("/api/v1/experiments/history").json()
    assert gap_history["evidence_status"] == "insufficient_evidence"
    assert experiment_history["evidence_status"] == "insufficient_evidence"
    assert gap_history["gaps"][0]["evidence_refs"][0]["is_available"] is False
    assert experiment_history["experiments"][0]["support_refs"][0]["is_available"] is False


def test_knowledge_base_delete_rejects_missing_paper() -> None:
    response = TestClient(app).delete("/api/v1/knowledge/papers/missing-doc")

    assert response.status_code == 404
    assert response.json()["error_code"] == "PAPER_NOT_FOUND"


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


def test_knowledge_search_chunks_are_bounded_without_full_corpus_load(monkeypatch) -> None:
    store = get_sqlite_store(get_settings().sqlite_path)
    store.add_paper(
        "bounded-doc",
        "Bounded Search",
        [
            PaperChunk(
                chunk_id=f"bounded-{index}",
                doc_id="bounded-doc",
                page=index + 1,
                ordinal=index,
                text=f"bounded retrieval evidence {index}",
            )
            for index in range(60)
        ],
    )

    def full_load_is_forbidden(*_args, **_kwargs):
        raise AssertionError("knowledge search must not call list_chunks")

    monkeypatch.setattr(store, "list_chunks", full_load_is_forbidden)
    response = TestClient(app).get(
        "/api/v1/knowledge/search",
        params={"query": "", "limit": 7},
    )

    assert response.status_code == 200
    assert len(response.json()["chunks"]) == 7
