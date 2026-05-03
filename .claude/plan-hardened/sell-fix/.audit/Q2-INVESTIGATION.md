# Q2-INVESTIGATION.md — Deep dive su market_price + multi-alternative

**Trigger**: utente ha segnalato che il framing binario potrebbe essere insufficiente, allegando screenshot Polymarket con multiple sub-markets per asset/date.
**Investigator**: `Explore` agent (read-only) + screenshot user
**Date**: 2026-05-02

---

## Screenshot context (utente)

Il mockup mostra una grouped market view (probabilmente "BTC price by date X"):

| Threshold | Volume | Implied Prob | Buy YES | Buy NO | YES+NO |
|-----------|--------|--------------|---------|--------|--------|
| ↑ $140 | $260,510 | 12% | 12.3¢ | 87.9¢ | 100.2¢ |
| ↑ $130 | $314,783 | 22% | 22¢ | 79¢ | 101¢ |
| ↑ $120 | $381,073 | 44% | 45¢ | 57¢ | **102¢** ← arb candidate |
| ↑ $115 | $10,264 | 61% | 61¢ | 40¢ | 101¢ |
| ↑ $110 | $296,416 | 75% | 75¢ | 26¢ | 101¢ |
| ↑ 105$ | $41,676 | 90% | 90¢ | 11¢ | 101¢ |
| ↓ $95 | $10,609 | 79% | 79¢ | 22¢ | 101¢ |
| ↓ $90 | $8,049 | 69% | 69¢ | 32¢ | 101¢ |
| ↓ $85 | $16,617 | 44% | 44¢ | 57¢ | **101¢** ← arb candidate |

**Conferma**: ogni threshold è un Market binario indipendente con suoi YES/NO token. Le "alternative" sono Market objects separati raggruppati a UI level, NON un singolo Market multi-outcome.

---

## 1. Data Model Reality

`app/models/market.py:65-85` definisce `Market` con `outcomes: list[Outcome]`. Ogni `Outcome` (linee 22-27) ha `token_id`, `outcome` ("Yes"/"No"), `price`.

REST client `app/clients/polymarket_rest.py:54-100` parsa una sola coppia YES/NO per Market. **Conferma**: 1 Market = 1 condizione binaria. Mercati come "BTC>115/>120/>125" sono Market objects separati.

## 2. Grouped/Related Markets Mechanism

**Esiste solo come signal informativo**, NON come selezione esplicita:
- `app/valuation/cross_market.py:1-192` — `CrossMarketAnalyzer` rileva mercati correlati per keyword overlap + price discrepancy
- `app/models/valuation.py:35` — campo `cross_market_signal` in `ValuationInput`
- `app/execution/engine.py:180-184` — VAE riceve l'universo dei market e calcola signal cross-market

Le strategie NON usano questo per scegliere "quale alternativa tradare". Il segnale cross-market è aggregato DENTRO la valutazione come componente pesata (1 dei 11 segnali VAE, peso 0.10), non come meccanismo di scelta tra Market.

## 3. Strategy Scope: Single Market

TUTTE le 4+ strategie operano su **un singolo Market in isolation**:

```python
# Tutte hanno questa firma:
async def evaluate(
    self,
    market: Market,                     # SINGOLO market
    valuation: ValuationResult,
    knowledge: KnowledgeContext | None = None,
) -> Signal | None
```

Pattern di chiamata in `app/execution/engine.py:213-230`:
```python
for market in markets:                  # iterates ONE at a time
    valuation = valuations.get(market.id)
    ...
    for strategy in applicable_strategies:
        result_signals = await strategy.evaluate(market, valuation)
```

Per "scegliere tra alternative" servirebbe rifirmare a `evaluate(markets: list[Market], ...)` — refactor architetturale **fuori scope** dal fix SELL→BUY-NO.

## 4. `signal.market_price` Downstream Usage

| File:Line | Uso |
|-----------|-----|
| `engine.py:294` | `price = signal.market_price if signal.market_price > 0 else 0.5` |
| `engine.py:297` | `risk.size_position(signal, balance.available, price)` |
| `risk/manager.py:202` | `from_signal(capital, price, ..., edge=abs(signal.edge_amount))` |
| `position_sizer.py:134` | `shares = size_eur / price` (calcolo share count) |
| `engine.py:313-320` | `OrderRequest(token_id=signal.token_id, price=price, ...)` |

**Critico**: `OrderRequest.price` è il prezzo per share del **token specifico** (`signal.token_id`). Per un BUY-NO con `market_price=YES_price`:
- Esempio dal screenshot riga $110: YES=75¢, NO=26¢
- Se `market_price=0.75` per BUY NO: `OrderRequest(token_id=NO_token, price=0.75)`
- Il book NO è a 26¢ → l'ordine dichiara prezzo 3x sopra mercato
- `shares = size_eur / 0.75` invece di `size_eur / 0.26` → 3x meno shares
- Conseguenze: rejection in shadow/live, P&L tracking sbagliato in dry_run

## 5. Q2 Refined Recommendation

**OPTION B** (`signal.market_price = 1.0 - valuation.market_price`) è inequivocabilmente corretta.

**Motivazione concreta dallo screenshot**:
- Per il market `$110`: se la strategia decide BUY NO (perché 75¢ YES è overpriced), il signal deve portare `market_price ≈ 0.26` (= 1.0 - 0.75)
- L'order book ha NO @ 26¢ — il broker accetta a quel prezzo
- Position sizing: `shares = capital / 0.26` — number corretto

**Option A** (`market_price = valuation.market_price` = YES_price = 0.75 nel caso) sarebbe:
- Order @ 0.75 su NO token che trada a 0.26 → rifiutato/fill errato
- Position sizing 3x sbagliata
- **Silently broken** in shadow/live, **P&L tracking sbagliato** anche in dry_run

`value_edge.py:97` ha lo stesso latent bug → tracciato come follow-up R2-04 in todo.md.

## 6. Multi-Alternative Impact su Q2

**Q2 e multi-alternative sono ortogonali**.

L'utente ha ragione che esiste un layer architetturale superiore: data una grouped view come lo screenshot, dovrebbe essere possibile evaluare "quale tra $140/$130/$120/.../$85 ha il maggior edge" (e poi su quella scegliere YES o NO). Ma:

- Il fix attuale (SELL→BUY-NO) opera **per-market**, dentro la decisione binaria YES/NO
- Per ogni market individuale, Option B è corretta indipendentemente dal selezione meta
- **Anche** se in futuro si aggiungesse un selettore meta-event, ogni market valuto resterebbe binario, e il signal generato per quello specifico market avrebbe `market_price = NO_price` quando si decide BUY NO

**Conclusione**: il "multi-alternative selection" è un follow-up architetturale separato. Non blocca questo fix. Richiede:
- Cambiare la firma di `evaluate()` per accettare un set di Market correlati (e una "best-edge picker" centrale)
- Aggiungere un campo di raggruppamento al modello Market (`event_group_id` o simili)
- Implementare la logica di scelta tra alternative

Questo è un **architectural refactor** che merita un ADR e plan dedicato. Fuori scope da `/plan-hardened` corrente.

---

## Decisione raccomandata

**Q2 = Option B** (`market_price = 1.0 - valuation.market_price`).

**Multi-alternative concern** → tracciato come follow-up architetturale in `.claude/tasks/todo.md`:
> "ADR: multi-alternative event selection — strategie attuali operano per-market in isolation. Su grouped views (es. BTC>thresholds) il bot non sceglie l'alternativa con più edge. Refactor proposto: aggiungere `event_group_id` al Market, e una funzione `select_best_edge_alternative(markets: list[Market], valuations: dict) -> Market | None` invocata prima dell'iterazione strategia. Stima: ~2-3 giorni di lavoro, richiede ADR."
