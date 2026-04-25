"""Tests for SnapshotWriter (Phase 13 S4a).

Test inventory:
    1. test_schema_roundtrip — DSSSnapshot serialises/deserialises without loss.
    2. test_atomic_write_success — tmp file absent after write; target file exists.
    3. test_atomic_write_failure_cleanup — original file preserved when os.replace raises.
    4. test_snapshot_size_under_200kb — 50 markets + 50 whales stays under 200 KB.
    5. test_tick_skipped_if_too_recent — second tick within 5 min is a no-op.
    6. test_tick_creates_file — integration: mock dependencies, verify file created
       and JSON parses back to valid DSSSnapshot.
    7. test_tick_creates_parent_dirs — output_path with missing parent dirs is
       created automatically.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.dss_snapshot import DSSSnapshot, DSSSnapshotMarket, DSSSnapshotWhale
from app.services.snapshot_writer import SnapshotWriter

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_snapshot(
    n_markets: int = 0,
    n_whales: int = 0,
) -> DSSSnapshot:
    """Build a realistic DSSSnapshot for size / roundtrip tests."""
    now = datetime.now(tz=UTC)

    markets = [
        DSSSnapshotMarket(
            market_id=f"market-{i:04d}",
            question=f"Will event {i} happen before 2025? (long question padding text here)",
            market_price=0.45 + (i % 10) * 0.01,
            fair_value=0.50 + (i % 10) * 0.01,
            edge_central=0.05,
            edge_lower=0.02,
            edge_dynamic=0.04,
            realized_volatility=0.012,
            has_open_position=(i % 5 == 0),
            recommendation="BUY",
        )
        for i in range(n_markets)
    ]

    whales = [
        DSSSnapshotWhale(
            timestamp=now - timedelta(minutes=i * 6),
            market_id=f"market-{i:04d}",
            wallet_address=f"0x{'a' * 20}{i:020d}",
            side="BUY" if i % 2 == 0 else "SELL",
            size_usd=float(100_000 + i * 1000),
            is_pre_resolution=(i % 10 == 0),
            wallet_total_pnl=float(i * 5000),
        )
        for i in range(n_whales)
    ]

    return DSSSnapshot(
        generated_at=now,
        config_version="polymarket-bot:0.1.0",
        weights={
            "base_rate": 0.15,
            "rule_analysis": 0.15,
            "microstructure": 0.15,
            "cross_market": 0.10,
            "event_signal": 0.15,
            "pattern_kg": 0.10,
            "cross_platform": 0.10,
            "crowd_calibration": 0.05,
            "temporal": 0.05,
        },
        volatility_config={
            "k_short": 0.5,
            "k_medium": 0.75,
            "k_long": 1.0,
            "velocity_alpha": 0.5,
            "strong_edge_threshold": 0.10,
            "window_minutes": 60.0,
        },
        monitored_markets=markets,
        recent_whales=whales,
        recent_insiders=[],
        popular_markets_top20=[
            {
                "market_id": f"pop-{i}",
                "question": f"Popular question {i}",
                "volume24h": float(1_000_000 - i * 10_000),
                "liquidity": float(500_000 - i * 5000),
            }
            for i in range(20)
        ],
        leaderboard_top50=[
            {
                "rank": i + 1,
                "wallet_address": f"0x{i:040x}",
                "pnl_usd": float(500_000 - i * 10_000),
                "win_rate": 0.6 - i * 0.001,
                "timeframe": "monthly",
            }
            for i in range(50)
        ],
        open_positions=[
            {
                "token_id": f"tok-{i}",
                "market_id": f"market-{i:04d}",
                "side": "BUY",
                "size": 10.0,
                "avg_price": 0.45,
                "current_price": 0.48,
            }
            for i in range(5)
        ],
        risk_state={
            "exposure_pct": 15.3,
            "circuit_breaker_open": False,
            "daily_pnl": 2.35,
        },
    )


def _make_writer(tmp_path: Path) -> SnapshotWriter:
    """Return a SnapshotWriter targeting a temp directory."""
    return SnapshotWriter(output_path=tmp_path / "intelligence_snapshot.json")


# ── Test 1: schema roundtrip ──────────────────────────────────────────────────


class TestSchemaRoundtrip:
    def test_schema_roundtrip(self) -> None:
        """DSSSnapshot serialises to JSON and back without losing any field."""
        original = _make_snapshot(n_markets=3, n_whales=2)

        json_str = original.model_dump_json()
        restored = DSSSnapshot.model_validate_json(json_str)

        assert restored.config_version == original.config_version
        assert restored.weights == original.weights
        assert len(restored.monitored_markets) == len(original.monitored_markets)
        assert len(restored.recent_whales) == len(original.recent_whales)
        assert restored.monitored_markets[0].market_id == original.monitored_markets[0].market_id
        assert (
            restored.monitored_markets[0].edge_dynamic
            == original.monitored_markets[0].edge_dynamic
        )
        assert restored.recent_whales[0].wallet_address == original.recent_whales[0].wallet_address
        assert restored.risk_state["exposure_pct"] == original.risk_state["exposure_pct"]


# ── Test 2: atomic write success ─────────────────────────────────────────────


class TestAtomicWrite:
    def test_atomic_write_success(self, tmp_path: Path) -> None:
        """After _write_atomic: target file exists and tmp file is absent."""
        writer = _make_writer(tmp_path)
        snapshot = _make_snapshot(n_markets=2, n_whales=1)

        writer._write_atomic(snapshot)

        target = tmp_path / "intelligence_snapshot.json"
        tmp = tmp_path / "intelligence_snapshot.json.tmp"
        assert target.exists(), "target file must exist after atomic write"
        assert not tmp.exists(), "tmp file must be absent after atomic write"

        # Verify the file parses back to a valid snapshot
        parsed = DSSSnapshot.model_validate_json(target.read_text(encoding="utf-8"))
        assert parsed.config_version == snapshot.config_version

    def test_atomic_write_failure_cleanup(self, tmp_path: Path) -> None:
        """When os.replace raises, the original target file is NOT corrupted."""
        writer = _make_writer(tmp_path)
        target = tmp_path / "intelligence_snapshot.json"
        original_content = '{"generated_at": "2020-01-01T00:00:00Z", "preserved": true}'
        target.write_text(original_content, encoding="utf-8")

        snapshot = _make_snapshot(n_markets=1, n_whales=0)

        # Simulate os.replace failure
        err = OSError("simulated disk full")
        with patch("os.replace", side_effect=err), pytest.raises(OSError):
            writer._write_atomic(snapshot)

        # Original file must still contain original content (not corrupted)
        assert target.read_text(encoding="utf-8") == original_content

        # The tmp file may or may not exist — we don't mandate its cleanup on
        # failure, only that the original is preserved.


# ── Test 3: snapshot size cap ─────────────────────────────────────────────────


class TestSnapshotSize:
    def test_snapshot_size_under_200kb(self) -> None:
        """50 markets + 50 whales snapshot must be under 200 KB."""
        snapshot = _make_snapshot(n_markets=50, n_whales=50)
        payload = snapshot.model_dump_json(indent=None)
        size_bytes = len(payload.encode("utf-8"))

        assert size_bytes < 200_000, (
            f"Snapshot size {size_bytes} bytes exceeds 200 KB cap "
            f"(localStorage limit). Review field sizes or cap lists."
        )


# ── Test 4: tick deduplication ────────────────────────────────────────────────


class TestTickDeduplication:
    @pytest.mark.asyncio()
    async def test_tick_skipped_if_too_recent(self, tmp_path: Path) -> None:
        """Second tick within 5 minutes must be a no-op (no file write)."""
        writer = _make_writer(tmp_path)
        target = tmp_path / "intelligence_snapshot.json"

        # Pre-set _last_tick to just 1 minute ago
        writer._last_tick = datetime.now(tz=UTC) - timedelta(minutes=1)

        # Patch _build_snapshot to track calls
        build_called = False

        async def _fake_build(now: datetime) -> DSSSnapshot:
            nonlocal build_called
            build_called = True
            return _make_snapshot()

        writer._build_snapshot = _fake_build  # type: ignore[method-assign]

        await writer.tick()

        assert not build_called, "_build_snapshot must NOT be called when < 5 min elapsed"
        assert not target.exists(), "No file should be written when tick is skipped"

    @pytest.mark.asyncio()
    async def test_tick_runs_after_interval(self, tmp_path: Path) -> None:
        """Tick runs when last_tick is exactly 5 minutes ago."""
        writer = _make_writer(tmp_path)

        # Set last_tick to exactly 5 minutes + 1 second ago
        writer._last_tick = datetime.now(tz=UTC) - timedelta(minutes=5, seconds=1)

        async def _fake_build(now: datetime) -> DSSSnapshot:
            return _make_snapshot(n_markets=1)

        writer._build_snapshot = _fake_build  # type: ignore[method-assign]

        await writer.tick()

        target = tmp_path / "intelligence_snapshot.json"
        assert target.exists(), "File should be written after interval elapsed"
        assert writer._last_tick is not None


# ── Test 5: integration tick creates file ─────────────────────────────────────


class TestTickIntegration:
    @pytest.mark.asyncio()
    async def test_tick_creates_file(self, tmp_path: Path) -> None:
        """Integration: tick() with no wired dependencies still creates a valid JSON file."""
        writer = _make_writer(tmp_path)
        # No dependencies wired — writer should produce empty/default sections.

        await writer.tick()

        target = tmp_path / "intelligence_snapshot.json"
        assert target.exists(), "Snapshot file must exist after tick()"

        raw = target.read_text(encoding="utf-8")
        data = json.loads(raw)
        # Must parse as valid DSSSnapshot
        snapshot = DSSSnapshot.model_validate(data)
        assert snapshot.generated_at is not None
        assert isinstance(snapshot.monitored_markets, list)
        assert isinstance(snapshot.recent_whales, list)
        assert isinstance(snapshot.risk_state, dict)
        # No wired dependencies → empty lists
        assert snapshot.monitored_markets == []
        assert snapshot.open_positions == []

    @pytest.mark.asyncio()
    async def test_tick_creates_parent_dirs(self, tmp_path: Path) -> None:
        """Snapshot is written even when the parent directory doesn't exist yet."""
        deep_path = tmp_path / "a" / "b" / "c" / "snapshot.json"
        writer = SnapshotWriter(output_path=deep_path)

        await writer.tick()

        assert deep_path.exists(), "File must be created even with missing parent dirs"
        DSSSnapshot.model_validate_json(deep_path.read_text(encoding="utf-8"))

    @pytest.mark.asyncio()
    async def test_tick_with_mock_engine(self, tmp_path: Path) -> None:
        """Tick with a mock engine exposing _last_valuations and _executor."""
        writer = _make_writer(tmp_path)

        # --- Mock risk manager ---
        mock_risk = MagicMock()
        mock_risk.current_exposure = 15.0
        mock_risk.daily_pnl = 1.5

        # --- Mock circuit breaker ---
        cb_state = MagicMock()
        cb_state.is_tripped = False
        mock_cb = MagicMock()
        mock_cb.check.return_value = cb_state

        # --- Mock executor (no open positions) ---
        mock_executor = AsyncMock()
        mock_executor.get_positions = AsyncMock(return_value=[])

        # --- Mock engine ---
        mock_engine = MagicMock()
        mock_engine._last_valuations = {}
        mock_engine._executor = mock_executor
        mock_engine._risk = mock_risk
        mock_engine._circuit_breaker = mock_cb
        mock_engine._market_service = None

        writer.set_engine(mock_engine)
        await writer.tick()

        target = tmp_path / "intelligence_snapshot.json"
        assert target.exists()

        snapshot = DSSSnapshot.model_validate_json(target.read_text(encoding="utf-8"))
        assert snapshot.risk_state["circuit_breaker_open"] is False
        # exposure_pct = 15.0 / 150.0 * 100 = 10.0
        assert abs(snapshot.risk_state["exposure_pct"] - 10.0) < 0.01
