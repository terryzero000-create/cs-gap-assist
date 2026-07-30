import asyncio
import os

import pytest

from backend.core.config import Settings
from backend.rag.embedder import XfyunSparkEmbeddingProvider
from backend.services.citation_graph import OpenAlexCitationClient


pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("RUN_LIVE_SMOKE") != "true",
        reason="Live provider smoke tests are manual only.",
    ),
]


def test_live_xfyun_embedding_protocol() -> None:
    settings = Settings(_env_file=None)
    result = asyncio.run(
        XfyunSparkEmbeddingProvider(settings, model="query").embed(
            ["retrieval augmented generation"]
        )
    )

    assert result.is_fallback is False
    assert len(result.vectors) == 1
    assert len(result.vectors[0]) == 2560


def test_live_openalex_search_returns_canonical_works() -> None:
    settings = Settings(_env_file=None)
    papers, warnings = asyncio.run(
        OpenAlexCitationClient(
            base_url=settings.openalex_base_url,
            api_key=settings.openalex_api_key,
            timeout_seconds=10.0,
        ).search("retrieval augmented generation", limit=3)
    )

    assert warnings == []
    assert papers
    assert all(paper.paper_id.startswith("W") for paper in papers)
