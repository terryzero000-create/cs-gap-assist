import hashlib
import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from backend.core.config import Settings
from backend.models.schemas import ModelOption


VECTOR_INDEX_SCHEMA_VERSION = 2


def _normalized_vector(text: str, dimension: int) -> list[float]:
    """Return a deterministic normalized vector with the requested dimension."""
    values: list[float] = []
    counter = 0
    while len(values) < dimension:
        digest = hashlib.sha256(f"{counter}:{text}".encode("utf-8")).digest()
        values.extend(float(byte) / 255.0 for byte in digest)
        counter += 1
    raw = values[:dimension]
    norm = math.sqrt(sum(value * value for value in raw)) or 1.0
    return [value / norm for value in raw]


@dataclass(frozen=True)
class EmbeddingProfile:
    """Stable identity for vectors that may safely share one collection."""

    provider: str
    model: str
    dimension: int
    schema_version: int = VECTOR_INDEX_SCHEMA_VERSION

    @property
    def key(self) -> str:
        """Return a stable profile key used by SQLite index bookkeeping."""
        return f"v{self.schema_version}:{self.provider}:{self.model}:{self.dimension}"

    @property
    def collection_name(self) -> str:
        """Return a deterministic Chroma collection name."""
        slug = re.sub(r"[^a-z0-9]+", "_", f"{self.provider}_{self.model}".lower()).strip("_")
        return f"paper_chunks_v{self.schema_version}_{slug}_{self.dimension}"


@dataclass(frozen=True)
class EmbeddingResult:
    """Vectors plus provenance required to prevent fallback index pollution."""

    vectors: list[list[float]]
    warnings: list[str]
    profile: EmbeddingProfile
    is_fallback: bool = False

    def __iter__(self):
        """Preserve the former two-value unpacking contract for internal callers."""
        yield self.vectors
        yield self.warnings


class EmbeddingProvider:
    """Interface for text embedding providers."""

    async def embed(self, texts: list[str]) -> EmbeddingResult:
        """Embed input texts and return vectors plus recoverable warnings."""
        raise NotImplementedError


class MockEmbeddingProvider(EmbeddingProvider):
    """Deterministic local embedding provider used when external keys are missing."""

    def __init__(self, model: str = "mock-embedding") -> None:
        self.profile = EmbeddingProfile(provider="mock", model=model, dimension=16)

    async def embed(self, texts: list[str]) -> EmbeddingResult:
        """Return stable hash-based vectors for local development."""
        vectors = [self._vectorize(text) for text in texts]
        return EmbeddingResult(vectors=vectors, warnings=[], profile=self.profile, is_fallback=False)

    def _vectorize(self, text: str) -> list[float]:
        """Convert text into a normalized deterministic vector."""
        return _normalized_vector(text, self.profile.dimension)


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """OpenAI embedding provider placeholder with safe local fallback."""

    def __init__(self, settings: Settings, model: str | None = None) -> None:
        """Create an OpenAI embedding provider."""
        self.settings = settings
        self.model = model or settings.default_embedding_model
        self.profile = EmbeddingProfile(provider="openai", model=self.model, dimension=1536)

    async def embed(self, texts: list[str]) -> EmbeddingResult:
        """Embed texts or fall back to mock vectors when no key is configured."""
        if not self.settings.openai_api_key:
            return EmbeddingResult(
                vectors=[_normalized_vector(text, self.profile.dimension) for text in texts],
                warnings=[f"OPENAI_API_KEY missing; embedding request fell back instead of {self.model}."],
                profile=self.profile,
                is_fallback=True,
            )
        return EmbeddingResult(
            vectors=[_normalized_vector(text, self.profile.dimension) for text in texts],
            warnings=[f"OpenAI embedding call is not enabled; request fell back for {self.model}."],
            profile=self.profile,
            is_fallback=True,
        )


class LocalBgeM3EmbeddingProvider(EmbeddingProvider):
    """Local bge-m3 embedding provider using Ollama's /api/embed endpoint."""

    def __init__(self, settings: Settings, model: str | None = None, transport: httpx.AsyncBaseTransport | None = None) -> None:
        """Create a local bge-m3 embedding provider."""
        self.settings = settings
        self.base_url = settings.local_bge_m3_base_url.rstrip("/")
        self.model = model or settings.local_bge_m3_model
        self.transport = transport
        self.profile = EmbeddingProfile(provider="local-bge-m3", model=self.model, dimension=1024)

    async def embed(self, texts: list[str]) -> EmbeddingResult:
        """Embed texts with local bge-m3 or fall back to deterministic mock vectors."""
        if not texts:
            return EmbeddingResult(vectors=[], warnings=[], profile=self.profile)
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
            dimension = len(vectors[0]) if vectors else self.profile.dimension
            profile = EmbeddingProfile(provider=self.profile.provider, model=self.profile.model, dimension=dimension)
            return EmbeddingResult(vectors=vectors, warnings=[], profile=profile)
        except Exception as exc:
            return EmbeddingResult(
                vectors=[_normalized_vector(text, self.profile.dimension) for text in texts],
                warnings=[f"Local bge-m3 embedding request failed ({exc}); using lexical fallback."],
                profile=self.profile,
                is_fallback=True,
            )


class XfyunSparkEmbeddingProvider(EmbeddingProvider):
    """讯飞星火 Embedding API provider — produces 2560-dim vectors.

    API docs: https://www.xfyun.cn/doc/spark/Embedding_api.html
    Auth: HMAC-SHA256 signature (app_id + APIKey + APISecret).
    Vector dimension: 2560 fixed (float32, little-endian binary).
    Two domain modes:
      - domain="query" — embed user queries for retrieval
      - domain="para" — embed document paragraphs for indexing

    Implementation follows the official Python demo (Embedding.zip) exactly.
    """

    def __init__(
        self,
        settings: Settings,
        model: str | None = None,
    ) -> None:
        self.settings = settings
        self.domain = model or settings.default_embedding_model or "query"
        self.profile = EmbeddingProfile(provider="xfyun-spark", model="spark-embedding", dimension=2560)

    async def embed(self, texts: list[str]) -> EmbeddingResult:
        if not texts:
            return EmbeddingResult(vectors=[], warnings=[], profile=self.profile)
        if not self.settings.xfyun_spark_app_id or not self.settings.xfyun_spark_api_key or not self.settings.xfyun_spark_api_secret:
            return EmbeddingResult(
                vectors=[self._vectorize_fallback(text) for text in texts],
                warnings=["XFYUN_SPARK credentials missing; using lexical fallback."],
                profile=self.profile,
                is_fallback=True,
            )

        vectors: list[list[float]] = []
        warnings: list[str] = []
        used_fallback = False

        for text in texts:
            try:
                vector = self._embed_single_sync(text)
                vectors.append(vector)
            except Exception as exc:
                vectors.append(self._vectorize_fallback(text))
                used_fallback = True
                warnings.append(f"Xfyun Spark embedding failed ({exc}); using lexical fallback.")

        return EmbeddingResult(vectors=vectors, warnings=warnings, profile=self.profile, is_fallback=used_fallback)

    def _vectorize_fallback(self, text: str) -> list[float]:
        """Return a deterministic 2560-dim vector compatible with Spark embeddings."""
        return _normalized_vector(text, self.profile.dimension)

    # ------------------------------------------------------------------
    # All methods below mirror the official Embedding.py demo precisely
    # ------------------------------------------------------------------

    def _build_auth_url(self, request_url: str, api_key: str, api_secret: str) -> str:
        """Build signed URL using the same algorithm as the Spark demo."""
        from datetime import datetime
        from time import mktime
        from wsgiref.handlers import format_date_time
        import hashlib, hmac, base64
        from urllib.parse import urlencode

        # Parse host + path from request_url
        stidx = request_url.index("://")
        host = request_url[stidx + 3:]
        schema = request_url[:stidx + 3]
        edidx = host.index("/")
        path = host[edidx:]
        host = host[:edidx]

        now = datetime.now()
        date = format_date_time(mktime(now.timetuple()))

        signature_origin = "host: {}\ndate: {}\nPOST {} HTTP/1.1".format(host, date, path)
        signature_sha = hmac.new(
            api_secret.encode("utf-8"),
            signature_origin.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        signature_sha_b64 = base64.b64encode(signature_sha).decode("utf-8")

        authorization_origin = 'api_key="{}", algorithm="{}", headers="{}", signature="{}"'.format(
            api_key, "hmac-sha256", "host date request-line", signature_sha_b64
        )
        authorization = base64.b64encode(authorization_origin.encode("utf-8")).decode("utf-8")

        values = {"host": host, "date": date, "authorization": authorization}
        return request_url + "?" + urlencode(values)

    def _build_body(self, text: str) -> dict:
        """Build request body matching the demo's get_Body()."""
        import json, base64 as b64mod

        text_obj = {"messages": [{"content": text, "role": "user"}]}
        text_b64 = b64mod.b64encode(json.dumps(text_obj).encode("utf-8")).decode()

        return {
            "header": {
                "app_id": self.settings.xfyun_spark_app_id,
                "uid": "39769795890",
                "status": 3,
            },
            "parameter": {
                "emb": {
                    "domain": self.domain,
                    "feature": {
                        "encoding": "utf8",
                        "compress": "raw",
                        "format": "plain",
                    },
                }
            },
            "payload": {
                "messages": {
                    "encoding": "utf8",
                    "compress": "raw",
                    "format": "json",
                    "status": 3,
                    "text": text_b64,
                },
            },
        }

    def _embed_single_sync(self, text: str) -> list[float]:
        """Sync call matching the demo. Uses requests library like the demo."""
        import requests as req_lib
        import json, base64 as b64mod
        import numpy as np

        request_url = f"{self.settings.xfyun_spark_embedding_url.rstrip('/')}{self.settings.xfyun_spark_embedding_path}"
        url = self._build_auth_url(
            request_url,
            api_key=self.settings.xfyun_spark_api_key or "",
            api_secret=self.settings.xfyun_spark_api_secret or "",
        )
        body = self._build_body(text)
        resp_text = req_lib.post(url, json=body, headers={"content-type": "application/json"}).text

        data = json.loads(resp_text)
        code = data["header"]["code"]
        if code != 0:
            raise RuntimeError(
                f"Xfyun Spark API error (code={code}): {data['header'].get('message', 'unknown')}"
            )

        text_base = data["payload"]["feature"]["text"]
        raw_bytes = b64mod.b64decode(text_base)
        dt = np.dtype(np.float32).newbyteorder("<")
        vector = np.frombuffer(raw_bytes, dtype=dt).tolist()
        return vector


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
    return MockEmbeddingProvider(model or "mock-embedding")


def _xfyun_spark_factory(settings: Settings, model: str | None) -> EmbeddingProvider:
    return XfyunSparkEmbeddingProvider(settings, model)


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
        provider="xfyun-spark",
        model=lambda settings: "query",  # "query" or "para"
        factory=_xfyun_spark_factory,
        available=lambda settings: bool(settings.xfyun_spark_app_id and settings.xfyun_spark_api_key and settings.xfyun_spark_api_secret),
        warning=lambda settings: (
            None
            if settings.xfyun_spark_app_id and settings.xfyun_spark_api_key and settings.xfyun_spark_api_secret
            else "XFYUN_SPARK credentials (app_id, api_key, api_secret) not fully configured; mock fallback will be used."
        ),
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
