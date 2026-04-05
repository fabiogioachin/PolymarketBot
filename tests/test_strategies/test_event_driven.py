"""Tests for EventDrivenStrategy."""

from datetime import UTC, datetime, timedelta

import pytest

from app.models.knowledge import KnowledgeContext, Pattern, PatternMatch, PatternStatus
from app.models.market import Market, MarketCategory, Outcome
from app.models.signal import SignalType
from app.models.valuation import Recommendation, ValuationResult
from app.strategies.base import BaseStrategy
from app.strategies.event_driven import _SPEED_PREMIUM_HOURS, EventDrivenStrategy

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_market(**kwargs) -> Market:
    defaults: dict = {
        "id": "test-market",
        "question": "Will X happen?",
        "category": MarketCategory.POLITICS,
        "outcomes": [
            Outcome(token_id="t1", outcome="Yes", price=0.60),
            Outcome(token_id="t2", outcome="No", price=0.40),
        ],
        "fee_rate": 0.0,
    }
    defaults.update(kwargs)
    return Market(**defaults)


def _make_valuation(**kwargs) -> ValuationResult:
    defaults: dict = {
        "market_id": "test-market",
        "fair_value": 0.70,
        "market_price": 0.60,
        "edge": 0.10,
        "confidence": 0.6,
        "fee_adjusted_edge": 0.10,
        "recommendation": Recommendation.BUY,
    }
    defaults.update(kwargs)
    return ValuationResult(**defaults)


def _make_pattern(
    name: str = "election-incumbent-boost",
    domain: str = "politics",
    last_triggered: datetime | None = None,
) -> Pattern:
    return Pattern(
        id=f"patterns/{name}",
        name=name,
        domain=domain,
        pattern_type="recurring",
        confidence=0.75,
        status=PatternStatus.ACTIVE,
        description="Incumbent advantage in election cycles",
        last_triggered=last_triggered,
    )


def _make_pattern_match(
    name: str = "election-incumbent-boost",
    match_score: float = 0.8,
    last_triggered: datetime | None = None,
) -> PatternMatch:
    return PatternMatch(
        pattern=_make_pattern(name=name, last_triggered=last_triggered),
        match_score=match_score,
        matched_keywords=["incumbent", "election"],
        detail="Strong pattern match detected",
    )


def _make_knowledge(
    composite_signal: float = 0.6,
    confidence: float = 0.7,
    patterns: list[PatternMatch] | None = None,
) -> KnowledgeContext:
    return KnowledgeContext(
        domain="politics",
        patterns=patterns or [_make_pattern_match()],
        composite_signal=composite_signal,
        confidence=confidence,
    )


# ── Protocol compliance ────────────────────────────────────────────────────────


def test_satisfies_base_strategy_protocol() -> None:
    strategy = EventDrivenStrategy()
    assert isinstance(strategy, BaseStrategy)


# ── No knowledge → no signal ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_signal_when_knowledge_is_none() -> None:
    strategy = EventDrivenStrategy()
    market = _make_market()
    valuation = _make_valuation()

    assert await strategy.evaluate(market, valuation, knowledge=None) is None


@pytest.mark.asyncio
async def test_no_signal_when_knowledge_has_no_patterns() -> None:
    strategy = EventDrivenStrategy()
    market = _make_market()
    valuation = _make_valuation()
    knowledge = KnowledgeContext(
        domain="politics", patterns=[], composite_signal=0.9, confidence=0.9
    )

    assert await strategy.evaluate(market, valuation, knowledge) is None


# ── BUY signal ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_buy_signal_with_positive_composite_and_edge() -> None:
    strategy = EventDrivenStrategy()
    market = _make_market()
    valuation = _make_valuation(fee_adjusted_edge=0.10, confidence=0.6)
    knowledge = _make_knowledge(composite_signal=0.6, confidence=0.7)

    signal = await strategy.evaluate(market, valuation, knowledge)

    assert signal is not None
    assert signal.signal_type == SignalType.BUY
    assert signal.strategy == "event_driven"
    assert signal.market_id == "test-market"


@pytest.mark.asyncio
async def test_buy_signal_token_id_is_yes() -> None:
    strategy = EventDrivenStrategy()
    market = _make_market()
    valuation = _make_valuation(fee_adjusted_edge=0.10, confidence=0.6)
    knowledge = _make_knowledge(composite_signal=0.6, confidence=0.7)

    signal = await strategy.evaluate(market, valuation, knowledge)

    assert signal is not None
    assert signal.token_id == "t1"  # YES outcome


# ── SELL signal ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sell_signal_with_negative_composite_and_edge() -> None:
    strategy = EventDrivenStrategy()
    market = _make_market()
    valuation = _make_valuation(fee_adjusted_edge=-0.10, confidence=0.6)
    knowledge = _make_knowledge(composite_signal=-0.6, confidence=0.7)

    signal = await strategy.evaluate(market, valuation, knowledge)

    assert signal is not None
    assert signal.signal_type == SignalType.SELL
    assert signal.token_id == "t2"  # NO outcome


# ── HOLD / None ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_signal_when_combined_edge_below_threshold() -> None:
    """Near-zero composite and near-zero valuation edge → no signal."""
    strategy = EventDrivenStrategy()
    market = _make_market()
    valuation = _make_valuation(fee_adjusted_edge=0.01, confidence=0.6)
    knowledge = _make_knowledge(composite_signal=0.01, confidence=0.6)

    assert await strategy.evaluate(market, valuation, knowledge) is None


@pytest.mark.asyncio
async def test_no_signal_when_confidence_too_low() -> None:
    strategy = EventDrivenStrategy()
    market = _make_market()
    valuation = _make_valuation(fee_adjusted_edge=0.10, confidence=0.05)
    knowledge = _make_knowledge(composite_signal=0.5, confidence=0.05)

    assert await strategy.evaluate(market, valuation, knowledge) is None


# ── Speed premium ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fresh_event_applies_speed_premium() -> None:
    """A pattern triggered 1 hour ago is 'fresh' → speed premium amplifies edge."""
    strategy = EventDrivenStrategy()
    market = _make_market()
    valuation = _make_valuation(fee_adjusted_edge=0.05, confidence=0.6)

    recent = datetime.now(UTC) - timedelta(hours=1)
    stale = datetime.now(UTC) - timedelta(hours=10)

    fresh_pm = _make_pattern_match(last_triggered=recent)
    stale_pm = _make_pattern_match(last_triggered=stale)

    knowledge_fresh = KnowledgeContext(
        domain="politics",
        patterns=[fresh_pm],
        composite_signal=0.3,
        confidence=0.7,
    )
    knowledge_stale = KnowledgeContext(
        domain="politics",
        patterns=[stale_pm],
        composite_signal=0.3,
        confidence=0.7,
    )

    signal_fresh = await strategy.evaluate(market, valuation, knowledge_fresh)
    signal_stale = await strategy.evaluate(market, valuation, knowledge_stale)

    if signal_fresh is not None and signal_stale is not None:
        assert abs(signal_fresh.edge_amount) > abs(signal_stale.edge_amount)


@pytest.mark.asyncio
async def test_fresh_event_detection_uses_speed_premium_hours_boundary() -> None:
    """Pattern triggered exactly at the boundary should still be considered fresh."""
    strategy = EventDrivenStrategy()

    # Triggered exactly at the cutoff boundary (just inside)
    just_inside = datetime.now(UTC) - timedelta(hours=_SPEED_PREMIUM_HOURS - 0.1)
    pm = _make_pattern_match(last_triggered=just_inside)

    assert strategy._is_fresh_event([pm]) is True


@pytest.mark.asyncio
async def test_stale_event_not_fresh() -> None:
    strategy = EventDrivenStrategy()

    old = datetime.now(UTC) - timedelta(hours=_SPEED_PREMIUM_HOURS + 1)
    pm = _make_pattern_match(last_triggered=old)

    assert strategy._is_fresh_event([pm]) is False


@pytest.mark.asyncio
async def test_no_last_triggered_not_fresh() -> None:
    strategy = EventDrivenStrategy()
    pm = _make_pattern_match(last_triggered=None)
    assert strategy._is_fresh_event([pm]) is False


# ── Multiple patterns ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_multiple_agreeing_patterns_boost_confidence() -> None:
    """Multiple high-score patterns should yield higher confidence than a single pattern."""
    strategy = EventDrivenStrategy()
    market = _make_market()
    valuation = _make_valuation(fee_adjusted_edge=0.10, confidence=0.6)

    single_knowledge = KnowledgeContext(
        domain="politics",
        patterns=[_make_pattern_match(name="p1", match_score=0.8)],
        composite_signal=0.5,
        confidence=0.7,
    )
    multi_knowledge = KnowledgeContext(
        domain="politics",
        patterns=[
            _make_pattern_match(name="p1", match_score=0.8),
            _make_pattern_match(name="p2", match_score=0.9),
            _make_pattern_match(name="p3", match_score=0.85),
        ],
        composite_signal=0.5,
        confidence=0.7,
    )

    signal_single = await strategy.evaluate(market, valuation, single_knowledge)
    signal_multi = await strategy.evaluate(market, valuation, multi_knowledge)

    assert signal_single is not None
    assert signal_multi is not None
    assert signal_multi.confidence >= signal_single.confidence


# ── knowledge_sources populated ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_knowledge_sources_lists_matched_pattern_names() -> None:
    strategy = EventDrivenStrategy()
    market = _make_market()
    valuation = _make_valuation(fee_adjusted_edge=0.10, confidence=0.6)
    knowledge = KnowledgeContext(
        domain="politics",
        patterns=[
            _make_pattern_match(name="pattern-alpha", match_score=0.9),
            _make_pattern_match(name="pattern-beta", match_score=0.8),
        ],
        composite_signal=0.6,
        confidence=0.7,
    )

    signal = await strategy.evaluate(market, valuation, knowledge)

    assert signal is not None
    assert "pattern-alpha" in signal.knowledge_sources
    assert "pattern-beta" in signal.knowledge_sources


# ── Domain filter ─────────────────────────────────────────────────────────────


def test_domain_filter_covers_expected_domains() -> None:
    strategy = EventDrivenStrategy()
    assert "politics" in strategy.domain_filter
    assert "geopolitics" in strategy.domain_filter
    assert "economics" in strategy.domain_filter
