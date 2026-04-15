# Refactor Log

Date: 2026-04-06
Description: Consolidate duplicate TimeHorizon enum, remove dead variables, fix dashboard weight display
Triggered by: /health findings DEAD-15, DEAD-12, DEAD-13, DEAD-14, UI-7
Health findings: DEAD-12, DEAD-13, DEAD-14, DEAD-15, UI-7

## Summary

| Metric | Value |
|--------|-------|
| Slices planned | 4 |
| Slices completed | 4 |
| Slices reverted | 0 |
| Files changed | 6 |
| Lines added | 4 |
| Lines removed | 16 |
| Net line change | -12 |
| Verification | `python -m pytest tests/ --tb=line -q` |
| Final status | 687 passed |

## Slices

| # | Description | Files | Status |
|---|-------------|-------|--------|
| 1 | Consolidate duplicate TimeHorizon enum | `app/models/intelligence.py` | Passed |
| 2 | Remove dead `_SENTINEL` variable + unused `field` import | `app/monitoring/alerting.py` | Passed |
| 3 | Remove dead `_field = field` and `_ = OrderSide` + unused imports | `app/execution/shadow.py`, `app/execution/live.py` | Passed |
| 4 | Add missing `cross_platform` weight label to dashboard | `static/js/app.js` | Passed |

## Changes by File

| File | What Changed |
|------|-------------|
| `app/models/intelligence.py` | Removed duplicate `TimeHorizon` class, re-exports from `app.models.market` instead. Removed unused `StrEnum` import. |
| `app/monitoring/alerting.py` | Removed dead `_SENTINEL` variable and unused `field` import. |
| `app/execution/shadow.py` | Removed dead `_field = field` alias and unused `field` import. |
| `app/execution/live.py` | Removed dead `_ = OrderSide` assignment and unused `OrderSide` import. |
| `static/js/app.js` | Added `cross_platform: "Cross Platform"` to valuation weights label map (was showing 8/9 weights). |

## Reverted Slices

None.

## Notes

- All importers of `TimeHorizon` from `intelligence.py` continue to work via re-export — no changes needed to `rss_client.py`, `institutional_client.py`, `news_service.py`, or their tests.
- The `OrderSide` import in `live.py` was justified by a comment claiming tests needed it, but no test actually imports `OrderSide` from `live.py`.
