"""FastAPI dependency injection — central service wiring."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.logging import get_logger
from app.core.yaml_config import app_config

if TYPE_CHECKING:
    from app.clients.polymarket_subgraph import PolymarketSubgraphClient
    from app.execution.engine import ExecutionEngine
    from app.execution.trade_store import TradeStore
    from app.knowledge.risk_kb import RiskKnowledgeBase
    from app.risk.circuit_breaker import CircuitBreaker
    from app.risk.manager import RiskManager
    from app.services.bot_service import BotService
    from app.services.intelligence_orchestrator import IntelligenceOrchestrator
    from app.services.intelligence_scheduler import IntelligenceScheduler
    from app.services.leaderboard_orchestrator import LeaderboardOrchestrator
    from app.services.manifold_service import ManifoldService
    from app.services.market_service import MarketService
    from app.services.popular_markets_orchestrator import (
        PopularMarketsOrchestrator,
    )
    from app.services.snapshot_writer import SnapshotWriter
    from app.services.whale_orchestrator import WhaleOrchestrator
    from app.strategies.registry import StrategyRegistry
    from app.valuation.engine import ValueAssessmentEngine

logger = get_logger(__name__)

# ── Singleton holders ────────────────────────────────────────────────

_market_service: MarketService | None = None
_risk_kb: RiskKnowledgeBase | None = None
_risk_manager: RiskManager | None = None
_circuit_breaker: CircuitBreaker | None = None
_strategy_registry: StrategyRegistry | None = None
_value_engine: ValueAssessmentEngine | None = None
_trade_store: TradeStore | None = None
_execution_engine: ExecutionEngine | None = None
_bot_service: BotService | None = None
_manifold_service: ManifoldService | None = None
_intelligence_orchestrator: IntelligenceOrchestrator | None = None
_whale_orchestrator: WhaleOrchestrator | None = None
_popular_markets_orchestrator: PopularMarketsOrchestrator | None = None
_leaderboard_orchestrator: LeaderboardOrchestrator | None = None
_subgraph_client: PolymarketSubgraphClient | None = None
_snapshot_writer: SnapshotWriter | None = None
_intelligence_scheduler: IntelligenceScheduler | None = None


# ── Lazy accessors ───────────────────────────────────────────────────


def get_market_service() -> MarketService:
    global _market_service  # noqa: PLW0603
    if _market_service is None:
        from app.services.market_service import MarketService

        _market_service = MarketService()
    return _market_service


async def get_manifold_service() -> ManifoldService | None:
    """Get ManifoldService singleton. Returns None if Manifold is disabled."""
    global _manifold_service  # noqa: PLW0603
    if not app_config.intelligence.manifold.enabled:
        return None
    if _manifold_service is None:
        from app.clients.manifold_client import ManifoldClient
        from app.services.manifold_service import ManifoldService

        client = ManifoldClient(rate_limit=app_config.intelligence.manifold.rate_limit)
        _manifold_service = ManifoldService(client)
    return _manifold_service


def get_intelligence_orchestrator() -> IntelligenceOrchestrator:
    """Get IntelligenceOrchestrator singleton (GDELT + RSS pipeline)."""
    global _intelligence_orchestrator  # noqa: PLW0603
    if _intelligence_orchestrator is None:
        from app.services.intelligence_orchestrator import IntelligenceOrchestrator

        _intelligence_orchestrator = IntelligenceOrchestrator()
        logger.info("intelligence_orchestrator_initialized")
    return _intelligence_orchestrator


def get_subgraph_client() -> PolymarketSubgraphClient | None:
    """Get the Polymarket subgraph client singleton, or None if disabled."""
    global _subgraph_client  # noqa: PLW0603
    sub_cfg = app_config.intelligence.subgraph
    if not sub_cfg.enabled:
        return None
    if _subgraph_client is None:
        import os

        from app.clients.polymarket_subgraph import PolymarketSubgraphClient

        api_key = os.getenv(sub_cfg.api_key_env) or None
        ttl_seconds = max(0.0, float(sub_cfg.enrichment_ttl_hours) * 3600.0)
        _subgraph_client = PolymarketSubgraphClient(
            endpoint=sub_cfg.endpoint,
            api_key=api_key,
            rate_limit_per_minute=sub_cfg.rate_limit_per_minute,
            cache_ttl_seconds=ttl_seconds,
        )
        logger.info(
            "subgraph_client_initialized",
            endpoint=sub_cfg.endpoint,
            has_api_key=bool(api_key),
        )
    return _subgraph_client


def get_whale_orchestrator() -> WhaleOrchestrator:
    """Get WhaleOrchestrator singleton (Polymarket /trades poller)."""
    global _whale_orchestrator  # noqa: PLW0603
    if _whale_orchestrator is None:
        from app.services.whale_orchestrator import WhaleOrchestrator

        _whale_orchestrator = WhaleOrchestrator()
        subgraph = get_subgraph_client()
        if subgraph is not None:
            _whale_orchestrator.set_subgraph_client(subgraph)
        logger.info("whale_orchestrator_initialized")
    return _whale_orchestrator


def get_popular_markets_orchestrator() -> PopularMarketsOrchestrator:
    """Get PopularMarketsOrchestrator singleton (top-N by volume24h)."""
    global _popular_markets_orchestrator  # noqa: PLW0603
    if _popular_markets_orchestrator is None:
        from app.services.popular_markets_orchestrator import (
            PopularMarketsOrchestrator,
        )

        _popular_markets_orchestrator = PopularMarketsOrchestrator()
        logger.info("popular_markets_orchestrator_initialized")
    return _popular_markets_orchestrator


def get_leaderboard_orchestrator() -> LeaderboardOrchestrator:
    """Get LeaderboardOrchestrator singleton (top traders by PnL)."""
    global _leaderboard_orchestrator  # noqa: PLW0603
    if _leaderboard_orchestrator is None:
        from app.services.leaderboard_orchestrator import (
            LeaderboardOrchestrator,
        )

        _leaderboard_orchestrator = LeaderboardOrchestrator()
        logger.info("leaderboard_orchestrator_initialized")
    return _leaderboard_orchestrator


def get_snapshot_writer() -> SnapshotWriter:
    """Get SnapshotWriter singleton (DSS intelligence_snapshot.json writer).

    Wires all available dependencies via the late-binding setter pattern.
    Returns the singleton regardless of whether dependencies are ready — each
    setter call is idempotent and safe to call before or after construction of
    the other services.
    """
    global _snapshot_writer  # noqa: PLW0603
    if _snapshot_writer is None:
        from pathlib import Path

        from app.services.snapshot_writer import SnapshotWriter

        _snapshot_writer = SnapshotWriter(
            output_path=Path("static/dss/intelligence_snapshot.json")
        )
        logger.info("snapshot_writer_initialized")
    return _snapshot_writer


async def get_risk_kb() -> RiskKnowledgeBase:
    global _risk_kb  # noqa: PLW0603
    if _risk_kb is None:
        from app.knowledge.risk_kb import RiskKnowledgeBase

        _risk_kb = RiskKnowledgeBase()
        await _risk_kb.init()
    return _risk_kb


def get_risk_manager() -> RiskManager:
    global _risk_manager  # noqa: PLW0603
    if _risk_manager is None:
        from app.risk.manager import RiskManager

        cfg = app_config.risk
        _risk_manager = RiskManager(
            capital=150.0,
            max_exposure_pct=cfg.max_exposure_pct,
            max_single_position_eur=cfg.max_single_position_eur,
            daily_loss_limit_eur=cfg.daily_loss_limit_eur,
            max_positions=cfg.max_positions,
        )
    return _risk_manager


def get_circuit_breaker() -> CircuitBreaker:
    global _circuit_breaker  # noqa: PLW0603
    if _circuit_breaker is None:
        from app.risk.circuit_breaker import CircuitBreaker

        cb_cfg = app_config.risk.circuit_breaker
        _circuit_breaker = CircuitBreaker(
            max_consecutive_losses=cb_cfg.consecutive_losses,
            max_daily_drawdown_pct=cb_cfg.daily_drawdown_pct,
            cooldown_minutes=cb_cfg.cooldown_minutes,
        )
        _circuit_breaker.initialize(starting_capital=150.0)
    return _circuit_breaker


def get_strategy_registry() -> StrategyRegistry:
    global _strategy_registry  # noqa: PLW0603
    if _strategy_registry is None:
        from app.strategies.arbitrage import ArbitrageStrategy
        from app.strategies.event_driven import EventDrivenStrategy
        from app.strategies.knowledge_driven import KnowledgeDrivenStrategy
        from app.strategies.registry import StrategyRegistry
        from app.strategies.resolution import ResolutionStrategy
        from app.strategies.rule_edge import RuleEdgeStrategy
        from app.strategies.sentiment import SentimentStrategy
        from app.strategies.value_edge import ValueEdgeStrategy

        _strategy_registry = StrategyRegistry()
        for strat in (
            ValueEdgeStrategy(
                min_edge=app_config.valuation.thresholds.min_edge,
                min_confidence=app_config.valuation.thresholds.min_confidence,
            ),
            ArbitrageStrategy(),
            RuleEdgeStrategy(),
            EventDrivenStrategy(),
            ResolutionStrategy(),
            SentimentStrategy(),
            KnowledgeDrivenStrategy(),
        ):
            _strategy_registry.register(strat)
        logger.info(
            "strategies_loaded",
            registered=[s.name for s in _strategy_registry.get_all()],
            enabled=app_config.strategies.enabled,
        )
    return _strategy_registry


async def get_value_engine() -> ValueAssessmentEngine:
    global _value_engine  # noqa: PLW0603
    if _value_engine is None:
        from app.valuation.db import ResolutionDB
        from app.valuation.engine import ValueAssessmentEngine

        db = ResolutionDB()
        await db.init()
        _value_engine = ValueAssessmentEngine(db)
    return _value_engine


async def get_trade_store() -> TradeStore:
    """Get the TradeStore singleton (Slice 2 / N2 extraction).

    Constructed and initialised on first call; returned as-is on subsequent
    calls. Accessible without going through ``get_execution_engine`` so the
    intelligence scheduler can wire orchestrators in monitoring-only mode.
    """
    global _trade_store  # noqa: PLW0603
    if _trade_store is None:
        from app.execution.trade_store import TradeStore

        _trade_store = TradeStore()
        await _trade_store.init()
    return _trade_store


async def get_execution_engine() -> ExecutionEngine:
    global _execution_engine  # noqa: PLW0603
    if _execution_engine is None:
        from app.clients.polymarket_clob import PolymarketClobClient
        from app.execution.dry_run import DryRunExecutor
        from app.execution.engine import ExecutionEngine

        clob = PolymarketClobClient()
        executor = DryRunExecutor(clob)
        value_engine = await get_value_engine()
        manifold_service = await get_manifold_service()
        store = await get_trade_store()

        # Intelligence orchestrator: only if GDELT or RSS is enabled
        intel_orch = None
        if app_config.intelligence.gdelt.enabled or app_config.intelligence.rss.enabled:
            intel_orch = get_intelligence_orchestrator()

        # Wire trade_store into intelligence orchestrator for anomaly persistence
        if intel_orch is not None:
            await intel_orch.set_trade_store(store)

        # Phase 13 S2: whale + popular markets orchestrators
        whale_orch = None
        if app_config.intelligence.whale.enabled:
            whale_orch = get_whale_orchestrator()
            await whale_orch.set_trade_store(store)

        pop_orch = None
        if app_config.intelligence.popular_markets.enabled:
            pop_orch = get_popular_markets_orchestrator()
            await pop_orch.set_trade_store(store)

        lb_orch = None
        if app_config.intelligence.leaderboard.enabled:
            lb_orch = get_leaderboard_orchestrator()
            await lb_orch.set_trade_store(store)

        # Knowledge service (Obsidian KG patterns): only if Obsidian is enabled
        knowledge_service = None
        if app_config.intelligence.obsidian.enabled:
            from app.services.knowledge_service import KnowledgeService

            knowledge_service = KnowledgeService()

        risk_kb = await get_risk_kb()

        _execution_engine = ExecutionEngine(
            executor=executor,
            risk_manager=get_risk_manager(),
            circuit_breaker=get_circuit_breaker(),
            strategy_registry=get_strategy_registry(),
            value_engine=value_engine,
            market_service=get_market_service(),
            trade_store=store,
            manifold_service=manifold_service,
            intelligence_orchestrator=intel_orch,
            knowledge_service=knowledge_service,
            risk_kb=risk_kb,
            whale_orchestrator=whale_orch,
            popular_markets_orchestrator=pop_orch,
            leaderboard_orchestrator=lb_orch,
        )
        await _execution_engine.restore_from_store()

        # Phase 13 S4a: wire SnapshotWriter with all available dependencies.
        # NOTE: snapshot_writer.tick() is NOT yet called from engine.tick() —
        # the orchestrator will add that call after S4b is merged.
        snapshot_writer = get_snapshot_writer()
        snapshot_writer.set_engine(_execution_engine)
        snapshot_writer.set_trade_store(store)
        if whale_orch is not None:
            snapshot_writer.set_whale_orchestrator(whale_orch)
        if pop_orch is not None:
            snapshot_writer.set_popular_markets_orchestrator(pop_orch)
        if lb_orch is not None:
            snapshot_writer.set_leaderboard_orchestrator(lb_orch)

    return _execution_engine


def get_intelligence_scheduler() -> IntelligenceScheduler:
    """Get the IntelligenceScheduler singleton.

    Phase 13 Fix 4 (Team A): the scheduler decouples intelligence ingest
    (whale / popular / leaderboard / snapshot) from ``ExecutionEngine.tick``.
    Construction is side-effect-free; loops only spawn when
    :func:`start_intelligence_scheduler` is awaited.

    Wiring of orchestrators uses the late-binding ``set_*`` setter pattern.
    The singleton is returned even if the orchestrators have not yet been
    constructed — set them after the first call to this getter.
    """
    global _intelligence_scheduler  # noqa: PLW0603
    if _intelligence_scheduler is None:
        from app.services.intelligence_scheduler import IntelligenceScheduler

        _intelligence_scheduler = IntelligenceScheduler(
            config=app_config.intelligence.scheduler
        )
        logger.info("intelligence_scheduler_initialized")
    return _intelligence_scheduler


async def start_intelligence_scheduler() -> IntelligenceScheduler:
    """Bootstrap intelligence orchestrators + start the scheduler loops.

    Phase 13 Fix 4 (Team A): MUST be invoked from the FastAPI lifespan so
    the scheduler runs even when the trading bot is stopped (monitoring-only
    mode). This wires the same orchestrator singletons that the execution
    engine uses, so the in-memory state (whale store, popular cache,
    leaderboard cache) is shared between the scheduler and the engine's
    ``_inject_whale_pressure_signals`` consumer.

    Idempotent: calling twice is a no-op (the scheduler's ``start`` is
    itself idempotent).
    """
    scheduler = get_intelligence_scheduler()

    # Wire market service (whale loop needs the active universe)
    scheduler.set_market_service(get_market_service())

    # Slice 2 / N2: TradeStore singleton is now independent of the engine —
    # build/return it eagerly so orchestrators always wire the same instance.
    store = await get_trade_store()

    # Wire orchestrators conditionally — same gating as get_execution_engine
    if app_config.intelligence.whale.enabled:
        whale_orch = get_whale_orchestrator()
        await whale_orch.set_trade_store(store)
        scheduler.set_whale_orchestrator(whale_orch)

    if app_config.intelligence.popular_markets.enabled:
        pop_orch = get_popular_markets_orchestrator()
        await pop_orch.set_trade_store(store)
        scheduler.set_popular_markets_orchestrator(pop_orch)

    if app_config.intelligence.leaderboard.enabled:
        lb_orch = get_leaderboard_orchestrator()
        await lb_orch.set_trade_store(store)
        scheduler.set_leaderboard_orchestrator(lb_orch)

    if app_config.dss.snapshot_writer.enabled:
        snapshot_writer = get_snapshot_writer()
        scheduler.set_snapshot_writer(snapshot_writer)

        # Phase 13 W5 Slice 1: wire SnapshotWriter runtime deps for
        # monitoring-only mode (bot.auto_start=False), where
        # get_execution_engine() is never invoked from lifespan.
        # Setters are idempotent (late-binding) so re-invocation in
        # full-bot mode is safe (no double-wiring bug).
        # Engine: only propagate if already built — do NOT force-construct.
        if _execution_engine is not None:
            snapshot_writer.set_engine(_execution_engine)
        # Slice 2 / N2: TradeStore is now an independent DI singleton, so we
        # always have a real store to wire (no engine/None fallback).
        snapshot_writer.set_trade_store(store)
        if app_config.intelligence.whale.enabled:
            snapshot_writer.set_whale_orchestrator(get_whale_orchestrator())
        if app_config.intelligence.popular_markets.enabled:
            snapshot_writer.set_popular_markets_orchestrator(
                get_popular_markets_orchestrator()
            )
        if app_config.intelligence.leaderboard.enabled:
            snapshot_writer.set_leaderboard_orchestrator(
                get_leaderboard_orchestrator()
            )

    await scheduler.start()
    return scheduler


async def stop_intelligence_scheduler() -> None:
    """Stop the scheduler loops if running. Safe to call from the lifespan."""
    global _intelligence_scheduler  # noqa: PLW0603
    if _intelligence_scheduler is None:
        return
    await _intelligence_scheduler.stop()


async def get_bot_service() -> BotService:
    global _bot_service  # noqa: PLW0603
    if _bot_service is None:
        from app.services.bot_service import BotService

        engine = await get_execution_engine()
        _bot_service = BotService(
            engine=engine,
            risk_manager=get_risk_manager(),
            circuit_breaker=get_circuit_breaker(),
        )
    return _bot_service
