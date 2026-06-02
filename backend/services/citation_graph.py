from dataclasses import dataclass, field
from typing import Protocol

import httpx

from backend.models.schemas import CitationGraphResponse, CitationLink, CitationNode


@dataclass(frozen=True)
class ExternalCitationPaper:
    """External citation metadata normalized from OpenAlex."""

    paper_id: str
    title: str
    year: int | None = None
    citation_count: int = 0
    influential_citation_count: int = 0
    references: list["ExternalCitationPaper"] = field(default_factory=list)
    citations: list["ExternalCitationPaper"] = field(default_factory=list)


class CitationClient(Protocol):
    """Search client contract for citation graph expansion."""

    async def search(self, keyword: str, limit: int) -> tuple[list[ExternalCitationPaper], list[str]]:
        """Return citation papers and recoverable warnings."""


class OpenAlexCitationClient:
    """OpenAlex citation client with deterministic fallback handled by the service."""

    def __init__(
        self,
        base_url: str = "https://api.openalex.org/works",
        api_key: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = 3.0,
    ) -> None:
        """Create an OpenAlex works API client."""
        self.base_url = base_url
        self.api_key = api_key
        self.transport = transport
        self.timeout_seconds = timeout_seconds

    async def search(self, keyword: str, limit: int) -> tuple[list[ExternalCitationPaper], list[str]]:
        """Search OpenAlex works and attach lightweight reference/citation neighbors."""
        if not keyword.strip():
            return [], ["OpenAlex query is empty; using deterministic citation graph data."]
        if not self.api_key:
            return [], ["OPENALEX_API_KEY missing; using deterministic citation graph data."]
        params = {
            "search": keyword,
            "per-page": str(max(1, min(limit, 25))),
            "sort": "cited_by_count:desc",
            "select": "id,display_name,publication_year,cited_by_count,referenced_works",
            "api_key": self.api_key,
        }
        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=self.timeout_seconds) as client:
                response = await client.get(self.base_url, params=params)
                response.raise_for_status()
                data = response.json()
                papers = [self._paper_from_item(item) for item in data.get("results", []) if self._is_work_item(item)]
                if not papers:
                    return [], ["OpenAlex returned no works; using deterministic citation graph data."]
                expanded = await self._attach_neighbors(client, papers[:limit])
                return expanded, []
        except Exception as exc:
            return [], [f"OpenAlex request failed ({exc}); using deterministic citation graph data."]

    async def _attach_neighbors(
        self,
        client: httpx.AsyncClient,
        papers: list[ExternalCitationPaper],
    ) -> list[ExternalCitationPaper]:
        """Attach a small number of citation neighbors for the highest-ranked works."""
        expanded: list[ExternalCitationPaper] = []
        lookup = {paper.paper_id: paper for paper in papers}
        for paper in papers:
            references = [lookup[work_id] for work_id in paper.references[0:2] if work_id.paper_id in lookup]
            citations = await self._fetch_citations(client, paper.paper_id, limit=2)
            expanded.append(
                ExternalCitationPaper(
                    paper_id=paper.paper_id,
                    title=paper.title,
                    year=paper.year,
                    citation_count=paper.citation_count,
                    influential_citation_count=paper.influential_citation_count,
                    references=references,
                    citations=citations,
                )
            )
        return expanded

    async def _fetch_citations(
        self,
        client: httpx.AsyncClient,
        paper_id: str,
        limit: int,
    ) -> list[ExternalCitationPaper]:
        """Fetch works that cite a given OpenAlex work."""
        params = {
            "filter": f"cites:{paper_id}",
            "per-page": str(limit),
            "sort": "cited_by_count:desc",
            "select": "id,display_name,publication_year,cited_by_count",
            "api_key": self.api_key or "",
        }
        response = await client.get(self.base_url, params=params)
        if response.status_code >= 400:
            return []
        data = response.json()
        return [self._paper_from_item(item) for item in data.get("results", []) if self._is_work_item(item)]

    def _paper_from_item(self, item: dict[str, object]) -> ExternalCitationPaper:
        """Convert an OpenAlex work item into citation graph metadata."""
        raw_id = str(item["id"]).rstrip("/").split("/")[-1]
        year = item.get("publication_year")
        cited_by = item.get("cited_by_count")
        references = item.get("referenced_works")
        reference_papers = [
            ExternalCitationPaper(paper_id=str(work_id).rstrip("/").split("/")[-1], title="Referenced work")
            for work_id in references
            if isinstance(work_id, str)
        ] if isinstance(references, list) else []
        return ExternalCitationPaper(
            paper_id=raw_id,
            title=str(item["display_name"]).strip(),
            year=year if isinstance(year, int) else None,
            citation_count=cited_by if isinstance(cited_by, int) else 0,
            references=reference_papers,
        )

    def _is_work_item(self, item: object) -> bool:
        """Return whether a value has the minimum OpenAlex work fields."""
        return isinstance(item, dict) and bool(item.get("id")) and bool(item.get("display_name"))


class CitationGraphService:
    """Build keyword-centered citation graph data for D3."""

    def __init__(self, citation_client: CitationClient | None = None) -> None:
        """Create the graph service with an optional external citation client."""
        self.citation_client = citation_client or OpenAlexCitationClient()

    async def build_graph(
        self,
        keyword: str,
        max_nodes: int = 25,
        use_openalex: bool = False,
    ) -> CitationGraphResponse:
        """Return a citation graph for an input keyword."""
        safe_keyword = keyword.strip() or "unknown topic"
        capped_nodes = max(3, min(max_nodes, 50))
        if use_openalex:
            papers, warnings = await self.citation_client.search(safe_keyword, limit=capped_nodes)
            if papers:
                graph = self._graph_from_external_papers(papers, capped_nodes)
                graph.warnings.extend(warnings)
                return graph
            fallback = self._fallback_graph(safe_keyword, capped_nodes)
            fallback.warnings.extend(warnings)
            return fallback
        graph = self._fallback_graph(safe_keyword, capped_nodes)
        graph.warnings.append("OpenAlex citation expansion is disabled; using deterministic MVP data.")
        return graph

    def _graph_from_external_papers(
        self,
        papers: list[ExternalCitationPaper],
        max_nodes: int,
    ) -> CitationGraphResponse:
        """Build a ranked, capped citation graph from external paper metadata."""
        candidates: dict[str, ExternalCitationPaper] = {}
        links: list[CitationLink] = []
        for paper in papers:
            candidates[paper.paper_id] = paper
            for reference in paper.references:
                candidates.setdefault(reference.paper_id, reference)
                links.append(CitationLink(source=self._node_id(paper.paper_id), target=self._node_id(reference.paper_id), relation="cites"))
            for citation in paper.citations:
                candidates.setdefault(citation.paper_id, citation)
                links.append(CitationLink(source=self._node_id(citation.paper_id), target=self._node_id(paper.paper_id), relation="cites"))

        ranked = sorted(candidates.values(), key=self._paper_rank, reverse=True)[:max_nodes]
        max_rank = max((self._paper_rank(paper) for paper in ranked), default=1.0)
        nodes = [
            CitationNode(
                id=self._node_id(paper.paper_id),
                title=paper.title,
                year=paper.year,
                importance_score=round(self._paper_rank(paper) / max_rank, 3),
                is_key=index < min(3, len(ranked)),
            )
            for index, paper in enumerate(ranked)
        ]
        node_ids = {node.id for node in nodes}
        valid_links = [link for link in links if link.source in node_ids and link.target in node_ids]
        if not valid_links and len(nodes) > 1:
            valid_links = [CitationLink(source=nodes[0].id, target=node.id) for node in nodes[1:]]
        return CitationGraphResponse(nodes=nodes, links=valid_links, warnings=[])

    def _fallback_graph(self, keyword: str, max_nodes: int) -> CitationGraphResponse:
        """Return deterministic graph data when OpenAlex is disabled or unavailable."""
        nodes = [
            CitationNode(id="paper-root", title=f"Survey of {keyword}", year=2025, importance_score=1.0, is_key=True),
            CitationNode(id="paper-method", title=f"Core method for {keyword}", year=2024, importance_score=0.82, is_key=True),
            CitationNode(id="paper-eval", title=f"Evaluation benchmark for {keyword}", year=2023, importance_score=0.66),
            CitationNode(id="paper-origin", title=f"Early work on {keyword}", year=2021, importance_score=0.52),
            CitationNode(id="paper-application", title=f"Applied system for {keyword}", year=2022, importance_score=0.46),
        ][:max_nodes]
        node_ids = {node.id for node in nodes}
        links = [
            CitationLink(source="paper-root", target="paper-method"),
            CitationLink(source="paper-root", target="paper-eval"),
            CitationLink(source="paper-method", target="paper-origin"),
            CitationLink(source="paper-eval", target="paper-application"),
        ]
        return CitationGraphResponse(nodes=nodes, links=[link for link in links if link.source in node_ids and link.target in node_ids])

    def _paper_rank(self, paper: ExternalCitationPaper) -> float:
        """Score key nodes by citations, influential citations, and recency."""
        recency = (paper.year or 2000) - 2000
        return max(1.0, paper.citation_count + paper.influential_citation_count * 8 + recency * 0.5)

    def _node_id(self, paper_id: str) -> str:
        """Return a stable OpenAlex graph node id."""
        return f"openalex-{paper_id}"
