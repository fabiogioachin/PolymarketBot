"""Tests for microstructure and cross-market analyzers."""

from datetime import UTC, datetime, timedelta

import pytest

from app.models.market import (
    Market,
    MarketCategory,
    OrderBook,
    OrderBookLevel,
    Outcome,
    PriceHistory,
    PricePoint,
)
from app.valuation.cross_market import CrossMarketAnalyzer
from app.valuation.microstructure import MicrostructureAnalyzer

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def analyzer() -> MicrostructureAnalyzer:
    return MicrostructureAnalyzer()


@pytest.fixture
def cross_analyzer() -> CrossMarketAnalyzer:
    return CrossMarketAnalyzer()


@pytest.fixture
def empty_orderbook() -> OrderBook:
    return OrderBook(market_id="m1", asset_id="a1", bids=[], asks=[])


@pytest.fixture
def tight_deep_orderbook() -> OrderBook:
    """Tight spread (1%), deep book."""
    return OrderBook(
        market_id="m1",
        asset_id="a1",
        bids=[
            OrderBookLevel(price=0.50, size=5000),
            OrderBookLevel(price=0.49, size=8000),
        ],
        asks=[
            OrderBookLevel(price=0.51, size=4000),
            OrderBookLevel(price=0.52, size=7000),
        ],
        spread=0.01,
        midpoint=0.505,
        timestamp=datetime(2026, 4, 1, tzinfo=UTC),
    )


@pytest.fixture
def imbalanced_orderbook() -> OrderBook:
    """More bid depth than ask depth."""
    return OrderBook(
        market_id="m2",
        asset_id="a2",
        bids=[
            OrderBookLevel(price=0.60, size=10000),
        ],
        asks=[
            OrderBookLevel(price=0.62, size=2000),
        ],
        spread=0.02,
        midpoint=0.61,
        timestamp=datetime(2026, 4, 1, tzinfo=UTC),
    )


@pytest.fixture
def price_history_with_momentum() -> PriceHistory:
    """Price rising from 0.40 to 0.60 over 7 days with steady volume."""
    now = datetime(2026, 4, 4, 12, 0, tzinfo=UTC)
    points = []
    for i in range(168):  # one point per hour for 7 days
        t = now - timedelta(hours=168 - i)
        price = 0.40 + 0.20 * (i / 167)
        points.append(PricePoint(timestamp=t, price=round(price, 4), volume=100.0))
    return PriceHistory(market_id="m1", token_id="t1", points=points)


@pytest.fixture
def price_history_volume_spike() -> PriceHistory:
    """Baseline volume ~100, last day volume ~500."""
    now = datetime(2026, 4, 4, 12, 0, tzinfo=UTC)
    points = []
    for i in range(168):  # 7 days hourly
        t = now - timedelta(hours=168 - i)
        hours_ago = 168 - i
        vol = 500.0 if hours_ago <= 24 else 100.0
        points.append(PricePoint(timestamp=t, price=0.50, volume=vol))
    return PriceHistory(market_id="m1", token_id="t1", points=points)


def _make_market(
    market_id: str,
    question: str,
    yes_price: float = 0.50,
    category: MarketCategory = MarketCategory.POLITICS,
) -> Market:
    return Market(
        id=market_id,
        question=question,
        category=category,
        outcomes=[
            Outcome(token_id=f"{market_id}_yes", outcome="Yes", price=yes_price),
            Outcome(token_id=f"{market_id}_no", outcome="No", price=round(1 - yes_price, 2)),
        ],
    )


# ---------------------------------------------------------------------------
# Microstructure: orderbook tests
# ---------------------------------------------------------------------------


class TestAnalyzeOrderbook:
    def test_analyze_empty_orderbook(
        self, analyzer: MicrostructureAnalyzer, empty_orderbook: OrderBook
    ) -> None:
        result = analyzer.analyze_orderbook(empty_orderbook)
        assert result.spread_pct == 0.0
        assert result.depth_imbalance == 0.0
        assert result.total_bid_depth == 0.0
        assert result.total_ask_depth == 0.0
        assert result.liquidity_score == 0.0

    def test_analyze_orderbook_spread(
        self, analyzer: MicrostructureAnalyzer, tight_deep_orderbook: OrderBook
    ) -> None:
        result = analyzer.analyze_orderbook(tight_deep_orderbook)
        expected = 0.01 / 0.505
        assert abs(result.spread_pct - expected) < 1e-6

    def test_analyze_orderbook_depth_imbalance(
        self, analyzer: MicrostructureAnalyzer, imbalanced_orderbook: OrderBook
    ) -> None:
        result = analyzer.analyze_orderbook(imbalanced_orderbook)
        # bid depth = 0.60*10000 = 6000, ask depth = 0.62*2000 = 1240
        # imbalance = (6000-1240)/(6000+1240) > 0
        assert result.depth_imbalance > 0
        assert result.total_bid_depth > result.total_ask_depth

    def test_analyze_orderbook_liquidity_score(
        self, analyzer: MicrostructureAnalyzer, tight_deep_orderbook: OrderBook
    ) -> None:
        result = analyzer.analyze_orderbook(tight_deep_orderbook)
        # Tight spread + decent depth -> high liquidity
        assert result.liquidity_score > 0.5


# ---------------------------------------------------------------------------
# Microstructure: price history tests
# ---------------------------------------------------------------------------


class TestAnalyzePriceHistory:
    def test_analyze_price_history_momentum(
        self,
        analyzer: MicrostructureAnalyzer,
        price_history_with_momentum: PriceHistory,
    ) -> None:
        result = analyzer.analyze_price_history(price_history_with_momentum)
        # Price went from ~0.40 to ~0.60, so 24h momentum should be positive
        assert result.momentum_24h > 0
        assert result.momentum_7d > 0

    def test_volume_anomaly_detection(
        self,
        analyzer: MicrostructureAnalyzer,
        price_history_volume_spike: PriceHistory,
    ) -> None:
        result = analyzer.analyze_price_history(price_history_volume_spike)
        # Recent volume 500 vs baseline 100 -> anomaly ~5
        assert result.volume_anomaly > 2.0


# ---------------------------------------------------------------------------
# Microstructure: composite tests
# ---------------------------------------------------------------------------


class TestCompositeScore:
    def test_composite_score(
        self,
        analyzer: MicrostructureAnalyzer,
        tight_deep_orderbook: OrderBook,
        price_history_with_momentum: PriceHistory,
    ) -> None:
        ob_analysis = analyzer.analyze_orderbook(tight_deep_orderbook)
        ph_analysis = analyzer.analyze_price_history(price_history_with_momentum)
        composite = analyzer.compute_composite(ob_analysis, ph_analysis)

        assert 0 <= composite.composite_score <= 1
        # Should carry forward fields from both analyses
        assert composite.spread_pct == ob_analysis.spread_pct
        assert composite.momentum_24h == ph_analysis.momentum_24h
        assert composite.volume_anomaly == ph_analysis.volume_anomaly


# ---------------------------------------------------------------------------
# Cross-market analyzer tests
# ---------------------------------------------------------------------------


class TestCrossMarketAnalyzer:
    def test_find_correlations_overlap(self, cross_analyzer: CrossMarketAnalyzer) -> None:
        target = _make_market("m1", "Will Biden win the 2024 election?", yes_price=0.60)
        universe = [
            target,
            _make_market("m2", "Will Biden win the 2024 presidential election?", yes_price=0.65),
            _make_market(
                "m3", "Will Bitcoin reach 100k?",
                yes_price=0.30, category=MarketCategory.CRYPTO,
            ),
        ]
        result = cross_analyzer.find_correlations(target, universe)
        # m2 shares many keywords with m1, m3 does not
        related_ids = {c.market_b_id for c in result.correlations}
        assert "m2" in related_ids
        assert "m3" not in related_ids

    def test_find_correlations_opposing(self, cross_analyzer: CrossMarketAnalyzer) -> None:
        target = _make_market("m1", "Will Trump win the 2024 election?", yes_price=0.55)
        universe = [
            target,
            _make_market(
                "m2",
                "Will Trump fail to win the 2024 election?",
                yes_price=0.40,
            ),
        ]
        result = cross_analyzer.find_correlations(target, universe)
        assert len(result.correlations) == 1
        assert result.correlations[0].correlation_type == "opposing"

    def test_price_discrepancy_opposing(self, cross_analyzer: CrossMarketAnalyzer) -> None:
        # Opposing markets: prices should sum to ~1. 0.70 + 0.50 = 1.20 -> discrepancy 0.20
        target = _make_market("m1", "Will Trump win the 2024 election?", yes_price=0.70)
        universe = [
            target,
            _make_market(
                "m2",
                "Will Trump fail to win the 2024 election?",
                yes_price=0.50,
            ),
        ]
        result = cross_analyzer.find_correlations(target, universe)
        assert len(result.correlations) == 1
        assert abs(result.correlations[0].price_discrepancy - 0.20) < 0.01

    def test_no_correlations_for_unique_market(
        self, cross_analyzer: CrossMarketAnalyzer
    ) -> None:
        target = _make_market("m1", "Will extraterrestrial life be discovered by NASA?")
        universe = [
            target,
            _make_market("m2", "Will Bitcoin reach 100k?", category=MarketCategory.CRYPTO),
            _make_market("m3", "Will France win the World Cup?", category=MarketCategory.SPORTS),
        ]
        result = cross_analyzer.find_correlations(target, universe)
        assert len(result.correlations) == 0
        assert result.composite_signal == 0.0

    def test_arbitrage_flag(self, cross_analyzer: CrossMarketAnalyzer) -> None:
        # Large discrepancy (>5%) should flag arbitrage
        target = _make_market("m1", "Will Trump win the 2024 election?", yes_price=0.80)
        universe = [
            target,
            _make_market(
                "m2",
                "Will Trump fail to win the 2024 election?",
                yes_price=0.50,
            ),
        ]
        result = cross_analyzer.find_correlations(target, universe)
        # 0.80 + 0.50 = 1.30, discrepancy = 0.30 > 0.05
        assert result.arbitrage_opportunity is True
        assert result.max_discrepancy > 0.05
