"""Tests for execution engine."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime, timedelta

import pytest

from app.execution.engine import ExecutionEngine
from app.knowledge.risk_kb import RiskKnowledgeBase, RiskLevel
from app.models.market import Market, MarketCategory, Outcome
from app.models.order import (
    Balance,
    OrderRequest,
    OrderResult,
    OrderSide,
    OrderStatus,
    Position,
)
from app.models.signal import Signal, SignalType
from app.models.valuation import Recommendation, ValuationResult
from app.risk.circuit_breaker import CircuitBreaker
from app.risk.manager import RiskManager
from app.strategies.registry import StrategyRegistry

# --- Fakes ---


class FakeExecutor:
    """Executor that always fills orders immediately."""

    def __init__(self, balance: float = 150.0) -> None:
        self._balance = balance
        self._orders: list[OrderRequest] = []

    async def execute(self, order: OrderRequest) -> OrderResult:
        self._orders.append(order)
        return OrderResult(
            order_id="fake-001",
            status=OrderStatus.FILLED,
            token_id=order.token_id,
            side=order.side,
            price=order.price,
            size=order.size,
            filled_size=order.size,
            is_simulated=True,
            timestamp=datetime.now(tz=UTC),
        )

    async def get_positions(self) -> list[Position]:
        return []

    async def get_balance(self) -> Balance:
        return Balance(total=self._balance, available=self._balance, locked=0.0)


class RejectingExecutor(FakeExecutor):
    """Executor that always rejects orders."""

    async def execute(self, order: OrderRequest) -> OrderResult:
        return OrderResult(
            order_id="fake-reject",
            status=OrderStatus.REJECTED,
            token_id=order.token_id,
            side=order.side,
            price=order.price,
            size=order.size,
            filled_size=0.0,
            is_simulated=True,
            timestamp=datetime.now(tz=UTC),
            error="Rejected by exchange",
        )


class ErrorExecutor(FakeExecutor):
    """Executor that raises on execute."""

    async def execute(self, order: OrderRequest) -> OrderResult:
        raise RuntimeError("Connection failed")


class FakeStrategy:
    """Strategy that always returns a BUY signal."""

    def __init__(self, name: str = "fake_strategy") -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def domain_filter(self) -> list[str]:
        return []

    async def evaluate(
        self,
        market: Market,
        valuation: ValuationResult,
        knowledge: object = None,
    ) -> Signal | None:
        return Signal(
            strategy=self._name,
            market_id=market.id,
            token_id=market.outcomes[0].token_id if market.outcomes else "tok-1",
            signal_type=SignalType.BUY,
            confidence=0.8,
            market_price=valuation.market_price,
            edge_amount=0.6,
            reasoning="Test signal",
        )


class MultiSignalStrategy:
    """Strategy that returns a list of signals (e.g. arbitrage two-legged)."""

    @property
    def name(self) -> str:
        return "multi_signal_strategy"

    @property
    def domain_filter(self) -> list[str]:
        return []

    async def evaluate(
        self,
        market: Market,
        valuation: ValuationResult,
        knowledge: object = None,
    ) -> list[Signal]:
        return [
            Signal(
                strategy=self.name,
                market_id=market.id,
                token_id="tok-yes",
                signal_type=SignalType.BUY,
                confidence=0.9,
                market_price=0.40,
                edge_amount=0.10,
                reasoning="Leg 1: buy YES",
            ),
            Signal(
                strategy=self.name,
                market_id=market.id,
                token_id="tok-no",
                signal_type=SignalType.BUY,
                confidence=0.9,
                market_price=0.50,
                edge_amount=0.10,
                reasoning="Leg 2: buy NO",
            ),
        ]


class ErrorStrategy:
    """Strategy that raises an exception."""

    @property
    def name(self) -> str:
        return "error_strategy"

    @property
    def domain_filter(self) -> list[str]:
        return []

    async def evaluate(
        self,
        market: Market,
        valuation: ValuationResult,
        knowledge: object = None,
    ) -> Signal | None:
        raise ValueError("Strategy failed")


class FakeValueEngine:
    """Value engine that returns a fixed valuation for every market."""

    def __init__(self) -> None:
        self.last_external_signals: dict[str, dict[str, float | None]] | None = None

    async def assess_batch(
        self,
        markets: list[Market],
        universe: list[Market] | None = None,
        external_signals: dict[str, dict[str, float | None]] | None = None,
    ) -> list[ValuationResult]:
        self.last_external_signals = external_signals
        return [
            ValuationResult(
                market_id=m.id,
                fair_value=0.65,
                market_price=0.50,
                edge=0.15,
                confidence=0.8,
                fee_adjusted_edge=0.15,
                recommendation=Recommendation.BUY,
            )
            for m in markets
        ]


# --- Helpers ---


def _make_market(market_id: str = "mkt-1") -> Market:
    return Market(
        id=market_id,
        question="Will X happen?",
        category=MarketCategory.POLITICS,
        outcomes=[Outcome(token_id="tok-1", outcome="Yes", price=0.5)],
        end_date=datetime.now(tz=UTC) + timedelta(days=1),  # SHORT horizon
    )


def _make_engine(
    executor: FakeExecutor | None = None,
    risk_manager: RiskManager | None = None,
    circuit_breaker: CircuitBreaker | None = None,
    registry: StrategyRegistry | None = None,
    value_engine: object = None,
) -> ExecutionEngine:
    if registry is None:
        registry = StrategyRegistry()
        strategy = FakeStrategy()
        registry.register(strategy)
    if circuit_breaker is None:
        circuit_breaker = CircuitBreaker()
        circuit_breaker.initialize(150.0)
    if risk_manager is None:
        risk_manager = RiskManager(capital=150.0)
    if executor is None:
        executor = FakeExecutor()
    return ExecutionEngine(
        executor=executor,
        risk_manager=risk_manager,
        circuit_breaker=circuit_breaker,
        strategy_registry=registry,
        value_engine=value_engine or FakeValueEngine(),
    )


# --- Tests ---


class TestTickEmpty:
    @pytest.mark.asyncio
    async def test_tick_with_empty_markets_returns_empty(self) -> None:
        engine = _make_engine()
        result = await engine.tick(markets=[])
        assert result.markets_scanned == 0
        assert result.signals_generated == 0
        assert result.orders_placed == 0

    @pytest.mark.asyncio
    async def test_tick_with_none_markets_and_no_service(self) -> None:
        engine = _make_engine()
        result = await engine.tick(markets=None)
        assert result.markets_scanned == 0


class TestCircuitBreakerIntegration:
    @pytest.mark.asyncio
    async def test_tick_skipped_when_circuit_breaker_tripped(self) -> None:
        cb = CircuitBreaker(max_consecutive_losses=1)
        cb.initialize(100.0)
        cb.record_trade_result(-10.0)  # trips
        assert cb.state.is_tripped is True

        engine = _make_engine(circuit_breaker=cb)
        result = await engine.tick(markets=[_make_market()])
        assert result.circuit_breaker_tripped is True
        assert result.markets_scanned == 0
        assert result.orders_placed == 0


class TestFullTick:
    @pytest.mark.asyncio
    async def test_tick_processes_markets_to_orders(self) -> None:
        executor = FakeExecutor()
        engine = _make_engine(executor=executor)
        market = _make_market()

        result = await engine.tick(markets=[market])
        assert result.markets_scanned == 1
        assert result.markets_assessed == 1
        assert result.signals_generated == 1
        assert result.orders_placed == 1
        assert len(executor._orders) == 1

    @pytest.mark.asyncio
    async def test_order_price_uses_market_price_not_edge(self) -> None:
        """Regression: order price must be the market price, not the edge amount."""
        executor = FakeExecutor()
        engine = _make_engine(executor=executor)
        market = _make_market()

        result = await engine.tick(markets=[market])
        assert result.orders_placed == 1
        order = executor._orders[0]
        # FakeValueEngine returns market_price=0.50, FakeStrategy forwards it
        # The order price must be the market price (0.50), NOT the edge (0.6)
        assert order.price == 0.50

    @pytest.mark.asyncio
    async def test_tick_rejects_order_when_risk_fails(self) -> None:
        # Use risk manager with zero positions allowed so it rejects
        risk = RiskManager(capital=150.0, max_positions=0)
        engine = _make_engine(risk_manager=risk)
        market = _make_market()

        result = await engine.tick(markets=[market])
        assert result.signals_generated == 1
        assert result.orders_rejected == 1
        assert result.orders_placed == 0

    @pytest.mark.asyncio
    async def test_tick_handles_multi_signal_strategy(self) -> None:
        """Engine must handle strategies returning list[Signal] (e.g. arbitrage)."""
        executor = FakeExecutor()
        registry = StrategyRegistry()
        registry.register(MultiSignalStrategy())  # type: ignore[arg-type]
        engine = _make_engine(executor=executor, registry=registry)
        market = _make_market()

        result = await engine.tick(markets=[market])
        assert result.signals_generated == 2
        assert result.orders_placed == 2
        assert len(executor._orders) == 2
        # Verify both legs have distinct token IDs
        token_ids = {o.token_id for o in executor._orders}
        assert token_ids == {"tok-yes", "tok-no"}

    @pytest.mark.asyncio
    async def test_tick_handles_strategy_exception(self) -> None:
        registry = StrategyRegistry()
        registry.register(ErrorStrategy())  # type: ignore[arg-type]
        engine = _make_engine(registry=registry)
        market = _make_market()

        result = await engine.tick(markets=[market])
        assert result.signals_generated == 0
        assert len(result.errors) == 1
        assert "error_strategy" in result.errors[0]

    @pytest.mark.asyncio
    async def test_tick_handles_executor_exception(self) -> None:
        executor = ErrorExecutor()
        engine = _make_engine(executor=executor)
        market = _make_market()

        result = await engine.tick(markets=[market])
        assert result.signals_generated == 1
        assert result.orders_rejected == 1
        assert any("execute" in e for e in result.errors)


class _PositionHoldingExecutor(FakeExecutor):
    """Executor that reports a configurable list of open positions.

    Used to simulate state carried across ticks: when get_positions() returns
    a non-empty list, the engine must dedup BUY signals on those token_ids.
    """

    def __init__(self, positions: list[Position], balance: float = 150.0) -> None:
        super().__init__(balance=balance)
        self._held: list[Position] = positions

    async def get_positions(self) -> list[Position]:
        return list(self._held)


class TestDuplicatePositionDedup:
    """Regression: BUG-1 — identical consecutive bets across ticks.

    Without the dedup guard, a strategy emits a BUY signal every tick and the
    engine routes it through the executor, merging into the existing position
    via weighted-average price (avg_price drift) and surfacing as duplicate
    "open" entries in the trade log on consecutive ticks.

    Fix: engine.tick() captures token_ids of currently-open positions after
    exit-management and drops BUY signals targeting any held token.
    """

    @pytest.mark.asyncio
    async def test_buy_signal_dropped_when_position_already_open(self) -> None:
        # Simulate state from a previous tick: position open on tok-1
        executor = _PositionHoldingExecutor(
            positions=[
                Position(
                    market_id="mkt-1",
                    token_id="tok-1",
                    side=OrderSide.BUY,
                    size=10.0,
                    avg_price=0.50,
                    current_price=0.50,
                )
            ]
        )
        engine = _make_engine(executor=executor)
        market = _make_market()  # FakeStrategy emits BUY on tok-1

        result = await engine.tick(markets=[market])

        assert result.signals_generated == 0
        assert result.orders_placed == 0
        assert len(executor._orders) == 0

    @pytest.mark.asyncio
    async def test_buy_signal_passes_when_no_position_open(self) -> None:
        # Sanity: no open positions → BUY proceeds normally
        executor = _PositionHoldingExecutor(positions=[])
        engine = _make_engine(executor=executor)
        market = _make_market()

        result = await engine.tick(markets=[market])

        assert result.signals_generated == 1
        assert result.orders_placed == 1

    @pytest.mark.asyncio
    async def test_dedup_is_per_token_not_per_market(self) -> None:
        # Holding a different token_id on the same market must not block
        # a BUY on a fresh outcome (precise dedup, not coarse over-blocking).
        executor = _PositionHoldingExecutor(
            positions=[
                Position(
                    market_id="mkt-1",
                    token_id="other-token",
                    side=OrderSide.BUY,
                    size=10.0,
                    avg_price=0.50,
                )
            ]
        )
        engine = _make_engine(executor=executor)
        market = _make_market()  # FakeStrategy emits BUY on tok-1

        result = await engine.tick(markets=[market])

        assert result.signals_generated == 1
        assert result.orders_placed == 1

    @pytest.mark.asyncio
    async def test_dust_position_does_not_block(self) -> None:
        # Effectively-closed position (size < 0.001) must not block new BUYs
        executor = _PositionHoldingExecutor(
            positions=[
                Position(
                    market_id="mkt-1",
                    token_id="tok-1",
                    side=OrderSide.BUY,
                    size=0.0005,
                    avg_price=0.50,
                )
            ]
        )
        engine = _make_engine(executor=executor)
        market = _make_market()

        result = await engine.tick(markets=[market])

        assert result.signals_generated == 1
        assert result.orders_placed == 1


class TestTradeLog:
    @pytest.mark.asyncio
    async def test_trade_log_populated_after_fill(self) -> None:
        engine = _make_engine()
        market = _make_market()

        await engine.tick(markets=[market])
        assert len(engine.trade_log) == 1
        entry = engine.trade_log[0]
        assert entry["market_id"] == "mkt-1"
        assert entry["strategy"] == "fake_strategy"


class TestTickCount:
    @pytest.mark.asyncio
    async def test_tick_count_increments(self) -> None:
        engine = _make_engine()
        assert engine.tick_count == 0

        await engine.tick(markets=[_make_market()])
        assert engine.tick_count == 1

        await engine.tick(markets=[_make_market()])
        assert engine.tick_count == 2


class TestRunStop:
    @pytest.mark.asyncio
    async def test_run_stop_lifecycle(self) -> None:
        engine = _make_engine()
        assert engine.is_running is False

        # Start engine with very short interval
        task = asyncio.create_task(engine.run(interval_seconds=0))
        # Give the loop time to do at least one tick
        await asyncio.sleep(0.1)

        assert engine.is_running is True
        await engine.stop()
        # Allow the loop to exit
        await asyncio.sleep(0.1)
        assert engine.is_running is False
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


# --- Manifold integration fakes ---


class FakeCrossPlatformSignal:
    """Minimal stand-in for CrossPlatformSignal with signal_value."""

    def __init__(self, signal_value: float) -> None:
        self.signal_value = signal_value


class FakeManifoldService:
    """Manifold service that returns deterministic signals for testing."""

    def __init__(self, signals: dict[str, FakeCrossPlatformSignal] | None = None) -> None:
        self._signals = signals or {}
        self.call_count = 0

    async def get_signals_batch(
        self, markets: list[Market]
    ) -> dict[str, FakeCrossPlatformSignal]:
        self.call_count += 1
        return self._signals


class ErrorManifoldService:
    """Manifold service that always raises."""

    call_count: int = 0

    async def get_signals_batch(
        self, markets: list[Market]
    ) -> dict[str, FakeCrossPlatformSignal]:
        self.call_count += 1
        raise RuntimeError("Manifold API unavailable")


# --- Manifold integration tests ---


class TestManifoldIntegration:
    @pytest.mark.asyncio
    async def test_manifold_signals_passed_to_value_engine(self) -> None:
        """When manifold_service is provided, external_signals are forwarded to assess_batch."""
        manifold_svc = FakeManifoldService(
            signals={"mkt-1": FakeCrossPlatformSignal(signal_value=0.72)}
        )
        value_engine = FakeValueEngine()
        engine = ExecutionEngine(
            executor=FakeExecutor(),
            risk_manager=RiskManager(capital=150.0),
            circuit_breaker=_make_cb(),
            strategy_registry=_make_registry(),
            value_engine=value_engine,
            manifold_service=manifold_svc,
        )
        market = _make_market()

        await engine.tick(markets=[market])

        assert manifold_svc.call_count == 1
        assert value_engine.last_external_signals is not None
        assert "mkt-1" in value_engine.last_external_signals
        assert value_engine.last_external_signals["mkt-1"]["cross_platform_signal"] == 0.72

    @pytest.mark.asyncio
    async def test_manifold_not_called_without_service(self) -> None:
        """When manifold_service is None, no external signals are passed."""
        value_engine = FakeValueEngine()
        engine = ExecutionEngine(
            executor=FakeExecutor(),
            risk_manager=RiskManager(capital=150.0),
            circuit_breaker=_make_cb(),
            strategy_registry=_make_registry(),
            value_engine=value_engine,
        )

        await engine.tick(markets=[_make_market()])
        # No external signals → assess_batch called with None
        assert value_engine.last_external_signals is None

    @pytest.mark.asyncio
    async def test_manifold_respects_cadence(self) -> None:
        """Manifold is polled once, then skipped until the cadence interval elapses."""
        manifold_svc = FakeManifoldService(signals={})
        engine = ExecutionEngine(
            executor=FakeExecutor(),
            risk_manager=RiskManager(capital=150.0),
            circuit_breaker=_make_cb(),
            strategy_registry=_make_registry(),
            value_engine=FakeValueEngine(),
            manifold_service=manifold_svc,
        )
        market = _make_market()

        # First tick: manifold is called
        await engine.tick(markets=[market])
        assert manifold_svc.call_count == 1

        # Second tick: within cadence window, manifold should NOT be called again
        await engine.tick(markets=[market])
        assert manifold_svc.call_count == 1

    @pytest.mark.asyncio
    async def test_manifold_error_does_not_break_tick(self) -> None:
        """If manifold raises, the tick completes normally without signals."""
        error_svc = ErrorManifoldService()
        value_engine = FakeValueEngine()
        engine = ExecutionEngine(
            executor=FakeExecutor(),
            risk_manager=RiskManager(capital=150.0),
            circuit_breaker=_make_cb(),
            strategy_registry=_make_registry(),
            value_engine=value_engine,
            manifold_service=error_svc,
        )
        market = _make_market()

        result = await engine.tick(markets=[market])
        assert error_svc.call_count == 1
        # Tick should still complete successfully
        assert result.markets_scanned == 1
        assert result.markets_assessed == 1
        # No external signals passed (error caught)
        assert value_engine.last_external_signals is None

    @pytest.mark.asyncio
    async def test_manifold_empty_signals_passes_none(self) -> None:
        """Empty external_signals dict should be passed as None to assess_batch."""
        manifold_svc = FakeManifoldService(signals={})
        value_engine = FakeValueEngine()
        engine = ExecutionEngine(
            executor=FakeExecutor(),
            risk_manager=RiskManager(capital=150.0),
            circuit_breaker=_make_cb(),
            strategy_registry=_make_registry(),
            value_engine=value_engine,
            manifold_service=manifold_svc,
        )

        await engine.tick(markets=[_make_market()])
        # Empty dict is falsy → external_signals or None → None
        assert value_engine.last_external_signals is None


# --- Small helpers for test construction ---


def _make_cb() -> CircuitBreaker:
    cb = CircuitBreaker()
    cb.initialize(150.0)
    return cb


def _make_registry() -> StrategyRegistry:
    registry = StrategyRegistry()
    registry.register(FakeStrategy())
    return registry


# --- Partial exit tests ---


class PositionAwareExecutor:
    """Executor that tracks positions and supports partial fill for sells."""

    def __init__(
        self,
        balance: float = 150.0,
        positions: list[Position] | None = None,
        sell_fill_fraction: float = 1.0,
    ) -> None:
        self._balance = balance
        self._positions: list[Position] = list(positions) if positions else []
        self._orders: list[OrderRequest] = []
        self._sell_fill_fraction = sell_fill_fraction

    async def execute(self, order: OrderRequest) -> OrderResult:
        self._orders.append(order)
        if order.side == OrderSide.SELL:
            filled = order.size * self._sell_fill_fraction
            # Remove position if fully sold
            if self._sell_fill_fraction >= 1.0:
                self._positions = [
                    p for p in self._positions if p.token_id != order.token_id
                ]
            else:
                for p in self._positions:
                    if p.token_id == order.token_id:
                        p.size -= filled
                        break
            return OrderResult(
                order_id="fake-sell",
                status=OrderStatus.FILLED,
                token_id=order.token_id,
                side=order.side,
                price=order.price,
                size=order.size,
                filled_size=filled,
                is_simulated=True,
                timestamp=datetime.now(tz=UTC),
            )
        return OrderResult(
            order_id="fake-buy",
            status=OrderStatus.FILLED,
            token_id=order.token_id,
            side=order.side,
            price=order.price,
            size=order.size,
            filled_size=order.size,
            is_simulated=True,
            timestamp=datetime.now(tz=UTC),
        )

    async def get_positions(self) -> list[Position]:
        return list(self._positions)

    async def get_balance(self) -> Balance:
        return Balance(total=self._balance, available=self._balance, locked=0.0)


class HoldStrategy:
    """Strategy that always returns HOLD (no signal)."""

    @property
    def name(self) -> str:
        return "hold_strategy"

    @property
    def domain_filter(self) -> list[str]:
        return []

    async def evaluate(
        self,
        market: Market,
        valuation: ValuationResult,
        knowledge: object = None,
    ) -> Signal | None:
        return None


class TestPartialExitFill:
    """Verify engine handles partial exit fills correctly."""

    @pytest.mark.asyncio
    async def test_full_exit_logs_close(self) -> None:
        """A full exit should log type=close and count as positions_closed."""
        pos = Position(
            market_id="mkt-1",
            token_id="tok-1",
            side=OrderSide.BUY,
            size=10.0,
            avg_price=0.40,
            current_price=0.80,  # high enough for take-profit
            unrealized_pnl=4.0,
        )
        executor = PositionAwareExecutor(
            positions=[pos], sell_fill_fraction=1.0
        )
        # Use HoldStrategy to prevent new buys
        registry = StrategyRegistry()
        registry.register(HoldStrategy())

        # Value engine that returns edge-reversed valuation to trigger exit
        class ExitValuation:
            async def assess_batch(
                self,
                markets: list[Market],
                universe: list[Market] | None = None,
                external_signals: object = None,
            ) -> list[ValuationResult]:
                return [
                    ValuationResult(
                        market_id=m.id,
                        fair_value=0.30,
                        market_price=0.80,
                        edge=-0.50,
                        confidence=0.8,
                        fee_adjusted_edge=-0.50,
                        recommendation=Recommendation.SELL,
                    )
                    for m in markets
                ]

        engine = ExecutionEngine(
            executor=executor,
            risk_manager=RiskManager(capital=150.0),
            circuit_breaker=_make_cb(),
            strategy_registry=registry,
            value_engine=ExitValuation(),
        )
        market = _make_market()
        result = await engine.tick(markets=[market])

        assert result.positions_closed == 1
        # Trade log should have a "close" entry
        close_trades = [t for t in engine.trade_log if t.get("type") == "close"]
        assert len(close_trades) == 1

    @pytest.mark.asyncio
    async def test_partial_exit_logs_partial_exit(self) -> None:
        """A partial exit should log type=partial_exit, not count as closed."""
        pos = Position(
            market_id="mkt-1",
            token_id="tok-1",
            side=OrderSide.BUY,
            size=10.0,
            avg_price=0.40,
            current_price=0.80,
            unrealized_pnl=4.0,
        )
        executor = PositionAwareExecutor(
            positions=[pos], sell_fill_fraction=0.5  # only 50% fills
        )
        registry = StrategyRegistry()
        registry.register(HoldStrategy())

        class ExitValuation:
            async def assess_batch(
                self,
                markets: list[Market],
                universe: list[Market] | None = None,
                external_signals: object = None,
            ) -> list[ValuationResult]:
                return [
                    ValuationResult(
                        market_id=m.id,
                        fair_value=0.30,
                        market_price=0.80,
                        edge=-0.50,
                        confidence=0.8,
                        fee_adjusted_edge=-0.50,
                        recommendation=Recommendation.SELL,
                    )
                    for m in markets
                ]

        engine = ExecutionEngine(
            executor=executor,
            risk_manager=RiskManager(capital=150.0),
            circuit_breaker=_make_cb(),
            strategy_registry=registry,
            value_engine=ExitValuation(),
        )
        market = _make_market()
        result = await engine.tick(markets=[market])

        # Partial fill should NOT count as a closed position
        assert result.positions_closed == 0
        # But realized P&L should still be recorded
        assert result.realized_pnl != 0.0
        # Trade log should have a "partial_exit" entry, not "close"
        partial_trades = [
            t for t in engine.trade_log if t.get("type") == "partial_exit"
        ]
        assert len(partial_trades) == 1
        close_trades = [t for t in engine.trade_log if t.get("type") == "close"]
        assert len(close_trades) == 0

    @pytest.mark.asyncio
    async def test_no_position_rebuy_in_same_tick(self) -> None:
        """R2: After a full exit, the engine must NOT rebuy in the same tick.

        The exited_market_ids mechanism blocks new signals for markets
        that were just closed, preventing buy-sell-rebuy loops.
        """
        pos = Position(
            market_id="mkt-1",
            token_id="tok-1",
            side=OrderSide.BUY,
            size=10.0,
            avg_price=0.40,
            current_price=0.80,  # high enough for take-profit
            unrealized_pnl=4.0,
        )
        executor = PositionAwareExecutor(
            positions=[pos], sell_fill_fraction=1.0  # full exit
        )
        # Use FakeStrategy that would BUY this market if allowed
        registry = _make_registry()

        class ExitValuation:
            async def assess_batch(
                self,
                markets: list[Market],
                universe: list[Market] | None = None,
                external_signals: object = None,
            ) -> list[ValuationResult]:
                return [
                    ValuationResult(
                        market_id=m.id,
                        fair_value=0.30,
                        market_price=0.80,
                        edge=-0.50,
                        confidence=0.8,
                        fee_adjusted_edge=-0.50,
                        recommendation=Recommendation.SELL,
                    )
                    for m in markets
                ]

        engine = ExecutionEngine(
            executor=executor,
            risk_manager=RiskManager(capital=150.0),
            circuit_breaker=_make_cb(),
            strategy_registry=registry,
            value_engine=ExitValuation(),
        )
        market = _make_market()
        result = await engine.tick(markets=[market])

        # Position should have been closed
        assert result.positions_closed >= 1
        # No new BUY orders should have been placed (rebuy blocked)
        assert result.orders_placed == 0

    @pytest.mark.asyncio
    async def test_partial_exit_does_not_block_reevaluation(self) -> None:
        """A partial exit should NOT add market to exited_market_ids.

        We hold a position on tok-1 (partially exited this tick) and have a
        strategy emit on tok-fresh in the same market. If exited_market_ids
        had been over-populated by the partial exit, no signal would be
        generated. The dedup guard (BUG-1) is per-token, so a BUY on a
        different token in the same market correctly passes through.
        """
        pos = Position(
            market_id="mkt-1",
            token_id="tok-1",
            side=OrderSide.BUY,
            size=10.0,
            avg_price=0.40,
            current_price=0.80,
            unrealized_pnl=4.0,
        )
        executor = PositionAwareExecutor(
            positions=[pos], sell_fill_fraction=0.5
        )

        # Reuse FakeStrategy's enabled name but override evaluate to emit on
        # a fresh token (tok-fresh) so dedup doesn't block this test path.
        class FreshTokenStrategy(FakeStrategy):
            async def evaluate(  # type: ignore[override]
                self,
                market: Market,
                valuation: ValuationResult,
                knowledge: object = None,
            ) -> Signal:
                return Signal(
                    strategy=self.name,
                    market_id=market.id,
                    token_id="tok-fresh",
                    signal_type=SignalType.BUY,
                    confidence=0.8,
                    market_price=valuation.market_price,
                    edge_amount=0.10,
                    reasoning="Same-market different-outcome BUY",
                )

        registry = StrategyRegistry()
        registry.register(FreshTokenStrategy())  # type: ignore[arg-type]

        class ExitValuation:
            async def assess_batch(
                self,
                markets: list[Market],
                universe: list[Market] | None = None,
                external_signals: object = None,
            ) -> list[ValuationResult]:
                return [
                    ValuationResult(
                        market_id=m.id,
                        fair_value=0.30,
                        market_price=0.80,
                        edge=-0.50,
                        confidence=0.8,
                        fee_adjusted_edge=-0.50,
                        recommendation=Recommendation.SELL,
                    )
                    for m in markets
                ]

        engine = ExecutionEngine(
            executor=executor,
            risk_manager=RiskManager(capital=150.0),
            circuit_breaker=_make_cb(),
            strategy_registry=registry,
            value_engine=ExitValuation(),
        )
        market = _make_market()
        result = await engine.tick(markets=[market])

        # Partial exit on tok-1 must not block strategies from generating
        # signals on a different outcome (tok-fresh) in the same market.
        assert result.signals_generated > 0


# --- Risk KB integration tests ---


class TestRiskKBIntegration:
    @pytest.mark.asyncio
    async def test_risk_kb_populated_during_tick(self) -> None:
        """Risk KB should receive upserts for each signal during tick."""
        risk_kb = RiskKnowledgeBase(db_path=":memory:")
        await risk_kb.init()

        engine = ExecutionEngine(
            executor=FakeExecutor(),
            risk_manager=RiskManager(capital=150.0),
            circuit_breaker=_make_cb(),
            strategy_registry=_make_registry(),
            value_engine=FakeValueEngine(),
            risk_kb=risk_kb,
        )
        market = _make_market()

        result = await engine.tick(markets=[market])
        assert result.signals_generated == 1

        # Verify the KB was populated
        record = await risk_kb.get("mkt-1")
        assert record is not None
        assert record.strategy_applied == "fake_strategy"
        assert record.risk_level == RiskLevel.LOW  # edge=0.6 > 0.15
        assert "Edge: 0.600" in record.risk_reason
        assert "Confidence: 0.80" in record.risk_reason

        await risk_kb.close()

    @pytest.mark.asyncio
    async def test_risk_kb_edge_thresholds(self) -> None:
        """Verify correct risk levels for different edge amounts."""
        risk_kb = RiskKnowledgeBase(db_path=":memory:")
        await risk_kb.init()

        # Strategy returning medium edge (0.10)
        class MediumEdgeStrategy:
            @property
            def name(self) -> str:
                return "medium_edge"

            @property
            def domain_filter(self) -> list[str]:
                return []

            async def evaluate(
                self,
                market: Market,
                valuation: ValuationResult,
                knowledge: object = None,
            ) -> Signal | None:
                return Signal(
                    strategy=self.name,
                    market_id=market.id,
                    token_id="tok-1",
                    signal_type=SignalType.BUY,
                    confidence=0.7,
                    market_price=0.50,
                    edge_amount=0.10,
                    reasoning="Medium edge",
                )

        registry = StrategyRegistry()
        registry.register(MediumEdgeStrategy())  # type: ignore[arg-type]

        engine = ExecutionEngine(
            executor=FakeExecutor(),
            risk_manager=RiskManager(capital=150.0),
            circuit_breaker=_make_cb(),
            strategy_registry=registry,
            value_engine=FakeValueEngine(),
            risk_kb=risk_kb,
        )

        await engine.tick(markets=[_make_market()])
        record = await risk_kb.get("mkt-1")
        assert record is not None
        assert record.risk_level == RiskLevel.MEDIUM  # 0.05 < 0.10 <= 0.15

        await risk_kb.close()

    @pytest.mark.asyncio
    async def test_risk_kb_none_does_not_break_tick(self) -> None:
        """When risk_kb is None, tick should work normally."""
        engine = ExecutionEngine(
            executor=FakeExecutor(),
            risk_manager=RiskManager(capital=150.0),
            circuit_breaker=_make_cb(),
            strategy_registry=_make_registry(),
            value_engine=FakeValueEngine(),
            risk_kb=None,
        )

        result = await engine.tick(markets=[_make_market()])
        assert result.signals_generated == 1
        assert result.orders_placed == 1

    @pytest.mark.asyncio
    async def test_risk_kb_error_does_not_break_tick(self) -> None:
        """If risk_kb.upsert raises, the tick should still complete."""

        class BrokenKB:
            async def upsert(self, knowledge: object) -> None:
                raise RuntimeError("DB write failed")

        engine = ExecutionEngine(
            executor=FakeExecutor(),
            risk_manager=RiskManager(capital=150.0),
            circuit_breaker=_make_cb(),
            strategy_registry=_make_registry(),
            value_engine=FakeValueEngine(),
            risk_kb=BrokenKB(),
        )

        result = await engine.tick(markets=[_make_market()])
        # Tick should complete normally despite KB errors
        assert result.signals_generated == 1
        assert result.orders_placed == 1


# --- BUG-1 dedup hardening regression tests (commit d0c8c36) ---


class _CountingGetPositionsExecutor(FakeExecutor):
    """Executor whose get_positions() can be configured per-call.

    side_effects is a list consumed in order; each entry is either a list of
    Positions to return, or an Exception instance to raise. Records the number
    of get_positions() calls in self.calls.
    """

    def __init__(
        self,
        side_effects: list[list[Position] | Exception],
        balance: float = 150.0,
    ) -> None:
        super().__init__(balance=balance)
        self._side_effects = list(side_effects)
        self.calls = 0

    async def get_positions(self) -> list[Position]:
        self.calls += 1
        if not self._side_effects:
            return []
        effect = self._side_effects.pop(0)
        if isinstance(effect, Exception):
            raise effect
        return list(effect)


class _AlwaysRaisingPositionsExecutor(FakeExecutor):
    """get_positions() always raises. Records call count."""

    def __init__(self, exc: Exception, balance: float = 150.0) -> None:
        super().__init__(balance=balance)
        self._exc = exc
        self.calls = 0

    async def get_positions(self) -> list[Position]:
        self.calls += 1
        raise self._exc


class _SpyStrategy(FakeStrategy):
    """FakeStrategy that records whether evaluate() was called.

    Uses the default name "fake_strategy" so it falls under the autouse
    yaml-config fixture's enabled list — see tests/test_execution/conftest.py.
    """

    def __init__(self) -> None:
        super().__init__(name="fake_strategy")
        self.evaluate_calls = 0

    async def evaluate(  # type: ignore[override]
        self,
        market: Market,
        valuation: ValuationResult,
        knowledge: object = None,
    ) -> Signal | None:
        self.evaluate_calls += 1
        return await super().evaluate(market, valuation, knowledge)


class TestDedupGuardFailClosed:
    """Regression tests for BUG-1 dedup BUY guard hardening (commit d0c8c36).

    Before the fix, a transient ``executor.get_positions()`` failure caused
    the engine to fail OPEN: the dedup set would silently be empty and any
    BUY signal would slip through, including ones for tokens already held
    (causing duplicate consecutive bets — the original BUG-1 symptom).

    After the fix, ``_fetch_open_position_token_ids`` retries up to 3 times
    with 100ms backoff. On exhaustion it returns ``None`` and ``tick()``
    skips the entire signal-generation phase (fail CLOSED).
    """

    async def test_fetch_open_position_token_ids_succeeds_first_try(self) -> None:
        executor = _CountingGetPositionsExecutor(
            side_effects=[
                [
                    Position(
                        market_id="mkt-1",
                        token_id="t1",
                        side=OrderSide.BUY,
                        size=10.0,
                        avg_price=0.50,
                    ),
                    Position(
                        market_id="mkt-1",
                        token_id="t2",
                        side=OrderSide.BUY,
                        size=0.0005,  # below MIN_OPEN_POSITION_SIZE → dust
                        avg_price=0.50,
                    ),
                ]
            ]
        )
        engine = _make_engine(executor=executor)

        result = await engine._fetch_open_position_token_ids()

        assert result == {"t1"}  # t2 filtered as dust
        assert executor.calls == 1

    async def test_fetch_open_position_token_ids_recovers_on_retry(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Spy on asyncio.sleep imported in the engine module to assert backoff
        sleep_calls: list[float] = []

        async def spy_sleep(seconds: float) -> None:
            sleep_calls.append(seconds)

        from app.execution import engine as engine_module
        monkeypatch.setattr(engine_module.asyncio, "sleep", spy_sleep)

        executor = _CountingGetPositionsExecutor(
            side_effects=[
                RuntimeError("transient"),
                [
                    Position(
                        market_id="mkt-1",
                        token_id="t1",
                        side=OrderSide.BUY,
                        size=5.0,
                        avg_price=0.50,
                    )
                ],
            ]
        )
        engine = _make_engine(executor=executor)

        result = await engine._fetch_open_position_token_ids()

        assert result == {"t1"}
        assert executor.calls == 2
        # Exactly one sleep between attempt 1 (failure) and attempt 2 (success)
        assert sleep_calls == [0.1]

    async def test_fetch_open_position_token_ids_returns_none_after_exhaustion(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sleep_calls: list[float] = []

        async def spy_sleep(seconds: float) -> None:
            sleep_calls.append(seconds)

        from app.execution import engine as engine_module
        monkeypatch.setattr(engine_module.asyncio, "sleep", spy_sleep)

        executor = _AlwaysRaisingPositionsExecutor(
            exc=RuntimeError("permanent")
        )
        engine = _make_engine(executor=executor)

        result = await engine._fetch_open_position_token_ids()

        assert result is None
        assert executor.calls == 3
        # Sleeps occur between attempts only — not after the final failure
        assert sleep_calls == [0.1, 0.1]

    async def test_tick_skips_signals_when_dedup_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Speed up the test by stubbing asyncio.sleep used by the helper
        from app.execution import engine as engine_module
        monkeypatch.setattr(engine_module.asyncio, "sleep", _no_sleep)

        spy = _SpyStrategy()
        registry = StrategyRegistry()
        registry.register(spy)  # type: ignore[arg-type]

        # _manage_positions calls get_positions() once BEFORE the dedup
        # guard. Allow that call to succeed (no positions to manage) so the
        # tick reaches the guard; subsequent calls (the dedup retries) all
        # raise — exhausting retries → fail CLOSED.
        executor = _CountingGetPositionsExecutor(
            side_effects=[
                [],  # call 1: _manage_positions (no positions)
                RuntimeError("attempt 1 broken"),
                RuntimeError("attempt 2 broken"),
                RuntimeError("attempt 3 broken"),
            ]
        )
        engine = _make_engine(executor=executor, registry=registry)

        result = await engine.tick(markets=[_make_market()])

        # Signal generation phase was skipped entirely
        assert result.signals_generated == 0
        assert result.orders_placed == 0
        # Strategy.evaluate() must NOT have been invoked under fail-closed
        assert spy.evaluate_calls == 0
        # An error was recorded for observability
        assert any(
            "dedup" in err.lower() or "signals_skipped" in err.lower()
            for err in result.errors
        ), f"expected dedup-skip error in {result.errors}"
        # 1 from _manage_positions + 3 retries from dedup helper = 4
        assert executor.calls == 4, (
            f"expected 4 get_positions calls "
            f"(1 from _manage_positions + 3 retries from dedup helper), "
            f"got {executor.calls}"
        )

    async def test_tick_executes_normally_when_dedup_succeeds(self) -> None:
        """Positive control: with a working get_positions(), held tokens are
        filtered and fresh tokens go through. Mixes one held + one fresh
        token in the same tick to verify per-token dedup precision.

        Uses MultiSignalStrategy (already in the autouse-enabled list) which
        emits 2 BUYs per market on tok-yes / tok-no — held_token = "tok-yes"
        so only the tok-no leg should pass.
        """
        executor = _PositionHoldingExecutor(
            positions=[
                Position(
                    market_id="mkt-1",
                    token_id="tok-yes",  # held → leg 1 dropped
                    side=OrderSide.BUY,
                    size=5.0,
                    avg_price=0.40,
                )
            ]
        )
        registry = StrategyRegistry()
        registry.register(MultiSignalStrategy())  # type: ignore[arg-type]
        engine = _make_engine(executor=executor, registry=registry)
        market = _make_market()

        result = await engine.tick(markets=[market])

        # Of the 2 BUYs MultiSignalStrategy emits, only tok-no passes
        # (tok-yes is held → dropped).
        assert result.signals_generated == 1
        assert result.orders_placed == 1
        assert len(executor._orders) == 1
        assert executor._orders[0].token_id == "tok-no"

    def test_min_open_position_size_constant_applied_at_fully_closed(self) -> None:
        """The MIN_OPEN_POSITION_SIZE constant must be referenced in
        _manage_positions for the fully_closed exit detection (so the dust
        threshold stays in sync with the dedup guard).
        """
        import inspect

        from app.execution import engine as engine_module

        source = inspect.getsource(engine_module.ExecutionEngine._manage_positions)
        assert "MIN_OPEN_POSITION_SIZE" in source, (
            "_manage_positions must use MIN_OPEN_POSITION_SIZE constant "
            "for the fully_closed check (no magic 0.001)"
        )
        # Sanity: the constant exists at module level with the documented value
        assert engine_module.MIN_OPEN_POSITION_SIZE == 0.001


async def _no_sleep(seconds: float) -> None:
    """Drop-in replacement for asyncio.sleep used by tests that don't want
    real backoff delays slowing down the suite.
    """
    return None
