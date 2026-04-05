"""Tests for async RSS feed client."""

from __future__ import annotations

import httpx
import pytest
import respx

from app.clients.rss_client import RssClient
from app.models.intelligence import TimeHorizon

SAMPLE_RSS = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
<title>Test Feed</title>
<item>
  <title>Fed Raises Interest Rates</title>
  <link>https://example.com/article1</link>
  <pubDate>Fri, 04 Apr 2026 12:00:00 GMT</pubDate>
  <description>The Federal Reserve raised rates by 25 basis points.</description>
</item>
<item>
  <title>Second Article</title>
  <link>https://example.com/article2</link>
  <pubDate>Fri, 04 Apr 2026 11:00:00 GMT</pubDate>
  <description>Some <b>HTML</b> content here.</description>
</item>
</channel>
</rss>"""

FEED_URL = "https://feeds.example.com/test"


@pytest.fixture()
def rss() -> RssClient:
    client = RssClient()
    client._feeds = []  # don't use config defaults in tests
    return client


class TestFetchFeed:
    @respx.mock
    @pytest.mark.asyncio()
    async def test_returns_news_items(self, rss: RssClient) -> None:
        respx.get(FEED_URL).mock(return_value=httpx.Response(200, text=SAMPLE_RSS))

        items = await rss.fetch_feed("Reuters World", FEED_URL)
        await rss.close()

        assert len(items) == 2
        assert items[0].title == "Fed Raises Interest Rates"
        assert items[0].source == "rss:reuters_world"
        assert items[0].url == "https://example.com/article1"
        assert items[0].published is not None
        # HTML should be stripped from summary
        assert "<b>" not in items[1].summary
        assert "HTML" in items[1].summary

    @respx.mock
    @pytest.mark.asyncio()
    async def test_fetch_feed_failure_returns_empty(self, rss: RssClient) -> None:
        respx.get(FEED_URL).mock(return_value=httpx.Response(500))

        items = await rss.fetch_feed("Reuters", FEED_URL)
        await rss.close()

        assert items == []

    @respx.mock
    @pytest.mark.asyncio()
    async def test_dedup_by_url(self, rss: RssClient) -> None:
        respx.get(FEED_URL).mock(return_value=httpx.Response(200, text=SAMPLE_RSS))

        first = await rss.fetch_feed("Test", FEED_URL)
        # Fetch again — same URLs should be deduped
        respx.get(FEED_URL).mock(return_value=httpx.Response(200, text=SAMPLE_RSS))
        second = await rss.fetch_feed("Test", FEED_URL)
        await rss.close()

        assert len(first) == 2
        assert len(second) == 0

    @respx.mock
    @pytest.mark.asyncio()
    async def test_clear_seen_resets_dedup(self, rss: RssClient) -> None:
        respx.get(FEED_URL).mock(return_value=httpx.Response(200, text=SAMPLE_RSS))

        first = await rss.fetch_feed("Test", FEED_URL)
        rss.clear_seen()
        respx.get(FEED_URL).mock(return_value=httpx.Response(200, text=SAMPLE_RSS))
        second = await rss.fetch_feed("Test", FEED_URL)
        await rss.close()

        assert len(first) == 2
        assert len(second) == 2


class TestFetchAllFeeds:
    @respx.mock
    @pytest.mark.asyncio()
    async def test_fetches_all_configured_feeds(self, rss: RssClient) -> None:
        from app.core.yaml_config import RssFeed

        rss._feeds = [
            RssFeed(name="Feed A", url="https://feeds.example.com/a"),
            RssFeed(name="Feed B", url="https://feeds.example.com/b"),
        ]
        respx.get("https://feeds.example.com/a").mock(
            return_value=httpx.Response(200, text=SAMPLE_RSS)
        )
        respx.get("https://feeds.example.com/b").mock(
            return_value=httpx.Response(200, text=SAMPLE_RSS)
        )

        items = await rss.fetch_all_feeds()
        await rss.close()

        # Feed A gets 2, Feed B deduped to 0 (same URLs)
        assert len(items) == 2


class TestTimeHorizonMapping:
    def test_reuters_is_short(self) -> None:
        assert RssClient._resolve_horizon("reuters world") == TimeHorizon.SHORT

    def test_ap_is_short(self) -> None:
        assert RssClient._resolve_horizon("ap top news") == TimeHorizon.SHORT

    def test_bbc_is_medium(self) -> None:
        assert RssClient._resolve_horizon("bbc world") == TimeHorizon.MEDIUM

    def test_economist_is_long(self) -> None:
        assert RssClient._resolve_horizon("the economist") == TimeHorizon.LONG

    def test_unknown_defaults_to_medium(self) -> None:
        assert RssClient._resolve_horizon("some random feed") == TimeHorizon.MEDIUM
