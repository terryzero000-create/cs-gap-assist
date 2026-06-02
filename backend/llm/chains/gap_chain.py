import json
import re
from typing import Any

from backend.core.config import Settings
from backend.llm.llm_service import get_chat_provider
from backend.models.schemas import GapAnalysisRequest, GapAnalysisResponse, GapItem
from backend.rag.vector_store import vector_store
from backend.repositories.sqlite_store import SQLiteStore
from backend.services.arxiv_search import ArxivSearchClient
from backend.services.semantic_scholar import ExternalPaper, SemanticScholarClient


async def analyze_research_gaps(request: GapAnalysisRequest, settings: Settings) -> GapAnalysisResponse:
    """Analyze research gaps from local papers and external literature evidence."""
    semantic_papers: list[ExternalPaper] = []
    semantic_warnings: list[str] = []
    if settings.enable_semantic_scholar:
        semantic_papers, semantic_warnings = await SemanticScholarClient(
            api_key=settings.semantic_scholar_api_key,
            timeout_seconds=settings.external_search_timeout_seconds,
        ).search(request.topic, limit=3)
    arxiv_papers, arxiv_warnings = await ArxivSearchClient(timeout_seconds=settings.external_search_timeout_seconds).search(
        request.topic,
        limit=2,
    )
    evidence_pool = [*semantic_papers, *arxiv_papers]
    local_context = "\n".join(chunk.text for chunk in vector_store.all_chunks(request.doc_ids)[:5])
    external_context = "\n".join(f"{paper.paper_id}: {paper.title}. {paper.abstract}" for paper in evidence_pool)
    prompt = (
        "GAP_JSON\n"
        "Return strict JSON with a gaps array. Each gap needs title, value_level "
        "('high' or 'mid'), description, and evidence_papers.\n"
        f"Research topic: {request.topic}\n"
        f"Uploaded paper context: {local_context}\n"
        f"External literature context: {external_context}"
    )
    selected = request.runtime_model_config
    provider = get_chat_provider(settings, selected.chat_provider if selected else None)
    raw_text, chat_warnings = await provider.generate(prompt, selected.chat_model if selected else None)
    gaps, repair_warnings = _parse_gap_items(raw_text, evidence_pool, request.topic)
    store = SQLiteStore(settings.sqlite_path)
    for gap in gaps:
        store.save_gap(gap)
    return GapAnalysisResponse(gaps=gaps, warnings=[*semantic_warnings, *arxiv_warnings, *chat_warnings, *repair_warnings])


def _parse_gap_items(raw_text: str, evidence_pool: list[ExternalPaper], topic: str) -> tuple[list[GapItem], list[str]]:
    """Parse and validate model-produced gap JSON with fallback repair."""
    warnings: list[str] = []
    payload = _extract_json(raw_text)
    if payload is None:
        return [_fallback_gap(topic, evidence_pool)], ["Model did not return valid gap JSON; using deterministic fallback gap."]

    raw_items = payload.get("gaps") if isinstance(payload, dict) else None
    if not isinstance(raw_items, list):
        return [_fallback_gap(topic, evidence_pool)], ["Model gap JSON missed a gaps array; using deterministic fallback gap."]

    gaps: list[GapItem] = []
    fallback_evidence = _fallback_evidence(evidence_pool)
    for item in raw_items:
        if not isinstance(item, dict):
            warnings.append("Skipped a malformed gap item.")
            continue
        title = _clean_text(item.get("title"))
        description = _clean_text(item.get("description"))
        if not title or not description:
            warnings.append("Skipped a gap item without title or description.")
            continue
        value_level = _clean_text(item.get("value_level")).lower()
        if value_level not in {"high", "mid"}:
            value_level = "mid"
            warnings.append(f"Normalized unsupported value_level for gap '{title}' to mid.")
        evidence = _evidence_from_item(item)
        if not evidence:
            evidence = fallback_evidence
            warnings.append(f"Filled missing evidence papers for gap '{title}'.")
        gaps.append(GapItem(title=title, value_level=value_level, description=description, evidence_papers=evidence))

    if gaps:
        return gaps, warnings
    return [_fallback_gap(topic, evidence_pool)], [*warnings, "No valid gap items remained after validation; using deterministic fallback gap."]


def _extract_json(raw_text: str) -> dict[str, Any] | None:
    """Extract a JSON object from strict, fenced, or prose-wrapped model text."""
    try:
        payload = json.loads(raw_text)
        return payload if isinstance(payload, dict) else None
    except json.JSONDecodeError:
        pass

    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_text, flags=re.DOTALL)
    candidate = fenced.group(1) if fenced else raw_text[raw_text.find("{") : raw_text.rfind("}") + 1]
    if not candidate:
        return None
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _clean_text(value: object) -> str:
    """Normalize scalar model output to trimmed text."""
    return str(value).strip() if value is not None else ""


def _evidence_from_item(item: dict[str, object]) -> list[str]:
    """Normalize model-produced evidence identifiers."""
    evidence = item.get("evidence_papers")
    if not isinstance(evidence, list):
        return []
    return [str(value).strip() for value in evidence if str(value).strip()]


def _fallback_evidence(evidence_pool: list[ExternalPaper]) -> list[str]:
    """Format external papers as evidence strings."""
    papers = evidence_pool[:3]
    if not papers:
        return ["local uploaded paper context"]
    return [f"{paper.paper_id}: {paper.title}" for paper in papers]


def _fallback_gap(topic: str, evidence_pool: list[ExternalPaper]) -> GapItem:
    """Create a deterministic gap when model output cannot be repaired."""
    return GapItem(
        title=f"Evidence coverage for {topic} remains incomplete",
        value_level="mid",
        description="The available local and external literature suggests unresolved evaluation, robustness, or reproducibility questions.",
        evidence_papers=_fallback_evidence(evidence_pool),
    )
