"""Intelligence pipeline API endpoints."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.core.dependencies import (
    get_intelligence_orchestrator,
    get_popular_markets_orchestrator,
    get_whale_orchestrator,
)
from app.core.logging import get_logger
from app.models.intelligence import (
    AnomalyReport,
    LeaderboardEntry,
    PopularMarket,
    WhaleTrade,
)
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


# ── Phase 13 S2 endpoints ────────────────────────────────────────────


@router.get("/intelligence/whales", response_model=list[WhaleTrade])
async def get_whales(
    market_id: str | None = Query(default=None),
    since_minutes: int = Query(default=60, ge=1, le=10_080),
    min_size: float = Query(default=0.0, ge=0.0),
    limit: int = Query(default=50, ge=1, le=500),
) -> list[WhaleTrade]:
    """Return whale trades.

    If `market_id` is provided, reads from the store for that market. Otherwise
    returns the most recent in-memory detections from the orchestrator.
    """
    orch = get_whale_orchestrator()
    if market_id:
        trades = await orch.get_whale_activity(
            market_id, since_minutes=since_minutes
        )
    else:
        cutoff = datetime.now(tz=UTC) - timedelta(minutes=since_minutes)
        trades = [t for t in orch._recent_trades if t.timestamp >= cutoff]
    filtered = [t for t in trades if t.size_usd >= min_size]
    return filtered[:limit]


@router.get("/intelligence/popular-markets", response_model=list[PopularMarket])
async def get_popular_markets(
    limit: int = Query(default=20, ge=1, le=200),
) -> list[PopularMarket]:
    """Return the latest popular-markets snapshot."""
    orch = get_popular_markets_orchestrator()
    snapshot = orch.get_popular_markets()
    if not snapshot and orch._trade_store is not None:
        rows = await orch._trade_store.load_latest_popular_markets(limit)
        snapshot = [
            PopularMarket(
                market_id=str(r["market_id"]),
                question=str(r.get("question", "") or ""),
                volume24h=float(r["volume24h"]),
                liquidity=(
                    float(r["liquidity"]) if r.get("liquidity") is not None else None
                ),
                snapshot_time=datetime.fromtimestamp(
                    float(r["snapshot_time"]), tz=UTC
                ),
            )
            for r in rows
        ]
    return snapshot[:limit]


@router.get("/intelligence/leaderboard", response_model=list[LeaderboardEntry])
async def get_leaderboard(
    timeframe: str = Query(default="monthly"),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[LeaderboardEntry]:
    """Return the latest leaderboard snapshot for a timeframe."""
    from app.core.dependencies import get_execution_engine

    engine = await get_execution_engine()
    store = engine._store
    if store is None:
        return []
    rows = await store.load_latest_leaderboard(timeframe, limit)
    return [
        LeaderboardEntry(
            rank=int(r["rank"]),
            wallet_address=str(r["wallet_address"]),
            pnl_usd=float(r["pnl_usd"]),
            win_rate=(
                float(r["win_rate"]) if r.get("win_rate") is not None else None
            ),
            timeframe=str(r["timeframe"]),
            snapshot_time=datetime.fromtimestamp(
                float(r["snapshot_time"]), tz=UTC
            ),
        )
        for r in rows
    ]
