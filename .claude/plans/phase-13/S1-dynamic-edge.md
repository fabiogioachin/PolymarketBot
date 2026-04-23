# S1 — Dynamic Edge + Tracker Update

| **Modello consigliato** | **Effort** | **Wave** | **Parallelizzabile con** |
|--------------------------|-----------|----------|---------------------------|
| **Opus 4.7** (1M context) | **alto** | W1 | — (standalone) |

**Perché Opus 4.7:** formula sign-preserving con 3 componenti interagenti (CI + velocity penalty + edge-strength dampener) richiede verifica matematica invariant-by-invariant. 1M context permette di caricare plan + engine.py completo + tutti i test valuation esistenti senza compaction, riducendo rischio di regressione su 687 test.

---

## Obiettivo

Implementare edge dinamico volatility-aware nel VAE (formula D1 con bug di segno fix + edge-strength dampener), aggiornare `todo.md`/`lessons.md`.

## Dipendenze

**Nessuna.** Codebase stabile (687 test pass). Prima sessione della Phase 13.

## File master (LEGGI PRIMA)

- [../00-decisions.md](../00-decisions.md) — decisioni D1-D6, specialmente **D1** (formula completa)

## File da leggere all'avvio

- [.claude/tasks/todo.md](.claude/tasks/todo.md), [.claude/tasks/lessons.md](.claude/tasks/lessons.md)
- [app/valuation/engine.py](app/valuation/engine.py) (edge block a 99-136; `_compute_fair_value` a 194)
- [app/valuation/microstructure.py](app/valuation/microstructure.py), [app/valuation/temporal.py](app/valuation/temporal.py)
- [app/models/valuation.py](app/models/valuation.py), [app/core/yaml_config.py](app/core/yaml_config.py)
- [app/clients/polymarket_rest.py](app/clients/polymarket_rest.py) (386-410: `get_price_history`)
- [config/config.example.yaml](config/config.example.yaml)

## Skills / Agenti / MCP

- Skill [.claude/skills/vae-signal/SKILL.md](.claude/skills/vae-signal/SKILL.md)
- Skill [.claude/skills/config-system/SKILL.md](.claude/skills/config-system/SKILL.md)
- Agente `backend-specialist` (implementazione)
- Agente `test-writer` (test suite)
- Agente `code-reviewer` (review finale)
- MCP `obsidian` per nota decisionale finale

---

## Step esecutivi

**STEP 0 — Tracker update (orchestrator).**
- Modifica [.claude/tasks/todo.md](.claude/tasks/todo.md): archivio Phase 11/12, apertura Phase 13 con link a `.claude/plans/phase-13/00-decisions.md`.
- Modifica [.claude/tasks/lessons.md](.claude/tasks/lessons.md): archivia 4 stale entries, aggiungi 3 nuove (vedi master `00-decisions.md` sezione "Aggiornamento lessons.md").

**STEP 1 — Volatility helpers** (backend-specialist). In [app/valuation/microstructure.py](app/valuation/microstructure.py) aggiungi a `MicrostructureAnalyzer`:
- `@staticmethod realized_volatility(points, window_minutes=60) -> float`: log-returns consecutivi, `statistics.stdev` se ≥3 punti, altrimenti 0.0. NON annualizzare.
- `@staticmethod price_velocity(points, window_minutes=30) -> float`: `(p_last - p_first) / window_minutes` se ≥2 punti, altrimenti 0.0.

**STEP 2 — Model extend.** In [app/models/valuation.py](app/models/valuation.py):
- `ValuationResult` +: `edge_lower`, `edge_upper`, `edge_dynamic`, `realized_volatility`, `price_velocity` (tutti `float | None = None`).
- `ValuationInput` +: `whale_pressure_signal: float | None = None`, `insider_pressure_signal: float | None = None` (placeholder per S4b).

**STEP 3 — Config.** In [config/config.example.yaml](config/config.example.yaml) dentro `valuation:`:
```yaml
volatility:
  window_minutes: 60
  velocity_window_minutes: 30
  k_short: 0.5
  k_medium: 0.75
  k_long: 1.0
  velocity_alpha: 0.5
  strong_edge_threshold: 0.10
  min_observations: 3
```
Aggiungi `VolatilityConfig` Pydantic in [app/core/yaml_config.py](app/core/yaml_config.py).

**STEP 4 — Engine (CORE, attenzione al bug di segno).** In [app/valuation/engine.py](app/valuation/engine.py) righe ~99-136 sostituisci il blocco edge con la **formula D1 completa** dal master (`00-decisions.md` → sezione D1). Popola i nuovi campi di `ValuationResult`. Mantieni `fee_adjusted_edge = edge_central` per backward compat (commento).

**STEP 5 — Test dynamic edge.** Crea `tests/test_valuation/test_dynamic_edge.py` con 10 test:
1. `test_realized_volatility_insufficient_data` (<3 pt → 0.0)
2. `test_realized_volatility_stable_price` (≈0)
3. `test_realized_volatility_volatile_price` (>0)
4. `test_price_velocity_positive`, `test_price_velocity_negative`
5. `test_edge_dynamic_zero_vol_equals_static` (backward compat critico)
6. `test_edge_dynamic_preserves_sign` — edge_central=-0.05, velocity adversa → edge_dynamic < 0 e |edge_dynamic| ≤ |edge_central| (bug di segno fix verify)
7. `test_edge_lower_gates_recommendation` (edge=0.04, vol=0.05 → HOLD)
8. `test_edge_strength_bypasses_velocity_penalty` — edge=0.12 (sopra threshold), velocity adversa → penalty ≈ 1.0 (allucinazione collettiva)
9. `test_valuation_result_backward_compat` (no price_history → edge_dynamic == edge_central o None)
10. **Regressione esplicita**: riesegui `tests/test_valuation/test_value_engine.py` — verifica 0 fallimenti.

**STEP 6 — Code review + Obsidian.**
- `code-reviewer` sui file modificati.
- Via MCP `obsidian` crea `Projects/PolymarketBot/Decisions/2026-04-23-Dynamic-Edge.md` con: formula, razionale, parametri config, riferimento a Phase 13 S1.

---

## Verification finale (exit code 0 su tutti)

```bash
cd "C:\Users\fgioa\OneDrive - SYNESIS CONSORTIUM\Desktop\PRO\PolyMarket"
python -m pytest tests/test_valuation/test_dynamic_edge.py -v
python -m pytest tests/ -q                                          # atteso: 697+ pass
python -m ruff check app/ tests/
python -m mypy app/valuation/ app/models/valuation.py
```

## Commit message proposto

```
feat(valuation): volatility-aware dynamic edge with sign-preserving velocity penalty (Phase 13 S1)

- Add realized_volatility() and price_velocity() to MicrostructureAnalyzer
- Replace scalar edge with (edge_lower, edge_central, edge_upper, edge_dynamic)
- edge_magnitude = max(0, |edge_central| - k*σ); preserves sign on negative edges
- edge-strength dampener: |edge| >= 0.10 bypasses velocity penalty (user caveat)
- Gating on edge_dynamic, not fee_adjusted_edge (kept for backward compat)
- Config: valuation.volatility block (window, k_per_horizon, velocity_alpha, strong_edge_threshold)
- 10 tests including sign-preservation and bypass regression
- Tracker: archive Phase 11-12, open Phase 13
```

## Handoff a S2

Conferma questi invarianti prima che S2 parta:
- [`app/valuation/microstructure.py`] ha i 2 nuovi statici `realized_volatility` e `price_velocity`
- [`app/models/valuation.py`] ha i 5 nuovi campi `ValuationResult` + 2 placeholder `ValuationInput`
- [`config/config.example.yaml`] ha `valuation.volatility` completa
- [`tests/test_valuation/test_dynamic_edge.py`] esiste con 10 test pass
- `pytest tests/ -q` esce con 0 (nessuna regressione)
- `git log -1 --oneline` mostra il commit Phase 13 S1
