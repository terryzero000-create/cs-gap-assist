from fastapi.testclient import TestClient

from backend.core.config import get_settings
from backend.main import app
from backend.models.schemas import PaperChunk
from backend.repositories.sqlite_store import SQLiteStore


def test_reproduction_agent_rejects_missing_paper() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/v1/reproduction-agent/run",
        json={"paper_id": "missing-paper", "mode": "standard", "user_requirement": "reproduce the main experiment"},
    )

    assert response.status_code == 400
    assert "Paper not found" in response.json()["error"]


def test_reproduction_agent_returns_tool_steps_and_report() -> None:
    client = TestClient(app)
    paper_id = "repro-test-paper"
    SQLiteStore(get_settings().sqlite_path).add_paper(
        paper_id,
        "repro.pdf",
        [
            PaperChunk(
                chunk_id="repro-test-chunk",
                doc_id=paper_id,
                page=1,
                text=(
                    "Title: RAG Reproduction. Method: retrieve passages then rerank answers. "
                    "Dataset: Natural Questions. Metric: F1. Baseline: BM25. "
                    "Algorithm uses retrieval and reranking steps."
                ),
            )
        ],
    )

    response = client.post(
        "/api/v1/reproduction-agent/run",
        json={"paper_id": paper_id, "mode": "template", "user_requirement": "only give safe templates"},
    )

    assert response.status_code == 200
    body = response.json()
    tool_names = [step["tool_name"] for step in body["agent_steps"]]
    assert tool_names[:2] == ["retrieve_paper_context", "extract_reproduction_info"]
    assert "generate_code_skeleton" in tool_names
    assert "generate_simulation_template" in tool_names
    assert tool_names[-1] == "generate_report"
    assert body["report"]["paper_id"] == paper_id
    assert "Natural Questions" in body["report"]["datasets"]
    assert body["report"]["code_template"]
    assert body["report"]["simulation_template"]
    assert any("不运行代码" in item for item in body["report"]["non_claims"])
    assert any("不承诺达到论文指标" in item for item in body["report"]["non_claims"])
    assert any("模板" in item for item in body["report"]["non_claims"])
