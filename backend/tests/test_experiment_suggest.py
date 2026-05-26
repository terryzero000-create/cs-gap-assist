from fastapi.testclient import TestClient

from backend.main import app


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
