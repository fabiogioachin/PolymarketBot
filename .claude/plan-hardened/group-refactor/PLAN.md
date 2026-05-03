# PLAN.md — Group-aware refactor (FINAL)

**Pipeline**: /plan-hardened
**Status**: FINAL — all Round 4 decisions resolved.
**Round 2 input**: 22 Codex issues — 22 VALID merged, 0 INVALID rejected, 0 NEEDS_USER (Q1=A, Q2=B in Round 4)
**Round 3 reviewer additions**: 3 R3- issues Codex missed (R3-01, R3-02, R3-03)
**Round 4 user decisions**: Q1=A (full scope expansion), Q2=B (split per category, then arbiter)
Generated: 2026-05-02

---

## Preflight precondition (BLOCKING — must pass before PR-A starts)

<!-- R2-15 merged -->

**The SELL→BUY-NO hotfix is NOT confirmed merged in the working tree.** Spot-check at `app/strategies/sentiment.py:143` shows `return SignalType.SELL` for bearish-aligned entry signals; analogous code paths in `event_driven.py` and `knowledge_driven.py` must also be verified. PR-A cannot start until the following preflight is green:

1. `rg -n "return\s+SignalType\.SELL" app/strategies/sentiment.py app/strategies/event_driven.py app/strategies/knowledge_driven.py` returns 0 hits, OR each remaining hit is in a code path provably unreachable from `evaluate(...)` for entry signals (must be commented inline as such).
2. `rg -n "BUY.*NO|buy_no|SignalType\.BUY.*outcome.*no" app/strategies/sentiment.py` confirms bearish path now emits BUY on the NO token.
3. Tests `tests/test_strategies/test_sentiment.py`, `test_event_driven.py`, `test_knowledge_driven.py` have at least one case verifying bearish entries return `SignalType.BUY` with `token_id` of the NO outcome.

If preflight fails: STOP. The hotfix must merge first via its own (out-of-scope) plan. Do NOT begin PR-A; do NOT silently ship the bug; do NOT inline-fix the hotfix here (that would be unauthorized scope creep into 3 strategy files for non-refactor reasons).

---

## Obiettivo

Far sì che il bot scelga la **migliore alternativa all'interno di un ladder di mercati raggruppati** (un Polymarket Event con N mercati correlati) invece di valutare ciascun mercato in isolation, così evitando double-exposure su event family e privilegiando il mercato con edge atteso più alto. Nuova firma cardinale: `BaseStrategy.evaluate(markets, valuations, knowledge=None) -> Signal | list[Signal] | None`, con `markets: list[Market]` di lunghezza 1..N appartenente allo stesso `event_id`.

---

## File impattati

### Modify (production)

- `app/models/market.py` — aggiungere `event_id: str = ""` e `event_slug: str = ""` al `Market` model (Pydantic v2). Non computed: popolati upstream dal client Gamma. <!-- R2-04 merged: lightweight Event payload stays inside polymarket_rest.py, no new app/models/event.py -->
- `app/clients/polymarket_rest.py` — aggiungere `list_events(...)` e `get_event(event_id)` che chiamano `GET /events` su `gamma-api.polymarket.com`; introdurre `_parse_event(...)` helper; introdurre **module-private dataclass `_EventPayload`** (or `TypedDict`) per il return type interno. <!-- R2-04: nessun nuovo file app/models/event.py senza scope expansion --> <!-- R2-05: NON estendere `_parse_market` per leggere `eventId` inline; il grouping deriva esclusivamente da `/events` -->
- `app/services/market_service.py` — nuovo `get_grouped_markets(...)` che ritorna `list[list[Market]]` (gruppi per event_id), oltre a mantenere l'attuale `get_filtered_markets()` per backward compat. Cache TTL deve essere aware del nuovo metodo (chiave separata, vedere R2-20). <!-- R2-09 merged: API canonica = MarketService.get_grouped_markets -->
- `app/services/market_scanner.py` — nessun nuovo helper `group_by_event` esposto. Il grouping vive solo in `MarketService`. <!-- R2-09 merged: rimosso ramo "oppure" -->
- `app/strategies/base.py` — riscrivere il `Protocol` con la nuova firma `evaluate(markets, valuations, knowledge=None)`. Mantenere temporaneamente un secondo metodo opzionale `evaluate_legacy(market, valuation, knowledge=None)` (default-implementabile? No — Protocol non supporta default; vedere step) — gestito tramite **adapter wrapper class** (vedere PR-B), non come metodo del Protocol.
- `app/strategies/registry.py` — `get_for_domain(domain)` continua a operare su un singolo dominio. Aggiungere helper `wrap_legacy(strategy)` che restituisce un wrapper conforme alla nuova `BaseStrategy` per le strategie non ancora migrate.
- `app/strategies/_legacy_adapter.py` (nuovo) — `class LegacyStrategyAdapter` che implementa il nuovo Protocol e delega per-market alla strategia legacy. **Evaluate-all-then-pick-best**, non first-non-None. Vedere PR-B step 2 e R2-12. <!-- R2-12 merged -->
- `app/execution/engine.py` (linee 211-249, focus 222-225) — il loop diventa: per ogni gruppo di mercati con stesso `event_id` e stesso dominio, costruire `valuations_by_market_id` per il gruppo e chiamare `strategy.evaluate(group, valuations_by_id)`. Mantenere il dedup `open_position_token_ids` e il filtro `exited_market_ids`. La riga 222 (`get_for_domain(market.category.value)`) si sposta a livello gruppo (mixed-category policy: split per category, vedere PR-B step 6 — Q2=B). **Aggiungere step 5d: arbiter event-level cross-strategy**, vedere R2-11. <!-- R2-09, R2-10, R2-11, R2-21 merged --> Engine deve anche acquisire un **tick-level asyncio.Lock** che wrappa il blocco `check_order` → `record_fill` per atomic reserve (R2-17, vedere PR-J).
- `app/strategies/value_edge.py` — migrare a nuova firma. Selettore: argmax di `fee_adjusted_edge` × `confidence` tra i mercati del gruppo che superano `min_edge` e `min_confidence`. Loggare gli scartati.
- `app/strategies/rule_edge.py` — migrare. Selettore: argmax di `|fee_adjusted_edge|` × `adjusted_confidence` tra i mercati che passano i gate (skip HIGH_RISK, soglie). Loggare scartati.
- `app/strategies/resolution.py` — migrare. Selettore: argmax di `profit_after_fee` (calcolo già locale) tra i mercati che passano gate (entro `MAX_DAYS_TO_RESOLUTION`, `discount >= MIN_DISCOUNT`).
- `app/strategies/sentiment.py` — migrare. Selettore: argmax di `|sentiment| × |edge|` tra i mercati allineati (sentiment direction == edge direction). Knowledge è gruppo-level (default fixed: knowledge dal market più liquido del gruppo, vedere R2-14). <!-- R2-14 merged with default: most-liquid-market source -->
- `app/strategies/event_driven.py` — migrare. Selettore: argmax di `|combined_edge| × adjusted_confidence`. Speed-premium per pattern freschi conservato. Knowledge gruppo-level (default fixed come sentiment).
- `app/strategies/knowledge_driven.py` — migrare. Selettore: argmax di `composite_confidence × |edge|` tra mercati con strong patterns matchanti.
- `app/strategies/arbitrage.py` — migrare con **eccezione esplicita** documentata: itera per-market e ritorna `list[Signal]` aggregando tutte le coppie YES/NO mispriced del gruppo (multi-leg legittimo, non "winner-takes-all"). Documentare nel docstring perché diverge dalla regola "1 Signal per gruppo". <!-- R2-13: arbitrage MUST be migrated in PR-B (not waiting for PR-I) OR the legacy adapter must list-aggregate for arbitrage; vedere PR-B step 2b -->
- `app/risk/manager.py` — implementare `_event_exposure: dict[str, float]` keyed by event_id, `_token_to_event: dict[str, str]`, e gate `max_event_exposure_pct`. Aggiungere `event_id` parameter a `check_order(...)` e `record_fill(...)`. `record_close(token_id)` decrementa exposure usando `_token_to_event`. `restore_from_store()` ricostruisce entrambe le mappe. <!-- R2-01, R2-16 merged via Q1=A -->
- `app/core/dependencies.py` — wireup strategie wrapped/un-wrapped lungo PR-B..PR-K. Wraps 6 strategie con `LegacyStrategyAdapter(strategy)` in PR-B; arbitrage wrapped con `LegacyStrategyAdapter(arbitrage, aggregate_lists=True)`. Un-wrap progressivo PR-C..PR-I. Final cleanup PR-K. Wireup `max_event_exposure_pct` e `markets.max_per_event` da config. <!-- R2-02, R3-01 merged via Q1=A -->
- `app/core/yaml_config.py` — aggiungere `risk.max_event_exposure_pct: float = 0.20` (default 20% di max_exposure) e `markets.max_per_event: int = 20` (top-K cap). <!-- R2-03, R2-10 merged via Q1=A -->
- `config/config.example.yaml` — mirror dei due nuovi campi con commenti. <!-- R2-03 merged via Q1=A -->
- `app/execution/trade_store.py` — aggiungere colonna `event_id` allo schema row trades/positions; persist `event_id` accanto a `token_id`. `restore_from_store` legge `event_id` per ricostruire `RiskManager._event_exposure`. **Transitive dependency di PR-J — esplicitamente in scope autorizzato (Q1=A)**. <!-- R2-16 merged -->

### Create (new files)

- `app/strategies/_legacy_adapter.py` — `LegacyStrategyAdapter` (PR-B). Wraps any old-style strategy con `evaluate(market, valuation, knowledge)` e la espone con la nuova firma `evaluate(markets, valuations, knowledge)`. **Strategia di selezione**: evaluate-all + deterministic best-pick (NOT first-non-None). Vedere R2-12. **Caso speciale arbitrage**: vedere PR-B step 2b e R2-13.
- `app/strategies/_group_selector.py` (opzionale ma consigliato) — utility `pick_best(items, key) -> tuple[Item, list[Item]] | None`. Estrarre in PR-C.
- `tests/test_clients/test_polymarket_rest_events.py` — copertura per `list_events`, `get_event`, parsing event payload con N markets, **pagination, 429/503/empty, missing condition_id joins**. <!-- R2-06, R2-07 merged -->
- `tests/test_strategies/test_legacy_adapter.py` — verifica che `LegacyStrategyAdapter` (a) preservi semantica per N=1, (b) selezioni il best signal per N>1, (c) propaghi `knowledge`, (d) **aggreghi list[Signal] per arbitrage** (R2-13).
- `tests/test_strategies/test_group_selector.py` (se introdotto in PR-C) — corner cases: empty list, single item, ties.
- `tests/test_risk/test_event_exposure.py` — gate `max_event_exposure_pct`, accumulo per `event_id`, reset su `record_close`, **persistence cross-restart e atomic reserve-and-record concurrency** (R2-16, R2-17).
- `tests/test_services/test_market_grouping.py` — `group_by_event` raggruppa correttamente, **NEVER falls back to inline /markets eventId** (R2-05), **fail-closed quando /events fallisce** (R2-06), **pagination beyond limit=100** (R2-07), ordering deterministico, **stale empty event_id cache recovery** (R2-20).
- `tests/test_execution/test_engine.py` (modify, non new) — aggiungere casi: `test_arbiter_picks_one_winner_per_event_across_strategies` (R2-11), `test_drops_signal_with_market_id_outside_group` (R2-21), `test_top_k_cap_applied_before_vae_for_large_event` (R2-10), `test_mixed_category_event_split_into_subgroups_then_arbiter_picks_one` (Q2=B / R2-18).

### Modify (tests)

<!-- R2-19 merged: enumerazione esplicita per ogni strategy migration -->

- `tests/test_strategies/test_value_edge.py` — aggiornare `_make_market()` per accettare `event_id`. Casi obbligatori (PR-C): (1) singleton group unchanged behavior, (2) N>1 winner picked correctly, (3) all filtered → None, (4) tie broken by deterministic id ordering, (5) market with missing valuation skipped, (6) legacy signature removed.
- `tests/test_strategies/test_rule_edge.py` — stessi 6 casi (PR-D), più: HIGH_RISK skippato dentro un gruppo misto, AMBIGUOUS scelto se è il migliore.
- `tests/test_strategies/test_resolution.py` — stessi 6 casi (PR-E), più: gruppo con solo un mercato within-window, gruppo con tutti out-of-window → None.
- `tests/test_strategies/test_sentiment.py` — stessi 6 casi (PR-F), più: edge directions differenti nel gruppo, **knowledge dal market più liquido** (R2-14), **missing knowledge → degraded behavior** (R2-14), **stale knowledge** (R2-14).
- `tests/test_strategies/test_event_driven.py` — stessi 6 casi (PR-G), più: speed-premium su un mercato vs altri freddi, knowledge most-liquid.
- `tests/test_strategies/test_knowledge_driven.py` — stessi 6 casi (PR-H), più: gruppo senza pattern matching → None.
- `tests/test_strategies/test_arbitrage.py` — stessi 6 casi (PR-I), più: ritorna `list[Signal]` aggregata multi-leg, ritorna None se nessun mispricing.
- `tests/test_strategies/test_registry.py` — `get_for_domain` invariato, ma aggiungere test che `wrap_legacy` produce un wrapper conforme.
- `tests/test_execution/test_engine.py` — aggiornare i test che mockano `strategy.evaluate(market, valuation)` alla nuova firma. Aggiungere test che engine raggruppa per `event_id`, che chiama `evaluate` una volta per gruppo, **arbiter event-level** (R2-11), **out-of-group market_id rejection** (R2-21), **top-K cap pre-VAE** (R2-10), **mixed-category split + arbiter** (Q2=B / R2-18), **tick-level lock around reserve+record** (R2-17).
- `tests/test_integration/test_probability_calculation.py` — verificare che il flow end-to-end funzioni con mercati raggruppati.
- `tests/test_integration/test_storage_retrieval.py` e `test_cross_source_flow.py` — review e aggiornare se assumono single-market evaluate.

### Out of scope (do NOT modify)

- `app/execution/position_monitor.py` — gestione exit (TP/SL/expiry/edge-evaporated) è per-position, non per-group. Non toccare.
- `app/execution/executor.py` — il mapping `Signal → OrderRequest` resta invariato.
- `app/valuation/engine.py` — VAE resta per-market. `assess_batch` continua a ritornare `list[ValuationResult]` indipendenti (ogni mercato del gruppo riceve la sua valutazione). **Il top-K cap (R2-10) avviene PRIMA di chiamare `assess_batch`, non dentro VAE.**
- `app/models/signal.py` — `Signal` model invariato.
- `app/models/valuation.py` — `ValuationResult` invariato.
- `app/models/event.py` — **NON creare** (R2-04). `_EventPayload` vive privato dentro `polymarket_rest.py`.
- `app/strategies/__init__.py` — solo aggiungere export del nuovo `_legacy_adapter` se necessario.
- File del SELL→BUY-NO hotfix: vedere Preflight precondition. Questo plan PARTE DALLO STATO POST-FIX. Nessuna modifica per fix qui.
- `.claude/plan-hardened/sell-fix/` — no-touch (archivio).
- `.claude/tasks/lessons.md` — **rimosso da done conditions**, vedere R2-22. <!-- R2-22 merged -->
- `app/api/v1/` — endpoint dashboard/markets non cambiano contract.
- `static/` — non toccato.
- `app/backtesting/` — vedere Ambiguità A6 (residua come informativa).

---

## Step di implementazione

### PR-A — Foundation (zero behavior change)

**Goal:** introdurre `event_id` lungo la pipeline senza che nessuno lo usi ancora. Tutti i test esistenti verdi.

1. **`app/models/market.py`** — aggiungere `event_id: str = ""` e `event_slug: str = ""`. Default empty per backward compat. Update docstring.
2. **`app/clients/polymarket_rest.py`** — <!-- R2-04, R2-05, R2-07, R2-08 merged -->
   - Definire **`_EventPayload`** dataclass (or `TypedDict`) module-private: `id: str`, `slug: str`, `title: str`, `end_date: datetime | None`, `market_ids: list[str]` (using market `id`), `condition_ids: list[str]` (using `conditionId`). **Schema contract frozen**: il join key primario è `conditionId`, fallback secondario `id`. Inconsistent mappings (event references condition_id non in any returned market) sono LOGGATE e SCARTATE — non si guess (R2-08).
   - **NON** estendere `_parse_market` per leggere `eventId`/`event`/`events` inline. Il `event_id` su `Market` resta `""` dopo `_parse_market` (R2-05). Diagnostic-only logging if inline fields are present (per future debugging) ma NEVER usati per grouping.
   - Aggiungere `_parse_event(data) -> _EventPayload`.
   - Aggiungere `async def list_events(active=True, limit=100, max_pages=20) -> list[_EventPayload]`. **Pagination loop**: incrementa `offset` di `limit` finché una pagina ritorna `< limit` records, fino a `max_pages * limit` (default 2000). Log warning se cap raggiunto (R2-07).
   - Aggiungere `async def get_event(event_id) -> _EventPayload | None` su `/events/{id}`.
   - Stesso `_TokenBucket` rate limiter (Ambiguità A8 residua per future tuning).
3. **`app/services/market_service.py`** —
   - Quando si chiama `list_markets()`, NON cambiare path principale. NON fare arricchimento "best-effort se Gamma include `eventId` inline" — quello è esplicitamente vietato da R2-05.
   - Aggiungere `get_grouped_markets()` che oggi ritorna `[[m] for m in get_filtered_markets()]` (singleton groups con `event_id=""`) — placeholder che PR-B sostituirà.
4. **`tests/test_clients/test_polymarket_rest_events.py`** — test cases: parse OK, event con 1 market, event con N markets, **pagination beyond limit=100 (R2-07)**, **429 retry behavior, 503 retry behavior, empty events response (R2-06)**, **missing condition_id join → logged + skipped (R2-08)**.
5. **`tests/test_services/test_market_grouping.py`** — placeholder test che `get_grouped_markets()` oggi ritorna singletons, ognuno con `event_id == ""`.
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

2. **`app/strategies/_legacy_adapter.py`** (nuovo) — <!-- R2-12, R2-13 merged -->
   - `class LegacyStrategyAdapter`:
     - `__init__(self, legacy_strategy, *, aggregate_lists: bool = False)` — `aggregate_lists=True` per arbitrage; default False (single-winner mode).
     - `evaluate(self, markets, valuations, knowledge=None)`:
       - Per ogni `m in markets`: `v = valuations.get(m.id)`; if None continue; chiama `legacy.evaluate(m, v, knowledge)`; raccogli (market_id, result) in `per_market_results`.
       - Filter: scarta entries con `result is None` o `result == HOLD`.
       - **Se `aggregate_lists=True` (arbitrage path):** flatten tutti `list[Signal]` results, ritorna `list[Signal]` concatenata. Non filtrare per "best".
       - **Else (default — single-winner):**
         - Per ogni Signal residuo, calcola priority = `abs(signal.edge_amount) * signal.confidence` (se entrambi None → 0). Ties broken by `(market_id_lex_asc, signal_type_value)`.
         - Pick argmax. Log strutturato `legacy_adapter_picked` con `event_id`, `market_id_winner`, `discarded=[(m.id, score) for ...]`.
         - Return Signal singolo (non lista).
       - Return None se `per_market_results` vuoto.

   2b. **Caso speciale arbitrage**: in `app/core/dependencies.py` (vedere step 4), wrap arbitrage con `LegacyStrategyAdapter(arbitrage_strategy, aggregate_lists=True)`. **Alternativa robusta**: migrare arbitrage direttamente in PR-B (anticipando PR-I). Decisione drafter: usare `aggregate_lists=True` flag. Se in test emergono regressioni, anticipare migration in PR-B.

3. **`app/strategies/registry.py`** — aggiungere `wrap_legacy(strategy, *, aggregate_lists=False) -> BaseStrategy` factory.

4. **`app/core/dependencies.py`** — al momento di registrare le 7 strategie, wrappare 6 con `LegacyStrategyAdapter(strategy)` e arbitrage con `LegacyStrategyAdapter(arbitrage, aggregate_lists=True)`. (Quando una strategia sarà migrata, si registrerà direttamente senza wrap.) <!-- Q1=A authorized -->

5. **`app/services/market_service.py`** — implementare `get_grouped_markets()` reale: <!-- R2-05, R2-06, R2-09, R2-10, R2-20 merged -->
   - Fetch markets come prima (NO inline event_id reading).
   - Fetch eventi via `list_events()` con pagination (R2-07). Cache eventi separata, **TTL 30 min** (events change less frequently than markets) e versionata: `grouping_version: int` incrementato a ogni successful refresh (R2-20).
   - Build `event_id_by_condition_id: dict[str, str]` join map dal payload eventi.
   - Per ogni market: `event_id = event_id_by_condition_id.get(market.condition_id, "")`. NON guess; NON fallback inline.
   - **Fail-closed policy** (R2-06): se la chiamata `list_events()` fallisce (post-retry — RuntimeError dopo `max_retries`) o ritorna lista vuota o non contiene join match per ≥50% dei markets attivi (threshold configurabile), tutti i markets vengono marcati `grouping_incomplete=True` (campo NUOVO temporaneo? o flag su `MarketService` state?). **Decisione drafter: `MarketService` espone un flag `last_grouping_incomplete: bool` letto dall'engine; markets con `event_id == ""` in stato `grouping_incomplete` sono SKIPPED da `get_grouped_markets()` per il tick corrente** (no singleton fallback).
   - Cache invalidation (R2-20): se `event_id == ""` su un market già in cache, ma il successivo `list_events()` ha un join match per quel `condition_id`, invalidare la entry market e re-fetch. Mai riusare cached `event_id == ""` dopo successful refresh.
   - **Top-K cap PRE-VAE (R2-10)**: dentro `get_grouped_markets()`, dopo grouping, applicare cap `top_K=markets.max_per_event` (default 20, configurabile via yaml_config). Ordering: `volume_24h` desc, ties → `id` asc. Markets scartati sono LOGGED ma NON valutati. R3-03 caveat: l'engine deve usare il dict `market_by_id` costruito DOPO il top-K cap, non quello pre-cap.
   - Group ordering: gruppi ordinati per max(volume_24h) discendente; markets dentro un gruppo già ordinati come sopra.

6. **`app/execution/engine.py`** (linee 211-249) — refactor del loop: <!-- R2-09, R2-10, R2-11, R2-21 merged -->
   - **Step 5a — Top-K cap**: il top-K è già applicato da `MarketService` (R2-10). L'engine riceve markets già capped. NON valutare markets oltre il cap.
   - **Step 5b — Loop per gruppi**: `groups = self._market_service.get_grouped_markets()` (single API; ramo "oppure" rimosso, R2-09).
   - Per ogni gruppo: filtrare markets con `valuation` presente E `not in exited_market_ids`. Se gruppo vuoto, skip.
   - **Determinare dominio** (Q2=B / R2-18 merged): se tutti i markets del gruppo hanno la stessa `category`, esegui un singolo `get_for_domain(category)`. Se group ha markets con category eterogenee, split in subgroups per category, esegui `get_for_domain(category)` per ogni subgroup, raccogli i Signal per-subgroup. L'arbiter R2-11 a fine tick deduplica per event_id (subgroups dello stesso event_id che producono winners differenti vengono ridotti a 1 winner totale).
   - `applicable_strategies = self._strategies.get_for_domain(category.value)` (per gruppo o subgroup)
   - `valuations_subset = {m.id: valuations[m.id] for m in group_or_subgroup}`
   - `result_signals = await strategy.evaluate(group_or_subgroup, valuations_subset, knowledge=...)` dove `knowledge` è quella del market più liquido del gruppo (R2-14 default; PR-F implementa il fetch concreto).
   - **Step 5b-validate (R2-21)**: per ogni `sig` in `result_signals`, se `sig.market_id not in {m.id for m in group_or_subgroup}` → log `invalid_strategy_signal` con strategy name, market_id, group event_id e SCARTA il signal. Non aggiungerlo a `signal_market_pairs`.
   - Resto del flow (`Signal | list[Signal] | None` handling, dedup, append a `signal_market_pairs`) invariato — usa `signal.market_id` per lookup `mkt` da `market_by_id`.
   - **Step 5d — Event-level cross-strategy arbiter (R2-11)**: dopo la priority sort esistente (linee 251-264), prima di andare in execution loop, applicare:
     - `non_arb_signals = [pair for pair in signal_market_pairs if pair[0].strategy != "arbitrage"]`
     - `arb_signals = [pair for pair in signal_market_pairs if pair[0].strategy == "arbitrage"]`
     - Group `non_arb_signals` by `mkt.event_id`. Per ogni event_id con > 1 signal (sia da strategie multiple sia da subgroups multipli, Q2=B), keep only the highest priority (la sort esistente ha già definito l'ordering — pick first per event_id).
     - `signal_market_pairs = winners_by_event + arb_signals` (arbitrage retains its multi-leg exception).
     - Log strutturato `event_arbiter_decision` con event_id, winner.strategy/winner.market_id, dropped=[(strategy, market_id) for ...].
   - **Step 5e — Tick-level atomic lock (R2-17)**: l'engine acquisisce un `asyncio.Lock` (instance attribute `self._tick_lock`) PRIMA del blocco execution loop che effettua `risk_manager.check_order(...)` seguito da `risk_manager.record_fill(...)`. Lock release alla fine del tick. Drafter motivation: 1 lock vs. per-call locking; non frammenta la RiskManager API. Concurrent ticks per stesso event_id non possono entrambe superare il cap.

7. **`tests/test_strategies/test_legacy_adapter.py`** —
   - `test_singleton_group_returns_legacy_signal` — N=1 deve produrre stesso output di legacy.
   - `test_picks_best_signal_for_n_gt_one` — N=3 dove markets[0] ha priority=0.05, markets[1] 0.10, markets[2] 0.07 → ritorna markets[1]. <!-- R2-12 merged: NOT first-non-None -->
   - `test_ties_broken_by_market_id_asc` — 2 markets con identical priority → vince market.id alfabeticamente minore.
   - `test_all_none_returns_none`.
   - `test_propagates_knowledge`.
   - `test_logs_discarded_markets_with_scores`.
   - `test_aggregates_lists_for_arbitrage_mode` — `aggregate_lists=True` con 2 markets ognuno mispriced → ritorna list[Signal] di lunghezza 4 (2 leg × 2 markets). <!-- R2-13 merged -->

8. **`tests/test_execution/test_engine.py`** —
   - Aggiornare i test che mockano `strategy.evaluate(market, valuation)` alla nuova firma.
   - `test_engine_groups_by_event_id` — 3 markets stesso event_id, `evaluate` chiamata 1 volta con 3 markets.
   - `test_engine_singleton_groups_for_no_event_id` — markets senza event_id NON ricevono call quando `last_grouping_incomplete=True`. <!-- R2-06 merged: fail-closed -->
   - `test_skips_markets_when_grouping_incomplete` — flag set → tutti i markets con event_id="" sono skipped per il tick.
   - `test_arbiter_picks_one_winner_per_event_across_strategies` — 2 strategie ritornano signals per stesso event (3 markets totali) → arbiter tiene 1 winner non-arbitrage. <!-- R2-11 merged -->
   - `test_arbiter_preserves_arbitrage_multi_leg` — arbitrage list[Signal] passa through arbiter unchanged.
   - `test_drops_signal_with_market_id_outside_group` — mock strategy ritorna signal con market_id non nel gruppo → signal scartato, log emesso. <!-- R2-21 merged -->
   - `test_top_k_cap_applied_before_vae_for_large_event` — event con N=50 markets, `assess_batch` chiamato con max 20 markets (i top-20 per volume_24h). <!-- R2-10 merged -->
   - `test_mixed_category_event_split_into_subgroups_then_arbiter_picks_one` — event con 5 markets di cui 3 sports e 2 entertainment → split in 2 subgroups, ogni subgroup chiama `get_for_domain(category)`, arbiter event-level riduce a 1 winner per event_id. <!-- Q2=B / R2-18 merged -->

9. **Verifica PR-B:**
   - `pytest tests/test_strategies/ -v`
   - `pytest tests/test_execution/test_engine.py -v`
   - `pytest tests/test_strategies/test_legacy_adapter.py -v`
   - `pytest -q` — full suite (870+ tests must stay green)
   - `ruff check && mypy --strict`

### PR-C — Migrate `value_edge` (simplest, no knowledge)

1. **`app/strategies/_group_selector.py`** (nuovo) — `pick_best(items, key)` utility.
2. **`app/strategies/value_edge.py`** — riscrivere `evaluate` con nuova firma:
   - Filtrare candidates: per ogni market in `markets`, prendere `valuation = valuations[market.id]`, scartare se `confidence < min_confidence` o `|edge| < min_edge`.
   - Se nessun candidate → return None.
   - `winner, discarded = pick_best(candidates, key=lambda c: abs(c.valuation.fee_adjusted_edge) * c.valuation.confidence)`
   - Costruire Signal sul `winner`.
   - Log strutturato `value_edge_group_decision`.
3. **`app/core/dependencies.py`** — registrare `ValueEdgeStrategy()` SENZA wrap.
4. **`tests/test_strategies/test_value_edge.py`** — 6 casi obbligatori (vedere "Modify (tests)"): singleton unchanged, N>1 winner, all filtered → None, tie by id, missing valuation skipped, legacy signature removed. <!-- R2-19 merged -->
5. **Verifica PR-C:**
   - `pytest tests/test_strategies/test_value_edge.py -v`
   - `pytest -q` — full suite
   - `ruff && mypy --strict`

### PR-D — Migrate `rule_edge`

1. `app/strategies/rule_edge.py` — Filter: `risk_level != HIGH_RISK`, `adjusted_confidence >= MIN_CONFIDENCE`, `|edge| >= MIN_EDGE`. Score: `|fee_adjusted_edge| * adjusted_confidence`.
2. `app/core/dependencies.py` — un-wrap.
3. `tests/test_strategies/test_rule_edge.py` — 6 casi obbligatori + HIGH_RISK skippato in gruppo misto + AMBIGUOUS scelto se best.
4. Verifica.

### PR-E — Migrate `resolution`

1. `app/strategies/resolution.py` — Filter: `end_date` within window, fair_value oltre soglia, discount sufficient. Score: `profit_after_fee`.
2. `app/core/dependencies.py` — un-wrap.
3. `tests/test_strategies/test_resolution.py` — 6 casi + gruppo con solo 1 within-window + tutti out-of-window → None.
4. Verifica.

### PR-F — Migrate `sentiment`

1. `app/strategies/sentiment.py` — knowledge è gruppo-level (most-liquid). Filter: `|sentiment| > effective_threshold` E direzione coerente con edge. Score: `|sentiment| * |edge| * knowledge.confidence`.
2. `app/core/dependencies.py` — un-wrap.
3. `tests/test_strategies/test_sentiment.py` — 6 casi + edge directions differenti + **knowledge dal market più liquido** + missing knowledge → None graceful + stale knowledge handling. <!-- R2-14 merged -->
4. **Engine update**: `engine.py` ora popola `knowledge` per il gruppo. Source: knowledge del market con `volume_24h` massimo nel gruppo. Implementazione: `most_liquid = max(group, key=lambda m: m.volume_24h or 0.0)`; `knowledge = await self._fetch_knowledge_for_market(most_liquid)`. Se fetch fallisce → log e passa `None` (degraded behavior, NON fail-closed).
5. Verifica.

### PR-G — Migrate `event_driven`

1. `app/strategies/event_driven.py` — analogo PR-F. Score: `|combined_edge| * adjusted_confidence`.
2. `app/core/dependencies.py` — un-wrap.
3. `tests/test_strategies/test_event_driven.py` — 6 casi + speed-premium su un mercato vince + most-liquid knowledge.
4. Verifica.

### PR-H — Migrate `knowledge_driven`

1. `app/strategies/knowledge_driven.py` — analogo PR-F. Score: `composite_confidence × |edge|`. Filter: almeno uno strong pattern matching.
2. `app/core/dependencies.py` — un-wrap.
3. `tests/test_strategies/test_knowledge_driven.py` — 6 casi + gruppo senza pattern matching → None.
4. Verifica.

### PR-I — Migrate `arbitrage` (eccezione documentata)

1. `app/strategies/arbitrage.py` — itera per-market dentro `evaluate`, accumula tutte le coppie YES+NO mispriced del gruppo, ritorna `list[Signal]`. Documentare nel docstring.
2. `app/core/dependencies.py` — un-wrap (rimuove `aggregate_lists=True` adapter).
3. `tests/test_strategies/test_arbitrage.py` — 6 casi + `test_returns_multiple_legs_for_group_with_multiple_misprices` + `test_returns_none_when_no_mispricing_in_group`.
4. Verifica.

### PR-J — Risk: event-level exposure cap

**Status**: AUTHORIZED via Q1=A. Full scope expansion approved. Persistence (R2-16) + atomic reserve (R2-17) included. <!-- Q1=A merged -->

1. **`app/core/yaml_config.py`** — aggiungere alla sezione `risk` Pydantic block: `max_event_exposure_pct: float = 0.20` (default 20% della max_exposure totale). Aggiungere alla sezione `markets`: `max_per_event: int = 20` (top-K cap per evento). Entrambi con validators Pydantic standard (es. `Field(gt=0, le=1.0)` per pct, `Field(gt=0, le=100)` per max_per_event).

2. **`config/config.example.yaml`** — mirror dei due nuovi campi:
   ```yaml
   risk:
     max_event_exposure_pct: 0.20  # max 20% of total exposure cap on a single event_id
   markets:
     max_per_event: 20  # top-K markets per event by volume_24h, evaluated by VAE
   ```

3. **`app/risk/manager.py`** — implementare event-level exposure tracking: <!-- R2-16, R2-17 merged via Q1=A -->
   - Aggiungere state: `_event_exposure: dict[str, float]` (event_id → EUR), `_token_to_event: dict[str, str]` mantenuto in sync con `_current_positions`.
   - Aggiungere parametro `max_event_exposure_pct: float` a `RiskManager.__init__`.
   - Aggiornare `check_order(...)`: aggiungere parametro `event_id: str | None`. Se `event_id` non vuoto, calcolare `event_exposure_eur = self._event_exposure.get(event_id, 0.0) + size_eur` e bloccare se `event_exposure_eur > max_event_exposure_pct * max_exposure_eur`. Return `RiskCheckResult` with reason `"event_exposure_exceeded"` quando blocca.
   - Aggiornare `record_fill(...)`: aggiungere parametro `event_id: str | None`. Se non vuoto, `self._event_exposure[event_id] += size_eur` e `self._token_to_event[token_id] = event_id`.
   - Aggiornare `record_close(token_id)`: lookup `event_id = self._token_to_event.pop(token_id, None)`; se trovato, `self._event_exposure[event_id] -= position_size`; se exposure <= 0, `del self._event_exposure[event_id]`.
   - Aggiornare `restore_from_store()`: leggere `event_id` per ogni position persistita e ricostruire `_event_exposure` + `_token_to_event`.
   - **NON** introdurre `asyncio.Lock` su `RiskManager` (vedere step 4 — il lock vive sull'engine).

4. **`app/execution/engine.py`** — aggiungere `self._tick_lock: asyncio.Lock` e wrappare il blocco `check_order` → `record_fill` con `async with self._tick_lock:` (R2-17 / drafter pick: engine-tick-lock come simpler choice — un lock vs. per-call locking; non frammenta RiskManager API). Passare `mkt.event_id` (preso da `market_by_id[sig.market_id].event_id`, NO mutazione di `Signal`) come parametro `event_id` a `check_order` e `record_fill`. `restore_from_store()` engine-side garantisce che RiskManager è restaurato prima del primo tick.

5. **`app/execution/trade_store.py`** — aggiungere colonna `event_id TEXT` al row schema di trades/positions. Insert path: scrive `event_id` accanto a `token_id`. `load_open_positions()` ritorna positions con `event_id` campo. `RiskManager.restore_from_store` (called via engine) usa il campo per ripopolare `_event_exposure` + `_token_to_event` cross-restart. **In scope autorizzato Q1=A come transitive dependency di PR-J**.

6. **`app/core/dependencies.py`** — wireup `max_event_exposure_pct` da config a RiskManager constructor; wireup `markets.max_per_event` a MarketService constructor.

7. **`tests/test_risk/test_event_exposure.py`** (nuovo) —
   - `test_event_cap_blocks_order_when_exceeded` — pre-popolare `_event_exposure[event_id] = 0.18 * max_exposure`; check_order con size = 0.05 * max_exposure → block (totale 0.23 > 0.20).
   - `test_atomic_reserve_under_concurrent_ticks` — usare `asyncio.gather(engine.tick(), engine.tick())` con stesso event_id; verificare che solo una tick produce un fill che supera il cap (l'altra resta sotto perché l'engine `_tick_lock` serializza).
   - `test_persistence_across_restart` — popolare `_event_exposure`, snapshot via TradeStore, instantiate new RiskManager, `restore_from_store()` → `_event_exposure` ricostruito con stessi valori.
   - `test_multiple_positions_same_event_dont_double_count` — 2 positions con stesso event_id ma token_id differenti → `_event_exposure[event_id]` = somma; chiusura di 1 → exposure decrementata correttamente.
   - `test_record_close_removes_token_to_event_mapping` — record_close di token_id elimina entry da `_token_to_event` E aggiorna `_event_exposure`.

8. **`tests/test_execution/test_engine.py`** — engine passa event_id correttamente; restore_from_store riempie event exposure; `test_tick_lock_serializes_reserve_and_record` (mock 2 concurrent reserves stesso event → solo 1 passa il cap).

9. Verifica: `pytest tests/test_risk/ tests/test_execution/test_engine.py -v && pytest -q`.

### PR-K — Cleanup

1. `app/strategies/_legacy_adapter.py` — eliminare.
2. `app/strategies/registry.py` — rimuovere `wrap_legacy` helper.
3. `tests/test_strategies/test_legacy_adapter.py` — eliminare.
4. `app/strategies/base.py` — finalize Protocol.
5. `app/core/dependencies.py` — finalize registration sans wrappers. <!-- R3-01 merged via Q1=A -->
6. Grep di sicurezza: `rg "evaluate\\(market[^s]" app/ tests/` deve essere 0 hits.
7. Verifica finale: full suite + lint + mypy + smoke dry_run.

**Done conditions removed**: lessons.md update is NO LONGER part of done conditions (R2-22 merged).

---

## Ambiguità note

### A1 — Popolamento di `event_id` per mercati cached vs fresh

**RESOLVED via R2-20**: cache eventi è separata da cache markets, TTL 30 min, versionata via `grouping_version`. Cached `event_id == ""` viene invalidato e re-fetched quando il successivo refresh `/events` ha join match per quel condition_id. Test esplicito incluso.

### A3 — Default `max_event_exposure_pct` (20% di max_exposure)

Default 20% confermato (50% × 20% = 10% del capital totale per singolo event). Backtest validation è follow-up post-merge, non parte di questo plan. Implementato in PR-J via Q1=A.

### A4 — Sorgente di `KnowledgeContext` per gruppo

**RESOLVED**: most-liquid market (R2-14 merged with default). Decisione documentata in PR-F step 4. Cambio in opzione A (aggregata) o C (dict per market) sarebbe un follow-up plan separato.

### A5 — Cap N markets per evento

**RESOLVED via R2-10**: top_K=20 default, configurabile via `markets.max_per_event` (yaml_config in scope grazie a Q1=A). Cap applicato PRIMA di `assess_batch`, non dopo.

### A6 — Backtesting compatibility

Residua come informativa: `app/backtesting/` non viene retro-popolato in questo plan. Backtest dopo PR-A vede tutti `event_id=""` → fail-closed grouping_incomplete kicks in → backtest non testa group selection. Drafter raccomanda backfill snapshot in plan dedicato post-merge.

### A7 — Modello `Event` separato vs dataclass leggero

**RESOLVED via R2-04**: NO `app/models/event.py`. `_EventPayload` (dataclass o TypedDict) module-private dentro `polymarket_rest.py`.

### A8 — Rate limit Gamma `/events` vs `/markets`

Residua come informativa: `_TokenBucket` singolo. Mitigazione adottata: cache 30min su eventi (R2-20), che riduce volume drasticamente. Bucket separato è follow-up se backpressure emerge.

### A9 — Adapter "first non-None"

**RESOLVED via R2-12**: adapter è ora evaluate-all-then-pick-best, NON first-non-None. Regressione transitoria eliminata.

### A10 — Knowledge fetch path nell'engine

**RESOLVED via R2-14 + PR-F step 4**: PR-F connette il knowledge fetch (most-liquid market) al call site engine. Behavioral change esplicito e documentato. PR-G/H riusano lo stesso path.

### A11 — `Signal.event_id` vs lookup runtime

**RESOLVED**: runtime lookup via `market_by_id[sig.market_id].event_id`. Constraint aggiunto: `market_by_id` deve essere built dal pool POST-top-K-cap, vedere R3-03.

### R3-02 (drafter-added) — Cross-market VAE signal interaction with event grouping

VAE include un signal `cross_market` (weight 0.10) che cerca mercati correlati. Non è documentato nel plan se "correlated" oggi significhi "stesso event_id" (cosa che aiuterebbe il refactor) o "match keyword/embedding" cross-event (cosa che potrebbe creare double-counting con il group selection). Spot-check post-PR-A consigliato per verificare che il cross_market signal NON pre-aggreghi info che il group selector poi sceglie di nuovo. Se overlap rilevato, follow-up plan per disambiguare. Per ora: assumiamo no overlap (Assunzione 19).

### R3-03 (drafter-added) — `market_by_id` scope post top-K cap

Dopo top-K cap (R2-10), il `markets` array che VAE riceve è subset del fetch originale. L'engine costruisce `market_by_id = {m.id: m for m in markets}` da quel subset. Se una strategia ritorna un signal con `market_id` di un market scartato dal cap, il lookup fallirà. R2-21 cattura il caso (signal.market_id not in group → drop), ma il LOG deve distinguere "outside-current-group" da "outside-tick-fetch-due-to-cap" per debugging utile.

### A13 — `last_grouping_incomplete` flag lifecycle

Drafter decision: il flag è scoped al singolo tick. `MarketService.get_grouped_markets()` lo resetta a `False` all'inizio e lo setta a `True` solo per il tick corrente se /events fail. L'engine legge il flag al ritorno della call e skippa markets con `event_id=""` per il tick. Tick successivo riprova. Se /events resta down per N tick consecutivi, alert (logging "grouping_incomplete_persistent" warning con counter).

---

## Resolved decisions (Round 4)

### Q1 = A (Approve full scope expansion)

**Decisione**: tutti e quattro i file (`app/risk/manager.py`, `app/core/dependencies.py`, `app/core/yaml_config.py`, `config/config.example.yaml`) sono autorizzati nello scope. PR-J ships con persistence (event_id tracked across restart via TradeStore) e atomic reserve (engine `_tick_lock` asyncio.Lock). Strategy wrapping vive in `dependencies.py`. Config espone `risk.max_event_exposure_pct` (default 0.20) e `markets.max_per_event` (default 20). `app/execution/trade_store.py` aggiunto come transitive dependency.

**Rationale (dal drafter)**: i quattro file sono genuinely needed; dependencies.py è il canonical wiring point, yaml_config + example.yaml sono il canonical config surface, e risk/manager.py è l'unico posto dove event-level exposure può vivere senza inventare un sistema parallel risk. Splitting PR-J in follow-up creerebbe una window dove il refactor è "done" ma la safety gate è missing.

**Bundles risolti**: R2-01, R2-02, R2-03, R2-16, R2-17, R3-01.

### Q2 = B (Split per category, then arbiter event-level)

**Decisione**: gruppi multi-category vengono splittati in subgroups per category. Ogni subgroup esegue `get_for_domain(category)` indipendentemente. L'arbiter R2-11 a fine tick deduplica per `event_id` raggruppando i Signal non-arbitrage e tenendo il winner con priority più alta.

**Rationale (dal drafter)**: l'arbiter R2-11 esiste specificamente per gestire "multiple non-arbitrage signals per event_id"; category-subgroup-winners sono esattamente questo pattern. Reusing l'arbiter è il marginal-cost più basso. Fail-closed (Option A) era too aggressive given mixed-category events possono includere alcune delle trade opportunities più interessanti.

**Bundles risolti**: R2-18, A2 (Round 1), A12 (Round 1).

---

## R3 issues found by drafter (not in Codex review)

- **R3-01 — Tracking `dependencies.py` modifications across PR-A..PR-K**: ogni PR da PR-B a PR-K tocca `app/core/dependencies.py` per wrap/un-wrap strategie. Merge note: incluso interamente in scope autorizzato via Q1=A; PR-K finalize re-finalizza il file rimuovendo wrap helpers.
- **R3-02 — Cross-market VAE signal interaction with event grouping**: VAE `cross_market` signal (weight 0.10) potrebbe overlap con group selection se "correlated" significa "same event_id". Merge note: documentato come Assunzione 19 + spot-check post-PR-A; se overlap rilevato, follow-up plan dedicato.
- **R3-03 — `market_by_id` scope post top-K cap**: dopo top-K cap, l'engine deve costruire `market_by_id` dal subset capped, non dal fetch originale. Merge note: vincolo aggiunto a `app/services/market_service.py` step 5 in PR-B; il LOG di R2-21 distingue "outside-current-group" da "outside-tick-fetch-due-to-cap".

---

## Assunzioni fatte

1. **`gamma-api.polymarket.com/events` esiste** e ritorna `{id, slug, title, markets: [...], endDate, ...}`. Schema verificato in PR-A via curl probe.
2. **`Event.id` (o slug) è stabile**: non cambia tra creazione e resolution.
3. **Tutti i punti di ingresso markets passano da `MarketService` o `polymarket_rest.list_markets()`**.
4. **`_make_market()` factory in tutti i test esistenti accetterà `event_id`** con default sintetico (`f"event-{id}"`). Update meccanico in N file di test.
5. ~~**Adapter shim "first non-None" è acceptable transitional behavior**~~ — **RESOLVED via R2-12**: l'adapter ora picks best, non first.
6. **`SignalType.SELL` resta riservato a position_monitor exits**: vedere Preflight precondition (R2-15) — questa è una BLOCKING precondition, non più solo assunzione.
7. **`Signal.market_id` resta il campo dominante** per mapping a `Market`; `event_id` derivato runtime.
8. **Rate limit Gamma sopporta volume aggiuntivo `/events`** (mitigato da cache 30min, A8).
9. **L'engine non va riscritto in altri punti**: solo step 5 del tick cambia + nuovo step 5d arbiter (R2-11) + step 5e tick-level lock (R2-17). Step 1-4 e 6 invariati.
10. **Arbitrage rimane multi-leg `list[Signal]`** documentato come eccezione esplicita.
11. **Knowledge per gruppo è opzionale in PR-B** (passato come None); diventa obbligatoria in PR-F/G/H usando market più liquido (R2-14).
12. **`pytest -q` continua a essere il comando di verifica canonico**.
13. **Convention `ruff line-length=100`, `mypy --strict`, async-first, structlog**.
14. **`config.example.yaml` è la single source of truth** per default config (in scope via Q1=A).
15. **Numero di test cumulativo**: ~870 oggi; refactor aggiunge ~45-55 (gruppi, adapter, event_id, exposure cap, fail-closed, top-K, arbiter, validation, mixed-category, persistence, atomic reserve), modifica ~50-80. Tot stimato post-refactor: ~915-935.
16. **Top-K per evento**: 20 markets default, configurabile via `markets.max_per_event` (Q1=A in scope).
17. **Backtest snapshots NON retro-popolati**: backtest behavior preservata via grouping_incomplete fail-closed (skip markets senza event_id).
18. **PR sequence è strettamente lineare** (PR-A → PR-K). PR-D/E/F/G/H/I sono mutually independent dopo PR-C, parallelizzabili (decisione operativa, non architettonica).
19. **VAE `cross_market` signal NON pre-aggrega info che il group selector poi sceglie**: spot-check necessario post-PR-A, vedere R3-02.

---

## Verifica

### Comandi per PR

| PR | Comando |
|----|---------|
| Preflight | `rg -n "return\\s+SignalType\\.SELL" app/strategies/sentiment.py app/strategies/event_driven.py app/strategies/knowledge_driven.py` (must be 0 hits in entry paths) + `pytest tests/test_strategies/test_sentiment.py tests/test_strategies/test_event_driven.py tests/test_strategies/test_knowledge_driven.py -k "bear or sell" -v` |
| PR-A | `pytest tests/test_clients/test_polymarket_rest.py tests/test_clients/test_polymarket_rest_events.py tests/test_services/test_market_grouping.py -v` poi `pytest -q` |
| PR-B | `pytest tests/test_strategies/ tests/test_strategies/test_legacy_adapter.py tests/test_execution/test_engine.py -v` poi `pytest -q` |
| PR-C..PR-I | `pytest tests/test_strategies/test_<strategy>.py -v` poi `pytest -q` |
| PR-J | `pytest tests/test_risk/test_event_exposure.py tests/test_execution/test_engine.py -v` poi `pytest -q` |
| PR-K | `pytest -q` (full suite) + `rg "evaluate\\(market[^s]" app/ tests/` deve essere 0 hits |

### Comandi globali ad ogni PR

- `pytest -v --tb=short` — full suite
- `ruff check app/ tests/` — 0 errors
- `ruff format --check app/ tests/` — 0 diffs
- `mypy app/ --strict` — 0 errors

### Smoke manuale (PR-J e PR-K)

1. Avviare bot in `dry_run`: `python -m app.main` con `EXECUTION_MODE=dry_run`.
2. Trovare un evento ladder noto (es. "BTC price end of month" con N markets a strike differenti).
3. Verificare nei log JSON:
   - `event_id` popolato sui mercati di quell'evento
   - `value_edge_group_decision` log con `winner_market_id` e `discarded` non vuoto
   - `event_arbiter_decision` log se più strategie producono signal su stesso evento
   - `position_opened` su un solo mercato del gruppo (non N)
   - `event_exposure` accumulato in `RiskKB`
   - `grouping_incomplete=False` (idealmente; se True, /events non disponibile e tick degraded come atteso)
4. Restart del bot: `event_id` deve essere persistito (cache 30min eventi, plus per-position event_id via TradeStore) e re-fetchato senza errori. `RiskManager._event_exposure` ricostruito coerentemente con positions live.

### Done conditions (intero refactor, post PR-K)

- [ ] Preflight precondition green PRIMA di PR-A
- [ ] Tutti i 870+ test originali verdi + ~45-55 nuovi (totale ~915-935) verdi
- [ ] `LegacyStrategyAdapter` rimosso; nessuna chiamata `evaluate(market, valuation)` legacy
- [ ] 7 strategie tutte conformi al nuovo Protocol
- [ ] `BaseStrategy.evaluate` ha la firma `(markets, valuations, knowledge=None)` e basta
- [ ] `Market` model ha `event_id` populated end-to-end SOLO via `/events` (mai inline)
- [ ] Engine ha event-level arbiter (R2-11) tra strategie multiple sullo stesso event_id
- [ ] Engine valida `signal.market_id ∈ group` prima di append (R2-21)
- [ ] Engine ha tick-level asyncio.Lock attorno a check_order → record_fill (R2-17)
- [ ] Top-K cap (default 20) applicato PRIMA di VAE (R2-10)
- [ ] `MarketService.get_grouped_markets` fail-closed quando /events non disponibile (R2-06)
- [ ] Mixed-category groups splittati in subgroups e dedotti dall'arbiter (Q2=B / R2-18)
- [ ] **`RiskManager` rispetta `max_event_exposure_pct` con persistence (TradeStore event_id) + atomic reserve (engine tick lock)** (PR-J — hard requirement)
- [ ] Smoke dry_run mostra group selection in azione
- [ ] `ruff` + `mypy --strict` 0 errors
- ~~Lessons.md aggiornato~~ — **REMOVED (R2-22 merged)**

---

## Note finali

Tutte le decisioni Round 4 risolte. Nessun [TBD] residuo. Plan è FINAL e ready for execution.

22 issue Codex tutte risolte (16 inline + 6 via user decisions Q1=A / Q2=B). 0 issue rejected. 3 R3 issues drafter-found tutte mergiate o documentate.
