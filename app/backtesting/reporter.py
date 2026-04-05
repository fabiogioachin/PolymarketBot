"""Backtest reporter: computes performance metrics from backtest trades."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

from app.backtesting.engine import BacktestTrade
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class BacktestResult:
    """Complete backtest result with performance metrics."""

    # Configuration
    starting_capital: float = 0.0
    final_capital: float = 0.0

    # Overall metrics
    total_return_pct: float = 0.0
    total_pnl: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0

    # Risk metrics
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0

    # Per-strategy breakdown
    strategy_breakdown: dict[str, dict] = field(default_factory=dict)

    # Per-category breakdown
    category_breakdown: dict[str, dict] = field(default_factory=dict)

    # Equity curve
    equity_curve: list[tuple[datetime, float]] = field(default_factory=list)

    # Trade log
    trades: list[dict] = field(default_factory=list)


class BacktestReporter:
    """Computes performance metrics from backtest trades."""

    def generate_report(
        self,
        trades: list[BacktestTrade],
        equity_curve: list[tuple[datetime, float]],
        starting_capital: float,
        final_capital: float,
    ) -> BacktestResult:
        """Generate a comprehensive backtest report."""
        result = BacktestResult(
            starting_capital=starting_capital,
            final_capital=round(final_capital, 2),
        )

        if not trades:
            logger.info("generate_report_empty", starting_capital=starting_capital)
            return result

        # Overall metrics
        result.total_pnl = round(final_capital - starting_capital, 2)
        result.total_return_pct = (
            round(result.total_pnl / starting_capital * 100, 2) if starting_capital > 0 else 0.0
        )
        result.total_trades = len(trades)
        result.winning_trades = sum(1 for t in trades if t.pnl > 0)
        result.losing_trades = sum(1 for t in trades if t.pnl <= 0)
        result.win_rate = (
            round(result.winning_trades / len(trades) * 100, 2) if trades else 0.0
        )

        # Max drawdown from equity curve
        result.max_drawdown_pct = self._compute_max_drawdown(equity_curve)

        # Sharpe ratio (annualized, assuming daily observations)
        result.sharpe_ratio = self._compute_sharpe(trades, starting_capital)

        # Per-strategy breakdown
        result.strategy_breakdown = self._compute_strategy_breakdown(trades)

        # Equity curve + trade log
        result.equity_curve = equity_curve
        result.trades = [
            {
                "timestamp": t.timestamp.isoformat() if t.timestamp else "",
                "market_id": t.market_id,
                "strategy": t.strategy,
                "side": t.side,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "size_eur": t.size_eur,
                "pnl": t.pnl,
                "fee_paid": t.fee_paid,
            }
            for t in trades
        ]

        logger.info(
            "report_generated",
            total_trades=result.total_trades,
            win_rate=result.win_rate,
            total_return_pct=result.total_return_pct,
            max_drawdown_pct=result.max_drawdown_pct,
            sharpe_ratio=result.sharpe_ratio,
        )
        return result

    @staticmethod
    def _compute_max_drawdown(equity_curve: list[tuple[datetime, float]]) -> float:
        """Compute max drawdown as percentage."""
        if len(equity_curve) < 2:
            return 0.0
        peak = equity_curve[0][1]
        max_dd = 0.0
        for _, equity in equity_curve:
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak * 100 if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd
        return round(max_dd, 2)

    @staticmethod
    def _compute_sharpe(trades: list[BacktestTrade], starting_capital: float) -> float:
        """Compute annualized Sharpe ratio from trade returns."""
        if len(trades) < 2:
            return 0.0
        returns = [t.pnl / starting_capital for t in trades]
        mean_ret = sum(returns) / len(returns)
        variance = sum((r - mean_ret) ** 2 for r in returns) / (len(returns) - 1)
        std_ret = math.sqrt(variance) if variance > 0 else 0.0
        if std_ret == 0:
            return 0.0
        # Annualize: assume ~252 trading days
        return round((mean_ret / std_ret) * math.sqrt(252), 2)

    @staticmethod
    def _compute_strategy_breakdown(trades: list[BacktestTrade]) -> dict[str, dict]:
        """Compute per-strategy performance."""
        by_strategy: dict[str, list[BacktestTrade]] = {}
        for t in trades:
            by_strategy.setdefault(t.strategy, []).append(t)

        breakdown: dict[str, dict] = {}
        for strategy, strades in by_strategy.items():
            wins = sum(1 for t in strades if t.pnl > 0)
            total_pnl = sum(t.pnl for t in strades)
            breakdown[strategy] = {
                "trades": len(strades),
                "wins": wins,
                "win_rate": round(wins / len(strades) * 100, 2) if strades else 0.0,
                "total_pnl": round(total_pnl, 2),
                "avg_pnl": round(total_pnl / len(strades), 2) if strades else 0.0,
            }
        return breakdown
