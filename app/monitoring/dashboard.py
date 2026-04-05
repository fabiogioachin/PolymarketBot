"""Dashboard data endpoints — wired to live engine state."""

import asyncio
import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.core.dependencies import (
    get_bot_service,
    get_circuit_breaker,
    get_execution_engine,
    get_market_service,
    get_risk_manager,
)
from app.core.yaml_config import app_config

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/overview")
async def get_overview() -> dict:  # type: ignore[type-arg]
    """Dashboard overview: bot status + key metrics + circuit breaker."""
    svc = await get_bot_service()
    st = svc.status()
    rm = get_risk_manager()
    cb = get_circuit_breaker()
    engine = await get_execution_engine()

    cb_state = cb.state
    balance = await engine._executor.get_balance()

    return {
        "bot": {
            "running": st.running,
            "mode": st.mode,
            "tick_count": st.tick_count,
        },
        "metrics": {
            "total_trades": len(engine.trade_log),
            "daily_pnl": round(rm.daily_pnl, 2),
            "win_rate": _win_rate(engine.trade_log),
            "open_positions": rm.position_count,
            "equity": round(balance.total, 2),
        },
        "circuit_breaker": {
            "tripped": cb_state.is_tripped,
            "reason": cb_state.reason,
            "consecutive_losses": cb_state.consecutive_losses,
            "daily_drawdown_pct": cb_state.daily_drawdown_pct,
        },
    }


@router.get("/config")
async def get_config() -> dict:  # type: ignore[type-arg]
    """Get current configuration for dashboard display."""
    return {
        "strategies": {
            "enabled": app_config.strategies.enabled,
            "domain_filters": app_config.strategies.domain_filters,
        },
        "risk": {
            "max_exposure_pct": app_config.risk.max_exposure_pct,
            "max_single_position_eur": app_config.risk.max_single_position_eur,
            "daily_loss_limit_eur": app_config.risk.daily_loss_limit_eur,
            "fixed_fraction_pct": app_config.risk.fixed_fraction_pct,
            "max_positions": app_config.risk.max_positions,
        },
        "valuation": {
            "weights": app_config.valuation.weights.model_dump(),
            "thresholds": app_config.valuation.thresholds.model_dump(),
        },
        "intelligence": {
            "gdelt_enabled": app_config.intelligence.gdelt.enabled,
            "rss_enabled": app_config.intelligence.rss.enabled,
        },
        "llm": {
            "enabled": app_config.llm.enabled,
            "triggers": app_config.llm.triggers,
            "model": app_config.llm.model,
        },
    }


@router.get("/equity")
async def get_equity_history() -> dict:  # type: ignore[type-arg]
    """Get equity curve data from trade log."""
    engine = await get_execution_engine()
    balance = await engine._executor.get_balance()
    return {"equity_curve": [], "starting_capital": 150.0, "current": round(balance.total, 2)}


@router.get("/trades")
async def get_trade_log() -> dict:  # type: ignore[type-arg]
    """Get recent trade log from engine."""
    engine = await get_execution_engine()
    trades = engine.trade_log
    # Return last 50 trades, most recent first
    recent = list(reversed(trades[-50:]))
    return {"trades": recent, "total": len(trades)}


@router.get("/strategies")
async def get_strategy_performance() -> dict:  # type: ignore[type-arg]
    """Get per-strategy performance from trade log."""
    engine = await get_execution_engine()
    trades = engine.trade_log

    by_strategy: dict[str, dict] = {}  # type: ignore[type-arg]
    for t in trades:
        name = str(t.get("strategy", "unknown"))
        if name not in by_strategy:
            by_strategy[name] = {"trades": 0, "total_edge": 0.0}
        by_strategy[name]["trades"] += 1
        by_strategy[name]["total_edge"] += float(t.get("edge", 0) or 0)

    return {
        "strategies": [
            {"name": k, "trades": v["trades"], "avg_edge": round(v["total_edge"] / v["trades"], 4)}
            for k, v in by_strategy.items()
            if v["trades"] > 0
        ]
    }


@router.get("/positions")
async def get_positions() -> dict:  # type: ignore[type-arg]
    """Get detailed open positions with entry metadata from trade log."""
    result, total_pnl = await _build_positions()
    return {"positions": result, "total_unrealized_pnl": total_pnl}


@router.get("/stream")
async def stream_dashboard() -> StreamingResponse:
    """SSE endpoint: pushes full dashboard state after every engine tick."""

    async def event_generator():  # type: ignore[no-untyped-def]
        last_tick = -1
        while True:
            engine = await get_execution_engine()
            current_tick = engine.tick_count
            if current_tick != last_tick:
                last_tick = current_tick
                data = await _build_full_state()
                yield f"data: {json.dumps(data)}\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── helpers ──────────────────────────────────────────────────────────────


async def _build_positions() -> tuple[list[dict[str, object]], float]:
    """Build detailed position list enriched with live market data.

    Returns (positions_list, total_unrealized_pnl).
    """
    engine = await get_execution_engine()
    market_svc = get_market_service()
    positions = await engine._executor.get_positions()
    trade_log = engine.trade_log

    # Build market_id -> entry info lookup from open trades
    entry_info: dict[str, dict[str, object]] = {}
    for t in trade_log:
        if t.get("type") == "open":
            entry_info[str(t.get("market_id", ""))] = {
                "strategy": t.get("strategy", ""),
                "edge": t.get("edge", 0),
                "reasoning": t.get("reasoning", ""),
                "opened_at": t.get("timestamp", ""),
            }

    result: list[dict[str, object]] = []
    for pos in positions:
        entry = entry_info.get(pos.market_id, {})

        # Fetch live market data for rich display
        question = ""
        end_date = ""
        category = ""
        volume = 0.0
        volume_24h = 0.0
        resolution_source = ""
        outcome_name = ""
        try:
            market = await market_svc.get_market(pos.market_id)
            question = market.question
            end_date = market.end_date.isoformat() if market.end_date else ""
            category = market.category.value
            volume = market.volume
            volume_24h = market.volume_24h
            if market.resolution_rules and market.resolution_rules.source:
                resolution_source = market.resolution_rules.source
            # Which outcome token is this position on?
            for o in market.outcomes:
                if o.token_id == pos.token_id:
                    outcome_name = o.outcome
                    break
        except Exception:
            pass

        # Build human-readable decision
        decision = f"{pos.side} {outcome_name}" if outcome_name else str(pos.side)

        result.append({
            "token_id": pos.token_id[:16] + "...",
            "market_id": pos.market_id,
            "question": question,
            "category": category,
            "end_date": end_date,
            "side": str(pos.side),
            "outcome": outcome_name,
            "decision": decision,
            "size": round(pos.size, 4),
            "avg_price": round(pos.avg_price, 4),
            "current_price": round(pos.current_price, 4),
            "unrealized_pnl": round(pos.unrealized_pnl, 4),
            "cost_basis": round(pos.size * pos.avg_price, 2),
            "strategy": str(entry.get("strategy", "unknown")),
            "edge_at_entry": round(float(entry.get("edge", 0) or 0), 4),
            "reasoning": str(entry.get("reasoning", ""))[:300],
            "opened_at": str(entry.get("opened_at", "")),
            "volume": round(volume, 0),
            "volume_24h": round(volume_24h, 0),
            "resolution_source": resolution_source[:100],
        })

    total_pnl = round(sum(float(p["unrealized_pnl"]) for p in result), 4)
    return result, total_pnl


async def _build_full_state() -> dict[str, object]:
    """Combine overview + positions + recent trades into one SSE payload."""
    svc = await get_bot_service()
    st = svc.status()
    rm = get_risk_manager()
    cb = get_circuit_breaker()
    engine = await get_execution_engine()

    cb_state = cb.state
    balance = await engine._executor.get_balance()
    trades = engine.trade_log
    recent = await _enrich_trades(list(reversed(trades[-50:])))
    positions_list, total_pnl = await _build_positions()

    return {
        "overview": {
            "bot": {
                "running": st.running,
                "mode": st.mode,
                "tick_count": st.tick_count,
            },
            "metrics": {
                "total_trades": len(trades),
                "daily_pnl": round(rm.daily_pnl, 2),
                "win_rate": _win_rate(trades),
                "open_positions": rm.position_count,
                "equity": round(balance.total, 2),
            },
            "circuit_breaker": {
                "tripped": cb_state.is_tripped,
                "reason": cb_state.reason,
                "consecutive_losses": cb_state.consecutive_losses,
                "daily_drawdown_pct": cb_state.daily_drawdown_pct,
            },
        },
        "positions": {
            "positions": positions_list,
            "total_unrealized_pnl": total_pnl,
        },
        "trades": {
            "trades": recent,
            "total": len(trades),
        },
    }


async def _enrich_trades(
    trades: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Add market question to trade entries for display."""
    market_svc = get_market_service()
    cache: dict[str, str] = {}
    enriched = []
    for t in trades:
        mid = str(t.get("market_id", ""))
        if mid not in cache:
            try:
                m = await market_svc.get_market(mid)
                cache[mid] = m.question
            except Exception:
                cache[mid] = ""
        enriched.append({**t, "question": cache[mid]})
    return enriched


def _win_rate(trade_log: list[dict[str, object]]) -> float:
    """Calculate win rate from closed trades. Returns 0.0 if no closes."""
    closes = [t for t in trade_log if t.get("type") == "close"]
    if not closes:
        return 0.0
    wins = sum(1 for t in closes if float(t.get("pnl", 0) or 0) > 0)
    return round(wins / len(closes) * 100, 1)
