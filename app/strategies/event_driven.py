"""Event Driven strategy — trades on events detected by the intelligence pipeline."""

from datetime import UTC, datetime, timedelta
from typing import Literal

from app.core.logging import get_logger
from app.models.knowledge import KnowledgeContext, PatternMatch
from app.models.market import Market
from app.models.signal import Signal, SignalType
from app.models.valuation import ValuationResult

logger = get_logger(__name__)

# Speed premium: within this many hours after an event, apply a factor boost
_SPEED_PREMIUM_HOURS = 6
_SPEED_PREMIUM_FACTOR = 1.5

# Minimum thresholds to emit a signal
_MIN_COMBINED_EDGE = 0.03
_MIN_CONFIDENCE = 0.25

# Weight blend between pattern composite signal and valuation edge
_PATTERN_WEIGHT = 0.4
_VALUATION_WEIGHT = 0.6


class EventDrivenStrategy:
    """Trades on events detected by the intelligence pipeline.

    Applies a speed premium when the triggering event is fresh (within
    SPEED_PREMIUM_HOURS).  Confidence increases when multiple patterns agree.
    """

    @property
    def name(self) -> str:
        return "event_driven"

    @property
    def domain_filter(self) -> list[str]:
        return ["politics", "geopolitics", "economics"]

    def _is_fresh_event(self, patterns: list[PatternMatch]) -> bool:
        """Return True if any matched pattern was triggered recently."""
        cutoff = datetime.now(UTC) - timedelta(hours=_SPEED_PREMIUM_HOURS)
        for pm in patterns:
            last = pm.pattern.last_triggered
            if last is not None:
                # Normalise to UTC-aware if naive
                if last.tzinfo is None:
                    last = last.replace(tzinfo=UTC)
                if last >= cutoff:
                    return True
        return False

    async def evaluate(
        self,
        market: Market,
        valuation: ValuationResult,
        knowledge: KnowledgeContext | None = None,
    ) -> Signal | None:
        """Evaluate using knowledge-graph pattern matches and valuation edge."""
        if not knowledge or not knowledge.patterns:
            return None

        patterns = knowledge.patterns

        # Blend composite pattern signal with valuation edge
        # composite_signal is -1…+1; edge is also signed
        composite = knowledge.composite_signal  # -1 to +1
        val_edge = valuation.fee_adjusted_edge  # signed edge

        combined_edge = _PATTERN_WEIGHT * composite + _VALUATION_WEIGHT * val_edge

        # Apply speed premium if event is fresh
        fresh = self._is_fresh_event(patterns)
        if fresh:
            combined_edge *= _SPEED_PREMIUM_FACTOR

        # Higher confidence when multiple patterns agree (same direction)
        positive_patterns = sum(1 for pm in patterns if pm.match_score > 0.5)
        pattern_agreement = positive_patterns / max(len(patterns), 1)
        base_confidence = knowledge.confidence if knowledge.confidence > 0 else valuation.confidence
        # Boost confidence proportionally to agreement
        adjusted_confidence = base_confidence * (0.7 + 0.3 * pattern_agreement)
        adjusted_confidence = max(0.0, min(1.0, adjusted_confidence))

        if adjusted_confidence < _MIN_CONFIDENCE or abs(combined_edge) < _MIN_COMBINED_EDGE:
            logger.debug(
                "event_driven: below thresholds",
                market_id=market.id,
                combined_edge=combined_edge,
                adjusted_confidence=adjusted_confidence,
            )
            return None

        target_outcome: Literal["yes", "no"] | None
        if combined_edge > 0:
            target_outcome = "yes"
        elif combined_edge < 0:
            target_outcome = "no"
        else:
            return None

        token_id = next(
            (o.token_id for o in market.outcomes if o.outcome.strip().lower() == target_outcome),
            None,
        )
        if not token_id:
            logger.debug(
                "event_driven: target outcome not found or empty token_id — skip",
                market_id=market.id,
                target_outcome=target_outcome,
            )
            return None

        yes_price = valuation.market_price
        market_price = yes_price if target_outcome == "yes" else 1.0 - yes_price

        knowledge_sources = [pm.pattern.name for pm in patterns if pm.pattern.name]

        speed_note = " [speed-premium applied]" if fresh else ""
        reasoning = (
            f"Composite pattern signal: {composite:.3f}, "
            f"Valuation edge: {val_edge:.3f}, "
            f"Combined edge: {combined_edge:.3f}{speed_note}; "
            f"Patterns matched: {len(patterns)} "
            f"({positive_patterns} high-score)"
        )

        logger.info(
            "event_driven: signal generated",
            market_id=market.id,
            target_outcome=target_outcome,
            combined_edge=combined_edge,
            fresh_event=fresh,
            patterns=len(patterns),
        )

        return Signal(
            strategy=self.name,
            market_id=market.id,
            token_id=token_id,
            signal_type=SignalType.BUY,
            confidence=adjusted_confidence,
            market_price=market_price,
            edge_amount=combined_edge,
            reasoning=reasoning,
            knowledge_sources=knowledge_sources,
            timestamp=datetime.now(UTC),
        )
