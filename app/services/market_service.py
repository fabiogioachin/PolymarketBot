"""Market service: caching, filtering, and market data access."""

import time
from datetime import UTC, datetime
from typing import Any

from app.clients.polymarket_rest import polymarket_rest
from app.core.logging import get_logger
from app.models.market import Market, MarketCategory
from app.services.market_scanner import MarketScanner

logger = get_logger(__name__)

_DEFAULT_TTL = 300  # 5 minutes


class MarketService:
    """Cached access to market data with filtering."""

    def __init__(self, ttl: int = _DEFAULT_TTL) -> None:
        self._cache: dict[str, tuple[float, Any]] = {}
        self._ttl = ttl
        self._scanner = MarketScanner()

    def _get_cached(self, key: str) -> Any | None:
        if key in self._cache:
            ts, value = self._cache[key]
            if time.monotonic() - ts < self._ttl:
                return value
            del self._cache[key]
        return None

    def _set_cached(self, key: str, value: Any) -> None:
        self._cache[key] = (time.monotonic(), value)

    async def get_markets(
        self,
        *,
        active: bool = True,
        limit: int = 100,
        min_liquidity: float = 0.0,
        min_volume: float = 0.0,
        category: MarketCategory | None = None,
    ) -> list[Market]:
        """Get markets with optional filtering. Results are TTL-cached."""
        cache_key = f"markets:{active}:{limit}:{min_liquidity}:{min_volume}:{category}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        markets = await polymarket_rest.list_markets(
            active=active, closed=False, limit=limit
        )

        # Apply filters
        now = datetime.now(tz=UTC)
        filtered: list[Market] = []
        for m in markets:
            if min_liquidity > 0 and m.liquidity < min_liquidity:
                continue
            if min_volume > 0 and m.volume < min_volume:
                continue
            if category is not None and self._scanner.classify(m) != category:
                continue
            # Skip expired/closed/resolved markets
            if m.end_date and m.end_date < now:
                continue
            if m.status.value in ("closed", "resolved"):
                continue
            filtered.append(m)

        self._set_cached(cache_key, filtered)
        logger.info("markets_fetched", count=len(filtered), total=len(markets))
        return filtered

    async def get_filtered_markets(
        self,
        *,
        limit: int = 100,
        min_liquidity: float = 0.0,
        min_volume: float = 0.0,
        category: MarketCategory | None = None,
    ) -> list[Market]:
        """Get tradeable markets with sensible defaults for the trading loop.

        Note: Gamma API returns liquidity=0.0 for most markets, so we
        filter primarily on volume (min 100 USDC lifetime volume).
        """
        return await self.get_markets(
            active=True,
            limit=limit,
            min_liquidity=min_liquidity,
            min_volume=min_volume,
            category=category,
        )

    async def get_market(self, market_id: str) -> Market:
        """Get a single market by ID, cached."""
        cache_key = f"market:{market_id}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        market = await polymarket_rest.get_market(market_id)
        self._set_cached(cache_key, market)
        return market

    def clear_cache(self) -> None:
        """Clear all cached data."""
        self._cache.clear()

    @property
    def scanner(self) -> MarketScanner:
        return self._scanner
