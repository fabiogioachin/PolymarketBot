# REJECTED-SUGGESTIONS.md — Round 3 merge decisions

**Pipeline**: `/plan-hardened`
**Round 3**: Opus merge of Round 2 adversarial review
**Source**: `.claude/plan-hardened/CODEX-REVIEW.json` (22 issues)

This file documents which Round 2 issues were **REJECTED** (false positives, out of scope, or merged with modification) with motivation. VALID issues are merged into `PLAN.v2.md`. NEEDS_USER issues are escalated to `OPEN-AMBIGUITIES.md`.

---

## Summary

| Severity | Total | VALID merged | NEEDS_USER | REJECTED | DEFERRED |
|----------|-------|--------------|------------|----------|----------|
| BLOCKER  | 4     | 2            | 2          | 0        | 0        |
| MAJOR    | 11    | 11           | 0          | 0        | 0        |
| MINOR    | 7     | 6            | 0          | 0        | 1        |
| **Tot**  | **22**| **19**       | **2**      | **0**    | **1**    |

No issue rejected as false positive — code-reviewer's verifications were all confirmed by independent reads of:
- `app/strategies/resolution.py` (R2-01 confirmed)
- `app/strategies/arbitrage.py` (R2-02 confirmed)
- `app/risk/manager.py:202` (R2-03 confirmed — uses `abs()`)
- `tests/test_execution/test_engine.py`, `tests/test_integration/` (R2-19 confirmed — no SELL usage)
- `tests/test_strategies/test_resolution.py:189` (R2-01 test confirmed)

---

## Issues classification

### BLOCKER

| ID | Decision | Notes |
|----|----------|-------|
| R2-01 | NEEDS_USER | Scope decision: include `resolution.py` (4th strategy with identical bug) in this PR or split? |
| R2-02 | VALID merged | V5 grep narrowed to 3 strategy files |
| R2-03 | VALID merged | A4 analysis corrected — all downstream uses `abs()` so sign is purely informational |
| R2-04 | NEEDS_USER | `market_price` for BUY NO: option A (consistent with value_edge bug, broken live) vs option B (correct, requires value_edge follow-up) |

### MAJOR

| ID | Decision | Notes |
|----|----------|-------|
| R2-05 | VALID merged | Multi-outcome test added; filter location couldn't be located at `app/services/market.py` (path doesn't exist) — assumption restated without file:line, accepting this caveat |
| R2-06 | VALID merged | `if not token_id` guard + empty-string test |
| R2-07 | VALID merged | Documented as known limitation, follow-up tracked, NO scope expansion |
| R2-08 | VALID merged | `logger.info` Step 2.2 made explicit |
| R2-09 | VALID merged | `logger.info` updates added to Steps 1 & 3 |
| R2-10 | VALID merged | Test class/module placement specified per file |
| R2-11 | VALID merged | `.strip().lower()` adopted; whitespace test added to `test_sentiment.py` only (single representative test, no need for triple coverage) |
| R2-12 | VALID merged | "Do NOT modify" list expanded |
| R2-13 | VALID merged | Sign convention test added: `assert result.edge_amount < 0` for BUY-NO. Engine integration test deferred as out-of-scope (current `engine.py:_priority` is fully exercised by other tests) |
| R2-14 | VALID merged with modification | Reasoning rewrite DROPPED (option a — minimal scope). Existing "bullish"/"bearish" wording preserved (also keeps `test_reasoning_contains_signal_value` working unchanged). Step 1.4 and Step 3.4 in PLAN.draft removed |
| R2-15 | VALID merged | `_resolve_signal_type|_pick_token` greps added to V5 |

### MINOR

| ID | Decision | Notes |
|----|----------|-------|
| R2-16 | VALID merged | `if/elif/else` defensive form for `combined_edge` |
| R2-17 | VALID merged | `Literal["yes", "no"] \| None` typing adopted |
| R2-18 | DEFERRED | Decision contingent on R2-04. If user picks option A → keep test with renamed-warning name; if option B → drop test entirely |
| R2-19 | VALID merged | Grep added to V5. Verified upfront: `tests/test_execution/` and `tests/test_integration/` use only `SignalType.BUY`, no breakage expected |
| R2-20 | VALID merged | Step 7 added: capture lesson in `.claude/tasks/lessons.md` |
| R2-21 | VALID merged | Step 2.1 expanded with literal current code |
| R2-22 | VALID merged | Commit organization documented: single atomic commit recommended |

---

## Rejected outright

**None.** All 22 issues were either accepted, escalated to user, or deferred pending earlier decision. Code-reviewer's adversarial pass surfaced legitimate gaps; no false positives.

---

## Round 2 substitution notice

Codex CLI was not available locally (`which codex` → not found). Per `/plan-hardened` skill fallback policy, Round 2 was performed by the `code-reviewer` agent (read-only by design, adversarial intent). The `CODEX-REVIEW.json` filename was preserved for pipeline consistency. The substitution is noted in the JSON's `reviewer` and `reviewer_note` fields.
