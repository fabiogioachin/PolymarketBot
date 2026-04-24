"""Tests for PolymarketTradesClient (Phase 13 S2)."""

from __future__ import annotations

import httpx
import pytest
import respx

from app.clients.polymarket_trades import PolymarketTradesClient
from app.core.yaml_config import app_config

CLOB_BASE = app_config.polymarket.clob_url


@pytest.fixture
def client() -> PolymarketTradesClient:
    return PolymarketTradesClient(rate_limit=20)


class TestFetchRecentTrades:
    @respx.mock
    @pytest.mark.asyncio()
    async def test_returns_parsed_list(
        self, client: PolymarketTradesClient
    ) -> None:
        sample = [
            {
                "id": "t1",
                "timestamp": "2026-04-20T10:00:00Z",
                "market": "m-1",
                "taker": "0xaaa",
                "side": "BUY",
                "size": 150000.0,
                "price": 0.65,
            },
            {
                "id": "t2",
                "timestamp": "2026-04-20T10:01:00Z",
                "market": "m-1",
                "taker": "0xbbb",
                "side": "SELL",
                "size": 200.0,
                "price": 0.66,
            },
        ]
        respx.get(f"{CLOB_BASE}/trades").mock(
            return_value=httpx.Response(200, json=sample)
        )
        trades = await client.fetch_recent_trades("m-1", limit=50)
        await client.close()

        assert len(trades) == 2
        assert trades[0]["id"] == "t1"

    @respx.mock
    @pytest.mark.asyncio()
    async def test_envelope_data_shape(
        self, client: PolymarketTradesClient
    ) -> None:
        respx.get(f"{CLOB_BASE}/trades").mock(
            return_value=httpx.Response(
                200, json={"data": [{"id": "t1", "price": 0.5, "size": 10}]}
            )
        )
        trades = await client.fetch_recent_trades("m-1")
        await client.close()

        assert len(trades) == 1
        assert trades[0]["id"] == "t1"

    @respx.mock
    @pytest.mark.asyncio()
    async def test_500_returns_empty(
        self, client: PolymarketTradesClient
    ) -> None:
        respx.get(f"{CLOB_BASE}/trades").mock(
            return_value=httpx.Response(500, json={"error": "boom"})
        )
        trades = await client.fetch_recent_trades("m-1")
        await client.close()

        assert trades == []

    @respx.mock
    @pytest.mark.asyncio()
    async def test_timeout_returns_empty(
        self, client: PolymarketTradesClient
    ) -> None:
        respx.get(f"{CLOB_BASE}/trades").mock(
            side_effect=httpx.ConnectTimeout("slow")
        )
        trades = await client.fetch_recent_trades("m-1")
        await client.close()

        assert trades == []

    @respx.mock
    @pytest.mark.asyncio()
    async def test_404_returns_empty(
        self, client: PolymarketTradesClient
    ) -> None:
        respx.get(f"{CLOB_BASE}/trades").mock(
            return_value=httpx.Response(404)
        )
        trades = await client.fetch_recent_trades("m-missing")
        await client.close()

        assert trades == []

    @respx.mock
    @pytest.mark.asyncio()
    async def test_non_list_payload_returns_empty(
        self, client: PolymarketTradesClient
    ) -> None:
        respx.get(f"{CLOB_BASE}/trades").mock(
            return_value=httpx.Response(200, json={"unexpected": "shape"})
        )
        trades = await client.fetch_recent_trades("m-1")
        await client.close()

        assert trades == []

    @pytest.mark.asyncio()
    async def test_close_is_idempotent(
        self, client: PolymarketTradesClient
    ) -> None:
        await client.close()
        await client.close()  # second call must not raise
