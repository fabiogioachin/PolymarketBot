"""Tests for TradeStore — intelligence_events persistence and time_horizon column."""

from __future__ import annotations

import pytest

from app.execution.trade_store import TradeStore


@pytest.fixture
async def store() -> TradeStore:
    """In-memory TradeStore for testing."""
    s = TradeStore(db_path=":memory:")
    await s.init()
    yield s
    await s.close()


def _base_trade(**overrides: object) -> dict[str, object]:
    """Minimal valid trade dict."""
    base: dict[str, object] = {
        "timestamp": "2026-04-15T10:00:00+00:00",
        "market_id": "mkt-1",
        "strategy": "test",
        "side": "BUY",
        "size_eur": 5.0,
        "price": 0.5,
        "edge": 0.1,
        "pnl": 0.0,
        "type": "open",
        "reasoning": "test reasoning",
    }
    base.update(overrides)
    return base


class TestTimeHorizon:
    @pytest.mark.asyncio()
    async def test_horizon_stored_and_returned(self, store: TradeStore) -> None:
        """append_trade with horizon='short' should persist and get_trades returns time_horizon='short'."""
        await store.append_trade(_base_trade(horizon="short"))

        trades = await store.get_trades()
        assert len(trades) == 1
        assert trades[0]["time_horizon"] == "short"

    @pytest.mark.asyncio()
    async def test_horizon_medium(self, store: TradeStore) -> None:
        """Horizon values 'medium' and 'long' are stored correctly."""
        await store.append_trade(_base_trade(horizon="medium"))
        await store.append_trade(_base_trade(horizon="long"))

        trades = await store.get_trades()
        # get_trades returns newest-first
        assert trades[0]["time_horizon"] == "long"
        assert trades[1]["time_horizon"] == "medium"

    @pytest.mark.asyncio()
    async def test_no_horizon_key_stores_empty_string(self, store: TradeStore) -> None:
        """append_trade with no 'horizon' key should store time_horizon=''."""
        await store.append_trade(_base_trade())  # no horizon key

        trades = await store.get_trades()
        assert len(trades) == 1
        assert trades[0]["time_horizon"] == ""

    @pytest.mark.asyncio()
    async def test_migration_existing_records_return_empty_string(self) -> None:
        """Records inserted before the migration (via raw SQL) should return time_horizon=''."""
        import aiosqlite

        # Build a DB whose trades table lacks time_horizon (simulates pre-migration state)
        store_old = TradeStore(db_path=":memory:")
        store_old._conn = await aiosqlite.connect(":memory:")
        store_old._conn.row_factory = aiosqlite.Row
        # Create table without time_horizon column
        await store_old._conn.execute("""
            CREATE TABLE trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                market_id TEXT NOT NULL,
                strategy TEXT NOT NULL,
                side TEXT NOT NULL,
                size_eur REAL NOT NULL DEFAULT 0,
                price REAL NOT NULL DEFAULT 0,
                edge REAL NOT NULL DEFAULT 0,
                pnl REAL NOT NULL DEFAULT 0,
                type TEXT NOT NULL DEFAULT 'open',
                reasoning TEXT NOT NULL DEFAULT ''
            )
        """)
        await store_old._conn.execute(
            "INSERT INTO trades (timestamp, market_id, strategy, side, reasoning) "
            "VALUES ('2026-01-01', 'mkt-old', 'strat', 'BUY', '')"
        )
        await store_old._conn.commit()

        # Now run the migration manually (same logic as init())
        try:
            await store_old._conn.execute(
                "ALTER TABLE trades ADD COLUMN time_horizon TEXT NOT NULL DEFAULT ''"
            )
            await store_old._conn.commit()
        except Exception:
            pass  # already exists

        trades = await store_old.get_trades()
        assert len(trades) == 1
        assert trades[0]["time_horizon"] == ""

        await store_old.close()


class TestSaveAnomalyReport:
    @pytest.mark.asyncio()
    async def test_save_and_load(self, store: TradeStore) -> None:
        """A saved report should be loadable."""
        report = {
            "detected_at": "2026-04-14T12:00:00+00:00",
            "total_anomalies": 3,
            "events_json": '[{"query": "ELECTION"}]',
            "news_json": '[{"title": "Test"}]',
        }
        await store.save_anomaly_report(report)

        loaded = await store.load_anomaly_reports(limit=10)
        assert len(loaded) == 1
        assert loaded[0]["detected_at"] == "2026-04-14T12:00:00+00:00"
        assert loaded[0]["total_anomalies"] == 3
        assert loaded[0]["events_json"] == '[{"query": "ELECTION"}]'
        assert loaded[0]["news_json"] == '[{"title": "Test"}]'

    @pytest.mark.asyncio()
    async def test_load_ordering(self, store: TradeStore) -> None:
        """Reports should be returned newest first."""
        for i in range(5):
            await store.save_anomaly_report({
                "detected_at": f"2026-04-14T{i:02d}:00:00+00:00",
                "total_anomalies": i,
                "events_json": "[]",
                "news_json": "[]",
            })

        loaded = await store.load_anomaly_reports(limit=3)
        assert len(loaded) == 3
        # Newest first
        assert loaded[0]["detected_at"] == "2026-04-14T04:00:00+00:00"
        assert loaded[1]["detected_at"] == "2026-04-14T03:00:00+00:00"
        assert loaded[2]["detected_at"] == "2026-04-14T02:00:00+00:00"

    @pytest.mark.asyncio()
    async def test_load_empty(self, store: TradeStore) -> None:
        """Loading from an empty table returns an empty list."""
        loaded = await store.load_anomaly_reports()
        assert loaded == []

    @pytest.mark.asyncio()
    async def test_limit_respected(self, store: TradeStore) -> None:
        """Limit parameter caps the number of results."""
        for i in range(10):
            await store.save_anomaly_report({
                "detected_at": f"2026-04-14T{i:02d}:00:00+00:00",
                "total_anomalies": i,
                "events_json": "[]",
                "news_json": "[]",
            })

        loaded = await store.load_anomaly_reports(limit=5)
        assert len(loaded) == 5
