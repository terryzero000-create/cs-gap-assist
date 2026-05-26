from backend.core.config import Settings
from backend.llm.llm_service import get_chat_provider
from backend.models.schemas import ReadingQARequest, ReadingQAResponse, SourceParagraph
from backend.rag.embedder import get_embedding_provider
from backend.rag.vector_store import vector_store


async def answer_question(request: ReadingQARequest, settings: Settings) -> ReadingQAResponse:
    """Answer a paper-reading question with paragraph-level citations."""
    selected = request.runtime_model_config
    embedding_provider = get_embedding_provider(
        settings,
        selected.embedding_provider if selected else None,
        selected.embedding_model if selected else None,
    )
    query_vectors, embedding_warnings = await embedding_provider.embed([request.question])
    chunks = vector_store.search(query_vectors[0], doc_ids=request.doc_ids, top_k=request.top_k)
    sources = [
        SourceParagraph(
            doc_id=chunk.doc_id,
            chunk_id=chunk.chunk_id,
            page=chunk.page,
            text=chunk.text,
            score=chunk.score or 0.0,
        )
        for chunk in chunks
    ]
    context = "\n\n".join(f"[{source.chunk_id} p.{source.page}] {source.text}" for source in sources)
    prompt = f"请基于以下论文段落回答问题，并保持中文简洁。\n问题：{request.question}\n段落：\n{context}"
    chat_provider = get_chat_provider(settings, selected.chat_provider if selected else None)
    answer, chat_warnings = await chat_provider.generate(prompt, selected.chat_model if selected else None)
    return ReadingQAResponse(answer=answer, sources=sources, warnings=[*embedding_warnings, *chat_warnings])
