---
name: execution-modes
description: >
  Understand and configure the execution loop, trade modes (dry_run/shadow/live),
  tick cycle, position management, and trade persistence. Use when debugging the
  trading loop, modifying tick behavior, or switching execution modes.
---

# Execution Modes & Tick Cycle

## Three Execution Modes

| Mode | Class | Real Orders? | Behavior |
|------|-------|-------------|----------|
| `dry_run` | `DryRunExecutor` | No | Simulates via `PolymarketClobClient` in-memory |
| `shadow` | `ShadowExecutor` | Both | Runs dry_run (primary) + live (logged only), compares |
| `live` | `LiveExecutor` | Yes | Placeholder — returns REJECTED until Predict Street launches |

All executors implement the `OrderExecutor` protocol:
```python
async def execute(order: OrderRequest) -> OrderResult
async def get_positions() -> list[Position]
async def get_balance() -> Balance
```

## Tick Cycle (`ExecutionEngine.tick()`)

```
1. Circuit breaker check → skip if tripped
2. Fetch markets (MarketService.get_filtered_markets())
2b. Fetch Manifold cross-platform signals (slower cadence)
3. Assess all markets (VAE assess_batch with external_signals)
4. Manage positions:
   a. Check resolutions → payout/loss
   b. Update live prices
   c. Evaluate exits (TP/SL/expiry/edge-reversal)
5. Generate signals (each strategy × each market)
6. Risk check → execute new orders
7. Persist state to SQLite
```

**Cadence:** Main tick runs every `execution.tick_interval_seconds` (default 60s).
Manifold refresh runs every `intelligence.manifold.poll_interval_minutes` (default 30m).

## Position Lifecycle

```
Signal (BUY) → RiskManager.check_order() → Executor.execute()
  → Position opened → tracked in CLOB client
  → Each tick: price updated, exit evaluated
  → Exit trigger (TP/SL/expiry/edge-gone/resolution)
  → Exit order → Position closed → P&L recorded
```

Exit conditions evaluated by `app/execution/position_monitor.py`:
- **Take profit**: unrealized P&L > 20% of entry cost
- **Edge reversal**: valuation now disagrees with position direction
- **Near expiry**: market closes within 24 hours
- **Edge evaporated**: original edge dropped below 2%

## Trade Persistence (`TradeStore`)

All trades and engine state are persisted to SQLite (`data/trades.db`) after every tick.
On startup, `restore_from_store()` reloads positions, balance, tick count, and P&L.

Tables: `trades` (full trade log), `positions` (current open), `engine_state` (key-value).

## Key Configuration

```yaml
execution:
  mode: dry_run        # dry_run | shadow | live
  tick_interval_seconds: 60
  shadow_mode: false
```

Mode can be changed at runtime: `POST /api/v1/bot/mode/shadow`

## Key Files

| File | Purpose |
|------|---------|
| `app/execution/engine.py` | Main tick cycle + position management |
| `app/execution/executor.py` | OrderExecutor protocol |
| `app/execution/dry_run.py` | Simulated execution |
| `app/execution/shadow.py` | Dual-mode comparison |
| `app/execution/live.py` | Real execution (placeholder) |
| `app/execution/position_monitor.py` | Exit condition evaluation |
| `app/execution/resolution_tracker.py` | Market resolution detection |
| `app/execution/trade_store.py` | SQLite persistence |
| `app/services/bot_service.py` | Start/stop/status lifecycle |

## Common Tasks

### Add a step to the tick cycle
Edit `ExecutionEngine.tick()` in `app/execution/engine.py`. Place new logic between
existing numbered steps. Update `TickResult` dataclass if new metrics are needed.

### Add an exit condition
Edit `evaluate_exit()` in `app/execution/position_monitor.py`. Add a new check
after the existing ones. Return `ExitDecision(should_exit=True, reason="...")`.

### Debug a tick
Enable `LOG_LEVEL=DEBUG` in `.env`. The engine logs: `tick_completed` (summary),
`market_assessed` (per-market), `position_opened/sold/resolved` (per-trade).
Check `GET /api/v1/dashboard/trades` for the full trade log.
