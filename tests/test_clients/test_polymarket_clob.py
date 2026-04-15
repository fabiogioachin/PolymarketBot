"""Tests for the dry-run CLOB client."""

import pytest

from app.clients.polymarket_clob import _INITIAL_BALANCE, PolymarketClobClient
from app.models.order import (
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
)


@pytest.fixture
def client() -> PolymarketClobClient:
    """Create a fresh dry-run CLOB client."""
    return PolymarketClobClient()


def _buy_order(
    token_id: str = "token_abc",
    price: float = 0.60,
    size: float = 10.0,
    market_id: str = "market_1",
) -> OrderRequest:
    return OrderRequest(
        token_id=token_id,
        side=OrderSide.BUY,
        price=price,
        size=size,
        order_type=OrderType.LIMIT,
        market_id=market_id,
        reason="test buy",
    )


def _sell_order(
    token_id: str = "token_abc",
    price: float = 0.70,
    size: float = 10.0,
    market_id: str = "market_1",
) -> OrderRequest:
    return OrderRequest(
        token_id=token_id,
        side=OrderSide.SELL,
        price=price,
        size=size,
        order_type=OrderType.LIMIT,
        market_id=market_id,
        reason="test sell",
    )


@pytest.mark.asyncio
async def test_mode_is_dry_run(client: PolymarketClobClient) -> None:
    assert client.mode == "dry_run"


@pytest.mark.asyncio
async def test_initial_balance(client: PolymarketClobClient) -> None:
    balance = await client.get_balance()
    assert balance.available == _INITIAL_BALANCE
    assert balance.total == _INITIAL_BALANCE
    assert balance.locked == 0.0
    assert balance.currency == "USDC"


@pytest.mark.asyncio
async def test_place_buy_order(client: PolymarketClobClient) -> None:
    order = _buy_order(price=0.60, size=10.0)
    result = await client.place_order(order)

    assert result.status == OrderStatus.FILLED
    assert result.is_simulated is True
    assert result.filled_size == 10.0
    assert result.order_id != ""
    assert result.timestamp is not None

    # Balance decreases by cost (with slippage, slightly more than 6.0)
    balance = await client.get_balance()
    assert balance.available == pytest.approx(_INITIAL_BALANCE - 6.0, abs=0.1)

    # Position should exist
    positions = await client.get_positions()
    assert len(positions) == 1
    assert positions[0].token_id == "token_abc"
    assert positions[0].size == 10.0
    # Fill price includes slippage
    assert positions[0].avg_price == pytest.approx(0.60, abs=0.01)


@pytest.mark.asyncio
async def test_place_sell_order(client: PolymarketClobClient) -> None:
    # First buy, then sell
    await client.place_order(_buy_order(price=0.60, size=10.0))
    result = await client.place_order(_sell_order(price=0.70, size=10.0))

    assert result.status == OrderStatus.FILLED
    assert result.is_simulated is True

    # Position should be closed (fully sold)
    positions = await client.get_positions()
    assert len(positions) == 0

    # Balance approximately: 150 - ~6.0 + ~7.0 = ~151 (with slippage on both sides)
    balance = await client.get_balance()
    assert balance.available == pytest.approx(151.0, abs=0.1)


@pytest.mark.asyncio
async def test_sell_without_position_rejected(client: PolymarketClobClient) -> None:
    """Selling without an existing position is rejected (no shorting on Polymarket)."""
    result = await client.place_order(_sell_order(price=0.50, size=5.0))

    assert result.status == OrderStatus.REJECTED
    assert "No position to sell" in result.error

    # Balance unchanged
    balance = await client.get_balance()
    assert balance.available == pytest.approx(_INITIAL_BALANCE)


@pytest.mark.asyncio
async def test_cancel_order(client: PolymarketClobClient) -> None:
    result = await client.place_order(_buy_order())
    cancelled = await client.cancel_order(result.order_id)
    assert cancelled is True

    # Non-existent order
    cancelled = await client.cancel_order("nonexistent-id")
    assert cancelled is False


@pytest.mark.asyncio
async def test_get_positions(client: PolymarketClobClient) -> None:
    positions = await client.get_positions()
    assert positions == []

    await client.place_order(_buy_order(token_id="tok1", price=0.50, size=5.0))
    await client.place_order(_buy_order(token_id="tok2", price=0.30, size=8.0))

    positions = await client.get_positions()
    assert len(positions) == 2
    token_ids = {p.token_id for p in positions}
    assert token_ids == {"tok1", "tok2"}


@pytest.mark.asyncio
async def test_multiple_orders_same_token(client: PolymarketClobClient) -> None:
    """Accumulating position with multiple buys on same token."""
    await client.place_order(_buy_order(price=0.50, size=10.0))
    await client.place_order(_buy_order(price=0.60, size=10.0))

    positions = await client.get_positions()
    assert len(positions) == 1
    pos = positions[0]
    assert pos.size == 20.0
    # Weighted avg approximately 0.55 (with slippage on each leg)
    assert pos.avg_price == pytest.approx(0.55, abs=0.01)

    # Balance approximately 150 - 5.0 - 6.0 = 139.0 (with slippage)
    balance = await client.get_balance()
    assert balance.available == pytest.approx(139.0, abs=0.1)


@pytest.mark.asyncio
async def test_insufficient_balance_partial_fill(client: PolymarketClobClient) -> None:
    """Buy order exceeding balance gets partially filled (buys what it can afford)."""
    order = _buy_order(price=1.0, size=200.0)  # cost = 200, balance = 150
    result = await client.place_order(order)

    # Partial fill: buys ~150/0.99 shares (with slippage) instead of 200
    assert result.status == OrderStatus.FILLED
    assert result.filled_size < 200.0
    assert result.filled_size > 100.0  # should fill a substantial amount

    # Balance should be near zero (spent everything affordable)
    balance = await client.get_balance()
    assert balance.available == pytest.approx(0.0, abs=1.0)


@pytest.mark.asyncio
async def test_live_mode_not_implemented(monkeypatch: pytest.MonkeyPatch) -> None:
    """Live mode should raise NotImplementedError."""
    from app.core import yaml_config

    original_mode = yaml_config.app_config.execution.mode
    monkeypatch.setattr(yaml_config.app_config.execution, "mode", "live")

    try:
        client = PolymarketClobClient()
        assert client.mode == "live"

        with pytest.raises(NotImplementedError, match="Live trading not yet implemented"):
            await client.place_order(_buy_order())

        with pytest.raises(NotImplementedError, match="Live trading not yet implemented"):
            await client.cancel_order("some-id")

        with pytest.raises(NotImplementedError, match="Live trading not yet implemented"):
            await client.get_positions()

        with pytest.raises(NotImplementedError, match="Live trading not yet implemented"):
            await client.get_balance()

        with pytest.raises(NotImplementedError, match="Live trading not yet implemented"):
            await client.get_open_orders()
    finally:
        monkeypatch.setattr(yaml_config.app_config.execution, "mode", original_mode)


@pytest.mark.asyncio
async def test_get_open_orders_empty(client: PolymarketClobClient) -> None:
    """All simulated orders are immediately filled, so open orders should be empty."""
    await client.place_order(_buy_order())
    open_orders = await client.get_open_orders()
    assert open_orders == []


@pytest.mark.asyncio
async def test_close(client: PolymarketClobClient) -> None:
    """Close should not raise."""
    await client.close()


# ── Regression tests: R3-R7 — Simulated Trading Realism ──────────────


class TestPnlConsistency:
    """R3: P&L must be consistent between CLOB buy/sell cycle and _realized_pnl."""

    @pytest.mark.asyncio
    async def test_pnl_consistency_clob_and_realized(
        self, client: PolymarketClobClient
    ) -> None:
        """Buy 10 shares @ 0.40, sell 10 @ 0.60. Realized P&L approx +2.0."""
        # Buy 10 shares at 0.40
        buy_result = await client.place_order(
            _buy_order(price=0.40, size=10.0)
        )
        assert buy_result.status == OrderStatus.FILLED
        buy_fill_price = buy_result.price

        # Sell 10 shares at 0.60
        sell_result = await client.place_order(
            _sell_order(price=0.60, size=10.0)
        )
        assert sell_result.status == OrderStatus.FILLED
        sell_fill_price = sell_result.price

        # Expected P&L = (sell_price - buy_price) * shares
        expected_pnl = (sell_fill_price - buy_fill_price) * sell_result.filled_size

        # Realized P&L should be approximately +2.0 (adjusted for spread/slippage)
        assert client._realized_pnl == pytest.approx(expected_pnl, abs=0.01)
        assert client._realized_pnl == pytest.approx(2.0, abs=0.5)

        # Position should be fully closed
        positions = await client.get_positions()
        assert len(positions) == 0


class TestEquityCalculation:
    """R4: Equity = available cash + cost_basis + unrealized P&L."""

    @pytest.mark.asyncio
    async def test_equity_calculation_correct(
        self, client: PolymarketClobClient
    ) -> None:
        """Buy shares, update price, verify balance components."""
        initial_balance = _INITIAL_BALANCE

        # Buy 10 shares @ 0.50
        buy_result = await client.place_order(
            _buy_order(price=0.50, size=10.0)
        )
        assert buy_result.status == OrderStatus.FILLED
        fill_price = buy_result.price
        fill_size = buy_result.filled_size
        cost = fill_price * fill_size

        # Available cash should have decreased
        balance = await client.get_balance()
        assert balance.available == pytest.approx(
            initial_balance - cost, abs=0.01
        )

        # Locked = cost basis
        assert balance.locked == pytest.approx(
            fill_size * fill_price, abs=0.01
        )

        # Update price upward to generate unrealized P&L
        client.update_market_price("token_abc", 0.55)

        balance_after = await client.get_balance()
        # Available unchanged after price update (no trade)
        assert balance_after.available == pytest.approx(
            initial_balance - cost, abs=0.01
        )
        # Locked still at cost basis (avg_price * size)
        assert balance_after.locked == pytest.approx(
            fill_size * fill_price, abs=0.01
        )
        # Total = available + locked + unrealized
        expected_total = (
            balance_after.available
            + balance_after.locked
            + (0.55 - fill_price) * fill_size
        )
        assert balance_after.total == pytest.approx(expected_total, abs=0.01)


class TestSpreadCost:
    """R5: Buying and immediately selling at the same price costs spread."""

    @pytest.mark.asyncio
    async def test_spread_cost_reduces_pnl(
        self, client: PolymarketClobClient
    ) -> None:
        """Buy then sell at same price: net P&L < 0 (spread cost)."""
        # Buy 10 shares @ 0.50
        await client.place_order(_buy_order(price=0.50, size=10.0))

        # Immediately sell at the same price
        await client.place_order(_sell_order(price=0.50, size=10.0))

        # Net P&L should be negative (spread cost)
        assert client._realized_pnl < 0.0
        # But not catastrophically negative (reasonable spread)
        assert client._realized_pnl > -0.10


class TestFillPriceCap:
    """R6: Buy fill price is capped at 0.99 even for high-priced orders."""

    @pytest.mark.asyncio
    async def test_fill_price_cap_on_buy(
        self, client: PolymarketClobClient
    ) -> None:
        """Buy at 0.95: fill price between 0.95 and 0.99 (capped)."""
        result = await client.place_order(
            _buy_order(price=0.95, size=5.0)
        )
        assert result.status == OrderStatus.FILLED
        # Fill price should be <= 0.99 (capped by CLOB simulation)
        assert result.price <= 0.99
        # Fill price should be > order price (spread + slippage)
        assert result.price > 0.95


class TestSubPennyDepthCap:
    """R7: Sub-penny tokens have severe depth limits."""

    @pytest.mark.asyncio
    async def test_sub_penny_depth_cap(
        self, client: PolymarketClobClient
    ) -> None:
        """Buy 1000 shares @ 0.005: depth cap limits fill to <= 100 shares."""
        result = await client.place_order(
            _buy_order(price=0.005, size=1000.0)
        )
        # Should fill (not reject), but with limited quantity
        assert result.status == OrderStatus.FILLED
        # Depth cap at sub-penny: max 100 shares fillable
        assert result.filled_size <= 100.0
        # Should fill something (not zero)
        assert result.filled_size > 0.0
