"""Tests for PolymarketLeaderboardClient (Phase 13 S2)."""

from __future__ import annotations

import httpx
import pytest
import respx

from app.clients.polymarket_leaderboard import PolymarketLeaderboardClient

BASE = "https://lb-api.polymarket.com"


@pytest.fixture
def client() -> PolymarketLeaderboardClient:
    return PolymarketLeaderboardClient(base_url=BASE, rate_limit=10)


class TestFetchLeaderboard:
    @respx.mock
    @pytest.mark.asyncio()
    async def test_returns_parsed_entries(
        self, client: PolymarketLeaderboardClient
    ) -> None:
        sample = [
            {"rank": 1, "wallet": "0xaaa", "pnl": 500000.0, "win_rate": 0.7},
            {"rank": 2, "wallet": "0xbbb", "pnl": 250000.0},
        ]
        respx.get(f"{BASE}/leaderboard").mock(
            return_value=httpx.Response(200, json=sample)
        )
        rows = await client.fetch_leaderboard(timeframe="monthly")
        await client.close()

        assert len(rows) == 2
        assert rows[0]["rank"] == 1

    @respx.mock
    @pytest.mark.asyncio()
    async def test_404_returns_empty_gracefully(
        self, client: PolymarketLeaderboardClient
    ) -> None:
        respx.get(f"{BASE}/leaderboard").mock(
            return_value=httpx.Response(404)
        )
        rows = await client.fetch_leaderboard(timeframe="monthly")
        await client.close()

        assert rows == []

    @respx.mock
    @pytest.mark.asyncio()
    async def test_network_error_returns_empty(
        self, client: PolymarketLeaderboardClient
    ) -> None:
        respx.get(f"{BASE}/leaderboard").mock(
            side_effect=httpx.ConnectError("no route")
        )
        rows = await client.fetch_leaderboard()
        await client.close()

        assert rows == []

    @respx.mock
    @pytest.mark.asyncio()
    async def test_envelope_shape_ok(
        self, client: PolymarketLeaderboardClient
    ) -> None:
        respx.get(f"{BASE}/leaderboard").mock(
            return_value=httpx.Response(
                200,
                json={"leaderboard": [{"rank": 1, "wallet": "0xaaa"}]},
            )
        )
        rows = await client.fetch_leaderboard()
        await client.close()

        assert len(rows) == 1
