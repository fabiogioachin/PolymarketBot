# CHANGES-FROM-DRAFT — Tracer-feature N1+N2+N4 Anchors

Diff strutturato: PLAN.draft.md (Round 1) → PLAN.md (Round 5 final).

## Aggiunte

| Anchor row | Cosa è stato aggiunto | Issue Codex |
|------------|------------------------|-------------|
| Inter-slice gate | Trigger concreti enumerati (a) status DONE_WITH_CONCERNS, (b) transizione N1→N2, (c) demo gate failure. Status protocol referenzia CLAUDE.md globale. | AR-006 |
| Demo gate semantics | Per Slice N2: requirement esplicito di test su ENTRAMBI gli ordini di init + assertion `get_trade_store() is engine.trade_store is scheduler.trade_store`. | AR-004 |
| Single-slice-per-blocker | Regola ordering univoca: parallelism N4-con-N1 default; seriale è opt-in fallback. | AR-009 |
| Verifica | Comando 5° aggiunto: assertion singleton-identity test per N2 su entrambi gli ordini. | AR-004 |
| Assunzioni fatte | +2 voci: N2 dual-order test esplicito; status protocol legato al CLAUDE.md globale. | AR-004, AR-006 |
| Ambiguità note | Sezione riformulata per documentare le 9 issue Round 2 (2 rejected, 7 merged). | (audit trail) |

## Rimozioni

| Anchor row | Cosa è stato rimosso | Issue Codex |
|------------|------------------------|-------------|
| Recovery budget | Auto-rollback git e auto-escalation a planning-specialist rimossi. La decisione di rollback/escalation è ora dell'utente. | AR-008 |
| Demo gate semantics | "<30 LOC come hard pass condition" rimosso come gate; demoto a advisory check. | AR-005 |
| Behavior change rule | "Osservabile via metric/log" per N4 rimosso; observability confinata al return value testato. | AR-007 |

## Modifiche

| Anchor row | Da → a | Issue Codex |
|------------|--------|-------------|
| File scope per slice | N2 era "+ tests" generico → ora "+ tests/test_core/test_dependencies_*.py" stesso glob mirror di N1. | AR-003 |
| OFF-LIMITS | Aggiunto explicit "tests/ outside mirroring convention (ANCHE per N2: solo tests/test_core/test_dependencies_*.py)". | AR-003 |
| Inter-slice gate | Trigger vago "DONE_WITH_CONCERNS o tocca dependencies.py" → tre trigger concreti enumerati con priorità implicita. | AR-006 |
| Behavior change rule | N4 "osservabile via metric/log" → "osservabile via return value del parser testato direttamente (es. parsed.usd == 500 per 10000 × $0.05)". | AR-007 |
| Recovery budget | "Slice FAILED, abort tracer; rollback git, segnalazione planning-specialist" → "Slice FAILED, implementer riporta evidenze e si ferma. NESSUN auto-rollback, NESSUNA escalation. Decisione utente sul FAILED report." | AR-008 |
| Demo gate semantics | "<30 LOC limited" come gate → "advisory scope check, advisory <30 LOC, superamento richiede motivazione nel commit body" | AR-005 |

## Issue Codex rejected (link a REJECTED-SUGGESTIONS.md)

| Issue | Severity | Reason |
|-------|----------|--------|
| AR-001 (Skill canonical paths scope_creep) | MAJOR | Required-by-spec da /tracer-feature Step 0.2. Anchors row obbligatoria nel protocollo. |
| AR-002 (Command paths scope_creep) | MINOR | Required-by-spec da /tracer-feature Step 0.2. Anchors row obbligatoria nel protocollo. |

## Round summary

- Round 1 (Sonnet): PLAN.draft.md generato (10 anchor rows + 7 assumptions)
- Round 2 (Codex): 9 issue identificate (2 MAJOR scope_creep, 3 MAJOR ambiguous/edge_case/unauthorized, 4 MINOR)
- Round 3 (Opus): 7 VALID merged, 2 INVALID rejected, 0 NEEDS_USER (Round 4 skipped)
- Round 4: SKIPPED (no open ambiguities)
- Round 5: final PLAN.md promoted from PLAN.v2.md, intermediate files archived in `.audit/`

## Audit trail

```
.claude/plan-hardened/tracer-anchors/
├── PLAN.md                      (final — used by /tracer-feature Step 0.3)
├── REJECTED-SUGGESTIONS.md      (audit: AR-001, AR-002)
├── CHANGES-FROM-DRAFT.md        (this file)
└── .audit/
    ├── PLAN.draft.md            (Round 1 raw)
    ├── PLAN.v2.md               (Round 3 merged)
    ├── CODEX-REVIEW.json        (Round 2 raw)
    └── OPEN-AMBIGUITIES.md      (one-line skip)
```
