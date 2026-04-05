"""Tests for MarketScanner classification and strategy selection."""

import pytest

from app.models.market import Market, MarketCategory
from app.services.market_scanner import MarketScanner


@pytest.fixture
def scanner() -> MarketScanner:
    return MarketScanner()


def _make_market(
    *,
    market_id: str = "test-1",
    question: str = "",
    description: str = "",
    category: MarketCategory = MarketCategory.OTHER,
    liquidity: float = 1000.0,
    volume: float = 5000.0,
    tags: list[str] | None = None,
) -> Market:
    """Helper to create a Market instance with sensible defaults."""
    return Market(
        id=market_id,
        question=question,
        description=description,
        category=category,
        liquidity=liquidity,
        volume=volume,
        tags=tags or [],
    )


class TestClassify:
    def test_classify_from_tags(self, scanner: MarketScanner) -> None:
        """Market with category already set (from Gamma tags) returns that category."""
        market = _make_market(
            question="Will Bitcoin reach $100k?",
            category=MarketCategory.CRYPTO,
        )
        assert scanner.classify(market) == MarketCategory.CRYPTO

    def test_classify_by_keywords_politics(self, scanner: MarketScanner) -> None:
        """OTHER market with election keywords -> POLITICS."""
        market = _make_market(
            question="Will the election results be contested?",
            description="Polling data suggests a close race for president.",
        )
        assert scanner.classify(market) == MarketCategory.POLITICS

    def test_classify_by_keywords_crypto(self, scanner: MarketScanner) -> None:
        """OTHER market with bitcoin/ethereum keywords -> CRYPTO."""
        market = _make_market(
            question="Will bitcoin ethereum market cap exceed $3T?",
        )
        assert scanner.classify(market) == MarketCategory.CRYPTO

    def test_classify_by_keywords_geopolitics(self, scanner: MarketScanner) -> None:
        """OTHER market with war/nato keywords -> GEOPOLITICS."""
        market = _make_market(
            question="Will NATO invoke Article 5 after the invasion?",
            description="Ceasefire negotiations have stalled.",
        )
        assert scanner.classify(market) == MarketCategory.GEOPOLITICS

    def test_classify_by_keywords_economics(self, scanner: MarketScanner) -> None:
        """OTHER market with inflation/recession keywords -> ECONOMICS."""
        market = _make_market(
            question="Will inflation exceed 5% this year?",
            description="The fed is considering raising the interest rate.",
        )
        assert scanner.classify(market) == MarketCategory.ECONOMICS

    def test_classify_by_keywords_sports(self, scanner: MarketScanner) -> None:
        """OTHER market with NBA/championship keywords -> SPORTS."""
        market = _make_market(
            question="Who will win the NBA championship?",
            description="The playoff bracket is set.",
        )
        assert scanner.classify(market) == MarketCategory.SPORTS

    def test_classify_no_match(self, scanner: MarketScanner) -> None:
        """No keywords matched -> OTHER."""
        market = _make_market(
            question="Will it rain in Paris on Friday?",
            description="A purely local affair with no global impact.",
        )
        assert scanner.classify(market) == MarketCategory.OTHER

    def test_classify_prefers_higher_count(self, scanner: MarketScanner) -> None:
        """When multiple categories match, the one with more keywords wins."""
        market = _make_market(
            question="Bitcoin ethereum defi token halving blockchain stablecoin war",
            description="",
        )
        # 7 crypto keywords vs 1 geopolitics keyword
        assert scanner.classify(market) == MarketCategory.CRYPTO


class TestClassifyBatch:
    def test_classify_batch(self, scanner: MarketScanner) -> None:
        """Groups markets correctly by domain."""
        markets = [
            _make_market(market_id="1", category=MarketCategory.POLITICS),
            _make_market(market_id="2", category=MarketCategory.CRYPTO),
            _make_market(market_id="3", category=MarketCategory.POLITICS),
            _make_market(market_id="4", question="Will it rain in Paris?"),
        ]
        result = scanner.classify_batch(markets)
        assert len(result[MarketCategory.POLITICS]) == 2
        assert len(result[MarketCategory.CRYPTO]) == 1
        assert len(result[MarketCategory.OTHER]) == 1

    def test_classify_batch_empty(self, scanner: MarketScanner) -> None:
        """Empty list returns empty dict."""
        assert scanner.classify_batch([]) == {}


class TestGetActiveDomains:
    def test_get_active_domains(self, scanner: MarketScanner) -> None:
        """Only domains with liquidity > 0 are included."""
        markets = [
            _make_market(market_id="1", category=MarketCategory.POLITICS, liquidity=100.0),
            _make_market(market_id="2", category=MarketCategory.CRYPTO, liquidity=0.0),
            _make_market(market_id="3", category=MarketCategory.SPORTS, liquidity=50.0),
        ]
        domains = scanner.get_active_domains(markets)
        assert domains == {MarketCategory.POLITICS, MarketCategory.SPORTS}

    def test_get_active_domains_empty(self, scanner: MarketScanner) -> None:
        """No markets -> empty set."""
        assert scanner.get_active_domains([]) == set()


class TestGetStrategiesForMarket:
    def test_get_strategies_for_market(self, scanner: MarketScanner) -> None:
        """Respects domain_filters from config."""
        # Default config: event_driven filters to [politics, geopolitics, economics]
        market = _make_market(category=MarketCategory.POLITICS)
        strategies = scanner.get_strategies_for_market(market)
        # event_driven should be included (politics is in its filter)
        assert "event_driven" in strategies
        # value_edge has empty filter -> applies to all
        assert "value_edge" in strategies

    def test_strategies_empty_filter(self, scanner: MarketScanner) -> None:
        """Empty filter -> strategy applies to all domains."""
        market = _make_market(category=MarketCategory.SCIENCE)
        strategies = scanner.get_strategies_for_market(market)
        # value_edge, arbitrage, rule_edge have empty filters -> all apply
        assert "value_edge" in strategies
        assert "arbitrage" in strategies
        assert "rule_edge" in strategies

    def test_strategies_excludes_non_matching(self, scanner: MarketScanner) -> None:
        """Strategy with domain filter that doesn't match is excluded."""
        # Default config: event_driven = [politics, geopolitics, economics]
        # resolution = [sports, crypto]
        market = _make_market(category=MarketCategory.SCIENCE)
        strategies = scanner.get_strategies_for_market(market)
        assert "event_driven" not in strategies
        assert "resolution" not in strategies

    def test_strategies_resolution_for_sports(self, scanner: MarketScanner) -> None:
        """Resolution strategy applies to sports domain."""
        market = _make_market(category=MarketCategory.SPORTS)
        strategies = scanner.get_strategies_for_market(market)
        assert "resolution" in strategies
        # event_driven should NOT apply to sports
        assert "event_driven" not in strategies
