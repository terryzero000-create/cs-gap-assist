from fastapi import APIRouter

from backend.core.config import get_settings
from backend.models.schemas import ModelConfigResponse, ModelOption

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
            "chat": [
                ModelOption(
                    provider="deepseek",
                    model="deepseek-v4-pro",
                    available=bool(settings.deepseek_api_key),
                    warning=None if settings.deepseek_api_key else "DEEPSEEK_API_KEY missing; mock fallback will be used.",
                ),
                ModelOption(provider="deepseek", model="deepseek-v4-flash", available=bool(settings.deepseek_api_key)),
                ModelOption(provider="mock", model="mock-chat", available=True),
            ],
            "embedding": [
                ModelOption(
                    provider="openai",
                    model="text-embedding-3-small",
                    available=bool(settings.openai_api_key),
                    warning=None if settings.openai_api_key else "OPENAI_API_KEY missing; mock fallback will be used.",
                ),
                ModelOption(provider="mock", model="mock-embedding", available=True),
            ],
        },
    )
