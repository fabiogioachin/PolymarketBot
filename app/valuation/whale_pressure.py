"""Whale pressure VAE signal — event-style (Phase 13 S4b).

Returns a probability-like float in [0, 1] capturing directional pressure from
whale trades observed on Polymarket:

- 0.5  → neutral (no whale activity, or BUY/SELL pressure balanced)
- >0.5 → aggregate BUY pressure (influential wallets buying YES)
- <0.5 → aggregate SELL pressure

The signal is consumed by the VAE in event-style (independent probability),
see D3 in ``.claude/plans/phase-13/00-decisions.md``.

Criteria (D4):
    (a) single trade size ≥ $100k            → base weight 1.0
    (b) wallet_volume_rank in top 10%         → +0.5
    (c) wallet_total_pnl > $500k OR
        wallet_weekly_pnl > $50k              → +0.5
    (d) new wallet (age < 7 days) AND
        size_usd ≥ $1M                        → weight 3.0 (max, overrides)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.core.logging import get_logger
from app.models.intelligence import WhaleTrade

logger = get_logger(__name__)

# ── Tunable thresholds (keep in sync with D4) ──────────────────────────
_SIZE_BASE_USD = 100_000.0
_SIZE_EXTREME_USD = 1_000_000.0
_TOP_RANK_THRESHOLD = 1_000            # best (lowest-rank value) 1000 wallets ~ top 10%
_PNL_TOTAL_THRESHOLD_USD = 500_000.0
_PNL_WEEKLY_THRESHOLD_USD = 50_000.0
_NEW_WALLET_MAX_AGE_DAYS = 7
_MAX_TRADE_WEIGHT = 3.0


def compute_whale_pressure(
    whale_trades: list[WhaleTrade],
    market_price: float,
    lookback_hours: int = 6,
    now: datetime | None = None,
) -> float:
    """Aggregate whale BUY/SELL pressure into a [0, 1] signal.

    Args:
        whale_trades: whale trades for a single market (already filtered by
            ``WhaleOrchestrator``). May be empty.
        market_price: current YES probability (unused for output, kept for
            symmetry with ``compute_insider_pressure``).
        lookback_hours: drop trades older than this window.
        now: override for reference time (used in tests to freeze the window).

    Returns:
        Signal in [0, 1]. 0.5 when no qualifying whales or perfectly balanced.
    """
    del market_price  # kept for signature parity with insider_pressure

    if not whale_trades:
        return 0.5

    reference = now or datetime.now(tz=UTC)
    cutoff = reference - timedelta(hours=lookback_hours)

    buy_weight = 0.0
    sell_weight = 0.0

    for trade in whale_trades:
        if trade.timestamp < cutoff:
            continue
        weight = _trade_weight(trade)
        if weight <= 0.0:
            continue
        if trade.side == "BUY":
            buy_weight += weight
        elif trade.side == "SELL":
            sell_weight += weight
        # Unknown sides are ignored defensively.

    total_weight = buy_weight + sell_weight
    if total_weight <= 0.0:
        return 0.5

    net_pressure = (buy_weight - sell_weight) / total_weight  # [-1, 1]
    signal = 0.5 + net_pressure * 0.5
    signal = max(0.0, min(1.0, signal))

    logger.debug(
        "whale_pressure_computed",
        buy_weight=round(buy_weight, 3),
        sell_weight=round(sell_weight, 3),
        signal=round(signal, 4),
        trades_considered=len(whale_trades),
    )
    return signal


def _trade_weight(trade: WhaleTrade) -> float:
    """Compute the influence weight of a single whale trade per D4 criteria.

    Returns 0.0 if the trade does not meet the minimum size threshold.
    The extreme-new-wallet rule overrides the additive criteria and caps at
    ``_MAX_TRADE_WEIGHT``.
    """
    if trade.size_usd < _SIZE_BASE_USD:
        return 0.0

    # (d) Extreme override: "new wallet + $1M+" receives the maximum weight.
    #
    # WhaleTrade currently does not carry a ``first_seen`` / ``age_days`` field
    # (subgraph enrichment in S3 only populates pnl + volume rank). As a proxy
    # for "new / unknown wallet" we treat the absence of BOTH a volume rank
    # and pnl metrics as a signal that the wallet is not yet in the subgraph's
    # aggregated tables — i.e. brand new or extremely low-activity. Combined
    # with a $1M+ trade this matches D4's "insider quasi certo" criterion.
    is_unknown_wallet = (
        trade.wallet_volume_rank is None
        and trade.wallet_total_pnl is None
        and trade.wallet_weekly_pnl is None
    )
    if is_unknown_wallet and trade.size_usd >= _SIZE_EXTREME_USD:
        return _MAX_TRADE_WEIGHT

    # (a) Base weight: qualified whale
    weight = 1.0

    # (b) Top-volume wallet bonus
    rank = trade.wallet_volume_rank
    if rank is not None and rank > 0 and rank <= _TOP_RANK_THRESHOLD:
        weight += 0.5

    # (c) PnL bonus
    pnl_total = trade.wallet_total_pnl
    pnl_weekly = trade.wallet_weekly_pnl
    if (
        (pnl_total is not None and pnl_total > _PNL_TOTAL_THRESHOLD_USD)
        or (pnl_weekly is not None and pnl_weekly > _PNL_WEEKLY_THRESHOLD_USD)
    ):
        weight += 0.5

    return min(weight, _MAX_TRADE_WEIGHT)
