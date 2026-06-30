from collections.abc import Callable
from dataclasses import dataclass, field
import re

from backend.models.schemas import (
    AgentStep,
    PaperChunk,
    PaperRecord,
    ReproductionAgentRequest,
    ReproductionAgentResponse,
    ReproductionReport,
    ToolObservation,
)
from backend.repositories.sqlite_store import SQLiteStore


NON_CLAIMS = [
    "这是辅助复现报告，不是自动完整复现。",
    "不运行代码；代码和仿真内容仅作为模板。",
    "不承诺达到论文指标。",
    "不得编造论文上下文没有提供的信息。",
]


@dataclass
class AgentState:
    """Mutable state carried across reproduction agent tool calls."""

    request: ReproductionAgentRequest
    paper: PaperRecord
    chunks: list[PaperChunk] = field(default_factory=list)
    steps: list[AgentStep] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    goal_understanding: str = ""
    reproduction_info: dict[str, list[str]] = field(default_factory=dict)
    formula_algorithm_notes: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    code_template: str = ""
    simulation_template: str = ""
    report: ReproductionReport | None = None


class ReproductionAgentService:
    """Tool-calling reproduction assistant with a small deterministic loop."""

    def __init__(self, store: SQLiteStore) -> None:
        """Create the service with persistent paper context access."""
        self.store = store
        self.tools: dict[str, Callable[[AgentState], ToolObservation]] = {
            "retrieve_paper_context": self.retrieve_paper_context,
            "extract_reproduction_info": self.extract_reproduction_info,
            "analyze_formula_algorithm": self.analyze_formula_algorithm,
            "assess_risks": self.assess_risks,
            "generate_code_skeleton": self.generate_code_skeleton,
            "generate_simulation_template": self.generate_simulation_template,
            "generate_report": self.generate_report,
        }

    async def run(self, request: ReproductionAgentRequest, paper: PaperRecord) -> ReproductionAgentResponse:
        """Run the bounded agent loop and return trace plus final report."""
        state = AgentState(request=request, paper=paper)
        for _ in range(8):
            tool_name = self.decide_next_tool(state)
            observation = self.tools[tool_name](state)
            state.warnings.extend(observation.warnings)
            completed = {step.tool_name for step in state.steps}
            next_tool = "complete" if state.report else self._next_tool_after(state, completed | {tool_name})
            state.steps.append(
                AgentStep(
                    step_index=len(state.steps) + 1,
                    tool_name=tool_name,
                    thought=self._thought(tool_name, state),
                    input_summary=self._input_summary(tool_name, state),
                    observation=observation,
                    next_decision=next_tool,
                )
            )
            if state.report:
                return ReproductionAgentResponse(agent_steps=state.steps, report=state.report, warnings=state.warnings)
        if state.report is None:
            self.generate_report(state)
        return ReproductionAgentResponse(agent_steps=state.steps, report=state.report, warnings=state.warnings)

    def decide_next_tool(self, state: AgentState) -> str:
        """Choose the next tool from state and requested mode."""
        completed = {step.tool_name for step in state.steps}
        return self._next_tool_after(state, completed)

    def _next_tool_after(self, state: AgentState, completed: set[str]) -> str:
        """Choose the next tool after a given completed-tool set."""
        if "retrieve_paper_context" not in completed:
            return "retrieve_paper_context"
        if not state.chunks:
            return "generate_report"
        if state.request.mode == "template":
            order = ["extract_reproduction_info", "generate_code_skeleton", "generate_simulation_template", "assess_risks", "generate_report"]
        elif state.request.mode == "focused":
            order = ["extract_reproduction_info", "analyze_formula_algorithm", "assess_risks", "generate_code_skeleton", "generate_report"]
        else:
            order = [
                "extract_reproduction_info",
                "analyze_formula_algorithm",
                "assess_risks",
                "generate_code_skeleton",
                "generate_simulation_template",
                "generate_report",
            ]
        return next((tool for tool in order if tool not in completed), "generate_report")

    def retrieve_paper_context(self, state: AgentState) -> ToolObservation:
        """Load stored paper chunks for grounded reproduction analysis."""
        state.chunks = self.store.list_chunks([state.paper.doc_id])
        evidence = self._evidence(state.chunks)
        if not state.chunks:
            warning = "Paper has no stored chunks; report is limited to metadata."
            return ToolObservation(summary=warning, warnings=[warning])
        return ToolObservation(summary=f"Loaded {len(state.chunks)} paper chunks for {state.paper.title}.", evidence=evidence)

    def extract_reproduction_info(self, state: AgentState) -> ToolObservation:
        """Extract reproduction details from paper text without filling gaps."""
        text = self._context_text(state)
        state.goal_understanding = (
            f"根据论文《{state.paper.title}》和用户需求“{state.request.user_requirement.strip()}”，整理可辅助复现的目标、数据、指标和基线。"
        )
        state.reproduction_info = {
            "targets": self._sentences_with(text, ["method", "task", "objective", "goal", "方法", "任务", "目标"]),
            "datasets": self._values_after_labels(text, ["Dataset", "Datasets", "Data", "数据集"]),
            "metrics": self._values_after_labels(text, ["Metric", "Metrics", "Evaluation", "指标"]),
            "baselines": self._values_after_labels(text, ["Baseline", "Baselines", "基线"]),
        }
        return ToolObservation(summary="Extracted reproduction fields; unknown marks information not present in stored chunks.", evidence=self._evidence(state.chunks))

    def analyze_formula_algorithm(self, state: AgentState) -> ToolObservation:
        """Collect formula and algorithm notes from explicit paper text."""
        text = self._context_text(state)
        notes = self._sentences_with(text, ["algorithm", "formula", "equation", "loss", "training", "inference", "算法", "公式", "训练", "推理"])
        state.formula_algorithm_notes = notes if notes != ["unknown"] else ["论文上下文未提供明确公式或算法细节。"]
        return ToolObservation(summary="Analyzed formula and algorithm evidence.", evidence=self._evidence(state.chunks))

    def assess_risks(self, state: AgentState) -> ToolObservation:
        """Assess reproduction risks using known fields and explicit unknowns."""
        info = state.reproduction_info
        risks: list[str] = []
        if info.get("datasets") == ["unknown"]:
            risks.append("unknown: 论文上下文未提供明确数据集，复现数据准备风险高。")
        if info.get("metrics") == ["unknown"]:
            risks.append("unknown: 论文上下文未提供明确指标定义，评估可比性风险高。")
        if info.get("baselines") == ["unknown"]:
            risks.append("unknown: 论文上下文未提供明确基线，难以判断对照实验。")
        if not state.formula_algorithm_notes:
            risks.append("unknown: 尚未分析到公式或算法细节，模板只能保留占位。")
        state.risks = risks or ["page/chunk evidence: 已提取数据集、指标和基线；仍需人工核对超参数、实现细节和随机种子。"]
        return ToolObservation(summary="Assessed reproduction risks with evidence or unknown markers.", evidence=self._evidence(state.chunks))

    def generate_code_skeleton(self, state: AgentState) -> ToolObservation:
        """Generate a non-executed Python skeleton template."""
        datasets = ", ".join(state.reproduction_info.get("datasets", ["unknown"]))
        metrics = ", ".join(state.reproduction_info.get("metrics", ["unknown"]))
        state.code_template = f'''"""
Template only. This code is not executed, is not complete reproduction,
and does not promise paper-level metrics.
Paper: {state.paper.title}
Datasets from paper context: {datasets}
Metrics from paper context: {metrics}
"""


def load_data():
    raise NotImplementedError("Fill in dataset access from the paper and your local environment.")


def build_model():
    raise NotImplementedError("Fill in the model from explicit paper algorithm details.")


def evaluate(model, data):
    raise NotImplementedError("Compute only the metrics explicitly defined by the paper.")
'''
        return ToolObservation(summary="Generated safe code skeleton template without running it.", evidence=self._evidence(state.chunks))

    def generate_simulation_template(self, state: AgentState) -> ToolObservation:
        """Generate a non-executed virtual simulation template."""
        state.simulation_template = """# Virtual simulation template only; do not treat as paper reproduction.
simulation = {
    "hypothesis": "replace with a paper-grounded hypothesis",
    "variables": ["replace with paper-supported variables"],
    "steps": ["configure synthetic inputs", "run local prototype manually", "compare only declared metrics"],
    "stop_condition": "manual review confirms assumptions are grounded in the paper",
}
"""
        return ToolObservation(summary="Generated virtual simulation template without executing code.", evidence=self._evidence(state.chunks))

    def generate_report(self, state: AgentState) -> ToolObservation:
        """Assemble final structured report."""
        info = state.reproduction_info
        state.report = ReproductionReport(
            paper_id=state.paper.doc_id,
            mode=state.request.mode,
            user_requirement=state.request.user_requirement,
            goal_understanding=state.goal_understanding or f"为《{state.paper.title}》生成辅助复现实验报告。",
            available_evidence=self._evidence(state.chunks),
            reproduction_targets=info.get("targets", ["unknown"]),
            datasets=info.get("datasets", ["unknown"]),
            metrics=info.get("metrics", ["unknown"]),
            baselines=info.get("baselines", ["unknown"]),
            formula_or_algorithm_notes=state.formula_algorithm_notes or ["论文上下文未提供明确公式或算法细节。"],
            implementation_plan=[
                "核对论文中数据集、指标、基线和算法描述。",
                "补全模板中的数据加载、模型构建和评估逻辑。",
                "人工运行实验并记录环境、随机种子和偏差来源。",
            ],
            code_template=state.code_template,
            simulation_template=state.simulation_template,
            risks=state.risks or ["unknown: 风险评估信息不足。"],
            limitations=["仅使用已上传论文的解析文本。", "缺失信息保留为 unknown，需人工回到论文核对。"],
            non_claims=NON_CLAIMS,
        )
        return ToolObservation(summary="Generated final structured reproduction report.", evidence=self._evidence(state.chunks))

    def _context_text(self, state: AgentState) -> str:
        return " ".join(chunk.text for chunk in state.chunks)

    def _evidence(self, chunks: list[PaperChunk]) -> list[str]:
        return [f"page {chunk.page}, chunk {chunk.chunk_id}" for chunk in chunks[:5]]

    def _values_after_labels(self, text: str, labels: list[str]) -> list[str]:
        for label in labels:
            match = re.search(rf"\b{re.escape(label)}s?\s*:\s*([^.\n;]+)", text, flags=re.IGNORECASE)
            if match:
                return [item.strip() for item in re.split(r",| and ", match.group(1)) if item.strip()]
        return ["unknown"]

    def _sentences_with(self, text: str, keywords: list[str]) -> list[str]:
        sentences = [part.strip() for part in re.split(r"(?<=[.!?。！？])\s+", text) if part.strip()]
        matches = [sentence for sentence in sentences if any(keyword.lower() in sentence.lower() for keyword in keywords)]
        return matches[:5] or ["unknown"]

    def _thought(self, tool_name: str, state: AgentState) -> str:
        thoughts = {
            "retrieve_paper_context": "先读取已上传论文上下文，确保后续结论有来源。",
            "extract_reproduction_info": "提取复现所需字段，缺失信息保持 unknown。",
            "analyze_formula_algorithm": "查找论文中明确的公式、算法和流程描述。",
            "assess_risks": "把缺失或不确定部分转成复现风险。",
            "generate_code_skeleton": "生成不会自动运行的代码模板。",
            "generate_simulation_template": "生成不会自动运行的虚拟仿真模板。",
            "generate_report": "汇总工具观察结果，生成最终结构化报告。",
        }
        return thoughts.get(tool_name, f"Continue {state.request.mode} reproduction assistance.")

    def _input_summary(self, tool_name: str, state: AgentState) -> str:
        if tool_name == "retrieve_paper_context":
            return f"paper_id={state.paper.doc_id}"
        return f"mode={state.request.mode}; chunks={len(state.chunks)}; requirement={state.request.user_requirement.strip()}"
