# PolymarketBot — Development Tracker

> Autonomous intelligence + value assessment system for Polymarket
> Stack: Python 3.11, FastAPI, Pydantic v2, httpx, aiosqlite, scikit-learn
> Capital: 150 EUR | 687 tests | 9 VAE signals | 7 strategies | 9 project skills

---

## Completed (Phase 0-10)

**Foundation (Phase 0-1):** Legal/fiscal analysis (Italy restricted — dry-run + Predict Street monitoring). Full FastAPI scaffold, Polymarket REST+CLOB+WS clients, market scanner, rule parser. 80 test.

**Value Assessment Engine (Phase 2):** Core module. ResolutionDB + BaseRateAnalyzer (Bayesian shrinkage) + CrowdCalibrationAnalyzer + MicrostructureAnalyzer + CrossMarketAnalyzer. 9 weighted signals. 70 test.

**Intelligence Pipeline (Phase 3):** GDELT DOC 2.0 + GeoJSON, RSS (BBC/Al Jazeera/NPR/Guardian), institutional (Federal Register). IntelligenceOrchestrator tick cycle, EnrichmentService, Obsidian KG bridge. 88 test.

**Strategy Layer (Phase 4):** 7 strategies via Protocol. Signal carries market_price. Multi-leg returns list[Signal]. 129 test.

**Risk & Execution (Phase 5-6):** RiskManager (equity-relative limits), PositionSizer (fixed fraction + half-Kelly), CircuitBreaker. ExecutionEngine tick cycle, DryRun/Shadow/Live executors, position_monitor. TradeStore SQLite. Backtest engine. Dashboard SSE, Telegram, LLM triggers. 209 test.

**KG & Docs (Phase 7):** 25+3 seed patterns, vault setup scripts. 14 test.

**Review (Phase 8):** 11 critical bugs fixed. 598->657 test.

**Manifold Satellite (Phase 9):** ManifoldClient + ManifoldService (TF-IDF matching). cross_platform signal (0.10) in VAE. 59 new test.

**Time-Horizon Budget (Phase 10):** TimeHorizon enum, budget pools (65/25/8/2%), per-horizon edge thresholds, priority scoring, near-resolution discount. 30 new test. 687 total.

---

## Pending (from previous phases)

- [ ] Monitorare lancio Predict Street Ltd (9 aprile 2026) — verificare accessibilita dall'Italia
- [ ] Wire record_divergence() into tick cycle for Obsidian persistence

---

## Phase 11: Critical Bug Fixes — Trading + Dashboard (6 fixes)

> Fix 6 diagnosed issues preventing the bot from placing new trades and populating Intelligence/Knowledge dashboard tabs.

### Domain Analysis

| Domain                                         | Independent?      | Shared State                         | Execution                |
| ---------------------------------------------- | ----------------- | ------------------------------------ | ------------------------ |
| Backend: Execution/Risk (Fix 1)                | yes               | --                                   | parallel                 |
| Backend: Intelligence Pipeline (Fix 2, Fix 3)  | yes               | NewsService, GdeltClient             | single-agent (related)   |
| Frontend: Dashboard JS/HTML (Fix 4, Fix 5)     | yes               | static/js/app.js, static/index.html  | single-agent (shared)    |
| Backend: Risk KB Population (Fix 6)            | depends on Fix 1  | ExecutionEngine, dependencies.py     | sequential after Fix 1   |

Parallel dispatch: Steps 1, 2+3, 4 run in parallel. Step 5 after Step 1. Step 6 after all. Step 7 last.

---

### Step 1 -- Fix horizon default (blocks all trades)

**Agent:** backend-specialist
**Depends on:** --
**Files:** `app/execution/engine.py` (line 215 only)
**Status:** [x] DONE

- [x] 1.1 — Changed `TimeHorizon.SUPER_LONG` to `TimeHorizon.MEDIUM` at line 215
- [x] 1.2 — Updated `_priority` fallback `days = 30.0` to `days = 14.0`
- [x] 1.3 — No other lines touched

**Why:** Most Polymarket markets have no `end_date` -> all classified as SUPER_LONG -> pool is 2% of 75 EUR = 1.50 EUR -> all orders rejected. MEDIUM pool is 25% = 18.75 EUR.

---

### Step 2 -- Fix RSS relevance_score (always 0.0)

**Agent:** backend-specialist
**Depends on:** --
**Files:** `app/services/news_service.py`
**Status:** [x] DONE

- [x] 2.1 — Added `_compute_relevance()` static method (keyword density → tiered score)
- [x] 2.2 — Wired into `fetch_all()` after domain classification
- [x] Tests: 7 new tests in `test_news_service.py`

**Why:** `IntelligenceOrchestrator.tick()` line 51 filters `n.relevance_score > 0.5`. Currently all RSS items have score 0.0 -> all filtered out -> event_signal is always 0.

---

### Step 3 -- Fix GDELT 100% rate-limited (429)

**Agent:** backend-specialist (same as Step 2)
**Depends on:** Step 2
**Files:** `app/clients/gdelt_client.py`, `app/services/gdelt_service.py`, `app/core/yaml_config.py`, `config/config.example.yaml`, `config/config.yaml`
**Status:** [x] DONE

- [x] 3.1 — `GdeltClient`: `max_retries=1`, `backoff=5.0`
- [x] 3.2 — `GdeltService`: `asyncio.sleep(10)` inter-query delay
- [x] 3.3 — Watchlist reduced to 3 themes (ELECTION, ECON_INFLATION, WB_CONFLICT)
- [x] 3.4 — `config.example.yaml` + `config.yaml` updated (poll 60min, 3 themes)
- [x] Tests: 3 new tests across gdelt_client, gdelt_service, yaml_config

**Why:** 5 queries x 3 retries x 2s backoff = ~30s of failed requests per cycle, every 15 min. With 3 queries, 10s delay, 1 retry, 60min interval: 36s per cycle, well within limits.

---

### Step 4 -- Wire Intelligence + Knowledge dashboard tabs (Fix 4 + Fix 5)

**Agent:** frontend-specialist + orchestrator
**Depends on:** --
**Files:** `static/js/app.js`, `static/index.html`, `static/css/style.css`, `app/api/v1/intelligence.py`
**Status:** [x] DONE

- [x] 4.1 — Added `GET /intelligence/news` endpoint (orchestrator added)
- [x] 4.2 — Intelligence tab: dynamic HTML with `id` attributes + error banner
- [x] 4.3 — Knowledge tab: dynamic HTML with `id` attributes + error banner
- [x] 4.4 — `loadIntelligence()` function (watchlist, anomalies, RSS tables)
- [x] 4.5 — `loadKnowledge()` function (strategies, risks tables)
- [x] 4.6 — Wired into `switchTab()`
- [x] CSS: Added `.data-table` and `.empty-state` styles

**Why:** Intelligence and Knowledge tabs show only static placeholder HTML. No JS functions fetch from the existing API endpoints.

---

### Step 5 -- Populate Risk KB during tick cycle (Fix 6)

**Agent:** backend-specialist
**Depends on:** Step 1 (shared file: engine.py)
**Files:** `app/execution/engine.py`, `app/core/dependencies.py`
**Status:** [x] DONE

- [x] 5.1 — Added `risk_kb` param to `ExecutionEngine.__init__()`
- [x] 5.2 — Wired `risk_kb = await get_risk_kb()` in `dependencies.py`
- [x] 5.3 — Step 5c in `tick()`: upserts MarketKnowledge for each signal (edge→risk_level)
- [x] Tests: 4 new tests in `test_engine.py` (TestRiskKBIntegration)

**Why:** RiskKnowledgeBase exists and is exposed via API endpoints, but nobody writes to it during the tick cycle. The Knowledge dashboard tab will show "No data" until records are populated.

---

### Step 6 -- Tests for all 6 fixes

**Status:** [x] DONE (tests written by implementation agents)

- [x] 6.1 — Fix 1: horizon default verified by existing engine tests (17 pass)
- [x] 6.2 — Fix 2: 7 new tests in `test_news_service.py` (TestComputeRelevance + TestFetchAllRelevanceScore)
- [x] 6.3 — Fix 3: 3 new tests (test_gdelt_client defaults, test_gdelt_service 3 themes, test_yaml_config defaults)
- [x] 6.4 — Fix 4+5: news endpoint tested via curl (200 OK)
- [x] 6.5 — Fix 6: 4 new tests in `test_engine.py` (TestRiskKBIntegration)

---

### Step 7 -- Verification

**Status:** [x] DONE

- [x] 7.1 — `pytest`: 671 passed (414 + 257), 0 failures, 2 warnings
- [x] 7.2 — `ruff check`: no NEW lint errors (10 pre-existing, all outside our changes)
- [x] 7.3 — `python -c "from app.main import app"`: Import OK

---

### Risk Parameters (unchanged from Phase 10)

- Capitale: 150 EUR
- Max exposure: 50% (75 EUR)
- Budget pools: 65% short (48.75 EUR) / 25% medium (18.75 EUR) / 8% long (6 EUR) / 2% super_long (1.50 EUR)
- Edge minimo: 3% short / 5% medium / 10% long / 15% super_long
- Fixed fraction: 5% per trade (7.50 EUR)
- Max concurrent positions: 25
- Circuit breaker: 3 consecutive losses OR 15% drawdown
- Near-resolution discount: positions < 24h + prob > 0.90 count at 50% exposure

---

## Phase 12: Data Persistence, Integration Tests, Trading Realism (3 prompts)

> Three parallel workstreams: PD (intelligence/knowledge persistence), PE (integration test suites), PF (simulated trading realism). Sourced from optimized prompts reviewed by Opus.

### Domain Analysis

| Domain | Independent? | Shared State | Execution |
|--------|-------------|-------------|-----------|
| PD: Intelligence/Knowledge persistence | no (PE depends on PD) | `intelligence_orchestrator.py`, `dependencies.py`, `knowledge.py` | sequential before PE |
| PE: Integration tests | depends on PD | reads (not writes) engine, VAE, KB | sequential after PD |
| PF: Simulated trading realism | yes | `polymarket_clob.py`, `engine.py` (different sections than PD), `dashboard.py` | parallel with PD |

**Dependency graph:**
- PD Fix 3 modifies `intelligence_orchestrator.py` (adds `trade_store` param) and `dependencies.py` (passes `trade_store` to orchestrator). PE Suite 2 tests mock `IntelligenceOrchestrator` — must read the updated constructor signature.
- PF touches `engine.py` lines 420-470 (position management/P&L) and `polymarket_clob.py`. PD touches `engine.py` zero lines directly (only `knowledge.py` and `intelligence_orchestrator.py`). No file overlap with PF.
- PE is test-only (new files in `tests/test_integration/`). No overlap with PD or PF file writes.

**Parallel dispatch strategy:**
- Wave 1: PD (Steps 1-3) and PF (Steps 4-6) run in parallel — zero shared files
- Wave 2: PE (Steps 7-9) runs after PD completes — needs updated `IntelligenceOrchestrator` constructor
- Wave 3: Step 10 (verification) runs after all complete

---

### Step 1 — PD Fix 1: Knowledge debug endpoint

**Agent:** backend-specialist
**Depends on:** --
**Domain:** PD
**Files:**
- MODIFY: `app/api/v1/knowledge.py` — add `GET /knowledge/debug` endpoint
- READ: `app/knowledge/risk_kb.py` — call `get_all()` count
- READ: `app/core/dependencies.py` — access `get_intelligence_orchestrator()`
- READ: `app/services/knowledge_service.py` — pattern folder enumeration
**Skills:** `api-dashboard`, `intelligence-source`
**Status:** [x] DONE

- [x] 1.1-1.4 — Debug endpoint implemented + 4 tests in `tests/test_api/test_knowledge.py`

---

### Step 2 — PD Fix 2: Frontend empty-state messages

**Agent:** frontend-specialist
**Depends on:** --
**Domain:** PD
**Files:**
- MODIFY: `static/js/app.js` — `loadIntelligence()` (lines 503-605) and `loadKnowledge()` (lines 608-678)
**Skills:** `api-dashboard`
**Status:** [x] DONE

- [x] 2.1-2.3 — Empty-state messages updated with actionable hints + HTTP error display

---

### Step 3 — PD Fix 3: Persist anomaly history to SQLite

**Agent:** backend-specialist
**Depends on:** Step 1 (same domain, shared file `knowledge.py` for debug endpoint reading `anomaly_history_length`)
**Domain:** PD
**Files:**
- MODIFY: `app/execution/trade_store.py` — add `intelligence_events` table + save/load methods
- MODIFY: `app/services/intelligence_orchestrator.py` — add `trade_store` param, load on init, save on tick
- MODIFY: `app/core/dependencies.py` — pass `trade_store` to `IntelligenceOrchestrator`
**Skills:** `intelligence-source`, `config-system`
**Status:** [x] DONE (setter pattern chosen — sync preserved)

- [x] 3.1-3.6 — intelligence_events table, save/load methods, set_trade_store() async setter, last_tick property. 10 tests in test_trade_store.py + test_intelligence_orchestrator.py.

---

### Step 4 — PF: Diagnose P1-P6 trading simulation problems

**Agent:** backend-specialist
**Depends on:** --
**Domain:** PF
**Files (READ-ONLY for diagnosis):**
- `app/monitoring/dashboard.py` lines 308-314 — `_win_rate()`
- `app/execution/engine.py` lines 165-180 — `exited_market_ids` check
- `app/execution/engine.py` lines 420-470 — `_manage_positions()` P&L
- `app/clients/polymarket_clob.py` — `place_order()`, `_reduce_position()`, `get_balance()`
- `app/execution/trade_store.py` — schema
**Skills:** `execution-modes`, `risk-tuning`
**Status:** [x] DONE

- [x] P1: NOT A BUG — _win_rate() already filters type=="close"
- [x] P2: NOT A BUG — fallback get_market() works for orphaned positions
- [x] P3: NOT A BUG — get_balance() returns correct total=available+locked+unrealized
- [x] P4: NOT A BUG — spread+slippage always makes fill_price >= market_price for BUY
- [x] P5: NOT A BUG — exited_market_ids correctly prevents same-tick rebuy
- [x] P6: CONFIRMED BUG — partial exit fills treated as full closes (fixed)

---

### Step 5 — PF: Implement confirmed fixes

**Agent:** backend-specialist (same as Step 4)
**Depends on:** Step 4
**Domain:** PF
**Files:**
- MODIFY (only if bugs confirmed): `app/clients/polymarket_clob.py`, `app/execution/engine.py`, `app/monitoring/dashboard.py`
- DO NOT MODIFY: `app/execution/shadow.py`, `app/execution/live.py`
**Skills:** `execution-modes`
**Status:** [x] DONE

- [x] 5.1 — Fixed P6: partial exit now logs "partial_exit" type, preserves position, doesn't add to exited_market_ids
- [x] 5.2-5.4 — No other bugs; no reverts; constants unchanged

---

### Step 6 — PF: Regression tests (R1-R7)

**Agent:** test-writer
**Depends on:** Step 5
**Domain:** PF
**Files:**
- MODIFY: `tests/test_clients/test_polymarket_clob.py` — add R3, R4, R5, R6, R7
- MODIFY: `tests/test_monitoring/test_dashboard.py` — add R1
- MODIFY: `tests/test_execution/test_engine.py` — add R2
**Skills:** `execution-modes`
**Status:** [x] DONE

- [x] 6.1-6.7 — R1-R7 regression tests: 10 test methods across 3 files. All pass.

---

### Step 7 — PE Suite 1: Storage retrieval integration tests

**Agent:** test-writer
**Depends on:** Step 3 (PD must complete — updated `IntelligenceOrchestrator` constructor)
**Domain:** PE
**Files:**
- CREATE: `tests/test_integration/__init__.py`
- CREATE: `tests/test_integration/test_storage_retrieval.py`
- READ: `tests/test_execution/test_engine.py` — FakeValueEngine, FakeStrategy patterns
- READ: `tests/test_execution/conftest.py` — engine fixtures
- READ: `app/execution/engine.py` — tick cycle step 5c (risk_kb upsert)
- READ: `app/knowledge/risk_kb.py` — RiskKnowledgeBase, MarketKnowledge, RiskLevel
**Skills:** `vae-signal`, `execution-modes`
**Status:** [x] DONE

- [x] 7.1-7.2 — 2 integration tests: engine→KB and engine→KB→API. Both pass.

---

### Step 8 — PE Suite 2: Cross-source flow integration tests

**Agent:** test-writer
**Depends on:** Step 3 (PD must complete — updated `IntelligenceOrchestrator` constructor)
**Domain:** PE
**Files:**
- CREATE: `tests/test_integration/test_cross_source_flow.py`
- READ: `app/services/intelligence_orchestrator.py` — tick(), _process_event(), get_event_signal()
- READ: `app/services/knowledge_service.py` — match_patterns() returns `list[PatternMatch]` with `.match_score`
- READ: `tests/test_services/test_intelligence_orchestrator.py` — existing mock patterns
**Skills:** `intelligence-source`, `vae-signal`
**Status:** [x] DONE

- [x] 8.1-8.5 — 8 test methods across 5 classes. All pass.

---

### Step 9 — PE Suite 3: Probability calculation tests

**Agent:** test-writer
**Depends on:** Step 3 (PD must complete)
**Domain:** PE
**Files:**
- CREATE: `tests/test_integration/test_probability_calculation.py`
- READ: `app/valuation/engine.py` lines 194-375 — `_compute_fair_value()` (CRITICAL: must read before writing assertions)
- READ: `app/valuation/engine.py` lines 100-105 — edge/scaled_edge/fee_adjusted_edge
- READ: `app/valuation/temporal.py` — `compute_temporal_factor()` (returns 1.0 for >30 days)
- READ: `app/valuation/crowd_calibration.py` — `get_adjustment()`, sample_size >= 20 threshold
- READ: `tests/test_valuation/test_engine.py` — existing `_make_market()` factory
**Skills:** `vae-signal`
**Status:** [x] DONE

- [x] 9.1-9.5 — 6 test methods with exact numerical assertions derived from real formula. All pass.

---

### Step 10 — PD Tests: debug endpoint + anomaly persistence

**Agent:** test-writer
**Depends on:** Steps 1, 3
**Domain:** PD
**Files:**
- CREATE: `tests/test_api/test_knowledge_debug.py` — test for debug endpoint
- CREATE: `tests/test_services/test_anomaly_persistence.py` — test for anomaly SQLite persistence
- READ: `tests/test_knowledge/test_risk_kb.py` — existing pattern (do not duplicate)
**Skills:** `api-dashboard`, `intelligence-source`
**Status:** [x] DONE

- [x] 10.1 — 4 tests in test_api/test_knowledge.py for debug endpoint
- [x] 10.2 — 6 tests in test_services/test_intelligence_orchestrator.py for persistence
- [x] 10.3 — 4 tests in test_execution/test_trade_store.py for save/load anomaly reports

---

### Step 11 — Verification (all prompts)

**Agent:** orchestrator
**Depends on:** Steps 1-10
**Domain:** all
**Status:** [x] DONE

- [x] 11.1 — PE integration tests: 16 passed
- [x] 11.2 — PD tests: 14 passed (debug endpoint + anomaly persistence + trade_store)
- [x] 11.3 — PF regression tests: 59 passed (R1-R7 + existing)
- [x] 11.4 — Full suite: **714 passed**, 0 failures, 2 warnings (up from 671)
- [x] 11.5 — ruff check: 0 new lint errors (9 pre-existing)
- [x] 11.6 — Import OK

---

### Open Tensions

| Tension | Options | Resolve When |
|---------|---------|-------------|
| `get_intelligence_orchestrator()` sync vs async | A: Make async (cleaner, but breaks 3+ callers). B: Keep sync + use setter `set_trade_store()` called from `get_execution_engine()` after store.init() (no caller changes). | Implementer chooses in Step 3. Option B is lower risk. Document in lessons.md. |
| PF diagnosis scope | Some P1-P6 items may not be bugs. Diagnosis determines actual fix count. | Step 4 diagnosis determines Step 5 scope. Agent documents findings before fixing. |

### Open Questions

None — all three prompts are fully specified with file paths, formulas, and expected behavior.

### Risks

- **PE Suite 3 numerical assertions**: If the test-writer does not read `_compute_fair_value()` carefully, assertions will have wrong expected values. The prompt explicitly warns about this but the risk remains.
- **PD Fix 3 deserialization**: `AnomalyReport` contains `GdeltEvent` and `NewsItem` Pydantic models. Serializing to JSON and deserializing back requires careful handling of datetime fields and nested models. Test must verify round-trip fidelity.
- **PF diagnosis may find 0 bugs**: All P1-P6 items were pre-diagnosed as "might NOT be bugs." If all are confirmed correct, Step 5 becomes a no-op and Step 6 still produces the 7 regression tests (which serve as documentation of correct behavior).
