"""Realistic dry-run CLOB simulation for Polymarket.

Mirrors real Polymarket mechanics:
- You BUY shares of an outcome (YES or NO) at a price between 0 and 1
- Each share costs `price` USDC and pays out $1 if the outcome wins, $0 if it loses
- P&L is realized ONLY when you sell shares or the market resolves
- Fill simulation uses real orderbook depth when available, with slippage
- Position tracking is in shares, not EUR
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.core.logging import get_logger
from app.core.yaml_config import app_config
from app.models.order import (
    Balance,
    OrderRequest,
    OrderResult,
    OrderSide,
    OrderStatus,
    Position,
)

logger = get_logger(__name__)

_INITIAL_BALANCE = 150.0

# Simulated slippage: for each $100 of order value, price moves by this fraction
_SLIPPAGE_PER_100 = 0.002

# Maximum fill as fraction of estimated market depth
_MAX_FILL_DEPTH_PCT = 0.10  # don't fill more than 10% of visible depth


class PolymarketClobClient:
    """Realistic dry-run CLOB client.

    Simulates Polymarket's actual mechanics:
    - Balance in USDC
    - Positions in outcome shares
    - Fill with slippage based on order size
    - P&L only on sell or resolution
    """

    def __init__(self) -> None:
        self._execution_mode = app_config.execution.mode
        self._balance = _INITIAL_BALANCE  # available USDC
        self._positions: dict[str, Position] = {}  # token_id → Position
        self._realized_pnl: float = 0.0
        self._orders: dict[str, OrderResult] = {}
        logger.info(
            "clob_client_init",
            mode=self._execution_mode,
            initial_balance=self._balance,
        )

    @property
    def mode(self) -> str:
        return self._execution_mode

    async def place_order(
        self,
        order: OrderRequest,
        orderbook_depth: float | None = None,
    ) -> OrderResult:
        """Place an order with realistic fill simulation.

        Args:
            order: The order to execute
            orderbook_depth: Total shares available on the relevant side of the book.
                             If provided, limits fill size.
        """
        if self._execution_mode == "live":
            raise NotImplementedError("Live trading not yet implemented")

        order_id = str(uuid4())
        now = datetime.now(tz=UTC)

        # Calculate slippage-adjusted price
        order_value = order.price * order.size
        slippage = _SLIPPAGE_PER_100 * (order_value / 100.0)
        if order.side == OrderSide.BUY:
            fill_price = min(0.99, order.price + slippage)
        else:
            fill_price = max(0.01, order.price - slippage)

        # Limit fill size by orderbook depth
        fill_size = order.size
        if orderbook_depth and orderbook_depth > 0:
            max_fill = orderbook_depth * _MAX_FILL_DEPTH_PCT
            if fill_size > max_fill:
                fill_size = max_fill
                logger.info(
                    "fill_size_limited",
                    requested=order.size,
                    filled=fill_size,
                    depth=orderbook_depth,
                )

        cost = fill_price * fill_size

        # Check balance for buys
        if order.side == OrderSide.BUY and cost > self._balance:
            # Partial fill: buy what we can afford
            if self._balance > fill_price:
                fill_size = self._balance / fill_price
                cost = self._balance
            else:
                return OrderResult(
                    order_id=order_id,
                    status=OrderStatus.REJECTED,
                    token_id=order.token_id,
                    side=order.side,
                    price=fill_price,
                    size=order.size,
                    filled_size=0.0,
                    is_simulated=True,
                    timestamp=now,
                    error="Insufficient balance",
                )

        # For sells: check we have shares to sell
        if order.side == OrderSide.SELL:
            pos = self._positions.get(order.token_id)
            if not pos or pos.size <= 0:
                return OrderResult(
                    order_id=order_id,
                    status=OrderStatus.REJECTED,
                    token_id=order.token_id,
                    side=order.side,
                    price=fill_price,
                    size=order.size,
                    filled_size=0.0,
                    is_simulated=True,
                    timestamp=now,
                    error="No position to sell",
                )
            fill_size = min(fill_size, pos.size)
            cost = fill_price * fill_size

        # Execute fill
        result = OrderResult(
            order_id=order_id,
            status=OrderStatus.FILLED,
            token_id=order.token_id,
            side=order.side,
            price=fill_price,
            size=fill_size,
            filled_size=fill_size,
            is_simulated=True,
            timestamp=now,
        )

        # Update balance and positions
        if order.side == OrderSide.BUY:
            self._balance -= cost
            self._add_to_position(order.market_id, order.token_id, fill_size, fill_price)
        else:
            self._balance += cost
            realized = self._reduce_position(order.token_id, fill_size, fill_price)
            self._realized_pnl += realized

        self._orders[order_id] = result

        logger.info(
            "order_filled",
            order_id=order_id,
            mode=self._execution_mode,
            token_id=order.token_id[:20] + "...",
            side=str(order.side),
            requested_price=order.price,
            fill_price=round(fill_price, 4),
            fill_size=round(fill_size, 2),
            slippage=round(slippage, 4),
            balance_after=round(self._balance, 2),
        )

        return result

    def _add_to_position(
        self, market_id: str, token_id: str, shares: float, price: float
    ) -> None:
        """Add shares to a position with weighted average cost basis."""
        existing = self._positions.get(token_id)
        if existing is None:
            self._positions[token_id] = Position(
                market_id=market_id,
                token_id=token_id,
                side=OrderSide.BUY,
                size=shares,
                avg_price=price,
                current_price=price,
            )
        else:
            total = existing.size + shares
            existing.avg_price = (
                (existing.avg_price * existing.size) + (price * shares)
            ) / total
            existing.size = total
            existing.current_price = price

    def _reduce_position(
        self, token_id: str, shares: float, sell_price: float
    ) -> float:
        """Reduce position by selling shares. Returns realized P&L."""
        pos = self._positions.get(token_id)
        if pos is None:
            return 0.0

        sold = min(shares, pos.size)
        # Realized P&L = (sell_price - avg_cost) * shares_sold
        realized = (sell_price - pos.avg_price) * sold

        pos.size -= sold
        if pos.size <= 0.001:  # effectively zero
            del self._positions[token_id]
        else:
            pos.current_price = sell_price

        return realized

    def resolve_position(self, token_id: str, payout: float) -> float:
        """Resolve a position when market outcome is determined.

        Args:
            payout: 1.0 if the outcome won, 0.0 if it lost.

        Returns:
            Realized P&L from resolution.
        """
        pos = self._positions.get(token_id)
        if pos is None:
            return 0.0

        # P&L = (payout - avg_cost) * shares
        realized = (payout - pos.avg_price) * pos.size
        # Add payout to balance
        self._balance += payout * pos.size
        self._realized_pnl += realized

        logger.info(
            "position_resolved",
            token_id=token_id[:20] + "...",
            payout=payout,
            shares=round(pos.size, 2),
            avg_cost=round(pos.avg_price, 4),
            realized_pnl=round(realized, 4),
        )

        del self._positions[token_id]
        return realized

    def update_market_price(self, token_id: str, current_price: float) -> None:
        """Update market price for unrealized P&L display (indicative only)."""
        pos = self._positions.get(token_id)
        if pos is None:
            return
        pos.current_price = current_price
        # Indicative unrealized P&L — NOT realized until sold or resolved
        pos.unrealized_pnl = (current_price - pos.avg_price) * pos.size

    async def cancel_order(self, order_id: str) -> bool:
        if self._execution_mode == "live":
            raise NotImplementedError("Live trading not yet implemented")
        if order_id in self._orders:
            self._orders[order_id].status = OrderStatus.CANCELLED
            return True
        return False

    async def get_positions(self) -> list[Position]:
        if self._execution_mode == "live":
            raise NotImplementedError("Live trading not yet implemented")
        return list(self._positions.values())

    async def get_balance(self) -> Balance:
        """Balance: available cash + value of positions at current market price."""
        if self._execution_mode == "live":
            raise NotImplementedError("Live trading not yet implemented")

        locked = 0.0
        unrealized = 0.0
        for pos in self._positions.values():
            locked += pos.size * pos.avg_price  # cost basis
            unrealized += pos.unrealized_pnl
        return Balance(
            total=self._balance + locked + unrealized,
            available=self._balance,
            locked=locked,
        )

    async def get_open_orders(self) -> list[OrderResult]:
        if self._execution_mode == "live":
            raise NotImplementedError("Live trading not yet implemented")
        return [
            o for o in self._orders.values()
            if o.status in (OrderStatus.PENDING, OrderStatus.LIVE)
        ]

    async def close(self) -> None:
        logger.info("clob_client_closed", mode=self._execution_mode)
