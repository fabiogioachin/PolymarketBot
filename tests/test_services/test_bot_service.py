"""Tests for bot service."""

import asyncio

import pytest

from app.execution.engine import ExecutionEngine
from app.models.order import Balance, OrderRequest, OrderResult, OrderStatus, Position
from app.risk.circuit_breaker import CircuitBreaker
from app.risk.manager import RiskManager
from app.services.bot_service import BotService, BotStatus
from app.strategies.registry import StrategyRegistry


class MinimalExecutor:
    """Minimal executor for bot service tests."""

    async def execute(self, order: OrderRequest) -> OrderResult:
        return OrderResult(status=OrderStatus.FILLED, is_simulated=True)

    async def get_positions(self) -> list[Position]:
        return []

    async def get_balance(self) -> Balance:
        return Balance(total=150.0, available=150.0)


def _make_bot_service() -> BotService:
    cb = CircuitBreaker()
    cb.initialize(150.0)
    risk = RiskManager(capital=150.0)
    registry = StrategyRegistry()
    executor = MinimalExecutor()
    engine = ExecutionEngine(
        executor=executor,
        risk_manager=risk,
        circuit_breaker=cb,
        strategy_registry=registry,
    )
    return BotService(engine=engine, risk_manager=risk, circuit_breaker=cb)


class TestBotStatus:
    def test_status_returns_correct_state(self) -> None:
        svc = _make_bot_service()
        status = svc.status()
        assert isinstance(status, BotStatus)
        assert status.running is False
        assert status.mode == "dry_run"
        assert status.tick_count == 0
        assert status.positions == 0
        assert status.circuit_breaker_tripped is False

    def test_status_reflects_mode_change(self) -> None:
        svc = _make_bot_service()
        svc.set_mode("shadow")
        assert svc.status().mode == "shadow"


class TestSetMode:
    def test_set_mode_accepts_valid_modes(self) -> None:
        svc = _make_bot_service()
        for mode in ("dry_run", "shadow", "live"):
            svc.set_mode(mode)
            assert svc.status().mode == mode

    def test_set_mode_rejects_invalid_mode(self) -> None:
        svc = _make_bot_service()
        with pytest.raises(ValueError, match="Invalid mode"):
            svc.set_mode("turbo")


class TestStartStop:
    @pytest.mark.asyncio
    async def test_start_stop_lifecycle(self) -> None:
        svc = _make_bot_service()
        assert svc.status().running is False

        await svc.start(interval_seconds=60)
        # Yield control so the background task starts executing
        await asyncio.sleep(0)
        assert svc.status().running is True
        assert svc.status().started_at is not None

        await svc.stop()
        assert svc.status().running is False
        assert svc.status().started_at is None

    @pytest.mark.asyncio
    async def test_start_idempotent(self) -> None:
        svc = _make_bot_service()
        await svc.start(interval_seconds=60)
        await asyncio.sleep(0)
        # Calling start again should not error (engine already running)
        await svc.start(interval_seconds=60)
        assert svc.status().running is True
        await svc.stop()
