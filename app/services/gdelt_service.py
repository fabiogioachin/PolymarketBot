"""GDELT monitoring service: watchlist polling and anomaly detection."""

from __future__ import annotations

from datetime import UTC, datetime

from app.clients.gdelt_client import GdeltClient, gdelt_client
from app.core.logging import get_logger
from app.core.yaml_config import app_config
from app.models.intelligence import (
    GdeltArticle,
    GdeltEvent,
    ToneScore,
)

logger = get_logger(__name__)

# Anomaly thresholds
_VOLUME_SPIKE_RATIO = 2.0  # 2x baseline = volume spike
_TONE_SHIFT_THRESHOLD = 1.5  # >1.5 point shift from baseline = tone anomaly


class GdeltService:
    """Monitors GDELT for watchlist events and detects anomalies."""

    def __init__(self, client: GdeltClient | None = None) -> None:
        self._client = client or gdelt_client
        self._watchlist = app_config.intelligence.gdelt.watchlist
        self._baselines: dict[str, dict[str, float]] = {}
        self._last_poll: datetime | None = None

    async def poll_watchlist(self) -> list[GdeltEvent]:
        """Poll all watchlist queries and detect anomalies."""
        events: list[GdeltEvent] = []
        all_queries = self._build_queries()

        for query in all_queries:
            try:
                event = await self._check_query(query)
                if event:
                    events.append(event)
            except Exception:
                logger.warning("gdelt_query_failed", query=query)

        self._last_poll = datetime.now(tz=UTC)
        logger.info(
            "gdelt_poll_complete", queries=len(all_queries), anomalies=len(events)
        )
        return events

    async def check_topic(self, topic: str) -> GdeltEvent | None:
        """Check a specific topic for anomalies (on-demand)."""
        return await self._check_query(topic)

    async def update_baselines(self) -> None:
        """Update 7-day baselines for all watchlist queries."""
        for query in self._build_queries():
            try:
                vol_data = await self._client.timeline_volume(query, timespan="7d")
                tone_data = await self._client.timeline_tone(query, timespan="7d")

                avg_vol = 0.0
                if vol_data:
                    values = [d.get("value", 0) for d in vol_data]
                    avg_vol = sum(values) / len(values) if values else 0.0

                avg_tone = 0.0
                if tone_data:
                    values = [d.get("value", 0) for d in tone_data]
                    avg_tone = sum(values) / len(values) if values else 0.0

                self._baselines[query] = {"volume": avg_vol, "tone": avg_tone}
            except Exception:
                logger.warning("baseline_update_failed", query=query)

        logger.info("baselines_updated", count=len(self._baselines))

    def _build_queries(self) -> list[str]:
        """Build GDELT query strings from watchlist config."""
        queries: list[str] = []
        for theme in self._watchlist.get("themes", []):
            queries.append(theme)
        for actor in self._watchlist.get("actors", []):
            queries.append(actor)
        for country in self._watchlist.get("countries", []):
            queries.append(country)
        return queries

    async def _check_query(self, query: str) -> GdeltEvent | None:
        """Check a single query for anomalies."""
        # Get recent articles
        raw_articles = await self._client.article_search(
            query, timespan="15min", max_records=25
        )

        # Get current volume and tone
        vol_data = await self._client.timeline_volume(query, timespan="24h")
        tone_data = await self._client.timeline_tone(query, timespan="24h")

        # Parse current values
        current_volume = 0
        if vol_data:
            current_volume = vol_data[-1].get("value", 0)

        current_tone = 0.0
        if tone_data:
            current_tone = tone_data[-1].get("value", 0.0)

        # Get baseline
        baseline = self._baselines.get(query, {"volume": 0, "tone": 0})
        baseline_vol = baseline["volume"]
        baseline_tone = baseline["tone"]

        # Detect anomalies
        volume_ratio = (current_volume / baseline_vol) if baseline_vol > 0 else 0.0
        tone_shift = abs(current_tone - baseline_tone)

        is_volume_spike = volume_ratio >= _VOLUME_SPIKE_RATIO
        is_tone_shift = tone_shift >= _TONE_SHIFT_THRESHOLD

        if not is_volume_spike and not is_tone_shift:
            return None

        # Determine event type
        if is_volume_spike and is_tone_shift:
            event_type = "volume_spike+tone_shift"
        elif is_volume_spike:
            event_type = "volume_spike"
        else:
            event_type = "tone_shift"

        # Parse articles
        articles = [
            GdeltArticle(
                url=a.get("url", ""),
                title=a.get("title", ""),
                seen_date=_parse_gdelt_date(a.get("seendate", "")),
                domain=a.get("domain", ""),
                source_country=a.get("sourcecountry", ""),
                language=a.get("language", "English"),
            )
            for a in raw_articles[:10]
        ]

        return GdeltEvent(
            query=query,
            event_type=event_type,
            detected_at=datetime.now(tz=UTC),
            articles=articles,
            tone=ToneScore(
                value=current_tone,
                baseline=baseline_tone,
                shift=round(current_tone - baseline_tone, 3),
                is_anomaly=is_tone_shift,
            ),
            volume_current=current_volume,
            volume_baseline=int(baseline_vol),
            volume_ratio=round(volume_ratio, 2),
            relevance_score=min(1.0, volume_ratio / 5 + tone_shift / 5),
        )


def _parse_gdelt_date(date_str: str) -> datetime | None:
    """Parse GDELT date format: 20260404T120000Z."""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None
