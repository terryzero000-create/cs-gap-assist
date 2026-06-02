from uuid import uuid4

from fastapi import APIRouter, File, UploadFile

from backend.core.config import get_settings
from backend.core.errors import ApiError
from backend.models.schemas import PaperChunk, PaperListResponse, PaperUploadResponse
from backend.rag.embedder import get_embedding_provider
from backend.rag.vector_store import vector_store
from backend.repositories.sqlite_store import SQLiteStore
from backend.services.pdf_parser import PdfParser

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
    embeddings, warnings = await get_embedding_provider(settings).embed([chunk.text for chunk in chunks])
    vector_store.add_chunks(chunks, embeddings)
    SQLiteStore(settings.sqlite_path).add_paper(doc_id, file.filename, chunks)
    return PaperUploadResponse(doc_id=doc_id, title=file.filename, chunk_count=len(chunks), warnings=warnings)
