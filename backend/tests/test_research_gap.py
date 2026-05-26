from fastapi.testclient import TestClient

from backend.main import app


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
