"""Risk manager: validates orders against portfolio limits.

Supports both fixed EUR values and equity-relative percentages for limits.
Example config:
    max_single_position_eur: "5%"   → 5% of current equity
    daily_loss_limit_eur: 20.0      → fixed 20 EUR

Phase 10: time-horizon budget pools + near-resolution exposure discount.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.logging import get_logger
from app.models.market import TimeHorizon
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

    Phase 10: tracks exposure per time-horizon pool and applies
    near-resolution discount to positions about to free up capital.
    """

    def __init__(
        self,
        capital: float = 150.0,
        max_exposure_pct: float = 50.0,
        max_single_position_eur: float | str = 25.0,
        daily_loss_limit_eur: float | str = 20.0,
        max_positions: int = 25,
        horizon_allocation: dict[str, float] | None = None,
    ) -> None:
        self._capital = capital
        self._max_exposure_pct = max_exposure_pct
        self._max_positions = max_positions

        # Horizon budget pools (% of max_exposure per horizon)
        alloc = horizon_allocation or {}
        self._horizon_pct: dict[TimeHorizon, float] = {
            TimeHorizon.SHORT: alloc.get("short_pct", 65.0),
            TimeHorizon.MEDIUM: alloc.get("medium_pct", 25.0),
            TimeHorizon.LONG: alloc.get("long_pct", 8.0),
            TimeHorizon.SUPER_LONG: alloc.get("super_long_pct", 2.0),
        }

        # Parse limits: may be fixed EUR or % of equity
        self._max_single_raw, self._max_single_is_pct = _parse_limit(max_single_position_eur)
        self._daily_loss_raw, self._daily_loss_is_pct = _parse_limit(daily_loss_limit_eur)

        # State tracking
        self._current_positions: dict[str, float] = {}  # token_id → exposure in EUR
        self._position_horizons: dict[str, TimeHorizon] = {}  # token_id → horizon
        self._position_near_resolution: dict[str, bool] = {}  # token_id → near-resolution flag
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
        time_horizon: TimeHorizon | None = None,
    ) -> RiskCheck:
        """Check if an order passes all risk limits.

        Percentage-based limits are resolved against current equity
        (capital + positions value).

        Phase 10: also checks per-horizon budget pool limits.
        Near-resolution positions (< 24h, prob > 0.90) count at 50%.
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

        # 4. Max exposure (total deployed capital) with near-resolution discount
        effective_exposure = self._effective_exposure()
        max_exposure_eur = equity * (self._max_exposure_pct / 100.0)
        if effective_exposure + size_eur > max_exposure_eur:
            return RiskCheck(
                approved=False,
                reason=(
                    f"Would exceed max exposure: "
                    f"{effective_exposure + size_eur:.2f} > {max_exposure_eur:.2f} EUR"
                ),
            )

        # 4b. Horizon pool limit (Phase 10)
        if time_horizon is not None:
            pool_pct = self._horizon_pct.get(time_horizon, 100.0)
            pool_limit = max_exposure_eur * (pool_pct / 100.0)
            pool_exposure = self._exposure_by_horizon(time_horizon)
            if pool_exposure + size_eur > pool_limit:
                return RiskCheck(
                    approved=False,
                    reason=(
                        f"Horizon {time_horizon.value} pool full: "
                        f"{pool_exposure + size_eur:.2f} > {pool_limit:.2f} EUR"
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

        if effective_exposure + size_eur > max_exposure_eur * 0.8:
            warnings.append(
                f"Approaching max exposure "
                f"({(effective_exposure + size_eur) / max_exposure_eur * 100:.0f}%)"
            )

        return RiskCheck(approved=True, warnings=warnings)

    def size_position(self, signal: Signal, capital: float, price: float) -> SizeResult:
        """Calculate position size using signal edge and confidence.

        Size is proportional to edge × confidence (half-Kelly).
        Updates the internal sizer's max_single_eur based on current equity.
        """
        # Resolve % limits against current capital
        self._sizer._max_single = self._resolve_max_single(capital)

        result = self._sizer.from_signal(
            capital, price, signal.confidence, edge=abs(signal.edge_amount)
        )
        logger.debug(
            "position_sized",
            token_id=signal.token_id[:20],
            confidence=signal.confidence,
            edge=signal.edge_amount,
            size_eur=result.size_eur,
            method=result.method,
            capped=result.capped,
        )
        return result

    def record_fill(
        self,
        token_id: str,
        size_eur: float,
        time_horizon: TimeHorizon | None = None,
    ) -> None:
        """Record a filled order for exposure tracking."""
        current = self._current_positions.get(token_id, 0.0)
        self._current_positions[token_id] = current + size_eur
        if time_horizon is not None:
            self._position_horizons[token_id] = time_horizon
        logger.info(
            "fill_recorded",
            token_id=token_id[:20],
            size_eur=size_eur,
            horizon=time_horizon.value if time_horizon else "unknown",
            total_exposure=self.current_exposure,
        )

    def record_close(self, token_id: str, pnl: float) -> None:
        """Record a closed position and its P&L."""
        self._current_positions.pop(token_id, None)
        self._position_horizons.pop(token_id, None)
        self._position_near_resolution.pop(token_id, None)
        self._daily_pnl += pnl
        logger.info(
            "position_closed",
            token_id=token_id[:20],
            pnl=pnl,
            daily_pnl=self._daily_pnl,
        )

    def mark_near_resolution(self, token_id: str, near: bool = True) -> None:
        """Mark a position as near-resolution (< 24h, prob > 0.90).

        Near-resolution positions count at 50% for exposure calculations,
        freeing up effective capital for new trades.
        """
        if near:
            self._position_near_resolution[token_id] = True
        else:
            self._position_near_resolution.pop(token_id, None)

    def reset_daily(self) -> None:
        """Reset daily P&L tracking (called at start of new trading day)."""
        self._daily_pnl = 0.0
        logger.info("daily_reset")

    def _effective_exposure(self) -> float:
        """Compute effective exposure with near-resolution discount.

        Positions flagged as near-resolution count at 50% because
        the capital is about to be freed.
        """
        total = 0.0
        for token_id, eur in self._current_positions.items():
            if self._position_near_resolution.get(token_id, False):
                total += eur * 0.5
            else:
                total += eur
        return total

    def _exposure_by_horizon(self, horizon: TimeHorizon) -> float:
        """Sum exposure for positions in a given horizon pool."""
        total = 0.0
        for token_id, eur in self._current_positions.items():
            if self._position_horizons.get(token_id) == horizon:
                if self._position_near_resolution.get(token_id, False):
                    total += eur * 0.5
                else:
                    total += eur
        return total

    @property
    def current_exposure(self) -> float:
        return sum(self._current_positions.values())

    @property
    def effective_exposure(self) -> float:
        return self._effective_exposure()

    @property
    def daily_pnl(self) -> float:
        return self._daily_pnl

    @property
    def position_count(self) -> int:
        return len(self._current_positions)
