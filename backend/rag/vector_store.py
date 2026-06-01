import math
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.models.schemas import PaperChunk


@dataclass
class VectorEntry:
    """A stored vector and its retrievable chunk metadata."""

    chunk: PaperChunk
    vector: list[float]
    tags: list[str] = field(default_factory=list)
    module_source: str = "upload"


class InMemoryVectorStore:
    """Small vector store with Chroma-like filtering semantics for the MVP."""

    def __init__(self) -> None:
        """Create an empty vector store."""
        self.entries: list[VectorEntry] = []

    def add_chunks(
        self,
        chunks: list[PaperChunk],
        vectors: list[list[float]],
        tags_by_chunk: dict[str, list[str]] | None = None,
        module_source: str = "upload",
    ) -> None:
        """Add chunks and corresponding vectors to the store."""
        for chunk, vector in zip(chunks, vectors, strict=False):
            tags = (tags_by_chunk or {}).get(chunk.chunk_id, [])
            self.entries.append(VectorEntry(chunk=chunk, vector=vector, tags=tags, module_source=module_source))

    def search(
        self,
        query_vector: list[float],
        doc_ids: list[str] | None = None,
        tags: list[str] | None = None,
        module_source: str | None = None,
        top_k: int = 5,
    ) -> list[PaperChunk]:
        """Return top chunks by cosine similarity with optional doc filtering."""
        scored: list[PaperChunk] = []
        for entry in self._filter_entries(doc_ids, tags, module_source):
            score = self._cosine(query_vector, entry.vector)
            scored.append(entry.chunk.model_copy(update={"score": score}))
        return sorted(scored, key=lambda item: item.score or 0.0, reverse=True)[:top_k]

    def all_chunks(
        self,
        doc_ids: list[str] | None = None,
        tags: list[str] | None = None,
        module_source: str | None = None,
    ) -> list[PaperChunk]:
        """Return chunks filtered by document ids."""
        return [entry.chunk for entry in self._filter_entries(doc_ids, tags, module_source)]

    def _filter_entries(
        self,
        doc_ids: list[str] | None = None,
        tags: list[str] | None = None,
        module_source: str | None = None,
    ) -> list[VectorEntry]:
        """Filter vector entries using Chroma-like metadata semantics."""
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
        """Compute cosine similarity for two vectors."""
        numerator = sum(a * b for a, b in zip(left, right, strict=False))
        left_norm = math.sqrt(sum(value * value for value in left)) or 1.0
        right_norm = math.sqrt(sum(value * value for value in right)) or 1.0
        return numerator / (left_norm * right_norm)


class ChromaVectorStore:
    """Chroma-backed vector store wrapper with an in-memory fallback for local tests."""

    def __init__(self, persist_directory: Path | str, collection_name: str = "paper_chunks") -> None:
        """Create a Chroma wrapper and keep a memory mirror for deterministic filtering."""
        self.persist_directory = Path(persist_directory)
        self.collection_name = collection_name
        self.memory = InMemoryVectorStore()
        self.collection: Any | None = None
        self.backend_name = "memory"
        try:
            import chromadb  # type: ignore[import-not-found]

            self.persist_directory.mkdir(parents=True, exist_ok=True)
            client = chromadb.PersistentClient(path=str(self.persist_directory))
            self.collection = client.get_or_create_collection(collection_name)
            self.backend_name = "chroma"
        except Exception:
            self.collection = None

    def add_chunks(
        self,
        chunks: list[PaperChunk],
        vectors: list[list[float]],
        tags_by_chunk: dict[str, list[str]] | None = None,
        module_source: str = "upload",
    ) -> None:
        """Persist chunks to Chroma when available and mirror them in memory."""
        self.memory.add_chunks(chunks, vectors, tags_by_chunk=tags_by_chunk, module_source=module_source)
        if self.collection is None:
            return
        metadatas = [
            {
                "doc_id": chunk.doc_id,
                "page": chunk.page,
                "tags": json.dumps((tags_by_chunk or {}).get(chunk.chunk_id, [])),
                "module_source": module_source,
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
        """Search chunks with doc_id, tag, and module_source filters."""
        return self.memory.search(query_vector, doc_ids=doc_ids, tags=tags, module_source=module_source, top_k=top_k)

    def all_chunks(
        self,
        doc_ids: list[str] | None = None,
        tags: list[str] | None = None,
        module_source: str | None = None,
    ) -> list[PaperChunk]:
        """Return all mirrored chunks matching metadata filters."""
        return self.memory.all_chunks(doc_ids=doc_ids, tags=tags, module_source=module_source)


vector_store = ChromaVectorStore(Path("data/chroma"))
