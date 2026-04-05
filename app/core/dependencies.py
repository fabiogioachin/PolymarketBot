"""FastAPI dependency injection — central service wiring."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.logging import get_logger
from app.core.yaml_config import app_config

if TYPE_CHECKING:
    from app.execution.engine import ExecutionEngine
    from app.knowledge.risk_kb import RiskKnowledgeBase
    from app.risk.circuit_breaker import CircuitBreaker
    from app.risk.manager import RiskManager
    from app.services.bot_service import BotService
    from app.services.market_service import MarketService
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
_execution_engine: ExecutionEngine | None = None
_bot_service: BotService | None = None


# ── Lazy accessors ───────────────────────────────────────────────────


def get_market_service() -> MarketService:
    global _market_service  # noqa: PLW0603
    if _market_service is None:
        from app.services.market_service import MarketService

        _market_service = MarketService()
    return _market_service


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


async def get_execution_engine() -> ExecutionEngine:
    global _execution_engine  # noqa: PLW0603
    if _execution_engine is None:
        from app.clients.polymarket_clob import PolymarketClobClient
        from app.execution.dry_run import DryRunExecutor
        from app.execution.engine import ExecutionEngine
        from app.execution.trade_store import TradeStore

        clob = PolymarketClobClient()
        executor = DryRunExecutor(clob)
        value_engine = await get_value_engine()
        store = TradeStore()
        await store.init()
        _execution_engine = ExecutionEngine(
            executor=executor,
            risk_manager=get_risk_manager(),
            circuit_breaker=get_circuit_breaker(),
            strategy_registry=get_strategy_registry(),
            value_engine=value_engine,
            market_service=get_market_service(),
            trade_store=store,
        )
        await _execution_engine.restore_from_store()
    return _execution_engine


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
