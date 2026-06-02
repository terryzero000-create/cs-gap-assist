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
    if not sources:
        return ReadingQAResponse(answer="证据不足：未在已上传论文中检索到可用于回答该问题的段落。", sources=[], warnings=embedding_warnings)

    context = "\n\n".join(
        f"[{index}] page {source.page}, chunk {source.chunk_id}: {source.text}"
        for index, source in enumerate(sources, start=1)
    )
    prompt = (
        "READING_QA\n"
        "请只基于给定论文段落回答问题。答案使用简洁中文，并在每个关键结论后标注来源编号，"
        "例如 [1] 或 [1][2]。如果段落不足以回答，请直接说明证据不足。\n\n"
        f"问题：{request.question}\n\n"
        f"来源段落：\n{context}"
    )
    chat_provider = get_chat_provider(settings, selected.chat_provider if selected else None)
    answer, chat_warnings = await chat_provider.generate(prompt, selected.chat_model if selected else None)
    return ReadingQAResponse(answer=answer, sources=sources, warnings=[*embedding_warnings, *chat_warnings])
