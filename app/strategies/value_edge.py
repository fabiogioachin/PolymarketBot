"""Value Edge strategy — primary strategy trading directly on Value Engine edge."""

from datetime import UTC, datetime

from app.core.logging import get_logger
from app.models.knowledge import KnowledgeContext
from app.models.market import Market
from app.models.signal import Signal, SignalType
from app.models.valuation import ValuationResult

logger = get_logger(__name__)


class ValueEdgeStrategy:
    """Trades directly on Value Engine edge. Works on ANY domain.

    Emits BUY when fee_adjusted_edge exceeds min_edge with sufficient confidence,
    SELL when the edge is negative beyond min_edge, and None otherwise.
    """

    def __init__(self, min_edge: float = 0.05, min_confidence: float = 0.3) -> None:
        self._min_edge = min_edge
        self._min_confidence = min_confidence

    @property
    def name(self) -> str:
        return "value_edge"

    @property
    def domain_filter(self) -> list[str]:
        return []  # applies to all domains

    async def evaluate(
        self,
        market: Market,
        valuation: ValuationResult,
        knowledge: KnowledgeContext | None = None,
    ) -> Signal | None:
        """Return a BUY/SELL signal when edge and confidence thresholds are met."""
        edge = valuation.fee_adjusted_edge
        confidence = valuation.confidence

        if confidence < self._min_confidence:
            logger.debug(
                "value_edge: confidence below threshold",
                market_id=market.id,
                confidence=confidence,
                min_confidence=self._min_confidence,
            )
            return None

        if edge > self._min_edge:
            signal_type = SignalType.BUY
            # Find the YES outcome token
            token_id = next(
                (o.token_id for o in market.outcomes if o.outcome.lower() == "yes"),
                market.outcomes[0].token_id if market.outcomes else "",
            )
        elif edge < -self._min_edge:
            signal_type = SignalType.BUY
            # YES is overpriced -> BUY the NO token (profits when YES price drops)
            token_id = next(
                (o.token_id for o in market.outcomes if o.outcome.lower() == "no"),
                market.outcomes[0].token_id if market.outcomes else "",
            )
        else:
            logger.debug(
                "value_edge: edge below threshold",
                market_id=market.id,
                edge=edge,
                min_edge=self._min_edge,
            )
            return None

        reasoning = (
            f"Fair value: {valuation.fair_value:.3f}, "
            f"Market price: {valuation.market_price:.3f}, "
            f"Edge: {valuation.edge:.3f}, "
            f"Fee-adjusted edge: {edge:.3f}, "
            f"Recommendation: {valuation.recommendation}"
        )

        logger.info(
            "value_edge: signal generated",
            market_id=market.id,
            signal_type=signal_type,
            edge=edge,
            confidence=confidence,
        )

        return Signal(
            strategy=self.name,
            market_id=market.id,
            token_id=token_id,
            signal_type=signal_type,
            confidence=confidence,
            market_price=valuation.market_price,
            edge_amount=edge,
            reasoning=reasoning,
            timestamp=datetime.now(UTC),
        )
