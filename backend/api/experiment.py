from fastapi import APIRouter

from backend.core.config import get_settings
from backend.llm.chains.experiment_chain import suggest_experiments
from backend.models.schemas import ExperimentSuggestRequest, ExperimentSuggestResponse

router = APIRouter(prefix="/experiments", tags=["experiments"])


@router.post("/suggest", response_model=ExperimentSuggestResponse)
async def suggest_experiment(request: ExperimentSuggestRequest) -> ExperimentSuggestResponse:
    """Suggest concrete experiments for a research gap with literature support."""
    return await suggest_experiments(request, get_settings())
