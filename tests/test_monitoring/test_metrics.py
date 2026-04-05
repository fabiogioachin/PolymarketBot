"""Tests for MetricsCollector."""

import pytest

from app.monitoring.metrics import MetricsCollector, TradingMetrics  # noqa: E402

# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def collector() -> MetricsCollector:
    return MetricsCollector()


# ── record_trade: counter increment ───────────────────────────────────


def test_record_trade_increments_trade_count(collector: MetricsCollector) -> None:
    assert collector._trade_count == 0
    collector.record_trade("value_edge", pnl=1.5)
    collector.record_trade("value_edge", pnl=-0.5)
    assert collector._trade_count == 2


# ── record_trade: wins/losses tracking ────────────────────────────────


def test_record_trade_tracks_wins_and_losses(collector: MetricsCollector) -> None:
    collector.record_trade("strategy_a", pnl=2.0)
    collector.record_trade("strategy_a", pnl=0.5)
    collector.record_trade("strategy_a", pnl=-1.0)

    assert collector._wins == 2
    assert collector._losses == 1


def test_record_trade_zero_pnl_counts_as_loss(collector: MetricsCollector) -> None:
    collector.record_trade("strategy_a", pnl=0.0)
    assert collector._wins == 0
    assert collector._losses == 1


# ── Strategy metrics per-strategy tracking ────────────────────────────


def test_strategy_metrics_tracked_separately(collector: MetricsCollector) -> None:
    collector.record_trade("alpha", pnl=1.0, edge=0.10)
    collector.record_trade("alpha", pnl=-0.5, edge=0.03)
    collector.record_trade("beta", pnl=2.0, edge=0.20)

    metrics = {sm.strategy_name: sm for sm in collector.get_strategy_metrics()}

    assert "alpha" in metrics
    assert "beta" in metrics
    assert metrics["alpha"].trades == 2
    assert metrics["alpha"].wins == 1
    assert metrics["beta"].trades == 1
    assert metrics["beta"].wins == 1


def test_strategy_win_rate_calculated(collector: MetricsCollector) -> None:
    collector.record_trade("alpha", pnl=1.0)
    collector.record_trade("alpha", pnl=1.0)
    collector.record_trade("alpha", pnl=-1.0)
    collector.record_trade("alpha", pnl=-1.0)

    metrics = {sm.strategy_name: sm for sm in collector.get_strategy_metrics()}
    assert metrics["alpha"].win_rate == 50.0


def test_strategy_avg_edge_running_average(collector: MetricsCollector) -> None:
    collector.record_trade("alpha", pnl=1.0, edge=0.10)
    collector.record_trade("alpha", pnl=1.0, edge=0.20)

    metrics = {sm.strategy_name: sm for sm in collector.get_strategy_metrics()}
    # avg_edge should be (0.10 + 0.20) / 2 = 0.15
    assert abs(metrics["alpha"].avg_edge - 0.15) < 1e-6


# ── reset_daily ────────────────────────────────────────────────────────


def test_reset_daily_clears_daily_pnl(collector: MetricsCollector) -> None:
    collector.record_trade("strategy_a", pnl=5.0)
    collector.record_trade("strategy_a", pnl=3.0)
    assert collector._daily_pnl == pytest.approx(8.0)

    collector.reset_daily()
    assert collector._daily_pnl == 0.0


def test_reset_daily_preserves_total_pnl(collector: MetricsCollector) -> None:
    collector.record_trade("strategy_a", pnl=5.0)
    collector.reset_daily()
    assert collector._total_pnl == pytest.approx(5.0)


# ── get_trading_metrics ────────────────────────────────────────────────


def test_get_trading_metrics_returns_correct_snapshot(collector: MetricsCollector) -> None:
    collector.record_trade("alpha", pnl=3.0)
    collector.record_trade("alpha", pnl=-1.0)

    m = collector.get_trading_metrics(exposure=20.0, positions=2, equity=152.0)

    assert isinstance(m, TradingMetrics)
    assert m.total_trades == 2
    assert m.winning_trades == 1
    assert m.losing_trades == 1
    assert m.total_pnl == pytest.approx(2.0)
    assert m.daily_pnl == pytest.approx(2.0)
    assert m.current_exposure == pytest.approx(20.0)
    assert m.open_positions == 2
    assert m.equity == pytest.approx(152.0)
    assert m.win_rate == pytest.approx(50.0)
    assert m.timestamp is not None


def test_get_trading_metrics_no_trades_win_rate_zero(collector: MetricsCollector) -> None:
    m = collector.get_trading_metrics()
    assert m.win_rate == 0.0
    assert m.total_trades == 0


# ── get_trade_log ──────────────────────────────────────────────────────


def test_get_trade_log_returns_recent_trades(collector: MetricsCollector) -> None:
    for i in range(10):
        collector.record_trade("alpha", pnl=float(i), edge=0.05)

    log = collector.get_trade_log(limit=5)
    assert len(log) == 5
    # Should be the last 5 — pnl 5..9
    assert log[-1]["pnl"] == pytest.approx(9.0)


def test_get_trade_log_contains_expected_keys(collector: MetricsCollector) -> None:
    collector.record_trade("alpha", pnl=1.0, edge=0.12)
    log = collector.get_trade_log()
    assert len(log) == 1
    entry = log[0]
    assert "timestamp" in entry
    assert "strategy" in entry
    assert entry["strategy"] == "alpha"
    assert entry["pnl"] == pytest.approx(1.0)
    assert entry["edge"] == pytest.approx(0.12)


# ── get_equity_history ─────────────────────────────────────────────────


def test_get_equity_history_returns_history(collector: MetricsCollector) -> None:
    collector.record_equity(150.0)
    collector.record_equity(151.5)
    collector.record_equity(149.0)

    history = collector.get_equity_history()
    assert len(history) == 3
    assert history[0]["equity"] == pytest.approx(150.0)
    assert history[2]["equity"] == pytest.approx(149.0)
    assert "timestamp" in history[0]


def test_get_equity_history_empty_initially(collector: MetricsCollector) -> None:
    assert collector.get_equity_history() == []


# ── win_rate calculation ───────────────────────────────────────────────


def test_win_rate_all_wins(collector: MetricsCollector) -> None:
    for _ in range(5):
        collector.record_trade("alpha", pnl=1.0)
    m = collector.get_trading_metrics()
    assert m.win_rate == pytest.approx(100.0)


def test_win_rate_all_losses(collector: MetricsCollector) -> None:
    for _ in range(5):
        collector.record_trade("alpha", pnl=-1.0)
    m = collector.get_trading_metrics()
    assert m.win_rate == pytest.approx(0.0)
