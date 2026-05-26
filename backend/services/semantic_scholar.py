from dataclasses import dataclass


@dataclass(frozen=True)
class ExternalPaper:
    """Minimal external paper metadata used as evidence."""

    paper_id: str
    title: str
    abstract: str
    year: int | None = None


class SemanticScholarClient:
    """Semantic Scholar search client with deterministic MVP fallback."""

    async def search(self, query: str, limit: int = 5) -> tuple[list[ExternalPaper], list[str]]:
        """Search papers related to a query."""
        papers = [
            ExternalPaper(
                paper_id=f"semantic-{index}",
                title=f"{query} evidence paper {index}",
                abstract="This mock paper highlights evaluation gaps, robustness limits, and reproducibility concerns.",
                year=2024,
            )
            for index in range(1, limit + 1)
        ]
        return papers, ["Semantic Scholar network call is mocked in the MVP."]
