"""Circuit breaker: halts trading after consecutive losses or excessive drawdown."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class CircuitBreakerState:
    is_tripped: bool = False
    reason: str = ""
    tripped_at: datetime | None = None
    cooldown_until: datetime | None = None
    consecutive_losses: int = 0
    daily_drawdown_pct: float = 0.0


class CircuitBreaker:
    """Monitors trading performance and halts trading when limits are exceeded."""

    def __init__(
        self,
        max_consecutive_losses: int = 3,
        max_daily_drawdown_pct: float = 15.0,
        cooldown_minutes: int = 60,
    ) -> None:
        self._max_losses = max_consecutive_losses
        self._max_drawdown = max_daily_drawdown_pct
        self._cooldown = timedelta(minutes=cooldown_minutes)

        self._consecutive_losses = 0
        self._starting_capital: float = 0.0
        self._current_capital: float = 0.0
        self._tripped = False
        self._tripped_at: datetime | None = None
        self._trip_reason = ""

    def initialize(self, starting_capital: float) -> None:
        """Set starting capital for drawdown calculation."""
        self._starting_capital = starting_capital
        self._current_capital = starting_capital

    def record_trade_result(self, pnl: float) -> CircuitBreakerState:
        """Record a trade result. Returns current state (may trip)."""
        self._current_capital += pnl

        if pnl < 0:
            self._consecutive_losses += 1
        else:
            self._consecutive_losses = 0

        # Check consecutive losses
        if self._consecutive_losses >= self._max_losses:
            return self._trip(f"Consecutive losses: {self._consecutive_losses}")

        # Check daily drawdown
        if self._starting_capital > 0:
            drawdown = (
                (self._starting_capital - self._current_capital)
                / self._starting_capital
                * 100
            )
            if drawdown >= self._max_drawdown:
                return self._trip(f"Daily drawdown: {drawdown:.1f}%")

        return self.state

    def check(self) -> CircuitBreakerState:
        """Check if circuit breaker allows trading."""
        if not self._tripped:
            return self.state

        # Check if cooldown has elapsed
        if self._tripped_at:
            cooldown_end = self._tripped_at + self._cooldown
            if datetime.now(tz=UTC) >= cooldown_end:
                self.reset()
                return self.state

        return self.state

    def _trip(self, reason: str) -> CircuitBreakerState:
        now = datetime.now(tz=UTC)
        self._tripped = True
        self._tripped_at = now
        self._trip_reason = reason
        logger.warning("circuit_breaker_tripped", reason=reason)
        return self.state

    def reset(self) -> None:
        """Reset the circuit breaker (clear tripped state)."""
        self._tripped = False
        self._tripped_at = None
        self._trip_reason = ""
        self._consecutive_losses = 0
        logger.info("circuit_breaker_reset")

    def reset_daily(self, new_capital: float) -> None:
        """Reset for a new trading day."""
        self.reset()
        self._starting_capital = new_capital
        self._current_capital = new_capital

    @property
    def state(self) -> CircuitBreakerState:
        drawdown = 0.0
        if self._starting_capital > 0:
            drawdown = (
                (self._starting_capital - self._current_capital)
                / self._starting_capital
                * 100
            )
        return CircuitBreakerState(
            is_tripped=self._tripped,
            reason=self._trip_reason,
            tripped_at=self._tripped_at,
            cooldown_until=(self._tripped_at + self._cooldown) if self._tripped_at else None,
            consecutive_losses=self._consecutive_losses,
            daily_drawdown_pct=round(drawdown, 2),
        )
