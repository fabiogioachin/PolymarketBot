"""Tests for PolymarketSubgraphClient (Phase 13 S3).

Uses `respx` to mock the GraphQL POST endpoint and an in-memory SQLite
TradeStore to verify the UPDATE propagation path.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

from app.clients.polymarket_subgraph import (
    PolymarketSubgraphClient,
    _TTLCache,
)
from app.execution.trade_store import TradeStore
from app.models.intelligence import WhaleTrade
from app.services.whale_orchestrator import WhaleOrchestrator

ENDPOINT = "https://gateway.thegraph.com/api/subgraphs/id/test-subgraph"


@pytest.fixture
def client() -> PolymarketSubgraphClient:
    return PolymarketSubgraphClient(
        endpoint=ENDPOINT,
        api_key=None,
        rate_limit_per_minute=600,
        cache_ttl_seconds=3600.0,
    )


# ── query + wallet_pnl_aggregates ───────────────────────────────────────


class TestWalletPnlAggregates:
    @respx.mock
    @pytest.mark.asyncio()
    async def test_happy_path_returns_parsed_floats(
        self, client: PolymarketSubgraphClient
    ) -> None:
        respx.post(ENDPOINT).mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "user": {
                            "id": "0xabc",
                            "profit": "512345.12",
                            "weeklyProfit": "7821.5",
                        }
                    }
                },
            )
        )
        result = await client.wallet_pnl_aggregates("0xABC")
        await client.close()

        assert result == {"total_pnl": 512345.12, "weekly_pnl": 7821.5}

    @respx.mock
    @pytest.mark.asyncio()
    async def test_missing_schema_fields_return_none(
        self, client: PolymarketSubgraphClient
    ) -> None:
        respx.post(ENDPOINT).mock(
            return_value=httpx.Response(
                200, json={"data": {"user": {"id": "0xabc"}}}
            )
        )
        result = await client.wallet_pnl_aggregates("0xabc")
        await client.close()

        assert result == {"total_pnl": None, "weekly_pnl": None}

    @respx.mock
    @pytest.mark.asyncio()
    async def test_user_not_found_returns_none(
        self, client: PolymarketSubgraphClient
    ) -> None:
        respx.post(ENDPOINT).mock(
            return_value=httpx.Response(200, json={"data": {"user": None}})
        )
        result = await client.wallet_pnl_aggregates("0xabc")
        await client.close()

        assert result == {"total_pnl": None, "weekly_pnl": None}

    @respx.mock
    @pytest.mark.asyncio()
    async def test_500_returns_empty_dict_no_raise(
        self, client: PolymarketSubgraphClient
    ) -> None:
        respx.post(ENDPOINT).mock(
            return_value=httpx.Response(500, json={"error": "bad"})
        )
        result = await client.wallet_pnl_aggregates("0xabc")
        await client.close()

        # 500 → empty data → both None
        assert result == {"total_pnl": None, "weekly_pnl": None}

    @respx.mock
    @pytest.mark.asyncio()
    async def test_transport_error_returns_empty(
        self, client: PolymarketSubgraphClient
    ) -> None:
        respx.post(ENDPOINT).mock(side_effect=httpx.ConnectError("down"))
        result = await client.wallet_pnl_aggregates("0xabc")
        await client.close()

        assert result == {"total_pnl": None, "weekly_pnl": None}

    @pytest.mark.asyncio()
    async def test_empty_wallet_address_returns_none(
        self, client: PolymarketSubgraphClient
    ) -> None:
        # No HTTP request should happen for a blank wallet — no respx mock needed.
        result = await client.wallet_pnl_aggregates("")
        await client.close()

        assert result == {"total_pnl": None, "weekly_pnl": None}


# ── wallet_volume_rank ──────────────────────────────────────────────────


class TestWalletVolumeRank:
    @respx.mock
    @pytest.mark.asyncio()
    async def test_returns_int(self, client: PolymarketSubgraphClient) -> None:
        respx.post(ENDPOINT).mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "user": {
                            "id": "0xabc",
                            "usdcVolume": "123456.0",
                            "volumeRank": 42,
                        }
                    }
                },
            )
        )
        rank = await client.wallet_volume_rank("0xabc")
        await client.close()

        assert rank == 42

    @respx.mock
    @pytest.mark.asyncio()
    async def test_missing_rank_returns_none(
        self, client: PolymarketSubgraphClient
    ) -> None:
        respx.post(ENDPOINT).mock(
            return_value=httpx.Response(
                200, json={"data": {"user": {"id": "0xabc"}}}
            )
        )
        rank = await client.wallet_volume_rank("0xabc")
        await client.close()

        assert rank is None


# ── top_traders_by_pnl ──────────────────────────────────────────────────


class TestTopTraders:
    @respx.mock
    @pytest.mark.asyncio()
    async def test_parses_list(self, client: PolymarketSubgraphClient) -> None:
        respx.post(ENDPOINT).mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "users": [
                            {
                                "id": "0xaaa",
                                "profit": "1000000",
                                "usdcVolume": "5000000",
                                "winRate": 0.62,
                            },
                            {
                                "id": "0xbbb",
                                "profit": "750000",
                                "usdcVolume": "2000000",
                                "winRate": 0.58,
                            },
                        ]
                    }
                },
            )
        )
        traders = await client.top_traders_by_pnl(limit=2, timeframe="weekly")
        await client.close()

        assert len(traders) == 2
        assert traders[0]["id"] == "0xaaa"
        assert traders[1]["winRate"] == 0.58

    @respx.mock
    @pytest.mark.asyncio()
    async def test_non_list_payload_returns_empty(
        self, client: PolymarketSubgraphClient
    ) -> None:
        respx.post(ENDPOINT).mock(
            return_value=httpx.Response(
                200, json={"data": {"users": None}}
            )
        )
        traders = await client.top_traders_by_pnl()
        await client.close()

        assert traders == []


# ── trades_for_market ───────────────────────────────────────────────────


class TestTradesForMarket:
    @respx.mock
    @pytest.mark.asyncio()
    async def test_parses_list(self, client: PolymarketSubgraphClient) -> None:
        respx.post(ENDPOINT).mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "trades": [
                            {
                                "id": "tx1",
                                "timestamp": "1700000000",
                                "taker": "0xaaa",
                                "maker": "0xbbb",
                                "side": "BUY",
                                "size": "500.0",
                                "price": "0.55",
                            }
                        ]
                    }
                },
            )
        )
        trades = await client.trades_for_market("market-x", since_unix=1699999000)
        await client.close()

        assert len(trades) == 1
        assert trades[0]["id"] == "tx1"


# ── TTL cache ───────────────────────────────────────────────────────────


class TestTtlCache:
    def test_set_then_get(self) -> None:
        cache: _TTLCache = _TTLCache(ttl_seconds=10.0)
        cache.set("k", {"v": 1})
        assert cache.get("k") == {"v": 1}

    def test_zero_ttl_is_immediately_expired(self) -> None:
        cache: _TTLCache = _TTLCache(ttl_seconds=0.0)
        cache.set("k", 1)
        # ttl=0 → expires_at == now → strictly-less comparison means miss
        assert cache.get("k") is None

    def test_clear(self) -> None:
        cache: _TTLCache = _TTLCache(ttl_seconds=10.0)
        cache.set("a", 1)
        cache.set("b", 2)
        assert len(cache) == 2
        cache.clear()
        assert len(cache) == 0

    @respx.mock
    @pytest.mark.asyncio()
    async def test_get_wallet_enrichment_hits_cache_on_second_call(
        self,
    ) -> None:
        client = PolymarketSubgraphClient(
            endpoint=ENDPOINT,
            api_key=None,
            rate_limit_per_minute=600,
            cache_ttl_seconds=3600.0,
        )
        route = respx.post(ENDPOINT).mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "user": {
                            "id": "0xabc",
                            "profit": "100.0",
                            "weeklyProfit": "10.0",
                            "usdcVolume": "1000.0",
                            "volumeRank": 7,
                        }
                    }
                },
            )
        )
        first = await client.get_wallet_enrichment("0xabc")
        calls_after_first = route.call_count
        second = await client.get_wallet_enrichment("0xabc")
        await client.close()

        assert first["total_pnl"] == 100.0
        assert first["weekly_pnl"] == 10.0
        assert first["volume_rank"] == 7
        assert second == first
        # First call fires TWO queries (pnl + rank), second call must be zero.
        assert calls_after_first == 2
        assert route.call_count == 2


# ── Authorization header ────────────────────────────────────────────────


class TestAuthHeader:
    @respx.mock
    @pytest.mark.asyncio()
    async def test_api_key_sets_bearer_header(self) -> None:
        captured: dict[str, str] = {}

        def _capture(request: httpx.Request) -> httpx.Response:
            captured["authorization"] = request.headers.get("authorization", "")
            return httpx.Response(
                200, json={"data": {"user": {"profit": "1", "weeklyProfit": "1"}}}
            )

        respx.post(ENDPOINT).mock(side_effect=_capture)

        client = PolymarketSubgraphClient(
            endpoint=ENDPOINT,
            api_key="secret-key",
            rate_limit_per_minute=600,
        )
        await client.wallet_pnl_aggregates("0xabc")
        await client.close()

        assert captured["authorization"] == "Bearer secret-key"

    @respx.mock
    @pytest.mark.asyncio()
    async def test_no_api_key_omits_header(self) -> None:
        captured: dict[str, str] = {}

        def _capture(request: httpx.Request) -> httpx.Response:
            captured["authorization"] = request.headers.get("authorization", "")
            return httpx.Response(
                200, json={"data": {"user": {"profit": "1", "weeklyProfit": "1"}}}
            )

        respx.post(ENDPOINT).mock(side_effect=_capture)

        client = PolymarketSubgraphClient(
            endpoint=ENDPOINT,
            api_key=None,
            rate_limit_per_minute=600,
        )
        # Ensure env var doesn't leak a key into this test
        client._api_key = None  # type: ignore[attr-defined]
        await client.wallet_pnl_aggregates("0xabc")
        await client.close()

        assert captured["authorization"] == ""


# ── UPDATE propagation through TradeStore + WhaleOrchestrator ───────────


class TestEnrichmentPropagation:
    @pytest.mark.asyncio()
    async def test_update_whale_trade_enrichment_touches_all_rows(self) -> None:
        store = TradeStore(db_path=":memory:")
        await store.init()

        # Persist two rows with the same wallet + one different wallet.
        for trade_id in ("t1", "t2"):
            await store.save_whale_trade({
                "id": trade_id,
                "timestamp": 1700000000.0,
                "market_id": "mkt-1",
                "wallet_address": "0xwhale",
                "side": "BUY",
                "size_usd": 150000.0,
                "price": 0.5,
                "is_pre_resolution": 0,
                "raw_json": "{}",
            })
        await store.save_whale_trade({
            "id": "t3",
            "timestamp": 1700000000.0,
            "market_id": "mkt-2",
            "wallet_address": "0xother",
            "side": "SELL",
            "size_usd": 110000.0,
            "price": 0.4,
            "is_pre_resolution": 0,
            "raw_json": "{}",
        })

        touched = await store.update_whale_trade_enrichment(
            "0xwhale", total_pnl=999.0, weekly_pnl=99.0, volume_rank=3
        )
        assert touched == 2

        enrichment = await store.load_whale_enrichment("0xwhale")
        assert enrichment == {
            "wallet_total_pnl": 999.0,
            "wallet_weekly_pnl": 99.0,
            "wallet_volume_rank": 3,
        }
        # Other wallet untouched.
        other = await store.load_whale_enrichment("0xother")
        assert other == {
            "wallet_total_pnl": None,
            "wallet_weekly_pnl": None,
            "wallet_volume_rank": None,
        }
        await store.close()

    @respx.mock
    @pytest.mark.asyncio()
    async def test_whale_orchestrator_enrichment_via_subgraph(self) -> None:
        respx.post(ENDPOINT).mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "user": {
                            "id": "0xwhale",
                            "profit": "750000.0",
                            "weeklyProfit": "60000.0",
                            "usdcVolume": "9000000.0",
                            "volumeRank": 5,
                        }
                    }
                },
            )
        )
        store = TradeStore(db_path=":memory:")
        await store.init()
        # Pre-populate a whale row (orchestrator persists itself too; we skip
        # the HTTP trade-tape leg and just call _enrich_wallets directly).
        await store.save_whale_trade({
            "id": "tWhale",
            "timestamp": 1700000000.0,
            "market_id": "mkt-1",
            "wallet_address": "0xwhale",
            "side": "BUY",
            "size_usd": 200000.0,
            "price": 0.6,
            "is_pre_resolution": 0,
            "raw_json": "{}",
        })

        sub = PolymarketSubgraphClient(
            endpoint=ENDPOINT,
            api_key=None,
            rate_limit_per_minute=600,
            cache_ttl_seconds=3600.0,
        )
        orchestrator = WhaleOrchestrator(
            trade_store=store, subgraph_client=sub
        )
        whale_trade = WhaleTrade(
            id="tWhale",
            timestamp=datetime.now(tz=UTC),
            market_id="mkt-1",
            wallet_address="0xwhale",
            side="BUY",
            size_usd=200000.0,
            price=0.6,
            is_pre_resolution=False,
            raw_json="{}",
        )
        await orchestrator._enrich_wallets([whale_trade])

        enrichment = await store.load_whale_enrichment("0xwhale")
        assert enrichment == {
            "wallet_total_pnl": 750000.0,
            "wallet_weekly_pnl": 60000.0,
            "wallet_volume_rank": 5,
        }

        # Second call must hit the cache (no new HTTP requests).
        route = list(respx.routes)[0]
        calls_before = route.call_count
        await orchestrator._enrich_wallets([whale_trade])
        assert route.call_count == calls_before

        await sub.close()
        await store.close()

    @respx.mock
    @pytest.mark.asyncio()
    async def test_orchestrator_enrichment_swallows_subgraph_errors(
        self,
    ) -> None:
        respx.post(ENDPOINT).mock(
            return_value=httpx.Response(500, json={"error": "oops"})
        )
        store = TradeStore(db_path=":memory:")
        await store.init()
        await store.save_whale_trade({
            "id": "tX",
            "timestamp": 1700000000.0,
            "market_id": "mkt-1",
            "wallet_address": "0xw",
            "side": "BUY",
            "size_usd": 150000.0,
            "price": 0.5,
            "is_pre_resolution": 0,
            "raw_json": "{}",
        })
        sub = PolymarketSubgraphClient(
            endpoint=ENDPOINT,
            api_key=None,
            rate_limit_per_minute=600,
        )
        orch = WhaleOrchestrator(trade_store=store, subgraph_client=sub)
        trade = WhaleTrade(
            id="tX",
            timestamp=datetime.now(tz=UTC) - timedelta(minutes=1),
            market_id="mkt-1",
            wallet_address="0xw",
            side="BUY",
            size_usd=150000.0,
            price=0.5,
            is_pre_resolution=False,
            raw_json="{}",
        )
        # Must not raise even though every subgraph call returns HTTP 500.
        await orch._enrich_wallets([trade])
        enrichment = await store.load_whale_enrichment("0xw")
        # All values stay None because the subgraph never returned data.
        assert enrichment == {
            "wallet_total_pnl": None,
            "wallet_weekly_pnl": None,
            "wallet_volume_rank": None,
        }
        await sub.close()
        await store.close()


# ── close is idempotent ─────────────────────────────────────────────────


class TestClose:
    @pytest.mark.asyncio()
    async def test_close_is_idempotent(
        self, client: PolymarketSubgraphClient
    ) -> None:
        await client.close()
        await client.close()
