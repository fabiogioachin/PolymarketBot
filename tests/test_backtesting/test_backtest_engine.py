"""Tests for app.backtesting.engine."""

from datetime import datetime, timedelta

from app.backtesting.data_loader import BacktestDataset, MarketSnapshot
from app.backtesting.engine import BacktestConfig, BacktestEngine

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BASE_TS = datetime(2024, 1, 1, 12, 0, 0)


def _make_snap(
    market_id: str,
    yes_price: float,
    no_price: float,
    offset_hours: int = 0,
    category: str = "geopolitics",
) -> MarketSnapshot:
    return MarketSnapshot(
        timestamp=BASE_TS + timedelta(hours=offset_hours),
        market_id=market_id,
        yes_price=yes_price,
        no_price=no_price,
        category=category,
    )


def _dataset(*snaps: MarketSnapshot) -> BacktestDataset:
    return BacktestDataset(market_snapshots=list(snaps))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_run_empty_dataset_returns_empty() -> None:
    """Empty dataset must return empty trade list."""
    engine = BacktestEngine()
    trades = engine.run(BacktestDataset())
    assert trades == []


def test_run_generates_trades_from_snapshots_with_edge() -> None:
    """An underpriced market (yes+no < 0.95) should trigger a trade."""
    snap = _make_snap("m1", yes_price=0.40, no_price=0.40)  # total 0.80 → edge
    engine = BacktestEngine()
    trades = engine.run(_dataset(snap))
    # Position is opened and then closed at end
    assert len(trades) >= 1
    assert trades[0].market_id == "m1"


def test_run_no_trade_when_no_edge() -> None:
    """Fairly priced market (yes+no ≈ 1.0) must not trigger a trade."""
    snap = _make_snap("m1", yes_price=0.50, no_price=0.50)  # total 1.0 → no edge
    engine = BacktestEngine()
    trades = engine.run(_dataset(snap))
    assert trades == []


def test_positions_closed_on_resolution_near_one() -> None:
    """Position should be closed automatically when yes_price reaches 0.95."""
    snap_open = _make_snap("m1", yes_price=0.40, no_price=0.40, offset_hours=0)
    snap_resolve = _make_snap("m1", yes_price=0.97, no_price=0.03, offset_hours=1)
    engine = BacktestEngine()
    trades = engine.run(_dataset(snap_open, snap_resolve))
    assert any(t.market_id == "m1" and t.exit_price >= 0.95 for t in trades)


def test_positions_closed_on_resolution_near_zero() -> None:
    """Position should be closed automatically when yes_price reaches 0.05."""
    snap_open = _make_snap("m1", yes_price=0.40, no_price=0.40, offset_hours=0)
    snap_resolve = _make_snap("m1", yes_price=0.03, no_price=0.97, offset_hours=1)
    engine = BacktestEngine()
    trades = engine.run(_dataset(snap_open, snap_resolve))
    assert any(t.market_id == "m1" and t.exit_price <= 0.05 for t in trades)


def test_remaining_positions_closed_at_end() -> None:
    """Positions not resolved during replay must still be closed at end."""
    snap = _make_snap("m1", yes_price=0.40, no_price=0.40)
    engine = BacktestEngine()
    trades = engine.run(_dataset(snap))
    # All positions closed → no open positions remain
    assert engine._open_positions == {}
    assert len(trades) >= 1


def test_capital_tracking_consistent() -> None:
    """final_capital must be consistent with starting capital and P&L."""
    config = BacktestConfig(starting_capital=100.0)
    snap = _make_snap("m1", yes_price=0.40, no_price=0.40)
    engine = BacktestEngine(config)
    trades = engine.run(_dataset(snap))
    total_pnl = sum(t.pnl for t in trades)
    # final_capital ≈ starting + pnl (within rounding tolerance)
    assert abs(engine.final_capital - (100.0 + total_pnl)) < 0.01


def test_equity_curve_populated() -> None:
    """equity_curve should have at least one entry per timestamp."""
    snap1 = _make_snap("m1", yes_price=0.40, no_price=0.40, offset_hours=0)
    snap2 = _make_snap("m2", yes_price=0.40, no_price=0.40, offset_hours=1)
    engine = BacktestEngine()
    engine.run(_dataset(snap1, snap2))
    assert len(engine.equity_curve) >= 2


def test_max_positions_limit_respected() -> None:
    """Engine must not open more positions than max_positions."""
    config = BacktestConfig(starting_capital=500.0, max_positions=2)
    snaps = [_make_snap(f"m{i}", yes_price=0.40, no_price=0.40) for i in range(5)]
    engine = BacktestEngine(config)
    engine.run(_dataset(*snaps))
    # After run, all positions closed, but trades count limited by max_positions
    assert len(engine._trades) <= 2


def test_config_slippage_used() -> None:
    """Custom slippage_pct from config must propagate to the simulator."""
    config = BacktestConfig(slippage_pct=0.02)
    engine = BacktestEngine(config)
    assert engine._simulator._slippage_pct == 0.02
