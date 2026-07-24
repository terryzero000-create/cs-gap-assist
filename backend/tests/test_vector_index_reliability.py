import asyncio
import os

import pytest
from fastapi.testclient import TestClient

from backend.core.config import Settings, get_settings
from backend.core.errors import ApiError
from backend.main import app
from backend.models.schemas import PaperChunk
from backend.rag.embedder import EmbeddingProfile
from backend.rag.vector_store import ChromaVectorStore, clear_vector_store_cache, get_vector_store
from backend.repositories.sqlite_store import SQLiteStore
from backend.scripts.migrate_vector_index import apply_migration, migration_plan
from backend.services.vector_index import VectorIndexManager, clear_vector_index_manager_cache


def _reset_runtime() -> None:
    get_settings.cache_clear()
    clear_vector_store_cache()
    clear_vector_index_manager_cache()


def test_real_provider_fallback_does_not_persist_upload(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SQLITE_URL", str(tmp_path / "fallback.db"))
    monkeypatch.setenv("CHROMA_DIR", str(tmp_path / "fallback-chroma"))
    monkeypatch.setenv("DEFAULT_EMBEDDING_PROVIDER", "xfyun-spark")
    monkeypatch.setenv("DEFAULT_EMBEDDING_MODEL", "query")
    monkeypatch.setenv("XFYUN_SPARK_APP_ID", "")
    monkeypatch.setenv("XFYUN_SPARK_API_KEY", "")
    monkeypatch.setenv("XFYUN_SPARK_API_SECRET", "")
    _reset_runtime()

    response = TestClient(app).post(
        "/api/v1/papers/upload",
        files={"file": ("fallback.pdf", b"Fallback vectors must never be indexed.", "application/pdf")},
    )

    assert response.status_code == 503
    assert SQLiteStore(get_settings().sqlite_path).count_chunks() == 0
    assert not (tmp_path / "fallback-chroma").exists()


def test_query_fallback_uses_sqlite_without_writing_vectors(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SQLITE_URL", str(tmp_path / "lexical.db"))
    monkeypatch.setenv("CHROMA_DIR", str(tmp_path / "lexical-chroma"))
    monkeypatch.setenv("DEFAULT_EMBEDDING_PROVIDER", "xfyun-spark")
    monkeypatch.setenv("DEFAULT_EMBEDDING_MODEL", "query")
    monkeypatch.setenv("XFYUN_SPARK_APP_ID", "")
    monkeypatch.setenv("XFYUN_SPARK_API_KEY", "")
    monkeypatch.setenv("XFYUN_SPARK_API_SECRET", "")
    _reset_runtime()
    store = SQLiteStore(get_settings().sqlite_path)
    store.add_paper(
        "doc-lexical",
        "lexical.pdf",
        [PaperChunk(chunk_id="chunk-lexical", doc_id="doc-lexical", page=2, text="Production drift evaluation for RAG systems.")],
    )

    response = TestClient(app).post(
        "/api/v1/reading/qa",
        json={"question": "production drift", "doc_ids": ["doc-lexical"]},
    )

    assert response.status_code == 200
    assert response.json()["sources"][0]["chunk_id"] == "chunk-lexical"
    assert "lexical fallback" in " ".join(response.json()["warnings"]).lower()
    assert not (tmp_path / "lexical-chroma").exists()


def test_explicit_mock_uses_isolated_profile_and_status_endpoint() -> None:
    response = TestClient(app).post(
        "/api/v1/papers/upload",
        files={"file": ("mock.pdf", b"Mock indexing is explicitly configured.", "application/pdf")},
    )
    assert response.status_code == 200

    status = TestClient(app).get("/api/v1/vector-index/status")

    assert status.status_code == 200
    body = status.json()
    assert body["state"] == "ready"
    assert body["profile"]["provider"] == "mock"
    assert "mock" in body["active_collection"]
    assert body["indexed_chunk_count"] == 1


def test_chroma_search_survives_store_recreation(tmp_path) -> None:
    profile = EmbeddingProfile(provider="mock", model="mock-embedding", dimension=2)
    chunk = PaperChunk(chunk_id="persistent", doc_id="doc", page=1, text="persistent retrieval")
    first = ChromaVectorStore(tmp_path / "chroma", profile.collection_name, profile=profile)
    first.add_chunks([chunk], [[1.0, 0.0]])

    second = ChromaVectorStore(tmp_path / "chroma", profile.collection_name, profile=profile)
    results = second.search([1.0, 0.0], doc_ids=["doc"], top_k=1)

    assert [item.chunk_id for item in results] == ["persistent"]


def test_index_write_failure_keeps_sqlite_and_marks_failed(tmp_path, monkeypatch) -> None:
    settings = Settings(
        sqlite_url=str(tmp_path / "failed.db"),
        chroma_dir=str(tmp_path / "failed-chroma"),
        default_embedding_provider="mock",
        default_embedding_model="mock-embedding",
    )
    manager = VectorIndexManager(settings)
    chunk = PaperChunk(chunk_id="failed-chunk", doc_id="failed-doc", page=1, text="keep sqlite source")
    manager.sqlite.add_paper("failed-doc", "failed.pdf", [chunk])

    class BrokenStore:
        collection_name = manager.profile.collection_name

        def add_chunks(self, chunks, vectors) -> None:
            raise RuntimeError("simulated Chroma failure")

    monkeypatch.setattr(manager, "store", lambda create_if_missing=False: BrokenStore())

    with pytest.raises(ApiError) as exc_info:
        manager.add_chunks([chunk], [[0.1] * 16])

    assert exc_info.value.code == 503
    assert manager.sqlite.count_chunks() == 1
    assert manager.sqlite.vector_entry_counts(manager.profile.key)["failed"] == 1
    assert manager.sqlite.get_vector_index_state(manager.profile.key)["state"] == "degraded"


def test_migration_lock_rejects_new_index_writes(tmp_path) -> None:
    settings = Settings(
        sqlite_url=str(tmp_path / "locked.db"),
        chroma_dir=str(tmp_path / "locked-chroma"),
        default_embedding_provider="mock",
        default_embedding_model="mock-embedding",
    )
    manager = VectorIndexManager(settings)
    assert manager.sqlite.acquire_vector_index_lock(f"{os.getpid()}:active") is True
    chunk = PaperChunk(chunk_id="locked", doc_id="doc", page=1, text="locked migration")

    with pytest.raises(ApiError) as exc_info:
        manager.add_chunks([chunk], [[0.1] * 16])

    assert exc_info.value.code == 503
    assert manager.sqlite.vector_entry_counts(manager.profile.key) == {}


def test_migration_is_dry_by_default_and_idempotent(tmp_path) -> None:
    settings = Settings(
        sqlite_url=str(tmp_path / "migration.db"),
        chroma_dir=str(tmp_path / "chroma"),
        default_embedding_provider="mock",
        default_embedding_model="mock-embedding",
    )
    sqlite = SQLiteStore(settings.sqlite_path)
    chunk = PaperChunk(chunk_id="migrate-me", doc_id="doc", page=1, text="migration content")
    sqlite.add_paper("doc", "migration.pdf", [chunk])
    legacy = get_vector_store(settings, collection_name="paper_chunks")
    legacy.add_chunks([chunk], [[0.1] * 16])
    manager = VectorIndexManager(settings)

    dry_run = migration_plan(manager)
    target_before = get_vector_store(
        settings,
        profile=manager.profile,
        collection_name=manager.profile.collection_name,
        create_if_missing=False,
    )
    assert dry_run["pending_count"] == 1
    assert target_before.collection is None
    assert manager.status()["state"] == "legacy"

    assert sqlite.acquire_vector_index_lock("999999:interrupted") is True
    assert manager.status()["state"] == "migrating"
    first = asyncio.run(apply_migration(manager))
    second = asyncio.run(apply_migration(manager))

    assert first["processed_count"] == 1
    assert first["activated"] is True
    assert second["processed_count"] == 0
    assert second["skipped_count"] == 1
    assert legacy.count() == 1
    assert manager.status()["state"] == "ready"
