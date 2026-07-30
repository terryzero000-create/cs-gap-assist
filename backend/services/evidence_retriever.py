import math
import re
from dataclasses import dataclass, field

from backend.core.config import Settings
from backend.models.schemas import EvidenceRef, PaperChunk
from backend.repositories.sqlite_store import SQLiteStore
from backend.services.vector_index import VectorIndexManager, configured_embedding_provider, lexical_chunk_search


@dataclass(frozen=True)
class RetrievalResult:
    """Trusted local evidence selected by the shared RAG relevance gate."""

    chunks: list[PaperChunk] = field(default_factory=list)
    evidence_refs: list[EvidenceRef] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    used_semantic: bool = False


class EvidenceRetriever:
    """Retrieve bounded, relevant local evidence for every RAG workflow."""

    def __init__(self, settings: Settings, store: SQLiteStore | None = None) -> None:
        self.settings = settings
        self.store = store or SQLiteStore(settings.sqlite_path)

    async def retrieve(
        self,
        query: str,
        doc_ids: list[str],
        top_k: int = 5,
        max_per_doc: int = 2,
    ) -> RetrievalResult:
        """Return only evidence that passes semantic or lexical relevance thresholds."""
        allowed_doc_ids = list(dict.fromkeys(doc_id for doc_id in doc_ids if doc_id))
        if not query.strip() or not allowed_doc_ids:
            return RetrievalResult()

        stored_chunks = self.store.list_chunks(allowed_doc_ids)
        if not stored_chunks:
            return RetrievalResult()

        warnings: list[str] = []
        semantic_chunks: list[PaperChunk] = []
        used_semantic = False
        try:
            embedding_result = await configured_embedding_provider(self.settings).embed([query])
            warnings.extend(embedding_result.warnings)
            if not embedding_result.is_fallback and embedding_result.vectors:
                candidates = VectorIndexManager(self.settings).search(
                    embedding_result.vectors[0],
                    doc_ids=allowed_doc_ids,
                    top_k=min(max(top_k * 5, top_k), 25),
                )
                semantic_chunks = [
                    chunk
                    for chunk in candidates
                    if (chunk.score if chunk.score is not None else -1.0) >= self.settings.rag_min_semantic_score
                ]
                used_semantic = bool(semantic_chunks)
        except Exception as exc:
            warnings.append(f"Semantic retrieval was unavailable ({exc}); lexical retrieval was used.")

        candidates = semantic_chunks
        if not candidates:
            candidates = [
                chunk
                for chunk in lexical_chunk_search(stored_chunks, query, min(max(top_k * 5, top_k), 25))
                if (chunk.score or 0.0) >= self.settings.rag_min_lexical_score
            ]
            if candidates:
                warnings.append("Semantic retrieval had no trusted match; SQLite lexical retrieval was used.")

        selected = self._bound_context(
            candidates,
            top_k=min(top_k, 5),
            max_per_doc=max_per_doc,
            max_tokens=self.settings.rag_max_context_tokens,
        )
        papers = {paper.doc_id: paper for paper in self.store.list_papers()}
        refs = [
            EvidenceRef(
                source="local",
                id=f"local:{chunk.doc_id}:{chunk.chunk_id}",
                title=papers[chunk.doc_id].title if chunk.doc_id in papers else f"Local paper {chunk.doc_id}",
                canonical_url=f"/api/v1/knowledge/papers/{chunk.doc_id}#chunk-{chunk.chunk_id}",
                doc_id=chunk.doc_id,
                chunk_id=chunk.chunk_id,
                page=chunk.page,
            )
            for chunk in selected
        ]
        return RetrievalResult(chunks=selected, evidence_refs=refs, warnings=warnings, used_semantic=used_semantic)

    def _bound_context(
        self,
        chunks: list[PaperChunk],
        top_k: int,
        max_per_doc: int,
        max_tokens: int,
    ) -> list[PaperChunk]:
        selected: list[PaperChunk] = []
        per_doc: dict[str, int] = {}
        token_count = 0
        for chunk in chunks:
            if len(selected) >= top_k:
                break
            if per_doc.get(chunk.doc_id, 0) >= max_per_doc:
                continue
            if any(self._near_duplicate(chunk.text, existing.text) for existing in selected):
                continue
            chunk_tokens = self._estimate_tokens(chunk.text)
            if selected and token_count + chunk_tokens > max_tokens:
                continue
            if not selected and chunk_tokens > max_tokens:
                truncated = self._truncate_to_token_budget(chunk, max_tokens)
                selected.append(truncated)
                break
            selected.append(chunk)
            per_doc[chunk.doc_id] = per_doc.get(chunk.doc_id, 0) + 1
            token_count += chunk_tokens
        return selected

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        cjk_count = len(re.findall(r"[\u3400-\u9fff]", text))
        latin_count = len(re.findall(r"[A-Za-z0-9_]+", text))
        other_count = len(re.findall(r"[^\sA-Za-z0-9_\u3400-\u9fff]", text))
        return max(1, cjk_count + math.ceil(latin_count * 1.3) + math.ceil(other_count / 2))

    def _truncate_to_token_budget(self, chunk: PaperChunk, max_tokens: int) -> PaperChunk:
        words = re.findall(r"[\u3400-\u9fff]|[A-Za-z0-9_]+|[^\s]", chunk.text)
        text = " ".join(words[:max_tokens]).strip()
        return chunk.model_copy(update={"text": text})

    @staticmethod
    def _near_duplicate(left: str, right: str) -> bool:
        left_tokens = set(re.findall(r"[A-Za-z0-9_]+|[\u3400-\u9fff]{2}", left.casefold()))
        right_tokens = set(re.findall(r"[A-Za-z0-9_]+|[\u3400-\u9fff]{2}", right.casefold()))
        if not left_tokens or not right_tokens:
            return left.strip() == right.strip()
        overlap = len(left_tokens & right_tokens) / max(1, len(left_tokens | right_tokens))
        return overlap >= 0.9
