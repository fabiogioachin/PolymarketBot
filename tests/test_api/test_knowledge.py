"""Tests for the knowledge API endpoints — debug endpoint."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

import app.core.dependencies as deps_module
from app.core.dependencies import get_risk_kb
from app.main import app
from app.services.intelligence_orchestrator import IntelligenceOrchestrator


@pytest.fixture
async def client() -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture(autouse=True)
def _mock_risk_kb() -> None:
    """Override get_risk_kb via FastAPI dependency_overrides.

    Cannot monkeypatch `deps_module.get_risk_kb` because KBDep in
    app.api.v1.knowledge captured the original reference at import time via
    `Annotated[..., Depends(get_risk_kb)]`.
    """
    mock_kb = AsyncMock()
    mock_kb.get_all = AsyncMock(return_value=[])

    async def _fake_get_risk_kb() -> AsyncMock:
        return mock_kb

    app.dependency_overrides[get_risk_kb] = _fake_get_risk_kb
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_risk_kb, None)


@pytest.fixture(autouse=True)
def _mock_intel_orch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provide a fake IntelligenceOrchestrator."""
    orch = IntelligenceOrchestrator(
        gdelt_service=AsyncMock(),
        news_service=AsyncMock(),
        knowledge_service=AsyncMock(),
    )
    monkeypatch.setattr(deps_module, "_intelligence_orchestrator", orch)


class TestKnowledgeDebug:
    @pytest.mark.asyncio
    async def test_debug_returns_all_fields(self, client: AsyncClient) -> None:
        """Endpoint returns the expected diagnostic fields."""
        with patch("app.api.v1.knowledge.httpx.AsyncClient") as mock_httpx:
            # Simulate Obsidian unreachable
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(side_effect=ConnectionError)
            mock_httpx.return_value = mock_ctx

            response = await client.get("/api/v1/knowledge/debug")

        assert response.status_code == 200
        data = response.json()

        assert "risk_kb_rows" in data
        assert "obsidian_enabled" in data
        assert "obsidian_reachable" in data
        assert "pattern_folders" in data
        assert "pattern_counts" in data
        assert "last_intelligence_tick" in data
        assert "anomaly_history_length" in data

    @pytest.mark.asyncio
    async def test_debug_risk_kb_rows(self, client: AsyncClient) -> None:
        """risk_kb_rows reflects the number of KB records."""
        response = await client.get("/api/v1/knowledge/debug")
        assert response.status_code == 200
        data = response.json()
        assert data["risk_kb_rows"] == 0

    @pytest.mark.asyncio
    async def test_debug_pattern_folders(self, client: AsyncClient) -> None:
        """pattern_folders contains the known domains."""
        response = await client.get("/api/v1/knowledge/debug")
        data = response.json()
        expected = [
            "politics", "geopolitics", "economics",
            "crypto", "sports", "science",
        ]
        assert data["pattern_folders"] == expected

    @pytest.mark.asyncio
    async def test_debug_intel_no_tick(self, client: AsyncClient) -> None:
        """last_intelligence_tick is null when no tick has run."""
        response = await client.get("/api/v1/knowledge/debug")
        data = response.json()
        assert data["last_intelligence_tick"] is None
        assert data["anomaly_history_length"] == 0
