"""Async client for GDELT DOC 2.0 and GeoJSON APIs."""

from __future__ import annotations

import asyncio

import httpx

from app.core.logging import get_logger

logger = get_logger(__name__)

_DOC_BASE = "https://api.gdeltproject.org/api/v2/doc/doc"
_GEO_BASE = "https://api.gdeltproject.org/api/v2/geo/geo"


class GdeltClient:
    """Async HTTP client for GDELT APIs with rate limiting and retry."""

    def __init__(
        self, rate_limit: int = 5, max_retries: int = 3, backoff: float = 2.0
    ) -> None:
        self._client: httpx.AsyncClient | None = None
        self._semaphore = asyncio.Semaphore(rate_limit)
        self._max_retries = max_retries
        self._backoff = backoff

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def _request(self, url: str, params: dict[str, str]) -> dict | list:
        """Execute HTTP GET with rate limiting and retry."""
        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            async with self._semaphore:
                try:
                    resp = await self._get_client().get(url, params=params)
                    if resp.status_code == 429 or resp.status_code >= 500:
                        wait = self._backoff * (2**attempt)
                        logger.warning(
                            "gdelt_retry",
                            status=resp.status_code,
                            attempt=attempt + 1,
                            wait=wait,
                        )
                        await asyncio.sleep(wait)
                        continue
                    resp.raise_for_status()
                    return resp.json()
                except httpx.HTTPStatusError as exc:
                    last_exc = exc
                    raise
                except httpx.RequestError as exc:
                    last_exc = exc
                    if attempt < self._max_retries:
                        wait = self._backoff * (2**attempt)
                        await asyncio.sleep(wait)
                        continue
                    raise
        if last_exc:
            raise last_exc
        msg = f"All {self._max_retries + 1} attempts failed for {url}"
        raise RuntimeError(msg)

    async def article_search(
        self,
        query: str,
        *,
        timespan: str = "24h",
        max_records: int = 75,
        source_lang: str = "english",
    ) -> list[dict]:
        """Search articles via DOC 2.0 API."""
        params = {
            "query": query,
            "mode": "artlist",
            "timespan": timespan,
            "maxrecords": str(max_records),
            "format": "json",
            "sourcelang": source_lang,
        }
        data = await self._request(_DOC_BASE, params)
        if isinstance(data, dict):
            return data.get("articles", [])
        return []

    async def timeline_volume(
        self,
        query: str,
        *,
        timespan: str = "7d",
    ) -> list[dict]:
        """Get article volume timeline."""
        params = {
            "query": query,
            "mode": "timelinevol",
            "timespan": timespan,
            "format": "json",
        }
        data = await self._request(_DOC_BASE, params)
        if isinstance(data, dict):
            timeline = data.get("timeline", [])
            if timeline and isinstance(timeline[0], dict):
                return timeline[0].get("series", [])
        return []

    async def timeline_tone(
        self,
        query: str,
        *,
        timespan: str = "7d",
    ) -> list[dict]:
        """Get tone/sentiment timeline."""
        params = {
            "query": query,
            "mode": "timelinetone",
            "timespan": timespan,
            "format": "json",
        }
        data = await self._request(_DOC_BASE, params)
        if isinstance(data, dict):
            timeline = data.get("timeline", [])
            if timeline and isinstance(timeline[0], dict):
                return timeline[0].get("series", [])
        return []

    async def geo_query(
        self,
        query: str,
        *,
        timespan: str = "24h",
    ) -> list[dict]:
        """Query GKG GeoJSON for geographic event data."""
        params = {
            "query": query,
            "mode": "pointdata",
            "format": "geojson",
            "timespan": timespan,
        }
        data = await self._request(_GEO_BASE, params)
        if isinstance(data, dict):
            return data.get("features", [])
        return []

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None


gdelt_client = GdeltClient()
