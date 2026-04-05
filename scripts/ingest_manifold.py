"""Ingest resolved Manifold Markets into ResolutionDB for calibration data."""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.clients.manifold_client import ManifoldClient
from app.core.logging import get_logger
from app.models.valuation import MarketResolution
from app.valuation.db import ResolutionDB

logger = get_logger(__name__)

# Map Manifold group slugs to our categories
_CATEGORY_MAP: dict[str, str] = {
    "politics": "politics",
    "us-politics": "politics",
    "world-politics": "geopolitics",
    "geopolitics": "geopolitics",
    "economics": "economics",
    "finance": "economics",
    "crypto": "crypto",
    "cryptocurrency": "crypto",
    "bitcoin": "crypto",
    "sports": "sports",
    "nfl": "sports",
    "nba": "sports",
    "science": "science",
    "technology": "science",
    "entertainment": "entertainment",
}


def _classify_category(group_slugs: list[str]) -> str:
    """Map Manifold group slugs to MarketCategory value."""
    for slug in group_slugs:
        slug_lower = slug.lower()
        if slug_lower in _CATEGORY_MAP:
            return _CATEGORY_MAP[slug_lower]
    return "other"


async def ingest(
    limit: int = 5000,
    min_volume: float = 500.0,
    db_path: str = "data/resolutions.db",
) -> None:
    """Paginate through Manifold resolved binary markets and insert into ResolutionDB."""
    client = ManifoldClient(rate_limit=5)
    db = ResolutionDB(db_path=db_path)
    await db.init()

    total_fetched = 0
    total_inserted = 0
    before: str | None = None

    try:
        while total_fetched < limit:
            batch_size = min(500, limit - total_fetched)
            markets = await client.list_markets(limit=batch_size, before=before)
            if not markets:
                break

            for m in markets:
                total_fetched += 1
                # Filter: only resolved binary markets with sufficient volume
                if not m.is_resolved or m.outcome_type != "BINARY":
                    continue
                if m.volume < min_volume:
                    continue
                if m.resolution not in ("YES", "NO"):
                    continue

                resolution_date = None
                if m.resolution_time:
                    resolution_date = datetime.fromtimestamp(
                        m.resolution_time / 1000, tz=UTC
                    )

                resolution = MarketResolution(
                    market_id=f"manifold:{m.id}",
                    category=_classify_category(m.group_slugs),
                    question=m.question,
                    final_price=m.probability,
                    resolved_yes=m.resolution == "YES",
                    resolution_date=resolution_date,
                    volume=m.volume,
                    source="manifold",
                )
                await db.add_resolution(resolution)
                total_inserted += 1

            # Use last market's ID as cursor for pagination
            before = markets[-1].id

            if total_fetched % 500 == 0:
                logger.info(
                    "ingest_progress",
                    fetched=total_fetched,
                    inserted=total_inserted,
                )

    finally:
        await db.close()
        await client.close()

    logger.info(
        "ingest_complete",
        total_fetched=total_fetched,
        total_inserted=total_inserted,
    )
    print(f"Done: fetched {total_fetched} markets, inserted {total_inserted} resolutions")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest Manifold resolved markets")
    parser.add_argument("--limit", type=int, default=5000, help="Max markets to fetch")
    parser.add_argument("--min-volume", type=float, default=500.0, help="Min volume filter")
    parser.add_argument("--db-path", default="data/resolutions.db", help="DB path")
    args = parser.parse_args()
    asyncio.run(ingest(limit=args.limit, min_volume=args.min_volume, db_path=args.db_path))


if __name__ == "__main__":
    main()
