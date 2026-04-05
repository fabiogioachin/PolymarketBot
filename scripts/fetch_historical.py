"""Fetch historical market data for backtesting.

Usage:
    python scripts/fetch_historical.py --days 30 --output data/backtest
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.backtesting.data_loader import BacktestDataLoader, MarketSnapshot
from app.clients.polymarket_rest import PolymarketRestClient


async def fetch_historical(days: int, output_dir: str) -> None:
    """Fetch historical market data and save as Parquet snapshots."""
    client = PolymarketRestClient()
    loader = BacktestDataLoader(data_dir=output_dir)

    try:
        markets = await client.list_markets(limit=100)
        print(f"Fetched {len(markets)} markets")

        snapshots: list[MarketSnapshot] = []
        now = datetime.now(tz=UTC)

        for market in markets:
            yes_price = 0.5
            no_price = 0.5
            for o in market.outcomes:
                if o.outcome.lower() == "yes":
                    yes_price = o.price
                elif o.outcome.lower() == "no":
                    no_price = o.price

            snapshots.append(
                MarketSnapshot(
                    timestamp=now,
                    market_id=market.id,
                    question=market.question,
                    category=market.category.value,
                    yes_price=yes_price,
                    no_price=no_price,
                    volume=market.volume,
                    liquidity=market.liquidity,
                    fee_rate=market.fee_rate,
                )
            )

        if snapshots:
            path = loader.save_market_snapshots(snapshots)
            print(f"Saved {len(snapshots)} snapshots to {path}")
        else:
            print("No snapshots to save")
    finally:
        await client.close()


def main() -> None:
    """Entry point for the fetch_historical script."""
    parser = argparse.ArgumentParser(description="Fetch historical market data")
    parser.add_argument("--days", type=int, default=30, help="Number of days to fetch")
    parser.add_argument(
        "--output", type=str, default="data/backtest", help="Output directory"
    )
    args = parser.parse_args()

    asyncio.run(fetch_historical(args.days, args.output))


if __name__ == "__main__":
    main()
