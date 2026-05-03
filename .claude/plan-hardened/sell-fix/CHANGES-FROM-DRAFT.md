# CHANGES-FROM-DRAFT.md — Diff PLAN.draft.md → PLAN.md (FINAL)

**Pipeline**: `/plan-hardened`
**Round 1 input**: `PLAN.draft.md` (Sonnet/Opus draft, 2026-05-02)
**Round 5 output**: `PLAN.md` (FINAL, post-Q1=A, Q2=B, 2026-05-02)
**Round 2 source**: 22 reviewer issues — 19 VALID merged, 0 INVALID rejected, 2 NEEDS_USER resolved (Q1=A, Q2=B), 1 DEFERRED resolved (R2-18 → drop "warning name" test, add NO-price test).

Each entry below includes the originating issue ID (`R2-NN`) or user decision (`Q1`/`Q2`).

---

## Aggiunte

### Scope expansion

| What | Source | Detail |
|------|--------|--------|
| `app/strategies/resolution.py` added to scope | **Q1=A** (R2-01 escalated → user) | Round 2 review found identical bug at `resolution.py:120` (`token_id=self._get_no_token(...)`, `signal_type=SignalType.SELL`). Original draft incorrectly excluded it. |
| `tests/test_strategies/test_resolution.py` added to scope | **Q1=A** (R2-01) | Companion test file modifications (Step 8). |

### New implementation guards

| What | Source | Step |
|------|--------|------|
| `if not token_id:` empty-string guard with `logger.debug(...)` skip | R2-06 | Step 1.3, 2.1, 3.3, 4.1 |
| `_pick_token` rewritten with `Literal["yes", "no"]` typing | R2-17 | Step 1.2 |
| `_pick_token` rewritten without `outcomes[0]` fallback | A3 (per draft) + R2-06 reinforcement | Step 1.2 |
| `.strip().lower()` outcome name matching | R2-11 | Step 1.2, 2.1, 3.2, 4.3 |
| `if/elif/else` defensive form for `combined_edge` | R2-16 | Step 2.1 |
| `combined_edge == 0` explicit `return None` | R2-16 (mediates A6) | Step 2.1 |
| `_get_no_token` returns `None` instead of `""` | R2-06 (Q1=A consequence) | Step 4.3 |

### New tests

| Test | Files | Source |
|------|-------|--------|
| `test_skips_signal_when_no_outcome_missing` | sentiment, event_driven, knowledge_driven, resolution | R2-05 |
| `test_returns_none_for_multi_outcome_market` | sentiment (representative) | R2-05 |
| `test_skips_signal_when_no_token_id_empty` | sentiment, event_driven, knowledge_driven | R2-06 |
| `test_matches_outcome_with_whitespace` | sentiment (representative — covers shared `_pick_token` pattern) | R2-11 |
| `test_buy_no_signal_market_price_equals_no_price` | sentiment, event_driven, knowledge_driven | R2-18 (resolved as Q2=B) |
| Sign convention assertion `assert result.edge_amount < 0` (or `> 0` for resolution) | all 4 test files | R2-13 |

### New "Do NOT modify" entries

| Entry | Source |
|-------|--------|
| `app/strategies/arbitrage.py` (legitimate SELL at lines 141, 152) | R2-12 + V5 grep narrowing (R2-02) |
| `app/strategies/rule_edge.py` | R2-12 |
| `tests/test_strategies/test_arbitrage.py` | R2-12 |
| `tests/test_risk/test_manager.py:119` | R2-12 |
| `tests/test_execution/test_engine.py` | R2-12 (verified empirically) |
| `tests/test_integration/` | R2-19 (verified empirically) |

### New verification commands

| What | Source |
|------|--------|
| V5 grep narrowed to 4 strategy files (was: blanket `app/strategies/`) | R2-02 |
| V5 grep for `_resolve_signal_type`, `_resolve_target_outcome`, `_pick_token` callers in `tests/` | R2-15 |
| V5 grep for `SignalType.SELL` in `tests/test_execution/`, `tests/test_integration/` | R2-19 |
| V2 mypy explicit per-file (covers `Literal` typing) | R2-17 |

### New documentation

| What | Source |
|------|--------|
| Step 9: `.claude/tasks/lessons.md` lesson capture | R2-20 |
| Step 10: follow-up tracking in `.claude/tasks/todo.md` | R2-04, R2-07, cross-ref group-refactor |
| Cross-reference to `.claude/plan-hardened/group-refactor/PLAN.md` (multi-alternative refactor) | User direction (separate `/plan-hardened` run completed) |
| Section "Cross-references" with reference pattern + engine-mapping bug citation | R2-21 + reviewer note + Round 4 user direction |
| Section "Note implementative" → `Order of execution`, `Commit organization`, `Risk assessment`, `Test budget` | R2-22 |
| Commit message proposed (single atomic commit) | R2-22 |
| Section "Ambiguità — TUTTE RISOLTE" closure table | Round 4 finalization |
| `_resolve_target_outcome` typed as `Literal["yes", "no"] | None` (was `str | None` in draft) | R2-17 |
| `market_price` calculation pattern: `yes_price if target_outcome == "yes" else 1.0 - yes_price` | **Q2=B** + R2-04 |

---

## Rimozioni

| What | Source | Why |
|------|--------|-----|
| Reasoning string rewrite ("bullish"/"bearish" replacement) | R2-14 | Scope creep — minimal-scope variant adopted. Existing reasoning preserved across all 4 strategies. Side effect: `test_reasoning_contains_signal_value` works unchanged. |
| Draft assertion "Other strategies (`arbitrage.py`, `rule_edge.py`, `resolution.py`, `value_edge.py`) — non emettono SELL strategico" | R2-01 (factual error: `resolution.py` DOES emit SELL bug) | Replaced with explicit per-strategy classification: arbitrage = legitimate SELL, rule_edge = no SELL, resolution = same bug (now in scope per Q1=A), value_edge = reference pattern. |
| Draft "Step 1.4 / Step 3.4 reasoning rewrite" | R2-14 | Dropped per minimal-scope choice. |
| Draft `_pick_token` with `outcomes[0]` fallback | A3 + R2-06 | Replaced with `None` return → caller skip. |
| Draft `if combined_edge > 0: ... else: ...` 2-branch form (event_driven) | R2-16 | Replaced with `if/elif/else` defensive form to handle `combined_edge == 0`. |
| Draft `valuation.market_price` raw assignment for BUY-NO | **Q2=B** | Replaced with `1.0 - valuation.market_price` (NO book price). |
| Draft `test_buy_no_signal_market_price_equals_valuation_market_price` (warning name) | R2-18 (resolved Q2=B) | Test alternative for option A no longer applicable. Replaced with `test_buy_no_signal_market_price_equals_no_price`. |
| Draft assertion that `value_edge.py` is "già corretto" | Reviewer (R2-04) + Q2 investigation | `value_edge.py:97` has the same `market_price` latent bug. Reclassified: pattern reference for SHAPE (BUY emission, NO token), but NOT for `market_price` value. Tracked as R2-04 follow-up. |

---

## Modifiche

### Helper signatures

| Helper | Draft | Final | Source |
|--------|-------|-------|--------|
| `_resolve_target_outcome` return type | `str | None` | `Literal["yes", "no"] | None` | R2-17 |
| `_pick_token` parameter | `outcome_name: str` | `outcome_name: Literal["yes", "no"]` | R2-17 |
| `_pick_token` empty-string handling | implicit (returned `""`) | explicit `o.token_id or None` | R2-06 |
| `_pick_token` whitespace handling | `.lower()` | `.strip().lower()` | R2-11 |
| `_get_no_token` (resolution.py) | returns `""` on miss | returns `None` on miss; caller checks `if not no_token_id` | R2-06 (Q1=A consequence) |

### Step bodies

| Step | Draft | Final | Source |
|------|-------|-------|--------|
| Step 1.3 (sentiment evaluate body) | hardcode `signal_type = SignalType.BUY`, `market_price = valuation.market_price` | adds `if not token_id:` guard, computes `market_price = yes_price if target == "yes" else 1.0 - yes_price` | R2-06 + Q2=B |
| Step 2.1 (event_driven inline body) | `if combined_edge > 0 / else` 2-branch, fallback `outcomes[0]` | `if/elif/else`, `target_outcome` Literal, `next(...)` with `None` default, guard skip, NO-price computation | R2-16 + R2-21 + R2-06 + Q2=B |
| Step 2.2 (event_driven logger) | not addressed | explicit log key swap `signal_type → target_outcome` | R2-08 |
| Step 3.3 (knowledge_driven evaluate body) | hardcode BUY, raw `market_price` | adds guard, NO-price computation | R2-06 + Q2=B |
| Step 3.4 (knowledge_driven logger) | not addressed | explicit log key swap | R2-09 |
| Step 4 (resolution.py) | NOT IN DRAFT | full Step added: token_id check, `SignalType.BUY`, `market_price = 1.0 - valuation.market_price`, log message rewrite | **Q1=A** + R2-06 + Q2=B |

### Test bodies

| Test | Draft | Final | Source |
|------|-------|-------|--------|
| `test_buy_no_on_negative_sentiment_and_negative_edge` | rename + `signal_type == SignalType.BUY` | + `assert result.edge_amount < 0` (sign convention lock) | R2-13 |
| `test_buy_no_signal_with_negative_composite_and_edge` (event_driven) | rename + `signal_type == SignalType.BUY` | + `assert signal.edge_amount < 0` | R2-13 |
| `test_buy_no_signal_low_probability_market` (resolution) | NOT IN DRAFT | full test added (rename) + `signal.market_price == 1.0 - 0.85` assertion | **Q1=A** + Q2=B |
| `_make_valuation` calls in market_price tests | `_make_valuation(fee_adjusted_edge=-0.06)` | `_make_valuation(fee_adjusted_edge=-0.06, market_price=yes_price)` (explicit fixture wiring) | Q2=B |

### Verification commands

| Command | Draft | Final | Source |
|---------|-------|-------|--------|
| V5 grep scope | `app/strategies/` (blanket) | `app/strategies/{sentiment,event_driven,knowledge_driven,resolution}.py` only | R2-02 (avoid false positives from arbitrage legitimate SELL) |
| V5 grep additions | none | `_resolve_signal_type`, `_resolve_target_outcome`, `_pick_token` in `tests/` (atteso 0); `SignalType.SELL` in `tests/test_execution/`, `tests/test_integration/` (atteso 0) | R2-15, R2-19 |
| V6 done conditions | 3 file test, vague test count | 4 file test, explicit count: +6 sentiment, +3 event_driven, +3 knowledge_driven, +1 resolution + 2 renames | Q1=A + R2-05 + R2-06 + R2-11 + R2-13 + R2-18 |

### Assumptions

| Assumption | Draft | Final | Source |
|------------|-------|-------|--------|
| `value_edge.py` status | "già corretto" | "pattern di riferimento per shape; ha latent `market_price` bug separato (R2-04, follow-up)" | R2-04 + Q2=B |
| Sign of `edge_amount` impact | "potential downstream issue" | "agnostico downstream — verificato in A4 post-R2-03: `engine.py:255`, `engine.py:271`, `risk/manager.py:202` usano `abs()`" | R2-03 |
| Outcome matching | `.lower()` | `.strip().lower()` | R2-11 |

### Cross-reference (NEW section, no draft equivalent)

The FINAL plan adds a top-level "Cross-references" section pointing to `.claude/plan-hardened/group-refactor/PLAN.md` for the multi-alternative event selection refactor. This was not in the draft because the multi-alternative concern surfaced during Round 4 user discussion. The two plans are orthogonal: this fix changes signal emission shape per-market; the group-refactor plan changes the strategy invocation API to operate on grouped Markets. The group-refactor plan declares a preflight gate that depends on **this** fix being merged first (`group-refactor/PLAN.md` lines 13–22). Source: separate `/plan-hardened` run on multi-alternative architectural refactor, completed before finalization of this plan.

---

## Round 2 substitution notice (carried forward)

Codex CLI was not available locally (`which codex` → not found). Per `/plan-hardened` skill fallback policy, Round 2 was performed by the `code-reviewer` subagent (read-only by design, adversarial intent). The `CODEX-REVIEW.json` filename was preserved for pipeline consistency. The substitution is noted in the JSON's `reviewer` and `reviewer_note` fields. No reviewer issue was rejected as false positive — all 22 were independently verified.

---

## Round summary table

| Round | Output | Status |
|-------|--------|--------|
| Round 1 | `PLAN.draft.md` | Archived to `.audit/` |
| Round 2 | `CODEX-REVIEW.json` (22 issues, code-reviewer fallback) | Archived to `.audit/` |
| Round 3 | `PLAN.v2.md`, `REJECTED-SUGGESTIONS.md`, `OPEN-AMBIGUITIES.md` | `PLAN.v2.md` archived; `REJECTED-SUGGESTIONS.md` retained at root; `OPEN-AMBIGUITIES.md` archived |
| Round 4a | Q1 user decision: **A** (include `resolution.py`) | Resolved |
| Round 4b | Q2 investigation (Q2-INVESTIGATION.md, Explore agent + screenshot) | Archived to `.audit/` |
| Round 4c | Q2 user decision: **B** (`market_price = 1.0 - valuation.market_price`) | Resolved (post-pause, after multi-alternative discussion concluded → separate plan) |
| Round 5 | `PLAN.md` (FINAL), `CHANGES-FROM-DRAFT.md` (this file), `REJECTED-SUGGESTIONS.md` (carried) | This commit |

---

## Post-implementation audit (2026-05-03)

After V1-V5 verification gates passed, an independent Codex audit was run on the implemented work to detect any drift between PLAN.md spec and committed code. Two gaps were identified and closed in the same atomic commit:

| ID | Severity | File | Issue | Fix |
|----|----------|------|-------|-----|
| R-AUDIT-01 | MAJOR | `tests/test_strategies/test_resolution.py` | Missing `test_skips_signal_when_no_token_id_empty`. The other 3 strategy test files all have it (R2-06 in this CHANGES doc). Asymmetric copy-paste during Step 8 — V5 did not catch it because grep was scoped to production files. | Added test at line 226. Resolution tests now 18/18 (was 17). |
| R-AUDIT-02 | MINOR | `app/strategies/resolution.py` | `_get_yes_price` (line 148) and `_get_yes_token` (line 155) used `.lower()` without `.strip()`, inconsistent with `_get_no_token` (line 162) which was updated per R2-11. Same surface bug class as R2-11. | Both helpers now use `.strip().lower()` for symmetry. |

Hallucination findings (lower severity, recorded for post-mortem):
- Test count claim "13 new tests" was off by one — actual delta is 12 net-new + 7 renames.
- Pre-V3 claim "73/73 strategy tests passed" was a function-count from static analysis, not a pytest run. Post-audit empirical V3 = 125/125 strategies dir, V4 = 778+1 new = 779 passed/0 failed.

**Lesson**: V5 (grep scoped to production) does not detect cross-file test asymmetries. For multi-file repeat-fix scope, add a "test parity matrix" verification step (Nx M cell grid: N test files × M required test names → all cells must be present).
