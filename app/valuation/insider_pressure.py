"""Insider pressure VAE signal — microstructure-style (Phase 13 S4b).

Detects suspicious pre-resolution whale activity on Polymarket. Unlike
``whale_pressure`` (event-style, takes an independent probability), this
signal is **microstructure-style**: the VAE consumes it as a small
probability nudge centered on ``market_price`` (see D3 in
``.claude/plans/phase-13/00-decisions.md``).

Output in [0, 1]:
    - 0.5  → no suspicious activity (default)
    - >0.5 → suspicious BUY (informed money entering YES side)
    - <0.5 → suspicious SELL (informed money exiting / shorting YES)

Detection criteria (D4 insider):
    - Filter out *obvious outcome* markets: if ``market_price`` is already
      extreme (>0.95 or <0.05), any trade there is likely not insider
      information — signal returns 0.5.
    - Only ``is_pre_resolution`` trades qualify (within 30 min of
      ``resolution_datetime``).
    - Per-trade "insider score" increments when:
        * wallet_total_pnl is high (track record → likely informed), OR
        * wallet is unknown (new account) AND size ≥ $1M (fresh whale).
    - If ≥2 suspicious trades match → escalate signal to [0.7, 0.9] range
      preserving direction (BUY vs SELL).
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.models.intelligence import WhaleTrade
from app.models.market import Market

logger = get_logger(__name__)

# ── Tunables (keep in sync with D4) ────────────────────────────────────
_OBVIOUS_UPPER = 0.95
_OBVIOUS_LOWER = 0.05
_INSIDER_PNL_THRESHOLD_USD = 500_000.0
_INSIDER_EXTREME_SIZE_USD = 1_000_000.0
_ESCALATION_MIN_MATCHES = 2
_NEUTRAL = 0.5
_STRONG_LOW = 0.7
_STRONG_HIGH = 0.9


def compute_insider_pressure(
    market: Market,
    recent_trades: list[WhaleTrade],
    market_price: float,
) -> float:
    """Compute insider pressure signal in [0, 1].

    Args:
        market: the market being evaluated (used only for the obvious-outcome
            filter; resolution window is pre-applied by ``WhaleOrchestrator``
            via ``is_pre_resolution``).
        recent_trades: recent whale trades for this market.
        market_price: current YES probability.

    Returns:
        0.5 when nothing suspicious, otherwise a value in [0, 1] carrying
        direction (BUY/SELL) and intensity.
    """
    del market  # reserved for future use (e.g., per-category tuning)

    # Filter: obvious-outcome markets yield no insider signal.
    if market_price >= _OBVIOUS_UPPER or market_price <= _OBVIOUS_LOWER:
        return _NEUTRAL

    # Restrict to pre-resolution window (flagged by WhaleOrchestrator).
    pre_res = [t for t in recent_trades if t.is_pre_resolution]
    if not pre_res:
        return _NEUTRAL

    buy_matches = 0
    sell_matches = 0

    for trade in pre_res:
        matches = _insider_match_count(trade)
        if matches < _ESCALATION_MIN_MATCHES:
            continue
        if trade.side == "BUY":
            buy_matches += 1
        elif trade.side == "SELL":
            sell_matches += 1

    total_matches = buy_matches + sell_matches
    if total_matches == 0:
        return _NEUTRAL

    # Direction: dominant side carries the signal; perfectly balanced → neutral.
    if buy_matches == sell_matches:
        return _NEUTRAL

    direction_up = buy_matches > sell_matches
    dominant = max(buy_matches, sell_matches)
    # Intensity: at least one qualifying trade → 0.7, each additional
    # qualifying trade adds 0.1, clamped at 0.9 (D4 escalation band).
    intensity = min(
        _STRONG_HIGH,
        _STRONG_LOW + 0.1 * (dominant - 1),
    )

    signal = intensity if direction_up else (1.0 - intensity)
    signal = max(0.0, min(1.0, signal))

    logger.debug(
        "insider_pressure_computed",
        buy_matches=buy_matches,
        sell_matches=sell_matches,
        intensity=round(intensity, 3),
        signal=round(signal, 4),
    )
    return signal


def _insider_match_count(trade: WhaleTrade) -> int:
    """Count how many D4 insider criteria a single pre-resolution trade meets.

    Criteria scored (binary):
        1. High-PnL wallet (track record)
        2. Unknown wallet + extreme size (fresh large whale)
        3. Extreme size alone ($1M+) regardless of enrichment
    """
    count = 0

    # 1. High-PnL track record
    if (
        trade.wallet_total_pnl is not None
        and trade.wallet_total_pnl > _INSIDER_PNL_THRESHOLD_USD
    ):
        count += 1

    # 2. Unknown wallet AND extreme size — prime insider pattern
    is_unknown_wallet = (
        trade.wallet_volume_rank is None
        and trade.wallet_total_pnl is None
        and trade.wallet_weekly_pnl is None
    )
    if is_unknown_wallet and trade.size_usd >= _INSIDER_EXTREME_SIZE_USD:
        count += 1

    # 3. Extreme size alone is itself a criterion (D4 lists "size $1M+" as a
    #    standalone flag combined with pre-res window).
    if trade.size_usd >= _INSIDER_EXTREME_SIZE_USD:
        count += 1

    return count
