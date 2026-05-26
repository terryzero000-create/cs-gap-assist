import json

from backend.core.config import Settings
from backend.llm.llm_service import get_chat_provider
from backend.models.schemas import GapAnalysisRequest, GapAnalysisResponse, GapItem
from backend.rag.vector_store import vector_store
from backend.repositories.sqlite_store import SQLiteStore
from backend.services.arxiv_search import ArxivSearchClient
from backend.services.semantic_scholar import SemanticScholarClient


async def analyze_research_gaps(request: GapAnalysisRequest, settings: Settings) -> GapAnalysisResponse:
    """Analyze research gaps from local papers and external literature evidence."""
    semantic_papers, semantic_warnings = await SemanticScholarClient().search(request.topic, limit=3)
    arxiv_papers, arxiv_warnings = await ArxivSearchClient().search(request.topic, limit=2)
    local_context = "\n".join(chunk.text for chunk in vector_store.all_chunks(request.doc_ids)[:5])
    external_context = "\n".join(f"{paper.paper_id}: {paper.title}. {paper.abstract}" for paper in [*semantic_papers, *arxiv_papers])
    prompt = f"GAP_JSON\n研究方向：{request.topic}\n已读论文：{local_context}\n外部文献：{external_context}"
    selected = request.runtime_model_config
    provider = get_chat_provider(settings, selected.chat_provider if selected else None)
    raw_text, chat_warnings = await provider.generate(prompt, selected.chat_model if selected else None)
    payload = json.loads(raw_text)
    gaps = [
        GapItem(
            title=item["title"],
            value_level=item["value_level"],
            description=item["description"],
            evidence_papers=item["evidence_papers"],
        )
        for item in payload.get("gaps", [])
    ]
    store = SQLiteStore(settings.sqlite_path)
    for gap in gaps:
        store.save_gap(gap)
    return GapAnalysisResponse(gaps=gaps, warnings=[*semantic_warnings, *arxiv_warnings, *chat_warnings])
