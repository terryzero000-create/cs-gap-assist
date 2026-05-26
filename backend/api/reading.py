from fastapi import APIRouter

from backend.core.config import get_settings
from backend.models.schemas import ReadingQARequest, ReadingQAResponse
from backend.llm.chains.qa_chain import answer_question

router = APIRouter(prefix="/reading", tags=["reading"])


@router.post("/qa", response_model=ReadingQAResponse)
async def reading_qa(request: ReadingQARequest) -> ReadingQAResponse:
    """Answer a question over uploaded papers using retrieved source paragraphs."""
    return await answer_question(request, get_settings())
