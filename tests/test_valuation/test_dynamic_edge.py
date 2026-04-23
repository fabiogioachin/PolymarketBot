"""Tests for Phase 13 S1 — volatility-aware dynamic edge."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.models.market import (
    Market,
    MarketCategory,
    MarketStatus,
    Outcome,
    PriceHistory,
    PricePoint,
)
from app.models.valuation import Recommendation
from app.valuation.db import ResolutionDB
from app.valuation.engine import ValueAssessmentEngine
from app.valuation.microstructure import MicrostructureAnalyzer

# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
async def db():
    database = ResolutionDB(db_path=":memory:")
    await database.init()
    yield database
    await database.close()


@pytest.fixture
def engine(db: ResolutionDB) -> ValueAssessmentEngine:
    return ValueAssessmentEngine(db)


def _points(prices: list[float], start_minutes_ago: int = 60) -> list[PricePoint]:
    """Build PricePoints evenly spaced in time from oldest to newest."""
    now = datetime.now(tz=UTC)
    step = timedelta(minutes=start_minutes_ago / max(len(prices) - 1, 1))
    return [
        PricePoint(timestamp=now - (timedelta(minutes=start_minutes_ago) - step * i), price=p)
        for i, p in enumerate(prices)
    ]


def _make_market(
    yes_price: float = 0.5,
    end_days: int = 7,
    fee_rate: float = 0.0,
) -> Market:
    return Market(
        id="m1",
        question="Q?",
        category=MarketCategory.POLITICS,
        status=MarketStatus.ACTIVE,
        outcomes=[
            Outcome(token_id="t1", outcome="Yes", price=yes_price),
            Outcome(token_id="t2", outcome="No", price=round(1.0 - yes_price, 4)),
        ],
        end_date=datetime.now(tz=UTC) + timedelta(days=end_days),
        volume=10000.0,
        liquidity=5000.0,
        fee_rate=fee_rate,
    )


# ── realized_volatility / price_velocity helpers ──────────────────────


def test_realized_volatility_insufficient_data():
    # <3 points → 0.0
    pts = _points([0.5, 0.52])
    assert MicrostructureAnalyzer.realized_volatility(pts) == 0.0
    assert MicrostructureAnalyzer.realized_volatility([]) == 0.0


def test_realized_volatility_stable_price():
    pts = _points([0.5, 0.5, 0.5, 0.5, 0.5])
    assert MicrostructureAnalyzer.realized_volatility(pts) == pytest.approx(0.0, abs=1e-9)


def test_realized_volatility_volatile_price():
    pts = _points([0.40, 0.50, 0.45, 0.55, 0.48])
    vol = MicrostructureAnalyzer.realized_volatility(pts)
    assert vol > 0.05


def test_price_velocity_positive():
    pts = _points([0.40, 0.45, 0.50], start_minutes_ago=30)
    v = MicrostructureAnalyzer.price_velocity(pts, window_minutes=30)
    # (0.50 - 0.40) / 30 ≈ 0.00333 per minute
    assert v == pytest.approx(0.10 / 30, rel=1e-3)


def test_price_velocity_negative():
    pts = _points([0.60, 0.55, 0.50], start_minutes_ago=30)
    v = MicrostructureAnalyzer.price_velocity(pts, window_minutes=30)
    assert v < 0
    assert v == pytest.approx(-0.10 / 30, rel=1e-3)


# ── Engine integration ───────────────────────────────────────────────


async def test_edge_dynamic_zero_vol_equals_static(engine: ValueAssessmentEngine):
    """Backward compat: no price history → edge_dynamic == fee_adjusted_edge."""
    market = _make_market(yes_price=0.40)
    result = await engine.assess(market, rule_analysis_score=0.8)
    assert result.edge_dynamic is not None
    assert result.fee_adjusted_edge == pytest.approx(result.edge_dynamic, abs=1e-6)
    assert result.realized_volatility == pytest.approx(0.0)
    assert result.price_velocity == pytest.approx(0.0)


async def test_edge_dynamic_preserves_sign(engine: ValueAssessmentEngine):
    """edge_central<0 → edge_dynamic<0 even with adverse velocity (bug fix)."""
    market = _make_market(yes_price=0.80)
    # rule_analysis_score=0.1 → fair value ≈ 0.1 → edge ≈ -0.70 → capped by fair_value math,
    # but even with mild negative edge we verify sign preservation.
    history = PriceHistory(
        market_id="m1",
        token_id="t1",
        points=_points([0.70, 0.75, 0.80], start_minutes_ago=30),
    )
    result = await engine.assess(
        market, price_history=history, rule_analysis_score=0.3
    )
    assert result.edge_dynamic is not None
    assert result.fee_adjusted_edge < 0
    assert result.edge_dynamic <= 0
    assert abs(result.edge_dynamic) <= abs(result.fee_adjusted_edge) + 1e-9


async def test_edge_lower_gates_recommendation(engine: ValueAssessmentEngine):
    """High realized vol swallows edge → HOLD."""
    market = _make_market(yes_price=0.46, end_days=7)  # MEDIUM horizon
    noisy_prices = [0.30, 0.60, 0.35, 0.58, 0.40, 0.55, 0.46]
    history = PriceHistory(
        market_id="m1",
        token_id="t1",
        points=_points(noisy_prices, start_minutes_ago=60),
    )
    result = await engine.assess(
        market, price_history=history, rule_analysis_score=0.5
    )
    # With highly volatile price, |edge_central|=~0.04 is overwhelmed by k*vol
    assert result.recommendation == Recommendation.HOLD


async def test_edge_strength_bypasses_velocity_penalty(engine: ValueAssessmentEngine):
    """|edge_central| >= strong_edge_threshold bypasses velocity penalty."""
    market = _make_market(yes_price=0.20, end_days=7)
    # rising price against BUY would normally trigger penalty; strong edge must bypass it.
    history = PriceHistory(
        market_id="m1",
        token_id="t1",
        points=_points([0.18, 0.19, 0.20], start_minutes_ago=30),
    )
    result = await engine.assess(
        market, price_history=history, rule_analysis_score=0.95
    )
    assert result.edge_dynamic is not None
    # With strong positive edge, dampener drives penalty→1.0; edge_dynamic ≈ |edge_central|
    # after magnitude gating (which is small since realized_vol is tiny).
    assert result.edge_dynamic > 0
    # sign same as fee_adjusted_edge, magnitude close to fee_adjusted_edge
    assert abs(result.edge_dynamic - result.fee_adjusted_edge) < 0.01


async def test_valuation_result_backward_compat_no_history(engine: ValueAssessmentEngine):
    """No price_history → edge_dynamic still populated and equals fee_adjusted_edge."""
    market = _make_market(yes_price=0.60)
    result = await engine.assess(market, rule_analysis_score=0.7)
    assert result.edge_dynamic is not None
    assert result.edge_lower is not None
    assert result.edge_upper is not None
    assert result.edge_lower == pytest.approx(result.fee_adjusted_edge)
    assert result.edge_upper == pytest.approx(result.fee_adjusted_edge)
    assert result.edge_dynamic == pytest.approx(result.fee_adjusted_edge, abs=1e-6)
