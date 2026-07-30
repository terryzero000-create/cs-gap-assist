from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ValueLevel = Literal["high", "mid"]
ReproductionMode = Literal["standard", "focused", "template"]
EvidenceStatus = Literal["verified", "local_only", "insufficient_evidence", "provider_unavailable", "synthetic"]
EvidenceSource = Literal["local", "arxiv", "openalex"]
TrustStatus = Literal["verified", "local_only", "synthetic", "legacy_unverified"]
UploadStatus = Literal[
    "received",
    "validating",
    "parsed",
    "chunked",
    "embedding",
    "indexed",
    "ready",
    "failed",
]


class WarningMixin(BaseModel):
    """Common response fields for recoverable system warnings."""

    warnings: list[str] = Field(default_factory=list)
    warning_codes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def populate_warning_codes(self) -> "WarningMixin":
        """Keep one stable machine-readable code parallel to every warning."""
        if len(self.warning_codes) < len(self.warnings):
            generated = [
                _warning_code(warning)
                for warning in self.warnings[len(self.warning_codes) :]
            ]
            self.warning_codes = [*self.warning_codes, *generated]
        return self


def _warning_code(warning: str) -> str:
    normalized = warning.casefold()
    patterns = (
        ("429", "EXTERNAL_RATE_LIMITED"),
        ("rate limit", "EXTERNAL_RATE_LIMITED"),
        ("external network is disabled", "EXTERNAL_NETWORK_DISABLED"),
        ("openalex citation expansion is disabled", "OPENALEX_DISABLED"),
        ("openalex_api_key missing", "OPENALEX_CREDENTIALS_MISSING"),
        ("returned no result", "EXTERNAL_EMPTY_RESULT"),
        ("returned no works", "EXTERNAL_EMPTY_RESULT"),
        ("no new arxiv", "EXTERNAL_EMPTY_RESULT"),
        ("arxiv request failed", "ARXIV_SEARCH_FAILED"),
        ("openalex request failed", "OPENALEX_SEARCH_FAILED"),
        ("semantic retrieval was unavailable", "SEMANTIC_RETRIEVAL_UNAVAILABLE"),
        ("lexical fallback", "LEXICAL_FALLBACK_USED"),
        ("fts5 returned no match", "LEXICAL_FALLBACK_USED"),
        ("cross-encoder", "RERANKER_UNAVAILABLE"),
        ("prompt injection", "SOURCE_PROMPT_INJECTION_FLAGGED"),
        ("instruction-like", "SOURCE_PROMPT_INJECTION_FLAGGED"),
        ("provider unavailable", "MODEL_PROVIDER_UNAVAILABLE"),
        ("synthetic", "SYNTHETIC_MODE"),
        ("mock", "SYNTHETIC_MODE"),
    )
    for needle, code in patterns:
        if needle in normalized:
            return code
    return "UNCLASSIFIED_WARNING"


class EvidenceResponseMixin(WarningMixin):
    """Response metadata describing whether conclusions are backed by trusted evidence."""

    evidence_status: EvidenceStatus = "verified"


class EvidenceRef(BaseModel):
    """Canonical reference to evidence admitted by a trusted retrieval source."""

    source: EvidenceSource
    id: str = Field(max_length=512)
    title: str = Field(max_length=1000)
    canonical_url: str = Field(max_length=4096)
    doc_id: str | None = Field(default=None, max_length=128)
    chunk_id: str | None = Field(default=None, max_length=128)
    page: int | None = None


class ModelOption(BaseModel):
    """A selectable model option exposed to the frontend."""

    provider: str
    model: str
    available: bool
    warning: str | None = None


class ModelConfig(BaseModel):
    """Runtime model selection for a single request."""

    chat_provider: str | None = Field(default=None, max_length=64)
    chat_model: str | None = Field(default=None, max_length=128)
    embedding_provider: str | None = Field(default=None, max_length=64)
    embedding_model: str | None = Field(default=None, max_length=128)


class RuntimeModelRequest(BaseModel):
    """Accept the public model_config key without conflicting with Pydantic internals."""

    model_config = ConfigDict(populate_by_name=True)
    runtime_model_config: ModelConfig | None = None

    @model_validator(mode="before")
    @classmethod
    def map_public_model_config(cls, value: object) -> object:
        """Map the wire-level model_config key to the internal field name."""
        if isinstance(value, dict) and "model_config" in value and "runtime_model_config" not in value:
            return {**value, "runtime_model_config": value["model_config"]}
        return value


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
    chunker_schema: str
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

    chunk_id: str = Field(max_length=128)
    doc_id: str = Field(max_length=128)
    page: int = Field(ge=1)
    text: str = Field(max_length=100_000)
    score: float | None = None
    revision_id: str | None = Field(default=None, max_length=128)
    ordinal: int = Field(default=0, ge=0)
    page_end: int | None = Field(default=None, ge=1)
    section_path: str = Field(default="", max_length=1000)
    char_start: int = Field(default=0, ge=0)
    char_end: int = Field(default=0, ge=0)
    block_type: Literal["text", "heading", "table", "formula", "code", "ocr"] = "text"
    chunker_version: str = Field(default="legacy", max_length=64)
    content_hash: str = Field(default="", max_length=128)
    injection_flagged: bool = False


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
    active_revision_id: str | None = None
    ingestion_status: str = "ready"
    reupload_required: bool = False


class PaperListResponse(BaseModel):
    """Stored paper listing response."""

    papers: list[PaperRecord]


class PaperUploadTaskResponse(WarningMixin):
    """State returned by asynchronous paper ingestion endpoints."""

    upload_id: str
    doc_id: str
    revision_id: str
    title: str
    status: UploadStatus
    status_url: str
    retryable: bool = False
    error_code: str | None = None
    error: str | None = None
    page_count: int | None = None
    chunk_count: int = 0


class PaperCollectionUpdateRequest(BaseModel):
    """Request to update personal collection metadata for a paper."""

    tags: list[str] = Field(default_factory=list, max_length=20)
    is_favorite: bool = False

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value: list[str]) -> list[str]:
        """Normalize and bound collection tags."""
        normalized = list(dict.fromkeys(tag.strip() for tag in value if tag.strip()))
        if any(len(tag) > 50 for tag in normalized):
            raise ValueError("Each tag must be at most 50 characters.")
        return normalized


class ReadingQARequest(RuntimeModelRequest):
    """Question request over uploaded papers."""

    question: str = Field(min_length=1, max_length=4000)
    doc_ids: list[str] = Field(min_length=1, max_length=50)
    top_k: int = Field(default=5, ge=1, le=10)

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
    title: str = Field(max_length=1000)
    value_level: ValueLevel
    description: str = Field(max_length=20_000)
    evidence_papers: list[str] = Field(max_length=50)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    trust_status: TrustStatus = "legacy_unverified"
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class GapAnalysisRequest(RuntimeModelRequest):
    """Request for research gap analysis."""

    topic: str = Field(min_length=1, max_length=500)
    doc_ids: list[str] = Field(max_length=50)


class GapAnalysisResponse(EvidenceResponseMixin):
    """Structured gap analysis result."""

    gaps: list[GapItem]


class ExperimentSuggestRequest(RuntimeModelRequest):
    """Request for literature-supported experiment suggestions."""

    gap_id: str = Field(min_length=1, max_length=128)
    topic: str | None = Field(default=None, max_length=500)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list, max_length=50)


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


class ReproductionAgentRequest(RuntimeModelRequest):
    """Request for the reproduction lab agent."""

    paper_id: str = Field(min_length=1, max_length=128)
    mode: ReproductionMode = "standard"
    user_requirement: str = Field(min_length=1, max_length=4000)


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


class ResearchPlanAgentRequest(RuntimeModelRequest):
    """Request for the research planning agent."""

    research_direction: str = Field(min_length=1, max_length=500)
    selected_paper_ids: list[str] = Field(min_length=1, max_length=50)
    experiment_result: str | None = Field(default=None, max_length=4000)


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
    recommended_refs: list[EvidenceRef] = Field(default_factory=list)
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

    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=100_000)
    tags: list[str] = Field(default_factory=list, max_length=20)
    related_doc_id: str | None = Field(default=None, max_length=128)
    related_gap_id: str | None = Field(default=None, max_length=128)

    @field_validator("tags")
    @classmethod
    def validate_note_tags(cls, value: list[str]) -> list[str]:
        """Normalize and bound note tags."""
        normalized = list(dict.fromkeys(tag.strip() for tag in value if tag.strip()))
        if any(len(tag) > 50 for tag in normalized):
            raise ValueError("Each tag must be at most 50 characters.")
        return normalized


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
