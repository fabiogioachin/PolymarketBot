# PolymarketBot

Autonomous intelligence and value assessment system for Polymarket prediction markets.

The system continuously assesses whether prediction market prices are mispriced relative to fair value, using multiple independent signals: historical base rates, resolution rules, order book microstructure, cross-market correlations, and an event intelligence pipeline sourced from GDELT and RSS feeds. When mispricing exceeds the minimum edge threshold and confidence is sufficient, a strategy layer generates trading signals that pass through risk management before reaching the execution engine.

---

## Features

- Value Assessment Engine with 7 configurable weighted signals (base rate, rule analysis, microstructure, cross-market, event signal, KG pattern, crowd calibration)
- Intelligence pipeline: GDELT DOC API + RSS feeds + Obsidian Knowledge Graph pattern matching
- 7 trading strategies: value_edge, arbitrage, rule_edge, event_driven, knowledge_driven, sentiment, resolution
- Three execution modes: dry_run (default), shadow, live
- Risk management: fixed fraction (5%) and half-Kelly sizing, max single position 25 EUR, max exposure 50%, daily loss limit 20 EUR
- Circuit breaker: halts trading after 3 consecutive losses or 15% daily drawdown, with 60-minute cooldown
- Backtesting engine with Parquet data pipeline and per-strategy performance reporting
- Telegram alerting for trade events, circuit breaker trips, and daily summaries
- Web dashboard served at `/static/index.html`
- Full REST API at `/api/v1` (see `docs/API-REFERENCE.md`)
- JSON structured logging with rotation (structlog)
- Docker support via `docker/Dockerfile` and `docker/docker-compose.yml`

---

## Quick Start

### Prerequisites

- Python 3.11 or later
- A Polymarket account with CLOB API credentials (for live/shadow mode)
- Obsidian with the Local REST API plugin (for KG features; optional)
- Telegram bot token (for alerts; optional)

### Install

```bash
# Clone the repository
git clone <repo-url>
cd PolyMarket

# Install dependencies
pip install -e ".[dev]"
# or with uv:
uv sync
```

### Configure

1. Copy the example files:

```bash
cp .env.example .env
cp config/config.example.yaml config/config.yaml
```

2. Edit `.env` and fill in your secrets:

```
POLYMARKET_API_KEY=
POLYMARKET_SECRET=
POLYMARKET_PASSPHRASE=
POLYMARKET_FUNDER=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
OBSIDIAN_API_KEY=
ANTHROPIC_API_KEY=
```

3. Review `config/config.yaml`. The most important sections are `execution.mode`, `risk`, and `valuation.weights`. The default mode is `dry_run`.

### Run

```bash
uvicorn app.main:app --reload
```

The API is available at `http://localhost:8000`.
Interactive docs: `http://localhost:8000/docs`.
Dashboard: `http://localhost:8000/static/index.html`.

### Docker

```bash
docker compose -f docker/docker-compose.yml up --build
# Backend API: http://localhost:8000
# Dashboard (via nginx): http://localhost
```

---

## Project Structure

```
app/
  core/           Config (secrets via .env, tunables via config.yaml), logging, DI
  models/         Pydantic v2 data models (market, order, valuation, signal, intelligence)
  clients/        Async HTTP/WS wrappers (Polymarket REST/CLOB/WS, GDELT, RSS, LLM, Telegram)
  services/       Business logic (market scanner, rule parser, intelligence orchestrator)
  valuation/      Value Assessment Engine: fair value from weighted signals
  strategies/     7 trading strategies consuming ValuationResult
  knowledge/      Risk KB (aiosqlite) + Obsidian KG bridge
  risk/           Position sizing (fixed fraction, Kelly), exposure manager, circuit breaker
  execution/      Execution engine loop + dry_run / shadow / live backends
  backtesting/    Parquet data loader, replay simulator, reporter
  monitoring/     Metrics collector, dashboard endpoints, Telegram alerting
  api/v1/         FastAPI routers
  main.py         Application entry point
config/           config.example.yaml
docker/           backend.Dockerfile, frontend.Dockerfile, docker-compose.yml, nginx.conf
static/           Single-page dashboard
scripts/          Data fetch, vault setup, pattern seeding
tests/            Mirrors app/ structure
```

---

## Configuration

Two layers:

- **`.env`** — secrets: API keys and tokens. Never committed. Copy from `.env.example`.
- **`config/config.yaml`** — all tunables: risk limits, valuation signal weights and thresholds, strategy list and domain filters, execution mode, intelligence watchlists, LLM call budget, Telegram alert rules. Copy from `config/config.example.yaml`.

In-memory runtime overrides to the YAML config are available via `PUT /api/v1/config/triggers` and `PUT /api/v1/config/alerts`. These reset on restart. To reset manually: `POST /api/v1/config/reset`.

---

## Running Tests

```bash
pytest
```

With coverage:

```bash
pytest --cov=app --cov-report=term-missing
```

Linting:

```bash
ruff check .
ruff format --check .
```

Type checking:

```bash
mypy app/
```

Tests use `pytest-asyncio` (auto mode), `respx` for HTTP client mocking, and real aiosqlite in-memory databases. No mocked databases.

---

## API Endpoints

A brief summary. For full request/response schemas, see `docs/API-REFERENCE.md`.

| Method | Path                                    | Description                                  |
|--------|-----------------------------------------|----------------------------------------------|
| GET    | /api/v1/health                          | Health check                                 |
| GET    | /api/v1/markets                         | List markets with filters                    |
| GET    | /api/v1/markets/{id}                    | Get market + applicable strategies           |
| GET    | /api/v1/markets/{id}/rules              | Get parsed resolution rules                  |
| GET    | /api/v1/knowledge/market/{id}           | Get market risk profile from KB              |
| PUT    | /api/v1/knowledge/market/{id}/notes     | Add/update note for a market                 |
| GET    | /api/v1/knowledge/strategies            | List strategies and their market counts      |
| GET    | /api/v1/knowledge/risks                 | List risk profiles, optionally filtered      |
| POST   | /api/v1/intelligence/enrich             | On-demand topic enrichment                   |
| GET    | /api/v1/intelligence/anomalies          | Recent anomaly reports                       |
| GET    | /api/v1/intelligence/watchlist          | Current GDELT watchlist                      |
| GET    | /api/v1/bot/status                      | Bot status                                   |
| POST   | /api/v1/bot/start                       | Start bot                                    |
| POST   | /api/v1/bot/stop                        | Stop bot                                     |
| POST   | /api/v1/bot/mode/{mode}                 | Set execution mode                           |
| POST   | /api/v1/backtest/run                    | Run backtest                                 |
| GET    | /api/v1/backtest/{id}                   | Get backtest result                          |
| GET    | /api/v1/dashboard/overview              | Dashboard overview metrics                   |
| GET    | /api/v1/dashboard/config                | Runtime configuration snapshot              |
| GET    | /api/v1/dashboard/equity                | Equity curve                                 |
| GET    | /api/v1/dashboard/trades                | Trade log                                    |
| GET    | /api/v1/dashboard/strategies            | Per-strategy performance                     |
| GET    | /api/v1/config                          | Full config (LLM + alerts)                   |
| GET    | /api/v1/config/triggers                 | LLM trigger config                           |
| PUT    | /api/v1/config/triggers                 | Update LLM trigger config                    |
| GET    | /api/v1/config/alerts                   | Alert config                                 |
| PUT    | /api/v1/config/alerts                   | Update alert config                          |
| POST   | /api/v1/config/reset                    | Reset overrides to YAML defaults             |

---

## Architecture

For a full description of the system design, data flow, component roles, signal weights, and strategy descriptions, see `docs/ARCHITECTURE.md`.

---

## Risk Parameters

Designed for a capital range of 100-200 EUR.

| Parameter                  | Value          |
|----------------------------|----------------|
| Position sizing method     | Fixed fraction |
| Fraction per trade         | 5%             |
| Max single position        | 25 EUR         |
| Max total exposure         | 50% of capital |
| Daily loss limit           | 20 EUR         |
| Circuit breaker: losses    | 3 consecutive  |
| Circuit breaker: drawdown  | 15%            |
| Cooldown after trip        | 60 minutes     |

All parameters are configurable under `risk` in `config/config.yaml`.

---

## License

MIT
