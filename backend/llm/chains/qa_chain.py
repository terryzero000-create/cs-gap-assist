from backend.core.config import Settings
from backend.llm.llm_service import ChatProviderUnavailable, get_chat_provider
from backend.models.schemas import ReadingQARequest, ReadingQAResponse, SourceParagraph
from backend.services.evidence_retriever import EvidenceRetriever


async def answer_question(request: ReadingQARequest, settings: Settings) -> ReadingQAResponse:
    """Answer a paper-reading question with paragraph-level citations."""
    selected = request.runtime_model_config
    retrieval_warnings: list[str] = []
    if selected and (
        (selected.embedding_provider and selected.embedding_provider != settings.default_embedding_provider)
        or (selected.embedding_model and selected.embedding_model != settings.default_embedding_model)
    ):
        retrieval_warnings.append("Runtime embedding override was ignored to preserve index compatibility.")
    retrieval = await EvidenceRetriever(settings).retrieve(request.question, request.doc_ids, request.top_k)
    retrieval_warnings.extend(retrieval.warnings)
    sources = [
        SourceParagraph(
            doc_id=chunk.doc_id,
            chunk_id=chunk.chunk_id,
            page=chunk.page,
            text=chunk.text,
            score=chunk.score or 0.0,
        )
        for chunk in retrieval.chunks
    ]
    if not sources:
        return ReadingQAResponse(
            answer="证据不足：未在已上传论文中检索到达到相关性门槛的片段。",
            sources=[],
            evidence_status="insufficient_evidence",
            warnings=retrieval_warnings,
        )

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
    try:
        chat_provider = get_chat_provider(settings, selected.chat_provider if selected else None)
        answer, chat_warnings = await chat_provider.generate(prompt, selected.chat_model if selected else None)
    except ChatProviderUnavailable as exc:
        return ReadingQAResponse(
            answer="生成模型不可用：已保留达到相关性门槛的来源片段，但未生成研究结论。",
            sources=sources,
            evidence_status="provider_unavailable",
            warnings=[*retrieval_warnings, str(exc)],
        )
    status = "synthetic" if bool(getattr(chat_provider, "is_synthetic", False)) else "local_only"
    return ReadingQAResponse(
        answer=answer,
        sources=sources,
        evidence_status=status,
        warnings=[*retrieval_warnings, *chat_warnings],
    )
