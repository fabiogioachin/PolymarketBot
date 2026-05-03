"""Knowledge-driven strategy — generates signals from KG pattern matches."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from app.core.logging import get_logger
from app.models.knowledge import KnowledgeContext, PatternMatch
from app.models.market import Market
from app.models.signal import Signal, SignalType
from app.models.valuation import ValuationResult

logger = get_logger(__name__)


class KnowledgeDrivenStrategy:
    """Generates trading signals from Knowledge Graph pattern matches.

    A pattern must clear both MIN_MATCH_SCORE and MIN_PATTERN_CONFIDENCE to
    be considered "strong". If any strong pattern exists, the strategy
    weighs the knowledge composite_signal against the valuation direction
    and emits a BUY signal on YES (bullish) or NO (bearish) token.
    """

    MIN_MATCH_SCORE: float = 0.4
    MIN_PATTERN_CONFIDENCE: float = 0.3

    @property
    def name(self) -> str:
        return "knowledge_driven"

    @property
    def domain_filter(self) -> list[str]:
        return []  # applies to all domains

    async def evaluate(
        self,
        market: Market,
        valuation: ValuationResult,
        knowledge: KnowledgeContext | None = None,
    ) -> Signal | None:
        """Return a signal when strong patterns are present in the knowledge context.

        Composite signal direction is combined with valuation edge direction to
        determine conviction. Confidence is the average of
        (pattern_confidence × match_score) across the strong patterns, scaled
        by the knowledge.confidence.
        """
        if not knowledge or not knowledge.patterns:
            logger.debug(
                "knowledge_driven: no knowledge context or patterns",
                market_id=market.id,
            )
            return None

        strong_patterns = [
            pm
            for pm in knowledge.patterns
            if pm.match_score >= self.MIN_MATCH_SCORE
            and pm.pattern.confidence >= self.MIN_PATTERN_CONFIDENCE
        ]

        if not strong_patterns:
            logger.debug(
                "knowledge_driven: no patterns above thresholds",
                market_id=market.id,
                total_patterns=len(knowledge.patterns),
            )
            return None

        # Composite confidence: weighted average of pattern_confidence × match_score
        composite_confidence = self._composite_confidence(strong_patterns, knowledge.confidence)

        composite_signal = knowledge.composite_signal
        edge = valuation.fee_adjusted_edge

        target_outcome = self._resolve_target_outcome(composite_signal, edge)
        if target_outcome is None:
            logger.debug(
                "knowledge_driven: signal and edge disagree — no trade",
                market_id=market.id,
                composite_signal=composite_signal,
                edge=edge,
            )
            return None

        token_id = self._pick_token(market, target_outcome)
        if not token_id:
            logger.debug(
                "knowledge_driven: target outcome not found or empty token_id — skip",
                market_id=market.id,
                target_outcome=target_outcome,
            )
            return None

        knowledge_sources = [pm.pattern.name for pm in strong_patterns if pm.pattern.name]
        reasoning = self._build_reasoning(strong_patterns, composite_signal, edge)

        yes_price = valuation.market_price
        market_price = yes_price if target_outcome == "yes" else 1.0 - yes_price

        logger.info(
            "knowledge_driven: signal generated",
            market_id=market.id,
            target_outcome=target_outcome,
            composite_signal=composite_signal,
            confidence=composite_confidence,
            patterns=knowledge_sources,
        )

        return Signal(
            strategy=self.name,
            market_id=market.id,
            token_id=token_id,
            signal_type=SignalType.BUY,
            confidence=composite_confidence,
            market_price=market_price,
            edge_amount=edge,
            reasoning=reasoning,
            knowledge_sources=knowledge_sources,
            timestamp=datetime.now(UTC),
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _composite_confidence(
        self,
        strong_patterns: list[PatternMatch],
        knowledge_confidence: float,
    ) -> float:
        """Weighted avg of (pattern.confidence × match_score), scaled by knowledge confidence."""
        if not strong_patterns:
            return 0.0
        total = sum(pm.pattern.confidence * pm.match_score for pm in strong_patterns)
        avg = total / len(strong_patterns)
        # Scale by the overall knowledge confidence (0-1)
        return round(min(1.0, avg * max(knowledge_confidence, 0.5)), 4)

    def _resolve_target_outcome(
        self,
        composite_signal: float,
        edge: float,
    ) -> Literal["yes", "no"] | None:
        """Return the target outcome for a BUY signal, or None if no signal."""
        if composite_signal > 0 and edge > 0:
            return "yes"
        if composite_signal < 0 and edge < 0:
            return "no"
        return None  # disagreement → no trade

    def _pick_token(self, market: Market, outcome_name: Literal["yes", "no"]) -> str | None:
        """Return the token_id matching outcome_name (case/whitespace-insensitive)."""
        for o in market.outcomes:
            if o.outcome.strip().lower() == outcome_name:
                return o.token_id or None
        return None

    def _build_reasoning(
        self,
        strong_patterns: list[PatternMatch],
        composite_signal: float,
        edge: float,
    ) -> str:
        pattern_names = [pm.pattern.name or pm.pattern.id for pm in strong_patterns]
        direction = "bullish" if composite_signal > 0 else "bearish"
        return (
            f"Knowledge composite signal {composite_signal:+.3f} ({direction}) "
            f"aligns with fee-adjusted edge {edge:+.3f}. "
            f"Strong patterns: {', '.join(pattern_names)}."
        )
