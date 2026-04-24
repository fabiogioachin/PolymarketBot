"""Tests for WhaleOrchestrator (Phase 13 S2)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.execution.trade_store import TradeStore
from app.models.market import Market, MarketCategory, MarketStatus, Outcome
from app.services.whale_orchestrator import WhaleOrchestrator


def _make_market(
    market_id: str = "m1",
    end_in: timedelta = timedelta(days=5),
) -> Market:
    return Market(
        id=market_id,
        question="Q?",
        category=MarketCategory.POLITICS,
        status=MarketStatus.ACTIVE,
        outcomes=[
            Outcome(token_id="t1", outcome="Yes", price=0.6),
            Outcome(token_id="t2", outcome="No", price=0.4),
        ],
        end_date=datetime.now(tz=UTC) + end_in,
        volume=10000.0,
        liquidity=5000.0,
    )


def _make_raw_trade(
    trade_id: str,
    size: float,
    price: float = 0.6,
    side: str = "BUY",
    taker: str = "0xwhale",
    timestamp: str | None = None,
) -> dict[str, Any]:
    return {
        "id": trade_id,
        "timestamp": timestamp or datetime.now(tz=UTC).isoformat(),
        "market": "m1",
        "taker": taker,
        "side": side,
        "size": size,
        "price": price,
    }


def _fake_client(trades: list[dict[str, Any]]) -> AsyncMock:
    client = AsyncMock()
    client.fetch_recent_trades = AsyncMock(return_value=trades)
    return client


class TestTickFiltering:
    @pytest.mark.asyncio()
    async def test_filters_below_threshold(self) -> None:
        """Trades below threshold_usd are dropped."""
        raws = [
            _make_raw_trade("t1", size=50_000),  # below default 100k
            _make_raw_trade("t2", size=250_000),  # above
        ]
        orch = WhaleOrchestrator(trades_client=_fake_client(raws))
        whales = await orch.tick([_make_market()])

        assert len(whales) == 1
        assert whales[0].id == "t2"
        assert whales[0].size_usd == 250_000

    @pytest.mark.asyncio()
    async def test_empty_when_no_trades(self) -> None:
        orch = WhaleOrchestrator(trades_client=_fake_client([]))
        whales = await orch.tick([_make_market()])
        assert whales == []
        assert orch.last_tick is not None


class TestPreResolutionFlag:
    @pytest.mark.asyncio()
    async def test_flags_trade_near_end_date(self) -> None:
        """Trade timestamp within 30 min of market end_date → pre_resolution."""
        now = datetime.now(tz=UTC)
        market = _make_market(end_in=timedelta(minutes=15))
        raw = _make_raw_trade(
            "t1",
            size=200_000,
            timestamp=now.isoformat(),
        )
        orch = WhaleOrchestrator(trades_client=_fake_client([raw]))
        whales = await orch.tick([market])

        assert len(whales) == 1
        assert whales[0].is_pre_resolution is True

    @pytest.mark.asyncio()
    async def test_does_not_flag_far_from_end(self) -> None:
        market = _make_market(end_in=timedelta(days=2))
        raw = _make_raw_trade("t1", size=200_000)
        orch = WhaleOrchestrator(trades_client=_fake_client([raw]))
        whales = await orch.tick([market])

        assert whales[0].is_pre_resolution is False


class TestPersistence:
    @pytest.mark.asyncio()
    async def test_persists_via_trade_store(self) -> None:
        store = TradeStore(db_path=":memory:")
        await store.init()

        raw = _make_raw_trade("t1", size=150_000, taker="0xwhale")
        orch = WhaleOrchestrator(trades_client=_fake_client([raw]))
        await orch.set_trade_store(store)

        whales = await orch.tick([_make_market()])
        assert len(whales) == 1

        rows = await store.load_whale_trades("m1", since_ts=0.0)
        assert len(rows) == 1
        assert rows[0]["id"] == "t1"
        assert rows[0]["size_usd"] == 150_000
        assert rows[0]["wallet_address"] == "0xwhale"
        await store.close()

    @pytest.mark.asyncio()
    async def test_persist_failure_does_not_crash(self) -> None:
        mock_store = AsyncMock()
        mock_store.save_whale_trade = AsyncMock(
            side_effect=RuntimeError("DB down")
        )
        raw = _make_raw_trade("t1", size=200_000)
        orch = WhaleOrchestrator(trades_client=_fake_client([raw]))
        await orch.set_trade_store(mock_store)

        whales = await orch.tick([_make_market()])
        assert len(whales) == 1  # tick still returns

    @pytest.mark.asyncio()
    async def test_get_whale_activity_reads_store(self) -> None:
        store = TradeStore(db_path=":memory:")
        await store.init()
        raw = _make_raw_trade("t1", size=300_000)
        orch = WhaleOrchestrator(trades_client=_fake_client([raw]))
        await orch.set_trade_store(store)
        await orch.tick([_make_market()])

        activity = await orch.get_whale_activity("m1", since_minutes=60)
        assert len(activity) == 1
        assert activity[0].id == "t1"
        await store.close()


class TestMalformedTrades:
    @pytest.mark.asyncio()
    async def test_skips_malformed_gracefully(self) -> None:
        raws: list[dict[str, Any]] = [
            {"not": "a trade"},
            _make_raw_trade("t1", size=200_000),
        ]
        orch = WhaleOrchestrator(trades_client=_fake_client(raws))
        whales = await orch.tick([_make_market()])

        # Malformed entry becomes a WhaleTrade with synthesized id + size 0,
        # so it's filtered by threshold, leaving only t1.
        assert len(whales) == 1
        assert whales[0].id == "t1"
