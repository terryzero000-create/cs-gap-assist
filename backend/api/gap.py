from fastapi import APIRouter

from backend.core.config import get_settings
from backend.models.schemas import GapAnalysisResponse
from backend.repositories.sqlite_store import SQLiteStore

router = APIRouter(prefix="/gaps", tags=["gaps"])


@router.get("/history", response_model=GapAnalysisResponse)
async def list_gap_history() -> GapAnalysisResponse:
    """Return persisted research gap analysis results."""
    settings = get_settings()
    return GapAnalysisResponse(gaps=SQLiteStore(settings.sqlite_path).list_gaps())
