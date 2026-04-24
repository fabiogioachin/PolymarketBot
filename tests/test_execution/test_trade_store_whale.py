"""Round-trip tests for Phase 13 S2 SQLite tables (whale/popular/leaderboard).

Per lesson 2026-04-15: INSERT column names must equal dict keys; we must
exercise both save + load paths to catch mismatches early.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.execution.trade_store import TradeStore


@pytest.fixture()
async def store() -> TradeStore:
    s = TradeStore(db_path=":memory:")
    await s.init()
    try:
        yield s
    finally:
        await s.close()


class TestWhaleTrades:
    @pytest.mark.asyncio()
    async def test_save_and_load_roundtrip(self, store: TradeStore) -> None:
        trade = {
            "id": "t1",
            "timestamp": 1_700_000_000.0,
            "market_id": "m1",
            "wallet_address": "0xaaa",
            "side": "BUY",
            "size_usd": 150_000.0,
            "price": 0.65,
            "is_pre_resolution": 1,
            "raw_json": '{"foo": "bar"}',
            "wallet_total_pnl": None,
            "wallet_weekly_pnl": None,
            "wallet_volume_rank": None,
        }
        await store.save_whale_trade(trade)
        rows = await store.load_whale_trades("m1", since_ts=0.0)
        assert len(rows) == 1
        got = rows[0]
        assert got["id"] == "t1"
        assert got["size_usd"] == 150_000.0
        assert got["side"] == "BUY"
        assert got["is_pre_resolution"] == 1
        assert got["wallet_address"] == "0xaaa"

    @pytest.mark.asyncio()
    async def test_since_ts_filter(self, store: TradeStore) -> None:
        await store.save_whale_trade({
            "id": "old",
            "timestamp": 1_000.0,
            "market_id": "m1",
            "wallet_address": "0xa",
            "side": "BUY",
            "size_usd": 100_000,
            "price": 0.5,
            "is_pre_resolution": 0,
            "raw_json": "",
        })
        await store.save_whale_trade({
            "id": "new",
            "timestamp": 2_000.0,
            "market_id": "m1",
            "wallet_address": "0xb",
            "side": "SELL",
            "size_usd": 200_000,
            "price": 0.55,
            "is_pre_resolution": 0,
            "raw_json": "",
        })
        rows = await store.load_whale_trades("m1", since_ts=1_500.0)
        assert len(rows) == 1
        assert rows[0]["id"] == "new"

    @pytest.mark.asyncio()
    async def test_insert_or_replace(self, store: TradeStore) -> None:
        base = {
            "id": "t1",
            "timestamp": 1_000.0,
            "market_id": "m1",
            "wallet_address": "0xa",
            "side": "BUY",
            "size_usd": 100_000,
            "price": 0.5,
            "is_pre_resolution": 0,
            "raw_json": "",
        }
        await store.save_whale_trade(base)
        await store.save_whale_trade({**base, "size_usd": 999_000})
        rows = await store.load_whale_trades("m1", since_ts=0.0)
        assert len(rows) == 1
        assert rows[0]["size_usd"] == 999_000

    @pytest.mark.asyncio()
    async def test_filter_by_market_id(self, store: TradeStore) -> None:
        for mid in ("m1", "m2"):
            await store.save_whale_trade({
                "id": f"t-{mid}",
                "timestamp": 1_000.0,
                "market_id": mid,
                "wallet_address": "0xa",
                "side": "BUY",
                "size_usd": 100_000,
                "price": 0.5,
                "is_pre_resolution": 0,
                "raw_json": "",
            })
        rows = await store.load_whale_trades("m2", since_ts=0.0)
        assert len(rows) == 1
        assert rows[0]["market_id"] == "m2"


class TestPopularMarkets:
    @pytest.mark.asyncio()
    async def test_save_and_load_latest(self, store: TradeStore) -> None:
        t1 = datetime.now(tz=UTC).timestamp()
        await store.save_popular_market_snapshot([
            {
                "snapshot_time": t1,
                "market_id": "a",
                "question": "Q A?",
                "volume24h": 100.0,
                "liquidity": 50.0,
            },
            {
                "snapshot_time": t1,
                "market_id": "b",
                "question": "Q B?",
                "volume24h": 200.0,
                "liquidity": None,
            },
        ])
        rows = await store.load_latest_popular_markets(10)
        assert len(rows) == 2
        # Ordered by volume24h DESC
        assert rows[0]["market_id"] == "b"
        assert rows[0]["volume24h"] == 200.0

    @pytest.mark.asyncio()
    async def test_latest_snapshot_supersedes(self, store: TradeStore) -> None:
        await store.save_popular_market_snapshot([
            {
                "snapshot_time": 1_000.0,
                "market_id": "a",
                "question": "old",
                "volume24h": 1.0,
                "liquidity": None,
            }
        ])
        await store.save_popular_market_snapshot([
            {
                "snapshot_time": 2_000.0,
                "market_id": "z",
                "question": "new",
                "volume24h": 99.0,
                "liquidity": None,
            }
        ])
        rows = await store.load_latest_popular_markets(10)
        assert len(rows) == 1
        assert rows[0]["market_id"] == "z"

    @pytest.mark.asyncio()
    async def test_empty_returns_empty(self, store: TradeStore) -> None:
        rows = await store.load_latest_popular_markets(10)
        assert rows == []


class TestLeaderboard:
    @pytest.mark.asyncio()
    async def test_save_and_load_roundtrip(self, store: TradeStore) -> None:
        t1 = datetime.now(tz=UTC).timestamp()
        await store.save_leaderboard_snapshot(
            [
                {
                    "snapshot_time": t1,
                    "rank": 1,
                    "wallet_address": "0xaaa",
                    "pnl_usd": 500_000.0,
                    "win_rate": 0.75,
                    "timeframe": "monthly",
                },
                {
                    "snapshot_time": t1,
                    "rank": 2,
                    "wallet_address": "0xbbb",
                    "pnl_usd": 250_000.0,
                    "win_rate": None,
                    "timeframe": "monthly",
                },
            ],
            timeframe="monthly",
        )
        rows = await store.load_latest_leaderboard("monthly", limit=10)
        assert len(rows) == 2
        assert rows[0]["rank"] == 1
        assert rows[0]["pnl_usd"] == 500_000.0

    @pytest.mark.asyncio()
    async def test_timeframe_isolation(self, store: TradeStore) -> None:
        t1 = datetime.now(tz=UTC).timestamp()
        await store.save_leaderboard_snapshot(
            [
                {
                    "snapshot_time": t1,
                    "rank": 1,
                    "wallet_address": "0xa",
                    "pnl_usd": 100.0,
                    "win_rate": None,
                    "timeframe": "weekly",
                },
            ],
            timeframe="weekly",
        )
        assert await store.load_latest_leaderboard("monthly") == []
        assert len(await store.load_latest_leaderboard("weekly")) == 1

    @pytest.mark.asyncio()
    async def test_empty_returns_empty(self, store: TradeStore) -> None:
        rows = await store.load_latest_leaderboard("monthly")
        assert rows == []
