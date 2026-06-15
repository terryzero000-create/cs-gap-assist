from fastapi import APIRouter

from backend.core.config import get_settings
from backend.llm.llm_service import list_chat_model_options
from backend.models.schemas import ModelConfigResponse
from backend.rag.embedder import list_embedding_model_options

router = APIRouter(prefix="/config", tags=["config"])


@router.get("/models", response_model=ModelConfigResponse)
async def list_models() -> ModelConfigResponse:
    """Return runtime-selectable model providers and defaults."""
    settings = get_settings()
    return ModelConfigResponse(
        default_chat_provider=settings.default_chat_provider,
        default_chat_model=settings.default_chat_model,
        default_embedding_provider=settings.default_embedding_provider,
        default_embedding_model=settings.default_embedding_model,
        providers={
            "chat": list_chat_model_options(settings),
            "embedding": list_embedding_model_options(settings),
        },
    )
