from fastapi.testclient import TestClient

from backend.core.config import get_settings
from backend.llm.chains import experiment_chain
from backend.main import app
from backend.models.schemas import ExperimentPlan, GapItem
from backend.repositories.sqlite_store import SQLiteStore
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

    class CapturingSemanticScholarClient:
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
    monkeypatch.setattr(experiment_chain, "SemanticScholarClient", CapturingSemanticScholarClient)
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
