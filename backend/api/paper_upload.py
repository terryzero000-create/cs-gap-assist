from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, Form, Header, UploadFile, status

from backend.core.config import get_settings
from backend.core.errors import ApiError
from backend.models.schemas import PaperUploadTaskResponse
from backend.repositories.sqlite_store import get_sqlite_store, paper_operation_lock
from backend.services.paper_ingestion import (
    get_ingestion_worker,
    persist_upload_file,
    upload_response,
)


router = APIRouter(prefix="/paper-uploads", tags=["paper-uploads"])


@router.post("", response_model=PaperUploadTaskResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_paper_upload(
    file: UploadFile = File(...),
    replace_doc_id: str | None = Form(default=None),
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=128),
) -> PaperUploadTaskResponse:
    """Persist a source PDF and queue an idempotent ingestion revision."""
    settings = get_settings()
    if not file.filename:
        raise ApiError("PDF filename is required.", error_code="PDF_FILENAME_REQUIRED")
    if len(file.filename) > 255:
        raise ApiError("PDF filename is too long.", error_code="PDF_FILENAME_TOO_LONG")
    if file.content_type not in {"application/pdf", "application/octet-stream", None, ""}:
        raise ApiError(
            f"Unsupported content type: {file.content_type}.",
            415,
            error_code="INVALID_PDF_CONTENT_TYPE",
        )
    store = get_sqlite_store(settings.sqlite_path)
    existing_paper = store.get_paper(replace_doc_id) if replace_doc_id else None
    if replace_doc_id and (
        existing_paper is None
        or existing_paper.ingestion_status not in {"ready", "reupload_required"}
    ):
        raise ApiError(
            f"Paper not found: {replace_doc_id}",
            404,
            error_code="PAPER_NOT_FOUND",
        )
    doc_id = replace_doc_id or str(uuid4())
    revision_id = str(uuid4())
    upload_id = str(uuid4())
    source_path = settings.documents_path / doc_id / f"{revision_id}.pdf"
    digest, size = await persist_upload_file(
        source=file,
        destination=source_path,
        max_bytes=settings.max_pdf_bytes,
    )
    created: dict[str, object] | None = None
    try:
        # Re-check after waiting: deletion may have won the per-document lock
        # while this replacement file was being streamed to disk.
        with paper_operation_lock(doc_id):
            if replace_doc_id:
                current_paper = store.get_paper(doc_id)
                if current_paper is None or current_paper.ingestion_status not in {"ready", "reupload_required"}:
                    raise ApiError(
                        f"Paper not found: {replace_doc_id}",
                        404,
                        error_code="PAPER_NOT_FOUND",
                    )
            created = store.create_upload(
                upload_id=upload_id,
                idempotency_key=idempotency_key,
                doc_id=doc_id,
                revision_id=revision_id,
                title=file.filename,
                content_sha256=digest,
                source_path=str(source_path),
                mime_type=file.content_type or "application/pdf",
                size_bytes=size,
            )
    except ValueError as exc:
        if created is None:
            source_path.unlink(missing_ok=True)
        if str(exc) == "IDEMPOTENCY_KEY_REUSED":
            raise ApiError(
                "Idempotency-Key was already used with different file content.",
                409,
                error_code="IDEMPOTENCY_KEY_REUSED",
            ) from exc
        raise
    except Exception:
        if created is None:
            source_path.unlink(missing_ok=True)
        raise
    assert created is not None
    if str(created["upload_id"]) != upload_id:
        source_path.unlink(missing_ok=True)
    await get_ingestion_worker(settings).enqueue(str(created["upload_id"]))
    record = store.get_upload(str(created["upload_id"]))
    assert record is not None
    return upload_response(record, settings.api_prefix)


@router.get("/{upload_id}", response_model=PaperUploadTaskResponse)
async def get_paper_upload(upload_id: str) -> PaperUploadTaskResponse:
    """Return the durable state of one ingestion task."""
    settings = get_settings()
    record = get_sqlite_store(settings.sqlite_path).get_upload(upload_id)
    if record is None:
        raise ApiError("Upload not found.", 404, error_code="UPLOAD_NOT_FOUND")
    return upload_response(record, settings.api_prefix)


@router.post("/{upload_id}/retry", response_model=PaperUploadTaskResponse, status_code=status.HTTP_202_ACCEPTED)
async def retry_paper_upload(upload_id: str) -> PaperUploadTaskResponse:
    """Retry a failed upload only when the stored error is retryable."""
    settings = get_settings()
    store = get_sqlite_store(settings.sqlite_path)
    try:
        store.reset_upload_for_retry(upload_id)
    except KeyError as exc:
        raise ApiError("Upload not found.", 404, error_code="UPLOAD_NOT_FOUND") from exc
    except ValueError as exc:
        raise ApiError(
            "Upload is not retryable.",
            409,
            error_code="UPLOAD_NOT_RETRYABLE",
        ) from exc
    await get_ingestion_worker(settings).enqueue(upload_id)
    record = store.get_upload(upload_id)
    assert record is not None
    return upload_response(record, settings.api_prefix)
