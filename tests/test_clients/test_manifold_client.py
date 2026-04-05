"""Tests for Manifold Markets async client."""

from __future__ import annotations

import httpx
import pytest
import respx

from app.clients.manifold_client import ManifoldClient

_BASE = "https://api.manifold.markets/v0"


@pytest.fixture()
def client() -> ManifoldClient:
    return ManifoldClient(rate_limit=10, max_retries=2, backoff=0.01)


# ── search_markets ────────────────────────────────────────────────────


class TestSearchMarkets:
    @respx.mock
    @pytest.mark.asyncio()
    async def test_returns_parsed_markets(self, client: ManifoldClient) -> None:
        respx.get(f"{_BASE}/search-markets").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "id": "mkt1",
                        "question": "Will X happen?",
                        "url": "https://manifold.markets/user/will-x-happen",
                        "probability": 0.42,
                        "outcomeType": "BINARY",
                        "mechanism": "cpmm-1",
                        "volume": 1000.0,
                        "volume24Hours": 100.0,
                        "totalLiquidity": 500.0,
                        "uniqueBettorCount": 25,
                        "isResolved": False,
                        "createdTime": 1700000000000,
                        "lastUpdatedTime": 1700001000000,
                        "creatorId": "user123",
                        "groupSlugs": ["politics"],
                        "textDescription": "Description here.",
                    },
                    {
                        "id": "mkt2",
                        "question": "Will Y happen?",
                        "url": "https://manifold.markets/user/will-y-happen",
                        "probability": 0.65,
                        "outcomeType": "BINARY",
                        "mechanism": "cpmm-1",
                        "volume": 2000.0,
                        "volume24Hours": 200.0,
                        "totalLiquidity": 800.0,
                        "uniqueBettorCount": 50,
                        "isResolved": False,
                        "createdTime": 1700000500000,
                        "lastUpdatedTime": 1700001500000,
                        "creatorId": "user456",
                        "groupSlugs": ["science"],
                        "textDescription": "",
                    },
                ],
            )
        )
        markets = await client.search_markets("election", limit=20)
        await client.close()

        assert len(markets) == 2
        assert markets[0].id == "mkt1"
        assert markets[0].probability == pytest.approx(0.42)
        assert markets[1].unique_bettor_count == 50

    @respx.mock
    @pytest.mark.asyncio()
    async def test_empty_list(self, client: ManifoldClient) -> None:
        respx.get(f"{_BASE}/search-markets").mock(
            return_value=httpx.Response(200, json=[])
        )
        markets = await client.search_markets("nothing")
        await client.close()
        assert markets == []

    @respx.mock
    @pytest.mark.asyncio()
    async def test_non_list_response_returns_empty(self, client: ManifoldClient) -> None:
        respx.get(f"{_BASE}/search-markets").mock(
            return_value=httpx.Response(200, json={"error": "unexpected"})
        )
        markets = await client.search_markets("broken")
        await client.close()
        assert markets == []


# ── get_market ────────────────────────────────────────────────────────


class TestGetMarket:
    @respx.mock
    @pytest.mark.asyncio()
    async def test_returns_single_market(self, client: ManifoldClient) -> None:
        respx.get(f"{_BASE}/market/abc123").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "abc123",
                    "question": "Will this resolve YES?",
                    "url": "https://manifold.markets/user/will-this",
                    "probability": 0.78,
                    "outcomeType": "BINARY",
                    "mechanism": "cpmm-1",
                    "volume": 3000.0,
                    "volume24Hours": 300.0,
                    "totalLiquidity": 1200.0,
                    "uniqueBettorCount": 80,
                    "isResolved": False,
                    "createdTime": 1700000000000,
                    "lastUpdatedTime": 1700002000000,
                    "creatorId": "creator1",
                    "groupSlugs": [],
                    "textDescription": "Full description.",
                },
            )
        )
        market = await client.get_market("abc123")
        await client.close()

        assert market.id == "abc123"
        assert market.probability == pytest.approx(0.78)
        assert market.description_text == "Full description."


# ── get_market_by_slug ────────────────────────────────────────────────


class TestGetMarketBySlug:
    @respx.mock
    @pytest.mark.asyncio()
    async def test_returns_market_by_slug(self, client: ManifoldClient) -> None:
        respx.get(f"{_BASE}/slug/will-this-happen").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "slug_mkt",
                    "question": "Will this happen?",
                    "url": "https://manifold.markets/user/will-this-happen",
                    "probability": 0.33,
                    "outcomeType": "BINARY",
                    "mechanism": "cpmm-1",
                    "volume": 500.0,
                    "volume24Hours": 50.0,
                    "totalLiquidity": 200.0,
                    "uniqueBettorCount": 10,
                    "isResolved": False,
                    "createdTime": 1700000000000,
                    "lastUpdatedTime": 1700001000000,
                    "creatorId": "creator2",
                    "groupSlugs": ["general"],
                    "textDescription": "",
                },
            )
        )
        market = await client.get_market_by_slug("will-this-happen")
        await client.close()

        assert market.id == "slug_mkt"
        assert market.probability == pytest.approx(0.33)


# ── get_bets ──────────────────────────────────────────────────────────


class TestGetBets:
    @respx.mock
    @pytest.mark.asyncio()
    async def test_returns_parsed_bets(self, client: ManifoldClient) -> None:
        respx.get(f"{_BASE}/bets").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "id": "bet1",
                        "contractId": "mkt1",
                        "userId": "user1",
                        "amount": 50.0,
                        "shares": 75.0,
                        "outcome": "YES",
                        "probBefore": 0.40,
                        "probAfter": 0.45,
                        "createdTime": 1700000100000,
                        "isFilled": True,
                    },
                    {
                        "id": "bet2",
                        "contractId": "mkt1",
                        "userId": "user2",
                        "amount": 20.0,
                        "shares": 40.0,
                        "outcome": "NO",
                        "probBefore": 0.45,
                        "probAfter": 0.43,
                        "createdTime": 1700000200000,
                        "isFilled": True,
                    },
                ],
            )
        )
        bets = await client.get_bets("mkt1")
        await client.close()

        assert len(bets) == 2
        assert bets[0].id == "bet1"
        assert bets[0].outcome == "YES"
        assert bets[1].amount == pytest.approx(20.0)

    @respx.mock
    @pytest.mark.asyncio()
    async def test_empty_bets(self, client: ManifoldClient) -> None:
        respx.get(f"{_BASE}/bets").mock(
            return_value=httpx.Response(200, json=[])
        )
        bets = await client.get_bets("empty_mkt")
        await client.close()
        assert bets == []


# ── get_comments ──────────────────────────────────────────────────────


class TestGetComments:
    @respx.mock
    @pytest.mark.asyncio()
    async def test_returns_parsed_comments(self, client: ManifoldClient) -> None:
        respx.get(f"{_BASE}/comments").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "id": "cmt1",
                        "contractId": "mkt1",
                        "userId": "commenter1",
                        "text": "Very interesting market!",
                        "createdTime": 1700000300000,
                    }
                ],
            )
        )
        comments = await client.get_comments("mkt1")
        await client.close()

        assert len(comments) == 1
        assert comments[0].id == "cmt1"
        assert comments[0].text == "Very interesting market!"

    @respx.mock
    @pytest.mark.asyncio()
    async def test_empty_comments(self, client: ManifoldClient) -> None:
        respx.get(f"{_BASE}/comments").mock(
            return_value=httpx.Response(200, json=[])
        )
        comments = await client.get_comments("silent_mkt")
        await client.close()
        assert comments == []


# ── list_markets ──────────────────────────────────────────────────────


class TestListMarkets:
    @respx.mock
    @pytest.mark.asyncio()
    async def test_returns_market_list(self, client: ManifoldClient) -> None:
        respx.get(f"{_BASE}/markets").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "id": "list_mkt1",
                        "question": "Listed market 1",
                        "url": "https://manifold.markets/u/listed-1",
                        "probability": 0.55,
                        "outcomeType": "BINARY",
                        "mechanism": "cpmm-1",
                        "volume": 400.0,
                        "volume24Hours": 40.0,
                        "totalLiquidity": 150.0,
                        "uniqueBettorCount": 8,
                        "isResolved": False,
                        "createdTime": 1700000000000,
                        "lastUpdatedTime": 1700001000000,
                        "creatorId": "lister",
                        "groupSlugs": [],
                        "textDescription": "",
                    }
                ],
            )
        )
        markets = await client.list_markets(limit=10)
        await client.close()

        assert len(markets) == 1
        assert markets[0].id == "list_mkt1"

    @respx.mock
    @pytest.mark.asyncio()
    async def test_passes_before_cursor(self, client: ManifoldClient) -> None:
        route = respx.get(f"{_BASE}/markets").mock(
            return_value=httpx.Response(200, json=[])
        )
        await client.list_markets(limit=5, before="cursor_xyz")
        await client.close()

        assert route.called
        request = route.calls[0].request
        assert b"before=cursor_xyz" in request.url.query

    @respx.mock
    @pytest.mark.asyncio()
    async def test_omits_before_when_none(self, client: ManifoldClient) -> None:
        route = respx.get(f"{_BASE}/markets").mock(
            return_value=httpx.Response(200, json=[])
        )
        await client.list_markets(limit=5)
        await client.close()

        assert route.called
        request = route.calls[0].request
        assert b"before" not in request.url.query


# ── Retry behavior ────────────────────────────────────────────────────


class TestRetryBehavior:
    @respx.mock
    @pytest.mark.asyncio()
    async def test_retry_on_429(self, client: ManifoldClient) -> None:
        route = respx.get(f"{_BASE}/search-markets")
        route.side_effect = [
            httpx.Response(429, text="rate limited"),
            httpx.Response(200, json=[{"id": "m1", "question": "OK?",
                                       "probability": 0.5, "outcomeType": "BINARY",
                                       "createdTime": 0, "lastUpdatedTime": 0}]),
        ]
        markets = await client.search_markets("retry_test")
        await client.close()

        assert len(markets) == 1
        assert route.call_count == 2

    @respx.mock
    @pytest.mark.asyncio()
    async def test_retry_on_500(self, client: ManifoldClient) -> None:
        route = respx.get(f"{_BASE}/search-markets")
        route.side_effect = [
            httpx.Response(500, text="server error"),
            httpx.Response(500, text="server error"),
            httpx.Response(200, json=[{"id": "m2", "question": "Recovered?",
                                       "probability": 0.6, "outcomeType": "BINARY",
                                       "createdTime": 0, "lastUpdatedTime": 0}]),
        ]
        markets = await client.search_markets("server_err")
        await client.close()

        assert len(markets) == 1
        assert markets[0].id == "m2"
        assert route.call_count == 3

    @respx.mock
    @pytest.mark.asyncio()
    async def test_raises_after_exhausted_retries(self, client: ManifoldClient) -> None:
        respx.get(f"{_BASE}/search-markets").mock(
            return_value=httpx.Response(500, text="always fails")
        )
        with pytest.raises(RuntimeError, match="All .* attempts failed"):
            await client.search_markets("always_fail")
        await client.close()

    @respx.mock
    @pytest.mark.asyncio()
    async def test_raises_on_request_error_after_retries(
        self, client: ManifoldClient
    ) -> None:
        respx.get(f"{_BASE}/search-markets").mock(
            side_effect=httpx.ConnectError("connection refused")
        )
        with pytest.raises(httpx.ConnectError):
            await client.search_markets("network_fail")
        await client.close()


# ── close ─────────────────────────────────────────────────────────────


class TestClose:
    @pytest.mark.asyncio()
    async def test_close_is_idempotent(self, client: ManifoldClient) -> None:
        await client.close()
        await client.close()  # second call must not raise
