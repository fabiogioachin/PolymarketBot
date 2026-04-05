"""Order executor protocol."""

from typing import Protocol, runtime_checkable

from app.models.order import Balance, OrderRequest, OrderResult, Position


@runtime_checkable
class OrderExecutor(Protocol):
    """Protocol for order execution backends (dry-run, shadow, live)."""

    async def execute(self, order: OrderRequest) -> OrderResult: ...

    async def get_positions(self) -> list[Position]: ...

    async def get_balance(self) -> Balance: ...
