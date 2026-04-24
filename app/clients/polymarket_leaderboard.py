"""Async client for Polymarket leaderboard endpoint.

The leaderboard REST endpoint is not publicly documented; this client is
best-effort and returns `[]` on 404 / network error so the orchestrator can
continue uninterrupted. A `base_url` argument is exposed so callers can point
to a different host (e.g. `lb-api.polymarket.com`) without code changes.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.core.logging import get_logger
from app.core.yaml_config import app_config

log = get_logger(__name__)


class PolymarketLeaderboardClient:
    """Async wrapper around Polymarket leaderboard."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        rate_limit: int = 10,
        timeout: float = 10.0,
    ) -> None:
        # Default to the CLOB base URL — users can override via kwarg.
        self._base_url = base_url or app_config.polymarket.clob_url
        self._timeout = timeout
        self._semaphore = asyncio.Semaphore(max(1, rate_limit))
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
                headers={"Accept": "application/json"},
            )
        return self._client

    async def fetch_leaderboard(
        self, timeframe: str = "monthly", limit: int = 100
    ) -> list[dict[str, Any]]:
        """GET /leaderboard?timeframe=...&limit=...

        Returns [] gracefully on 404 (endpoint unavailable) or transport error.
        """
        client = self._get_client()
        try:
            async with self._semaphore:
                resp = await client.get(
                    "/leaderboard",
                    params={"timeframe": timeframe, "limit": limit},
                )
            if resp.status_code == 404:
                log.warning(
                    "leaderboard_not_available",
                    timeframe=timeframe,
                    base_url=self._base_url,
                )
                return []
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as exc:
            log.warning(
                "leaderboard_fetch_failed",
                timeframe=timeframe,
                error=str(exc),
            )
            return []
        except ValueError as exc:
            log.warning(
                "leaderboard_decode_failed",
                timeframe=timeframe,
                error=str(exc),
            )
            return []

        if isinstance(data, dict):
            inner = data.get("data") or data.get("leaderboard") or []
            data = inner
        if not isinstance(data, list):
            return []
        return [e for e in data if isinstance(e, dict)]

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None
