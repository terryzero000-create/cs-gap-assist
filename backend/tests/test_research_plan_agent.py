import asyncio

from fastapi.testclient import TestClient

from backend.core.config import get_settings
from backend.llm.chains import experiment_chain, gap_chain
from backend.main import app
from backend.models.schemas import (
    EvidenceRef,
    ExperimentPlan,
    ExperimentSuggestResponse,
    GapItem,
    PaperChunk,
    ResearchPlanAgentRequest,
)
from backend.repositories.sqlite_store import SQLiteStore
from backend.services import research_plan_agent
from backend.services.experiment_persistence import persist_trusted_experiments
from backend.services.external_paper import ExternalPaper


class StubArxivSearchClient:
    def __init__(self, *args, **kwargs) -> None:
        pass

    async def search(self, query: str, limit: int = 5) -> tuple[list[ExternalPaper], list[str]]:
        return [
            ExternalPaper(
                paper_id=f"arxiv-2501.{index:05d}",
                title=f"Follow-up paper {index}",
                abstract="Evidence for research planning.",
                year=2026,
                canonical_url=f"https://arxiv.org/abs/2501.{index:05d}",
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
    assert body["routes"]
    assert body["routes"][0]["gap"]["gap_id"]
    assert body["routes"][0]["experiments"]
    card = body["final_cards"][0]
    assert card["title"]
    assert card["background"]
    assert card["research_gap"]
    assert card["entry_point"]
    assert card["experiment_suggestion"]
    assert card["recommended_papers"]
    assert card["risks"]
    assert card["next_action"]


def test_research_plan_agent_reads_persistent_sqlite_chunks(tmp_path, monkeypatch) -> None:
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
    assert "Retrieved" in search_step["observation"]


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


def test_experiment_suggestions_isolate_one_gap_failure(tmp_path, monkeypatch) -> None:
    completed: list[str] = []

    async def isolated_suggestion(request, _settings):
        if request.gap_id == "gap-failing":
            raise RuntimeError("provider exploded")
        await asyncio.sleep(0)
        completed.append(request.gap_id)
        return ExperimentSuggestResponse(
            experiments=[
                ExperimentPlan(
                    gap_id=request.gap_id,
                    objective=f"Test {request.gap_id}",
                    datasets=["dataset"],
                    metrics=["metric"],
                    baselines=["baseline"],
                    steps=["run"],
                    risks=["risk"],
                    support_papers=[],
                    trust_status="local_only",
                )
            ],
            evidence_status="local_only",
        )

    monkeypatch.setattr(research_plan_agent, "suggest_experiments", isolated_suggestion)
    service = research_plan_agent.ResearchPlanAgentService(
        get_settings(),
        SQLiteStore(tmp_path / "isolated-agent.db"),
    )
    state = research_plan_agent.ResearchPlanState(
        request=ResearchPlanAgentRequest(
            research_direction="isolated planning",
            selected_paper_ids=["paper-1"],
        ),
        top_gaps=[
            GapItem(
                gap_id=gap_id,
                title=gap_id,
                value_level="high",
                description="test gap",
                evidence_papers=[],
            )
            for gap_id in ("gap-one", "gap-failing", "gap-two")
        ],
    )

    observation = asyncio.run(service.experiment_suggestion_tool(state))

    assert sorted(completed) == ["gap-one", "gap-two"]
    assert sorted(plan.gap_id for plan in state.experiment_suggestions) == [
        "gap-one",
        "gap-two",
    ]
    assert "Generated 2" in observation
    assert any("gap-failing" in warning for warning in state.warnings)


def test_research_plan_persists_trusted_experiments_idempotently(tmp_path, monkeypatch) -> None:
    store = SQLiteStore(tmp_path / "persisted-agent.db")
    store.add_paper(
        "paper-persist",
        "persist.pdf",
        [
            PaperChunk(
                chunk_id="chunk-persist",
                doc_id="paper-persist",
                page=1,
                text="Dataset: Visual Genome. Metric: Recall@50.",
            )
        ],
    )
    evidence = EvidenceRef(
        source="local",
        id="local:paper-persist:chunk-persist",
        title="persist.pdf",
        canonical_url="/api/v1/knowledge/papers/paper-persist#chunk-chunk-persist",
        doc_id="paper-persist",
        chunk_id="chunk-persist",
        page=1,
    )
    gap = GapItem(
        gap_id="gap-persist",
        title="Cross-domain gap",
        value_level="high",
        description="Evaluate robustness.",
        evidence_papers=[evidence.id],
        evidence_refs=[evidence],
        trust_status="local_only",
    )

    async def trusted_suggestion(request, _settings):
        return ExperimentSuggestResponse(
            experiments=[
                ExperimentPlan(
                    gap_id=request.gap_id,
                    objective="Evaluate cross-domain robustness",
                    datasets=["Visual Genome"],
                    metrics=["Recall@50"],
                    baselines=["Neural Motifs"],
                    steps=["Run evaluation"],
                    risks=["Domain mismatch"],
                    support_papers=[evidence.id],
                    support_refs=[evidence],
                    trust_status="local_only",
                )
            ],
            evidence_status="local_only",
        )

    monkeypatch.setattr(research_plan_agent, "suggest_experiments", trusted_suggestion)
    service = research_plan_agent.ResearchPlanAgentService(get_settings(), store)
    state = research_plan_agent.ResearchPlanState(
        request=ResearchPlanAgentRequest(
            research_direction="cross-domain robustness",
            selected_paper_ids=["paper-persist"],
        ),
        top_gaps=[gap],
    )

    asyncio.run(service.experiment_suggestion_tool(state))
    asyncio.run(service.experiment_suggestion_tool(state))

    stored = store.list_experiments(gap_id=gap.gap_id)
    assert len(stored) == 1
    assert stored[0].objective == "Evaluate cross-domain robustness"

    synthetic_response = ExperimentSuggestResponse(
        experiments=[
            state.experiment_suggestions[0].model_copy(
                update={"experiment_id": "synthetic-plan", "trust_status": "synthetic"}
            )
        ],
        evidence_status="synthetic",
    )
    persisted, warnings = persist_trusted_experiments(store, synthetic_response)
    assert persisted == []
    assert warnings == []
    assert len(store.list_experiments(gap_id=gap.gap_id)) == 1
