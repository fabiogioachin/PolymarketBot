"""Base rate analyzer: historical resolution rates by market category."""

from app.core.logging import get_logger
from app.core.yaml_config import app_config
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

    async def get_prior(self, market: Market) -> float | None:
        """Get prior probability for a market, or ``None`` when data is too sparse.

        Returns the **historical YES rate** for the market's category — an
        independent prior, NOT a Bayesian blend with ``market_price``. The
        engine's weighted average is what blends signals; baking ``market_price``
        into a single signal silently anchors ``fair_value`` to ``market_price``
        and collapses the edge across all other signals (P1 fix 2026-04-27).

        Below ``valuation.gating.min_base_rate_resolutions`` historical samples
        the rate is too noisy to trust and we return ``None`` (signal excluded).
        """
        count = await self._db.get_resolution_count(category=market.category.value)
        threshold = app_config.valuation.gating.min_base_rate_resolutions
        if count < threshold:
            return None
        return await self.get_base_rate(market)
