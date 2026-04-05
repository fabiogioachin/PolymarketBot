"""Market scanner: classifies markets by domain and activates strategy modules."""

import re

from app.core.logging import get_logger
from app.core.yaml_config import app_config
from app.models.market import Market, MarketCategory

logger = get_logger(__name__)

# Keyword sub-classification rules (extend categories from Gamma API tags)
_KEYWORD_RULES: dict[MarketCategory, list[str]] = {
    MarketCategory.POLITICS: [
        "election",
        "president",
        "congress",
        "senate",
        "vote",
        "polling",
        "democrat",
        "republican",
        "ballot",
        "impeach",
        "governor",
    ],
    MarketCategory.GEOPOLITICS: [
        "war",
        "invasion",
        "nato",
        "sanction",
        "treaty",
        "ceasefire",
        "nuclear",
        "missile",
        "diplomatic",
        "territorial",
    ],
    MarketCategory.ECONOMICS: [
        "gdp",
        "inflation",
        "interest rate",
        "fed",
        "recession",
        "unemployment",
        "cpi",
        "tariff",
        "trade deficit",
        "fiscal",
    ],
    MarketCategory.CRYPTO: [
        "bitcoin",
        "ethereum",
        "btc",
        "eth",
        "defi",
        "nft",
        "blockchain",
        "token",
        "stablecoin",
        "mining",
        "halving",
    ],
    MarketCategory.SPORTS: [
        "nba",
        "nfl",
        "mlb",
        "nhl",
        "premier league",
        "champions league",
        "world cup",
        "super bowl",
        "playoff",
        "championship",
        "mvp",
    ],
    MarketCategory.ENTERTAINMENT: [
        "oscar",
        "emmy",
        "grammy",
        "box office",
        "album",
        "netflix",
        "streaming",
        "celebrity",
        "reality tv",
    ],
    MarketCategory.SCIENCE: [
        "nasa",
        "space",
        "climate",
        "vaccine",
        "fda",
        "approval",
        "pandemic",
        "research",
        "discovery",
    ],
}


class MarketScanner:
    """Classifies markets by domain and determines which strategy modules to activate."""

    def classify(self, market: Market) -> MarketCategory:
        """Classify a market into a domain category.

        Uses Gamma API tags as primary signal, keyword matching as fallback.
        """
        # If already classified (from Gamma API tags), trust it unless OTHER
        if market.category != MarketCategory.OTHER:
            return market.category

        # Keyword sub-classification from question + description
        text = f"{market.question} {market.description}".lower()
        best_match: MarketCategory | None = None
        best_count = 0

        for category, keywords in _KEYWORD_RULES.items():
            count = sum(
                1 for kw in keywords
                if re.search(rf"\b{re.escape(kw)}\b", text)
            )
            if count > best_count:
                best_count = count
                best_match = category

        return best_match if best_match and best_count > 0 else MarketCategory.OTHER

    def classify_batch(self, markets: list[Market]) -> dict[MarketCategory, list[Market]]:
        """Classify a list of markets, returning them grouped by domain."""
        result: dict[MarketCategory, list[Market]] = {}
        for market in markets:
            cat = self.classify(market)
            result.setdefault(cat, []).append(market)
        return result

    def get_active_domains(self, markets: list[Market]) -> set[MarketCategory]:
        """Get domains that have active markets with sufficient liquidity."""
        domains: set[MarketCategory] = set()
        for market in markets:
            if market.liquidity > 0:
                domains.add(self.classify(market))
        return domains

    def get_strategies_for_market(self, market: Market) -> list[str]:
        """Get applicable strategies for a market based on its domain."""
        category = self.classify(market)
        enabled = app_config.strategies.enabled
        filters = app_config.strategies.domain_filters

        applicable: list[str] = []
        for strategy in enabled:
            domain_filter = filters.get(strategy, [])
            # Empty filter = applies to all domains
            if not domain_filter or category.value in domain_filter:
                applicable.append(strategy)
        return applicable
