"""Intelligence scheduler — drives intelligence ingest INDEPENDENTLY of trading.

Phase 13 Fix 4 (Team A): decouple intelligence ingest from ``ExecutionEngine.tick``
so DSS / dashboards stay fresh even when the bot is in monitoring-only mode.

Four independent asyncio tasks tick at their own cadence:

    whale       → ``WhaleOrchestrator.tick(markets)``
    popular     → ``PopularMarketsOrchestrator.tick()``
    leaderboard → ``LeaderboardOrchestrator.tick(timeframe)``
    snapshot    → ``SnapshotWriter.tick()``

Every loop is self-healing: a failed tick logs and sleeps before retrying,
never killing the task.

Wiring is late-binding (mirrors :class:`SnapshotWriter`): get the singleton
from :func:`app.core.dependencies.get_intelligence_scheduler`, attach the
orchestrators with ``set_*``, then call :meth:`start`. The recommended boot
path is :func:`app.core.dependencies.start_intelligence_scheduler` invoked
from the FastAPI lifespan (handled by the ``main.py`` Fix in this Phase 13
batch).
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger
from app.core.yaml_config import IntelligenceSchedulerConfig

if TYPE_CHECKING:
    from app.services.leaderboard_orchestrator import LeaderboardOrchestrator
    from app.services.market_service import MarketService
    from app.services.popular_markets_orchestrator import (
        PopularMarketsOrchestrator,
    )
    from app.services.snapshot_writer import SnapshotWriter
    from app.services.whale_orchestrator import WhaleOrchestrator

logger = get_logger(__name__)


class IntelligenceScheduler:
    """Run intelligence orchestrators on independent asyncio loops.

    Construction is cheap and side-effect-free. Tasks are spawned only when
    :meth:`start` is awaited (so dependency wiring can happen first).
    """

    def __init__(self, config: IntelligenceSchedulerConfig) -> None:
        self._config = config
        self._whale_orch: WhaleOrchestrator | None = None
        self._popular_orch: PopularMarketsOrchestrator | None = None
        self._leaderboard_orch: LeaderboardOrchestrator | None = None
        self._snapshot_writer: SnapshotWriter | None = None
        self._market_service: MarketService | None = None
        self._leaderboard_timeframe: str = "week"

        self._tasks: list[asyncio.Task[None]] = []
        self._running: bool = False
        self._error_backoff_seconds: float = 30.0

    # ── Late-binding setters ─────────────────────────────────────────────

    def set_whale_orchestrator(self, orch: WhaleOrchestrator | None) -> None:
        self._whale_orch = orch

    def set_popular_markets_orchestrator(
        self, orch: PopularMarketsOrchestrator | None
    ) -> None:
        self._popular_orch = orch

    def set_leaderboard_orchestrator(
        self, orch: LeaderboardOrchestrator | None
    ) -> None:
        self._leaderboard_orch = orch

    def set_snapshot_writer(self, writer: SnapshotWriter | None) -> None:
        self._snapshot_writer = writer

    def set_market_service(self, market_service: MarketService | None) -> None:
        """Wire the market service so the whale loop can fetch active markets."""
        self._market_service = market_service

    def set_leaderboard_timeframe(self, timeframe: str) -> None:
        """Override the leaderboard timeframe (default: ``"week"``)."""
        self._leaderboard_timeframe = timeframe

    # ── Public lifecycle ─────────────────────────────────────────────────

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self) -> None:
        """Spawn one asyncio task per enabled orchestrator.

        Idempotent: subsequent calls while already running are no-ops.
        """
        if self._running:
            logger.debug("intelligence_scheduler_already_running")
            return
        if not self._config.enabled:
            logger.info("intelligence_scheduler_disabled")
            return

        self._running = True
        spawned: list[str] = []

        if self._whale_orch is not None:
            task = asyncio.create_task(
                self._whale_loop(),
                name="intelligence_scheduler.whale",
            )
            self._tasks.append(task)
            spawned.append("whale")

        if self._popular_orch is not None:
            task = asyncio.create_task(
                self._popular_loop(),
                name="intelligence_scheduler.popular",
            )
            self._tasks.append(task)
            spawned.append("popular")

        if self._leaderboard_orch is not None:
            task = asyncio.create_task(
                self._leaderboard_loop(),
                name="intelligence_scheduler.leaderboard",
            )
            self._tasks.append(task)
            spawned.append("leaderboard")

        if self._snapshot_writer is not None:
            task = asyncio.create_task(
                self._snapshot_loop(),
                name="intelligence_scheduler.snapshot",
            )
            self._tasks.append(task)
            spawned.append("snapshot")

        logger.info(
            "intelligence_scheduler_started",
            tasks=spawned,
            task_ids=[id(t) for t in self._tasks],
            whale_interval_seconds=self._config.whale_interval_seconds,
            popular_interval_seconds=self._config.popular_interval_seconds,
            leaderboard_interval_seconds=(
                self._config.leaderboard_interval_seconds
            ),
            snapshot_interval_seconds=self._config.snapshot_interval_seconds,
        )

    async def stop(self) -> None:
        """Cancel all loops and await their teardown."""
        if not self._running:
            return
        self._running = False
        for task in self._tasks:
            if not task.done():
                task.cancel()
        # Drain
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._tasks.clear()
        logger.info("intelligence_scheduler_stopped")

    # ── Loops ────────────────────────────────────────────────────────────

    async def _whale_loop(self) -> None:
        """Poll whale trades for currently-active markets."""
        interval = max(1, int(self._config.whale_interval_seconds))
        while self._running:
            try:
                markets = await self._fetch_active_markets()
                if markets:
                    whales = await self._whale_orch.tick(markets)  # type: ignore[union-attr]
                    if whales:
                        logger.info(
                            "intelligence_scheduler_whale_tick",
                            whales=len(whales),
                            markets=len(markets),
                        )
                else:
                    logger.debug(
                        "intelligence_scheduler_whale_skip_no_markets"
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "intelligence_scheduler_whale_failed",
                    error=str(exc),
                )
                await self._sleep(self._error_backoff_seconds)
                continue
            await self._sleep(interval)

    async def _popular_loop(self) -> None:
        interval = max(1, int(self._config.popular_interval_seconds))
        while self._running:
            try:
                snapshot = await self._popular_orch.tick()  # type: ignore[union-attr]
                if snapshot:
                    logger.info(
                        "intelligence_scheduler_popular_tick",
                        count=len(snapshot),
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "intelligence_scheduler_popular_failed",
                    error=str(exc),
                )
                await self._sleep(self._error_backoff_seconds)
                continue
            await self._sleep(interval)

    async def _leaderboard_loop(self) -> None:
        interval = max(1, int(self._config.leaderboard_interval_seconds))
        while self._running:
            try:
                snapshot = await self._leaderboard_orch.tick(  # type: ignore[union-attr]
                    timeframe=self._leaderboard_timeframe
                )
                if snapshot:
                    logger.info(
                        "intelligence_scheduler_leaderboard_tick",
                        count=len(snapshot),
                        timeframe=self._leaderboard_timeframe,
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "intelligence_scheduler_leaderboard_failed",
                    error=str(exc),
                )
                await self._sleep(self._error_backoff_seconds)
                continue
            await self._sleep(interval)

    async def _snapshot_loop(self) -> None:
        interval = max(1, int(self._config.snapshot_interval_seconds))
        while self._running:
            try:
                await self._snapshot_writer.tick()  # type: ignore[union-attr]
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "intelligence_scheduler_snapshot_failed",
                    error=str(exc),
                )
                await self._sleep(self._error_backoff_seconds)
                continue
            await self._sleep(interval)

    # ── Internals ────────────────────────────────────────────────────────

    async def _fetch_active_markets(self) -> list[Any]:
        """Resolve current active markets for the whale loop.

        Falls back to an empty list if the market service is not wired or
        the call fails — the loop will simply skip the tick.
        """
        if self._market_service is None:
            return []
        try:
            return await self._market_service.get_filtered_markets()
        except Exception as exc:
            logger.warning(
                "intelligence_scheduler_market_fetch_failed",
                error=str(exc),
            )
            return []

    async def _sleep(self, seconds: float) -> None:
        """Cancel-aware sleep that exits early when ``stop()`` is called."""
        try:
            await asyncio.sleep(seconds)
        except asyncio.CancelledError:
            raise
