import asyncio
import json

import httpx

from backend.core.config import Settings
from backend.rag.embedder import LocalBgeM3EmbeddingProvider, XfyunSparkEmbeddingProvider, get_embedding_provider


def test_local_bge_m3_provider_parses_ollama_embed_response() -> None:
    """Local bge-m3 embeddings use Ollama's batch /api/embed response."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "http://127.0.0.1:11434/api/embed"
        payload = json.loads(request.read().decode("utf-8"))
        assert payload == {"model": "bge-m3", "input": ["first chunk", "second chunk"]}
        return httpx.Response(200, json={"embeddings": [[0.1, 0.2], [0.3, 0.4]]})

    provider = LocalBgeM3EmbeddingProvider(
        Settings(default_embedding_provider="local-bge-m3"),
        transport=httpx.MockTransport(handler),
    )

    vectors, warnings = asyncio.run(provider.embed(["first chunk", "second chunk"]))

    assert vectors == [[0.1, 0.2], [0.3, 0.4]]
    assert warnings == []


def test_get_embedding_provider_resolves_local_bge_m3() -> None:
    """The embedding provider registry exposes local bge-m3 for development."""
    provider = get_embedding_provider(Settings(default_embedding_provider="local-bge-m3"))

    assert isinstance(provider, LocalBgeM3EmbeddingProvider)


def test_xfyun_spark_provider_marks_fallback_on_api_error(monkeypatch) -> None:
    """Spark failures must be marked so their vectors cannot pollute a real index."""
    async def no_wait(_seconds: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", no_wait)
    provider = XfyunSparkEmbeddingProvider(
        Settings(
            xfyun_spark_app_id="app",
            xfyun_spark_api_key="key",
            xfyun_spark_api_secret="secret",
        ),
        transport=httpx.MockTransport(lambda _request: httpx.Response(503)),
    )

    result = asyncio.run(provider.embed(["paper chunk"]))
    vectors, warnings = result

    assert vectors == []
    assert result.is_fallback is True
    assert "lexical retrieval remains available" in warnings[0]


def test_xfyun_spark_provider_uses_configured_default_domain() -> None:
    """Spark embedding should respect DEFAULT_EMBEDDING_MODEL when no runtime model is supplied."""
    provider = XfyunSparkEmbeddingProvider(Settings(default_embedding_model="para"))

    assert provider.domain == "para"
