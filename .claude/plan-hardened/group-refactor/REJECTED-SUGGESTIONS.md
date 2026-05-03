# REJECTED-SUGGESTIONS.md — Group-aware refactor (Round 3)

**Pipeline**: /plan-hardened — Round 3 adversarial-merge
Generated: 2026-05-02

---

All 22 Codex issues were accepted as VALID (merged into PLAN.v2.md) or NEEDS_USER (escalated to OPEN-AMBIGUITIES.md). **No rejections.**

The drafter found Codex's review thorough and grounded: every BLOCKER reflected a real gap or constraint violation, every MAJOR identified a genuine ambiguity or edge case, and the single MINOR (R2-22) was a straightforward scope hygiene catch.

## Summary

| Status | Count | Issues |
|--------|-------|--------|
| VALID (merged) | 16 | R2-04, R2-05, R2-06, R2-07, R2-08, R2-09, R2-10, R2-11, R2-12, R2-13, R2-14, R2-15, R2-19, R2-20, R2-21, R2-22 |
| NEEDS_USER (escalated) | 6 (collapsed into 2 questions) | R2-01, R2-02, R2-03, R2-16, R2-17 → Q1; R2-18 → Q2 |
| INVALID (rejected) | 0 | — |

## Borderline calls documented (VALID with default, not escalated)

The following issues were borderline VALID/NEEDS_USER. Per Round 3 instructions, the drafter merged them as VALID with a sane default rather than creating additional Q3+ entries that would push past the 5-question cap. Each is annotated for revisitability:

### R2-04 — Event model placement
- **Default chosen**: module-private `_EventPayload` dataclass/TypedDict inside `app/clients/polymarket_rest.py`.
- **Why this default and not user-decision**: The fixed scope explicitly lists `app/models/market.py` only. Creating `app/models/event.py` is a clear scope violation; using a private structure is consistent with the constraint. There's no architectural fork — the alternative (full Pydantic Event model) is a follow-up cleanup, not a planning question.
- **Revisit if**: a follow-up plan needs Event as a first-class model exposed beyond the client (e.g., for API responses or storage).

### R2-14 — KnowledgeContext source per group
- **Default chosen**: knowledge from the most-liquid market in the group (option B from A4).
- **Why this default and not user-decision**: Options A (aggregated) and C (dict-per-market) both require Protocol changes or new aggregation logic that don't fit cleanly within the fixed signature. Option B preserves the signature, has a defensible heuristic (most-liquid market is most likely to share intelligence context with the rest of the group), and is the cheapest transitional choice. Both alternatives are easy follow-ups.
- **Revisit if**: post-merge data shows that most-liquid-market knowledge is systematically wrong for specific event types (e.g., niche markets within a popular event have divergent intelligence).

### R2-15 — SELL→BUY-NO hotfix preflight
- **Default chosen**: hard BLOCKING preflight precondition added at the top of PLAN.v2.md, must pass before PR-A.
- **Why this default and not user-decision**: The fixed scope explicitly says SELL→BUY-NO is OUT OF SCOPE here (ships separately). The only sane response to "the hotfix isn't merged yet" is to gate this plan's execution behind the hotfix landing. There's no design alternative — silently shipping the bug or inline-fixing it would both violate scope.
- **Revisit if**: spot-check at preflight time shows the hotfix in fact merged; preflight passes trivially and we proceed.

## Notes on completeness

The drafter cross-checked Codex's findings against the source files referenced in each issue (sentiment.py:143, arbitrage.py:94-117, engine.py:222-245, polymarket_rest.py:54-137 and :250-304, risk/manager.py:102-243). Every reference was accurate. No false positives identified.
