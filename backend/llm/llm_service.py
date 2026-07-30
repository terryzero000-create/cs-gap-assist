import json
import re
from dataclasses import dataclass
from collections.abc import Callable
from typing import Any

import httpx

from backend.core.config import Settings
from backend.core.sanitize import safe_exception_message
from backend.models.schemas import ModelOption


class ChatProvider:
    """Interface for chat-completion providers."""

    is_synthetic = False

    async def generate(self, prompt: str, model: str | None = None) -> tuple[str, list[str]]:
        """Generate text from a prompt and return warnings."""
        raise NotImplementedError


class ChatProviderUnavailable(RuntimeError):
    """Raised when a configured real chat provider cannot produce a trusted response."""


class MockChatProvider(ChatProvider):
    """Deterministic chat provider for local development and tests."""

    is_synthetic = True

    async def generate(self, prompt: str, model: str | None = None) -> tuple[str, list[str]]:
        """Generate deterministic Chinese text or structured JSON for the supplied prompt."""
        if "GAP_JSON" in prompt:
            allowed_match = re.search(r"允许的证据 id：([^\n]+)", prompt)
            allowed_ids = (
                [value.strip() for value in allowed_match.group(1).split(",") if value.strip()]
                if allowed_match
                else []
            )
            payload = {
                "gaps": [
                    {
                        "title": "跨数据集泛化评估不足",
                        "value_level": "high",
                        "description": "现有工作通常只在单一基准上报告结果，缺少跨领域鲁棒性证据。Cross-dataset generalization 可保留为英文术语。",
                        "evidence_papers": allowed_ids[:2],
                    },
                    {
                        "title": "消融实验覆盖不完整",
                        "value_level": "mid",
                        "description": "关键模块贡献需要更充分的 ablation study 和错误分析支撑。",
                        "evidence_papers": allowed_ids[1:2] or allowed_ids[:1],
                    },
                ]
            }
            return json.dumps(payload, ensure_ascii=False), ["Synthetic mock chat generation was explicitly selected."]
        if "EXPERIMENT_JSON" in prompt:
            payload = {
                "experiments": [
                    {
                        "objective": "评估方法在跨领域条件下的鲁棒性。",
                        "datasets": ["PapersWithCode 公开基准", "arXiv 领域子集"],
                        "metrics": ["Accuracy", "F1", "NDCG"],
                        "baselines": ["BM25", "标准 RAG", "不使用 reranking 的 RAG"],
                        "steps": ["构建领域划分", "配置基线系统", "运行跨领域评估", "进行错误分析"],
                        "risks": ["数据集规模可能偏小", "外部 API 可能不稳定"],
                    }
                ]
            }
            return json.dumps(payload, ensure_ascii=False), ["Synthetic mock chat generation was explicitly selected."]
        if "READING_QA" in prompt:
            return "根据已检索到的来源片段，可以给出一个有证据支撑的中文回答。[S1]", ["Synthetic mock chat generation was explicitly selected."]
        return "这是一个基于检索片段生成的中文测试回答。", ["Synthetic mock chat generation was explicitly selected."]


class OpenAICompatibleChatProvider(ChatProvider):
    """Chat provider for APIs that implement OpenAI's chat-completions shape."""

    def __init__(
        self,
        provider_name: str,
        api_key: str | None,
        base_url: str,
        default_model: str,
        missing_api_key_name: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """Create an OpenAI-compatible provider."""
        self.provider_name = provider_name
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self.missing_api_key_name = missing_api_key_name
        self.transport = transport

    async def generate(self, prompt: str, model: str | None = None) -> tuple[str, list[str]]:
        """Generate with the configured provider and fail closed when it is unavailable."""
        selected_model = model or self.default_model
        if not self.api_key:
            key_name = self.missing_api_key_name or f"{self.provider_name.upper()}_API_KEY"
            raise ChatProviderUnavailable(f"{key_name} missing; {selected_model} was not called.")
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload: dict[str, Any] = {"model": selected_model, "messages": [{"role": "user", "content": prompt}]}
        try:
            async with httpx.AsyncClient(timeout=30.0, transport=self.transport) as client:
                response = await client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
                response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"], []
        except Exception as exc:
            raise ChatProviderUnavailable(
                f"{self.provider_name} request failed: "
                f"{safe_exception_message(exc)}"
            ) from exc


class DeepSeekChatProvider(OpenAICompatibleChatProvider):
    """DeepSeek chat provider using the OpenAI-compatible API shape."""

    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        """Create a DeepSeek chat provider."""
        default_model = settings.default_chat_model if settings.default_chat_provider == "deepseek" else "deepseek-v4-pro"
        super().__init__(
            provider_name="DeepSeek",
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            default_model=default_model,
            missing_api_key_name="DEEPSEEK_API_KEY",
            transport=transport,
        )


@dataclass(frozen=True)
class ChatModelRegistration:
    """Registry entry for a selectable chat model."""

    provider: str
    model: str
    factory: Callable[[Settings], ChatProvider]
    available: Callable[[Settings], bool]
    warning: Callable[[Settings], str | None]


def _deepseek_factory(settings: Settings) -> ChatProvider:
    return DeepSeekChatProvider(settings)


def _openai_factory(settings: Settings) -> ChatProvider:
    default_model = settings.default_chat_model if settings.default_chat_provider == "openai" else "gpt-4o-mini"
    return OpenAICompatibleChatProvider(
        provider_name="OpenAI",
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        default_model=default_model,
        missing_api_key_name="OPENAI_API_KEY",
    )


def _mock_factory(settings: Settings) -> ChatProvider:
    return MockChatProvider()


CHAT_MODEL_REGISTRY: tuple[ChatModelRegistration, ...] = (
    ChatModelRegistration(
        provider="deepseek",
        model="deepseek-v4-pro",
        factory=_deepseek_factory,
        available=lambda settings: bool(settings.deepseek_api_key),
        warning=lambda settings: None if settings.deepseek_api_key else "DEEPSEEK_API_KEY missing; generation is unavailable.",
    ),
    ChatModelRegistration(
        provider="deepseek",
        model="deepseek-v4-flash",
        factory=_deepseek_factory,
        available=lambda settings: bool(settings.deepseek_api_key),
        warning=lambda settings: None if settings.deepseek_api_key else "DEEPSEEK_API_KEY missing; generation is unavailable.",
    ),
    ChatModelRegistration(
        provider="openai",
        model="gpt-4o-mini",
        factory=_openai_factory,
        available=lambda settings: bool(settings.openai_api_key),
        warning=lambda settings: None if settings.openai_api_key else "OPENAI_API_KEY missing; generation is unavailable.",
    ),
    ChatModelRegistration(
        provider="mock",
        model="mock-chat",
        factory=_mock_factory,
        available=lambda settings: settings.synthetic_mode_enabled,
        warning=lambda settings: (
            None
            if settings.synthetic_mode_enabled
            else "Synthetic chat is disabled outside test or explicit development mode."
        ),
    ),
)


def list_chat_model_options(settings: Settings) -> list[ModelOption]:
    """Return chat models exposed through the provider registry."""
    return [
        ModelOption(
            provider=entry.provider,
            model=entry.model,
            available=entry.available(settings),
            warning=entry.warning(settings),
        )
        for entry in CHAT_MODEL_REGISTRY
    ]


def get_chat_provider(settings: Settings, provider: str | None = None) -> ChatProvider:
    """Resolve a chat provider from runtime config."""
    selected = provider or settings.default_chat_provider
    if selected == "mock" and not settings.synthetic_mode_enabled:
        raise ChatProviderUnavailable(
            "Synthetic chat is disabled; set ALLOW_SYNTHETIC_MODE=true only for explicit development use."
        )
    for entry in CHAT_MODEL_REGISTRY:
        if entry.provider == selected:
            return entry.factory(settings)
    raise ChatProviderUnavailable(f"Unsupported chat provider: {selected}")
