from backend.core.config import Settings
from backend.llm.llm_service import get_chat_provider
from backend.models.schemas import ReadingQARequest, ReadingQAResponse, SourceParagraph
from backend.repositories.sqlite_store import SQLiteStore
from backend.services.vector_index import (
    configured_embedding_provider,
    get_vector_index_manager,
    lexical_chunk_search,
)


async def answer_question(request: ReadingQARequest, settings: Settings) -> ReadingQAResponse:
    """Answer a paper-reading question with paragraph-level citations."""
    selected = request.runtime_model_config
    embedding_warnings: list[str] = []
    if selected and (
        (selected.embedding_provider and selected.embedding_provider != settings.default_embedding_provider)
        or (selected.embedding_model and selected.embedding_model != settings.default_embedding_model)
    ):
        embedding_warnings.append("Runtime embedding override was ignored to preserve index compatibility.")
    embedding_result = await configured_embedding_provider(settings).embed([request.question])
    embedding_warnings.extend(embedding_result.warnings)
    stored_chunks = SQLiteStore(settings.sqlite_path).list_chunks(request.doc_ids)
    if embedding_result.is_fallback and settings.default_embedding_provider != "mock":
        chunks = lexical_chunk_search(stored_chunks, request.question, request.top_k)
        embedding_warnings.append("Semantic retrieval was unavailable; SQLite lexical fallback was used.")
    else:
        try:
            chunks = get_vector_index_manager().search(
                embedding_result.vectors[0], doc_ids=request.doc_ids, top_k=request.top_k
            )
        except Exception as exc:
            chunks = lexical_chunk_search(stored_chunks, request.question, request.top_k)
            embedding_warnings.append(f"Vector index was unavailable ({exc}); SQLite lexical fallback was used.")
        if not chunks and stored_chunks:
            chunks = lexical_chunk_search(stored_chunks, request.question, request.top_k)
            embedding_warnings.append("Active vector index had no matching chunks; SQLite lexical fallback was used.")
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
        return ReadingQAResponse(answer="证据不足：未在已上传论文中检索到可用于回答该问题的片段。", sources=[], warnings=embedding_warnings)

    context = "\n\n".join(
        f"[{index}] page {source.page}, chunk {source.chunk_id}: {source.text}"
        for index, source in enumerate(sources, start=1)
    )
    prompt = (
        "READING_QA\n"
        "请只基于给定论文片段回答问题。无论论文原文是什么语言，最终回答必须使用简体中文。"
        "专业术语可以保留英文，并在必要时附上中文解释。"
        "请在每个关键结论后标注来源编号，例如 [1] 或 [1][2]。"
        "如果片段不足以回答，请直接说明“证据不足”。\n\n"
        f"问题：{request.question}\n\n"
        f"来源片段：\n{context}"
    )
    chat_provider = get_chat_provider(settings, selected.chat_provider if selected else None)
    answer, chat_warnings = await chat_provider.generate(prompt, selected.chat_model if selected else None)
    return ReadingQAResponse(answer=answer, sources=sources, warnings=[*embedding_warnings, *chat_warnings])
