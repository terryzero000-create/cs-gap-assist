from xml.etree import ElementTree

import httpx

from backend.services.external_paper import ExternalPaper


class ArxivSearchClient:
    """arXiv search client with deterministic fallback."""

    def __init__(
        self,
        base_url: str = "https://export.arxiv.org/api/query",
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = 3.0,
    ) -> None:
        """Create an arXiv search client."""
        self.base_url = base_url
        self.transport = transport
        self.timeout_seconds = timeout_seconds

    async def search(self, query: str, limit: int = 5) -> tuple[list[ExternalPaper], list[str]]:
        """Search arXiv papers related to a query."""
        if not query.strip():
            return [], ["arXiv query is empty; no external papers searched."]
        params = {
            "search_query": f"all:{query}",
            "start": "0",
            "max_results": str(limit),
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=self.timeout_seconds) as client:
                response = await client.get(self.base_url, params=params)
                response.raise_for_status()
            papers = self._parse_atom(response.text)
            if papers:
                return papers[:limit], []
            return self._fallback(query, limit), ["arXiv returned no results; using deterministic fallback."]
        except Exception as exc:
            return self._fallback(query, limit), [f"arXiv request failed ({exc}); using deterministic fallback."]

    def _parse_atom(self, text: str) -> list[ExternalPaper]:
        """Parse arXiv Atom XML into common metadata."""
        root = ElementTree.fromstring(text)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        papers: list[ExternalPaper] = []
        for entry in root.findall("atom:entry", ns):
            raw_id = self._entry_text(entry, "id", ns)
            title = self._entry_text(entry, "title", ns)
            summary = self._entry_text(entry, "summary", ns)
            published = self._entry_text(entry, "published", ns)
            if not raw_id or not title:
                continue
            paper_id = raw_id.rsplit("/", 1)[-1].split("v", 1)[0]
            year = int(published[:4]) if len(published) >= 4 and published[:4].isdigit() else None
            papers.append(
                ExternalPaper(
                    paper_id=f"arxiv-{paper_id}",
                    title=" ".join(title.split()),
                    abstract=" ".join((summary or "No abstract available.").split()),
                    year=year,
                )
            )
        return papers

    def _entry_text(self, entry: ElementTree.Element, tag: str, ns: dict[str, str]) -> str:
        """Return normalized text from an Atom entry."""
        value = entry.findtext(f"atom:{tag}", namespaces=ns)
        return value.strip() if value else ""

    def _fallback(self, query: str, limit: int) -> list[ExternalPaper]:
        """Return deterministic local papers when live search is unavailable."""
        return [
            ExternalPaper(
                paper_id=f"arxiv-{index}",
                title=f"arXiv study on {query} #{index}",
                abstract="This mock arXiv result discusses recent methods and unresolved experimental coverage.",
                year=2025,
            )
            for index in range(1, limit + 1)
        ]
