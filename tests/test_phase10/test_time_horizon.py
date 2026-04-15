"""Tests for Phase 10: TimeHorizon classification."""

from datetime import UTC, datetime, timedelta

from app.models.market import (
    Market,
    MarketCategory,
    MarketStatus,
    Outcome,
    TimeHorizon,
)
from app.valuation.temporal import classify_horizon


# ── classify_horizon ─────────────────────────────────────────────────


def test_classify_horizon_short() -> None:
    """< 3 days → SHORT."""
    end = datetime.now(tz=UTC) + timedelta(hours=12)
    assert classify_horizon(end) == TimeHorizon.SHORT


def test_classify_horizon_medium() -> None:
    """3-14 days → MEDIUM."""
    end = datetime.now(tz=UTC) + timedelta(days=7)
    assert classify_horizon(end) == TimeHorizon.MEDIUM


def test_classify_horizon_long() -> None:
    """14-30 days → LONG."""
    end = datetime.now(tz=UTC) + timedelta(days=20)
    assert classify_horizon(end) == TimeHorizon.LONG


def test_classify_horizon_super_long() -> None:
    """> 30 days → SUPER_LONG."""
    end = datetime.now(tz=UTC) + timedelta(days=60)
    assert classify_horizon(end) == TimeHorizon.SUPER_LONG


def test_classify_horizon_none_is_super_long() -> None:
    """No end_date → SUPER_LONG (maximum uncertainty)."""
    assert classify_horizon(None) == TimeHorizon.SUPER_LONG


def test_classify_horizon_boundary_3_days() -> None:
    """Exactly at 3 days → MEDIUM (>= 3 days)."""
    end = datetime.now(tz=UTC) + timedelta(days=3, seconds=1)
    assert classify_horizon(end) == TimeHorizon.MEDIUM


def test_classify_horizon_boundary_14_days() -> None:
    """Exactly at 14 days → LONG (>= 14 days)."""
    end = datetime.now(tz=UTC) + timedelta(days=14, seconds=1)
    assert classify_horizon(end) == TimeHorizon.LONG


def test_classify_horizon_boundary_30_days() -> None:
    """Exactly at 30 days → SUPER_LONG (>= 30 days)."""
    end = datetime.now(tz=UTC) + timedelta(days=30, seconds=1)
    assert classify_horizon(end) == TimeHorizon.SUPER_LONG


# ── Market.time_horizon computed field ───────────────────────────────


def _make_market(end_date: datetime | None = None) -> Market:
    return Market(
        id="m1",
        question="Test?",
        category=MarketCategory.POLITICS,
        status=MarketStatus.ACTIVE,
        outcomes=[Outcome(token_id="t1", outcome="Yes", price=0.5)],
        end_date=end_date,
    )


def test_market_time_horizon_short() -> None:
    m = _make_market(end_date=datetime.now(tz=UTC) + timedelta(hours=6))
    assert m.time_horizon == TimeHorizon.SHORT


def test_market_time_horizon_medium() -> None:
    m = _make_market(end_date=datetime.now(tz=UTC) + timedelta(days=5))
    assert m.time_horizon == TimeHorizon.MEDIUM


def test_market_time_horizon_long() -> None:
    m = _make_market(end_date=datetime.now(tz=UTC) + timedelta(days=20))
    assert m.time_horizon == TimeHorizon.LONG


def test_market_time_horizon_super_long() -> None:
    m = _make_market(end_date=datetime.now(tz=UTC) + timedelta(days=60))
    assert m.time_horizon == TimeHorizon.SUPER_LONG


def test_market_time_horizon_none() -> None:
    m = _make_market(end_date=None)
    assert m.time_horizon == TimeHorizon.SUPER_LONG
