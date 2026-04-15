"""Tests for Phase 10: per-horizon edge thresholds in VAE."""

from datetime import UTC, datetime, timedelta

import pytest

from app.models.market import (
    Market,
    MarketCategory,
    MarketStatus,
    Outcome,
    TimeHorizon,
)
from app.models.valuation import Recommendation
from app.valuation.db import ResolutionDB
from app.valuation.engine import ValueAssessmentEngine


@pytest.fixture
async def db():
    database = ResolutionDB(db_path=":memory:")
    await database.init()
    yield database
    await database.close()


@pytest.fixture
def engine(db: ResolutionDB) -> ValueAssessmentEngine:
    return ValueAssessmentEngine(db)


def _make_market(
    end_date: datetime | None = None,
    yes_price: float = 0.5,
    fee_rate: float = 0.0,
) -> Market:
    if end_date is None:
        end_date = datetime.now(tz=UTC) + timedelta(days=60)
    return Market(
        id="m1",
        question="Test?",
        category=MarketCategory.POLITICS,
        status=MarketStatus.ACTIVE,
        outcomes=[
            Outcome(token_id="t1", outcome="Yes", price=yes_price),
            Outcome(token_id="t2", outcome="No", price=round(1.0 - yes_price, 4)),
        ],
        end_date=end_date,
        volume=10000.0,
        liquidity=5000.0,
        fee_rate=fee_rate,
    )


# ── _recommend with horizons ────────────────────────────────────────


def test_short_horizon_accepts_low_edge(engine: ValueAssessmentEngine) -> None:
    """SHORT horizon: 3% edge → BUY (min_edge_short=0.03)."""
    rec = engine._recommend(0.035, confidence=0.8, time_horizon=TimeHorizon.SHORT)
    assert rec == Recommendation.BUY


def test_short_horizon_rejects_very_low_edge(engine: ValueAssessmentEngine) -> None:
    """SHORT horizon: 2% edge → HOLD (below 3% threshold)."""
    rec = engine._recommend(0.02, confidence=0.8, time_horizon=TimeHorizon.SHORT)
    assert rec == Recommendation.HOLD


def test_medium_horizon_needs_5pct(engine: ValueAssessmentEngine) -> None:
    """MEDIUM horizon: 3% edge → HOLD, 5% → BUY."""
    rec_low = engine._recommend(0.035, confidence=0.8, time_horizon=TimeHorizon.MEDIUM)
    rec_ok = engine._recommend(0.06, confidence=0.8, time_horizon=TimeHorizon.MEDIUM)
    assert rec_low == Recommendation.HOLD
    assert rec_ok == Recommendation.BUY


def test_long_horizon_needs_10pct(engine: ValueAssessmentEngine) -> None:
    """LONG horizon: 5% edge → HOLD, 10% → BUY."""
    rec_low = engine._recommend(0.06, confidence=0.8, time_horizon=TimeHorizon.LONG)
    rec_ok = engine._recommend(0.11, confidence=0.8, time_horizon=TimeHorizon.LONG)
    assert rec_low == Recommendation.HOLD
    assert rec_ok == Recommendation.BUY


def test_no_horizon_uses_default(engine: ValueAssessmentEngine) -> None:
    """No horizon → default min_edge (0.05)."""
    rec_low = engine._recommend(0.04, confidence=0.8, time_horizon=None)
    rec_ok = engine._recommend(0.06, confidence=0.8, time_horizon=None)
    assert rec_low == Recommendation.HOLD
    assert rec_ok == Recommendation.BUY


def test_strong_edge_ignores_horizon(engine: ValueAssessmentEngine) -> None:
    """strong_edge threshold (0.15) is the same regardless of horizon."""
    rec = engine._recommend(0.16, confidence=0.8, time_horizon=TimeHorizon.LONG)
    assert rec == Recommendation.STRONG_BUY


def test_sell_thresholds_also_horizon_aware(engine: ValueAssessmentEngine) -> None:
    """Negative edge uses the same per-horizon threshold for SELL."""
    # SHORT: -3% → SELL
    rec = engine._recommend(-0.035, confidence=0.8, time_horizon=TimeHorizon.SHORT)
    assert rec == Recommendation.SELL

    # LONG: -3% → HOLD (needs -10%)
    rec_long = engine._recommend(-0.035, confidence=0.8, time_horizon=TimeHorizon.LONG)
    assert rec_long == Recommendation.HOLD


# ── Full assess() integration with horizon ───────────────────────────


@pytest.mark.asyncio
async def test_assess_uses_market_time_horizon(engine: ValueAssessmentEngine) -> None:
    """assess() passes market's time_horizon to _recommend."""
    # Short-horizon market (1 day)
    market = _make_market(
        end_date=datetime.now(tz=UTC) + timedelta(days=1),
        yes_price=0.5,
    )
    assert market.time_horizon == TimeHorizon.SHORT

    # Long-horizon market (20 days)
    market_long = _make_market(
        end_date=datetime.now(tz=UTC) + timedelta(days=20),
        yes_price=0.5,
    )
    assert market_long.time_horizon == TimeHorizon.LONG

    # Super-long market (60 days)
    market_super = _make_market(
        end_date=datetime.now(tz=UTC) + timedelta(days=60),
        yes_price=0.5,
    )
    assert market_super.time_horizon == TimeHorizon.SUPER_LONG
