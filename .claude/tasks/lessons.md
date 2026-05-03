## Active
Lessons that affect future tasks. Target: under 15 entries.

### 2026-05-03 — [workflow] Helper-driven test regressions in N4-style behavior fixes — bug-tests embed buggy contract via data builders
**Context**: /tracer-feature Slice 3 (N4 whale size/USD source provenance). Existing `tests/test_services/test_whale_orchestrator.py::test_filters_below_threshold` failed after the fix because it asserted `whale.size_usd == 250_000` for `_make_raw_trade(size=250_000, price=0.6)` — the assertion encoded the buggy interpretation (250000 share count silently passed as $250k USD).
**What happened**: Demo gate Slice 3 first run: 3 new tests green, 1 existing test red (regression). Root cause was not in the fix — the existing helper `_make_raw_trade` emitted `{"size": N, ...}` (share-count field) but the test semantics treated `N` as USD-denominated for threshold filtering. Pre-fix the bug masked the asymmetry (size_usd `or` size collapsed both into one path). Fix-until-green iter 1: change the helper to emit `{"size_usd": N, ...}` instead. 11/11 whale tests green afterwards.
**Root cause**: Bug-tests can embed the buggy contract via data builders, not just assertions. When N-style behavior fixes change a parser/heuristic, audit ALL builders that produce input data for tests — they may be hardcoded to the buggy field semantics.
**Action**: Pre-impl checklist for behavior fixes that change input parsing: (1) grep test data builders for the field being re-interpreted (`grep -rn "size_usd\|size\":" tests/`); (2) update builders semantically before running impl tests; (3) accept that file-scope anchors may need scope amendment for helper updates — log it in phases.md, not silently. Specifically for tracer-feature anchors: a glob like `test_<module>_*.py` does NOT match the bare `test_<module>.py` — explicit scope amendment is the lean answer, not a renamed scope.

### 2026-05-03 — [workflow] /tracer-feature is structurally oversized for bounded bug-fixes — but anchors-driven gates cap the cost
**Context**: User invoked /tracer-feature on 3 review-blockers (N1, N2, N4) explicitly accepted the mismatch (tracer hard-rule says "bug fix → /fix-until-green or standard investigation"). Branch phase-13-master-sync, FastAPI Python project.
**What happened**: Full /tracer-feature lifecycle ran cleanly across 3 slices despite the structural mismatch. Total cost: /plan-hardened anchors phase (Round 1 prompt-analyzer + Round 2 codex-rescue + Round 3 prompt-critic + Round 5 promotion = ~3 model passes), 3 planning-specialist dispatches (one per slice), 3 dispatch pairs (backend-specialist + test-writer parallel per slice), 1 inter-slice gate (Slice 1→2 via codex-rescue read-only — full /plan-hardened skipped because anchor-driven invocation showed gate review-only didn't need full draft+critique pipeline), 1 fix-until-green iter (Slice 3 regression). The anchor "Inter-slice gate trigger CONCRETI" with explicit (a/b/c) conditions saved one full /plan-hardened invocation between Slice 2→3 (file-disjoint, demo green, no concerns).
**Root cause**: tracer's overhead is concentrated in /plan-hardened gates and demo-gate ceremony. Bounded bug-fixes have low uncertainty by definition — most ceremony adds no signal. The cost cap depends on (1) anchor-driven gate skip logic kicking in for clean slices on disjoint files; (2) being willing to use shortcut-paths within anchor compliance (e.g. invoking codex-rescue directly for inter-slice review instead of full 5-round /plan-hardened when the gate is review-only).
**Action**: When user explicitly accepts a workflow mismatch ("use tracer for bug fixes"), respect the choice but apply cost-discipline: (a) skip /plan-hardened enrichment per slice if anchors phase already encoded the slice goal precisely (log skip in phases.md); (b) for inter-slice gates that are review-only, invoke codex-rescue directly (Round 2 equivalent) rather than full 5-round pipeline — log motivation; (c) populate Slice N+1 spec only when its turn arrives, not all slices upfront — fresh-context handoff (Step 1.6) demands it. Never violate anchor immutability — only short-circuit subordinate workflows like /plan-hardened sub-rounds when the value isn't there.

### 2026-05-02 — [codebase] `SignalType.SELL` mappa a `OrderSide.SELL` sul token taggato — non è "intent ribassista"
**Context**: P1 SELL≠BUY-NO fix — `sentiment`, `event_driven`, `knowledge_driven`, `resolution` emettevano `SignalType.SELL` su NO token per esprimere bearish intent.
**What happened**: `engine.py:312` mappa `SELL → OrderSide.SELL` sul token tagged. Senza posizione esistente l'ordine è silently invalid in shadow/live e rompe il P&L tracking in dry_run. 4 strategie convertite: `signal_type=SignalType.BUY` su `token_id=NO_token` con `market_price = 1.0 - valuation.market_price` (NO book price, allineato a position-sizing). Helper rinominati `_resolve_signal_type` → `_resolve_target_outcome` (return `Literal["yes","no"] | None`); `_pick_token` rimosso fallback `outcomes[0]` (return `None` su missing); guard `if not token_id: return None` aggiunto in tutte le 4 strategie. Outcome matching usa `.strip().lower()` (anche YES helpers in `resolution.py`). 12 nuovi test + 7 rename coprono: NO outcome missing, token_id vuoto, whitespace match, `market_price == 1.0 - YES_price`, sign convention `edge_amount < 0` per BUY-NO. Verifica empirica: V3 strategies 125/125, V4 full suite 778+ passed/0 failed (con 1 test resolution aggiunto post-audit → 779/0).
**Root cause**: Confusione semantica diffusa — `SignalType.SELL` letto come "direzione opposta" mentre nell'engine è exit-side puro. Il pattern corretto era già in `value_edge.py:52-65` ma copiato male altrove.
**Action**: `SignalType.SELL` resta nell'enum **solo** per (a) exits via `position_monitor.build_exit_order`, (b) arbitrage strategico (`arbitrage.py:141,152`). Trigger anti-regressione: ogni volta che si scrive `signal_type = SignalType.SELL` chiedere "è una EXIT o un ARBITRAGE leg? Se nessuna → bug, usa BUY sul token inverso". Follow-up tracked: R2-04 (`value_edge.py:97` ha latent `market_price` bug analogo), R2-07 (cross-token same-market dedup `engine.py:233-244`). Cross-ref: `.claude/plan-hardened/group-refactor/PLAN.md` (multi-alternative refactor, gates su questo merge).
**Post-implementation audit (Codex)**: dopo implementazione + V1-V5, audit indipendente Codex ha individuato 2 gap: (1) `test_resolution.py` mancava `test_skips_signal_when_no_token_id_empty` (gli altri 3 test file ce l'avevano — copy-paste asimmetrico durante Step 8); (2) `resolution.py` `_get_yes_price`/`_get_yes_token` usavano `.lower()` senza `.strip()`, inconsistenti con `_get_no_token` post-fix e con gli helper degli altri 3 strategy. Entrambi chiusi nello stesso commit. **Insegnamento generale**: l'ultimo step di un fix ripetuto su N file è il più rischioso (fatica → mancata replica). Audit indipendente post-V5 cattura quello che V5 grep non vede (asimmetrie cross-file).

### 2026-04-27 — [codebase] VAE: signal anchored a market_price = edge collassato per tutto il tick
**Context**: P1 "Edge near-zero in practice" — il bot non genera mai segnali perché `|edge|` non supera `min_edge`.
**What happened**: Diagnostico in `scripts/debug_edge_zero.py` ha confermato la hypothesis con numeri reali. Su un mercato sparse-data (price=0.60, no orderbook, no history, DB vuoto), l'engine produce `fair_value=0.59`, `edge=-0.01`. UNICO signal attivo: `base_rate`, che restituiva `0.10*0.5 + 0.90*market_price = 0.59` (formula di shrinkage con `count<5`). Output indistinguibile da market_price → contributo nullo all'edge ma weight=0.15 dilutava QUALSIASI altro signal. Audit completo dei 11 signal: `microstructure` (composite_score=0.0 → market_price-0.05) e `cross_market` (composite_signal=0.0 → market_price+0) anch'essi anchored quando data assente; gli altri 8 signal correttamente esclusi via `None` upstream nell'engine wiring.
**Root cause**: confusione tra "Bayesian shrinkage at signal level" (sbagliato — fa il blending nel signal) e "weighted average at engine level" (corretto — i signal restano indipendenti, è l'engine che blenda). `base_rate.get_prior` faceva il blending dentro il signal; con poca evidenza storica restituiva ~market_price; il weighted-avg lo includeva con weight 0.15 → dampava tutti gli altri segnali. Stesso errore in `microstructure` (formula `market_price + (score-0.5)*0.1` quando score=0) e `cross_market` (`composite_signal=0` quando no correlazioni).
**Action**: (1) `BaseRateAnalyzer.get_prior` ora restituisce `Optional[float]`: `None` quando `count < min_resolutions` (default 5, configurabile), altrimenti la rate storica DIRETTAMENTE (no blending con market_price). (2) Engine valuation: `_has_microstructure_data()` esclude la signal quando orderbook E history sono entrambi vuoti. `cross_signal=None` quando `cross_analysis.correlations` vuoto. (3) Nuovo `valuation.gating` block in `yaml_config.py` con 3 knob (`min_base_rate_resolutions`, `require_cross_market_correlations`, `require_microstructure_data`) — tutti default ON. (4) Test di regressione: 7 nuovi test gating in `test_engine.py`, 4 nuovi test base_rate, aggiornati 3 test stale che dipendevano dal vecchio shrinkage. (5) `test_insider_pressure_signal_is_dampened` ora osserva delta=0.04 (cap nominale ±0.05) — pre-fix dampato a ~0.02 dal bug del base_rate. **Insegnamento generale**: signal-level blending con market_price è anti-pattern — anchora silenziosamente l'edge a 0. Mantieni i signal indipendenti, lascia che il weighted-avg dell'engine faccia il blending.

### 2026-04-26 — [process] Verifica current code prima di accettare un bug-report — BUG-2 falso positivo
**Context**: Ticket BUG-2 in `todo.md` indicava `rule_edge.py:136` come "always returns BUY on negative edge" e prescriveva di applicare il pattern di `value_edge.py`.
**What happened**: Letto il file: linee 128-140 già implementano il pattern corretto (`edge > 0 → BUY YES`, `edge < 0 → BUY NO`). `git log -p` conferma: il file è così dal commit iniziale, mai bug. Il ticket era basato su misreading della riga 136 (`signal_type = SignalType.BUY` *dentro* il branch negativo) senza guardare il token_id swap adiacente (137-140). Anche il lesson 2026-04-25 ("rule_edge.py:136 ha un bug confermato") era basato sulla stessa false claim, mai verificata. Test esistente `test_sell_signal_when_negative_edge_with_clear_rules` già passava — nome fuorviante ("sell") ma assertion corretta (BUY su token NO).
**Root cause**: Bug-report scritto a partire da un'ispezione della singola riga 136 estratta dal contesto. La riga isolata sembra "sempre BUY", ma il branch padre swap-pa il token_id. Errore di micro-lettura non confermato con `git log` né con `pytest`.
**Action**: Prima di applicare un fix da un ticket: (1) leggi l'intero blocco function-level, non solo la line cited; (2) `git log -p <file>` per capire se il "bug" è recente o congenito; (3) esegui i test esistenti: se il caso è già coperto e green, il bug è false-positive. Aggiornato `todo.md` (BUG-2 marcato FALSE POSITIVE), rinominato test (`test_buy_no_token_when_negative_edge_*`), aggiunto test ambiguous-rules + negative-edge per completezza. Issue collaterale documentato (`signal.market_price` = prezzo YES anche su BUY-NO) ma fuori scope BUG-2 — da aprire come nuovo ticket dopo audit trade-log.

### 2026-04-25 — [codebase] BUG-1: dedup mancante — strategie cieche allo stato del portafoglio
**Context**: Bug report "il bot piazza ordini identici (stesso market, stesso side, stesso price) in tick consecutivi".
**What happened**: Tre fallimenti combinati. (1) `BaseStrategy.evaluate(market, valuation, knowledge)` non riceve le posizioni aperte: ogni tick rideriva un BUY dalla stessa valuation. (2) `engine.tick()` filtrava solo `exited_market_ids` (chiusure full *di questo tick*); nessun guard per posizioni still-open da tick precedenti. (3) `RiskManager.record_fill()` accumula esposizione sullo stesso `token_id` invece di rifiutare il re-entry, e `PolymarketClobClient._add_to_position()` fa weighted-merge nel position esistente — l'avg_price drifta ma ogni fill viene loggato come trade separato (`_persist_trade`) → log di "open" duplicati su tick consecutivi.
**Root cause**: L'engine non aveva alcun dedup guard. Il design partiva dall'assunto che le strategie fossero stateless rispetto al portafoglio (corretto), ma nessun layer downstream introduceva il vincolo "non riaprire una posizione già aperta sullo stesso token".
**Action**: Aggiunto guard in `engine.tick()` dopo `_manage_positions`: cattura `open_position_token_ids` (`pos.size > 0.001`) e droppa i `SignalType.BUY` il cui `token_id` è già held. Dedup è per-`token_id` (non per-market) per non bloccare arbitraggi multi-leg o BUY su outcome NO quando si è long YES. SELL non sono filtrate (gli exit sono gestiti da `position_monitor`, ma una strategia può legittimamente emettere SELL e il CLOB già rifiuta SELL senza posizione). Test di regressione: `TestDuplicatePositionDedup` (4 casi: dedup attivo, sanity senza posizioni, dedup per-token non per-market, dust < 0.001 non blocca). Aggiornato `test_partial_exit_does_not_block_reevaluation` per usare un fresh token (`tok-fresh`) — il vecchio assert "BUY su tok-1 still-held genera signal" era proprio il bug.

### 2026-04-25 — [codebase] SELL signal ≠ BUY NO — confusione semantica nelle strategie
**Context**: Brainstorming "perché il bot non compra mai NO" — code exploration su strategies + execution engine.
**What happened**: `sentiment`, `event_driven`, `knowledge_driven` emettono `SignalType.SELL` per edge negativi. L'engine traduce SELL → `OrderSide.SELL` sul token_id corrente (YES). Se non esiste una posizione YES aperta, il segnale è silenziosamente sprecato — nessun ordine piazzato. Solo `value_edge` implementa correttamente la conversione: edge < 0 → `BUY token_id=NO_token`. In aggiunta, `rule_edge.py:136` ha un bug confermato: restituisce sempre `SignalType.BUY` anche su edge negativo.
**Root cause**: Confusione tra "esci da posizione YES" (SELL YES) e "apri posizione NO" (BUY NO). Le strategie copiano il pattern di `value_edge` senza capire che l'engine non fa l'inferenza NO automaticamente — la richiede esplicita via token_id swap.
**Action**: Fix P0 `rule_edge.py:136`. Fix P1: nelle 3 strategie con SELL, convertire in `BUY token_id=NO_token` quando edge < -min_edge e non esiste posizione YES aperta. Il pattern corretto è quello di `value_edge`: `signal_type=SignalType.BUY` + `token_id=market.no_token_id`.

### 2026-04-25 — [tooling] Subagents possono avere Write/Edit/Bash denied dal sandbox del harness
**Context**: Phase 13 W5 — dispatch parallelo S5a (frontend-specialist, opus) + S5b (general-purpose, sonnet) per scope file disgiunti.
**What happened**: Entrambi i subagent hanno restituito `BLOCKED` immediato senza scrivere/modificare un singolo file. S5a: tentativi `Write`, `Bash touch`, `PowerShell New-Item` — tutti negati. S5b: `Edit` negato sul primo file. I tool sono *visibili* nello schema dei subagent (no `disabled_tools`) ma il sandbox di permessi del harness li blocca runtime. Costo: 2 round-trip persi (~3 min wall-clock + token), ma i due agent hanno comunque restituito un piano d'edit dettagliato e accurato che è stato eseguito nel main turn senza re-pianificazione.
**Root cause**: Il sandbox di permission mode (auto/plan/etc) può negare i write tool ai subagent anche quando lo stesso tool è permesso al main agent. Non c'è feedback up-front: il subagent scopre la denial al primo tool call.
**Action**: Per task di file-write puro (no ricerca pesante né reasoning isolato), preferire l'esecuzione diretta nel main turn, specialmente in auto-mode. Quando si delega comunque, includere nel prompt: *"Se Write/Edit/Bash falliscono per permission denial, restituisci IMMEDIATAMENTE un edit-plan strutturato (file → diff esatto in HEREDOC) come BLOCKED status — non tentare altri tool."* Il piano dettagliato è recuperabile; un re-dispatch in main session è O(minuti), un retry blind del subagent è O(ore).

### 2026-04-24 — [tooling] Background Agent silent-hang: transcript 0B ≠ agent failed
**Context**: Phase 13 W4 — S4b (opus, backend-specialist) dispatched in background parallel a S4a. S4a completa regolarmente con summary; S4b "appare" stuck — transcript file resta 0 bytes per ~50 min senza notifica di completamento.
**What happened**: Temptation di concludere "agent failed" basandosi solo sul transcript vuoto e assenza di notifica. Ma i file prodotti esistevano (whale_pressure.py, insider_pressure.py, tests, yaml_config.py, engine.py tutti modificati). `TaskOutput` non-blocking confermò status=running. Dopo `TaskStop` (task non più trovato), test diretto sui 4 file target → 40/40 pass. Il lavoro era completo e corretto; solo la finalizzazione del summary è mancata.
**Root cause**: Background agent può perdere il canale di uscita finale (transcript buffer non flushato, runtime terminato prima di emettere il tool_result finale) ma lasciare il filesystem in stato coerente. Il transcript 0B non è sinonimo di "agent non ha fatto nulla".
**Action**: Prima di dichiarare un agent fallito: (1) verifica presenza file attesi con `Glob` + timestamp; (2) esegui i test che l'agent doveva produrre — se verdi, il lavoro è completo a prescindere dal summary mancato; (3) solo dopo `TaskStop` + verifica che il process è morto considera re-dispatch. NON re-dispatchare lo stesso task se il codice esiste già: rischio di overwrite o duplicazione.

### 2026-04-24 — [tooling] Hook `protect-critical-files.sh` blocca anche `.env.example`
**Context**: Chiusura GAP 1 Phase 13 S3 — aggiunta `# THEGRAPH_API_KEY=` commentata in `.env.example`.
**What happened**: Sia backend-specialist sia orchestrator bloccati con `BLOCKED: .env files contain credentials and must be edited manually`. Nessun bypass documentato nel hook.
**Root cause**: Il regex al rigo 12 di `~/.claude/hooks/protect-critical-files.sh` è `'/\.env(\..*)?$'` — `\..*` greedy cattura `.example`, `.local`, ecc. Intenzionale (previene leak credenziali nei template committed) ma tratta `.example` — file di documentazione — come i `.env` reali.
**Action**: Per modifiche a `.env.example` (o qualsiasi `.env*`) prevedere fin dal planning: azione manuale utente, oppure rilassare il regex a `'/\.env$'` o `'/\.env\.(local|prod|dev)$'` per consentire i template. Non dispatch-are agent per quel singolo file o sprecheremo round-trip. Tabella `trader_leaderboard` e resto S2/S3 chiusi normalmente; solo il marker `.env.example` è rimasto open — non-bloccante (client fail-soft su free tier).

### 2026-04-23 — [codebase] Static edge ignora volatility regime
**Context**: Phase 13 kickoff — utente evidenzia "IL TIMING è IL PIù GRANDE EDGE"
**What happened**: `fee_adjusted_edge` scalare non distingue 3% su vol 0.3% (alpha) da 3% su vol 5% (rumore). Gating omogeneo → trade rumorosi.
**Root cause**: nessun penalty di volatilità realizzata / velocity sul prezzo; nessun CI bounds.
**Action**: Phase 13 S1 introduce `edge_dynamic` (CI con `k_per_horizon` + sign-preserving velocity penalty + edge-strength dampener). `valuation.volatility` block con `strong_edge_threshold=0.10` per bypass penalty su edge forti (allucinazioni collettive).

### 2026-04-23 — [codebase] Polymarket platform data free-tier non integrato
**Context**: Audit pre-Phase 13 — bot cieco su trade tape, volume ranking e leaderboard
**What happened**: Letto solo orderbook e price-history. Non sa chi muove size, né quali sono i mercati gettonati.
**Root cause**: Client e orchestrator non implementati.
**Action**: Phase 13 S2+S3 aggiungono `PolymarketTradesClient`, `PolymarketLeaderboardClient`, `PopularMarketsOrchestrator`, `WhaleOrchestrator` + subgraph on-chain.

### 2026-04-24 — [codebase] FastAPI `Depends()` cattura il riferimento a import-time — monkeypatch bypassato
**Context**: Fix `tests/test_api/test_knowledge.py::test_debug_risk_kb_rows` fallito con `5 == 0`.
**What happened**: Il test faceva `monkeypatch.setattr(deps_module, "get_risk_kb", fake)` ma l'endpoint usa `KBDep = Annotated[RiskKnowledgeBase, Depends(get_risk_kb)]` a livello modulo — FastAPI ha risolto il riferimento originale a import-time, quindi il patch era invisibile. Il `RiskKnowledgeBase()` reale apriva `data/risk_kb.db` con 5 righe.
**Root cause**: `Depends(func)` memorizza l'oggetto funzione, non il nome; monkeypatching del modulo dopo l'import non lo intercetta.
**Action**: Usare sempre `app.dependency_overrides[dep_func] = fake` (FastAPI-canonico) per override di dependency in test, e fare `pop()` nel teardown. Non affidarsi a `monkeypatch.setattr` per `Depends()`. Applicato in `tests/test_api/test_knowledge.py` fixture `_mock_risk_kb`.

### 2026-04-23 — [codebase] CORS verdict Polymarket — clob aperto, gamma chiuso
**Context**: Valutazione DSS live-artifact standalone
**What happened**: `clob.polymarket.com/*` risponde con CORS aperto (fetch browser-side OK). `gamma-api` no.
**Root cause**: configurazione server-side lato piattaforma.
**Action**: DSS Live Artifact (Phase 13 S5a) fetcha diretto solo da clob + The Graph subgraph gateway; per Gamma popular-markets si polla `intelligence_snapshot.json` scritto dal backend (S4a).

### 2026-04-05 — [codebase] Signal must carry market_price, not just edge
**Context**: Full project review — execution engine used `signal.edge_amount` as order price
**What happened**: Orders placed at ~0.05 (the edge) instead of ~0.65 (the market price). Position sizing, risk checks, everything downstream was wrong.
**Root cause**: Signal model lacked market_price field. Engine had no other way to get the price for the token being traded.
**Action**: Every Signal must set `market_price` from the valuation. Engine uses `signal.market_price` for orders, not edge. All strategies updated.

### 2026-04-05 — [codebase] DI must be wired before endpoints are useful
**Context**: Bot API and dashboard returned hardcoded placeholders
**What happened**: dependencies.py only had MarketService and RiskKB. No DI for ExecutionEngine, BotService, RiskManager, CircuitBreaker, StrategyRegistry, ValueAssessmentEngine.
**Root cause**: Phase 6 left DI wiring as "Phase 6 TODO" but it was never done.
**Action**: dependencies.py now provides the full service graph. New modules must register their singletons here. Dashboard and bot API read live state.

### 2026-04-05 — [codebase] Strategies returning list[Signal] for multi-leg trades
**Context**: Arbitrage needed two-legged execution (BUY YES + BUY NO)
**What happened**: BaseStrategy protocol returned `Signal | None`, forcing one-legged arb (= directional bet).
**Root cause**: Protocol designed for single-signal strategies; arbitrage is inherently multi-leg.
**Action**: BaseStrategy.evaluate now returns `Signal | list[Signal] | None`. Engine normalizes to list. Any future multi-leg strategy follows same pattern.

### 2026-04-05 — [codebase] External plan assumptions must be verified against actual code
**Context**: /feature with user-provided MANIFOLD_INTEGRATION_PLAN.md
**What happened**: The plan assumed `SignalType` enum contained signal sources (it contains BUY/SELL/HOLD), that the VAE used a `signals` dict (it uses individual float params), and that `config.yaml` existed (only `config.example.yaml` does). Planning-specialist caught all 3 and produced a corrected plan.
**Root cause**: Plan was written from memory/documentation, not from reading the actual code.
**Action**: Always run codebase exploration before planning, even when user provides a detailed plan. Verify every file path, class name, and method signature referenced in external plans.

### 2026-04-05 — [codebase] assess_batch needs external_signals forwarding pattern
**Context**: Wiring Manifold cross-platform signal into the VAE
**What happened**: `assess_batch()` had no way to pass per-market external signals to individual `assess()` calls. Added a generic `external_signals: dict[str, dict[str, float | None]]` parameter.
**Root cause**: Original design only supported signals computed internally by the engine (base_rate, microstructure, etc.), not externally-provided per-market signals.
**Action**: The `external_signals` pattern is now the standard way to inject per-market signals from satellite sources. Use it for any future data integrations.

### 2026-04-14 — [codebase] IntelligenceOrchestrator must be wired into DI + tick cycle

**Context**: Docker debugging session — intelligence pipeline not producing event_signal data
**What happened**: GDELT/RSS services were fully implemented but IntelligenceOrchestrator was never registered in dependencies.py, never injected into ExecutionEngine, and never called during tick(). The event_signal weight (0.15) was allocated but unused.
**Root cause**: Intelligence pipeline was built as an API-only service; nobody wired it into the execution loop.
**Action**: Added `get_intelligence_orchestrator()` to dependencies.py and `_fetch_intelligence_signals()` to ExecutionEngine. The external_signals pattern already supported event_signal — just needed the data to flow.

### 2026-04-14 — [codebase] CLOB simulation sell-price floor created fake arbitrage

**Context**: Dashboard showed 100% win rate, 150→580 EUR in minutes. User correctly flagged as unrealistic.
**What happened**: `max(0.01, order.price - slippage)` guaranteed minimum sell price of 0.01. Tokens bought at 0.001 were sold at 0.01 = 10x guaranteed return. This repeated every tick (buy→exit→rebuy cycle).
**Root cause**: The 0.01 floor was meant to prevent negative prices but created artificial arbitrage for sub-penny tokens. No liquidity/spread simulation.
**Action**: Removed artificial floor (`max(0.0001, ...)`). Added `_estimate_spread()` (hyperbolically wider at extreme prices) and `_estimate_depth()` (max 100 shares at <0.01). Sub-penny tokens now have 50-100% spread and capped depth.

### 2026-04-15 — [codebase] SQLite schema mismatch: dict key vs column name

**Context**: Bug 2 fix — `time_horizon` null in trade log
**What happened**: `engine.py` passed `"horizon"` in the trade dict, but `trade_store.py` didn't have the column in `_CREATE_TRADES` and `append_trade()` didn't extract it. The field was silently dropped.
**Root cause**: The dict key name (`"horizon"`) differed from the intended column name (`time_horizon`), and no test covered the round-trip store→retrieve with this field.
**Action**: When adding a new field to a trade/position dict, always update schema + INSERT + SELECT + write a round-trip test in the same PR. For existing DBs, add `ALTER TABLE ... ADD COLUMN` in `init()` with `logger.debug` on duplicate-column exception.

### 2026-04-15 — [codebase] position_monitor: sub-10-cent positions on expired markets never exited

**Context**: Bug 3 fix — unrealized -20%/-36% on AAPL position (expired April 13)
**What happened**: Monitor comment said "let cheap long-shots ride to resolution". But in dry_run, resolved markets don't get processed — the position stays open indefinitely with capital locked.
**Root cause**: The "ride to resolution" logic assumed that resolution events would eventually close the position. In dry_run with no settlement feed, they don't.
**Action**: Added `if time_left.total_seconds() <= 0: force_exit` before the 12h flatten logic. Any market with `end_date` in the past gets an urgency=1.0 exit regardless of price. 11 new tests added.

### 2026-04-14 — [codebase] Federal Register API returns agencies as list[dict], not list[str]
**Context**: Intelligence tick failed with Pydantic validation on NewsItem.tags
**What happened**: `institutional_client.py` passed `doc.get("agencies")` directly to NewsItem.tags, but the Federal Register API returns agencies as `[{"raw_name": "...", ...}]`.
**Root cause**: No type coercion when extracting tags from the API response.
**Action**: Extract `a.get("raw_name")` from each agency dict. Always validate external API payloads against your Pydantic models, especially list fields.

## Archive
Resolved or one-off entries. Not read by agents.

### 2026-04-04 — [codebase] Python 3.11 not 3.12
**Context**: `pip install -e ".[dev]"` during Session 1.1 scaffold
**What happened**: pyproject.toml had `requires-python = ">=3.12"` but system has Python 3.11.9. Also `target-version = "py312"` in ruff config.
**Root cause**: todo.md spec assumed Python 3.12+, but dev machine only has 3.11.
**Action**: Always check `python --version` before setting requires-python. Current project uses `>=3.11` and `target-version = "py311"`.

### 2026-04-04 — [tool] hatchling editable install broken on this pip
**Context**: `pip install -e ".[dev]"` failed with `AttributeError: module 'hatchling.build' has no attribute 'prepare_metadata_for_build_editable'`
**What happened**: Even after upgrading pip+hatchling, editable install still failed. Workaround: install deps directly with `pip install`.
**Root cause**: pip/hatchling version incompatibility on Windows Python 3.11 from Microsoft Store.
**Action**: For this project, use `pip install <deps>` directly instead of `pip install -e ".[dev]"`. Consider switching to uv or a venv with standard Python installer in future.

### 2026-04-15 — [workflow] Browser test against live server validates runtime, not code
Archived 2026-04-23 — post Phase 13 kickoff; runtime verification policy baked in.

### 2026-04-15 — [workflow] Browser caches Docker static assets across rebuilds
Archived 2026-04-23 — nginx `Cache-Control: no-store` + `?v=N` versioning permanently adopted.

### 2026-04-06 — [codebase] Duplicate enum: TimeHorizon in two model files
**Context**: Phase 10 added `TimeHorizon` enum to `models/market.py`
**What happened**: `TimeHorizon` already existed in `models/intelligence.py` (from Phase 3). Now two identical enums exist, imported by different modules. Health scan caught it (DEAD-15).
**Root cause**: Did not grep for existing `TimeHorizon` definition before creating a new one.
**Action**: Consolidated to `models/market.py`, `intelligence.py` re-exports. Always grep for existing definitions before adding enums/classes. RESOLVED via /refactor 2026-04-06.
