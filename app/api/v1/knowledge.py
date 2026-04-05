"""Knowledge base API endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.dependencies import get_risk_kb
from app.knowledge.risk_kb import MarketKnowledge, RiskKnowledgeBase, RiskLevel

router = APIRouter()

KBDep = Annotated[RiskKnowledgeBase, Depends(get_risk_kb)]


class NoteRequest(BaseModel):
    note: str


class StrategyListItem(BaseModel):
    strategy: str
    market_count: int
    market_ids: list[str]


class RiskSummaryItem(BaseModel):
    market_id: str
    risk_level: RiskLevel
    risk_reason: str
    strategy_applied: str


@router.get("/knowledge/market/{market_id}", response_model=MarketKnowledge)
async def get_market_knowledge(
    market_id: str,
    kb: KBDep,
) -> MarketKnowledge:
    """Get complete knowledge profile for a market."""
    record = await kb.get(market_id)
    if record is None:
        raise HTTPException(
            status_code=404, detail=f"No knowledge for market {market_id}"
        )
    return record


@router.put("/knowledge/market/{market_id}/notes")
async def add_market_note(
    market_id: str,
    request: NoteRequest,
    kb: KBDep,
) -> dict:
    """Add or update notes for a market."""
    success = await kb.add_note(market_id, request.note)
    if not success:
        raise HTTPException(
            status_code=404,
            detail=f"Market {market_id} not in knowledge base",
        )
    return {"status": "ok", "market_id": market_id}


@router.get("/knowledge/strategies", response_model=list[StrategyListItem])
async def list_strategies(
    kb: KBDep,
) -> list[StrategyListItem]:
    """Get all active strategies with their market counts."""
    all_records = await kb.get_all()
    strategy_map: dict[str, list[str]] = {}
    for record in all_records:
        if record.strategy_applied:
            strategy_map.setdefault(record.strategy_applied, []).append(
                record.market_id
            )
    return [
        StrategyListItem(strategy=s, market_count=len(ids), market_ids=ids)
        for s, ids in sorted(strategy_map.items())
    ]


@router.get("/knowledge/risks", response_model=list[RiskSummaryItem])
async def list_risks(
    level: RiskLevel | None = None,
    *,
    kb: KBDep,
) -> list[RiskSummaryItem]:
    """Get risk profiles for all tracked markets."""
    records = (
        await kb.get_by_risk_level(level) if level else await kb.get_all()
    )
    return [
        RiskSummaryItem(
            market_id=r.market_id,
            risk_level=r.risk_level,
            risk_reason=r.risk_reason,
            strategy_applied=r.strategy_applied,
        )
        for r in records
    ]
