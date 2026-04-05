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
