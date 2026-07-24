from uuid import uuid4

from fastapi import APIRouter, File, UploadFile

from backend.core.config import get_settings
from backend.core.errors import ApiError
from backend.models.schemas import PaperChunk, PaperListResponse, PaperUploadResponse
from backend.rag.embedder import get_embedding_provider
from backend.repositories.sqlite_store import SQLiteStore
from backend.services.pdf_parser import PdfParser
from backend.services.vector_index import get_vector_index_manager

router = APIRouter(prefix="/papers", tags=["papers"])


@router.get("", response_model=PaperListResponse)
async def list_papers() -> PaperListResponse:
    """Return stored papers available for follow-up analysis."""
    settings = get_settings()
    return PaperListResponse(papers=SQLiteStore(settings.sqlite_path).list_papers())


@router.post("/upload", response_model=PaperUploadResponse)
async def upload_paper(file: UploadFile = File(...)) -> PaperUploadResponse:
    """Upload a PDF, parse it into chunks, persist metadata, and index vectors."""
    if not file.filename:
        raise ApiError("PDF filename is required.")
    content = await file.read()
    if not content:
        raise ApiError("Uploaded PDF is empty.")
    settings = get_settings()
    doc_id = str(uuid4())
    parsed_chunks = PdfParser().parse(content, file.filename)
    chunks = [PaperChunk(chunk_id=item.chunk_id, doc_id=doc_id, page=item.page, text=item.text) for item in parsed_chunks]
    document_embedding_model = "para" if settings.default_embedding_provider == "xfyun-spark" else None
    result = await get_embedding_provider(settings, model=document_embedding_model).embed([chunk.text for chunk in chunks])
    if result.is_fallback and settings.default_embedding_provider != "mock":
        raise ApiError("Embedding provider is unavailable; fallback vectors were not indexed.", 503)
    manager = get_vector_index_manager()
    if result.profile != manager.profile:
        raise ApiError(
            f"Embedding profile mismatch: configured {manager.profile.key}, received {result.profile.key}.",
            409,
        )
    SQLiteStore(settings.sqlite_path).add_paper(doc_id, file.filename, chunks)
    manager.add_chunks(chunks, result.vectors)
    return PaperUploadResponse(doc_id=doc_id, title=file.filename, chunk_count=len(chunks), warnings=result.warnings)
