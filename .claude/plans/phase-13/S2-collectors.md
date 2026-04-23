# S2 — Platform Data Collectors (trades, popular, leaderboard)

| **Modello consigliato** | **Effort** | **Wave** | **Parallelizzabile con** |
|--------------------------|-----------|----------|---------------------------|
| **Sonnet 4.6** (200K context) | **medio** | W2 | — (standalone, richiede S1 committed) |

**Perché Sonnet 4.6:** scope meccanico — 2 client HTTP con endpoint/schema noti, 2 orchestrator che replicano pattern esistente (`IntelligenceOrchestrator`), 3 tabelle SQLite, 3 endpoint REST. Nessun ragionamento matematico. Context 200K sufficiente per leggere pattern di riferimento + file da modificare.

---

## Obiettivo

Aggiungere 3 client Polymarket (`/trades`, `/leaderboard`, popular markets via Gamma `?order=volume24hr`), `WhaleOrchestrator` + `PopularMarketsOrchestrator` con tick cycle, 3 tabelle SQLite, wiring DI, 3 nuovi endpoint REST.

## Dipendenze

**S1 committed.** `ValuationResult` ha `realized_volatility` (sarà usato da S5b endpoint volatility). Nessuna dipendenza su file S1 per il codice S2.

## File master (LEGGI PRIMA)

- [../00-decisions.md](../00-decisions.md) — specialmente **D4** (criteri whale)

## File da leggere all'avvio

- [app/services/intelligence_orchestrator.py](app/services/intelligence_orchestrator.py) (21-60: pattern constructor + `set_trade_store()` late-binding — REPLICARE IDENTICO)
- [app/core/dependencies.py](app/core/dependencies.py)
- [app/execution/trade_store.py](app/execution/trade_store.py) (19-33 trades, 55-63 intelligence_events)
- [app/execution/engine.py](app/execution/engine.py) (485-520: `_fetch_intelligence_signals` pattern)
- [app/clients/polymarket_rest.py](app/clients/polymarket_rest.py) (pattern httpx client)
- [app/api/v1/intelligence.py](app/api/v1/intelligence.py) (4 endpoint esistenti da PRESERVARE)
- [app/models/intelligence.py](app/models/intelligence.py), [config/config.example.yaml](config/config.example.yaml)
- [.claude/tasks/lessons.md](.claude/tasks/lessons.md) (lesson 2026-04-15 SQLite dict-key vs column)

## Skills / Agenti / MCP

- Skill [.claude/skills/intelligence-source/SKILL.md](.claude/skills/intelligence-source/SKILL.md)
- Skill [.claude/skills/api-dashboard/SKILL.md](.claude/skills/api-dashboard/SKILL.md)
- 2 `backend-specialist` con scope disgiunto (parallelizzabili INTRA-SESSIONE):
  - A: client + orchestrator + trade_store
  - B: API endpoint + DI + engine integration
- `test-writer`, `code-reviewer`

**Codex-First candidate.** I 2 client HTTP sono mecanici (endpoint URL + parsing Pydantic noti): delegare a `codex:rescue --write` in background mentre orchestrator verifica wiring DI.

---

## Step esecutivi

**STEP 1 — `PolymarketTradesClient`.** Nuovo file `app/clients/polymarket_trades.py`:
- `class PolymarketTradesClient(base_url="https://clob.polymarket.com", rate_limit=20)`
- `async fetch_recent_trades(market_id, limit=50) -> list[dict]`: GET `/trades?market={id}&limit={limit}`, timeout 10s, `async with semaphore`.
- `async close()`

In [app/models/intelligence.py](app/models/intelligence.py) aggiungi (preservando `AnomalyReport`):
```python
class WhaleTrade(BaseModel):
    id: str
    timestamp: datetime
    market_id: str
    wallet_address: str       # taker_address
    side: str                 # "BUY" | "SELL"
    size_usd: float
    price: float
    is_pre_resolution: bool = False
    raw_json: str
```

**STEP 2 — `PolymarketLeaderboardClient`.** Nuovo file `app/clients/polymarket_leaderboard.py`:
- `async fetch_leaderboard(timeframe="monthly", limit=100) -> list[dict]` — endpoint ufficiale Polymarket leaderboard.

**STEP 3 — `PopularMarketsOrchestrator`.** Nuovo file `app/services/popular_markets_orchestrator.py`:
- Wrapper Gamma API `/markets?order=volume24hr&active=true&limit=20`
- Costruttore `(trade_store=None)` + metodo `set_trade_store(store)` (pattern IntelligenceOrchestrator late-binding).
- `async tick() -> list[PopularMarket]` + `get_popular_markets()`.
- Cadenza 5 min.

**STEP 4 — `WhaleOrchestrator`.** Nuovo file `app/services/whale_orchestrator.py`:
- Pattern **IDENTICO** a `IntelligenceOrchestrator` (costruttore + `set_trade_store()` late-binding).
- `async tick(markets) -> list[WhaleTrade]`: per market aperto + posizioni → call `fetch_recent_trades` → filtra `size_usd >= whale_threshold` (default $100k) → flag `is_pre_resolution` (trade in 30 min da `resolution_datetime`) → persisti SQLite.
- Cadenza 60s su markets con posizioni, 5 min su top 50 per volume.
- `get_whale_activity(market_id, since_minutes=360) -> list[WhaleTrade]` per VAE consumption (S4b) e API.

**STEP 5 — SQLite schema.** In [app/execution/trade_store.py](app/execution/trade_store.py) aggiungi 3 tabelle (**applicare lesson 2026-04-15**: ALTER TABLE con try/except duplicate-column, dict-keys === column names):

```sql
CREATE TABLE IF NOT EXISTS whale_trades (
    id TEXT PRIMARY KEY,
    timestamp REAL NOT NULL,
    market_id TEXT NOT NULL,
    wallet_address TEXT NOT NULL,
    side TEXT NOT NULL,
    size_usd REAL NOT NULL,
    price REAL NOT NULL,
    is_pre_resolution INTEGER NOT NULL DEFAULT 0,
    raw_json TEXT,
    wallet_total_pnl REAL,      -- populated S3 from subgraph
    wallet_weekly_pnl REAL,     -- populated S3
    wallet_volume_rank INTEGER  -- populated S3
);
CREATE INDEX IF NOT EXISTS idx_whale_trades_market ON whale_trades(market_id, timestamp);

CREATE TABLE IF NOT EXISTS popular_markets_snapshot (
    snapshot_time REAL NOT NULL,
    market_id TEXT NOT NULL,
    volume24h REAL NOT NULL,
    liquidity REAL,
    PRIMARY KEY (snapshot_time, market_id)
);

CREATE TABLE IF NOT EXISTS trader_leaderboard (
    snapshot_time REAL NOT NULL,
    rank INTEGER NOT NULL,
    wallet_address TEXT NOT NULL,
    pnl_usd REAL NOT NULL,
    win_rate REAL,
    timeframe TEXT NOT NULL,
    PRIMARY KEY (snapshot_time, wallet_address, timeframe)
);
```

Aggiungi metodi save/load. **Round-trip test obbligatorio per ogni tabella** (lesson 2026-04-15).

**STEP 6 — DI wiring.** In [app/core/dependencies.py](app/core/dependencies.py):
- `get_whale_orchestrator()` e `get_popular_markets_orchestrator()` singleton.
- In `get_execution_engine()` post `store.init()`: `whale_orch.set_trade_store(store)`, `popular_orch.set_trade_store(store)` (late-binding).

In [app/execution/engine.py](app/execution/engine.py) pattern linee 485-520:
```python
async def _fetch_whale_signals(self, markets):
    await self._whale_orchestrator.tick(markets)
# chiamato in tick() prima di assess_batch
```

**STEP 7 — API endpoint.** In [app/api/v1/intelligence.py](app/api/v1/intelligence.py) AGGIUNGI (preservando i 4 esistenti):
- `GET /intelligence/whales?since=1h&min_size=5000&limit=50` → `list[WhaleTrade]`
- `GET /intelligence/popular-markets?limit=20` → `list[PopularMarket]`
- `GET /intelligence/leaderboard?timeframe=monthly&limit=100` → `list[LeaderboardEntry]`

**STEP 8 — Config.** In [config/config.example.yaml](config/config.example.yaml):
```yaml
intelligence:
  whale:
    enabled: true
    threshold_usd: 100000
    pre_resolution_window_minutes: 30
    tick_interval_seconds: 60
  popular_markets:
    enabled: true
    top_n: 20
    tick_interval_minutes: 5
  leaderboard:
    enabled: true
    tick_interval_minutes: 60
```

**STEP 9 — Tests.** +20-30 test: `tests/test_clients/test_polymarket_trades.py`, `test_polymarket_leaderboard.py` (respx). `tests/test_services/test_whale_orchestrator.py`, `test_popular_markets_orchestrator.py`. `tests/test_execution/test_trade_store.py` round-trip per 3 tabelle.

---

## Verification

```bash
python -m pytest tests/ -q                    # atteso: 720+ pass
python -m ruff check app/ tests/
python -m mypy app/
# Smoke endpoint (richiede docker up):
curl http://localhost:8000/api/v1/intelligence/whales?since=1h
curl http://localhost:8000/api/v1/intelligence/popular-markets?limit=10
curl http://localhost:8000/api/v1/intelligence/leaderboard
```

## Commit message proposto

```
feat(intelligence): Polymarket platform data collectors — whale, popular, leaderboard (Phase 13 S2)

- PolymarketTradesClient + PolymarketLeaderboardClient (httpx, rate-limited)
- WhaleOrchestrator: poll /trades, filter >=$100k, flag pre-resolution
- PopularMarketsOrchestrator: top-20 by volume24h every 5min
- 3 new SQLite tables (whale_trades, popular_markets_snapshot, trader_leaderboard)
- DI wiring with late-binding pattern (IntelligenceOrchestrator precedent)
- 3 new /intelligence/* endpoints preserving existing 4
- Config intelligence.{whale,popular_markets,leaderboard}
- 20+ tests including SQLite round-trip
```

## Handoff a S3

- 3 client + 2 orchestrator wired in DI
- 3 tabelle create e round-trip OK
- 3 endpoint rispondono 200
- 4 endpoint esistenti invariati
- `whale_trades` ha colonne `wallet_total_pnl`, `wallet_weekly_pnl`, `wallet_volume_rank` vuote (S3 le popolerà)
