"""Tests for ResolutionStrategy."""

from datetime import UTC, datetime, timedelta

import pytest

from app.models.market import Market, MarketCategory, Outcome
from app.models.signal import SignalType
from app.models.valuation import Recommendation, ValuationResult
from app.strategies.base import BaseStrategy
from app.strategies.resolution import ResolutionStrategy

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_market(
    days_from_now: float = 7,
    yes_price: float = 0.88,
    fee_rate: float = 0.0,
    **kwargs,
) -> Market:
    defaults: dict = {
        "id": "res-market",
        "question": "Will X happen?",
        "category": MarketCategory.SPORTS,
        "outcomes": [
            Outcome(token_id="yes-tok", outcome="Yes", price=yes_price),
            Outcome(token_id="no-tok", outcome="No", price=round(1 - yes_price, 4)),
        ],
        "end_date": datetime.now(tz=UTC) + timedelta(days=days_from_now),
        "fee_rate": fee_rate,
    }
    defaults.update(kwargs)
    return Market(**defaults)


def _make_valuation(
    fair_value: float = 0.95,
    market_price: float = 0.88,
    confidence: float = 0.8,
    **kwargs,
) -> ValuationResult:
    defaults: dict = {
        "market_id": "res-market",
        "fair_value": fair_value,
        "market_price": market_price,
        "edge": fair_value - market_price,
        "confidence": confidence,
        "fee_adjusted_edge": fair_value - market_price,
        "recommendation": Recommendation.BUY,
    }
    defaults.update(kwargs)
    return ValuationResult(**defaults)


# ── Protocol compliance ────────────────────────────────────────────────────────


def test_satisfies_base_strategy_protocol() -> None:
    strategy = ResolutionStrategy()
    assert isinstance(strategy, BaseStrategy)


def test_name_is_resolution() -> None:
    strategy = ResolutionStrategy()
    assert strategy.name == "resolution"


def test_domain_filter_is_empty() -> None:
    """Empty domain_filter means the strategy applies to all domains."""
    strategy = ResolutionStrategy()
    assert strategy.domain_filter == []


# ── None cases ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_returns_none_when_no_end_date() -> None:
    strategy = ResolutionStrategy()
    market = _make_market()
    market = market.model_copy(update={"end_date": None})
    valuation = _make_valuation()

    assert await strategy.evaluate(market, valuation) is None


@pytest.mark.asyncio
async def test_returns_none_when_end_date_too_far_away() -> None:
    """Markets resolving in >14 days are excluded."""
    strategy = ResolutionStrategy()
    market = _make_market(days_from_now=15)
    valuation = _make_valuation()

    assert await strategy.evaluate(market, valuation) is None


@pytest.mark.asyncio
async def test_returns_none_when_end_date_already_passed() -> None:
    strategy = ResolutionStrategy()
    market = _make_market(days_from_now=-1)
    valuation = _make_valuation()

    assert await strategy.evaluate(market, valuation) is None


@pytest.mark.asyncio
async def test_returns_none_when_fair_value_in_middle_range() -> None:
    """fair_value=0.50 is neither high nor low enough to generate a signal."""
    strategy = ResolutionStrategy()
    market = _make_market(days_from_now=7, yes_price=0.50)
    valuation = _make_valuation(fair_value=0.50, market_price=0.50)

    assert await strategy.evaluate(market, valuation) is None


# ── BUY signals ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_buy_signal_with_clear_discount_zero_fee() -> None:
    """fair_value=0.95, market_price=0.88, fee=0.0 → BUY with edge ~0.07."""
    strategy = ResolutionStrategy()
    market = _make_market(days_from_now=7, yes_price=0.88, fee_rate=0.0)
    valuation = _make_valuation(fair_value=0.95, market_price=0.88)

    signal = await strategy.evaluate(market, valuation)

    assert signal is not None
    assert signal.signal_type == SignalType.BUY
    assert signal.strategy == "resolution"
    assert signal.market_id == "res-market"
    assert signal.token_id == "yes-tok"
    assert signal.edge_amount == pytest.approx(0.07, abs=1e-4)


@pytest.mark.asyncio
async def test_buy_signal_fee_exceeds_edge_no_signal() -> None:
    """fair_value=0.95, price=0.88 → gross edge 0.07, fee=0.072 → profit < 0, no signal."""
    strategy = ResolutionStrategy()
    market = _make_market(days_from_now=7, yes_price=0.88, fee_rate=0.072)
    valuation = _make_valuation(fair_value=0.95, market_price=0.88)

    signal = await strategy.evaluate(market, valuation)

    assert signal is None


@pytest.mark.asyncio
async def test_buy_signal_discount_below_min_discount_no_signal() -> None:
    """fair_value=0.90, price=0.88 → discount 0.02 < MIN_DISCOUNT(0.03) → no signal."""
    strategy = ResolutionStrategy()
    market = _make_market(days_from_now=7, yes_price=0.88, fee_rate=0.0)
    valuation = _make_valuation(fair_value=0.90, market_price=0.88)

    signal = await strategy.evaluate(market, valuation)

    assert signal is None


@pytest.mark.asyncio
async def test_buy_signal_reasoning_contains_key_fields() -> None:
    strategy = ResolutionStrategy()
    market = _make_market(days_from_now=7, yes_price=0.88, fee_rate=0.0)
    valuation = _make_valuation(fair_value=0.95, market_price=0.88)

    signal = await strategy.evaluate(market, valuation)

    assert signal is not None
    assert "fair_value=0.95" in signal.reasoning
    assert "price=0.88" in signal.reasoning
    assert "days_left=" in signal.reasoning


# ── SELL signals ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sell_signal_low_probability_market() -> None:
    """fair_value=0.10, yes_price=0.85 → NO is mispriced, buy NO (SELL signal)."""
    strategy = ResolutionStrategy()
    # yes_price=0.85 → no_price=0.15; expected_no_value=0.90; discount=0.75
    market = _make_market(days_from_now=7, yes_price=0.85, fee_rate=0.0)
    valuation = _make_valuation(fair_value=0.10, market_price=0.85)

    signal = await strategy.evaluate(market, valuation)

    assert signal is not None
    assert signal.signal_type == SignalType.SELL
    assert signal.strategy == "resolution"
    assert signal.token_id == "no-tok"
    assert signal.edge_amount > 0


@pytest.mark.asyncio
async def test_sell_signal_reasoning_contains_key_fields() -> None:
    strategy = ResolutionStrategy()
    market = _make_market(days_from_now=5, yes_price=0.85, fee_rate=0.0)
    valuation = _make_valuation(fair_value=0.10, market_price=0.85)

    signal = await strategy.evaluate(market, valuation)

    assert signal is not None
    assert "fair_value=0.10" in signal.reasoning
    assert "days_left=" in signal.reasoning


# ── Time weight: confidence comparison ────────────────────────────────────────


@pytest.mark.asyncio
async def test_time_weight_closer_resolution_has_higher_confidence() -> None:
    """Market 1 day from resolution should have higher confidence than 13 days."""
    strategy = ResolutionStrategy()
    base_confidence = 0.8
    valuation = _make_valuation(fair_value=0.95, market_price=0.88, confidence=base_confidence)

    market_1d = _make_market(days_from_now=1, yes_price=0.88)
    market_13d = _make_market(days_from_now=13, yes_price=0.88)

    signal_1d = await strategy.evaluate(market_1d, valuation)
    signal_13d = await strategy.evaluate(market_13d, valuation)

    assert signal_1d is not None
    assert signal_13d is not None
    assert signal_1d.confidence > signal_13d.confidence


@pytest.mark.asyncio
async def test_time_weight_exactly_at_boundary_14_days() -> None:
    """Market exactly at 14.0 days should be excluded (> MAX_DAYS_TO_RESOLUTION)."""
    strategy = ResolutionStrategy()
    # Use 14.01 to be safely above the threshold
    market = _make_market(days_from_now=14.01)
    valuation = _make_valuation(fair_value=0.95, market_price=0.88)

    assert await strategy.evaluate(market, valuation) is None


# ── Knowledge context is ignored ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_knowledge_context_does_not_affect_outcome() -> None:
    from app.models.knowledge import KnowledgeContext

    strategy = ResolutionStrategy()
    market = _make_market(days_from_now=7, yes_price=0.88)
    valuation = _make_valuation(fair_value=0.95, market_price=0.88)

    signal_no_knowledge = await strategy.evaluate(market, valuation)
    signal_with_knowledge = await strategy.evaluate(
        market,
        valuation,
        KnowledgeContext(domain="sports", composite_signal=0.9, confidence=0.9),
    )

    assert signal_no_knowledge is not None
    assert signal_with_knowledge is not None
    assert signal_no_knowledge.signal_type == signal_with_knowledge.signal_type
    assert signal_no_knowledge.edge_amount == signal_with_knowledge.edge_amount
