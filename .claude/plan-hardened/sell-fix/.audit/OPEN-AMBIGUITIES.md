# OPEN-AMBIGUITIES.md — Round 4 user decisions required

**Pipeline**: `/plan-hardened`
**Source**: Round 3 merge of Round 2 review
**Status**: 2 decisions blocking finalization

---

## Q1 — R2-01 — Scope decision: include `resolution.py`?

### Background

`app/strategies/resolution.py:99-128` has the **identical** bug pattern as the 3 strategies in scope:

```python
# resolution.py:116-120
return Signal(
    strategy=self.name,
    market_id=market.id,
    token_id=self._get_no_token(market),    # NO token id
    signal_type=SignalType.SELL,            # ← BUG: should be BUY
    confidence=confidence,
    market_price=valuation.market_price,
    ...
)
```

The `logger.info("resolution: SELL signal (buy NO)", ...)` at line 109 even acknowledges the intent (`buy NO`) while the emitted SignalType is wrong.

### Options

**A. Include `resolution.py` in this PR (widen scope)**
- 4 strategies fixed atomically: `sentiment`, `event_driven`, `knowledge_driven`, `resolution`
- `tests/test_strategies/test_resolution.py:179-192` (`test_sell_signal_low_probability_market`) updated alongside
- Larger blast radius (1 more prod file, 1 more test file)
- Single commit message covers all 4
- Removes a known live instance of the bug immediately

**B. Document `resolution.py` as separate follow-up (keep scope)**
- 3 strategies fixed in this PR (as originally specified)
- Issue tracked in `.claude/tasks/todo.md` for next session
- Smaller, more reviewable PR
- Bug remains live in `resolution.py` until follow-up

### Recommendation

**Option A** — the user's original prompt said "fix this tech debt" with reference pattern from `value_edge.py`. The drafter's claim that "resolution.py doesn't have the bug" was incorrect (factual error). Including it now is true to the prompt's intent. The marginal cost is tiny (1 file + 1 test, same logic).

---

## Q2 — R2-04 — `market_price` semantic for BUY NO

### Background

The user's original prompt asserted:
```python
market_price = 1.0 - yes_price     # NO token price
```

But `value_edge.py:97` (cited as the reference) does NOT do this — it passes `valuation.market_price` (= YES price) verbatim for both BUY YES and BUY NO branches. Code-reviewer flagged this as a position-sizing bug:

- `engine.py:294`: `price = signal.market_price` → if YES price, OrderRequest carries YES price for a NO order
- `engine.py:297` → `risk.size_position(signal, balance, price)` → shares computed with wrong price reference
- `engine.py:313` → `OrderRequest(token_id=NO_token, price=YES_price, size=...)` — economically incorrect in shadow/live modes

In `dry_run` the trade "works" but P&L tracking is wrong. In `shadow`/`live` the broker would either reject (price too far from book) or fill at market with completely wrong economics tracking.

### Options

**A. `market_price = valuation.market_price` (consistent with `value_edge.py`)**
- Same code as the existing reference
- BUT `value_edge.py` itself has this latent bug — both stay broken
- Requires a "live mode unsafe pending value_edge fix" gate

**B. `market_price = 1.0 - valuation.market_price` (correct)**
- Position sizing and order price both use NO_price reference (correct economics)
- BUT diverges from `value_edge.py` (which keeps the latent bug until separately fixed)
- Tracks a follow-up task: `value_edge.py:97 — fix market_price to NO_price for BUY-NO branch`
- The 3 strategies in scope are correct from day one

### Recommendation

**Option B** — option A is silently broken in shadow/live mode (the entire reason the user filed this tech debt). Choosing option A "for consistency" with a buggy reference perpetuates the problem. The right fix is option B + follow-up issue for `value_edge.py`.

### Downstream impact (verified)

Sign of `edge_amount` is **agnostic** in all observed code paths:
- `engine.py:255` priority: `abs(sig.edge_amount)`
- `engine.py:271` risk KB: `abs(signal.edge_amount)`
- `risk/manager.py:202` sizing: `edge=abs(signal.edge_amount)`
- `engine.py:339, 353` log strings only print signed value (informational)

So the only material consequence of A vs B is whether the `market_price` field on the Signal is YES or NO price. Option B propagates correctly to OrderRequest pricing.

### R2-18 cascade

If option A → keep `test_buy_no_signal_market_price_equals_valuation_market_price` (with renamed warning name `..._currently_equals_yes_price_pending_value_edge_followup`).
If option B → drop that test entirely; add `test_buy_no_signal_market_price_equals_one_minus_yes_price` instead.

---

## Decision summary

| Question | Recommendation | Reason |
|----------|---------------|--------|
| Q1: include `resolution.py`? | A (include) | Same bug, atomic fix matches prompt intent |
| Q2: `market_price` semantic? | B (1.0 - yes_price) | Option A is silently broken in shadow/live |

Both decisions are independent. User can pick any combination (4 total combinations).
