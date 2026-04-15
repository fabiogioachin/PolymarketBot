---
name: Prompt PE — Integration tests: cross-source flow, probability calculation, engine-to-KB
description: Scrivere test di integrazione per flussi critici senza copertura end-to-end. Cross-source (GDELT->KG->VAE), calcolo probabilita' nel VAE con formula reale, engine tick che popola Risk KB. SQLite in-memory reale, respx per HTTP mock.
type: project
---

## Obiettivo

Scrivere una suite di test di integrazione (non unit test) per tre flussi critici che attualmente non hanno copertura end-to-end:

1. **Engine-to-KB** — un tick dell'ExecutionEngine popola il Risk KB con i segnali generati
2. **Cross-source interconnections** — simula un ciclo GDELT->KG patterns->VAE event_signal->signal generato
3. **Probability calculation** — verifica che i 9 segnali del VAE producano fair_value e edge corretti su input noti

## Contesto

### Sistema testato

**VAE (Value Assessment Engine)** — `app/valuation/engine.py`

ATTENZIONE: la formula del VAE non e' una semplice media pesata dei segnali grezzi. L'agente DEVE leggere `_compute_fair_value()` (linee 194-375 di `engine.py`) prima di scrivere qualsiasi asserzione numerica. Ecco le trasformazioni critiche:

- `microstructure_score` viene trasformato: `micro_signal = market_price + (score - 0.5) * 0.1` (NON il valore grezzo)
- `cross_market_signal` ha range **-1 to +1** (non 0-1): `cross_prob = market_price + signal * 0.15`
- `crowd_calibration_adjustment` non e' un segnale indipendente: viene applicato come `adjusted_price = market_price + calibration_adj` e ponderato
- `crowd_calibration_adjustment == 0` NON attiva il branch nel codice (linea 224: `if inputs.crowd_calibration_adjustment != 0`)
- Il `fair_value` finale e' `weighted_sum / weight_total` con RENORMALIZZAZIONE dei pesi quando alcuni segnali sono None
- `temporal_factor` NON entra in `_compute_fair_value()` — viene usato DOPO: `scaled_edge = edge * temporal_factor`
- `fee_adjusted_edge = scaled_edge - market.fee_rate` (NON un fisso 0.02 — `fee_rate` varia per market, default 0.0 nel factory di test)

La formula completa dell'edge nel metodo `assess()` (linee 103-105):
```
edge = fair_value - market_price
scaled_edge = edge * temporal_factor
fee_adjusted_edge = scaled_edge - market.fee_rate
```

**Risk KB** — `app/knowledge/risk_kb.py`
- `RiskKnowledgeBase`: SQLite, upsert/get/get_all/get_by_strategy
- Tabella `market_knowledge`: market_id, risk_level, risk_reason, strategy_applied, strategy_params, notes, resolution_outcome
- Test unitari gia' esistenti in `tests/test_knowledge/test_risk_kb.py` — non duplicarli

**Intelligence flow** — `app/services/intelligence_orchestrator.py`
- `IntelligenceOrchestrator.tick()` → chiama `GdeltService.poll_watchlist()` + `NewsService.fetch_all()`
- Per ogni evento GDELT: `_process_event(event)` → `knowledge.match_patterns(domain, event_text)` → se match → aggiorna `event.relevance_score`, poi `knowledge.write_event()`
- `get_event_signal(domain)` → 0.0-1.0 basato su `max(relevance_score)` dell'ultimo report per quel domain

**CrowdCalibrationAnalyzer** — `app/valuation/crowd_calibration.py`
- `get_adjustment(category)` ritorna `0.0` se `sample_size < 20` (linea 94)
- `bias = sum((bucket_center - actual_freq) * count) / total_samples`
- Ritorna `-bias` (se crowd overestimates, adjustment e' negativo)
- Per testarlo servono **almeno 20 record** nella ResolutionDB per la stessa categoria

**KnowledgeService** — `app/services/knowledge_service.py`
- `match_patterns(domain, event_text)` → ritorna lista di oggetti con attributo `match_score` (non `confidence`)
- Leggere `app/services/knowledge_service.py` per il tipo esatto di ritorno prima di scrivere mock

### Strutture dati chiave

```python
# ValuationResult (app/models/valuation.py)
ValuationResult(
    market_id: str,
    fair_value: float,        # 0-1
    market_price: float,      # 0-1
    edge: float,              # fair_value - market_price
    confidence: float,        # 0-1
    fee_adjusted_edge: float, # (edge * temporal_factor) - market.fee_rate
    recommendation: Recommendation,  # BUY/SELL/HOLD/STRONG_BUY/STRONG_SELL
)

# MarketKnowledge (app/knowledge/risk_kb.py)
MarketKnowledge(
    market_id: str,
    risk_level: RiskLevel,    # low/medium/high
    risk_reason: str,
    strategy_applied: str,
    strategy_params: dict,
    notes: list[str],
    resolution_outcome: str | None,
)

# AnomalyReport (app/models/intelligence.py)
AnomalyReport(
    detected_at: datetime,
    events: list[GdeltEvent],
    news_items: list[NewsItem],
    total_anomalies: int,
)
```

### Fixture e pattern esistenti

- `tests/conftest.py` — fixture globali
- `tests/test_execution/conftest.py` — fixture engine
- Pattern usato in tutti i test: `_make_market()`, `_make_valuation()` factory functions
- SQLite in-memory: `RiskKnowledgeBase(":memory:")` — gia' supportato dal costruttore
- Mock HTTP: `respx` (gia' usato in `tests/test_clients/`, `tests/test_services/`)
- `pytest-asyncio` in modalita' `auto` (da `pytest.ini` o `pyproject.toml`)

### File da leggere PRIMA di scrivere qualsiasi test

- `app/valuation/engine.py` linee 194-375 — `_compute_fair_value()` per formula reale
- `app/valuation/engine.py` linee 100-105 — calcolo edge/scaled_edge/fee_adjusted_edge
- `app/valuation/crowd_calibration.py` — `compute_calibration()` e `get_adjustment()`
- `app/valuation/temporal.py` — `compute_temporal_factor()`
- `app/services/knowledge_service.py` — `match_patterns()` tipo di ritorno
- `tests/test_knowledge/test_risk_kb.py` — pattern gia' esistenti (non duplicare)
- `tests/test_services/test_intelligence_orchestrator.py` — pattern mock per GdeltService/NewsService
- `tests/test_valuation/test_engine.py` — pattern VAE assessment, factory `_make_market()`
- `tests/test_execution/test_engine.py` — pattern FakeValueEngine, FakeStrategy

## Vincoli

- Nessun mock database. SQLite in-memory reale: `RiskKnowledgeBase(":memory:")`, `TradeStore(":memory:")`
- Mock HTTP con `respx` per tutte le chiamate esterne (GDELT, Obsidian REST API, Manifold)
- Nessun accesso a file system reale o Obsidian vault fisico
- `ObsidianBridge` deve essere mockato via respx o sostituito con una fake implementation
- I test devono essere deterministici: niente `asyncio.sleep()`, niente timestamp dinamici non mockati
- I file di test vanno in:
  - `tests/test_integration/test_storage_retrieval.py`
  - `tests/test_integration/test_cross_source_flow.py`
  - `tests/test_integration/test_probability_calculation.py`
  - `tests/test_integration/__init__.py`

## Output atteso

### Suite 1 — `test_storage_retrieval.py`

Nota: i test unitari per RiskKnowledgeBase (upsert, get, get_by_strategy, add_note, update_resolution) esistono gia' in `tests/test_knowledge/test_risk_kb.py`. NON duplicarli. Questa suite testa solo il flusso di integrazione engine->KB.

**Test 1.1 — engine_tick_populates_risk_kb**
```
Dato: ExecutionEngine con FakeExecutor + FakeValueEngine(edge=0.2) + RiskKnowledgeBase in-memory
      FakeStrategy che genera un segnale BUY con edge_amount=0.2
Azione: engine.tick(markets=[market_con_segnale_approvato])
Assert: risk_kb.get_all() ritorna almeno 1 record
Assert: record.strategy_applied != ""
Assert: record.risk_level == RiskLevel.LOW (edge 0.2 > 0.15 threshold in step 5c)
```

**Test 1.2 — engine_tick_to_api_endpoint** (end-to-end: engine -> KB -> API)
```
Dato: ExecutionEngine con risk_kb in-memory, FastAPI app con dependency override
Azione: engine.tick() produce almeno 1 segnale
Assert: GET /api/v1/knowledge/strategies ritorna lista non vuota
Assert: GET /api/v1/knowledge/risks ritorna lista non vuota
```

### Suite 2 — `test_cross_source_flow.py`

**Test 2.1 — gdelt_event_writes_to_knowledge_service**
```
Dato: KnowledgeService con ObsidianBridge mockato (write_event ritorna True, match_patterns ritorna [])
     GdeltService mockato: ritorna 1 GdeltEvent(domain="politics", query="ELECTION")
     NewsService mockato: ritorna []
Azione: IntelligenceOrchestrator(gdelt=fake_gdelt, news=fake_news, knowledge=fake_knowledge).tick()
Assert: knowledge.write_event chiamato esattamente 1 volta con domain="politics"
Assert: report.total_anomalies == 1
```

**Test 2.2 — pattern_match_boosts_event_relevance**
```
Dato: KnowledgeService con match_patterns mockato: ritorna oggetto con match_score=0.9
     (ATTENZIONE: leggere il tipo di ritorno reale di match_patterns() prima di creare il mock)
     GdeltEvent(query="ELECTION turnout expected", domain="politics", relevance_score=0.3)
Azione: IntelligenceOrchestrator._process_event(event)
Assert: event.relevance_score == 0.9  (max(0.3, 0.9) — codice linea 87)
```

**Test 2.3 — event_signal_flows_to_vae**
```
Dato: IntelligenceOrchestrator con 1 anomalia in history (domain="politics", relevance=0.8)
     ExecutionEngine con intelligence_orchestrator=orch
     Market(category=POLITICS)
Azione: engine._fetch_intelligence_signals(markets=[market], external_signals={}, now=now)
Assert: external_signals[market.id]["event_signal"] == 0.8
```

**Test 2.4 — vae_uses_event_signal_in_fair_value**
```
Dato: Market(price=0.50, category=POLITICS, fee_rate=0.0, end_date=now+60days)
     assess() chiamato con event_signal=0.80
Assert: valuation.fair_value != 0.50  (event_signal sposta il fair_value)
Assert: valuation.edge != 0.0
Note: il fair_value dipende dalla renormalizzazione dei pesi. Con solo base_rate + event_signal attivi,
      i pesi vengono ribilanciati. L'agente deve calcolare il valore atteso dalla formula reale.
```

**Test 2.5 — full_intelligence_to_signal_pipeline** (end-to-end)
```
Dato: ExecutionEngine completo con:
     - ValueAssessmentEngine reale (non fake) + ResolutionDB in-memory
     - IntelligenceOrchestrator mockato (get_event_signal("politics") -> 0.75)
     - FakeStrategy che genera BUY se edge > 0.05
Azione: engine.tick(markets=[market_politics])
Assert: result.signals_generated >= 1
```

### Suite 3 — `test_probability_calculation.py`

REGOLA CRITICA: L'agente deve calcolare TUTTI i valori attesi partendo dalla formula reale in `_compute_fair_value()`, NON da assunzioni. Leggere il codice prima di scrivere qualsiasi asserzione numerica.

**Test 3.1 — fair_value_with_all_signals_known**
```
Input:
  market_price = 0.40, fee_rate = 0.0
  end_date = now + 60 days (temporal_factor = 1.0)
  base_rate = 0.55 (peso 0.15)
  rule_analysis_score = 0.60 (peso 0.15)
  microstructure_score = 0.50 (peso 0.15) → micro_signal = 0.40 + (0.50-0.5)*0.1 = 0.40
  cross_market_signal = 0.45 (peso 0.10) → cross_prob = 0.40 + 0.45*0.15 = 0.4675
  event_signal = 0.70 (peso 0.15)
  pattern_kg_signal = 0.60 (peso 0.10)
  cross_platform_signal = 0.50 (peso 0.10)
  crowd_calibration_adjustment = 0.0  → NON attiva il branch (if != 0)
  temporal_factor = calcolato automaticamente da end_date

L'agente deve calcolare:
  weighted_sum = 0.15*0.55 + 0.15*0.60 + 0.15*0.40 + 0.10*0.4675 + 0.15*0.70 + 0.10*0.60 + 0.10*0.50
  weight_total = 0.15+0.15+0.15+0.10+0.15+0.10+0.10 = 0.90 (crowd_cal non attivo = -0.05, temporal non in formula = -0.05)
  fair_value = weighted_sum / weight_total

  VERIFICARE questo calcolo dal codice reale prima di scrivere l'asserzione.

Assert: abs(fair_value - expected) < 0.01
Assert: edge = fair_value - 0.40
Assert: scaled_edge = edge * temporal_factor (dove temporal_factor = 1.0 per end_date > 30 days)
Assert: fee_adjusted_edge = scaled_edge - 0.0 (fee_rate=0.0)
Assert: recommendation == BUY (se fee_adjusted_edge > min_edge config)
```

**Test 3.2 — fair_value_with_partial_signals**
```
Input: market_price=0.60, fee_rate=0.0, end_date=now+60d
       solo base_rate=0.45 fornito, tutti gli altri segnali = None
Assert: fair_value e' calcolato (non eccezione)
Assert: confidence < 0.5 (pochi segnali + coverage scaling)
Note: con 1 sorgente, coverage = 0.5 + 1/6 = 0.667, avg_confidence = 0.5 (base_rate ha conf 0.5)
      confidence = 0.5 * 0.667 = 0.333
      L'agente deve verificare dal codice.
```

**Test 3.3 — edge_calculation_symmetry**
```
Input A: market_price=0.30, base_rate=0.60, fee_rate=0.0, end_date=now+60d
Input B: market_price=0.70, base_rate=0.40, fee_rate=0.0, end_date=now+60d
Assert: edge_A > 0 (fair_value > market_price)
Assert: edge_B < 0 (fair_value < market_price)
Assert: fee_adjusted_edge_A = edge_A * temporal_factor - 0.0
Assert: fee_adjusted_edge_B = edge_B * temporal_factor - 0.0
```

**Test 3.4 — temporal_factor_scales_edge**
```
Input: market (end_date = now + 2h) vs market (end_date = now + 60 days)
       Stessi segnali per entrambi, stessa market_price
Assert: temporal_factor(near) < temporal_factor(far)
Assert: abs(fee_adjusted_edge_near) < abs(fee_adjusted_edge_far)
       (stessa fair_value ma edge scalato diversamente dal temporal_factor)
Note: temporal_factor NON influenza fair_value direttamente (non e' in _compute_fair_value)
      Influenza solo scaled_edge = edge * temporal_factor
```

**Test 3.5 — crowd_calibration_adjusts_fair_value**
```
Dato: ResolutionDB in-memory con ALMENO 25 mercati "politics" risolti
      Tutti nel bucket 0.75-0.85 (final_price tra 0.75 e 0.85)
      Di questi, 60% risolti YES (actual_freq = 0.60 vs predicted ~0.80)
      bias = (0.80 - 0.60) * 25 / 25 = 0.20 (crowd overconfident)
      adjustment = -0.20 (negate bias)
Assert: calibration_adj < 0 (crowd overestimates → adjustment negativo)
Assert: fair_value con calibration != fair_value senza calibration
       (verificare che il branch crowd_calibration in _compute_fair_value si attivi)
Note: la threshold e' sample_size >= 20. Con 25 campioni supera la threshold.
```

### Criteri di accettazione finali

- Tutti i test passano con `pytest tests/test_integration/ -v`
- Nessun test usa `time.sleep()` o dipende dall'orologio di sistema
- Coverage: ogni test verifica almeno un'asserzione su un valore numerico concreto
- Nessun test usa mock per SQLite (usare in-memory reale)
- Nessun test duplica copertura gia' presente in `tests/test_knowledge/test_risk_kb.py`

## Note

- Skill da consultare: `vae-signal` (SKILL.md in `.claude/skills/vae-signal/`), `intelligence-source` (`.claude/skills/intelligence-source/`)
- Il `TemporalAnalyzer` e' in `app/valuation/temporal.py` — leggerlo prima di Test 3.4
- `CrowdCalibrationAnalyzer` e' in `app/valuation/crowd_calibration.py` — leggerlo prima di Test 3.5. Nota: `get_adjustment()` ritorna 0.0 se sample_size < 20
- `match_patterns()` in KnowledgeService ritorna oggetti con `match_score`, non `confidence` — leggere il tipo reale prima di creare mock
- Usare `@pytest.mark.asyncio` su tutti i test async (gia' configurato in auto mode)
- L'agente DEVE leggere il codice effettivo delle formule VAE prima di scrivere le asserzioni numeriche. Mai inventare i valori attesi — calcolarli dalla formula reale
- Nella factory `_make_market()` dei test VAE esistenti, `fee_rate` ha default `0.0` — usare lo stesso default per coerenza
