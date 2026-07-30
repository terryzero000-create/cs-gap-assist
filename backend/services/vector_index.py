import math
import re
from dataclasses import dataclass
from functools import lru_cache

from backend.core.config import Settings, get_settings
from backend.core.errors import ApiError
from backend.models.schemas import PaperChunk
from backend.rag.embedder import EmbeddingProfile, EmbeddingProvider, get_embedding_provider
from backend.rag.vector_store import ChromaVectorStore, chunk_content_hash, clear_vector_store_cache, get_vector_store
from backend.repositories.sqlite_store import SQLiteStore


LEGACY_COLLECTION = "paper_chunks"


def configured_embedding_provider(settings: Settings, document: bool = False) -> EmbeddingProvider:
    """Resolve the single deployment embedding provider and its document/query mode."""
    model = "para" if document and settings.default_embedding_provider == "xfyun-spark" else settings.default_embedding_model
    return get_embedding_provider(settings, provider=settings.default_embedding_provider, model=model)


def provider_profile(provider: EmbeddingProvider) -> EmbeddingProfile:
    """Return the declared profile for a registered embedding provider."""
    profile = getattr(provider, "profile", None)
    if not isinstance(profile, EmbeddingProfile):
        raise RuntimeError("Embedding provider does not declare an index profile.")
    return profile


def lexical_chunk_search(chunks: list[PaperChunk], query: str, top_k: int) -> list[PaperChunk]:
    """Rank SQLite chunks deterministically when semantic retrieval is unavailable."""
    query_tokens = _tokens(query)
    scored: list[PaperChunk] = []
    for chunk in chunks:
        chunk_tokens = _tokens(chunk.text)
        overlap = len(query_tokens & chunk_tokens)
        denominator = math.sqrt(max(len(query_tokens), 1) * max(len(chunk_tokens), 1))
        score = overlap / denominator if overlap else 0.0
        scored.append(chunk.model_copy(update={"score": score}))
    return sorted(scored, key=lambda item: (item.score or 0.0, -item.page, item.chunk_id), reverse=True)[:top_k]


def _tokens(text: str) -> set[str]:
    normalized = text.casefold()
    words = re.findall(r"[a-z0-9_]{2,}", normalized)
    latin = set(words)
    for word in words:
        for suffix in ("ing", "ed", "es", "s"):
            if word.endswith(suffix) and len(word) - len(suffix) >= 3:
                latin.add(word[: -len(suffix)])
                break
    latin.update(
        "".join(word[0] for word in words[index : index + 3])
        for index in range(max(len(words) - 2, 0))
    )
    cjk = "".join(re.findall(r"[\u3400-\u9fff]", normalized))
    bigrams = {cjk[index : index + 2] for index in range(max(len(cjk) - 1, 0))}
    return latin | bigrams


@dataclass
class VectorIndexManager:
    """Coordinate active collections with SQLite source-of-truth state."""

    settings: Settings

    def __post_init__(self) -> None:
        self.sqlite = SQLiteStore(self.settings.sqlite_path)
        self.profile = provider_profile(configured_embedding_provider(self.settings))

    def collection_name(self) -> str:
        state = self.sqlite.get_vector_index_state(self.profile.key)
        if state and state.get("active_collection"):
            return str(state["active_collection"])
        return self.profile.collection_name

    def store(self, create_if_missing: bool = False) -> ChromaVectorStore:
        name = self.collection_name()
        return get_vector_store(
            self.settings,
            profile=self.profile,
            collection_name=name,
            create_if_missing=create_if_missing,
        )

    def add_chunks(self, chunks: list[PaperChunk], vectors: list[list[float]]) -> None:
        if self.sqlite.vector_index_lock():
            raise ApiError(
                "Vector index migration is in progress; paper uploads are temporarily disabled.",
                503,
                error_code="INDEX_MIGRATION_IN_PROGRESS",
                retryable=True,
            )
        store = self.store(create_if_missing=True)
        hashes = {chunk.chunk_id: chunk_content_hash(chunk) for chunk in chunks}
        self.sqlite.mark_vector_entries(chunks, self.profile.key, store.collection_name, hashes, "pending")
        try:
            store.add_chunks(chunks, vectors)
        except Exception as exc:
            self.sqlite.mark_vector_entries(chunks, self.profile.key, store.collection_name, hashes, "failed", str(exc))
            self.sqlite.set_vector_index_state(self.profile.key, "degraded", store.collection_name)
            raise ApiError(
                f"Vector indexing failed: {exc}",
                503,
                error_code="INDEX_WRITE_FAILED",
                retryable=True,
            ) from exc
        self.sqlite.mark_vector_entries(chunks, self.profile.key, store.collection_name, hashes, "ready")
        state = "legacy" if store.collection_name == LEGACY_COLLECTION else "ready"
        self.sqlite.set_vector_index_state(self.profile.key, state, store.collection_name)
        clear_vector_store_cache()

    def search(self, query_vector: list[float], doc_ids: list[str], top_k: int) -> list[PaperChunk]:
        return self.store().search(query_vector, doc_ids=doc_ids, top_k=top_k)

    def reconcile_orphan_vectors(self) -> int:
        """Remove v4 vectors that are not part of any active SQLite revision."""
        source_ids = {chunk.chunk_id for chunk in self.sqlite.list_chunks()}
        store = self.store(create_if_missing=False)
        orphan_ids = sorted(store.ids() - source_ids)
        if orphan_ids:
            store.delete_chunks(orphan_ids)
            self.sqlite.delete_vector_entries(orphan_ids, self.profile.key)
            clear_vector_store_cache()
        return len(orphan_ids)

    def status(self) -> dict[str, object]:
        chunks = self.sqlite.list_chunks()
        source_ids = {chunk.chunk_id for chunk in chunks}
        store = self.store(create_if_missing=False)
        indexed_ids = store.ids()
        state_record = self.sqlite.get_vector_index_state(self.profile.key)
        lock = self.sqlite.vector_index_lock()
        counts = self.sqlite.vector_entry_counts(self.profile.key)
        missing = source_ids - indexed_ids
        orphan = indexed_ids - source_ids
        if lock:
            state = "migrating"
        elif counts.get("failed", 0):
            state = "degraded"
        elif not chunks and not indexed_ids:
            state = "empty"
        elif store.collection_name == LEGACY_COLLECTION:
            state = "legacy"
        elif missing:
            state = "migration_required"
        elif state_record and state_record.get("state") == "degraded":
            state = "degraded"
        else:
            state = "ready"
        return {
            "state": state,
            "profile": {
                "provider": self.profile.provider,
                "model": self.profile.model,
                "dimension": self.profile.dimension,
                "schema_version": self.profile.schema_version,
                "chunker_schema": self.profile.chunker_schema,
                "key": self.profile.key,
            },
            "active_collection": store.collection_name,
            "legacy_collection": LEGACY_COLLECTION
            if get_vector_store(self.settings, collection_name=LEGACY_COLLECTION, create_if_missing=False).count()
            else None,
            "sqlite_chunk_count": len(source_ids),
            "indexed_chunk_count": len(indexed_ids & source_ids),
            "missing_chunk_count": len(missing),
            "orphan_vector_count": len(orphan),
            "failed_chunk_count": counts.get("failed", 0),
            "last_migration": self.sqlite.latest_vector_migration(self.profile.key),
            "warnings": self._status_warnings(store, missing, orphan),
        }

    def _status_warnings(
        self, store: ChromaVectorStore, missing: set[str], orphan: set[str]
    ) -> list[str]:
        warnings: list[str] = []
        if store.backend_name != "chroma":
            warnings.append("Chroma is unavailable; semantic retrieval is not persistent.")
        if missing:
            warnings.append(f"{len(missing)} SQLite chunks are missing from the active vector index.")
        if orphan:
            warnings.append(f"{len(orphan)} vectors do not have a matching SQLite chunk.")
        return warnings


@lru_cache(maxsize=1)
def get_vector_index_manager() -> VectorIndexManager:
    """Return the configured process-local index manager."""
    return VectorIndexManager(get_settings())


def clear_vector_index_manager_cache() -> None:
    get_vector_index_manager.cache_clear()
