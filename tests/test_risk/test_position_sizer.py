"""Tests for app.risk.position_sizer."""

import pytest

from app.risk.position_sizer import PositionSizer


@pytest.fixture
def sizer() -> PositionSizer:
    return PositionSizer(fixed_fraction_pct=5.0, max_single_eur=25.0)


# ── fixed_fraction ────────────────────────────────────────────────────


def test_fixed_fraction_basic(sizer: PositionSizer) -> None:
    """5% of 200 EUR capital = 10 EUR."""
    result = sizer.fixed_fraction(capital=200.0, price=0.5)
    assert result.size_eur == 10.0
    assert result.method == "fixed_fraction"
    assert result.capped is False


def test_fixed_fraction_capped_at_max_single(sizer: PositionSizer) -> None:
    """With large capital, size is capped at max_single_eur (25 EUR)."""
    result = sizer.fixed_fraction(capital=1000.0, price=0.5)
    assert result.size_eur == 25.0
    assert result.capped is True
    assert "max_single_position" in result.cap_reason


def test_fixed_fraction_shares_calculation(sizer: PositionSizer) -> None:
    """Shares = size_eur / price."""
    result = sizer.fixed_fraction(capital=200.0, price=0.5)
    assert result.size_eur == 10.0
    assert result.size_shares == pytest.approx(20.0, rel=1e-4)


# ── kelly_criterion ───────────────────────────────────────────────────


def test_kelly_positive(sizer: PositionSizer) -> None:
    """Positive Kelly returns a non-zero size using half-Kelly."""
    # win_prob=0.6, win_payout=1.0 → b=1.0, f*=(0.6*1 - 0.4)/1=0.2, half=0.1
    result = sizer.kelly_criterion(
        capital=200.0,
        price=0.5,
        win_prob=0.6,
        win_payout=1.0,
        loss_amount=1.0,
    )
    # half_kelly = 0.1, raw_size = 200 * 0.1 = 20
    assert result.size_eur == 20.0
    assert result.method == "kelly"
    assert result.capped is False


def test_kelly_negative_returns_zero(sizer: PositionSizer) -> None:
    """Negative Kelly (unfavorable bet) returns zero size."""
    # win_prob=0.3, win_payout=1.0 → b=1.0, f*=(0.3-0.7)/1=-0.4
    result = sizer.kelly_criterion(
        capital=200.0,
        price=0.5,
        win_prob=0.3,
        win_payout=1.0,
        loss_amount=1.0,
    )
    assert result.size_eur == 0.0
    assert result.size_shares == 0.0
    assert result.method == "kelly"


def test_kelly_edge_case_win_prob_zero(sizer: PositionSizer) -> None:
    """win_prob=0 → invalid, return zero SizeResult."""
    result = sizer.kelly_criterion(capital=200.0, price=0.5, win_prob=0.0, win_payout=1.0)
    assert result.size_eur == 0.0
    assert result.method == "kelly"


def test_kelly_edge_case_win_prob_one(sizer: PositionSizer) -> None:
    """win_prob=1 → invalid (no uncertainty), return zero SizeResult."""
    result = sizer.kelly_criterion(capital=200.0, price=0.5, win_prob=1.0, win_payout=1.0)
    assert result.size_eur == 0.0
    assert result.method == "kelly"


def test_kelly_capped_at_max_single(sizer: PositionSizer) -> None:
    """Kelly result is capped when it would exceed max_single_eur."""
    # Very favorable bet: win_prob=0.9, win_payout=1.0 → f*=0.8, half=0.4
    # capital=200, raw=80 → capped at 25
    result = sizer.kelly_criterion(
        capital=200.0,
        price=0.5,
        win_prob=0.9,
        win_payout=1.0,
        loss_amount=1.0,
    )
    assert result.size_eur == 25.0
    assert result.capped is True


# ── from_signal ───────────────────────────────────────────────────────


def test_from_signal_low_confidence(sizer: PositionSizer) -> None:
    """confidence < 0.3 → 50% of fixed fraction allocation."""
    # 5% of 200 = 10, 50% of 10 = 5
    result = sizer.from_signal(capital=200.0, price=0.5, signal_confidence=0.1)
    assert result.size_eur == 5.0
    assert result.method == "confidence_scaled"


def test_from_signal_high_confidence(sizer: PositionSizer) -> None:
    """confidence > 0.7 → 100% of fixed fraction allocation."""
    # 5% of 200 = 10
    result = sizer.from_signal(capital=200.0, price=0.5, signal_confidence=0.9)
    assert result.size_eur == 10.0
    assert result.method == "confidence_scaled"


def test_from_signal_mid_confidence_interpolated(sizer: PositionSizer) -> None:
    """confidence=0.5 → linear interpolation between 0.5 and 1.0."""
    # fraction = 0.5 + (0.5 - 0.3) / 0.4 * 0.5 = 0.5 + 0.25 = 0.75
    # raw_size = 200 * 0.05 * 0.75 = 7.5
    result = sizer.from_signal(capital=200.0, price=0.5, signal_confidence=0.5)
    assert result.size_eur == pytest.approx(7.5, rel=1e-4)
    assert result.method == "confidence_scaled"


def test_from_signal_shares_equals_size_over_price(sizer: PositionSizer) -> None:
    """size_shares = size_eur / price."""
    result = sizer.from_signal(capital=200.0, price=0.25, signal_confidence=0.9)
    # size_eur=10, shares=10/0.25=40
    assert result.size_shares == pytest.approx(40.0, rel=1e-4)


# ── _apply_caps ───────────────────────────────────────────────────────


def test_apply_caps_sets_cap_reason_when_capped() -> None:
    """Capping sets capped=True and populates cap_reason."""
    sizer_tight = PositionSizer(fixed_fraction_pct=50.0, max_single_eur=5.0)
    result = sizer_tight.fixed_fraction(capital=100.0, price=0.5)
    assert result.capped is True
    assert result.cap_reason != ""
    assert result.size_eur == 5.0


def test_apply_caps_zero_price_returns_zero_shares(sizer: PositionSizer) -> None:
    """price=0 should not raise; shares should be 0."""
    result = sizer.fixed_fraction(capital=200.0, price=0.0)
    assert result.size_shares == 0.0
    assert result.size_eur > 0.0
