from fastapi.testclient import TestClient

import asyncio
import json

import httpx

from backend.core.config import Settings, get_settings
from backend.llm.chains import experiment_chain
from backend.main import app
from backend.models.schemas import ExperimentPlan, ExperimentSuggestRequest, GapItem
from backend.repositories.sqlite_store import SQLiteStore
from backend.services.arxiv_search import ArxivSearchClient
from backend.services.semantic_scholar import ExternalPaper


def test_experiment_suggestion_contains_literature_supported_plan() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/v1/experiments/suggest",
        json={"gap_id": "gap-123", "topic": "RAG robustness evaluation"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["experiments"]
    plan = body["experiments"][0]
    assert plan["gap_id"] == "gap-123"
    assert plan["datasets"]
    assert plan["metrics"]
    assert plan["baselines"]
    assert plan["steps"]
    assert len(plan["support_papers"]) >= 3
    assert len(plan["support_papers"]) <= 5


def test_experiment_suggestion_is_persisted(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SQLITE_URL", str(tmp_path / "experiments.db"))
    get_settings.cache_clear()
    client = TestClient(app)

    response = client.post(
        "/api/v1/experiments/suggest",
        json={"gap_id": "gap-persist", "topic": "Multimodal benchmark gaps"},
    )

    assert response.status_code == 200
    plan = response.json()["experiments"][0]
    stored = SQLiteStore(get_settings().sqlite_path).list_experiments(gap_id="gap-persist")
    get_settings.cache_clear()

    assert [item.experiment_id for item in stored] == [plan["experiment_id"]]


def test_experiment_suggestion_uses_stored_gap_when_topic_is_omitted(tmp_path, monkeypatch) -> None:
    captured_queries: list[str] = []

    class CapturingArxivSearchClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def search(self, query: str, limit: int = 5) -> tuple[list[ExternalPaper], list[str]]:
            captured_queries.append(query)
            papers = [
                ExternalPaper(
                    paper_id=f"paper-{index}",
                    title=f"Support paper {index}",
                    abstract="Experiment evidence.",
                    year=2025,
                )
                for index in range(1, limit + 1)
            ]
            return papers, []

    monkeypatch.setenv("SQLITE_URL", str(tmp_path / "experiments.db"))
    monkeypatch.setattr(experiment_chain, "ArxivSearchClient", CapturingArxivSearchClient)
    get_settings.cache_clear()
    store = SQLiteStore(get_settings().sqlite_path)
    store.save_gap(
        GapItem(
            gap_id="gap-real",
            title="Longitudinal deployment evaluation is missing",
            value_level="high",
            description="Existing RAG studies rarely measure production drift over time.",
            evidence_papers=["paper-a"],
        )
    )
    client = TestClient(app)

    response = client.post("/api/v1/experiments/suggest", json={"gap_id": "gap-real"})

    assert response.status_code == 200
    get_settings.cache_clear()
    assert captured_queries == [
        "Longitudinal deployment evaluation is missing. Existing RAG studies rarely measure production drift over time."
    ]


def test_gap_history_endpoint_returns_stored_gaps(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SQLITE_URL", str(tmp_path / "experiments.db"))
    get_settings.cache_clear()
    store = SQLiteStore(get_settings().sqlite_path)
    store.save_gap(
        GapItem(
            gap_id="gap-history",
            title="Benchmark coverage is narrow",
            value_level="mid",
            description="Existing evaluations do not cover enough deployment settings.",
            evidence_papers=["paper-b"],
        )
    )
    client = TestClient(app)

    response = client.get("/api/v1/gaps/history")

    assert response.status_code == 200
    get_settings.cache_clear()
    assert response.json()["gaps"][0]["gap_id"] == "gap-history"


def test_experiment_history_endpoint_filters_by_gap_id(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SQLITE_URL", str(tmp_path / "experiments.db"))
    get_settings.cache_clear()
    store = SQLiteStore(get_settings().sqlite_path)
    expected = store.save_experiment(
        ExperimentPlan(
            gap_id="gap-history",
            objective="Evaluate benchmark transfer.",
            datasets=["Dataset A"],
            metrics=["F1"],
            baselines=["BM25"],
            steps=["Run baseline"],
            risks=["Small sample"],
            support_papers=["paper-a", "paper-b", "paper-c"],
        )
    )
    store.save_experiment(
        ExperimentPlan(
            gap_id="other-gap",
            objective="Unrelated plan.",
            datasets=["Dataset B"],
            metrics=["Accuracy"],
            baselines=["RAG"],
            steps=["Run model"],
            risks=["Noisy labels"],
            support_papers=["paper-d", "paper-e", "paper-f"],
        )
    )
    client = TestClient(app)

    response = client.get("/api/v1/experiments/history", params={"gap_id": "gap-history"})

    assert response.status_code == 200
    get_settings.cache_clear()
    experiments = response.json()["experiments"]
    assert [experiment["experiment_id"] for experiment in experiments] == [expected.experiment_id]


def test_arxiv_client_parses_atom_response_shape() -> None:
    atom = """<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <id>http://arxiv.org/abs/2501.00001v1</id>
        <title>Experiment Design for Robust RAG</title>
        <summary>We evaluate retrieval systems under domain shift.</summary>
        <published>2025-01-02T00:00:00Z</published>
      </entry>
    </feed>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["search_query"] == "all:rag experiments"
        return httpx.Response(200, text=atom)

    client = ArxivSearchClient(transport=httpx.MockTransport(handler))

    papers, warnings = asyncio.run(client.search("rag experiments", limit=1))

    assert warnings == []
    assert papers[0].paper_id == "arxiv-2501.00001"
    assert papers[0].title == "Experiment Design for Robust RAG"
    assert papers[0].abstract == "We evaluate retrieval systems under domain shift."
    assert papers[0].year == 2025


def test_experiment_suggestion_skips_semantic_scholar_by_default(monkeypatch, tmp_path) -> None:
    class BlockingSemanticScholarClient:
        def __init__(self, *args, **kwargs) -> None:
            raise AssertionError("Semantic Scholar should be disabled by default.")

    class StubArxivSearchClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def search(self, query: str, limit: int = 5) -> tuple[list[ExternalPaper], list[str]]:
            return [
                ExternalPaper(
                    paper_id=f"arxiv-{index}",
                    title=f"Experiment support {index}",
                    abstract="Evidence for experiment design.",
                    year=2025,
                )
                for index in range(1, limit + 1)
            ], []

    monkeypatch.setenv("SQLITE_URL", str(tmp_path / "experiments.db"))
    get_settings.cache_clear()
    monkeypatch.setattr(experiment_chain, "SemanticScholarClient", BlockingSemanticScholarClient)
    monkeypatch.setattr(experiment_chain, "ArxivSearchClient", StubArxivSearchClient)
    client = TestClient(app)

    response = client.post(
        "/api/v1/experiments/suggest",
        json={"gap_id": "gap-arxiv", "topic": "rag experiments"},
    )

    assert response.status_code == 200
    get_settings.cache_clear()
    assert response.json()["experiments"][0]["support_papers"][0] == "arxiv-1"


def test_experiment_suggestion_does_not_pass_semantic_scholar_credentials(monkeypatch, tmp_path) -> None:
    captured_kwargs: list[dict[str, object]] = []

    class CapturingSemanticScholarClient:
        def __init__(self, **kwargs: object) -> None:
            captured_kwargs.append(kwargs)

        async def search(self, query: str, limit: int = 5) -> tuple[list[ExternalPaper], list[str]]:
            return [
                ExternalPaper(
                    paper_id=f"semantic-{index}",
                    title=f"Semantic support {index}",
                    abstract="Evidence for experiment design.",
                    year=2025,
                )
                for index in range(1, limit + 1)
            ], []

    class StubArxivSearchClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def search(self, query: str, limit: int = 5) -> tuple[list[ExternalPaper], list[str]]:
            return [
                ExternalPaper(
                    paper_id=f"arxiv-{index}",
                    title=f"Arxiv support {index}",
                    abstract="Evidence for experiment design.",
                    year=2025,
                )
                for index in range(1, limit + 1)
            ], []

    monkeypatch.setattr(experiment_chain, "SemanticScholarClient", CapturingSemanticScholarClient)
    monkeypatch.setattr(experiment_chain, "ArxivSearchClient", StubArxivSearchClient)

    response = asyncio.run(
        experiment_chain.suggest_experiments(
            ExperimentSuggestRequest(gap_id="gap-semantic", topic="rag experiments"),
            Settings(enable_semantic_scholar=True, sqlite_url=f"sqlite:///{tmp_path / 'experiment.db'}"),
        )
    )

    assert response.experiments[0].support_papers[0] == "semantic-1"
    assert captured_kwargs == [{"timeout_seconds": 3.0}]


def test_experiment_suggestion_repairs_fenced_json(monkeypatch, tmp_path) -> None:
    class FencedJsonProvider:
        async def generate(self, prompt: str, model: str | None = None) -> tuple[str, list[str]]:
            payload = {
                "experiments": [
                    {
                        "objective": "Evaluate drift-aware retrieval robustness.",
                        "datasets": ["Dataset A"],
                        "metrics": ["F1"],
                        "baselines": ["BM25"],
                        "steps": ["Run cross-domain split"],
                        "risks": ["Limited labels"],
                    }
                ]
            }
            return f"Here is the plan:\n```json\n{json.dumps(payload)}\n```", ["used test provider"]

    class StubArxivSearchClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def search(self, query: str, limit: int = 5) -> tuple[list[ExternalPaper], list[str]]:
            return [
                ExternalPaper(
                    paper_id=f"arxiv-{index}",
                    title=f"Support paper {index}",
                    abstract="Evidence for experiment design.",
                    year=2025,
                )
                for index in range(1, limit + 1)
            ], []

    monkeypatch.setattr(experiment_chain, "ArxivSearchClient", StubArxivSearchClient)
    monkeypatch.setattr(experiment_chain, "get_chat_provider", lambda settings, provider=None: FencedJsonProvider())

    response = asyncio.run(
        experiment_chain.suggest_experiments(
            ExperimentSuggestRequest(gap_id="gap-fenced", topic="rag drift"),
            Settings(sqlite_url=f"sqlite:///{tmp_path / 'experiment.db'}"),
        )
    )

    assert response.experiments[0].objective == "Evaluate drift-aware retrieval robustness."
    assert response.experiments[0].support_papers == ["arxiv-1", "arxiv-2", "arxiv-3", "arxiv-4", "arxiv-5"]
    assert "used test provider" in response.warnings


def test_experiment_suggestion_falls_back_for_invalid_model_output(monkeypatch, tmp_path) -> None:
    class InvalidJsonProvider:
        async def generate(self, prompt: str, model: str | None = None) -> tuple[str, list[str]]:
            return "not json", ["used invalid provider"]

    class StubArxivSearchClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def search(self, query: str, limit: int = 5) -> tuple[list[ExternalPaper], list[str]]:
            return [
                ExternalPaper(
                    paper_id=f"arxiv-{index}",
                    title=f"Support paper {index}",
                    abstract="Evidence for experiment design.",
                    year=2025,
                )
                for index in range(1, limit + 1)
            ], []

    monkeypatch.setattr(experiment_chain, "ArxivSearchClient", StubArxivSearchClient)
    monkeypatch.setattr(experiment_chain, "get_chat_provider", lambda settings, provider=None: InvalidJsonProvider())

    response = asyncio.run(
        experiment_chain.suggest_experiments(
            ExperimentSuggestRequest(gap_id="gap-invalid", topic="rag drift"),
            Settings(sqlite_url=f"sqlite:///{tmp_path / 'experiment.db'}"),
        )
    )

    assert response.experiments[0].gap_id == "gap-invalid"
    assert response.experiments[0].datasets
    assert len(response.experiments[0].support_papers) == 5
    assert "Model did not return valid experiment JSON; using deterministic fallback experiment." in response.warnings
