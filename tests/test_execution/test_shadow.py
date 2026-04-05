"""Tests for shadow executor."""

import pytest

from app.execution.dry_run import DryRunExecutor
from app.execution.executor import OrderExecutor
from app.execution.live import LiveExecutor
from app.execution.shadow import ShadowComparison, ShadowExecutor
from app.models.order import Balance, OrderRequest, OrderSide, OrderStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_order(
    token_id: str = "tok-shadow-1",
    side: OrderSide = OrderSide.BUY,
    price: float = 0.60,
    size: float = 15.0,
    market_id: str = "mkt-shadow-1",
) -> OrderRequest:
    return OrderRequest(
        token_id=token_id,
        side=side,
        price=price,
        size=size,
        market_id=market_id,
    )


def _make_shadow() -> ShadowExecutor:
    return ShadowExecutor(dry_run=DryRunExecutor(), live=LiveExecutor())


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestShadowProtocol:
    def test_satisfies_executor_protocol(self) -> None:
        executor = _make_shadow()
        assert isinstance(executor, OrderExecutor)


# ---------------------------------------------------------------------------
# execute() — primary result is dry-run
# ---------------------------------------------------------------------------


class TestShadowExecute:
    @pytest.mark.asyncio
    async def test_execute_returns_dry_run_result(self) -> None:
        """Shadow must return the dry-run result, not the live result."""
        executor = _make_shadow()
        order = _make_order()
        result = await executor.execute(order)
        # Dry-run executor always returns FILLED and is_simulated=True
        assert result.status == OrderStatus.FILLED
        assert result.is_simulated is True

    @pytest.mark.asyncio
    async def test_execute_not_live_result(self) -> None:
        """Live executor always returns REJECTED — shadow must NOT return that."""
        executor = _make_shadow()
        result = await executor.execute(_make_order())
        assert result.status != OrderStatus.REJECTED

    @pytest.mark.asyncio
    async def test_execute_records_comparison(self) -> None:
        executor = _make_shadow()
        assert len(executor.comparisons) == 0
        await executor.execute(_make_order())
        assert len(executor.comparisons) == 1

    @pytest.mark.asyncio
    async def test_comparison_fields_are_correct(self) -> None:
        executor = _make_shadow()
        order = _make_order(price=0.60)
        await executor.execute(order)
        cmp = executor.comparisons[0]
        assert isinstance(cmp, ShadowComparison)
        # dry-run FILLED vs live REJECTED → no match
        assert cmp.dry_run_status == OrderStatus.FILLED
        assert cmp.live_status == OrderStatus.REJECTED
        assert cmp.match is False
        # dry-run echoes the requested price; live echoes it too
        assert cmp.dry_run_price == pytest.approx(0.60, abs=0.01)

    @pytest.mark.asyncio
    async def test_comparisons_list_grows_with_each_execution(self) -> None:
        executor = _make_shadow()
        for i in range(3):
            await executor.execute(_make_order(token_id=f"tok-{i}"))
        assert len(executor.comparisons) == 3

    @pytest.mark.asyncio
    async def test_comparisons_property_returns_snapshot(self) -> None:
        """Mutating the returned list must not affect internal state."""
        executor = _make_shadow()
        await executor.execute(_make_order())
        snapshot = executor.comparisons
        snapshot.clear()
        assert len(executor.comparisons) == 1  # internal list unchanged


# ---------------------------------------------------------------------------
# execute() — live exception handled gracefully
# ---------------------------------------------------------------------------


class TestShadowLiveExceptionHandling:
    @pytest.mark.asyncio
    async def test_live_exception_does_not_propagate(self) -> None:
        """If the live executor raises, shadow must still return dry-run result."""

        class BrokenLive(LiveExecutor):
            async def execute(self, order: OrderRequest) -> None:  # type: ignore[override]
                raise RuntimeError("live exploded")

        executor = ShadowExecutor(dry_run=DryRunExecutor(), live=BrokenLive())
        result = await executor.execute(_make_order())
        assert result.status == OrderStatus.FILLED
        assert result.is_simulated is True

    @pytest.mark.asyncio
    async def test_live_exception_recorded_in_comparison(self) -> None:
        class BrokenLive(LiveExecutor):
            async def execute(self, order: OrderRequest) -> None:  # type: ignore[override]
                raise RuntimeError("live exploded")

        executor = ShadowExecutor(dry_run=DryRunExecutor(), live=BrokenLive())
        await executor.execute(_make_order())
        cmp = executor.comparisons[0]
        assert cmp.live_status == OrderStatus.REJECTED


# ---------------------------------------------------------------------------
# get_positions() / get_balance() — delegate to dry-run
# ---------------------------------------------------------------------------


class TestShadowDelegation:
    @pytest.mark.asyncio
    async def test_get_positions_delegates_to_dry_run(self) -> None:
        executor = _make_shadow()
        positions = await executor.get_positions()
        assert isinstance(positions, list)

    @pytest.mark.asyncio
    async def test_get_balance_delegates_to_dry_run(self) -> None:
        executor = _make_shadow()
        balance = await executor.get_balance()
        assert isinstance(balance, Balance)
        assert balance.available > 0  # dry-run has simulated balance
        assert balance.currency == "USDC"

    @pytest.mark.asyncio
    async def test_get_positions_not_from_live(self) -> None:
        """Dry-run and live positions can diverge; shadow uses dry-run."""
        executor = _make_shadow()
        # Execute an order so dry-run may record state
        await executor.execute(_make_order())
        positions = await executor.get_positions()
        # Whatever the result, it should be a list (not a live error)
        assert isinstance(positions, list)
