# Project Health Report

Generated: 2026-04-06
Project: PolymarketBot
Stack: Python 3.11, FastAPI, Pydantic v2, httpx, aiosqlite, scikit-learn
Mode: scan-only

## Summary

| Metric | Count |
|--------|-------|
| Total findings | 24 |
| Auto-fixed | 0 (scan-only mode) |
| Manual action needed | 24 |
| Dead code found | 5 orphan files/classes, ~600 lines |
| Dependencies to clean | 3 packages |
| UI/API issues found | 9 |
| Duplicate definitions | 1 (TimeHorizon enum) |

## Correlated Findings

Some findings from different scans share a root cause:

- **DEAD-4 + UI-8**: `MetricsCollector` is unused (dead code) AND the dashboard reimplements its logic inline. Single root cause: MetricsCollector was never wired into DI.
- **DEAD-11 + UI-1 + UI-2**: Backtest API returns placeholder responses despite `BacktestEngine`/`BacktestReporter` being fully implemented. Fix is wiring, not removal.
- **DEAD-3 + DEAD-5 + DEAD-10**: Telegram client + AlertManager + CommandHandler form an unwired alerting pipeline. All have tests but no runtime integration.
- **DEAD-15**: `TimeHorizon` enum duplicated in `models/intelligence.py` and `models/market.py` (Phase 10 regression).

## Manual Action Required

### CRITICAL / P0

| # | ID | File | Issue | Suggested Fix | Effort |
|---|-----|------|-------|--------------|--------|
| 1 | DEAD-15 | `models/intelligence.py` + `models/market.py` | Duplicate `TimeHorizon` enum in two files | Consolidate to `market.py`, update 3 importers in intelligence modules | 5 min |
| 2 | DEAD-1 | `app/clients/polymarket_ws.py` | Orphan file: 0 importers, 0 tests | Delete file | 1 min |

### HIGH / P1

| # | ID | File | Issue | Suggested Fix | Effort |
|---|-----|------|-------|--------------|--------|
| 3 | UI-1+2 | `app/api/v1/backtest.py` | Both backtest endpoints return hardcoded placeholders | Wire to existing `BacktestEngine` + `BacktestReporter` | 30 min |
| 4 | UI-3 | `app/monitoring/dashboard.py:86` | Equity curve always empty `[]` | Record equity at each tick via `MetricsCollector.record_equity()` | 20 min |
| 5 | UI-5 | `static/index.html:191-215` | Intelligence tab: 3 placeholder cards, no data fetching | Wire JS to existing `/intelligence/anomalies` and `/intelligence/watchlist` | 30 min |
| 6 | UI-6 | `static/index.html:218-242` | Knowledge tab: 3 placeholder cards, no data fetching | Wire JS to existing `/knowledge/risks` and `/knowledge/strategies` | 30 min |
| 7 | UI-9 | `app/api/v1/intelligence.py:15` | Module-level singletons bypass DI; anomalies always empty | Register orchestrator in `dependencies.py`, inject via `Depends()` | 15 min |
| 8 | DEP-1 | `pyproject.toml` | `py-clob-client` unused (custom CLOB client used instead) | Move to optional deps `[live]` group | 2 min |
| 9 | DEP-2 | `pyproject.toml` | `python-telegram-bot` unused (raw httpx used instead) | Remove from dependencies | 2 min |
| 10 | DEP-3 | `pyproject.toml` | `aiofiles` unused (no async file I/O in project) | Remove from dependencies | 2 min |
| 11 | DEAD-4 | `app/monitoring/metrics.py` | `MetricsCollector` never instantiated; dashboard does its own metrics | Either wire into DI or delete (dashboard has inline impl) | 5 min |
| 12 | DEAD-5 | `app/monitoring/alerting.py` | `AlertManager` never instantiated, not in DI | Wire into DI or keep as planned infrastructure | 15 min |

### MEDIUM / P2

| # | ID | File | Issue | Suggested Fix | Effort |
|---|-----|------|-------|--------------|--------|
| 13 | UI-4 | `dashboard.py:91` + `dependencies.py:79,99` | Hardcoded `capital=150.0` in 3 places | Read from config, single source of truth | 5 min |
| 14 | UI-7 | `static/js/app.js:436` | Missing `cross_platform` weight in dashboard display (shows 8/9) | Add `cross_platform: "Cross Platform"` to weights label map | 1 min |
| 15 | DEAD-2 | `app/clients/llm_client.py` | Entire file unused in production (future integration) | Keep as planned infrastructure; note in code | 0 min |
| 16 | DEAD-3 | `app/clients/telegram_client.py` | Not wired in production (used only by DEAD-5) | Keep if alerting pipeline planned | 0 min |
| 17 | DEAD-6 | `app/services/market_scanner.py:129` | `classify_batch()` never called from app | Remove method or keep for future batch scanning | 2 min |
| 18 | DEAD-7 | `app/services/market_scanner.py:137` | `get_active_domains()` never called from app | Remove method | 2 min |
| 19 | DEAD-8 | `app/knowledge/obsidian_bridge.py:181` | `write_market_analysis()` never called | Keep -- planned Obsidian write-back | 0 min |
| 20 | DEAD-9 | `app/knowledge/obsidian_bridge.py:279` | `read_divergence_events()` never called | Keep -- planned divergence tracking | 0 min |

### LOW / P3

| # | ID | File | Issue | Suggested Fix | Effort |
|---|-----|------|-------|--------------|--------|
| 21 | DEAD-12 | `app/monitoring/alerting.py:47` | `_SENTINEL` dead variable | Delete line | 1 min |
| 22 | DEAD-13 | `app/execution/shadow.py:95` | `_field = field` dead alias | Delete line | 1 min |
| 23 | DEAD-14 | `app/execution/live.py:80` | `_ = OrderSide` unnecessary | Delete line | 1 min |
| 24 | DEP-4 | `pyproject.toml` | `python-dotenv` is transitive via `pydantic-settings` | Optional: remove for lean deps, or keep for safety | 0 min |

## Quick-Fix Commands

```bash
# Remove unused dependencies
pip uninstall py-clob-client python-telegram-bot aiofiles -y

# Delete orphan file
rm app/clients/polymarket_ws.py

# Delete dead variables (manual edits)
# - app/monitoring/alerting.py:47 → delete _SENTINEL line
# - app/execution/shadow.py:95 → delete _field = field line
# - app/execution/live.py:80 → delete _ = OrderSide line
```

## Files Safe to Delete

- `app/clients/polymarket_ws.py` -- 0 importers, 0 tests, no side effects
- `app/monitoring/metrics.py` -- 0 app importers, fully redundant with dashboard inline logic (CAUTION: has tests)

## Suggested Follow-Up Commands

| Condition | Suggested Command | Scope |
|-----------|------------------|-------|
| DEAD-15 duplicate enum | `/refactor` | `models/intelligence.py` + `models/market.py` |
| UI-5, UI-6 dead dashboard tabs | `/feature` | `static/js/app.js` + API wiring |
| UI-1, UI-2 placeholder backtest API | `/feature` | `app/api/v1/backtest.py` |
| UI-9 DI bypass | `/refactor` | `app/api/v1/intelligence.py` + `dependencies.py` |

### Refactor Commands

```
/refactor Consolidate duplicate TimeHorizon enum (DEAD-15): keep canonical definition in models/market.py, update intelligence.py to re-export from market.py, update 3 importers (institutional_client, rss_client, news_service) + 2 test files
```

```
/refactor Wire intelligence DI (UI-9): register IntelligenceOrchestrator and EnrichmentService as singletons in dependencies.py, replace module-level instances in app/api/v1/intelligence.py with Depends() injection
```

```
/refactor Wire MetricsCollector into execution pipeline (DEAD-4, UI-3, UI-8): register in dependencies.py, call record_trade()/record_equity() from execution engine tick(), use in dashboard equity endpoint instead of hardcoded empty list
```
