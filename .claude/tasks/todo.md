# PolymarketBot — Task Tracker

> **System state (2026-04-25):** Phase 13 complete. 870+ tests passing. Python 3.11, FastAPI, Pydantic v2, 11 VAE signals, 7 strategies, 150 EUR capital (dry_run).
> **History:** Phase 11 (trading + dashboard fixes), Phase 12 (persistence + integration tests), Phase 13 (dynamic edge, platform collectors, subgraph, whale/insider VAE, DSS artifact + dashboard widgets) — all done.
> **Config:** secrets in `.env`, tunables in `config/config.yaml` (not in repo — use `config.example.yaml`). Singletons wired in `app/core/dependencies.py`.

---

## Pending User Action (non-automatable)

- [ ] Add `# THEGRAPH_API_KEY=` (commented) to `.env.example` manually.
  Hook `~/.claude/hooks/protect-critical-files.sh` regex `'/\.env(\..*)?$'` blocks all automated edits on `.env*` including `.env.example`. Non-blocking: `TheGraphClient` fails soft on free tier without the var.

---

## P0 — Bugs (fix before any new feature)

### BUG-1: Identical consecutive bets across ticks ✅ FIXED 2026-04-25

**Symptom:** Bot places identical orders (same market, same side, same price) in consecutive ticks.
**Root cause:** No dedup guard in `engine.tick()`. Strategies are stateless w.r.t. portfolio (correct), but no downstream layer enforced "non riaprire posizione già aperta sullo stesso token". `RiskManager.record_fill()` accumula esposizione, `PolymarketClobClient._add_to_position()` weighted-merge → avg_price drift; ogni fill loggato come trade separato → "open" duplicati.
**Fix:** [engine.py:199-209](app/execution/engine.py:199) cattura `open_position_token_ids` (size > 0.001) dopo `_manage_positions`; [engine.py:233-244](app/execution/engine.py:233) droppa `SignalType.BUY` su token già held. Per-token (non per-market) per non bloccare arbitraggi multi-leg / outcome NO.
**Tests:** [test_engine.py](tests/test_execution/test_engine.py) `TestDuplicatePositionDedup` (4 casi: dedup attivo, sanity, per-token, dust). Aggiornato `test_partial_exit_does_not_block_reevaluation` per usare `tok-fresh`. 244/244 pass su execution+risk+strategies.
**Lesson:** `lessons.md` — 2026-04-25 BUG-1 dedup mancante.

---

### BUG-2: `rule_edge.py` always returns BUY on negative edge ✅ FALSE POSITIVE 2026-04-26

**Verified:** Bug doesn't exist. `rule_edge.py:128-140` already implements the value_edge pattern: `edge > 0` → BUY YES, `edge < 0` → BUY NO. Confirmed via `git log -p` (this is the original implementation from initial commit, never broken). The earlier ticket misread line 136 (`signal_type = SignalType.BUY` inside the negative-edge branch) without seeing the adjacent token_id swap on lines 137-140.
**Action taken 2026-04-26:**
- Renamed misleading test `test_sell_signal_when_negative_edge_with_clear_rules` → `test_buy_no_token_when_negative_edge_with_clear_rules` (the test name said "sell" but the assertions verify BUY-NO).
- Strengthened assertions: `edge_amount` preservation, confidence boost/penalty under clear/ambiguous rules.
- Added `test_buy_no_token_when_negative_edge_with_ambiguous_rules` for completeness.
**Tests:** 12/12 in `test_rule_edge.py`, 245/245 across strategies+execution+risk.
**Related (out of scope):** Both `rule_edge` and `value_edge` set `Signal.market_price = valuation.market_price` (YES price) even when emitting on the NO token. Engine uses `signal.market_price` directly as the order price ([engine.py:294,316](app/execution/engine.py:294)). On a BUY-NO order this places the order at the YES price (~0.6 → buy NO at 0.6, when NO actually trades at ~0.4). This is a *separate* systemic issue affecting both strategies — file as a new ticket if confirmed by trade-log audit. Keeping out of BUG-2 scope per spec ("mirror value_edge.py pattern").

---

## P1 — Investigation + Fix: Edge near-zero in practice ✅ FIXED 2026-04-27

**Hypothesis confirmed empirically.** Diagnostic in [scripts/debug_edge_zero.py](scripts/debug_edge_zero.py): on a sparse-data market (price 0.60, no orderbook, no history, empty resolution DB) the engine produced `fair_value=0.59`, `edge=-0.01` — only `base_rate` fired, contributing `-0.01` because its old shrinkage formula returned `0.10 * 0.5 + 0.90 * market_price = 0.59` (anchored).

**Per-signal behavior (pre-fix audit):**
| Signal | Behavior on missing data | Anchored? |
|--------|--------------------------|-----------|
| `base_rate` | `0.10*hist + 0.90*market_price` (count<5) | **YES — primary culprit** |
| `microstructure` | `composite_score=0.0 → market_price - 0.05` (empty orderbook) | **YES — secondary** |
| `cross_market` | `composite_signal=0.0 → market_price + 0` (no correlations) | **YES — secondary** |
| `crowd_calibration` | `0.0` (excluded by `if != 0`) | NO ✓ |
| `rule_analysis` | `None` (never populated in production) | NO ✓ |
| `event_signal` | `None` (filtered by `_fetch_intelligence_signals`) | NO ✓ |
| `pattern_kg` | `None` (filtered by `_fetch_kg_signals`) | NO ✓ |
| `cross_platform` | `None` (Manifold disabled) | NO ✓ |
| `whale_pressure` | `None` (filtered when `signal == 0.5`) | NO ✓ |
| `insider_pressure` | `None` (filtered when `signal == 0.5`) | NO ✓ |
| `temporal` | scales edge, not anchored | N/A ✓ |

**Fix applied:**
- [base_rate.py:40-58](app/valuation/base_rate.py:40) — `get_prior` now returns `Optional[float]`. Below `valuation.gating.min_base_rate_resolutions` (default 5) → `None`. Above → raw historical rate (no market_price blending; the engine's weighted average is what mixes signals).
- [valuation/engine.py:78-90](app/valuation/engine.py:78) — `microstructure` excluded when both orderbook (no bids/asks) and history (no points) are empty. `cross_market` excluded when no correlations found.
- [yaml_config.py:146-179](app/core/yaml_config.py:146) — new `GatingConfig` with `min_base_rate_resolutions: int = 5`, `require_cross_market_correlations: bool = True`, `require_microstructure_data: bool = True`.
- [config/config.example.yaml:71-78](config/config.example.yaml:71) — new `valuation.gating` block documenting the knobs.

**Tests:** added 7 gating regression tests in [test_engine.py:500-624](tests/test_valuation/test_engine.py:500), updated 3 base_rate tests + 1 integration test. `test_insider_pressure_signal_is_dampened` now correctly observes 0.04 delta (the actual ±0.05 cap was masked by base_rate's anchoring pre-fix). 103/103 valuation tests green.

**Verification (post-fix diagnostic, [scripts/debug_edge_zero.py](scripts/debug_edge_zero.py)):** on the same sparse-data market the engine now reports honest output instead of fake-anchored output:
| Scenario | Pre-fix | Post-fix |
|----------|---------|----------|
| sparse (no inputs) | `fair_value=0.59`, edge=-0.01 (anchored) | `fair_value=0.60`, edge=0.00 (no signals fire) |
| `whale_pressure=0.85` | `fair_value=0.655`, edge=+0.055 (dampened) | `fair_value=0.85`, edge=+0.25 (full impact) |
| `event_signal=0.40` | `fair_value=0.495`, edge=-0.105 (dampened) | `fair_value=0.40`, edge=-0.20 (full impact) |

---

## P1 — Tech Debt: SELL ≠ BUY NO (4 strategies) ✅ FIXED 2026-05-02

**Problem:** `sentiment`, `event_driven`, `knowledge_driven`, `resolution` emit `SignalType.SELL` on the NO token to express "buy NO" intent. The engine (`engine.py:312`) maps `SELL` → `OrderSide.SELL` on the tagged token — silently invalid in shadow/live (sells shares the bot does not own), broken P&L tracking in dry_run.

**Plan**: `.claude/plan-hardened/sell-fix/PLAN.md` (FINAL, post-`/plan-hardened` pipeline). Q1=A (resolution.py incluso, 4° strategia con stesso bug), Q2=B (`market_price = 1.0 - valuation.market_price` per BUY-NO).

**Fix applied:** 4 strategies now emit `SignalType.BUY` on `token_id=NO_token` for bearish intent, with `market_price = 1.0 - valuation.market_price`. Helper `_resolve_target_outcome` returns `Literal["yes","no"] | None`; `_pick_token` removed `outcomes[0]` fallback (returns `None`); guard `if not token_id: return None` in all 4. `.strip().lower()` on outcome name matching (incluso YES helpers in `resolution.py`, allineato post-audit). 12 nuovi test + 7 rename coprono skip-no-missing, skip-empty-token (anche `test_resolution.py`, aggiunto post-audit), whitespace match, market_price=NO_price, edge_amount sign convention. Verifica empirica: V3 strategies 125/125, V4 full suite 779/1 skipped/0 failed.

**Post-implementation Codex audit (2026-05-03)**: 2 gap chiusi nello stesso commit:
- MAJOR: `test_resolution.py` mancava `test_skips_signal_when_no_token_id_empty` (asimmetria cross-file sui 4 test file — gli altri 3 ce l'avevano).
- MINOR: `resolution.py::_get_yes_price` e `_get_yes_token` usavano `.lower()` senza `.strip()`, inconsistenti con `_get_no_token` post-fix.

**Audit trail**:
- `PLAN.md` — final implementation plan (4 strategies + 4 test files + lessons + this todo update)
- `CHANGES-FROM-DRAFT.md` — diff Round 1 → Final con citation per ogni cambio
- `REJECTED-SUGGESTIONS.md` — Round 3 reviewer triage (22 issues, 19 VALID, 0 false positives)
- `.audit/` — intermediates: `PLAN.draft.md`, `PLAN.v2.md`, `CODEX-REVIEW.json`, `OPEN-AMBIGUITIES.md`, `Q2-INVESTIGATION.md`

**Lesson:** `lessons.md` — 2026-05-02 SignalType.SELL semantics.

**Branched workstream**: multi-alternative event selection refactor — `.claude/plan-hardened/group-refactor/PLAN.md` (separate `/plan-hardened` run). That plan declares a preflight gate that **depends on the SELL→BUY-NO fix being merged first**.

### Follow-ups discovered durante il `/plan-hardened` (da pianificare separatamente)

- **R2-04**: `value_edge.py:97` — fix `market_price` to `1.0 - valuation.market_price` for BUY-NO branch (consistency con post-fix sentiment/event_driven/knowledge_driven/resolution). Latent bug analogo, non incluso nello scope del fix corrente per minimal-blast-radius. Reference pattern shape resta corretto, solo `market_price` field è errato.
- **R2-07** (BUG-3): cross-token same-market dedup guard — `engine.py:233-244` controlla solo `sig.token_id in open_position_token_ids`, non cross-token same-market. Conseguenza post-fix: il bot può aprire YES + NO sullo stesso market (hedge parziale, controproducente date le fee). Fix proposto: dedup chiave su `(market_id,)` invece di `(token_id,)` PRIMA di chiamare `risk.size_position`.

---

## P2 — Tech Debt: Silence as evidence (evidence-of-absence)

**Problem:** No GDELT news on an upcoming event → `event_signal` returns `market_price` (neutral). No whale activity → `whale_pressure` returns `0.5` (neutral). Absence of evidence should weakly push `fair_value` below `market_price`, not anchor it.

**Proposed approach:**
- `event_signal`: if query returns 0 articles AND market has been live > N days → return `market_price * decay_factor` (e.g., `* 0.95`), not `market_price`.
- `whale_pressure`: if no whale trades in last 48h → return `0.45` (slight NO pressure), not `0.5`.
- Make both configurable via `config.yaml` so they can be tuned/disabled.

**Files to modify:**
- `app/valuation/` — whichever file implements `event_signal` (likely called from `engine.py` via `intelligence_orchestrator`)
- `app/valuation/whale_pressure.py`
- `config/config.example.yaml` — add config keys for silence decay params

**Done = ** on markets with zero recent activity, `fair_value` is measurably < `market_price`. Tunable via config. Tests cover silence scenario.

---

## P3 — New Feature: NO-hunter strategy

**What:** A dedicated strategy that actively searches for overpriced YES markets (= underpriced NO). Unlike `value_edge` (which incidentally handles NO via negative edge), this strategy is explicitly optimized for:
- Markets where the event is structurally unlikely (base_rate < 0.3, no recent GDELT, no whale momentum)
- YES price > 0.5 (market over-assigns probability to event happening)
- Edge on NO side > threshold

**Design:**
```python
class NoHunterStrategy(BaseStrategy):
    """Finds YES-overpriced markets → BUY NO."""
    
    def evaluate(self, market, valuation) -> Signal | None:
        no_edge = (1.0 - valuation.fair_value) - (1.0 - market.yes_price)
        # equivalent to: market.yes_price - valuation.fair_value
        if no_edge > self._min_edge and market.yes_price > 0.5:
            return Signal(
                signal_type=SignalType.BUY,
                token_id=market.no_token_id,
                market_price=1.0 - market.yes_price,
                edge_amount=no_edge,
                ...
            )
```

**Files to create/modify:**
- `app/strategies/no_hunter.py` (new)
- `app/strategies/__init__.py` — register strategy
- `app/core/dependencies.py` — add to `StrategyRegistry`
- `config/config.example.yaml` — add `no_hunter` strategy config block
- `tests/test_strategies/test_no_hunter.py` (new)

**Done = ** strategy registered, evaluates correctly in tick cycle, emits BUY NO signals when YES is overpriced. Tests cover positive signal, below-threshold no-signal, and no_token_id missing cases.

---

## Deferred (Phase 14)

- **ValuationResultStore:** `realized_volatility` and `price_history_60min` in SSE payload currently return `None/[]`. Dashboard `static/dss/dss.js` and `static/js/app.js` have `// TODO Phase 14: ValuationResultStore`. Requires an in-memory or SQLite store that accumulates per-market VAE outputs over time.
- **`record_divergence()`** not yet wired into the tick cycle. Tracks Manifold vs Polymarket price divergences to SQLite for calibration.
- **Obsidian seeding:** `pattern_kg` signal returns `None` (weight excluded) until Obsidian vault is seeded with market patterns. `event_driven` strategy inactive for same reason. See `scripts/seed_patterns.py`.
