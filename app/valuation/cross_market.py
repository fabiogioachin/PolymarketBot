"""Cross-market correlation: find related markets and price discrepancies."""

from dataclasses import dataclass, field

from app.core.logging import get_logger
from app.models.market import Market

logger = get_logger(__name__)


@dataclass
class MarketCorrelation:
    """Correlation between two markets."""

    market_a_id: str
    market_b_id: str
    market_a_question: str = ""
    market_b_question: str = ""
    correlation_type: str = ""  # "complementary", "subset", "opposing", "related"
    keyword_overlap: float = 0.0  # 0-1, how many keywords shared
    price_discrepancy: float = 0.0  # |implied_a - implied_b| when they should be consistent
    detail: str = ""


@dataclass
class CrossMarketAnalysis:
    """Result of cross-market analysis for a target market."""

    market_id: str
    correlations: list[MarketCorrelation] = field(default_factory=list)
    max_discrepancy: float = 0.0
    arbitrage_opportunity: bool = False
    composite_signal: float = 0.0  # -1 to +1, direction of cross-market evidence


class CrossMarketAnalyzer:
    """Finds correlated markets and detects price discrepancies."""

    # Minimum keyword overlap to consider markets related
    MIN_OVERLAP = 0.3

    def find_correlations(
        self, target: Market, universe: list[Market]
    ) -> CrossMarketAnalysis:
        """Find markets correlated to the target and analyze price consistency."""
        correlations: list[MarketCorrelation] = []
        target_keywords = self._extract_keywords(target.question)

        for candidate in universe:
            if candidate.id == target.id:
                continue

            candidate_keywords = self._extract_keywords(candidate.question)
            overlap = self._keyword_overlap(target_keywords, candidate_keywords)

            if overlap < self.MIN_OVERLAP:
                continue

            # Determine correlation type
            corr_type = self._classify_correlation(target, candidate, overlap)

            # Check price consistency
            discrepancy = self._compute_discrepancy(target, candidate, corr_type)

            correlations.append(
                MarketCorrelation(
                    market_a_id=target.id,
                    market_b_id=candidate.id,
                    market_a_question=target.question,
                    market_b_question=candidate.question,
                    correlation_type=corr_type,
                    keyword_overlap=round(overlap, 3),
                    price_discrepancy=round(discrepancy, 4),
                )
            )

        # Sort by discrepancy (most interesting first)
        correlations.sort(key=lambda c: abs(c.price_discrepancy), reverse=True)

        max_disc = max((abs(c.price_discrepancy) for c in correlations), default=0.0)
        has_arb = max_disc > 0.05  # >5% discrepancy

        # Composite signal: aggregate direction from correlated markets
        signal = self._compute_composite_signal(target, correlations)

        return CrossMarketAnalysis(
            market_id=target.id,
            correlations=correlations,
            max_discrepancy=round(max_disc, 4),
            arbitrage_opportunity=has_arb,
            composite_signal=round(signal, 4),
        )

    @staticmethod
    def _extract_keywords(text: str) -> set[str]:
        """Extract meaningful keywords from text."""
        stop_words = {
            "the", "a", "an", "in", "on", "at", "to", "for", "of", "and",
            "or", "is", "be", "will", "by", "this", "that", "it", "with",
            "from", "as", "not", "but", "if", "has", "have", "had", "was",
            "were", "been", "are", "do", "does", "did", "than", "more",
            "before", "after", "above", "below", "between", "yes", "no",
        }
        words = set(text.lower().split())
        # Remove short words and stop words, keep meaningful terms
        return {
            w.strip("?.,!\"'()[]") for w in words if len(w) > 2 and w not in stop_words
        }

    @staticmethod
    def _keyword_overlap(kw_a: set[str], kw_b: set[str]) -> float:
        """Compute Jaccard similarity between keyword sets."""
        if not kw_a or not kw_b:
            return 0.0
        intersection = kw_a & kw_b
        union = kw_a | kw_b
        return len(intersection) / len(union) if union else 0.0

    @staticmethod
    def _classify_correlation(target: Market, candidate: Market, overlap: float) -> str:
        """Classify the type of correlation between two markets."""
        t_lower = target.question.lower()
        c_lower = candidate.question.lower()

        # Check for opposing/negation
        negation_words = ["not", "won't", "fail", "lose", "against"]
        target_has_neg = any(w in t_lower for w in negation_words)
        candidate_has_neg = any(w in c_lower for w in negation_words)
        if target_has_neg != candidate_has_neg and overlap > 0.4:
            return "opposing"

        # Very high overlap likely means subset/superset relationship
        if overlap > 0.6:
            return "subset"

        # Same category, related terms
        if target.category == candidate.category:
            return "related"

        return "complementary"

    @staticmethod
    def _compute_discrepancy(
        target: Market, candidate: Market, corr_type: str
    ) -> float:
        """Compute price discrepancy between correlated markets."""
        t_price = 0.5
        c_price = 0.5
        for o in target.outcomes:
            if o.outcome.lower() == "yes":
                t_price = o.price
        for o in candidate.outcomes:
            if o.outcome.lower() == "yes":
                c_price = o.price

        if corr_type == "opposing":
            # Opposing markets: prices should sum to ~1
            return abs(t_price + c_price - 1.0)
        elif corr_type == "subset":
            # Subset: child probability <= parent probability
            return max(0, c_price - t_price)  # discrepancy if child > parent
        else:
            # Related: just report the price difference as informational
            return abs(t_price - c_price)

    @staticmethod
    def _compute_composite_signal(
        target: Market, correlations: list[MarketCorrelation]
    ) -> float:
        """Compute directional signal from cross-market evidence.

        Positive = cross-market evidence suggests YES is underpriced.
        Negative = cross-market evidence suggests YES is overpriced.
        """
        if not correlations:
            return 0.0

        weighted_sum = 0.0
        weight_total = 0.0

        for corr in correlations:
            weight = corr.keyword_overlap  # more similar = more weight
            if corr.correlation_type == "opposing":
                # If correlated opposing market is cheap, our market should be expensive
                weighted_sum += weight * corr.price_discrepancy
            elif corr.price_discrepancy > 0.03:
                weighted_sum += weight * corr.price_discrepancy
            weight_total += weight

        if weight_total == 0:
            return 0.0
        return max(-1.0, min(1.0, weighted_sum / weight_total))
