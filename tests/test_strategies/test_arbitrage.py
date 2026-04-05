"""Tests for ArbitrageStrategy."""

import pytest

from app.models.market import Market, MarketCategory, Outcome
from app.models.signal import SignalType
from app.models.valuation import Recommendation, ValuationResult
from app.strategies.arbitrage import ArbitrageStrategy
from app.strategies.base import BaseStrategy

# -- Helpers -------------------------------------------------------------------


def _make_market(yes_price: float = 0.60, no_price: float = 0.40, **kwargs) -> Market:
    defaults: dict = {
        "id": "test-market",
        "question": "Will X happen?",
        "category": MarketCategory.POLITICS,
        "outcomes": [
            Outcome(token_id="t1", outcome="Yes", price=yes_price),
            Outcome(token_id="t2", outcome="No", price=no_price),
        ],
        "fee_rate": 0.0,
    }
    defaults.update(kwargs)
    return Market(**defaults)


def _make_valuation(**kwargs) -> ValuationResult:
    defaults: dict = {
        "market_id": "test-market",
        "fair_value": 0.60,
        "market_price": 0.60,
        "edge": 0.0,
        "confidence": 0.5,
        "fee_adjusted_edge": 0.0,
        "recommendation": Recommendation.HOLD,
    }
    defaults.update(kwargs)
    return ValuationResult(**defaults)


# -- Protocol compliance -------------------------------------------------------


def test_satisfies_base_strategy_protocol() -> None:
    strategy = ArbitrageStrategy()
    assert isinstance(strategy, BaseStrategy)


# -- BUY (buy-both) signal -----------------------------------------------------


@pytest.mark.asyncio
async def test_buy_signal_when_total_below_one_minus_fee() -> None:
    """YES(0.40) + NO(0.40) = 0.80; fee=0.0; profit=0.20 -> BUY both legs."""
    strategy = ArbitrageStrategy()
    market = _make_market(yes_price=0.40, no_price=0.40, category=MarketCategory.POLITICS)
    valuation = _make_valuation()

    signals = await strategy.evaluate(market, valuation)

    assert signals is not None
    assert isinstance(signals, list)
    assert len(signals) == 2

    yes_sig, no_sig = signals
    assert yes_sig.signal_type == SignalType.BUY
    assert no_sig.signal_type == SignalType.BUY
    assert yes_sig.strategy == "arbitrage"
    assert no_sig.strategy == "arbitrage"
    assert yes_sig.token_id == "t1"  # YES token
    assert no_sig.token_id == "t2"  # NO token
    assert yes_sig.edge_amount == pytest.approx(0.20)
    assert no_sig.edge_amount == pytest.approx(0.20)


@pytest.mark.asyncio
async def test_buy_signal_market_price_per_leg() -> None:
    """Each leg carries the market price of its own outcome token."""
    strategy = ArbitrageStrategy()
    market = _make_market(yes_price=0.35, no_price=0.45, category=MarketCategory.POLITICS)
    valuation = _make_valuation()

    signals = await strategy.evaluate(market, valuation)

    assert signals is not None
    yes_sig, no_sig = signals
    assert yes_sig.market_price == pytest.approx(0.35)
    assert no_sig.market_price == pytest.approx(0.45)


@pytest.mark.asyncio
async def test_buy_signal_profit_above_one_percent_threshold() -> None:
    """Profit must exceed 1% to emit signal."""
    strategy = ArbitrageStrategy()
    # YES(0.485) + NO(0.485) = 0.97; fee=0; profit=0.03
    market = _make_market(yes_price=0.485, no_price=0.485, category=MarketCategory.POLITICS)
    valuation = _make_valuation()

    signals = await strategy.evaluate(market, valuation)

    assert signals is not None
    assert len(signals) == 2
    assert signals[0].signal_type == SignalType.BUY
    assert signals[0].edge_amount == pytest.approx(0.03)


@pytest.mark.asyncio
async def test_no_buy_signal_when_profit_below_one_percent() -> None:
    """YES(0.497) + NO(0.497) = 0.994; fee=0; profit=0.006 < 1% -> no signal."""
    strategy = ArbitrageStrategy()
    market = _make_market(yes_price=0.497, no_price=0.497, category=MarketCategory.POLITICS)
    valuation = _make_valuation()

    signals = await strategy.evaluate(market, valuation)

    assert signals is None


# -- SELL (sell-both) signal ---------------------------------------------------


@pytest.mark.asyncio
async def test_sell_signal_when_total_above_one_plus_fee() -> None:
    """YES(0.65) + NO(0.55) = 1.20; fee=0; profit=0.20 -> SELL both legs."""
    strategy = ArbitrageStrategy()
    market = _make_market(yes_price=0.65, no_price=0.55, category=MarketCategory.POLITICS)
    valuation = _make_valuation()

    signals = await strategy.evaluate(market, valuation)

    assert signals is not None
    assert isinstance(signals, list)
    assert len(signals) == 2

    yes_sig, no_sig = signals
    assert yes_sig.signal_type == SignalType.SELL
    assert no_sig.signal_type == SignalType.SELL
    assert yes_sig.token_id == "t1"
    assert no_sig.token_id == "t2"
    assert yes_sig.edge_amount == pytest.approx(0.20)
    assert yes_sig.market_price == pytest.approx(0.65)
    assert no_sig.market_price == pytest.approx(0.55)


@pytest.mark.asyncio
async def test_sell_signal_respects_fee_offset() -> None:
    """For crypto (fee=7.2%): total=1.10; net=1.10-1.0-0.072=0.028 -> SELL."""
    strategy = ArbitrageStrategy()
    market = _make_market(yes_price=0.60, no_price=0.50, category=MarketCategory.CRYPTO)
    valuation = _make_valuation()

    signals = await strategy.evaluate(market, valuation)

    assert signals is not None
    assert len(signals) == 2
    assert signals[0].signal_type == SignalType.SELL
    assert signals[0].edge_amount == pytest.approx(1.10 - 1.0 - 0.072, abs=1e-6)


# -- No signal -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_signal_when_prices_sum_to_one() -> None:
    strategy = ArbitrageStrategy()
    market = _make_market(yes_price=0.60, no_price=0.40)
    valuation = _make_valuation()

    assert await strategy.evaluate(market, valuation) is None


@pytest.mark.asyncio
async def test_no_signal_when_insufficient_outcomes() -> None:
    strategy = ArbitrageStrategy()
    market = Market(
        id="test-market",
        question="Will X happen?",
        category=MarketCategory.POLITICS,
        outcomes=[Outcome(token_id="t1", outcome="Yes", price=0.60)],
    )
    valuation = _make_valuation()

    assert await strategy.evaluate(market, valuation) is None


@pytest.mark.asyncio
async def test_no_signal_when_missing_yes_or_no_outcome() -> None:
    strategy = ArbitrageStrategy()
    market = Market(
        id="test-market",
        question="Will X happen?",
        category=MarketCategory.POLITICS,
        outcomes=[
            Outcome(token_id="t1", outcome="Option A", price=0.40),
            Outcome(token_id="t2", outcome="Option B", price=0.40),
        ],
    )
    valuation = _make_valuation()

    # No YES/NO outcomes -- strategy must return None safely
    assert await strategy.evaluate(market, valuation) is None


# -- Fee rates by category -----------------------------------------------------


def test_fee_rate_politics_is_zero() -> None:
    strategy = ArbitrageStrategy()
    market = _make_market(category=MarketCategory.POLITICS)
    assert strategy._fee_rate(market) == 0.0


def test_fee_rate_geopolitics_is_zero() -> None:
    strategy = ArbitrageStrategy()
    market = _make_market(category=MarketCategory.GEOPOLITICS)
    assert strategy._fee_rate(market) == 0.0


def test_fee_rate_crypto_is_7_2_percent() -> None:
    strategy = ArbitrageStrategy()
    market = _make_market(category=MarketCategory.CRYPTO)
    assert strategy._fee_rate(market) == pytest.approx(0.072)


def test_fee_rate_sports_is_3_percent() -> None:
    strategy = ArbitrageStrategy()
    market = _make_market(category=MarketCategory.SPORTS)
    assert strategy._fee_rate(market) == pytest.approx(0.03)


def test_fee_rate_unknown_category_uses_default() -> None:
    strategy = ArbitrageStrategy()
    market = _make_market(category=MarketCategory.OTHER)
    assert strategy._fee_rate(market) == pytest.approx(ArbitrageStrategy.DEFAULT_FEE)


# -- Fee-aware: no buy when profit wiped out by fee ----------------------------


@pytest.mark.asyncio
async def test_no_buy_signal_when_fee_wipes_out_profit() -> None:
    """For crypto (fee=7.2%): total=0.97; profit before fee=0.03; net=-0.042 -> no signal."""
    strategy = ArbitrageStrategy()
    market = _make_market(yes_price=0.485, no_price=0.485, category=MarketCategory.CRYPTO)
    valuation = _make_valuation()

    assert await strategy.evaluate(market, valuation) is None


# -- Confidence scaled from profit ---------------------------------------------


@pytest.mark.asyncio
async def test_confidence_capped_at_one() -> None:
    """Large profit (>10%) should not produce confidence > 1.0."""
    strategy = ArbitrageStrategy()
    market = _make_market(yes_price=0.20, no_price=0.20, category=MarketCategory.POLITICS)
    valuation = _make_valuation()

    signals = await strategy.evaluate(market, valuation)

    assert signals is not None
    for sig in signals:
        assert sig.confidence <= 1.0


# -- Both legs share timestamp -------------------------------------------------


@pytest.mark.asyncio
async def test_both_legs_share_same_timestamp() -> None:
    """Both legs of an arbitrage trade must have identical timestamps."""
    strategy = ArbitrageStrategy()
    market = _make_market(yes_price=0.40, no_price=0.40, category=MarketCategory.POLITICS)
    valuation = _make_valuation()

    signals = await strategy.evaluate(market, valuation)

    assert signals is not None
    assert signals[0].timestamp == signals[1].timestamp
