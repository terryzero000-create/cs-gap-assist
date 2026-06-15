import hashlib
import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from backend.core.config import Settings
from backend.models.schemas import ModelOption


class EmbeddingProvider:
    """Interface for text embedding providers."""

    async def embed(self, texts: list[str]) -> tuple[list[list[float]], list[str]]:
        """Embed input texts and return vectors plus recoverable warnings."""
        raise NotImplementedError


class MockEmbeddingProvider(EmbeddingProvider):
    """Deterministic local embedding provider used when external keys are missing."""

    async def embed(self, texts: list[str]) -> tuple[list[list[float]], list[str]]:
        """Return stable hash-based vectors for local development."""
        vectors = [self._vectorize(text) for text in texts]
        return vectors, ["Embedding provider fell back to mock vectors."]

    def _vectorize(self, text: str) -> list[float]:
        """Convert text into a normalized deterministic vector."""
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        raw = [float(byte) / 255.0 for byte in digest[:16]]
        norm = math.sqrt(sum(value * value for value in raw)) or 1.0
        return [value / norm for value in raw]


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """OpenAI embedding provider placeholder with safe local fallback."""

    def __init__(self, settings: Settings, model: str | None = None) -> None:
        """Create an OpenAI embedding provider."""
        self.settings = settings
        self.model = model or settings.default_embedding_model
        self.mock = MockEmbeddingProvider()

    async def embed(self, texts: list[str]) -> tuple[list[list[float]], list[str]]:
        """Embed texts or fall back to mock vectors when no key is configured."""
        if not self.settings.openai_api_key:
            vectors, warnings = await self.mock.embed(texts)
            return vectors, [f"OPENAI_API_KEY missing; using mock embeddings instead of {self.model}.", *warnings]
        vectors, warnings = await self.mock.embed(texts)
        return vectors, [f"OpenAI embedding call is not enabled in MVP tests; using mock vectors for {self.model}.", *warnings]


class LocalBgeM3EmbeddingProvider(EmbeddingProvider):
    """Local bge-m3 embedding provider using Ollama's /api/embed endpoint."""

    def __init__(self, settings: Settings, model: str | None = None, transport: httpx.AsyncBaseTransport | None = None) -> None:
        """Create a local bge-m3 embedding provider."""
        self.settings = settings
        self.base_url = settings.local_bge_m3_base_url.rstrip("/")
        self.model = model or settings.local_bge_m3_model
        self.transport = transport
        self.mock = MockEmbeddingProvider()

    async def embed(self, texts: list[str]) -> tuple[list[list[float]], list[str]]:
        """Embed texts with local bge-m3 or fall back to deterministic mock vectors."""
        if not texts:
            return [], []
        payload: dict[str, Any] = {"model": self.model, "input": texts}
        try:
            async with httpx.AsyncClient(timeout=60.0, transport=self.transport) as client:
                response = await client.post(f"{self.base_url}/api/embed", json=payload)
                response.raise_for_status()
            data = response.json()
            embeddings = data.get("embeddings")
            if not isinstance(embeddings, list) or len(embeddings) != len(texts):
                raise ValueError("Ollama /api/embed response did not contain one embedding per input text.")
            vectors = [[float(value) for value in vector] for vector in embeddings]
            return vectors, []
        except Exception as exc:
            vectors, _warnings = await self.mock.embed(texts)
            return vectors, [f"Local bge-m3 embedding request failed ({exc}); using mock vectors."]


@dataclass(frozen=True)
class EmbeddingModelRegistration:
    """Registry entry for a selectable embedding model."""

    provider: str
    model: Callable[[Settings], str]
    factory: Callable[[Settings, str | None], EmbeddingProvider]
    available: Callable[[Settings], bool]
    warning: Callable[[Settings], str | None]


def _local_bge_m3_factory(settings: Settings, model: str | None) -> EmbeddingProvider:
    return LocalBgeM3EmbeddingProvider(settings, model)


def _openai_factory(settings: Settings, model: str | None) -> EmbeddingProvider:
    return OpenAIEmbeddingProvider(settings, model)


def _mock_factory(settings: Settings, model: str | None) -> EmbeddingProvider:
    return MockEmbeddingProvider()


EMBEDDING_MODEL_REGISTRY: tuple[EmbeddingModelRegistration, ...] = (
    EmbeddingModelRegistration(
        provider="local-bge-m3",
        model=lambda settings: settings.local_bge_m3_model,
        factory=_local_bge_m3_factory,
        available=lambda settings: True,
        warning=lambda settings: (
            f"Requires Ollama running at {settings.local_bge_m3_base_url} with model {settings.local_bge_m3_model}."
        ),
    ),
    EmbeddingModelRegistration(
        provider="openai",
        model=lambda settings: "text-embedding-3-small",
        factory=_openai_factory,
        available=lambda settings: bool(settings.openai_api_key),
        warning=lambda settings: None if settings.openai_api_key else "OPENAI_API_KEY missing; mock fallback will be used.",
    ),
    EmbeddingModelRegistration(
        provider="mock",
        model=lambda settings: "mock-embedding",
        factory=_mock_factory,
        available=lambda settings: True,
        warning=lambda settings: None,
    ),
)


def list_embedding_model_options(settings: Settings) -> list[ModelOption]:
    """Return embedding models exposed through the provider registry."""
    return [
        ModelOption(
            provider=entry.provider,
            model=entry.model(settings),
            available=entry.available(settings),
            warning=entry.warning(settings),
        )
        for entry in EMBEDDING_MODEL_REGISTRY
    ]


def get_embedding_provider(settings: Settings, provider: str | None = None, model: str | None = None) -> EmbeddingProvider:
    """Resolve an embedding provider from runtime config."""
    selected = provider or settings.default_embedding_provider
    for entry in EMBEDDING_MODEL_REGISTRY:
        if entry.provider == selected:
            return entry.factory(settings, model)
    return MockEmbeddingProvider()
