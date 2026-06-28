from fastapi import APIRouter

from backend.core.config import get_settings
from backend.core.errors import ApiError
from backend.models.schemas import ResearchPlanAgentRequest, ResearchPlanAgentResponse
from backend.repositories.sqlite_store import SQLiteStore
from backend.services.research_plan_agent import ResearchPlanAgentService

router = APIRouter(prefix="/research-plan-agent", tags=["research-plan-agent"])


@router.post("/run", response_model=ResearchPlanAgentResponse)
async def run_research_plan_agent(request: ResearchPlanAgentRequest) -> ResearchPlanAgentResponse:
    """Run the bounded research route planning agent."""
    settings = get_settings()
    store = SQLiteStore(settings.sqlite_path)
    known_paper_ids = {paper.doc_id for paper in store.list_papers()}
    missing = [paper_id for paper_id in request.selected_paper_ids if paper_id not in known_paper_ids]
    if missing:
        raise ApiError(f"Paper not found: {missing[0]}", 404)
    return await ResearchPlanAgentService(settings, store).run(request)
