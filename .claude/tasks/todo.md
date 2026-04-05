# PolymarketBot — Development Sessions

> Autonomous intelligence + value assessment system for Polymarket
> Core: fair value estimation → price edge detection → execution
> Capital: 100-200 EUR | Stack: Python 3.12+, FastAPI, async
> Execute: VS Code + Claude Code extension | Agents: backend/frontend/test-writer/code-reviewer

---

## Architecture Overview

```
                    ┌─────────────────────────┐
                    │   VALUE ASSESSMENT ENGINE │  ← CORE
                    │                         │
                    │  fair_value = f(         │
                    │    base_rates,           │  ← historical outcomes for similar markets
                    │    rule_analysis,        │  ← resolution rules, source, conditions, edge cases
                    │    market_microstructure,│  ← orderbook shape, spread, liquidity, volume
                    │    cross_market_corr,    │  ← related markets on Polymarket, discrepancies
                    │    event_signal,         │  ← GDELT, RSS, institutional sources
                    │    pattern_kg,           │  ← Obsidian KG patterns + domain knowledge
                    │    temporal_decay,       │  ← time to resolution, convergence
                    │    crowd_calibration     │  ← how calibrated is the crowd on this type?
                    │  )                       │
                    │                         │
                    │  edge = fair_value - market_price │
                    │  if edge > fee + threshold → TRADE │
                    └──────────┬──────────────┘
                               │
          ┌────────────────────┼────────────────────┐
          ▼                    ▼                    ▼
   ┌─────────────┐    ┌──────────────┐    ┌──────────────┐
   │ RISK MANAGER │    │  EXECUTION   │    │  KNOWLEDGE   │
   │ sizing,limit │    │ dry/live/    │    │  FEEDBACK    │
   │ breaker,halt │    │ shadow mode  │    │  → Obsidian  │
   └─────────────┘    └──────────────┘    └──────────────┘
```

---

## Phase 0: Legal & Access ✅

### Session 0.1 — Legal/Fiscal Exploration ✅
- [x] Restrizioni geografiche Polymarket per Italia/EU
- [x] Opzioni: VPN, giurisdizione alternativa, rischi legali
- [x] Regime fiscale italiano (crypto 33% dal 2026, Quadro RW, IVCA 0.2%)
- [x] Obblighi dichiarativi wallet Polygon + USDC
- [x] Decision note Obsidian: `Accesso Polymarket da Italia.md`
- [x] **Decisione**: ibrido — Polymarket dry-run + monitoraggio Predict Street (lancio 9/4/2026)
- [ ] Monitorare lancio Predict Street Ltd (9 aprile 2026) — verificare accessibilità dall'Italia

---

## Phase 1: Foundation

> Skill: `anthropic-skills:project-scaffold` per bootstrap iniziale
> Skill: `anthropic-skills:system-design` per architettura
> Agent: backend-specialist per implementazione

### Session 1.1 — Project Scaffold + Config ✅
> Completata 2026-04-04

- [x] Init git, .gitignore, pyproject.toml (tutte le dipendenze)
- [x] .env.example (secrets) + config/config.example.yaml (tunables)
- [x] .claude/CLAUDE.md con convenzioni progetto
- [x] app/core/config.py — Pydantic Settings da .env
- [x] app/core/yaml_config.py — YAML loader + validazione Pydantic
- [x] app/core/logging.py — structlog JSON con rotation
- [x] app/main.py — FastAPI + lifespan + CORS
- [x] app/api/v1/router.py + health.py
- [x] Dockerfile + docker-compose.yml
- [x] tests/conftest.py + tests/test_api/test_health.py (+ test_config.py, test_yaml_config.py — 17 tests)
- [x] **Verifica**: `uvicorn` starts, `/health` 200, `pytest` 17/17 pass, `ruff` clean

### Session 1.2 — Polymarket REST Client + Models ✅
> Completata 2026-04-04 | 20 test

- [x] app/models/market.py — Market, Outcome, OrderBook, MarketCategory, ResolutionRules
- [x] app/clients/polymarket_rest.py — httpx.AsyncClient per Gamma API (rate limiting, retry, _parse_market)
- [x] tests/test_clients/test_polymarket_rest.py (respx mocks, 20 test)
- [x] **Verifica**: tests pass, ruff clean

### Session 1.3 — CLOB Client + WebSocket ✅
> Completata 2026-04-04 | 12 test

- [x] app/models/order.py — OrderSide, OrderRequest, OrderResult, Position, Balance
- [x] app/clients/polymarket_clob.py — Mode-aware dry-run/shadow/live (150 USDC simulated)
- [x] app/clients/polymarket_ws.py — WebSocket con heartbeat, reconnect, subscribe
- [x] tests/test_clients/test_polymarket_clob.py (12 test)
- [x] **Verifica**: dry-run tests pass, ruff clean

### Session 1.4 — Market Scanner + Rule Parser ✅
> Completata 2026-04-04 | 31 test

- [x] app/services/market_scanner.py — classificazione per dominio (word boundary matching)
- [x] app/services/market_service.py — TTL cache, filtering
- [x] app/core/dependencies.py — FastAPI DI
- [x] app/services/rule_parser.py — risk classification (CLEAR/AMBIGUOUS/HIGH_RISK), edge case detection
- [x] app/api/v1/markets.py — GET /markets, /markets/{id}, /markets/{id}/rules
- [x] tests/test_services/test_market_scanner.py (16 test) + test_rule_parser.py (15 test)
- [x] **Verifica**: 80/80 test pass, 4 endpoint attivi, ruff clean

---

## Phase 2: Value Assessment Engine

> Questo è il CORE del sistema. Tutto il resto è input o output di questo engine.
> Skill: `anthropic-skills:financial-analysis` per modelli quantitativi
> Skill: `anthropic-skills:data-pipeline` per ETL patterns

### Session 2.1 — Base Rate Analyzer + Crowd Calibration ✅
> Completata 2026-04-04 | 17 test

- [x] app/models/valuation.py — Recommendation, EdgeSource, ValuationInput, ValuationResult, CalibrationData, MarketResolution
- [x] app/valuation/db.py — ResolutionDB (aiosqlite, in-memory per test)
- [x] app/valuation/base_rate.py — BaseRateAnalyzer con Bayesian shrinkage prior
- [x] app/valuation/crowd_calibration.py — CrowdCalibrationAnalyzer con bias detection
- [x] tests/test_valuation/test_base_rate.py (17 test)
- [x] **Verifica**: calibration curve, base rates, adjustment, real SQLite in-memory

### Session 2.2 — Market Microstructure Analyzer ✅
> Completata 2026-04-04 | 12 test

- [x] app/valuation/microstructure.py — spread, depth imbalance, liquidity score, momentum, volume anomaly
- [x] app/valuation/cross_market.py — keyword correlation, price discrepancy, arbitrage detection
- [x] tests/test_valuation/test_microstructure.py (12 test)
- [x] **Verifica**: composite score, correlazioni, arbitrage flag

### Session 2.3 — Value Assessment Engine ✅
> Completata 2026-04-04 | 15 test | CORE MODULE

- [x] app/valuation/engine.py — ValueAssessmentEngine (assess + assess_batch)
- [x] app/valuation/temporal.py — TemporalAnalyzer (deadline decay, convergence speed)
- [x] tests/test_valuation/test_engine.py (15 test)
- [x] **Verifica**: fair value weighted, edge calculation, fee adjustment, recommendations

### Session 2.4 — Risk/Strategy Knowledge Base ✅
> Completata 2026-04-04 | 26 test

- [x] app/knowledge/risk_kb.py — RiskKnowledgeBase (SQLite CRUD, risk levels, notes)
- [x] app/api/v1/knowledge.py — 4 endpoint (market knowledge, notes, strategies, risks)
- [x] app/knowledge/obsidian_bridge.py — ObsidianBridge (read/write patterns, market analysis)
- [x] tests/test_knowledge/ (13 + 13 test)
- [x] **Verifica**: 150/150 test pass, 8 API endpoint, ruff clean

---

## Phase 3: Intelligence Pipeline

> Skill: `anthropic-skills:data-pipeline` per ETL
> Skill: `anthropic-skills:research-synthesis` per analisi profonde
> Agent: backend-specialist

### Session 3.1 — GDELT Integration ✅
> Completata 2026-04-04 | 21 test

- [x] app/models/intelligence.py — GdeltArticle, GdeltEvent, ToneScore, NewsItem, AnomalyReport
- [x] app/clients/gdelt_client.py — DOC 2.0 + GeoJSON APIs (rate limit, retry)
- [x] app/services/gdelt_service.py — watchlist polling, anomaly detection (volume spike 2x, tone shift 1.5)
- [x] tests/ (11 client + 10 service)
- [x] **Verifica**: all tests pass, ruff clean

### Session 3.2 — RSS + Institutional Sources ✅
> Completata 2026-04-04 | 28 test

- [x] app/clients/rss_client.py — feedparser async, dedup, horizon mapping
- [x] app/clients/institutional_client.py — Federal Register API
- [x] app/services/news_service.py — aggregazione, dedup, domain classification
- [x] tests/ (10 rss + 4 institutional + 14 news_service)
- [x] **Verifica**: all tests pass, ruff clean

### Session 3.3 — Obsidian KG Integration ✅
> Completata 2026-04-04 | 13 test

- [x] app/models/knowledge.py — Pattern, PatternMatch, KnowledgeContext
- [x] app/services/knowledge_service.py — pattern matching, context building, confidence updates, standby rotation
- [x] tests/test_services/test_knowledge_service.py (13 test)
- [x] **Verifica**: all tests pass, ruff clean (note: obsidian_bridge.py già in Phase 2)

### Session 3.4 — Intelligence Orchestrator + Enrichment ✅
> Completata 2026-04-04 | 26 test

- [x] app/services/intelligence_orchestrator.py — tick cycle (GDELT + RSS + KG), event_signal API
- [x] app/services/enrichment_service.py — on-demand deep-dive (GDELT + KG + news)
- [x] app/api/v1/intelligence.py — POST /enrich, GET /anomalies, GET /watchlist
- [x] tests/ (21 orchestrator + 5 enrichment)
- [x] **Verifica**: 238/238 test pass, 11 endpoint attivi, ruff clean

---

## Phase 4: Strategy Layer

> Le strategie USANO il Value Assessment Engine, non lo sostituiscono.
> Ogni strategia è un modo specifico di sfruttare un tipo di edge.

### Session 4.1 — Strategy Framework ✅
> Completata 2026-04-05 | 10 test

- [x] app/models/signal.py — Signal, SignalType
- [x] app/strategies/base.py — BaseStrategy Protocol (runtime_checkable)
- [x] app/strategies/registry.py — StrategyRegistry (register, get_enabled, get_for_domain)
- [x] tests/test_strategies/test_registry.py (10 test)
- [x] **Verifica**: registry carica, filtra per dominio, ruff clean

### Session 4.2 — Core Strategies ✅
> Completata 2026-04-05 | 54 test

- [x] app/strategies/value_edge.py — STRATEGIA PRINCIPALE (fee_adjusted_edge + confidence thresholds)
- [x] app/strategies/arbitrage.py — YES+NO mispricing, fee-aware per categoria
- [x] app/strategies/rule_edge.py — edge da regole, RuleAnalysis integration, risk level filtering
- [x] app/strategies/event_driven.py — pattern-triggered, speed premium 1.5x entro 6h
- [x] tests/ (12 + 17 + 11 + 14 test)
- [x] **Verifica**: ogni strategia genera segnali coerenti, ruff clean

### Session 4.3 — LLM Connector + Sentiment ✅
> Completata 2026-04-05 | 49 test

- [x] app/clients/llm_client.py — Claude API wrapper (daily limit, structured prompt, marker parsing)
- [x] app/strategies/knowledge_driven.py — pattern KG → segnali (match_score × confidence)
- [x] app/strategies/sentiment.py — GDELT tone-driven, baseline tracking, domain-filtered
- [x] tests/ (19 llm + 14 knowledge + 16 sentiment)
- [x] **Verifica**: LLM invocato solo su trigger, sentiment calcolato, ruff clean

### Session 4.4 — Resolution Hunting + Temporal ✅
> Completata 2026-04-05 | 16 test

- [x] app/strategies/resolution.py — near-resolution markets (HIGH_PROB ≥0.85, LOW_PROB ≤0.15)
- [x] Fee-aware, time_weight (0.5-1.0), MAX_DAYS_TO_RESOLUTION=14
- [x] tests/test_strategies/test_resolution.py (16 test)
- [x] **Verifica**: 95%@88c→BUY, fee block, timing corretto, 367/367 test pass, ruff clean

---

## Phase 5: Risk Controls & Backtesting

> Skill: `anthropic-skills:testing-strategy` per test plan
> Skill: `anthropic-skills:financial-analysis` per metriche

### Session 5.1 — Risk Manager + Position Sizing ✅
> Completata 2026-04-05 | 29 test

- [x] app/risk/position_sizer.py — FixedFraction, Kelly (half-Kelly), confidence-scaled
- [x] app/risk/manager.py — RiskManager (check_order, size_position, exposure tracking, daily P&L)
- [x] tests/test_risk/ (14 sizer + 15 manager)
- [x] **Verifica**: rifiuta over-exposure, sizing corretto, ruff clean

### Session 5.2 — Circuit Breaker + Execution Engine ✅
> Completata 2026-04-05 | 33 test

- [x] app/risk/circuit_breaker.py — 3 consecutive losses, 15% drawdown, cooldown
- [x] app/execution/engine.py — ExecutionEngine (tick/run/stop, full pipeline)
- [x] app/execution/executor.py — OrderExecutor Protocol
- [x] app/execution/dry_run.py — DryRunExecutor (wraps ClobClient)
- [x] app/services/bot_service.py — start/stop/status/mode
- [x] app/api/v1/bot.py — 4 endpoint (status, start, stop, mode)
- [x] tests/ (13 circuit_breaker + 8 engine + 4 dry_run + 6 bot_service)
- [x] **Verifica**: tick end-to-end, circuit breaker trips, ruff clean

### Session 5.3 — Backtest Data Pipeline ✅
> Completata 2026-04-05 | 12 test

- [x] app/backtesting/data_loader.py — Parquet I/O (MarketSnapshot, EventSnapshot, BacktestDataset)
- [x] scripts/fetch_historical.py — standalone data fetch script
- [x] tests/test_backtesting/test_data_loader.py (12 test, pyarrow importorskip)
- [x] **Verifica**: roundtrip save/load, ruff clean

### Session 5.4 — Backtest Engine + Reporting ✅
> Completata 2026-04-05 | 29 test

- [x] app/backtesting/simulator.py — FillSimulator (slippage + fee per categoria)
- [x] app/backtesting/engine.py — BacktestEngine (replay loop, resolution detection, edge signal)
- [x] app/backtesting/reporter.py — BacktestReporter (return, Sharpe, drawdown, win rate, strategy breakdown)
- [x] app/api/v1/backtest.py — POST /run, GET /{id}
- [x] tests/ (8 simulator + 10 engine + 8 reporter)
- [x] **Verifica**: 470/470 test pass, 17 API endpoint, ruff clean

---

## Phase 6: Live, Monitoring & UI

> Skill: `anthropic-skills:chart-dashboard` per dashboard
> Skill: `anthropic-skills:webapp-testing` per test UI con Playwright
> Agent: frontend-specialist per dashboard, backend-specialist per il resto

### Session 6.1 — Live Executor + Shadow Mode ✅
> Completata 2026-04-05 | 28 test

- [x] app/execution/live.py — LiveExecutor placeholder (rejects orders, awaiting platform launch)
- [x] app/execution/shadow.py — ShadowExecutor (dry-run primary + live secondary, comparison log)
- [x] tests/ (16 live + 12 shadow)
- [x] **Verifica**: protocol compliance, shadow comparison, ruff clean

### Session 6.2 — Dashboard Web ✅
> Completata 2026-04-05 | 23 test

- [x] app/monitoring/metrics.py — MetricsCollector (trade/equity/strategy tracking)
- [x] app/monitoring/dashboard.py — 5 endpoint (overview, config, equity, trades, strategies)
- [x] static/ — dark-theme SPA dashboard (4 tab: Trading, Config, Intelligence, Knowledge)
- [x] app/main.py — StaticFiles mount
- [x] tests/ (16 metrics + 7 dashboard)
- [x] **Verifica**: dashboard carica, API serve dati, ruff clean

### Session 6.3 — Telegram Bot + Alerting ✅
> Completata 2026-04-05 | 46 test

- [x] app/clients/telegram_client.py — TelegramClient + TelegramCommandHandler
- [x] app/monitoring/alerting.py — AlertManager (rule-based, cooldown, 7 alert types)
- [x] tests/ (20 telegram + 26 alerting)
- [x] **Verifica**: alert rule-based, command formatting, ruff clean

### Session 6.4 — LLM Trigger Config ✅
> Completata 2026-04-05 | 8 test

- [x] app/api/v1/config.py — CRUD trigger/alert config (in-memory override + reset)
- [x] tests/test_api/test_config.py (8 test)
- [x] **Verifica**: trigger CRUD, validation, reset, ruff clean

---

## Phase 7: Obsidian KG & Documentation

### Session 7.1 — Obsidian Vault Setup + GDELT Seed ✅
> Completata 2026-04-05 | 14 test

- [x] app/knowledge/pattern_templates.py — 25 seed patterns (5 domains, 4 types)
- [x] scripts/setup_vault.py — vault directory structure + MOC
- [x] scripts/seed_patterns.py — generates pattern .md files with YAML frontmatter
- [x] tests/test_knowledge/test_pattern_templates.py (14 test)
- [x] **Verifica**: 25 patterns, all domains covered, ruff clean

### Session 7.2 — Documentation ✅
> Completata 2026-04-05

- [x] docs/ARCHITECTURE.md — full system architecture (12.9 KB)
- [x] docs/API-REFERENCE.md — all 27 API endpoints documented (11.8 KB)
- [x] README.md — project overview, quick start, structure, config (8.8 KB)

---

## Phase 8: Review & Hardening

### Session 8.1 — Full Project Review + Bug Fixes ✅
> Completata 2026-04-05 | 598 test (da 516)

- [x] P0: Order price = edge instead of market price → added `market_price` to Signal, fixed engine
- [x] P0: `get_filtered_markets()` missing → added to MarketService with sensible defaults
- [x] P0: Frontend Docker broken (path mismatch) → fixed Dockerfile + nginx + root redirect
- [x] P1: SELL signal wrong token direction → BUY NO when YES overpriced
- [x] P1: Arbitrage single-leg → two-legged (returns list[Signal])
- [x] P1: Daily reset never called → scheduler at UTC midnight in BotService
- [x] P1: No position exit → position_monitor.py (TP/SL/expiry/edge-evaporated)
- [x] P1: Dashboard hardcoded → full DI wiring, live engine state
- [x] P2: Rate limiter semaphore → token bucket (N req/sec)
- [x] P2: No P&L tracking → update_market_price + unrealized P&L in balance
- [x] P2: Confidence too low with few sources → coverage floor 0.5 + count/6
- [x] **Verifica**: 598/598 test pass, app boots, dashboard verified in browser
- [ ] Integrate position_monitor into execution engine tick cycle
- [ ] Add P&L tracking to trade_log entries (realized vs unrealized)
- [ ] Ruff + mypy pass on all new code

---

## Execution Notes

### Dependencies
```
1.1 → 1.2 → 1.3 → 1.4           (sequential: foundation)
2.1 → 2.2 → 2.3                  (sequential: value engine builds up)
2.4 after 1.4 + 2.3              (risk KB needs scanner + value engine)
3.1 ∥ 3.2                        (parallel: independent data sources)
3.3 after 3.1/3.2                (KG needs data to write)
3.4 after 3.1-3.3                (orchestrator needs all components)
4.1 after 2.3                    (strategies need value engine)
4.2 ∥ 4.3 ∥ 4.4                 (parallel: independent strategies)
5.1 after 4.1                    (risk needs strategy framework)
5.2 after 5.1                    (engine needs risk)
5.3 ∥ 5.4                        (parallel: data + engine)
6.1 after 5.2 + 0.1              (live needs engine + legal)
6.2 after 5.2                    (dashboard needs metrics)
6.3 ∥ 6.2                        (parallel: Telegram ∥ dashboard)
6.4 after 6.2 + 6.3              (polish after features)
7.1 ∥ Phase 4                    (KG setup independent from strategies)
7.2 after all phases              (final documentation)
```

### Slash Commands & Skills per Session
| Command/Skill | When to Use |
|---|---|
| `/feature` | New module scaffolding (Sessions 1.x, 2.x) |
| `/health` | After each phase completion |
| `/refactor` | Session 6.4 cleanup |
| `/commit` or `anthropic-skills:gitpush` | After each session |
| `anthropic-skills:project-scaffold` | Session 1.1 bootstrap |
| `anthropic-skills:system-design` | Sessions 2.3, 2.4 architecture |
| `anthropic-skills:financial-analysis` | Sessions 2.1, 2.2, 5.4 quantitative models |
| `anthropic-skills:data-pipeline` | Sessions 3.1, 3.2, 5.3 ETL |
| `anthropic-skills:research-synthesis` | Session 3.4 enrichment |
| `anthropic-skills:chart-dashboard` | Session 6.2 dashboard |
| `anthropic-skills:webapp-testing` | Session 6.2 UI testing |
| `anthropic-skills:testing-strategy` | Session 5.x test planning |
| `anthropic-skills:code-audit` | Session 6.4 final review |
| `anthropic-skills:api-documentation` | Session 7.2 docs |
| `anthropic-skills:claude-api` | Session 4.3 LLM integration |
| `anthropic-skills:personal-automation` | Recurring scripts (GDELT polling) |
| `anthropic-skills:schedule` | Scheduled tasks (daily digest, monitoring) |
| `obsidian-kg` | Sessions 3.3, 7.1, 7.2 |
| `anthropic-skills:knowledge-sync` | Session 7.2 final sync |

### Agent Dispatch
| Agent | Sessions |
|---|---|
| planning-specialist | Complex session kickoffs (2.3, 2.4) |
| backend-specialist | 1.x, 2.x, 3.x, 4.x, 5.x, 6.1, 6.3, 6.4 |
| frontend-specialist | 6.2 (dashboard) |
| test-writer | After each phase |
| code-reviewer | End of Phase 2, 4, 5 |
| spec-reviewer | End of Phase 4 (strategies match spec?) |

### Verification Protocol
Per session: pytest, ruff, mypy, uvicorn starts

Milestones:
- Phase 1: FastAPI + market data + rules parsed + dry-run orders
- Phase 2: Value engine assesses 10 markets, identifies edge on 2+
- Phase 3: GDELT → events feed into value engine
- Phase 4: Strategies generate signals based on value assessment
- Phase 5: 30-day backtest with per-strategy + per-edge-source breakdown
- Phase 6: 1h dry-run + dashboard + Telegram + knowledge consultabile
- Phase 7: Vault completo, docs generati

### Data Retention
- 14 giorni: GDELT core + raw text excerpts
- 60 giorni: GDELT core + GCAM sentiment
- 7 anni: aggregati stagionali monthly
- Obsidian KG: permanente (knowledge grows forever)
- Risk KB (SQLite): permanente (market rules + resolution history)

### Risk Parameters (100-200 EUR)
- Fixed fraction: 5% (5-10 EUR/trade)
- Max exposure: 50% capital deployed
- Max single position: 25 EUR
- Daily loss limit: 20 EUR
- Circuit breaker: 3 consecutive losses OR 15% daily drawdown
- Fee exploitation: priorità mercati geopolitici (0% fee)
- Maker preference: 0% fee + daily USDC rebates
