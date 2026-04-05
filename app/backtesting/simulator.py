"""Fill simulator with slippage and fee modeling."""

from dataclasses import dataclass

from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class SimulatedFill:
    """Result of a simulated order fill."""

    market_id: str = ""
    strategy: str = ""
    side: str = ""  # "BUY" or "SELL"
    entry_price: float = 0.0
    exit_price: float = 0.0  # set when position closed
    size_eur: float = 0.0
    fee_paid: float = 0.0
    slippage: float = 0.0  # price impact
    pnl: float = 0.0  # realized P&L (set on close)
    is_open: bool = True


class FillSimulator:
    """Simulates order fills with realistic slippage and fees."""

    # Fee rates by category
    FEE_RATES: dict[str, float] = {
        "geopolitics": 0.0,
        "politics": 0.0,
        "crypto": 0.072,
        "sports": 0.03,
        "economics": 0.01,
        "entertainment": 0.02,
    }
    DEFAULT_FEE = 0.02

    # Slippage model: percentage of price
    BASE_SLIPPAGE_PCT = 0.005  # 0.5% base slippage

    def __init__(self, slippage_pct: float | None = None) -> None:
        self._slippage_pct = slippage_pct if slippage_pct is not None else self.BASE_SLIPPAGE_PCT

    def simulate_entry(
        self,
        market_id: str,
        strategy: str,
        side: str,
        price: float,
        size_eur: float,
        category: str = "",
    ) -> SimulatedFill:
        """Simulate entering a position."""
        fee_rate = self.FEE_RATES.get(category, self.DEFAULT_FEE)
        slippage = price * self._slippage_pct

        entry_price = price + slippage if side == "BUY" else price - slippage

        fee = size_eur * fee_rate

        logger.debug(
            "simulate_entry",
            market_id=market_id,
            side=side,
            price=price,
            entry_price=round(entry_price, 4),
            fee=round(fee, 4),
        )

        return SimulatedFill(
            market_id=market_id,
            strategy=strategy,
            side=side,
            entry_price=round(entry_price, 4),
            size_eur=round(size_eur, 2),
            fee_paid=round(fee, 4),
            slippage=round(slippage, 4),
        )

    def simulate_exit(self, fill: SimulatedFill, exit_price: float) -> SimulatedFill:
        """Simulate closing a position. Returns updated fill with P&L."""
        if fill.side == "BUY":
            # Bought at entry, selling at exit
            price_diff = exit_price - fill.entry_price
        else:
            # Sold at entry, buying back at exit
            price_diff = fill.entry_price - exit_price

        # P&L: price_diff * shares - fees
        shares = fill.size_eur / fill.entry_price if fill.entry_price > 0 else 0
        pnl = price_diff * shares - fill.fee_paid

        fill.exit_price = round(exit_price, 4)
        fill.pnl = round(pnl, 4)
        fill.is_open = False

        logger.debug(
            "simulate_exit",
            market_id=fill.market_id,
            side=fill.side,
            exit_price=exit_price,
            pnl=fill.pnl,
        )

        return fill
