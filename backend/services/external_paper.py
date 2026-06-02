from dataclasses import dataclass


@dataclass(frozen=True)
class ExternalPaper:
    """Minimal external paper metadata used as evidence."""

    paper_id: str
    title: str
    abstract: str
    year: int | None = None
