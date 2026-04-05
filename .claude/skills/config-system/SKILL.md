---
name: config-system
description: >
  Dual configuration system (env vars + YAML), dependency injection, and service wiring.
  Use when adding new config parameters, modifying DI wiring, debugging config loading,
  or understanding how secrets vs behavior settings are separated.
---

# Configuration & Dependency Injection

## Dual Config System

| Layer | File | What | Access | Hot-reload |
|-------|------|------|--------|------------|
| **Secrets/env** | `app/core/config.py` | API keys, tokens, runtime flags | `from app.core.config import settings` | No |
| **Behavior/YAML** | `app/core/yaml_config.py` | All trading behavior | `from app.core.yaml_config import app_config` | `reload_config()` |

**Rule:** Secrets and credentials → `.env`. Everything else → `config.yaml`.

## Environment Variables (`.env`)

```bash
# Polymarket API (required for live trading)
POLYMARKET_API_KEY=
POLYMARKET_SECRET=
POLYMARKET_PASSPHRASE=
POLYMARKET_FUNDER=

# Telegram alerts (optional)
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# Obsidian vault (optional, for KG)
OBSIDIAN_API_KEY=
OBSIDIAN_API_URL=http://127.0.0.1:27123

# LLM (optional)
ANTHROPIC_API_KEY=

# Runtime
APP_ENV=development
LOG_LEVEL=INFO
DRY_RUN=true
```

Loaded by `pydantic-settings` (`BaseSettings` with `env_file=".env"`).

## YAML Configuration

Loaded from `config/config.yaml`, falls back to `config/config.example.yaml`,
then falls back to pure Pydantic defaults (everything works with zero config).

### Full Model Hierarchy

```
AppConfig
├── app: AppMeta (name, version, env, log_level, dry_run)
├── polymarket: PolymarketConfig (base_url, clob_url, ws_url, rate_limit, retry)
├── execution: ExecutionConfig (mode, tick_interval_seconds, shadow_mode)
├── risk: RiskConfig
│   ├── max_exposure_pct, max_single_position_eur, daily_loss_limit_eur
│   ├── fixed_fraction_pct, max_positions
│   └── circuit_breaker: CircuitBreakerConfig
├── valuation: ValuationConfig
│   ├── tick_interval_seconds
│   ├── weights: WeightsConfig (9 signals, sum = 1.0)
│   └── thresholds: ThresholdsConfig (min_edge, min_confidence, strong_edge)
├── intelligence: IntelligenceConfig
│   ├── gdelt: GdeltConfig (enabled, poll_interval, watchlist)
│   ├── rss: RssConfig (enabled, poll_interval, feeds list)
│   ├── obsidian: ObsidianKgConfig (vault_path, patterns_path, enabled)
│   └── manifold: ManifoldConfig (enabled, rate_limit, thresholds)
├── strategies: StrategiesConfig (enabled list, domain_filters dict)
├── telegram: TelegramAlertConfig (enabled, alert_rules)
└── llm: LlmConfig (enabled, triggers, max_daily_calls, model)
```

### Adding a New Config Section

1. Define Pydantic model in `yaml_config.py`:
```python
class MyConfig(BaseModel):
    enabled: bool = False
    some_param: int = 42
```

2. Add to parent model:
```python
class IntelligenceConfig(BaseModel):
    # ... existing ...
    my_source: MyConfig = Field(default_factory=MyConfig)
```

3. Add to `config/config.example.yaml`:
```yaml
intelligence:
  my_source:
    enabled: false
    some_param: 42
```

4. Access in code:
```python
from app.core.yaml_config import app_config
if app_config.intelligence.my_source.enabled:
    ...
```

## Dependency Injection (`app/core/dependencies.py`)

All services are **lazy singletons** — created on first access, reused thereafter.

Pattern:
```python
_my_service: MyService | None = None

async def get_my_service() -> MyService | None:
    global _my_service
    if not app_config.some.enabled:
        return None
    if _my_service is None:
        from app.services.my_service import MyService
        _my_service = MyService()
    return _my_service
```

### Current Singletons

| Accessor | Returns | Async? |
|----------|---------|--------|
| `get_market_service()` | `MarketService` | No |
| `get_risk_kb()` | `RiskKnowledgeBase` | Yes |
| `get_risk_manager()` | `RiskManager` | No |
| `get_circuit_breaker()` | `CircuitBreaker` | No |
| `get_strategy_registry()` | `StrategyRegistry` | No |
| `get_value_engine()` | `ValueAssessmentEngine` | Yes |
| `get_manifold_service()` | `ManifoldService | None` | Yes |
| `get_execution_engine()` | `ExecutionEngine` | Yes |
| `get_bot_service()` | `BotService` | Yes |

**Wiring order matters:** `get_execution_engine()` calls `get_value_engine()`,
`get_manifold_service()`, `get_risk_manager()`, etc. The DI graph is implicit.

### Import Pattern

All service imports are **inside the function body** (not at module top level)
to avoid circular imports:

```python
async def get_value_engine() -> ValueAssessmentEngine:
    if _value_engine is None:
        from app.valuation.db import ResolutionDB       # lazy import
        from app.valuation.engine import ValueAssessmentEngine
        ...
```

## Runtime Config Overrides

`PUT /api/v1/config/triggers` and `PUT /api/v1/config/alerts` modify in-memory state
only — changes are lost on restart. For persistent changes, edit the YAML file and call
`POST /api/v1/config/reset` (which calls `reload_config()`).

## Key Files

| File | Purpose |
|------|---------|
| `app/core/config.py` | `settings` — env vars via pydantic-settings |
| `app/core/yaml_config.py` | `app_config` — YAML behavior config |
| `app/core/dependencies.py` | Lazy singleton DI wiring |
| `config/config.example.yaml` | Default YAML config |
| `.env.example` | Template for environment variables |
