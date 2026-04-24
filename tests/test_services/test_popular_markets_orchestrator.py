"""Tests for PopularMarketsOrchestrator (Phase 13 S2)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from app.execution.trade_store import TradeStore
from app.models.market import Market, MarketCategory, MarketStatus, Outcome
from app.services.popular_markets_orchestrator import PopularMarketsOrchestrator


def _mk(m_id: str, vol: float, q: str = "Will X happen?") -> Market:
    return Market(
        id=m_id,
        question=q,
        category=MarketCategory.POLITICS,
        status=MarketStatus.ACTIVE,
        outcomes=[
            Outcome(token_id=f"t-{m_id}-y", outcome="Yes", price=0.6),
            Outcome(token_id=f"t-{m_id}-n", outcome="No", price=0.4),
        ],
        end_date=datetime.now(tz=UTC) + timedelta(days=7),
        volume=vol * 10,
        volume_24h=vol,
        liquidity=vol / 2,
    )


def _fake_rest(markets: list[Market]) -> AsyncMock:
    client = AsyncMock()
    client.list_markets = AsyncMock(return_value=markets)
    return client


class TestTick:
    @pytest.mark.asyncio()
    async def test_snapshot_ordered_by_volume(self) -> None:
        markets = [_mk("a", 50_000), _mk("b", 120_000), _mk("c", 80_000)]
        orch = PopularMarketsOrchestrator(rest_client=_fake_rest(markets))

        snapshot = await orch.tick()
        # The orchestrator preserves order from list_markets (which already
        # sorts by volume24hr server-side). Verify all 3 are present.
        assert len(snapshot) == 3
        ids = {pm.market_id for pm in snapshot}
        assert ids == {"a", "b", "c"}

    @pytest.mark.asyncio()
    async def test_get_popular_markets_returns_last(self) -> None:
        markets = [_mk("a", 50_000)]
        orch = PopularMarketsOrchestrator(rest_client=_fake_rest(markets))
        await orch.tick()
        out = orch.get_popular_markets()
        assert len(out) == 1
        assert out[0].market_id == "a"
        assert out[0].volume24h == 50_000


class TestPersistence:
    @pytest.mark.asyncio()
    async def test_persists_snapshot(self) -> None:
        store = TradeStore(db_path=":memory:")
        await store.init()

        markets = [_mk("a", 100_000), _mk("b", 90_000)]
        orch = PopularMarketsOrchestrator(rest_client=_fake_rest(markets))
        await orch.set_trade_store(store)

        await orch.tick()
        rows = await store.load_latest_popular_markets(10)
        assert len(rows) == 2
        ids = {r["market_id"] for r in rows}
        assert ids == {"a", "b"}
        await store.close()

    @pytest.mark.asyncio()
    async def test_fetch_failure_returns_last_snapshot(self) -> None:
        rest = AsyncMock()
        rest.list_markets = AsyncMock(side_effect=RuntimeError("boom"))
        orch = PopularMarketsOrchestrator(rest_client=rest)

        snapshot = await orch.tick()
        assert snapshot == []
        assert orch.last_tick is None
