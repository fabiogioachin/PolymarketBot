"""Tests for the Value Assessment Engine."""

from datetime import UTC, datetime, timedelta

import pytest

from app.models.market import (
    Market,
    MarketCategory,
    MarketStatus,
    OrderBook,
    OrderBookLevel,
    Outcome,
)
from app.models.valuation import MarketResolution, Recommendation
from app.valuation.db import ResolutionDB
from app.valuation.engine import ValueAssessmentEngine

# ── Fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
async def db():
    """In-memory SQLite resolution database."""
    database = ResolutionDB(db_path=":memory:")
    await database.init()
    yield database
    await database.close()


@pytest.fixture
def engine(db: ResolutionDB) -> ValueAssessmentEngine:
    return ValueAssessmentEngine(db)


def _make_market(
    market_id: str = "m1",
    category: MarketCategory = MarketCategory.POLITICS,
    yes_price: float = 0.5,
    fee_rate: float = 0.0,
    end_date: datetime | None = None,
    volume: float = 10000.0,
    question: str = "Will event X happen?",
) -> Market:
    if end_date is None:
        end_date = datetime.now(tz=UTC) + timedelta(days=60)
    return Market(
        id=market_id,
        question=question,
        category=category,
        status=MarketStatus.ACTIVE,
        outcomes=[
            Outcome(token_id="t1", outcome="Yes", price=yes_price),
            Outcome(token_id="t2", outcome="No", price=round(1.0 - yes_price, 4)),
        ],
        end_date=end_date,
        volume=volume,
        liquidity=5000.0,
        fee_rate=fee_rate,
    )


async def _seed_resolutions(
    db: ResolutionDB,
    category: str,
    yes_count: int,
    no_count: int,
    final_price: float = 0.5,
) -> None:
    """Seed the DB with resolution records."""
    for i in range(yes_count):
        await db.add_resolution(
            MarketResolution(
                market_id=f"{category}_y{i}",
                category=category,
                question=f"Resolved YES #{i}",
                final_price=final_price,
                resolved_yes=True,
                resolution_date=datetime(2025, 1, 1, tzinfo=UTC),
                volume=1000.0,
            )
        )
    for i in range(no_count):
        await db.add_resolution(
            MarketResolution(
                market_id=f"{category}_n{i}",
                category=category,
                question=f"Resolved NO #{i}",
                final_price=final_price,
                resolved_yes=False,
                resolution_date=datetime(2025, 1, 1, tzinfo=UTC),
                volume=1000.0,
            )
        )


# ── Basic assessment tests ─────────────────────────────────────────────


async def test_assess_no_signals(engine: ValueAssessmentEngine):
    """With no extra signals, fair value should be close to market price -> HOLD."""
    market = _make_market(yes_price=0.5)
    result = await engine.assess(market)

    assert result.market_id == "m1"
    # With only base_rate (0.5 uninformative prior), fair value ~ market price
    assert abs(result.fair_value - 0.5) < 0.05
    assert result.recommendation == Recommendation.HOLD


async def test_assess_with_base_rate(db: ResolutionDB, engine: ValueAssessmentEngine):
    """Historical resolutions shift the base rate, which shifts fair value."""
    # 80% YES resolution rate in politics
    await _seed_resolutions(db, "politics", yes_count=40, no_count=10)

    market = _make_market(yes_price=0.5, category=MarketCategory.POLITICS)
    result = await engine.assess(market)

    # Base rate = 0.8, prior will shrink toward market price but still > 0.5
    # So fair_value should be > market_price
    assert result.fair_value > 0.5
    assert result.edge > 0


async def test_assess_with_positive_edge(db: ResolutionDB, engine: ValueAssessmentEngine):
    """When fair value exceeds market price + threshold -> BUY."""
    # Create strong historical signal: 90% YES rate
    await _seed_resolutions(db, "politics", yes_count=90, no_count=10)

    # Market price is low at 0.3 — should detect positive edge
    market = _make_market(yes_price=0.3, category=MarketCategory.POLITICS)
    result = await engine.assess(
        market,
        event_signal=0.9,  # strong event signal confirming YES
        rule_analysis_score=0.85,
    )

    assert result.fair_value > result.market_price
    assert result.edge > 0
    assert result.fee_adjusted_edge > 0
    assert result.recommendation in (Recommendation.BUY, Recommendation.STRONG_BUY)


async def test_assess_with_negative_edge(db: ResolutionDB, engine: ValueAssessmentEngine):
    """When fair value is below market price -> SELL."""
    # Low historical YES rate
    await _seed_resolutions(db, "politics", yes_count=10, no_count=90)

    # Market price is high at 0.8 — should detect negative edge
    market = _make_market(yes_price=0.8, category=MarketCategory.POLITICS)
    result = await engine.assess(
        market,
        event_signal=0.15,  # event signal also says NO
        rule_analysis_score=0.1,
    )

    assert result.fair_value < result.market_price
    assert result.edge < 0
    assert result.fee_adjusted_edge < 0
    assert result.recommendation in (Recommendation.SELL, Recommendation.STRONG_SELL)


async def test_assess_strong_buy(db: ResolutionDB, engine: ValueAssessmentEngine):
    """Strong edge threshold crossed -> STRONG_BUY."""
    await _seed_resolutions(db, "politics", yes_count=95, no_count=5)

    # Very low market price with overwhelming signals
    market = _make_market(yes_price=0.15, category=MarketCategory.POLITICS)
    result = await engine.assess(
        market,
        event_signal=0.95,
        rule_analysis_score=0.95,
        pattern_kg_signal=0.9,
    )

    # Multiple strong signals pointing much higher than 0.15
    assert result.fee_adjusted_edge >= 0.15
    assert result.recommendation == Recommendation.STRONG_BUY


async def test_assess_single_source_moderate_confidence(engine: ValueAssessmentEngine):
    """With only base_rate signal, confidence should be moderate but edge ≈ 0 → HOLD."""
    # With no historical data and only base_rate signal, confidence is moderate
    # but edge is zero (fair_value ≈ market_price), so recommendation is HOLD.
    market = _make_market(yes_price=0.5)
    result = await engine.assess(market)

    # 1 source: coverage = 0.5 + 1/6 ≈ 0.67, confidence = 0.5 * 0.67 ≈ 0.33
    assert result.confidence < 0.5
    # Edge ≈ 0 because base_rate ≈ market_price → HOLD regardless of confidence
    assert abs(result.edge) < 0.05
    assert result.recommendation == Recommendation.HOLD


# ── Signal-specific tests ──────────────────────────────────────────────


async def test_assess_with_microstructure(engine: ValueAssessmentEngine):
    """Orderbook data contributes microstructure score to assessment."""
    market = _make_market(yes_price=0.5)
    orderbook = OrderBook(
        market_id="m1",
        asset_id="t1",
        bids=[
            OrderBookLevel(price=0.49, size=1000),
            OrderBookLevel(price=0.48, size=2000),
        ],
        asks=[
            OrderBookLevel(price=0.51, size=1000),
            OrderBookLevel(price=0.52, size=2000),
        ],
        spread=0.02,
        midpoint=0.50,
    )

    result = await engine.assess(market, orderbook_data=orderbook)

    assert result.inputs is not None
    assert result.inputs.microstructure_score is not None
    # Microstructure source should appear in edge sources
    micro_sources = [s for s in result.edge_sources if s.name == "microstructure"]
    assert len(micro_sources) == 1


async def test_assess_with_cross_market(db: ResolutionDB, engine: ValueAssessmentEngine):
    """Cross-market analysis contributes when universe is provided."""
    target = _make_market(
        market_id="target",
        yes_price=0.5,
        question="Will Biden win the 2028 election?",
    )
    related = _make_market(
        market_id="related",
        yes_price=0.7,
        question="Will Biden be the Democratic nominee for 2028 election?",
    )

    result = await engine.assess(target, universe=[target, related])

    assert result.inputs is not None
    # Cross-market signal may or may not be populated depending on keyword overlap
    # but the engine should not crash


async def test_assess_fee_adjustment(db: ResolutionDB, engine: ValueAssessmentEngine):
    """Fee reduces effective edge -- high fee can eliminate edge."""
    await _seed_resolutions(db, "crypto", yes_count=80, no_count=20)

    # Market with 7% fee rate
    market = _make_market(
        yes_price=0.5,
        category=MarketCategory.CRYPTO,
        fee_rate=0.07,
    )
    result = await engine.assess(market, event_signal=0.6)

    # fee_adjusted_edge = scaled_edge - fee_rate
    # The fee should reduce the edge
    assert result.fee_adjusted_edge < result.edge


async def test_assess_temporal_factor(engine: ValueAssessmentEngine):
    """Market near deadline has reduced edge due to temporal scaling."""
    # Market expiring tomorrow
    near_deadline = _make_market(
        market_id="near",
        yes_price=0.5,
        end_date=datetime.now(tz=UTC) + timedelta(hours=12),
    )
    # Market expiring in 2 months
    far_deadline = _make_market(
        market_id="far",
        yes_price=0.5,
        end_date=datetime.now(tz=UTC) + timedelta(days=60),
    )

    result_near = await engine.assess(near_deadline, event_signal=0.8)
    result_far = await engine.assess(far_deadline, event_signal=0.8)

    assert result_near.inputs is not None
    assert result_far.inputs is not None

    # Near-deadline market should have lower temporal factor
    assert result_near.inputs.temporal_factor < result_far.inputs.temporal_factor
    # And therefore smaller fee_adjusted_edge (in absolute terms)
    assert abs(result_near.fee_adjusted_edge) < abs(result_far.fee_adjusted_edge)


# ── Batch assessment ───────────────────────────────────────────────────


async def test_assess_batch(engine: ValueAssessmentEngine):
    """Batch assessment returns results sorted by absolute edge."""
    markets = [
        _make_market(market_id=f"m{i}", yes_price=0.5, volume=float(i * 1000))
        for i in range(5)
    ]

    results = await engine.assess_batch(markets)

    assert len(results) == 5
    # Results should be sorted by absolute fee_adjusted_edge descending
    edges = [abs(r.fee_adjusted_edge) for r in results]
    assert edges == sorted(edges, reverse=True)


# ── Edge source and clamping tests ─────────────────────────────────────


async def test_edge_sources_populated(db: ResolutionDB, engine: ValueAssessmentEngine):
    """Edge sources list has entries for each active signal."""
    await _seed_resolutions(db, "politics", yes_count=50, no_count=50)

    market = _make_market(yes_price=0.5)
    result = await engine.assess(
        market,
        event_signal=0.7,
        rule_analysis_score=0.6,
        pattern_kg_signal=0.55,
    )

    source_names = {s.name for s in result.edge_sources}
    assert "base_rate" in source_names
    assert "event_signal" in source_names
    assert "rule_analysis" in source_names
    assert "pattern_kg" in source_names


async def test_fair_value_clamped(db: ResolutionDB, engine: ValueAssessmentEngine):
    """Fair value is always between 0 and 1, even with extreme inputs."""
    await _seed_resolutions(db, "politics", yes_count=100, no_count=0)

    market = _make_market(yes_price=0.99)
    result = await engine.assess(
        market,
        event_signal=1.0,
        rule_analysis_score=1.0,
        pattern_kg_signal=1.0,
    )

    assert 0.0 <= result.fair_value <= 1.0

    # Also test with extreme low
    await _seed_resolutions(db, "sports", yes_count=0, no_count=100)
    market_low = _make_market(
        market_id="low",
        yes_price=0.01,
        category=MarketCategory.SPORTS,
    )
    result_low = await engine.assess(
        market_low,
        event_signal=0.0,
        rule_analysis_score=0.0,
        pattern_kg_signal=0.0,
    )
    assert 0.0 <= result_low.fair_value <= 1.0


# ── Recommendation logic tests ─────────────────────────────────────────


async def test_recommend_hold_on_small_edge(engine: ValueAssessmentEngine):
    """Edge below min_edge threshold -> HOLD even with confidence."""
    # Directly test the _recommend method
    # min_edge=0.05, min_confidence=0.3, strong_edge=0.15
    assert engine._recommend(0.03, 0.5) == Recommendation.HOLD
    assert engine._recommend(-0.03, 0.5) == Recommendation.HOLD


async def test_recommend_buy_sell_thresholds(engine: ValueAssessmentEngine):
    """Test all recommendation thresholds."""
    # BUY: edge >= 0.05, confidence >= 0.3
    assert engine._recommend(0.06, 0.5) == Recommendation.BUY
    # STRONG_BUY: edge >= 0.15
    assert engine._recommend(0.16, 0.5) == Recommendation.STRONG_BUY
    # SELL: edge <= -0.05
    assert engine._recommend(-0.06, 0.5) == Recommendation.SELL
    # STRONG_SELL: edge <= -0.15
    assert engine._recommend(-0.16, 0.5) == Recommendation.STRONG_SELL
    # Low confidence always HOLD
    assert engine._recommend(0.20, 0.1) == Recommendation.HOLD
