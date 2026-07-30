from uuid import uuid4

from fastapi import APIRouter, File, Response, UploadFile

from backend.core.config import get_settings
from backend.core.errors import ApiError
from backend.models.schemas import PaperChunk, PaperListResponse, PaperUploadResponse
from backend.rag.embedder import get_embedding_provider
from backend.repositories.sqlite_store import SQLiteStore
from backend.services.pdf_parser import PdfParser, PdfValidationError
from backend.services.vector_index import get_vector_index_manager

router = APIRouter(prefix="/papers", tags=["papers"])


@router.get("", response_model=PaperListResponse)
async def list_papers() -> PaperListResponse:
    """Return stored papers available for follow-up analysis."""
    settings = get_settings()
    return PaperListResponse(papers=SQLiteStore(settings.sqlite_path).list_papers())


@router.post("/upload", response_model=PaperUploadResponse)
async def upload_paper(response: Response, file: UploadFile = File(...)) -> PaperUploadResponse:
    """Deprecated synchronous upload path for small, text-extractable PDFs."""
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
    settings = get_settings()
    content = await _read_limited_upload(
        file,
        settings.legacy_sync_max_pdf_bytes,
    )
    if not content:
        raise ApiError("Uploaded PDF is empty.", error_code="EMPTY_UPLOAD")
    doc_id = str(uuid4())
    revision_id = str(uuid4())
    parser = PdfParser(
        max_pages=settings.legacy_sync_max_pdf_pages,
        max_payload_bytes=settings.xfyun_max_text_bytes,
        enable_ocr=False,
    )
    try:
        parsed_chunks = parser.parse(
            content,
            file.filename,
            doc_id=doc_id,
            revision_id=revision_id,
            allow_text_fallback=settings.app_env == "test",
        )
    except PdfValidationError as exc:
        if exc.error_code == "OCR_REQUIRED":
            raise ApiError(
                "Use POST /api/v1/paper-uploads for PDFs that require OCR.",
                409,
                error_code="ASYNC_UPLOAD_REQUIRED",
            ) from exc
        raise ApiError(
            str(exc),
            400,
            error_code=exc.error_code,
            retryable=exc.retryable,
        ) from exc
    chunks = [
        PaperChunk(
            chunk_id=item.chunk_id,
            doc_id=doc_id,
            revision_id=None,
            page=item.page,
            page_end=item.page_end,
            ordinal=item.ordinal,
            text=item.text,
            section_path=item.section_path,
            char_start=item.char_start,
            char_end=item.char_end,
            block_type=item.block_type,
            chunker_version=item.chunker_version,
            content_hash=item.content_hash,
            injection_flagged=item.injection_flagged,
        )
        for item in parsed_chunks
    ]
    document_embedding_model = "para" if settings.default_embedding_provider == "xfyun-spark" else None
    result = await get_embedding_provider(settings, model=document_embedding_model).embed([chunk.text for chunk in chunks])
    if result.is_fallback and settings.default_embedding_provider != "mock":
        raise ApiError(
            "Embedding provider is unavailable; no vectors were indexed.",
            503,
            error_code="EMBEDDING_UNAVAILABLE",
            retryable=True,
        )
    manager = get_vector_index_manager()
    if result.profile != manager.profile:
        raise ApiError(
            f"Embedding profile mismatch: configured {manager.profile.key}, received {result.profile.key}.",
            409,
            error_code="EMBEDDING_PROFILE_MISMATCH",
        )
    SQLiteStore(settings.sqlite_path).add_paper(doc_id, file.filename, chunks)
    manager.add_chunks(chunks, result.vectors)
    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = "Wed, 30 Sep 2026 00:00:00 GMT"
    response.headers["Link"] = '</api/v1/paper-uploads>; rel="successor-version"'
    return PaperUploadResponse(doc_id=doc_id, title=file.filename, chunk_count=len(chunks), warnings=result.warnings)


async def _read_limited_upload(file: UploadFile, max_bytes: int) -> bytes:
    """Read only the bounded legacy payload; larger inputs must use async upload."""
    content = bytearray()
    while True:
        chunk = await file.read(min(1024 * 1024, max_bytes + 1))
        if not chunk:
            break
        content.extend(chunk)
        if len(content) > max_bytes:
            raise ApiError(
                "Use POST /api/v1/paper-uploads for PDFs larger than the synchronous compatibility limit.",
                409,
                error_code="ASYNC_UPLOAD_REQUIRED",
            )
    return bytes(content)
