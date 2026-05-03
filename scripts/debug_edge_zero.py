"""Diagnostic script for P1 'Edge near-zero in practice' (2026-04-27).

Reproduces the anchoring hypothesis: with no real signal data (no orderbook,
no history, no external signals, no historical resolutions), what does the
VAE produce? Expectation: fair_value ≈ market_price.
"""

import asyncio
import sys
from pathlib import Path

# Make sure we import from the project root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.market import Market, MarketCategory, Outcome
from app.valuation.db import ResolutionDB
from app.valuation.engine import ValueAssessmentEngine


async def _scenario(label: str, **assess_kwargs) -> None:
    db = ResolutionDB(":memory:")
    await db.init()
    engine = ValueAssessmentEngine(db)
    market = Market(
        id="probe-mkt",
        question="Will X happen by year end?",
        category=MarketCategory.POLITICS,
        outcomes=[
            Outcome(token_id="y", outcome="Yes", price=0.60),
            Outcome(token_id="n", outcome="No", price=0.40),
        ],
        fee_rate=0.0,
    )
    result = await engine.assess(market, **assess_kwargs)
    print(f"--- {label} ---", flush=True)
    print(
        f"market_price={result.market_price:.4f} "
        f"fair_value={result.fair_value:.4f} "
        f"edge={result.edge:.4f} "
        f"fee_adj_edge={result.fee_adjusted_edge:.4f} "
        f"edge_dynamic={result.edge_dynamic:.4f} "
        f"confidence={result.confidence:.4f}",
        flush=True,
    )
    for s in result.edge_sources:
        print(
            f"  signal={s.name:<20} contrib={s.contribution:+.4f} "
            f"conf={s.confidence:.2f} | {s.detail}",
            flush=True,
        )
    print(flush=True)


async def main() -> None:
    print("VAE diagnostic — sparse data scenarios\n", flush=True)
    await _scenario("S1: zero data, zero external signals")
    await _scenario(
        "S2: external whale_pressure=0.85 (BUY pressure), nothing else",
        whale_pressure=0.85,
    )
    await _scenario(
        "S3: external event_signal=0.40 (NO bias), nothing else",
        event_signal=0.40,
    )


if __name__ == "__main__":
    asyncio.run(main())
