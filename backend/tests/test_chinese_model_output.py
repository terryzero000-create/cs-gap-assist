import asyncio

from backend.core.config import Settings
from backend.llm.chains import experiment_chain, gap_chain
from backend.llm.llm_service import MockChatProvider
from backend.models.schemas import ExperimentSuggestRequest, GapAnalysisRequest
from backend.services.external_paper import ExternalPaper


def has_cjk(text: str) -> bool:
    """Return whether text contains a Chinese character."""
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def test_mock_chat_provider_returns_chinese_gap_and_experiment_content() -> None:
    """Fallback model output should match the Chinese product experience."""
    provider = MockChatProvider()

    gap_text, _gap_warnings = asyncio.run(provider.generate("GAP_JSON"))
    experiment_text, _experiment_warnings = asyncio.run(provider.generate("EXPERIMENT_JSON"))
    qa_text, _qa_warnings = asyncio.run(provider.generate("READING_QA"))

    assert has_cjk(gap_text)
    assert has_cjk(experiment_text)
    assert has_cjk(qa_text)


def test_gap_prompt_requires_chinese_structured_values(monkeypatch, tmp_path) -> None:
    """Gap analysis prompts should force Chinese values while keeping JSON keys stable."""
    captured_prompts: list[str] = []

    class CapturingProvider:
        async def generate(self, prompt: str, model: str | None = None) -> tuple[str, list[str]]:
            captured_prompts.append(prompt)
            return '{"gaps":[{"title":"证据覆盖不足","value_level":"mid","description":"现有研究缺少长期评估。","evidence_papers":["paper-1"]}]}', []

    class StubArxivSearchClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def search(self, query: str, limit: int = 5) -> tuple[list[ExternalPaper], list[str]]:
            return [ExternalPaper(paper_id="paper-1", title="RAG Robustness", abstract="Evidence.", year=2025)], []

    monkeypatch.setattr(gap_chain, "get_chat_provider", lambda settings, provider=None: CapturingProvider())
    monkeypatch.setattr(gap_chain, "ArxivSearchClient", StubArxivSearchClient)

    response = asyncio.run(
        gap_chain.analyze_research_gaps(
            GapAnalysisRequest(topic="RAG robustness", doc_ids=[]),
            Settings(sqlite_url=f"sqlite:///{tmp_path / 'gap.db'}"),
        )
    )

    assert "必须使用简体中文" in captured_prompts[0]
    assert "JSON 字段名保持英文" in captured_prompts[0]
    assert response.gaps[0].title == "证据覆盖不足"


def test_experiment_prompt_requires_chinese_structured_values(monkeypatch, tmp_path) -> None:
    """Experiment prompts should force Chinese list values and explanations."""
    captured_prompts: list[str] = []

    class CapturingProvider:
        async def generate(self, prompt: str, model: str | None = None) -> tuple[str, list[str]]:
            captured_prompts.append(prompt)
            return (
                '{"experiments":[{"objective":"评估跨域鲁棒性","datasets":["公开 RAG 基准"],'
                '"metrics":["F1"],"baselines":["BM25"],"steps":["构建跨域划分"],"risks":["标注可能不足"]}]}',
                [],
            )

    class StubArxivSearchClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def search(self, query: str, limit: int = 5) -> tuple[list[ExternalPaper], list[str]]:
            return [
                ExternalPaper(paper_id=f"paper-{index}", title=f"Paper {index}", abstract="Evidence.", year=2025)
                for index in range(1, limit + 1)
            ], []

    monkeypatch.setattr(experiment_chain, "get_chat_provider", lambda settings, provider=None: CapturingProvider())
    monkeypatch.setattr(experiment_chain, "ArxivSearchClient", StubArxivSearchClient)

    response = asyncio.run(
        experiment_chain.suggest_experiments(
            ExperimentSuggestRequest(gap_id="gap-cn", topic="RAG robustness"),
            Settings(sqlite_url=f"sqlite:///{tmp_path / 'experiment.db'}"),
        )
    )

    assert "必须使用简体中文" in captured_prompts[0]
    assert "JSON 字段名保持英文" in captured_prompts[0]
    assert response.experiments[0].objective == "评估跨域鲁棒性"
