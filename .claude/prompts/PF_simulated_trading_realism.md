---
name: Prompt PF — Fix simulated trading realism (positions, win rate, P&L)
description: Diagnostica e fix del trading simulato in dry_run: win rate irrealistico, posizioni aperte non aggiornate correttamente, P&L non riflette comportamento reale di mercato. Verifica end-to-end del ciclo buy->hold->exit->P&L.
type: project
---

## Obiettivo

Diagnosticare e correggere i problemi di realismo nel trading simulato (dry_run). Il sistema deve comportarsi come un trading bot reale: posizioni aperte con costo base corretto, P&L realizzato solo su vendita/risoluzione, win rate calcolato sul subset di trade chiusi, equity che riflette cash + valore posizioni.

## Contesto

### Stato attuale del problema

Il contesto di progetto segnala: "il trading simulato non rispecchia un comportamento reale. Posizioni aperte, win rate, profitto: il bot non sembra andare al 100%."

Phase 11 ha gia' corretto un bug critico di fake arbitrage (floor 0.01 rimosso, sostituito con `_estimate_spread()` + `_estimate_depth()`). Possono esistere altri problemi residui.

### Componenti coinvolti

**PolymarketClobClient** — `app/clients/polymarket_clob.py`
- `place_order()`: calcola fill_price con slippage e spread, aggiorna balance e posizioni
- `_estimate_spread(price)`: spread iperbolicamente crescente agli estremi (0.5% a 0.50, 50% a 0.01)
- `_estimate_depth(price, size)`: cap depth a 100 shares per token < 0.01
- `_balance`: USDC disponibile (inizia a 150.0)
- `_realized_pnl`: P&L totale realizzato da tutte le vendite/risoluzioni
- `get_balance()`: ritorna `total = _balance + locked + unrealized` (NON solo cash)

**ExecutionEngine** — `app/execution/engine.py`
- `_manage_positions()`: aggiorna prezzi live, valuta exit conditions (TP/SL/scadenza/edge reversal)
- `_persist_trade()`: scrive nel trade log ogni open/close
- `restore_from_store()`: ricarica posizioni da SQLite al restart

**PositionMonitor** — `app/execution/position_monitor.py`
- `evaluate_exit()`: take profit (1.5x ratio), edge reversal (-3%), flatten near expiry (12h)
- NOT un stop-loss tradizionale — prediction markets sono binari

**Dashboard** — `app/monitoring/dashboard.py`
- `_win_rate(trade_log)`: calcola win rate sul trade_log. Filtra gia' per `type == "close"` (linea 310). Ritorna percentuale (es. 50.0, non 0.5).
- `GET /dashboard/overview`: ritorna `win_rate`, `daily_pnl`, `open_positions`, `equity`

**TradeStore** — `app/execution/trade_store.py`
- Schema: trades(id, timestamp, market_id, strategy, side, size_eur, price, edge, pnl, type)
- `type`: "open" o "close"
- `pnl`: 0.0 per open, valore reale per close

### Possibili problemi da diagnosticare

**P1 — Win rate calcolato su TUTTI i trade o solo i CLOSE?**
Il win rate deve essere calcolato solo sui trade di tipo "close" (vendita o risoluzione). `_win_rate()` in `dashboard.py` (linee 308-314) filtra GIA' per `type == "close"`. Questo potrebbe NON essere un bug — l'agente deve verificare e confermare.

**P2 — Posizioni aperte: unrealized P&L non si aggiorna tra tick?**
`pos.current_price` viene aggiornato in `_manage_positions()` step 2, ma solo se il market e' presente nel `market_by_id` lookup del tick corrente. Se un market esce dal set dei mercati filtrati (market_service.get_filtered_markets()), le posizioni aperte su quel market non ricevono aggiornamenti di prezzo. Nota: il codice gia' tenta un fetch dedicato (linee 354-358): `market = await self._market_service.get_market(market_id)`.

**P3 — Balance mostrato nel dashboard = equity totale o solo cash?**
`get_balance()` ritorna `total = cash + cost_basis_of_positions + unrealized`. Se il dashboard mostra `balance.total` come "equity" e `balance.available` come "disponibile", devono corrispondere a etichette diverse. Verificare che la UI mostri correttamente entrambi.

**P4 — Fill price alle condizioni estreme**
Per token a prezzo 0.50, lo spread e' ~1% (0.005). Un buy a 0.50 viene eseguito a ~0.5025. Una posizione comprata a 0.5025 e venduta immediatamente (nessun movimento di prezzo) riporta un P&L di circa -0.5% (spread cost). Questo e' corretto. Verificare che non ci siano scenari in cui il fill_price e' sempre migliore del market_price.

**P5 — Ciclo buy->exit nello stesso tick**
In `engine.py`, lo step 4 (`_manage_positions`) avviene PRIMA dello step 5 (generazione nuovi segnali). I mercati appena venduti vengono aggiunti a `exited_market_ids` per evitare il rebuy. Il codice controlla GIA' `if market.id in exited_market_ids: continue` (linea 180). Potrebbe NON essere un bug — l'agente deve verificare e confermare.

**P6 — P&L nei trade "close" e' coerente con il P&L dell'executor?**
Il trade log registra `pnl = (exit_price - entry_price) * shares` (linea 441 di engine.py). Verificare che questo sia coerente con `_clob._realized_pnl` e con quanto salvato in `engine_state["realized_pnl"]` nel TradeStore. Attenzione: `_reduce_position()` in CLOB usa `min(shares, pos.size)` — se `order_result.filled_size` e `pos.size` divergono, il P&L potrebbe non corrispondere.

### Metrica di "comportamento reale atteso"

Su un bot dry_run con mercati simulati senza edge reale:
- Win rate convergente a ~50% su N grande
- P&L convergente a ~0 meno i costi di spread
- Equity che oscilla ma non esplode in nessuna direzione
- Nessuna posizione con P&L impossibile (es. +1000% su un trade singolo)

### File chiave

```
app/clients/polymarket_clob.py    — fill simulation, balance, positions
app/execution/engine.py           — tick cycle, position management, exited_market_ids
app/execution/position_monitor.py — exit conditions
app/execution/trade_store.py      — schema SQLite, append_trade, get_trades
app/monitoring/dashboard.py       — _win_rate(), get_overview(), get_equity_history()
static/js/app.js                  — display di metrics, positions, trades nella UI
```

## Vincoli

- Non cambiare la meccanica fondamentale di Polymarket (prezzi 0-1, payout $1/$0 a risoluzione)
- Non introdurre stop-loss basati su prezzo assoluto: le prediction markets sono binarie
- Non simulare market impact che superi le dimensioni realistiche (cap gia' in `_estimate_depth`)
- `_INITIAL_BALANCE = 150.0` non deve cambiare
- Il `_SLIPPAGE_PER_100 = 0.002` e' calibrato e non va modificato senza analisi
- I fix di Phase 11 sul floor 0.01 non vanno ripristinati

## Output atteso

### Diagnosi documentata (da produrre PRIMA di qualsiasi fix)

Leggere il codice di `_win_rate()` in `dashboard.py`, la logica di `_manage_positions()` in `engine.py`, e `place_order()` in `polymarket_clob.py`. Per ogni problema P1-P6 sopra elencato:
- Conferma se il bug esiste o no nel codice attuale
- Se esiste: descrizione precisa della causa e del fix proposto
- Se non esiste: evidenza che il comportamento e' corretto

### Fix implementati (solo quelli confermati come bug)

- Fix per ogni problema confermato, con test di regressione
- Nessuna modifica speculativa: fix solo per bug verificati nel codice

### Test di regressione obbligatori

**Test R1 — win_rate_computed_on_closed_trades_only**
```
Setup: trade_log con 3 trade "open" (pnl=0.0) + 2 trade "close" (pnl=+5.0, pnl=-2.0)
Assert: win_rate == 50.0 (1 win su 2 close, ritornato come percentuale non come frazione)
Assert: win_rate != 40.0 (sbagliato se conta anche gli open)
```

**Test R2 — no_position_rebuy_in_same_tick**
```
Setup: ExecutionEngine, market "mkt-1" con posizione aperta che triggera take profit
Azione: engine.tick(markets=[market_mkt-1_con_exit_condition])
Assert: result.positions_closed == 1
Assert: result.orders_placed == 0  (rebuy bloccato da exited_market_ids)
```

**Test R3 — pnl_consistency_between_clob_and_trade_log**
```
Setup: ClobClient con posizione esistente (10 shares @ 0.40)
Azione: sell 10 shares @ 0.60
Assert: _reduce_position ritorna realized = (0.60 - 0.40) * 10 = 2.0
Assert: trade_log entry per questa vendita ha pnl ~= 2.0 (allowance per spread)
Assert: _clob._realized_pnl == 2.0
Nota: il spread viene applicato sia in buy che in sell, quindi il P&L netto sara'
      leggermente inferiore a 2.0. L'asserzione deve essere `pnl approximately 2.0 +/- spread_cost`
      non `pnl == 2.0`.
```

**Test R4 — equity_calculation_correct**
```
Setup: ClobClient, balance=100.0, 1 posizione (10 shares @ 0.50, current=0.55)
Azione: get_balance()
Assert: balance.available == 100.0
Assert: balance.locked == 5.0  (10 * 0.50 cost basis)
Assert: balance.total == 100.0 + 5.0 + (0.55-0.50)*10 = 105.5
```

**Test R5 — spread_cost_reduces_pnl**
```
Setup: ClobClient, buy 10 shares @ price=0.50
       sell immediately @ price=0.50 (no price movement)
Assert: net P&L < 0  (spread cost eaten)
Assert: net P&L > -0.10  (costo spread < 10% del valore)
```

**Test R6 — fill_price_never_exceeds_0.99_on_buy**
```
Setup: ordine buy @ price=0.95 (alta probabilita' -> wide spread)
Assert: fill_price <= 0.99  (capped da min(0.99, ...))
Assert: fill_price > 0.95   (spread su ask)
```

**Test R7 — sub_penny_token_depth_capped**
```
Setup: ordine buy 1000 shares @ price=0.005
Assert: fill_size <= 100  (_estimate_depth cap for price <= 0.01)
Assert: order_result.status == FILLED (parziale, non rejected)
```

### Verifica finale

Dopo tutti i fix, eseguire:
```
pytest tests/test_clients/test_polymarket_clob.py tests/test_execution/test_engine.py tests/test_monitoring/test_dashboard.py -v
```
Output atteso: 0 failures, nessun nuovo warning.

## Note

- Consultare skill `execution-modes` (`.claude/skills/execution-modes/SKILL.md`) e `risk-tuning` (`.claude/skills/risk-tuning/SKILL.md`) prima di toccare il tick cycle
- La diagnosi deve precedere ogni fix: scrivere la diagnosi come commento nel codice o nel task log, non saltare direttamente all'implementazione
- `_win_rate()` si trova in `app/monitoring/dashboard.py` linee 308-314 — l'implementazione attuale filtra gia' per `type == "close"` e ritorna una percentuale (es. 50.0)
- Non modificare `app/execution/shadow.py` o `app/execution/live.py` — scope limitato a dry_run
