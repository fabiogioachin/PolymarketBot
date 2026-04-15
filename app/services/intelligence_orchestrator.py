"""Intelligence orchestrator: coordinates GDELT, RSS, and KG for event detection."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from app.core.logging import get_logger
from app.models.intelligence import AnomalyReport, GdeltEvent
from app.services.gdelt_service import GdeltService
from app.services.knowledge_service import KnowledgeService
from app.services.news_service import NewsService

logger = get_logger(__name__)


class IntelligenceOrchestrator:
    """Orchestrates the intelligence pipeline tick cycle."""

    def __init__(
        self,
        *,
        gdelt_service: GdeltService | None = None,
        news_service: NewsService | None = None,
        knowledge_service: KnowledgeService | None = None,
        trade_store: Any = None,
    ) -> None:
        self._gdelt = gdelt_service or GdeltService()
        self._news = news_service or NewsService()
        self._knowledge = knowledge_service or KnowledgeService()
        self._last_tick: datetime | None = None
        self._anomaly_history: list[AnomalyReport] = []
        self._trade_store = trade_store

    @property
    def last_tick(self) -> datetime | None:
        """Timestamp of the last intelligence tick."""
        return self._last_tick

    async def set_trade_store(self, store: Any) -> None:
        """Wire the trade store for anomaly persistence and load history."""
        self._trade_store = store
        try:
            reports = await store.load_anomaly_reports(100)
            for r in reports:
                report = AnomalyReport(
                    detected_at=datetime.fromisoformat(str(r["detected_at"])),
                    events=[],
                    news_items=[],
                    total_anomalies=int(r["total_anomalies"]),
                )
                self._anomaly_history.append(report)
            if reports:
                logger.info(
                    "anomaly_history_loaded",
                    count=len(reports),
                )
        except Exception:
            logger.warning("anomaly_history_load_failed", exc_info=True)

    async def tick(self) -> AnomalyReport:
        """Execute one intelligence cycle.

        1. Poll GDELT watchlist for anomalies
        2. Fetch RSS + institutional news
        3. For each anomaly: classify domain, match KG patterns, write events
        4. Return consolidated anomaly report
        """
        now = datetime.now(tz=UTC)

        # 1. GDELT anomalies
        gdelt_events = await self._gdelt.poll_watchlist()

        # 2. RSS news
        news_items = await self._news.fetch_all()

        # 3. Process anomalies through KG
        for event in gdelt_events:
            await self._process_event(event)

        # 4. Check news for high-relevance items
        relevant_news = [n for n in news_items if n.relevance_score > 0.5]

        report = AnomalyReport(
            detected_at=now,
            events=gdelt_events,
            news_items=relevant_news,
            total_anomalies=len(gdelt_events) + len(relevant_news),
        )

        self._anomaly_history.append(report)
        # Keep last 100 reports
        if len(self._anomaly_history) > 100:
            self._anomaly_history = self._anomaly_history[-100:]

        # Persist to SQLite
        if self._trade_store is not None:
            try:
                await self._trade_store.save_anomaly_report({
                    "detected_at": report.detected_at.isoformat()
                    if report.detected_at
                    else now.isoformat(),
                    "total_anomalies": report.total_anomalies,
                    "events_json": json.dumps(
                        [e.model_dump(mode="json") for e in report.events]
                    ),
                    "news_json": json.dumps(
                        [n.model_dump(mode="json") for n in report.news_items]
                    ),
                })
            except Exception as exc:
                logger.warning("anomaly_persist_failed", error=str(exc))

        self._last_tick = now
        logger.info(
            "intelligence_tick",
            gdelt_events=len(gdelt_events),
            news_items=len(news_items),
            anomalies=report.total_anomalies,
        )
        return report

    async def _process_event(self, event: GdeltEvent) -> None:
        """Process a GDELT event: classify, match patterns, write to KG."""
        domain = event.domain or self._infer_domain(event.query)
        event.domain = domain

        # Match against KG patterns
        article_titles = " ".join(a.title for a in event.articles[:5])
        event_text = f"{event.query} {article_titles}"
        matches = await self._knowledge.match_patterns(domain, event_text)

        if matches:
            # Update event relevance based on pattern matches
            best_match = matches[0].match_score
            event.relevance_score = max(event.relevance_score, best_match)

            logger.info(
                "event_pattern_match",
                query=event.query,
                domain=domain,
                patterns_matched=len(matches),
                best_score=best_match,
            )

        # Write event to KG
        title = f"{event.event_type}: {event.query}"
        content = f"## {event.event_type}\n\n"
        content += f"- **Query**: {event.query}\n"
        content += (
            f"- **Volume**: {event.volume_current} "
            f"(baseline: {event.volume_baseline}, ratio: {event.volume_ratio})\n"
        )
        content += f"- **Tone**: {event.tone.value:.2f} (shift: {event.tone.shift:+.2f})\n"
        if event.articles:
            content += "\n### Top Articles\n"
            for article in event.articles[:5]:
                content += f"- [{article.title}]({article.url})\n"

        await self._knowledge.write_event(
            domain=domain,
            title=title,
            content=content,
            tags=[event.event_type, event.query],
        )

    def get_recent_anomalies(self, limit: int = 10) -> list[AnomalyReport]:
        """Get recent anomaly reports."""
        return self._anomaly_history[-limit:]

    def get_event_signal(self, domain: str) -> float:
        """Get the current event signal for a domain (for the Value Engine).

        Returns 0-1: higher means more significant events detected.
        """
        if not self._anomaly_history:
            return 0.0

        latest = self._anomaly_history[-1]
        domain_events = [e for e in latest.events if e.domain == domain]

        if not domain_events:
            return 0.0

        # Aggregate relevance scores
        max_relevance = max(e.relevance_score for e in domain_events)
        return min(1.0, max_relevance)

    @staticmethod
    def _infer_domain(query: str) -> str:
        """Infer market domain from a GDELT query string."""
        query_lower = query.lower()
        domain_hints = {
            "election": "politics",
            "econ": "economics",
            "inflation": "economics",
            "interest_rate": "economics",
            "climate": "science",
            "conflict": "geopolitics",
            "war": "geopolitics",
            "usa": "politics",
            "rus": "geopolitics",
            "chn": "geopolitics",
        }
        for hint, domain in domain_hints.items():
            if hint in query_lower:
                return domain
        return "other"
