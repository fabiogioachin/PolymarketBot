"""Async RSS feed client using feedparser."""

from __future__ import annotations

import asyncio
import re
import time
from datetime import UTC, datetime

import feedparser
import httpx

from app.core.logging import get_logger
from app.core.yaml_config import app_config
from app.models.intelligence import NewsItem, TimeHorizon

logger = get_logger(__name__)

# Source name fragment -> time horizon mapping
_SOURCE_HORIZON: dict[str, TimeHorizon] = {
    "reuters": TimeHorizon.SHORT,
    "ap": TimeHorizon.SHORT,
    "bbc": TimeHorizon.MEDIUM,
    "aljazeera": TimeHorizon.MEDIUM,
    "ft": TimeHorizon.MEDIUM,
    "bloomberg": TimeHorizon.SHORT,
    "economist": TimeHorizon.LONG,
    "foreign affairs": TimeHorizon.LONG,
}

_HTML_TAG_RE = re.compile(r"<[^>]+>")


class RssClient:
    """Fetches and parses RSS feeds asynchronously."""

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._feeds = app_config.intelligence.rss.feeds
        self._seen_urls: set[str] = set()

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=15.0,
                follow_redirects=True,
                headers={"User-Agent": "PolymarketBot/0.1"},
            )
        return self._client

    async def fetch_feed(self, name: str, url: str) -> list[NewsItem]:
        """Fetch and parse a single RSS feed."""
        try:
            resp = await self._get_client().get(url)
            resp.raise_for_status()
            feed = feedparser.parse(resp.text)
        except (httpx.RequestError, httpx.HTTPStatusError) as exc:
            logger.warning("rss_fetch_failed", feed=name, error=str(exc))
            return []

        items: list[NewsItem] = []
        source_key = name.lower()
        horizon = self._resolve_horizon(source_key)

        for entry in feed.entries:
            item_url: str = getattr(entry, "link", "")
            if item_url in self._seen_urls:
                continue
            self._seen_urls.add(item_url)

            published = self._parse_published(entry)
            title: str = getattr(entry, "title", "")
            summary: str = getattr(entry, "summary", "")

            # Strip HTML tags from summary
            if "<" in summary:
                summary = _HTML_TAG_RE.sub("", summary).strip()

            items.append(
                NewsItem(
                    source=f"rss:{name.lower().replace(' ', '_')}",
                    title=title,
                    url=item_url,
                    published=published,
                    domain="",  # classified by news_service
                    time_horizon=horizon,
                    summary=summary[:500] if summary else "",
                    tags=[],
                )
            )

        logger.info("rss_feed_fetched", feed=name, items=len(items))
        return items

    async def fetch_all_feeds(self) -> list[NewsItem]:
        """Fetch all configured RSS feeds concurrently."""
        tasks = [self.fetch_feed(feed.name, feed.url) for feed in self._feeds]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_items: list[NewsItem] = []
        for result in results:
            if isinstance(result, list):
                all_items.extend(result)
            else:
                logger.warning("rss_feed_error", error=str(result))

        # Sort by published date (most recent first)
        all_items.sort(
            key=lambda x: x.published or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )
        return all_items

    def clear_seen(self) -> None:
        """Clear dedup cache."""
        self._seen_urls.clear()

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    @staticmethod
    def _resolve_horizon(source_key: str) -> TimeHorizon:
        for key, horizon in _SOURCE_HORIZON.items():
            if key in source_key:
                return horizon
        return TimeHorizon.MEDIUM

    @staticmethod
    def _parse_published(entry: object) -> datetime | None:
        parsed = getattr(entry, "published_parsed", None)
        if parsed is not None:
            try:
                return datetime.fromtimestamp(time.mktime(parsed), tz=UTC)
            except (ValueError, OverflowError, OSError):
                pass
        return None


rss_client = RssClient()
