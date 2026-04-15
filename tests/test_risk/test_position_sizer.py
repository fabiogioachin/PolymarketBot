"""Tests for app.risk.position_sizer — edge-scaled half-Kelly sizing."""

import pytest

from app.risk.position_sizer import PositionSizer


@pytest.fixture
def sizer() -> PositionSizer:
    return PositionSizer(fixed_fraction_pct=5.0, max_single_eur=25.0, min_size_eur=1.0)


# ── from_signal (primary method: half-Kelly) ─────────────────────────


def test_from_signal_scales_with_edge(sizer: PositionSizer) -> None:
    """Higher edge → larger position size."""
    small_edge = sizer.from_signal(capital=200.0, price=0.5, confidence=0.8, edge=0.03)
    large_edge = sizer.from_signal(capital=200.0, price=0.5, confidence=0.8, edge=0.15)
    assert large_edge.size_eur > small_edge.size_eur
    assert large_edge.method == "half_kelly"


def test_from_signal_scales_with_confidence(sizer: PositionSizer) -> None:
    """Higher confidence → larger position size (same edge)."""
    low_conf = sizer.from_signal(capital=200.0, price=0.5, confidence=0.3, edge=0.10)
    high_conf = sizer.from_signal(capital=200.0, price=0.5, confidence=0.9, edge=0.10)
    assert high_conf.size_eur > low_conf.size_eur


def test_from_signal_zero_edge_returns_minimum(sizer: PositionSizer) -> None:
    """Zero edge → minimum size (don't bet on nothing)."""
    result = sizer.from_signal(capital=200.0, price=0.5, confidence=0.8, edge=0.0)
    assert result.size_eur == 1.0
    assert result.method == "minimum"


def test_from_signal_negative_edge_returns_minimum(sizer: PositionSizer) -> None:
    """Negative edge → minimum size."""
    result = sizer.from_signal(capital=200.0, price=0.5, confidence=0.8, edge=-0.05)
    assert result.size_eur == 1.0
    assert result.method == "minimum"


def test_from_signal_capped_at_max_single(sizer: PositionSizer) -> None:
    """Very large edge + capital is capped at max_single_eur."""
    result = sizer.from_signal(capital=10000.0, price=0.5, confidence=1.0, edge=0.20)
    assert result.size_eur == 25.0
    assert result.capped is True


def test_from_signal_capped_at_max_fraction(sizer: PositionSizer) -> None:
    """Even huge Kelly fraction is capped at fixed_fraction_pct of capital."""
    # edge=0.40 on price=0.5 → Kelly would be massive (0.80)
    # But max_fraction=5% of 200=10 EUR, then capped at 25 → should be 10
    result = sizer.from_signal(capital=200.0, price=0.5, confidence=1.0, edge=0.40)
    assert result.size_eur == 10.0
    assert result.method == "half_kelly"


def test_from_signal_shares_equals_size_over_price(sizer: PositionSizer) -> None:
    """size_shares = size_eur / price."""
    result = sizer.from_signal(capital=200.0, price=0.25, confidence=0.8, edge=0.10)
    assert result.size_shares == pytest.approx(result.size_eur / 0.25, rel=1e-4)


def test_from_signal_concrete_half_kelly(sizer: PositionSizer) -> None:
    """Verify actual half-Kelly math: edge=0.10, price=0.50, confidence=0.80.

    kelly = 0.10 / (1 - 0.50) = 0.20
    half_kelly = 0.10
    with confidence=0.80: fraction = 0.10 * 0.80 = 0.08
    capped at max_fraction=0.05 → fraction=0.05
    size = 200 * 0.05 = 10.0
    """
    result = sizer.from_signal(capital=200.0, price=0.50, confidence=0.80, edge=0.10)
    assert result.size_eur == 10.0


def test_from_signal_small_edge_small_size() -> None:
    """3% edge, price=0.50, confidence=0.70, capital=150.

    kelly = 0.03 / 0.50 = 0.06
    half_kelly = 0.03
    with confidence=0.70: fraction = 0.03 * 0.70 = 0.021
    size = 150 * 0.021 = 3.15
    """
    sizer = PositionSizer(fixed_fraction_pct=5.0, max_single_eur=25.0, min_size_eur=1.0)
    result = sizer.from_signal(capital=150.0, price=0.50, confidence=0.70, edge=0.03)
    assert result.size_eur == pytest.approx(3.15, rel=0.01)


def test_from_signal_price_near_one_returns_minimum(sizer: PositionSizer) -> None:
    """price >= 1.0 → no valid odds, return minimum."""
    result = sizer.from_signal(capital=200.0, price=1.0, confidence=0.8, edge=0.05)
    assert result.size_eur == 1.0
    assert result.method == "minimum"


# ── kelly_criterion (classic method) ─────────────────────────────────


def test_kelly_positive(sizer: PositionSizer) -> None:
    """Positive Kelly returns a non-zero size using half-Kelly."""
    result = sizer.kelly_criterion(
        capital=200.0, price=0.5, win_prob=0.6, win_payout=1.0, loss_amount=1.0,
    )
    assert result.size_eur == 20.0
    assert result.method == "kelly"


def test_kelly_negative_returns_zero(sizer: PositionSizer) -> None:
    """Negative Kelly (unfavorable bet) returns zero size."""
    result = sizer.kelly_criterion(
        capital=200.0, price=0.5, win_prob=0.3, win_payout=1.0, loss_amount=1.0,
    )
    assert result.size_eur == 0.0


def test_kelly_capped_at_max_single(sizer: PositionSizer) -> None:
    """Kelly result is capped at max_single_eur."""
    result = sizer.kelly_criterion(
        capital=200.0, price=0.5, win_prob=0.9, win_payout=1.0, loss_amount=1.0,
    )
    assert result.size_eur == 25.0
    assert result.capped is True


# ── _apply_caps ──────────────────────────────────────────────────────


def test_apply_caps_zero_price_returns_zero_shares(sizer: PositionSizer) -> None:
    """price=0 → shares should be 0, size still >= min."""
    result = sizer.from_signal(capital=200.0, price=0.0, confidence=0.8, edge=0.05)
    assert result.size_shares == 0.0
    assert result.size_eur >= 1.0
