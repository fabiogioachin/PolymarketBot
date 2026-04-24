"""Intelligence pipeline data models."""

from datetime import datetime

from pydantic import BaseModel, Field

# Canonical TimeHorizon definition lives in models.market (Phase 10).
# Re-exported here for backward compatibility with intelligence importers.
from app.models.market import TimeHorizon  # noqa: F401


class GdeltArticle(BaseModel):
    """A single GDELT article result."""

    url: str = ""
    title: str = ""
    seen_date: datetime | None = None
    domain: str = ""
    source_country: str = ""
    language: str = "English"


class ToneScore(BaseModel):
    """Tone/sentiment measurement."""

    value: float = 0.0  # -10 to +10 (GDELT Goldstein-like scale)
    baseline: float = 0.0  # 7-day average for comparison
    shift: float = 0.0  # value - baseline
    is_anomaly: bool = False


class VolumeData(BaseModel):
    """Article volume data point."""

    timestamp: datetime
    count: int = 0


class GdeltEvent(BaseModel):
    """A detected event/anomaly from GDELT monitoring."""

    query: str = ""
    event_type: str = ""  # "volume_spike", "tone_shift", "new_theme"
    detected_at: datetime | None = None
    articles: list[GdeltArticle] = Field(default_factory=list)
    tone: ToneScore = Field(default_factory=ToneScore)
    volume_current: int = 0
    volume_baseline: int = 0
    volume_ratio: float = 0.0  # current / baseline
    domain: str = ""  # mapped market domain
    time_horizon: TimeHorizon = TimeHorizon.SHORT
    relevance_score: float = 0.0  # 0-1


class NewsItem(BaseModel):
    """A generic news item from any source (GDELT, RSS, institutional)."""

    source: str = ""  # "gdelt", "rss:reuters", "institutional:fed"
    title: str = ""
    url: str = ""
    published: datetime | None = None
    domain: str = ""  # mapped market domain
    time_horizon: TimeHorizon = TimeHorizon.MEDIUM
    summary: str = ""
    tags: list[str] = Field(default_factory=list)
    relevance_score: float = 0.0


class AnomalyReport(BaseModel):
    """Summary of detected anomalies from intelligence sources."""

    detected_at: datetime | None = None
    events: list[GdeltEvent] = Field(default_factory=list)
    news_items: list[NewsItem] = Field(default_factory=list)
    total_anomalies: int = 0


# ── Phase 13 S2: Platform data collectors ──────────────────────────────


class WhaleTrade(BaseModel):
    """A large trade detected on Polymarket (size >= whale threshold)."""

    id: str
    timestamp: datetime
    market_id: str
    wallet_address: str
    side: str  # "BUY" | "SELL"
    size_usd: float
    price: float
    is_pre_resolution: bool = False
    raw_json: str = ""
    # Populated by S3 (wallet enrichment from subgraph); None until then.
    wallet_total_pnl: float | None = None
    wallet_weekly_pnl: float | None = None
    wallet_volume_rank: int | None = None


class PopularMarket(BaseModel):
    """A market snapshot ranked by 24h volume."""

    market_id: str
    question: str = ""
    volume24h: float = 0.0
    liquidity: float | None = None
    snapshot_time: datetime


class LeaderboardEntry(BaseModel):
    """A single leaderboard row: top trader by PnL for a timeframe."""

    rank: int
    wallet_address: str
    pnl_usd: float
    win_rate: float | None = None
    timeframe: str
    snapshot_time: datetime
