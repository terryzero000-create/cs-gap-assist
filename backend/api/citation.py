from fastapi import APIRouter

from backend.models.schemas import CitationGraphResponse
from backend.services.citation_graph import CitationGraphService

router = APIRouter(prefix="/citations", tags=["citations"])


@router.get("/graph", response_model=CitationGraphResponse)
async def citation_graph(keyword: str) -> CitationGraphResponse:
    """Return a D3-compatible citation evolution graph for a keyword."""
    return await CitationGraphService().build_graph(keyword)
