# API Reference

Base path: `/api/v1`

All responses are JSON. All endpoints are async. Authentication is not currently enforced (internal service).

---

## Health

### GET /api/v1/health

Returns application health and version.

**Response**

```json
{
  "status": "ok",
  "version": "0.1.0",
  "app": "polymarket-bot"
}
```

| Field   | Type   | Description                |
|---------|--------|----------------------------|
| status  | string | Always `"ok"` if running   |
| version | string | App version from config.yaml |
| app     | string | App name from config.yaml  |

---

## Markets

### GET /api/v1/markets

List markets with optional filters.

**Query Parameters**

| Parameter    | Type    | Default | Description                         |
|--------------|---------|---------|-------------------------------------|
| active       | bool    | true    | Return only active markets          |
| limit        | int     | 100     | Max results (hard cap: 500)         |
| min_liquidity| float   | 0.0     | Minimum liquidity in EUR            |
| min_volume   | float   | 0.0     | Minimum volume in EUR               |
| category     | string  | null    | Filter by `MarketCategory` value    |

**Response**

```json
{
  "markets": [ { ...Market } ],
  "count": 42
}
```

---

### GET /api/v1/markets/{market_id}

Get a single market with applicable strategy names.

**Path Parameters**

| Parameter | Type   | Description        |
|-----------|--------|--------------------|
| market_id | string | Polymarket market ID |

**Response**

```json
{
  "market": { ...Market },
  "strategies": ["value_edge", "rule_edge"]
}
```

**Errors**

- `404` — Market not found

---

### GET /api/v1/markets/{market_id}/rules

Get parsed resolution rules for a market.

**Path Parameters**

| Parameter | Type   | Description        |
|-----------|--------|--------------------|
| market_id | string | Polymarket market ID |

**Response** — `RuleAnalysis`

```json
{
  "market_id": "abc123",
  "rule_text": "...",
  "clarity_score": 0.82,
  "resolution_source": "official_results",
  "ambiguity_flags": [],
  "parsed_conditions": []
}
```

**Errors**

- `404` — Market not found

---

## Knowledge

### GET /api/v1/knowledge/market/{market_id}

Get the complete knowledge profile for a market from the Risk KB.

**Path Parameters**

| Parameter | Type   | Description        |
|-----------|--------|--------------------|
| market_id | string | Polymarket market ID |

**Response** — `MarketKnowledge`

```json
{
  "market_id": "abc123",
  "risk_level": "medium",
  "risk_reason": "Thin order book",
  "strategy_applied": "value_edge",
  "notes": "Observed spread compression before resolution",
  "updated_at": "2026-04-05T10:00:00Z"
}
```

**Errors**

- `404` — No knowledge record for this market

---

### PUT /api/v1/knowledge/market/{market_id}/notes

Add or update a free-text note for a market in the Risk KB.

**Path Parameters**

| Parameter | Type   | Description        |
|-----------|--------|--------------------|
| market_id | string | Polymarket market ID |

**Request Body**

```json
{
  "note": "Spread narrowed significantly after announcement."
}
```

**Response**

```json
{
  "status": "ok",
  "market_id": "abc123"
}
```

**Errors**

- `404` — Market not in knowledge base

---

### GET /api/v1/knowledge/strategies

List all active strategies with the count and IDs of markets they are applied to.

**Response**

```json
[
  {
    "strategy": "value_edge",
    "market_count": 15,
    "market_ids": ["abc123", "def456"]
  }
]
```

---

### GET /api/v1/knowledge/risks

Get risk profiles for all tracked markets.

**Query Parameters**

| Parameter | Type   | Default | Description                               |
|-----------|--------|---------|-------------------------------------------|
| level     | string | null    | Filter by risk level: `low`, `medium`, `high` |

**Response**

```json
[
  {
    "market_id": "abc123",
    "risk_level": "high",
    "risk_reason": "Low liquidity",
    "strategy_applied": "resolution"
  }
]
```

---

## Intelligence

### POST /api/v1/intelligence/enrich

Perform on-demand topic enrichment. Calls GDELT and optionally the LLM (if `llm.enabled` is true in config).

**Request Body**

```json
{
  "topic": "US election results",
  "domain": "politics",
  "depth": "standard",
  "timespan": "7d"
}
```

| Field    | Type   | Default    | Description                            |
|----------|--------|------------|----------------------------------------|
| topic    | string | required   | Topic to enrich                        |
| domain   | string | `""`       | Market domain hint                     |
| depth    | string | `"standard"` | Enrichment depth (`standard`, `deep`) |
| timespan | string | `"7d"`     | GDELT query window                     |

**Response** — `EnrichmentResult`

```json
{
  "topic": "US election results",
  "domain": "politics",
  "gdelt_events": [],
  "news_items": [],
  "kg_patterns": [],
  "event_signal": 0.62,
  "summary": "..."
}
```

---

### GET /api/v1/intelligence/anomalies

Get recent anomaly reports from the in-memory history (last 100 ticks).

**Query Parameters**

| Parameter | Type | Default | Description             |
|-----------|------|---------|-------------------------|
| limit     | int  | 10      | Number of reports (max 100) |

**Response** — list of `AnomalyReport`

```json
[
  {
    "detected_at": "2026-04-05T10:00:00Z",
    "events": [ { ...GdeltEvent } ],
    "news_items": [ { ...NewsItem } ],
    "total_anomalies": 3
  }
]
```

---

### GET /api/v1/intelligence/watchlist

Get the current GDELT watchlist configuration (themes, actors, countries).

**Response**

```json
{
  "themes": ["ELECTION", "ECON_INFLATION", "ECON_INTEREST_RATE"],
  "actors": ["USA", "RUS", "CHN", "EU"],
  "countries": ["US", "RU", "CN", "UA", "IL"]
}
```

---

## Bot Control

### GET /api/v1/bot/status

Get current bot status.

**Response**

```json
{
  "running": false,
  "mode": "dry_run",
  "tick_count": 0,
  "message": "Bot service not initialized"
}
```

---

### POST /api/v1/bot/start

Start the trading bot.

**Response**

```json
{
  "status": "started",
  "message": "Bot started"
}
```

---

### POST /api/v1/bot/stop

Stop the trading bot.

**Response**

```json
{
  "status": "stopped",
  "message": "Bot stopped"
}
```

---

### POST /api/v1/bot/mode/{mode}

Set the execution mode.

**Path Parameters**

| Parameter | Type   | Description                            |
|-----------|--------|----------------------------------------|
| mode      | string | One of: `dry_run`, `shadow`, `live`    |

**Response**

```json
{
  "mode": "dry_run",
  "message": "Mode set"
}
```

**Errors**

- `400` — Invalid mode value

---

## Backtest

### POST /api/v1/backtest/run

Run a backtest. Requires historical Parquet data (see `scripts/fetch_historical.py`).

**Request Body**

```json
{
  "starting_capital": 150.0,
  "max_positions": 10,
  "slippage_pct": 0.005,
  "data_prefix": ""
}
```

| Field            | Type   | Default | Description                              |
|------------------|--------|---------|------------------------------------------|
| starting_capital | float  | 150.0   | Starting capital in EUR                  |
| max_positions    | int    | 10      | Max concurrent open positions            |
| slippage_pct     | float  | 0.005   | Slippage model (0.5% default)            |
| data_prefix      | string | `""`    | Prefix filter for Parquet file selection |

**Response**

```json
{
  "status": "not_available",
  "message": "Backtest requires historical data. Use scripts/fetch_historical.py first.",
  "config": { ...BacktestRequest }
}
```

---

### GET /api/v1/backtest/{backtest_id}

Get a backtest result by ID.

**Path Parameters**

| Parameter   | Type   | Description  |
|-------------|--------|--------------|
| backtest_id | string | Backtest run ID |

**Response**

```json
{
  "status": "not_found",
  "backtest_id": "run-001",
  "message": "Backtest storage not yet implemented"
}
```

---

## Dashboard

### GET /api/v1/dashboard/overview

Dashboard overview: bot status and key performance metrics.

**Response**

```json
{
  "bot": {
    "running": false,
    "mode": "dry_run",
    "tick_count": 0
  },
  "metrics": {
    "total_trades": 0,
    "daily_pnl": 0.0,
    "win_rate": 0.0,
    "open_positions": 0,
    "equity": 150.0
  },
  "circuit_breaker": {
    "tripped": false
  }
}
```

---

### GET /api/v1/dashboard/config

Get current runtime configuration (strategies, risk limits, valuation weights, intelligence flags, LLM settings).

**Response**

```json
{
  "strategies": {
    "enabled": ["value_edge", "rule_edge"],
    "domain_filters": {}
  },
  "risk": {
    "max_exposure_pct": 50,
    "max_single_position_eur": 25,
    "daily_loss_limit_eur": 20,
    "fixed_fraction_pct": 5,
    "max_positions": 10
  },
  "valuation": {
    "weights": { "base_rate": 0.15, "microstructure": 0.20, "..." : "..." },
    "thresholds": { "min_edge": 0.05, "min_confidence": 0.3, "strong_edge": 0.15 }
  },
  "intelligence": {
    "gdelt_enabled": true,
    "rss_enabled": true
  },
  "llm": {
    "enabled": false,
    "triggers": ["anomaly", "new_market"],
    "model": "claude-sonnet-4-6"
  }
}
```

---

### GET /api/v1/dashboard/equity

Get equity curve data.

**Response**

```json
{
  "equity_curve": [],
  "starting_capital": 150.0
}
```

---

### GET /api/v1/dashboard/trades

Get the recent trade log.

**Response**

```json
{
  "trades": [],
  "total": 0
}
```

---

### GET /api/v1/dashboard/strategies

Get per-strategy performance statistics.

**Response**

```json
{
  "strategies": []
}
```

---

## Configuration

### GET /api/v1/config

Get the full runtime configuration (LLM triggers + alert rules).

**Response**

```json
{
  "llm": {
    "llm_enabled": false,
    "triggers": ["anomaly", "new_market", "daily_digest"],
    "max_daily_calls": 20,
    "model": "claude-sonnet-4-6"
  },
  "alerts": {
    "telegram_enabled": false,
    "rules": [
      { "type": "trade_executed", "enabled": true, "min_edge": 0.10 }
    ]
  }
}
```

---

### GET /api/v1/config/triggers

Get current LLM trigger configuration (merges YAML defaults with in-memory overrides).

**Response** — `TriggerConfig`

```json
{
  "llm_enabled": false,
  "triggers": ["anomaly", "new_market", "daily_digest"],
  "max_daily_calls": 20,
  "model": "claude-sonnet-4-6"
}
```

---

### PUT /api/v1/config/triggers

Update LLM trigger configuration. Changes are in-memory and reset on restart.

**Request Body** — `TriggerConfig`

```json
{
  "llm_enabled": true,
  "triggers": ["anomaly"],
  "max_daily_calls": 5,
  "model": "claude-sonnet-4-6"
}
```

Valid trigger values: `anomaly`, `new_market`, `daily_digest`, `manual_request`.

**Response** — echoes the updated `TriggerConfig`.

**Errors**

- `400` — Invalid trigger value

---

### GET /api/v1/config/alerts

Get current Telegram alert configuration.

**Response** — `AlertConfig`

```json
{
  "telegram_enabled": false,
  "rules": [
    { "type": "trade_executed", "enabled": true, "min_edge": 0.10 },
    { "type": "circuit_breaker", "enabled": true, "min_edge": null },
    { "type": "daily_summary", "enabled": true, "min_edge": null }
  ]
}
```

---

### PUT /api/v1/config/alerts

Update Telegram alert configuration. Changes are in-memory and reset on restart.

**Request Body** — `AlertConfig`

```json
{
  "telegram_enabled": true,
  "rules": [
    { "type": "trade_executed", "enabled": true, "min_edge": 0.08 }
  ]
}
```

**Response** — echoes the updated `AlertConfig`.

---

### POST /api/v1/config/reset

Reset all in-memory configuration overrides to the YAML defaults.

**Response**

```json
{
  "status": "reset",
  "message": "Config reset to YAML defaults"
}
```
