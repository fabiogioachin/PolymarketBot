"""Base rate analyzer: historical resolution rates by market category."""

from app.core.logging import get_logger
from app.models.market import Market, MarketCategory
from app.valuation.db import ResolutionDB

logger = get_logger(__name__)


class BaseRateAnalyzer:
    """Calculates base rates (prior probabilities) from historical market resolutions."""

    def __init__(self, db: ResolutionDB) -> None:
        self._db = db
        # Cache base rates after computation
        self._rates: dict[str, float] = {}

    async def compute_base_rates(self) -> dict[str, float]:
        """Compute YES resolution rate for each category."""
        rates: dict[str, float] = {}
        for cat in MarketCategory:
            resolutions = await self._db.get_resolutions(category=cat.value)
            if not resolutions:
                rates[cat.value] = 0.5  # uninformative prior
                continue
            yes_count = sum(1 for r in resolutions if r.resolved_yes)
            rates[cat.value] = yes_count / len(resolutions)

        self._rates = rates
        logger.info("base_rates_computed", rates=rates)
        return rates

    async def get_base_rate(self, market: Market) -> float:
        """Get the base rate for a market's category."""
        if not self._rates:
            await self.compute_base_rates()
        return self._rates.get(market.category.value, 0.5)

    async def get_prior(self, market: Market) -> float:
        """Get prior probability for a market.

        Uses base rate as starting point. If the market has outcomes with prices,
        adjusts slightly toward market consensus (Bayesian shrinkage toward prior).
        """
        base_rate = await self.get_base_rate(market)

        # If we have very few historical observations, lean more on market price
        count = await self._db.get_resolution_count(category=market.category.value)
        if count < 10:
            # Weak prior — give more weight to market consensus
            shrinkage = 0.3  # 30% prior, 70% market
        elif count < 50:
            shrinkage = 0.5
        else:
            shrinkage = 0.7  # Strong prior — 70% historical, 30% market

        market_price = 0.5
        if market.outcomes:
            # Use YES outcome price as market's implied probability
            for outcome in market.outcomes:
                if outcome.outcome.lower() == "yes":
                    market_price = outcome.price
                    break

        return shrinkage * base_rate + (1 - shrinkage) * market_price
