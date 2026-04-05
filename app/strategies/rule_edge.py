"""Rule Edge strategy — exploits ambiguities in resolution rules."""

from datetime import UTC, datetime

from app.core.logging import get_logger
from app.models.knowledge import KnowledgeContext
from app.models.market import Market
from app.models.signal import Signal, SignalType
from app.models.valuation import ValuationResult
from app.services.rule_parser import RuleAnalysis, RuleParser, RuleRiskLevel

logger = get_logger(__name__)

# Confidence adjustments based on rule quality
_CLEAR_BOOST = 0.10
_AMBIGUOUS_PENALTY = 0.15
_EDGE_CASE_PENALTY = 0.05
_TRUSTED_SOURCE_BOOST = 0.05

# Minimum fee-adjusted edge required to emit a signal
_MIN_EDGE = 0.03
_MIN_CONFIDENCE = 0.25

# Sources treated as high-trust (lower-cased for comparison)
_TRUSTED_SOURCES = {
    "associated press",
    "ap",
    "reuters",
    "official government",
    "federal reserve",
    "bls",
    "bureau of labor statistics",
    "sec",
    "fda",
    "who",
    "un",
    "world bank",
    "imf",
}


class RuleEdgeStrategy:
    """Exploits edge arising from rule clarity or ambiguity.

    Clear rules with a trusted resolution source boost confidence in the
    valuation.  Ambiguous rules reduce confidence and add a warning.
    High-risk rules are skipped entirely.
    """

    def __init__(self, rule_analysis: dict[str, RuleAnalysis] | None = None) -> None:
        self._rule_analyses: dict[str, RuleAnalysis] = rule_analysis or {}
        self._parser = RuleParser()

    @property
    def name(self) -> str:
        return "rule_edge"

    @property
    def domain_filter(self) -> list[str]:
        return []  # applies to all domains

    def set_rule_analysis(self, market_id: str, analysis: RuleAnalysis) -> None:
        """Store a pre-computed rule analysis for a market."""
        self._rule_analyses[market_id] = analysis

    async def evaluate(
        self,
        market: Market,
        valuation: ValuationResult,
        knowledge: KnowledgeContext | None = None,
    ) -> Signal | None:
        """Evaluate a market using its resolution-rule risk profile."""
        analysis = self._rule_analyses.get(market.id)
        if analysis is None:
            # Fall back to on-the-fly parsing
            analysis = self._parser.analyze(market)

        # Skip entirely for high-risk rules
        if analysis.risk_level == RuleRiskLevel.HIGH_RISK:
            logger.info(
                "rule_edge: skipping high-risk market",
                market_id=market.id,
                ambiguities=len(analysis.ambiguities),
                edge_cases=len(analysis.edge_cases),
            )
            return None

        # Derive adjusted confidence
        adjusted_confidence = valuation.confidence
        warning_notes: list[str] = []

        if analysis.risk_level == RuleRiskLevel.CLEAR:
            adjusted_confidence += _CLEAR_BOOST
            warning_notes.append("Clear resolution rules — confidence boosted")
        else:
            # AMBIGUOUS
            adjusted_confidence -= _AMBIGUOUS_PENALTY
            if analysis.ambiguities:
                warning_notes.append(
                    f"Ambiguous rules ({len(analysis.ambiguities)} indicators)"
                )

        # Edge cases reduce confidence further
        if analysis.edge_cases:
            adjusted_confidence -= _EDGE_CASE_PENALTY * len(analysis.edge_cases)
            warning_notes.append(f"{len(analysis.edge_cases)} edge case(s) detected")

        # Trusted resolution source boosts confidence
        source_lower = analysis.resolution_source.lower()
        if any(trusted in source_lower for trusted in _TRUSTED_SOURCES):
            adjusted_confidence += _TRUSTED_SOURCE_BOOST
            warning_notes.append(f"Trusted source: {analysis.resolution_source}")

        adjusted_confidence = max(0.0, min(1.0, adjusted_confidence))

        # Require minimum thresholds to emit
        edge = valuation.fee_adjusted_edge
        if adjusted_confidence < _MIN_CONFIDENCE or abs(edge) < _MIN_EDGE:
            logger.debug(
                "rule_edge: below thresholds after adjustment",
                market_id=market.id,
                adjusted_confidence=adjusted_confidence,
                edge=edge,
            )
            return None

        # Determine signal direction from valuation
        if edge > 0:
            signal_type = SignalType.BUY
            token_id = next(
                (o.token_id for o in market.outcomes if o.outcome.lower() == "yes"),
                market.outcomes[0].token_id if market.outcomes else "",
            )
        else:
            # YES overpriced -> BUY the NO token (profits when YES price drops)
            signal_type = SignalType.BUY
            token_id = next(
                (o.token_id for o in market.outcomes if o.outcome.lower() == "no"),
                market.outcomes[0].token_id if market.outcomes else "",
            )

        reasoning = (
            f"Rule risk: {analysis.risk_level}; "
            f"Source: '{analysis.resolution_source or 'unknown'}'; "
            f"Original confidence: {valuation.confidence:.3f} → {adjusted_confidence:.3f}; "
            f"Edge: {edge:.3f}. "
            + "; ".join(warning_notes)
        )

        logger.info(
            "rule_edge: signal generated",
            market_id=market.id,
            signal_type=signal_type,
            risk_level=analysis.risk_level,
            adjusted_confidence=adjusted_confidence,
        )

        return Signal(
            strategy=self.name,
            market_id=market.id,
            token_id=token_id,
            signal_type=signal_type,
            confidence=adjusted_confidence,
            market_price=valuation.market_price,
            edge_amount=edge,
            reasoning=reasoning,
            timestamp=datetime.now(UTC),
        )
