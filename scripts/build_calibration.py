"""Build calibration curves from ResolutionDB data."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.logging import get_logger
from app.valuation.db import ResolutionDB

logger = get_logger(__name__)

_BUCKETS = [(i / 10, (i + 1) / 10) for i in range(10)]  # 0.0-0.1, ..., 0.9-1.0


async def build_curves(
    db_path: str = "data/resolutions.db",
    output_path: str = "data/calibration_curves.json",
    source: str | None = None,
) -> None:
    """Compute calibration curves: predicted probability bins vs actual resolution rate."""
    db = ResolutionDB(db_path=db_path)
    await db.init()

    try:
        resolutions = await db.get_resolutions(source=source)
    finally:
        await db.close()

    if not resolutions:
        print("No resolutions found.")
        return

    # Group by category
    by_category: dict[str, list] = defaultdict(list)
    for r in resolutions:
        by_category[r.category].append(r)
    by_category["_all"] = list(resolutions)

    curves: dict[str, dict[str, dict]] = {}

    for category, records in by_category.items():
        cat_curve: dict[str, dict] = {}

        for low, high in _BUCKETS:
            bucket_label = f"{low:.1f}-{high:.1f}"
            in_bucket = [
                r for r in records
                if low <= r.final_price < high or (high == 1.0 and r.final_price == 1.0)
            ]
            if not in_bucket:
                cat_curve[bucket_label] = {
                    "midpoint": (low + high) / 2,
                    "actual_rate": None,
                    "sample_size": 0,
                    "calibration_error": None,
                }
                continue

            actual_yes = sum(1 for r in in_bucket if r.resolved_yes)
            actual_rate = actual_yes / len(in_bucket)
            midpoint = (low + high) / 2
            cal_error = actual_rate - midpoint

            cat_curve[bucket_label] = {
                "midpoint": midpoint,
                "actual_rate": round(actual_rate, 4),
                "sample_size": len(in_bucket),
                "calibration_error": round(cal_error, 4),
            }

        curves[category] = cat_curve

    # Write output
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(
        json.dumps(curves, indent=2), encoding="utf-8"
    )

    print(f"Calibration curves written to {output_path}")
    print(f"Categories: {sorted(curves.keys())}")
    print(f"Total records: {len(resolutions)}")

    # Print summary
    if "_all" in curves:
        print("\nOverall calibration:")
        for bucket, data in curves["_all"].items():
            if data["sample_size"] > 0:
                print(
                    f"  {bucket}: actual={data['actual_rate']:.3f}, "
                    f"error={data['calibration_error']:+.3f}, n={data['sample_size']}"
                )


def main() -> None:
    parser = argparse.ArgumentParser(description="Build calibration curves")
    parser.add_argument("--db-path", default="data/resolutions.db", help="DB path")
    parser.add_argument(
        "--output", default="data/calibration_curves.json", help="Output JSON path"
    )
    parser.add_argument("--source", default=None, help="Filter by source (manifold|polymarket)")
    args = parser.parse_args()
    asyncio.run(build_curves(db_path=args.db_path, output_path=args.output, source=args.source))


if __name__ == "__main__":
    main()
