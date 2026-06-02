import json
import re
from typing import Any

from backend.core.config import Settings
from backend.llm.llm_service import get_chat_provider
from backend.models.schemas import ExperimentPlan, ExperimentSuggestRequest, ExperimentSuggestResponse
from backend.services.arxiv_search import ArxivSearchClient
from backend.services.external_paper import ExternalPaper


async def suggest_experiments(request: ExperimentSuggestRequest, settings: Settings) -> ExperimentSuggestResponse:
    """Generate literature-supported experiment plans for a research gap."""
    query = request.topic or request.gap_id
    arxiv_papers, arxiv_warnings = await ArxivSearchClient(timeout_seconds=settings.external_search_timeout_seconds).search(
        query,
        limit=5,
    )
    papers = arxiv_papers[:5]
    selected = request.runtime_model_config
    prompt = (
        "EXPERIMENT_JSON\n"
        "Return strict JSON with an experiments array. Each experiment needs objective, datasets, metrics, baselines, steps, and risks.\n"
        f"Gap or topic: {query}\n"
        "External literature context:\n"
        + "\n".join(f"{paper.paper_id}: {paper.title}. {paper.abstract}" for paper in papers)
    )
    provider = get_chat_provider(settings, selected.chat_provider if selected else None)
    raw_text, chat_warnings = await provider.generate(prompt, selected.chat_model if selected else None)
    support_papers = [paper.paper_id for paper in papers[:5]]
    experiments, repair_warnings = _parse_experiment_items(raw_text, request.gap_id, support_papers, query)
    return ExperimentSuggestResponse(
        experiments=experiments,
        warnings=[*arxiv_warnings, *chat_warnings, *repair_warnings],
    )


def _parse_experiment_items(
    raw_text: str,
    gap_id: str,
    support_papers: list[str],
    query: str,
) -> tuple[list[ExperimentPlan], list[str]]:
    """Parse and validate model-produced experiment JSON with fallback repair."""
    payload = _extract_json(raw_text)
    if payload is None:
        return [_fallback_experiment(gap_id, support_papers, query)], [
            "Model did not return valid experiment JSON; using deterministic fallback experiment."
        ]

    raw_items = payload.get("experiments") if isinstance(payload, dict) else None
    if not isinstance(raw_items, list):
        return [_fallback_experiment(gap_id, support_papers, query)], [
            "Model experiment JSON missed an experiments array; using deterministic fallback experiment."
        ]

    warnings: list[str] = []
    experiments: list[ExperimentPlan] = []
    evidence = _support_papers(support_papers)
    for item in raw_items:
        if not isinstance(item, dict):
            warnings.append("Skipped a malformed experiment item.")
            continue
        objective = _clean_text(item.get("objective"))
        datasets = _string_list(item.get("datasets"))
        metrics = _string_list(item.get("metrics"))
        baselines = _string_list(item.get("baselines"))
        steps = _string_list(item.get("steps"))
        risks = _string_list(item.get("risks"))
        if not objective or not datasets or not metrics or not baselines or not steps or not risks:
            warnings.append("Skipped an experiment item with missing required fields.")
            continue
        experiments.append(
            ExperimentPlan(
                gap_id=gap_id,
                objective=objective,
                datasets=datasets,
                metrics=metrics,
                baselines=baselines,
                steps=steps,
                risks=risks,
                support_papers=evidence,
            )
        )

    if experiments:
        return experiments, warnings
    return [_fallback_experiment(gap_id, support_papers, query)], [
        *warnings,
        "No valid experiment items remained after validation; using deterministic fallback experiment.",
    ]


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


def _string_list(value: object) -> list[str]:
    """Normalize model-produced list fields."""
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _support_papers(support_papers: list[str]) -> list[str]:
    """Return a support paper list that satisfies the public 3-5 paper contract."""
    if len(support_papers) >= 3:
        return support_papers[:5]
    fallback = [*support_papers]
    while len(fallback) < 3:
        fallback.append(f"fallback-support-paper-{len(fallback) + 1}")
    return fallback


def _fallback_experiment(gap_id: str, support_papers: list[str], query: str) -> ExperimentPlan:
    """Create a deterministic experiment plan when model output cannot be repaired."""
    return ExperimentPlan(
        gap_id=gap_id,
        objective=f"Evaluate experimental evidence for {query}.",
        datasets=["Public benchmark dataset", "arXiv-derived paper subset"],
        metrics=["Accuracy", "F1", "NDCG"],
        baselines=["BM25", "standard RAG", "RAG without reranking"],
        steps=["Prepare evaluation splits", "Run baseline systems", "Compare metrics", "Analyze failure cases"],
        risks=["External evidence may be incomplete", "Dataset labels may be noisy"],
        support_papers=_support_papers(support_papers),
    )
