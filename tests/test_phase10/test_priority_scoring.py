"""Tests for Phase 10: priority scoring in execution engine."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.execution.engine import ExecutionEngine
from app.models.market import Market, MarketCategory, MarketStatus, Outcome
from app.models.order import Balance, OrderRequest, OrderResult, OrderStatus
from app.models.signal import Signal, SignalType
from app.models.valuation import Recommendation, ValuationResult
from app.risk.circuit_breaker import CircuitBreaker
from app.risk.manager import RiskManager
from app.strategies.registry import StrategyRegistry


# --- Fakes ---


class FakeExecutor:
    def __init__(self, balance: float = 150.0) -> None:
        self._balance = balance
        self.orders: list[OrderRequest] = []

    async def execute(self, order: OrderRequest) -> OrderResult:
        self.orders.append(order)
        return OrderResult(
            order_id="f-001",
            status=OrderStatus.FILLED,
            token_id=order.token_id,
            side=order.side,
            price=order.price,
            size=order.size,
            filled_size=order.size,
            is_simulated=True,
            timestamp=datetime.now(tz=UTC),
        )

    async def get_positions(self) -> list:
        return []

    async def get_balance(self) -> Balance:
        return Balance(total=self._balance, available=self._balance, locked=0.0)


class PriorityStrategy:
    """Strategy that emits a signal with the given edge for every market."""

    def __init__(self, edge: float = 0.06) -> None:
        self._edge = edge

    @property
    def name(self) -> str:
        return "priority_test"

    @property
    def domain_filter(self) -> list[str]:
        return []

    async def evaluate(self, market: Market, valuation: ValuationResult, **kw: object) -> Signal:
        return Signal(
            strategy=self.name,
            market_id=market.id,
            token_id=market.outcomes[0].token_id,
            signal_type=SignalType.BUY,
            confidence=0.8,
            market_price=valuation.market_price,
            edge_amount=self._edge,
            reasoning="test",
        )


def _make_market(
    market_id: str,
    token_id: str,
    days_to_resolution: float,
    yes_price: float = 0.5,
) -> Market:
    return Market(
        id=market_id,
        question=f"Market {market_id}?",
        category=MarketCategory.POLITICS,
        status=MarketStatus.ACTIVE,
        outcomes=[
            Outcome(token_id=token_id, outcome="Yes", price=yes_price),
            Outcome(token_id=f"{token_id}-no", outcome="No", price=1.0 - yes_price),
        ],
        end_date=datetime.now(tz=UTC) + timedelta(days=days_to_resolution),
        volume=10000.0,
        liquidity=5000.0,
    )


def _make_valuation(market_id: str, market_price: float = 0.5) -> ValuationResult:
    return ValuationResult(
        market_id=market_id,
        fair_value=0.6,
        market_price=market_price,
        edge=0.1,
        confidence=0.8,
        fee_adjusted_edge=0.06,
        recommendation=Recommendation.BUY,
    )


@pytest.mark.asyncio
async def test_priority_scoring_short_term_first() -> None:
    """Short-term trades should execute before long-term, even with same edge."""
    executor = FakeExecutor()
    registry = StrategyRegistry()
    registry.register(PriorityStrategy(edge=0.06))

    engine = ExecutionEngine(
        executor=executor,
        risk_manager=RiskManager(
            capital=500.0,
            max_exposure_pct=90.0,
            max_single_position_eur=50.0,
            daily_loss_limit_eur=100.0,
            max_positions=25,
        ),
        circuit_breaker=CircuitBreaker(),
        strategy_registry=registry,
    )

    # Market A: 2 days to resolution (short)
    # Market B: 30 days to resolution (long)
    market_short = _make_market("m-short", "tok-short", days_to_resolution=2)
    market_long = _make_market("m-long", "tok-long", days_to_resolution=30)

    # Feed in long first — engine should reorder by priority
    engine._value_engine = None  # skip assess, we inject valuations manually

    # We'll test via the signal sorting in tick() by providing pre-assessed valuations
    # through a fake value engine
    class FakeVAE:
        async def assess_batch(self, markets, **kw):
            return [_make_valuation(m.id) for m in markets]

    engine._value_engine = FakeVAE()

    result = await engine.tick(markets=[market_long, market_short])

    # Both should be executed (large capital)
    assert result.orders_placed == 2

    # Short-term market should be executed FIRST (higher priority)
    assert executor.orders[0].token_id == "tok-short"
    assert executor.orders[1].token_id == "tok-long"


@pytest.mark.asyncio
async def test_priority_scoring_higher_edge_over_time_wins() -> None:
    """Priority = edge / days. Higher edge with same time wins."""
    executor = FakeExecutor()
    registry = StrategyRegistry()

    class HighEdgeStrategy:
        @property
        def name(self) -> str:
            return "high_edge"

        @property
        def domain_filter(self) -> list[str]:
            return []

        async def evaluate(self, market, valuation, **kw):
            # Give different edges per market
            edge = 0.10 if market.id == "m-high" else 0.03
            return Signal(
                strategy=self.name,
                market_id=market.id,
                token_id=market.outcomes[0].token_id,
                signal_type=SignalType.BUY,
                confidence=0.8,
                market_price=valuation.market_price,
                edge_amount=edge,
                reasoning="test",
            )

    registry.register(HighEdgeStrategy())

    engine = ExecutionEngine(
        executor=executor,
        risk_manager=RiskManager(
            capital=500.0, max_exposure_pct=90.0,
            max_single_position_eur=50.0, daily_loss_limit_eur=100.0,
        ),
        circuit_breaker=CircuitBreaker(),
        strategy_registry=registry,
    )

    # Both markets have 5 days, but different edges
    m_high = _make_market("m-high", "tok-high", days_to_resolution=5)
    m_low = _make_market("m-low", "tok-low", days_to_resolution=5)

    class FakeVAE:
        async def assess_batch(self, markets, **kw):
            return [_make_valuation(m.id) for m in markets]

    engine._value_engine = FakeVAE()
    result = await engine.tick(markets=[m_low, m_high])

    assert result.orders_placed == 2
    # Higher edge should execute first
    assert executor.orders[0].token_id == "tok-high"
