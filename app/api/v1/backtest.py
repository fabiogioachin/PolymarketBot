"""Backtest API endpoints."""

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/backtest", tags=["backtest"])


class BacktestRequest(BaseModel):
    """Request body for a backtest run."""

    starting_capital: float = 150.0
    max_positions: int = 10
    slippage_pct: float = 0.005
    data_prefix: str = ""


@router.post("/run")
async def run_backtest(request: BacktestRequest) -> dict:
    """Run a backtest. Returns placeholder until data pipeline is connected."""
    return {
        "status": "not_available",
        "message": "Backtest requires historical data. Use scripts/fetch_historical.py first.",
        "config": request.model_dump(),
    }


@router.get("/{backtest_id}")
async def get_backtest_result(backtest_id: str) -> dict:
    """Get backtest result by ID. Placeholder endpoint."""
    return {
        "status": "not_found",
        "backtest_id": backtest_id,
        "message": "Backtest storage not yet implemented",
    }
