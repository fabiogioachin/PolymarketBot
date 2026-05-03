# CHANGES-FROM-DRAFT.md — Group-aware refactor (audit trail)

**Pipeline**: /plan-hardened — Round 5 final synthesis
**Diff scope**: PLAN.draft.md (Round 1) → PLAN.md (Round 5 FINAL)
**Generated**: 2026-05-02

---

This document audits every meaningful difference between the Round 1 draft (`PLAN.draft.md`) and the final plan (`PLAN.md`). Each entry references the source: `R2-XX` for Codex review issues, `R3-XX` for drafter-found issues, `Q1=A` / `Q2=B` for user decisions in Round 4.

---

## Aggiunte

- **Preflight precondition (BLOCKING)**: nuova sezione in cima a PLAN.md che verifica esplicitamente che il SELL→BUY-NO hotfix sia merged prima che PR-A possa partire (rg sui 3 strategy file + test cases che verificano bearish entries → SignalType.BUY su NO token). Source: R2-15 (Codex).
- **Schema contract frozen per `_EventPayload`**: `id`, `slug`, `title`, `end_date`, `market_ids`, `condition_ids` con join-key primary `conditionId` e fallback `id`. Inconsistent mappings logged + scartati, no guess. Source: R2-08 (Codex).
- **Pagination loop su `list_events`**: `max_pages=20` cap, increment `offset` di `limit` finché page < limit, log warning su cap raggiunto. Source: R2-07 (Codex).
- **Fail-closed grouping policy**: `MarketService.last_grouping_incomplete: bool` flag; quando `/events` fallisce post-retry o ritorna < 50% join match, markets con `event_id == ""` sono SKIPPED dal tick (no singleton fallback). Test esplicito 429/503/empty/missing-condition. Source: R2-06 (Codex).
- **Cache versioning + invalidation per stale empty event_id**: cache eventi separata, TTL 30 min, `grouping_version: int` incrementato a ogni successful refresh. Cached `event_id == ""` invalidato e re-fetched quando refresh ha join match. Source: R2-20 (Codex).
- **Concrete `MarketService.get_grouped_markets` API canonica**: ramo "oppure" rimosso; engine consuma single API. Source: R2-09 (Codex).
- **Top-K cap PRE-VAE**: `markets.max_per_event=20` default, applicato dentro `get_grouped_markets()` prima di chiamare `assess_batch`. Source: R2-10 (Codex).
- **Event-level cross-strategy arbiter (Step 5d)**: dopo priority sort, group `non_arb_signals` per `event_id`, keep highest-priority winner. Arbitrage list[Signal] passa through. Log `event_arbiter_decision`. Source: R2-11 (Codex).
- **Adapter "evaluate-all-then-pick-best" semantics**: `LegacyStrategyAdapter` ora valuta tutti i markets, calcola priority `abs(edge_amount) * confidence`, ties broken by market_id_lex_asc + signal_type_value, picks argmax. NOT first-non-None. Source: R2-12 (Codex).
- **Special-case adapter for arbitrage `list[Signal]`**: `LegacyStrategyAdapter(arbitrage, aggregate_lists=True)` flatten + concatena tutte le coppie YES/NO mispriced, no winner-pick. Source: R2-13 (Codex).
- **KnowledgeContext source decision (most-liquid market)**: PR-F implementa `most_liquid = max(group, key=volume_24h)`; `knowledge = await self._fetch_knowledge_for_market(most_liquid)`. Failure → degraded behavior con None. Source: R2-14 (Codex).
- **Engine guard `signal.market_id ∈ group`** (Step 5b-validate): drop e log `invalid_strategy_signal` quando strategia ritorna market_id non nel gruppo. Test con mock strategy che viola. Source: R2-21 (Codex).
- **Test enumeration esplicita per ogni migrated strategy**: 6 casi obbligatori (singleton unchanged, N>1 winner, all filtered → None, tie by id, missing valuation skipped, legacy signature removed) + casi specifici per strategia (HIGH_RISK skip, AMBIGUOUS pick, knowledge most-liquid, ecc). Source: R2-19 (Codex).
- **Mixed-category split + arbiter**: PR-B step 6 specifica esplicitamente "se group ha markets con category eterogenee, split in subgroups per category, esegui `get_for_domain(category)` per ogni subgroup, raccogli i Signal per-subgroup. L'arbiter R2-11 a fine tick deduplica per event_id". Test `test_mixed_category_event_split_into_subgroups_then_arbiter_picks_one` aggiunto. Source: Q2=B (user) / R2-18 (Codex).
- **PR-J full event-exposure cap**: `_event_exposure: dict[str, float]` keyed by event_id, `_token_to_event` map, `max_event_exposure_pct=0.20` parameter su RiskManager. Block in check_order quando exposure + size_eur > cap. Source: R2-01 (Codex), Q1=A (user).
- **PR-J persistence cross-restart**: `event_id` colonna nuova in `app/execution/trade_store.py` row schema; `restore_from_store()` ricostruisce `_event_exposure` + `_token_to_event` cross-restart. Test `test_persistence_across_restart`. Source: R2-16 (Codex), Q1=A (user).
- **PR-J atomic reserve via engine tick-level asyncio.Lock**: `engine._tick_lock` wrappa il blocco `check_order` → `record_fill`. Drafter pick: engine-tick-lock vs. RiskManager-internal lock (one lock vs. per-call locking; non frammenta API). Test `test_atomic_reserve_under_concurrent_ticks` (asyncio.gather di 2 ticks stesso event_id, solo 1 supera cap). Source: R2-17 (Codex), Q1=A (user).
- **PR-J config exposure**: `risk.max_event_exposure_pct: float = 0.20` in yaml_config + example.yaml; `markets.max_per_event: int = 20` in yaml_config + example.yaml. Pydantic validators standard. Source: R2-03 (Codex), R2-10 (Codex), Q1=A (user).
- **Authorized scope additions**: `app/risk/manager.py`, `app/core/dependencies.py`, `app/core/yaml_config.py`, `config/config.example.yaml`, `app/execution/trade_store.py` aggiunti come scope autorizzato. Source: Q1=A (user) / R2-01, R2-02, R2-03, R2-16.
- **R3-01 (drafter)**: tracking esplicito di tutti i tocchi a `dependencies.py` lungo PR-A..PR-K (wrap PR-B, un-wrap PR-C..PR-I, finalize PR-K), tutti coperti da Q1=A. Source: R3-01 (drafter).
- **R3-02 (drafter)**: spot-check post-PR-A documentato per VAE `cross_market` signal vs event grouping; Assunzione 19 aggiunta. Source: R3-02 (drafter).
- **R3-03 (drafter)**: vincolo "engine deve costruire `market_by_id` dal pool POST-top-K-cap"; LOG di R2-21 distingue "outside-current-group" da "outside-tick-fetch-due-to-cap". Source: R3-03 (drafter).
- **A13 — `last_grouping_incomplete` flag lifecycle**: nuova ambiguità documentata, scoped al singolo tick, alert su persistente N tick consecutivi. Source: drafter (Round 3 enrichment).
- **Done conditions hard requirement**: "RiskManager rispetta `max_event_exposure_pct` con persistence + atomic reserve" è hard requirement, non conditional. Source: Q1=A (user).
- **Resolved decisions appendix**: nuova sezione `## Resolved decisions (Round 4)` con Q1=A e Q2=B + rationale. Source: Round 4 (user) + drafter.
- **R3 issues appendix**: nuova sezione `## R3 issues found by drafter (not in Codex review)` con merge note per R3-01, R3-02, R3-03. Source: drafter (Round 3 enrichment).
- **Tests dedicati per fail-closed/pagination/atomic reserve**: `test_polymarket_rest_events.py` casi 429/503/empty/missing-condition (R2-06, R2-07, R2-08); `test_market_grouping.py` casi pagination/stale-cache (R2-07, R2-20); `test_event_exposure.py` casi persistence + atomic concurrency (R2-16, R2-17). Source: R2-06, R2-07, R2-08, R2-16, R2-17, R2-20.
- **Step 5e — Tick-level atomic lock**: nuovo step esplicito in PR-B step 6 (poi referenziato da PR-J step 4) per l'asyncio.Lock engine-side. Source: R2-17 (Codex), Q1=A (user).

---

## Rimozioni

- **Inline `eventId` reads from `/markets` payload**: rimosso `_parse_market` extension che leggeva `eventId`/`event`/`events` inline dal payload Gamma `/markets`. Diagnostic-only logging permesso, MAI usato per grouping. Source: R2-05 (Codex).
- **"First non-None" semantics from `LegacyStrategyAdapter`**: rimossa la regola "ritorna il primo Signal non-None"; sostituita con evaluate-all-then-pick-best. Source: R2-12 (Codex), supersede A9.
- **Lessons.md update from done conditions**: rimosso item "Lessons.md aggiornato" da done conditions (out of scope). Source: R2-22 (Codex).
- **"oppure" branch in PR-B step 6**: rimosso il dual-API ramo (MarketService.group_by_event vs MarketScanner.group_by_event); single API canonica `MarketService.get_grouped_markets`. Source: R2-09 (Codex).
- **`app/services/market_scanner.py` `group_by_event` helper**: rimosso (mai più esposto); grouping vive solo in MarketService. Source: R2-09 (Codex).
- **Plan reference a `app/models/event.py` come opzione**: rimosso ogni hint a creare un file separato `app/models/event.py`. `_EventPayload` rimane module-private dentro `polymarket_rest.py`. Source: R2-04 (Codex).
- **PR-A step 3 "best-effort se Gamma include eventId inline"**: rimosso il path "se inline disponibile, usa quello"; il grouping viene SOLO da `/events`. Source: R2-05 (Codex).
- **Singleton fallback per markets con `event_id == ""` in fail-closed mode**: rimosso (in draft venivano messi in singleton groups; ora sono SKIPPED quando `last_grouping_incomplete=True`). Source: R2-06 (Codex).
- **Tutti i `[TBD-Q1]` markers**: 8 markers risolti in scope autorizzato via Q1=A (File con scope expansion pendente block, PR-B step 4, PR-C..PR-I un-wrap, PR-J entirely, PR-K step 5, Verification table row, Done conditions item). Source: Q1=A (user).
- **Tutti i `[TBD-Q2]` markers**: 3 markers risolti in policy esplicita via Q2=B (PR-B step 6 "Determinare dominio", A2 ambiguità, A12 ambiguità). Source: Q2=B (user).
- **"File con scope expansion pendente" block**: rimosso interamente (i 4 file sono ora in scope autorizzato, top-level Modify section). Source: Q1=A (user).
- **A2 e A12 entries dalla open ambiguity list**: rimosse dalla "Ambiguità note" sezione attiva e marcate RESOLVED via Q2=B. Source: Q2=B (user).
- **A4, A5, A7, A9, A10, A11 entries dalla open ambiguity list**: rimosse dalla "Ambiguità note" come open e marcate RESOLVED via R2-XX. Source: R2-04, R2-10, R2-12, R2-14.
- **Status "<N> NEEDS_USER decisions pending"** nella header: sostituita con "FINAL — all Round 4 decisions resolved". Source: Round 5 finalization.

---

## Modifiche

- **File scope production**: era ~16 file (di cui 4 contestati come scope creep), ora 16 file tutti autorizzati + 1 nuovo (`trade_store.py`). Net: +1 file (`app/execution/trade_store.py` come transitive dependency PR-J), e i 4 contestati (`app/risk/manager.py`, `app/core/dependencies.py`, `app/core/yaml_config.py`, `config/config.example.yaml`) sono ora in scope autorizzato top-level. Source: Q1=A (user) / R2-01, R2-02, R2-03, R2-16.
- **PR count**: era 11 PRs (PR-A..PR-K), ora 11 PRs (stesso count, contents tightened). PR-J rimane in scope (non scorporato in plan separato). Source: Q1=A (user).
- **PR-J status**: era "TBD if scope approved", ora "AUTHORIZED via Q1=A — full scope expansion approved with persistence (R2-16) + atomic reserve (R2-17)". Source: Q1=A (user).
- **PR-J step count**: era 6 step (1-6 con [TBD-Q1] tags), ora 9 step espansi: yaml_config (step 1), example.yaml (step 2), risk/manager.py refactor (step 3), engine.py tick lock (step 4), trade_store.py schema (step 5), dependencies.py wireup (step 6), tests (step 7-8), verifica (step 9). Source: Q1=A (user) / R2-16, R2-17.
- **`max_event_exposure_pct` default**: era 0.08 (8% di equity) in draft, ora 0.20 (20% di max_exposure totale) in PLAN.md. Drafter pick basato sul prompt finale che spell out 20% default. Source: Q1=A (user) — drafter chose 20%.
- **Adapter selection rule**: era "first non-None", ora "evaluate-all + deterministic best-pick (priority = abs(edge) × confidence)". Source: R2-12 (Codex).
- **Engine tick loop step 5**: era "loop per market", ora "loop per group con top-K cap + multi-category split + per-strategy evaluate + Step 5b-validate + Step 5d arbiter + Step 5e tick-lock". Source: R2-09, R2-10, R2-11, R2-17, R2-21, Q2=B.
- **Cache TTL eventi**: era "5 min" (assumed in draft PR-B step 5), ora "30 min" (events change less frequently than markets, mitigates rate limit A8). Source: R2-20 (Codex).
- **`list_events` signature**: era `list_events(active=True, limit=100, offset=0)`, ora `list_events(active=True, limit=100, max_pages=20)` con pagination loop interno. Source: R2-07 (Codex).
- **PR-J event_id parameter passing**: era "passare `mkt.event_id` a `record_fill` e `check_order`" (no enforcement), ora "engine `_tick_lock` wrappa il blocco; lookup `event_id` da `market_by_id[sig.market_id].event_id` (no Signal mutation)". Source: R2-17 (Codex), Q1=A (user).
- **Ambiguità note count**: era 12 entries (A1-A12) tutte open in draft, ora 9 entries (A1, A3, A4, A5, A6, A7, A8, A9, A10, A11, A13 + R3-02, R3-03) con la maggior parte RESOLVED tramite R2-XX o user decisions. Open residuali (informativa only): A6 (backtesting), A8 (rate limit Gamma). Source: multiple R2 + Q1=A + Q2=B.
- **Assunzioni count**: era 18 (1-18) in draft, ora 19 (1-19) con Assunzione 5 marked RESOLVED via R2-12 e Assunzione 19 nuova (VAE cross_market non pre-aggrega — R3-02). Source: R2-12, R3-02 (drafter).
- **Test cumulative count**: era stimato ~30-40 nuovi (totale ~900-920) in draft, ora ~45-55 nuovi (totale ~915-935). Aggiungono i test per fail-closed, pagination, top-K, arbiter, mixed-category, persistence, atomic reserve. Source: R2-06, R2-07, R2-10, R2-11, R2-16, R2-17, R2-18, R2-19, R2-21.
- **Smoke manuale checklist**: era 4 step generici, ora 4 step specifici con `event_arbiter_decision` log + `grouping_incomplete=False` check + `event_exposure` accumulato in RiskKB. Source: R2-06, R2-11, Q1=A.
- **Header/status line**: era `Round 1 — Sonnet/Opus draft` con generated date, ora `**Status**: FINAL — all Round 4 decisions resolved.` con tracking di Round 4 user decisions. Source: Round 5 finalization.
- **Verifica table — PR-J row**: era `PR-J [TBD-Q1]`, ora `PR-J` (clean, no TBD). Source: Q1=A (user).
- **Done conditions list**: era 9 items in draft (di cui 1 era Lessons.md update), ora 14 items (no Lessons.md, ma + arbiter R2-11, + market_id validation R2-21, + tick lock R2-17, + top-K cap R2-10, + fail-closed R2-06, + mixed-category split Q2=B, + persistence + atomic reserve in PR-J hard requirement). Source: R2-06, R2-10, R2-11, R2-17, R2-21, R2-22, Q1=A, Q2=B.
- **PR-B step 6 dominio policy**: era "altrimenti split del gruppo per category — vedere Ambiguità A2" (TBD), ora "se group ha markets con category eterogenee, split in subgroups per category, esegui `get_for_domain(category)` per ogni subgroup, raccogli i Signal per-subgroup. L'arbiter R2-11 a fine tick deduplica per event_id". Source: Q2=B (user) / R2-18 (Codex).

---

## Note

- Tutte le 22 issue Codex (R2-01 … R2-22) sono state risolte: 16 mergiate inline in PLAN.v2 + 6 mergiate via user decisions Q1=A / Q2=B in Round 5.
- 0 issue rejected (REJECTED-SUGGESTIONS.md è header-only).
- 3 R3 issue drafter-found (R3-01, R3-02, R3-03) tutte mergiate o documentate.
- Audit markers `<!-- R2-XX merged -->` preservati lungo tutto PLAN.md per traceability.
