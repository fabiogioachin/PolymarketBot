"""Tests for app.risk.manager."""

import pytest

from app.models.signal import Signal, SignalType
from app.risk.manager import RiskManager
from app.risk.position_sizer import SizeResult

# ── helpers ───────────────────────────────────────────────────────────


def make_signal(
    signal_type: SignalType = SignalType.BUY,
    confidence: float = 0.8,
    token_id: str = "token-abc",
    market_id: str = "market-1",
) -> Signal:
    return Signal(
        strategy="test_strategy",
        market_id=market_id,
        token_id=token_id,
        signal_type=signal_type,
        confidence=confidence,
    )


@pytest.fixture
def manager() -> RiskManager:
    return RiskManager(
        capital=150.0,
        max_exposure_pct=50.0,
        max_single_position_eur=25.0,
        daily_loss_limit_eur=20.0,
        max_positions=10,
    )


# ── check_order ───────────────────────────────────────────────────────


def test_check_order_approve_valid(manager: RiskManager) -> None:
    """Valid BUY order within all limits is approved."""
    signal = make_signal(signal_type=SignalType.BUY)
    result = manager.check_order(signal, price=0.5, size_eur=10.0)
    assert result.approved is True
    assert result.reason == ""


def test_check_order_reject_hold_signal(manager: RiskManager) -> None:
    """HOLD signal is always rejected."""
    signal = make_signal(signal_type=SignalType.HOLD)
    result = manager.check_order(signal, price=0.5, size_eur=10.0)
    assert result.approved is False
    assert "HOLD" in result.reason


def test_check_order_reject_daily_loss_limit_reached(manager: RiskManager) -> None:
    """Order rejected when daily loss limit is at or beyond the threshold."""
    manager.record_close("token-xyz", pnl=-20.0)  # exactly at limit
    signal = make_signal()
    result = manager.check_order(signal, price=0.5, size_eur=5.0)
    assert result.approved is False
    assert "Daily loss limit" in result.reason


def test_check_order_reject_exceeds_max_single_position(manager: RiskManager) -> None:
    """Order rejected when size_eur > max_single_position_eur."""
    signal = make_signal()
    result = manager.check_order(signal, price=0.5, size_eur=30.0)
    assert result.approved is False
    assert "max single position" in result.reason


def test_check_order_reject_exceeds_max_exposure(manager: RiskManager) -> None:
    """Order rejected when it would push total exposure past the limit."""
    # capital=150, max_exposure=50% → 75 EUR ceiling
    # fill 70 EUR already, then try to add 10 more → 80 > 75 → reject
    manager.record_fill("token-1", 25.0)
    manager.record_fill("token-2", 25.0)
    manager.record_fill("token-3", 20.0)  # total = 70
    signal = make_signal(token_id="token-new")
    result = manager.check_order(signal, price=0.5, size_eur=10.0)
    assert result.approved is False
    assert "max exposure" in result.reason


def test_check_order_reject_max_positions_reached(manager: RiskManager) -> None:
    """Order rejected when all position slots are occupied."""
    mgr = RiskManager(
        capital=500.0,
        max_exposure_pct=50.0,
        max_single_position_eur=25.0,
        daily_loss_limit_eur=20.0,
        max_positions=2,
    )
    mgr.record_fill("token-1", 5.0)
    mgr.record_fill("token-2", 5.0)
    signal = make_signal(token_id="token-3")
    result = mgr.check_order(signal, price=0.5, size_eur=5.0)
    assert result.approved is False
    assert "Max positions" in result.reason


def test_check_order_warning_approaching_max_exposure(manager: RiskManager) -> None:
    """Warning issued when order would push exposure above 80% of the limit."""
    # capital=150, max_exposure=75 EUR, 80% = 60 EUR
    # fill 55 EUR, add 10 → 65 > 60 → warning but still approved
    manager.record_fill("token-1", 25.0)
    manager.record_fill("token-2", 25.0)
    manager.record_fill("token-3", 5.0)  # total = 55
    signal = make_signal(token_id="token-new")
    result = manager.check_order(signal, price=0.5, size_eur=10.0)
    assert result.approved is True
    assert any("Approaching max exposure" in w for w in result.warnings)


def test_check_order_sell_signal_approved(manager: RiskManager) -> None:
    """SELL signal (not HOLD) is also a valid trade direction."""
    signal = make_signal(signal_type=SignalType.SELL)
    result = manager.check_order(signal, price=0.5, size_eur=10.0)
    assert result.approved is True


# ── size_position ──────────────────────────────────────────────────────


def test_size_position_returns_size_result(manager: RiskManager) -> None:
    """size_position returns a SizeResult with positive size for valid signal."""
    signal = make_signal(confidence=0.8)
    result = manager.size_position(signal, capital=150.0, price=0.5)
    assert isinstance(result, SizeResult)
    assert result.size_eur > 0.0
    assert result.method == "confidence_scaled"


# ── record_fill ───────────────────────────────────────────────────────


def test_record_fill_updates_exposure(manager: RiskManager) -> None:
    """record_fill increases current_exposure."""
    assert manager.current_exposure == 0.0
    manager.record_fill("token-1", 10.0)
    assert manager.current_exposure == 10.0
    manager.record_fill("token-1", 5.0)  # adding to same token
    assert manager.current_exposure == 15.0


def test_record_fill_updates_position_count(manager: RiskManager) -> None:
    """Each unique token_id increments position_count."""
    manager.record_fill("token-a", 10.0)
    manager.record_fill("token-b", 10.0)
    assert manager.position_count == 2


# ── record_close ──────────────────────────────────────────────────────


def test_record_close_removes_position_updates_pnl(manager: RiskManager) -> None:
    """record_close removes position and updates daily_pnl."""
    manager.record_fill("token-1", 10.0)
    assert manager.position_count == 1
    manager.record_close("token-1", pnl=-3.0)
    assert manager.position_count == 0
    assert manager.daily_pnl == pytest.approx(-3.0)


def test_record_close_unknown_token_no_error(manager: RiskManager) -> None:
    """Closing a token that was never opened does not raise."""
    manager.record_close("ghost-token", pnl=0.0)  # should not raise
    assert manager.daily_pnl == 0.0


# ── reset_daily ───────────────────────────────────────────────────────


def test_reset_daily_clears_pnl(manager: RiskManager) -> None:
    """reset_daily sets daily_pnl back to 0."""
    manager.record_close("token-1", pnl=-15.0)
    assert manager.daily_pnl == pytest.approx(-15.0)
    manager.reset_daily()
    assert manager.daily_pnl == 0.0


# ── integration ───────────────────────────────────────────────────────


def test_integration_fill_multiple_positions_exposure_limit(manager: RiskManager) -> None:
    """Integration: filling positions triggers exposure limit on further orders."""
    # max exposure = 150 * 50% = 75 EUR
    tokens = [f"token-{i}" for i in range(4)]
    for t in tokens:
        manager.record_fill(t, 18.0)  # 4 * 18 = 72 EUR

    # Next order of 10 EUR would reach 82 > 75 → reject
    signal = make_signal(token_id="token-final")
    result = manager.check_order(signal, price=0.5, size_eur=10.0)
    assert result.approved is False
    assert "max exposure" in result.reason

    # But a tiny order of 2 EUR fits (72 + 2 = 74 ≤ 75) → approve
    result_small = manager.check_order(signal, price=0.5, size_eur=2.0)
    assert result_small.approved is True
