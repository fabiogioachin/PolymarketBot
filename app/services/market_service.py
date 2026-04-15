"""Market service: caching, filtering, and market data access."""

import time
from datetime import UTC, datetime, timedelta
from typing import Any

from app.clients.polymarket_rest import polymarket_rest
from app.core.logging import get_logger
from app.models.market import Market, MarketCategory, MarketStatus, Outcome
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
        Falls back to static demo markets if the Polymarket API is unavailable.
        """
        try:
            return await self.get_markets(
                active=True,
                limit=limit,
                min_liquidity=min_liquidity,
                min_volume=min_volume,
                category=category,
            )
        except Exception as exc:
            logger.warning("market_api_unavailable_using_demo", error=str(exc))
            return self._demo_markets()

    def _demo_markets(self) -> list[Market]:
        """Return static demo markets for dry_run when Polymarket API is offline."""
        now = datetime.now(tz=UTC)
        return [
            Market(
                id="demo-politics-1",
                question="Will Congress pass a major budget bill before the deadline?",
                category=MarketCategory.POLITICS,
                outcomes=[
                    Outcome(token_id="demo-token-pol-1-yes", outcome="Yes", price=0.62),
                    Outcome(token_id="demo-token-pol-1-no", outcome="No", price=0.38),
                ],
                end_date=now + timedelta(days=7),
                volume=75_000.0,
                liquidity=15_000.0,
                status=MarketStatus.ACTIVE,
            ),
            Market(
                id="demo-politics-2",
                question="Will a third-party candidate win a US Senate seat this year?",
                category=MarketCategory.POLITICS,
                outcomes=[
                    Outcome(token_id="demo-token-pol-2-yes", outcome="Yes", price=0.18),
                    Outcome(token_id="demo-token-pol-2-no", outcome="No", price=0.82),
                ],
                end_date=now + timedelta(days=2),
                volume=45_000.0,
                liquidity=8_000.0,
                status=MarketStatus.ACTIVE,
            ),
            Market(
                id="demo-geopolitics-1",
                question="Will there be a diplomatic breakthrough in the Ukraine conflict?",
                category=MarketCategory.GEOPOLITICS,
                outcomes=[
                    Outcome(token_id="demo-token-geo-1-yes", outcome="Yes", price=0.28),
                    Outcome(token_id="demo-token-geo-1-no", outcome="No", price=0.72),
                ],
                end_date=now + timedelta(days=14),
                volume=120_000.0,
                liquidity=25_000.0,
                status=MarketStatus.ACTIVE,
            ),
            Market(
                id="demo-economics-1",
                question="Will the Federal Reserve announce a rate pause in the next meeting?",
                category=MarketCategory.ECONOMICS,
                outcomes=[
                    Outcome(token_id="demo-token-eco-1-yes", outcome="Yes", price=0.58),
                    Outcome(token_id="demo-token-eco-1-no", outcome="No", price=0.42),
                ],
                end_date=now + timedelta(days=10),
                volume=200_000.0,
                liquidity=40_000.0,
                status=MarketStatus.ACTIVE,
            ),
            Market(
                id="demo-economics-2",
                question="Will US unemployment rise above 5% this quarter?",
                category=MarketCategory.ECONOMICS,
                outcomes=[
                    Outcome(token_id="demo-token-eco-2-yes", outcome="Yes", price=0.32),
                    Outcome(token_id="demo-token-eco-2-no", outcome="No", price=0.68),
                ],
                end_date=now + timedelta(days=2),
                volume=55_000.0,
                liquidity=12_000.0,
                status=MarketStatus.ACTIVE,
            ),
            Market(
                id="demo-crypto-1",
                question="Will Bitcoin price exceed $90,000 this month?",
                category=MarketCategory.CRYPTO,
                outcomes=[
                    Outcome(token_id="demo-token-cry-1-yes", outcome="Yes", price=0.52),
                    Outcome(token_id="demo-token-cry-1-no", outcome="No", price=0.48),
                ],
                end_date=now + timedelta(days=20),
                volume=300_000.0,
                liquidity=60_000.0,
                status=MarketStatus.ACTIVE,
            ),
            Market(
                id="demo-sports-1",
                question="Will the home team win the next major championship final?",
                category=MarketCategory.SPORTS,
                outcomes=[
                    Outcome(token_id="demo-token-spt-1-yes", outcome="Yes", price=0.45),
                    Outcome(token_id="demo-token-spt-1-no", outcome="No", price=0.55),
                ],
                end_date=now + timedelta(days=25),
                volume=90_000.0,
                liquidity=18_000.0,
                status=MarketStatus.ACTIVE,
            ),
            Market(
                id="demo-geopolitics-2",
                question="Will NATO formally expand membership in the next six months?",
                category=MarketCategory.GEOPOLITICS,
                outcomes=[
                    Outcome(token_id="demo-token-geo-2-yes", outcome="Yes", price=0.70),
                    Outcome(token_id="demo-token-geo-2-no", outcome="No", price=0.30),
                ],
                end_date=now + timedelta(days=45),
                volume=65_000.0,
                liquidity=13_000.0,
                status=MarketStatus.ACTIVE,
            ),
        ]

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
