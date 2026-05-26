from backend.models.schemas import CitationGraphResponse, CitationLink, CitationNode


class CitationGraphService:
    """Build keyword-centered citation graph data for D3."""

    async def build_graph(self, keyword: str) -> CitationGraphResponse:
        """Return a deterministic citation graph for an input keyword."""
        safe_keyword = keyword.strip() or "unknown topic"
        nodes = [
            CitationNode(id="paper-root", title=f"Survey of {safe_keyword}", year=2025, importance_score=0.98, is_key=True),
            CitationNode(id="paper-method", title=f"Core method for {safe_keyword}", year=2024, importance_score=0.81, is_key=True),
            CitationNode(id="paper-eval", title=f"Evaluation benchmark for {safe_keyword}", year=2023, importance_score=0.66),
            CitationNode(id="paper-origin", title=f"Early work on {safe_keyword}", year=2021, importance_score=0.52),
        ]
        links = [
            CitationLink(source="paper-root", target="paper-method"),
            CitationLink(source="paper-root", target="paper-eval"),
            CitationLink(source="paper-method", target="paper-origin"),
        ]
        return CitationGraphResponse(nodes=nodes, links=links, warnings=["Citation graph uses deterministic MVP data."])
