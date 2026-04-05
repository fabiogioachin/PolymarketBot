"""Resolution tracker: checks if markets with open positions have resolved.

When a Polymarket market resolves:
- outcomePrices becomes ["1","0"] or ["0","1"]
- The winning outcome pays $1/share, the losing pays $0
- This is the ONLY way to realize P&L on prediction markets (besides selling)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.clients.polymarket_rest import polymarket_rest
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ResolutionResult:
    """Result of checking a market for resolution."""

    market_id: str
    resolved: bool = False
    winning_outcome: str = ""  # "Yes" or "No"
    outcome_payouts: dict[str, float] | None = None  # token_id -> payout (0 or 1)


async def check_resolution(market_id: str) -> ResolutionResult:
    """Check if a market has resolved and determine payouts.

    Returns a ResolutionResult with payout per token_id.
    """
    try:
        market = await polymarket_rest.get_market(market_id)
    except Exception as e:
        logger.warning("resolution_check_failed", market_id=market_id, error=str(e))
        return ResolutionResult(market_id=market_id)

    # Check if market is closed/resolved
    if not (market.status.value in ("closed", "resolved")):
        return ResolutionResult(market_id=market_id)

    # Check if outcome prices indicate resolution
    # Resolved markets have prices at exactly 0 or 1
    resolved = False
    payouts: dict[str, float] = {}
    winning = ""

    for outcome in market.outcomes:
        if outcome.price >= 0.95:
            # This outcome won
            payouts[outcome.token_id] = 1.0
            resolved = True
            winning = outcome.outcome
        elif outcome.price <= 0.05:
            # This outcome lost
            payouts[outcome.token_id] = 0.0
            resolved = True
        else:
            # Price not at boundary — market may be closed but not resolved
            # (e.g., still settling)
            pass

    if not resolved:
        return ResolutionResult(market_id=market_id)

    logger.info(
        "market_resolved",
        market_id=market_id,
        winning_outcome=winning,
        question=market.question[:60],
    )

    return ResolutionResult(
        market_id=market_id,
        resolved=True,
        winning_outcome=winning,
        outcome_payouts=payouts,
    )
