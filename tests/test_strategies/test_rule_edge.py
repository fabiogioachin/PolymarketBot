"""Tests for RuleEdgeStrategy."""

import pytest

from app.models.market import Market, MarketCategory, Outcome
from app.models.signal import SignalType
from app.models.valuation import Recommendation, ValuationResult
from app.services.rule_parser import RuleAnalysis, RuleRiskLevel
from app.strategies.base import BaseStrategy
from app.strategies.rule_edge import RuleEdgeStrategy

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


def _make_clear_analysis(market_id: str = "test-market") -> RuleAnalysis:
    return RuleAnalysis(
        market_id=market_id,
        resolution_source="Associated Press",
        conditions=["This market resolves YES if X is confirmed by AP."],
        risk_level=RuleRiskLevel.CLEAR,
        ambiguities=[],
        edge_cases=[],
    )


def _make_ambiguous_analysis(market_id: str = "test-market") -> RuleAnalysis:
    return RuleAnalysis(
        market_id=market_id,
        resolution_source="",
        conditions=[],
        risk_level=RuleRiskLevel.AMBIGUOUS,
        ambiguities=["Ambiguous language: 'may be'"],
        edge_cases=[],
    )


def _make_high_risk_analysis(market_id: str = "test-market") -> RuleAnalysis:
    return RuleAnalysis(
        market_id=market_id,
        resolution_source="",
        conditions=[],
        risk_level=RuleRiskLevel.HIGH_RISK,
        ambiguities=["amb1", "amb2", "amb3"],
        edge_cases=["ec1", "ec2", "ec3"],
    )


# ── Protocol compliance ────────────────────────────────────────────────────────


def test_satisfies_base_strategy_protocol() -> None:
    strategy = RuleEdgeStrategy()
    assert isinstance(strategy, BaseStrategy)


# ── High-risk rules: always skip ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_signal_for_high_risk_rules() -> None:
    strategy = RuleEdgeStrategy()
    market = _make_market()
    strategy.set_rule_analysis(market.id, _make_high_risk_analysis())
    valuation = _make_valuation(fee_adjusted_edge=0.30, confidence=0.9)

    assert await strategy.evaluate(market, valuation) is None


# ── Clear rules: confidence boosted ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_buy_signal_for_clear_rules_with_trusted_source() -> None:
    strategy = RuleEdgeStrategy()
    market = _make_market()
    strategy.set_rule_analysis(market.id, _make_clear_analysis())
    valuation = _make_valuation(fee_adjusted_edge=0.10, confidence=0.6)

    signal = await strategy.evaluate(market, valuation)

    assert signal is not None
    assert signal.signal_type == SignalType.BUY
    # Confidence should be boosted above original 0.6
    assert signal.confidence > 0.6


@pytest.mark.asyncio
async def test_clear_rules_reasoning_mentions_clear() -> None:
    strategy = RuleEdgeStrategy()
    market = _make_market()
    strategy.set_rule_analysis(market.id, _make_clear_analysis())
    valuation = _make_valuation(fee_adjusted_edge=0.10, confidence=0.6)

    signal = await strategy.evaluate(market, valuation)

    assert signal is not None
    assert "clear_rules" in signal.reasoning.lower() or "clear" in signal.reasoning.lower()


# ── Ambiguous rules: confidence reduced ───────────────────────────────────────


@pytest.mark.asyncio
async def test_buy_signal_for_ambiguous_rules_reduced_confidence() -> None:
    strategy = RuleEdgeStrategy()
    market = _make_market()
    strategy.set_rule_analysis(market.id, _make_ambiguous_analysis())
    # Provide sufficient edge so we still get a signal despite reduced confidence
    valuation = _make_valuation(fee_adjusted_edge=0.20, confidence=0.7)

    signal = await strategy.evaluate(market, valuation)

    assert signal is not None
    # Confidence should be lower than original 0.7 due to AMBIGUOUS penalty
    assert signal.confidence < 0.7


@pytest.mark.asyncio
async def test_no_signal_when_ambiguous_rules_drop_confidence_too_low() -> None:
    strategy = RuleEdgeStrategy()
    market = _make_market()
    strategy.set_rule_analysis(market.id, _make_ambiguous_analysis())
    # Start with low confidence — ambiguity penalty should push below min threshold
    valuation = _make_valuation(fee_adjusted_edge=0.10, confidence=0.3)

    assert await strategy.evaluate(market, valuation) is None


# ── Negative edge → BUY NO token (BUG-2 regression) ──────────────────────────


@pytest.mark.asyncio
async def test_buy_no_token_when_negative_edge_with_clear_rules() -> None:
    """Regression for BUG-2: negative edge must emit BUY on NO token, not SELL.

    Mirrors the value_edge.py contract — when fair_value < market_price - min_edge,
    YES is overpriced, so the strategy buys NO (which profits when YES drops).
    """
    strategy = RuleEdgeStrategy()
    market = _make_market()
    strategy.set_rule_analysis(market.id, _make_clear_analysis())
    valuation = _make_valuation(
        fee_adjusted_edge=-0.10,
        edge=-0.10,
        fair_value=0.50,
        recommendation=Recommendation.SELL,
        confidence=0.6,
    )

    signal = await strategy.evaluate(market, valuation)

    assert signal is not None
    assert signal.signal_type == SignalType.BUY, "must be BUY (on NO), never SELL"
    assert signal.token_id == "t2", "must target NO outcome token"
    assert signal.edge_amount == pytest.approx(-0.10), "preserves signed edge"
    # Clear rules + trusted source still boost confidence on negative-edge BUY
    assert signal.confidence > 0.6, "clear rules boost should still apply"


@pytest.mark.asyncio
async def test_buy_no_token_when_negative_edge_with_ambiguous_rules() -> None:
    """Negative-edge BUY-NO behavior holds under ambiguous rules too."""
    strategy = RuleEdgeStrategy()
    market = _make_market()
    strategy.set_rule_analysis(market.id, _make_ambiguous_analysis())
    valuation = _make_valuation(
        fee_adjusted_edge=-0.20,
        edge=-0.20,
        fair_value=0.40,
        recommendation=Recommendation.SELL,
        confidence=0.7,
    )

    signal = await strategy.evaluate(market, valuation)

    assert signal is not None
    assert signal.signal_type == SignalType.BUY
    assert signal.token_id == "t2"
    assert signal.edge_amount == pytest.approx(-0.20)
    # Ambiguity penalty reduces confidence vs the original 0.7
    assert signal.confidence < 0.7


# ── No analysis pre-loaded: falls back to parser ─────────────────────────────


@pytest.mark.asyncio
async def test_falls_back_to_parser_when_no_stored_analysis() -> None:
    """Without a stored analysis, strategy should run the RuleParser inline."""
    strategy = RuleEdgeStrategy()
    market = _make_market(
        description="This market resolves YES as determined by Associated Press."
    )
    # No set_rule_analysis call
    valuation = _make_valuation(fee_adjusted_edge=0.10, confidence=0.6)

    # Should not raise; may or may not produce a signal depending on parsed risk
    signal = await strategy.evaluate(market, valuation)
    # Just verify no exception — result can be None or Signal
    assert signal is None or signal.market_id == "test-market"


# ── set_rule_analysis ─────────────────────────────────────────────────────────


def test_set_rule_analysis_stores_and_overwrites() -> None:
    strategy = RuleEdgeStrategy()
    analysis_v1 = _make_clear_analysis()
    analysis_v2 = _make_ambiguous_analysis()

    strategy.set_rule_analysis("test-market", analysis_v1)
    assert strategy._rule_analyses["test-market"].risk_level == RuleRiskLevel.CLEAR

    strategy.set_rule_analysis("test-market", analysis_v2)
    assert strategy._rule_analyses["test-market"].risk_level == RuleRiskLevel.AMBIGUOUS


# ── Edge cases: edge cases in analysis reduce confidence ──────────────────────


@pytest.mark.asyncio
async def test_edge_cases_reduce_confidence() -> None:
    strategy = RuleEdgeStrategy()
    market = _make_market()

    # Clear rules but with two edge cases
    analysis_with_edge_cases = RuleAnalysis(
        market_id="test-market",
        resolution_source="Associated Press",
        conditions=["This market resolves YES if AP says so."],
        risk_level=RuleRiskLevel.CLEAR,
        ambiguities=[],
        edge_cases=["Conditional resolution logic detected", "Deadline without timezone"],
    )
    strategy.set_rule_analysis(market.id, analysis_with_edge_cases)
    valuation = _make_valuation(fee_adjusted_edge=0.10, confidence=0.6)

    signal = await strategy.evaluate(market, valuation)

    if signal is not None:
        # Edge case penalty should result in lower confidence than pure clear boost
        clear_analysis = _make_clear_analysis()
        strategy_no_ec = RuleEdgeStrategy()
        strategy_no_ec.set_rule_analysis(market.id, clear_analysis)
        signal_no_ec = await strategy_no_ec.evaluate(market, valuation)
        if signal_no_ec is not None:
            assert signal.confidence < signal_no_ec.confidence


# ── Reasoning content ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reasoning_includes_source_and_risk_level() -> None:
    strategy = RuleEdgeStrategy()
    market = _make_market()
    strategy.set_rule_analysis(market.id, _make_clear_analysis())
    valuation = _make_valuation(fee_adjusted_edge=0.10, confidence=0.6)

    signal = await strategy.evaluate(market, valuation)

    assert signal is not None
    assert "Associated Press" in signal.reasoning
