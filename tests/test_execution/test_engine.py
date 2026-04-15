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
        """A partial exit should NOT add market to exited_market_ids."""
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
        # Use a strategy that generates BUY signals to check exited_market_ids
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

        # Partial exit: market should NOT be in exited_market_ids
        # so strategies can still generate signals (signals_generated > 0)
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
