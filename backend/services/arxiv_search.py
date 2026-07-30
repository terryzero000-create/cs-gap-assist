import asyncio
import time
from xml.etree import ElementTree

import httpx

from backend.core.sanitize import safe_exception_message
from backend.services.external_paper import ExternalPaper


_CACHE: dict[str, tuple[float, list[ExternalPaper]]] = {}
_LAST_LIVE_REQUEST_AT = 0.0
_IN_FLIGHT: dict[tuple[int, str], asyncio.Task[tuple[list[ExternalPaper], list[str]]]] = {}
_RATE_LOCKS: dict[int, asyncio.Lock] = {}


class ArxivSearchClient:
    """Rate-limited arXiv search client that never manufactures papers."""

    def __init__(
        self,
        base_url: str = "https://export.arxiv.org/api/query",
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = 3.0,
        enabled: bool = True,
        user_agent: str = "CS-Gap-Assist/0.1 (literature-research-client)",
        min_interval_seconds: float = 3.0,
        cache_ttl_seconds: float = 300.0,
    ) -> None:
        """Create an arXiv search client."""
        self.base_url = base_url
        self.transport = transport
        self.timeout_seconds = timeout_seconds
        self.enabled = enabled
        self.user_agent = user_agent
        self.min_interval_seconds = max(0.0, min_interval_seconds)
        self.cache_ttl_seconds = max(0.0, cache_ttl_seconds)

    async def search(self, query: str, limit: int = 5) -> tuple[list[ExternalPaper], list[str]]:
        """Search arXiv papers related to a query."""
        if not query.strip():
            return [], ["arXiv query is empty; no external papers searched."]
        if not self.enabled:
            return [], ["External network is disabled; arXiv evidence is unavailable."]
        safe_limit = max(1, min(limit, 25))
        cache_key = f"{self.base_url}|{query.strip().casefold()}|{safe_limit}"
        cached = _CACHE.get(cache_key)
        if self.transport is None and cached and time.monotonic() - cached[0] <= self.cache_ttl_seconds:
            return cached[1], []
        params = {
            "search_query": f"all:{query}",
            "start": "0",
            "max_results": str(safe_limit),
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
        if self.transport is None:
            inflight_key = (id(asyncio.get_running_loop()), cache_key)
            existing = _IN_FLIGHT.get(inflight_key)
            if existing is not None:
                return await existing
            task = asyncio.create_task(
                self._search_uncached(params, safe_limit, cache_key)
            )
            _IN_FLIGHT[inflight_key] = task
            try:
                return await task
            finally:
                _IN_FLIGHT.pop(inflight_key, None)
        return await self._search_uncached(params, safe_limit, cache_key)

    async def _search_uncached(
        self,
        params: dict[str, str],
        safe_limit: int,
        cache_key: str,
    ) -> tuple[list[ExternalPaper], list[str]]:
        """Run one deduplicated request and cache successful live results."""
        try:
            await self._respect_rate_limit()
            async with httpx.AsyncClient(
                transport=self.transport,
                timeout=self.timeout_seconds,
                headers={"User-Agent": self.user_agent},
            ) as client:
                response = await self._get_with_retry(client, params)
            papers = self._parse_atom(response.text)
            if papers:
                selected = papers[:safe_limit]
                if self.transport is None:
                    _CACHE[cache_key] = (time.monotonic(), selected)
                return selected, []
            return [], ["arXiv returned no results."]
        except Exception as exc:
            return [], [
                f"arXiv request failed: {safe_exception_message(exc)}"
            ]

    async def _respect_rate_limit(self) -> None:
        """Throttle live arXiv calls while keeping injected test transports immediate."""
        global _LAST_LIVE_REQUEST_AT
        if self.transport is not None or self.min_interval_seconds <= 0:
            return
        loop_id = id(asyncio.get_running_loop())
        lock = _RATE_LOCKS.setdefault(loop_id, asyncio.Lock())
        async with lock:
            delay = self.min_interval_seconds - (
                time.monotonic() - _LAST_LIVE_REQUEST_AT
            )
            if delay > 0:
                await asyncio.sleep(delay)
            _LAST_LIVE_REQUEST_AT = time.monotonic()

    async def _get_with_retry(self, client: httpx.AsyncClient, params: dict[str, str]) -> httpx.Response:
        """Retry rate-limited requests twice without substituting local data."""
        response: httpx.Response | None = None
        for attempt in range(3):
            response = await client.get(self.base_url, params=params)
            if response.status_code != 429:
                response.raise_for_status()
                return response
            if attempt < 2:
                retry_after = response.headers.get("Retry-After")
                delay = float(retry_after) if retry_after and retry_after.replace(".", "", 1).isdigit() else 2**attempt
                await asyncio.sleep(min(max(delay, 0.0), 10.0))
        assert response is not None
        response.raise_for_status()
        return response

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
                    canonical_url=raw_id.replace("http://", "https://", 1),
                )
            )
        return papers

    def _entry_text(self, entry: ElementTree.Element, tag: str, ns: dict[str, str]) -> str:
        """Return normalized text from an Atom entry."""
        value = entry.findtext(f"atom:{tag}", namespaces=ns)
        return value.strip() if value else ""
