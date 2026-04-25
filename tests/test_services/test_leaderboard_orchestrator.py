"""Tests for LeaderboardOrchestrator (Phase 13 S2)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.execution.trade_store import TradeStore
from app.services.leaderboard_orchestrator import LeaderboardOrchestrator


def _fake_client(raw_rows: list[dict]) -> AsyncMock:
    client = AsyncMock()
    client.fetch_leaderboard = AsyncMock(return_value=raw_rows)
    return client


class TestTick:
    @pytest.mark.asyncio()
    async def test_snapshot_parses_entries(self) -> None:
        raw = [
            {"rank": 1, "wallet": "0xAAA", "pnl": 500_000.0, "win_rate": 0.7},
            {"rank": 2, "wallet": "0xBBB", "pnl": 250_000.0},
        ]
        orch = LeaderboardOrchestrator(leaderboard_client=_fake_client(raw))

        snapshot = await orch.tick(timeframe="monthly")

        assert len(snapshot) == 2
        assert snapshot[0].rank == 1
        # Wallet normalized to lower-case
        assert snapshot[0].wallet_address == "0xaaa"
        assert snapshot[0].pnl_usd == 500_000.0
        assert snapshot[0].win_rate == 0.7
        assert snapshot[0].timeframe == "monthly"
        assert snapshot[1].rank == 2
        assert snapshot[1].wallet_address == "0xbbb"
        assert snapshot[1].pnl_usd == 250_000.0
        assert snapshot[1].win_rate is None

    @pytest.mark.asyncio()
    async def test_envelope_alternative_keys(self) -> None:
        raw = [
            {
                "position": 1,
                "wallet_address": "0xaaa",
                "pnl_usd": 123.0,
                "winRate": 0.42,
            },
            {
                "rank": 2,
                "address": "0xbbb",
                "profit": 77.0,
            },
        ]
        orch = LeaderboardOrchestrator(leaderboard_client=_fake_client(raw))

        snapshot = await orch.tick(timeframe="weekly")

        assert len(snapshot) == 2
        assert snapshot[0].rank == 1
        assert snapshot[0].wallet_address == "0xaaa"
        assert snapshot[0].pnl_usd == 123.0
        assert snapshot[0].win_rate == 0.42
        assert snapshot[0].timeframe == "weekly"
        assert snapshot[1].rank == 2
        assert snapshot[1].wallet_address == "0xbbb"
        assert snapshot[1].pnl_usd == 77.0

    @pytest.mark.asyncio()
    async def test_get_leaderboard_returns_cached(self) -> None:
        raw = [{"rank": 1, "wallet": "0xaaa", "pnl": 10.0}]
        orch = LeaderboardOrchestrator(leaderboard_client=_fake_client(raw))

        await orch.tick(timeframe="monthly")
        out = orch.get_leaderboard("monthly")

        assert len(out) == 1
        assert out[0].wallet_address == "0xaaa"
        # Different timeframe → empty cache
        assert orch.get_leaderboard("weekly") == []


class TestPersistence:
    @pytest.mark.asyncio()
    async def test_persists_snapshot(self) -> None:
        store = TradeStore(db_path=":memory:")
        await store.init()

        raw = [
            {"rank": 1, "wallet": "0xaaa", "pnl": 100.0, "win_rate": 0.6},
            {"rank": 2, "wallet": "0xbbb", "pnl": 50.0},
        ]
        orch = LeaderboardOrchestrator(leaderboard_client=_fake_client(raw))
        await orch.set_trade_store(store)

        await orch.tick(timeframe="monthly")
        rows = await store.load_latest_leaderboard("monthly", 10)

        assert len(rows) == 2
        wallets = {r["wallet_address"] for r in rows}
        assert wallets == {"0xaaa", "0xbbb"}
        # Verify timeframe isolation — different tf must not pick these up
        assert await store.load_latest_leaderboard("weekly", 10) == []
        await store.close()

    @pytest.mark.asyncio()
    async def test_fetch_failure_returns_last_snapshot(self) -> None:
        client = AsyncMock()
        client.fetch_leaderboard = AsyncMock(side_effect=RuntimeError("boom"))
        orch = LeaderboardOrchestrator(leaderboard_client=client)

        snapshot = await orch.tick(timeframe="monthly")

        assert snapshot == []
        assert orch.last_tick is None


class TestMalformedEntries:
    @pytest.mark.asyncio()
    async def test_skips_entries_without_wallet(self) -> None:
        raw = [
            {"rank": 1, "wallet": "0xaaa", "pnl": 10.0},
            {"rank": 2, "pnl": 5.0},  # missing wallet entirely
            {"rank": 3, "wallet": "0xccc", "pnl": 1.0},
        ]
        orch = LeaderboardOrchestrator(leaderboard_client=_fake_client(raw))

        snapshot = await orch.tick(timeframe="monthly")

        assert len(snapshot) == 2
        wallets = [e.wallet_address for e in snapshot]
        assert wallets == ["0xaaa", "0xccc"]
