import asyncio

from fastapi.testclient import TestClient

from backend.main import app
from backend.services.citation_graph import CitationGraphService, ExternalCitationPaper, OpenAlexCitationClient


def test_citation_graph_returns_d3_nodes_and_links() -> None:
    client = TestClient(app)

    response = client.get("/api/v1/citations/graph", params={"keyword": "retrieval augmented generation", "max_nodes": 5})

    assert response.status_code == 200
    body = response.json()
    assert body["nodes"]
    assert body["links"]
    assert body["nodes"][0]["id"]
    assert body["nodes"][0]["importance_score"] >= 0
    assert any(node["is_key"] for node in body["nodes"])
    assert {"source", "target", "relation"}.issubset(body["links"][0].keys())


def test_citation_graph_caps_nodes_and_keeps_valid_links() -> None:
    client = TestClient(app)

    response = client.get("/api/v1/citations/graph", params={"keyword": "retrieval augmented generation", "max_nodes": 3})

    assert response.status_code == 200
    body = response.json()
    node_ids = {node["id"] for node in body["nodes"]}
    assert len(body["nodes"]) == 3
    assert all(link["source"] in node_ids and link["target"] in node_ids for link in body["links"])


def test_openalex_citation_papers_are_ranked_and_capped() -> None:
    papers = [
        ExternalCitationPaper(
            paper_id="W1",
            title="Retrieval Augmented Generation",
            year=2020,
            citation_count=100,
            influential_citation_count=12,
            references=[
                ExternalCitationPaper(
                    paper_id="W2",
                    title="Early Neural Retrieval",
                    year=2018,
                    citation_count=60,
                    influential_citation_count=8,
                )
            ],
            citations=[
                ExternalCitationPaper(
                    paper_id="W3",
                    title="Agentic RAG Systems",
                    year=2024,
                    citation_count=30,
                    influential_citation_count=6,
                )
            ],
        ),
        ExternalCitationPaper(
            paper_id="W4",
            title="RAG Survey",
            year=2023,
            citation_count=70,
            influential_citation_count=5,
        ),
        ExternalCitationPaper(
            paper_id="W5",
            title="Overflow Node",
            year=2025,
            citation_count=1,
            influential_citation_count=0,
        ),
    ]

    class FakeOpenAlexClient:
        async def search(self, keyword: str, limit: int) -> tuple[list[ExternalCitationPaper], list[str]]:
            return papers[:limit], ["OpenAlex fake client used."]

    service = CitationGraphService(citation_client=FakeOpenAlexClient())

    graph = asyncio.run(service.build_graph("retrieval augmented generation", max_nodes=3, use_openalex=True))

    node_ids = {node.id for node in graph.nodes}
    assert len(graph.nodes) == 3
    assert graph.nodes[0].id == "openalex-W1"
    assert graph.nodes[0].importance_score == 1.0
    assert graph.nodes[0].is_key is True
    assert "openalex-W5" not in node_ids
    assert all(link.source in node_ids and link.target in node_ids for link in graph.links)
    assert graph.warnings == ["OpenAlex fake client used."]


def test_openalex_client_requires_api_key() -> None:
    client = OpenAlexCitationClient(api_key=None)

    papers, warnings = asyncio.run(client.search("retrieval augmented generation", limit=3))

    assert papers == []
    assert warnings == ["OPENALEX_API_KEY missing; using deterministic citation graph data."]
