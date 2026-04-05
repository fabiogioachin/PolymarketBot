"""Backtest replay engine: replays historical data through strategies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from itertools import groupby

from app.backtesting.data_loader import BacktestDataset, MarketSnapshot
from app.backtesting.simulator import FillSimulator, SimulatedFill
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class BacktestConfig:
    """Configuration for a backtest run."""

    starting_capital: float = 150.0
    max_positions: int = 10
    slippage_pct: float = 0.005
    strategies: list[str] | None = None  # None = all enabled


@dataclass
class BacktestTrade:
    """A single trade in the backtest."""

    timestamp: datetime
    market_id: str
    strategy: str
    side: str
    entry_price: float
    exit_price: float = 0.0
    size_eur: float = 0.0
    fee_paid: float = 0.0
    pnl: float = 0.0
    reasoning: str = ""


class BacktestEngine:
    """Replays market snapshots through the value engine and strategies."""

    def __init__(self, config: BacktestConfig | None = None) -> None:
        self._config = config or BacktestConfig()
        self._capital = self._config.starting_capital
        self._trades: list[BacktestTrade] = []
        self._equity_curve: list[tuple[datetime, float]] = []
        self._open_positions: dict[str, SimulatedFill] = {}
        self._simulator = FillSimulator(slippage_pct=self._config.slippage_pct)

    def run(self, dataset: BacktestDataset) -> list[BacktestTrade]:
        """Run a backtest on a dataset.

        For each unique timestamp in the market snapshots:
        1. Update market prices
        2. Check if any open positions should be closed
           (market resolved: price went to 0 or 1)
        3. Generate signals from market data
        4. Execute new trades (respecting position limits)

        This is a simplified backtest that uses market snapshot prices
        directly as fair values. In production, the full ValueAssessmentEngine
        would be used.
        """
        if not dataset.market_snapshots:
            return []

        snapshots = sorted(dataset.market_snapshots, key=lambda s: s.timestamp)

        for timestamp, group in groupby(snapshots, key=lambda s: s.timestamp):
            group_list = list(group)
            self._equity_curve.append((timestamp, self._capital))

            # Close positions for resolved markets (price near 0 or 1)
            self._check_resolutions(group_list)

            # Simple signal generation: buy underpriced, sell overpriced
            for snap in group_list:
                if snap.market_id in self._open_positions:
                    continue  # already have position
                if len(self._open_positions) >= self._config.max_positions:
                    break

                # Simple edge detection: if price far from 0.5, there may be edge
                edge = self._estimate_edge(snap)
                if abs(edge) > 0.05:  # 5% edge threshold
                    side = "BUY" if edge > 0 else "SELL"
                    size = min(self._capital * 0.05, 25.0)  # 5% or max 25 EUR

                    if size > 1.0 and self._capital >= size:
                        fill = self._simulator.simulate_entry(
                            market_id=snap.market_id,
                            strategy="backtest_value_edge",
                            side=side,
                            price=snap.yes_price,
                            size_eur=size,
                            category=snap.category,
                        )
                        self._open_positions[snap.market_id] = fill
                        self._capital -= size
                        logger.debug(
                            "position_opened",
                            market_id=snap.market_id,
                            side=side,
                            size=size,
                            capital_remaining=self._capital,
                        )

        # Close all remaining positions at last known price
        self._close_all_remaining(snapshots)

        logger.info(
            "backtest_complete",
            trades=len(self._trades),
            final_capital=self._capital,
        )
        return self._trades

    def _estimate_edge(self, snap: MarketSnapshot) -> float:
        """Simple edge estimation from snapshot."""
        # If yes_price + no_price != 1.0, there's an arbitrage-like signal
        total = snap.yes_price + snap.no_price
        if total < 0.95:
            return 0.10  # underpriced market
        if total > 1.05:
            return -0.10  # overpriced market
        return 0.0

    def _check_resolutions(self, snapshots: list[MarketSnapshot]) -> None:
        """Close positions for resolved markets."""
        for snap in snapshots:
            if snap.market_id not in self._open_positions:
                continue
            # Resolved if price is near 0 or 1
            if snap.yes_price >= 0.95 or snap.yes_price <= 0.05:
                fill = self._open_positions.pop(snap.market_id)
                fill = self._simulator.simulate_exit(fill, snap.yes_price)
                self._capital += fill.size_eur + fill.pnl
                self._trades.append(
                    BacktestTrade(
                        timestamp=snap.timestamp,
                        market_id=snap.market_id,
                        strategy=fill.strategy,
                        side=fill.side,
                        entry_price=fill.entry_price,
                        exit_price=fill.exit_price,
                        size_eur=fill.size_eur,
                        fee_paid=fill.fee_paid,
                        pnl=fill.pnl,
                    )
                )
                logger.debug(
                    "position_resolved",
                    market_id=snap.market_id,
                    pnl=fill.pnl,
                )

    def _close_all_remaining(self, snapshots: list[MarketSnapshot]) -> None:
        """Close all remaining positions at last known price."""
        last_prices: dict[str, float] = {}
        for snap in snapshots:
            last_prices[snap.market_id] = snap.yes_price

        for market_id, fill in list(self._open_positions.items()):
            exit_price = last_prices.get(market_id, fill.entry_price)
            fill = self._simulator.simulate_exit(fill, exit_price)
            self._capital += fill.size_eur + fill.pnl
            self._trades.append(
                BacktestTrade(
                    timestamp=snapshots[-1].timestamp if snapshots else datetime.now(),
                    market_id=market_id,
                    strategy=fill.strategy,
                    side=fill.side,
                    entry_price=fill.entry_price,
                    exit_price=fill.exit_price,
                    size_eur=fill.size_eur,
                    fee_paid=fill.fee_paid,
                    pnl=fill.pnl,
                )
            )
        self._open_positions.clear()

    @property
    def equity_curve(self) -> list[tuple[datetime, float]]:
        """Return the equity curve recorded during the run."""
        return list(self._equity_curve)

    @property
    def final_capital(self) -> float:
        """Return the final capital after the backtest."""
        return self._capital
