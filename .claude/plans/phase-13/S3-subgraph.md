# S3 — Subgraph Integration (The Graph)

| **Modello consigliato** | **Effort** | **Wave** | **Parallelizzabile con** |
|--------------------------|-----------|----------|---------------------------|
| **Sonnet 4.6** (200K context) | **basso** | W3 | — (standalone, richiede S2 committed) |

**Perché Sonnet 4.6:** client GraphQL isolato, 4 query templates, enrichment meccanico via UPDATE SQL. Scope piccolo e chiuso. Context 200K abbondante.

---

## Obiettivo

Client GraphQL su Polymarket Subgraph (The Graph, free 100k query/mese) per arricchire `whale_trades` con `wallet_total_pnl`, `wallet_weekly_pnl`, `wallet_volume_rank` (criteri D4 whale signal).

## Dipendenze

**S2 committed.** Tabella `whale_trades` ha le colonne aggregate pronte (empty). Metodi `save_whale_trade` / `load_whale_trades` disponibili.

## File master

- [../00-decisions.md](../00-decisions.md) — D4 (criteri whale con volume_rank, pnl)

## File da leggere all'avvio

- [app/clients/polymarket_rest.py](app/clients/polymarket_rest.py) (pattern httpx)
- [app/services/whale_orchestrator.py](app/services/whale_orchestrator.py) (da S2 — extend con enrichment call)
- [app/execution/trade_store.py](app/execution/trade_store.py) (tabella whale_trades + metodi UPDATE)
- [config/config.example.yaml](config/config.example.yaml)

## Skills / Agenti / MCP

- Skill [.claude/skills/intelligence-source/SKILL.md](.claude/skills/intelligence-source/SKILL.md)
- Agente `backend-specialist`, `test-writer`

---

## Step esecutivi

**STEP 1 — `PolymarketSubgraphClient`.** Nuovo file `app/clients/polymarket_subgraph.py`:
- `__init__(api_key: str | None, endpoint: str)` (api_key da env `THEGRAPH_API_KEY`, free-tier se None)
- Query templates hardcoded (in docstring):
  - `wallet_pnl_aggregates(wallet_address) -> {total_pnl, weekly_pnl}`
  - `wallet_volume_rank(wallet_address, window_days=30) -> rank`
  - `top_traders_by_pnl(limit, timeframe) -> list`
  - `trades_for_market(market_id, since) -> list`
- `async query(query: str, variables: dict) -> dict` (httpx POST GraphQL)

**STEP 2 — Whale enrichment.** In `WhaleOrchestrator.tick()` (da S2): dopo filtro whale_trades >threshold, batch-query subgraph per distinct `wallet_address`, UPDATE rows con i 3 campi aggregate. Cache in-memory `wallet_address → aggregates` con TTL 1h per rispettare quota 100k/mese.

**STEP 3 — Config.** In [config/config.example.yaml](config/config.example.yaml):
```yaml
intelligence:
  subgraph:
    enabled: true
    endpoint: "https://gateway.thegraph.com/api/subgraphs/id/81Dm16JjuFSrqz813HysXoUPvzTwE7fsfPk2RTf66nyC"
    api_key_env: "THEGRAPH_API_KEY"
    rate_limit_per_minute: 100
    enrichment_ttl_hours: 1
```

In `.env.example` aggiungi `THEGRAPH_API_KEY=` (commentato, opzionale — free tier funziona senza).

**STEP 4 — Tests.** `tests/test_clients/test_polymarket_subgraph.py` con respx GraphQL mocking. Verificare parsing risposta + UPDATE su whale_trades.

---

## Verification

```bash
python -m pytest tests/test_clients/test_polymarket_subgraph.py -v
python -m pytest tests/ -q                    # atteso: 725+ pass
python -m ruff check app/ tests/
python -m mypy app/clients/polymarket_subgraph.py
```

## Commit message proposto

```
feat(intelligence): The Graph subgraph integration for whale enrichment (Phase 13 S3)

- PolymarketSubgraphClient with 4 GraphQL query templates
- WhaleOrchestrator enriches whale_trades with wallet_total_pnl, weekly_pnl, volume_rank
- In-memory TTL cache (1h) to stay under 100k/month free quota
- Config: intelligence.subgraph block, THEGRAPH_API_KEY env var optional (free tier works)
```

## Handoff a W4 (S4a // S4b)

- Subgraph client queryabile (smoke test manuale)
- `whale_trades` enriched con 3 campi wallet per i trade più recenti
- Free-tier rate limit rispettato (check counter in log)
- S4a può ora costruire snapshot con dati whale completi
- S4b può ora usare i criteri D4 (volume_rank, pnl) nel `whale_pressure` calcolo
