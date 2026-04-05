---
name: backtesting
description: >
  Run backtests, collect historical data, and interpret results. Use when setting up
  backtesting infrastructure, adding new data sources, or evaluating strategy performance
  on historical data.
---

# Backtesting

## Architecture

```
Data Collection (scripts/) → Parquet files (data/backtest/)
  → BacktestDataLoader → BacktestEngine.run() → list[BacktestTrade]
  → BacktestReporter → metrics + equity curve
```

## Data Format

Two snapshot types in `app/backtesting/data_loader.py`:

**MarketSnapshot** — point-in-time market state:
- `market_id`, `timestamp`, `yes_price`, `no_price`, `volume`, `liquidity`
- `is_resolved`, `resolution` (YES/NO/None)

**EventSnapshot** — GDELT-style event:
- `timestamp`, `theme`, `tone`, `volume`, `country`

Stored as Parquet via `pyarrow`. Load with `BacktestDataLoader.load_dataset(prefix)`.

## Running a Backtest

### 1. Collect data
```bash
python scripts/fetch_historical.py  # populates data/backtest/
```

### 2. Run via API (placeholder)
```
POST /api/v1/backtest/run
```
Currently returns `not_available` — data must be populated first.

### 3. Run programmatically
```python
from app.backtesting.engine import BacktestEngine
from app.backtesting.data_loader import BacktestDataLoader

loader = BacktestDataLoader()
dataset = loader.load_dataset("my_data")
engine = BacktestEngine(initial_capital=150.0)
trades = engine.run(dataset)
```

## Backtest Engine Logic

`BacktestEngine.run()` processes snapshots chronologically:
1. Group snapshots by timestamp (tick)
2. Per tick: record equity, close resolved positions, detect edges, open new positions
3. Force-close remaining positions at end

**Current limitation:** Uses simplified edge detection (`yes_price + no_price` vs 1.0),
not the full VAE pipeline. This is a known gap noted in code comments.

## Fill Simulation

`FillSimulator` in `app/backtesting/simulator.py` applies:

| Category | Fee Rate |
|----------|---------|
| geopolitics, politics | 0% |
| crypto | 7.2% |
| sports | 3% |
| economics | 1% |
| entertainment | 2% |
| default | 2% |

Slippage: `price * slippage_pct` (default 0.5%).

## Reporter

`BacktestReporter.generate_report(trades, initial_capital)` returns:

```python
{
    "total_trades": int,
    "winning_trades": int,
    "losing_trades": int,
    "win_rate": float,
    "total_pnl": float,
    "max_drawdown": float,
    "sharpe_ratio": float,
    "avg_trade_pnl": float,
    "best_trade": float,
    "worst_trade": float,
    "equity_curve": list[dict],  # timestamp + equity
}
```

## Key Files

| File | Purpose |
|------|---------|
| `app/backtesting/engine.py` | BacktestEngine: replay + trade logic |
| `app/backtesting/simulator.py` | FillSimulator: fees + slippage |
| `app/backtesting/data_loader.py` | Parquet load/save |
| `app/backtesting/reporter.py` | Metrics computation |
| `app/api/v1/backtest.py` | REST endpoint (placeholder) |
| `scripts/fetch_historical.py` | Data collection script |

## Common Tasks

### Add the full VAE to backtesting
Replace the simplified edge detection in `BacktestEngine.run()` with calls to
`ValueAssessmentEngine.assess()`. Requires wiring the ResolutionDB and providing
historical price/orderbook data per snapshot.

### Add a new data source for backtesting
1. Create a collection script in `scripts/`
2. Define a new snapshot type or extend `MarketSnapshot`
3. Save as Parquet with `BacktestDataLoader.save_dataset()`
