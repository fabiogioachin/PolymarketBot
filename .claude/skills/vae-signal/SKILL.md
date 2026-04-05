---
name: vae-signal
description: >
  Guide for adding new signals to the Value Assessment Engine (VAE). Use when
  integrating a new data source, modifying signal weights, or extending the
  valuation pipeline with additional probability estimates.
---

# Adding a New Signal to the VAE

## Architecture

The VAE computes fair value as a weighted average of independent probability signals.
Each signal is a `float` (0-1 probability or -1 to +1 directional adjustment) with a
corresponding weight in `WeightsConfig`. Weights should sum to ~1.0.

## Step-by-step

### 1. Define the signal model (optional)

If the signal has rich metadata beyond a single float, create a model in `app/models/`:

```python
class MySignal(BaseModel):
    value: float = 0.0
    confidence: float = 0.0
    metadata: dict = Field(default_factory=dict)
```

### 2. Add parameter to `assess()`

In `app/valuation/engine.py`, add a keyword parameter:

```python
async def assess(
    self,
    market: Market,
    *,
    # ... existing params ...
    my_new_signal: float | None = None,  # ADD
) -> ValuationResult:
```

### 3. Add field to `ValuationInput`

In `app/models/valuation.py`:

```python
class ValuationInput(BaseModel):
    # ... existing fields ...
    my_new_signal: float | None = None
```

Pack it in the `inputs = ValuationInput(...)` construction in `assess()`.

### 4. Add weight to `WeightsConfig`

In `app/core/yaml_config.py`:

```python
class WeightsConfig(BaseModel):
    # ... existing weights ...
    my_new_signal: float = 0.10  # choose weight, rebalance others to sum to 1.0
```

Also update `config/config.example.yaml`.

### 5. Add computation block in `_compute_fair_value()`

Follow the exact pattern of existing blocks:

```python
if inputs.my_new_signal is not None:
    w = self._weights.my_new_signal
    prob = max(0, min(1, inputs.my_new_signal))
    weighted_sum += w * prob
    weight_total += w
    conf = ...  # signal-specific confidence
    sources.append(
        EdgeSource(
            name="my_new_signal",
            contribution=round(prob - inputs.market_price, 4),
            confidence=conf,
            detail=f"My signal: {prob:.3f}",
        )
    )
    confidence_sum += conf
    source_count += 1
```

### 6. Forward from execution engine

If the signal comes from an external service, use `assess_batch(external_signals=...)`:

```python
external_signals = {
    market_id: {"my_new_signal": value}
    for market_id, value in my_service_results.items()
}
await value_engine.assess_batch(markets, external_signals=external_signals)
```

### 7. Tests

- Test `assess()` with the new signal → verify fair value changes
- Test `assess()` with `None` → verify no effect (backward compatible)
- Test weight sum still ~1.0

## Current Signals (9 total, sum = 1.0)

| Signal | Weight | Source | Type |
|--------|--------|--------|------|
| base_rate | 0.15 | ResolutionDB | Historical prior |
| rule_analysis | 0.15 | RuleParser | Rule clarity score |
| microstructure | 0.15 | OrderBook/PriceHistory | Market structure |
| cross_market | 0.10 | Market universe | Correlated markets |
| event_signal | 0.15 | Intelligence pipeline | News/events |
| pattern_kg | 0.10 | Obsidian KG | Knowledge patterns |
| temporal | 0.05 | Market end date | Time decay factor |
| crowd_calibration | 0.05 | ResolutionDB | Calibration bias |
| cross_platform | 0.10 | Manifold Markets | Cross-platform price |
