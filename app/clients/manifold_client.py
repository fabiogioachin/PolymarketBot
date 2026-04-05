"""Async client for the Manifold Markets v0 REST API."""

from __future__ import annotations

import asyncio

import httpx

from app.core.logging import get_logger
from app.models.manifold import ManifoldBet, ManifoldComment, ManifoldMarket

logger = get_logger(__name__)

_BASE_URL = "https://api.manifold.markets/v0"


class ManifoldClient:
    """Async HTTP client for Manifold Markets API with rate limiting and retry."""

    def __init__(
        self, rate_limit: int = 10, max_retries: int = 3, backoff: float = 2.0
    ) -> None:
        self._client: httpx.AsyncClient | None = None
        self._semaphore = asyncio.Semaphore(rate_limit)
        self._max_retries = max_retries
        self._backoff = backoff

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(base_url=_BASE_URL, timeout=30.0)
        return self._client

    async def _request(self, path: str, params: dict[str, str] | None = None) -> dict | list:
        """Execute HTTP GET with rate limiting and retry."""
        if params is None:
            params = {}
        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            async with self._semaphore:
                try:
                    resp = await self._get_client().get(path, params=params)
                    if resp.status_code == 429 or resp.status_code >= 500:
                        wait = self._backoff * (2**attempt)
                        logger.warning(
                            "manifold_retry",
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
        msg = f"All {self._max_retries + 1} attempts failed for {path}"
        raise RuntimeError(msg)

    async def search_markets(self, term: str, limit: int = 20) -> list[ManifoldMarket]:
        """Search markets by keyword term."""
        params: dict[str, str] = {"term": term, "limit": str(limit)}
        data = await self._request("/search-markets", params)
        if not isinstance(data, list):
            return []
        return [ManifoldMarket.model_validate(item) for item in data]

    async def get_market(self, market_id: str) -> ManifoldMarket:
        """Fetch a single market by its ID."""
        data = await self._request(f"/market/{market_id}")
        return ManifoldMarket.model_validate(data)

    async def get_market_by_slug(self, slug: str) -> ManifoldMarket:
        """Fetch a single market by its URL slug."""
        data = await self._request(f"/slug/{slug}")
        return ManifoldMarket.model_validate(data)

    async def get_bets(self, market_id: str, limit: int = 1000) -> list[ManifoldBet]:
        """Fetch bets for a market."""
        params: dict[str, str] = {"contractId": market_id, "limit": str(limit)}
        data = await self._request("/bets", params)
        if not isinstance(data, list):
            return []
        return [ManifoldBet.model_validate(item) for item in data]

    async def get_comments(self, market_id: str) -> list[ManifoldComment]:
        """Fetch comments for a market."""
        params: dict[str, str] = {"contractId": market_id}
        data = await self._request("/comments", params)
        if not isinstance(data, list):
            return []
        return [ManifoldComment.model_validate(item) for item in data]

    async def list_markets(
        self, limit: int = 500, before: str | None = None
    ) -> list[ManifoldMarket]:
        """List markets, optionally paginated with a cursor."""
        params: dict[str, str] = {"limit": str(limit)}
        if before is not None:
            params["before"] = before
        data = await self._request("/markets", params)
        if not isinstance(data, list):
            return []
        return [ManifoldMarket.model_validate(item) for item in data]

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
