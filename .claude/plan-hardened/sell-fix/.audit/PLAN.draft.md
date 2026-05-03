# PLAN.draft.md — P1 Tech Debt: SELL ≠ BUY NO

**Round 1 — Sonnet/Opus draft**
Generated: 2026-05-02
Pipeline: `/plan-hardened`

---

## Obiettivo

Eliminare l'emissione di `SignalType.SELL` da `sentiment`, `event_driven`, `knowledge_driven` quando l'edge è negativo, sostituendola con `SignalType.BUY` sul token NO. `SELL` rimane riservato alle exit gestite da `position_monitor.build_exit_order`. Pattern di riferimento: `app/strategies/value_edge.py:59-65`.

---

## File impattati

**Modify (production code, 3 files):**
- `app/strategies/sentiment.py`
- `app/strategies/event_driven.py`
- `app/strategies/knowledge_driven.py`

**Modify (tests, 3 files):**
- `tests/test_strategies/test_sentiment.py`
- `tests/test_strategies/test_event_driven.py`
- `tests/test_strategies/test_knowledge_driven.py`

**Do NOT modify:**
- `app/models/signal.py` — `SignalType.SELL` resta nell'enum (usato per exit)
- `app/execution/engine.py` — mapping `BUY→BUY` / `SELL→SELL` invariato (line 312)
- `app/strategies/value_edge.py` — già corretto, è il riferimento
- `app/execution/position_monitor.py` — `build_exit_order` non tocca strategie
- Altre strategie (`arbitrage.py`, `rule_edge.py`, `resolution.py`, `value_edge.py`) — non emettono SELL strategico

---

## Step di implementazione

### Step 1 — `app/strategies/sentiment.py`

**1.1.** Sostituire `_resolve_signal_type` (linee 134-144) con `_resolve_target_outcome` che ritorna `"yes"`, `"no"`, o `None`:
```python
def _resolve_target_outcome(self, sentiment: float, edge: float) -> str | None:
    """Return the target outcome ('yes' or 'no') for a BUY signal, or None."""
    if sentiment > 0 and edge > 0:
        return "yes"
    if sentiment < 0 and edge < 0:
        return "no"
    return None
```

**1.2.** Riformulare `_pick_token` (linee 146-155) per ricevere il nome dell'outcome e ritornare `str | None` (no fallback su outcomes[0]):
```python
def _pick_token(self, market: Market, outcome_name: str) -> str | None:
    target = outcome_name.lower()
    for o in market.outcomes:
        if o.outcome.lower() == target:
            return o.token_id
    return None
```

**1.3.** Nel corpo di `evaluate` (linee 79-130):
- Rinominare `signal_type = self._resolve_signal_type(...)` → `target_outcome = self._resolve_target_outcome(...)`
- Cambiare il check `if signal_type is None` → `if target_outcome is None`
- Calcolare `token_id = self._pick_token(market, target_outcome)`
- Aggiungere check: `if token_id is None: logger.debug(...); return None`
- Hardcodare `signal_type = SignalType.BUY` prima della creazione del Signal
- Mantenere `market_price=valuation.market_price` invariato (vedere Ambiguità A1)
- Mantenere `edge_amount=edge` invariato (signed, vedere Ambiguità A4)

**1.4.** Aggiornare reasoning per chiarezza:
```python
direction_label = "BUY YES" if target_outcome == "yes" else "BUY NO"
reasoning = (
    f"Sentiment {sentiment:+.3f} ({'bullish' if sentiment > 0 else 'bearish'}) "
    f"aligns with edge {edge:+.3f} → {direction_label}.{baseline_note}"
)
```

### Step 2 — `app/strategies/event_driven.py`

**2.1.** Sostituire il blocco SELL inline (linee 95-106):
```python
# PRIMA:
if combined_edge > 0:
    signal_type = SignalType.BUY
    token_id = next((... if "yes" ...), market.outcomes[0]...)
else:
    signal_type = SignalType.SELL  # BUG
    token_id = next((... if "no" ...), market.outcomes[0]...)

# DOPO:
signal_type = SignalType.BUY
target_outcome = "yes" if combined_edge > 0 else "no"
token_id = next(
    (o.token_id for o in market.outcomes if o.outcome.lower() == target_outcome),
    None,
)
if token_id is None:
    logger.debug(
        "event_driven: target outcome not found — skip",
        market_id=market.id,
        target_outcome=target_outcome,
    )
    return None
```

**2.2.** Aggiornare il `logger.info` (linea 119-126) per registrare `target_outcome` invece (o accanto a) `signal_type` (che ora è sempre BUY).

**2.3.** Nessun helper `_pick_token` da aggiungere (vedere Ambiguità A5 — manteniamo logica inline per minimal-scope).

### Step 3 — `app/strategies/knowledge_driven.py`

Stessa pattern di Step 1 (questo modulo ha già helper analoghi a sentiment).

**3.1.** Rinominare `_resolve_signal_type` (linee 128-138) → `_resolve_target_outcome`. Stessa firma di Step 1.1.

**3.2.** Rinominare `_pick_token` (linee 140-150) per accettare `outcome_name: str` invece di `signal_type: SignalType`. Stessa firma di Step 1.2 (no fallback).

**3.3.** Nel corpo di `evaluate` (linee 75-110):
- `target_outcome = self._resolve_target_outcome(composite_signal, edge)`
- `if target_outcome is None: return None`
- `token_id = self._pick_token(market, target_outcome)`
- `if token_id is None: logger.debug(...); return None`
- Hardcodare `signal_type = SignalType.BUY`
- Mantenere `market_price`, `edge_amount`, `knowledge_sources` invariati

**3.4.** Aggiornare `_build_reasoning` (linee 152-164) per includere "BUY YES"/"BUY NO" invece di solo "bullish"/"bearish".

### Step 4 — `tests/test_strategies/test_sentiment.py`

**4.1.** Rinominare `test_sell_on_negative_sentiment_and_negative_edge` (linee 148-157) → `test_buy_no_on_negative_sentiment_and_negative_edge`:
- Cambiare assert `result.signal_type == SignalType.SELL` → `result.signal_type == SignalType.BUY`
- Aggiungere assert `result.token_id == "no-token"`

**4.2.** Rinominare `test_sell_token_is_no_outcome` (linee 169-178) → `test_buy_no_token_is_no_outcome`:
- Aggiungere assert `result.signal_type == SignalType.BUY`
- Mantenere assert `result.token_id == "no-token"`

**4.3.** Aggiungere `test_skips_signal_when_no_outcome_missing`:
```python
@pytest.mark.asyncio()
async def test_skips_signal_when_no_outcome_missing(
    self, strategy: SentimentStrategy
) -> None:
    """Market without 'No' outcome → BUY NO signal must be skipped."""
    market = Market(
        id="mkt-only-yes",
        question="?",
        category=MarketCategory.POLITICS,
        outcomes=[Outcome(token_id="yes-token", outcome="Yes", price=0.55)],
    )
    valuation = _make_valuation(fee_adjusted_edge=-0.06)
    knowledge = _make_knowledge(composite_signal=-0.5)
    result = await strategy.evaluate(market, valuation, knowledge)
    assert result is None
```

**4.4.** Aggiungere `test_buy_no_signal_market_price_equals_valuation_market_price`:
```python
@pytest.mark.asyncio()
async def test_buy_no_signal_market_price_equals_valuation_market_price(
    self, strategy: SentimentStrategy, market: Market
) -> None:
    """BUY NO signal carries valuation.market_price unchanged (consistent w/ value_edge)."""
    valuation = _make_valuation(fee_adjusted_edge=-0.06)
    knowledge = _make_knowledge(composite_signal=-0.5)
    result = await strategy.evaluate(market, valuation, knowledge)
    assert result is not None
    assert result.market_price == valuation.market_price
```

### Step 5 — `tests/test_strategies/test_event_driven.py`

**5.1.** Riscrivere `test_sell_signal_with_negative_composite_and_edge` (linee 156-166) → `test_buy_no_signal_with_negative_composite_and_edge`:
- Assert `signal.signal_type == SignalType.BUY` (era SELL)
- Mantenere assert `signal.token_id == "t2"` (NO outcome)

**5.2.** Aggiungere `test_skips_signal_when_no_outcome_missing` (analogo a 4.3, market con solo Yes outcome).

**5.3.** Aggiungere `test_buy_no_signal_market_price_equals_valuation_market_price`.

### Step 6 — `tests/test_strategies/test_knowledge_driven.py`

**6.1.** Riscrivere `test_sell_signal_on_negative_patterns_and_negative_edge` (linee 188-200) → `test_buy_no_signal_on_negative_patterns_and_negative_edge`:
- Assert `signal_type == SignalType.BUY` (era SELL)

**6.2.** Riscrivere `test_sell_token_is_no_outcome` (linee 228-238) → `test_buy_no_token_is_no_outcome`:
- Aggiungere assert `result.signal_type == SignalType.BUY`
- Mantenere assert `result.token_id == "no-token"`

**6.3.** Aggiungere `test_skips_signal_when_no_outcome_missing`.

**6.4.** Aggiungere `test_buy_no_signal_market_price_equals_valuation_market_price`.

---

## Ambiguità note (OBBLIGATORIO)

### A1 — `market_price` per BUY NO: divergenza prompt vs codice di riferimento

Il prompt utente afferma:
```python
market_price = 1.0 - yes_price     # NO token price
```
Tuttavia `value_edge.py:97` (citato come riferimento dal prompt stesso) NON fa questo — passa `valuation.market_price` verbatim per ENTRAMBI i branch (BUY YES e BUY NO):
```python
return Signal(
    ...,
    market_price=valuation.market_price,   # YES price, anche per branch BUY NO
    edge_amount=edge,
    ...
)
```

**Conseguenze divergenti:**

- Plan adotta `valuation.market_price` (consistenza con value_edge): `engine.py:294` userà il prezzo YES come prezzo dell'ordine sul token NO. Il risk manager calcolerà position size in unità di prezzo YES. **Bug latente** identico a quello già in value_edge.py.

- Plan adotta `1.0 - valuation.market_price`: position sizing e prezzo ordine semanticamente corretti per token NO. **Incoerenza** con value_edge.py (che resterebbe da fixare in PR separato).

**Raccomandazione del drafter**: opzione A (allineare a value_edge) per minimal-scope. Tracciare follow-up issue per investigare se value_edge.py ha lo stesso bug latente.

**Richiede decisione utente**: SI

### A2 — `market.no_token_id` non esiste

Il prompt utente cita:
```python
token_id = market.no_token_id      # on the NO token
```
Nessun campo `no_token_id` esiste in `app/models/market.py:65-99`. Il pattern reale (in tutto il codice) è name-based:
```python
next(o.token_id for o in market.outcomes if o.outcome.lower() == "no")
```

Plan procede con il pattern name-based esistente (no aggiunta di campo computed al modello).

**Richiede decisione utente**: solo se vuole aggiungere `no_token_id`/`yes_token_id` come computed_field (out-of-scope rispetto al fix richiesto).

### A3 — Fallback su `outcomes[0]` rimosso

Il pattern attuale ha fallback `market.outcomes[0].token_id if market.outcomes else ""`. Se manca esplicitamente l'outcome chiamata "No", il codice attuale finirebbe a comprare la prima outcome (probabilmente YES) — ricreando il bug originale ma in forma silenziosa.

**Plan rimuove il fallback**: se non si trova outcome "no" (o "yes") matchando per nome → return None (skip signal, log warning).

**Richiede decisione utente**: solo se invece preferisci log+continue con outcome[0] (sconsigliato).

### A4 — Segno di `edge_amount` per BUY NO

Per BUY YES: `edge_amount` positivo (edge favorevole).
Per BUY NO con edge YES negativo, `edge_amount` può essere:
- (a) negativo (segno originale; consistente con value_edge.py:98 `edge_amount=edge`)
- (b) positivo `abs(edge)` (rappresenta l'edge favorevole della posizione NO)

**Conseguenze**:
- `engine.py:255` priority scoring usa `abs(sig.edge_amount)` → agnostico
- `engine.py:271-275` risk KB classification usa segno → influisce
- DSS snapshot writer (Phase 13 W4) — da verificare

Plan adotta (a) per consistenza con value_edge.py.

### A5 — Helper `_pick_token` non estratto in `event_driven.py`

`sentiment.py` e `knowledge_driven.py` hanno helper `_pick_token`. `event_driven.py` ha la logica inline.

Plan tiene la logica inline in `event_driven.py` per minimizzare scope. Estrarre un helper condiviso in `base.py` o un modulo utility sarebbe rifactoring out-of-scope.

**Richiede decisione utente**: solo se vuole uniformare le 3 strategie con helper condiviso.

### A6 — `event_driven`: branch `combined_edge == 0` (non in scope, segnalato)

Il check `abs(combined_edge) < _MIN_COMBINED_EDGE` (linea 86) esclude lo zero (assumendo `_MIN_COMBINED_EDGE > 0`). Quindi `combined_edge == 0` non raggiunge il branch SELL nel codice attuale. Edge case latente già coperto. Plan non tocca questa logica.

---

## Assunzioni fatte (OBBLIGATORIO)

1. **`SignalType.SELL` resta nell'enum** — usato da `position_monitor.build_exit_order` per le exit. Non rimuoviamo il valore.

2. **`engine.py` invariato** — il mapping `SignalType.BUY → OrderSide.BUY` (riga 312) funziona correttamente: una BUY su token NO viene tradotta in `OrderSide.BUY` su quel token.

3. **`market_price` segue value_edge.py** (Ambiguità A1, opzione A): passa `valuation.market_price` verbatim. Se è bug pregresso anche in value_edge, fix in piano separato.

4. **Outcome name matching case-insensitive**: `o.outcome.lower() == "yes"|"no"` — pattern già consolidato.

5. **Mercati binari**: tutte e 3 le strategie operano su mercati binari Polymarket (politics/geopolitics/economics/all-domains) con outcome YES/NO. Mercati non-binari sono esclusi a monte dal `MarketService` filter.

6. **`value_edge.py` non modificato**: già corretto (linee 59-65). Pattern di riferimento.

7. **Test rinominati restano nello stesso file**: no relocation, no nuovo modulo.

8. **Convention `ruff` line-length=100, `mypy --strict`** rispettate.

9. **`_pick_token` cambiamento di firma è breaking ma interno**: nessun test ne usa direttamente la firma (verificato: test usano solo `evaluate`).

10. **Status di `signal.knowledge_sources`**: `event_driven` e `knowledge_driven` lo popolano; `sentiment` no. Plan non aggiunge `knowledge_sources` a `sentiment` (out-of-scope).

---

## Verifica (comandi eseguibili)

### V1 — Lint + format
```bash
ruff check app/strategies/ tests/test_strategies/
ruff format --check app/strategies/ tests/test_strategies/
```

### V2 — Type check
```bash
mypy --strict app/strategies/sentiment.py app/strategies/event_driven.py app/strategies/knowledge_driven.py
```

### V3 — Test mirati
```bash
pytest tests/test_strategies/test_sentiment.py tests/test_strategies/test_event_driven.py tests/test_strategies/test_knowledge_driven.py -v
```

### V4 — Test full suite (regressione)
```bash
pytest tests/ -x --ff
```

### V5 — Sanity grep post-modifica
```bash
# Deve essere 0: nessuna strategia emette SELL
rg "SignalType\.SELL" app/strategies/
# Deve apparire SOLO in execution/ (engine mapping + position_monitor exits)
rg "SignalType\.SELL" app/
```

### V6 — Done conditions
- [ ] V1 verde (lint + format)
- [ ] V2 verde (mypy strict, 0 errors)
- [ ] V3 verde (3 file test, +6 test cases nuovi: 3 "skip if NO missing" + 3 "market_price unchanged")
- [ ] V4 verde (full suite, no regressions)
- [ ] V5: `rg "SignalType.SELL" app/strategies/` ritorna 0 results
- [ ] Manuale (opzionale): tick in dry_run con market che evoca edge negativo → log `position_opened` su NO token, side=BUY

---

## Note implementative

- **Order of execution**: Step 1 → Step 2 → Step 3 sono indipendenti (file diversi, logica analoga). Possono essere parallelizzati. Step 4-6 dipendono da rispettivi Step 1-3.
- **Test budget**: ~30 min per implementazione + 15 min per test + 5 min per verifica = 50 min totali.
- **Risk**: BASSO. Cambiamenti localizzati, pattern già consolidato in `value_edge.py`. Test esistenti coprono i casi principali.
- **Commit message proposto**: `fix(strategies): emit BUY on NO token instead of SELL for negative edge`
