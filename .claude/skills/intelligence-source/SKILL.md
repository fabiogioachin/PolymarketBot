---
name: intelligence-source
description: >
  Add or modify intelligence data sources (GDELT, RSS, Manifold, or new ones).
  Use when integrating a new external data feed, modifying polling behavior,
  or extending the intelligence pipeline. Covers clients, services, and VAE wiring.
---

# Intelligence Sources

## Architecture

```
External APIs → Clients (app/clients/) → Services (app/services/) → VAE signals
                                       → Obsidian KG (persistence)
```

The intelligence pipeline runs on two tracks:
1. **IntelligenceOrchestrator** — periodic polling (GDELT + RSS), produces `event_signal`
2. **ManifoldService** — periodic polling, produces `cross_platform_signal`

Both feed the VAE as float signals (0-1).

## Current Sources

| Source | Client | Service | VAE Signal | Weight |
|--------|--------|---------|-----------|--------|
| GDELT | `gdelt_client.py` | `gdelt_service.py` | `event_signal` | 0.15 |
| RSS feeds | `rss_client.py` | `news_service.py` | (via event_signal) | — |
| Institutional | `institutional_client.py` | `news_service.py` | (via event_signal) | — |
| Manifold | `manifold_client.py` | `manifold_service.py` | `cross_platform_signal` | 0.10 |
| Obsidian KG | `obsidian_bridge.py` | `knowledge_service.py` | `pattern_kg_signal` | 0.10 |

## Step-by-Step: Add a New Intelligence Source

### 1. Create the API client

`app/clients/my_client.py` — follow `gdelt_client.py` pattern:
```python
class MyClient:
    def __init__(self, rate_limit: int = 5, max_retries: int = 3, backoff: float = 2.0):
        self._client: httpx.AsyncClient | None = None
        self._semaphore = asyncio.Semaphore(rate_limit)
        self._max_retries = max_retries
        self._backoff = backoff

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(base_url="...", timeout=30.0)
        return self._client

    async def _request(self, path: str, params: dict) -> dict | list:
        # Rate limiting + retry with exponential backoff
        ...

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
```

### 2. Create data models (if needed)

`app/models/my_source.py` — Pydantic v2 models with `Field(alias=...)` for API fields.

### 3. Create the service

`app/services/my_service.py` — orchestrates the client, produces a signal float:
```python
class MyService:
    def __init__(self, client: MyClient):
        self._client = client

    async def get_signal(self, market: Market) -> float | None:
        # Fetch data, compute signal, return 0-1 float
        ...
```

### 4. Add configuration

In `app/core/yaml_config.py`, create a config model and add to `IntelligenceConfig`:
```python
class MySourceConfig(BaseModel):
    enabled: bool = False
    poll_interval_minutes: int = 30

class IntelligenceConfig(BaseModel):
    # ... existing ...
    my_source: MySourceConfig = Field(default_factory=MySourceConfig)
```

### 5. Wire into VAE

See the `vae-signal` skill for the complete 7-step process. Key points:
- Add `my_signal: float | None = None` to `assess()` and `ValuationInput`
- Add weight to `WeightsConfig` (rebalance to sum ~1.0)
- Add computation block in `_compute_fair_value()`

### 6. Wire into execution engine

In `app/execution/engine.py`, add signal fetching in `tick()` (step 2b area):
```python
if self._my_service is not None:
    my_signals = await self._fetch_my_signals(markets, now)
    external_signals = merge(external_signals, my_signals)
```

Use the `external_signals` dict to forward per-market signals to `assess_batch()`.

### 7. Wire into DI

In `app/core/dependencies.py`:
```python
async def get_my_service() -> MyService | None:
    if not app_config.intelligence.my_source.enabled:
        return None
    client = MyClient(rate_limit=app_config.intelligence.my_source.rate_limit)
    return MyService(client)
```

Pass to `ExecutionEngine` in `get_execution_engine()`.

## Intelligence Orchestrator

`app/services/intelligence_orchestrator.py` handles GDELT + RSS polling:

```python
async def tick() -> AnomalyReport | None:
    # 1. Poll GDELT watchlist
    # 2. Fetch RSS + institutional news
    # 3. Match KG patterns for each event
    # 4. Write significant events to Obsidian
    # 5. Return AnomalyReport
```

`get_event_signal(domain) -> float` returns 0-1 based on max relevance score.

## Key Files

| File | Purpose |
|------|---------|
| `app/services/intelligence_orchestrator.py` | Periodic polling coordinator |
| `app/services/enrichment_service.py` | On-demand deep-dive by topic |
| `app/services/news_service.py` | RSS + institutional aggregation |
| `app/services/manifold_service.py` | Cross-platform matching + signals |
| `app/services/knowledge_service.py` | Obsidian KG pattern matching |
