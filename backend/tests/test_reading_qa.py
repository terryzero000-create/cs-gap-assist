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


def test_reading_qa_answer_uses_numbered_source_citations() -> None:
    client = TestClient(app)
    upload = client.post(
        "/api/v1/papers/upload",
        files={"file": ("citations.pdf", b"Cited evidence helps readers verify generated answers.", "application/pdf")},
    )
    doc_id = upload.json()["doc_id"]

    response = client.post(
        "/api/v1/reading/qa",
        json={"question": "Why are citations useful?", "doc_ids": [doc_id], "top_k": 1},
    )

    assert response.status_code == 200
    body = response.json()
    assert "[1]" in body["answer"]
    assert len(body["sources"]) == 1


def test_reading_qa_reports_insufficient_evidence_without_sources() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/v1/reading/qa",
        json={"question": "What does the missing paper say?", "doc_ids": ["missing-doc"], "top_k": 3},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["sources"] == []
    assert "证据不足" in body["answer"]
    assert "[1]" not in body["answer"]


def test_reading_qa_rejects_empty_question_and_doc_ids() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/v1/reading/qa",
        json={"question": "   ", "doc_ids": [], "top_k": 3},
    )

    assert response.status_code == 400
    body = response.json()
    assert body["code"] == 400
    assert "error" in body


def test_reading_qa_rejects_invalid_top_k() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/v1/reading/qa",
        json={"question": "What changed?", "doc_ids": ["doc-1"], "top_k": 0},
    )

    assert response.status_code == 400
    body = response.json()
    assert body["code"] == 400
    assert "error" in body
