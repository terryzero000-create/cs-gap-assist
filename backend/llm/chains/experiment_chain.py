import json

from backend.core.config import Settings
from backend.llm.llm_service import get_chat_provider
from backend.models.schemas import ExperimentPlan, ExperimentSuggestRequest, ExperimentSuggestResponse
from backend.services.semantic_scholar import SemanticScholarClient


async def suggest_experiments(request: ExperimentSuggestRequest, settings: Settings) -> ExperimentSuggestResponse:
    """Generate literature-supported experiment plans for a research gap."""
    query = request.topic or request.gap_id
    papers, paper_warnings = await SemanticScholarClient().search(query, limit=5)
    selected = request.runtime_model_config
    prompt = "EXPERIMENT_JSON\n" + "\n".join(f"{paper.paper_id}: {paper.title}. {paper.abstract}" for paper in papers)
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
    return ExperimentSuggestResponse(experiments=experiments, warnings=[*paper_warnings, *chat_warnings])
