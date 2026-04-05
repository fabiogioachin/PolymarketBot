"""Intelligence pipeline API endpoints."""

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.core.logging import get_logger
from app.models.intelligence import AnomalyReport
from app.services.enrichment_service import EnrichmentResult, EnrichmentService
from app.services.intelligence_orchestrator import IntelligenceOrchestrator

logger = get_logger(__name__)

router = APIRouter()

# Module-level singletons (will be replaced by proper DI later)
_orchestrator = IntelligenceOrchestrator()
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
    return _orchestrator.get_recent_anomalies(limit=limit)


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
