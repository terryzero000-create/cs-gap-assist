from fastapi.testclient import TestClient

from backend.main import app


def test_citation_graph_returns_d3_nodes_and_links() -> None:
    client = TestClient(app)

    response = client.get("/api/v1/citations/graph", params={"keyword": "retrieval augmented generation"})

    assert response.status_code == 200
    body = response.json()
    assert body["nodes"]
    assert body["links"]
    assert body["nodes"][0]["id"]
    assert body["nodes"][0]["importance_score"] >= 0
    assert any(node["is_key"] for node in body["nodes"])
    assert {"source", "target", "relation"}.issubset(body["links"][0].keys())
