"""Tests for Polymarket REST client."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import httpx
import pytest
import respx

from app.clients.polymarket_rest import PolymarketRestClient, _parse_market
from app.models.market import (
    MarketCategory,
    MarketStatus,
)

# ── Fixtures ─────────────────────────────────────────────────────────

GAMMA_BASE = "https://gamma-api.polymarket.com"
CLOB_BASE = "https://clob.polymarket.com"


def _sample_market_json(
    *,
    market_id: str = "market-123",
    active: bool = True,
    closed: bool = False,
) -> dict[str, Any]:
    """Realistic Gamma API market response."""
    return {
        "id": market_id,
        "conditionId": "cond-abc",
        "slug": "will-x-happen-by-2025",
        "question": "Will X happen by 2025?",
        "description": (
            "This market will resolve to Yes if X happens.\n"
            "Resolution source: Associated Press.\n"
            "The market will be settled according to official data."
        ),
        "outcomes": "Yes,No",
        "outcomePrices": '[\"0.65\",\"0.35\"]',
        "clobTokenIds": '[\"token-yes-1\",\"token-no-1\"]',
        "active": active,
        "closed": closed,
        "resolved": False,
        "volume": 125000.50,
        "liquidity": 45000.0,
        "volume24hr": 8500.25,
        "endDate": "2025-12-31T23:59:59Z",
        "createdAt": "2024-06-01T10:00:00Z",
        "updatedAt": "2024-11-15T12:30:00Z",
        "fee": 0.0,
        "tags": [
            {"id": "1", "label": "Politics"},
            {"id": "2", "label": "US"},
        ],
    }


def _sample_orderbook_json() -> dict[str, Any]:
    return {
        "market": "market-123",
        "asset_id": "token-yes-1",
        "bids": [
            {"price": "0.63", "size": "500"},
            {"price": "0.62", "size": "1000"},
            {"price": "0.60", "size": "2000"},
        ],
        "asks": [
            {"price": "0.67", "size": "400"},
            {"price": "0.68", "size": "800"},
            {"price": "0.70", "size": "1500"},
        ],
    }


def _sample_price_history_json() -> dict[str, Any]:
    return {
        "history": [
            {"t": 1700000000, "p": 0.55},
            {"t": 1700086400, "p": 0.58},
            {"t": 1700172800, "p": 0.62},
            {"t": 1700259200, "p": 0.65},
        ]
    }


@pytest.fixture()
def client() -> PolymarketRestClient:
    c = PolymarketRestClient()
    # Use small backoff for tests
    c._backoff = 0.01
    return c


# ── _parse_market unit tests ────────────────────────────────────────


class TestParseMarket:
    def test_basic_fields(self) -> None:
        data = _sample_market_json()
        market = _parse_market(data)
        assert market.id == "market-123"
        assert market.condition_id == "cond-abc"
        assert market.slug == "will-x-happen-by-2025"
        assert market.question == "Will X happen by 2025?"
        assert market.status == MarketStatus.ACTIVE
        assert market.volume == 125000.50
        assert market.liquidity == 45000.0
        assert market.volume_24h == 8500.25
        assert market.fee_rate == 0.0

    def test_outcomes_parsed(self) -> None:
        data = _sample_market_json()
        market = _parse_market(data)
        assert len(market.outcomes) == 2
        assert market.outcomes[0].outcome == "Yes"
        assert market.outcomes[0].token_id == "token-yes-1"
        assert market.outcomes[0].price == 0.65
        assert market.outcomes[1].outcome == "No"
        assert market.outcomes[1].price == 0.35

    def test_category_from_tags(self) -> None:
        data = _sample_market_json()
        market = _parse_market(data)
        assert market.category == MarketCategory.POLITICS

    def test_closed_status(self) -> None:
        data = _sample_market_json(active=False, closed=True)
        market = _parse_market(data)
        assert market.status == MarketStatus.CLOSED

    def test_tags_extracted(self) -> None:
        data = _sample_market_json()
        market = _parse_market(data)
        assert "Politics" in market.tags
        assert "US" in market.tags

    def test_timestamps_parsed(self) -> None:
        data = _sample_market_json()
        market = _parse_market(data)
        assert market.end_date is not None
        assert market.end_date.year == 2025
        assert market.created_at is not None
        assert market.created_at.year == 2024

    def test_resolution_rules_extracted(self) -> None:
        data = _sample_market_json()
        market = _parse_market(data)
        rules = market.resolution_rules
        assert rules.raw_text != ""
        assert any("resolve" in c.lower() for c in rules.conditions)
        assert "Associated Press" in rules.source

    def test_missing_optional_fields(self) -> None:
        """Market with minimal data should still parse."""
        data = {
            "id": "minimal-1",
            "question": "Minimal market?",
            "outcomes": "Yes,No",
            "outcomePrices": "",
            "clobTokenIds": "",
            "active": True,
        }
        market = _parse_market(data)
        assert market.id == "minimal-1"
        assert len(market.outcomes) == 2
        assert market.outcomes[0].price == 0.0
        assert market.outcomes[0].token_id == ""

    def test_comma_separated_prices(self) -> None:
        """Handle outcomePrices as comma-separated (not JSON array)."""
        data = _sample_market_json()
        data["outcomePrices"] = "0.70,0.30"
        market = _parse_market(data)
        assert market.outcomes[0].price == 0.70
        assert market.outcomes[1].price == 0.30


# ── Client integration tests (respx mocked) ─────────────────────────


class TestListMarkets:
    @respx.mock
    @pytest.mark.asyncio()
    async def test_returns_parsed_markets(self, client: PolymarketRestClient) -> None:
        respx.get(f"{GAMMA_BASE}/markets").mock(
            return_value=httpx.Response(
                200,
                json=[_sample_market_json(), _sample_market_json(market_id="market-456")],
            )
        )
        markets = await client.list_markets()
        await client.close()

        assert len(markets) == 2
        assert markets[0].id == "market-123"
        assert markets[1].id == "market-456"
        assert markets[0].status == MarketStatus.ACTIVE

    @respx.mock
    @pytest.mark.asyncio()
    async def test_empty_response(self, client: PolymarketRestClient) -> None:
        respx.get(f"{GAMMA_BASE}/markets").mock(
            return_value=httpx.Response(200, json=[])
        )
        markets = await client.list_markets()
        await client.close()
        assert markets == []


class TestGetMarket:
    @respx.mock
    @pytest.mark.asyncio()
    async def test_returns_single_market(self, client: PolymarketRestClient) -> None:
        respx.get(f"{GAMMA_BASE}/markets/market-123").mock(
            return_value=httpx.Response(200, json=_sample_market_json())
        )
        market = await client.get_market("market-123")
        await client.close()

        assert market.id == "market-123"
        assert market.question == "Will X happen by 2025?"
        assert len(market.outcomes) == 2


class TestGetOrderbook:
    @respx.mock
    @pytest.mark.asyncio()
    async def test_returns_orderbook_with_spread(
        self, client: PolymarketRestClient
    ) -> None:
        respx.get(f"{CLOB_BASE}/book").mock(
            return_value=httpx.Response(200, json=_sample_orderbook_json())
        )
        ob = await client.get_orderbook("token-yes-1")
        await client.close()

        assert ob.market_id == "market-123"
        assert ob.asset_id == "token-yes-1"
        assert len(ob.bids) == 3
        assert len(ob.asks) == 3
        # best bid = 0.63, best ask = 0.67
        assert ob.spread == pytest.approx(0.04, abs=1e-4)
        assert ob.midpoint == pytest.approx(0.65, abs=1e-4)

    @respx.mock
    @pytest.mark.asyncio()
    async def test_empty_orderbook(self, client: PolymarketRestClient) -> None:
        respx.get(f"{CLOB_BASE}/book").mock(
            return_value=httpx.Response(
                200, json={"market": "m1", "asset_id": "t1", "bids": [], "asks": []}
            )
        )
        ob = await client.get_orderbook("t1")
        await client.close()

        assert ob.spread == 0.0
        assert ob.midpoint == 0.0


class TestGetPriceHistory:
    @respx.mock
    @pytest.mark.asyncio()
    async def test_returns_price_points(self, client: PolymarketRestClient) -> None:
        respx.get(f"{CLOB_BASE}/prices-history").mock(
            return_value=httpx.Response(200, json=_sample_price_history_json())
        )
        ph = await client.get_price_history("token-yes-1")
        await client.close()

        assert ph.token_id == "token-yes-1"
        assert len(ph.points) == 4
        assert ph.points[0].price == 0.55
        assert ph.points[-1].price == 0.65
        assert isinstance(ph.points[0].timestamp, datetime)


class TestGetMarketRules:
    @respx.mock
    @pytest.mark.asyncio()
    async def test_extracts_rules_from_market(
        self, client: PolymarketRestClient
    ) -> None:
        respx.get(f"{GAMMA_BASE}/markets/market-123").mock(
            return_value=httpx.Response(200, json=_sample_market_json())
        )
        rules = await client.get_market_rules("market-123")
        await client.close()

        assert rules.raw_text != ""
        assert any("resolve" in c.lower() for c in rules.conditions)


class TestRetryBehavior:
    @respx.mock
    @pytest.mark.asyncio()
    async def test_retries_on_429(self, client: PolymarketRestClient) -> None:
        route = respx.get(f"{GAMMA_BASE}/markets/retry-test")
        route.side_effect = [
            httpx.Response(429, text="rate limited"),
            httpx.Response(429, text="rate limited"),
            httpx.Response(200, json=_sample_market_json(market_id="retry-test")),
        ]
        market = await client.get_market("retry-test")
        await client.close()

        assert market.id == "retry-test"
        assert route.call_count == 3

    @respx.mock
    @pytest.mark.asyncio()
    async def test_retries_on_500(self, client: PolymarketRestClient) -> None:
        route = respx.get(f"{GAMMA_BASE}/markets/server-err")
        route.side_effect = [
            httpx.Response(500, text="server error"),
            httpx.Response(200, json=_sample_market_json(market_id="server-err")),
        ]
        market = await client.get_market("server-err")
        await client.close()

        assert market.id == "server-err"
        assert route.call_count == 2

    @respx.mock
    @pytest.mark.asyncio()
    async def test_raises_after_max_retries(
        self, client: PolymarketRestClient
    ) -> None:
        respx.get(f"{GAMMA_BASE}/markets/always-fail").mock(
            return_value=httpx.Response(500, text="always fails")
        )
        with pytest.raises(RuntimeError, match="All .* attempts failed"):
            await client.get_market("always-fail")
        await client.close()


class TestRateLimiting:
    @respx.mock
    @pytest.mark.asyncio()
    async def test_token_bucket_rate_limits(self) -> None:
        """Verify the token bucket enforces rate limiting."""
        from app.clients.polymarket_rest import _TokenBucket

        client = PolymarketRestClient()
        client._backoff = 0.01
        # Set rate to 10 req/s — burst of 10 tokens
        client._rate_limiter = _TokenBucket(rate=10)

        call_count = 0

        async def fast_response(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(200, json=_sample_market_json())

        respx.get(f"{GAMMA_BASE}/markets/rate-test").mock(side_effect=fast_response)

        tasks = [client.get_market("rate-test") for _ in range(5)]
        results = await asyncio.gather(*tasks)
        await client.close()

        assert len(results) == 5
        assert call_count == 5
