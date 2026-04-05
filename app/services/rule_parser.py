"""Resolution rule parser and risk classifier."""

import re
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.models.market import Market

logger = get_logger(__name__)


class RuleRiskLevel(StrEnum):
    CLEAR = "clear_rules"
    AMBIGUOUS = "ambiguous_rules"
    HIGH_RISK = "high_risk_rules"


class RuleAnalysis(BaseModel):
    """Detailed analysis of a market's resolution rules."""

    market_id: str
    resolution_source: str = ""
    conditions: list[str] = Field(default_factory=list)
    deadline: datetime | None = None
    risk_level: RuleRiskLevel = RuleRiskLevel.CLEAR
    ambiguities: list[str] = Field(default_factory=list)
    edge_cases: list[str] = Field(default_factory=list)
    raw_text: str = ""


class RuleParser:
    """Analyzes market resolution rules to identify risks, ambiguities, and edge cases."""

    # Known authoritative sources (higher confidence)
    TRUSTED_SOURCES = [
        "associated press",
        "ap",
        "reuters",
        "official government",
        "federal reserve",
        "bls",
        "bureau of labor statistics",
        "sec",
        "fda",
        "who",
        "un",
        "world bank",
        "imf",
    ]

    # Ambiguity indicators
    AMBIGUITY_MARKERS = [
        "at the discretion",
        "may be",
        "could be",
        "subject to",
        "in the opinion",
        "reasonable",
        "approximately",
        "broadly",
        "generally",
        "typically",
        "usually",
        "might",
    ]

    # Edge case patterns
    TIMEZONE_PATTERN = re.compile(r"\b(EST|PST|UTC|GMT|ET|PT|CT)\b", re.IGNORECASE)
    DEADLINE_PATTERN = re.compile(
        r"(by|before|no later than|on or before)\s+"
        r"(\w+\s+\d{1,2},?\s+\d{4}|\d{1,2}/\d{1,2}/\d{4})",
        re.IGNORECASE,
    )

    def analyze(self, market: Market) -> RuleAnalysis:
        """Perform full rule analysis on a market."""
        rules = market.resolution_rules
        text = rules.raw_text or market.description
        text_lower = text.lower()

        source = self._extract_source(text, rules.source)
        conditions = self._extract_conditions(text, rules.conditions)
        ambiguities = self._detect_ambiguities(text_lower)
        edge_cases = self._detect_edge_cases(text)
        risk_level = self._classify_risk(source, ambiguities, edge_cases, conditions)

        return RuleAnalysis(
            market_id=market.id,
            resolution_source=source,
            conditions=conditions,
            deadline=rules.deadline or market.end_date,
            risk_level=risk_level,
            ambiguities=ambiguities,
            edge_cases=edge_cases,
            raw_text=text,
        )

    def _extract_source(self, text: str, existing_source: str) -> str:
        """Extract the resolution source from rule text."""
        if existing_source and existing_source not in ("", "unknown"):
            return existing_source

        text_lower = text.lower()
        for trusted in self.TRUSTED_SOURCES:
            if trusted in text_lower:
                return trusted.title()

        # Look for "according to X" or "as reported by X"
        patterns = [
            r"according to\s+([^,.]+)",
            r"as reported by\s+([^,.]+)",
            r"data from\s+([^,.]+)",
            r"based on\s+([^,.]+)",
            r"source:\s*([^\n]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip()

        return ""

    def _extract_conditions(self, text: str, existing: list[str]) -> list[str]:
        """Extract resolution conditions from text."""
        if existing:
            return existing

        conditions: list[str] = []
        resolution_keywords = [
            "resolve",
            "resolution",
            "will be determined",
            "settled",
            "will resolve",
            "this market resolves",
        ]

        for line in text.split("\n"):
            stripped = line.strip()
            if not stripped:
                continue
            if any(kw in stripped.lower() for kw in resolution_keywords):
                conditions.append(stripped)

        return conditions

    def _detect_ambiguities(self, text_lower: str) -> list[str]:
        """Detect ambiguous language in rules."""
        found: list[str] = []
        for marker in self.AMBIGUITY_MARKERS:
            if marker in text_lower:
                for sentence in re.split(r"[.!?]", text_lower):
                    if marker in sentence:
                        found.append(
                            f"Ambiguous language: '{marker}' in: {sentence.strip()}"
                        )
                        break
        return found

    def _detect_edge_cases(self, text: str) -> list[str]:
        """Detect potential edge cases in rules."""
        edge_cases: list[str] = []

        # Timezone ambiguity
        tz_matches = self.TIMEZONE_PATTERN.findall(text)
        if len({m.upper() for m in tz_matches}) > 1:
            unique = sorted({m.upper() for m in tz_matches})
            edge_cases.append(f"Multiple timezones referenced: {', '.join(unique)}")
        elif not tz_matches and self.DEADLINE_PATTERN.search(text):
            edge_cases.append("Deadline specified without explicit timezone")

        # Specific source not named
        if "official" in text.lower() and not any(
            s in text.lower() for s in self.TRUSTED_SOURCES
        ):
            edge_cases.append(
                "References 'official' source without naming specific entity"
            )

        # Conditional resolution (if/then)
        if re.search(r"\bif\b.*\bthen\b", text.lower()):
            edge_cases.append("Conditional resolution logic detected")

        return edge_cases

    def _classify_risk(
        self,
        source: str,
        ambiguities: list[str],
        edge_cases: list[str],
        conditions: list[str],
    ) -> RuleRiskLevel:
        """Classify overall rule risk level."""
        # High risk: no source + ambiguities
        if not source and len(ambiguities) > 0:
            return RuleRiskLevel.HIGH_RISK

        # High risk: many ambiguities or edge cases
        if len(ambiguities) >= 3 or len(edge_cases) >= 3:
            return RuleRiskLevel.HIGH_RISK

        # Ambiguous: some ambiguities or edge cases, or no clear conditions
        if ambiguities or edge_cases or not conditions:
            return RuleRiskLevel.AMBIGUOUS

        # Clear: trusted source, clear conditions, no ambiguities
        return RuleRiskLevel.CLEAR
