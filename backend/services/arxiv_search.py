from backend.services.semantic_scholar import ExternalPaper


class ArxivSearchClient:
    """arXiv search client with deterministic MVP fallback."""

    async def search(self, query: str, limit: int = 5) -> tuple[list[ExternalPaper], list[str]]:
        """Search arXiv papers related to a query."""
        papers = [
            ExternalPaper(
                paper_id=f"arxiv-{index}",
                title=f"arXiv study on {query} #{index}",
                abstract="This mock arXiv result discusses recent methods and unresolved experimental coverage.",
                year=2025,
            )
            for index in range(1, limit + 1)
        ]
        return papers, ["arXiv network call is mocked in the MVP."]
