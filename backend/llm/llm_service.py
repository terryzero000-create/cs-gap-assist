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
        """Generate deterministic text or structured JSON for the supplied prompt."""
        if "GAP_JSON" in prompt:
            payload = {
                "gaps": [
                    {
                        "title": "Cross-dataset generalization is under-evaluated",
                        "value_level": "high",
                        "description": "Existing work often reports results on one benchmark and lacks cross-domain robustness evidence.",
                        "evidence_papers": ["mock-paper-1", "mock-paper-2"],
                    },
                    {
                        "title": "Ablation coverage is incomplete",
                        "value_level": "mid",
                        "description": "Key module contributions need stronger ablation and error analysis.",
                        "evidence_papers": ["mock-paper-2"],
                    },
                ]
            }
            return json.dumps(payload), ["Chat provider fell back to mock generation."]
        if "EXPERIMENT_JSON" in prompt:
            payload = {
                "experiments": [
                    {
                        "objective": "Evaluate method robustness under cross-domain conditions.",
                        "datasets": ["PapersWithCode public benchmark", "arXiv domain subset"],
                        "metrics": ["Accuracy", "F1", "NDCG"],
                        "baselines": ["BM25", "standard RAG", "RAG without reranking"],
                        "steps": ["Build domain splits", "Configure baselines", "Run cross-domain evaluation", "Perform error analysis"],
                        "risks": ["Dataset size may be small", "External APIs may be unstable"],
                    }
                ]
            }
            return json.dumps(payload), ["Chat provider fell back to mock generation."]
        if "READING_QA" in prompt:
            return "根据已检索到的来源段落，可以给出一个有依据的回答。[1]", ["Chat provider fell back to mock generation."]
        return "Mock answer grounded in retrieved source paragraphs.", ["Chat provider fell back to mock generation."]


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
