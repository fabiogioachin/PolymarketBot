"""Tests for SentimentStrategy."""

from __future__ import annotations

import pytest

from app.models.knowledge import KnowledgeContext
from app.models.market import Market, MarketCategory, Outcome
from app.models.signal import SignalType
from app.models.valuation import ValuationResult
from app.strategies.base import BaseStrategy
from app.strategies.sentiment import SentimentStrategy

# ── Helpers / factories ───────────────────────────────────────────────────────


def _make_market(
    market_id: str = "mkt-1",
    category: MarketCategory = MarketCategory.POLITICS,
) -> Market:
    return Market(
        id=market_id,
        question="Will Y happen?",
        category=category,
        outcomes=[
            Outcome(token_id="yes-token", outcome="Yes", price=0.55),
            Outcome(token_id="no-token", outcome="No", price=0.45),
        ],
    )


def _make_valuation(
    market_id: str = "mkt-1",
    fee_adjusted_edge: float = 0.07,
    confidence: float = 0.6,
) -> ValuationResult:
    return ValuationResult(
        market_id=market_id,
        fair_value=0.62,
        market_price=0.55,
        edge=0.07,
        confidence=confidence,
        fee_adjusted_edge=fee_adjusted_edge,
    )


def _make_knowledge(
    composite_signal: float = 0.0,
    confidence: float = 0.7,
    domain: str = "politics",
) -> KnowledgeContext:
    return KnowledgeContext(
        domain=domain,
        composite_signal=composite_signal,
        confidence=confidence,
    )


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def strategy() -> SentimentStrategy:
    return SentimentStrategy()


@pytest.fixture()
def market() -> Market:
    return _make_market()


@pytest.fixture()
def valuation() -> ValuationResult:
    return _make_valuation()


# ── Protocol conformance ──────────────────────────────────────────────────────


class TestProtocol:
    def test_satisfies_base_strategy_protocol(self, strategy: SentimentStrategy) -> None:
        assert isinstance(strategy, BaseStrategy)

    def test_name_is_sentiment(self, strategy: SentimentStrategy) -> None:
        assert strategy.name == "sentiment"

    def test_domain_filter_contains_expected_domains(self, strategy: SentimentStrategy) -> None:
        assert "politics" in strategy.domain_filter
        assert "geopolitics" in strategy.domain_filter
        assert "economics" in strategy.domain_filter


# ── Returns None cases ────────────────────────────────────────────────────────


class TestReturnsNone:
    @pytest.mark.asyncio()
    async def test_returns_none_without_knowledge_context(
        self, strategy: SentimentStrategy, market: Market, valuation: ValuationResult
    ) -> None:
        result = await strategy.evaluate(market, valuation, knowledge=None)
        assert result is None

    @pytest.mark.asyncio()
    async def test_returns_none_with_weak_sentiment(
        self, strategy: SentimentStrategy, market: Market, valuation: ValuationResult
    ) -> None:
        """Composite signal very close to zero — below effective threshold."""
        knowledge = _make_knowledge(composite_signal=0.001)  # effectively zero
        result = await strategy.evaluate(market, valuation, knowledge)
        assert result is None

    @pytest.mark.asyncio()
    async def test_returns_none_when_sentiment_and_edge_disagree(
        self, strategy: SentimentStrategy, market: Market
    ) -> None:
        """Positive sentiment but negative edge → no trade."""
        valuation = _make_valuation(fee_adjusted_edge=-0.05)
        knowledge = _make_knowledge(composite_signal=0.8)  # strongly bullish
        result = await strategy.evaluate(market, valuation, knowledge)
        assert result is None

    @pytest.mark.asyncio()
    async def test_returns_none_when_negative_sentiment_and_positive_edge(
        self, strategy: SentimentStrategy, market: Market, valuation: ValuationResult
    ) -> None:
        knowledge = _make_knowledge(composite_signal=-0.8)
        result = await strategy.evaluate(market, valuation, knowledge)
        assert result is None


# ── Signal generation ─────────────────────────────────────────────────────────


class TestSignalGeneration:
    @pytest.mark.asyncio()
    async def test_buy_on_positive_sentiment_and_positive_edge(
        self, strategy: SentimentStrategy, market: Market, valuation: ValuationResult
    ) -> None:
        knowledge = _make_knowledge(composite_signal=0.5)
        result = await strategy.evaluate(market, valuation, knowledge)

        assert result is not None
        assert result.signal_type == SignalType.BUY
        assert result.strategy == "sentiment"
        assert result.market_id == market.id

    @pytest.mark.asyncio()
    async def test_sell_on_negative_sentiment_and_negative_edge(
        self, strategy: SentimentStrategy, market: Market
    ) -> None:
        valuation = _make_valuation(fee_adjusted_edge=-0.06)
        knowledge = _make_knowledge(composite_signal=-0.5)
        result = await strategy.evaluate(market, valuation, knowledge)

        assert result is not None
        assert result.signal_type == SignalType.SELL

    @pytest.mark.asyncio()
    async def test_buy_token_is_yes_outcome(
        self, strategy: SentimentStrategy, market: Market, valuation: ValuationResult
    ) -> None:
        knowledge = _make_knowledge(composite_signal=0.5)
        result = await strategy.evaluate(market, valuation, knowledge)

        assert result is not None
        assert result.token_id == "yes-token"

    @pytest.mark.asyncio()
    async def test_sell_token_is_no_outcome(
        self, strategy: SentimentStrategy, market: Market
    ) -> None:
        valuation = _make_valuation(fee_adjusted_edge=-0.06)
        knowledge = _make_knowledge(composite_signal=-0.5)
        result = await strategy.evaluate(market, valuation, knowledge)

        assert result is not None
        assert result.token_id == "no-token"

    @pytest.mark.asyncio()
    async def test_reasoning_contains_signal_value(
        self, strategy: SentimentStrategy, market: Market, valuation: ValuationResult
    ) -> None:
        knowledge = _make_knowledge(composite_signal=0.4)
        result = await strategy.evaluate(market, valuation, knowledge)

        assert result is not None
        assert (
            "+0.4" in result.reasoning
            or "0.400" in result.reasoning
            or "bullish" in result.reasoning
        )

    @pytest.mark.asyncio()
    async def test_confidence_is_positive(
        self, strategy: SentimentStrategy, market: Market, valuation: ValuationResult
    ) -> None:
        knowledge = _make_knowledge(composite_signal=0.5, confidence=0.8)
        result = await strategy.evaluate(market, valuation, knowledge)

        assert result is not None
        assert result.confidence > 0


# ── Baseline management ───────────────────────────────────────────────────────


class TestBaseline:
    def test_update_baseline_stores_value(self, strategy: SentimentStrategy) -> None:
        strategy.update_baseline("politics", -1.5)
        assert strategy._baselines["politics"] == -1.5

    def test_update_baseline_overwrites_existing(self, strategy: SentimentStrategy) -> None:
        strategy.update_baseline("economics", 2.0)
        strategy.update_baseline("economics", 3.5)
        assert strategy._baselines["economics"] == 3.5

    @pytest.mark.asyncio()
    async def test_baseline_note_appears_in_reasoning_when_set(
        self, strategy: SentimentStrategy, market: Market, valuation: ValuationResult
    ) -> None:
        strategy.update_baseline("politics", -0.5)
        knowledge = _make_knowledge(composite_signal=0.5, domain="politics")
        result = await strategy.evaluate(market, valuation, knowledge)

        assert result is not None
        assert "Baseline tone" in result.reasoning
