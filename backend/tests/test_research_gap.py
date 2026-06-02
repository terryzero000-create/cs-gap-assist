import asyncio
import json

import httpx
from fastapi.testclient import TestClient

from backend.core.config import Settings
from backend.llm.chains import gap_chain
from backend.main import app
from backend.models.schemas import GapAnalysisRequest
from backend.services.arxiv_search import ArxivSearchClient
from backend.services.semantic_scholar import SemanticScholarClient


def test_gap_analysis_returns_contract_shape() -> None:
    client = TestClient(app)
    upload = client.post(
        "/api/v1/papers/upload",
        files={"file": ("gap.pdf", b"Most RAG systems lack cross-domain robustness evaluation.", "application/pdf")},
    )
    doc_id = upload.json()["doc_id"]

    response = client.post(
        "/api/v1/gaps/analyze",
        json={"topic": "retrieval augmented generation robustness", "doc_ids": [doc_id]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["gaps"]
    first = body["gaps"][0]
    assert first["gap_id"]
    assert first["title"]
    assert first["value_level"] in {"high", "mid"}
    assert first["description"]
    assert first["evidence_papers"]
    assert first["created_at"]


def test_gap_history_returns_persisted_results() -> None:
    client = TestClient(app)
    upload = client.post(
        "/api/v1/papers/upload",
        files={"file": ("history.pdf", b"RAG evaluation misses production drift scenarios.", "application/pdf")},
    )
    doc_id = upload.json()["doc_id"]
    analyzed = client.post(
        "/api/v1/gaps/analyze",
        json={"topic": "rag production drift", "doc_ids": [doc_id]},
    )
    gap_id = analyzed.json()["gaps"][0]["gap_id"]

    response = client.get("/api/v1/gaps/history")

    assert response.status_code == 200
    body = response.json()
    assert any(gap["gap_id"] == gap_id for gap in body["gaps"])


def test_semantic_scholar_client_parses_live_response_shape() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["fields"] == "paperId,title,abstract,year,url"
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "paperId": "abc123",
                        "title": "Robust RAG Evaluation",
                        "abstract": "Benchmarks expose cross-domain failures.",
                        "year": 2025,
                    }
                ]
            },
        )

    client = SemanticScholarClient(transport=httpx.MockTransport(handler))

    papers, warnings = asyncio.run(client.search("rag robustness", limit=1))

    assert warnings == []
    assert papers[0].paper_id == "semantic-abc123"
    assert papers[0].title == "Robust RAG Evaluation"
    assert papers[0].abstract == "Benchmarks expose cross-domain failures."
    assert papers[0].year == 2025


def test_arxiv_client_parses_atom_response_shape() -> None:
    atom = """<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <id>http://arxiv.org/abs/2501.00001v1</id>
        <title>RAG Robustness Under Shift</title>
        <summary>We study retrieval robustness under domain shift.</summary>
        <published>2025-01-02T00:00:00Z</published>
      </entry>
    </feed>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["search_query"] == "all:rag robustness"
        return httpx.Response(200, text=atom)

    client = ArxivSearchClient(transport=httpx.MockTransport(handler))

    papers, warnings = asyncio.run(client.search("rag robustness", limit=1))

    assert warnings == []
    assert papers[0].paper_id == "arxiv-2501.00001"
    assert papers[0].title == "RAG Robustness Under Shift"
    assert papers[0].abstract == "We study retrieval robustness under domain shift."
    assert papers[0].year == 2025


def test_gap_analysis_repairs_fenced_json_and_normalizes_values(monkeypatch, tmp_path) -> None:
    class FencedJsonProvider:
        async def generate(self, prompt: str, model: str | None = None) -> tuple[str, list[str]]:
            payload = {
                "gaps": [
                    {
                        "title": "Missing longitudinal evaluation",
                        "value_level": "HIGH",
                        "description": "Current work lacks long-running deployment evidence.",
                        "evidence_papers": [],
                    }
                ]
            }
            return f"Here is the analysis:\n```json\n{json.dumps(payload)}\n```", ["used test provider"]

    monkeypatch.setattr(gap_chain, "get_chat_provider", lambda settings, provider=None: FencedJsonProvider())

    response = asyncio.run(
        gap_chain.analyze_research_gaps(
            GapAnalysisRequest(topic="rag robustness", doc_ids=[]),
            Settings(sqlite_url=f"sqlite:///{tmp_path / 'gap.db'}"),
        )
    )

    assert response.gaps[0].value_level == "high"
    assert response.gaps[0].evidence_papers
    assert "used test provider" in response.warnings
