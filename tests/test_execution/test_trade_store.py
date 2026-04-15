"""Tests for TradeStore — intelligence_events persistence."""

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
