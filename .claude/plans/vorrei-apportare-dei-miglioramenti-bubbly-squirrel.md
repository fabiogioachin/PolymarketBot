# Phase 13 — Redirect to Split Plan

> Il piano originale è stato suddiviso in file separati per sessione in `.claude/plans/phase-13/`.
> Ogni sessione è self-contained: un Claude Opus/Sonnet in sessione fresca carica solo il suo file + il master.

## Struttura

```
.claude/plans/phase-13/
├── 00-decisions.md              # Master condiviso (Context, D1-D6, Wave schedule, Verification)
├── S1-dynamic-edge.md           # Opus 4.7 — alto    — W1 (standalone)
├── S2-collectors.md             # Sonnet 4.6 — medio — W2 (dopo S1)
├── S3-subgraph.md               # Sonnet 4.6 — basso — W3 (dopo S2)
├── S4a-snapshot-writer.md       # Sonnet 4.6 — medio — W4 ∥ S4b
├── S4b-whale-insider-vae.md     # Opus 4.7 — alto    — W4 ∥ S4a
├── S5a-dss-artifact.md          # Opus 4.7 — alto    — W5 ∥ S5b
└── S5b-dashboard-widgets.md     # Sonnet 4.6 — basso — W5 ∥ S5a
```

## Wave schedule

| Wave | Sessioni | Modelli |
|------|----------|---------|
| W1 | S1 | Opus 4.7 |
| W2 | S2 | Sonnet 4.6 |
| W3 | S3 | Sonnet 4.6 |
| W4 | **S4a ∥ S4b** (parallelo) | Sonnet 4.6 + Opus 4.7 |
| W5 | **S5a ∥ S5b** (parallelo) | Opus 4.7 + Sonnet 4.6 |

## Come eseguire una sessione

1. Apri una nuova sessione Claude (Opus 4.7 o Sonnet 4.6 secondo tabella)
2. Passa come prompt iniziale: *"Leggi `.claude/plans/phase-13/00-decisions.md` e `.claude/plans/phase-13/SX-*.md`, poi eseguila"*
3. A fine sessione: commit + conferma handoff invariants prima della successiva

## Link rapidi

- [Master decisions](phase-13/00-decisions.md)
- [S1 — Dynamic Edge](phase-13/S1-dynamic-edge.md)
- [S2 — Collectors](phase-13/S2-collectors.md)
- [S3 — Subgraph](phase-13/S3-subgraph.md)
- [S4a — Snapshot Writer](phase-13/S4a-snapshot-writer.md)
- [S4b — Whale/Insider VAE](phase-13/S4b-whale-insider-vae.md)
- [S5a — DSS Artifact](phase-13/S5a-dss-artifact.md)
- [S5b — Dashboard Widgets](phase-13/S5b-dashboard-widgets.md)
