"""Manifold Markets data models and cross-platform signal model."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ManifoldMarket(BaseModel):
    """Mirrors Manifold's LiteMarket API response."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    question: str = ""
    url: str = ""
    probability: float = 0.0
    outcome_type: str = Field(default="BINARY", alias="outcomeType")
    mechanism: str = "cpmm-1"
    volume: float = 0.0
    volume_24h: float = Field(default=0.0, alias="volume24Hours")
    total_liquidity: float = Field(default=0.0, alias="totalLiquidity")
    unique_bettor_count: int = Field(default=0, alias="uniqueBettorCount")
    is_resolved: bool = Field(default=False, alias="isResolved")
    resolution: str | None = None
    resolution_time: int | None = Field(default=None, alias="resolutionTime")
    close_time: int | None = Field(default=None, alias="closeTime")
    created_time: int = Field(default=0, alias="createdTime")
    last_updated_time: int = Field(default=0, alias="lastUpdatedTime")
    creator_id: str = Field(default="", alias="creatorId")
    group_slugs: list[str] = Field(default_factory=list, alias="groupSlugs")
    description_text: str = Field(default="", alias="textDescription")


class ManifoldBet(BaseModel):
    """Single trade record from Manifold Markets."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    contract_id: str = Field(default="", alias="contractId")
    user_id: str = Field(default="", alias="userId")
    amount: float = 0.0
    shares: float = 0.0
    outcome: str = ""
    prob_before: float = Field(default=0.0, alias="probBefore")
    prob_after: float = Field(default=0.0, alias="probAfter")
    created_time: int = Field(default=0, alias="createdTime")
    is_filled: bool = Field(default=True, alias="isFilled")


class ManifoldComment(BaseModel):
    """Comment on a Manifold market."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    contract_id: str = Field(default="", alias="contractId")
    user_id: str = Field(default="", alias="userId")
    text: str = ""
    created_time: int = Field(default=0, alias="createdTime")


class MarketMatch(BaseModel):
    """Links a Polymarket market to its Manifold equivalent."""

    polymarket_id: str
    manifold_id: str
    manifold_url: str = ""
    polymarket_question: str = ""
    manifold_question: str = ""
    similarity_score: float = 0.0
    match_method: str = "tfidf"
    matched_at: datetime | None = None


class CrossPlatformSignal(BaseModel):
    """Output of the cross-platform analyzer used as input to the Value Assessment Engine."""

    polymarket_id: str
    manifold_id: str
    poly_price: float = 0.0
    manifold_price: float = 0.0
    divergence: float = 0.0
    manifold_volume: float = 0.0
    manifold_liquidity: float = 0.0
    manifold_unique_bettors: int = 0
    confidence: float = 0.0
    signal_value: float = 0.0
    timestamp: datetime | None = None
