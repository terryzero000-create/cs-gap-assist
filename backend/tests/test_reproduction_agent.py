from fastapi.testclient import TestClient

from backend.core.config import get_settings
from backend.main import app
from backend.models.schemas import PaperChunk
from backend.repositories.sqlite_store import SQLiteStore
from backend.services import reproduction_agent


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


def test_reproduction_agent_repairs_missing_dataset_and_metric_once(monkeypatch) -> None:
    calls: list[str] = []

    class RepairProvider:
        is_synthetic = False

        async def generate(self, prompt: str, model: str | None = None):
            calls.append(prompt)
            return '{"datasets":["Natural Questions"],"metrics":["F1"]}', []

    monkeypatch.setattr(
        reproduction_agent,
        "get_chat_provider",
        lambda _settings, _provider=None: RepairProvider(),
    )
    paper_id = "repro-repair-paper"
    SQLiteStore(get_settings().sqlite_path).add_paper(
        paper_id,
        "repair.pdf",
        [
            PaperChunk(
                chunk_id="repro-repair-chunk",
                doc_id=paper_id,
                page=1,
                text="Experiments use Natural Questions and report F1 for evaluation.",
            )
        ],
    )

    response = TestClient(app).post(
        "/api/v1/reproduction-agent/run",
        json={
            "paper_id": paper_id,
            "mode": "standard",
            "user_requirement": "extract the reproduction fields",
        },
    )

    assert response.status_code == 200
    assert len(calls) == 1
    assert "REPRODUCTION_FIELDS_REPAIR_JSON" in calls[0]
    assert response.json()["report"]["datasets"] == ["Natural Questions"]
    assert response.json()["report"]["metrics"] == ["F1"]


def test_reproduction_agent_rejects_ungrounded_repair_values(monkeypatch) -> None:
    calls = 0

    class UngroundedRepairProvider:
        is_synthetic = False

        async def generate(self, _prompt: str, model: str | None = None):
            nonlocal calls
            calls += 1
            return '{"datasets":["Invented Dataset"],"metrics":["Invented Metric"]}', []

    monkeypatch.setattr(
        reproduction_agent,
        "get_chat_provider",
        lambda _settings, _provider=None: UngroundedRepairProvider(),
    )
    paper_id = "repro-ungrounded-paper"
    SQLiteStore(get_settings().sqlite_path).add_paper(
        paper_id,
        "ungrounded.pdf",
        [
            PaperChunk(
                chunk_id="repro-ungrounded-chunk",
                doc_id=paper_id,
                page=1,
                text="The paper describes a method but omits evaluation details.",
            )
        ],
    )

    response = TestClient(app).post(
        "/api/v1/reproduction-agent/run",
        json={
            "paper_id": paper_id,
            "mode": "focused",
            "user_requirement": "extract only grounded fields",
        },
    )

    assert response.status_code == 200
    assert calls == 1
    assert response.json()["report"]["datasets"] == ["unknown"]
    assert response.json()["report"]["metrics"] == ["unknown"]
    assert any("ungrounded datasets" in warning for warning in response.json()["warnings"])
