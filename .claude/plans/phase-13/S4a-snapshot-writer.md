# S4a — Snapshot Writer (contratto dati DSS)

| **Modello consigliato** | **Effort** | **Wave** | **Parallelizzabile con** |
|--------------------------|-----------|----------|---------------------------|
| **Sonnet 4.6** (200K context) | **medio** | W4 | **S4b** (scope file disgiunti) |

**Perché Sonnet 4.6:** schema JSON Pydantic + atomic write + Docker Compose extend. Specs chiare (cadenza, formato, size cap). Nessun ragionamento matematico.

**Parallelizzazione con S4b:** scope file completamente disgiunto (S4a crea file NUOVI in `app/services/`, `app/models/`, `docker/`; S4b modifica `app/valuation/engine.py`, `app/core/yaml_config.py`, `app/execution/engine.py`). Solo overlap è `config/config.example.yaml` che riceve sezioni diverse (merge trivial).

---

## Obiettivo

Creare `snapshot_writer.py` che scrive `static/dss/intelligence_snapshot.json` ogni 5 min con ultimo stato VAE/risk/intelligence. Definire lo **schema JSON = contratto dati** per S5a (il DSS artifact legge questo file). Estendere `docker-compose.yml` con 2 profili (`full`, `dss-only`).

## Dipendenze

**S2 + S3 committed.** Dati whale/popular/leaderboard disponibili. S1 idealmente committed (per accesso a `realized_volatility`).

## File master

- [../00-decisions.md](../00-decisions.md) — **D5** (Docker split architettura)

## File da leggere all'avvio

- [app/services/intelligence_orchestrator.py](app/services/intelligence_orchestrator.py) (pattern tick cycle)
- [app/execution/trade_store.py](app/execution/trade_store.py), [app/execution/engine.py](app/execution/engine.py)
- [app/valuation/engine.py](app/valuation/engine.py) (estrarre ultimo ValuationResult per market)
- [app/core/dependencies.py](app/core/dependencies.py), [app/models/](app/models/)
- [docker/docker-compose.yml](docker/docker-compose.yml), [docker/nginx.conf](docker/nginx.conf)

## Skills / Agenti / MCP

- Skill [.claude/skills/api-dashboard/SKILL.md](.claude/skills/api-dashboard/SKILL.md)
- Skill [.claude/skills/execution-modes/SKILL.md](.claude/skills/execution-modes/SKILL.md)
- Agente `backend-specialist`, `test-writer`

---

## Step esecutivi

**STEP 1 — Modelli JSON.** Nuovo file `app/models/dss_snapshot.py`:
```python
class DSSSnapshotMarket(BaseModel):
    market_id: str
    question: str
    market_price: float
    fair_value: float | None
    edge_central: float | None
    edge_lower: float | None
    edge_dynamic: float | None
    realized_volatility: float | None
    has_open_position: bool
    recommendation: str | None  # BUY|SELL|HOLD

class DSSSnapshotWhale(BaseModel):
    timestamp: datetime
    market_id: str
    wallet_address: str
    side: str
    size_usd: float
    is_pre_resolution: bool
    wallet_total_pnl: float | None

class DSSSnapshot(BaseModel):
    generated_at: datetime
    config_version: str
    weights: dict[str, float]
    volatility_config: dict[str, float]
    # STATELESS — no history arrays (charts fetchano da CLOB)
    monitored_markets: list[DSSSnapshotMarket]   # top 50 + posizioni
    recent_whales: list[DSSSnapshotWhale]        # top 50 ultimi 6h
    recent_insiders: list[DSSSnapshotWhale]      # insider ultimi 24h (se S4b committed)
    popular_markets_top20: list[dict]
    leaderboard_top50: list[dict]
    open_positions: list[dict]
    risk_state: dict  # {exposure_pct, circuit_breaker_open, daily_pnl}
```

**STEP 2 — `SnapshotWriter`.** Nuovo file `app/services/snapshot_writer.py`:
- `class SnapshotWriter(engine, whale_orch, popular_orch, trade_store, output_path)` con `set_*()` late-binding
- `async tick() -> None`: build `DSSSnapshot`, scrive **atomicamente** su `output_path` (write temp file + `os.replace` per evitare reader legga JSON parziale — Windows-safe).
- Cadenza 5 min, avviato da `ExecutionEngine.tick()` come `intelligence_orchestrator`.
- `output_path` default = `Path("static/dss/intelligence_snapshot.json")`.

**STEP 3 — DI wiring.** In [app/core/dependencies.py](app/core/dependencies.py): `get_snapshot_writer()` singleton, wired nel grafo. Chiamato da `engine.tick()` DOPO `assess_batch()` e `whale_orchestrator.tick()`.

**STEP 4 — Docker profili.** In [docker/docker-compose.yml](docker/docker-compose.yml) aggiungi `profiles:` ai servizi esistenti e nuovo servizio:
```yaml
services:
  backend:
    profiles: ["full"]
    # ... existing
  frontend:
    profiles: ["full"]
    ports: ["5174:80"]
    # ... existing (mantieni invariata)
  frontend-dss:
    profiles: ["full", "dss-only"]
    image: nginx:alpine
    ports: ["5175:80"]
    volumes:
      - ../static/dss:/usr/share/nginx/html:ro
      - ./nginx-dss.conf:/etc/nginx/nginx.conf:ro
    restart: unless-stopped
```

Crea [docker/nginx-dss.conf](docker/nginx-dss.conf) minimale:
- `Cache-Control: no-store` su HTML/JS/CSS
- Cache 5min su `.json`
- CORS aperto (Access-Control-Allow-Origin: *) per cross-origin fetch

**STEP 5 — Config.** In [config/config.example.yaml](config/config.example.yaml):
```yaml
dss:
  snapshot_writer:
    enabled: true
    output_path: "static/dss/intelligence_snapshot.json"
    tick_interval_minutes: 5
```

**STEP 6 — Tests.** `tests/test_services/test_snapshot_writer.py`:
- Schema JSON valido `DSSSnapshot`
- Atomic write (verify temp file cleanup post-success, permane post-failure)
- Snapshot size <200KB con 50 markets + 50 whales (Opus cap check per localStorage limit)
- Tick cycle integration (mock engine state → verify file created)

---

## Verification

```bash
python -m pytest tests/test_services/test_snapshot_writer.py -v
# Integration manuale
python -c "
from app.services.snapshot_writer import SnapshotWriter
# ... init engine dry_run, run tick, check file
"
ls -la static/dss/intelligence_snapshot.json
python -c "import json; d=json.load(open('static/dss/intelligence_snapshot.json')); print(d['generated_at'])"

# Docker profile test
docker compose --profile dss-only up -d
curl http://localhost:5175/intelligence_snapshot.json
docker compose --profile dss-only down
```

## Commit message proposto

```
feat(dss): snapshot writer for Decision Support System (Phase 13 S4a)

- DSSSnapshot model (stateless, shallow — no history arrays, <200KB)
- SnapshotWriter tick every 5min, atomic file write (temp + os.replace)
- docker-compose profiles: full (backend+dashboard+dss) / dss-only (nginx alone)
- New frontend-dss service on port 5175, nginx:alpine with CORS open
- DI wiring with late-binding pattern
- 6+ tests including atomic write + size cap verification
```

## Handoff a S5a

- Snapshot JSON generato <200KB (verify `ls -la`)
- Schema validato via Pydantic
- Profile `dss-only` serve snapshot anche con backend Python giù
- File `docker/nginx-dss.conf` pronto (CORS aperto, cache corretta)
- S5a può ora fare fetch `./intelligence_snapshot.json` dal suo HTML
