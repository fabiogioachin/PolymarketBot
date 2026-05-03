# PLAN.v2.md — P1 Tech Debt: SELL ≠ BUY NO (Round 3 merged)

**Round 3 — Opus merge of Round 2 critiques**
**Status**: 2 decisions pending in `OPEN-AMBIGUITIES.md` (Q1, Q2). Sections affected by these decisions are marked **[TBD-Q1]** / **[TBD-Q2]**.
Generated: 2026-05-02

---

## Obiettivo

Eliminare l'emissione di `SignalType.SELL` da `sentiment`, `event_driven`, `knowledge_driven` (e potenzialmente `resolution` — vedi Q1) quando l'edge è negativo, sostituendola con `SignalType.BUY` sul token NO. `SELL` rimane riservato alle exit gestite da `position_monitor.build_exit_order` e all'arbitraggio strategico (`arbitrage.py`).

---

## File impattati

### Modify (production code) — **[TBD-Q1]**

| Path | Always | Only if Q1=A |
|------|--------|--------------|
| `app/strategies/sentiment.py` | ✓ | |
| `app/strategies/event_driven.py` | ✓ | |
| `app/strategies/knowledge_driven.py` | ✓ | |
| `app/strategies/resolution.py` | | ✓ (4th strategy with same bug) |

### Modify (tests) — **[TBD-Q1]**

| Path | Always | Only if Q1=A |
|------|--------|--------------|
| `tests/test_strategies/test_sentiment.py` | ✓ | |
| `tests/test_strategies/test_event_driven.py` | ✓ | |
| `tests/test_strategies/test_knowledge_driven.py` | ✓ | |
| `tests/test_strategies/test_resolution.py` | | ✓ |

### Other

- `.claude/tasks/lessons.md` — append lesson entry (Step 7)
- `.claude/tasks/todo.md` — track follow-up issues (R2-07 dedup; R2-04 value_edge.py if Q2=B; R2-01 resolution.py if Q1=B)

### Do NOT modify

- `app/models/signal.py` — `SignalType.SELL` resta nell'enum (usato per exit + arbitrage)
- `app/execution/engine.py` — mapping `BUY→BUY` / `SELL→SELL` invariato (line 312)
- `app/strategies/value_edge.py` — pattern di riferimento; ha latent bug separato (Q2/follow-up)
- `app/strategies/arbitrage.py` — emette SELL **legittimamente** in arbitraggio sell-both (linee 141, 152)
- `app/strategies/rule_edge.py` — non emette SELL bug-style
- `app/execution/position_monitor.py` — `build_exit_order` invariato
- `tests/test_strategies/test_arbitrage.py` — assert `SignalType.SELL` legittimo (linee 138, 139, 158)
- `tests/test_risk/test_manager.py:119` — usa `SignalType.SELL` per testare risk-manager exit-side handling (estraneo al fix)
- `tests/test_execution/test_engine.py` — verificato: usa solo `SignalType.BUY` (linee 108, 138, 148, 966, 1070), nessuna interferenza
- `tests/test_integration/` — verificato: usa solo `SignalType.BUY`, nessuna interferenza

---

## Step di implementazione

### Step 1 — `app/strategies/sentiment.py`

**1.1.** Sostituire `_resolve_signal_type` (linee 134-144) con `_resolve_target_outcome`:
```python
from typing import Literal

def _resolve_target_outcome(
    self, sentiment: float, edge: float
) -> Literal["yes", "no"] | None:
    """Return the target outcome for a BUY signal, or None if no signal."""
    if sentiment > 0 and edge > 0:
        return "yes"
    if sentiment < 0 and edge < 0:
        return "no"
    return None
```

**1.2.** Riformulare `_pick_token` (linee 146-155). NUOVA FIRMA — accetta nome outcome, ritorna `str | None`, **rimuove fallback su outcomes[0]** (per A3):
```python
def _pick_token(
    self, market: Market, outcome_name: Literal["yes", "no"]
) -> str | None:
    target = outcome_name
    for o in market.outcomes:
        if o.outcome.strip().lower() == target:  # strip() per R2-11
            return o.token_id or None  # empty string → None per R2-06
    return None
```

**1.3.** Riscrivere il corpo di `evaluate` (linee 79-130) sostituendo l'attuale logica:
- `target_outcome = self._resolve_target_outcome(sentiment, edge)`
- `if target_outcome is None: ... return None` (logica disagree invariata)
- `token_id = self._pick_token(market, target_outcome)`
- **NUOVO check**:
  ```python
  if not token_id:  # None or empty string
      logger.debug(
          "sentiment: target outcome not found or empty token_id — skip",
          market_id=market.id,
          target_outcome=target_outcome,
      )
      return None
  ```
- `signal_type = SignalType.BUY` (hardcoded prima della creazione Signal)
- `market_price = ` **[TBD-Q2]**: vedi sotto
- Reasoning **invariato** (no rewrite — R2-14 dropped). La stringa attuale "Sentiment composite signal {sentiment} (bullish/bearish) aligns with fee-adjusted edge {edge}" resta come è.

**1.4.** Aggiornare `logger.info` (linee 111-118) — sostituire `signal_type=signal_type` con `target_outcome=target_outcome`. Mantenere `sentiment`, `edge`, `confidence`, `market_id` invariati.

**[TBD-Q2]** — `market_price` value:
- Q2=A → `market_price=valuation.market_price` (YES price; consistent w/ value_edge bug)
- Q2=B → `market_price=valuation.market_price if target_outcome == "yes" else 1.0 - valuation.market_price` (correct)

### Step 2 — `app/strategies/event_driven.py`

**2.1.** Sostituire il blocco SELL inline (linee 95-106). **CURRENT CODE** (riga 95-106):
```python
if combined_edge > 0:
    signal_type = SignalType.BUY
    token_id = next(
        (o.token_id for o in market.outcomes if o.outcome.lower() == "yes"),
        market.outcomes[0].token_id if market.outcomes else "",
    )
else:
    signal_type = SignalType.SELL
    token_id = next(
        (o.token_id for o in market.outcomes if o.outcome.lower() == "no"),
        market.outcomes[0].token_id if market.outcomes else "",
    )
```

**Replace with** (R2-16 defensive form, R2-21 expanded):
```python
signal_type = SignalType.BUY
target_outcome: Literal["yes", "no"] | None
if combined_edge > 0:
    target_outcome = "yes"
elif combined_edge < 0:
    target_outcome = "no"
else:
    return None  # unreachable in practice (filtered by abs check at line 86), defensive

token_id = next(
    (
        o.token_id
        for o in market.outcomes
        if o.outcome.strip().lower() == target_outcome
    ),
    None,
)
if not token_id:  # None or empty string
    logger.debug(
        "event_driven: target outcome not found or empty token_id — skip",
        market_id=market.id,
        target_outcome=target_outcome,
    )
    return None
```

Note: rimuove il fallback `market.outcomes[0].token_id if market.outcomes else ""` (per A3).

**2.2.** Aggiornare `logger.info` (linee 119-126):
- Sostituire `signal_type=signal_type` con `target_outcome=target_outcome`
- Mantenere `combined_edge`, `fresh_event`, `patterns` invariati

**2.3.** Reasoning string (linee 110-117) **invariato** — R2-14 dropped.

**[TBD-Q2]** — `market_price` come Step 1.

### Step 3 — `app/strategies/knowledge_driven.py`

Pattern uguale a Step 1 (questo modulo ha già helper analoghi a sentiment).

**3.1.** Rinominare `_resolve_signal_type` (linee 128-138) → `_resolve_target_outcome`. Stessa firma di Step 1.1 con `Literal["yes","no"] | None`.

**3.2.** Rinominare `_pick_token` (linee 140-150) per accettare `outcome_name: Literal["yes","no"]` ritornando `str | None`. **Stessa logica di Step 1.2** (strip+lower, no fallback, empty → None).

**3.3.** Nel corpo di `evaluate` (linee 75-110):
- `target_outcome = self._resolve_target_outcome(composite_signal, edge)`
- `if target_outcome is None: return None`
- `token_id = self._pick_token(market, target_outcome)`
- `if not token_id: logger.debug(...); return None`
- Hardcodare `signal_type = SignalType.BUY`

**3.4.** Aggiornare `logger.info` (linee 91-98):
- Sostituire `signal_type=signal_type` con `target_outcome=target_outcome`
- Mantenere `composite_signal`, `confidence`, `patterns` invariati

**3.5.** `_build_reasoning` (linee 152-164) **invariato** — R2-14 dropped.

**[TBD-Q2]** — `market_price` come Step 1.

### Step 4 — `app/strategies/resolution.py` — **[TBD-Q1]**, applicabile solo se Q1=A

Se Q1=A (widen scope):

**4.1.** Modificare il blocco SELL (linee 116-128). **CURRENT CODE**:
```python
return Signal(
    strategy=self.name,
    market_id=market.id,
    token_id=self._get_no_token(market),
    signal_type=SignalType.SELL,         # ← BUG
    confidence=confidence,
    market_price=valuation.market_price,
    edge_amount=round(profit, 4),
    reasoning=(...),
)
```

**Replace with**:
```python
no_token_id = self._get_no_token(market)
if not no_token_id:
    logger.debug(
        "resolution: NO outcome not found or empty token_id — skip",
        market_id=market.id,
    )
    return None
return Signal(
    strategy=self.name,
    market_id=market.id,
    token_id=no_token_id,
    signal_type=SignalType.BUY,          # ← FIXED
    confidence=confidence,
    market_price=<TBD-Q2>,                # see Q2
    edge_amount=round(profit, 4),
    reasoning=(...),                      # invariato
)
```

**4.2.** Aggiornare `logger.info` (linee 108-115): sostituire `"resolution: SELL signal (buy NO)"` con `"resolution: BUY NO signal"`. Mantenere `fair_value`, `yes_price`, `days_remaining`, `profit` invariati.

**4.3.** Aggiornare `_get_no_token` (linee 152-157) per applicare `.strip().lower()` come Step 1.2 (consistency).

### Step 5 — `tests/test_strategies/test_sentiment.py`

Convention: tests nella class `TestSignalGeneration` (R2-10).

**5.1.** Modificare `test_sell_on_negative_sentiment_and_negative_edge` (linee 148-157) → rinominare `test_buy_no_on_negative_sentiment_and_negative_edge`:
```python
@pytest.mark.asyncio()
async def test_buy_no_on_negative_sentiment_and_negative_edge(
    self, strategy: SentimentStrategy, market: Market
) -> None:
    valuation = _make_valuation(fee_adjusted_edge=-0.06)
    knowledge = _make_knowledge(composite_signal=-0.5)
    result = await strategy.evaluate(market, valuation, knowledge)

    assert result is not None
    assert result.signal_type == SignalType.BUY      # was SELL
    assert result.token_id == "no-token"
    assert result.edge_amount < 0                     # R2-13: sign convention lock
```

**5.2.** Modificare `test_sell_token_is_no_outcome` (linee 169-178) → rinominare `test_buy_no_token_is_no_outcome`. Aggiungere `assert result.signal_type == SignalType.BUY`.

**5.3.** [Class `TestSignalGeneration`] Aggiungere `test_skips_signal_when_no_outcome_missing` (R2-05 like, applicato all'edge case "no NO outcome"):
```python
@pytest.mark.asyncio()
async def test_skips_signal_when_no_outcome_missing(
    self, strategy: SentimentStrategy
) -> None:
    """Market without 'No' outcome → BUY NO signal must be skipped (no fallback)."""
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

**5.4.** [Class `TestSignalGeneration`] Aggiungere `test_returns_none_for_multi_outcome_market` (R2-05):
```python
@pytest.mark.asyncio()
async def test_returns_none_for_multi_outcome_market(
    self, strategy: SentimentStrategy
) -> None:
    """3+ outcome market with no exact 'no' match → return None (defensive)."""
    market = Market(
        id="mkt-multi",
        question="?",
        category=MarketCategory.POLITICS,
        outcomes=[
            Outcome(token_id="yes", outcome="Yes", price=0.4),
            Outcome(token_id="maybe", outcome="Maybe", price=0.3),
            Outcome(token_id="no", outcome="No", price=0.3),
        ],
    )
    # 3-outcome market WITH "No" outcome — strategy still works (matches "No")
    valuation = _make_valuation(fee_adjusted_edge=-0.06)
    knowledge = _make_knowledge(composite_signal=-0.5)
    result = await strategy.evaluate(market, valuation, knowledge)
    # The current implementation accepts any market with a "No" outcome.
    # This test documents that behavior — change if a binary-only guard is added.
    assert result is not None
    assert result.token_id == "no"
```

**5.5.** [Class `TestSignalGeneration`] Aggiungere `test_skips_signal_when_no_token_id_empty` (R2-06):
```python
@pytest.mark.asyncio()
async def test_skips_signal_when_no_token_id_empty(
    self, strategy: SentimentStrategy
) -> None:
    """Outcome 'No' with empty token_id → skip signal."""
    market = Market(
        id="mkt-empty-no",
        question="?",
        category=MarketCategory.POLITICS,
        outcomes=[
            Outcome(token_id="yes-token", outcome="Yes", price=0.55),
            Outcome(token_id="", outcome="No", price=0.45),  # empty token_id
        ],
    )
    valuation = _make_valuation(fee_adjusted_edge=-0.06)
    knowledge = _make_knowledge(composite_signal=-0.5)
    result = await strategy.evaluate(market, valuation, knowledge)
    assert result is None
```

**5.6.** [Class `TestSignalGeneration`] Aggiungere `test_matches_outcome_with_whitespace` (R2-11 — single representative test, applies via shared `_pick_token` pattern):
```python
@pytest.mark.asyncio()
async def test_matches_outcome_with_whitespace(
    self, strategy: SentimentStrategy
) -> None:
    """Outcome name with whitespace ' No ' should match via strip()."""
    market = Market(
        id="mkt-ws",
        question="?",
        category=MarketCategory.POLITICS,
        outcomes=[
            Outcome(token_id="yes-token", outcome=" Yes ", price=0.55),
            Outcome(token_id="no-token", outcome=" No ", price=0.45),
        ],
    )
    valuation = _make_valuation(fee_adjusted_edge=-0.06)
    knowledge = _make_knowledge(composite_signal=-0.5)
    result = await strategy.evaluate(market, valuation, knowledge)
    assert result is not None
    assert result.token_id == "no-token"
```

**5.7.** **[TBD-Q2]** — market_price test. **Decision contingent**:
- Q2=A → Aggiungere `test_buy_no_signal_market_price_currently_equals_yes_price_pending_value_edge_followup` (warning name) asserting `result.market_price == valuation.market_price`.
- Q2=B → Aggiungere `test_buy_no_signal_market_price_equals_no_price` asserting `result.market_price == 1.0 - valuation.market_price`.

### Step 6 — `tests/test_strategies/test_event_driven.py`

Convention: module-level functions con `@pytest.mark.asyncio` (no class grouping in this file — R2-10).

**6.1.** Modificare `test_sell_signal_with_negative_composite_and_edge` (linee 156-166) → rinominare `test_buy_no_signal_with_negative_composite_and_edge`:
```python
@pytest.mark.asyncio
async def test_buy_no_signal_with_negative_composite_and_edge() -> None:
    strategy = EventDrivenStrategy()
    market = _make_market()
    valuation = _make_valuation(fee_adjusted_edge=-0.10, confidence=0.6)
    knowledge = _make_knowledge(composite_signal=-0.6, confidence=0.7)

    signal = await strategy.evaluate(market, valuation, knowledge)

    assert signal is not None
    assert signal.signal_type == SignalType.BUY     # was SELL
    assert signal.token_id == "t2"                   # NO outcome
    assert signal.edge_amount < 0                    # R2-13
```

**6.2.** Aggiungere `test_skips_signal_when_no_outcome_missing` (analogo a 5.3, market-level function).

**6.3.** Aggiungere `test_skips_signal_when_no_token_id_empty` (analogo a 5.5).

**6.4.** **[TBD-Q2]** — market_price test (analogo a 5.7).

### Step 7 — `tests/test_strategies/test_knowledge_driven.py`

Convention: tests nella class `TestSignalGeneration` (R2-10).

**7.1.** Modificare `test_sell_signal_on_negative_patterns_and_negative_edge` (linee 188-200) → rinominare `test_buy_no_signal_on_negative_patterns_and_negative_edge`. Aggiungere `signal_type == SignalType.BUY` e `signal.edge_amount < 0`.

**7.2.** Modificare `test_sell_token_is_no_outcome` (linee 228-238) → rinominare `test_buy_no_token_is_no_outcome`. Aggiungere `signal_type == SignalType.BUY`.

**7.3.** Aggiungere `test_skips_signal_when_no_outcome_missing` (analogo a 5.3, in class `TestSignalGeneration`).

**7.4.** Aggiungere `test_skips_signal_when_no_token_id_empty` (analogo a 5.5).

**7.5.** **[TBD-Q2]** — market_price test.

### Step 8 — `tests/test_strategies/test_resolution.py` — **[TBD-Q1]**, applicabile solo se Q1=A

Se Q1=A:

**8.1.** Modificare `test_sell_signal_low_probability_market` (linee 178-192) → rinominare `test_buy_no_signal_low_probability_market`:
```python
async def test_buy_no_signal_low_probability_market() -> None:
    """fair_value=0.10, yes_price=0.85 → NO is mispriced, buy NO (BUY signal on NO token)."""
    ...
    assert signal.signal_type == SignalType.BUY     # was SELL
    assert signal.token_id == "no-tok"
    assert signal.edge_amount > 0                    # resolution.py uses positive edge_amount
```

**8.2.** Modificare `test_sell_signal_reasoning_contains_key_fields` → rinominare `test_buy_no_signal_reasoning_contains_key_fields`. Reasoning string invariato (R2-14 dropped).

**8.3.** Aggiungere `test_skips_signal_when_no_outcome_missing` (resolution-specific edge).

### Step 9 — Capture lesson — `.claude/tasks/lessons.md` (R2-20)

Append per format `~/.claude/lessons-format.md` (1 voce):
- **Lesson**: SignalType.SELL means OrderSide.SELL on the tagged token, NOT "opposite direction". To express bearish → BUY on NO token.
- **Reference pattern**: `app/strategies/value_edge.py:59-65`
- **Engine mapping**: `app/execution/engine.py:312` (`signal_type → OrderSide` map)
- **Trigger to remember**: any time you write `signal_type = SignalType.SELL`, ask: "is this an EXIT (existing position) or an ARBITRAGE leg (intentional)? If neither → wrong, use BUY on the inverse token."

### Step 10 — Track follow-ups — `.claude/tasks/todo.md`

Aggiungere voci (in base alle decisioni Q1/Q2):
- **R2-07** (always): "BUG-2 dedup guard cross-token same-market — engine.py:233-244 dovrebbe skippare BUY signals su market dove qualsiasi token è già held"
- **R2-04 / Q2** (if Q2=B): "value_edge.py:97 — fix market_price to (1.0 - yes_price) for BUY-NO branch (consistency con post-fix sentiment/event_driven/knowledge_driven)"
- **R2-01 / Q1** (if Q1=B): "resolution.py:120 — same SELL→BUY-NO bug; same fix as sentiment/event_driven/knowledge_driven"

---

## Ambiguità note (residue dopo Round 3)

### A1 — `market_price` per BUY NO **[TBD-Q2]**

Vedi `OPEN-AMBIGUITIES.md` Q2. Decisione utente richiesta.

### A2 — `market.no_token_id` non esiste — RISOLTA

Confermato: il campo non esiste. Pattern name-based (con `.strip().lower()` per R2-11) adottato uniformemente.

### A3 — Fallback su `outcomes[0]` — RISOLTA

Pattern di fallback rimosso. Tutti i 3 (o 4) strategy ritornano `None` se outcome non trovato o `token_id` vuoto/None (R2-06).

### A4 — Segno `edge_amount` per BUY NO — CORRETTA POST-R2-03

L'analisi originale era materialmente errata. Stato corretto:
- `engine.py:255` priority: usa `abs(edge_amount)` → agnostico al segno
- `engine.py:271` risk KB: usa `abs(signal.edge_amount)` → agnostico
- `engine.py:339, 353` log: stampa segno raw → solo informativo
- `risk/manager.py:202` sizing: usa `abs(signal.edge_amount)` → agnostico

**Conclusione**: la scelta tra (a) `edge_amount=edge` (signed) e (b) `edge_amount=abs(edge)` è puramente di documentazione/log clarity. Nessun impatto comportamentale. Plan adotta (a) per consistenza con value_edge.py:98.

### A5 — Helper `_pick_token` non estratto in event_driven.py — INVARIATA

event_driven.py mantiene logica inline. Helper estratto in base.py o utility resta out-of-scope (sentiment.py e knowledge_driven.py mantengono i propri helper privati).

### A6 — `event_driven` `combined_edge == 0` — RISOLTA via R2-16

Branch ora esplicito `if/elif/else` con `return None` su zero (defensive).

### A7 — Cross-token same-market dedup (NEW da R2-07)

**Fuori scope**. Documentato come known limitation:
> Dopo questo fix, una strategia potrebbe emettere BUY YES al tick T1, poi BUY NO sullo stesso market al tick T2 (es. sentiment flip). Il dedup guard a `engine.py:233-244` controlla solo `sig.token_id in open_position_token_ids` — non cross-token same-market. Risultato: si potrebbe finire con YES + NO sullo stesso market (hedge parziale, controproducente date le fee).

Follow-up tracciato in `.claude/tasks/todo.md` (Step 10).

### A8 — Multi-outcome markets (NEW da R2-05)

Non esiste un filtro centralizzato verificabile in `app/services/market.py` (path non esiste). Comportamento attuale:
- Strategia matcha `outcome.strip().lower() == "no"` → ritorna NO outcome se presente
- Se mercato ha 3+ outcome ma una di queste è chiamata "No" → strategy procede normalmente
- Se nessuna outcome chiamata "no" (es. mercato categorial puro) → return None (safe-by-construction)

Test 5.4 documenta questo comportamento.

---

## Assunzioni fatte (residue dopo Round 3)

1. `SignalType.SELL` resta nell'enum (exits via `position_monitor` + arbitrage strategico).
2. `engine.py` invariato (mapping BUY→BUY).
3. **[TBD-Q2]**: `market_price` semantic decision pending.
4. Outcome name matching: `o.outcome.strip().lower() == "yes"|"no"` (R2-11 strip aggiunto).
5. Mercati binari: niente filter centralizzato verificato; defensive return None se outcome name non trova match.
6. `value_edge.py` invariato: ha latent bug separato (Q2 follow-up se Q2=B).
7. Test rinominati restano nei rispettivi file (no relocation).
8. `ruff` line-length=100, `mypy --strict` rispettati.
9. `_pick_token` cambiamento di firma è breaking ma interno (helper privato, no test diretto: verificato).
10. `signal.knowledge_sources` invariato per ogni strategia.
11. **(NEW)** Reasoning string invariato (R2-14 dropped — no scope creep).

---

## Verifica (comandi eseguibili) — aggiornata Round 3

### V1 — Lint + format
```bash
ruff check app/strategies/ tests/test_strategies/
ruff format --check app/strategies/ tests/test_strategies/
```

### V2 — Type check (Literal richiede mypy strict OK)
```bash
mypy --strict app/strategies/sentiment.py app/strategies/event_driven.py app/strategies/knowledge_driven.py
# Se Q1=A:
mypy --strict app/strategies/resolution.py
```

### V3 — Test mirati
```bash
pytest tests/test_strategies/test_sentiment.py \
       tests/test_strategies/test_event_driven.py \
       tests/test_strategies/test_knowledge_driven.py \
       -v
# Se Q1=A:
pytest tests/test_strategies/test_resolution.py -v
```

### V4 — Test full suite (regressione)
```bash
pytest tests/ -x --ff
```

### V5 — Sanity grep post-modifica (ristretto, R2-02 fix)

```bash
# Strategie in scope: 0 occorrenze attese
rg "SignalType\.SELL" app/strategies/sentiment.py \
                      app/strategies/event_driven.py \
                      app/strategies/knowledge_driven.py
# Se Q1=A: aggiungi anche resolution.py al check sopra

# Restanti strategie: occorrenze legittime (arbitrage SELL strategici)
rg "SignalType\.SELL" app/strategies/arbitrage.py
# Atteso: 2 occorrenze (linee 141, 152) — sell-both arbitrage leg

# Helper rinominati: no caller rotti
rg "_resolve_signal_type" tests/  # atteso: 0
rg "_resolve_target_outcome" tests/  # atteso: 0 (helper privato)
rg "_pick_token" tests/  # atteso: 0 (helper privato)

# Integration tests: verifica nessuna assertion SELL per testare strategy
rg "SignalType\.SELL" tests/test_execution/ tests/test_integration/
# Atteso: 0 (verificato durante Round 3)
```

### V6 — Done conditions
- [ ] V1 verde (lint + format)
- [ ] V2 verde (mypy strict, 0 errors)
- [ ] V3 verde — 3 file test base + 4° (resolution) se Q1=A
  - +6 nuovi test base (skip-no-missing, skip-empty-token, multi-outcome, whitespace, market_price, sign convention dove applicabile) per `sentiment` (la più rappresentativa)
  - +2-3 test analoghi per `event_driven` e `knowledge_driven`
  - +1-3 test per `resolution` se Q1=A
- [ ] V4 verde (full suite, no regressions)
- [ ] V5 grep risultati allineati
- [ ] Step 9 lesson aggiunta a `.claude/tasks/lessons.md`
- [ ] Step 10 follow-up tracciati in `.claude/tasks/todo.md`

---

## Note implementative

### Order of execution
- Step 1, 2, 3 (e Step 4 se Q1=A) sono indipendenti (file diversi). Parallelizzabili in subagenti distinti.
- Step 5, 6, 7 (e Step 8 se Q1=A) dipendono dai rispettivi file di produzione modificati.
- Step 9 e 10 alla fine, dopo verifica V1-V5.

### Commit organization (R2-22)
**Raccomandato**: **single atomic commit** con tutti i 3 (o 4) strategie + tests. Razionale: bug semantico unico, atomic revert se issue. Bisectability garantita perché il commit "abbraccia" l'intera correzione.

Alternative: 3 (o 4) commit sequenziali — uno per strategia + suoi test. Maggiore granularità ma reverting un solo file lascerebbe stato incoerente (alcune strategie corrette, altre no).

Commit message proposto:
```
fix(strategies): emit BUY on NO token instead of SELL for negative edge

Sentiment, event_driven, knowledge_driven (e resolution se Q1=A) emettevano
SignalType.SELL su NO token per esprimere "buy NO" — silently invalid in
shadow/live perché engine.py:312 mappa SELL→OrderSide.SELL su quel token.
Fix: emette BUY su NO token (pattern di value_edge.py:59-65).

Adds test coverage:
- skip when NO outcome missing
- skip when token_id empty
- whitespace-tolerant outcome name matching
- sign convention lock for edge_amount
- [TBD-Q2] market_price assertion

Tracks follow-ups in .claude/tasks/todo.md (R2-04, R2-07, R2-01 if Q1=B).
```

### Risk assessment
**BASSO**. Cambiamenti localizzati (3-4 file prod, 3-4 file test). Pattern di riferimento consolidato (value_edge.py). Test esistenti coprono i casi principali. Test nuovi lockano comportamento safety-by-construction.

### Test budget
~45-60 min totali post-decisione Q1/Q2:
- Implementazione 3 (o 4) strategie: ~25 min
- Test rewrite + 6 nuovi test: ~20 min
- Lint, mypy, run test, fix iterativo: ~15 min
