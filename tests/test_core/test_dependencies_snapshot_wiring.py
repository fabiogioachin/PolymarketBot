"""Tests for SnapshotWriter wiring inside ``start_intelligence_scheduler``.

Phase 13 W5 — Slice 1 (N1: snapshot wiring monitoring-only).

The orchestrator under test is ``app.core.dependencies.start_intelligence_scheduler``.
In monitoring-only mode (``bot.auto_start=False``) the FastAPI lifespan does NOT
invoke ``get_execution_engine()``, so the SnapshotWriter must be wired with its
intelligence orchestrator dependencies *inside* ``start_intelligence_scheduler``
itself. These tests assert the public contract:

1. With ``intelligence.whale.enabled``, ``intelligence.popular_markets.enabled``
   and ``intelligence.leaderboard.enabled`` all True (and the DSS writer flag
   on), the snapshot writer's ``_whale_orch``/``_popular_orch``/
   ``_leaderboard_orch`` private attributes are bound to the same singletons
   exposed by ``get_whale_orchestrator()`` / etc. ``_engine`` and
   ``_trade_store`` MAY be None (Slice 2's scope; the engine is lifespan-managed
   only when ``bot.auto_start=True``).

2. With those three intel flags False but the DSS writer flag still True, the
   orchestrator setters remain None — no spurious wiring of disabled
   orchestrators.

3. ``start_intelligence_scheduler`` is import-safe (no top-level side effects).

Project conventions honoured:
    - ``pytest-asyncio`` with ``asyncio_mode=auto`` → ``async def test_...``.
    - Real, non-mocked singletons. The fixture resets module-level globals so
      each test starts from a clean DI graph.
    - ``monkeypatch`` flips ``app_config`` flags without writing to disk.
    - Each test stops the scheduler before exiting so spawned asyncio tasks do
      not leak across tests.
"""

from __future__ import annotations

from typing import Any

import pytest

import app.core.dependencies as deps
from app.core.yaml_config import app_config


# ── Helpers ──────────────────────────────────────────────────────────────────

# Names of the module-level singletons in app.core.dependencies that the
# scheduler-wiring path touches. Reset between tests for full isolation.
#
# Slice 2 (N2) additions:
#   - ``_trade_store``: the new module-global singleton holder introduced by
#     ``get_trade_store()``. Must reset to None so each test observes a fresh
#     construction path through the dual-order singleton-identity invariant.
#   - ``_execution_engine``: the engine caches ``_store``; if a previous test
#     left an engine populated, a later test asserting identity against
#     ``await get_trade_store()`` would see a stale store. Reset is mandatory
#     for the dual-order parametrization to be meaningful.
_SINGLETON_NAMES: tuple[str, ...] = (
    "_intelligence_scheduler",
    "_snapshot_writer",
    "_whale_orchestrator",
    "_popular_markets_orchestrator",
    "_leaderboard_orchestrator",
    "_market_service",
    "_subgraph_client",
    "_trade_store",
    "_execution_engine",
)


async def _reset_singletons() -> None:
    """Stop any running scheduler and clear singleton holders."""
    # If a scheduler is already alive from a previous test, stop its loops
    # first so we don't leak asyncio tasks into the next test.
    existing = getattr(deps, "_intelligence_scheduler", None)
    if existing is not None:
        try:
            await deps.stop_intelligence_scheduler()
        except Exception:  # pragma: no cover — best-effort teardown
            pass

    for name in _SINGLETON_NAMES:
        setattr(deps, name, None)


@pytest.fixture
async def clean_singletons() -> Any:
    """Reset DI singletons before AND after each test (order-independent)."""
    await _reset_singletons()
    try:
        yield
    finally:
        await _reset_singletons()


# ── Test 3 (smoke import) ────────────────────────────────────────────────────


def test_smoke_import_start_intelligence_scheduler() -> None:
    """Guard against import-time regression on the public entrypoint.

    A fresh ``import`` of ``start_intelligence_scheduler`` from
    ``app.core.dependencies`` must succeed and resolve to a callable. This
    catches circular-import bugs or new top-level dependencies that fail in CI
    before any test ever runs.
    """
    from app.core.dependencies import start_intelligence_scheduler

    assert callable(start_intelligence_scheduler)


# ── Test 1 (positive wiring) ─────────────────────────────────────────────────


async def test_snapshot_wiring_in_monitoring_only_mode(
    monkeypatch: pytest.MonkeyPatch,
    clean_singletons: Any,
) -> None:
    """Monitoring-only + intel flags ON → snapshot writer orch deps wired.

    Asserts that after ``await start_intelligence_scheduler()``:

        get_snapshot_writer()._whale_orch        is get_whale_orchestrator()
        get_snapshot_writer()._popular_orch      is get_popular_markets_orchestrator()
        get_snapshot_writer()._leaderboard_orch  is get_leaderboard_orchestrator()

    The engine and trade_store fields MAY be None — they are populated only
    when ``get_execution_engine()`` runs (full-bot mode, Slice 2 for the
    independent trade store).
    """
    # Monitoring-only mode (no auto-start of the trading bot).
    monkeypatch.setattr(app_config.bot, "auto_start", False)

    # All four flags ON so the wiring branches inside
    # start_intelligence_scheduler() actually fire.
    monkeypatch.setattr(app_config.intelligence.whale, "enabled", True)
    monkeypatch.setattr(app_config.intelligence.popular_markets, "enabled", True)
    monkeypatch.setattr(app_config.intelligence.leaderboard, "enabled", True)
    monkeypatch.setattr(app_config.dss.snapshot_writer, "enabled", True)

    # Scheduler enabled — otherwise start() returns early without wiring loops.
    monkeypatch.setattr(app_config.intelligence.scheduler, "enabled", True)

    scheduler = await deps.start_intelligence_scheduler()
    try:
        writer = deps.get_snapshot_writer()

        # Snapshot writer must hold the SAME singleton instances exposed by
        # the public accessors — identity check (``is``), not equality.
        assert writer._whale_orch is deps.get_whale_orchestrator(), (
            "snapshot writer's whale orchestrator must be the singleton "
            "returned by get_whale_orchestrator()"
        )
        assert writer._popular_orch is deps.get_popular_markets_orchestrator(), (
            "snapshot writer's popular markets orchestrator must be the "
            "singleton returned by get_popular_markets_orchestrator()"
        )
        assert writer._leaderboard_orch is deps.get_leaderboard_orchestrator(), (
            "snapshot writer's leaderboard orchestrator must be the singleton "
            "returned by get_leaderboard_orchestrator()"
        )

        # Sanity: scheduler returned by the bootstrap is the singleton.
        assert scheduler is deps.get_intelligence_scheduler()
    finally:
        await deps.stop_intelligence_scheduler()


# ── Test 2 (negative — no spurious wiring) ───────────────────────────────────


async def test_snapshot_wiring_skipped_when_intel_flags_off(
    monkeypatch: pytest.MonkeyPatch,
    clean_singletons: Any,
) -> None:
    """Intel flags OFF + DSS writer ON → orchestrator deps stay None.

    Even though the DSS writer is enabled (and therefore the writer singleton
    is registered with the scheduler), none of the three orchestrator setters
    must fire when their respective intelligence flags are False. Spurious
    wiring of disabled orchestrators would defeat the gating.
    """
    monkeypatch.setattr(app_config.bot, "auto_start", False)

    # Disable all three intelligence sources …
    monkeypatch.setattr(app_config.intelligence.whale, "enabled", False)
    monkeypatch.setattr(app_config.intelligence.popular_markets, "enabled", False)
    monkeypatch.setattr(app_config.intelligence.leaderboard, "enabled", False)

    # … but keep the DSS snapshot writer enabled so its block executes.
    monkeypatch.setattr(app_config.dss.snapshot_writer, "enabled", True)
    monkeypatch.setattr(app_config.intelligence.scheduler, "enabled", True)

    await deps.start_intelligence_scheduler()
    try:
        writer = deps.get_snapshot_writer()

        assert writer._whale_orch is None, (
            "whale orch must NOT be wired when intelligence.whale.enabled=False"
        )
        assert writer._popular_orch is None, (
            "popular orch must NOT be wired when "
            "intelligence.popular_markets.enabled=False"
        )
        assert writer._leaderboard_orch is None, (
            "leaderboard orch must NOT be wired when "
            "intelligence.leaderboard.enabled=False"
        )
    finally:
        await deps.stop_intelligence_scheduler()


# ── Slice 2 / N2: dual-order singleton-identity invariant ────────────────────


@pytest.mark.parametrize("init_order", ["scheduler_first", "engine_first"])
async def test_trade_store_singleton_identity_dual_order_init(
    monkeypatch: pytest.MonkeyPatch,
    clean_singletons: Any,
    init_order: str,
) -> None:
    """TradeStore singleton identity must hold under both bootstrap orders.

    Phase 13 W5 Slice 2 (N2) demo gate (anchor "Demo gate semantics" point 2):
    no matter whether ``start_intelligence_scheduler()`` runs before or after
    ``get_execution_engine()``, the SAME ``TradeStore`` instance must be
    visible from:

        get_trade_store()
        engine._store                 (ExecutionEngine ctor stores trade_store as _store)
        whale_orch._trade_store       (set via WhaleOrchestrator.set_trade_store)
        snapshot_writer._trade_store  (set via SnapshotWriter.set_trade_store)

    Identity, not equality — module globals must hold the EXACT same object,
    otherwise dual-write races (engine appends to one store, scheduler reads
    from another) would silently corrupt DSS snapshots.
    """
    # Monitoring-only is irrelevant for engine_first (we explicitly build it),
    # but keep auto_start=False so no background lifespan task fires.
    monkeypatch.setattr(app_config.bot, "auto_start", False)

    # All flags ON so every wiring branch fires in both orderings.
    monkeypatch.setattr(app_config.intelligence.whale, "enabled", True)
    monkeypatch.setattr(app_config.intelligence.popular_markets, "enabled", True)
    monkeypatch.setattr(app_config.intelligence.leaderboard, "enabled", True)
    monkeypatch.setattr(app_config.dss.snapshot_writer, "enabled", True)
    monkeypatch.setattr(app_config.intelligence.scheduler, "enabled", True)

    try:
        if init_order == "scheduler_first":
            # Scheduler boots → wires whale_orch + snapshot_writer with the
            # store from get_trade_store(). Engine then runs and must adopt
            # the SAME store rather than constructing a fresh one.
            await deps.start_intelligence_scheduler()
            engine = await deps.get_execution_engine()
        else:  # engine_first
            # Engine boots first → ``get_execution_engine`` must call
            # ``get_trade_store()`` (instead of constructing TradeStore
            # inline). Scheduler then runs and must reuse the same singleton
            # for snapshot_writer wiring.
            engine = await deps.get_execution_engine()
            await deps.start_intelligence_scheduler()

        store_singleton = await deps.get_trade_store()
        whale_orch = deps.get_whale_orchestrator()
        snapshot_writer = deps.get_snapshot_writer()

        # ExecutionEngine.__init__ stores the trade_store kwarg as
        # ``self._store`` (see app/execution/engine.py line 90). Verified
        # against the constructor in the Slice 1 implementer's note.
        assert store_singleton is engine._store, (
            f"[{init_order}] engine._store must be the get_trade_store() singleton; "
            f"got id(store_singleton)={id(store_singleton)} "
            f"vs id(engine._store)={id(engine._store)}"
        )
        assert store_singleton is whale_orch._trade_store, (
            f"[{init_order}] whale_orch._trade_store must be the singleton"
        )
        assert store_singleton is snapshot_writer._trade_store, (
            f"[{init_order}] snapshot_writer._trade_store must be the singleton"
        )
    finally:
        # Mirror Slice 1 cleanup: stop scheduler so its loops do not leak
        # into subsequent tests. The fixture also resets module globals on
        # teardown — this stop() is the symmetric counterpart to start().
        await deps.stop_intelligence_scheduler()
