"""Tests for IntelligenceScheduler (Phase 13 Fix 4 — Team B).

Spec under test:
    - ``IntelligenceScheduler(config)`` constructor with ``set_*`` late-binding
      setters for whale/popular/leaderboard/snapshot orchestrators.
    - ``await scheduler.start()`` creates one ``asyncio.Task`` per wired
      orchestrator (up to 4: whale, popular, leaderboard, snapshot).
    - ``await scheduler.stop()`` cancels every task gracefully.
    - Each loop is ``while running: try: await orch.tick(...);
      except: log; sleep_backoff; continue``.
    - ``IntelligenceSchedulerConfig`` carries ``enabled`` (default True) and
      four ``*_interval_seconds`` fields (60 / 300 / 900 / 300).
    - The scheduler is INDEPENDENT from the trading engine — it runs even when
      the bot is stopped.

Sub-second timing is achieved by stubbing ``IntelligenceScheduler._sleep`` so
each loop iteration cycles instantly. The real implementation enforces a
minimum 1 s cadence, so we cannot rely on real ``asyncio.sleep``.
"""

from __future__ import annotations

import asyncio
import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.yaml_config import IntelligenceSchedulerConfig
from app.services.intelligence_scheduler import IntelligenceScheduler

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_orch(name: str = "orch", *, tick_return=None) -> MagicMock:
    """Return a mock orchestrator with an awaitable ``tick``."""
    m = MagicMock(name=name)
    m.tick = AsyncMock(name=f"{name}.tick", return_value=tick_return)
    return m


def _make_market_service(markets: list | None = None) -> MagicMock:
    """Mock MarketService that returns the given list of markets."""
    svc = MagicMock(name="market_service")
    svc.get_filtered_markets = AsyncMock(return_value=markets or [object()])
    return svc


def _make_scheduler(
    *,
    enabled: bool = True,
    whale_interval: int = 1,
    popular_interval: int = 1,
    leaderboard_interval: int = 1,
    snapshot_interval: int = 1,
    wire_whale: bool = True,
    wire_popular: bool = True,
    wire_leaderboard: bool = True,
    wire_snapshot: bool = True,
) -> tuple[
    IntelligenceScheduler,
    MagicMock,
    MagicMock,
    MagicMock,
    MagicMock,
]:
    """Factory: build a scheduler wired to four mock orchestrators.

    Returns ``(scheduler, whale, popular, leaderboard, snapshot)``.

    The scheduler's ``_sleep`` and ``_error_backoff_seconds`` are kept short
    by individual tests via ``_install_fast_sleep``.
    """
    cfg = IntelligenceSchedulerConfig(
        enabled=enabled,
        whale_interval_seconds=whale_interval,
        popular_interval_seconds=popular_interval,
        leaderboard_interval_seconds=leaderboard_interval,
        snapshot_interval_seconds=snapshot_interval,
    )
    scheduler = IntelligenceScheduler(config=cfg)

    whale = _make_orch("whale", tick_return=[])
    popular = _make_orch("popular", tick_return=[])
    leaderboard = _make_orch("leaderboard", tick_return=[])
    snapshot = _make_orch("snapshot")

    if wire_whale:
        scheduler.set_whale_orchestrator(whale)
        scheduler.set_market_service(_make_market_service())
    if wire_popular:
        scheduler.set_popular_markets_orchestrator(popular)
    if wire_leaderboard:
        scheduler.set_leaderboard_orchestrator(leaderboard)
    if wire_snapshot:
        scheduler.set_snapshot_writer(snapshot)

    return scheduler, whale, popular, leaderboard, snapshot


def _install_fast_sleep(scheduler: IntelligenceScheduler) -> None:
    """Patch the scheduler so every internal sleep is near-zero.

    The real ``_sleep`` enforces ≥1 s ticks and a 30 s error backoff. Tests
    need millisecond cadences, so we monkey-patch the bound method and the
    backoff field.
    """

    async def _fast_sleep(_seconds: float) -> None:
        await asyncio.sleep(0)

    scheduler._sleep = _fast_sleep  # type: ignore[method-assign]
    scheduler._error_backoff_seconds = 0.0


# ── Test 1: start spawns one task per wired orchestrator ──────────────────────


class TestStart:
    @pytest.mark.asyncio()
    async def test_start_creates_four_tasks(self) -> None:
        """All four orchestrators wired → four tasks scheduled and running."""
        scheduler, *_ = _make_scheduler()
        _install_fast_sleep(scheduler)

        await scheduler.start()
        try:
            assert len(scheduler._tasks) == 4, (
                f"expected 4 tasks (whale, popular, leaderboard, snapshot), "
                f"got {len(scheduler._tasks)}"
            )
            assert all(isinstance(t, asyncio.Task) for t in scheduler._tasks)
            assert all(not t.done() for t in scheduler._tasks), (
                "no task should be done immediately after start()"
            )
            assert scheduler.is_running is True
        finally:
            await scheduler.stop()


# ── Test 2: each loop invokes tick at the configured cadence ──────────────────


class TestLoopCadence:
    @pytest.mark.asyncio()
    async def test_whale_loop_invokes_tick_at_interval(self) -> None:
        """Whale loop must call ``whale.tick`` repeatedly."""
        scheduler, whale, *_ = _make_scheduler()
        _install_fast_sleep(scheduler)

        await scheduler.start()
        try:
            # With _sleep patched to ~0, the loop yields rapidly. Give the
            # event loop a few ticks to accumulate calls.
            await asyncio.sleep(0.05)
            assert whale.tick.call_count >= 3, (
                f"expected >=3 ticks with fast _sleep; got {whale.tick.call_count}"
            )
            # tick(markets) signature — markets list comes from MarketService.
            call_args = whale.tick.call_args_list[0]
            assert len(call_args.args) == 1, "whale.tick must be called with markets"
            assert isinstance(call_args.args[0], list)
        finally:
            await scheduler.stop()

    @pytest.mark.asyncio()
    async def test_snapshot_loop_invokes_tick(self) -> None:
        """Snapshot loop calls ``snapshot.tick()`` with no args."""
        scheduler, _, _, _, snapshot = _make_scheduler()
        _install_fast_sleep(scheduler)

        await scheduler.start()
        try:
            await asyncio.sleep(0.05)
            assert snapshot.tick.call_count >= 3
            assert snapshot.tick.call_args_list[0].args == ()
        finally:
            await scheduler.stop()


# ── Test 3: a tick exception does not kill the loop ───────────────────────────


class TestLoopResilience:
    @pytest.mark.asyncio()
    async def test_loop_survives_tick_exception(self) -> None:
        """An exception in ``tick()`` is logged and the loop keeps ticking."""
        scheduler, whale, *_ = _make_scheduler(
            wire_popular=False,
            wire_leaderboard=False,
            wire_snapshot=False,
        )
        _install_fast_sleep(scheduler)
        whale.tick.side_effect = [
            Exception("boom"),
            [],
            [],
            [],
            [],
            [],
        ]

        await scheduler.start()
        try:
            await asyncio.sleep(0.05)
            # First call raised, but the loop must keep ticking.
            assert whale.tick.call_count >= 3, (
                f"loop must survive the exception and keep ticking; "
                f"got {whale.tick.call_count} calls"
            )
        finally:
            await scheduler.stop()


# ── Test 4: disabled scheduler is a no-op ─────────────────────────────────────


class TestDisabled:
    @pytest.mark.asyncio()
    async def test_disabled_scheduler_does_nothing(self) -> None:
        """When ``config.enabled=False`` no tasks are created and no tick fires."""
        scheduler, whale, popular, leaderboard, snapshot = _make_scheduler(
            enabled=False,
        )
        _install_fast_sleep(scheduler)

        await scheduler.start()
        try:
            await asyncio.sleep(0.05)
            assert len(scheduler._tasks) == 0, (
                "disabled scheduler must not create any task"
            )
            assert scheduler.is_running is False
            assert whale.tick.call_count == 0
            assert popular.tick.call_count == 0
            assert leaderboard.tick.call_count == 0
            assert snapshot.tick.call_count == 0
        finally:
            await scheduler.stop()


# ── Test 5: stop cancels every task ───────────────────────────────────────────


class TestStop:
    @pytest.mark.asyncio()
    async def test_stop_cancels_all_tasks(self) -> None:
        """After ``stop()`` every task is cancelled or finished, list cleared."""
        scheduler, *_ = _make_scheduler()
        _install_fast_sleep(scheduler)

        await scheduler.start()
        await asyncio.sleep(0.01)
        # Snapshot the tasks BEFORE stop (the impl clears the list).
        tasks_before_stop = list(scheduler._tasks)
        await scheduler.stop()

        assert all(t.cancelled() or t.done() for t in tasks_before_stop), (
            "every scheduled task must be cancelled or done after stop()"
        )
        # The implementation also clears its internal list and flips the flag.
        assert scheduler._tasks == []
        assert scheduler.is_running is False


# ── Test 6: scheduler is independent of the trading engine ────────────────────


class TestEngineIndependence:
    @pytest.mark.asyncio()
    async def test_independence_from_bot(self) -> None:
        """Scheduler keeps ticking even when the trading engine is stopped.

        This is the contract: intelligence (whale/popular/leaderboard/snapshot)
        runs autonomously. The bot can be paused without affecting the DSS feed.
        Here we wire ONLY the snapshot writer (no engine dependency in the
        scheduler at all) and confirm it ticks.
        """
        # Mock engine in a stopped state — defensive: the scheduler must NOT
        # depend on it. We do not pass it to the scheduler in any way.
        mock_engine = MagicMock(name="engine")
        mock_engine._running = False  # engine is OFF

        scheduler, _, _, _, snapshot = _make_scheduler(
            wire_whale=False,
            wire_popular=False,
            wire_leaderboard=False,
        )
        _install_fast_sleep(scheduler)

        await scheduler.start()
        try:
            await asyncio.sleep(0.05)
            assert snapshot.tick.call_count >= 2, (
                f"snapshot writer must tick autonomously even when engine is "
                f"stopped; got {snapshot.tick.call_count} calls"
            )
            # And only the snapshot loop is running — exactly 1 task.
            assert len(scheduler._tasks) == 1
        finally:
            await scheduler.stop()


# ── Test 7: YAML config block parses end-to-end ───────────────────────────────
# (Mirrored in tests/test_core/test_yaml_config.py for coverage by that suite.)


class TestYamlConfigSchedulerBlock:
    def test_yaml_config_loads_scheduler_block(self, tmp_path: Path) -> None:
        """The ``intelligence.scheduler.*`` YAML block must hydrate the config."""
        from app.core.yaml_config import _load_config

        yaml_content = textwrap.dedent("""\
            intelligence:
              scheduler:
                enabled: true
                whale_interval_seconds: 45
                popular_interval_seconds: 200
                leaderboard_interval_seconds: 800
                snapshot_interval_seconds: 250
        """)
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml_content, encoding="utf-8")

        with patch("app.core.yaml_config._CONFIG_PATH", config_file):
            cfg = _load_config()

        sched = cfg.intelligence.scheduler
        assert sched.enabled is True
        assert sched.whale_interval_seconds == 45
        assert sched.popular_interval_seconds == 200
        assert sched.leaderboard_interval_seconds == 800
        assert sched.snapshot_interval_seconds == 250
