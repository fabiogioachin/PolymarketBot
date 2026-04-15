"""Intelligence pipeline API endpoints."""

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.core.dependencies import get_intelligence_orchestrator
from app.core.logging import get_logger
from app.models.intelligence import AnomalyReport
from app.services.enrichment_service import EnrichmentResult, EnrichmentService

logger = get_logger(__name__)

router = APIRouter()

_enrichment = EnrichmentService()


class EnrichRequest(BaseModel):
    topic: str
    domain: str = ""
    depth: str = "standard"
    timespan: str = "7d"


class WatchlistResponse(BaseModel):
    themes: list[str]
    actors: list[str]
    countries: list[str]


@router.post("/intelligence/enrich", response_model=EnrichmentResult)
async def enrich_topic(request: EnrichRequest) -> EnrichmentResult:
    """Perform on-demand enrichment for a topic."""
    return await _enrichment.enrich_topic(
        request.topic,
        domain=request.domain,
        depth=request.depth,
        timespan=request.timespan,
    )


@router.get("/intelligence/anomalies", response_model=list[AnomalyReport])
async def get_anomalies(
    limit: int = Query(default=10, le=100),
) -> list[AnomalyReport]:
    """Get recent anomaly reports."""
    return get_intelligence_orchestrator().get_recent_anomalies(limit=limit)


@router.get("/intelligence/news")
async def get_news() -> list[dict]:
    """Get cached RSS/institutional news items."""
    orch = get_intelligence_orchestrator()
    items = orch._news.get_cached()
    return [
        {
            "title": item.title,
            "source": item.source,
            "domain": item.domain,
            "published": item.published.isoformat() if item.published else None,
            "url": item.url,
            "summary": item.summary[:200] if item.summary else "",
            "relevance_score": item.relevance_score,
        }
        for item in items[:30]
    ]


@router.get("/intelligence/watchlist", response_model=WatchlistResponse)
async def get_watchlist() -> WatchlistResponse:
    """Get the current GDELT watchlist configuration."""
    from app.core.yaml_config import app_config

    wl = app_config.intelligence.gdelt.watchlist
    return WatchlistResponse(
        themes=wl.get("themes", []),
        actors=wl.get("actors", []),
        countries=wl.get("countries", []),
    )
