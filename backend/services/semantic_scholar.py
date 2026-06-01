from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class ExternalPaper:
    """Minimal external paper metadata used as evidence."""

    paper_id: str
    title: str
    abstract: str
    year: int | None = None


class SemanticScholarClient:
    """Semantic Scholar search client with deterministic fallback."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://api.semanticscholar.org/graph/v1/paper/search",
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = 3.0,
    ) -> None:
        """Create a Semantic Scholar client."""
        self.api_key = api_key
        self.base_url = base_url
        self.transport = transport
        self.timeout_seconds = timeout_seconds

    async def search(self, query: str, limit: int = 5) -> tuple[list[ExternalPaper], list[str]]:
        """Search papers related to a query."""
        if not query.strip():
            return [], ["Semantic Scholar query is empty; no external papers searched."]
        params = {"query": query, "limit": str(limit), "fields": "paperId,title,abstract,year,url"}
        headers = {"x-api-key": self.api_key} if self.api_key else None
        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=self.timeout_seconds) as client:
                response = await client.get(self.base_url, params=params, headers=headers)
                response.raise_for_status()
            data = response.json()
            papers = [self._paper_from_item(item) for item in data.get("data", []) if item.get("paperId") and item.get("title")]
            if papers:
                return papers[:limit], []
            return self._fallback(query, limit), ["Semantic Scholar returned no results; using deterministic fallback."]
        except Exception as exc:
            return self._fallback(query, limit), [f"Semantic Scholar request failed ({exc}); using deterministic fallback."]

    def _paper_from_item(self, item: dict[str, object]) -> ExternalPaper:
        """Convert a Semantic Scholar result item into common metadata."""
        year = item.get("year")
        return ExternalPaper(
            paper_id=f"semantic-{item['paperId']}",
            title=str(item["title"]).strip(),
            abstract=str(item.get("abstract") or "No abstract available.").strip(),
            year=year if isinstance(year, int) else None,
        )

    def _fallback(self, query: str, limit: int) -> list[ExternalPaper]:
        """Return deterministic local papers when live search is unavailable."""
        papers = [
            ExternalPaper(
                paper_id=f"semantic-{index}",
                title=f"{query} evidence paper {index}",
                abstract="This mock paper highlights evaluation gaps, robustness limits, and reproducibility concerns.",
                year=2024,
            )
            for index in range(1, limit + 1)
        ]
        return papers
