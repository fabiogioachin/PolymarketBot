"""Tests for Phase 10: horizon budget pools in RiskManager."""

import pytest

from app.models.market import TimeHorizon
from app.models.signal import Signal, SignalType
from app.risk.manager import RiskManager


def _signal(token_id: str = "tok-1", market_id: str = "m1") -> Signal:
    return Signal(
        strategy="test",
        market_id=market_id,
        token_id=token_id,
        signal_type=SignalType.BUY,
        confidence=0.8,
        market_price=0.5,
        edge_amount=0.05,
    )


@pytest.fixture
def mgr() -> RiskManager:
    """150 EUR capital, 50% exposure (75 EUR max).

    Horizon pools: 60% short (45 EUR), 30% medium (22.50 EUR), 10% long (7.50 EUR).
    """
    return RiskManager(
        capital=150.0,
        max_exposure_pct=50.0,
        max_single_position_eur=25.0,
        daily_loss_limit_eur=20.0,
        max_positions=25,
        horizon_allocation={"short_pct": 60.0, "medium_pct": 30.0, "long_pct": 10.0},
    )


# ── Horizon pool enforcement ────────────────────────────────────────


def test_short_pool_accepts_within_limit(mgr: RiskManager) -> None:
    """Trade within short pool limit is accepted."""
    result = mgr.check_order(_signal(), price=0.5, size_eur=10.0, time_horizon=TimeHorizon.SHORT)
    assert result.approved is True


def test_short_pool_rejects_when_full(mgr: RiskManager) -> None:
    """Short pool: 45 EUR. Fill 40, try to add 10 → reject."""
    mgr.record_fill("tok-a", 20.0, time_horizon=TimeHorizon.SHORT)
    mgr.record_fill("tok-b", 20.0, time_horizon=TimeHorizon.SHORT)
    result = mgr.check_order(
        _signal(token_id="tok-c"), price=0.5, size_eur=10.0, time_horizon=TimeHorizon.SHORT
    )
    assert result.approved is False
    assert "short" in result.reason.lower()


def test_medium_pool_rejects_when_full(mgr: RiskManager) -> None:
    """Medium pool: 22.50 EUR. Fill 20, try to add 5 → reject."""
    mgr.record_fill("tok-a", 20.0, time_horizon=TimeHorizon.MEDIUM)
    result = mgr.check_order(
        _signal(token_id="tok-b"), price=0.5, size_eur=5.0, time_horizon=TimeHorizon.MEDIUM
    )
    assert result.approved is False
    assert "medium" in result.reason.lower()


def test_long_pool_rejects_when_full(mgr: RiskManager) -> None:
    """Long pool: 7.50 EUR. Fill 7, try to add 2 → reject."""
    mgr.record_fill("tok-a", 7.0, time_horizon=TimeHorizon.LONG)
    result = mgr.check_order(
        _signal(token_id="tok-b"), price=0.5, size_eur=2.0, time_horizon=TimeHorizon.LONG
    )
    assert result.approved is False
    assert "long" in result.reason.lower()


def test_short_pool_full_does_not_block_medium(mgr: RiskManager) -> None:
    """Different pools are independent: short full, medium still open."""
    mgr.record_fill("tok-s1", 20.0, time_horizon=TimeHorizon.SHORT)
    mgr.record_fill("tok-s2", 20.0, time_horizon=TimeHorizon.SHORT)
    # Short pool has 40/45, medium is empty
    result = mgr.check_order(
        _signal(token_id="tok-m1"), price=0.5, size_eur=10.0, time_horizon=TimeHorizon.MEDIUM
    )
    assert result.approved is True


def test_close_frees_horizon_pool(mgr: RiskManager) -> None:
    """Closing a position frees up its horizon pool."""
    mgr.record_fill("tok-a", 40.0, time_horizon=TimeHorizon.SHORT)
    # Pool is 40/45, adding 10 would bust
    result = mgr.check_order(
        _signal(token_id="tok-b"), price=0.5, size_eur=10.0, time_horizon=TimeHorizon.SHORT
    )
    assert result.approved is False

    # Close the position → pool freed
    mgr.record_close("tok-a", pnl=2.0)
    result2 = mgr.check_order(
        _signal(token_id="tok-b"), price=0.5, size_eur=10.0, time_horizon=TimeHorizon.SHORT
    )
    assert result2.approved is True


# ── Near-resolution discount ────────────────────────────────────────


def test_near_resolution_discount_frees_exposure(mgr: RiskManager) -> None:
    """Near-resolution positions count at 50%, freeing effective exposure."""
    # Fill 70 EUR raw → effective would normally be 70, max is 75
    mgr.record_fill("tok-1", 40.0, time_horizon=TimeHorizon.SHORT)
    mgr.record_fill("tok-2", 30.0, time_horizon=TimeHorizon.MEDIUM)

    # Without discount: 70 + 10 = 80 > 75 → reject
    result = mgr.check_order(
        _signal(token_id="tok-3"), price=0.5, size_eur=10.0, time_horizon=TimeHorizon.SHORT
    )
    assert result.approved is False

    # Mark tok-1 as near-resolution → effective becomes 20 + 30 = 50
    mgr.mark_near_resolution("tok-1", True)
    result2 = mgr.check_order(
        _signal(token_id="tok-3"), price=0.5, size_eur=10.0, time_horizon=TimeHorizon.SHORT
    )
    assert result2.approved is True


def test_near_resolution_discount_applies_to_horizon_pool(mgr: RiskManager) -> None:
    """Near-resolution discount also applies within horizon pool calculation."""
    # Short pool limit: 45 EUR
    mgr.record_fill("tok-a", 40.0, time_horizon=TimeHorizon.SHORT)
    # Pool: 40/45, want to add 10 → 50 > 45 → reject
    result = mgr.check_order(
        _signal(token_id="tok-b"), price=0.5, size_eur=10.0, time_horizon=TimeHorizon.SHORT
    )
    assert result.approved is False

    # Mark as near-resolution → effective pool = 20, add 10 = 30 < 45 → approve
    mgr.mark_near_resolution("tok-a", True)
    result2 = mgr.check_order(
        _signal(token_id="tok-b"), price=0.5, size_eur=10.0, time_horizon=TimeHorizon.SHORT
    )
    assert result2.approved is True


# ── Backward compatibility ──────────────────────────────────────────


def test_backward_compat_no_horizon_config() -> None:
    """Without horizon_allocation, defaults work (60/30/10)."""
    mgr = RiskManager(
        capital=150.0,
        max_exposure_pct=50.0,
        max_single_position_eur=25.0,
        daily_loss_limit_eur=20.0,
        max_positions=10,
    )
    # No horizon_allocation passed → should still work
    result = mgr.check_order(_signal(), price=0.5, size_eur=10.0)
    assert result.approved is True


def test_backward_compat_no_horizon_in_check_order() -> None:
    """check_order without time_horizon skips pool check (backward compat)."""
    mgr = RiskManager(
        capital=150.0,
        max_exposure_pct=50.0,
        max_single_position_eur=25.0,
        daily_loss_limit_eur=20.0,
        max_positions=10,
        horizon_allocation={"short_pct": 60.0, "medium_pct": 30.0, "long_pct": 10.0},
    )
    # Even with allocation configured, no horizon → no pool check → approve
    result = mgr.check_order(_signal(), price=0.5, size_eur=10.0)
    assert result.approved is True
