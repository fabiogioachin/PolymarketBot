"""LLM client for Claude API — invoked ONLY on configured triggers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx

from app.core.logging import get_logger

logger = get_logger(__name__)

_ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"


@dataclass
class LlmAssessment:
    """Structured response from LLM analysis."""

    probability_estimate: float = 0.5  # 0-1
    confidence: float = 0.0  # 0-1
    reasoning: str = ""
    key_factors: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)


class LlmClient:
    """Claude API client — invoked only on specific triggers."""

    def __init__(
        self,
        api_key: str = "",
        model: str = "claude-sonnet-4-6",
        max_daily: int = 20,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._daily_calls: int = 0
        self._last_reset: datetime | None = None
        self._max_daily = max_daily
        self._base_url = _ANTHROPIC_MESSAGES_URL

    async def assess_market(
        self,
        market_question: str,
        context: str = "",
        patterns: list[str] | None = None,
        events: list[str] | None = None,
    ) -> LlmAssessment:
        """Ask Claude to assess a market given context.

        Builds a structured prompt with market question, available context
        (patterns, events), and requests a probability estimate, key factors,
        risk flags, and reasoning. Parses the response into an LlmAssessment.

        Raises:
            RuntimeError: if the daily call limit has been exceeded.
            httpx.HTTPStatusError: if the API returns a non-2xx response.
        """
        self._check_daily_limit()

        prompt = self._build_prompt(market_question, context, patterns, events)

        async with httpx.AsyncClient() as client:
            response = await client.post(
                self._base_url,
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": self._model,
                    "max_tokens": 1024,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=30.0,
            )
            response.raise_for_status()

        assessment = self._parse_response(response.json())

        logger.info(
            "llm_client: market assessed",
            market_question=market_question[:80],
            probability=assessment.probability_estimate,
            confidence=assessment.confidence,
            daily_calls=self._daily_calls,
        )

        return assessment

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _check_daily_limit(self) -> None:
        """Reset counter daily, raise if limit exceeded."""
        now = datetime.now(tz=UTC)
        if self._last_reset is None or (now - self._last_reset).days >= 1:
            self._daily_calls = 0
            self._last_reset = now
        if self._daily_calls >= self._max_daily:
            raise RuntimeError(f"LLM daily call limit ({self._max_daily}) exceeded")
        self._daily_calls += 1

    def _build_prompt(
        self,
        question: str,
        context: str,
        patterns: list[str] | None,
        events: list[str] | None,
    ) -> str:
        """Build a structured assessment prompt with clear output markers."""
        parts: list[str] = [
            "You are an expert prediction market analyst. Assess the following market question.",
            "",
            f"MARKET QUESTION: {question}",
        ]

        if context:
            parts += ["", f"CONTEXT: {context}"]

        if patterns:
            parts += ["", "KNOWN PATTERNS:"]
            parts += [f"- {p}" for p in patterns]

        if events:
            parts += ["", "RECENT EVENTS:"]
            parts += [f"- {e}" for e in events]

        parts += [
            "",
            "Provide your assessment using EXACTLY the following format. "
            "Do not deviate from these markers.",
            "",
            "PROBABILITY: <float 0.0-1.0>",
            "CONFIDENCE: <float 0.0-1.0>",
            "KEY_FACTORS:",
            "- <factor 1>",
            "- <factor 2>",
            "RISK_FLAGS:",
            "- <risk 1>",
            "- <risk 2>",
            "REASONING: <one paragraph explanation>",
        ]

        return "\n".join(parts)

    def _parse_response(self, response_data: dict) -> LlmAssessment:
        """Parse Claude's response into a structured LlmAssessment.

        Extracts PROBABILITY, CONFIDENCE, KEY_FACTORS, RISK_FLAGS, and REASONING
        markers from the text. Falls back to safe defaults if parsing fails.
        """
        try:
            content_blocks: list[dict] = response_data.get("content", [])
            text = ""
            for block in content_blocks:
                if block.get("type") == "text":
                    text += block.get("text", "")
        except (AttributeError, TypeError):
            return LlmAssessment()

        if not text:
            return LlmAssessment()

        probability = 0.5
        confidence = 0.0
        reasoning = ""
        key_factors: list[str] = []
        risk_flags: list[str] = []

        lines = text.splitlines()
        current_section: str | None = None

        for line in lines:
            stripped = line.strip()

            if stripped.startswith("PROBABILITY:"):
                current_section = None
                try:
                    probability = float(stripped.split(":", 1)[1].strip())
                    probability = max(0.0, min(1.0, probability))
                except (ValueError, IndexError):
                    pass

            elif stripped.startswith("CONFIDENCE:"):
                current_section = None
                try:
                    confidence = float(stripped.split(":", 1)[1].strip())
                    confidence = max(0.0, min(1.0, confidence))
                except (ValueError, IndexError):
                    pass

            elif stripped.startswith("KEY_FACTORS:"):
                current_section = "key_factors"

            elif stripped.startswith("RISK_FLAGS:"):
                current_section = "risk_flags"

            elif stripped.startswith("REASONING:"):
                current_section = "reasoning"
                tail = stripped.split(":", 1)[1].strip()
                if tail:
                    reasoning = tail

            elif stripped.startswith("-") and current_section in ("key_factors", "risk_flags"):
                item = stripped.lstrip("- ").strip()
                if item:
                    if current_section == "key_factors":
                        key_factors.append(item)
                    else:
                        risk_flags.append(item)

            elif current_section == "reasoning" and stripped:
                reasoning = (reasoning + " " + stripped).strip()

        return LlmAssessment(
            probability_estimate=probability,
            confidence=confidence,
            reasoning=reasoning,
            key_factors=key_factors,
            risk_flags=risk_flags,
        )

    # ── Public properties ─────────────────────────────────────────────────────

    @property
    def daily_calls_remaining(self) -> int:
        """Number of LLM calls remaining today."""
        return max(0, self._max_daily - self._daily_calls)


# ── Singleton (lazy) ──────────────────────────────────────────────────────────

_llm_client: LlmClient | None = None


def get_llm_client() -> LlmClient:
    """Return the process-level LlmClient singleton, creating it on first call."""
    global _llm_client  # noqa: PLW0603
    if _llm_client is None:
        from app.core.yaml_config import app_config

        api_key = ""
        try:
            from app.core.config import settings

            api_key = getattr(settings, "anthropic_api_key", "")
        except Exception:  # noqa: BLE001, S110
            logger.debug("llm_client: could not import settings, api_key defaults to empty")

        _llm_client = LlmClient(
            api_key=api_key,
            model=app_config.llm.model,
            max_daily=app_config.llm.max_daily_calls,
        )

    return _llm_client
