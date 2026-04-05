"""Tests for EnrichmentService."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.models.knowledge import Pattern, PatternMatch
from app.services.enrichment_service import EnrichmentService


def _make_service(
    *,
    pattern_matches: list[PatternMatch] | None = None,
    cached_news: list | None = None,
) -> EnrichmentService:
    """Create an EnrichmentService with mocked sub-services."""
    news = AsyncMock()
    news.get_cached = lambda: cached_news or []

    knowledge = AsyncMock()
    knowledge.match_patterns = AsyncMock(return_value=pattern_matches or [])
    knowledge.write_event = AsyncMock(return_value=True)

    return EnrichmentService(news_service=news, knowledge_service=knowledge)


def _mock_gdelt_client() -> dict[str, AsyncMock]:
    """Create mocked gdelt_client methods returning test data."""
    articles = [
        {"url": "https://example.com/1", "title": "Article 1"},
        {"url": "https://example.com/2", "title": "Article 2"},
    ]
    vol_trend = [{"date": "2026-04-01", "value": 100}, {"date": "2026-04-02", "value": 150}]
    tone_trend = [{"date": "2026-04-01", "value": -1.0}, {"date": "2026-04-02", "value": -2.5}]

    return {
        "article_search": AsyncMock(return_value=articles),
        "timeline_volume": AsyncMock(return_value=vol_trend),
        "timeline_tone": AsyncMock(return_value=tone_trend),
    }


# ── enrich_topic ─────────────────────────────────────────────────────


class TestEnrichTopic:
    @pytest.mark.asyncio()
    async def test_enrich_topic(self) -> None:
        """Basic enrichment returns populated result."""
        service = _make_service()
        mocks = _mock_gdelt_client()

        with patch("app.services.enrichment_service.gdelt_client", **mocks):
            result = await service.enrich_topic("inflation")

        assert result.topic == "inflation"
        assert result.gdelt_articles == 2
        assert len(result.gdelt_volume_trend) == 2
        assert len(result.gdelt_tone_trend) == 2
        assert result.timestamp is not None
        assert "2 articles found" in result.summary

    @pytest.mark.asyncio()
    async def test_enrich_topic_quick_depth(self) -> None:
        """Quick depth passes max_records=25."""
        service = _make_service()
        mocks = _mock_gdelt_client()

        with patch("app.services.enrichment_service.gdelt_client", **mocks):
            await service.enrich_topic("inflation", depth="quick")

        mocks["article_search"].assert_called_once_with("inflation", timespan="7d", max_records=25)

    @pytest.mark.asyncio()
    async def test_enrich_topic_with_domain(self) -> None:
        """Domain triggers pattern matching."""
        pattern = Pattern(name="inflation_pattern", confidence=0.8)
        match = PatternMatch(pattern=pattern, match_score=0.75, detail="keyword match")
        service = _make_service(pattern_matches=[match])
        mocks = _mock_gdelt_client()

        with patch("app.services.enrichment_service.gdelt_client", **mocks):
            result = await service.enrich_topic("inflation", domain="economics")

        assert len(result.pattern_matches) == 1
        assert result.pattern_matches[0]["pattern"] == "inflation_pattern"
        assert result.pattern_matches[0]["score"] == 0.75
        assert "1 pattern matches" in result.summary

    @pytest.mark.asyncio()
    async def test_enrich_topic_writes_to_kg(self) -> None:
        """When domain is provided, event is written to KG."""
        service = _make_service()
        mocks = _mock_gdelt_client()

        with patch("app.services.enrichment_service.gdelt_client", **mocks):
            await service.enrich_topic("inflation", domain="economics")

        service._knowledge.write_event.assert_called_once()
        call_kwargs = service._knowledge.write_event.call_args
        assert call_kwargs.kwargs["domain"] == "economics"
        assert "Enrichment: inflation" in call_kwargs.kwargs["title"]

    @pytest.mark.asyncio()
    async def test_enrich_topic_no_domain_skips_kg_write(self) -> None:
        """Without domain, KG write is skipped."""
        service = _make_service()
        mocks = _mock_gdelt_client()

        with patch("app.services.enrichment_service.gdelt_client", **mocks):
            await service.enrich_topic("inflation")

        service._knowledge.write_event.assert_not_called()
