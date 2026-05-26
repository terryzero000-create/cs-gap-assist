from fastapi import APIRouter

from backend.core.config import get_settings
from backend.models.schemas import KnowledgeSearchResponse, NoteCreateRequest, NoteRecord, PaperRecord
from backend.rag.vector_store import vector_store
from backend.repositories.sqlite_store import SQLiteStore

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.get("/papers", response_model=list[PaperRecord])
async def list_knowledge_papers() -> list[PaperRecord]:
    """List papers stored in the personal knowledge base."""
    return SQLiteStore(get_settings().sqlite_path).list_papers()


@router.post("/notes", response_model=NoteRecord)
async def create_note(request: NoteCreateRequest) -> NoteRecord:
    """Create a tagged note in the personal knowledge base."""
    return SQLiteStore(get_settings().sqlite_path).add_note(request)


@router.get("/notes", response_model=list[NoteRecord])
async def list_notes(query: str | None = None) -> list[NoteRecord]:
    """List notes, optionally filtered by text query."""
    return SQLiteStore(get_settings().sqlite_path).list_notes(query)


@router.get("/search", response_model=KnowledgeSearchResponse)
async def search_knowledge(query: str) -> KnowledgeSearchResponse:
    """Search papers, notes, and indexed chunks from the personal knowledge base."""
    store = SQLiteStore(get_settings().sqlite_path)
    papers = [paper for paper in store.list_papers() if query.lower() in paper.title.lower()] or store.list_papers()
    notes = store.list_notes(query)
    chunks = [chunk for chunk in vector_store.all_chunks() if query.lower() in chunk.text.lower()]
    if not chunks:
        chunks = vector_store.all_chunks()[:5]
    return KnowledgeSearchResponse(papers=papers, notes=notes, chunks=chunks)
