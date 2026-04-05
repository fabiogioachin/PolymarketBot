"""Metrics collector for dashboard and monitoring."""

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass
class TradingMetrics:
    """Current trading metrics snapshot."""

    timestamp: datetime | None = None
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl: float = 0.0
    daily_pnl: float = 0.0
    current_exposure: float = 0.0
    open_positions: int = 0
    equity: float = 0.0
    win_rate: float = 0.0


@dataclass
class StrategyMetrics:
    """Per-strategy performance metrics."""

    strategy_name: str = ""
    trades: int = 0
    wins: int = 0
    pnl: float = 0.0
    win_rate: float = 0.0
    avg_edge: float = 0.0


class MetricsCollector:
    """Collects and aggregates trading metrics."""

    def __init__(self) -> None:
        self._trade_count = 0
        self._wins = 0
        self._losses = 0
        self._total_pnl = 0.0
        self._daily_pnl = 0.0
        self._equity_history: list[tuple[datetime, float]] = []
        self._trade_log: list[dict] = []  # type: ignore[type-arg]
        self._strategy_metrics: dict[str, StrategyMetrics] = {}

    def record_trade(self, strategy: str, pnl: float, edge: float = 0.0) -> None:
        """Record a completed trade."""
        self._trade_count += 1
        self._total_pnl += pnl
        self._daily_pnl += pnl

        if pnl > 0:
            self._wins += 1
        else:
            self._losses += 1

        # Per-strategy
        sm = self._strategy_metrics.setdefault(strategy, StrategyMetrics(strategy_name=strategy))
        sm.trades += 1
        if pnl > 0:
            sm.wins += 1
        sm.pnl += pnl
        sm.win_rate = round(sm.wins / sm.trades * 100, 2) if sm.trades else 0.0
        # Running average edge
        sm.avg_edge = (
            round((sm.avg_edge * (sm.trades - 1) + edge) / sm.trades, 4) if sm.trades else 0.0
        )

        self._trade_log.append(
            {
                "timestamp": datetime.now(tz=UTC).isoformat(),
                "strategy": strategy,
                "pnl": round(pnl, 4),
                "edge": round(edge, 4),
            }
        )

    def record_equity(self, equity: float) -> None:
        """Record an equity data point."""
        self._equity_history.append((datetime.now(tz=UTC), equity))

    def reset_daily(self) -> None:
        """Reset daily metrics."""
        self._daily_pnl = 0.0

    def get_trading_metrics(
        self, exposure: float = 0.0, positions: int = 0, equity: float = 0.0
    ) -> TradingMetrics:
        """Return a snapshot of current trading metrics."""
        return TradingMetrics(
            timestamp=datetime.now(tz=UTC),
            total_trades=self._trade_count,
            winning_trades=self._wins,
            losing_trades=self._losses,
            total_pnl=round(self._total_pnl, 2),
            daily_pnl=round(self._daily_pnl, 2),
            current_exposure=round(exposure, 2),
            open_positions=positions,
            equity=round(equity, 2),
            win_rate=(
                round(self._wins / self._trade_count * 100, 2) if self._trade_count else 0.0
            ),
        )

    def get_strategy_metrics(self) -> list[StrategyMetrics]:
        """Return per-strategy performance list."""
        return list(self._strategy_metrics.values())

    def get_equity_history(self) -> list[dict]:  # type: ignore[type-arg]
        """Return equity curve as list of dicts."""
        return [{"timestamp": t.isoformat(), "equity": e} for t, e in self._equity_history]

    def get_trade_log(self, limit: int = 50) -> list[dict]:  # type: ignore[type-arg]
        """Return the most recent trades up to limit."""
        return self._trade_log[-limit:]
