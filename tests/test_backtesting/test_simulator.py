"""Tests for app.backtesting.simulator."""

from app.backtesting.simulator import FillSimulator

# ---------------------------------------------------------------------------
# simulate_entry
# ---------------------------------------------------------------------------


def test_simulate_entry_buy_adds_slippage() -> None:
    """BUY entry price must be price + slippage."""
    sim = FillSimulator(slippage_pct=0.01)
    fill = sim.simulate_entry(
        market_id="m1", strategy="s", side="BUY", price=0.50, size_eur=10.0
    )
    expected_entry = round(0.50 + 0.50 * 0.01, 4)
    assert fill.entry_price == expected_entry
    assert fill.is_open is True


def test_simulate_entry_sell_subtracts_slippage() -> None:
    """SELL entry price must be price - slippage."""
    sim = FillSimulator(slippage_pct=0.01)
    fill = sim.simulate_entry(
        market_id="m1", strategy="s", side="SELL", price=0.60, size_eur=10.0
    )
    expected_entry = round(0.60 - 0.60 * 0.01, 4)
    assert fill.entry_price == expected_entry


def test_simulate_entry_fee_geopolitics_zero() -> None:
    """geopolitics category must have 0% fee."""
    sim = FillSimulator()
    fill = sim.simulate_entry(
        market_id="m1",
        strategy="s",
        side="BUY",
        price=0.50,
        size_eur=100.0,
        category="geopolitics",
    )
    assert fill.fee_paid == 0.0


def test_simulate_entry_fee_crypto() -> None:
    """crypto category must apply 7.2% fee."""
    sim = FillSimulator()
    fill = sim.simulate_entry(
        market_id="m1",
        strategy="s",
        side="BUY",
        price=0.50,
        size_eur=100.0,
        category="crypto",
    )
    assert fill.fee_paid == round(100.0 * 0.072, 4)


def test_simulate_entry_fee_default_unknown_category() -> None:
    """Unknown category must fall back to DEFAULT_FEE (2%)."""
    sim = FillSimulator()
    fill = sim.simulate_entry(
        market_id="m1",
        strategy="s",
        side="BUY",
        price=0.50,
        size_eur=100.0,
        category="unknown_cat",
    )
    assert fill.fee_paid == round(100.0 * FillSimulator.DEFAULT_FEE, 4)


def test_simulate_entry_custom_slippage_pct() -> None:
    """Custom slippage_pct must be applied at construction time."""
    sim = FillSimulator(slippage_pct=0.02)
    fill = sim.simulate_entry(
        market_id="m1", strategy="s", side="BUY", price=0.40, size_eur=5.0
    )
    expected_slip = round(0.40 * 0.02, 4)
    assert fill.slippage == expected_slip


# ---------------------------------------------------------------------------
# simulate_exit
# ---------------------------------------------------------------------------


def test_simulate_exit_buy_positive_pnl() -> None:
    """BUY position with exit > entry must yield positive P&L."""
    sim = FillSimulator(slippage_pct=0.0)
    fill = sim.simulate_entry(
        market_id="m1", strategy="s", side="BUY", price=0.50, size_eur=10.0, category="geopolitics"
    )
    fill = sim.simulate_exit(fill, exit_price=0.70)
    shares = 10.0 / 0.50
    expected_pnl = round((0.70 - 0.50) * shares, 4)
    assert fill.pnl == expected_pnl
    assert fill.pnl > 0


def test_simulate_exit_sell_positive_pnl() -> None:
    """SELL position where exit < entry must yield positive P&L."""
    sim = FillSimulator(slippage_pct=0.0)
    fill = sim.simulate_entry(
        market_id="m1", strategy="s", side="SELL", price=0.60, size_eur=10.0, category="geopolitics"
    )
    fill = sim.simulate_exit(fill, exit_price=0.40)
    shares = 10.0 / 0.60
    expected_pnl = round((0.60 - 0.40) * shares, 4)
    assert fill.pnl == expected_pnl
    assert fill.pnl > 0


def test_simulate_exit_sets_is_open_false() -> None:
    """After exit, fill.is_open must be False."""
    sim = FillSimulator()
    fill = sim.simulate_entry(
        market_id="m1", strategy="s", side="BUY", price=0.50, size_eur=10.0
    )
    assert fill.is_open is True
    fill = sim.simulate_exit(fill, exit_price=0.50)
    assert fill.is_open is False
