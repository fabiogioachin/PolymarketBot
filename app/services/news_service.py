"""News aggregation service: dedup, classify, and rank news items."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from app.clients.institutional_client import institutional_client
from app.clients.rss_client import rss_client
from app.core.logging import get_logger
from app.models.intelligence import NewsItem, TimeHorizon

logger = get_logger(__name__)

# Keyword -> domain mapping for news classification
_DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "politics": [
        "election",
        "president",
        "congress",
        "senate",
        "vote",
        "democrat",
        "republican",
        "parliament",
        "prime minister",
    ],
    "geopolitics": [
        "war",
        "invasion",
        "nato",
        "sanction",
        "treaty",
        "ceasefire",
        "nuclear",
        "missile",
        "diplomatic",
        "un security",
    ],
    "economics": [
        "gdp",
        "inflation",
        "interest rate",
        "fed",
        "recession",
        "unemployment",
        "cpi",
        "tariff",
        "central bank",
        "fiscal",
    ],
    "crypto": [
        "bitcoin",
        "ethereum",
        "crypto",
        "blockchain",
        "defi",
        "stablecoin",
        "sec crypto",
        "mining",
    ],
    "sports": [
        "nba",
        "nfl",
        "mlb",
        "premier league",
        "champions league",
        "world cup",
        "olympics",
    ],
    "science": [
        "nasa",
        "climate",
        "vaccine",
        "fda",
        "pandemic",
        "research",
    ],
}

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]")


class NewsService:
    """Aggregates news from all sources with dedup and domain classification."""

    def __init__(self) -> None:
        self._seen_titles: set[str] = set()
        self._cache: list[NewsItem] = []
        self._last_fetch: datetime | None = None

    async def fetch_all(self) -> list[NewsItem]:
        """Fetch from all news sources, dedup, and classify."""
        rss_items = await rss_client.fetch_all_feeds()
        inst_items = await institutional_client.fetch_all()

        all_items = rss_items + inst_items

        deduped: list[NewsItem] = []
        for item in all_items:
            norm_title = self._normalize_title(item.title)
            if norm_title in self._seen_titles:
                continue
            self._seen_titles.add(norm_title)

            # Classify domain if not already set
            if not item.domain:
                item.domain = self._classify_domain(item.title + " " + item.summary)

            deduped.append(item)

        deduped.sort(
            key=lambda x: x.published or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )

        self._cache = deduped
        self._last_fetch = datetime.now(tz=UTC)
        logger.info("news_fetched", total=len(all_items), deduped=len(deduped))
        return deduped

    def get_cached(self) -> list[NewsItem]:
        """Return cached news items."""
        return self._cache

    def get_by_domain(self, domain: str) -> list[NewsItem]:
        """Filter cached items by domain."""
        return [item for item in self._cache if item.domain == domain]

    def get_by_horizon(self, horizon: TimeHorizon) -> list[NewsItem]:
        """Filter cached items by time horizon."""
        return [item for item in self._cache if item.time_horizon == horizon]

    def clear_cache(self) -> None:
        """Clear all caches."""
        self._seen_titles.clear()
        self._cache.clear()

    @staticmethod
    def _normalize_title(title: str) -> str:
        """Normalize title for dedup comparison."""
        return _NON_ALNUM_RE.sub("", title.lower())

    @staticmethod
    def _classify_domain(text: str) -> str:
        """Classify text into a market domain using keyword matching."""
        text_lower = text.lower()
        best_domain = ""
        best_count = 0
        for domain, keywords in _DOMAIN_KEYWORDS.items():
            count = sum(1 for kw in keywords if kw in text_lower)
            if count > best_count:
                best_count = count
                best_domain = domain
        return best_domain or "other"
