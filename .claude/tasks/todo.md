# PolymarketBot — Development Tracker

> Autonomous intelligence + value assessment system for Polymarket
> Stack: Python 3.11, FastAPI, Pydantic v2, httpx, aiosqlite, scikit-learn
> Capital: 150 EUR | 657 tests | 9 VAE signals | 7 strategies | 9 project skills

---

## Completed (Phase 0-9)

**Foundation (Phase 0-1):** Legal/fiscal analysis (Italy restricted — dry-run + Predict Street monitoring). Full FastAPI scaffold, Polymarket REST+CLOB+WS clients, market scanner, rule parser. 80 test.

**Value Assessment Engine (Phase 2):** Core module. ResolutionDB + BaseRateAnalyzer (Bayesian shrinkage) + CrowdCalibrationAnalyzer + MicrostructureAnalyzer + CrossMarketAnalyzer + TemporalAnalyzer. 9 weighted signals → fair_value → edge → recommendation. 70 test.

**Intelligence Pipeline (Phase 3):** GDELT DOC 2.0 + GeoJSON, RSS (Reuters/AP/BBC/Al Jazeera), institutional (Federal Register). IntelligenceOrchestrator tick cycle, EnrichmentService deep-dive, Obsidian KG bridge. 88 test.

**Strategy Layer (Phase 4):** 7 strategies via Protocol (value_edge, arbitrage, rule_edge, event_driven, resolution, sentiment, knowledge_driven). Signal carries market_price. Multi-leg returns list[Signal]. 129 test.

**Risk & Execution (Phase 5-6):** RiskManager (equity-relative limits "5%"), PositionSizer (fixed fraction + half-Kelly), CircuitBreaker (3 losses / 15% drawdown). ExecutionEngine tick cycle, DryRun/Shadow/Live executors, position_monitor (TP/SL/expiry/edge-reversal). TradeStore SQLite persistence. Backtest engine + Parquet data loader. Dashboard SSE, Telegram alerts, LLM triggers. 209 test.

**KG & Docs (Phase 7):** 25+3 seed patterns, vault setup scripts, ARCHITECTURE.md, API-REFERENCE.md. 14 test.

**Review (Phase 8):** 11 critical bugs fixed (order price, SELL direction, arb two-leg, daily reset, DI wiring, confidence floor). 598→657 test.

**Manifold Satellite (Phase 9):** ManifoldClient + ManifoldService (TF-IDF matching). cross_platform signal (weight 0.10) in VAE via external_signals pattern. ResolutionDB multi-source. Obsidian divergence notes. 9 project skills. 59 new test.

---

## Pending (from previous phases)

- [ ] Monitorare lancio Predict Street Ltd (9 aprile 2026) — verificare accessibilita dall'Italia
- [ ] Enable manifold in config.yaml and run ingest script
- [ ] Wire record_divergence() into tick cycle for Obsidian persistence

---

## Phase 10: Time-Horizon Budget Allocation & Capital Efficiency

> **Problema**: il bot usa il budget come pool unico. Con 150 EUR, max_exposure 50% (75 EUR), e
> max_single 5% (7.50 EUR), bastano ~10 posizioni per bloccare tutto il capitale. Se sono tutte
> trade a lungo termine (30+ giorni), il capitale e immobilizzato e il bot non opera per settimane.
> Il focus deve essere su trade a breve termine (ore/giorni) con turnover alto.

### 10.1 — Time Horizon Classification

**Files:** `app/models/market.py` (MOD), `app/valuation/temporal.py` (MOD)

- [ ] Definire `TimeHorizon` enum: `SHORT` (< 3 giorni), `MEDIUM` (3-14 giorni), `LONG` (> 14 giorni)
- [ ] Aggiungere `time_horizon: TimeHorizon` a `Market` model (calcolato da `end_date`)
- [ ] Aggiungere helper `classify_horizon(end_date) -> TimeHorizon` in `temporal.py`
- [ ] Mercati senza `end_date` → `LONG` (conservativo, non bloccare budget short)

### 10.2 — Budget Pool per Horizon

**Files:** `app/risk/manager.py` (MOD), `app/core/yaml_config.py` (MOD), `config/config.example.yaml` (MOD)

- [ ] Aggiungere config budget allocation:
  ```yaml
  risk:
    horizon_allocation:
      short_pct: 60    # 60% del budget per trade < 3 giorni
      medium_pct: 30   # 30% per 3-14 giorni
      long_pct: 10     # 10% per > 14 giorni (solo trade molto favorevoli)
  ```
- [ ] `RiskManager`: tracciare esposizione per horizon (`_exposure_by_horizon: dict[TimeHorizon, float]`)
- [ ] `check_order()`: aggiungere check #4b — rifiutare se il pool dell'horizon e pieno
  - Es: 150 EUR × 50% exposure × 60% short = 45 EUR max per posizioni short
  - Se short pool pieno ma medium ha spazio → la trade short viene comunque eseguita se c'e edge
- [ ] `record_fill()` / `record_close()`: tracciare horizon della posizione

### 10.3 — Edge Threshold per Horizon (scadenza vicina = edge minore accettabile)

**Files:** `app/valuation/engine.py` (MOD), `app/core/yaml_config.py` (MOD)

- [ ] Aggiungere config edge thresholds per horizon:
  ```yaml
  valuation:
    thresholds:
      min_edge: 0.05           # default (usato come fallback)
      min_edge_short: 0.03     # trade brevi: edge minimo 3% (turnover veloce compensa)
      min_edge_medium: 0.05    # trade medie: edge standard 5%
      min_edge_long: 0.10      # trade lunghe: edge minimo 10% (capital lockup cost)
  ```
- [ ] `_recommend()` in `engine.py`: accettare `time_horizon` e usare la soglia corrispondente
- [ ] Logica: a parita di edge, privilegiare la trade con scadenza piu vicina (gia implicito nel budget allocation, ma il threshold piu basso per short lo rinforza)

### 10.4 — Priority Scoring nel Tick Cycle

**Files:** `app/execution/engine.py` (MOD)

- [ ] Dopo `assess_batch()`, ordinare i segnali per priority score prima di eseguirli:
  ```
  priority = fee_adjusted_edge / days_to_resolution
  ```
  - Trade con edge 5% e scadenza 2 giorni → priority 2.5
  - Trade con edge 10% e scadenza 30 giorni → priority 0.33
  - La trade a breve vince, anche se ha meno edge assoluto
- [ ] Eseguire in ordine di priority fino a esaurimento budget per pool
- [ ] Se un pool (es. short) e pieno, i segnali short rimanenti vengono droppati, non spostati in medium

### 10.5 — Fix: Exposure Blocking con Posizioni Max

**Files:** `app/risk/manager.py` (MOD)

- [ ] **Bug attuale**: `max_positions=25` ma `max_exposure_pct=50%` con `max_single=5%` → dopo ~10 posizioni il budget e bloccato (10 × 7.50 EUR = 75 EUR = 50% di 150). Le restanti 15 slot non vengono mai usate.
- [ ] **Fix**: Il check exposure deve considerare che le posizioni si risolvono e liberano capitale. Opzioni:
  - A) Aumentare `max_exposure_pct` (es. 70%) — semplice ma piu rischioso
  - B) Calcolare exposure netta: posizioni near-resolution (< 24h, probability > 0.90) contano al 50% perche il capitale sta per tornare
  - C) Il budget per horizon risolve implicitamente: se short_pct=60% e le trade short si chiudono in 1-3 giorni, il pool si ricicla naturalmente
- [ ] **Decisione raccomandata**: combinare B + C. L'horizon allocation garantisce che il capitale short ruota velocemente. Le posizioni near-resolution non bloccano il pool.

### 10.6 — Tests + Validation

**Files:** `tests/test_risk/` (MOD), `tests/test_valuation/` (MOD), `tests/test_execution/` (MOD)

- [ ] Test: budget allocation rifiuta trade quando pool dell'horizon e pieno
- [ ] Test: trade SHORT con edge 3% accettata, trade LONG con edge 3% rifiutata
- [ ] Test: priority ordering (breve > lungo a parita di edge)
- [ ] Test: near-resolution discount nell'exposure
- [ ] Test: backward compat — senza horizon config, comportamento identico a prima
- [ ] Dry-run 1h con nuovi parametri: verificare che il bot apra trade short e non si blocchi

---

## Execution Notes

### Dependency Order Phase 10
```
10.1 (TimeHorizon enum + classify) → 10.2 (budget pools) → 10.3 (edge thresholds)
                                                          → 10.4 (priority scoring)
                                                          → 10.5 (exposure fix)
                                                          → 10.6 (tests)
```

10.2 e 10.3 sono indipendenti (config diversi). 10.4 e 10.5 dipendono da 10.2.

### Risk Parameters (aggiornati)
- Capitale: 150 EUR
- Max exposure: 50% (75 EUR) — da rivalutare con horizon allocation
- Budget pools: 60% short / 30% medium / 10% long
- Edge minimo: 3% short / 5% medium / 10% long
- Fixed fraction: 5% per trade (7.50 EUR)
- Max concurrent positions: 25
- Circuit breaker: 3 consecutive losses OR 15% drawdown
