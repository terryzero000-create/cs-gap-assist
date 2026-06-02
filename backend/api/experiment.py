from fastapi import APIRouter

from backend.core.config import get_settings
from backend.llm.chains.experiment_chain import suggest_experiments
from backend.models.schemas import ExperimentSuggestRequest, ExperimentSuggestResponse
from backend.repositories.sqlite_store import SQLiteStore

router = APIRouter(prefix="/experiments", tags=["experiments"])


@router.post("/suggest", response_model=ExperimentSuggestResponse)
async def suggest_experiment(request: ExperimentSuggestRequest) -> ExperimentSuggestResponse:
    """Suggest concrete experiments for a research gap with literature support."""
    settings = get_settings()
    store = SQLiteStore(settings.sqlite_path)
    resolved_request = request
    if not request.topic:
        stored_gap = next((gap for gap in store.list_gaps() if gap.gap_id == request.gap_id), None)
        if stored_gap:
            resolved_request = ExperimentSuggestRequest(
                gap_id=request.gap_id,
                topic=f"{stored_gap.title}. {stored_gap.description}",
                runtime_model_config=request.runtime_model_config,
            )
    response = await suggest_experiments(resolved_request, settings)
    for experiment in response.experiments:
        store.save_experiment(experiment)
    return response
