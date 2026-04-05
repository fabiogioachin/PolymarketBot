"""Trading signal models."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class SignalType(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class Signal(BaseModel):
    """A trading signal produced by a strategy."""

    strategy: str  # name of the strategy that produced it
    market_id: str
    token_id: str = ""
    signal_type: SignalType
    confidence: float = 0.0  # 0-1
    market_price: float = 0.0  # current market price of the token
    edge_amount: float = 0.0  # expected edge (positive = favorable)
    suggested_size: float = 0.0  # suggested position size in EUR
    reasoning: str = ""
    knowledge_sources: list[str] = Field(default_factory=list)
    timestamp: datetime | None = None
