"""Temporal analysis: time-to-resolution effects on fair value."""

from datetime import UTC, datetime

from app.core.logging import get_logger
from app.models.market import Market, MarketCategory

logger = get_logger(__name__)

# Decay rate by category: how quickly edge disappears as deadline approaches
_DECAY_RATES: dict[MarketCategory, float] = {
    MarketCategory.POLITICS: 0.8,  # slow convergence (uncertainty until vote)
    MarketCategory.GEOPOLITICS: 0.6,  # moderate convergence
    MarketCategory.ECONOMICS: 0.9,  # fast convergence (data releases)
    MarketCategory.CRYPTO: 0.5,  # volatile until resolution
    MarketCategory.SPORTS: 0.95,  # very fast convergence (game starts)
    MarketCategory.ENTERTAINMENT: 0.7,
    MarketCategory.SCIENCE: 0.7,
    MarketCategory.OTHER: 0.7,
}


class TemporalAnalyzer:
    """Analyzes time-to-resolution effects on market value."""

    def compute_temporal_factor(self, market: Market) -> float:
        """Compute temporal factor for a market.

        Returns a multiplier (0-1) that scales the edge:
        - Close to 1.0 when far from deadline (edge is actionable, early mover advantage)
        - Close to 0.0 when near deadline (market already converging to true value)
        - 0.5 when no deadline is known
        """
        if market.end_date is None:
            return 0.5  # unknown timeline, moderate factor

        now = datetime.now(tz=UTC)
        time_remaining = (market.end_date - now).total_seconds()

        if time_remaining <= 0:
            return 0.0  # expired, no edge

        # Normalize to days
        days_remaining = time_remaining / 86400

        # Get category-specific decay rate
        decay_rate = _DECAY_RATES.get(market.category, 0.7)

        # Sigmoid-like function: high when far from deadline, drops as deadline approaches
        # When days_remaining is large: factor ~ 1 (lots of time, edge is actionable)
        # When days_remaining is small: factor drops toward 0

        if days_remaining > 30:
            return 1.0  # more than a month = full edge preservation

        # Linear decay in last 30 days, modulated by category decay rate
        factor = (days_remaining / 30) * decay_rate + (1 - decay_rate)
        return round(max(0.0, min(1.0, factor)), 4)

    def compute_convergence_speed(self, market: Market) -> float:
        """Estimate how quickly price is converging to final value.

        Returns 0-1: 0 = slow convergence, 1 = fast convergence.
        """
        if market.end_date is None:
            return 0.5

        now = datetime.now(tz=UTC)
        days_remaining = (market.end_date - now).total_seconds() / 86400

        if days_remaining <= 0:
            return 1.0

        decay = _DECAY_RATES.get(market.category, 0.7)

        # Closer to deadline + fast-converging category = higher speed
        if days_remaining < 1:
            return decay
        elif days_remaining < 7:
            return decay * 0.7
        elif days_remaining < 30:
            return decay * 0.3
        return 0.1
