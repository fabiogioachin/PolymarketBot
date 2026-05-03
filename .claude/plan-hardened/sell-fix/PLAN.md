# PLAN.md — P1 Tech Debt: SELL ≠ BUY NO (FINAL)

**Pipeline**: `/plan-hardened`
**Status**: FINAL — all Round 4 decisions resolved.
**Round 4 user decisions**: **Q1=A** (include `resolution.py`), **Q2=B** (`market_price = 1.0 - valuation.market_price` for BUY-NO).
**Round 2 input**: 22 reviewer issues — 19 VALID merged, 0 INVALID rejected, 2 NEEDS_USER resolved (Q1=A, Q2=B), 1 DEFERRED (R2-18, contingent on Q2 → resolved as Q2=B → drop "warning name" test, add NO-price test).
Generated: 2026-05-02

---

## Cross-references

- **Multi-alternative event selection refactor** (orthogonal architectural workstream, separate plan): see `.claude/plan-hardened/group-refactor/PLAN.md`. That plan **gates on this fix being merged first** (preflight check at `group-refactor/PLAN.md` line 13–22). The two changes do not overlap in code paths and can be implemented sequentially.
- **Reference pattern** (correct shape for BUY-NO emission): `app/strategies/value_edge.py:52-65`. Note: `value_edge.py:97` has a separate latent `market_price` bug — tracked as follow-up R2-04 because we picked Q2=B.
- **Engine mapping** (proves the bug): `app/execution/engine.py:312` — `OrderSide.BUY if signal.signal_type == SignalType.BUY else OrderSide.SELL`. Issuing `SELL` on a NO token attempts to sell shares the bot does not own → silently invalid in shadow/live, broken P&L tracking in dry_run.

---

## Obiettivo

Eliminare l'emissione di `SignalType.SELL` da `sentiment`, `event_driven`, `knowledge_driven`, `resolution` quando l'edge è negativo, sostituendola con `SignalType.BUY` sul token NO con `market_price = 1.0 - valuation.market_price`. `SELL` rimane riservato alle exit gestite da `position_monitor.build_exit_order` e all'arbitraggio strategico (`arbitrage.py`).

---

## File impattati

### Modify (production code, 4 files)

- `app/strategies/sentiment.py`
- `app/strategies/event_driven.py`
- `app/strategies/knowledge_driven.py`
- `app/strategies/resolution.py` *(included per Q1=A)*

### Modify (tests, 4 files)

- `tests/test_strategies/test_sentiment.py`
- `tests/test_strategies/test_event_driven.py`
- `tests/test_strategies/test_knowledge_driven.py`
- `tests/test_strategies/test_resolution.py` *(included per Q1=A)*

### Other

- `.claude/tasks/lessons.md` — append lesson entry (Step 9)
- `.claude/tasks/todo.md` — track follow-up issues (R2-04 `value_edge.py` market_price; R2-07 cross-token same-market dedup; cross-ref to multi-alternative refactor in `group-refactor/`)

### Do NOT modify

- `app/models/signal.py` — `SignalType.SELL` resta nell'enum (usato per exit + arbitrage)
- `app/execution/engine.py` — mapping `BUY→BUY` / `SELL→SELL` invariato (line 312)
- `app/strategies/value_edge.py` — pattern di riferimento; ha latent `market_price` bug separato (R2-04, follow-up)
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

**1.2.** Riformulare `_pick_token` (linee 146-155). NUOVA FIRMA — accetta nome outcome, ritorna `str | None`, **rimuove fallback su `outcomes[0]`** (per A3):
```python
def _pick_token(
    self, market: Market, outcome_name: Literal["yes", "no"]
) -> str | None:
    for o in market.outcomes:
        if o.outcome.strip().lower() == outcome_name:  # strip() per R2-11
            return o.token_id or None  # empty string → None per R2-06
    return None
```

**1.3.** Riscrivere il corpo di `evaluate` (linee 79-130):
- `target_outcome = self._resolve_target_outcome(sentiment, edge)`
- `if target_outcome is None: ... return None` (logica disagree invariata)
- `token_id = self._pick_token(market, target_outcome)`
- **Guard NUOVO**:
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
- **`market_price` (Q2=B)**:
  ```python
  yes_price = valuation.market_price
  market_price = yes_price if target_outcome == "yes" else 1.0 - yes_price
  ```
- Reasoning **invariato** (no rewrite — R2-14 dropped). La stringa attuale "Sentiment composite signal {sentiment} (bullish/bearish) aligns with fee-adjusted edge {edge}" resta come è.

**1.4.** Aggiornare `logger.info` (linee 111-118) — sostituire `signal_type=signal_type` con `target_outcome=target_outcome`. Mantenere `sentiment`, `edge`, `confidence`, `market_id` invariati.

### Step 2 — `app/strategies/event_driven.py`

**2.1.** Sostituire il blocco SELL inline (linee 95-106). **CURRENT CODE**:
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

**Replace with** (R2-16 `if/elif/else` defensive form, R2-21 expanded, R2-06 empty-token guard, A3 no fallback):
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

yes_price = valuation.market_price
market_price = yes_price if target_outcome == "yes" else 1.0 - yes_price
```

**2.2.** Aggiornare `logger.info` (linee 119-126):
- Sostituire `signal_type=signal_type` con `target_outcome=target_outcome`
- Mantenere `combined_edge`, `fresh_event`, `patterns` invariati

**2.3.** Reasoning string (linee 110-117) **invariato** — R2-14 dropped.

**2.4.** Nel `Signal(...)` constructor: `market_price=market_price` (la variabile locale calcolata sopra), non più `valuation.market_price` raw.

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
- **`market_price` (Q2=B)**: `market_price = valuation.market_price if target_outcome == "yes" else 1.0 - valuation.market_price`

**3.4.** Aggiornare `logger.info` (linee 91-98):
- Sostituire `signal_type=signal_type` con `target_outcome=target_outcome`
- Mantenere `composite_signal`, `confidence`, `patterns` invariati

**3.5.** `_build_reasoning` (linee 152-164) **invariato** — R2-14 dropped.

### Step 4 — `app/strategies/resolution.py` *(Q1=A)*

**4.1.** Modificare il blocco SELL (linee 116-128). **CURRENT CODE**:
```python
return Signal(
    strategy=self.name,
    market_id=market.id,
    token_id=self._get_no_token(market),
    signal_type=SignalType.SELL,         # ← BUG
    confidence=confidence,
    market_price=valuation.market_price, # ← also wrong (Q2=B)
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
    signal_type=SignalType.BUY,                       # ← FIXED
    confidence=confidence,
    market_price=1.0 - valuation.market_price,        # ← FIXED (Q2=B, NO price)
    edge_amount=round(profit, 4),
    reasoning=(...),                                   # invariato
)
```

**4.2.** Aggiornare `logger.info` (linee 108-115): sostituire `"resolution: SELL signal (buy NO)"` con `"resolution: BUY NO signal"`. Mantenere `fair_value`, `yes_price`, `days_remaining`, `profit` invariati.

**4.3.** Aggiornare `_get_no_token` (linee 152-157) per applicare `.strip().lower()` come Step 1.2 (consistency) e ritornare `None` invece di `""` quando non trova match (così il guard `if not no_token_id` copre entrambi i casi).

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

**5.3.** [Class `TestSignalGeneration`] Aggiungere `test_skips_signal_when_no_outcome_missing` (R2-05):
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
    """3+ outcome market WITH a 'No' label still works (matches via name)."""
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
    valuation = _make_valuation(fee_adjusted_edge=-0.06)
    knowledge = _make_knowledge(composite_signal=-0.5)
    result = await strategy.evaluate(market, valuation, knowledge)
    # Documents current behavior — strategy accepts any market with a "No" outcome.
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

**5.6.** [Class `TestSignalGeneration`] Aggiungere `test_matches_outcome_with_whitespace` (R2-11):
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

**5.7.** [Class `TestSignalGeneration`] Aggiungere `test_buy_no_signal_market_price_equals_no_price` (R2-18, Q2=B):
```python
@pytest.mark.asyncio()
async def test_buy_no_signal_market_price_equals_no_price(
    self, strategy: SentimentStrategy, market: Market
) -> None:
    """For BUY-NO, market_price must be 1.0 - YES_price (the actual NO book price)."""
    yes_price = 0.55
    valuation = _make_valuation(fee_adjusted_edge=-0.06, market_price=yes_price)
    knowledge = _make_knowledge(composite_signal=-0.5)
    result = await strategy.evaluate(market, valuation, knowledge)
    assert result is not None
    assert result.signal_type == SignalType.BUY
    assert result.market_price == pytest.approx(1.0 - yes_price)
```

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

**6.2.** Aggiungere `test_skips_signal_when_no_outcome_missing` (analogo a 5.3, module-level).

**6.3.** Aggiungere `test_skips_signal_when_no_token_id_empty` (analogo a 5.5).

**6.4.** Aggiungere `test_buy_no_signal_market_price_equals_no_price` (analogo a 5.7).

### Step 7 — `tests/test_strategies/test_knowledge_driven.py`

Convention: tests nella class `TestSignalGeneration` (R2-10).

**7.1.** Modificare `test_sell_signal_on_negative_patterns_and_negative_edge` (linee 188-200) → rinominare `test_buy_no_signal_on_negative_patterns_and_negative_edge`. Aggiungere `signal_type == SignalType.BUY` e `signal.edge_amount < 0`.

**7.2.** Modificare `test_sell_token_is_no_outcome` (linee 228-238) → rinominare `test_buy_no_token_is_no_outcome`. Aggiungere `signal_type == SignalType.BUY`.

**7.3.** Aggiungere `test_skips_signal_when_no_outcome_missing` (analogo a 5.3, in class `TestSignalGeneration`).

**7.4.** Aggiungere `test_skips_signal_when_no_token_id_empty` (analogo a 5.5).

**7.5.** Aggiungere `test_buy_no_signal_market_price_equals_no_price` (analogo a 5.7).

### Step 8 — `tests/test_strategies/test_resolution.py` *(Q1=A)*

**8.1.** Modificare `test_sell_signal_low_probability_market` (linee 178-192) → rinominare `test_buy_no_signal_low_probability_market`:
```python
async def test_buy_no_signal_low_probability_market() -> None:
    """fair_value=0.10, yes_price=0.85 → NO is mispriced, buy NO (BUY signal on NO token)."""
    ...
    assert signal.signal_type == SignalType.BUY     # was SELL
    assert signal.token_id == "no-tok"
    assert signal.edge_amount > 0                    # resolution.py uses positive edge_amount
    assert signal.market_price == pytest.approx(1.0 - 0.85)  # NO price (Q2=B)
```

**8.2.** Modificare `test_sell_signal_reasoning_contains_key_fields` → rinominare `test_buy_no_signal_reasoning_contains_key_fields`. Reasoning string invariato (R2-14 dropped).

**8.3.** Aggiungere `test_skips_signal_when_no_outcome_missing` (resolution-specific edge: `_get_no_token` returns None → strategy returns None invece di emettere Signal con `token_id=""`).

### Step 9 — Capture lesson — `.claude/tasks/lessons.md` (R2-20)

Append (1 voce):

> **Lesson — `SignalType.SELL` semantics**
> `SignalType.SELL` mappa a `OrderSide.SELL` sul token taggato (`engine.py:312`), NON a "direzione opposta". Per esprimere intent bearish da una strategia entry-side: emettere `SignalType.BUY` sul **token NO** con `market_price = 1.0 - valuation.market_price`. Pattern di riferimento: `app/strategies/value_edge.py:52-65` (con caveat: `value_edge.py:97` ha lo stesso latent `market_price` bug — tracked R2-04).
> **Trigger**: ogni volta che si scrive `signal_type = SignalType.SELL`, chiedere: "è una EXIT (`position_monitor`) o un'ARBITRAGE leg (`arbitrage.py`)? Se nessuna → bug, usare BUY sul token inverso."

### Step 10 — Track follow-ups — `.claude/tasks/todo.md`

Aggiungere (P2 sezione, sotto P1 SELL≠BUY-NO che diventa "✅ FIXED 2026-05-02"):

- **R2-04** (Q2=B implication): `value_edge.py:97` — fix `market_price` to `1.0 - valuation.market_price` for BUY-NO branch (consistency con post-fix sentiment/event_driven/knowledge_driven/resolution).
- **R2-07**: BUG-3 cross-token same-market dedup guard — `engine.py:233-244` controlla solo `sig.token_id in open_position_token_ids`, non cross-token same-market. Conseguenza: il bot può finire con YES + NO sullo stesso market (hedge parziale, controproducente date le fee).
- **CROSS-REF**: multi-alternative event selection refactor — vedi `.claude/plan-hardened/group-refactor/PLAN.md`. Plan separato già prodotto via `/plan-hardened`. Preflight check di quel plan (linee 13–22) dipende dal merge di **questo** fix.

---

## Verifica (comandi eseguibili)

### V1 — Lint + format
```bash
ruff check app/strategies/sentiment.py app/strategies/event_driven.py \
           app/strategies/knowledge_driven.py app/strategies/resolution.py \
           tests/test_strategies/
ruff format --check app/strategies/sentiment.py app/strategies/event_driven.py \
                    app/strategies/knowledge_driven.py app/strategies/resolution.py \
                    tests/test_strategies/
```

### V2 — Type check
```bash
mypy --strict app/strategies/sentiment.py app/strategies/event_driven.py \
              app/strategies/knowledge_driven.py app/strategies/resolution.py
```

### V3 — Test mirati
```bash
pytest tests/test_strategies/test_sentiment.py \
       tests/test_strategies/test_event_driven.py \
       tests/test_strategies/test_knowledge_driven.py \
       tests/test_strategies/test_resolution.py -v
```

### V4 — Test full suite (regressione)
```bash
pytest tests/ -x --ff
```

### V5 — Sanity grep post-modifica (R2-02 narrowed scope)
```bash
# Strategie in scope: 0 occorrenze attese
rg "SignalType\.SELL" app/strategies/sentiment.py \
                      app/strategies/event_driven.py \
                      app/strategies/knowledge_driven.py \
                      app/strategies/resolution.py
# Atteso: 0

# Restanti strategie: occorrenze legittime (arbitrage SELL strategici)
rg "SignalType\.SELL" app/strategies/arbitrage.py
# Atteso: 2 occorrenze (linee 141, 152) — sell-both arbitrage leg

# Helper rinominati: no caller rotti
rg "_resolve_signal_type" tests/  # atteso: 0
rg "_resolve_target_outcome" tests/  # atteso: 0 (helper privato)
rg "_pick_token" tests/  # atteso: 0 (helper privato)

# Integration tests: nessuna assertion SELL su strategy entry signals
rg "SignalType\.SELL" tests/test_execution/ tests/test_integration/
# Atteso: 0
```

### V6 — Done conditions
- [ ] V1 verde (lint + format)
- [ ] V2 verde (mypy strict, 0 errors)
- [ ] V3 verde — 4 file test
  - +6 nuovi test in `test_sentiment.py` (skip-no-missing, skip-empty-token, multi-outcome, whitespace, market_price=NO_price, sign convention)
  - +3 nuovi test in `test_event_driven.py` (skip-no-missing, skip-empty-token, market_price=NO_price)
  - +3 nuovi test in `test_knowledge_driven.py` (skip-no-missing, skip-empty-token, market_price=NO_price)
  - +1 nuovo test in `test_resolution.py` (skip-no-missing) + 2 rename con assertion strengthened
- [ ] V4 verde (full suite, no regressions)
- [ ] V5 grep risultati allineati
- [ ] Step 9 lesson aggiunta a `.claude/tasks/lessons.md`
- [ ] Step 10 follow-up tracciati in `.claude/tasks/todo.md` (R2-04, R2-07, cross-ref group-refactor)

---

## Assunzioni residue (post-Round 4)

1. `SignalType.SELL` resta nell'enum (exits via `position_monitor` + arbitrage strategico).
2. `engine.py` invariato (mapping BUY→BUY).
3. **Q2=B confermato**: `market_price = 1.0 - valuation.market_price` per BUY-NO (allineato a NO book price). `value_edge.py:97` ha bug analogo → R2-04 follow-up.
4. **Q1=A confermato**: `resolution.py` incluso in scope.
5. Outcome name matching: `o.outcome.strip().lower() == "yes"|"no"` (R2-11 strip aggiunto, consistency cross-strategie).
6. Mercati binari: niente filter centralizzato verificato; defensive return None se outcome name non trova match.
7. Test rinominati restano nei rispettivi file (no relocation).
8. `ruff` line-length=100, `mypy --strict` rispettati.
9. `_pick_token` cambiamento di firma è breaking ma interno (helper privato, no test diretto: verificato).
10. `signal.knowledge_sources` invariato per ogni strategia.
11. Reasoning string invariato (R2-14 dropped — no scope creep).
12. Sign di `edge_amount` agnostico downstream (verificato in A4 post-R2-03: `engine.py:255`, `engine.py:271`, `risk/manager.py:202` usano `abs()`). Plan adotta segno raw per consistency con `value_edge.py:98`.

---

## Ambiguità — TUTTE RISOLTE

| ID | Stato |
|----|-------|
| A1 / Q2 — `market_price` per BUY NO | **RISOLTA Q2=B** — `1.0 - valuation.market_price` |
| A2 — `market.no_token_id` non esiste | RISOLTA — name-based pattern `.strip().lower()` |
| A3 — Fallback `outcomes[0]` | RISOLTA — rimosso, return `None` |
| A4 — Segno `edge_amount` BUY NO | RISOLTA post-R2-03 — agnostico downstream, plan segna raw value |
| A5 — Helper estratto in event_driven | INVARIATA — logica inline mantenuta out-of-scope |
| A6 — `combined_edge == 0` | RISOLTA via R2-16 — `if/elif/else` defensive |
| A7 — Cross-token same-market dedup (R2-07) | FUORI SCOPE — tracked R2-07 follow-up |
| A8 — Multi-outcome markets (R2-05) | DOCUMENTATA — test 5.4 lock comportamento |
| Q1 — Include `resolution.py`? | **RISOLTA Q1=A** — incluso |

---

## Note implementative

### Order of execution
- Step 1, 2, 3, 4 sono indipendenti (file diversi). Parallelizzabili in 4 subagenti distinti.
- Step 5, 6, 7, 8 dipendono dai rispettivi file di produzione modificati.
- Step 9 e 10 alla fine, dopo verifica V1-V5.

### Commit organization (R2-22)

**Raccomandato**: **single atomic commit** con tutti i 4 strategie + tests. Razionale: bug semantico unico, atomic revert se issue. Bisectability garantita perché il commit "abbraccia" l'intera correzione.

Commit message proposto:
```
fix(strategies): emit BUY on NO token instead of SELL for negative edge

Sentiment, event_driven, knowledge_driven, resolution emettevano
SignalType.SELL su NO token per esprimere "buy NO" — silently invalid in
shadow/live perché engine.py:312 mappa SELL→OrderSide.SELL su quel token.
Fix: emette BUY su NO token con market_price = 1.0 - valuation.market_price
(NO book price, allineato al position-sizing downstream).

Pattern di riferimento: app/strategies/value_edge.py:52-65 (caveat: linea 97
ha lo stesso latent market_price bug, tracciato come R2-04).

Adds test coverage:
- skip when NO outcome missing
- skip when token_id empty
- whitespace-tolerant outcome name matching
- sign convention lock per edge_amount
- market_price == NO_price assertion (Q2=B)

Tracks follow-ups in .claude/tasks/todo.md (R2-04, R2-07).
Cross-ref: .claude/plan-hardened/group-refactor/PLAN.md (architectural,
gates on this fix being merged).
```

### Risk assessment

**BASSO**. Cambiamenti localizzati (4 file prod, 4 file test). Pattern di riferimento consolidato (value_edge.py). Test esistenti coprono i casi principali. Test nuovi lockano comportamento safety-by-construction. Q2=B introduce divergenza temporanea da `value_edge.py:97` ma il follow-up R2-04 chiude il gap.

### Test budget

~50-65 min totali:
- Implementazione 4 strategie: ~30 min
- Test rewrite + ~13 nuovi test: ~25 min
- Lint, mypy, run test, fix iterativo: ~15 min
