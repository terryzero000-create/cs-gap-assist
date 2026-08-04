from fastapi import APIRouter

from backend.core.config import get_settings
from backend.core.errors import ApiError
from backend.models.schemas import ReproductionAgentRequest, ReproductionAgentResponse
from backend.repositories.sqlite_store import get_sqlite_store
from backend.services.reproduction_agent import ReproductionAgentService

router = APIRouter(prefix="/reproduction-agent", tags=["reproduction-agent"])


@router.post("/run", response_model=ReproductionAgentResponse)
async def run_reproduction_agent(request: ReproductionAgentRequest) -> ReproductionAgentResponse:
    """Run the assisted reproduction agent for a stored paper."""
    settings = get_settings()
    store = get_sqlite_store(settings.sqlite_path)
    paper = store.get_paper(request.paper_id)
    if paper is None:
        raise ApiError(f"Paper not found: {request.paper_id}")
    return await ReproductionAgentService(settings, store).run(request, paper)
