"""Backtest data loader: Parquet I/O for market snapshots and events."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app.core.logging import get_logger

try:
    import pyarrow as pa  # noqa: F401
    import pyarrow.parquet as pq  # noqa: F401

    _PYARROW_AVAILABLE = True
except ImportError:
    _PYARROW_AVAILABLE = False

logger = get_logger(__name__)


def _require_pyarrow() -> None:
    """Raise a clear error if pyarrow is not installed."""
    if not _PYARROW_AVAILABLE:
        raise ImportError(
            "pyarrow is required for Parquet I/O. "
            "Install it with: pip install pyarrow"
        )


@dataclass
class MarketSnapshot:
    """A point-in-time snapshot of a market."""

    timestamp: datetime
    market_id: str
    question: str = ""
    category: str = ""
    yes_price: float = 0.0
    no_price: float = 0.0
    volume: float = 0.0
    liquidity: float = 0.0
    fee_rate: float = 0.0


@dataclass
class EventSnapshot:
    """A point-in-time event record for backtesting."""

    timestamp: datetime
    domain: str = ""
    event_type: str = ""
    query: str = ""
    tone_value: float = 0.0
    tone_baseline: float = 0.0
    volume_ratio: float = 0.0
    relevance_score: float = 0.0


@dataclass
class BacktestDataset:
    """Complete dataset for a backtest run."""

    market_snapshots: list[MarketSnapshot] = field(default_factory=list)
    event_snapshots: list[EventSnapshot] = field(default_factory=list)
    start_date: datetime | None = None
    end_date: datetime | None = None


class BacktestDataLoader:
    """Loads and saves backtest data in Parquet format."""

    def __init__(self, data_dir: Path | str = "data/backtest") -> None:
        self._data_dir = Path(data_dir)

    def save_market_snapshots(
        self,
        snapshots: list[MarketSnapshot],
        filename: str = "markets.parquet",
    ) -> Path:
        """Save market snapshots to Parquet."""
        _require_pyarrow()
        import pyarrow as pa
        import pyarrow.parquet as pq

        self._data_dir.mkdir(parents=True, exist_ok=True)
        path = self._data_dir / filename

        table = pa.table(
            {
                "timestamp": [s.timestamp for s in snapshots],
                "market_id": [s.market_id for s in snapshots],
                "question": [s.question for s in snapshots],
                "category": [s.category for s in snapshots],
                "yes_price": [s.yes_price for s in snapshots],
                "no_price": [s.no_price for s in snapshots],
                "volume": [s.volume for s in snapshots],
                "liquidity": [s.liquidity for s in snapshots],
                "fee_rate": [s.fee_rate for s in snapshots],
            }
        )
        pq.write_table(table, path)
        logger.info("saved_market_snapshots", count=len(snapshots), path=str(path))
        return path

    def load_market_snapshots(
        self,
        filename: str = "markets.parquet",
    ) -> list[MarketSnapshot]:
        """Load market snapshots from Parquet."""
        _require_pyarrow()
        import pyarrow.parquet as pq

        path = self._data_dir / filename
        if not path.exists():
            return []

        table = pq.read_table(path)
        df = table.to_pydict()

        snapshots: list[MarketSnapshot] = []
        for i in range(len(df["market_id"])):
            ts = df["timestamp"][i]
            if not isinstance(ts, datetime):
                ts = ts.as_py() if hasattr(ts, "as_py") else datetime.fromisoformat(str(ts))
            snapshots.append(
                MarketSnapshot(
                    timestamp=ts,
                    market_id=df["market_id"][i],
                    question=df["question"][i],
                    category=df["category"][i],
                    yes_price=df["yes_price"][i],
                    no_price=df["no_price"][i],
                    volume=df["volume"][i],
                    liquidity=df["liquidity"][i],
                    fee_rate=df["fee_rate"][i],
                )
            )
        logger.info("loaded_market_snapshots", count=len(snapshots), path=str(path))
        return snapshots

    def save_event_snapshots(
        self,
        events: list[EventSnapshot],
        filename: str = "events.parquet",
    ) -> Path:
        """Save event snapshots to Parquet."""
        _require_pyarrow()
        import pyarrow as pa
        import pyarrow.parquet as pq

        self._data_dir.mkdir(parents=True, exist_ok=True)
        path = self._data_dir / filename

        table = pa.table(
            {
                "timestamp": [e.timestamp for e in events],
                "domain": [e.domain for e in events],
                "event_type": [e.event_type for e in events],
                "query": [e.query for e in events],
                "tone_value": [e.tone_value for e in events],
                "tone_baseline": [e.tone_baseline for e in events],
                "volume_ratio": [e.volume_ratio for e in events],
                "relevance_score": [e.relevance_score for e in events],
            }
        )
        pq.write_table(table, path)
        logger.info("saved_event_snapshots", count=len(events), path=str(path))
        return path

    def load_event_snapshots(
        self,
        filename: str = "events.parquet",
    ) -> list[EventSnapshot]:
        """Load event snapshots from Parquet."""
        _require_pyarrow()
        import pyarrow.parquet as pq

        path = self._data_dir / filename
        if not path.exists():
            return []

        table = pq.read_table(path)
        df = table.to_pydict()

        events: list[EventSnapshot] = []
        for i in range(len(df["domain"])):
            ts = df["timestamp"][i]
            if not isinstance(ts, datetime):
                ts = ts.as_py() if hasattr(ts, "as_py") else datetime.fromisoformat(str(ts))
            events.append(
                EventSnapshot(
                    timestamp=ts,
                    domain=df["domain"][i],
                    event_type=df["event_type"][i],
                    query=df["query"][i],
                    tone_value=df["tone_value"][i],
                    tone_baseline=df["tone_baseline"][i],
                    volume_ratio=df["volume_ratio"][i],
                    relevance_score=df["relevance_score"][i],
                )
            )
        logger.info("loaded_event_snapshots", count=len(events), path=str(path))
        return events

    def save_dataset(self, dataset: BacktestDataset, prefix: str = "") -> None:
        """Save a complete backtest dataset."""
        market_file = f"{prefix}markets.parquet" if prefix else "markets.parquet"
        event_file = f"{prefix}events.parquet" if prefix else "events.parquet"
        self.save_market_snapshots(dataset.market_snapshots, market_file)
        self.save_event_snapshots(dataset.event_snapshots, event_file)

    def load_dataset(self, prefix: str = "") -> BacktestDataset:
        """Load a complete backtest dataset."""
        market_file = f"{prefix}markets.parquet" if prefix else "markets.parquet"
        event_file = f"{prefix}events.parquet" if prefix else "events.parquet"
        markets = self.load_market_snapshots(market_file)
        events = self.load_event_snapshots(event_file)

        all_timestamps = [s.timestamp for s in markets] + [e.timestamp for e in events]
        start = min(all_timestamps) if all_timestamps else None
        end = max(all_timestamps) if all_timestamps else None

        return BacktestDataset(
            market_snapshots=markets,
            event_snapshots=events,
            start_date=start,
            end_date=end,
        )
