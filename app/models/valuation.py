"""Valuation and assessment data models."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class Recommendation(StrEnum):
    STRONG_BUY = "STRONG_BUY"
    BUY = "BUY"
    HOLD = "HOLD"
    SELL = "SELL"
    STRONG_SELL = "STRONG_SELL"


class EdgeSource(BaseModel):
    """A single source contributing to the edge calculation."""

    name: str  # e.g., "base_rate", "microstructure", "rule_analysis"
    contribution: float = 0.0  # how much this source shifts fair value
    confidence: float = 0.0  # confidence in this source's signal (0-1)
    detail: str = ""  # human-readable explanation


class ValuationInput(BaseModel):
    """Inputs gathered for a single market valuation."""

    market_id: str
    market_price: float = 0.0
    base_rate: float | None = None
    crowd_calibration_adjustment: float = 0.0  # +/- adjustment based on crowd bias
    rule_analysis_score: float | None = None  # 0-1, how clear/favorable the rules are
    microstructure_score: float | None = None
    cross_market_signal: float | None = None
    event_signal: float | None = None
    pattern_kg_signal: float | None = None
    temporal_factor: float | None = None


class ValuationResult(BaseModel):
    """Complete result of a market value assessment."""

    market_id: str
    fair_value: float = 0.0  # 0.0-1.0 estimated true probability
    market_price: float = 0.0
    edge: float = 0.0  # fair_value - market_price (signed)
    confidence: float = 0.0  # 0.0-1.0
    fee_adjusted_edge: float = 0.0
    recommendation: Recommendation = Recommendation.HOLD
    edge_sources: list[EdgeSource] = Field(default_factory=list)
    timestamp: datetime | None = None
    inputs: ValuationInput | None = None


class CalibrationPoint(BaseModel):
    """A single point on the calibration curve."""

    predicted_probability: float  # market price bucket (e.g., 0.1, 0.2, ... 0.9)
    actual_frequency: float  # actual resolution frequency
    sample_size: int = 0


class CalibrationData(BaseModel):
    """Calibration analysis for a market category."""

    category: str
    points: list[CalibrationPoint] = Field(default_factory=list)
    bias: float = 0.0  # positive = crowd overconfident, negative = underconfident
    sample_size: int = 0


class MarketResolution(BaseModel):
    """Historical record of how a market resolved."""

    market_id: str
    category: str
    question: str = ""
    final_price: float = 0.0  # last market price before resolution
    resolved_yes: bool = False
    resolution_date: datetime | None = None
    volume: float = 0.0
