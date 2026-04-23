# Phase 13 — Master Decisions & Execution Plan

> **Fonte di verità condivisa.** Ogni sessione S1→S5b legge questo file PRIMA del proprio piano.
> Decisioni consolidate dopo iterazione utente + review Codex + review Opus.

---

## Context

Il bot PolymarketBot ha tre limiti strutturali che bloccano la generazione di edge reale:

1. **Edge statico su prezzo volatile.** `edge = (fair_value - market_price) * temporal_factor - fee_rate` è scalare. Nessun aggiustamento per la volatilità realizzata. Su un market che oscilla ±5%/h un edge di 3% è rumore; sullo stesso market a vol 0.3% è alpha. Oggi il bot li tratta uguale ([app/valuation/engine.py](app/valuation/engine.py)).

2. **Cieco sulla piattaforma.** Legge orderbook e price-history, ma non sa chi compra/vende (no trade tape), quali sono i mercati gettonati (no top-by-volume24h ranking), chi sono i top trader, né riconosce pattern pre-resolution sospetti. Tutto free-tier pubblico lasciato sul tavolo.

3. **Dashboard cieco sulla volatilità.** Tab Intelligence mostra anomalies GDELT/RSS, ma niente regime di volatilità posizioni aperte, whale activity, top market live. L'operatore non vede ciò che il bot non sa.

**Direzione strategica esplicita utente:** *"IL TIMING è IL PIù GRANDE EDGE. L'edge non può essere un numero statico per un prezzo estremamente volatile."*

---

## Execution Plan — Wave Schedule

| Wave | Sessioni | Parallelo? | Modelli | Effort |
|------|----------|-----------|---------|--------|
| **W1** | S1 | solo | Opus 4.7 | alto |
| **W2** | S2 | solo (richiede S1 committed) | Sonnet 4.6 | medio |
| **W3** | S3 | solo (richiede S2 committed) | Sonnet 4.6 | basso |
| **W4** | **S4a + S4b** | **parallelo** (scope file disgiunti) | S4a: Sonnet 4.6 / S4b: Opus 4.7 | S4a: medio / S4b: alto |
| **W5** | **S5a + S5b** | **parallelo** (scope file disgiunti) | S5a: Opus 4.7 / S5b: Sonnet 4.6 | S5a: alto / S5b: basso |

**Razionale modelli:**
- **Opus 4.7 (1M ctx)** per sessioni con ragionamento matematico non banale (S1 formula sign-preserving, S4b integrazione ibrida + validator) o frontend complesso senza build tool (S5a standalone DSS con CORS/WS/localStorage).
- **Sonnet 4.6** per sessioni meccaniche con specs chiare (S2/S3 client HTTP, S4a atomic write, S5b widget extension).
- Opus 4.7 1M context permette a S1/S4b/S5a di caricare plan + file codebase + skills + test esistenti senza compaction — riduce rischio di perdere riferimenti mid-execution.

**Parallelizzazione W4 (S4a // S4b):**
- S4a tocca: `app/services/snapshot_writer.py` (NEW), `app/models/dss_snapshot.py` (NEW), `app/core/dependencies.py` (+snapshot_writer singleton), `docker/docker-compose.yml` (profiles + frontend-dss service), `docker/nginx-dss.conf` (NEW), `config/config.example.yaml` (+dss block)
- S4b tocca: `app/valuation/whale_pressure.py` (NEW), `app/valuation/insider_pressure.py` (NEW), `app/valuation/engine.py` (integrazione signals), `app/core/yaml_config.py` (+weights + validator), `app/execution/engine.py` (external_signals injection), `config/config.example.yaml` (+weights), `tests/test_valuation/` + `tests/test_core/test_yaml_config.py`
- Overlap: solo `config/config.example.yaml` (entrambi aggiungono sezioni DIVERSE — merge trivial). `app/core/yaml_config.py` solo S4b.

**Parallelizzazione W5 (S5a // S5b):**
- S5a tocca: `static/dss/dss.html` (NEW), `static/dss/dss.js` (NEW), `static/dss/dss.css` (NEW)
- S5b tocca: `static/index.html`, `static/js/app.js`, `static/css/style.css`, `docker/nginx.conf`, `app/monitoring/dashboard.py` (SSE payload extend)
- Overlap: zero. Directory separate (`static/dss/` vs `static/` root).

---

## Decisioni finali (D1–D6)

### D1 — Edge dinamico volatility-aware con edge-strength dampener

**Formula definitiva** (sostituisce blocco edge in [app/valuation/engine.py:99-136](app/valuation/engine.py:99)):

```python
STRONG_EDGE_THRESHOLD = 0.10  # configurabile in volatility block

# 1. Componenti base
edge_central = (fair_value - market_price) * temporal_factor - market.fee_rate

# 2. CI volatility bounds
k = {SHORT: 0.5, MEDIUM: 0.75, LONG: 1.0}.get(market.time_horizon, 1.0)
edge_lower = edge_central - k * realized_vol_1h    # può essere negativo
edge_upper = edge_central + k * realized_vol_1h

# 3. Velocity penalty su |edge_central|, preservando segno (bug di segno fix)
velocity_against = -velocity_val if (edge_central > 0) else velocity_val
velocity_penalty_raw = max(0.3, 1.0 - velocity_alpha * abs(velocity_against))

# 4. Edge-strength dampener (user caveat: allucinazioni collettive vanno sfruttate)
edge_strength = min(1.0, abs(edge_central) / STRONG_EDGE_THRESHOLD)
penalty_dampener = 1.0 - edge_strength
velocity_penalty_effective = 1.0 - penalty_dampener * (1.0 - velocity_penalty_raw)

# 5. edge_dynamic preserva SEGNO, magnitude ridotta da vol e penalty
edge_magnitude = max(0.0, abs(edge_central) - k * realized_vol_1h)  # gated at 0
edge_dynamic = math.copysign(edge_magnitude, edge_central) * velocity_penalty_effective

# 6. Gating
recommendation = self._recommend(edge_dynamic, confidence, time_horizon)
```

**Proprietà garantite:**
- `realized_vol=0, velocity=0` → `edge_dynamic == edge_central` (backward compat)
- `|edge_central| >= 0.10` → `velocity_penalty_effective = 1.0` (edge forte bypass penalty)
- `|edge_central| <= k * realized_vol` → `edge_magnitude = 0` (gated, no trade su mercati troppo noisy)
- Segno di `edge_dynamic` identico a `edge_central` (fix bug di segno SELL)

### D2 — Pesi VAE: 9 esistenti invariati + 2 nuovi a 0.05

```yaml
# config/config.example.yaml — sezione valuation.weights
base_rate: 0.15          # invariato
rule_analysis: 0.15      # invariato
microstructure: 0.15     # invariato
cross_market: 0.10       # invariato
event_signal: 0.15       # invariato
pattern_kg: 0.10         # invariato
cross_platform: 0.10     # invariato (effective=0 fintanto Manifold disabled)
crowd_calibration: 0.05  # invariato
temporal: 0.05           # invariato
whale_pressure: 0.05     # NUOVO
insider_pressure: 0.05   # NUOVO
# nominal sum: 1.10 — effective ≈ 1.00 con Manifold off
```

**Implicazione test:** `tests/test_core/test_yaml_config.py:39-53` va **riscritto dinamicamente** — enumerare tutti i campi weights, accettare sum in `[0.95, 1.15]` con tolleranza (il calcolo fair_value normalizza per `weight_total` effettivo).

### D3 — Semantica integrazione whale/insider nel VAE: ibrida

```python
# WHALE_PRESSURE — event-style (come event_signal, pattern_kg)
# whale_signal in [0, 1]: 0=SELL pressure, 0.5=neutrale, 1=BUY pressure
if inputs.whale_pressure_signal is not None:
    weighted_sum += weights.whale_pressure * inputs.whale_pressure_signal
    weight_total += weights.whale_pressure

# INSIDER_PRESSURE — microstructure-style (centrata su market_price, ±0.05)
# insider_signal in [0, 1]: 0.5=nessun sospetto, >0.5=sospetto BUY, <0.5=sospetto SELL
if inputs.insider_pressure_signal is not None:
    insider_prob = market_price + (inputs.insider_pressure_signal - 0.5) * 0.1
    insider_prob = max(0.01, min(0.99, insider_prob))
    weighted_sum += weights.insider_pressure * insider_prob
    weight_total += weights.insider_pressure
```

**Razionale:** whale = presenza direzionale di trader influenti, giustifica spinta autonoma. Insider = conferma sospetta, impact minimo per preservare prezzo base.

### D4 — Whale vs Insider: criteri detection

**Whale signal** — "qualcuno di grosso si muove":
- (a) Single trade size ≥ **$100k** → flag immediato
- (b) Wallet in top-10% volume Polymarket all-time
- (c) Wallet con `total_pnl > $500k` OR `weekly_pnl > $50k`
- (d) New wallet (<7 giorni) con single order ≥ **$1M** → flag massimo

Side: BUY whale → signal > 0.5, SELL whale → signal < 0.5.

**Insider signal** — "movimento anomalo sospetto":
- Filtro obvious_outcome: prezzo fuori da [0.05, 0.95] da >24h → IGNORA
- Pre-resolution window: trade entro 30 min da `resolution_datetime`
- Wallet win-rate storico >50% (binomial p<0.05, min 10 trade) OR asymmetric outcome-match
- New-account guard: <7 giorni + size ≥ $1M + pre-res flag → insider quasi certo

Score: base 0.5, sale a 0.7-0.9 se ≥2 criteri matchano.

### D5 — DSS Live Artifact: Docker split profiles

```yaml
# docker/docker-compose.yml
services:
  backend:
    profiles: ["full"]
  frontend-dashboard:
    profiles: ["full"]
    ports: ["5174:80"]
  frontend-dss:
    profiles: ["full", "dss-only"]   # SEMPRE disponibile
    image: nginx:alpine
    ports: ["5175:80"]
    volumes:
      - ../static/dss:/usr/share/nginx/html:ro
```

**Uso:**
- `docker compose --profile full up` → full bot + DSS
- `docker compose --profile dss-only up` → solo DSS (backend Python spento)

**Architettura dati DSS** (`static/dss/dss.html`):
- Fetch DIRETTO `https://clob.polymarket.com/*` (CORS aperto, verificato Codex)
- Fetch The Graph subgraph gateway (CORS aperto) per dati on-chain
- Polling `/intelligence_snapshot.json` per ultima intelligence VAE
- localStorage cache shallow (<5MB, no history arrays — charts fetchano da CLOB)
- Banner "Intelligence stale: last update X hours ago"

### D6 — Sequenza sessioni: S1→S2→S3→{S4a//S4b}→{S5a//S5b}

Split S5 originale in S4a (snapshot writer = contratto dati), S5a (dss.html), S5b (dashboard widget minori) raccomandato da Opus.

---

## Aggiornamento `.claude/tasks/todo.md` (S1 eseguirà)

**Archivia:** Phase 11 Critical Bug Fixes (6 fixes) → `[DONE 2026-04-15]`, Phase 12 PD/PE/PF → `[DONE 2026-04-15]`, Open Items from Browser Test → `[DONE 2026-04-15]`.

**Rimuovi:** frase libera *"IL TIMING è IL PIù GRANDE EDGE..."* in header.

**Aggiungi:** sezione `## Phase 13 — Dynamic Edge & Platform Intelligence` con sottosezioni S1→S5b come checklist `[ ]`, link a `.claude/plans/phase-13/`.

## Aggiornamento `.claude/tasks/lessons.md` (S1 eseguirà)

**Archivia** (muovi da Active a Archive): `2026-04-04 Python 3.11`, `2026-04-04 hatchling editable`, `2026-04-15 nginx Cache-Control`, `2026-04-15 Browser test against live server`.

**Aggiungi in Active:**
1. `2026-04-23 — [codebase] Static edge ignora volatility regime`: Action: Phase 13 S1 introduce edge_dynamic con CI + velocity penalty + edge-strength dampener.
2. `2026-04-23 — [codebase] Polymarket platform data free-tier non integrato`: Action: Phase 13 S2+S3.
3. `2026-04-23 — [codebase] CORS verdict Polymarket — clob aperto, gamma chiuso`: Action: DSS Live Artifact usa solo clob + Subgraph direttamente.

Target finale `## Active`: 10-11 entries.

---

## Verification finale end-to-end (post S5b)

```bash
cd "C:\Users\fgioa\OneDrive - SYNESIS CONSORTIUM\Desktop\PRO\PolyMarket"

# Regression full
python -m pytest tests/ -v --tb=short     # atteso: 730+ pass, 0 fail
python -m ruff check app/ tests/
python -m mypy app/

# Docker full profile
docker compose --profile full down -v
docker compose --profile full up -d --build
sleep 30

# Smoke API
curl http://localhost:8000/api/v1/intelligence/whales?since=1h     | jq '. | length'
curl http://localhost:8000/api/v1/intelligence/popular-markets      | jq '. | length'
curl http://localhost:8000/api/v1/intelligence/leaderboard          | jq '. | length'
curl http://localhost:5175/dss.html                                 | grep -q '<title>DSS' && echo OK

# Profile dss-only (backend off)
docker compose --profile full down
docker compose --profile dss-only up -d
curl http://localhost:5175/dss.html                                 | grep -q '<title>DSS' && echo OK

# Browser MCP (via mcp__Claude_in_Chrome__*):
# 1. http://localhost:5174 — whale counter, DSS link, vol sparkline
# 2. Click "Open DSS" → :5175 opens
# 3. Stop full, start dss-only: DSS loads con stale banner
```

---

## Open items per Phase 14 (out of scope)

- **WebSocket trade stream backend-side** (real-time whale detection)
- **Wallet clustering** (PolygonScan on-chain funding source)
- **Manifold satellite re-enable** (rebilanciare pesi VAE)
- **Backtesting edge_dynamic** su dati storici per calibrare `strong_edge_threshold` e `k_per_horizon`
- **Regime detection Hurst exponent** (scartato per samplesize insufficiente)
- **DSS artifact hosting pubblico** (Vercel privato o GH Pages privato)

---

## Riferimenti file chiave (ground truth verificata)

| File | Linee | Scope |
|------|-------|-------|
| [app/valuation/engine.py](app/valuation/engine.py) | 99-136 edge block, 194+ `_compute_fair_value`, 265 `_make_input`, 285 assess | Core VAE, modificato S1 + S4b |
| [app/core/yaml_config.py](app/core/yaml_config.py) | 74-84 `WeightsConfig` (nome esatto classe) | Config Pydantic, esteso S1 + S4b |
| [tests/test_core/test_yaml_config.py](tests/test_core/test_yaml_config.py) | 39-53 test sum | Riscrittura dinamica S4b |
| [app/services/intelligence_orchestrator.py](app/services/intelligence_orchestrator.py) | 21-60 pattern late-binding | Template per WhaleOrchestrator + SnapshotWriter |
| [docker/docker-compose.yml](docker/docker-compose.yml) | 27 frontend `5174:80`, backend `8000:8000` | Split profili S4a |
| [docker/nginx.conf](docker/nginx.conf) | — (path corretto, NON `nginx/nginx.conf`) | Cache-busting S5b |
| [static/js/app.js](static/js/app.js) | 311+ `renderPositions` (NON 191-307) | Sparkline widget S5b |
