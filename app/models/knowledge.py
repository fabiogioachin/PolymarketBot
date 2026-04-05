"""Knowledge graph data models."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class PatternStatus(StrEnum):
    ACTIVE = "active"
    STANDBY = "standby"
    RETIRED = "retired"


class Pattern(BaseModel):
    """A reusable pattern from the Knowledge Graph."""

    id: str = ""  # path-based ID
    name: str = ""
    domain: str = ""
    pattern_type: str = ""  # "recurring", "seasonal", "causal", "correlation"
    confidence: float = 0.5
    status: PatternStatus = PatternStatus.ACTIVE
    description: str = ""
    expected_outcome: str = ""
    trigger_condition: str = ""
    historical_accuracy: float = 0.0
    times_triggered: int = 0
    last_triggered: datetime | None = None
    tags: list[str] = Field(default_factory=list)


class PatternMatch(BaseModel):
    """Result of matching a pattern against current events."""

    pattern: Pattern
    match_score: float = 0.0  # 0-1, how well current events match
    matched_keywords: list[str] = Field(default_factory=list)
    detail: str = ""


class KnowledgeContext(BaseModel):
    """Knowledge context gathered for a market assessment."""

    domain: str = ""
    patterns: list[PatternMatch] = Field(default_factory=list)
    domain_notes: list[str] = Field(default_factory=list)
    composite_signal: float = 0.0  # -1 to +1, aggregated pattern signal
    confidence: float = 0.0
