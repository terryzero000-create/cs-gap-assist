import asyncio
import math
import re
import time
from dataclasses import dataclass, field

from backend.core.config import Settings
from backend.core.sanitize import safe_exception_message
from backend.models.schemas import EvidenceRef, PaperChunk
from backend.repositories.sqlite_store import SQLiteStore, get_sqlite_store
from backend.services.vector_index import (
    VectorIndexManager,
    configured_embedding_provider,
    lexical_chunk_search,
)


@dataclass(frozen=True)
class RetrievalResult:
    """Trusted local evidence selected by the shared hybrid relevance gate."""

    chunks: list[PaperChunk] = field(default_factory=list)
    evidence_refs: list[EvidenceRef] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    used_semantic: bool = False
    latency_ms: float = 0.0
    duplicate_ratio: float = 0.0


class ContextBudgeter:
    """Apply one shared context and per-document token budget."""

    def __init__(self, max_tokens: int, max_per_doc: int, max_bytes: int) -> None:
        self.max_tokens = max_tokens
        self.max_per_doc = max_per_doc
        self.max_bytes = max_bytes

    def select(self, chunks: list[PaperChunk], top_k: int) -> list[PaperChunk]:
        """Return bounded chunks without exceeding document concentration limits."""
        selected: list[PaperChunk] = []
        per_doc: dict[str, int] = {}
        token_count = 0
        byte_count = 0
        per_doc_budget = max(1, math.ceil(self.max_tokens * 0.55))
        per_doc_tokens: dict[str, int] = {}
        first_per_doc: list[PaperChunk] = []
        remainder: list[PaperChunk] = []
        seen_docs: set[str] = set()
        for chunk in chunks:
            if chunk.doc_id not in seen_docs:
                first_per_doc.append(chunk)
                seen_docs.add(chunk.doc_id)
            else:
                remainder.append(chunk)
        for chunk in [*first_per_doc, *remainder]:
            if len(selected) >= top_k:
                break
            if per_doc.get(chunk.doc_id, 0) >= self.max_per_doc:
                continue
            chunk_tokens = self.estimate_tokens(chunk.text)
            chunk_bytes = len(chunk.text.encode("utf-8"))
            if per_doc_tokens.get(chunk.doc_id, 0) + chunk_tokens > per_doc_budget:
                continue
            if selected and (
                token_count + chunk_tokens > self.max_tokens
                or byte_count + chunk_bytes > self.max_bytes
            ):
                continue
            if not selected and (
                chunk_tokens > self.max_tokens or chunk_bytes > self.max_bytes
            ):
                chunk = self.truncate(chunk, self.max_tokens, self.max_bytes)
                chunk_tokens = self.estimate_tokens(chunk.text)
                chunk_bytes = len(chunk.text.encode("utf-8"))
            selected.append(chunk)
            per_doc[chunk.doc_id] = per_doc.get(chunk.doc_id, 0) + 1
            per_doc_tokens[chunk.doc_id] = per_doc_tokens.get(chunk.doc_id, 0) + chunk_tokens
            token_count += chunk_tokens
            byte_count += chunk_bytes
        return selected

    @staticmethod
    def estimate_tokens(text: str) -> int:
        cjk_count = len(re.findall(r"[\u3400-\u9fff]", text))
        latin_count = len(re.findall(r"[A-Za-z0-9_]+", text))
        other_count = len(re.findall(r"[^\sA-Za-z0-9_\u3400-\u9fff]", text))
        return max(1, cjk_count + math.ceil(latin_count * 1.3) + math.ceil(other_count / 2))

    def truncate(
        self,
        chunk: PaperChunk,
        max_tokens: int,
        max_bytes: int,
    ) -> PaperChunk:
        units = re.findall(r"[\u3400-\u9fff]|[A-Za-z0-9_]+|[^\s]", chunk.text)
        text = " ".join(units[:max_tokens]).strip()
        while len(text.encode("utf-8")) > max_bytes and text:
            text = text[: max(1, len(text) * 3 // 4)]
        return chunk.model_copy(update={"text": text})


class OptionalCrossEncoderReranker:
    """Lazy optional multilingual reranker with deterministic fallback."""

    def __init__(self, enabled: bool, model_name: str) -> None:
        self.enabled = enabled
        self.model_name = model_name
        self._model: object | None = None

    async def rerank(
        self,
        query: str,
        chunks: list[PaperChunk],
    ) -> tuple[list[PaperChunk], list[str]]:
        if not self.enabled or not chunks:
            return chunks, []
        try:
            scores = await asyncio.to_thread(self._predict, query, chunks)
            reranked = [
                chunk.model_copy(update={"score": float(score)})
                for chunk, score in zip(chunks, scores, strict=True)
            ]
            return sorted(reranked, key=lambda item: item.score or 0.0, reverse=True), []
        except Exception as exc:
            return chunks, [
                "Optional cross-encoder rerank was unavailable "
                f"({safe_exception_message(exc)}); RRF order was used."
            ]

    def _predict(self, query: str, chunks: list[PaperChunk]) -> list[float]:
        if self._model is None:
            from sentence_transformers import CrossEncoder  # type: ignore[import-not-found]

            self._model = CrossEncoder(self.model_name)
        values = self._model.predict([(query, chunk.text) for chunk in chunks])
        return [float(value) for value in values]


class EvidenceRetriever:
    """Hybrid FTS5/vector retrieval shared by every grounded workflow."""

    def __init__(self, settings: Settings, store: SQLiteStore | None = None) -> None:
        self.settings = settings
        self.store = store or get_sqlite_store(settings.sqlite_path)

    async def retrieve(
        self,
        query: str,
        doc_ids: list[str],
        top_k: int = 5,
        max_per_doc: int = 3,
    ) -> RetrievalResult:
        """Fuse BM25 and cosine candidates, diversify, merge, and budget them."""
        started = time.perf_counter()
        allowed_doc_ids = list(dict.fromkeys(doc_id for doc_id in doc_ids if doc_id))[:50]
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
                semantic_chunks = [
                    chunk
                    for chunk in VectorIndexManager(self.settings).search(
                        embedding_result.vectors[0],
                        doc_ids=allowed_doc_ids,
                        top_k=30,
                    )
                    if (chunk.score if chunk.score is not None else -1.0)
                    >= self.settings.rag_min_semantic_score
                ]
                used_semantic = bool(semantic_chunks)
        except Exception as exc:
            warnings.append(
                "Semantic retrieval was unavailable "
                f"({safe_exception_message(exc)}); BM25 remained available."
            )

        lexical_chunks = self.store.search_chunks_fts(query, allowed_doc_ids, limit=30)
        if not lexical_chunks:
            lexical_chunks = [
                chunk
                for chunk in lexical_chunk_search(stored_chunks, query, 30)
                if (chunk.score or 0.0) >= self.settings.rag_min_lexical_score
            ]
            if lexical_chunks:
                warnings.append("FTS5 returned no match; bounded lexical fallback was used.")

        fused = self._rrf(semantic_chunks, lexical_chunks)
        if not fused:
            return RetrievalResult(
                warnings=warnings,
                used_semantic=used_semantic,
                latency_ms=(time.perf_counter() - started) * 1000,
            )
        unique_count = len({chunk.chunk_id for chunk in [*semantic_chunks, *lexical_chunks]})
        candidate_overlap_ratio = 1.0 - (
            unique_count / max(1, len(semantic_chunks) + len(lexical_chunks))
        )
        capped = self._cap_per_doc(fused, max_per_doc=3)
        diversified = self._mmr(capped, limit=20)
        reranker = OptionalCrossEncoderReranker(
            enabled=getattr(self.settings, "enable_reranker", False),
            model_name=getattr(self.settings, "reranker_model", "BAAI/bge-reranker-v2-m3"),
        )
        reranked, rerank_warnings = await reranker.rerank(query, diversified[:20])
        warnings.extend(rerank_warnings)
        merged = self._dedupe_merged(self._merge_adjacent(reranked, stored_chunks))
        selected = ContextBudgeter(
            self.settings.rag_max_context_tokens,
            max_per_doc,
            self.settings.rag_max_prompt_bytes,
        ).select(merged, min(max(top_k, 1), self.settings.rag_final_top_k))

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
        if any(chunk.injection_flagged for chunk in selected):
            warnings.append("Instruction-like source content was isolated as untrusted evidence.")
        latency_ms = (time.perf_counter() - started) * 1000
        duplicate_ratio = self._duplicate_ratio(selected)
        self.store.record_metric("retrieval.latency", latency_ms, "ms")
        self.store.record_metric(
            "retrieval.candidate_overlap_ratio",
            max(0.0, candidate_overlap_ratio),
            "ratio",
        )
        self.store.record_metric("retrieval.top_k_duplicate_ratio", duplicate_ratio, "ratio")
        return RetrievalResult(
            chunks=selected,
            evidence_refs=refs,
            warnings=warnings,
            used_semantic=used_semantic,
            latency_ms=latency_ms,
            duplicate_ratio=max(0.0, duplicate_ratio),
        )

    def _rrf(
        self,
        semantic: list[PaperChunk],
        lexical: list[PaperChunk],
    ) -> list[PaperChunk]:
        scores: dict[str, float] = {}
        chunks: dict[str, PaperChunk] = {}
        for weight, values in (
            (self.settings.rag_vector_weight, semantic),
            (self.settings.rag_lexical_weight, lexical),
        ):
            for rank, chunk in enumerate(values, start=1):
                scores[chunk.chunk_id] = scores.get(chunk.chunk_id, 0.0) + (
                    weight / (self.settings.rag_rrf_k + rank)
                )
                chunks[chunk.chunk_id] = chunk
        return sorted(
            (
                chunk.model_copy(update={"score": scores[chunk_id]})
                for chunk_id, chunk in chunks.items()
            ),
            key=lambda item: item.score or 0.0,
            reverse=True,
        )

    def _mmr(self, chunks: list[PaperChunk], limit: int) -> list[PaperChunk]:
        selected: list[PaperChunk] = []
        remaining = list(chunks)
        while remaining and len(selected) < limit:
            best = max(
                remaining,
                key=lambda candidate: (
                    self.settings.rag_mmr_lambda * (candidate.score or 0.0)
                    - (1.0 - self.settings.rag_mmr_lambda)
                    * max(
                        (self._text_similarity(candidate.text, prior.text) for prior in selected),
                        default=0.0,
                    )
                ),
            )
            selected.append(best)
            remaining.remove(best)
        return selected

    @staticmethod
    def _cap_per_doc(chunks: list[PaperChunk], max_per_doc: int) -> list[PaperChunk]:
        """Keep the fused candidate pool from being dominated by one paper."""
        counts: dict[str, int] = {}
        selected: list[PaperChunk] = []
        for chunk in chunks:
            if counts.get(chunk.doc_id, 0) >= max_per_doc:
                continue
            selected.append(chunk)
            counts[chunk.doc_id] = counts.get(chunk.doc_id, 0) + 1
        return selected

    def _dedupe_merged(self, chunks: list[PaperChunk]) -> list[PaperChunk]:
        """Remove near-identical expanded windows while preserving rank order."""
        selected: list[PaperChunk] = []
        for chunk in chunks:
            if any(
                chunk.doc_id == prior.doc_id
                and self._text_similarity(chunk.text, prior.text) >= 0.88
                for prior in selected
            ):
                continue
            selected.append(chunk)
        return selected

    def _duplicate_ratio(self, chunks: list[PaperChunk]) -> float:
        """Return the share of selected chunks that substantially repeat an earlier result."""
        duplicates = 0
        for index, chunk in enumerate(chunks):
            if any(
                self._text_similarity(chunk.text, prior.text) >= 0.88
                for prior in chunks[:index]
            ):
                duplicates += 1
        return duplicates / max(1, len(chunks))

    def _merge_adjacent(
        self,
        ranked: list[PaperChunk],
        all_chunks: list[PaperChunk],
    ) -> list[PaperChunk]:
        lookup = {
            (chunk.doc_id, chunk.revision_id, chunk.section_path, chunk.ordinal): chunk
            for chunk in all_chunks
        }
        merged: list[PaperChunk] = []
        for chunk in ranked:
            neighbors = [
                lookup.get((chunk.doc_id, chunk.revision_id, chunk.section_path, chunk.ordinal - 1)),
                chunk,
                lookup.get((chunk.doc_id, chunk.revision_id, chunk.section_path, chunk.ordinal + 1)),
            ]
            values = [item for item in neighbors if item is not None]
            text = values[0].text
            for neighbor in values[1:]:
                text = self._collapse_overlap(text, neighbor.text)
            merged.append(
                chunk.model_copy(
                    update={
                        "text": text,
                        "page": min(item.page for item in values),
                        "page_end": max(item.page_end or item.page for item in values),
                    }
                )
            )
        return merged

    @staticmethod
    def _collapse_overlap(left: str, right: str) -> str:
        max_overlap = min(len(left), len(right), 1000)
        for length in range(max_overlap, 19, -1):
            if left[-length:] == right[:length]:
                return f"{left}{right[length:]}".strip()
        return f"{left}\n{right}".strip()

    @staticmethod
    def _text_similarity(left: str, right: str) -> float:
        left_tokens = set(re.findall(r"[A-Za-z0-9_]+|[\u3400-\u9fff]{2}", left.casefold()))
        right_tokens = set(re.findall(r"[A-Za-z0-9_]+|[\u3400-\u9fff]{2}", right.casefold()))
        if not left_tokens or not right_tokens:
            return float(left.strip() == right.strip())
        return len(left_tokens & right_tokens) / max(1, len(left_tokens | right_tokens))
