import math
from dataclasses import dataclass, field

from backend.models.schemas import PaperChunk


@dataclass
class VectorEntry:
    """A stored vector and its retrievable chunk metadata."""

    chunk: PaperChunk
    vector: list[float]
    tags: list[str] = field(default_factory=list)


class InMemoryVectorStore:
    """Small vector store with Chroma-like filtering semantics for the MVP."""

    def __init__(self) -> None:
        """Create an empty vector store."""
        self.entries: list[VectorEntry] = []

    def add_chunks(self, chunks: list[PaperChunk], vectors: list[list[float]]) -> None:
        """Add chunks and corresponding vectors to the store."""
        for chunk, vector in zip(chunks, vectors, strict=False):
            self.entries.append(VectorEntry(chunk=chunk, vector=vector))

    def search(self, query_vector: list[float], doc_ids: list[str] | None = None, top_k: int = 5) -> list[PaperChunk]:
        """Return top chunks by cosine similarity with optional doc filtering."""
        allowed = set(doc_ids or [])
        scored: list[PaperChunk] = []
        for entry in self.entries:
            if allowed and entry.chunk.doc_id not in allowed:
                continue
            score = self._cosine(query_vector, entry.vector)
            scored.append(entry.chunk.model_copy(update={"score": score}))
        return sorted(scored, key=lambda item: item.score or 0.0, reverse=True)[:top_k]

    def all_chunks(self, doc_ids: list[str] | None = None) -> list[PaperChunk]:
        """Return chunks filtered by document ids."""
        allowed = set(doc_ids or [])
        return [entry.chunk for entry in self.entries if not allowed or entry.chunk.doc_id in allowed]

    def _cosine(self, left: list[float], right: list[float]) -> float:
        """Compute cosine similarity for two vectors."""
        numerator = sum(a * b for a, b in zip(left, right, strict=False))
        left_norm = math.sqrt(sum(value * value for value in left)) or 1.0
        right_norm = math.sqrt(sum(value * value for value in right)) or 1.0
        return numerator / (left_norm * right_norm)


vector_store = InMemoryVectorStore()
