"""Live executor — will connect to real CLOB when platform is available."""

from datetime import UTC, datetime
from uuid import uuid4

from app.core.logging import get_logger
from app.models.order import Balance, OrderRequest, OrderResult, OrderStatus, Position

logger = get_logger(__name__)


class LiveExecutor:
    """Live order executor.

    Currently a placeholder — Predict Street (EU-accessible prediction market)
    launches 2026-04-09. Until then, this executor logs orders but does not
    submit to any real exchange.

    When ready:
    - Will use AsyncClobClient with real API keys
    - WebSocket fill tracking for order status updates
    - Retry with exponential backoff on failures
    """

    def __init__(self, api_key: str = "", api_secret: str = "") -> None:
        self._api_key = api_key
        self._api_secret = api_secret
        self._positions: dict[str, Position] = {}
        self._balance = Balance(total=0.0, available=0.0, locked=0.0)
        self._connected = False

    async def execute(self, order: OrderRequest) -> OrderResult:
        """Execute order on live exchange. Currently returns REJECTED with explanation."""
        logger.warning(
            "live_order_attempted",
            token_id=order.token_id,
            side=order.side,
            price=order.price,
            size=order.size,
        )
        return OrderResult(
            order_id=str(uuid4()),
            status=OrderStatus.REJECTED,
            token_id=order.token_id,
            side=order.side,
            price=order.price,
            size=order.size,
            filled_size=0.0,
            is_simulated=False,
            timestamp=datetime.now(tz=UTC),
            error="Live trading not yet available — awaiting platform launch",
        )

    async def get_positions(self) -> list[Position]:
        """Return all open positions (empty until platform is live)."""
        return list(self._positions.values())

    async def get_balance(self) -> Balance:
        """Return account balance (zero until platform is live)."""
        return self._balance

    async def connect(self) -> None:
        """Connect to live exchange. Placeholder."""
        self._connected = True
        logger.info("live_executor_connected")

    async def disconnect(self) -> None:
        """Disconnect from live exchange."""
        self._connected = False
        logger.info("live_executor_disconnected")

    @property
    def is_connected(self) -> bool:
        """Whether the executor believes it is connected."""
        return self._connected


__all__ = ["LiveExecutor"]
