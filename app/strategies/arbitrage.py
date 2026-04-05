"""Arbitrage strategy — detects YES+NO mispricing and cross-market inconsistencies."""

from datetime import UTC, datetime

from app.core.logging import get_logger
from app.models.knowledge import KnowledgeContext
from app.models.market import Market, MarketCategory
from app.models.signal import Signal, SignalType
from app.models.valuation import ValuationResult

logger = get_logger(__name__)

# Minimum profit threshold after fees to emit a signal
_MIN_PROFIT = 0.01


class ArbitrageStrategy:
    """Detects YES+NO mispricing and cross-market inconsistencies.

    A binary market must have YES + NO prices summing to exactly 1.0.
    When fees are applied the no-arb band widens.  Any deviation beyond
    that band represents a risk-free profit opportunity.
    """

    # Fee rates by market category (taker side, applied once)
    FEE_RATES: dict[str, float] = {
        "geopolitics": 0.0,
        "politics": 0.0,
        "crypto": 0.072,
        "sports": 0.03,
    }
    DEFAULT_FEE: float = 0.02

    @property
    def name(self) -> str:
        return "arbitrage"

    @property
    def domain_filter(self) -> list[str]:
        return []  # applies to all domains

    def _fee_rate(self, market: Market) -> float:
        """Return the applicable fee rate for a market's category."""
        cat = (
            market.category.value
            if isinstance(market.category, MarketCategory)
            else str(market.category)
        )
        return self.FEE_RATES.get(cat, self.DEFAULT_FEE)

    async def evaluate(
        self,
        market: Market,
        valuation: ValuationResult,
        knowledge: KnowledgeContext | None = None,
    ) -> list[Signal] | None:
        """Detect YES+NO pricing anomalies and return both arbitrage legs.

        Returns a list of two signals (YES leg + NO leg) for proper two-legged
        execution, or None if no mispricing is detected.
        """
        outcomes = market.outcomes
        if len(outcomes) < 2:
            return None

        yes_outcome = next((o for o in outcomes if o.outcome.lower() == "yes"), None)
        no_outcome = next((o for o in outcomes if o.outcome.lower() == "no"), None)

        if yes_outcome is None or no_outcome is None:
            return None

        yes_price = yes_outcome.price
        no_price = no_outcome.price
        total = yes_price + no_price
        fee = self._fee_rate(market)

        # BUY both sides: guaranteed profit when total < 1.0 - fee
        # (cost = total, payout = 1.0, net = 1.0 - total - fee)
        buy_profit = 1.0 - total - fee
        if buy_profit > _MIN_PROFIT:
            reasoning = (
                f"YES ({yes_price:.3f}) + NO ({no_price:.3f}) = {total:.3f}; "
                f"fee={fee:.3f}; buy-both profit={buy_profit:.3f}"
            )
            logger.info(
                "arbitrage: buy-both signal",
                market_id=market.id,
                yes_price=yes_price,
                no_price=no_price,
                profit=buy_profit,
            )
            confidence = min(buy_profit * 10, 1.0)
            now = datetime.now(UTC)
            return [
                Signal(
                    strategy=self.name,
                    market_id=market.id,
                    token_id=yes_outcome.token_id,
                    signal_type=SignalType.BUY,
                    confidence=confidence,
                    market_price=yes_price,
                    edge_amount=buy_profit,
                    reasoning=reasoning,
                    timestamp=now,
                ),
                Signal(
                    strategy=self.name,
                    market_id=market.id,
                    token_id=no_outcome.token_id,
                    signal_type=SignalType.BUY,
                    confidence=confidence,
                    market_price=no_price,
                    edge_amount=buy_profit,
                    reasoning=reasoning,
                    timestamp=now,
                ),
            ]

        # SELL both sides: guaranteed profit when total > 1.0 + fee
        # (receive total, payout = 1.0, net = total - 1.0 - fee)
        sell_profit = total - 1.0 - fee
        if sell_profit > _MIN_PROFIT:
            reasoning = (
                f"YES ({yes_price:.3f}) + NO ({no_price:.3f}) = {total:.3f}; "
                f"fee={fee:.3f}; sell-both profit={sell_profit:.3f}"
            )
            logger.info(
                "arbitrage: sell-both signal",
                market_id=market.id,
                yes_price=yes_price,
                no_price=no_price,
                profit=sell_profit,
            )
            confidence = min(sell_profit * 10, 1.0)
            now = datetime.now(UTC)
            return [
                Signal(
                    strategy=self.name,
                    market_id=market.id,
                    token_id=yes_outcome.token_id,
                    signal_type=SignalType.SELL,
                    confidence=confidence,
                    market_price=yes_price,
                    edge_amount=sell_profit,
                    reasoning=reasoning,
                    timestamp=now,
                ),
                Signal(
                    strategy=self.name,
                    market_id=market.id,
                    token_id=no_outcome.token_id,
                    signal_type=SignalType.SELL,
                    confidence=confidence,
                    market_price=no_price,
                    edge_amount=sell_profit,
                    reasoning=reasoning,
                    timestamp=now,
                ),
            ]

        logger.debug(
            "arbitrage: no mispricing",
            market_id=market.id,
            total=total,
            fee=fee,
        )
        return None
