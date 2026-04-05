"""Tests for LlmClient — Claude API wrapper."""

from __future__ import annotations

import httpx
import pytest
import respx

from app.clients.llm_client import LlmAssessment, LlmClient

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def client() -> LlmClient:
    return LlmClient(api_key="test-key", model="claude-sonnet-4-6", max_daily=5)


def _make_response(text: str) -> dict:
    """Build a minimal Anthropic messages API response payload."""
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": text}],
        "model": "claude-sonnet-4-6",
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 100, "output_tokens": 200},
    }


# ── _build_prompt ─────────────────────────────────────────────────────────────


class TestBuildPrompt:
    def test_prompt_contains_market_question(self, client: LlmClient) -> None:
        prompt = client._build_prompt("Will Biden win?", "", None, None)
        assert "Will Biden win?" in prompt

    def test_prompt_contains_output_markers(self, client: LlmClient) -> None:
        prompt = client._build_prompt("Test question", "", None, None)
        for marker in ("PROBABILITY:", "CONFIDENCE:", "KEY_FACTORS:", "RISK_FLAGS:", "REASONING:"):
            assert marker in prompt

    def test_prompt_includes_context(self, client: LlmClient) -> None:
        prompt = client._build_prompt("Q?", "Some important context", None, None)
        assert "Some important context" in prompt

    def test_prompt_includes_patterns_and_events(self, client: LlmClient) -> None:
        prompt = client._build_prompt(
            "Q?",
            "",
            patterns=["Pattern A", "Pattern B"],
            events=["Event X"],
        )
        assert "Pattern A" in prompt
        assert "Pattern B" in prompt
        assert "Event X" in prompt

    def test_prompt_without_optional_fields(self, client: LlmClient) -> None:
        prompt = client._build_prompt("Bare question?", "", None, None)
        assert "KNOWN PATTERNS:" not in prompt
        assert "RECENT EVENTS:" not in prompt


# ── _parse_response ───────────────────────────────────────────────────────────


class TestParseResponse:
    def test_parses_all_fields(self, client: LlmClient) -> None:
        text = (
            "PROBABILITY: 0.72\n"
            "CONFIDENCE: 0.85\n"
            "KEY_FACTORS:\n"
            "- Strong incumbent advantage\n"
            "- Positive economic indicators\n"
            "RISK_FLAGS:\n"
            "- Possible third-party split\n"
            "REASONING: The incumbent holds a structural advantage based on historical data.\n"
        )
        result = client._parse_response(_make_response(text))
        assert result.probability_estimate == pytest.approx(0.72)
        assert result.confidence == pytest.approx(0.85)
        assert len(result.key_factors) == 2
        assert "Strong incumbent advantage" in result.key_factors
        assert len(result.risk_flags) == 1
        assert "historical data" in result.reasoning

    def test_clamps_probability_to_0_1(self, client: LlmClient) -> None:
        text = "PROBABILITY: 1.5\nCONFIDENCE: -0.2\n"
        result = client._parse_response(_make_response(text))
        assert result.probability_estimate == 1.0
        assert result.confidence == 0.0

    def test_returns_defaults_on_empty_response(self, client: LlmClient) -> None:
        result = client._parse_response({"content": []})
        assert result.probability_estimate == 0.5
        assert result.confidence == 0.0
        assert result.key_factors == []
        assert result.risk_flags == []

    def test_returns_defaults_on_malformed_data(self, client: LlmClient) -> None:
        result = client._parse_response({})
        assert isinstance(result, LlmAssessment)
        assert result.probability_estimate == 0.5


# ── _check_daily_limit ────────────────────────────────────────────────────────


class TestDailyLimit:
    def test_increments_counter(self, client: LlmClient) -> None:
        assert client.daily_calls_remaining == 5
        client._check_daily_limit()
        assert client.daily_calls_remaining == 4

    def test_raises_when_limit_exceeded(self, client: LlmClient) -> None:
        for _ in range(5):
            client._check_daily_limit()
        with pytest.raises(RuntimeError, match="daily call limit"):
            client._check_daily_limit()

    def test_resets_counter_after_one_day(self, client: LlmClient) -> None:
        from datetime import timedelta

        # Exhaust the limit
        for _ in range(5):
            client._check_daily_limit()

        # Simulate last_reset being >24 hours ago
        old_time = client._last_reset - timedelta(days=2)  # type: ignore[operator]
        client._last_reset = old_time

        # Should not raise — counter has been reset
        client._check_daily_limit()
        assert client.daily_calls_remaining == 4


# ── daily_calls_remaining ─────────────────────────────────────────────────────


class TestDailyCallsRemaining:
    def test_initial_remaining_equals_max(self, client: LlmClient) -> None:
        assert client.daily_calls_remaining == 5

    def test_never_below_zero(self, client: LlmClient) -> None:
        # Force counter above max to verify the floor
        client._daily_calls = 100
        assert client.daily_calls_remaining == 0


# ── assess_market (full HTTP mock) ────────────────────────────────────────────


class TestAssessMarket:
    @respx.mock
    @pytest.mark.asyncio()
    async def test_returns_parsed_assessment(self, client: LlmClient) -> None:
        mock_text = (
            "PROBABILITY: 0.65\n"
            "CONFIDENCE: 0.70\n"
            "KEY_FACTORS:\n"
            "- Factor one\n"
            "RISK_FLAGS:\n"
            "- Risk one\n"
            "REASONING: Short explanation.\n"
        )
        respx.post(ANTHROPIC_URL).mock(
            return_value=httpx.Response(200, json=_make_response(mock_text))
        )

        result = await client.assess_market(
            market_question="Will X happen?",
            context="Some context",
        )

        assert result.probability_estimate == pytest.approx(0.65)
        assert result.confidence == pytest.approx(0.70)
        assert "Factor one" in result.key_factors
        assert "Risk one" in result.risk_flags

    @respx.mock
    @pytest.mark.asyncio()
    async def test_sends_correct_headers(self, client: LlmClient) -> None:
        respx.post(ANTHROPIC_URL).mock(
            return_value=httpx.Response(200, json=_make_response("PROBABILITY: 0.5\n"))
        )

        await client.assess_market("Q?")

        request = respx.calls.last.request
        assert request.headers["x-api-key"] == "test-key"
        assert request.headers["anthropic-version"] == "2023-06-01"

    @respx.mock
    @pytest.mark.asyncio()
    async def test_raises_on_http_error(self, client: LlmClient) -> None:
        respx.post(ANTHROPIC_URL).mock(
            return_value=httpx.Response(401, json={"error": "unauthorized"})
        )

        with pytest.raises(httpx.HTTPStatusError):
            await client.assess_market("Will Y happen?")

    @respx.mock
    @pytest.mark.asyncio()
    async def test_decrements_daily_calls(self, client: LlmClient) -> None:
        respx.post(ANTHROPIC_URL).mock(
            return_value=httpx.Response(200, json=_make_response("PROBABILITY: 0.5\n"))
        )
        before = client.daily_calls_remaining
        await client.assess_market("Q?")
        assert client.daily_calls_remaining == before - 1

    @pytest.mark.asyncio()
    async def test_raises_when_daily_limit_exhausted(self, client: LlmClient) -> None:
        # Prime _last_reset so the daily-reset branch is not triggered, then exhaust the limit.
        client._check_daily_limit()  # sets _last_reset
        client._daily_calls = client._max_daily

        with pytest.raises(RuntimeError, match="daily call limit"):
            await client.assess_market("Q?")
