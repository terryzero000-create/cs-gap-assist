from fastapi import APIRouter

from backend.core.config import get_settings
from backend.llm.chains.gap_chain import analyze_research_gaps
from backend.models.schemas import GapAnalysisRequest, GapAnalysisResponse
from backend.repositories.sqlite_store import get_sqlite_store

router = APIRouter(prefix="/gaps", tags=["gaps"])


@router.post("/analyze", response_model=GapAnalysisResponse)
async def analyze_gaps(request: GapAnalysisRequest) -> GapAnalysisResponse:
    """Analyze high- and mid-value research gaps for a topic."""
    return await analyze_research_gaps(request, get_settings())


@router.get("/history", response_model=GapAnalysisResponse)
async def list_gap_history(include_unverified: bool = False) -> GapAnalysisResponse:
    """Return persisted research gap analysis results."""
    settings = get_settings()
    gaps = get_sqlite_store(settings.sqlite_path).list_gaps(include_unverified=include_unverified)
    has_deleted_sources = any(
        not ref.is_available
        for gap in gaps
        for ref in gap.evidence_refs
    )
    return GapAnalysisResponse(
        gaps=gaps,
        evidence_status=(
            "synthetic"
            if include_unverified and any(gap.trust_status == "legacy_unverified" for gap in gaps)
            else "insufficient_evidence"
            if has_deleted_sources
            else "verified"
        ),
        warnings=(
            ["Some saved gap evidence sources were deleted and are unavailable."]
            if has_deleted_sources
            else []
        ),
    )
