"""Bot service: high-level start/stop/status for the trading bot."""

import asyncio
import contextlib
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta

from app.core.logging import get_logger
from app.execution.engine import ExecutionEngine
from app.risk.circuit_breaker import CircuitBreaker
from app.risk.manager import RiskManager

logger = get_logger(__name__)

# UTC midnight — daily reset time
_DAILY_RESET_TIME = time(0, 0, tzinfo=UTC)


@dataclass
class BotStatus:
    running: bool = False
    mode: str = "dry_run"
    tick_count: int = 0
    started_at: datetime | None = None
    positions: int = 0
    daily_pnl: float = 0.0
    circuit_breaker_tripped: bool = False


class BotService:
    """Manages the trading bot lifecycle."""

    def __init__(
        self,
        engine: ExecutionEngine,
        risk_manager: RiskManager,
        circuit_breaker: CircuitBreaker,
    ) -> None:
        self._engine = engine
        self._risk = risk_manager
        self._cb = circuit_breaker
        self._task: asyncio.Task[None] | None = None
        self._reset_task: asyncio.Task[None] | None = None
        self._started_at: datetime | None = None
        self._mode = "dry_run"

    async def start(self, interval_seconds: int = 60) -> None:
        """Start the trading bot loop and daily reset scheduler."""
        if self._engine.is_running:
            return
        self._started_at = datetime.now(tz=UTC)
        self._task = asyncio.create_task(self._engine.run(interval_seconds))
        self._reset_task = asyncio.create_task(self._daily_reset_loop())
        logger.info("bot_started", mode=self._mode, interval=interval_seconds)

    async def stop(self) -> None:
        """Stop the trading bot loop and daily reset scheduler."""
        await self._engine.stop()
        for task in (self._task, self._reset_task):
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        self._task = None
        self._reset_task = None
        self._started_at = None
        logger.info("bot_stopped")

    def status(self) -> BotStatus:
        """Get current bot status."""
        cb_state = self._cb.check()
        return BotStatus(
            running=self._engine.is_running,
            mode=self._mode,
            tick_count=self._engine.tick_count,
            started_at=self._started_at,
            positions=self._risk.position_count,
            daily_pnl=self._risk.daily_pnl,
            circuit_breaker_tripped=cb_state.is_tripped,
        )

    def set_mode(self, mode: str) -> None:
        """Set execution mode. Validates against allowed modes."""
        if mode not in ("dry_run", "shadow", "live"):
            raise ValueError(f"Invalid mode: {mode}")
        self._mode = mode
        logger.info("bot_mode_changed", mode=mode)

    async def _daily_reset_loop(self) -> None:
        """Sleep until next UTC midnight, then reset daily counters. Repeats."""
        while True:
            now = datetime.now(tz=UTC)
            tomorrow = (now + timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            seconds_until = (tomorrow - now).total_seconds()
            await asyncio.sleep(seconds_until)

            # Reset risk manager daily P&L and circuit breaker
            self._risk.reset_daily()
            balance = await self._engine._executor.get_balance()
            self._cb.reset_daily(new_capital=balance.total)
            logger.info(
                "daily_reset_completed",
                new_capital=balance.total,
            )
