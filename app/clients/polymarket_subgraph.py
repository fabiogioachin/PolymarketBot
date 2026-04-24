"""Async GraphQL client for the Polymarket Subgraph on The Graph.

Used by :class:`WhaleOrchestrator` to enrich `whale_trades` with per-wallet
aggregates (total PnL, weekly PnL, volume rank) that satisfy the D4 whale
criteria from Phase 13.

The free tier of The Graph gateway allows 100k queries/month without an API
key.  When `THEGRAPH_API_KEY` is set an `Authorization: Bearer <key>` header
is attached automatically (needed for higher quotas).

Every public method is defensive: on HTTP errors, missing fields, or unknown
schema shapes the client returns sensible empty values (`None` for scalars,
`[]` for lists) and emits a `warning` log.  The caller (whale orchestrator)
must never fail its tick because of subgraph flakiness.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import httpx

from app.core.logging import get_logger

log = get_logger(__name__)


# ── GraphQL query templates ──────────────────────────────────────────────
#
# These are hardcoded strings rather than files on disk so the client stays
# a single self-contained module.  Field names follow the public Polymarket
# subgraph schema published on The Graph explorer.  If the upstream schema
# drifts we fall back to `None` / `[]` rather than raising.

_QUERY_WALLET_PNL = """
query WalletPnl($wallet: ID!) {
  user(id: $wallet) {
    id
    profit
    weeklyProfit
  }
}
""".strip()

_QUERY_WALLET_VOLUME_RANK = """
query WalletVolumeRank($wallet: ID!) {
  user(id: $wallet) {
    id
    usdcVolume
    volumeRank
  }
}
""".strip()

_QUERY_TOP_TRADERS = """
query TopTraders($limit: Int!, $timeframe: String!) {
  users(
    first: $limit
    orderBy: profit
    orderDirection: desc
    where: { timeframe: $timeframe }
  ) {
    id
    profit
    usdcVolume
    winRate
  }
}
""".strip()

_QUERY_TRADES_FOR_MARKET = """
query TradesForMarket($market: String!, $since: BigInt!) {
  trades(
    where: { market: $market, timestamp_gte: $since }
    orderBy: timestamp
    orderDirection: desc
    first: 100
  ) {
    id
    timestamp
    taker
    maker
    side
    size
    price
  }
}
""".strip()


# ── Simple in-memory TTL cache ───────────────────────────────────────────


class _TTLCache:
    """Minimal `{key: (value, expires_at)}` cache with wallclock TTL.

    Not thread-safe but fine for the single-loop asyncio world.  Used so we
    do not re-query the subgraph for every whale trade from the same wallet
    during the same hour.
    """

    def __init__(self, ttl_seconds: float) -> None:
        self._ttl = max(0.0, float(ttl_seconds))
        self._store: dict[str, tuple[Any, float]] = {}

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if time.monotonic() >= expires_at:
            # Expired — drop it so the caller sees a miss.
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        self._store[key] = (value, time.monotonic() + self._ttl)

    def clear(self) -> None:
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)


# ── Client ───────────────────────────────────────────────────────────────


class PolymarketSubgraphClient:
    """Async GraphQL wrapper for the Polymarket Subgraph.

    Parameters
    ----------
    endpoint:
        Full HTTPS URL of the subgraph (The Graph gateway URL).
    api_key:
        Optional The Graph API key.  When ``None`` the client reads
        ``THEGRAPH_API_KEY`` from the environment.  A missing key is fine —
        the gateway serves the free tier without authentication.
    timeout:
        Per-request timeout in seconds (default 10s).
    rate_limit_per_minute:
        Soft rate limit.  The client guarantees at most this many outgoing
        requests per 60-second sliding window.
    cache_ttl_seconds:
        TTL for the per-wallet aggregates cache.  Defaults to one hour.
    """

    def __init__(
        self,
        endpoint: str,
        api_key: str | None = None,
        timeout: float = 10.0,
        *,
        rate_limit_per_minute: int = 100,
        cache_ttl_seconds: float = 3600.0,
    ) -> None:
        self._endpoint = endpoint
        self._api_key = api_key if api_key is not None else os.getenv("THEGRAPH_API_KEY")
        self._timeout = timeout
        self._rate_limit = max(1, int(rate_limit_per_minute))
        self._request_timestamps: list[float] = []
        self._rate_lock = asyncio.Lock()
        self._client: httpx.AsyncClient | None = None
        # Cache: wallet_address -> {"total_pnl": float|None, "weekly_pnl": float|None,
        #                           "volume_rank": int|None}
        self._wallet_cache: _TTLCache = _TTLCache(cache_ttl_seconds)

    # ── Internal helpers ────────────────────────────────────────────────

    def _build_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                headers=self._build_headers(),
            )
        return self._client

    async def _rate_gate(self) -> None:
        """Enforce the configured requests-per-minute ceiling."""
        async with self._rate_lock:
            now = time.monotonic()
            window_start = now - 60.0
            self._request_timestamps = [
                t for t in self._request_timestamps if t > window_start
            ]
            if len(self._request_timestamps) >= self._rate_limit:
                wait = 60.0 - (now - self._request_timestamps[0])
                if wait > 0:
                    await asyncio.sleep(wait)
                    now = time.monotonic()
                    window_start = now - 60.0
                    self._request_timestamps = [
                        t for t in self._request_timestamps if t > window_start
                    ]
            self._request_timestamps.append(now)

    # ── Public API ──────────────────────────────────────────────────────

    @property
    def cache(self) -> _TTLCache:
        """Expose the internal TTL cache (used in tests and by orchestrators)."""
        return self._wallet_cache

    async def query(
        self, query: str, variables: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Execute a GraphQL POST. Returns the parsed ``data`` field.

        Returns ``{}`` on transport error, non-200 status, or malformed JSON.
        Never raises for network issues so callers can fail-soft.
        """
        await self._rate_gate()
        payload: dict[str, Any] = {"query": query}
        if variables is not None:
            payload["variables"] = variables

        client = self._get_client()
        try:
            resp = await client.post(self._endpoint, json=payload)
        except httpx.HTTPError as exc:
            log.warning(
                "subgraph_request_failed",
                endpoint=self._endpoint,
                error=str(exc),
            )
            return {}

        if resp.status_code != 200:
            log.warning(
                "subgraph_bad_status",
                endpoint=self._endpoint,
                status=resp.status_code,
                body=resp.text[:200],
            )
            return {}

        try:
            body = resp.json()
        except ValueError as exc:
            log.warning("subgraph_decode_failed", error=str(exc))
            return {}

        if not isinstance(body, dict):
            log.warning("subgraph_unexpected_body", body_type=type(body).__name__)
            return {}

        if body.get("errors"):
            log.warning("subgraph_graphql_errors", errors=body.get("errors"))
            # Some GraphQL errors still carry partial data — return it if present
            # so downstream callers can extract what they can.
        data = body.get("data")
        if not isinstance(data, dict):
            return {}
        return data

    async def wallet_pnl_aggregates(
        self, wallet_address: str
    ) -> dict[str, float | None]:
        """Return ``{"total_pnl": .., "weekly_pnl": ..}`` for a wallet.

        Both values are ``None`` when the wallet is unknown or the schema
        fields are missing.
        """
        if not wallet_address:
            return {"total_pnl": None, "weekly_pnl": None}

        data = await self.query(
            _QUERY_WALLET_PNL, {"wallet": wallet_address.lower()}
        )
        user = data.get("user") if isinstance(data, dict) else None
        if not isinstance(user, dict):
            return {"total_pnl": None, "weekly_pnl": None}
        return {
            "total_pnl": _to_float_or_none(user.get("profit")),
            "weekly_pnl": _to_float_or_none(user.get("weeklyProfit")),
        }

    async def wallet_volume_rank(self, wallet_address: str) -> int | None:
        """Return the wallet's rank by usdcVolume, or ``None`` if unknown."""
        if not wallet_address:
            return None
        data = await self.query(
            _QUERY_WALLET_VOLUME_RANK, {"wallet": wallet_address.lower()}
        )
        user = data.get("user") if isinstance(data, dict) else None
        if not isinstance(user, dict):
            return None
        rank = user.get("volumeRank")
        try:
            return int(rank) if rank is not None else None
        except (TypeError, ValueError):
            return None

    async def top_traders_by_pnl(
        self, limit: int = 100, timeframe: str = "monthly"
    ) -> list[dict[str, Any]]:
        """Return up to ``limit`` top traders ordered by PnL for ``timeframe``.

        Each row is the raw dict from the subgraph (``id``, ``profit``,
        ``usdcVolume``, ``winRate``).  An empty list is returned on error.
        """
        data = await self.query(
            _QUERY_TOP_TRADERS, {"limit": int(limit), "timeframe": timeframe}
        )
        users = data.get("users") if isinstance(data, dict) else None
        if not isinstance(users, list):
            return []
        return [u for u in users if isinstance(u, dict)]

    async def trades_for_market(
        self, market_id: str, since_unix: int
    ) -> list[dict[str, Any]]:
        """Return raw trade rows for ``market_id`` with ``timestamp >= since_unix``."""
        data = await self.query(
            _QUERY_TRADES_FOR_MARKET,
            {"market": market_id, "since": str(int(since_unix))},
        )
        trades = data.get("trades") if isinstance(data, dict) else None
        if not isinstance(trades, list):
            return []
        return [t for t in trades if isinstance(t, dict)]

    async def get_wallet_enrichment(
        self, wallet_address: str
    ) -> dict[str, Any]:
        """Cache-aware fetch of all 3 aggregate fields for ``wallet_address``.

        Shape: ``{"total_pnl": float|None, "weekly_pnl": float|None,
        "volume_rank": int|None}``.  On a cache hit no HTTP request is made.
        """
        cached = self._wallet_cache.get(wallet_address)
        if cached is not None:
            return dict(cached)

        pnl = await self.wallet_pnl_aggregates(wallet_address)
        rank = await self.wallet_volume_rank(wallet_address)
        enrichment = {
            "total_pnl": pnl.get("total_pnl"),
            "weekly_pnl": pnl.get("weekly_pnl"),
            "volume_rank": rank,
        }
        self._wallet_cache.set(wallet_address, enrichment)
        return dict(enrichment)

    async def close(self) -> None:
        """Close the underlying httpx client (idempotent)."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None


def _to_float_or_none(raw: Any) -> float | None:
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None
