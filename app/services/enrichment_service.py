"""On-demand enrichment: deep-dive analysis on a topic."""

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from app.clients.gdelt_client import gdelt_client
from app.core.logging import get_logger
from app.services.knowledge_service import KnowledgeService
from app.services.news_service import NewsService

logger = get_logger(__name__)


class EnrichmentResult(BaseModel):
    """Result of an enrichment deep-dive."""

    topic: str
    domain: str = ""
    timestamp: datetime | None = None
    gdelt_articles: int = 0
    gdelt_volume_trend: list[dict] = Field(default_factory=list)
    gdelt_tone_trend: list[dict] = Field(default_factory=list)
    related_news: list[dict] = Field(default_factory=list)
    pattern_matches: list[dict] = Field(default_factory=list)
    summary: str = ""


class EnrichmentService:
    """On-demand deep-dive enrichment for specific topics."""

    def __init__(
        self,
        *,
        news_service: NewsService | None = None,
        knowledge_service: KnowledgeService | None = None,
    ) -> None:
        self._news = news_service or NewsService()
        self._knowledge = knowledge_service or KnowledgeService()

    async def enrich_topic(
        self,
        topic: str,
        *,
        domain: str = "",
        depth: str = "standard",  # "quick", "standard", "deep"
        timespan: str = "7d",
    ) -> EnrichmentResult:
        """Perform enrichment on a topic.

        Gathers GDELT history, RSS matches, and KG patterns.
        """
        now = datetime.now(tz=UTC)

        # Adjust parameters by depth
        max_articles = {"quick": 25, "standard": 75, "deep": 250}.get(depth, 75)

        # 1. GDELT article search
        articles = await gdelt_client.article_search(
            topic, timespan=timespan, max_records=max_articles
        )

        # 2. GDELT volume timeline
        vol_trend = await gdelt_client.timeline_volume(topic, timespan=timespan)

        # 3. GDELT tone timeline
        tone_trend = await gdelt_client.timeline_tone(topic, timespan=timespan)

        # 4. Match against KG patterns
        pattern_matches: list[dict] = []
        if domain:
            matches = await self._knowledge.match_patterns(domain, topic)
            pattern_matches = [
                {
                    "pattern": m.pattern.name,
                    "score": m.match_score,
                    "detail": m.detail,
                }
                for m in matches
            ]

        # 5. Related news from cache
        related: list[dict] = []
        cached_news = self._news.get_cached()
        topic_lower = topic.lower()
        for item in cached_news:
            if topic_lower in item.title.lower() or topic_lower in item.summary.lower():
                related.append(
                    {
                        "title": item.title,
                        "source": item.source,
                        "url": item.url,
                        "domain": item.domain,
                    }
                )
            if len(related) >= 20:
                break

        # Build summary
        summary = f"Enrichment for '{topic}': {len(articles)} articles found"
        if vol_trend:
            recent_vol = vol_trend[-1].get("value", 0) if vol_trend else 0
            summary += f", recent volume={recent_vol}"
        if tone_trend:
            recent_tone = tone_trend[-1].get("value", 0) if tone_trend else 0
            summary += f", tone={recent_tone:.1f}"
        if pattern_matches:
            summary += f", {len(pattern_matches)} pattern matches"

        result = EnrichmentResult(
            topic=topic,
            domain=domain,
            timestamp=now,
            gdelt_articles=len(articles),
            gdelt_volume_trend=vol_trend,
            gdelt_tone_trend=tone_trend,
            related_news=related,
            pattern_matches=pattern_matches,
            summary=summary,
        )

        # Write to KG
        if domain:
            await self._knowledge.write_event(
                domain=domain,
                title=f"Enrichment: {topic}",
                content=(
                    f"## Enrichment Report\n\n{summary}\n\n"
                    f"### Articles: {len(articles)}\n"
                    f"### Patterns: {len(pattern_matches)}"
                ),
                tags=["enrichment", topic],
            )

        logger.info("enrichment_complete", topic=topic, articles=len(articles))
        return result
