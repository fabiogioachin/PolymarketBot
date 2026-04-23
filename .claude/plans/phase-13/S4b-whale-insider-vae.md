# S4b — Whale/Insider VAE signals

| **Modello consigliato** | **Effort** | **Wave** | **Parallelizzabile con** |
|--------------------------|-----------|----------|---------------------------|
| **Opus 4.7** (1M context) | **alto** | W4 | **S4a** (scope file disgiunti) |

**Perché Opus 4.7:** integrazione ibrida (event-style whale + microstructure-style insider) con validator Pydantic che accetta sum pesi in [0.95, 1.15] senza rompere 687 test esistenti. 1M context permette caricamento completo di `engine.py` + `_compute_fair_value` + tutti i test valuation per verificare invarianti mentre si modifica il core.

**Parallelizzazione con S4a:** scope disgiunto. S4b tocca `app/valuation/`, `app/core/yaml_config.py`, `app/execution/engine.py`, `tests/test_valuation/`, `tests/test_core/test_yaml_config.py`. S4a non tocca questi file.

---

## Obiettivo

Implementare `whale_pressure` (event-style D3) + `insider_pressure` (microstructure-style D3) con criteri D4. Integrazione nel VAE con pesi D2 (sum nominale 1.10, effective ~1.00 con Manifold off). Aggiornare test weights dinamicamente.

## Dipendenze

**S1 + S2 + S3 committed.** `ValuationInput` ha placeholder (S1), `whale_trades` arricchita con wallet aggregates (S3).

## File master

- [../00-decisions.md](../00-decisions.md) — **D2** (pesi), **D3** (integrazione ibrida), **D4** (criteri)

## File da leggere all'avvio

- [app/valuation/engine.py](app/valuation/engine.py) (302-335 signal integration, 359-375 fair_value)
- [app/valuation/microstructure.py](app/valuation/microstructure.py) (pattern prob centrata su market_price per insider)
- [app/valuation/event_signal.py](app/valuation/event_signal.py) o event-style reference (pattern per whale)
- [app/services/whale_orchestrator.py](app/services/whale_orchestrator.py) (da S2)
- [app/models/valuation.py](app/models/valuation.py) (placeholder aggiunti in S1)
- [app/core/yaml_config.py](app/core/yaml_config.py) (**74-84 `WeightsConfig`** — nome classe reale, NON "ValuationWeights")
- [app/execution/engine.py](app/execution/engine.py) (505-507 `external_signals` injection — lesson 2026-04-05)
- [tests/test_core/test_yaml_config.py](tests/test_core/test_yaml_config.py) (**39-53 test sum weights — da riscrivere dinamicamente**)
- [config/config.example.yaml](config/config.example.yaml) (37-48 weights)

## Skills / Agenti / MCP

- Skill [.claude/skills/vae-signal/SKILL.md](.claude/skills/vae-signal/SKILL.md) (pattern integrazione signal nel VAE)
- Skill [.claude/skills/config-system/SKILL.md](.claude/skills/config-system/SKILL.md)
- Agente `backend-specialist`, `test-writer`, `code-reviewer`

---

## Step esecutivi

**STEP 1 — `WhalePressureAnalyzer`.** Nuovo file `app/valuation/whale_pressure.py`:
- `compute_whale_pressure(whale_activity: list[WhaleTrade], market_price: float, lookback_hours: int = 6) -> float` → signal in [0, 1]
- Logica: per ogni whale trade in ultime `lookback_hours`, peso basato su criteri D4:
  - (a) size ≥ $100k → peso base 1.0
  - (b) wallet top-10% volume → +0.5
  - (c) wallet PnL >$500k OR weekly >$50k → +0.5
  - (d) new wallet (<7d) + size ≥ $1M → peso 3.0 (massimo)
- Aggrega BUY pressure vs SELL pressure (pesata). Output = `0.5 + net_pressure * 0.5` clampato [0, 1].
- 0.5 = nessun whale / bilanciati. >0.5 = BUY. <0.5 = SELL.

**STEP 2 — `InsiderPressureAnalyzer`.** Nuovo file `app/valuation/insider_pressure.py`:
- `compute_insider_pressure(market, recent_trades, market_price) -> float` → signal in [0, 1]
- Logica D4 insider:
  - **Filtro obvious_outcome**: se `market_price > 0.95 or market_price < 0.05` da >24h → ritorna **0.5** (neutrale, no insider signal)
  - Pre-resolution: filtra trades con `is_pre_resolution=True` (entro 30 min da resolution_datetime)
  - Per ciascuno: score basato su (win-rate storico wallet via subgraph con binomial p<0.05, min 10 trade) OR (new-account <7d + size ≥ $1M)
  - Aggrega: base 0.5, sale a 0.7-0.9 se ≥2 criteri matchano, direzione basata su side trades

**STEP 3 — `WeightsConfig` extend.** In [app/core/yaml_config.py](app/core/yaml_config.py) aggiungi:
```python
whale_pressure: float = Field(default=0.05, ge=0.0, le=1.0)
insider_pressure: float = Field(default=0.05, ge=0.0, le=1.0)

@model_validator(mode="after")
def _validate_sum(self) -> Self:
    total = sum(v for v in self.model_dump().values() if isinstance(v, (int, float)))
    # Permissive range to accommodate Manifold on/off
    if not (0.95 <= total <= 1.15):
        raise ValueError(f"weights nominal sum {total} outside [0.95, 1.15]")
    return self
```

**STEP 4 — Test weights dinamico (critico).** Riscrivi [tests/test_core/test_yaml_config.py:39-53](tests/test_core/test_yaml_config.py) per enumerare dinamicamente:
```python
def test_weights_config_sum_in_range():
    w = WeightsConfig()
    total = sum(v for k, v in w.model_dump().items() if isinstance(v, (int, float)))
    assert 0.95 <= total <= 1.15, f"sum={total}"

def test_weights_config_contains_whale_and_insider():
    w = WeightsConfig()
    assert hasattr(w, "whale_pressure")
    assert hasattr(w, "insider_pressure")
    assert w.whale_pressure == 0.05
    assert w.insider_pressure == 0.05
```

**STEP 5 — Engine integration (D3 semantica ibrida).** In [app/valuation/engine.py](app/valuation/engine.py) `_compute_fair_value()`, aggiungi DOPO gli altri signal blocks:
```python
# WHALE_PRESSURE — event-style (prob indipendente)
if inputs.whale_pressure_signal is not None:
    weighted_sum += weights.whale_pressure * inputs.whale_pressure_signal
    weight_total += weights.whale_pressure
    edge_sources.append(("whale_pressure", weights.whale_pressure * inputs.whale_pressure_signal))

# INSIDER_PRESSURE — microstructure-style (prob centrata su market_price, ±0.05)
if inputs.insider_pressure_signal is not None:
    insider_prob = market_price + (inputs.insider_pressure_signal - 0.5) * 0.1
    insider_prob = max(0.01, min(0.99, insider_prob))
    weighted_sum += weights.insider_pressure * insider_prob
    weight_total += weights.insider_pressure
    edge_sources.append(("insider_pressure", weights.insider_pressure * insider_prob))
```

`fair_value = weighted_sum / weight_total` normalizza automaticamente (linea 372 esistente).

**STEP 6 — External signals injection.** In [app/execution/engine.py](app/execution/engine.py) PRIMA di `assess_batch()`:
```python
for market in markets:
    whales = await self._whale_orch.get_whale_activity(market.id, since_minutes=360)
    external_signals[market.id]["whale_pressure"] = compute_whale_pressure(whales, market.price)
    recent = await self._whale_orch.get_whale_activity(market.id, since_minutes=1440)
    external_signals[market.id]["insider_pressure"] = compute_insider_pressure(market, recent, market.price)
```

In `VAE.assess_batch()` / `_make_input()` propaga i 2 external signals nei campi `whale_pressure_signal` / `insider_pressure_signal` di `ValuationInput`.

**STEP 7 — Config weights update.** In [config/config.example.yaml](config/config.example.yaml) sotto `valuation.weights`:
```yaml
whale_pressure: 0.05
insider_pressure: 0.05
```
Altri 9 pesi **invariati**. Commento: sum nominal = 1.10, effective ≈ 1.00 con Manifold disabled.

**STEP 8 — Tests.**
- `tests/test_valuation/test_whale_pressure.py`: 8 test (no whales→0.5, BUY→>0.5, SELL→<0.5, large single→strong, new account→strong, top volume→amplified, mixed→averaged, empty→0.5)
- `tests/test_valuation/test_insider_pressure.py`: 8 test (obvious_outcome→0.5, pre-res→>0.5, high win-rate wallet→amplified, asymmetric match→strong, no pre-res→0.5, new account + size extreme→0.9, normale→0.5)
- `tests/test_valuation/test_engine_integration.py`: external_signals → `_make_input()` → `_compute_fair_value` passa correttamente

---

## Verification

```bash
python -m pytest tests/test_valuation/test_whale_pressure.py tests/test_valuation/test_insider_pressure.py -v
python -m pytest tests/test_core/test_yaml_config.py -v      # sum validator
python -m pytest tests/ -q                                    # atteso: 720+ pass (fu 725 pre-S4b + 16 nuovi)
python -m ruff check app/ tests/
python -m mypy app/valuation/whale_pressure.py app/valuation/insider_pressure.py app/core/yaml_config.py
```

## Commit message proposto

```
feat(valuation): whale_pressure + insider_pressure VAE signals (Phase 13 S4b)

- whale_pressure: event-style (prob indipendente, 0.5=neutrale), criteri D4 size/rank/pnl/new-account
- insider_pressure: microstructure-style (prob centrata su market_price ±0.05), filtri obvious_outcome + pre-res
- WeightsConfig: add whale_pressure=0.05, insider_pressure=0.05 (nominal sum 1.10, effective ~1.00)
- @model_validator accepts sum in [0.95, 1.15] to accommodate Manifold on/off
- Rewrite test_weights_config_sum dynamically (enumerates all fields)
- ExecutionEngine injects signals via external_signals dict (lesson 2026-04-05 pattern)
- 16 new tests + integration test_engine
```

## Handoff a S5b (S5a è indipendente)

- 2 nuovi signal files creati
- `WeightsConfig` esteso con validator permissivo
- VAE integra whale (event) + insider (microstructure) via `_make_input()`
- Test `test_weights_config_sum` passa dinamicamente
- `pytest tests/ -q` 0 fallimenti
- S5b può leggere i nuovi signals nella SSE payload per visualizzazione
