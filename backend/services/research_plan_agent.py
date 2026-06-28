from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from backend.core.config import Settings
from backend.llm.chains.experiment_chain import suggest_experiments
from backend.llm.chains.gap_chain import analyze_research_gaps
from backend.models.schemas import (
    ExperimentPlan,
    ExperimentSuggestRequest,
    GapAnalysisRequest,
    GapItem,
    PaperChunk,
    ResearchPlanAgentRequest,
    ResearchPlanAgentResponse,
    ResearchPlanAgentStep,
    ResearchPlanCard,
)
from backend.rag.vector_store import vector_store
from backend.repositories.sqlite_store import SQLiteStore
from backend.services.arxiv_search import ArxivSearchClient


MAX_STEPS = 10


@dataclass
class ResearchPlanState:
    """Mutable state carried through the bounded planning agent."""

    request: ResearchPlanAgentRequest
    retrieved_context: list[PaperChunk] = field(default_factory=list)
    paper_summary: str = ""
    planned_tools: list[str] = field(default_factory=list)
    gaps: list[GapItem] = field(default_factory=list)
    top_gaps: list[GapItem] = field(default_factory=list)
    experiment_suggestions: list[ExperimentPlan] = field(default_factory=list)
    recommended_papers: list[str] = field(default_factory=list)
    agent_steps: list[ResearchPlanAgentStep] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    final_cards: list[ResearchPlanCard] = field(default_factory=list)


class ResearchPlanAgentService:
    """Small state-machine agent for research route planning."""

    def __init__(self, settings: Settings, store: SQLiteStore) -> None:
        self.settings = settings
        self.store = store
        self.tools: dict[str, Callable[[ResearchPlanState], Awaitable[str]]] = {
            "understand_goal": self.understand_goal,
            "plan_steps": self.plan_steps,
            "knowledge_search_tool": self.knowledge_search_tool,
            "paper_summary_tool": self.paper_summary_tool,
            "gap_analysis_tool": self.gap_analysis_tool,
            "select_top_3_gaps": self.select_top_3_gaps,
            "experiment_suggestion_tool": self.experiment_suggestion_tool,
            "paper_recommendation_tool": self.paper_recommendation_tool,
            "research_report_tool": self.research_report_tool,
        }

    async def run(self, request: ResearchPlanAgentRequest) -> ResearchPlanAgentResponse:
        """Run a bounded tool-calling loop and return trace plus cards."""
        state = ResearchPlanState(request=request)
        for _ in range(MAX_STEPS):
            tool_name = self.decide_next_tool(state)
            if tool_name == "done":
                break
            observation = await self.tools[tool_name](state)
            next_decision = self.decide_next_tool(state)
            state.agent_steps.append(
                ResearchPlanAgentStep(
                    step_index=len(state.agent_steps) + 1,
                    tool_name=tool_name,
                    thought=self._thought(tool_name, state),
                    observation=observation,
                    next_decision="Agent finished." if next_decision == "done" else f"Next call: {next_decision}.",
                )
            )
        if not state.final_cards:
            state.warnings.append("Agent reached max_steps before report generation; returning partial cards.")
            await self.research_report_tool(state)
        return ResearchPlanAgentResponse(agent_steps=state.agent_steps, final_cards=state.final_cards, warnings=state.warnings)

    def decide_next_tool(self, state: ResearchPlanState) -> str:
        """Choose the next tool from state, not from a blind fixed pipeline."""
        completed = {step.tool_name for step in state.agent_steps}
        if "understand_goal" not in completed:
            return "understand_goal"
        if not state.planned_tools:
            return "plan_steps"
        if not state.retrieved_context:
            return "knowledge_search_tool"
        if not state.paper_summary:
            return "paper_summary_tool"
        if not state.gaps:
            return "gap_analysis_tool"
        if not state.top_gaps:
            return "select_top_3_gaps"
        if not state.experiment_suggestions:
            return "experiment_suggestion_tool"
        if not state.recommended_papers:
            return "paper_recommendation_tool"
        if not state.final_cards:
            return "research_report_tool"
        return "done"

    async def understand_goal(self, state: ResearchPlanState) -> str:
        direction = state.request.research_direction.strip()
        if state.request.experiment_result:
            return f"Research direction parsed as '{direction}' with current experiment evidence included."
        return f"Research direction parsed as '{direction}' without current experiment evidence."

    async def plan_steps(self, state: ResearchPlanState) -> str:
        state.planned_tools = [
            "knowledge_search_tool",
            "paper_summary_tool",
            "gap_analysis_tool",
            "select_top_3_gaps",
            "experiment_suggestion_tool",
            "paper_recommendation_tool",
            "research_report_tool",
        ]
        return "Plan created: retrieve context, summarize papers, analyze gaps, suggest experiments, recommend papers, generate cards."

    async def knowledge_search_tool(self, state: ResearchPlanState) -> str:
        chunks = vector_store.all_chunks(doc_ids=state.request.selected_paper_ids)
        if not chunks:
            chunks = self.store.list_chunks(state.request.selected_paper_ids)
            state.warnings.append("Vector memory had no selected chunks; used SQLite chunk fallback.")
        state.retrieved_context = self._rank_chunks(chunks, state.request.research_direction)[:8]
        return f"Retrieved {len(state.retrieved_context)} context chunks from {len(state.request.selected_paper_ids)} selected paper(s)."

    async def paper_summary_tool(self, state: ResearchPlanState) -> str:
        snippets = [chunk.text.strip().replace("\n", " ")[:180] for chunk in state.retrieved_context[:3]]
        base = " ".join(snippets) if snippets else "No uploaded-paper context was available."
        state.paper_summary = f"已有研究主要围绕 {state.request.research_direction.strip()} 展开。证据片段：{base}"
        return f"Paper summary created from {len(snippets)} top chunk(s)."

    async def gap_analysis_tool(self, state: ResearchPlanState) -> str:
        response = await analyze_research_gaps(
            GapAnalysisRequest(
                topic=state.request.research_direction,
                doc_ids=state.request.selected_paper_ids,
                model_config=state.request.runtime_model_config,
            ),
            self.settings,
        )
        state.gaps = response.gaps
        state.warnings.extend(response.warnings)
        return f"Analyzed {len(state.gaps)} research gap(s)."

    async def select_top_3_gaps(self, state: ResearchPlanState) -> str:
        state.top_gaps = sorted(state.gaps, key=lambda gap: 0 if gap.value_level == "high" else 1)[:3]
        return f"Selected {len(state.top_gaps)} top gap(s), prioritizing high-value items."

    async def experiment_suggestion_tool(self, state: ResearchPlanState) -> str:
        plans: list[ExperimentPlan] = []
        for gap in state.top_gaps:
            topic = f"{gap.title}. {gap.description}"
            if state.request.experiment_result:
                topic = f"{topic}\nCurrent experiment result: {state.request.experiment_result}"
            response = await suggest_experiments(
                ExperimentSuggestRequest(
                    gap_id=gap.gap_id,
                    topic=topic,
                    model_config=state.request.runtime_model_config,
                ),
                self.settings,
            )
            plans.extend(response.experiments[:1])
            state.warnings.extend(response.warnings)
        state.experiment_suggestions = plans
        return f"Generated {len(plans)} experiment suggestion(s) for selected gaps."

    async def paper_recommendation_tool(self, state: ResearchPlanState) -> str:
        query = " ".join([state.request.research_direction, *[gap.title for gap in state.top_gaps]])
        papers, warnings = await ArxivSearchClient(timeout_seconds=self.settings.external_search_timeout_seconds).search(query, limit=5)
        state.warnings.extend(warnings)
        state.recommended_papers = [f"{paper.paper_id}: {paper.title}" for paper in papers]
        if not state.recommended_papers:
            fallback = [paper for gap in state.top_gaps for paper in gap.evidence_papers]
            fallback.extend(paper for plan in state.experiment_suggestions for paper in plan.support_papers)
            state.recommended_papers = list(dict.fromkeys(fallback))[:5]
            state.warnings.append("No new arXiv recommendations found; reused evidence and support papers.")
        return f"Recommended {len(state.recommended_papers)} follow-up paper(s)."

    async def research_report_tool(self, state: ResearchPlanState) -> str:
        cards: list[ResearchPlanCard] = []
        for gap in state.top_gaps:
            plan = next((item for item in state.experiment_suggestions if item.gap_id == gap.gap_id), None)
            cards.append(
                ResearchPlanCard(
                    title=f"{state.request.research_direction.strip()}：{gap.title}",
                    background=state.paper_summary,
                    research_gap=gap.description,
                    entry_point=self._entry_point(gap),
                    experiment_suggestion=self._experiment_text(plan),
                    recommended_papers=state.recommended_papers[:5] or gap.evidence_papers,
                    risks=plan.risks if plan else ["证据不足，需要先补充基线实验。"],
                    next_action=self._next_action(plan),
                )
            )
        state.final_cards = cards
        return f"Generated {len(cards)} research execution card(s)."

    def _rank_chunks(self, chunks: list[PaperChunk], direction: str) -> list[PaperChunk]:
        terms = {term.lower() for term in direction.split() if term.strip()}
        if not terms:
            return chunks
        return sorted(chunks, key=lambda chunk: sum(term in chunk.text.lower() for term in terms), reverse=True)

    def _entry_point(self, gap: GapItem) -> str:
        return f"从“{gap.title}”入手，先复现实有证据，再补齐 {gap.value_level} 价值缺口。"

    def _experiment_text(self, plan: ExperimentPlan | None) -> str:
        if plan is None:
            return "先定义公开数据集、基础指标和可复现实验脚本。"
        return f"{plan.objective} 数据集：{', '.join(plan.datasets)}；指标：{', '.join(plan.metrics)}。"

    def _next_action(self, plan: ExperimentPlan | None) -> str:
        if plan and plan.steps:
            return plan.steps[0]
        return "整理 selected papers 的方法和实验设置，形成第一个 baseline。"

    def _thought(self, tool_name: str, state: ResearchPlanState) -> str:
        thoughts = {
            "understand_goal": "先明确研究方向、已选论文和可选实验结果，避免后续工具跑偏。",
            "plan_steps": "目标已明确，需要制定有限步骤，保证 Agent 不无限循环。",
            "knowledge_search_tool": "需要从已上传论文中拿到可引用上下文，再分析路线。",
            "paper_summary_tool": "已有研究总结能约束 gap 和实验建议不要凭空生成。",
            "gap_analysis_tool": "路线规划的核心是找到有证据支撑的 Research Gap。",
            "select_top_3_gaps": "第一版只保留最多三个课题，减少不可执行的发散。",
            "experiment_suggestion_tool": "每个 Gap 需要落到数据集、指标、baseline 和步骤。",
            "paper_recommendation_tool": "需要给用户下一批阅读材料，补齐路线证据。",
            "research_report_tool": "把中间结果压缩成可执行课题卡。",
        }
        return thoughts[tool_name]
