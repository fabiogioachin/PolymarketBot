# PolymarketBot — Project Conventions

## Stack
- Python 3.11+, FastAPI, async/await everywhere
- Pydantic v2 for all models and settings
- httpx for HTTP, websockets for WS
- structlog for logging (JSON format)
- SQLite for runtime data (risk KB, resolutions)
- Obsidian KG for knowledge persistence

## Code Style
- ruff for linting + formatting (line-length=100)
- mypy strict mode
- Type hints on all public functions
- Async by default — sync only when forced by library

## Architecture
- `app/core/` — config, logging, dependencies
- `app/models/` — Pydantic models (data, not logic)
- `app/clients/` — external API wrappers (httpx/ws)
- `app/services/` — business logic orchestration
- `app/valuation/` — Value Assessment Engine (CORE)
- `app/strategies/` — trading strategies (use valuation output)
- `app/knowledge/` — risk KB + Obsidian bridge
- `app/risk/` — position sizing, circuit breaker
- `app/execution/` — order execution (dry/live/shadow)
- `app/api/v1/` — FastAPI routes
- `config/` — YAML configuration
- `tests/` — mirrors app/ structure

## Conventions
- Config: secrets in .env (Pydantic Settings), tunables in config.yaml
- All API clients: async, with token bucket rate limiting
- Execution modes: dry_run (default), shadow, live
- Never mock data — use respx for HTTP mocking in tests
- Test file naming: test_{module}.py mirroring app/ path
- Imports: absolute from app root (e.g., `from app.core.config import settings`)
- Strategies return `Signal | list[Signal] | None` (multi-leg trades like arbitrage return lists)
- Signal must always carry `market_price` — engine uses it for orders, not edge_amount
- All singletons wired in `app/core/dependencies.py` — register new services there
- Position exits handled by `app/execution/position_monitor.py` (TP/SL/expiry/edge-evaporated)

## Testing
- pytest + pytest-asyncio (auto mode)
- respx for HTTP client mocking
- No mocked databases — use real SQLite in-memory for tests
- Minimum: every public function has at least one test

## Risk Parameters (100-200 EUR capital)
- Fixed fraction: 5% per trade
- Max exposure: 50%
- Daily loss limit: 20 EUR
- Circuit breaker: 3 consecutive losses OR 15% drawdown
