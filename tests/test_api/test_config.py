"""Tests for the configuration CRUD API endpoints."""

import pytest
from httpx import ASGITransport, AsyncClient

import app.api.v1.config as config_module
from app.main import app


@pytest.fixture(autouse=True)
def clear_overrides() -> None:
    """Clear in-memory override dicts before and after each test to avoid pollution."""
    config_module._llm_overrides.clear()
    config_module._alert_overrides.clear()
    yield
    config_module._llm_overrides.clear()
    config_module._alert_overrides.clear()


@pytest.fixture
async def client() -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_get_full_config_returns_structure(client: AsyncClient) -> None:
    """GET /config returns FullConfig with llm and alerts keys."""
    response = await client.get("/api/v1/config")
    assert response.status_code == 200
    data = response.json()
    assert "llm" in data
    assert "alerts" in data
    assert "llm_enabled" in data["llm"]
    assert "triggers" in data["llm"]
    assert "telegram_enabled" in data["alerts"]
    assert "rules" in data["alerts"]


@pytest.mark.asyncio
async def test_get_triggers_returns_defaults(client: AsyncClient) -> None:
    """GET /config/triggers returns default LLM config from yaml_config."""
    response = await client.get("/api/v1/config/triggers")
    assert response.status_code == 200
    data = response.json()
    assert data["llm_enabled"] is False
    assert set(data["triggers"]) == {"anomaly", "new_market", "daily_digest"}
    assert data["max_daily_calls"] == 20
    assert data["model"] == "claude-sonnet-4-6"


@pytest.mark.asyncio
async def test_put_triggers_updates_overrides(client: AsyncClient) -> None:
    """PUT /config/triggers persists the in-memory override."""
    payload = {
        "llm_enabled": True,
        "triggers": ["anomaly", "manual_request"],
        "max_daily_calls": 50,
        "model": "claude-sonnet-4-6",
    }
    put_resp = await client.put("/api/v1/config/triggers", json=payload)
    assert put_resp.status_code == 200
    assert put_resp.json()["llm_enabled"] is True

    # Verify the override is visible via GET
    get_resp = await client.get("/api/v1/config/triggers")
    assert get_resp.status_code == 200
    data = get_resp.json()
    assert data["llm_enabled"] is True
    assert data["max_daily_calls"] == 50
    assert set(data["triggers"]) == {"anomaly", "manual_request"}


@pytest.mark.asyncio
async def test_put_triggers_rejects_invalid_trigger(client: AsyncClient) -> None:
    """PUT /config/triggers returns 400 for an unrecognised trigger type."""
    payload = {
        "llm_enabled": True,
        "triggers": ["anomaly", "nonexistent_trigger"],
        "max_daily_calls": 20,
        "model": "claude-sonnet-4-6",
    }
    response = await client.put("/api/v1/config/triggers", json=payload)
    assert response.status_code == 400
    assert "nonexistent_trigger" in response.json()["detail"]


@pytest.mark.asyncio
async def test_get_alerts_returns_default_rules(client: AsyncClient) -> None:
    """GET /config/alerts returns default alert rules from yaml_config."""
    response = await client.get("/api/v1/config/alerts")
    assert response.status_code == 200
    data = response.json()
    assert data["telegram_enabled"] is False
    rule_types = {r["type"] for r in data["rules"]}
    assert "trade_executed" in rule_types
    assert "circuit_breaker" in rule_types
    assert "daily_summary" in rule_types


@pytest.mark.asyncio
async def test_put_alerts_updates_overrides(client: AsyncClient) -> None:
    """PUT /config/alerts persists the in-memory override."""
    payload = {
        "telegram_enabled": True,
        "rules": [
            {"type": "trade_executed", "enabled": True, "min_edge": 0.05},
            {"type": "circuit_breaker", "enabled": False},
        ],
    }
    put_resp = await client.put("/api/v1/config/alerts", json=payload)
    assert put_resp.status_code == 200
    assert put_resp.json()["telegram_enabled"] is True

    # Verify the override is visible via GET
    get_resp = await client.get("/api/v1/config/alerts")
    assert get_resp.status_code == 200
    data = get_resp.json()
    assert data["telegram_enabled"] is True
    assert len(data["rules"]) == 2


@pytest.mark.asyncio
async def test_post_reset_clears_overrides(client: AsyncClient) -> None:
    """POST /config/reset wipes all in-memory overrides."""
    # Apply an override first
    await client.put(
        "/api/v1/config/triggers",
        json={
            "llm_enabled": True,
            "triggers": ["anomaly"],
            "max_daily_calls": 99,
            "model": "claude-sonnet-4-6",
        },
    )

    reset_resp = await client.post("/api/v1/config/reset")
    assert reset_resp.status_code == 200
    body = reset_resp.json()
    assert body["status"] == "reset"


@pytest.mark.asyncio
async def test_get_triggers_after_reset_returns_defaults(client: AsyncClient) -> None:
    """After POST /config/reset, GET /config/triggers returns YAML defaults."""
    # Apply override
    await client.put(
        "/api/v1/config/triggers",
        json={
            "llm_enabled": True,
            "triggers": ["manual_request"],
            "max_daily_calls": 99,
            "model": "claude-sonnet-4-6",
        },
    )

    # Reset
    await client.post("/api/v1/config/reset")

    # Verify defaults are restored
    get_resp = await client.get("/api/v1/config/triggers")
    assert get_resp.status_code == 200
    data = get_resp.json()
    assert data["llm_enabled"] is False
    assert data["max_daily_calls"] == 20
    assert set(data["triggers"]) == {"anomaly", "new_market", "daily_digest"}
