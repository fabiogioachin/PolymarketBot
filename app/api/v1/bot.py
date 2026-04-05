"""Bot control API endpoints."""

from fastapi import APIRouter, HTTPException

from app.core.dependencies import get_bot_service
from app.core.yaml_config import app_config

router = APIRouter(prefix="/bot", tags=["bot"])


@router.get("/status")
async def get_status() -> dict[str, object]:
    """Get bot status."""
    svc = await get_bot_service()
    st = svc.status()
    return {
        "running": st.running,
        "mode": st.mode,
        "tick_count": st.tick_count,
        "started_at": st.started_at.isoformat() if st.started_at else None,
        "positions": st.positions,
        "daily_pnl": st.daily_pnl,
        "circuit_breaker_tripped": st.circuit_breaker_tripped,
    }


@router.post("/start")
async def start_bot() -> dict[str, str]:
    """Start the trading bot."""
    svc = await get_bot_service()
    if svc.status().running:
        return {"status": "already_running"}
    interval = app_config.execution.tick_interval_seconds
    await svc.start(interval_seconds=interval)
    return {"status": "started", "mode": svc.status().mode}


@router.post("/stop")
async def stop_bot() -> dict[str, str]:
    """Stop the trading bot."""
    svc = await get_bot_service()
    await svc.stop()
    return {"status": "stopped"}


@router.post("/mode/{mode}")
async def set_mode(mode: str) -> dict[str, str]:
    """Set execution mode."""
    if mode not in ("dry_run", "shadow", "live"):
        raise HTTPException(status_code=400, detail=f"Invalid mode: {mode}")
    svc = await get_bot_service()
    svc.set_mode(mode)
    return {"mode": mode, "status": "updated"}
