import json

from backend.core.config import Settings
from backend.llm.llm_service import get_chat_provider
from backend.models.schemas import ExperimentPlan, ExperimentSuggestRequest, ExperimentSuggestResponse
from backend.services.arxiv_search import ArxivSearchClient
from backend.services.semantic_scholar import ExternalPaper, SemanticScholarClient


async def suggest_experiments(request: ExperimentSuggestRequest, settings: Settings) -> ExperimentSuggestResponse:
    """Generate literature-supported experiment plans for a research gap."""
    query = request.topic or request.gap_id
    semantic_papers: list[ExternalPaper] = []
    semantic_warnings: list[str] = []
    if settings.enable_semantic_scholar:
        semantic_papers, semantic_warnings = await SemanticScholarClient(
            api_key=settings.semantic_scholar_api_key,
            timeout_seconds=settings.external_search_timeout_seconds,
        ).search(query, limit=3)
    arxiv_limit = max(2, 5 - len(semantic_papers))
    arxiv_papers, arxiv_warnings = await ArxivSearchClient(timeout_seconds=settings.external_search_timeout_seconds).search(
        query,
        limit=arxiv_limit,
    )
    papers = [*semantic_papers, *arxiv_papers][:5]
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
    payload = json.loads(raw_text)
    support_papers = [paper.paper_id for paper in papers[:5]]
    experiments = [
        ExperimentPlan(
            gap_id=request.gap_id,
            objective=item["objective"],
            datasets=item["datasets"],
            metrics=item["metrics"],
            baselines=item["baselines"],
            steps=item["steps"],
            risks=item["risks"],
            support_papers=support_papers[: max(3, min(5, len(support_papers)))],
        )
        for item in payload.get("experiments", [])
    ]
    return ExperimentSuggestResponse(experiments=experiments, warnings=[*semantic_warnings, *arxiv_warnings, *chat_warnings])
