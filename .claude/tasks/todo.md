# PolymarketBot — Development Tracker

> Autonomous intelligence + value assessment system for Polymarket
> Stack: Python 3.11, FastAPI, Pydantic v2, httpx, aiosqlite, scikit-learn
> Capital: 150 EUR | 11 VAE signals (post-S4b) | 7 strategies | 9 project skills

## Phase 13 — Dynamic Edge & Platform Intelligence

> Volatility-aware edge + Polymarket platform collectors (trades/popular/leaderboard) + on-chain subgraph + whale/insider VAE signals + standalone DSS artifact.
> Master decisions: [.claude/plans/phase-13/00-decisions.md](.claude/plans/phase-13/00-decisions.md)

### Wave schedule

| Wave | Sessioni | Status |
|------|----------|--------|
| W1 | S1 Dynamic edge | [x] 2026-04-24 |
| W2 | S2 Collectors (trades, popular, leaderboard) | [x] 2026-04-24 |
| W3 | S3 Subgraph client | [x] 2026-04-24 |
| W4 | S4a Snapshot writer + Docker profiles // S4b Whale/insider VAE | [ ] / [ ] |
| W5 | S5a DSS artifact // S5b Dashboard widgets | [ ] / [ ] |

### Session plans

- [x] [S1 Dynamic edge](.claude/plans/phase-13/S1-dynamic-edge.md) — 10 new tests
- [x] [S2 Collectors](.claude/plans/phase-13/S2-collectors.md) — 33 new tests
- [x] [S3 Subgraph client](.claude/plans/phase-13/S3-subgraph.md) — 21 new tests
- [ ] [S4a Snapshot writer](.claude/plans/phase-13/S4a-snapshot-writer.md)
- [ ] [S4b Whale/insider VAE](.claude/plans/phase-13/S4b-whale-insider-vae.md)
- [ ] [S5a DSS artifact](.claude/plans/phase-13/S5a-dss-artifact.md)
- [ ] [S5b Dashboard widgets](.claude/plans/phase-13/S5b-dashboard-widgets.md)

**Baseline post-W3:** 826 pass, 0 fail. (+65 vs. pre-Phase 13, inclusi fix isolation `test_debug_risk_kb_rows`.)

---

## Phase 11: Critical Bug Fixes — Trading + Dashboard (6 fixes) [DONE 2026-04-15]

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

### Open Items from Browser Test (2026-04-15)

> Risultati da `BROWSER-TEST-REPORT.md`. Il server testato era avviato prima delle fix Phase 11-12.
> Fix code-side già applicati e testati (714 pass). Richiede restart server + re-validation browser.

- [x] **DONE (2026-04-15)**: Rebuild Docker + restart + browser re-validation post-tick-1680:
  - `GET /api/v1/knowledge/debug` → 200, `risk_kb_rows: 5` ✅ (Phase 12 Step 1)
  - `GET /api/v1/intelligence/news` → 200, 30 items ✅ (Phase 11 Step 4.1)
  - Intelligence tab → chiama anomalies+watchlist+news su click, dati renderizzati ✅ (Phase 11 Step 4.6)
  - Knowledge tab → chiama strategies+risks su click, tabelle renderizzate ✅ (Phase 11 Step 4.6)
  - `knowledge/risks` → 5 records, `knowledge/strategies` → rule_edge/5 mercati ✅
  - **Side-fix**: nginx `Cache-Control: no-store` per /static/ + `?v=13` su script/css in index.html (browser cached vecchio app.js dopo rebuild Docker)
- [x] **NON-BUG (2026-04-15)**: 4 strategie inattive — by design dato infrastruttura attuale. VAE edge ~3.3% < soglia value_edge 5%. event_driven dipende da Obsidian (non seeded). arbitrage dipende da Yes+No ≠ 1.0 (Polymarket ha sum esatto). resolution richiede fair_value ≥ 0.85. Da riesaminare quando Obsidian sarà seeded.
- [x] **NON-BUG (2026-04-15)**: knowledge/risks e knowledge/strategies vuoti — cascata da server stale pre-Phase 12. Si auto-risolve dopo restart (engine.py ha già il KB upsert per i segnali rule_edge).

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
