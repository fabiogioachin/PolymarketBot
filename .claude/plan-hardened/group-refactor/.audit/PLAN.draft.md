# PLAN.draft.md — Group-aware Strategy Refactor

**Round 1 — Sonnet/Opus draft**
Generated: 2026-05-02
Pipeline: `/plan-hardened`
Mode: planning (no code, no tests, no implementation)

---

## Obiettivo

Far sì che il bot scelga la **migliore alternativa all'interno di un ladder di mercati raggruppati** (un Polymarket Event con N mercati correlati) invece di valutare ciascun mercato in isolation, così evitando double-exposure su event family e privilegiando il mercato con edge atteso più alto. Nuova firma cardinale: `BaseStrategy.evaluate(markets, valuations, knowledge=None) -> Signal | list[Signal] | None`, con `markets: list[Market]` di lunghezza 1..N appartenente allo stesso `event_id`.

---

## File impattati

### Modify (production)

- `app/models/market.py` — aggiungere `event_id: str = ""` e `event_slug: str = ""` al `Market` model (Pydantic v2). Non computed: popolati upstream dal client Gamma.
- `app/clients/polymarket_rest.py` — aggiungere `list_events(...)` e `get_event(event_id)` che chiamano `GET /events` su `gamma-api.polymarket.com`; estendere `_parse_market` per leggere `eventId`/`event` dal payload Gamma quando presente; introdurre `_parse_event(...)` helper.
- `app/services/market_service.py` — nuovo `get_grouped_markets(...)` che ritorna `list[list[Market]]` (gruppi per event_id), oltre a mantenere l'attuale `get_filtered_markets()` per backward compat. Cache TTL deve essere aware del nuovo metodo (chiave separata).
- `app/services/market_scanner.py` — nuovo helper `group_by_event(markets)` → `dict[str, list[Market]]` per uso interno (deterministic ordering: per-event, ordered per `volume_24h` desc).
- `app/strategies/base.py` — riscrivere il `Protocol` con la nuova firma `evaluate(markets, valuations, knowledge=None)`. Mantenere temporaneamente un secondo metodo opzionale `evaluate_legacy(market, valuation, knowledge=None)` (default-implementabile? No — Protocol non supporta default; vedere step) — gestito tramite **adapter wrapper class** (vedere PR-B), non come metodo del Protocol.
- `app/strategies/registry.py` — `get_for_domain(domain)` continua a operare su un singolo dominio. Aggiungere helper `wrap_legacy(strategy)` che restituisce un wrapper conforme alla nuova `BaseStrategy` per le strategie non ancora migrate.
- `app/strategies/_legacy_adapter.py` (nuovo) — `class LegacyStrategyAdapter` che implementa il nuovo Protocol e delega per-market alla strategia legacy; ritorna il primo `Signal` non-None. Vedere PR-B.
- `app/execution/engine.py` (linee 211-249, focus 222-225) — il loop diventa: per ogni gruppo di mercati con stesso `event_id` e stesso dominio, costruire `valuations_by_market_id` per il gruppo e chiamare `strategy.evaluate(group, valuations_by_id)`. Mantenere il dedup `open_position_token_ids` e il filtro `exited_market_ids`. La riga 222 (`get_for_domain(market.category.value)`) si sposta a livello gruppo (assunzione: stessa `category` per tutti i mercati di un evento — vedere Ambiguità A2).
- `app/strategies/value_edge.py` — migrare a nuova firma. Selettore: argmax di `fee_adjusted_edge` × `confidence` tra i mercati del gruppo che superano `min_edge` e `min_confidence`. Loggare gli scartati.
- `app/strategies/rule_edge.py` — migrare. Selettore: argmax di `|fee_adjusted_edge|` × `adjusted_confidence` tra i mercati che passano i gate (skip HIGH_RISK, soglie). Loggare scartati.
- `app/strategies/resolution.py` — migrare. Selettore: argmax di `profit_after_fee` (calcolo già locale) tra i mercati che passano gate (entro `MAX_DAYS_TO_RESOLUTION`, `discount >= MIN_DISCOUNT`).
- `app/strategies/sentiment.py` — migrare. Selettore: argmax di `|sentiment| × |edge|` tra i mercati allineati (sentiment direction == edge direction). Knowledge è gruppo-level (assunzione: una `KnowledgeContext` per evento; vedere Ambiguità A4).
- `app/strategies/event_driven.py` — migrare. Selettore: argmax di `|combined_edge| × adjusted_confidence`. Speed-premium per pattern freschi conservato. Knowledge gruppo-level.
- `app/strategies/knowledge_driven.py` — migrare. Selettore: argmax di `composite_confidence × |edge|` tra mercati con strong patterns matchanti.
- `app/strategies/arbitrage.py` — migrare con **eccezione esplicita** documentata: itera per-market e ritorna `list[Signal]` aggregando tutte le coppie YES/NO mispriced del gruppo (multi-leg legittimo, non "winner-takes-all"). Documentare nel docstring perché diverge dalla regola "1 Signal per gruppo".
- `app/risk/manager.py` — aggiungere tracking `_event_exposure: dict[str, float]` (event_id → EUR) e nuovo gate in `check_order(...)`: `max_event_exposure_eur` (default 8% di equity, configurabile in `config.example.yaml`). Vedere Ambiguità A3 per default.
- `app/core/yaml_config.py` — aggiungere `risk.max_event_exposure_pct` (Pydantic field, default `8.0`). Wireup in `app/core/dependencies.py` se necessario.
- `config/config.example.yaml` — aggiungere `risk.max_event_exposure_pct: 8.0` con commento.
- `app/services/market_scanner.py` — `get_strategies_for_market` resta valido per backward compat; nessuna modifica funzionale richiesta.

### Create (new files)

- `app/strategies/_legacy_adapter.py` — `LegacyStrategyAdapter` (PR-B). Wraps any old-style strategy con `evaluate(market, valuation, knowledge)` e la espone con la nuova firma `evaluate(markets, valuations, knowledge)`, iterando in-order e ritornando il primo non-None. Documenta che "in-order" segue l'ordering passato dall'engine.
- `app/strategies/_group_selector.py` (opzionale ma consigliato) — utility `pick_best(items, key) -> tuple[Item, list[Item]] | None` che ritorna `(winner, discarded)` per uso uniforme nelle strategie. Estrarre in PR-C (prima strategia) per evitare duplicazione.
- `tests/test_clients/test_polymarket_rest_events.py` — copertura per `list_events`, `get_event`, parsing event payload con N markets.
- `tests/test_strategies/test_legacy_adapter.py` — verifica che `LegacyStrategyAdapter` preservi semantica per N=1, ritorni primo non-None per N>1, propaghi `knowledge`.
- `tests/test_strategies/test_group_selector.py` (se introdotto in PR-C) — corner cases: empty list, single item, ties.
- `tests/test_risk/test_event_exposure.py` — gate `max_event_exposure_pct`, accumulo per `event_id`, reset su `record_close`.
- `tests/test_services/test_market_grouping.py` — `group_by_event` raggruppa correttamente, fallback su event_id vuoto = singleton group, ordering deterministico.

### Modify (tests)

- `tests/test_strategies/test_value_edge.py` — aggiornare `_make_market()` per accettare `event_id` (default `f"event-{id}"` per ogni test che non lo specifica). Aggiungere casi N>1: vince mercato con `edge × confidence` massimo; tutti sotto soglia → None; ties → primo per ordering deterministico.
- `tests/test_strategies/test_rule_edge.py` — analogo. Casi: HIGH_RISK skippato, AMBIGUOUS scelto se è il migliore, gruppo misto.
- `tests/test_strategies/test_resolution.py` — analogo. Casi: gruppo con solo un mercato within-window, gruppo con tutti out-of-window → None.
- `tests/test_strategies/test_sentiment.py` — analogo. Casi: edge directions differenti nel gruppo, knowledge unica per gruppo.
- `tests/test_strategies/test_event_driven.py` — analogo. Casi: speed-premium su un mercato vs altri freddi.
- `tests/test_strategies/test_knowledge_driven.py` — analogo.
- `tests/test_strategies/test_arbitrage.py` — verificare che ritorna `list[Signal]` aggregata (multi-leg per più mercati del gruppo se ognuno mispriced).
- `tests/test_strategies/test_registry.py` — `get_for_domain` invariato, ma aggiungere test che `wrap_legacy` produce un wrapper conforme.
- `tests/test_execution/test_engine.py` — aggiornare i test che mockano `strategy.evaluate(market, valuation)` alla nuova firma. Aggiungere test che engine raggruppa per `event_id` e chiama `evaluate` una volta per gruppo.
- `tests/test_integration/test_probability_calculation.py` — verificare che il flow end-to-end funzioni con mercati raggruppati (il test attualmente assume single-market path).
- `tests/test_integration/test_storage_retrieval.py` e `test_cross_source_flow.py` — review e aggiornare se assumono single-market evaluate (probabilmente solo un'aggiornata di `_make_market` factory).

### Out of scope (do NOT modify)

- `app/execution/position_monitor.py` — gestione exit (TP/SL/expiry/edge-evaporated) è per-position, non per-group. Non toccare.
- `app/execution/executor.py` — il mapping `Signal → OrderRequest` resta invariato.
- `app/valuation/engine.py` — VAE resta per-market. `assess_batch` continua a ritornare `list[ValuationResult]` indipendenti (ogni mercato del gruppo riceve la sua valutazione).
- `app/models/signal.py` — `Signal` model invariato (continua a portare `market_id`, `token_id`, `market_price`).
- `app/models/valuation.py` — `ValuationResult` invariato.
- `app/strategies/__init__.py` — esiste? verificare; in caso, solo aggiungere export del nuovo `_legacy_adapter` se necessario.
- File del SELL→BUY-NO hotfix (`app/strategies/sentiment.py`, `event_driven.py`, `knowledge_driven.py` per la parte signal_type): questo plan PARTE DALLO STATO POST-FIX — ogni conflitto va risolto preferendo il fix già mergiato (BUY-NO).
- `.claude/plan-hardened/sell-fix/` — no-touch (archivio).
- `app/api/v1/` — endpoint dashboard/markets non cambiano contract (ritornano ancora liste piatte). Eventuale esposizione `event_id` sul JSON è opzionale e fuori scope.
- `static/` (dashboard) — non toccato in questo plan.
- `app/backtesting/` — il backtest engine usa la stessa pipeline strategie; verrà aggiornato implicitamente quando le strategie migrate. Nessuna modifica strutturale richiesta nel plan, ma vedere Ambiguità A6.

---

## Step di implementazione

### PR-A — Foundation (zero behavior change)

**Goal:** introdurre `event_id` lungo la pipeline senza che nessuno lo usi ancora. Tutti i test esistenti verdi.

1. **`app/models/market.py`** — aggiungere `event_id: str = ""` e `event_slug: str = ""`. Default empty per backward compat. Update docstring.
2. **`app/clients/polymarket_rest.py`** —
   - Aggiungere `_parse_event(data)` → `Event` (nuovo dataclass o dict). Decisione tra "creare modello `Event` separato" vs "ritornare `tuple[event_id, list[Market]]`": preferire dataclass leggero `Event(id, slug, title, markets, end_date)` in `app/models/market.py` o nuovo `app/models/event.py`. Vedere Ambiguità A7.
   - Estendere `_parse_market` per leggere `eventId` se presente nel payload (Gamma `/markets` endpoint a volte include `events: [...]`).
   - Aggiungere `async def list_events(active=True, limit=100, offset=0) -> list[Event]` su `/events`.
   - Aggiungere `async def get_event(event_id) -> Event` su `/events/{id}`.
   - Stesso `_TokenBucket` rate limiter (no doppio rate — vedere Ambiguità A8).
3. **`app/services/market_service.py`** —
   - Quando si chiama `list_markets()`, NON cambiare path principale (zero behavior change). In parallelo, dopo il fetch, popolare `event_id` per i mercati (best-effort: se il payload include `events`, leggere; altrimenti fare lookup batch via `list_events()` e join client-side per `condition_id`/`market.id`). Decisione di policy: in PR-A facciamo SOLO arricchimento se gratis (payload già contiene). Il fetch separato `/events` arriva in PR-B.
   - Aggiungere `get_grouped_markets()` che oggi ritorna `[[m] for m in get_filtered_markets()]` (singleton groups) — placeholder che PR-B sostituirà.
4. **`tests/test_clients/test_polymarket_rest_events.py`** — test per `list_events`, `get_event` con respx mock. 4 test cases: parse OK, event con 1 market, event con N markets, error retry.
5. **`tests/test_services/test_market_grouping.py`** — placeholder test che `get_grouped_markets()` oggi ritorna singletons.
6. **Verifica PR-A:**
   - `pytest tests/test_clients/test_polymarket_rest.py tests/test_clients/test_polymarket_rest_events.py -v`
   - `pytest tests/test_services/test_market_grouping.py -v`
   - `pytest -q` (full suite must stay green)
   - `ruff check app/ tests/ && mypy app/ --strict`

### PR-B — Engine + adapter shim (Protocol switch, behavior preserved)

**Goal:** tutte le strategie continuano a funzionare via adapter; engine call site usa la nuova firma. ALL existing tests pass.

1. **`app/strategies/base.py`** — riscrivere `BaseStrategy` Protocol:
   - `async def evaluate(self, markets: list[Market], valuations: dict[str, ValuationResult], knowledge: KnowledgeContext | None = None) -> Signal | list[Signal] | None`
   - Mantenere `name` e `domain_filter` come prima.
2. **`app/strategies/_legacy_adapter.py`** (nuovo) —
   - `class LegacyStrategyAdapter`:
     - `__init__(self, legacy_strategy)` — type hinted come `Any` (legacy non ha più Protocol).
     - `name`, `domain_filter` — proxied.
     - `evaluate(self, markets, valuations, knowledge=None)`:
       - Per ogni `m in markets` (in ordine ricevuto):
         - `v = valuations.get(m.id)`; if None continue
         - `result = await legacy.evaluate(m, v, knowledge)` (firma legacy)
         - if `result` is not None → log strutturato `legacy_adapter_picked` con `event_id`, `market_id`, `discarded=[m.id for ... non ancora valutati]` → return `result`
       - return None
3. **`app/strategies/registry.py`** — aggiungere `wrap_legacy(strategy) -> BaseStrategy` factory. Tutte le strategie attualmente registrate vengono wrappate al register-time tramite questo helper (in `app/core/dependencies.py`, vedere step 4).
4. **`app/core/dependencies.py`** — al momento di registrare le 7 strategie, wrappare ognuna con `LegacyStrategyAdapter` finché non sarà migrata nei PR successivi. (Quando una strategia sarà migrata, si registrerà direttamente senza wrap.)
5. **`app/services/market_service.py`** — implementare `get_grouped_markets()` reale:
   - Fetch markets come prima.
   - Se `event_id` mancante per un market (perché Gamma non l'ha incluso nel payload), fetch `list_events()` e join per `condition_id`. Cache events 5min TTL.
   - Group by `event_id` (markets con `event_id == ""` vanno ognuno in singleton group con event_id sintetico = `market.id`).
   - Ordering: gruppi ordinati per max(volume_24h) discendente; markets dentro un gruppo ordinati per `volume_24h` desc, ties broken da `id` asc (deterministic).
6. **`app/execution/engine.py`** (linee 211-249) — refactor del loop:
   - Sostituire il loop `for market in markets:` con `groups = self._market_service.group_by_event(markets, valuations)` (oppure prendere `groups` da `get_grouped_markets` se passato dall'esterno).
   - Per ogni gruppo: filtrare markets con `valuation` presente E `not in exited_market_ids`. Se gruppo vuoto, skip.
   - Determinare dominio: se tutti i markets del gruppo hanno la stessa `category`, usarla; altrimenti split del gruppo per category (vedere Ambiguità A2).
   - `applicable_strategies = self._strategies.get_for_domain(category.value)`
   - `valuations_subset = {m.id: valuations[m.id] for m in group}`
   - `result_signals = await strategy.evaluate(group, valuations_subset)` (knowledge=None per ora — vedere Ambiguità A4)
   - Resto del flow (`Signal | list[Signal] | None` handling, dedup, append a `signal_market_pairs`) invariato — usa `signal.market_id` per lookup `mkt` da `market_by_id`.
7. **`tests/test_strategies/test_legacy_adapter.py`** —
   - `test_singleton_group_returns_legacy_signal` — N=1 deve produrre stesso output di legacy
   - `test_returns_first_non_none` — N=3 dove markets[1] produce signal, markets[0] e markets[2] None → ritorna markets[1]
   - `test_all_none_returns_none`
   - `test_propagates_knowledge`
   - `test_logs_discarded_markets` (verifica che il log contiene `discarded` field)
8. **`tests/test_execution/test_engine.py`** — aggiornare:
   - I test che mockano `strategy.evaluate(market, valuation)` ora ricevono `(markets, valuations, knowledge)`. Adapter shim significa che il signal output non cambia per legacy strategies, ma la firma del mock sì.
   - Aggiungere `test_engine_groups_by_event_id` — 3 markets con stesso `event_id`, verificare che `strategy.evaluate` viene chiamata 1 volta con 3 markets.
   - Aggiungere `test_engine_singleton_groups_for_no_event_id` — markets senza `event_id` ricevono ognuno la propria call.
9. **Verifica PR-B:**
   - `pytest tests/test_strategies/ -v` — tutti gli existing tests verdi (la firma legacy è preservata via adapter)
   - `pytest tests/test_execution/test_engine.py -v`
   - `pytest tests/test_strategies/test_legacy_adapter.py -v`
   - `pytest -q` — full suite (870+ tests must stay green)
   - `ruff check && mypy --strict`

### PR-C — Migrate `value_edge` (simplest, no knowledge)

1. **`app/strategies/_group_selector.py`** (nuovo) — `pick_best(items, key)` utility (vedere "Create").
2. **`app/strategies/value_edge.py`** — riscrivere `evaluate` con nuova firma:
   - Filtrare candidates: per ogni market in `markets`, prendere `valuation = valuations[market.id]`, scartare se `confidence < min_confidence` o `|edge| < min_edge`.
   - Se nessun candidate → return None.
   - `winner, discarded = pick_best(candidates, key=lambda c: abs(c.valuation.fee_adjusted_edge) * c.valuation.confidence)`
   - Costruire Signal sul `winner` (riusando logica esistente per BUY YES vs BUY NO).
   - Log strutturato `value_edge_group_decision` con `event_id`, `winner_market_id`, `winner_score`, `discarded=[(m.id, edge, conf) for ...]`.
3. **`app/core/dependencies.py`** — registrare `ValueEdgeStrategy()` SENZA wrap (è migrata).
4. **`tests/test_strategies/test_value_edge.py`** — aggiornare `_make_market(event_id="event-1")`. Aggiornare test esistenti per chiamare `evaluate([market], {market.id: valuation})`. Aggiungere:
   - `test_picks_best_in_group` — 3 mercati, vince quello con edge × conf più alto
   - `test_returns_none_when_all_below_threshold`
   - `test_singleton_group_unchanged_behavior`
   - `test_logs_discarded_markets` (caplog)
5. **Verifica PR-C:**
   - `pytest tests/test_strategies/test_value_edge.py -v`
   - `pytest -q` — full suite
   - `ruff && mypy --strict`

### PR-D — Migrate `rule_edge`

1. `app/strategies/rule_edge.py` — analogo a PR-C. Filter: `risk_level != HIGH_RISK`, `adjusted_confidence >= MIN_CONFIDENCE`, `|edge| >= MIN_EDGE`. Score: `|fee_adjusted_edge| * adjusted_confidence`.
2. `app/core/dependencies.py` — un-wrap.
3. `tests/test_strategies/test_rule_edge.py` — update analogo a PR-C.
4. Verifica: `pytest tests/test_strategies/test_rule_edge.py -v && pytest -q`.

### PR-E — Migrate `resolution`

1. `app/strategies/resolution.py` — Filter: `end_date` within window, fair_value oltre soglia, discount sufficient. Score: `profit_after_fee` (già calcolato).
2. `app/core/dependencies.py` — un-wrap.
3. `tests/test_strategies/test_resolution.py` — update. Aggiungere caso "gruppo con N mercati, solo 1 within-window".
4. Verifica: `pytest tests/test_strategies/test_resolution.py -v && pytest -q`.

### PR-F — Migrate `sentiment`

1. `app/strategies/sentiment.py` — knowledge è gruppo-level. Filter: `|sentiment| > effective_threshold` E direzione coerente con edge. Score: `|sentiment| * |edge| * knowledge.confidence`.
2. `app/core/dependencies.py` — un-wrap.
3. `tests/test_strategies/test_sentiment.py` — update. Aggiungere test "knowledge condivisa, scelto market con edge più favorevole".
4. **Engine update**: `engine.py:225` ora passa `knowledge` (vedere PR-B step 6 — knowledge=None placeholder). In PR-F l'engine deve fornire `KnowledgeContext` per il gruppo. Vedere Ambiguità A4 per la sorgente. Decisione: leggere `knowledge` dal `external_signals` aggregato per `event_id` se disponibile, altrimenti per `condition_id` del primo market (degraded).
5. Verifica: `pytest tests/test_strategies/test_sentiment.py -v && pytest -q`.

### PR-G — Migrate `event_driven`

1. `app/strategies/event_driven.py` — analogo PR-F. Score: `|combined_edge| * adjusted_confidence` (con speed_premium baked in `combined_edge`).
2. `app/core/dependencies.py` — un-wrap.
3. `tests/test_strategies/test_event_driven.py` — update. Test specifico "speed-premium su un mercato vince anche se edge minore".
4. Verifica.

### PR-H — Migrate `knowledge_driven`

1. `app/strategies/knowledge_driven.py` — analogo PR-F. Score: `composite_confidence × |edge|`. Filter: almeno uno strong pattern matching.
2. `app/core/dependencies.py` — un-wrap.
3. `tests/test_strategies/test_knowledge_driven.py` — update.
4. Verifica.

### PR-I — Migrate `arbitrage` (eccezione documentata)

1. `app/strategies/arbitrage.py` — itera per-market dentro `evaluate`, accumula tutte le coppie YES+NO mispriced del gruppo, ritorna `list[Signal]` (concatenazione di tutte le 2-leg). Documentare nel docstring perché diverge dalla regola "1 Signal per gruppo".
2. `app/core/dependencies.py` — un-wrap.
3. `tests/test_strategies/test_arbitrage.py` — update. Aggiungere `test_returns_multiple_legs_for_group_with_multiple_misprices` e `test_returns_none_when_no_mispricing_in_group`.
4. Verifica.

### PR-J — Risk: event-level exposure cap

1. `app/risk/manager.py` — implementare `_event_exposure: dict[str, float]` e gate. `record_fill` accetta optional `event_id`; `record_close` decrementa; `check_order` blocca se `event_exposure + size > max_event_exposure_eur`.
2. `app/execution/engine.py` — passare `mkt.event_id` a `record_fill` e `check_order` (signal carry: aggiungere `event_id` a `Signal`? — preferibile leggere da `market_by_id[sig.market_id].event_id` invece di mutare `Signal`).
3. `app/core/yaml_config.py` + `config/config.example.yaml` — `risk.max_event_exposure_pct: 8.0`.
4. `tests/test_risk/test_event_exposure.py` (nuovo) — gate enforce, accumulo, reset su close, default config OK.
5. `tests/test_execution/test_engine.py` — test che engine passa `event_id` correttamente.
6. Verifica: `pytest tests/test_risk/ tests/test_execution/test_engine.py -v && pytest -q`.

### PR-K — Cleanup

1. `app/strategies/_legacy_adapter.py` — eliminare.
2. `app/strategies/registry.py` — rimuovere `wrap_legacy` helper.
3. `tests/test_strategies/test_legacy_adapter.py` — eliminare.
4. `app/strategies/base.py` — finalize Protocol (rimuovere ogni reference legacy nei docstring).
5. Grep di sicurezza: `rg "evaluate\\(market[^s]" app/ tests/` deve essere 0 hits (nessuna chiamata legacy residua).
6. Verifica finale: full suite + lint + mypy + smoke dry_run.

---

## Ambiguità note (OBBLIGATORIO)

### A1 — Popolamento di `event_id` per mercati cached vs fresh

`MarketService` ha cache TTL 300s. Se i mercati vengono caricati dalla cache, hanno già `event_id` popolato (perché la cache contiene `Market` complete). Ma se il fetch iniziale di Gamma `/markets` NON include `eventId` nel payload (verificato? — vedere assunzione 2), il primo arricchimento richiede una call separata a `/events`. Domande aperte:
- La cache deve invalidare e re-fetch eventi quando un market è "stale" sul campo `event_id` (= `""`)?
- Se Gamma `/markets` ritorna sempre `eventId` inline (non confermato dal codice attuale), tutto si semplifica. Serve una probe in produzione (o consultazione doc Gamma) prima di decidere.
- Decisione drafter: PR-A best-effort solo se inline; PR-B aggiunge fetch separato. Se Gamma include sempre eventId inline → PR-B step 5b (fetch eventi separato) è no-op.

### A2 — Mercati di un evento con `category` differenti

Un Polymarket Event può raggruppare mercati di domain diversi? (es. evento "Super Bowl 2026" è solo `sports`, ma un evento meta-prediction "2026 Q2 Recession Indicators" potrebbe mescolare crypto+economics?). Se sì, `get_for_domain(category)` non si applica clean a un gruppo eterogeneo.
- Opzione A (raccomandata dal drafter): split del gruppo per category prima di chiamare strategie. Subgruppi → call separate.
- Opzione B: usare la category del primo market (deterministico ma può sbagliare il dominio).
- Opzione C: aggiungere `Event.category` aggregato.
- **Richiede decisione utente.**

### A3 — Default `max_event_exposure_pct` (8% di equity)

Il valore 8% è un guess: con max_exposure 50% e ~6 eventi attivi tipici, 8% lascia spazio per 6 eventi pieni (50/8 ≈ 6). Possibili alternative: 10% (più aggressivo, 5 eventi), 5% (10 eventi), o config `max_concurrent_events` invece di `max_event_exposure_pct`.
- **Richiede decisione utente.** Default 8% è raccomandato dal drafter ma da validare con backtest.

### A4 — Sorgente di `KnowledgeContext` per gruppo (event-level vs market-level)

Le strategie `sentiment`, `event_driven`, `knowledge_driven` usano `knowledge.composite_signal` e `knowledge.patterns`. Oggi questi dati sono fetchati per-market in `engine.py` (vedere `_fetch_kg_signals`, `_fetch_intelligence_signals`). Per il gruppo:
- Opzione A: aggregare al livello event (median, max, weighted by volume). Cambia semantica.
- Opzione B: passare la `knowledge` del market più liquido del gruppo. Approssimazione ragionevole se i mercati di un evento condividono il context (es. tutti su stesso geopolitical event).
- Opzione C: passare un `dict[market_id, KnowledgeContext]` invece del single value e lasciare le strategie scegliere — cambia firma del Protocol.
- **Richiede decisione utente.** Drafter raccomanda opzione B (per-most-liquid-market) come transizione, con TODO per opzione A in un PR successivo.

### A5 — Cap N markets per evento

Eventi sportivi tipo "32-team Super Bowl winner" o "100+ candidates 2028 election" possono avere N>10 markets. Costi:
- VAE costa ~50-200ms per market (chiamate I/O + compute), un evento N=32 → 1.6-6.4s solo per assess_batch.
- Strategy evaluate è O(N) → trascurabile.
- **Decisione drafter**: cap a `top_K=20` per gruppo, ordinato per `volume_24h` desc. Configurable in `config/config.example.yaml` come `markets.max_per_event: 20`. **Richiede decisione utente** sul valore esatto.

### A6 — Backtesting compatibility

`app/backtesting/` carica market history da snapshot. Se gli snapshot storici NON hanno `event_id` (probabile, dato che il campo è nuovo), il backtest dopo PR-A vedrà `event_id=""` per tutti, finendo con singleton groups → comportamento identico al pre-refactor. Questa è OK come transizione, ma significa che il backtest non testerà la logica di group selection finché non si retro-popolano gli snapshot.
- **Richiede decisione utente** se serve script di backfill snapshot in PR-K.

### A7 — Modello `Event` separato vs dataclass leggero in `polymarket_rest.py`

Il drafter raccomanda creare `app/models/event.py` con `class Event(BaseModel)` per consistenza con `Market` e per type-safety nei test. Alternativa: tuple/dict locale al client per minimizzare scope. **Richiede decisione utente.**

### A8 — Rate limit Gamma `/events` vs `/markets`

`PolymarketRestClient._rate_limiter` è singolo (`_TokenBucket` da `app_config.polymarket.rate_limit`). Aggiungere `/events` raddoppia approssimativamente il volume di chiamate Gamma. Se rate_limit è già stretto, può causare backpressure.
- **Richiede decisione utente.** Mitigazioni possibili: bucket separato per `/events`, cache più aggressiva (eventi cambiano raramente, TTL 30min), o batch fetching.

### A9 — Adapter "first non-None" è cost transitivo accettabile?

L'adapter PR-B itera in-order e ritorna il primo non-None signal. Per N=5 markets dove il "best" è markets[3], l'adapter restituirà markets[0] se markets[0] produce un signal. Questo è strettamente PEGGIORE del comportamento attuale (che valuta tutti e tutti producono signal indipendenti, poi priority-sort) — riduce signals_generated.
- Mitigazione: ordering `by volume_24h desc` significa che il market più liquido viene per primo, statisticamente è anche quello con meno edge. Effetto attenuato.
- **Decisione drafter**: accettabile come transitional cost dato che (a) PR-C..PR-I si chiudono in fretta, (b) il behavior pre-refactor è già subottimale (double-exposure).
- **Richiede conferma utente** dell'accettabilità.

### A10 — Knowledge fetch path nell'engine

`engine.py` passa attualmente `external_signals` solo a VAE (linea 181). Le strategie ricevono `knowledge=None` (call site `await strategy.evaluate(market, valuation)` sulla riga 225). Nel codice attuale, **le strategie non ricevono mai `knowledge`** anche se la firma lo permette. Quindi le strategie come `sentiment`, `event_driven`, `knowledge_driven` ricevono sempre None oggi e i loro test usano factory `_make_knowledge`.
- **Implicazione**: PR-F/G/H devono ANCHE collegare il knowledge fetch al call site engine, non solo migrare la firma. Questo è una behavioral change indiretta. Richiede attenzione: i test integration potrebbero rompersi se ora le strategie iniziano a ricevere knowledge non-None.
- **Richiede decisione utente** se questo è in scope (drafter raccomanda SI, è il vero shift di comportamento atteso) o se va in plan separato.

### A11 — `Signal.event_id` vs lookup runtime

Per il gate `max_event_exposure` in `RiskManager`, serve `event_id` accanto a `token_id`. Opzioni:
- Aggiungere `event_id: str = ""` a `Signal` model (richiede update pyrobotic/serialization)
- Lookup `market_by_id[sig.market_id].event_id` runtime nell'engine prima di chiamare `record_fill`/`check_order` (drafter preferisce questa opzione, no model change).
- **Richiede decisione utente.**

### A12 — Domain split deterministica per gruppi multi-domain (collega A2)

Se un evento ha 5 markets di cui 3 sports e 2 entertainment, lo split crea 2 sub-gruppi che vengono valutati separatamente. Ma il "winner" di ognuno potrebbe causare 2 trade sullo stesso event_id, ricreando il problema di double-exposure. Il gate `max_event_exposure` (PR-J) lo previene a livello capital, ma non a livello "selezionare un solo trade per event".
- **Richiede decisione utente** se serve un secondo gate "max_signals_per_event=1" oltre al cap di esposizione.

---

## Assunzioni fatte (OBBLIGATORIO)

1. **`gamma-api.polymarket.com/events` esiste e ritorna `{id, slug, title, markets: [...], endDate, ...}`**. Confermato da uso pubblico Gamma; lo schema esatto va verificato durante PR-A (curl probe documentato).
2. **L'`Event.id` (o slug) è stabile**: non cambia tra creazione e resolution del mercato. Necessario per il gate `max_event_exposure` cross-tick.
3. **Tutti i punti di ingresso markets passano da `MarketService` o `polymarket_rest.list_markets()`**: nessun bypass diretto. Verificato per scanner; `app/backtesting/` resta separato (vedere A6).
4. **`_make_market()` factory in tutti i test esistenti accetterà `event_id` con default sintetico** (`f"event-{id}"` o `""`) senza rompere assert esistenti. Richiede update meccanico in N file di test (~7 file in tests/test_strategies + alcuni in tests/test_integration e tests/test_execution).
5. **Adapter shim "first non-None" è acceptable transitional behavior** (vedere A9).
6. **`SignalType.SELL` resta riservato a position_monitor exits** — assumiamo che il sell-fix è già mergiato; se non è, blocker.
7. **`Signal.market_id` resta il campo dominante per mapping a `Market`**; `event_id` non viene aggiunto a `Signal`, ma derivato runtime via `market_by_id[market_id].event_id` (vedere A11).
8. **Rate limit Gamma sopporta volume aggiuntivo `/events`** (verificare in PR-A; mitigazione = cache aggressiva degli events).
9. **L'engine non va riscritto in altri punti**: solo lo step 5 del tick (signal generation) cambia. Steps 1-4 (circuit breaker, position management, valuation) e 6 (risk+execute) restano per-market.
10. **Arbitrage rimane multi-leg `list[Signal]`** documentato come eccezione esplicita; è l'unica strategia per cui la regola "1 Signal per gruppo" è violata.
11. **Knowledge per gruppo è opzionale in PR-B** (passato come None); diventa obbligatoria nei PR-F/G/H (vedere A4 e A10).
12. **`pytest -q` continua a essere il comando di verifica canonico** (già usato dal progetto).
13. **Convention `ruff line-length=100`, `mypy --strict`, async-first, structlog** rispettate ovunque.
14. **`config.example.yaml` è la single source of truth** per default config; `config.yaml` non è committato.
15. **Numero di test cumulativo**: ~870 oggi; questo refactor ne aggiunge ~30-40 (gruppi, adapter, event_id, exposure cap), ne modifica ~50-80 per la firma. Tot stimato post-refactor: ~900-920.
16. **Cap top-K per evento** = 20 markets (vedere A5), configurable.
17. **Backtest snapshots NON vengono retro-popolati** in questo refactor (vedere A6); backtest behavior pre-refactor preservato (singleton groups).
18. **Il PR sequence è strettamente lineare** (PR-A → PR-K). Non parallelizzabile a livello PR perché ognuno depende dal precedente per behavior preservation. PR-D/E/F/G/H/I sono però mutually independent dopo PR-C, quindi POTREBBERO essere parallelizzati su branch separati con merge ordinato (decisione utente).

---

## Verifica

### Comandi per PR

| PR | Comando |
|----|---------|
| PR-A | `pytest tests/test_clients/test_polymarket_rest.py tests/test_clients/test_polymarket_rest_events.py tests/test_services/test_market_grouping.py -v` poi `pytest -q` |
| PR-B | `pytest tests/test_strategies/ tests/test_strategies/test_legacy_adapter.py tests/test_execution/test_engine.py -v` poi `pytest -q` |
| PR-C..PR-I | `pytest tests/test_strategies/test_<strategy>.py -v` poi `pytest -q` |
| PR-J | `pytest tests/test_risk/test_event_exposure.py tests/test_execution/test_engine.py -v` poi `pytest -q` |
| PR-K | `pytest -q` (full suite) + `rg "evaluate\\(market[^s]" app/ tests/` deve essere 0 hits |

### Comandi globali ad ogni PR

- `pytest -v --tb=short` — full suite (must stay 870+ tests green a ogni PR; conta sale a ~900-920 a fine refactor)
- `ruff check app/ tests/` — 0 errors
- `ruff format --check app/ tests/` — 0 diffs
- `mypy app/ --strict` — 0 errors

### Smoke manuale (PR-J e PR-K)

1. Avviare bot in `dry_run` mode contro Polymarket live: `python -m app.main` con `EXECUTION_MODE=dry_run`.
2. Trovare un evento ladder noto (es. "BTC price end of month" con N markets a strike differenti).
3. Verificare nei log JSON:
   - `event_id` popolato sui mercati di quell'evento
   - `value_edge_group_decision` log con `winner_market_id` e `discarded` non vuoto
   - `position_opened` su un solo mercato del gruppo (non N)
   - `event_exposure` accumulato in `RiskKB` (PR-J)
4. Restart del bot: `event_id` deve essere persistito (cache 5min) o re-fetchato senza errori.

### Done conditions (intero refactor, post PR-K)

- [ ] Tutti i 870+ test originali verdi + ~30-40 nuovi (totale ~900-920) verdi
- [ ] `LegacyStrategyAdapter` rimosso; nessuna chiamata `evaluate(market, valuation)` legacy in app/ o tests/
- [ ] 7 strategie tutte conformi al nuovo Protocol
- [ ] `BaseStrategy.evaluate` ha la firma `(markets, valuations, knowledge=None)` e basta
- [ ] `Market` model ha `event_id` populated end-to-end (Gamma fetch → cache → engine → strategy → signal)
- [ ] `RiskManager` rispetta `max_event_exposure_pct`
- [ ] Smoke dry_run mostra group selection in azione (log `*_group_decision`)
- [ ] `ruff` + `mypy --strict` 0 errors
- [ ] Lessons.md aggiornato con eventuali gotcha emersi durante l'esecuzione

---

## Note finali per Round 2 (Codex review)

Questo draft assume:
- SELL-fix già mergiato (orthogonal hotfix)
- Gamma `/events` schema da verificare in PR-A
- 12 ambiguità esplicite richiedono decisione utente prima del freeze del plan

Punti deboli che il critic dovrebbe colpire:
1. A4 (knowledge per gruppo) è probabilmente la decisione più impattante e meno fondata.
2. A9 (adapter first-non-None) è una regressione transitoria — sopportabile?
3. A11 (Signal.event_id) — ho scelto runtime lookup ma potrebbe non scalare se Signal viene serializzato altrove.
4. PR sequence stringe: nessun rollback intra-PR (ogni PR è atomic).
5. Backfill snapshot per backtesting (A6) non è in scope; verificare se è un blocker per validare il refactor con dati storici.
