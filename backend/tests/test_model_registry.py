import asyncio
import json

import httpx

from backend.core.config import Settings
from backend.llm.llm_service import OpenAICompatibleChatProvider, get_chat_provider, list_chat_model_options
from backend.rag.embedder import get_embedding_provider, list_embedding_model_options


def test_chat_model_registry_lists_configured_options() -> None:
    """Chat model choices are exposed from a single registry."""
    settings = Settings(deepseek_api_key=None, openai_api_key="sk-test")

    options = list_chat_model_options(settings)

    assert [option.provider for option in options] == ["deepseek", "deepseek", "openai", "mock"]
    assert ("openai", "gpt-4o-mini", True) in {
        (option.provider, option.model, option.available) for option in options
    }
    assert any(option.provider == "deepseek" and option.available is False for option in options)


def test_embedding_model_registry_lists_configured_options() -> None:
    """Embedding model choices are exposed from a single registry."""
    settings = Settings(openai_api_key=None, local_bge_m3_model="bge-m3")

    options = list_embedding_model_options(settings)

    assert [option.provider for option in options] == ["local-bge-m3", "openai", "xfyun-spark", "mock"]
    assert any(option.provider == "local-bge-m3" and option.model == "bge-m3" for option in options)
    assert any(option.provider == "openai" and option.available is False for option in options)
    assert any(option.provider == "xfyun-spark" and option.model == "query" for option in options)


def test_get_chat_provider_resolves_registered_openai_provider() -> None:
    """The chat provider factory resolves providers by registry key."""
    provider = get_chat_provider(Settings(openai_api_key="sk-test"), "openai")

    assert isinstance(provider, OpenAICompatibleChatProvider)


def test_get_embedding_provider_uses_requested_model_for_local_bge_m3() -> None:
    """Runtime model selection reaches the embedding provider, not just the provider key."""
    provider = get_embedding_provider(
        Settings(default_embedding_provider="local-bge-m3"),
        "local-bge-m3",
        "custom-bge-m3",
    )

    assert provider.model == "custom-bge-m3"


def test_openai_compatible_chat_provider_posts_selected_model() -> None:
    """OpenAI-compatible providers send the runtime-selected model in the API payload."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://api.example.test/chat/completions"
        assert request.headers["Authorization"] == "Bearer test-token"
        payload = json.loads(request.read().decode("utf-8"))
        assert payload == {"model": "runtime-model", "messages": [{"role": "user", "content": "hello"}]}
        return httpx.Response(200, json={"choices": [{"message": {"content": "world"}}]})

    provider = OpenAICompatibleChatProvider(
        provider_name="example",
        api_key="test-token",
        base_url="https://api.example.test",
        default_model="default-model",
        transport=httpx.MockTransport(handler),
    )

    text, warnings = asyncio.run(provider.generate("hello", "runtime-model"))

    assert text == "world"
    assert warnings == []


def test_openai_provider_uses_openai_default_when_only_provider_is_selected() -> None:
    """Switching only the provider should not send another provider's default model."""

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.read().decode("utf-8"))
        assert payload["model"] == "gpt-4o-mini"
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    provider = get_chat_provider(Settings(openai_api_key="sk-test"), "openai")
    provider.transport = httpx.MockTransport(handler)

    text, warnings = asyncio.run(provider.generate("hello"))

    assert text == "ok"
    assert warnings == []
