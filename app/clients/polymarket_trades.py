"""Async client for Polymarket CLOB `/trades` endpoint.

Fetches the recent trade tape for a market so the whale detector can
spot large orders (size_usd >= threshold) and pre-resolution activity.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.core.logging import get_logger
from app.core.yaml_config import app_config

log = get_logger(__name__)


class PolymarketTradesClient:
    """Async wrapper around Polymarket CLOB `/trades`.

    Uses an asyncio semaphore as a lightweight rate limiter (default 20 rps).
    The endpoint is best-effort — Polymarket does not publish a stable schema,
    so callers must parse defensively.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        rate_limit: int = 20,
        timeout: float = 10.0,
    ) -> None:
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

    async def fetch_recent_trades(
        self, market_id: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        """GET /trades?market={id}&limit={limit}.

        Returns a list of raw trade dicts on success. On transport errors,
        timeouts, or unexpected shape returns `[]` and logs a warning so the
        caller can continue without raising.
        """
        client = self._get_client()
        try:
            async with self._semaphore:
                resp = await client.get(
                    "/trades",
                    params={"market": market_id, "limit": limit},
                )
            if resp.status_code == 404:
                log.info("trades_not_found", market_id=market_id)
                return []
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as exc:
            log.warning(
                "trades_fetch_failed",
                market_id=market_id,
                error=str(exc),
            )
            return []
        except ValueError as exc:  # JSON decode
            log.warning(
                "trades_decode_failed",
                market_id=market_id,
                error=str(exc),
            )
            return []

        if isinstance(data, dict):
            # Some envelope shapes use {"data": [...]} or {"trades": [...]}
            inner = data.get("data") or data.get("trades") or []
            data = inner
        if not isinstance(data, list):
            return []
        return [t for t in data if isinstance(t, dict)]

    async def close(self) -> None:
        """Close the underlying httpx client."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None
