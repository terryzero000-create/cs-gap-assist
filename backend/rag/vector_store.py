import hashlib
import json
import math
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from backend.core.config import Settings
from backend.models.schemas import PaperChunk
from backend.rag.embedder import EmbeddingProfile


class VectorDimensionError(ValueError):
    """Raised when a vector cannot safely share the active collection."""


def chunk_content_hash(chunk: PaperChunk) -> str:
    """Return the stable content hash used by idempotent indexing."""
    payload = f"{chunk.doc_id}\n{chunk.page}\n{chunk.text}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass
class VectorEntry:
    """A stored vector and its retrievable chunk metadata."""

    chunk: PaperChunk
    vector: list[float]
    tags: list[str] = field(default_factory=list)
    module_source: str = "upload"


class InMemoryVectorStore:
    """Small vector store with Chroma-like filtering semantics."""

    def __init__(self) -> None:
        self.entries: list[VectorEntry] = []

    def add_chunks(
        self,
        chunks: list[PaperChunk],
        vectors: list[list[float]],
        tags_by_chunk: dict[str, list[str]] | None = None,
        module_source: str = "upload",
    ) -> None:
        for chunk, vector in zip(chunks, vectors, strict=False):
            tags = (tags_by_chunk or {}).get(chunk.chunk_id, [])
            self.entries = [entry for entry in self.entries if entry.chunk.chunk_id != chunk.chunk_id]
            self.entries.append(VectorEntry(chunk=chunk, vector=vector, tags=tags, module_source=module_source))

    def search(
        self,
        query_vector: list[float],
        doc_ids: list[str] | None = None,
        tags: list[str] | None = None,
        module_source: str | None = None,
        top_k: int = 5,
    ) -> list[PaperChunk]:
        scored: list[PaperChunk] = []
        for entry in self._filter_entries(doc_ids, tags, module_source):
            if len(query_vector) != len(entry.vector):
                continue
            score = self._cosine(query_vector, entry.vector)
            scored.append(entry.chunk.model_copy(update={"score": score}))
        return sorted(scored, key=lambda item: item.score or 0.0, reverse=True)[:top_k]

    def all_chunks(
        self,
        doc_ids: list[str] | None = None,
        tags: list[str] | None = None,
        module_source: str | None = None,
    ) -> list[PaperChunk]:
        return [entry.chunk for entry in self._filter_entries(doc_ids, tags, module_source)]

    def _filter_entries(
        self,
        doc_ids: list[str] | None = None,
        tags: list[str] | None = None,
        module_source: str | None = None,
    ) -> list[VectorEntry]:
        allowed = set(doc_ids or [])
        required_tags = set(tags or [])
        results: list[VectorEntry] = []
        for entry in self.entries:
            if allowed and entry.chunk.doc_id not in allowed:
                continue
            if required_tags and not required_tags.issubset(set(entry.tags)):
                continue
            if module_source and entry.module_source != module_source:
                continue
            results.append(entry)
        return results

    def _cosine(self, left: list[float], right: list[float]) -> float:
        numerator = sum(a * b for a, b in zip(left, right, strict=True))
        left_norm = math.sqrt(sum(value * value for value in left)) or 1.0
        right_norm = math.sqrt(sum(value * value for value in right)) or 1.0
        return numerator / (left_norm * right_norm)


class ChromaVectorStore:
    """Persistent Chroma store with a deterministic memory fallback."""

    def __init__(
        self,
        persist_directory: Path | str,
        collection_name: str = "paper_chunks",
        profile: EmbeddingProfile | None = None,
        create_if_missing: bool = True,
    ) -> None:
        self.persist_directory = Path(persist_directory)
        self.collection_name = collection_name
        self.profile = profile
        self.memory = InMemoryVectorStore()
        self.collection: Any | None = None
        self.backend_name = "memory"
        if not create_if_missing and not self.persist_directory.exists():
            return
        try:
            import chromadb  # type: ignore[import-not-found]

            self.persist_directory.mkdir(parents=True, exist_ok=True)
            client = chromadb.PersistentClient(path=str(self.persist_directory))
            existing = {item.name for item in client.list_collections()}
            if collection_name in existing:
                self.collection = client.get_collection(collection_name)
            elif create_if_missing:
                metadata = self._profile_metadata(profile) if profile else None
                self.collection = client.get_or_create_collection(collection_name, metadata=metadata)
            self.backend_name = "chroma"
        except Exception:
            self.collection = None

    @staticmethod
    def _profile_metadata(profile: EmbeddingProfile) -> dict[str, str | int]:
        return {
            "schema_version": profile.schema_version,
            "embedding_provider": profile.provider,
            "embedding_model": profile.model,
            "embedding_dimension": profile.dimension,
            "profile_key": profile.key,
        }

    def count(self) -> int:
        if self.collection is not None:
            return int(self.collection.count())
        return len(self.memory.entries)

    def dimension(self) -> int | None:
        if self.collection is None or self.collection.count() == 0:
            return self.profile.dimension if self.profile else None
        payload = self.collection.peek(limit=1)
        embeddings = payload.get("embeddings")
        if embeddings is None or len(embeddings) == 0:
            return None
        return len(embeddings[0])

    def add_chunks(
        self,
        chunks: list[PaperChunk],
        vectors: list[list[float]],
        tags_by_chunk: dict[str, list[str]] | None = None,
        module_source: str = "upload",
    ) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("Each chunk must have exactly one embedding vector.")
        expected = self.dimension()
        for vector in vectors:
            if expected is not None and len(vector) != expected:
                raise VectorDimensionError(f"Collection expects {expected}-dimensional vectors, got {len(vector)}.")
        self.memory.add_chunks(chunks, vectors, tags_by_chunk=tags_by_chunk, module_source=module_source)
        if self.collection is None or not chunks:
            return
        metadatas = [
            {
                "doc_id": chunk.doc_id,
                "page": chunk.page,
                "tags": json.dumps((tags_by_chunk or {}).get(chunk.chunk_id, [])),
                "module_source": module_source,
                "content_hash": chunk_content_hash(chunk),
                "profile_key": self.profile.key if self.profile else "legacy",
            }
            for chunk in chunks
        ]
        self.collection.upsert(
            ids=[chunk.chunk_id for chunk in chunks],
            documents=[chunk.text for chunk in chunks],
            embeddings=vectors,
            metadatas=metadatas,
        )

    def search(
        self,
        query_vector: list[float],
        doc_ids: list[str] | None = None,
        tags: list[str] | None = None,
        module_source: str | None = None,
        top_k: int = 5,
    ) -> list[PaperChunk]:
        expected = self.dimension()
        if expected is not None and len(query_vector) != expected:
            raise VectorDimensionError(f"Collection expects {expected}-dimensional vectors, got {len(query_vector)}.")
        if self.collection is None or self.collection.count() == 0:
            return self.memory.search(query_vector, doc_ids, tags, module_source, top_k)
        where = self._where(doc_ids, module_source)
        candidate_count = min(self.collection.count(), max(top_k * 5, top_k))
        result = self.collection.query(
            query_embeddings=[query_vector],
            n_results=candidate_count,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        ids = (result.get("ids") or [[]])[0]
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        required_tags = set(tags or [])
        chunks: list[PaperChunk] = []
        for chunk_id, document, metadata, distance in zip(ids, documents, metadatas, distances, strict=False):
            metadata = metadata or {}
            stored_tags = set(json.loads(metadata.get("tags", "[]")))
            if required_tags and not required_tags.issubset(stored_tags):
                continue
            score = 1.0 / (1.0 + max(float(distance), 0.0))
            chunks.append(
                PaperChunk(
                    chunk_id=chunk_id,
                    doc_id=str(metadata.get("doc_id", "")),
                    page=int(metadata.get("page", 1)),
                    text=document or "",
                    score=score,
                )
            )
            if len(chunks) >= top_k:
                break
        return chunks

    def all_chunks(
        self,
        doc_ids: list[str] | None = None,
        tags: list[str] | None = None,
        module_source: str | None = None,
    ) -> list[PaperChunk]:
        if self.collection is None or self.collection.count() == 0:
            return self.memory.all_chunks(doc_ids, tags, module_source)
        result = self.collection.get(where=self._where(doc_ids, module_source), include=["documents", "metadatas"])
        chunks: list[PaperChunk] = []
        required_tags = set(tags or [])
        for chunk_id, document, metadata in zip(
            result.get("ids") or [], result.get("documents") or [], result.get("metadatas") or [], strict=False
        ):
            metadata = metadata or {}
            stored_tags = set(json.loads(metadata.get("tags", "[]")))
            if required_tags and not required_tags.issubset(stored_tags):
                continue
            chunks.append(
                PaperChunk(
                    chunk_id=chunk_id,
                    doc_id=str(metadata.get("doc_id", "")),
                    page=int(metadata.get("page", 1)),
                    text=document or "",
                )
            )
        return chunks

    def get_entry(self, chunk_id: str, include_embedding: bool = False) -> dict[str, Any] | None:
        if self.collection is None:
            return None
        includes = ["documents", "metadatas"]
        if include_embedding:
            includes.append("embeddings")
        result = self.collection.get(ids=[chunk_id], include=includes)
        if not result.get("ids"):
            return None
        entry: dict[str, Any] = {
            "id": result["ids"][0],
            "document": (result.get("documents") or [""])[0],
            "metadata": (result.get("metadatas") or [{}])[0] or {},
        }
        embeddings = result.get("embeddings")
        if include_embedding and embeddings is not None and len(embeddings):
            entry["embedding"] = [float(value) for value in embeddings[0]]
        return entry

    def ids(self) -> set[str]:
        if self.collection is None:
            return {entry.chunk.chunk_id for entry in self.memory.entries}
        return set(self.collection.get(include=[]).get("ids") or [])

    @staticmethod
    def _where(doc_ids: list[str] | None, module_source: str | None) -> dict[str, Any] | None:
        filters: list[dict[str, Any]] = []
        if doc_ids:
            filters.append({"doc_id": {"$in": doc_ids}})
        if module_source:
            filters.append({"module_source": module_source})
        if not filters:
            return None
        return filters[0] if len(filters) == 1 else {"$and": filters}


@lru_cache(maxsize=32)
def _cached_vector_store(
    persist_directory: str,
    collection_name: str,
    profile_key: str,
    provider: str,
    model: str,
    dimension: int,
    create_if_missing: bool,
) -> ChromaVectorStore:
    profile = EmbeddingProfile(provider=provider, model=model, dimension=dimension) if profile_key else None
    return ChromaVectorStore(
        persist_directory, collection_name, profile=profile, create_if_missing=create_if_missing
    )


def get_vector_store(
    settings: Settings,
    profile: EmbeddingProfile | None = None,
    collection_name: str | None = None,
    create_if_missing: bool = True,
) -> ChromaVectorStore:
    """Return a configured, cached vector store without touching hard-coded paths."""
    name = collection_name or (profile.collection_name if profile else "paper_chunks")
    return _cached_vector_store(
        str(settings.chroma_dir),
        name,
        profile.key if profile else "",
        profile.provider if profile else "",
        profile.model if profile else "",
        profile.dimension if profile else 0,
        create_if_missing,
    )


def clear_vector_store_cache() -> None:
    """Clear cached stores after tests or configuration changes."""
    _cached_vector_store.cache_clear()
