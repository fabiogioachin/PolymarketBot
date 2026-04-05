"""Async REST client for Polymarket Gamma API and CLOB API."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

import httpx

from app.core.logging import get_logger
from app.core.yaml_config import app_config
from app.models.market import (
    Market,
    MarketCategory,
    MarketStatus,
    OrderBook,
    OrderBookLevel,
    Outcome,
    PriceHistory,
    PricePoint,
    ResolutionRules,
)

log = get_logger(__name__)

# ── Category mapping ─────────────────────────────────────────────────

_CATEGORY_MAP: dict[str, MarketCategory] = {
    "politics": MarketCategory.POLITICS,
    "political": MarketCategory.POLITICS,
    "geopolitics": MarketCategory.GEOPOLITICS,
    "economics": MarketCategory.ECONOMICS,
    "economy": MarketCategory.ECONOMICS,
    "crypto": MarketCategory.CRYPTO,
    "cryptocurrency": MarketCategory.CRYPTO,
    "sports": MarketCategory.SPORTS,
    "entertainment": MarketCategory.ENTERTAINMENT,
    "pop-culture": MarketCategory.ENTERTAINMENT,
    "science": MarketCategory.SCIENCE,
}


def _resolve_category(tags: list[dict[str, Any]]) -> MarketCategory:
    """Map Gamma API tag labels to our MarketCategory enum."""
    for tag in tags:
        label = str(tag.get("label", "")).lower().strip()
        if label in _CATEGORY_MAP:
            return _CATEGORY_MAP[label]
    return MarketCategory.OTHER


def _parse_market(data: dict[str, Any]) -> Market:
    """Parse a Gamma API market JSON object into our Market model."""
    # --- status ---
    if data.get("closed"):
        status = MarketStatus.CLOSED
    elif data.get("resolved"):
        status = MarketStatus.RESOLVED
    elif data.get("active"):
        status = MarketStatus.ACTIVE
    else:
        status = MarketStatus.CLOSED

    # --- outcomes + prices + token IDs ---
    raw_outcomes = data.get("outcomes", "")
    raw_prices = data.get("outcomePrices", "")
    raw_tokens = data.get("clobTokenIds", "")

    outcome_names: list[str] = (
        [s.strip().strip("[]\"'") for s in raw_outcomes.split(",") if s.strip()]
        if isinstance(raw_outcomes, str)
        else [str(o).strip("[]\"'") for o in raw_outcomes]
    )
    prices: list[float] = []
    if isinstance(raw_prices, str) and raw_prices:
        try:
            parsed = json.loads(raw_prices)
            prices = [float(p) for p in parsed]
        except (json.JSONDecodeError, ValueError):
            prices = [float(p) for p in raw_prices.split(",") if p.strip()]
    elif isinstance(raw_prices, list):
        prices = [float(p) for p in raw_prices]

    token_ids: list[str] = []
    if isinstance(raw_tokens, str) and raw_tokens:
        try:
            parsed = json.loads(raw_tokens)
            token_ids = [str(t) for t in parsed]
        except (json.JSONDecodeError, ValueError):
            token_ids = [s.strip() for s in raw_tokens.split(",") if s.strip()]
    elif isinstance(raw_tokens, list):
        token_ids = [str(t) for t in raw_tokens]

    outcomes: list[Outcome] = []
    for i, name in enumerate(outcome_names):
        outcomes.append(
            Outcome(
                token_id=token_ids[i] if i < len(token_ids) else "",
                outcome=name,
                price=prices[i] if i < len(prices) else 0.0,
            )
        )

    # --- tags ---
    raw_tags = data.get("tags", [])
    tag_labels = [str(t.get("label", "")) for t in raw_tags] if raw_tags else []

    # --- category ---
    category = _resolve_category(raw_tags or [])

    # --- resolution rules ---
    description = str(data.get("description", ""))
    resolution_rules = _extract_rules(description)

    # --- fee ---
    fee_raw = data.get("fee", 0)
    fee_rate = float(fee_raw) if fee_raw else 0.0
    # Sanity cap: Gamma API sometimes returns absurd fee values (e.g., 1e16)
    if fee_rate > 1.0:
        fee_rate = 0.02  # fallback to default 2%

    # --- timestamps ---
    end_date = _parse_dt(data.get("endDate"))
    created_at = _parse_dt(data.get("createdAt"))
    updated_at = _parse_dt(data.get("updatedAt"))

    return Market(
        id=str(data.get("id", "")),
        condition_id=str(data.get("conditionId", "")),
        slug=str(data.get("slug", "")),
        question=str(data.get("question", "")),
        description=description,
        category=category,
        status=status,
        outcomes=outcomes,
        resolution_rules=resolution_rules,
        end_date=end_date,
        volume=float(data.get("volume", 0) or 0),
        liquidity=float(data.get("liquidity", 0) or 0),
        volume_24h=float(data.get("volume24hr", 0) or 0),
        created_at=created_at,
        updated_at=updated_at,
        fee_rate=fee_rate,
        tags=tag_labels,
    )


def _parse_dt(raw: Any) -> datetime | None:
    """Parse an ISO datetime string or unix timestamp, returning None on failure."""
    if raw is None:
        return None
    if isinstance(raw, int | float):
        return datetime.fromtimestamp(raw, tz=UTC)
    try:
        text = str(raw)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except (ValueError, TypeError):
        return None


def _extract_rules(description: str) -> ResolutionRules:
    """Extract resolution rules from market description text."""
    if not description:
        return ResolutionRules()

    raw_text = description
    conditions: list[str] = []
    source = ""

    # Heuristic extraction: look for resolution-related sentences
    for line in description.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        line_lower = stripped.lower()
        # Lines mentioning resolution criteria
        if any(
            kw in line_lower
            for kw in ("resolve", "resolution", "will be determined", "settled")
        ):
            conditions.append(stripped)
        # Source extraction — prefer explicit "source:" over "according to"
        if "source:" in line_lower or ("according to" in line_lower and not source):
            source = stripped

    return ResolutionRules(
        source=source,
        conditions=conditions,
        raw_text=raw_text,
    )


# ── Client ───────────────────────────────────────────────────────────


class _TokenBucket:
    """Simple token-bucket rate limiter: allows `rate` requests per second."""

    def __init__(self, rate: float) -> None:
        self._rate = rate
        self._max_tokens = rate  # burst = 1 second worth
        self._tokens = rate
        self._last_refill = asyncio.get_event_loop().time() if rate > 0 else 0.0

    async def acquire(self) -> None:
        while True:
            now = asyncio.get_event_loop().time()
            elapsed = now - self._last_refill
            self._tokens = min(self._max_tokens, self._tokens + elapsed * self._rate)
            self._last_refill = now
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return
            wait = (1.0 - self._tokens) / self._rate
            await asyncio.sleep(wait)


class PolymarketRestClient:
    """Async REST client for Polymarket Gamma API."""

    def __init__(self) -> None:
        self._gamma_client: httpx.AsyncClient | None = None
        self._clob_client: httpx.AsyncClient | None = None
        self._rate_limiter = _TokenBucket(rate=app_config.polymarket.rate_limit)
        self._max_retries = app_config.polymarket.retry_max
        self._backoff = app_config.polymarket.retry_backoff

    def _get_gamma_client(self) -> httpx.AsyncClient:
        if self._gamma_client is None or self._gamma_client.is_closed:
            self._gamma_client = httpx.AsyncClient(
                base_url=app_config.polymarket.base_url,
                timeout=30.0,
                headers={"Accept": "application/json"},
            )
        return self._gamma_client

    def _get_clob_client(self) -> httpx.AsyncClient:
        if self._clob_client is None or self._clob_client.is_closed:
            self._clob_client = httpx.AsyncClient(
                base_url=app_config.polymarket.clob_url,
                timeout=30.0,
                headers={"Accept": "application/json"},
            )
        return self._clob_client

    async def _request(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Execute an HTTP request with rate limiting and retry."""
        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            await self._rate_limiter.acquire()
            try:
                resp = await client.request(method, url, params=params)
                if resp.status_code == 429 or resp.status_code >= 500:
                    wait = self._backoff * (2**attempt)
                    log.warning(
                        "retryable_status",
                        status=resp.status_code,
                        attempt=attempt + 1,
                        wait=wait,
                        url=url,
                    )
                    await asyncio.sleep(wait)
                    continue
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                if exc.response.status_code == 429 or exc.response.status_code >= 500:
                    wait = self._backoff * (2**attempt)
                    log.warning(
                        "retryable_error",
                        status=exc.response.status_code,
                        attempt=attempt + 1,
                        wait=wait,
                    )
                    await asyncio.sleep(wait)
                    continue
                raise
            except httpx.RequestError as exc:
                last_exc = exc
                if attempt < self._max_retries:
                    wait = self._backoff * (2**attempt)
                    log.warning(
                        "request_error",
                        error=str(exc),
                        attempt=attempt + 1,
                        wait=wait,
                    )
                    await asyncio.sleep(wait)
                    continue
                raise
        # All retries exhausted
        if last_exc is not None:
            raise last_exc
        msg = f"All {self._max_retries + 1} attempts failed for {url}"
        raise RuntimeError(msg)

    async def list_markets(
        self,
        *,
        active: bool = True,
        closed: bool = False,
        limit: int = 100,
        offset: int = 0,
        order: str = "volume",
        ascending: bool = False,
        tag: str | None = None,
    ) -> list[Market]:
        """GET /markets with filters. Parse each into Market model."""
        params: dict[str, Any] = {
            "limit": limit,
            "offset": offset,
            "order": order,
            "ascending": ascending,
        }
        if active:
            params["active"] = True
        if not closed:
            params["closed"] = False
        if tag:
            params["tag_id"] = tag

        data = await self._request(
            self._get_gamma_client(), "GET", "/markets", params=params
        )
        markets_raw = data if isinstance(data, list) else data.get("data", data)
        if not isinstance(markets_raw, list):
            markets_raw = []

        result: list[Market] = []
        for item in markets_raw:
            try:
                result.append(_parse_market(item))
            except Exception:
                log.warning("parse_market_failed", market_id=item.get("id"))
        return result

    async def get_market(self, market_id: str) -> Market:
        """GET /markets/{id}. Returns full Market with outcomes."""
        data = await self._request(
            self._get_gamma_client(), "GET", f"/markets/{market_id}"
        )
        return _parse_market(data)

    async def get_orderbook(self, token_id: str) -> OrderBook:
        """GET /book from CLOB API. Returns parsed OrderBook with spread/midpoint."""
        data = await self._request(
            self._get_clob_client(), "GET", "/book", params={"token_id": token_id}
        )

        bids = [
            OrderBookLevel(price=float(b["price"]), size=float(b["size"]))
            for b in data.get("bids", [])
        ]
        asks = [
            OrderBookLevel(price=float(a["price"]), size=float(a["size"]))
            for a in data.get("asks", [])
        ]

        best_bid = max((b.price for b in bids), default=0.0)
        best_ask = min((a.price for a in asks), default=0.0)
        spread = best_ask - best_bid if best_ask > 0 and best_bid > 0 else 0.0
        midpoint = (best_ask + best_bid) / 2 if best_ask > 0 and best_bid > 0 else 0.0

        return OrderBook(
            market_id=str(data.get("market", "")),
            asset_id=str(data.get("asset_id", "")),
            bids=bids,
            asks=asks,
            spread=round(spread, 6),
            midpoint=round(midpoint, 6),
            timestamp=datetime.now(tz=UTC),
        )

    async def get_price_history(
        self, token_id: str, *, interval: str = "1d", fidelity: int = 60
    ) -> PriceHistory:
        """GET /prices-history. Returns PriceHistory with points."""
        data = await self._request(
            self._get_clob_client(),
            "GET",
            "/prices-history",
            params={"market": token_id, "interval": interval, "fidelity": fidelity},
        )

        history = data.get("history", [])
        points = [
            PricePoint(
                timestamp=datetime.fromtimestamp(int(p["t"]), tz=UTC),
                price=float(p["p"]),
            )
            for p in history
        ]

        return PriceHistory(
            market_id=token_id,
            token_id=token_id,
            points=points,
        )

    async def get_market_rules(self, market_id: str) -> ResolutionRules:
        """Extract resolution rules from market description/rules text."""
        market = await self.get_market(market_id)
        return market.resolution_rules

    async def close(self) -> None:
        """Close the underlying HTTP clients."""
        if self._gamma_client and not self._gamma_client.is_closed:
            await self._gamma_client.aclose()
        if self._clob_client and not self._clob_client.is_closed:
            await self._clob_client.aclose()


# Module-level singleton (lazy — clients created on first use)
polymarket_rest = PolymarketRestClient()
