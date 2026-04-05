"""Execution engine: the main trading loop.

Full tick cycle:
1. Circuit breaker check
2. Update open positions with live market prices
3. Evaluate exits (TP/SL/expiry/edge-gone) → close positions → realized P&L
4. Scan markets → valuations → strategies → signals
5. Risk check → execute new orders
6. Feed results to circuit breaker + metrics
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger
from app.execution.executor import OrderExecutor
from app.execution.position_monitor import build_exit_order, evaluate_exit
from app.execution.resolution_tracker import check_resolution
from app.execution.trade_store import TradeStore
from app.models.order import OrderRequest, OrderSide, OrderStatus
from app.models.signal import Signal, SignalType
from app.models.valuation import ValuationResult
from app.risk.circuit_breaker import CircuitBreaker
from app.risk.manager import RiskManager
from app.strategies.registry import StrategyRegistry

if TYPE_CHECKING:
    from app.models.market import Market

logger = get_logger(__name__)


@dataclass
class TickResult:
    """Result of a single tick cycle."""

    timestamp: datetime
    markets_scanned: int = 0
    markets_assessed: int = 0
    signals_generated: int = 0
    orders_placed: int = 0
    orders_rejected: int = 0
    positions_closed: int = 0
    realized_pnl: float = 0.0
    circuit_breaker_tripped: bool = False
    errors: list[str] = field(default_factory=list)


class ExecutionEngine:
    """Main trading loop: scan -> assess -> strategize -> risk check -> execute."""

    def __init__(
        self,
        executor: OrderExecutor,
        risk_manager: RiskManager,
        circuit_breaker: CircuitBreaker,
        strategy_registry: StrategyRegistry,
        value_engine: Any = None,
        market_service: Any = None,
        trade_store: TradeStore | None = None,
        manifold_service: Any = None,
    ) -> None:
        self._executor = executor
        self._risk = risk_manager
        self._circuit_breaker = circuit_breaker
        self._strategies = strategy_registry
        self._value_engine = value_engine
        self._market_service = market_service
        self._store = trade_store
        self._manifold_service = manifold_service
        self._running = False
        self._tick_count = 0
        self._last_tick: datetime | None = None
        self._trade_log: list[dict[str, object]] = []
        # Map token_id → market_id for position lookups
        self._token_to_market: dict[str, str] = {}
        self._last_manifold_refresh: datetime | None = None

    async def tick(self, markets: list[Market] | None = None) -> TickResult:
        """Execute a single tick cycle."""
        now = datetime.now(tz=UTC)
        result = TickResult(timestamp=now)

        # 1. Circuit breaker check
        cb_state = self._circuit_breaker.check()
        if cb_state.is_tripped:
            result.circuit_breaker_tripped = True
            logger.warning("tick_skipped", reason="circuit_breaker_tripped")
            return result

        # 2. Get markets
        if markets is None and self._market_service:
            markets = await self._market_service.get_filtered_markets()
        if not markets:
            return result
        result.markets_scanned = len(markets)

        # Build market lookup for position management
        market_by_id: dict[str, Market] = {m.id: m for m in markets}

        # 2b. Fetch Manifold cross-platform signals (on slower cadence)
        external_signals: dict[str, dict[str, float | None]] = {}
        if self._manifold_service is not None:
            external_signals = await self._fetch_manifold_signals(markets, now)

        # 3. Assess values
        valuations: dict[str, ValuationResult] = {}
        if self._value_engine:
            assessed = await self._value_engine.assess_batch(
                markets, universe=markets, external_signals=external_signals or None
            )
            for v in assessed:
                valuations[v.market_id] = v
        result.markets_assessed = len(valuations)

        # 4. UPDATE open positions with live prices + EVALUATE exits
        await self._manage_positions(market_by_id, valuations, result, now)

        # 5. Generate new signals
        signals: list[Signal] = []
        for market in markets:
            valuation = valuations.get(market.id)
            if not valuation:
                continue

            applicable_strategies = self._strategies.get_for_domain(market.category.value)
            for strategy in applicable_strategies:
                try:
                    result_signals = await strategy.evaluate(market, valuation)
                    if result_signals is None:
                        continue
                    if isinstance(result_signals, Signal):
                        result_signals = [result_signals]
                    for sig in result_signals:
                        if sig.signal_type != SignalType.HOLD:
                            signals.append(sig)
                except Exception as e:
                    result.errors.append(f"{strategy.name}: {e}")

        result.signals_generated = len(signals)

        # 6. Risk check + Execute new orders
        balance = await self._executor.get_balance()
        for signal in signals:
            price = signal.market_price if signal.market_price > 0 else 0.5

            size_result = self._risk.size_position(signal, balance.available, price)

            risk_check = self._risk.check_order(signal, price, size_result.size_eur)
            if not risk_check.approved:
                result.orders_rejected += 1
                logger.info(
                    "order_rejected",
                    market_id=signal.market_id,
                    reason=risk_check.reason,
                )
                continue

            side = OrderSide.BUY if signal.signal_type == SignalType.BUY else OrderSide.SELL
            order = OrderRequest(
                token_id=signal.token_id,
                side=side,
                price=price,
                size=size_result.size_shares,
                market_id=signal.market_id,
                reason=signal.reasoning,
            )

            try:
                order_result = await self._executor.execute(order)
                if order_result.status == OrderStatus.FILLED:
                    # Use actual fill price and size (may differ from requested due to slippage)
                    fill_cost = order_result.price * order_result.filled_size
                    self._risk.record_fill(signal.token_id, fill_cost)
                    self._token_to_market[signal.token_id] = signal.market_id
                    result.orders_placed += 1
                    await self._persist_trade({
                        "timestamp": now.isoformat(),
                        "market_id": signal.market_id,
                        "strategy": signal.strategy,
                        "side": str(side),
                        "size_eur": round(fill_cost, 2),
                        "shares": round(order_result.filled_size, 2),
                        "price": round(order_result.price, 4),
                        "edge": signal.edge_amount,
                        "pnl": 0.0,
                        "type": "open",
                        "reasoning": signal.reasoning,
                    })
                    logger.info(
                        "position_opened",
                        market_id=signal.market_id,
                        strategy=signal.strategy,
                        side=str(side),
                        fill_price=round(order_result.price, 4),
                        shares=round(order_result.filled_size, 2),
                        cost=round(fill_cost, 2),
                        edge=signal.edge_amount,
                    )
                else:
                    result.orders_rejected += 1
            except Exception as e:
                result.errors.append(f"execute: {e}")
                result.orders_rejected += 1

        self._tick_count += 1
        self._last_tick = now

        # Persist state to SQLite after each tick
        await self._persist_state()

        logger.info(
            "tick_completed",
            tick=self._tick_count,
            scanned=result.markets_scanned,
            assessed=result.markets_assessed,
            signals=result.signals_generated,
            opened=result.orders_placed,
            closed=result.positions_closed,
            realized_pnl=round(result.realized_pnl, 4),
            rejected=result.orders_rejected,
        )

        return result

    async def _manage_positions(
        self,
        market_by_id: dict[str, Market],
        valuations: dict[str, ValuationResult],
        result: TickResult,
        now: datetime,
    ) -> None:
        """Update prices, check resolutions, evaluate exits.

        Order of operations:
        1. Check if any markets resolved → payout or loss
        2. Update live prices for remaining positions
        3. Evaluate sell conditions (take profit, edge reversal, near expiry)
        """
        positions = await self._executor.get_positions()
        if not positions:
            return

        for pos in list(positions):  # copy list since resolution mutates it
            market_id = pos.market_id or self._token_to_market.get(pos.token_id, "")
            market = market_by_id.get(market_id)

            # Fetch market if not in current scan
            if not market and market_id and self._market_service:
                try:
                    market = await self._market_service.get_market(market_id)
                except Exception:
                    pass

            # ── 1. Check resolution ──────────────────────────────
            resolution = await check_resolution(market_id)
            if resolution.resolved and resolution.outcome_payouts:
                payout = resolution.outcome_payouts.get(pos.token_id, 0.0)
                # Resolve through the CLOB client
                clob = self._executor._clob if hasattr(self._executor, '_clob') else None
                if clob:
                    realized = clob.resolve_position(pos.token_id, payout)
                else:
                    realized = (payout - pos.avg_price) * pos.size

                result.positions_closed += 1
                result.realized_pnl += realized
                self._risk.record_close(pos.token_id, realized)
                self._circuit_breaker.record_trade_result(realized)

                won = payout > 0.5
                await self._persist_trade({
                    "timestamp": now.isoformat(),
                    "market_id": market_id,
                    "strategy": "resolution",
                    "side": "RESOLVED",
                    "size_eur": round(pos.size * pos.avg_price, 2),
                    "price": payout,
                    "edge": 0.0,
                    "pnl": round(realized, 4),
                    "type": "close",
                    "reasoning": (
                        f"Market resolved: {resolution.winning_outcome} won. "
                        f"Payout ${payout}/share. "
                        f"{'WON' if won else 'LOST'}: {pos.size:.0f} shares "
                        f"@ avg {pos.avg_price:.3f}"
                    ),
                })

                logger.info(
                    "position_resolved",
                    market_id=market_id,
                    winning=resolution.winning_outcome,
                    payout=payout,
                    realized_pnl=round(realized, 4),
                    won=won,
                )
                continue  # position is gone, skip to next

            # ── 2. Update live price ─────────────────────────────
            valuation = valuations.get(market_id)
            if market:
                for outcome in market.outcomes:
                    if outcome.token_id == pos.token_id:
                        clob = self._executor._clob if hasattr(self._executor, '_clob') else None
                        if clob:
                            clob.update_market_price(pos.token_id, outcome.price)
                        pos.current_price = outcome.price
                        break

            # Indicative unrealized P&L (not realized until sold/resolved)
            if pos.current_price > 0 and pos.avg_price > 0:
                pos.unrealized_pnl = (pos.current_price - pos.avg_price) * pos.size

            # ── 3. Evaluate sell on secondary market ─────────────
            exit_decision = evaluate_exit(pos, market=market, valuation=valuation)
            if not exit_decision.should_exit:
                continue

            exit_order = build_exit_order(pos)
            try:
                order_result = await self._executor.execute(exit_order)
                if order_result.status == OrderStatus.FILLED:
                    # P&L realized by the CLOB client's _reduce_position
                    realized = (order_result.price - pos.avg_price) * order_result.filled_size
                    result.positions_closed += 1
                    result.realized_pnl += realized
                    self._risk.record_close(pos.token_id, realized)
                    self._circuit_breaker.record_trade_result(realized)

                    await self._persist_trade({
                        "timestamp": now.isoformat(),
                        "market_id": market_id,
                        "strategy": "exit",
                        "side": str(exit_order.side),
                        "size_eur": round(order_result.filled_size * pos.avg_price, 2),
                        "price": order_result.price,
                        "edge": 0.0,
                        "pnl": round(realized, 4),
                        "type": "close",
                        "reasoning": exit_decision.reason,
                    })

                    logger.info(
                        "position_sold",
                        market_id=market_id,
                        reason=exit_decision.reason,
                        entry=round(pos.avg_price, 4),
                        exit=round(order_result.price, 4),
                        realized_pnl=round(realized, 4),
                    )
            except Exception as e:
                result.errors.append(f"exit {pos.token_id}: {e}")

    async def _fetch_manifold_signals(
        self, markets: list[Market], now: datetime
    ) -> dict[str, dict[str, float | None]]:
        """Fetch cross-platform signals from Manifold on a slower cadence."""
        from app.core.yaml_config import app_config

        interval = app_config.intelligence.manifold.poll_interval_minutes * 60
        if (
            self._last_manifold_refresh is not None
            and (now - self._last_manifold_refresh).total_seconds() < interval
        ):
            return {}

        try:
            signals_map = await self._manifold_service.get_signals_batch(markets)
            self._last_manifold_refresh = now

            external: dict[str, dict[str, float | None]] = {}
            for market_id, signal in signals_map.items():
                external[market_id] = {
                    "cross_platform_signal": signal.signal_value,
                }

            if external:
                logger.info(
                    "manifold_signals_fetched",
                    count=len(external),
                )
            return external
        except Exception as exc:
            logger.warning("manifold_fetch_failed", error=str(exc))
            return {}

    async def restore_from_store(self) -> None:
        """Restore trade log and positions from SQLite on startup."""
        if not self._store:
            return
        trades = await self._store.get_trades(limit=1000)
        # Trades come back newest-first, reverse to chronological
        self._trade_log = list(reversed(trades))
        # Restore simulated balance from state
        balance_str = await self._store.load_state("simulated_balance")
        if balance_str and hasattr(self._executor, "_clob"):
            self._executor._clob._balance = float(balance_str)
        # Restore positions into CLOB client
        positions = await self._store.load_positions()
        if positions and hasattr(self._executor, "_clob"):
            for pos in positions:
                self._executor._clob._positions[pos.token_id] = pos
                self._token_to_market[pos.token_id] = pos.market_id
                self._risk.record_fill(pos.token_id, pos.size * pos.avg_price)
        tick_str = await self._store.load_state("tick_count")
        if tick_str:
            self._tick_count = int(tick_str)
        # Restore P&L state
        daily_pnl_str = await self._store.load_state("daily_pnl")
        if daily_pnl_str:
            self._risk._daily_pnl = float(daily_pnl_str)
        realized_pnl_str = await self._store.load_state("realized_pnl")
        if realized_pnl_str and hasattr(self._executor, "_clob"):
            self._executor._clob._realized_pnl = float(realized_pnl_str)
        logger.info(
            "engine_restored",
            trades=len(self._trade_log),
            positions=len(positions) if positions else 0,
            tick_count=self._tick_count,
            daily_pnl=self._risk._daily_pnl,
            realized_pnl=realized_pnl_str or "0",
        )

    async def _persist_trade(self, trade: dict[str, object]) -> None:
        """Append trade to in-memory log and persist to SQLite."""
        self._trade_log.append(trade)
        if self._store:
            await self._store.append_trade(trade)

    async def _persist_state(self) -> None:
        """Persist positions and engine state to SQLite after each tick."""
        if not self._store:
            return
        positions = await self._executor.get_positions()
        await self._store.save_positions(positions)
        await self._store.save_state("tick_count", str(self._tick_count))
        balance = await self._executor.get_balance()
        await self._store.save_state("simulated_balance", str(balance.available))
        await self._store.save_state("daily_pnl", str(self._risk.daily_pnl))
        clob = self._executor._clob if hasattr(self._executor, "_clob") else None
        if clob:
            await self._store.save_state("realized_pnl", str(clob._realized_pnl))

    async def run(self, interval_seconds: int = 60) -> None:
        """Run the engine loop. Stops when stop() is called."""
        self._running = True
        logger.info("engine_started", interval=interval_seconds)
        while self._running:
            try:
                await self.tick()
            except Exception as e:
                logger.error("tick_error", error=str(e))
            await asyncio.sleep(interval_seconds)
        logger.info("engine_stopped", total_ticks=self._tick_count)

    async def stop(self) -> None:
        """Stop the engine loop."""
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def tick_count(self) -> int:
        return self._tick_count

    @property
    def trade_log(self) -> list[dict[str, object]]:
        return list(self._trade_log)
