"""Position sizing algorithms."""

from dataclasses import dataclass

from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class SizeResult:
    size_eur: float = 0.0  # position size in EUR
    size_shares: float = 0.0  # number of shares (size_eur / price)
    method: str = ""
    capped: bool = False  # True if size was reduced by a limit
    cap_reason: str = ""


class PositionSizer:
    """Calculates position sizes using various methods."""

    def __init__(
        self,
        fixed_fraction_pct: float = 5.0,
        max_single_eur: float = 25.0,
    ) -> None:
        self._fixed_fraction = fixed_fraction_pct / 100.0
        self._max_single = max_single_eur

    def fixed_fraction(self, capital: float, price: float) -> SizeResult:
        """Fixed fraction sizing: risk fixed_fraction_pct of capital per trade."""
        raw_size = capital * self._fixed_fraction
        return self._apply_caps(raw_size, price, method="fixed_fraction")

    def kelly_criterion(
        self,
        capital: float,
        price: float,
        win_prob: float,
        win_payout: float,
        loss_amount: float = 1.0,
    ) -> SizeResult:
        """Kelly criterion: f* = (p*b - q) / b
        where p=win_prob, q=1-p, b=win_payout/loss_amount.

        Uses half-Kelly for safety (f*/2).
        """
        if win_prob <= 0 or win_prob >= 1 or win_payout <= 0:
            return SizeResult(method="kelly")

        q = 1.0 - win_prob
        b = win_payout / loss_amount
        kelly_f = (win_prob * b - q) / b

        if kelly_f <= 0:
            return SizeResult(method="kelly")  # negative Kelly = don't bet

        # Half-Kelly for safety
        half_kelly = kelly_f / 2.0
        raw_size = capital * half_kelly
        return self._apply_caps(raw_size, price, method="kelly")

    def from_signal(self, capital: float, price: float, signal_confidence: float) -> SizeResult:
        """Size based on signal confidence: higher confidence = larger position.

        Maps confidence (0-1) to fraction of fixed_fraction allocation.
        confidence < 0.3  → 50% of fixed fraction
        confidence 0.3-0.7 → 50-100% of fixed fraction (linear)
        confidence > 0.7  → 100% of fixed fraction
        """
        if signal_confidence < 0.3:
            fraction = 0.5
        elif signal_confidence > 0.7:
            fraction = 1.0
        else:
            # Linear interpolation between 0.5 and 1.0
            fraction = 0.5 + (signal_confidence - 0.3) / 0.4 * 0.5

        raw_size = capital * self._fixed_fraction * fraction
        return self._apply_caps(raw_size, price, method="confidence_scaled")

    def _apply_caps(self, raw_size: float, price: float, method: str) -> SizeResult:
        """Apply position size caps."""
        capped = False
        cap_reason = ""

        size = raw_size
        if size > self._max_single:
            size = self._max_single
            capped = True
            cap_reason = f"max_single_position ({self._max_single} EUR)"

        shares = size / price if price > 0 else 0.0

        return SizeResult(
            size_eur=round(size, 2),
            size_shares=round(shares, 4),
            method=method,
            capped=capped,
            cap_reason=cap_reason,
        )
