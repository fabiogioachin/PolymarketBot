"""Polymarket market data models."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class MarketStatus(StrEnum):
    ACTIVE = "active"
    CLOSED = "closed"
    RESOLVED = "resolved"


class Outcome(BaseModel):
    """A single outcome (YES/NO) within a market."""

    token_id: str
    outcome: str  # "Yes" or "No"
    price: float = 0.0


class OrderBookLevel(BaseModel):
    price: float
    size: float


class OrderBook(BaseModel):
    market_id: str
    asset_id: str
    bids: list[OrderBookLevel] = Field(default_factory=list)
    asks: list[OrderBookLevel] = Field(default_factory=list)
    spread: float = 0.0
    midpoint: float = 0.0
    timestamp: datetime | None = None


class ResolutionRules(BaseModel):
    """Parsed resolution rules for a market."""

    source: str = ""  # e.g., "Associated Press", "Official Government Data"
    conditions: list[str] = Field(default_factory=list)
    deadline: datetime | None = None
    raw_text: str = ""  # original rules text from Polymarket


class MarketCategory(StrEnum):
    POLITICS = "politics"
    GEOPOLITICS = "geopolitics"
    ECONOMICS = "economics"
    CRYPTO = "crypto"
    SPORTS = "sports"
    ENTERTAINMENT = "entertainment"
    SCIENCE = "science"
    OTHER = "other"


class Market(BaseModel):
    """A Polymarket prediction market."""

    id: str
    condition_id: str = ""
    slug: str = ""
    question: str = ""
    description: str = ""
    category: MarketCategory = MarketCategory.OTHER
    status: MarketStatus = MarketStatus.ACTIVE
    outcomes: list[Outcome] = Field(default_factory=list)
    resolution_rules: ResolutionRules = Field(default_factory=ResolutionRules)
    end_date: datetime | None = None
    volume: float = 0.0
    liquidity: float = 0.0
    volume_24h: float = 0.0
    created_at: datetime | None = None
    updated_at: datetime | None = None
    fee_rate: float = 0.0  # 0% for geopolitics, 7.2% for crypto, etc.
    tags: list[str] = Field(default_factory=list)


class PricePoint(BaseModel):
    timestamp: datetime
    price: float
    volume: float = 0.0


class PriceHistory(BaseModel):
    market_id: str
    token_id: str
    points: list[PricePoint] = Field(default_factory=list)
