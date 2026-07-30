from fastapi import APIRouter, Query

from backend.core.config import get_settings
from backend.models.schemas import CitationGraphResponse
from backend.services.citation_graph import CitationGraphService, OpenAlexCitationClient

router = APIRouter(prefix="/citations", tags=["citations"])


@router.get("/graph", response_model=CitationGraphResponse)
async def citation_graph(keyword: str, max_nodes: int = Query(default=25, ge=3, le=50)) -> CitationGraphResponse:
    """Return a D3-compatible citation evolution graph for a keyword."""
    settings = get_settings()
    client = OpenAlexCitationClient(
        base_url=settings.openalex_base_url,
        api_key=settings.openalex_api_key,
        timeout_seconds=settings.external_search_timeout_seconds,
    )
    return await CitationGraphService(client).build_graph(keyword, max_nodes=max_nodes, use_openalex=settings.enable_openalex)
