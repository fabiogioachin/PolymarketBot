"""Integration tests — whale/insider signals routed through assess_batch.

Phase 13 S4b: verifies that ``external_signals`` propagates the new
``whale_pressure`` / ``insider_pressure`` kwargs to the VAE's ValuationInput,
and that the VAE invariants from S1 are preserved (realized_vol=0, velocity=0
→ edge_dynamic == edge_central).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.models.market import (
    Market,
    MarketCategory,
    MarketStatus,
    Outcome,
)
from app.valuation.db import ResolutionDB
from app.valuation.engine import ValueAssessmentEngine


@pytest.fixture
async def db():
    database = ResolutionDB(db_path=":memory:")
    await database.init()
    yield database
    await database.close()


@pytest.fixture
def engine(db: ResolutionDB) -> ValueAssessmentEngine:
    return ValueAssessmentEngine(db)


def _make_market(
    market_id: str = "m1",
    yes_price: float = 0.50,
) -> Market:
    return Market(
        id=market_id,
        question="Will event X happen?",
        category=MarketCategory.POLITICS,
        status=MarketStatus.ACTIVE,
        outcomes=[
            Outcome(token_id="t1", outcome="Yes", price=yes_price),
            Outcome(token_id="t2", outcome="No", price=round(1.0 - yes_price, 4)),
        ],
        end_date=datetime.now(tz=UTC) + timedelta(days=7),
        volume=10_000.0,
        liquidity=5_000.0,
        fee_rate=0.0,
    )


async def test_external_signals_propagate_whale_pressure(
    engine: ValueAssessmentEngine,
) -> None:
    market = _make_market(yes_price=0.50)
    results = await engine.assess_batch(
        [market],
        external_signals={
            market.id: {"whale_pressure": 0.9},  # strong BUY whale
        },
    )
    assert len(results) == 1
    inputs = results[0].inputs
    assert inputs is not None
    assert inputs.whale_pressure_signal == 0.9
    # Whale BUY pressure pulls fair value above market price.
    assert results[0].fair_value > 0.50
    assert any(s.name == "whale_pressure" for s in results[0].edge_sources)


async def test_external_signals_propagate_insider_pressure(
    engine: ValueAssessmentEngine,
) -> None:
    market = _make_market(yes_price=0.50)
    results = await engine.assess_batch(
        [market],
        external_signals={
            market.id: {"insider_pressure": 0.9},  # strong BUY insider
        },
    )
    inputs = results[0].inputs
    assert inputs is not None
    assert inputs.insider_pressure_signal == 0.9
    assert any(s.name == "insider_pressure" for s in results[0].edge_sources)


async def test_whale_and_insider_both_active(
    engine: ValueAssessmentEngine,
) -> None:
    market = _make_market(yes_price=0.50)
    results = await engine.assess_batch(
        [market],
        external_signals={
            market.id: {
                "whale_pressure": 0.9,
                "insider_pressure": 0.9,
            },
        },
    )
    inputs = results[0].inputs
    assert inputs is not None
    assert inputs.whale_pressure_signal == 0.9
    assert inputs.insider_pressure_signal == 0.9
    names = {s.name for s in results[0].edge_sources}
    assert "whale_pressure" in names
    assert "insider_pressure" in names


async def test_no_whale_insider_signals_backward_compat(
    engine: ValueAssessmentEngine,
) -> None:
    """When not supplied, the signals must be None and NOT contribute."""
    market = _make_market(yes_price=0.50)
    results = await engine.assess_batch([market])
    inputs = results[0].inputs
    assert inputs is not None
    assert inputs.whale_pressure_signal is None
    assert inputs.insider_pressure_signal is None
    names = {s.name for s in results[0].edge_sources}
    assert "whale_pressure" not in names
    assert "insider_pressure" not in names


async def test_s1_invariant_preserved_with_whale_signal(
    engine: ValueAssessmentEngine,
) -> None:
    """realized_vol=0, velocity=0 → edge_dynamic == edge_central."""
    market = _make_market(yes_price=0.50)
    # No price_history → realized_vol=0, velocity=0 by default.
    results = await engine.assess_batch(
        [market],
        external_signals={
            market.id: {"whale_pressure": 0.8},
        },
    )
    r = results[0]
    # fee_adjusted_edge is the backward-compat alias for edge_central.
    assert r.edge_dynamic is not None
    assert abs(r.edge_dynamic - r.fee_adjusted_edge) < 1e-9


async def test_insider_pressure_signal_is_dampened(
    engine: ValueAssessmentEngine,
) -> None:
    """Insider signal must nudge fair value only slightly (±0.05 max scale).

    The insider mapping ``market_price + (signal - 0.5) * 0.1`` clamps the
    nudge at ±0.05 (signal in [0, 1]). With insider as the only firing
    signal, the impact on fair_value is exactly that nudge.

    Pre-P1-fix this delta was much smaller (~0.02) because base_rate also
    fired with a value anchored to market_price, dampening any other
    signal's contribution. The new gating excludes base_rate under sparse
    data, so the true insider scale is now visible.
    """
    market = _make_market(yes_price=0.50)
    neutral = await engine.assess_batch([market])
    amplified = await engine.assess_batch(
        [market],
        external_signals={market.id: {"insider_pressure": 0.9}},
    )
    # Insider signal 0.9 → market_price + (0.9 - 0.5) * 0.1 = 0.54.
    # Insider is the only firing signal here, so fair_value = 0.54 exactly,
    # delta = 0.04 — bounded by the formula's ±0.05 cap.
    delta = abs(amplified[0].fair_value - neutral[0].fair_value)
    assert delta == pytest.approx(0.04, abs=1e-6)
    assert delta <= 0.05  # within the documented ±0.05 cap
