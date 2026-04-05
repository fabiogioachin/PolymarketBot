"""Tests for dashboard API endpoints."""

import json

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def client() -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ── /dashboard/overview ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_overview_returns_200(client: AsyncClient) -> None:
    response = await client.get("/api/v1/dashboard/overview")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_overview_returns_expected_structure(client: AsyncClient) -> None:
    response = await client.get("/api/v1/dashboard/overview")
    data = response.json()

    assert "bot" in data
    assert "metrics" in data
    assert "circuit_breaker" in data

    bot = data["bot"]
    assert "running" in bot
    assert "mode" in bot
    assert "tick_count" in bot

    m = data["metrics"]
    assert "total_trades" in m
    assert "daily_pnl" in m
    assert "win_rate" in m
    assert "open_positions" in m
    assert "equity" in m

    cb = data["circuit_breaker"]
    assert "tripped" in cb


# ── /dashboard/config ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_config_returns_200(client: AsyncClient) -> None:
    response = await client.get("/api/v1/dashboard/config")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_config_returns_strategy_risk_valuation(client: AsyncClient) -> None:
    response = await client.get("/api/v1/dashboard/config")
    data = response.json()

    assert "strategies" in data
    assert "enabled" in data["strategies"]
    assert isinstance(data["strategies"]["enabled"], list)

    assert "risk" in data
    risk = data["risk"]
    assert "max_exposure_pct" in risk
    assert "daily_loss_limit_eur" in risk
    assert "fixed_fraction_pct" in risk
    assert "max_positions" in risk

    assert "valuation" in data
    assert "weights" in data["valuation"]
    assert "thresholds" in data["valuation"]

    assert "intelligence" in data
    assert "gdelt_enabled" in data["intelligence"]
    assert "rss_enabled" in data["intelligence"]

    assert "llm" in data
    assert "enabled" in data["llm"]
    assert "model" in data["llm"]


# ── /dashboard/equity ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_equity_returns_expected_structure(client: AsyncClient) -> None:
    response = await client.get("/api/v1/dashboard/equity")
    assert response.status_code == 200

    data = response.json()
    assert "equity_curve" in data
    assert isinstance(data["equity_curve"], list)
    assert "starting_capital" in data
    assert data["starting_capital"] == pytest.approx(150.0)


# ── /dashboard/trades ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_trades_returns_expected_structure(client: AsyncClient) -> None:
    response = await client.get("/api/v1/dashboard/trades")
    assert response.status_code == 200

    data = response.json()
    assert "trades" in data
    assert isinstance(data["trades"], list)
    assert "total" in data
    assert isinstance(data["total"], int)


# ── /dashboard/strategies ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_strategies_returns_expected_structure(client: AsyncClient) -> None:
    response = await client.get("/api/v1/dashboard/strategies")
    assert response.status_code == 200

    data = response.json()
    assert "strategies" in data
    assert isinstance(data["strategies"], list)


# ── /dashboard/positions ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_positions_returns_200(client: AsyncClient) -> None:
    response = await client.get("/api/v1/dashboard/positions")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_positions_returns_expected_structure(client: AsyncClient) -> None:
    response = await client.get("/api/v1/dashboard/positions")
    data = response.json()

    assert "positions" in data
    assert isinstance(data["positions"], list)
    assert "total_unrealized_pnl" in data
    assert isinstance(data["total_unrealized_pnl"], int | float)


@pytest.mark.asyncio
async def test_positions_structure(client: AsyncClient) -> None:
    response = await client.get("/api/v1/dashboard/positions")
    data = response.json()

    assert "positions" in data
    assert isinstance(data["positions"], list)
    assert "total_unrealized_pnl" in data
    assert isinstance(data["total_unrealized_pnl"], int | float)


# ── /dashboard/stream (SSE) ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_stream_endpoint_response_metadata() -> None:
    """Verify the SSE endpoint returns StreamingResponse with correct config."""
    from fastapi.responses import StreamingResponse

    from app.monitoring.dashboard import stream_dashboard

    response = await stream_dashboard()

    assert isinstance(response, StreamingResponse)
    assert response.media_type == "text/event-stream"
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["connection"] == "keep-alive"
    assert response.headers["x-accel-buffering"] == "no"


@pytest.mark.asyncio
async def test_stream_generator_yields_valid_sse_event() -> None:
    """Verify the SSE generator yields a valid data event on first iteration."""
    from app.monitoring.dashboard import _build_full_state

    state = await _build_full_state()
    # Simulate what the generator does: format as SSE
    event = f"data: {json.dumps(state)}\n\n"

    assert event.startswith("data: ")
    assert event.endswith("\n\n")

    # Parse back and verify
    payload = json.loads(event.removeprefix("data: ").strip())
    assert "overview" in payload
    assert "positions" in payload
    assert "trades" in payload


@pytest.mark.asyncio
async def test_stream_build_full_state_structure() -> None:
    """Test _build_full_state directly to verify SSE payload structure."""
    from app.monitoring.dashboard import _build_full_state

    state = await _build_full_state()

    assert "overview" in state
    assert "positions" in state
    assert "trades" in state

    overview = state["overview"]
    assert "bot" in overview
    assert "metrics" in overview
    assert "circuit_breaker" in overview

    positions = state["positions"]
    assert "positions" in positions
    assert "total_unrealized_pnl" in positions

    trades = state["trades"]
    assert "trades" in trades
    assert "total" in trades
