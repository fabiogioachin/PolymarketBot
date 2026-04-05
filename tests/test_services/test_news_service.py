"""Tests for news aggregation service."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.models.intelligence import NewsItem, TimeHorizon
from app.services.news_service import NewsService


def _make_item(
    title: str = "Test",
    source: str = "rss:test",
    domain: str = "",
    horizon: TimeHorizon = TimeHorizon.MEDIUM,
    published: datetime | None = None,
) -> NewsItem:
    return NewsItem(
        source=source,
        title=title,
        url=f"https://example.com/{title.lower().replace(' ', '-')}",
        published=published or datetime.now(tz=UTC),
        domain=domain,
        time_horizon=horizon,
        summary=title,
    )


class TestFetchAllDedup:
    @pytest.mark.asyncio()
    async def test_removes_duplicate_titles(self) -> None:
        items = [
            _make_item(title="Breaking: NATO Summit Begins"),
            _make_item(title="Breaking: NATO Summit Begins", source="rss:other"),
        ]
        svc = NewsService()

        with (
            patch(
                "app.services.news_service.rss_client.fetch_all_feeds",
                new_callable=AsyncMock,
                return_value=items,
            ),
            patch(
                "app.services.news_service.institutional_client.fetch_all",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            result = await svc.fetch_all()

        assert len(result) == 1

    @pytest.mark.asyncio()
    async def test_different_titles_kept(self) -> None:
        items = [
            _make_item(title="NATO Summit Begins"),
            _make_item(title="Fed Raises Rates"),
        ]
        svc = NewsService()

        with (
            patch(
                "app.services.news_service.rss_client.fetch_all_feeds",
                new_callable=AsyncMock,
                return_value=items,
            ),
            patch(
                "app.services.news_service.institutional_client.fetch_all",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            result = await svc.fetch_all()

        assert len(result) == 2


class TestClassifyDomain:
    def test_economics(self) -> None:
        domain = NewsService._classify_domain(
            "Fed raises interest rate amid inflation concerns"
        )
        assert domain == "economics"

    def test_geopolitics(self) -> None:
        domain = NewsService._classify_domain(
            "NATO imposes new sanction after missile launch"
        )
        assert domain == "geopolitics"

    def test_politics(self) -> None:
        domain = NewsService._classify_domain(
            "President announces new congress vote on election reform"
        )
        assert domain == "politics"

    def test_crypto(self) -> None:
        domain = NewsService._classify_domain("Bitcoin and ethereum surge in crypto markets")
        assert domain == "crypto"

    def test_other_for_no_match(self) -> None:
        domain = NewsService._classify_domain("Cat videos go viral on the internet")
        assert domain == "other"


class TestGetByDomain:
    def test_filters_correctly(self) -> None:
        svc = NewsService()
        svc._cache = [
            _make_item(title="A", domain="economics"),
            _make_item(title="B", domain="politics"),
            _make_item(title="C", domain="economics"),
        ]

        result = svc.get_by_domain("economics")
        assert len(result) == 2
        assert all(i.domain == "economics" for i in result)

    def test_empty_on_no_match(self) -> None:
        svc = NewsService()
        svc._cache = [_make_item(title="A", domain="economics")]

        assert svc.get_by_domain("sports") == []


class TestGetByHorizon:
    def test_filters_correctly(self) -> None:
        svc = NewsService()
        svc._cache = [
            _make_item(title="A", horizon=TimeHorizon.SHORT),
            _make_item(title="B", horizon=TimeHorizon.LONG),
            _make_item(title="C", horizon=TimeHorizon.SHORT),
        ]

        result = svc.get_by_horizon(TimeHorizon.SHORT)
        assert len(result) == 2

    def test_empty_on_no_match(self) -> None:
        svc = NewsService()
        svc._cache = [_make_item(title="A", horizon=TimeHorizon.SHORT)]

        assert svc.get_by_horizon(TimeHorizon.LONG) == []


class TestNormalizeTitle:
    def test_removes_punctuation_and_lowercases(self) -> None:
        assert NewsService._normalize_title("Hello, World!") == "helloworld"

    def test_handles_spaces_and_special_chars(self) -> None:
        assert NewsService._normalize_title("Fed Raises Rate — 25bp") == "fedraisesrate25bp"

    def test_empty_string(self) -> None:
        assert NewsService._normalize_title("") == ""
