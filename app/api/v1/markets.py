"""Market API endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.core.dependencies import get_market_service
from app.models.market import Market, MarketCategory
from app.services.market_service import MarketService
from app.services.rule_parser import RuleAnalysis, RuleParser

router = APIRouter()

_rule_parser = RuleParser()

ServiceDep = Annotated[MarketService, Depends(get_market_service)]


class MarketListResponse(BaseModel):
    markets: list[Market]
    count: int


class MarketWithAnalysis(BaseModel):
    market: Market
    strategies: list[str]


@router.get("/markets", response_model=MarketListResponse)
async def list_markets(
    service: ServiceDep,
    active: bool = True,
    limit: Annotated[int, Query(le=500)] = 100,
    min_liquidity: float = 0.0,
    min_volume: float = 0.0,
    category: MarketCategory | None = None,
) -> MarketListResponse:
    """List markets with optional filters."""
    markets = await service.get_markets(
        active=active,
        limit=limit,
        min_liquidity=min_liquidity,
        min_volume=min_volume,
        category=category,
    )
    return MarketListResponse(markets=markets, count=len(markets))


@router.get("/markets/{market_id}", response_model=MarketWithAnalysis)
async def get_market(
    market_id: str,
    service: ServiceDep,
) -> MarketWithAnalysis:
    """Get a single market with applicable strategies."""
    try:
        market = await service.get_market(market_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    strategies = service.scanner.get_strategies_for_market(market)
    return MarketWithAnalysis(market=market, strategies=strategies)


@router.get("/markets/{market_id}/rules", response_model=RuleAnalysis)
async def get_market_rules(
    market_id: str,
    service: ServiceDep,
) -> RuleAnalysis:
    """Get parsed and analyzed resolution rules for a market."""
    try:
        market = await service.get_market(market_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return _rule_parser.analyze(market)
