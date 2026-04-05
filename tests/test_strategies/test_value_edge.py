"""Tests for ValueEdgeStrategy."""

import pytest

from app.models.market import Market, MarketCategory, Outcome
from app.models.signal import SignalType
from app.models.valuation import Recommendation, ValuationResult
from app.strategies.base import BaseStrategy
from app.strategies.value_edge import ValueEdgeStrategy

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


# ── Protocol compliance ────────────────────────────────────────────────────────


def test_satisfies_base_strategy_protocol() -> None:
    strategy = ValueEdgeStrategy()
    assert isinstance(strategy, BaseStrategy)


# ── BUY signal ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_buy_signal_when_positive_edge_above_threshold() -> None:
    strategy = ValueEdgeStrategy(min_edge=0.05, min_confidence=0.3)
    market = _make_market()
    valuation = _make_valuation(fee_adjusted_edge=0.10, confidence=0.6)

    signal = await strategy.evaluate(market, valuation)

    assert signal is not None
    assert signal.signal_type == SignalType.BUY
    assert signal.strategy == "value_edge"
    assert signal.market_id == "test-market"
    assert signal.edge_amount == pytest.approx(0.10)
    assert signal.confidence == pytest.approx(0.6)


@pytest.mark.asyncio
async def test_buy_signal_token_id_is_yes_outcome() -> None:
    strategy = ValueEdgeStrategy()
    market = _make_market()
    valuation = _make_valuation(fee_adjusted_edge=0.10, confidence=0.6)

    signal = await strategy.evaluate(market, valuation)

    assert signal is not None
    assert signal.token_id == "t1"  # YES outcome token


# ── Negative edge -> BUY NO token ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_buy_no_signal_when_negative_edge_beyond_threshold() -> None:
    """When YES is overpriced (negative edge), we BUY the NO token."""
    strategy = ValueEdgeStrategy(min_edge=0.05, min_confidence=0.3)
    market = _make_market()
    valuation = _make_valuation(
        fee_adjusted_edge=-0.10,
        edge=-0.10,
        fair_value=0.50,
        recommendation=Recommendation.SELL,
    )

    signal = await strategy.evaluate(market, valuation)

    assert signal is not None
    assert signal.signal_type == SignalType.BUY  # BUY the NO side
    assert signal.token_id == "t2"  # NO outcome token
    assert signal.edge_amount == pytest.approx(-0.10)


@pytest.mark.asyncio
async def test_negative_edge_token_id_is_no_outcome() -> None:
    """When YES is overpriced, the signal targets the NO outcome token."""
    strategy = ValueEdgeStrategy()
    market = _make_market()
    valuation = _make_valuation(fee_adjusted_edge=-0.10, confidence=0.6)

    signal = await strategy.evaluate(market, valuation)

    assert signal is not None
    assert signal.signal_type == SignalType.BUY
    assert signal.token_id == "t2"  # NO outcome token


# ── No signal (None) ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_signal_when_edge_below_threshold() -> None:
    strategy = ValueEdgeStrategy(min_edge=0.05)
    market = _make_market()
    valuation = _make_valuation(fee_adjusted_edge=0.02, confidence=0.7)

    assert await strategy.evaluate(market, valuation) is None


@pytest.mark.asyncio
async def test_no_signal_when_confidence_below_threshold() -> None:
    strategy = ValueEdgeStrategy(min_confidence=0.5)
    market = _make_market()
    valuation = _make_valuation(fee_adjusted_edge=0.15, confidence=0.2)

    assert await strategy.evaluate(market, valuation) is None


@pytest.mark.asyncio
async def test_no_signal_when_edge_exactly_at_threshold() -> None:
    """Edge exactly equal to min_edge should NOT trigger (strict >)."""
    strategy = ValueEdgeStrategy(min_edge=0.05)
    market = _make_market()
    valuation = _make_valuation(fee_adjusted_edge=0.05, confidence=0.7)

    assert await strategy.evaluate(market, valuation) is None


# ── Reasoning content ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reasoning_includes_key_values() -> None:
    strategy = ValueEdgeStrategy()
    market = _make_market()
    valuation = _make_valuation(
        fair_value=0.70,
        market_price=0.60,
        edge=0.10,
        fee_adjusted_edge=0.10,
        recommendation=Recommendation.BUY,
    )

    signal = await strategy.evaluate(market, valuation)

    assert signal is not None
    assert "0.700" in signal.reasoning or "0.70" in signal.reasoning
    assert "0.600" in signal.reasoning or "0.60" in signal.reasoning


# ── Custom thresholds ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_custom_min_edge_threshold() -> None:
    strategy = ValueEdgeStrategy(min_edge=0.20)
    market = _make_market()
    valuation = _make_valuation(fee_adjusted_edge=0.15, confidence=0.7)

    assert await strategy.evaluate(market, valuation) is None


@pytest.mark.asyncio
async def test_custom_min_edge_triggers_buy() -> None:
    strategy = ValueEdgeStrategy(min_edge=0.20)
    market = _make_market()
    valuation = _make_valuation(fee_adjusted_edge=0.25, confidence=0.7)

    signal = await strategy.evaluate(market, valuation)
    assert signal is not None
    assert signal.signal_type == SignalType.BUY


# ── Knowledge context ignored (primary strategy) ──────────────────────────────


@pytest.mark.asyncio
async def test_knowledge_context_does_not_affect_outcome() -> None:
    """ValueEdge ignores knowledge context — result should be the same."""
    from app.models.knowledge import KnowledgeContext

    strategy = ValueEdgeStrategy()
    market = _make_market()
    valuation = _make_valuation(fee_adjusted_edge=0.10, confidence=0.6)

    signal_no_knowledge = await strategy.evaluate(market, valuation)
    signal_with_knowledge = await strategy.evaluate(
        market, valuation, KnowledgeContext(domain="politics", composite_signal=0.9, confidence=0.9)
    )

    assert signal_no_knowledge is not None
    assert signal_with_knowledge is not None
    assert signal_no_knowledge.signal_type == signal_with_knowledge.signal_type
    assert signal_no_knowledge.edge_amount == signal_with_knowledge.edge_amount
