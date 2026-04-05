---
name: risk-tuning
description: >
  Configure risk parameters, position sizing, and circuit breaker. Use when adjusting
  capital allocation, exposure limits, daily loss limits, or circuit breaker thresholds.
  Also trigger when debugging why orders are rejected or the circuit breaker tripped.
---

# Risk Management & Tuning

## Architecture

```
Signal → PositionSizer.from_signal() → SizeResult
      → RiskManager.check_order() → RiskCheck (approved/rejected + reason)
      → If approved: Executor.execute()
      → RiskManager.record_fill() / record_close()
      → CircuitBreaker.record_trade_result()
```

## Risk Configuration

```yaml
risk:
  max_exposure_pct: 50          # max % of equity deployed across all positions
  max_single_position_eur: 5%   # accepts EUR value OR "X%" of equity
  daily_loss_limit_eur: 15%     # same dual format
  fixed_fraction_pct: 5         # base fraction for position sizing
  max_positions: 25             # max concurrent open positions
  circuit_breaker:
    consecutive_losses: 3       # trip after N consecutive losses
    daily_drawdown_pct: 15      # trip when drawdown exceeds X%
    cooldown_minutes: 60        # auto-reset after cooldown
```

### The `float | "X%"` Syntax

`max_single_position_eur` and `daily_loss_limit_eur` accept either:
- A fixed EUR value: `25.0` → always 25 EUR
- A percentage string: `"5%"` → resolved at runtime against current equity

This is handled by `RiskManager._resolve_limit()` which checks if the value is a string
ending with `%`, then computes `equity * pct / 100`.

## Position Sizing Methods

`app/risk/position_sizer.py` provides three methods:

| Method | Formula | Use Case |
|--------|---------|----------|
| `fixed_fraction` | `capital * fixed_fraction_pct / 100 / price` | Default for all signals |
| `kelly_criterion` | Half-Kelly: `f/2` where `f = (p*b - q) / b` | When win probability is known |
| `from_signal` | `fixed_fraction * confidence_scale` | Used in tick cycle |

**Confidence scaling** in `from_signal()`:
- `confidence < 0.3` → 50% of base fraction
- `0.3 ≤ confidence ≤ 0.7` → linear 50-100%
- `confidence > 0.7` → 100% of base fraction

All methods cap at `max_single_position_eur`.

## Order Rejection Checks (sequential)

`RiskManager.check_order()` runs 5 checks in order:

1. **HOLD signal** → rejected ("Signal is HOLD")
2. **Daily loss limit** → rejected if `daily_pnl <= -daily_loss_limit`
3. **Single position size** → rejected if `size_eur > max_single_position_eur`
4. **Total exposure** → rejected if `(current_exposure + size_eur) / capital > max_exposure_pct`
5. **Position count** → rejected if `position_count >= max_positions`

## Circuit Breaker

Trips on two conditions (checked independently):
- **Consecutive losses**: N losses in a row without a win
- **Daily drawdown**: `(starting_capital - current_capital) / starting_capital > threshold`

When tripped, the entire tick is skipped. Auto-resets after `cooldown_minutes`.
Daily reset at UTC midnight resets both the breaker and the risk manager's daily P&L.

## Common Tasks

### Debug order rejections
Check the engine logs for `order_rejected` events with `reason` field. Common causes:
- "Daily loss limit reached" → `daily_pnl` too negative
- "Max exposure exceeded" → too many open positions by EUR value
- "Max positions reached" → 25 concurrent positions

### Adjust for different capital levels
The system is designed for 100-200 EUR. For larger capital:
- Increase `max_positions` (more diversification)
- Keep `max_single_position_eur` as `"5%"` (auto-scales)
- Consider lowering `fixed_fraction_pct` for more conservative sizing

### Reset after circuit breaker trip
The breaker auto-resets after `cooldown_minutes`. Manual reset: restart the bot
or wait for the UTC midnight daily reset.

## Key Files

| File | Purpose |
|------|---------|
| `app/risk/manager.py` | RiskManager: check_order, record_fill/close, exposure tracking |
| `app/risk/position_sizer.py` | PositionSizer: fixed_fraction, kelly, from_signal |
| `app/risk/circuit_breaker.py` | CircuitBreaker: trip/reset/cooldown logic |
| `app/core/yaml_config.py` | RiskConfig + CircuitBreakerConfig models |
| `app/core/dependencies.py` | Risk manager initialization with YAML config |
