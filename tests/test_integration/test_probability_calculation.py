"""Integration tests: probability calculation (VAE formula verification).

Tests verify the full Value Assessment Engine pipeline:
- _compute_fair_value() weighted average with renormalization
- Signal transformations (microstructure, cross_market)
- Edge scaling by temporal_factor
- Fee adjustment
- Crowd calibration DB-driven path
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.models.market import (
    Market,
    MarketCategory,
    MarketStatus,
    Outcome,
)
from app.models.valuation import (
    MarketResolution,
    Recommendation,
    ValuationInput,
)
from app.valuation.db import ResolutionDB
from app.valuation.engine import ValueAssessmentEngine

# ── Helpers ───────────────────────────────────────────────────────────


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


# ── Test 3.1: Fair value with all signals known ──────────────────────


async def test_fair_value_with_all_signals_known(
    engine: ValueAssessmentEngine,
) -> None:
    """Verify _compute_fair_value() weighted average with all 7 signals.

    Inputs (constructed directly into ValuationInput):
      market_price = 0.40, fee_rate = 0.0
      base_rate = 0.55
      rule_analysis_score = 0.60
      microstructure_score = 0.50
      cross_market_signal = 0.45
      event_signal = 0.70
      pattern_kg_signal = 0.60
      cross_platform_signal = 0.50
      crowd_calibration_adjustment = 0.0  (NOT active, code: "if != 0")
      temporal_factor = 1.0

    Formula from _compute_fair_value():
      Weights (default): base_rate=0.15, rule=0.15, micro=0.15,
                          cross_mkt=0.10, event=0.15, pattern=0.10,
                          cross_plat=0.10
      crowd weight=0.05 but crowd_adj==0 so NOT included.

      Signal values fed into weighted_sum:
        base_rate:      0.55                              (direct)
        rule_analysis:  0.60                              (direct)
        microstructure: 0.40 + (0.50 - 0.5) * 0.1 = 0.40 (clamped 0-1)
        cross_market:   0.40 + 0.45 * 0.15 = 0.4675      (clamped 0-1)
        event_signal:   0.70                              (clamped 0-1)
        pattern_kg:     0.60                              (clamped 0-1)
        cross_platform: 0.50                              (clamped 0-1)

      weighted_sum = 0.15*0.55 + 0.15*0.60 + 0.15*0.40
                   + 0.10*0.4675 + 0.15*0.70 + 0.10*0.60 + 0.10*0.50
      = 0.0825 + 0.09 + 0.06 + 0.04675 + 0.105 + 0.06 + 0.05
      = 0.49425

      weight_total = 0.15 + 0.15 + 0.15 + 0.10 + 0.15 + 0.10 + 0.10 = 0.90

      fair_value = 0.49425 / 0.90 = 0.54917 (rounded to 0.5492)

      edge = fair_value - market_price = 0.5492 - 0.40 = 0.1492
      scaled_edge = edge * temporal_factor = 0.1492 * 1.0 = 0.1492
      fee_adjusted_edge = scaled_edge - fee_rate = 0.1492 - 0.0 = 0.1492
    """
    market_price = 0.40

    inputs = ValuationInput(
        market_id="m1",
        market_price=market_price,
        base_rate=0.55,
        crowd_calibration_adjustment=0.0,
        rule_analysis_score=0.60,
        microstructure_score=0.50,
        cross_market_signal=0.45,
        event_signal=0.70,
        pattern_kg_signal=0.60,
        cross_platform_signal=0.50,
        temporal_factor=1.0,
    )

    fair_value, edge_sources, confidence = engine._compute_fair_value(inputs)

    # Verify computed fair value matches formula
    # weighted_sum = 0.0825 + 0.09 + 0.06 + 0.04675 + 0.105 + 0.06 + 0.05
    expected_weighted_sum = (
        0.15 * 0.55  # base_rate
        + 0.15 * 0.60  # rule_analysis
        + 0.15 * 0.40  # micro: mkt_price + (0.50 - 0.5) * 0.1 = 0.40
        + 0.10 * 0.4675  # cross_market: mkt_price + 0.45 * 0.15
        + 0.15 * 0.70  # event_signal
        + 0.10 * 0.60  # pattern_kg
        + 0.10 * 0.50  # cross_platform
    )
    expected_weight_total = 0.15 + 0.15 + 0.15 + 0.10 + 0.15 + 0.10 + 0.10
    expected_fv = expected_weighted_sum / expected_weight_total

    assert abs(fair_value - expected_fv) < 0.01, f"fair_value={fair_value}, expected={expected_fv}"

    # Edge is positive (underpriced market)
    edge = fair_value - market_price
    assert edge > 0, f"Expected positive edge, got {edge}"

    # With temporal_factor=1.0 and fee_rate=0.0: fee_adjusted_edge == edge
    fee_adjusted_edge = edge * 1.0 - 0.0
    assert abs(fee_adjusted_edge - edge) < 0.0001

    # 7 active sources (crowd excluded since adj==0) -> all 7 should appear
    assert len(edge_sources) == 7
    source_names = {s.name for s in edge_sources}
    assert "base_rate" in source_names
    assert "rule_analysis" in source_names
    assert "microstructure" in source_names
    assert "cross_market" in source_names
    assert "event_signal" in source_names
    assert "pattern_kg" in source_names
    assert "cross_platform" in source_names

    # Confidence: 7 sources, coverage = min(1.0, 0.5 + 7/6) = 1.0
    # avg_confidence is average of per-source confidences
    assert confidence > 0.3  # above min_confidence threshold

    # Also verify recommendation through full assess() path
    # We seed enough resolutions so get_prior returns ~0.55
    # But for the direct _compute_fair_value test, the assertion above is enough


async def test_fair_value_with_all_signals_end_to_end(
    db: ResolutionDB,
    engine: ValueAssessmentEngine,
) -> None:
    """End-to-end assess() with multiple signals -> BUY recommendation.

    Seeds 70 YES + 30 NO resolutions so base_rate=0.70 (returned directly,
    no market_price shrinkage — P1 fix 2026-04-27). With market_price=0.40
    and additional bullish signals (event=0.70, rule=0.60, pattern=0.60,
    cross_platform=0.50), the weighted average sits well above 0.40.
    """
    await _seed_resolutions(db, "politics", yes_count=70, no_count=30)

    market = _make_market(
        yes_price=0.40,
        fee_rate=0.0,
        category=MarketCategory.POLITICS,
        end_date=datetime.now(tz=UTC) + timedelta(days=60),
    )

    result = await engine.assess(
        market,
        event_signal=0.70,
        rule_analysis_score=0.60,
        pattern_kg_signal=0.60,
        cross_platform_signal=0.50,
    )

    assert result.fair_value > result.market_price
    assert result.edge > 0
    # temporal_factor = 1.0 (60d), fee_rate = 0.0, so fee_adjusted_edge == edge
    assert abs(result.fee_adjusted_edge - result.edge) < 0.001
    assert result.recommendation in (
        Recommendation.BUY,
        Recommendation.STRONG_BUY,
    )


# ── Test 3.2: Fair value with partial signals ────────────────────────


async def test_fair_value_with_partial_signals(
    engine: ValueAssessmentEngine,
) -> None:
    """With an empty DB, ALL signals are correctly excluded — no anchoring.

    P1 fix 2026-04-27: previously base_rate produced ``0.10*0.5 + 0.90*0.6 = 0.59``
    (anchored to market_price), and the engine reported it as the only active
    edge source. Now ``get_prior`` returns ``None`` when historical resolutions
    are below ``min_base_rate_resolutions``, so the signal is excluded entirely.

    With zero signals and no orderbook/universe data, the engine falls back to
    ``fair_value = market_price`` via the ``weight_total == 0`` branch. The
    result is honest: confidence=0.0 (we know nothing), edge=0.0 (no opinion).
    """
    market = _make_market(
        yes_price=0.60,
        fee_rate=0.0,
        end_date=datetime.now(tz=UTC) + timedelta(days=60),
    )

    result = await engine.assess(market)

    # Should compute without exception, fair_value defaults to market_price.
    assert result.fair_value is not None
    assert result.fair_value == pytest.approx(0.60)
    assert result.edge == pytest.approx(0.0, abs=0.001)

    # Zero confidence: no signals fired → engine knows nothing.
    assert result.confidence == pytest.approx(0.0)

    # Critically: no signals — no false anchoring.
    source_names = {s.name for s in result.edge_sources}
    assert source_names == set(), f"Expected no signals, got {source_names}"


# ── Test 3.3: Edge calculation symmetry ──────────────────────────────


async def test_edge_calculation_symmetry(
    db: ResolutionDB,
    engine: ValueAssessmentEngine,
) -> None:
    """Verify edge sign: underpriced market -> positive edge, overpriced -> negative.

    Input A: market_price=0.30, strong YES signals -> edge > 0
    Input B: market_price=0.70, strong NO signals  -> edge < 0

    Both use the same category with 60% YES rate (base_rate = 0.60). After the
    P1 fix 2026-04-27 base_rate is returned directly (no market_price shrinkage),
    so the prior is ``0.60`` for both markets and the event_signal/rule_score
    push fair_value above 0.30 for A and below 0.70 for B.
    """
    await _seed_resolutions(db, "politics", yes_count=60, no_count=40)

    market_a = _make_market(
        market_id="underpriced",
        yes_price=0.30,
        fee_rate=0.0,
        category=MarketCategory.POLITICS,
        end_date=datetime.now(tz=UTC) + timedelta(days=60),
    )
    market_b = _make_market(
        market_id="overpriced",
        yes_price=0.70,
        fee_rate=0.0,
        category=MarketCategory.POLITICS,
        end_date=datetime.now(tz=UTC) + timedelta(days=60),
    )

    # Market A: underpriced, signals push fair value above 0.30
    result_a = await engine.assess(
        market_a,
        event_signal=0.60,
        rule_analysis_score=0.65,
    )
    # Market B: overpriced, signals push fair value below 0.70
    result_b = await engine.assess(
        market_b,
        event_signal=0.40,
        rule_analysis_score=0.35,
    )

    # A is underpriced: fair_value > market_price -> positive edge
    assert result_a.edge > 0, (
        f"Expected positive edge for underpriced market, "
        f"got edge={result_a.edge}, fv={result_a.fair_value}, mp={result_a.market_price}"
    )
    # B is overpriced: fair_value < market_price -> negative edge
    assert result_b.edge < 0, (
        f"Expected negative edge for overpriced market, "
        f"got edge={result_b.edge}, fv={result_b.fair_value}, mp={result_b.market_price}"
    )

    # fee_adjusted_edge should have same sign as edge (fee_rate=0, temporal=1.0)
    assert result_a.fee_adjusted_edge > 0
    assert result_b.fee_adjusted_edge < 0


# ── Test 3.4: Temporal factor scales edge ────────────────────────────


async def test_temporal_factor_scales_edge(
    db: ResolutionDB,
    engine: ValueAssessmentEngine,
) -> None:
    """Near-expiry market gets smaller fee_adjusted_edge due to temporal scaling.

    Market A: end_date = now + 2 hours
      days_remaining = 2/24 ≈ 0.083
      For POLITICS (decay_rate=0.8):
        factor = (0.083/30) * 0.8 + (1 - 0.8)
               = 0.0022 + 0.2 = 0.2022
      So temporal_factor_A ≈ 0.20

    Market B: end_date = now + 60 days
      days_remaining > 30 -> temporal_factor = 1.0

    Same signals for both. Edge is the same but scaled_edge differs:
      scaled_edge_A = edge * 0.20
      scaled_edge_B = edge * 1.0
    Therefore abs(fee_adjusted_edge_A) < abs(fee_adjusted_edge_B).
    """
    # Seed DB so base_rate drives some edge
    await _seed_resolutions(db, "politics", yes_count=80, no_count=20)

    market_near = _make_market(
        market_id="near",
        yes_price=0.40,
        fee_rate=0.0,
        category=MarketCategory.POLITICS,
        end_date=datetime.now(tz=UTC) + timedelta(hours=2),
    )
    market_far = _make_market(
        market_id="far",
        yes_price=0.40,
        fee_rate=0.0,
        category=MarketCategory.POLITICS,
        end_date=datetime.now(tz=UTC) + timedelta(days=60),
    )

    result_near = await engine.assess(
        market_near,
        event_signal=0.75,
        rule_analysis_score=0.70,
    )
    result_far = await engine.assess(
        market_far,
        event_signal=0.75,
        rule_analysis_score=0.70,
    )

    # Verify temporal factors
    assert result_near.inputs is not None
    assert result_far.inputs is not None
    assert result_near.inputs.temporal_factor < result_far.inputs.temporal_factor, (
        f"Near temporal={result_near.inputs.temporal_factor} should be < "
        f"far temporal={result_far.inputs.temporal_factor}"
    )
    # Far market: > 30 days -> temporal_factor = 1.0
    assert result_far.inputs.temporal_factor == 1.0

    # Near market: temporal_factor should be much less than 1.0
    assert result_near.inputs.temporal_factor < 0.5

    # The fee_adjusted_edge magnitude should be smaller for the near market
    # because: fee_adjusted_edge = edge * temporal_factor - fee_rate
    # With fee_rate=0: fee_adjusted_edge = edge * temporal_factor
    # Same signals -> same fair_value -> same edge
    # But temporal scaling reduces the near market's effective edge
    assert abs(result_near.fee_adjusted_edge) < abs(result_far.fee_adjusted_edge), (
        f"Near fee_adj_edge={result_near.fee_adjusted_edge} "
        f"should be < far fee_adj_edge={result_far.fee_adjusted_edge} (abs)"
    )


# ── Test 3.5: Crowd calibration adjusts fair value ──────────────────


async def test_crowd_calibration_adjusts_fair_value(
    db: ResolutionDB,
) -> None:
    """Crowd calibration shifts fair value when sample_size >= 20.

    Setup: 25 "politics" resolutions with final_price in 0.75-0.85 range.
    These land in bucket center 0.80 (range: 0.75 to 0.85).
    - 15 resolved YES, 10 resolved NO -> actual_freq = 15/25 = 0.60
    - bias contribution = (0.80 - 0.60) * 25 = 5.0
    - overall_bias = 5.0 / 25 = 0.20 (crowd overconfident by 0.20)
    - adjustment = -bias = -0.20

    When crowd_calibration_adjustment != 0, _compute_fair_value() adds
    the crowd_calibration weighted signal:
      adjusted_price = market_price + adjustment
      weighted_sum += w_crowd * adjusted_price
      weight_total += w_crowd
    """
    # Seed 15 YES + 10 NO, all with final_price=0.80 (in the 0.80 bucket)
    for i in range(15):
        await db.add_resolution(
            MarketResolution(
                market_id=f"pol_y{i}",
                category="politics",
                question=f"Crowd YES #{i}",
                final_price=0.80,
                resolved_yes=True,
                resolution_date=datetime(2025, 1, 1, tzinfo=UTC),
                volume=1000.0,
            )
        )
    for i in range(10):
        await db.add_resolution(
            MarketResolution(
                market_id=f"pol_n{i}",
                category="politics",
                question=f"Crowd NO #{i}",
                final_price=0.80,
                resolved_yes=False,
                resolution_date=datetime(2025, 1, 1, tzinfo=UTC),
                volume=1000.0,
            )
        )

    # Engine WITH calibration (uses seeded DB)
    engine_with = ValueAssessmentEngine(db)

    market = _make_market(
        yes_price=0.50,
        fee_rate=0.0,
        category=MarketCategory.POLITICS,
        end_date=datetime.now(tz=UTC) + timedelta(days=60),
    )

    result_with = await engine_with.assess(
        market,
        event_signal=0.60,
        rule_analysis_score=0.55,
    )

    # The calibration adjustment should be negative (crowd overconfident)
    assert result_with.inputs is not None
    calibration_adj = result_with.inputs.crowd_calibration_adjustment
    assert calibration_adj < 0, f"Expected negative calibration adjustment, got {calibration_adj}"

    # Verify the adjustment value: bias=0.20, adjustment=-0.20
    assert abs(calibration_adj - (-0.20)) < 0.02, (
        f"Expected calibration_adj ~ -0.20, got {calibration_adj}"
    )

    # Now compute fair value WITHOUT calibration for comparison.
    # Build a ValuationInput identical to what assess() produced, but zero out
    # the calibration to see the difference.
    inputs_without = result_with.inputs.model_copy(update={"crowd_calibration_adjustment": 0.0})
    fv_without, _, _ = engine_with._compute_fair_value(inputs_without)
    fv_with, _, _ = engine_with._compute_fair_value(result_with.inputs)

    # The fair values must differ
    assert fv_with != fv_without, (
        f"Fair value with calibration ({fv_with}) should differ from without ({fv_without})"
    )

    # Negative calibration adj should push fair value DOWN relative to
    # the version without calibration
    assert fv_with < fv_without, (
        f"With negative calibration, fv_with={fv_with} should be < fv_without={fv_without}"
    )

    # Verify crowd_calibration appears in edge_sources
    crowd_sources = [s for s in result_with.edge_sources if s.name == "crowd_calibration"]
    assert len(crowd_sources) == 1, (
        f"Expected crowd_calibration in edge_sources, "
        f"found: {[s.name for s in result_with.edge_sources]}"
    )
