# PolymarketBot — Project Conventions

## Stack
- Python 3.11+, FastAPI, async/await everywhere
- Pydantic v2 for all models and settings
- httpx for HTTP, websockets for WS
- structlog for logging (JSON format)
- SQLite for runtime data (risk KB, resolutions, trades)
- Obsidian KG for knowledge persistence
- scikit-learn for TF-IDF market matching (Manifold)

## Code Style
- ruff for linting + formatting (line-length=100)
- mypy strict mode
- Type hints on all public functions
- Async by default — sync only when forced by library

## Architecture
- `app/core/` — config, logging, dependencies (DI wiring)
- `app/models/` — Pydantic models (data, not logic)
- `app/clients/` — external API wrappers (Polymarket, Manifold, GDELT, RSS, Telegram, LLM)
- `app/services/` — business logic orchestration (bot, market, manifold, knowledge, intelligence, news)
- `app/valuation/` — Value Assessment Engine (CORE) — 11 weighted signals
- `app/strategies/` — trading strategies (7 strategies, use valuation output)
- `app/knowledge/` — risk KB + Obsidian bridge + pattern templates
- `app/risk/` — position sizing, circuit breaker, risk manager
- `app/execution/` — order execution (dry/live/shadow), position monitor, trade store
- `app/backtesting/` — backtest engine, simulator, data loader, reporter
- `app/monitoring/` — metrics, alerting (Telegram), dashboard (SSE)
- `app/api/v1/` — FastAPI routes (health, markets, bot, dashboard, config, backtest, intelligence, knowledge)
- `config/` — YAML configuration (config.example.yaml, no config.yaml in repo)
- `scripts/` — standalone scripts (ingest, calibration, vault setup, seed patterns)
- `static/` — dark-theme SPA dashboard (vanilla JS)
- `tests/` — mirrors app/ structure, 870+ tests

## Project Structure (`.claude/`)
- `.claude/tasks/todo.md` — canonical project task tracker (Phase 0-10)
- `.claude/tasks/lessons.md` — lessons learned across sessions (8 active entries)
- `.claude/skills/` — 9 project skills (see Skills section below)

## Conventions
- Config: secrets in .env (Pydantic Settings), tunables in config.yaml
- All API clients: async, with rate limiting (semaphore or token bucket)
- Execution modes: dry_run (default), shadow, live
- Never mock data — use respx for HTTP mocking in tests
- Test file naming: test_{module}.py mirroring app/ path
- Imports: absolute from app root (e.g., `from app.core.config import settings`)
- Strategies return `Signal | list[Signal] | None` (multi-leg trades like arbitrage return lists)
- Signal must always carry `market_price` — engine uses it for orders, not edge_amount
- All singletons wired in `app/core/dependencies.py` — register new services there (includes IntelligenceOrchestrator)
- Position exits handled by `app/execution/position_monitor.py` (TP/SL/expiry/edge-evaporated)
- External signals from satellite sources injected via `assess_batch(external_signals=...)` — generic dict pattern, no per-source modifications to assess_batch needed
- Manifold integration disabled by default (`intelligence.manifold.enabled: false`) — enable in config.yaml
- `Market.time_horizon` is a computed field (SHORT/MEDIUM/LONG) based on `end_date`
- Risk checks accept optional `time_horizon` for per-horizon pool enforcement; `None` skips pool check (backward compat)
- Near-resolution positions (`mark_near_resolution()`) count at 50% for exposure calculations
- Tick cycle sorts signals by priority score (`edge / days_to_resolution`) before execution

## VAE Signals (11, nominal sum 1.10, effective ~1.00 w/ Manifold off — validator accepts [0.95, 1.15])
| Signal | Weight | Source |
|--------|--------|--------|
| base_rate | 0.15 | ResolutionDB historical priors |
| rule_analysis | 0.15 | Rule parser clarity score |
| microstructure | 0.15 | Orderbook/price history |
| cross_market | 0.10 | Correlated Polymarket markets |
| event_signal | 0.15 | GDELT + RSS intelligence |
| pattern_kg | 0.10 | Obsidian KG patterns |
| cross_platform | 0.10 | Manifold Markets divergence (0 when disabled) |
| temporal | 0.05 | Time-to-resolution decay |
| crowd_calibration | 0.05 | Historical crowd bias |
| whale_pressure | 0.05 | Polymarket whale trades (event-style, indep. prob) |
| insider_pressure | 0.05 | Pre-resolution suspicious trades (microstructure-style, ±0.05 on market_price) |

## Skills (9 project-specific)
| Skill | Purpose |
|-------|---------|
| `strategy-authoring` | Create/register/test trading strategies |
| `execution-modes` | Tick cycle, dry_run/shadow/live, position management |
| `risk-tuning` | Risk parameters, position sizing, circuit breaker |
| `intelligence-source` | Add new data sources to the intelligence pipeline |
| `vae-signal` | Add new signals to the Value Assessment Engine |
| `manifold-satellite` | Manifold Markets integration specifics |
| `backtesting` | Historical data, backtest engine, result interpretation |
| `api-dashboard` | REST endpoints, SSE stream, dashboard |
| `config-system` | Dual config (env + YAML), DI, reload |

## Testing
- pytest + pytest-asyncio (auto mode)
- respx for HTTP client mocking
- No mocked databases — use real SQLite in-memory for tests
- Minimum: every public function has at least one test
- Test helpers: `_make_market()`, `_make_valuation()` factory patterns

## Risk Parameters (100-200 EUR capital)
- Fixed fraction: 5% per trade
- Max exposure: 50%
- Daily loss limit: 15% of equity (was fixed 20 EUR, now equity-relative)
- Max single position: 5% of equity
- Circuit breaker: 3 consecutive losses OR 15% drawdown
- Max concurrent positions: 25
- Horizon budget pools: 60% short / 30% medium / 10% long (of max_exposure)
- Min edge per horizon: 3% short / 5% medium / 10% long
- Near-resolution discount: 50% (positions < 24h + prob > 0.90)
