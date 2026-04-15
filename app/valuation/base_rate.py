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
        adjusts toward market consensus (Bayesian shrinkage).

        Key principle: without historical data, trust the market price.
        The market aggregates all public information — our uninformed 50% prior
        should NOT override it. Only deviate from market price when we have
        real evidence (historical resolution data for this category).
        """
        base_rate = await self.get_base_rate(market)

        # Shrinkage toward base_rate scales with evidence strength.
        # Without evidence, the market price IS the best estimate.
        count = await self._db.get_resolution_count(category=market.category.value)
        if count < 5:
            # No meaningful evidence — mostly trust the market,
            # but allow small deviation for other signals to work
            shrinkage = 0.10  # 10% prior, 90% market
        elif count < 20:
            shrinkage = 0.20
        elif count < 50:
            shrinkage = 0.30
        else:
            shrinkage = 0.50  # Strong prior — 50% historical, 50% market

        market_price = 0.5
        if market.outcomes:
            for outcome in market.outcomes:
                if outcome.outcome.lower() == "yes":
                    market_price = outcome.price
                    break

        return shrinkage * base_rate + (1 - shrinkage) * market_price
