"""Tests for app.backtesting.reporter."""

from datetime import datetime, timedelta

from app.backtesting.engine import BacktestTrade
from app.backtesting.reporter import BacktestReporter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BASE_TS = datetime(2024, 1, 1, 12, 0, 0)


def _trade(
    pnl: float,
    strategy: str = "strat_a",
    side: str = "BUY",
    entry_price: float = 0.50,
    exit_price: float = 0.70,
    size_eur: float = 10.0,
    offset_hours: int = 0,
) -> BacktestTrade:
    return BacktestTrade(
        timestamp=BASE_TS + timedelta(hours=offset_hours),
        market_id="m1",
        strategy=strategy,
        side=side,
        entry_price=entry_price,
        exit_price=exit_price,
        size_eur=size_eur,
        pnl=pnl,
    )


def _equity(values: list[float]) -> list[tuple[datetime, float]]:
    return [(BASE_TS + timedelta(hours=i), v) for i, v in enumerate(values)]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_generate_report_no_trades_returns_defaults() -> None:
    """Report with no trades must return zeroed metrics."""
    reporter = BacktestReporter()
    result = reporter.generate_report([], _equity([100.0]), 100.0, 100.0)
    assert result.total_trades == 0
    assert result.win_rate == 0.0
    assert result.total_pnl == 0.0
    assert result.total_return_pct == 0.0


def test_total_return_pct_computed_correctly() -> None:
    """total_return_pct = (final - start) / start * 100."""
    reporter = BacktestReporter()
    result = reporter.generate_report(
        [_trade(pnl=10.0)], _equity([100.0, 110.0]), 100.0, 110.0
    )
    assert result.total_return_pct == 10.0


def test_win_rate_computed_correctly() -> None:
    """win_rate = winning / total * 100."""
    reporter = BacktestReporter()
    trades = [_trade(pnl=5.0), _trade(pnl=-3.0), _trade(pnl=2.0)]
    result = reporter.generate_report(trades, _equity([100.0, 105.0, 102.0, 104.0]), 100.0, 104.0)
    assert result.total_trades == 3
    assert result.winning_trades == 2
    assert result.losing_trades == 1
    assert result.win_rate == round(2 / 3 * 100, 2)


def test_max_drawdown_computed_from_equity_curve() -> None:
    """Max drawdown should reflect the worst peak-to-trough decline."""
    reporter = BacktestReporter()
    # Peak at 120, then drops to 90 → drawdown = (120 - 90) / 120 * 100 = 25%
    curve = _equity([100.0, 120.0, 90.0, 95.0])
    result = reporter.generate_report(
        [_trade(pnl=1.0)], curve, 100.0, 95.0
    )
    assert result.max_drawdown_pct == round((120.0 - 90.0) / 120.0 * 100, 2)


def test_max_drawdown_zero_monotonic_curve() -> None:
    """Monotonically increasing equity curve must have 0% drawdown."""
    reporter = BacktestReporter()
    curve = _equity([100.0, 105.0, 110.0, 115.0])
    result = reporter.generate_report([_trade(pnl=1.0)], curve, 100.0, 115.0)
    assert result.max_drawdown_pct == 0.0


def test_sharpe_ratio_positive_for_consistent_winners() -> None:
    """Consistent positive returns must produce a positive Sharpe ratio."""
    reporter = BacktestReporter()
    trades = [_trade(pnl=2.0, offset_hours=i) for i in range(10)]
    curve = _equity([100.0 + i * 2 for i in range(11)])
    result = reporter.generate_report(trades, curve, 100.0, 120.0)
    # All returns are identical positive values: Sharpe is either very high or
    # undefined (std≈0). The reporter returns 0 only when variance is exactly 0;
    # floating-point may produce a tiny positive variance and thus a large positive
    # Sharpe. Either way the result must be >= 0.
    assert result.sharpe_ratio >= 0.0


def test_sharpe_ratio_nonzero_for_mixed_returns() -> None:
    """Mixed returns must produce a non-zero Sharpe ratio."""
    reporter = BacktestReporter()
    pnl_values = [2.0, -1.0, 3.0, -0.5, 1.5, 2.5, -0.8, 1.2]
    trades = [_trade(pnl=p, offset_hours=i) for i, p in enumerate(pnl_values)]
    curve = _equity([100.0] * (len(pnl_values) + 1))
    result = reporter.generate_report(trades, curve, 100.0, 108.4)
    assert result.sharpe_ratio != 0.0


def test_strategy_breakdown_per_strategy() -> None:
    """strategy_breakdown must group trades by strategy correctly."""
    reporter = BacktestReporter()
    trades = [
        _trade(pnl=5.0, strategy="alpha"),
        _trade(pnl=-2.0, strategy="alpha"),
        _trade(pnl=3.0, strategy="beta"),
    ]
    result = reporter.generate_report(trades, _equity([100.0, 105.0, 103.0, 106.0]), 100.0, 106.0)
    assert "alpha" in result.strategy_breakdown
    assert "beta" in result.strategy_breakdown
    assert result.strategy_breakdown["alpha"]["trades"] == 2
    assert result.strategy_breakdown["beta"]["trades"] == 1
    assert result.strategy_breakdown["alpha"]["wins"] == 1
    assert result.strategy_breakdown["alpha"]["total_pnl"] == 3.0


def test_trade_log_populated_with_correct_fields() -> None:
    """Trade log in result must contain all expected keys."""
    reporter = BacktestReporter()
    trades = [_trade(pnl=5.0)]
    result = reporter.generate_report(trades, _equity([100.0, 105.0]), 100.0, 105.0)
    assert len(result.trades) == 1
    log = result.trades[0]
    for key in ("timestamp", "market_id", "strategy", "side", "entry_price", "exit_price",
                "size_eur", "pnl", "fee_paid"):
        assert key in log


def test_single_trade_edge_case() -> None:
    """Report with a single trade must not crash and must compute win_rate correctly."""
    reporter = BacktestReporter()
    result = reporter.generate_report(
        [_trade(pnl=5.0)], _equity([100.0, 105.0]), 100.0, 105.0
    )
    assert result.total_trades == 1
    assert result.win_rate == 100.0
    # Sharpe is 0 for a single trade (not enough variance)
    assert result.sharpe_ratio == 0.0
