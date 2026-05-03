"""DSS (Decision Support System) snapshot data models.

Defines the schema for ``static/dss/intelligence_snapshot.json``.
Written every 5 minutes by :class:`~app.services.snapshot_writer.SnapshotWriter`.
Read by the standalone DSS HTML artifact (S5a).

Design constraints:
- Stateless: no history arrays (charts fetch live from CLOB).
- Size cap: <200 KB with 50 markets + 50 whales (localStorage limit).
- Atomic write: tmp file + os.replace ensures readers never see partial JSON.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class DSSSnapshotMarket(BaseModel):
    """Snapshot of a single monitored market's current valuation state."""

    market_id: str
    question: str
    market_price: float
    outcomes: dict[str, float] = {}  # e.g. {"Yes": 0.45, "No": 0.55}
    fair_value: float | None = None
    edge_central: float | None = None
    edge_lower: float | None = None
    edge_dynamic: float | None = None
    realized_volatility: float | None = None
    has_open_position: bool = False
    recommendation: str | None = None  # BUY | SELL | HOLD | STRONG_BUY | STRONG_SELL


class DSSSnapshotWhale(BaseModel):
    """A single whale/insider trade record for the DSS feed."""

    timestamp: datetime
    market_id: str
    question: str = ""  # Resolved from market_service cache; empty if unknown.
    outcome: str = ""   # "Yes" or "No" — derived from asset_id in raw_json.
    wallet_address: str
    side: str           # BUY or SELL (on the outcome above)
    size_usd: float
    is_pre_resolution: bool = False
    wallet_total_pnl: float | None = None


class DSSSnapshot(BaseModel):
    """Full DSS snapshot — the JSON contract between backend and dss.html.

    Fields
    ------
    generated_at:
        UTC timestamp when the snapshot was written.
    config_version:
        ``{app.name}:{app.version}`` for cache-busting on config reload.
    weights:
        Copy of ``valuation.weights`` from active config.
    volatility_config:
        Key volatility parameters for the DSS overlay.
    monitored_markets:
        Top ~50 markets by VAE |edge| + any market with an open position.
    recent_whales:
        Whale trades in the last 6 hours, capped at 50 entries.
    recent_insiders:
        Insider (pre-resolution) trades in the last 24 hours (may be empty
        until S4b whale/insider signals are committed).
    popular_markets_top20:
        Latest PopularMarketsOrchestrator snapshot (top 20 by volume24h).
    leaderboard_top50:
        Latest LeaderboardOrchestrator snapshot (top 50 traders by PnL).
    open_positions:
        All currently open positions with their token_id, market_id, side,
        size, avg_price, current_price.
    risk_state:
        Snapshot of key risk metrics for the DSS risk panel.
    """

    generated_at: datetime
    config_version: str
    weights: dict[str, float]
    volatility_config: dict[str, float]
    monitored_markets: list[DSSSnapshotMarket]
    recent_whales: list[DSSSnapshotWhale]
    recent_insiders: list[DSSSnapshotWhale]
    popular_markets_top20: list[dict]  # type: ignore[type-arg]
    leaderboard_top50: list[dict]  # type: ignore[type-arg]
    open_positions: list[dict]  # type: ignore[type-arg]
    risk_state: dict  # type: ignore[type-arg]
