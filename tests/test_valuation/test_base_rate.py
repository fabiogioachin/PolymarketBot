"""Tests for base rate analyzer, crowd calibration, and resolution DB."""

from datetime import datetime

import pytest

from app.models.market import Market, MarketCategory, Outcome
from app.models.valuation import MarketResolution
from app.valuation.base_rate import BaseRateAnalyzer
from app.valuation.crowd_calibration import CrowdCalibrationAnalyzer
from app.valuation.db import ResolutionDB


@pytest.fixture
async def db():
    """In-memory SQLite resolution database."""
    database = ResolutionDB(db_path=":memory:")
    await database.init()
    yield database
    await database.close()


def _make_market(
    market_id: str = "m1",
    category: MarketCategory = MarketCategory.POLITICS,
    yes_price: float = 0.5,
) -> Market:
    return Market(
        id=market_id,
        category=category,
        outcomes=[
            Outcome(token_id="t1", outcome="Yes", price=yes_price),
            Outcome(token_id="t2", outcome="No", price=1.0 - yes_price),
        ],
    )


def _make_resolution(
    market_id: str,
    category: str,
    resolved_yes: bool,
    final_price: float = 0.5,
) -> MarketResolution:
    return MarketResolution(
        market_id=market_id,
        category=category,
        question=f"Question for {market_id}",
        final_price=final_price,
        resolved_yes=resolved_yes,
        resolution_date=datetime(2025, 1, 1),
        volume=1000.0,
    )


# ── ResolutionDB Tests ──────────────────────────────────────────────


async def test_db_add_and_get(db: ResolutionDB):
    res = _make_resolution("m1", "politics", resolved_yes=True)
    await db.add_resolution(res)
    fetched = await db.get_resolution("m1")
    assert fetched is not None
    assert fetched.market_id == "m1"
    assert fetched.resolved_yes is True


async def test_db_get_missing(db: ResolutionDB):
    assert await db.get_resolution("nonexistent") is None


async def test_db_count(db: ResolutionDB):
    for i in range(5):
        await db.add_resolution(
            _make_resolution(f"m{i}", "politics", resolved_yes=True)
        )
    assert await db.get_resolution_count(category="politics") == 5
    assert await db.get_resolution_count(category="sports") == 0
    assert await db.get_resolution_count() == 5


async def test_db_filter_by_category(db: ResolutionDB):
    await db.add_resolution(_make_resolution("m1", "politics", True))
    await db.add_resolution(_make_resolution("m2", "sports", False))
    politics = await db.get_resolutions(category="politics")
    assert len(politics) == 1
    assert politics[0].market_id == "m1"


async def test_db_upsert(db: ResolutionDB):
    await db.add_resolution(_make_resolution("m1", "politics", True, final_price=0.6))
    await db.add_resolution(_make_resolution("m1", "politics", False, final_price=0.4))
    fetched = await db.get_resolution("m1")
    assert fetched is not None
    assert fetched.resolved_yes is False
    assert fetched.final_price == pytest.approx(0.4)


# ── Base Rate Tests ─────────────────────────────────────────────────


async def test_base_rate_no_data(db: ResolutionDB):
    analyzer = BaseRateAnalyzer(db)
    market = _make_market(category=MarketCategory.POLITICS)
    rate = await analyzer.get_base_rate(market)
    assert rate == 0.5  # uninformative prior


async def test_base_rate_with_data(db: ResolutionDB):
    # 7 YES, 3 NO in politics
    for i in range(7):
        await db.add_resolution(_make_resolution(f"y{i}", "politics", True))
    for i in range(3):
        await db.add_resolution(_make_resolution(f"n{i}", "politics", False))

    analyzer = BaseRateAnalyzer(db)
    market = _make_market(category=MarketCategory.POLITICS)
    rate = await analyzer.get_base_rate(market)
    assert rate == pytest.approx(0.7)


async def test_base_rate_multiple_categories(db: ResolutionDB):
    # politics: 8/10 YES, sports: 3/10 YES
    for i in range(8):
        await db.add_resolution(_make_resolution(f"py{i}", "politics", True))
    for i in range(2):
        await db.add_resolution(_make_resolution(f"pn{i}", "politics", False))
    for i in range(3):
        await db.add_resolution(_make_resolution(f"sy{i}", "sports", True))
    for i in range(7):
        await db.add_resolution(_make_resolution(f"sn{i}", "sports", False))

    analyzer = BaseRateAnalyzer(db)
    rates = await analyzer.compute_base_rates()
    assert rates["politics"] == pytest.approx(0.8)
    assert rates["sports"] == pytest.approx(0.3)


async def test_get_prior_weak_prior(db: ResolutionDB):
    """With <10 samples, shrinkage=0.3: leans toward market price."""
    # 5 resolutions, all YES -> base_rate = 1.0
    for i in range(5):
        await db.add_resolution(_make_resolution(f"m{i}", "politics", True))

    analyzer = BaseRateAnalyzer(db)
    market = _make_market(category=MarketCategory.POLITICS, yes_price=0.6)
    prior = await analyzer.get_prior(market)
    # shrinkage=0.3: 0.3 * 1.0 + 0.7 * 0.6 = 0.3 + 0.42 = 0.72
    assert prior == pytest.approx(0.72)


async def test_get_prior_strong_prior(db: ResolutionDB):
    """With 50+ samples, shrinkage=0.7: leans toward base rate."""
    # 50 resolutions, 40 YES -> base_rate = 0.8
    for i in range(40):
        await db.add_resolution(_make_resolution(f"y{i}", "politics", True))
    for i in range(10):
        await db.add_resolution(_make_resolution(f"n{i}", "politics", False))

    analyzer = BaseRateAnalyzer(db)
    market = _make_market(category=MarketCategory.POLITICS, yes_price=0.6)
    prior = await analyzer.get_prior(market)
    # shrinkage=0.7: 0.7 * 0.8 + 0.3 * 0.6 = 0.56 + 0.18 = 0.74
    assert prior == pytest.approx(0.74)


async def test_compute_caches_rates(db: ResolutionDB):
    """Calling get_base_rate twice doesn't recompute (uses cache)."""
    for i in range(3):
        await db.add_resolution(_make_resolution(f"m{i}", "politics", True))

    analyzer = BaseRateAnalyzer(db)
    market = _make_market(category=MarketCategory.POLITICS)
    rate1 = await analyzer.get_base_rate(market)

    # Add more data after first call — rate should NOT change (cached)
    for i in range(10):
        await db.add_resolution(_make_resolution(f"extra{i}", "politics", False))

    rate2 = await analyzer.get_base_rate(market)
    assert rate1 == rate2  # still cached


# ── Crowd Calibration Tests ─────────────────────────────────────────


async def test_calibration_no_data(db: ResolutionDB):
    analyzer = CrowdCalibrationAnalyzer(db)
    cal = await analyzer.compute_calibration(category="politics")
    assert cal.sample_size == 0
    assert cal.points == []


async def test_calibration_well_calibrated(db: ResolutionDB):
    """Prices at ~0.7 that resolve YES 70% of the time -> bias near 0."""
    # 70 YES, 30 NO, all with final_price in [0.65, 0.75) bucket (center=0.7)
    for i in range(70):
        await db.add_resolution(
            _make_resolution(f"y{i}", "politics", True, final_price=0.70)
        )
    for i in range(30):
        await db.add_resolution(
            _make_resolution(f"n{i}", "politics", False, final_price=0.70)
        )

    analyzer = CrowdCalibrationAnalyzer(db)
    cal = await analyzer.compute_calibration(category="politics")
    assert cal.sample_size == 100
    assert len(cal.points) == 1
    assert cal.points[0].predicted_probability == pytest.approx(0.7)
    assert cal.points[0].actual_frequency == pytest.approx(0.7)
    assert cal.bias == pytest.approx(0.0, abs=0.01)


async def test_calibration_overconfident(db: ResolutionDB):
    """Prices at 0.8 but only 60% resolve YES -> crowd overconfident, positive bias."""
    for i in range(60):
        await db.add_resolution(
            _make_resolution(f"y{i}", "politics", True, final_price=0.80)
        )
    for i in range(40):
        await db.add_resolution(
            _make_resolution(f"n{i}", "politics", False, final_price=0.80)
        )

    analyzer = CrowdCalibrationAnalyzer(db)
    cal = await analyzer.compute_calibration(category="politics")
    # bias = (0.8 - 0.6) = 0.2 positive (overconfident)
    assert cal.bias > 0
    assert cal.bias == pytest.approx(0.2, abs=0.01)


async def test_calibration_underconfident(db: ResolutionDB):
    """Prices at 0.3 but 50% resolve YES -> crowd underconfident, negative bias."""
    for i in range(50):
        await db.add_resolution(
            _make_resolution(f"y{i}", "politics", True, final_price=0.30)
        )
    for i in range(50):
        await db.add_resolution(
            _make_resolution(f"n{i}", "politics", False, final_price=0.30)
        )

    analyzer = CrowdCalibrationAnalyzer(db)
    cal = await analyzer.compute_calibration(category="politics")
    # bias = (0.3 - 0.5) = -0.2 negative (underconfident)
    assert cal.bias < 0
    assert cal.bias == pytest.approx(-0.2, abs=0.01)


async def test_adjustment_negates_bias(db: ResolutionDB):
    """Adjustment should be -bias."""
    for i in range(60):
        await db.add_resolution(
            _make_resolution(f"y{i}", "politics", True, final_price=0.80)
        )
    for i in range(40):
        await db.add_resolution(
            _make_resolution(f"n{i}", "politics", False, final_price=0.80)
        )

    analyzer = CrowdCalibrationAnalyzer(db)
    cal = await analyzer.compute_calibration(category="politics")
    adj = await analyzer.get_adjustment("politics")
    assert adj == pytest.approx(-cal.bias)


async def test_adjustment_insufficient_data(db: ResolutionDB):
    """With <20 samples, adjustment returns 0.0."""
    for i in range(10):
        await db.add_resolution(
            _make_resolution(f"y{i}", "politics", True, final_price=0.80)
        )

    analyzer = CrowdCalibrationAnalyzer(db)
    adj = await analyzer.get_adjustment("politics")
    assert adj == 0.0


# ── ResolutionDB source column Tests ───────────────────────────────


async def test_db_default_source(db: ResolutionDB):
    """Resolution stored without explicit source defaults to 'polymarket'."""
    res = _make_resolution("m_default", "politics", resolved_yes=True)
    await db.add_resolution(res)
    fetched = await db.get_resolution("m_default")
    assert fetched is not None
    assert fetched.source == "polymarket"


async def test_db_explicit_source(db: ResolutionDB):
    """Resolution stored with explicit source='manifold' roundtrips correctly."""
    res = MarketResolution(
        market_id="manifold:abc123",
        category="sports",
        question="Will Team A win?",
        final_price=0.65,
        resolved_yes=True,
        resolution_date=datetime(2025, 3, 1),
        volume=2000.0,
        source="manifold",
    )
    await db.add_resolution(res)
    fetched = await db.get_resolution("manifold:abc123")
    assert fetched is not None
    assert fetched.source == "manifold"


async def test_db_filter_by_source(db: ResolutionDB):
    """get_resolutions(source=...) returns only records matching that source."""
    poly_res = MarketResolution(
        market_id="poly:1",
        category="politics",
        question="Poly question",
        final_price=0.4,
        resolved_yes=False,
        volume=1000.0,
        source="polymarket",
    )
    manifold_res = MarketResolution(
        market_id="manifold:1",
        category="politics",
        question="Manifold question",
        final_price=0.6,
        resolved_yes=True,
        volume=800.0,
        source="manifold",
    )
    await db.add_resolution(poly_res)
    await db.add_resolution(manifold_res)

    poly_results = await db.get_resolutions(source="polymarket")
    manifold_results = await db.get_resolutions(source="manifold")
    all_results = await db.get_resolutions()

    assert len(poly_results) == 1
    assert poly_results[0].market_id == "poly:1"
    assert len(manifold_results) == 1
    assert manifold_results[0].market_id == "manifold:1"
    assert len(all_results) == 2


async def test_db_filter_by_category_and_source(db: ResolutionDB):
    """get_resolutions with both category and source applies both filters."""
    await db.add_resolution(
        MarketResolution(
            market_id="p1",
            category="politics",
            question="Q1",
            final_price=0.5,
            resolved_yes=True,
            volume=500.0,
            source="polymarket",
        )
    )
    await db.add_resolution(
        MarketResolution(
            market_id="m1",
            category="politics",
            question="Q2",
            final_price=0.5,
            resolved_yes=False,
            volume=600.0,
            source="manifold",
        )
    )
    await db.add_resolution(
        MarketResolution(
            market_id="m2",
            category="sports",
            question="Q3",
            final_price=0.7,
            resolved_yes=True,
            volume=700.0,
            source="manifold",
        )
    )

    results = await db.get_resolutions(category="politics", source="manifold")
    assert len(results) == 1
    assert results[0].market_id == "m1"


async def test_db_source_preserved_on_upsert(db: ResolutionDB):
    """Upserting a record with a different source replaces the previous source."""
    res1 = MarketResolution(
        market_id="shared:1",
        category="crypto",
        question="BTC?",
        final_price=0.8,
        resolved_yes=True,
        volume=3000.0,
        source="polymarket",
    )
    res2 = MarketResolution(
        market_id="shared:1",
        category="crypto",
        question="BTC?",
        final_price=0.9,
        resolved_yes=True,
        volume=3500.0,
        source="manifold",
    )
    await db.add_resolution(res1)
    await db.add_resolution(res2)

    fetched = await db.get_resolution("shared:1")
    assert fetched is not None
    assert fetched.source == "manifold"
    assert fetched.final_price == pytest.approx(0.9)
