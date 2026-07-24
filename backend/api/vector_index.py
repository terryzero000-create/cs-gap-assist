from fastapi import APIRouter

from backend.models.schemas import VectorIndexStatusResponse
from backend.services.vector_index import get_vector_index_manager


router = APIRouter(prefix="/vector-index", tags=["vector-index"])


@router.get("/status", response_model=VectorIndexStatusResponse)
async def vector_index_status() -> VectorIndexStatusResponse:
    """Return non-sensitive vector index health and migration state."""
    return VectorIndexStatusResponse.model_validate(get_vector_index_manager().status())
