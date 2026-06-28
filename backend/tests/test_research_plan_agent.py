from fastapi.testclient import TestClient

from backend.core.config import get_settings
from backend.llm.chains import experiment_chain, gap_chain
from backend.main import app
from backend.models.schemas import PaperChunk
from backend.repositories.sqlite_store import SQLiteStore
from backend.services import research_plan_agent
from backend.services.external_paper import ExternalPaper


class StubArxivSearchClient:
    def __init__(self, *args, **kwargs) -> None:
        pass

    async def search(self, query: str, limit: int = 5) -> tuple[list[ExternalPaper], list[str]]:
        return [
            ExternalPaper(
                paper_id=f"arxiv-{index}",
                title=f"Follow-up paper {index}",
                abstract="Evidence for research planning.",
                year=2026,
            )
            for index in range(1, limit + 1)
        ], []


def test_research_plan_agent_requires_selected_papers() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/v1/research-plan-agent/run",
        json={"research_direction": "RAG robustness", "selected_paper_ids": []},
    )

    assert response.status_code == 400
    assert response.json()["error"]


def test_research_plan_agent_returns_steps_and_cards(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SQLITE_URL", str(tmp_path / "agent.db"))
    monkeypatch.setattr(gap_chain, "ArxivSearchClient", StubArxivSearchClient)
    monkeypatch.setattr(experiment_chain, "ArxivSearchClient", StubArxivSearchClient)
    monkeypatch.setattr(research_plan_agent, "ArxivSearchClient", StubArxivSearchClient)
    get_settings.cache_clear()
    paper_id = "paper-agent"
    SQLiteStore(get_settings().sqlite_path).add_paper(
        paper_id,
        "agent.pdf",
        [
            PaperChunk(
                chunk_id="chunk-agent",
                doc_id=paper_id,
                page=1,
                text="RAG robustness needs cross-domain evaluation, BM25 baselines, and F1 metrics.",
            )
        ],
    )
    client = TestClient(app)

    response = client.post(
        "/api/v1/research-plan-agent/run",
        json={
            "research_direction": "RAG robustness",
            "selected_paper_ids": [paper_id],
            "experiment_result": "BM25 baseline is weak on domain shift.",
        },
    )

    get_settings.cache_clear()
    assert response.status_code == 200
    body = response.json()
    tool_names = [step["tool_name"] for step in body["agent_steps"]]
    assert len(tool_names) <= 10
    assert tool_names == [
        "understand_goal",
        "plan_steps",
        "knowledge_search_tool",
        "paper_summary_tool",
        "gap_analysis_tool",
        "select_top_3_gaps",
        "experiment_suggestion_tool",
        "paper_recommendation_tool",
        "research_report_tool",
    ]
    assert all(step["thought"] and step["observation"] and step["next_decision"] for step in body["agent_steps"])
    card = body["final_cards"][0]
    assert card["title"]
    assert card["background"]
    assert card["research_gap"]
    assert card["entry_point"]
    assert card["experiment_suggestion"]
    assert card["recommended_papers"]
    assert card["risks"]
    assert card["next_action"]


def test_research_plan_agent_falls_back_to_sqlite_chunks(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SQLITE_URL", str(tmp_path / "fallback.db"))
    monkeypatch.setattr(gap_chain, "ArxivSearchClient", StubArxivSearchClient)
    monkeypatch.setattr(experiment_chain, "ArxivSearchClient", StubArxivSearchClient)
    monkeypatch.setattr(research_plan_agent, "ArxivSearchClient", StubArxivSearchClient)
    get_settings.cache_clear()
    paper_id = "paper-sqlite-only"
    SQLiteStore(get_settings().sqlite_path).add_paper(
        paper_id,
        "sqlite-only.pdf",
        [PaperChunk(chunk_id="chunk-sqlite-only", doc_id=paper_id, page=1, text="Evaluation misses production drift.")],
    )
    client = TestClient(app)

    response = client.post(
        "/api/v1/research-plan-agent/run",
        json={"research_direction": "production drift evaluation", "selected_paper_ids": [paper_id]},
    )

    get_settings.cache_clear()
    assert response.status_code == 200
    body = response.json()
    search_step = next(step for step in body["agent_steps"] if step["tool_name"] == "knowledge_search_tool")
    assert "Retrieved" in search_step["observation"]
    assert body["final_cards"]
    assert "SQLite chunk fallback" in " ".join(body["warnings"])


def test_research_plan_agent_keeps_original_gap_and_experiment_endpoints(monkeypatch) -> None:
    monkeypatch.setattr(gap_chain, "ArxivSearchClient", StubArxivSearchClient)
    monkeypatch.setattr(experiment_chain, "ArxivSearchClient", StubArxivSearchClient)
    client = TestClient(app)
    upload = client.post(
        "/api/v1/papers/upload",
        files={"file": ("old.pdf", b"RAG evaluations need better baselines.", "application/pdf")},
    )
    doc_id = upload.json()["doc_id"]

    gap_response = client.post("/api/v1/gaps/analyze", json={"topic": "RAG baselines", "doc_ids": [doc_id]})
    experiment_response = client.post("/api/v1/experiments/suggest", json={"gap_id": "gap-old", "topic": "RAG baselines"})

    assert gap_response.status_code == 200
    assert gap_response.json()["gaps"]
    assert experiment_response.status_code == 200
    assert experiment_response.json()["experiments"]
