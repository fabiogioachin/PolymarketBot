"""Risk manager: validates orders against portfolio limits.

Supports both fixed EUR values and equity-relative percentages for limits.
Example config:
    max_single_position_eur: "5%"   → 5% of current equity
    daily_loss_limit_eur: 20.0      → fixed 20 EUR
"""

from dataclasses import dataclass, field

from app.core.logging import get_logger
from app.models.signal import Signal, SignalType
from app.risk.position_sizer import PositionSizer, SizeResult

logger = get_logger(__name__)


def _parse_limit(value: float | str) -> tuple[float, bool]:
    """Parse a limit value. Returns (number, is_percentage).

    "5%" → (5.0, True)
    25.0 → (25.0, False)
    """
    if isinstance(value, str):
        s = value.strip()
        if s.endswith("%"):
            return float(s[:-1]), True
        return float(s), False
    return float(value), False


@dataclass
class RiskCheck:
    approved: bool = True
    reason: str = ""
    warnings: list[str] = field(default_factory=list)


class RiskManager:
    """Validates signals/orders against portfolio risk limits.

    Limits can be fixed EUR values or equity-relative percentages.
    Percentages are resolved at check time against current equity.
    """

    def __init__(
        self,
        capital: float = 150.0,
        max_exposure_pct: float = 50.0,
        max_single_position_eur: float | str = 25.0,
        daily_loss_limit_eur: float | str = 20.0,
        max_positions: int = 25,
    ) -> None:
        self._capital = capital
        self._max_exposure_pct = max_exposure_pct
        self._max_positions = max_positions

        # Parse limits: may be fixed EUR or % of equity
        self._max_single_raw, self._max_single_is_pct = _parse_limit(max_single_position_eur)
        self._daily_loss_raw, self._daily_loss_is_pct = _parse_limit(daily_loss_limit_eur)

        # State tracking
        self._current_positions: dict[str, float] = {}  # token_id → exposure in EUR
        self._daily_pnl: float = 0.0
        self._sizer = PositionSizer(
            fixed_fraction_pct=5.0,
            max_single_eur=self._resolve_max_single(capital),
        )

    def _resolve_max_single(self, equity: float) -> float:
        """Resolve max single position limit against equity."""
        if self._max_single_is_pct:
            return equity * self._max_single_raw / 100.0
        return self._max_single_raw

    def _resolve_daily_loss(self, equity: float) -> float:
        """Resolve daily loss limit against equity."""
        if self._daily_loss_is_pct:
            return equity * self._daily_loss_raw / 100.0
        return self._daily_loss_raw

    def check_order(
        self,
        signal: Signal,
        price: float,
        size_eur: float,
    ) -> RiskCheck:
        """Check if an order passes all risk limits.

        Percentage-based limits are resolved against current equity
        (capital + positions value).
        """
        warnings: list[str] = []
        equity = self._capital  # base equity for % calculations

        # Resolve dynamic limits
        max_single = self._resolve_max_single(equity)
        daily_loss_limit = self._resolve_daily_loss(equity)

        # 1. Signal type check
        if signal.signal_type == SignalType.HOLD:
            return RiskCheck(approved=False, reason="Signal is HOLD, no trade")

        # 2. Daily loss limit
        if self._daily_pnl <= -daily_loss_limit:
            return RiskCheck(
                approved=False,
                reason=f"Daily loss limit reached ({self._daily_pnl:.2f} / -{daily_loss_limit:.2f} EUR)",
            )

        # 3. Max single position
        if size_eur > max_single:
            return RiskCheck(
                approved=False,
                reason=f"Size {size_eur:.2f} exceeds max single position {max_single:.2f} EUR",
            )

        # 4. Max exposure (total deployed capital)
        current_exposure = sum(self._current_positions.values())
        max_exposure_eur = equity * (self._max_exposure_pct / 100.0)
        if current_exposure + size_eur > max_exposure_eur:
            return RiskCheck(
                approved=False,
                reason=(
                    f"Would exceed max exposure: "
                    f"{current_exposure + size_eur:.2f} > {max_exposure_eur:.2f} EUR"
                ),
            )

        # 5. Max positions count
        is_new_position = signal.token_id not in self._current_positions
        if is_new_position and len(self._current_positions) >= self._max_positions:
            return RiskCheck(
                approved=False,
                reason=f"Max positions reached ({self._max_positions})",
            )

        # Warnings
        remaining_loss_budget = daily_loss_limit + self._daily_pnl
        if remaining_loss_budget < size_eur:
            warnings.append(
                f"Size ({size_eur:.2f}) exceeds remaining daily loss budget "
                f"({remaining_loss_budget:.2f})"
            )

        if current_exposure + size_eur > max_exposure_eur * 0.8:
            warnings.append(
                f"Approaching max exposure "
                f"({(current_exposure + size_eur) / max_exposure_eur * 100:.0f}%)"
            )

        return RiskCheck(approved=True, warnings=warnings)

    def size_position(self, signal: Signal, capital: float, price: float) -> SizeResult:
        """Calculate position size using signal confidence.

        Updates the internal sizer's max_single_eur based on current equity.
        """
        # Resolve % limits against current capital
        self._sizer._max_single = self._resolve_max_single(capital)

        result = self._sizer.from_signal(capital, price, signal.confidence)
        logger.debug(
            "position_sized",
            token_id=signal.token_id[:20],
            confidence=signal.confidence,
            size_eur=result.size_eur,
            method=result.method,
            capped=result.capped,
        )
        return result

    def record_fill(self, token_id: str, size_eur: float) -> None:
        """Record a filled order for exposure tracking."""
        current = self._current_positions.get(token_id, 0.0)
        self._current_positions[token_id] = current + size_eur
        logger.info(
            "fill_recorded",
            token_id=token_id[:20],
            size_eur=size_eur,
            total_exposure=self.current_exposure,
        )

    def record_close(self, token_id: str, pnl: float) -> None:
        """Record a closed position and its P&L."""
        self._current_positions.pop(token_id, None)
        self._daily_pnl += pnl
        logger.info(
            "position_closed",
            token_id=token_id[:20],
            pnl=pnl,
            daily_pnl=self._daily_pnl,
        )

    def reset_daily(self) -> None:
        """Reset daily P&L tracking (called at start of new trading day)."""
        self._daily_pnl = 0.0
        logger.info("daily_reset")

    @property
    def current_exposure(self) -> float:
        return sum(self._current_positions.values())

    @property
    def daily_pnl(self) -> float:
        return self._daily_pnl

    @property
    def position_count(self) -> int:
        return len(self._current_positions)
