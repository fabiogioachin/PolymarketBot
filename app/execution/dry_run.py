"""Dry-run executor using simulated CLOB client."""

from app.clients.polymarket_clob import PolymarketClobClient
from app.core.logging import get_logger
from app.models.order import Balance, OrderRequest, OrderResult, Position

logger = get_logger(__name__)


class DryRunExecutor:
    """Wraps PolymarketClobClient for dry-run execution."""

    def __init__(self, clob_client: PolymarketClobClient | None = None) -> None:
        self._clob = clob_client or PolymarketClobClient()

    async def execute(self, order: OrderRequest) -> OrderResult:
        """Execute an order via the CLOB client (simulated in dry-run)."""
        return await self._clob.place_order(order)

    async def get_positions(self) -> list[Position]:
        """Get all open positions."""
        return await self._clob.get_positions()

    async def get_balance(self) -> Balance:
        """Get account balance."""
        return await self._clob.get_balance()
