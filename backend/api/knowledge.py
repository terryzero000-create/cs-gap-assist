from fastapi import APIRouter, Query

from backend.core.config import get_settings
from backend.core.errors import ApiError
from backend.models.schemas import (
    ExperimentPlan,
    GapItem,
    KnowledgeSearchResponse,
    NoteCreateRequest,
    NoteRecord,
    PaperCollectionUpdateRequest,
    PaperDeleteResponse,
    PaperRecord,
)
from backend.repositories.sqlite_store import get_sqlite_store
from backend.services.paper_deletion import delete_paper_data

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.get("/papers", response_model=list[PaperRecord])
async def list_knowledge_papers(
    tag: str | None = Query(default=None, max_length=50),
    favorites_only: bool = False,
) -> list[PaperRecord]:
    """List papers stored in the personal knowledge base."""
    papers = get_sqlite_store(get_settings().sqlite_path).list_papers()
    if tag:
        papers = [paper for paper in papers if tag in paper.tags]
    if favorites_only:
        papers = [paper for paper in papers if paper.is_favorite]
    return papers


@router.patch("/papers/{doc_id}", response_model=PaperRecord)
async def update_knowledge_paper(doc_id: str, request: PaperCollectionUpdateRequest) -> PaperRecord:
    """Update tags and favorite state for a stored paper."""
    try:
        return get_sqlite_store(get_settings().sqlite_path).update_paper_collection(
            doc_id=doc_id,
            tags=request.tags,
            is_favorite=request.is_favorite,
        )
    except KeyError as exc:
        raise ApiError(str(exc), 404) from exc


@router.delete("/papers/{doc_id}", response_model=PaperDeleteResponse)
async def delete_knowledge_paper(doc_id: str) -> PaperDeleteResponse:
    """Permanently remove one paper and all managed ingestion artifacts."""
    settings = get_settings()
    return delete_paper_data(
        settings,
        get_sqlite_store(settings.sqlite_path),
        doc_id,
    )


@router.post("/notes", response_model=NoteRecord)
async def create_note(request: NoteCreateRequest) -> NoteRecord:
    """Create a tagged note in the personal knowledge base."""
    return get_sqlite_store(get_settings().sqlite_path).add_note(request)


@router.get("/notes", response_model=list[NoteRecord])
async def list_notes(
    query: str | None = Query(default=None, max_length=500),
) -> list[NoteRecord]:
    """List notes, optionally filtered by text query."""
    return get_sqlite_store(get_settings().sqlite_path).list_notes(query)


@router.get("/search", response_model=KnowledgeSearchResponse)
async def search_knowledge(
    query: str = Query(default="", max_length=500),
    tag: str | None = Query(default=None, max_length=50),
    favorites_only: bool = False,
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
) -> KnowledgeSearchResponse:
    """Search papers, notes, chunks, gap history, and experiment history."""
    store = get_sqlite_store(get_settings().sqlite_path)
    all_papers = store.list_papers()
    papers = [paper for paper in all_papers if _matches_paper(paper, query)]
    if not papers:
        papers = all_papers
    if tag:
        papers = [paper for paper in papers if tag in paper.tags]
    if favorites_only:
        papers = [paper for paper in papers if paper.is_favorite]
    notes = store.list_notes(query)
    chunks = store.search_knowledge_chunks(
        query,
        tag=tag,
        favorites_only=favorites_only,
        limit=limit,
        offset=offset,
    )
    gaps = [gap for gap in store.list_gaps() if _matches_gap(gap, query)]
    experiments = [experiment for experiment in store.list_experiments() if _matches_experiment(experiment, query)]
    return KnowledgeSearchResponse(papers=papers, notes=notes, chunks=chunks, gaps=gaps, experiments=experiments)


def _matches_paper(paper: PaperRecord, query: str) -> bool:
    """Return whether a paper matches a text query."""
    normalized = query.lower()
    return normalized in paper.title.lower() or normalized in paper.doc_id.lower() or any(normalized in tag.lower() for tag in paper.tags)


def _matches_gap(gap: GapItem, query: str) -> bool:
    """Return whether a saved gap matches a text query."""
    normalized = query.lower()
    fields = [gap.gap_id, gap.title, gap.value_level, gap.description, *gap.evidence_papers]
    return any(normalized in field.lower() for field in fields)


def _matches_experiment(experiment: ExperimentPlan, query: str) -> bool:
    """Return whether a saved experiment matches a text query."""
    normalized = query.lower()
    fields = [
        experiment.experiment_id,
        experiment.gap_id,
        experiment.objective,
        *experiment.datasets,
        *experiment.metrics,
        *experiment.baselines,
        *experiment.steps,
        *experiment.risks,
        *experiment.support_papers,
    ]
    return any(normalized in field.lower() for field in fields)
