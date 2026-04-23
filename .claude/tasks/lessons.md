## Active
Lessons that affect future tasks. Target: under 15 entries.

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
