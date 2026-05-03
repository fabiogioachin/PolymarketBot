"""Tests for KnowledgeDrivenStrategy."""

from __future__ import annotations

import pytest

from app.models.knowledge import KnowledgeContext, Pattern, PatternMatch, PatternStatus
from app.models.market import Market, MarketCategory, Outcome
from app.models.signal import SignalType
from app.models.valuation import ValuationResult
from app.strategies.base import BaseStrategy
from app.strategies.knowledge_driven import KnowledgeDrivenStrategy

# ── Helpers / factories ───────────────────────────────────────────────────────


def _make_market(market_id: str = "mkt-1") -> Market:
    return Market(
        id=market_id,
        question="Will X happen?",
        category=MarketCategory.POLITICS,
        outcomes=[
            Outcome(token_id="yes-token", outcome="Yes", price=0.6),
            Outcome(token_id="no-token", outcome="No", price=0.4),
        ],
    )


def _make_valuation(
    market_id: str = "mkt-1",
    fee_adjusted_edge: float = 0.08,
    confidence: float = 0.6,
    market_price: float = 0.6,
) -> ValuationResult:
    return ValuationResult(
        market_id=market_id,
        fair_value=0.68,
        market_price=market_price,
        edge=0.08,
        confidence=confidence,
        fee_adjusted_edge=fee_adjusted_edge,
    )


def _make_pattern(
    name: str = "Test Pattern",
    confidence: float = 0.7,
    domain: str = "politics",
) -> Pattern:
    return Pattern(
        id=f"pattern-{name}",
        name=name,
        domain=domain,
        pattern_type="recurring",
        confidence=confidence,
        status=PatternStatus.ACTIVE,
    )


def _make_pattern_match(
    name: str = "Test Pattern",
    match_score: float = 0.8,
    pattern_confidence: float = 0.7,
) -> PatternMatch:
    return PatternMatch(
        pattern=_make_pattern(name=name, confidence=pattern_confidence),
        match_score=match_score,
        matched_keywords=["election", "incumbent"],
    )


def _make_knowledge(
    composite_signal: float = 0.5,
    confidence: float = 0.7,
    pattern_matches: list[PatternMatch] | None = None,
) -> KnowledgeContext:
    return KnowledgeContext(
        domain="politics",
        patterns=pattern_matches or [],
        composite_signal=composite_signal,
        confidence=confidence,
    )


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def strategy() -> KnowledgeDrivenStrategy:
    return KnowledgeDrivenStrategy()


@pytest.fixture()
def market() -> Market:
    return _make_market()


@pytest.fixture()
def valuation() -> ValuationResult:
    return _make_valuation()


# ── Protocol conformance ──────────────────────────────────────────────────────


class TestProtocol:
    def test_satisfies_base_strategy_protocol(self, strategy: KnowledgeDrivenStrategy) -> None:
        assert isinstance(strategy, BaseStrategy)

    def test_name_is_knowledge_driven(self, strategy: KnowledgeDrivenStrategy) -> None:
        assert strategy.name == "knowledge_driven"

    def test_domain_filter_is_empty(self, strategy: KnowledgeDrivenStrategy) -> None:
        assert strategy.domain_filter == []


# ── Returns None cases ────────────────────────────────────────────────────────


class TestReturnsNone:
    @pytest.mark.asyncio()
    async def test_returns_none_without_knowledge_context(
        self, strategy: KnowledgeDrivenStrategy, market: Market, valuation: ValuationResult
    ) -> None:
        result = await strategy.evaluate(market, valuation, knowledge=None)
        assert result is None

    @pytest.mark.asyncio()
    async def test_returns_none_with_empty_patterns(
        self, strategy: KnowledgeDrivenStrategy, market: Market, valuation: ValuationResult
    ) -> None:
        knowledge = _make_knowledge(pattern_matches=[])
        result = await strategy.evaluate(market, valuation, knowledge)
        assert result is None

    @pytest.mark.asyncio()
    async def test_returns_none_when_match_score_below_threshold(
        self, strategy: KnowledgeDrivenStrategy, market: Market, valuation: ValuationResult
    ) -> None:
        weak_match = _make_pattern_match(match_score=0.2, pattern_confidence=0.8)
        knowledge = _make_knowledge(
            composite_signal=0.7,
            pattern_matches=[weak_match],
        )
        result = await strategy.evaluate(market, valuation, knowledge)
        assert result is None

    @pytest.mark.asyncio()
    async def test_returns_none_when_pattern_confidence_below_threshold(
        self, strategy: KnowledgeDrivenStrategy, market: Market, valuation: ValuationResult
    ) -> None:
        weak_pattern = _make_pattern_match(match_score=0.9, pattern_confidence=0.1)
        knowledge = _make_knowledge(pattern_matches=[weak_pattern])
        result = await strategy.evaluate(market, valuation, knowledge)
        assert result is None

    @pytest.mark.asyncio()
    async def test_returns_none_when_sentiment_and_edge_disagree(
        self, strategy: KnowledgeDrivenStrategy, market: Market
    ) -> None:
        """Positive composite signal but negative valuation edge → no trade."""
        valuation = _make_valuation(fee_adjusted_edge=-0.06)
        strong_match = _make_pattern_match(match_score=0.9, pattern_confidence=0.8)
        knowledge = _make_knowledge(composite_signal=0.5, pattern_matches=[strong_match])
        result = await strategy.evaluate(market, valuation, knowledge)
        assert result is None


# ── Signal generation ─────────────────────────────────────────────────────────


class TestSignalGeneration:
    @pytest.mark.asyncio()
    async def test_buy_signal_on_positive_patterns_and_edge(
        self, strategy: KnowledgeDrivenStrategy, market: Market, valuation: ValuationResult
    ) -> None:
        strong_match = _make_pattern_match(
            name="Bull Pattern", match_score=0.9, pattern_confidence=0.8
        )
        knowledge = _make_knowledge(composite_signal=0.6, pattern_matches=[strong_match])
        result = await strategy.evaluate(market, valuation, knowledge)

        assert result is not None
        assert result.signal_type == SignalType.BUY
        assert result.strategy == "knowledge_driven"
        assert result.market_id == market.id
        assert result.confidence > 0

    @pytest.mark.asyncio()
    async def test_buy_no_signal_on_negative_patterns_and_negative_edge(
        self, strategy: KnowledgeDrivenStrategy, market: Market
    ) -> None:
        valuation = _make_valuation(fee_adjusted_edge=-0.07)
        strong_match = _make_pattern_match(
            name="Bear Pattern", match_score=0.85, pattern_confidence=0.7
        )
        knowledge = _make_knowledge(composite_signal=-0.5, pattern_matches=[strong_match])
        result = await strategy.evaluate(market, valuation, knowledge)

        assert result is not None
        assert result.signal_type == SignalType.BUY
        assert result.token_id == "no-token"
        assert result.edge_amount < 0

    @pytest.mark.asyncio()
    async def test_knowledge_sources_populated_from_pattern_names(
        self, strategy: KnowledgeDrivenStrategy, market: Market, valuation: ValuationResult
    ) -> None:
        matches = [
            _make_pattern_match(name="Pattern Alpha", match_score=0.8),
            _make_pattern_match(name="Pattern Beta", match_score=0.9),
        ]
        knowledge = _make_knowledge(composite_signal=0.7, pattern_matches=matches)
        result = await strategy.evaluate(market, valuation, knowledge)

        assert result is not None
        assert "Pattern Alpha" in result.knowledge_sources
        assert "Pattern Beta" in result.knowledge_sources

    @pytest.mark.asyncio()
    async def test_buy_token_is_yes_outcome(
        self, strategy: KnowledgeDrivenStrategy, market: Market, valuation: ValuationResult
    ) -> None:
        strong_match = _make_pattern_match(match_score=0.8)
        knowledge = _make_knowledge(composite_signal=0.5, pattern_matches=[strong_match])
        result = await strategy.evaluate(market, valuation, knowledge)

        assert result is not None
        assert result.token_id == "yes-token"

    @pytest.mark.asyncio()
    async def test_buy_no_token_is_no_outcome(
        self, strategy: KnowledgeDrivenStrategy, market: Market
    ) -> None:
        valuation = _make_valuation(fee_adjusted_edge=-0.06)
        strong_match = _make_pattern_match(match_score=0.8)
        knowledge = _make_knowledge(composite_signal=-0.4, pattern_matches=[strong_match])
        result = await strategy.evaluate(market, valuation, knowledge)

        assert result is not None
        assert result.signal_type == SignalType.BUY
        assert result.token_id == "no-token"

    @pytest.mark.asyncio()
    async def test_reasoning_mentions_patterns(
        self, strategy: KnowledgeDrivenStrategy, market: Market, valuation: ValuationResult
    ) -> None:
        strong_match = _make_pattern_match(name="Election Cycle", match_score=0.85)
        knowledge = _make_knowledge(composite_signal=0.6, pattern_matches=[strong_match])
        result = await strategy.evaluate(market, valuation, knowledge)

        assert result is not None
        assert "Election Cycle" in result.reasoning

    @pytest.mark.asyncio()
    async def test_skips_signal_when_no_outcome_missing(
        self, strategy: KnowledgeDrivenStrategy
    ) -> None:
        """Market without 'No' outcome → BUY NO signal must be skipped (no fallback)."""
        market = Market(
            id="mkt-only-yes",
            question="?",
            category=MarketCategory.POLITICS,
            outcomes=[Outcome(token_id="yes-token", outcome="Yes", price=0.6)],
        )
        valuation = _make_valuation(fee_adjusted_edge=-0.06)
        strong_match = _make_pattern_match(match_score=0.8)
        knowledge = _make_knowledge(composite_signal=-0.4, pattern_matches=[strong_match])
        result = await strategy.evaluate(market, valuation, knowledge)
        assert result is None

    @pytest.mark.asyncio()
    async def test_skips_signal_when_no_token_id_empty(
        self, strategy: KnowledgeDrivenStrategy
    ) -> None:
        """Outcome 'No' with empty token_id → skip signal."""
        market = Market(
            id="mkt-empty-no",
            question="?",
            category=MarketCategory.POLITICS,
            outcomes=[
                Outcome(token_id="yes-token", outcome="Yes", price=0.6),
                Outcome(token_id="", outcome="No", price=0.4),
            ],
        )
        valuation = _make_valuation(fee_adjusted_edge=-0.06)
        strong_match = _make_pattern_match(match_score=0.8)
        knowledge = _make_knowledge(composite_signal=-0.4, pattern_matches=[strong_match])
        result = await strategy.evaluate(market, valuation, knowledge)
        assert result is None

    @pytest.mark.asyncio()
    async def test_buy_no_signal_market_price_equals_no_price(
        self, strategy: KnowledgeDrivenStrategy, market: Market
    ) -> None:
        """For BUY-NO, market_price must be 1.0 - YES_price (the actual NO book price)."""
        yes_price = 0.6
        valuation = _make_valuation(fee_adjusted_edge=-0.06, market_price=yes_price)
        strong_match = _make_pattern_match(match_score=0.8)
        knowledge = _make_knowledge(composite_signal=-0.4, pattern_matches=[strong_match])
        result = await strategy.evaluate(market, valuation, knowledge)
        assert result is not None
        assert result.signal_type == SignalType.BUY
        assert result.market_price == pytest.approx(1.0 - yes_price)
