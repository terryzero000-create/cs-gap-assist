from fastapi.testclient import TestClient

from backend.main import app


def test_knowledge_base_lists_papers_and_manages_notes() -> None:
    client = TestClient(app)
    upload = client.post(
        "/api/v1/papers/upload",
        files={"file": ("knowledge.pdf", b"Knowledge bases store notes, tags, and research history.", "application/pdf")},
    )
    doc_id = upload.json()["doc_id"]

    papers = client.get("/api/v1/knowledge/papers")
    assert papers.status_code == 200
    assert any(paper["doc_id"] == doc_id for paper in papers.json())

    note = client.post(
        "/api/v1/knowledge/notes",
        json={"title": "RAG note", "content": "Track robustness gaps", "tags": ["rag"], "related_doc_id": doc_id},
    )
    assert note.status_code == 200
    assert note.json()["note_id"]

    search = client.get("/api/v1/knowledge/search", params={"query": "robustness"})
    assert search.status_code == 200
    body = search.json()
    assert body["papers"]
    assert body["notes"]
    assert body["chunks"]
