"""Tests for execution engine."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime

import pytest

from app.execution.engine import ExecutionEngine
from app.models.market import Market, MarketCategory, Outcome
from app.models.order import (
    Balance,
    OrderRequest,
    OrderResult,
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

    async def assess_batch(
        self, markets: list[Market], universe: list[Market] | None = None
    ) -> list[ValuationResult]:
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
