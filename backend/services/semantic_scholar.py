from dataclasses import dataclass


@dataclass(frozen=True)
class ExternalPaper:
    """Minimal external paper metadata used as experiment evidence."""

    paper_id: str
    title: str
    abstract: str
    year: int | None = None


class SemanticScholarClient:
    """Semantic Scholar search client with deterministic MVP fallback."""

    async def search(self, query: str, limit: int = 5) -> tuple[list[ExternalPaper], list[str]]:
        """Search papers related to an experiment planning query."""
        papers = [
            ExternalPaper(
                paper_id=f"support-paper-{index}",
                title=f"Experiment evidence for {query} #{index}",
                abstract="This mock paper provides dataset, metric, and baseline evidence for experiment design.",
                year=2025,
            )
            for index in range(1, limit + 1)
        ]
        return papers, ["Semantic Scholar network call is mocked in the MVP."]
