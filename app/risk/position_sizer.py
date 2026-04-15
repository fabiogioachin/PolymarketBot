"""Position sizing algorithms.

Core principle: size is proportional to edge × confidence.
Higher edge = larger position. Higher confidence = larger position.
Uses half-Kelly as the primary method for bankroll-optimal sizing.
"""

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
    """Calculates position sizes proportional to edge and confidence.

    Primary method: half-Kelly criterion.
    - f* = edge / odds, then halved for safety.
    - Scaled by confidence (low confidence = smaller fraction of Kelly).
    - Bounded by max_single and min_size.

    This ensures:
    - A 15% edge trade gets ~5× the size of a 3% edge trade.
    - Low confidence reduces size even with high edge.
    - The fixed_fraction_pct acts as an UPPER BOUND, not the default size.
    """

    def __init__(
        self,
        fixed_fraction_pct: float = 5.0,
        max_single_eur: float = 25.0,
        min_size_eur: float = 1.0,
    ) -> None:
        self._max_fraction = fixed_fraction_pct / 100.0  # upper bound
        self._max_single = max_single_eur
        self._min_size = min_size_eur

    def from_signal(
        self,
        capital: float,
        price: float,
        confidence: float,
        edge: float = 0.0,
    ) -> SizeResult:
        """Size based on edge and confidence (half-Kelly).

        Kelly fraction = edge / (price × (1 - price))
        → simplified for binary markets where payout is 1/price - 1.
        Half-Kelly = kelly / 2 for safety.
        Confidence scales the result: low confidence → smaller position.

        Falls back to confidence-only scaling if edge is 0 or negative.
        """
        if edge <= 0 or price <= 0 or price >= 1.0:
            # No edge or invalid price → minimum size
            return self._apply_caps(self._min_size, price, method="minimum")

        # Kelly for binary markets: f* = edge / (1 - price)
        # where edge = fair_value - price, odds = (1/price) - 1
        # Simplified: f* = edge / (1 - price) when payout at resolution is $1
        odds = (1.0 / price) - 1.0  # payout ratio if we win
        if odds <= 0:
            return self._apply_caps(self._min_size, price, method="minimum")

        kelly_f = edge / (1.0 - price)

        # Half-Kelly for safety
        half_kelly = kelly_f / 2.0

        # Scale by confidence (0-1): low confidence → smaller fraction
        # confidence < 0.3 is already filtered by VAE, but handle gracefully
        confidence_factor = max(0.2, min(1.0, confidence))
        fraction = half_kelly * confidence_factor

        # Cap at max_fraction (the old "fixed fraction" becomes an upper bound)
        fraction = min(fraction, self._max_fraction)

        raw_size = capital * fraction
        return self._apply_caps(raw_size, price, method="half_kelly")

    def kelly_criterion(
        self,
        capital: float,
        price: float,
        win_prob: float,
        win_payout: float,
        loss_amount: float = 1.0,
    ) -> SizeResult:
        """Classic Kelly criterion: f* = (p*b - q) / b

        Uses half-Kelly for safety.
        """
        if win_prob <= 0 or win_prob >= 1 or win_payout <= 0:
            return SizeResult(method="kelly")

        q = 1.0 - win_prob
        b = win_payout / loss_amount
        kelly_f = (win_prob * b - q) / b

        if kelly_f <= 0:
            return SizeResult(method="kelly")

        half_kelly = kelly_f / 2.0
        raw_size = capital * half_kelly
        return self._apply_caps(raw_size, price, method="kelly")

    def _apply_caps(self, raw_size: float, price: float, method: str) -> SizeResult:
        """Apply position size caps and minimum."""
        capped = False
        cap_reason = ""

        size = max(raw_size, 0.0)

        # Apply minimum
        if size < self._min_size:
            size = self._min_size

        # Apply maximum
        if size > self._max_single:
            size = self._max_single
            capped = True
            cap_reason = f"max_single_position ({self._max_single:.2f} EUR)"

        shares = size / price if price > 0 else 0.0

        return SizeResult(
            size_eur=round(size, 2),
            size_shares=round(shares, 4),
            method=method,
            capped=capped,
            cap_reason=cap_reason,
        )
