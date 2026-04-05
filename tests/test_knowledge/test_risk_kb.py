"""Tests for the Risk/Strategy Knowledge Base."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.knowledge.risk_kb import MarketKnowledge, RiskKnowledgeBase, RiskLevel


@pytest.fixture
async def kb() -> RiskKnowledgeBase:
    """Provide an in-memory RiskKnowledgeBase for tests."""
    instance = RiskKnowledgeBase(db_path=":memory:")
    await instance.init()
    yield instance
    await instance.close()


def _make_knowledge(
    market_id: str = "mkt-1",
    risk_level: RiskLevel = RiskLevel.MEDIUM,
    risk_reason: str = "some reason",
    strategy_applied: str = "momentum",
    notes: list[str] | None = None,
) -> MarketKnowledge:
    return MarketKnowledge(
        market_id=market_id,
        rule_analysis={"source": "test"},
        risk_level=risk_level,
        risk_reason=risk_reason,
        strategy_applied=strategy_applied,
        strategy_params={"threshold": 0.6},
        notes=notes or [],
    )


@pytest.mark.asyncio
async def test_init_creates_table(kb: RiskKnowledgeBase) -> None:
    """init() succeeds and the table exists."""
    records = await kb.get_all()
    assert records == []


@pytest.mark.asyncio
async def test_upsert_and_get(kb: RiskKnowledgeBase) -> None:
    """Insert a record and retrieve it by market_id."""
    mk = _make_knowledge()
    await kb.upsert(mk)

    result = await kb.get("mkt-1")
    assert result is not None
    assert result.market_id == "mkt-1"
    assert result.risk_level == RiskLevel.MEDIUM
    assert result.risk_reason == "some reason"
    assert result.strategy_applied == "momentum"
    assert result.rule_analysis == {"source": "test"}
    assert result.strategy_params == {"threshold": 0.6}
    assert result.created_at is not None
    assert result.updated_at is not None


@pytest.mark.asyncio
async def test_upsert_updates_existing(kb: RiskKnowledgeBase) -> None:
    """Upserting an existing market_id overwrites fields."""
    await kb.upsert(_make_knowledge(risk_reason="original"))
    await kb.upsert(_make_knowledge(risk_reason="updated", risk_level=RiskLevel.HIGH))

    result = await kb.get("mkt-1")
    assert result is not None
    assert result.risk_reason == "updated"
    assert result.risk_level == RiskLevel.HIGH


@pytest.mark.asyncio
async def test_get_nonexistent_returns_none(kb: RiskKnowledgeBase) -> None:
    """Getting a missing market returns None."""
    result = await kb.get("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_get_all(kb: RiskKnowledgeBase) -> None:
    """get_all returns all inserted records."""
    await kb.upsert(_make_knowledge(market_id="a"))
    await kb.upsert(_make_knowledge(market_id="b"))
    await kb.upsert(_make_knowledge(market_id="c"))

    results = await kb.get_all()
    assert len(results) == 3
    ids = {r.market_id for r in results}
    assert ids == {"a", "b", "c"}


@pytest.mark.asyncio
async def test_get_by_risk_level(kb: RiskKnowledgeBase) -> None:
    """Filtering by risk level returns only matching records."""
    await kb.upsert(_make_knowledge(market_id="low1", risk_level=RiskLevel.LOW))
    await kb.upsert(_make_knowledge(market_id="med1", risk_level=RiskLevel.MEDIUM))
    await kb.upsert(_make_knowledge(market_id="high1", risk_level=RiskLevel.HIGH))
    await kb.upsert(_make_knowledge(market_id="high2", risk_level=RiskLevel.HIGH))

    high = await kb.get_by_risk_level(RiskLevel.HIGH)
    assert len(high) == 2
    assert {r.market_id for r in high} == {"high1", "high2"}

    low = await kb.get_by_risk_level(RiskLevel.LOW)
    assert len(low) == 1
    assert low[0].market_id == "low1"


@pytest.mark.asyncio
async def test_get_by_strategy(kb: RiskKnowledgeBase) -> None:
    """Filtering by strategy returns only matching records."""
    await kb.upsert(_make_knowledge(market_id="a", strategy_applied="momentum"))
    await kb.upsert(_make_knowledge(market_id="b", strategy_applied="mean_reversion"))
    await kb.upsert(_make_knowledge(market_id="c", strategy_applied="momentum"))

    results = await kb.get_by_strategy("momentum")
    assert len(results) == 2
    assert {r.market_id for r in results} == {"a", "c"}

    results = await kb.get_by_strategy("mean_reversion")
    assert len(results) == 1


@pytest.mark.asyncio
async def test_add_note(kb: RiskKnowledgeBase) -> None:
    """add_note appends a note to an existing record."""
    await kb.upsert(_make_knowledge(notes=["first"]))

    success = await kb.add_note("mkt-1", "second")
    assert success is True

    result = await kb.get("mkt-1")
    assert result is not None
    assert result.notes == ["first", "second"]


@pytest.mark.asyncio
async def test_add_note_missing_market(kb: RiskKnowledgeBase) -> None:
    """add_note returns False for a nonexistent market."""
    success = await kb.add_note("nonexistent", "some note")
    assert success is False


@pytest.mark.asyncio
async def test_update_resolution(kb: RiskKnowledgeBase) -> None:
    """update_resolution records the outcome."""
    await kb.upsert(_make_knowledge())

    success = await kb.update_resolution("mkt-1", "yes")
    assert success is True

    result = await kb.get("mkt-1")
    assert result is not None
    assert result.resolution_outcome == "yes"


@pytest.mark.asyncio
async def test_update_resolution_missing_market(kb: RiskKnowledgeBase) -> None:
    """update_resolution returns False for a nonexistent market."""
    success = await kb.update_resolution("nonexistent", "no")
    assert success is False


@pytest.mark.asyncio
async def test_delete(kb: RiskKnowledgeBase) -> None:
    """delete removes a record and returns True; repeat returns False."""
    await kb.upsert(_make_knowledge())

    deleted = await kb.delete("mkt-1")
    assert deleted is True

    result = await kb.get("mkt-1")
    assert result is None

    deleted_again = await kb.delete("mkt-1")
    assert deleted_again is False


@pytest.mark.asyncio
async def test_knowledge_api_endpoints() -> None:
    """Test the FastAPI knowledge endpoints via httpx."""
    from app.core.dependencies import get_risk_kb
    from app.main import app

    # Create a test KB and override the dependency
    test_kb = RiskKnowledgeBase(db_path=":memory:")
    await test_kb.init()

    app.dependency_overrides[get_risk_kb] = lambda: test_kb

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # GET nonexistent market -> 404
            resp = await client.get("/api/v1/knowledge/market/mkt-x")
            assert resp.status_code == 404

            # Seed data via KB directly
            await test_kb.upsert(
                _make_knowledge(
                    market_id="mkt-api",
                    risk_level=RiskLevel.HIGH,
                    risk_reason="volatile",
                    strategy_applied="momentum",
                )
            )

            # GET existing market
            resp = await client.get("/api/v1/knowledge/market/mkt-api")
            assert resp.status_code == 200
            data = resp.json()
            assert data["market_id"] == "mkt-api"
            assert data["risk_level"] == "high"

            # PUT note on existing market
            resp = await client.put(
                "/api/v1/knowledge/market/mkt-api/notes",
                json={"note": "test note"},
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "ok"

            # PUT note on missing market -> 404
            resp = await client.put(
                "/api/v1/knowledge/market/missing/notes",
                json={"note": "x"},
            )
            assert resp.status_code == 404

            # GET strategies
            resp = await client.get("/api/v1/knowledge/strategies")
            assert resp.status_code == 200
            strategies = resp.json()
            assert len(strategies) == 1
            assert strategies[0]["strategy"] == "momentum"
            assert strategies[0]["market_count"] == 1

            # GET risks (unfiltered)
            resp = await client.get("/api/v1/knowledge/risks")
            assert resp.status_code == 200
            risks = resp.json()
            assert len(risks) == 1
            assert risks[0]["risk_level"] == "high"

            # GET risks (filtered)
            resp = await client.get("/api/v1/knowledge/risks?level=low")
            assert resp.status_code == 200
            assert resp.json() == []
    finally:
        app.dependency_overrides.pop(get_risk_kb, None)
        await test_kb.close()
