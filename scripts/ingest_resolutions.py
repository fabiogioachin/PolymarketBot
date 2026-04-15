"""Ingest synthetic resolution data for demo mode.

Populates ResolutionDB with realistic market resolutions
so that BaseRateAnalyzer has statistical priors.

Usage:
    python scripts/ingest_resolutions.py
"""

from __future__ import annotations

import asyncio
import random
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.models.valuation import MarketResolution
from app.valuation.db import ResolutionDB

# ~55% YES, ~45% NO — realistic Polymarket base rate
_RESOLUTIONS: list[tuple[str, str, str, bool]] = [
    # ── politics (7 YES, 5 NO) ──────────────────────────────────────────
    ("pol-001", "politics", "Will Congress pass a government funding bill before the October deadline?", True),
    ("pol-002", "politics", "Will the Supreme Court overturn the Chevron deference doctrine?", True),
    ("pol-003", "politics", "Will the US Senate confirm a new Cabinet nominee?", True),
    ("pol-004", "politics", "Will Congress pass new TikTok legislation restricting the app?", True),
    ("pol-005", "politics", "Will the debt ceiling be raised without a US sovereign default?", True),
    ("pol-006", "politics", "Will the Electoral College certify the 2024 election results without incident?", True),
    ("pol-007", "politics", "Will a major US infrastructure spending bill pass Congress?", True),
    ("pol-008", "politics", "Will there be a US government shutdown lasting more than 7 days?", False),
    ("pol-009", "politics", "Will the US pass comprehensive immigration reform legislation?", False),
    ("pol-010", "politics", "Will the House impeach any executive branch official in Q2?", False),
    ("pol-011", "politics", "Will ranked choice voting be banned statewide in a major US state?", False),
    ("pol-012", "politics", "Will Congress successfully override a presidential veto?", False),

    # ── geopolitics (6 YES, 6 NO) ────────────────────────────────────────
    ("geo-001", "geopolitics", "Will NATO formally accept a new member state?", True),
    ("geo-002", "geopolitics", "Will Iran and Israel engage in a direct military exchange?", True),
    ("geo-003", "geopolitics", "Will the UN Security Council pass a ceasefire resolution on Gaza?", True),
    ("geo-004", "geopolitics", "Will there be a significant US-China diplomatic incident?", True),
    ("geo-005", "geopolitics", "Will the BRICS bloc expand to include at least one new member country?", True),
    ("geo-006", "geopolitics", "Will China impose significant new tariffs on European goods?", True),
    ("geo-007", "geopolitics", "Will Ukraine retake Crimea by end of year?", False),
    ("geo-008", "geopolitics", "Will Russia formally default on foreign currency debt?", False),
    ("geo-009", "geopolitics", "Will there be a ceasefire in Gaza by mid-year?", False),
    ("geo-010", "geopolitics", "Will North Korea conduct a nuclear weapon test?", False),
    ("geo-011", "geopolitics", "Will there be a coup attempt in a G20 nation?", False),
    ("geo-012", "geopolitics", "Will Russia voluntarily withdraw troops from Ukrainian territory?", False),

    # ── economics (7 YES, 5 NO) ──────────────────────────────────────────
    ("eco-001", "economics", "Will the Federal Reserve cut interest rates before year end?", True),
    ("eco-002", "economics", "Will US CPI inflation fall below 3% by mid-year?", True),
    ("eco-003", "economics", "Will the Bitcoin spot ETF receive final SEC approval?", True),
    ("eco-004", "economics", "Will US annualized GDP growth exceed 2%?", True),
    ("eco-005", "economics", "Will the European Central Bank cut rates before the Federal Reserve?", True),
    ("eco-006", "economics", "Will gold prices reach a new all-time high?", True),
    ("eco-007", "economics", "Will US unemployment remain below 5% for the full year?", True),
    ("eco-008", "economics", "Will the US economy enter a technical recession (two consecutive quarters)?", False),
    ("eco-009", "economics", "Will Brent crude oil prices exceed $100 per barrel?", False),
    ("eco-010", "economics", "Will the US trade deficit narrow by more than 10%?", False),
    ("eco-011", "economics", "Will China's GDP contract in absolute nominal terms?", False),
    ("eco-012", "economics", "Will US residential housing prices fall more than 10% nationally?", False),

    # ── crypto (6 YES, 6 NO) ─────────────────────────────────────────────
    ("cry-001", "crypto", "Will Bitcoin price exceed $100,000 USD?", True),
    ("cry-002", "crypto", "Will an Ethereum spot ETF receive SEC approval?", True),
    ("cry-003", "crypto", "Will the Bitcoin halving event occur in Q2?", True),
    ("cry-004", "crypto", "Will a major crypto exchange face significant regulatory enforcement action?", True),
    ("cry-005", "crypto", "Will Ripple reach a favorable settlement with the SEC?", True),
    ("cry-006", "crypto", "Will a central bank digital currency launch in at least one major economy?", True),
    ("cry-007", "crypto", "Will Solana overtake Ethereum in total market capitalization?", False),
    ("cry-008", "crypto", "Will DeFi total value locked exceed $200 billion?", False),
    ("cry-009", "crypto", "Will there be a single DeFi hack exceeding $500 million in losses?", False),
    ("cry-010", "crypto", "Will a new Layer-1 blockchain enter the top 5 by market cap?", False),
    ("cry-011", "crypto", "Will NFT market trading volume recover to 2022 peak levels?", False),
    ("cry-012", "crypto", "Will the overall crypto market cap exceed $5 trillion?", False),

    # ── sports (7 YES, 5 NO) ─────────────────────────────────────────────
    ("spt-001", "sports", "Will Real Madrid win the UEFA Champions League?", True),
    ("spt-002", "sports", "Will the United States lead the overall Olympic Games medal count?", True),
    ("spt-003", "sports", "Will the Kansas City Chiefs win Super Bowl LVIII?", True),
    ("spt-004", "sports", "Will Max Verstappen win the Formula 1 World Championship?", True),
    ("spt-005", "sports", "Will India win the ICC Cricket World Cup?", True),
    ("spt-006", "sports", "Will a first-time Grand Slam singles champion emerge in tennis?", True),
    ("spt-007", "sports", "Will Tiger Woods compete in at least one major golf tournament?", True),
    ("spt-008", "sports", "Will Lewis Hamilton win a Formula 1 race?", False),
    ("spt-009", "sports", "Will a non-European team win UEFA Euro 2024?", False),
    ("spt-010", "sports", "Will the NBA season face significant interruption due to labor dispute?", False),
    ("spt-011", "sports", "Will Major League Baseball have a work stoppage?", False),
    ("spt-012", "sports", "Will the 2024 Tour de France have a first-time overall winner?", False),
]


def _random_date(days_back_min: int = 7, days_back_max: int = 180) -> datetime:
    """Return a random resolution date within the last 6 months."""
    offset = random.randint(days_back_min, days_back_max)
    return datetime.now(tz=UTC) - timedelta(days=offset)


def _random_volume() -> float:
    """Return a realistic market volume (10k–500k USDC)."""
    return round(random.uniform(10_000, 500_000), 2)


async def ingest(db_path: str = "data/resolutions.db") -> None:
    """Populate ResolutionDB with synthetic resolutions."""
    db = ResolutionDB(db_path)
    await db.init()

    inserted = 0
    for market_id, category, question, resolved_yes in _RESOLUTIONS:
        resolution = MarketResolution(
            market_id=market_id,
            category=category,
            question=question,
            final_price=1.0 if resolved_yes else 0.0,
            resolved_yes=resolved_yes,
            resolution_date=_random_date(),
            volume=_random_volume(),
            source="synthetic",
        )
        await db.add_resolution(resolution)
        inserted += 1

    await db.close()

    yes_count = sum(1 for _, _, _, yes in _RESOLUTIONS if yes)
    no_count = len(_RESOLUTIONS) - yes_count
    print(
        f"Ingested {inserted} synthetic resolutions: "
        f"{yes_count} YES ({yes_count / inserted:.0%}), "
        f"{no_count} NO ({no_count / inserted:.0%})"
    )
    print(f"Database: {db_path}")


if __name__ == "__main__":
    asyncio.run(ingest())
