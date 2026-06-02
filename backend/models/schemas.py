from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


ValueLevel = Literal["high", "mid"]


class WarningMixin(BaseModel):
    """Common response fields for recoverable system warnings."""

    warnings: list[str] = Field(default_factory=list)


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


class ReadingQAResponse(WarningMixin):
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
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class GapAnalysisRequest(BaseModel):
    """Request for research gap analysis."""

    model_config = ConfigDict(populate_by_name=True)

    topic: str
    doc_ids: list[str]
    runtime_model_config: ModelConfig | None = Field(default=None, alias="model_config")


class GapAnalysisResponse(WarningMixin):
    """Structured gap analysis result."""

    gaps: list[GapItem]


class ExperimentSuggestRequest(BaseModel):
    """Request for literature-supported experiment suggestions."""

    model_config = ConfigDict(populate_by_name=True)

    gap_id: str
    topic: str | None = None
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


class ExperimentSuggestResponse(WarningMixin):
    """Experiment suggestion response."""

    experiments: list[ExperimentPlan]


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


class CitationGraphResponse(WarningMixin):
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
