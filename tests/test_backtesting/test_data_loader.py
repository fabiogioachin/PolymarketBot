"""Tests for backtesting data loader (Parquet I/O)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

pyarrow = pytest.importorskip("pyarrow")

from app.backtesting.data_loader import (  # noqa: E402
    BacktestDataLoader,
    BacktestDataset,
    EventSnapshot,
    MarketSnapshot,
)

# ── Helpers ───────────────────────────────────────────────────────────


def _make_market_snapshot(
    *,
    market_id: str = "market-1",
    timestamp: datetime | None = None,
    yes_price: float = 0.6,
    no_price: float = 0.4,
) -> MarketSnapshot:
    return MarketSnapshot(
        timestamp=timestamp or datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC),
        market_id=market_id,
        question="Will X happen?",
        category="politics",
        yes_price=yes_price,
        no_price=no_price,
        volume=10_000.0,
        liquidity=5_000.0,
        fee_rate=0.0,
    )


def _make_event_snapshot(
    *,
    domain: str = "politics",
    timestamp: datetime | None = None,
) -> EventSnapshot:
    return EventSnapshot(
        timestamp=timestamp or datetime(2024, 1, 15, 14, 0, 0, tzinfo=UTC),
        domain=domain,
        event_type="volume_spike",
        query="US election",
        tone_value=-2.5,
        tone_baseline=1.0,
        volume_ratio=3.5,
        relevance_score=0.85,
    )


# ── Tests ─────────────────────────────────────────────────────────────


def test_save_and_load_market_snapshots_roundtrip(tmp_path: Path) -> None:
    """Saved market snapshots can be loaded back with identical data."""
    loader = BacktestDataLoader(data_dir=tmp_path)
    snapshots = [_make_market_snapshot(market_id=f"m-{i}") for i in range(3)]

    loader.save_market_snapshots(snapshots)
    loaded = loader.load_market_snapshots()

    assert len(loaded) == 3
    for original, result in zip(snapshots, loaded, strict=True):
        assert result.market_id == original.market_id
        assert result.question == original.question
        assert result.yes_price == pytest.approx(original.yes_price)
        assert result.no_price == pytest.approx(original.no_price)


def test_save_and_load_event_snapshots_roundtrip(tmp_path: Path) -> None:
    """Saved event snapshots can be loaded back with identical data."""
    loader = BacktestDataLoader(data_dir=tmp_path)
    events = [_make_event_snapshot(domain=f"domain-{i}") for i in range(3)]

    loader.save_event_snapshots(events)
    loaded = loader.load_event_snapshots()

    assert len(loaded) == 3
    for original, result in zip(events, loaded, strict=True):
        assert result.domain == original.domain
        assert result.event_type == original.event_type
        assert result.tone_value == pytest.approx(original.tone_value)
        assert result.volume_ratio == pytest.approx(original.volume_ratio)
        assert result.relevance_score == pytest.approx(original.relevance_score)


def test_load_market_snapshots_nonexistent_returns_empty(tmp_path: Path) -> None:
    """Loading from a nonexistent file returns an empty list."""
    loader = BacktestDataLoader(data_dir=tmp_path)
    result = loader.load_market_snapshots("nonexistent.parquet")
    assert result == []


def test_load_event_snapshots_nonexistent_returns_empty(tmp_path: Path) -> None:
    """Loading from a nonexistent events file returns an empty list."""
    loader = BacktestDataLoader(data_dir=tmp_path)
    result = loader.load_event_snapshots("nonexistent.parquet")
    assert result == []


def test_save_and_load_dataset_roundtrip(tmp_path: Path) -> None:
    """save_dataset and load_dataset preserve all snapshot data."""
    loader = BacktestDataLoader(data_dir=tmp_path)
    dataset = BacktestDataset(
        market_snapshots=[_make_market_snapshot()],
        event_snapshots=[_make_event_snapshot()],
    )

    loader.save_dataset(dataset)
    loaded = loader.load_dataset()

    assert len(loaded.market_snapshots) == 1
    assert len(loaded.event_snapshots) == 1
    assert loaded.market_snapshots[0].market_id == "market-1"
    assert loaded.event_snapshots[0].domain == "politics"


def test_dataset_start_and_end_date_computed_correctly(tmp_path: Path) -> None:
    """load_dataset computes start_date and end_date from all timestamps."""
    loader = BacktestDataLoader(data_dir=tmp_path)
    early = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
    mid = datetime(2024, 6, 15, 0, 0, 0, tzinfo=UTC)
    late = datetime(2024, 12, 31, 23, 59, 59, tzinfo=UTC)

    dataset = BacktestDataset(
        market_snapshots=[
            _make_market_snapshot(timestamp=mid),
            _make_market_snapshot(market_id="m-2", timestamp=early),
        ],
        event_snapshots=[
            _make_event_snapshot(timestamp=late),
        ],
    )

    loader.save_dataset(dataset)
    loaded = loader.load_dataset()

    assert loaded.start_date is not None
    assert loaded.end_date is not None
    # pyarrow strips tzinfo on round-trip; compare naive-aware safely
    assert loaded.start_date.replace(tzinfo=None) == early.replace(tzinfo=None)
    assert loaded.end_date.replace(tzinfo=None) == late.replace(tzinfo=None)


def test_empty_market_snapshots_save_and_load(tmp_path: Path) -> None:
    """Saving an empty list of market snapshots produces a loadable file."""
    loader = BacktestDataLoader(data_dir=tmp_path)
    loader.save_market_snapshots([])
    loaded = loader.load_market_snapshots()
    assert loaded == []


def test_empty_event_snapshots_save_and_load(tmp_path: Path) -> None:
    """Saving an empty list of event snapshots produces a loadable file."""
    loader = BacktestDataLoader(data_dir=tmp_path)
    loader.save_event_snapshots([])
    loaded = loader.load_event_snapshots()
    assert loaded == []


def test_multiple_snapshots_preserve_order(tmp_path: Path) -> None:
    """Multiple market snapshots are loaded in the same order they were saved."""
    loader = BacktestDataLoader(data_dir=tmp_path)
    ids = [f"market-{i:03d}" for i in range(10)]
    snapshots = [_make_market_snapshot(market_id=mid) for mid in ids]

    loader.save_market_snapshots(snapshots)
    loaded = loader.load_market_snapshots()

    assert [s.market_id for s in loaded] == ids


def test_prefix_parameter_saves_and_loads_separate_files(tmp_path: Path) -> None:
    """The prefix parameter routes data to correctly-named files."""
    loader = BacktestDataLoader(data_dir=tmp_path)
    dataset_a = BacktestDataset(
        market_snapshots=[_make_market_snapshot(market_id="a-market")],
        event_snapshots=[],
    )
    dataset_b = BacktestDataset(
        market_snapshots=[_make_market_snapshot(market_id="b-market")],
        event_snapshots=[],
    )

    loader.save_dataset(dataset_a, prefix="run_a_")
    loader.save_dataset(dataset_b, prefix="run_b_")

    loaded_a = loader.load_dataset(prefix="run_a_")
    loaded_b = loader.load_dataset(prefix="run_b_")

    assert loaded_a.market_snapshots[0].market_id == "a-market"
    assert loaded_b.market_snapshots[0].market_id == "b-market"


def test_market_snapshot_all_fields_preserved(tmp_path: Path) -> None:
    """Every field of MarketSnapshot survives a Parquet roundtrip."""
    loader = BacktestDataLoader(data_dir=tmp_path)
    ts = datetime(2024, 3, 20, 9, 30, 0, tzinfo=UTC)
    snap = MarketSnapshot(
        timestamp=ts,
        market_id="full-field-market",
        question="Full field test?",
        category="crypto",
        yes_price=0.72,
        no_price=0.28,
        volume=99_999.99,
        liquidity=12_345.67,
        fee_rate=0.072,
    )

    loader.save_market_snapshots([snap])
    loaded = loader.load_market_snapshots()

    r = loaded[0]
    assert r.market_id == snap.market_id
    assert r.question == snap.question
    assert r.category == snap.category
    assert r.yes_price == pytest.approx(snap.yes_price)
    assert r.no_price == pytest.approx(snap.no_price)
    assert r.volume == pytest.approx(snap.volume)
    assert r.liquidity == pytest.approx(snap.liquidity)
    assert r.fee_rate == pytest.approx(snap.fee_rate)


def test_event_snapshot_all_fields_preserved(tmp_path: Path) -> None:
    """Every field of EventSnapshot survives a Parquet roundtrip."""
    loader = BacktestDataLoader(data_dir=tmp_path)
    ts = datetime(2024, 5, 10, 18, 0, 0, tzinfo=UTC)
    event = EventSnapshot(
        timestamp=ts,
        domain="geopolitics",
        event_type="tone_shift",
        query="NATO summit",
        tone_value=-5.5,
        tone_baseline=0.3,
        volume_ratio=4.2,
        relevance_score=0.93,
    )

    loader.save_event_snapshots([event])
    loaded = loader.load_event_snapshots()

    r = loaded[0]
    assert r.domain == event.domain
    assert r.event_type == event.event_type
    assert r.query == event.query
    assert r.tone_value == pytest.approx(event.tone_value)
    assert r.tone_baseline == pytest.approx(event.tone_baseline)
    assert r.volume_ratio == pytest.approx(event.volume_ratio)
    assert r.relevance_score == pytest.approx(event.relevance_score)
