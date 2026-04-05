"""Tests for dry-run executor."""

import pytest

from app.execution.dry_run import DryRunExecutor
from app.execution.executor import OrderExecutor
from app.models.order import Balance, OrderRequest, OrderSide, OrderStatus


class TestDryRunProtocol:
    def test_satisfies_executor_protocol(self) -> None:
        executor = DryRunExecutor()
        assert isinstance(executor, OrderExecutor)


class TestDryRunExecute:
    @pytest.mark.asyncio
    async def test_execute_delegates_to_clob_client(self) -> None:
        executor = DryRunExecutor()
        order = OrderRequest(
            token_id="tok-1",
            side=OrderSide.BUY,
            price=0.5,
            size=10.0,
            market_id="mkt-1",
        )
        result = await executor.execute(order)
        assert result.status == OrderStatus.FILLED
        assert result.token_id == "tok-1"
        assert result.is_simulated is True

    @pytest.mark.asyncio
    async def test_get_positions_returns_list(self) -> None:
        executor = DryRunExecutor()
        positions = await executor.get_positions()
        assert isinstance(positions, list)

    @pytest.mark.asyncio
    async def test_get_balance_returns_balance(self) -> None:
        executor = DryRunExecutor()
        balance = await executor.get_balance()
        assert isinstance(balance, Balance)
        assert balance.available > 0
        assert balance.currency == "USDC"
