# OPEN-AMBIGUITIES.md — Group-aware refactor (Round 4 input)

**Pipeline**: /plan-hardened — Round 3 → Round 4 escalations
Generated: 2026-05-02

Two questions for the user. Both block the freeze of PLAN.v2.md. PR-J explicitly depends on Q1; PR-B engine refactor depends on Q2.

---

## Q1 — Scope: include `app/risk/manager.py`, `app/core/dependencies.py`, `app/core/yaml_config.py`, `config/config.example.yaml`?

**Bundles**: R2-01 (BLOCKER), R2-02 (MAJOR), R2-03 (MAJOR), R2-16 (MAJOR), R2-17 (MAJOR), R3-01 (drafter-found).

### Background

The Round 1 draft routinely modifies four files that were NOT in the explicitly authorized scope of this refactor:

1. **`app/risk/manager.py`** — entirely owned by PR-J (event-level exposure cap). PR-J also requires persistence across restart (R2-16: track `token_id → event_id` in TradeStore/RiskKB) and atomic reserve-and-record (R2-17: `asyncio.Lock` to prevent concurrent ticks from both passing the cap). All three issues are real, but they live in a file the user did not authorize.

2. **`app/core/dependencies.py`** — every PR from PR-B through PR-K touches the strategy registration block (lines 218-243) to wrap or un-wrap strategies through `LegacyStrategyAdapter` as migration progresses. The mechanism is genuinely needed for the incremental migration; the question is whether it lives in `dependencies.py` (cleanest) or in `app/strategies/registry.py` (in-scope, but architecturally awkward — registry would need to know about which strategies are "currently wrapped" as state).

3. **`app/core/yaml_config.py`** — needs `risk.max_event_exposure_pct` (PR-J) and arguably `markets.max_per_event` (R2-10 top-K cap, currently merged as a hardcoded constant if config stays out of scope).

4. **`config/config.example.yaml`** — same as above; user-visible default config.

The fixed constraint says nothing about these files — they were neither blessed nor explicitly excluded. The Codex review surfaced the omission as scope creep.

### Options

- **A — Approve scope expansion**. Add all four files to the authorized scope. PR-J ships in this plan with full persistence + atomic reserve. Strategy wrapping lives in `dependencies.py` (one-line wrap/un-wrap per strategy). Config exposes both knobs. **Tradeoff**: largest scope, but cleanest architecture and avoids fragmenting the work into a follow-up plan that nobody reads. Done condition list grows ~5-7 items. Estimated extra work: ~1 small PR worth of test coverage for persistence + concurrency.

- **B — Reject PR-J only; keep dependencies/yaml_config in scope**. Approve `app/core/dependencies.py` + `app/core/yaml_config.py` + `config/config.example.yaml` (these three are necessary for any sane migration), but split PR-J (event exposure cap) into a separate authorized risk plan. Result: this plan has 10 PRs (drop PR-J), the cap lives elsewhere. **Tradeoff**: avoids touching `app/risk/manager.py`. Risk: the double-exposure problem remains until the separate plan ships. Mitigation: the engine-level arbiter (R2-11) already prevents multiple non-arbitrage trades on the same event_id within a single tick, so the per-tick winner is enforced; what's missing is the cap on aggregate event_exposure across multiple ticks (which is what PR-J adds via persistence).

- **C — Reject all four**. Move strategy wrapping into `app/strategies/registry.py` as a stateful service (registry tracks "which strategies are currently wrapped"), make top-K cap a hardcoded constant, drop PR-J entirely (handle in separate plan). **Tradeoff**: respects the strictest interpretation of "fixed scope". Cost: registry becomes more complex (it now tracks lifecycle state), config lacks user-tunable cap, and event exposure is unfettered until the separate plan lands. Highest churn-to-value ratio.

### Drafter recommendation

**Option A (approve full scope expansion)**. The four files are genuinely needed: dependencies.py is the canonical wiring point for singletons (per project convention `app/core/dependencies.py`), yaml_config + example.yaml are the canonical config surface, and risk/manager.py is the only place event-level exposure can live without inventing a parallel risk system. Splitting PR-J into a follow-up plan creates a window where the refactor is "done" but the safety gate is missing — the kind of seam where bugs hide. The extra work for R2-16 (persistence) and R2-17 (atomic reserve) is real but bounded: ~50-80 LOC of RiskManager changes + tests.

If the user is uncomfortable with Option A, **Option B is the next-best**: it preserves the architectural cleanliness of dependencies/yaml_config touches (which are unavoidable) while deferring the actual risk policy change. The arbiter (R2-11) provides per-tick safety; cross-tick safety waits for the separate plan.

### Sections affected in PLAN.v2.md

All sections marked `[TBD-Q1]`:
- "File con scope expansion pendente" block (top of File impattati)
- PR-B step 4 (`app/core/dependencies.py` wrap registration)
- PR-C through PR-I step "un-wrap" (all reference dependencies.py)
- PR-J entirely (steps 1-6)
- PR-K step 5 (final dependencies.py registration)
- Verification table row "PR-J [TBD-Q1]"
- Done conditions item "RiskManager rispetta `max_event_exposure_pct`"

---

## Q2 — Mixed-category events: fail-closed or category-split-then-arbiter?

**Bundles**: R2-18 (MAJOR), A2 (Round 1 ambiguity), A12 (Round 1 ambiguity).

### Background

A Polymarket Event can in principle group markets of different `category` (e.g., a meta-event "2026 Q2 Indicators" mixing economics + crypto markets, or a debate event mixing politics + entertainment markets). The strategy registry is keyed by domain (`get_for_domain(category)`), which means a mixed-category group can't be evaluated by a single strategy call. The plan must define what the engine does in this case.

Whatever policy is chosen must respect the fixed constraint "one Signal per group (winner)" — splitting a group into category-subgroups risks producing one winner per subgroup (i.e., multiple winners per event_id), which directly defeats the refactor's purpose unless an event-level arbiter is added on top.

The engine-level arbiter (R2-11) already exists in PLAN.v2.md to handle "multiple strategies returning signals on the same event_id". The question is whether the same arbiter handles "multiple subgroups returning signals on the same event_id", or whether mixed-category groups should be skipped entirely.

### Options

- **A — Fail closed for mixed-category events**. If a group's markets don't all share the same `category`, log `mixed_category_event_skipped` with event_id and category breakdown, and skip the entire group for the tick. Mark `grouping_incomplete=True` for those markets. **Tradeoff**: zero risk of double-trade-per-event from this code path; simplest engine logic. Cost: any event that is genuinely mixed-category is never traded. Real-world frequency is unclear; drafter's spot-impression is "rare but non-zero".

- **B — Category-split-then-event-level-arbiter**. Split the mixed-category group into per-category subgroups. Run each subgroup through `get_for_domain(category)` independently. Collect winners. Apply the existing R2-11 arbiter at the event_id level: if multiple subgroups produce winners for the same event_id, keep only the highest-priority one. **Tradeoff**: traded events even when mixed-category. Cost: more engine complexity, more test surface. The arbiter must already handle this pattern (multiple non-arbitrage signals per event_id is exactly its job), so the marginal complexity is small if the arbiter is robust.

- **C — Treat the group as homogeneous, use first market's category**. Just call `get_for_domain(group[0].category.value)` for the whole group. **Tradeoff**: simplest code; broken behavior — strategies for the wrong domain will see markets they don't expect, likely returning None or worse, malformed signals. The drafter does NOT recommend C; it's listed for completeness because the Round 1 draft mentioned it as Option B in A2.

### Drafter recommendation

**Option B (category-split-then-arbiter)**. The R2-11 arbiter exists specifically to handle "multiple non-arbitrage signals per event_id", and category-subgroup-winners are exactly that pattern. Reusing the arbiter is the lowest-marginal-cost path. Fail-closed (A) is too aggressive given that mixed-category events, while rare, may include some of the most interesting trade opportunities (e.g., meta-events spanning domains).

If the user prefers conservative behavior, **A is acceptable**: the lost trade opportunity is bounded (rare events) and the safety guarantee is absolute.

**C is rejected** by the drafter — it produces malformed strategy calls.

### Sections affected in PLAN.v2.md

All sections marked `[TBD-Q2]`:
- PR-B step 6, the "Determinare dominio" line ("...altrimenti applicare la policy [TBD-Q2] (R2-18)")
- "Ambiguità note" → A2 entry → "[TBD-Q2]"
- "Ambiguità note" → A12 entry → "[TBD-Q2]"
- New test cases needed in `tests/test_execution/test_engine.py`:
  - If A: `test_mixed_category_event_skipped_with_grouping_incomplete`
  - If B: `test_mixed_category_event_split_into_subgroups_then_arbiter_picks_one`
  - If C: not recommended; would need `test_mixed_category_uses_first_market_category` (drafter strongly advises against)
