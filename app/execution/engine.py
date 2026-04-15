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
import contextlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app.clients.polymarket_ws import PolymarketWsClient
from app.core.logging import get_logger
from app.execution.executor import OrderExecutor
from app.execution.position_monitor import build_exit_order, evaluate_exit
from app.execution.resolution_tracker import check_resolution
from app.execution.trade_store import TradeStore
from app.knowledge.risk_kb import MarketKnowledge, RiskLevel
from app.models.market import OrderBook, OrderBookLevel, TimeHorizon
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
        intelligence_orchestrator: Any = None,
        knowledge_service: Any = None,
        risk_kb: Any = None,
    ) -> None:
        self._executor = executor
        self._risk = risk_manager
        self._circuit_breaker = circuit_breaker
        self._strategies = strategy_registry
        self._value_engine = value_engine
        self._market_service = market_service
        self._store = trade_store
        self._manifold_service = manifold_service
        self._intelligence = intelligence_orchestrator
        self._knowledge_service = knowledge_service
        self._risk_kb = risk_kb
        self._running = False
        self._tick_count = 0
        self._last_tick: datetime | None = None
        self._trade_log: list[dict[str, object]] = []
        # Map token_id → market_id for position lookups
        self._token_to_market: dict[str, str] = {}
        self._last_manifold_refresh: datetime | None = None
        self._last_intel_refresh: datetime | None = None
        # WebSocket orderbook cache (background task)
        self._ws_client = PolymarketWsClient()
        self._orderbook_cache: dict[str, OrderBook] = {}
        self._ws_task: asyncio.Task[None] | None = None

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

        # 2a. Subscribe new asset_ids to WS orderbook (non-blocking)
        if self._ws_client.is_connected:
            new_asset_ids = []
            for m in markets:
                for outcome in m.outcomes:
                    if outcome.token_id and outcome.token_id not in self._ws_client._subscribed_assets:
                        new_asset_ids.append(outcome.token_id)
                        self._token_to_market[outcome.token_id] = m.id
            if new_asset_ids:
                try:
                    await self._ws_client.subscribe(new_asset_ids)
                except Exception as exc:
                    logger.warning("ws_subscribe_failed", error=str(exc))

        # 2b. Fetch intelligence signals (GDELT + RSS, on slower cadence)
        external_signals: dict[str, dict[str, Any]] = {}
        if self._intelligence is not None:
            await self._fetch_intelligence_signals(markets, external_signals, now)

        # 2c. Fetch KG pattern signals from Obsidian vault
        await self._fetch_kg_signals(markets, external_signals)

        # 2d. Fetch Manifold cross-platform signals (on slower cadence)
        if self._manifold_service is not None:
            manifold_signals = await self._fetch_manifold_signals(markets, now)
            for mid, sigs in manifold_signals.items():
                external_signals.setdefault(mid, {}).update(sigs)

        # 2e. Inject live orderbook data from WS cache
        for m in markets:
            for outcome in m.outcomes:
                ob = self._orderbook_cache.get(outcome.token_id)
                if ob:
                    external_signals.setdefault(m.id, {})["orderbook_data"] = ob
                    break  # use the first outcome's orderbook (YES)

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
        exited_market_ids: set[str] = set()
        await self._manage_positions(
            market_by_id, valuations, result, now, exited_market_ids
        )

        # 5. Generate new signals (with market reference for horizon)
        signal_market_pairs: list[tuple[Signal, Market]] = []
        for market in markets:
            valuation = valuations.get(market.id)
            if not valuation:
                continue

            # Skip markets that were just exited this tick (prevent buy-sell-rebuy loop)
            if market.id in exited_market_ids:
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
                            signal_market_pairs.append((sig, market))
                except Exception as e:
                    result.errors.append(f"{strategy.name}: {e}")

        result.signals_generated = len(signal_market_pairs)

        # 5b. Priority scoring (Phase 10): sort by fee_adjusted_edge / days_to_resolution
        # Short-term high-edge trades execute first
        def _priority(pair: tuple[Signal, Market]) -> float:
            sig, mkt = pair
            edge = abs(sig.edge_amount) if sig.edge_amount else 0.0
            if mkt.end_date is not None:
                days = max(
                    0.1, (mkt.end_date - now).total_seconds() / 86400
                )
            else:
                days = 14.0  # unknown → treat as medium
            return edge / days

        signal_market_pairs.sort(key=_priority, reverse=True)

        # 5c. Populate Risk KB with market assessments
        if self._risk_kb is not None:
            for signal, mkt in signal_market_pairs:
                try:
                    edge = abs(signal.edge_amount) if signal.edge_amount else 0.0
                    if edge > 0.15:
                        risk_level = RiskLevel.LOW
                    elif edge > 0.05:
                        risk_level = RiskLevel.MEDIUM
                    else:
                        risk_level = RiskLevel.HIGH
                    await self._risk_kb.upsert(
                        MarketKnowledge(
                            market_id=mkt.id,
                            strategy_applied=signal.strategy,
                            risk_level=risk_level,
                            risk_reason=(
                                f"Edge: {edge:.3f},"
                                f" Confidence: {signal.confidence:.2f}"
                            ),
                        )
                    )
                except Exception as exc:
                    logger.debug("risk_kb_upsert_failed", error=str(exc))

        # 6. Risk check + Execute new orders (horizon-aware)
        balance = await self._executor.get_balance()
        for signal, mkt in signal_market_pairs:
            price = signal.market_price if signal.market_price > 0 else 0.5
            horizon: TimeHorizon | None = mkt.time_horizon if mkt.end_date else TimeHorizon.MEDIUM

            size_result = self._risk.size_position(signal, balance.available, price)

            risk_check = self._risk.check_order(
                signal, price, size_result.size_eur, time_horizon=horizon
            )
            if not risk_check.approved:
                result.orders_rejected += 1
                logger.info(
                    "order_rejected",
                    market_id=signal.market_id,
                    reason=risk_check.reason,
                    horizon=horizon.value if horizon else "unknown",
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
                    fill_cost = order_result.price * order_result.filled_size
                    self._risk.record_fill(
                        signal.token_id, fill_cost, time_horizon=horizon
                    )
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
                        "horizon": horizon.value if horizon else "unknown",
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
                        horizon=horizon.value if horizon else "unknown",
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
        exited_market_ids: set[str] | None = None,
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
                if exited_market_ids is not None:
                    exited_market_ids.add(market_id)

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
                    "horizon": "",
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

            # ── 2b. Mark near-resolution for exposure discount ──
            if market and market.end_date:
                hours_remaining = (market.end_date - now).total_seconds() / 3600
                price_near_resolved = pos.current_price > 0.90 or pos.current_price < 0.10
                if hours_remaining < 24 and price_near_resolved:
                    self._risk.mark_near_resolution(pos.token_id, True)
                else:
                    self._risk.mark_near_resolution(pos.token_id, False)

            # ── 3. Evaluate sell on secondary market ─────────────
            exit_decision = evaluate_exit(pos, market=market, valuation=valuation)
            if not exit_decision.should_exit:
                continue

            exit_order = build_exit_order(pos)
            original_size = pos.size
            try:
                order_result = await self._executor.execute(exit_order)
                if order_result.status == OrderStatus.FILLED:
                    # P&L realized by the CLOB client's _reduce_position
                    realized = (order_result.price - pos.avg_price) * order_result.filled_size
                    fully_closed = order_result.filled_size >= original_size - 0.001
                    result.realized_pnl += realized
                    self._circuit_breaker.record_trade_result(realized)

                    if fully_closed:
                        result.positions_closed += 1
                        self._risk.record_close(pos.token_id, realized)
                        if exited_market_ids is not None:
                            exited_market_ids.add(market_id)

                    await self._persist_trade({
                        "timestamp": now.isoformat(),
                        "market_id": market_id,
                        "strategy": "exit",
                        "side": str(exit_order.side),
                        "size_eur": round(order_result.filled_size * pos.avg_price, 2),
                        "shares": round(order_result.filled_size, 2),
                        "price": order_result.price,
                        "edge": 0.0,
                        "pnl": round(realized, 4),
                        "type": "close" if fully_closed else "partial_exit",
                        "horizon": "",
                        "reasoning": exit_decision.reason,
                    })

                    logger.info(
                        "position_sold",
                        market_id=market_id,
                        reason=exit_decision.reason,
                        entry=round(pos.avg_price, 4),
                        exit=round(order_result.price, 4),
                        realized_pnl=round(realized, 4),
                        fully_closed=fully_closed,
                        filled=round(order_result.filled_size, 2),
                        remaining=round(original_size - order_result.filled_size, 2),
                    )
            except Exception as e:
                result.errors.append(f"exit {pos.token_id}: {e}")

    async def _fetch_intelligence_signals(
        self,
        markets: list[Market],
        external_signals: dict[str, dict[str, Any]],
        now: datetime,
    ) -> None:
        """Fetch GDELT + RSS intelligence signals on a configurable cadence."""
        from app.core.yaml_config import app_config

        interval = app_config.intelligence.gdelt.poll_interval_minutes * 60
        if (
            self._last_intel_refresh is not None
            and (now - self._last_intel_refresh).total_seconds() < interval
        ):
            return

        try:
            report = await self._intelligence.tick()
            self._last_intel_refresh = now

            # Inject event_signal per market based on domain
            for market in markets:
                sig = self._intelligence.get_event_signal(market.category.value)
                if sig > 0:
                    external_signals.setdefault(market.id, {})["event_signal"] = sig

            logger.info(
                "intelligence_signals_fetched",
                anomalies=report.total_anomalies,
                gdelt_events=len(report.events),
                news_items=len(report.news_items),
            )
        except Exception as exc:
            logger.warning("intelligence_fetch_failed", error=str(exc))

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

    async def _ws_listener_loop(self) -> None:
        """Background loop: maintain WS connection and update orderbook cache."""
        try:
            await self._ws_client.connect()
        except Exception as exc:
            logger.warning("ws_connect_failed_background", error=str(exc))
            return

        try:
            async for msg in self._ws_client.listen():
                self._process_ws_message(msg)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.warning("ws_listener_error", error=str(exc))
        finally:
            await self._ws_client.disconnect()

    def _process_ws_message(self, msg: dict[str, Any]) -> None:
        """Parse WS message and update orderbook cache."""
        asset_id = msg.get("asset_id")
        if not asset_id:
            return

        bids_raw = msg.get("bids", [])
        asks_raw = msg.get("asks", [])

        bids = [
            OrderBookLevel(price=float(b["price"]), size=float(b["size"]))
            for b in bids_raw
            if "price" in b and "size" in b
        ]
        asks = [
            OrderBookLevel(price=float(a["price"]), size=float(a["size"]))
            for a in asks_raw
            if "price" in a and "size" in a
        ]

        spread = (asks[0].price - bids[0].price) if bids and asks else 0.0
        midpoint = (bids[0].price + asks[0].price) / 2 if bids and asks else 0.0
        market_id = self._token_to_market.get(asset_id, msg.get("market", ""))

        self._orderbook_cache[asset_id] = OrderBook(
            market_id=market_id,
            asset_id=asset_id,
            bids=bids,
            asks=asks,
            spread=round(spread, 4),
            midpoint=round(midpoint, 4),
        )

    async def _fetch_kg_signals(
        self,
        markets: list[Market],
        external_signals: dict[str, dict[str, Any]],
    ) -> None:
        """Fetch pattern KG signals from Obsidian vault via KnowledgeService."""
        if self._knowledge_service is None:
            return
        for market in markets:
            try:
                ctx = await self._knowledge_service.build_knowledge_context(
                    domain=market.category.value,
                    event_text=market.question,
                    keywords=market.tags[:5] if market.tags else None,
                )
                if ctx.composite_signal > 0:
                    external_signals.setdefault(market.id, {})[
                        "pattern_kg_signal"
                    ] = ctx.composite_signal
            except Exception as exc:
                logger.warning("kg_signal_failed", market_id=market.id, error=str(exc))

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
        # Start WS orderbook background listener
        self._ws_task = asyncio.create_task(self._ws_listener_loop())
        logger.info("engine_started", interval=interval_seconds)
        while self._running:
            try:
                await self.tick()
            except Exception as e:
                logger.error("tick_error", error=str(e))
            await asyncio.sleep(interval_seconds)
        # Cleanup WS background task
        if self._ws_task and not self._ws_task.done():
            self._ws_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._ws_task
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
