from fastapi.testclient import TestClient

from backend.main import app


def test_health_check_returns_ok() -> None:
    client = TestClient(app)

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_missing_model_key_uses_mock_provider() -> None:
    client = TestClient(app)

    response = client.get("/api/v1/config/models")

    assert response.status_code == 200
    body = response.json()
    assert body["default_chat_model"] == "deepseek-v4-pro"
    assert body["providers"]["chat"][0]["provider"] == "deepseek"
    assert "mock" in {item["provider"] for item in body["providers"]["chat"]}


def test_pdf_upload_returns_doc_id_and_chunks(tmp_path) -> None:
    client = TestClient(app)
    sample = b"Title: Test Paper\nThis paper studies retrieval augmented generation.\nIt has a method section."

    response = client.post(
        "/api/v1/papers/upload",
        files={"file": ("paper.pdf", sample, "application/pdf")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["doc_id"]
    assert body["chunk_count"] >= 1
    assert body["title"] == "paper.pdf"


def test_paper_list_returns_uploaded_papers() -> None:
    client = TestClient(app)
    upload = client.post(
        "/api/v1/papers/upload",
        files={"file": ("listed.pdf", b"Listed paper content for gap analysis.", "application/pdf")},
    )
    doc_id = upload.json()["doc_id"]

    response = client.get("/api/v1/papers")

    assert response.status_code == 200
    body = response.json()
    assert any(paper["doc_id"] == doc_id and paper["title"] == "listed.pdf" for paper in body["papers"])


def test_uniform_error_shape_for_bad_upload() -> None:
    client = TestClient(app)

    response = client.post("/api/v1/papers/upload")

    assert response.status_code == 400
    assert response.json()["code"] == 400
    assert "error" in response.json()
