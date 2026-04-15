"""Integration tests: Engine -> Risk KB -> API endpoint.

Tests the full data flow from ExecutionEngine tick through RiskKnowledgeBase
persistence to the FastAPI knowledge endpoints.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

import app.core.yaml_config as yaml_cfg_module
from app.core.yaml_config import AppConfig, StrategiesConfig
from app.execution.engine import ExecutionEngine
from app.knowledge.risk_kb import RiskKnowledgeBase, RiskLevel
from app.models.market import Market, MarketCategory, Outcome
from app.models.order import (
    Balance,
    OrderRequest,
    OrderResult,
    OrderStatus,
)
from app.models.signal import Signal, SignalType
from app.models.valuation import Recommendation, ValuationResult
from app.risk.circuit_breaker import CircuitBreaker
from app.risk.manager import RiskManager
from app.strategies.registry import StrategyRegistry

# --- Fakes (mirrored from tests/test_execution/test_engine.py) ---


class FakeExecutor:
    """Executor that always fills orders immediately."""

    def __init__(self, balance: float = 150.0) -> None:
        self._balance = balance
        self._orders: list[OrderRequest] = []

    async def execute(self, order: OrderRequest) -> OrderResult:
        self._orders.append(order)
        return OrderResult(
            order_id="fake-int-001",
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


class FakeValueEngine:
    """Value engine returning a fixed valuation with edge=0.2 for any market."""

    async def assess_batch(
        self,
        markets: list[Market],
        universe: list[Market] | None = None,
        external_signals: dict | None = None,
    ) -> list[ValuationResult]:
        return [
            ValuationResult(
                market_id=m.id,
                fair_value=0.70,
                market_price=0.50,
                edge=0.20,
                confidence=0.85,
                fee_adjusted_edge=0.20,
                recommendation=Recommendation.BUY,
            )
            for m in markets
        ]


class FakeStrategy:
    """Strategy that returns a BUY signal for any market with edge > 0.05."""

    @property
    def name(self) -> str:
        return "fake_integration_strategy"

    @property
    def domain_filter(self) -> list[str]:
        return []

    async def evaluate(
        self,
        market: Market,
        valuation: ValuationResult,
        knowledge: object = None,
    ) -> Signal | None:
        if valuation.edge <= 0.05:
            return None
        return Signal(
            strategy=self.name,
            market_id=market.id,
            token_id=market.outcomes[0].token_id if market.outcomes else "tok-1",
            signal_type=SignalType.BUY,
            confidence=0.85,
            market_price=valuation.market_price,
            edge_amount=valuation.edge,
            reasoning="Integration test signal",
        )


# --- Helpers ---


def _make_market(market_id: str = "int-mkt-1") -> Market:
    return Market(
        id=market_id,
        question="Will integration test pass?",
        category=MarketCategory.POLITICS,
        outcomes=[Outcome(token_id="int-tok-1", outcome="Yes", price=0.5)],
        end_date=datetime.now(tz=UTC) + timedelta(days=1),
    )


def _make_circuit_breaker() -> CircuitBreaker:
    cb = CircuitBreaker()
    cb.initialize(150.0)
    return cb


def _make_registry() -> StrategyRegistry:
    registry = StrategyRegistry()
    registry.register(FakeStrategy())  # type: ignore[arg-type]
    return registry


@pytest.fixture(autouse=True)
def _patch_yaml_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure strategy registry finds our fake strategy as enabled."""
    cfg = AppConfig(
        strategies=StrategiesConfig(
            enabled=["fake_integration_strategy"],
            domain_filters={},
        )
    )
    monkeypatch.setattr(yaml_cfg_module, "app_config", cfg)


# --- Test 1.1: Engine tick populates Risk KB ---


class TestEngineTickPopulatesRiskKB:
    @pytest.mark.asyncio
    async def test_engine_tick_populates_risk_kb(self) -> None:
        """Full flow: engine.tick() -> risk_kb.upsert() -> verify stored data."""
        risk_kb = RiskKnowledgeBase(db_path=":memory:")
        await risk_kb.init()

        engine = ExecutionEngine(
            executor=FakeExecutor(),
            risk_manager=RiskManager(capital=150.0),
            circuit_breaker=_make_circuit_breaker(),
            strategy_registry=_make_registry(),
            value_engine=FakeValueEngine(),
            risk_kb=risk_kb,
        )

        market = _make_market()
        result = await engine.tick(markets=[market])

        # Engine must have generated and executed at least one signal
        assert result.signals_generated >= 1
        assert result.orders_placed >= 1

        # Risk KB must contain the persisted record
        records = await risk_kb.get_all()
        assert len(records) >= 1

        record = records[0]
        assert record.strategy_applied != ""
        assert record.strategy_applied == "fake_integration_strategy"
        # edge=0.2 > 0.15 threshold -> RiskLevel.LOW
        assert record.risk_level == RiskLevel.LOW
        assert record.risk_reason != ""

        await risk_kb.close()


# --- Test 1.2: Engine tick to API endpoint ---


class TestEngineTickToAPIEndpoint:
    @pytest.mark.asyncio
    async def test_engine_tick_to_api_endpoint(self) -> None:
        """Full flow: engine.tick() -> risk_kb -> API endpoints return data."""
        risk_kb = RiskKnowledgeBase(db_path=":memory:")
        await risk_kb.init()

        engine = ExecutionEngine(
            executor=FakeExecutor(),
            risk_manager=RiskManager(capital=150.0),
            circuit_breaker=_make_circuit_breaker(),
            strategy_registry=_make_registry(),
            value_engine=FakeValueEngine(),
            risk_kb=risk_kb,
        )

        market = _make_market()
        await engine.tick(markets=[market])

        # Verify data is in the KB before hitting the API
        records = await risk_kb.get_all()
        assert len(records) >= 1

        # Override the get_risk_kb dependency to return our in-memory KB
        from app.core.dependencies import get_risk_kb
        from app.main import app

        async def _override_risk_kb() -> RiskKnowledgeBase:
            return risk_kb

        app.dependency_overrides[get_risk_kb] = _override_risk_kb

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                # GET /api/v1/knowledge/strategies -> non-empty list
                resp_strategies = await client.get(
                    "/api/v1/knowledge/strategies"
                )
                assert resp_strategies.status_code == 200
                strategies = resp_strategies.json()
                assert len(strategies) >= 1
                assert strategies[0]["strategy"] == "fake_integration_strategy"
                assert strategies[0]["market_count"] >= 1

                # GET /api/v1/knowledge/risks -> non-empty list
                resp_risks = await client.get("/api/v1/knowledge/risks")
                assert resp_risks.status_code == 200
                risks = resp_risks.json()
                assert len(risks) >= 1
                assert risks[0]["market_id"] == "int-mkt-1"
                assert risks[0]["risk_level"] == "low"
                assert risks[0]["strategy_applied"] == "fake_integration_strategy"
        finally:
            app.dependency_overrides.pop(get_risk_kb, None)
            await risk_kb.close()
