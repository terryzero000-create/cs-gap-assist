import json
import sqlite3
import threading

import pytest
from fastapi.testclient import TestClient

from backend.core.config import get_settings
from backend.core.errors import ApiError
from backend.main import app
from backend.models.schemas import EvidenceRef, ExperimentPlan, GapItem, NoteCreateRequest, PaperChunk
from backend.repositories.sqlite_store import SQLiteStore, get_sqlite_store, paper_operation_lock
from backend.services import paper_deletion
from backend.services.paper_deletion import delete_paper_data
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


def test_knowledge_search_tolerates_legacy_and_malformed_tags(tmp_path) -> None:
    database = tmp_path / "legacy-tags.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE papers (
                doc_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                is_favorite INTEGER NOT NULL DEFAULT 0,
                tags TEXT,
                active_revision_id TEXT,
                ingestion_status TEXT NOT NULL DEFAULT 'ready',
                reupload_required INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT
            )
            """
        )
    store = SQLiteStore(database)
    tag_values = [None, "", "not-json", "[]", json.dumps(["legacy-tag"])]
    for index, tags in enumerate(tag_values):
        doc_id = f"legacy-tags-{index}"
        store.add_paper(
            doc_id,
            f"Legacy tags {index}",
            [
                PaperChunk(
                    chunk_id=f"legacy-tags-chunk-{index}",
                    doc_id=doc_id,
                    page=1,
                    text="legacy tag search needle",
                )
            ],
        )
        with sqlite3.connect(database) as connection:
            connection.execute("UPDATE papers SET tags = ? WHERE doc_id = ?", (tags, doc_id))

    papers = {paper.doc_id: paper for paper in store.list_papers()}
    assert [papers[f"legacy-tags-{index}"].tags for index in range(5)] == [[], [], [], [], ["legacy-tag"]]

    fts_results = store.search_knowledge_chunks("needle", tag="legacy-tag")
    assert [chunk.doc_id for chunk in fts_results] == ["legacy-tags-4"]
    like_results = store.search_knowledge_chunks("nee", tag="legacy-tag")
    assert [chunk.doc_id for chunk in like_results] == ["legacy-tags-4"]
    assert {
        chunk.doc_id for chunk in store.search_knowledge_chunks("needle")
    } == {f"legacy-tags-{index}" for index in range(5)}


def test_delete_failure_keeps_sqlite_chunks_and_vectors(monkeypatch) -> None:
    settings = get_settings()
    store = get_sqlite_store(settings.sqlite_path)
    chunk = PaperChunk(
        chunk_id="failed-delete-chunk",
        doc_id="failed-delete-doc",
        page=1,
        text="vector must remain after failed deletion",
    )
    store.add_paper(chunk.doc_id, "failed-delete.pdf", [chunk])
    vector_manager = VectorIndexManager(settings)
    vector_manager.add_chunks([chunk], [[0.5] * vector_manager.profile.dimension])

    class FailingManager:
        def __init__(self, _settings) -> None:
            pass

        def collection_name(self) -> str:
            return "failing-delete-collection"

    class FailingVectorStore:
        def delete_chunks(self, _chunk_ids) -> None:
            raise RuntimeError("injected vector delete failure")

    monkeypatch.setattr(paper_deletion, "VectorIndexManager", FailingManager)
    monkeypatch.setattr(paper_deletion, "get_vector_store", lambda *_args, **_kwargs: FailingVectorStore())

    with pytest.raises(ApiError) as error:
        delete_paper_data(settings, store, chunk.doc_id)

    assert error.value.error_code == "PAPER_VECTOR_DELETE_FAILED"
    assert [item.chunk_id for item in store.list_chunks([chunk.doc_id])] == [chunk.chunk_id]
    assert chunk.chunk_id in vector_manager.store(create_if_missing=False).ids()


def test_delete_and_replacement_upload_are_serialized_and_replacement_rechecks_state(monkeypatch) -> None:
    settings = get_settings()
    store = get_sqlite_store(settings.sqlite_path)
    doc_id = "serialized-delete-doc"
    store.add_paper(
        doc_id,
        "serialized.pdf",
        [PaperChunk(chunk_id="serialized-chunk", doc_id=doc_id, page=1, text="serialized evidence")],
    )
    delete_started = threading.Event()
    allow_delete = threading.Event()
    replacement_staged = threading.Event()
    replacement_result: dict[str, object] = {}

    class BlockingManager:
        def __init__(self, _settings) -> None:
            pass

        def collection_name(self) -> str:
            return "blocking-delete-collection"

    class BlockingVectorStore:
        def delete_chunks(self, _chunk_ids) -> None:
            delete_started.set()
            assert allow_delete.wait(3)

    monkeypatch.setattr(paper_deletion, "VectorIndexManager", BlockingManager)
    monkeypatch.setattr(
        paper_deletion,
        "get_vector_store",
        lambda *_args, **_kwargs: BlockingVectorStore(),
    )

    from backend.api import paper_upload

    original_persist = paper_upload.persist_upload_file

    async def tracked_persist(*args, **kwargs):
        result = await original_persist(*args, **kwargs)
        replacement_staged.set()
        return result

    class NoopWorker:
        async def enqueue(self, _upload_id: str) -> None:
            return None

    monkeypatch.setattr(paper_upload, "persist_upload_file", tracked_persist)
    monkeypatch.setattr(paper_upload, "get_ingestion_worker", lambda _settings: NoopWorker())

    def run_delete() -> None:
        try:
            replacement_result["delete"] = delete_paper_data(settings, store, doc_id)
        except Exception as exc:  # pragma: no cover - assertion below reports unexpected errors
            replacement_result["delete_error"] = exc

    def run_replacement() -> None:
        from fastapi.testclient import TestClient

        with TestClient(app) as client:
            replacement_result["upload"] = client.post(
                "/api/v1/paper-uploads",
                data={"replace_doc_id": doc_id},
                headers={"Idempotency-Key": "serialized-replacement-key"},
                files={"file": ("replacement.pdf", b"replacement", "application/pdf")},
            )

    delete_thread = threading.Thread(target=run_delete)
    delete_thread.start()
    assert delete_started.wait(3)
    replacement_thread = threading.Thread(target=run_replacement)
    replacement_thread.start()
    assert replacement_staged.wait(3)
    allow_delete.set()
    delete_thread.join(3)
    replacement_thread.join(3)

    assert "delete_error" not in replacement_result
    assert replacement_result["upload"].status_code == 404
    assert store.get_paper(doc_id) is None
    assert not list((settings.documents_path / doc_id).glob("*.pdf"))


def test_paper_operation_locks_are_isolated_by_doc_id() -> None:
    acquired = threading.Event()

    def acquire_other_document() -> None:
        with paper_operation_lock("independent-doc-b"):
            acquired.set()

    with paper_operation_lock("independent-doc-a"):
        thread = threading.Thread(target=acquire_other_document)
        thread.start()
        assert acquired.wait(1)
        thread.join(1)


def test_experiment_deduplication_canonicalizes_support_ref_order() -> None:
    store = get_sqlite_store(get_settings().sqlite_path)
    chunks = [
        PaperChunk(chunk_id="signature-chunk-a", doc_id="signature-doc", page=1, text="a"),
        PaperChunk(chunk_id="signature-chunk-b", doc_id="signature-doc", page=2, text="b"),
        PaperChunk(chunk_id="signature-chunk-c", doc_id="signature-doc", page=3, text="c"),
    ]
    store.add_paper("signature-doc", "signature.pdf", chunks)

    def ref(chunk: PaperChunk) -> EvidenceRef:
        return EvidenceRef(
            source="local",
            id=f"local:{chunk.doc_id}:{chunk.chunk_id}",
            title="signature.pdf",
            canonical_url=f"/api/v1/knowledge/papers/{chunk.doc_id}#chunk-{chunk.chunk_id}",
            doc_id=chunk.doc_id,
            chunk_id=chunk.chunk_id,
            page=chunk.page,
        )

    first, second, third = (ref(chunk) for chunk in chunks)
    first_experiment = store.save_experiment(
        ExperimentPlan(
            gap_id="signature-gap",
            objective="Compare canonical references",
            datasets=["dataset"],
            metrics=["metric"],
            baselines=["baseline"],
            steps=["run"],
            risks=["risk"],
            support_papers=[first.id, second.id],
            support_refs=[first, second],
            trust_status="local_only",
        )
    )
    reused = store.save_experiment(
        ExperimentPlan(
            gap_id="signature-gap",
            objective="Compare canonical references",
            datasets=["dataset"],
            metrics=["metric"],
            baselines=["baseline"],
            steps=["run"],
            risks=["risk"],
            support_papers=[second.id, first.id],
            support_refs=[second, first],
            trust_status="local_only",
        )
    )
    different = store.save_experiment(
        ExperimentPlan(
            gap_id="signature-gap",
            objective="Compare canonical references",
            datasets=["dataset"],
            metrics=["metric"],
            baselines=["baseline"],
            steps=["run"],
            risks=["risk"],
            support_papers=[first.id, third.id],
            support_refs=[first, third],
            trust_status="local_only",
        )
    )

    assert reused.experiment_id == first_experiment.experiment_id
    assert [item.id for item in reused.support_refs] == [first.id, second.id]
    assert different.experiment_id != first_experiment.experiment_id
    assert len(store.list_experiments(gap_id="signature-gap")) == 2
