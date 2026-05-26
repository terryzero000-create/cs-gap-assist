import hashlib
import math

from backend.core.config import Settings


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


def get_embedding_provider(settings: Settings, provider: str | None = None, model: str | None = None) -> EmbeddingProvider:
    """Resolve an embedding provider from runtime config."""
    selected = provider or settings.default_embedding_provider
    if selected == "openai":
        return OpenAIEmbeddingProvider(settings, model)
    return MockEmbeddingProvider()
