import json
from typing import Any

import httpx

from backend.core.config import Settings


class ChatProvider:
    """Interface for chat-completion providers."""

    async def generate(self, prompt: str, model: str | None = None) -> tuple[str, list[str]]:
        """Generate text from a prompt and return warnings."""
        raise NotImplementedError


class MockChatProvider(ChatProvider):
    """Deterministic chat provider for local development and tests."""

    async def generate(self, prompt: str, model: str | None = None) -> tuple[str, list[str]]:
        """Generate a deterministic Chinese response for the supplied prompt."""
        if "GAP_JSON" in prompt:
            payload = {
                "gaps": [
                    {
                        "title": "跨数据集泛化验证不足",
                        "value_level": "high",
                        "description": "现有工作往往只在单一数据集上验证，缺少跨领域迁移和长期鲁棒性证据。",
                        "evidence_papers": ["mock-paper-1", "mock-paper-2"],
                    },
                    {
                        "title": "消融实验覆盖不完整",
                        "value_level": "mid",
                        "description": "关键模块的独立贡献尚未通过系统消融和误差分析充分解释。",
                        "evidence_papers": ["mock-paper-2"],
                    },
                ]
            }
            return json.dumps(payload, ensure_ascii=False), ["Chat provider fell back to mock generation."]
        if "EXPERIMENT_JSON" in prompt:
            payload = {
                "experiments": [
                    {
                        "objective": "验证方法在跨领域场景下的泛化能力。",
                        "datasets": ["PapersWithCode公开数据集", "arXiv领域子集"],
                        "metrics": ["Accuracy", "F1", "NDCG"],
                        "baselines": ["BM25", "标准RAG", "无重排序版本"],
                        "steps": ["构建领域划分", "训练或配置基线", "执行跨领域评估", "进行误差分析"],
                        "risks": ["数据集规模不足", "外部API返回不稳定"],
                    }
                ]
            }
            return json.dumps(payload, ensure_ascii=False), ["Chat provider fell back to mock generation."]
        return "基于已检索段落，当前论文的核心贡献和局限已在来源中标注。", ["Chat provider fell back to mock generation."]


class DeepSeekChatProvider(ChatProvider):
    """DeepSeek chat provider using the OpenAI-compatible API shape."""

    def __init__(self, settings: Settings) -> None:
        """Create a DeepSeek chat provider."""
        self.settings = settings
        self.mock = MockChatProvider()

    async def generate(self, prompt: str, model: str | None = None) -> tuple[str, list[str]]:
        """Generate with DeepSeek or fall back to mock output when unavailable."""
        selected_model = model or self.settings.default_chat_model
        if not self.settings.deepseek_api_key:
            text, warnings = await self.mock.generate(prompt, selected_model)
            return text, [f"DEEPSEEK_API_KEY missing; using mock chat instead of {selected_model}.", *warnings]
        headers = {"Authorization": f"Bearer {self.settings.deepseek_api_key}", "Content-Type": "application/json"}
        payload: dict[str, Any] = {"model": selected_model, "messages": [{"role": "user", "content": prompt}]}
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(f"{self.settings.deepseek_base_url}/chat/completions", headers=headers, json=payload)
                response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"], []
        except Exception as exc:
            text, warnings = await self.mock.generate(prompt, selected_model)
            return text, [f"DeepSeek request failed ({exc}); using mock chat.", *warnings]


def get_chat_provider(settings: Settings, provider: str | None = None) -> ChatProvider:
    """Resolve a chat provider from runtime config."""
    selected = provider or settings.default_chat_provider
    if selected == "deepseek":
        return DeepSeekChatProvider(settings)
    return MockChatProvider()
