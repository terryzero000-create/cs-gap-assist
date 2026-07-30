from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


ValueLevel = Literal["high", "mid"]
ReproductionMode = Literal["standard", "focused", "template"]
EvidenceStatus = Literal["verified", "local_only", "insufficient_evidence", "provider_unavailable", "synthetic"]
EvidenceSource = Literal["local", "arxiv", "openalex"]
TrustStatus = Literal["verified", "local_only", "synthetic", "legacy_unverified"]


class WarningMixin(BaseModel):
    """Common response fields for recoverable system warnings."""

    warnings: list[str] = Field(default_factory=list)


class EvidenceResponseMixin(WarningMixin):
    """Response metadata describing whether conclusions are backed by trusted evidence."""

    evidence_status: EvidenceStatus = "verified"


class EvidenceRef(BaseModel):
    """Canonical reference to evidence admitted by a trusted retrieval source."""

    source: EvidenceSource
    id: str
    title: str
    canonical_url: str
    doc_id: str | None = None
    chunk_id: str | None = None
    page: int | None = None


class ModelOption(BaseModel):
    """A selectable model option exposed to the frontend."""

    provider: str
    model: str
    available: bool
    warning: str | None = None


class ModelConfig(BaseModel):
    """Runtime model selection for a single request."""

    chat_provider: str | None = None
    chat_model: str | None = None
    embedding_provider: str | None = None
    embedding_model: str | None = None


class ModelConfigResponse(BaseModel):
    """Supported model providers and defaults."""

    default_chat_provider: str
    default_chat_model: str
    default_embedding_provider: str
    default_embedding_model: str
    providers: dict[str, list[ModelOption]]


class EmbeddingProfileStatus(BaseModel):
    """Non-sensitive identity of the configured vector space."""

    provider: str
    model: str
    dimension: int
    schema_version: int
    key: str


class VectorIndexStatusResponse(WarningMixin):
    """Operational status of the rebuildable vector index."""

    state: Literal["ready", "legacy", "migrating", "migration_required", "degraded", "empty"]
    profile: EmbeddingProfileStatus
    active_collection: str
    legacy_collection: str | None = None
    sqlite_chunk_count: int
    indexed_chunk_count: int
    missing_chunk_count: int
    orphan_vector_count: int
    failed_chunk_count: int
    last_migration: dict[str, Any] | None = None


class PaperChunk(BaseModel):
    """A searchable chunk extracted from a PDF."""

    chunk_id: str
    doc_id: str
    page: int
    text: str
    score: float | None = None


class PaperUploadResponse(WarningMixin):
    """Response returned after a PDF upload is parsed and indexed."""

    doc_id: str
    title: str
    chunk_count: int


class PaperRecord(BaseModel):
    """Stored paper metadata."""

    doc_id: str
    title: str
    created_at: str
    is_favorite: bool = False
    tags: list[str] = Field(default_factory=list)


class PaperListResponse(BaseModel):
    """Stored paper listing response."""

    papers: list[PaperRecord]


class PaperCollectionUpdateRequest(BaseModel):
    """Request to update personal collection metadata for a paper."""

    tags: list[str] = Field(default_factory=list)
    is_favorite: bool = False


class ReadingQARequest(BaseModel):
    """Question request over uploaded papers."""

    model_config = ConfigDict(populate_by_name=True)

    question: str = Field(min_length=1)
    doc_ids: list[str] = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=10)
    runtime_model_config: ModelConfig | None = Field(default=None, alias="model_config")

    @field_validator("question")
    @classmethod
    def question_must_not_be_blank(cls, value: str) -> str:
        """Reject whitespace-only questions."""
        stripped = value.strip()
        if not stripped:
            raise ValueError("Question must not be blank.")
        return stripped


class SourceParagraph(BaseModel):
    """Evidence paragraph used to ground a generated answer."""

    doc_id: str
    chunk_id: str
    page: int
    text: str
    score: float


class ReadingQAResponse(EvidenceResponseMixin):
    """Answer with paragraph-level sources."""

    answer: str
    sources: list[SourceParagraph]


class GapItem(BaseModel):
    """Research gap item following the public API contract."""

    gap_id: str = Field(default_factory=lambda: str(uuid4()))
    title: str
    value_level: ValueLevel
    description: str
    evidence_papers: list[str]
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    trust_status: TrustStatus = "legacy_unverified"
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class GapAnalysisRequest(BaseModel):
    """Request for research gap analysis."""

    model_config = ConfigDict(populate_by_name=True)

    topic: str
    doc_ids: list[str]
    runtime_model_config: ModelConfig | None = Field(default=None, alias="model_config")


class GapAnalysisResponse(EvidenceResponseMixin):
    """Structured gap analysis result."""

    gaps: list[GapItem]


class ExperimentSuggestRequest(BaseModel):
    """Request for literature-supported experiment suggestions."""

    model_config = ConfigDict(populate_by_name=True)

    gap_id: str
    topic: str | None = None
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    runtime_model_config: ModelConfig | None = Field(default=None, alias="model_config")


class ExperimentPlan(BaseModel):
    """Concrete experiment plan for a research gap."""

    experiment_id: str = Field(default_factory=lambda: str(uuid4()))
    gap_id: str
    objective: str
    datasets: list[str]
    metrics: list[str]
    baselines: list[str]
    steps: list[str]
    risks: list[str]
    support_papers: list[str]
    support_refs: list[EvidenceRef] = Field(default_factory=list)
    trust_status: TrustStatus = "legacy_unverified"


class ExperimentSuggestResponse(EvidenceResponseMixin):
    """Experiment suggestion response."""

    experiments: list[ExperimentPlan]


class ReproductionAgentRequest(BaseModel):
    """Request for the reproduction lab agent."""

    model_config = ConfigDict(populate_by_name=True)

    paper_id: str
    mode: ReproductionMode = "standard"
    user_requirement: str
    runtime_model_config: ModelConfig | None = Field(default=None, alias="model_config")


class ToolObservation(BaseModel):
    """Observed result from a reproduction agent tool call."""

    summary: str
    evidence: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class AgentStep(BaseModel):
    """Single tool call made by the reproduction agent."""

    step_index: int
    tool_name: str
    thought: str
    input_summary: str
    observation: ToolObservation
    next_decision: str


class ReproductionReport(BaseModel):
    """Structured assisted reproduction report."""

    paper_id: str
    mode: ReproductionMode
    user_requirement: str
    goal_understanding: str
    available_evidence: list[str] = Field(default_factory=list)
    reproduction_targets: list[str] = Field(default_factory=list)
    datasets: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    baselines: list[str] = Field(default_factory=list)
    formula_or_algorithm_notes: list[str] = Field(default_factory=list)
    implementation_plan: list[str] = Field(default_factory=list)
    code_template: str = ""
    simulation_template: str = ""
    risks: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    non_claims: list[str] = Field(default_factory=list)


class ReproductionAgentResponse(WarningMixin):
    """Reproduction agent trace and final structured report."""

    agent_steps: list[AgentStep]
    report: ReproductionReport


class ResearchPlanAgentRequest(BaseModel):
    """Request for the research planning agent."""

    model_config = ConfigDict(populate_by_name=True)

    research_direction: str = Field(min_length=1)
    selected_paper_ids: list[str] = Field(min_length=1)
    experiment_result: str | None = None
    runtime_model_config: ModelConfig | None = Field(default=None, alias="model_config")


class ResearchPlanAgentStep(BaseModel):
    """One bounded tool call in the research planning agent trace."""

    step_index: int
    tool_name: str
    thought: str
    observation: str
    next_decision: str


class ResearchPlanCard(BaseModel):
    """A compact research execution card."""

    title: str
    background: str
    research_gap: str
    entry_point: str
    experiment_suggestion: str
    recommended_papers: list[str]
    risks: list[str]
    next_action: str


class ResearchPlanRoute(BaseModel):
    """A route-level pairing of a selected gap and its experiment plans."""

    gap: GapItem
    experiments: list[ExperimentPlan] = Field(default_factory=list)


class ResearchPlanAgentResponse(EvidenceResponseMixin):
    """Research planning agent trace and final execution cards."""

    agent_steps: list[ResearchPlanAgentStep]
    routes: list[ResearchPlanRoute]
    final_cards: list[ResearchPlanCard]


class CitationNode(BaseModel):
    """D3-compatible citation graph node."""

    id: str
    title: str
    year: int | None = None
    importance_score: float
    is_key: bool = False


class CitationLink(BaseModel):
    """D3-compatible citation graph edge."""

    source: str
    target: str
    relation: str = "cites"


class CitationGraphResponse(EvidenceResponseMixin):
    """Citation graph response for D3 force layout."""

    nodes: list[CitationNode]
    links: list[CitationLink]


class NoteCreateRequest(BaseModel):
    """Request to create a knowledge-base note."""

    title: str
    content: str
    tags: list[str] = Field(default_factory=list)
    related_doc_id: str | None = None
    related_gap_id: str | None = None


class NoteRecord(NoteCreateRequest):
    """Stored note record."""

    note_id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class KnowledgeSearchResponse(BaseModel):
    """Unified knowledge search result."""

    papers: list[PaperRecord] = Field(default_factory=list)
    notes: list[NoteRecord] = Field(default_factory=list)
    chunks: list[PaperChunk] = Field(default_factory=list)
    gaps: list[GapItem] = Field(default_factory=list)
    experiments: list[ExperimentPlan] = Field(default_factory=list)
