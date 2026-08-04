import asyncio
import base64
import hashlib
import hmac
import json
import math
import random
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from time import mktime
from typing import Any
from urllib.parse import urlencode
from wsgiref.handlers import format_date_time

import httpx

from backend.core.config import Settings
from backend.core.sanitize import safe_exception_message
from backend.models.schemas import ModelOption
from backend.services.chunker import xfyun_request_payload_bytes


VECTOR_INDEX_SCHEMA_VERSION = 4
_SHARED_HTTP_CLIENTS: dict[str, httpx.AsyncClient] = {}
_SHARED_LIMITERS: dict[tuple[int, str, int], asyncio.Semaphore] = {}


def _shared_http_client(key: str, timeout: httpx.Timeout) -> httpx.AsyncClient:
    client = _SHARED_HTTP_CLIENTS.get(key)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(timeout=timeout)
        _SHARED_HTTP_CLIENTS[key] = client
    return client


def _shared_limiter(key: str, concurrency: int) -> asyncio.Semaphore:
    loop_key = (id(asyncio.get_running_loop()), key, concurrency)
    limiter = _SHARED_LIMITERS.get(loop_key)
    if limiter is None:
        limiter = asyncio.Semaphore(concurrency)
        _SHARED_LIMITERS[loop_key] = limiter
    return limiter


async def close_embedding_http_clients() -> None:
    """Close process-shared provider clients during application shutdown."""
    clients = list(_SHARED_HTTP_CLIENTS.values())
    _SHARED_HTTP_CLIENTS.clear()
    _SHARED_LIMITERS.clear()
    await asyncio.gather(
        *(client.aclose() for client in clients if not client.is_closed),
        return_exceptions=True,
    )


def _normalized_vector(text: str, dimension: int) -> list[float]:
    """Return a deterministic normalized vector with the requested dimension."""
    values: list[float] = []
    counter = 0
    while len(values) < dimension:
        digest = hashlib.sha256(f"{counter}:{text}".encode("utf-8")).digest()
        values.extend((float(byte) - 127.5) / 127.5 for byte in digest)
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
    metric: str = "cosine"
    service_id: str = "unspecified"
    protocol_version: str = "unspecified"
    normalization: str = "provider"
    domain_compatibility: str = "query-para"
    chunker_schema: str = "chunker-v2"

    @property
    def key(self) -> str:
        """Return a stable profile key used by SQLite index bookkeeping."""
        return ":".join(
            (
                f"v{self.schema_version}",
                self.provider,
                self.model,
                self.service_id,
                self.protocol_version,
                str(self.dimension),
                self.metric,
                self.normalization,
                self.domain_compatibility,
                self.chunker_schema,
            )
        )

    @property
    def collection_name(self) -> str:
        """Return a deterministic Chroma collection name."""
        slug = re.sub(
            r"[^a-z0-9]+",
            "_",
            f"{self.provider}_{self.model}_{self.protocol_version}_{self.metric}".lower(),
        ).strip("_")
        fingerprint = hashlib.sha256(self.key.encode("utf-8")).hexdigest()[:12]
        return f"paper_chunks_v{self.schema_version}_{slug}_{self.dimension}_{fingerprint}"


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
        self.profile = EmbeddingProfile(
            provider="mock",
            model=model,
            dimension=16,
            service_id="deterministic-test-only",
            protocol_version="mock-v1",
            normalization="l2",
        )

    async def embed(self, texts: list[str]) -> EmbeddingResult:
        """Return stable hash-based vectors for local development."""
        vectors = [self._vectorize(text) for text in texts]
        return EmbeddingResult(vectors=vectors, warnings=[], profile=self.profile, is_fallback=False)

    def _vectorize(self, text: str) -> list[float]:
        """Convert text into a normalized deterministic vector."""
        return _normalized_vector(text, self.profile.dimension)


class LocalBgeM3EmbeddingProvider(EmbeddingProvider):
    """Local bge-m3 embedding provider using Ollama's /api/embed endpoint."""

    def __init__(self, settings: Settings, model: str | None = None, transport: httpx.AsyncBaseTransport | None = None) -> None:
        """Create a local bge-m3 embedding provider."""
        self.settings = settings
        self.base_url = settings.local_bge_m3_base_url.rstrip("/")
        self.model = model or settings.local_bge_m3_model
        self.transport = transport
        self.profile = EmbeddingProfile(
            provider="local-bge-m3",
            model=self.model,
            dimension=1024,
            service_id="ollama-api-embed",
            protocol_version="ollama-v1",
            normalization="provider",
        )

    async def embed(self, texts: list[str]) -> EmbeddingResult:
        """Embed texts with local bge-m3 or fall back to deterministic mock vectors."""
        if not texts:
            return EmbeddingResult(vectors=[], warnings=[], profile=self.profile)
        payload: dict[str, Any] = {"model": self.model, "input": texts}
        try:
            if self.transport is None:
                client = _shared_http_client(
                    self.base_url,
                    httpx.Timeout(60.0),
                )
                response = await client.post(f"{self.base_url}/api/embed", json=payload)
            else:
                async with httpx.AsyncClient(
                    timeout=60.0,
                    transport=self.transport,
                ) as client:
                    response = await client.post(
                        f"{self.base_url}/api/embed",
                        json=payload,
                    )
            response.raise_for_status()
            data = response.json()
            embeddings = data.get("embeddings")
            if not isinstance(embeddings, list) or len(embeddings) != len(texts):
                raise ValueError("Ollama /api/embed response did not contain one embedding per input text.")
            vectors = [[float(value) for value in vector] for vector in embeddings]
            dimension = len(vectors[0]) if vectors else self.profile.dimension
            profile = EmbeddingProfile(
                provider=self.profile.provider,
                model=self.profile.model,
                dimension=dimension,
                service_id=self.profile.service_id,
                protocol_version=self.profile.protocol_version,
                normalization=self.profile.normalization,
            )
            return EmbeddingResult(vectors=vectors, warnings=[], profile=profile)
        except Exception as exc:
            return EmbeddingResult(
                vectors=[_normalized_vector(text, self.profile.dimension) for text in texts],
                warnings=[
                    "Local bge-m3 embedding request failed "
                    f"({safe_exception_message(exc)}); using lexical fallback."
                ],
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
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.domain = model or settings.default_embedding_model or "query"
        self.transport = transport
        self.profile = EmbeddingProfile(
            provider="xfyun-spark",
            model="spark-embedding",
            dimension=2560,
            service_id="xfyun-spark-embedding",
            protocol_version="embedding-http-v1",
            normalization="provider",
            domain_compatibility="query-para",
        )

    async def embed(self, texts: list[str]) -> EmbeddingResult:
        if not texts:
            return EmbeddingResult(vectors=[], warnings=[], profile=self.profile)
        if not self.settings.xfyun_spark_app_id or not self.settings.xfyun_spark_api_key or not self.settings.xfyun_spark_api_secret:
            return EmbeddingResult(
                vectors=[],
                warnings=["XFYUN_SPARK credentials missing; using lexical fallback."],
                profile=self.profile,
                is_fallback=True,
            )
        oversized = [
            index
            for index, text in enumerate(texts)
            if self._payload_text_bytes(text) > self.settings.xfyun_max_text_bytes
        ]
        if oversized:
            return EmbeddingResult(
                vectors=[],
                warnings=[
                    f"Xfyun Spark input exceeded {self.settings.xfyun_max_text_bytes} bytes at indexes {oversized}."
                ],
                profile=self.profile,
                is_fallback=True,
            )
        request_url = (
            f"{self.settings.xfyun_spark_embedding_url.rstrip('/')}"
            f"{self.settings.xfyun_spark_embedding_path}"
        )
        semaphore = _shared_limiter(
            request_url,
            self.settings.xfyun_embedding_concurrency,
        )
        timeout = httpx.Timeout(connect=5.0, read=30.0, write=30.0, pool=5.0)
        try:
            if self.transport is None:
                client = _shared_http_client(request_url, timeout)
                vectors = await asyncio.gather(
                    *(self._embed_single(client, semaphore, text) for text in texts)
                )
            else:
                async with httpx.AsyncClient(
                    transport=self.transport,
                    timeout=timeout,
                ) as client:
                    vectors = await asyncio.gather(
                        *(self._embed_single(client, semaphore, text) for text in texts)
                    )
            self._validate_vectors(vectors, len(texts))
            return EmbeddingResult(vectors=vectors, warnings=[], profile=self.profile)
        except Exception as exc:
            return EmbeddingResult(
                vectors=[],
                warnings=[
                    "Xfyun Spark embedding failed "
                    f"({safe_exception_message(exc)}); lexical retrieval remains available."
                ],
                profile=self.profile,
                is_fallback=True,
            )

    def _build_auth_url(self, request_url: str, api_key: str, api_secret: str) -> str:
        """Build signed URL using the same algorithm as the Spark demo."""
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
        text_obj = {"messages": [{"content": text, "role": "user"}]}
        text_b64 = base64.b64encode(
            json.dumps(text_obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).decode()

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

    async def _embed_single(
        self,
        client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
        text: str,
    ) -> list[float]:
        """Call one protocol-compatible endpoint with bounded retries."""
        request_url = f"{self.settings.xfyun_spark_embedding_url.rstrip('/')}{self.settings.xfyun_spark_embedding_path}"
        async with semaphore:
            for attempt in range(3):
                url = self._build_auth_url(
                    request_url,
                    api_key=self.settings.xfyun_spark_api_key or "",
                    api_secret=self.settings.xfyun_spark_api_secret or "",
                )
                try:
                    response = await client.post(
                        url,
                        json=self._build_body(text),
                        headers={"content-type": "application/json"},
                    )
                    if response.status_code == 429 or response.status_code >= 500:
                        if attempt < 2:
                            await asyncio.sleep((0.5 * (2**attempt)) + random.uniform(0.0, 0.1))
                            continue
                    response.raise_for_status()
                    data = response.json()
                    code = data["header"]["code"]
                    if code != 0:
                        raise RuntimeError(
                            f"Xfyun Spark API error (code={code}): "
                            f"{data['header'].get('message', 'unknown')}"
                        )
                    return self._decode_vector(data["payload"]["feature"]["text"])
                except (httpx.TimeoutException, httpx.NetworkError):
                    if attempt >= 2:
                        raise
                    await asyncio.sleep((0.5 * (2**attempt)) + random.uniform(0.0, 0.1))
        raise RuntimeError("Xfyun Spark embedding retry loop exhausted.")

    @staticmethod
    def _decode_vector(text_base: str) -> list[float]:
        import numpy as np

        raw_bytes = base64.b64decode(text_base)
        dt = np.dtype(np.float32).newbyteorder("<")
        return np.frombuffer(raw_bytes, dtype=dt).tolist()

    def _payload_text_bytes(self, text: str) -> int:
        return xfyun_request_payload_bytes(
            text,
            app_id=self.settings.xfyun_spark_app_id or "",
            domain=self.domain,
        )

    def _validate_vectors(self, vectors: list[list[float]], expected_count: int) -> None:
        if len(vectors) != expected_count:
            raise ValueError(
                f"Xfyun Spark returned {len(vectors)} vectors for {expected_count} texts."
            )
        for vector in vectors:
            if len(vector) != self.profile.dimension:
                raise ValueError(
                    f"Xfyun Spark returned {len(vector)} dimensions; expected {self.profile.dimension}."
                )
            if not all(math.isfinite(float(value)) for value in vector):
                raise ValueError("Xfyun Spark returned NaN or Inf values.")


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
        provider="xfyun-spark",
        model=lambda settings: "query",  # "query" or "para"
        factory=_xfyun_spark_factory,
        available=lambda settings: bool(settings.xfyun_spark_app_id and settings.xfyun_spark_api_key and settings.xfyun_spark_api_secret),
        warning=lambda settings: (
            None
            if settings.xfyun_spark_app_id and settings.xfyun_spark_api_key and settings.xfyun_spark_api_secret
            else "XFYUN_SPARK credentials are incomplete; semantic retrieval will use lexical fallback."
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
    if selected == "mock" and not settings.synthetic_mode_enabled:
        raise ValueError(
            "Synthetic embeddings are disabled; set ALLOW_SYNTHETIC_MODE=true only for explicit development use."
        )
    for entry in EMBEDDING_MODEL_REGISTRY:
        if entry.provider == selected:
            return entry.factory(settings, model)
    raise ValueError(f"Unsupported embedding provider: {selected}")
