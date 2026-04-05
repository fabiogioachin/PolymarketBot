---
name: api-dashboard
description: >
  FastAPI endpoints, dashboard SSE stream, and runtime config API. Use when adding
  new endpoints, modifying the dashboard, debugging API responses, or working with
  the real-time SSE data stream.
---

# API & Dashboard

## Route Structure

All routes under `/api/v1` prefix. Router assembled in `app/api/v1/router.py`.

### Core Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/health` | Health check |
| `GET` | `/markets` | List filtered markets |
| `GET` | `/markets/{id}` | Single market detail |
| `GET` | `/markets/{id}/rules` | Parsed resolution rules |

### Bot Control

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/bot/status` | Running state, mode, tick count, P&L |
| `POST` | `/bot/start` | Start the trading loop |
| `POST` | `/bot/stop` | Stop the trading loop |
| `POST` | `/bot/mode/{mode}` | Switch mode: `dry_run`, `shadow`, `live` |

### Intelligence

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/intelligence/enrich` | On-demand deep-dive enrichment |
| `GET` | `/intelligence/anomalies` | Recent anomaly reports |
| `GET` | `/intelligence/watchlist` | GDELT watchlist config |

### Knowledge

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/knowledge/market/{id}` | KG context for a market |
| `PUT` | `/knowledge/market/{id}/notes` | Add notes to market KG entry |
| `GET` | `/knowledge/strategies` | Strategy metadata |
| `GET` | `/knowledge/risks` | Risk KB entries |

### Dashboard (real-time)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/dashboard/overview` | Summary: equity, P&L, positions, CB status |
| `GET` | `/dashboard/config` | Current config snapshot |
| `GET` | `/dashboard/equity` | Equity curve data points |
| `GET` | `/dashboard/trades` | Trade log (with human-readable decisions) |
| `GET` | `/dashboard/strategies` | Per-strategy metrics |
| `GET` | `/dashboard/positions` | Open positions with live data |
| `GET` | `/dashboard/stream` | **SSE stream** — real-time updates |

### Runtime Config

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/config/triggers` | LLM trigger config |
| `PUT` | `/config/triggers` | Update LLM triggers (in-memory) |
| `GET` | `/config/alerts` | Alert rules |
| `PUT` | `/config/alerts` | Update alert rules (in-memory) |
| `GET` | `/config` | Full config snapshot |
| `POST` | `/config/reset` | Reload from disk |

### Backtesting

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/backtest/run` | Run backtest (placeholder) |
| `GET` | `/backtest/{id}` | Get backtest results |

## SSE Stream

`GET /dashboard/stream` sends Server-Sent Events. The stream polls `engine.tick_count`
every 1 second and pushes a combined JSON payload on state change:

```json
{
  "overview": { "equity": 150.0, "daily_pnl": 0.0, ... },
  "positions": [ { "market_id": "...", "question": "...", ... } ],
  "trades": [ { "timestamp": "...", "market_id": "...", ... } ]
}
```

Connect from browser: `new EventSource("/api/v1/dashboard/stream")`

Positions are enriched with live market data (question, category, end_date, volume).

## Adding a New Endpoint

### 1. Create or edit route file

`app/api/v1/my_routes.py`:
```python
from fastapi import APIRouter
router = APIRouter()

@router.get("/my-endpoint")
async def my_endpoint():
    return {"status": "ok"}
```

### 2. Include in router

In `app/api/v1/router.py`:
```python
from app.api.v1.my_routes import router as my_router
api_v1_router.include_router(my_router)
```

### 3. Use DI for services

```python
from app.core.dependencies import get_bot_service

@router.get("/my-endpoint")
async def my_endpoint():
    bot = await get_bot_service()
    return bot.status()
```

## Static Frontend

`static/index.html` + `static/js/app.js` — vanilla JS dashboard that consumes the SSE
stream and REST endpoints. Served by FastAPI static files mount.

## Key Files

| File | Purpose |
|------|---------|
| `app/api/v1/router.py` | Route aggregation |
| `app/api/v1/bot.py` | Bot control endpoints |
| `app/api/v1/dashboard.py` | Dashboard data endpoints |
| `app/monitoring/dashboard.py` | SSE stream + position enrichment |
| `app/main.py` | FastAPI app + static mount |
| `static/` | Frontend HTML/JS/CSS |
