"""Position monitor for prediction market positions.

Exit logic for prediction markets is fundamentally different from equities:
- Positions are binary bets — they resolve to $1 or $0
- Price oscillations before resolution are noise, not signal
- "Stop loss" on small price moves makes no sense — you bought the probability
- Exit when: edge vanished (valuation changed), market about to resolve with
  wrong outcome, or you can sell at a profit

Exit triggers:
1. SELL at profit: current price significantly above entry (take profit on secondary market)
2. Edge reversed: valuation now says fair_value < entry price (your thesis was wrong)
3. Near resolution with wrong direction: price collapsed toward 0 near expiry
4. Opportunity cost: capital locked in a position with no remaining edge
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from app.core.logging import get_logger
from app.models.order import OrderRequest, OrderSide, Position

if TYPE_CHECKING:
    from app.models.market import Market
    from app.models.valuation import ValuationResult

logger = get_logger(__name__)

# Take profit: sell if price rose enough to lock in gain
_TAKE_PROFIT_RATIO = 1.5  # sell if current_price / entry_price >= 1.5

# Edge reversal: exit if valuation now says position is wrong
_EDGE_REVERSAL_THRESHOLD = -0.03  # exit if edge flipped to -3%+

# Near expiry: flatten positions within this many hours of resolution
_FLATTEN_HOURS = 12

# Near expiry + price collapsed: strong signal the bet is losing
_COLLAPSE_PRICE = 0.05  # if price < 5 cents near expiry, outcome is losing


@dataclass
class ExitDecision:
    should_exit: bool = False
    reason: str = ""
    urgency: float = 0.0  # 0-1


def evaluate_exit(
    position: Position,
    market: Market | None = None,
    valuation: ValuationResult | None = None,
) -> ExitDecision:
    """Evaluate whether to sell a position on the secondary market.

    Does NOT use stop-loss on price oscillations — prediction markets
    are binary events, not continuous price processes.
    """
    if position.size <= 0:
        return ExitDecision()

    entry = position.avg_price
    current = position.current_price

    if entry <= 0 or current <= 0:
        return ExitDecision()

    # 1. Take profit: price rose significantly, lock in secondary market gain
    if current > 0 and entry > 0 and current / entry >= _TAKE_PROFIT_RATIO:
        gain_pct = (current - entry) / entry * 100
        return ExitDecision(
            should_exit=True,
            reason=f"Take profit: price {entry:.3f} -> {current:.3f} (+{gain_pct:.0f}%)",
            urgency=0.6,
        )

    # 2. Edge reversed: valuation now disagrees with our position
    if valuation:
        # We bought YES (or NO) because we thought fair_value > market_price
        # If the edge has reversed, our thesis is wrong
        if valuation.fee_adjusted_edge < _EDGE_REVERSAL_THRESHOLD:
            return ExitDecision(
                should_exit=True,
                reason=(
                    f"Edge reversed: current edge {valuation.fee_adjusted_edge:.3f} "
                    f"(was positive at entry)"
                ),
                urgency=0.5,
            )

    # 3. Near resolution: flatten to avoid binary risk
    if market and market.end_date:
        time_left = market.end_date - datetime.now(tz=UTC)
        if time_left < timedelta(hours=_FLATTEN_HOURS):
            hours = time_left.total_seconds() / 3600
            # If price collapsed near expiry, the bet is almost certainly losing.
            # "Collapsed" means it DROPPED significantly from entry, not just that
            # the absolute price is low. A token bought at 0.003 still at 0.002
            # hasn't collapsed — it was always a long-shot bet.
            price_dropped = entry > 0 and current < entry * 0.5
            if current < _COLLAPSE_PRICE and price_dropped:
                return ExitDecision(
                    should_exit=True,
                    reason=(
                        f"Expiry in {hours:.1f}h, price collapsed to {current:.3f} "
                        f"from entry {entry:.3f} — likely losing"
                    ),
                    urgency=0.9,
                )
            # Flatten near expiry ONLY for mid-range positions (0.10-0.80).
            # Very low prices (< 0.10) are cheap long-shot bets — let them ride
            # to resolution. The downside is capped at the small entry cost.
            if 0.10 <= current < 0.80:
                return ExitDecision(
                    should_exit=True,
                    reason=f"Expiry in {hours:.1f}h — flattening to avoid resolution risk",
                    urgency=0.7,
                )

    return ExitDecision()


def build_exit_order(position: Position) -> OrderRequest:
    """Build a SELL order to close a BUY position."""
    return OrderRequest(
        token_id=position.token_id,
        side=OrderSide.SELL,
        price=position.current_price if position.current_price > 0 else position.avg_price,
        size=position.size,
        market_id=position.market_id,
        reason="position_exit",
    )
