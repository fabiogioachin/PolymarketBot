"""Order and position models for CLOB trading."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"


class OrderStatus(StrEnum):
    PENDING = "pending"
    LIVE = "live"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class OrderRequest(BaseModel):
    """Request to place an order."""

    token_id: str
    side: OrderSide
    price: float
    size: float
    order_type: OrderType = OrderType.LIMIT
    market_id: str = ""
    reason: str = ""  # why this trade


class OrderResult(BaseModel):
    """Result of an order placement."""

    order_id: str = ""
    status: OrderStatus = OrderStatus.PENDING
    token_id: str = ""
    side: OrderSide = OrderSide.BUY
    price: float = 0.0
    size: float = 0.0
    filled_size: float = 0.0
    is_simulated: bool = False  # True for dry-run orders
    timestamp: datetime | None = None
    error: str = ""


class Position(BaseModel):
    """An open position."""

    market_id: str = ""
    token_id: str
    side: OrderSide = OrderSide.BUY
    size: float = 0.0
    avg_price: float = 0.0
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0


class Balance(BaseModel):
    """Account balance."""

    total: float = 0.0
    available: float = 0.0
    locked: float = 0.0
    currency: str = "USDC"
