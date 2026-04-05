# Architecture

## System Overview

PolymarketBot is an autonomous intelligence and value assessment system for Polymarket prediction markets. The system is built around a single design principle: **price mispricing is independent of news**. A market can be mispriced with no active events, and well-covered events can already be fully priced in. The Value Assessment Engine (VAE) therefore stands at the core of every decision, synthesizing multiple independent signals into a single fair-value estimate before any strategy or execution logic runs.

The overall data flow is:

```
External Data Sources
    |-- Polymarket REST/CLOB/WS
    |-- GDELT DOC API
    |-- RSS Feeds (Reuters, AP, BBC, Al Jazeera)
    |-- Institutional feeds
          |
          v
   Intelligence Pipeline
   (GDELT Service + News Service + KG Pattern Matching)
          |
          v
  Value Assessment Engine     <-- Obsidian KG (pattern signal)
  (7 weighted signals -> fair value, edge, confidence)
          |
          v
   Strategy Layer (7 strategies)
          |
          v
   Risk Manager (position sizing, exposure checks)
          |
          v
   Circuit Breaker (consecutive losses / drawdown guard)
          |
          v
   Execution Engine (dry_run | shadow | live)
          |
          v
   Order Executor -> Polymarket CLOB
```

---

## Component Descriptions

### `app/core/`

Application foundation. `config.py` loads secrets from `.env` using Pydantic Settings (`PolymarketSettings`, `TelegramSettings`, `ObsidianSettings`, `Settings`). `yaml_config.py` loads all tunables (risk limits, valuation weights, strategy list, intelligence watchlists) from `config/config.yaml` into typed Pydantic models. `logging.py` configures structlog for JSON output with rotation. `dependencies.py` provides FastAPI dependency functions (`get_market_service`, `get_risk_kb`, etc.).

### `app/models/`

Pure Pydantic v2 data models with no business logic.

- `market.py` — `Market`, `MarketOutcome`, `OrderBook`, `PriceHistory`, `MarketCategory`
- `order.py` — `OrderRequest`, `OrderResult`, `OrderSide`, `OrderStatus`
- `valuation.py` — `ValuationInput`, `ValuationResult`, `EdgeSource`, `Recommendation`
- `signal.py` — `Signal`, `SignalType`
- `intelligence.py` — `GdeltEvent`, `NewsItem`, `AnomalyReport`
- `knowledge.py` — `MarketKnowledge`, `PatternMatch`

### `app/clients/`

All external API wrappers. Every client is async, uses httpx for HTTP and websockets for WS, and implements retry with exponential backoff and per-client rate limiting.

- `polymarket_rest.py` — Polymarket Gamma REST API (market listings, prices)
- `polymarket_clob.py` — CLOB API (`py-clob-client` wrapper: order placement, book data)
- `polymarket_ws.py` — WebSocket subscriptions for live price feeds
- `gdelt_client.py` — GDELT DOC API (volume queries, article fetch)
- `rss_client.py` — RSS/Atom feed polling via `feedparser`
- `institutional_client.py` — Institutional data aggregator
- `llm_client.py` — Anthropic Claude API (optional enrichment, gated by `llm.enabled`)
- `telegram_client.py` — Telegram Bot API for alerts (`python-telegram-bot`)

### `app/services/`

Business logic orchestration layer. Services compose clients and models; they do not contain raw HTTP calls.

- `market_service.py` — Fetches, filters, and caches market data
- `market_scanner.py` — Selects applicable strategies per market based on domain and filters
- `rule_parser.py` — Parses resolution rule text, produces `RuleAnalysis` (rule clarity score)
- `gdelt_service.py` — Polls GDELT watchlist, detects volume/tone anomalies
- `news_service.py` — Polls all RSS feeds, scores relevance
- `knowledge_service.py` — Reads/writes patterns and events to the Obsidian KG
- `intelligence_orchestrator.py` — Runs one full intelligence cycle: GDELT + RSS + KG pattern matching -> `AnomalyReport`
- `enrichment_service.py` — On-demand topic enrichment (calls LLM if enabled)
- `bot_service.py` — Top-level service wiring the execution engine with all subsystems

### `app/valuation/`

The Value Assessment Engine. This is the most critical module.

- `engine.py` — `ValueAssessmentEngine`: the main class. `assess()` collects signals, calls `_compute_fair_value()`, applies temporal scaling, and returns a `ValuationResult` with recommendation. `assess_batch()` runs concurrent assessment across a market universe with a semaphore limit.
- `base_rate.py` — `BaseRateAnalyzer`: derives a prior probability from historical resolution data in the ResolutionDB
- `crowd_calibration.py` — `CrowdCalibrationAnalyzer`: adjusts for known crowd biases per market category (e.g., overconfidence in extreme probabilities)
- `microstructure.py` — `MicrostructureAnalyzer`: analyzes order book spread, depth, and price momentum to produce a 0-1 activity score
- `cross_market.py` — `CrossMarketAnalyzer`: detects correlated markets in the universe and produces a composite signal
- `temporal.py` — `TemporalAnalyzer`: computes a time-decay factor based on days-to-resolution; scales the edge (not the fair value directly)
- `db.py` — `ResolutionDB`: aiosqlite-backed store of historical resolution outcomes, used by base_rate and crowd_calibration

### Value Engine Signal Weights (from `config.yaml`)

| Signal             | Default Weight | Source                              |
|--------------------|---------------|-------------------------------------|
| base_rate          | 0.15          | ResolutionDB historical outcomes    |
| rule_analysis      | 0.15          | RuleParser clarity score            |
| microstructure     | 0.20          | Order book + price momentum         |
| cross_market       | 0.10          | Correlated market universe          |
| event_signal       | 0.15          | Intelligence pipeline output        |
| pattern_kg         | 0.10          | Obsidian KG pattern match           |
| temporal           | 0.10          | Time-decay edge scaling factor      |
| crowd_calibration  | 0.05          | Category bias adjustment            |

Weights are configurable in `config/config.yaml` under `valuation.weights`. The engine normalizes across the signals that are actually present; missing signals (e.g., `event_signal` when intelligence is disabled) are excluded from the weighted average.

Confidence is computed as the average confidence of contributing sources scaled by coverage (source count / 5). Below `thresholds.min_confidence` (default 0.3), the recommendation is always HOLD.

### Intelligence Pipeline

The intelligence pipeline feeds the `event_signal` and `pattern_kg` inputs to the Value Engine.

```
GdeltService.poll_watchlist()       --> GdeltEvent list (volume ratio, tone shift)
NewsService.fetch_all()             --> NewsItem list (RSS, scored by relevance)
KnowledgeService.match_patterns()   --> PatternMatch list (Obsidian KG lookup)
KnowledgeService.write_event()      --> Writes event note back to Obsidian KG
IntelligenceOrchestrator.tick()     --> AnomalyReport (aggregated)
```

GDELT is polled every 15 minutes against a configurable watchlist of themes (`ELECTION`, `ECON_INFLATION`, `WB_CONFLICT`, etc.) and actor codes (`USA`, `RUS`, `CHN`, `EU`). Anomaly detection is based on the volume ratio (current vs. baseline) and tone shift. RSS feeds are polled every 30 minutes; items scoring above 0.5 relevance are included in the `AnomalyReport`.

### `app/strategies/`

Seven strategies, each extending `base.py::BaseStrategy`. Strategies receive a `Market` and `ValuationResult` and return a `Signal` or None.

- `value_edge.py` — Trades when fee-adjusted edge exceeds `thresholds.min_edge`. Primary strategy; applies to all domains.
- `arbitrage.py` — Detects correlated market price divergences.
- `rule_edge.py` — Trades when rule clarity score indicates a likely resolution direction.
- `event_driven.py` — Activates on high-relevance intelligence events; domain-filtered to politics, geopolitics, economics.
- `knowledge_driven.py` — Uses Obsidian KG pattern matches as entry triggers.
- `sentiment.py` — Analyzes crowd sentiment signals for contrarian or momentum positions.
- `resolution.py` — Targets markets near resolution; domain-filtered to sports, crypto.

`registry.py` manages strategy instantiation and domain-based selection. `strategies.enabled` in `config.yaml` controls which strategies are active.

### `app/risk/`

- `position_sizer.py` — `PositionSizer`: three methods: `fixed_fraction()` (5% of capital), `kelly_criterion()` (half-Kelly, capped), `from_signal()` (confidence-scaled fraction of fixed fraction). All methods apply the max-single-position cap (25 EUR by default).
- `manager.py` — `RiskManager`: wraps position sizer with exposure tracking (max 50% of capital deployed), daily loss accounting, and per-signal risk checks.
- `circuit_breaker.py` — `CircuitBreaker`: trips on 3 consecutive losses OR 15% daily drawdown. After tripping, imposes a 60-minute cooldown before re-enabling trading. Resets daily via `reset_daily()`.

### `app/execution/`

- `engine.py` — `ExecutionEngine`: the main trading loop. Each `tick()` runs: circuit breaker check -> market scan -> batch valuation -> strategy signals -> risk sizing -> order execution. `run()` loops on a configurable interval (default 60 seconds).
- `executor.py` — `OrderExecutor`: dispatches orders to the correct backend based on mode.
- `dry_run.py` — Simulates order fills with no real money; logs all activity.
- `shadow.py` — Places real orders but with 0 size (shadow trading for latency/fill analysis).
- `live.py` — Sends orders to the Polymarket CLOB.

Mode is set via `execution.mode` in `config.yaml` or via the `/api/v1/bot/mode/{mode}` endpoint.

### `app/backtesting/`

- `data_loader.py` — Loads historical market snapshots from Parquet files (written by `scripts/fetch_historical.py`). Produces `BacktestDataset`.
- `simulator.py` — `FillSimulator`: replays market snapshots, applies slippage model, produces `SimulatedFill` records.
- `engine.py` — `BacktestEngine`: drives the replay loop using `BacktestConfig` (starting capital, max positions, slippage_pct). Feeds snapshots through the full strategy + risk pipeline.
- `reporter.py` — Computes performance statistics (Sharpe, max drawdown, win rate, per-strategy breakdown) from `BacktestTrade` records.

Before running a backtest, historical data must be fetched: `python scripts/fetch_historical.py`.

### `app/monitoring/`

- `metrics.py` — `MetricsCollector`: collects tick-level statistics (trades, PnL, win rate, open positions, equity curve).
- `dashboard.py` — FastAPI router (`/api/v1/dashboard/*`) serving aggregated metrics to the web dashboard.
- `alerting.py` — Sends Telegram alerts according to `telegram.alert_rules` (trade executed above min_edge, circuit breaker trips, daily summary).

### `app/knowledge/`

- `risk_kb.py` — `RiskKnowledgeBase`: aiosqlite-backed store of per-market risk profiles (`MarketKnowledge`). Tracks risk level, risk reason, and active strategy.
- `obsidian_bridge.py` — `ObsidianBridge`: bidirectional sync with the Obsidian vault via the Obsidian Local REST API (port 27123). Reads pattern notes from `Projects/PolymarketBot/patterns/`, writes event notes.
- `pattern_templates.py` — Defines the Markdown templates for pattern notes written to the vault.

### `app/api/v1/`

FastAPI routers. Each router corresponds to one domain. See `docs/API-REFERENCE.md` for the full endpoint list.

### `static/`

Single-page dashboard (`index.html`, `css/style.css`, `js/app.js`) served at `/static`. Reads data from `/api/v1/dashboard/*` endpoints.

### `scripts/`

- `fetch_historical.py` — Fetches historical Polymarket data and writes Parquet files for backtesting.
- `setup_vault.py` — Initializes the Obsidian vault folder structure.
- `seed_patterns.py` — Seeds the vault with starter pattern notes.

---

## Configuration

Two configuration layers:

1. **`.env`** — Secrets only: `POLYMARKET_API_KEY`, `POLYMARKET_SECRET`, `POLYMARKET_PASSPHRASE`, `POLYMARKET_FUNDER`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `OBSIDIAN_API_KEY`, `ANTHROPIC_API_KEY`.
2. **`config/config.yaml`** — All tunables: risk limits, valuation weights and thresholds, strategy list, execution mode, intelligence watchlists, LLM settings, Telegram alert rules.

In-memory overrides to the YAML config are supported via the `/api/v1/config` endpoints and persist until the process restarts.

---

## Deployment

Docker deployment uses two containers:

- **backend** (`docker/backend.Dockerfile`): Python 3.11 + uvicorn, serves the API on port 8000.
- **frontend** (`docker/frontend.Dockerfile`): nginx, serves the static dashboard on port 80 and proxies `/api/` to the backend.

Configuration: `docker/docker-compose.yml` with `docker/nginx.conf` for reverse proxy.

For local development without Docker, `uvicorn app.main:app` serves both API and static files (via FastAPI StaticFiles mount). Logs are written in JSON format to `logs/` with rotation.

Default ports: 8000 (backend API), 80 (dashboard via nginx in Docker).
Local dev dashboard: `http://localhost:8000/static/index.html`.
Interactive API docs: `http://localhost:8000/docs`.
