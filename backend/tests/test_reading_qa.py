from fastapi.testclient import TestClient

from backend.main import app


def test_reading_qa_returns_answer_with_sources() -> None:
    client = TestClient(app)
    upload = client.post(
        "/api/v1/papers/upload",
        files={"file": ("rag.pdf", b"Retrieval augmented generation improves grounded question answering.", "application/pdf")},
    )
    doc_id = upload.json()["doc_id"]

    response = client.post(
        "/api/v1/reading/qa",
        json={"question": "What does RAG improve?", "doc_ids": [doc_id], "top_k": 3},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer"]
    assert body["sources"]
    assert body["sources"][0]["doc_id"] == doc_id
    assert body["sources"][0]["chunk_id"]
    assert body["sources"][0]["page"] >= 1
    assert body["sources"][0]["score"] >= 0
