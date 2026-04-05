"""Tests for IntelligenceOrchestrator."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.models.intelligence import (
    GdeltArticle,
    GdeltEvent,
    NewsItem,
    ToneScore,
)
from app.models.knowledge import Pattern, PatternMatch
from app.services.intelligence_orchestrator import IntelligenceOrchestrator


def _make_gdelt_event(
    query: str = "ELECTION",
    event_type: str = "volume_spike",
    domain: str = "",
    relevance: float = 0.6,
) -> GdeltEvent:
    return GdeltEvent(
        query=query,
        event_type=event_type,
        detected_at=datetime.now(tz=UTC),
        articles=[
            GdeltArticle(url="https://example.com/1", title="Test Article"),
        ],
        tone=ToneScore(value=-2.0, baseline=0.0, shift=-2.0, is_anomaly=True),
        volume_current=300,
        volume_baseline=100,
        volume_ratio=3.0,
        domain=domain,
        relevance_score=relevance,
    )


def _make_news_item(
    title: str = "Test News",
    relevance: float = 0.7,
    domain: str = "politics",
) -> NewsItem:
    return NewsItem(
        source="rss:reuters",
        title=title,
        url="https://reuters.com/test",
        published=datetime.now(tz=UTC),
        domain=domain,
        summary="Test summary",
        relevance_score=relevance,
    )


def _make_orchestrator(
    gdelt_events: list[GdeltEvent] | None = None,
    news_items: list[NewsItem] | None = None,
    pattern_matches: list[PatternMatch] | None = None,
) -> IntelligenceOrchestrator:
    """Create an orchestrator with mocked sub-services."""
    gdelt = AsyncMock()
    gdelt.poll_watchlist = AsyncMock(return_value=gdelt_events or [])

    news = AsyncMock()
    news.fetch_all = AsyncMock(return_value=news_items or [])

    knowledge = AsyncMock()
    knowledge.match_patterns = AsyncMock(return_value=pattern_matches or [])
    knowledge.write_event = AsyncMock(return_value=True)

    return IntelligenceOrchestrator(
        gdelt_service=gdelt,
        news_service=news,
        knowledge_service=knowledge,
    )


# ── tick ─────────────────────────────────────────────────────────────


class TestTick:
    @pytest.mark.asyncio()
    async def test_tick_no_anomalies(self) -> None:
        """Empty services produce a report with 0 anomalies."""
        orch = _make_orchestrator()
        report = await orch.tick()

        assert report.total_anomalies == 0
        assert report.events == []
        assert report.news_items == []
        assert report.detected_at is not None
        assert orch._last_tick is not None

    @pytest.mark.asyncio()
    async def test_tick_with_gdelt_event(self) -> None:
        """GDELT event is processed and written to KG."""
        event = _make_gdelt_event()
        orch = _make_orchestrator(gdelt_events=[event])

        report = await orch.tick()

        assert report.total_anomalies == 1
        assert len(report.events) == 1
        # KG write_event should have been called
        orch._knowledge.write_event.assert_called_once()
        # Domain should be inferred (ELECTION -> politics)
        assert event.domain == "politics"

    @pytest.mark.asyncio()
    async def test_tick_with_news(self) -> None:
        """High-relevance news items appear in the report."""
        high = _make_news_item(relevance=0.8)
        low = _make_news_item(title="Low relevance", relevance=0.2)
        orch = _make_orchestrator(news_items=[high, low])

        report = await orch.tick()

        # Only the high-relevance item (>0.5) should appear
        assert len(report.news_items) == 1
        assert report.news_items[0].title == "Test News"
        assert report.total_anomalies == 1

    @pytest.mark.asyncio()
    async def test_tick_with_pattern_matches(self) -> None:
        """Pattern match updates event relevance."""
        event = _make_gdelt_event(relevance=0.3)
        pattern = Pattern(name="test_pattern", confidence=0.9)
        match = PatternMatch(pattern=pattern, match_score=0.85, detail="matched")
        orch = _make_orchestrator(gdelt_events=[event], pattern_matches=[match])

        await orch.tick()

        # Relevance should be updated to the best match score
        assert event.relevance_score == 0.85


# ── get_recent_anomalies ─────────────────────────────────────────────


class TestGetRecentAnomalies:
    @pytest.mark.asyncio()
    async def test_returns_history(self) -> None:
        orch = _make_orchestrator()

        await orch.tick()
        await orch.tick()
        await orch.tick()

        reports = orch.get_recent_anomalies(limit=2)
        assert len(reports) == 2

    def test_empty_history(self) -> None:
        orch = _make_orchestrator()
        assert orch.get_recent_anomalies() == []


# ── get_event_signal ─────────────────────────────────────────────────


class TestGetEventSignal:
    @pytest.mark.asyncio()
    async def test_returns_signal(self) -> None:
        event = _make_gdelt_event(domain="politics", relevance=0.7)
        orch = _make_orchestrator(gdelt_events=[event])
        # Pre-set domain so _process_event doesn't overwrite
        event.domain = "politics"
        await orch.tick()

        signal = orch.get_event_signal("politics")
        assert signal == pytest.approx(0.7)

    def test_no_data_returns_zero(self) -> None:
        orch = _make_orchestrator()
        assert orch.get_event_signal("politics") == 0.0

    @pytest.mark.asyncio()
    async def test_no_domain_match_returns_zero(self) -> None:
        event = _make_gdelt_event(domain="economics", relevance=0.8)
        event.domain = "economics"
        orch = _make_orchestrator(gdelt_events=[event])
        await orch.tick()

        assert orch.get_event_signal("sports") == 0.0

    @pytest.mark.asyncio()
    async def test_signal_capped_at_one(self) -> None:
        event = _make_gdelt_event(domain="politics", relevance=1.5)
        event.domain = "politics"
        orch = _make_orchestrator(gdelt_events=[event])
        await orch.tick()

        assert orch.get_event_signal("politics") == 1.0


# ── _infer_domain ────────────────────────────────────────────────────


class TestInferDomain:
    @pytest.mark.parametrize(
        ("query", "expected"),
        [
            ("ELECTION", "politics"),
            ("ECON_INFLATION", "economics"),
            ("ECON_INTEREST_RATE", "economics"),
            ("CLIMATE_CHANGE", "science"),
            ("WB_CONFLICT", "geopolitics"),
            ("WAR_ZONE", "geopolitics"),
            ("USA_POLITICS", "politics"),
            ("RUS_MILITARY", "geopolitics"),
            ("CHN_TRADE", "geopolitics"),
            ("RANDOM_TOPIC", "other"),
        ],
    )
    def test_infer_domain(self, query: str, expected: str) -> None:
        assert IntelligenceOrchestrator._infer_domain(query) == expected


# ── anomaly history cap ──────────────────────────────────────────────


class TestAnomalyHistoryCap:
    @pytest.mark.asyncio()
    async def test_capped_at_100(self) -> None:
        orch = _make_orchestrator()

        for _ in range(105):
            await orch.tick()

        assert len(orch._anomaly_history) == 100
