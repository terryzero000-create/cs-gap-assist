from fastapi import APIRouter

from backend.core.config import get_settings
from backend.llm.chains.experiment_chain import suggest_experiments
from backend.models.schemas import ExperimentSuggestRequest, ExperimentSuggestResponse
from backend.repositories.sqlite_store import get_sqlite_store
from backend.services.experiment_persistence import persist_trusted_experiments

router = APIRouter(prefix="/experiments", tags=["experiments"])


@router.get("/history", response_model=ExperimentSuggestResponse)
async def list_experiment_history(
    gap_id: str | None = None,
    include_unverified: bool = False,
) -> ExperimentSuggestResponse:
    """Return persisted experiment suggestions, optionally filtered by gap."""
    settings = get_settings()
    experiments = get_sqlite_store(settings.sqlite_path).list_experiments(
        gap_id=gap_id,
        include_unverified=include_unverified,
    )
    has_deleted_sources = any(
        not ref.is_available
        for plan in experiments
        for ref in plan.support_refs
    )
    return ExperimentSuggestResponse(
        experiments=experiments,
        evidence_status=(
            "synthetic"
            if include_unverified and any(plan.trust_status == "legacy_unverified" for plan in experiments)
            else "insufficient_evidence"
            if has_deleted_sources
            else "verified"
        ),
        warnings=(
            ["Some saved experiment evidence sources were deleted and are unavailable."]
            if has_deleted_sources
            else []
        ),
    )


@router.post("/suggest", response_model=ExperimentSuggestResponse)
async def suggest_experiment(request: ExperimentSuggestRequest) -> ExperimentSuggestResponse:
    """Suggest concrete experiments for a research gap with literature support."""
    settings = get_settings()
    store = get_sqlite_store(settings.sqlite_path)
    stored_gap = next((gap for gap in store.list_gaps() if gap.gap_id == request.gap_id), None)
    resolved_request = ExperimentSuggestRequest(
        gap_id=request.gap_id,
        topic=request.topic or (
            f"{stored_gap.title}. {stored_gap.description}"
            if stored_gap
            else None
        ),
        evidence_refs=stored_gap.evidence_refs if stored_gap else [],
        runtime_model_config=request.runtime_model_config,
    )
    response = await suggest_experiments(resolved_request, settings)
    _, persistence_warnings = persist_trusted_experiments(store, response)
    response.warnings.extend(persistence_warnings)
    return response
