"""Resolution hunting: targets markets near expiry with discounted prices."""

from datetime import UTC, datetime

from app.core.logging import get_logger
from app.models.knowledge import KnowledgeContext
from app.models.market import Market
from app.models.signal import Signal, SignalType
from app.models.valuation import ValuationResult

logger = get_logger(__name__)


class ResolutionStrategy:
    """Buys near-resolution markets where outcome is likely known but price hasn't converged.

    Logic:
    - Market must have an end_date within MAX_DAYS_TO_RESOLUTION days
    - ValuationResult fair_value must be high (>= HIGH_PROB_THRESHOLD → BUY YES)
      or low (<= LOW_PROB_THRESHOLD → BUY NO)
    - Market price must be discounted: price < fair_value - min_discount
    - Fee-aware: only trade if profit > fee
    """

    # Thresholds
    HIGH_PROB_THRESHOLD: float = 0.85  # fair_value must be >= this for BUY YES
    LOW_PROB_THRESHOLD: float = 0.15  # fair_value must be <= this for BUY NO
    MIN_DISCOUNT: float = 0.03  # minimum price discount to bother (3 cents)
    MAX_DAYS_TO_RESOLUTION: float = 14.0  # only consider markets resolving within N days

    @property
    def name(self) -> str:
        return "resolution"

    @property
    def domain_filter(self) -> list[str]:
        return []  # applies to all domains

    async def evaluate(
        self,
        market: Market,
        valuation: ValuationResult,
        knowledge: KnowledgeContext | None = None,
    ) -> Signal | None:
        """Evaluate a near-resolution market and return a signal, or None if no signal."""
        # 1. Check if market has end_date and is within MAX_DAYS_TO_RESOLUTION
        if not market.end_date:
            logger.debug("resolution: no end_date", market_id=market.id)
            return None

        now = datetime.now(tz=UTC)
        days_remaining = (market.end_date - now).total_seconds() / 86400

        if days_remaining <= 0 or days_remaining > self.MAX_DAYS_TO_RESOLUTION:
            logger.debug(
                "resolution: market outside time window",
                market_id=market.id,
                days_remaining=days_remaining,
            )
            return None

        # 2. Time weight: closer to resolution = more confident
        time_weight = max(0.5, 1.0 - (days_remaining / self.MAX_DAYS_TO_RESOLUTION))

        # 3. Check BUY condition: high probability, discounted price
        yes_price = self._get_yes_price(market)
        fair_value = valuation.fair_value

        if fair_value >= self.HIGH_PROB_THRESHOLD:
            discount = fair_value - yes_price
            if discount >= self.MIN_DISCOUNT:
                profit = discount - market.fee_rate
                if profit > 0:
                    confidence = min(0.95, valuation.confidence * time_weight)
                    logger.info(
                        "resolution: BUY signal",
                        market_id=market.id,
                        fair_value=fair_value,
                        yes_price=yes_price,
                        discount=discount,
                        days_remaining=days_remaining,
                        profit=profit,
                    )
                    return Signal(
                        strategy=self.name,
                        market_id=market.id,
                        token_id=self._get_yes_token(market),
                        signal_type=SignalType.BUY,
                        confidence=confidence,
                        market_price=valuation.market_price,
                        edge_amount=round(profit, 4),
                        reasoning=(
                            f"Resolution hunt: fair_value={fair_value:.2f}, price={yes_price:.2f}, "
                            f"discount={discount:.2f}, days_left={days_remaining:.1f}, "
                            f"profit_after_fee={profit:.4f}"
                        ),
                    )

        # 4. Check BUY-NO condition: low probability, overpriced YES
        if fair_value <= self.LOW_PROB_THRESHOLD:
            no_price = 1.0 - yes_price  # approximate NO price
            expected_no_value = 1.0 - fair_value
            discount = expected_no_value - no_price
            if discount >= self.MIN_DISCOUNT:
                profit = discount - market.fee_rate
                if profit > 0:
                    no_token_id = self._get_no_token(market)
                    if not no_token_id:
                        logger.debug(
                            "resolution: NO outcome not found or empty token_id — skip",
                            market_id=market.id,
                        )
                        return None
                    confidence = min(0.95, valuation.confidence * time_weight)
                    logger.info(
                        "resolution: BUY NO signal",
                        market_id=market.id,
                        fair_value=fair_value,
                        yes_price=yes_price,
                        days_remaining=days_remaining,
                        profit=profit,
                    )
                    return Signal(
                        strategy=self.name,
                        market_id=market.id,
                        token_id=no_token_id,
                        signal_type=SignalType.BUY,
                        confidence=confidence,
                        market_price=1.0 - valuation.market_price,
                        edge_amount=round(profit, 4),
                        reasoning=(
                            f"Resolution hunt (NO): fair_value={fair_value:.2f}, "
                            f"yes_price={yes_price:.2f}, days_left={days_remaining:.1f}"
                        ),
                    )

        logger.debug(
            "resolution: no signal",
            market_id=market.id,
            fair_value=fair_value,
            yes_price=yes_price,
        )
        return None

    @staticmethod
    def _get_yes_price(market: Market) -> float:
        for o in market.outcomes:
            if o.outcome.strip().lower() == "yes":
                return o.price
        return 0.5

    @staticmethod
    def _get_yes_token(market: Market) -> str:
        for o in market.outcomes:
            if o.outcome.strip().lower() == "yes":
                return o.token_id
        return ""

    @staticmethod
    def _get_no_token(market: Market) -> str | None:
        for o in market.outcomes:
            if o.outcome.strip().lower() == "no":
                return o.token_id or None
        return None
