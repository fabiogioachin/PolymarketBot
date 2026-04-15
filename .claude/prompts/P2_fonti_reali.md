# P2 -- Fonti dati reali: WS orderbook, GDELT tuning, KG pattern injection

## Obiettivo

Collegare il bot a fonti dati reali: orderbook live via WebSocket, GDELT con
rate limiting corretto, e pattern KG dal vault Obsidian iniettati nel tick cycle.

Prerequisito: P1 completato (bot operativo in dry_run con dati sintetici).

## Contesto

Il bot gira in `dry_run`. I segnali del Value Assessment Engine (`app/valuation/engine.py`)
accettano gia `pattern_kg_signal`, `event_signal`, `cross_platform_signal` come kwargs
opzionali in `assess()`, passati via `assess_batch(external_signals=...)`.

Il tick cycle in `ExecutionEngine.tick()` (riga ~111-118 di `app/execution/engine.py`)
costruisce `external_signals: dict[str, dict[str, float | None]]` e lo popola con:
- `event_signal` -- da `IntelligenceOrchestrator.get_event_signal()` (gia funzionante)
- `cross_platform_signal` -- da `ManifoldService` (gia funzionante, disabilitato di default)

Mancano: `pattern_kg_signal` (da KnowledgeService) e microstructure dai dati orderbook reali.

### File coinvolti (scope esclusivo)

**Da modificare:**
- `app/execution/engine.py` (2 aggiunte: WS background task + pattern KG injection)
- `app/clients/gdelt_client.py` (rate limiting piu conservativo)
- `app/services/gdelt_service.py` (delay inter-query + poll interval)
- `app/core/dependencies.py` (wiring KnowledgeService nell'engine)
- `config/config.yaml` (abilitare GDELT, ajustare poll_interval)

**Da eseguire (non modificare):**
- `scripts/seed_patterns.py` (gia esistente, 28 pattern, 6 domini)

**Da NON toccare:**
- `app/valuation/engine.py` -- il VAE accetta gia tutti i segnali
- `app/clients/polymarket_ws.py` -- il WS client e completo, non serve modificarlo
- `app/knowledge/obsidian_bridge.py` -- il bridge e completo
- `app/services/knowledge_service.py` -- il servizio e completo

---

## Task 1: WebSocket orderbook come background task

### Problema

`PolymarketWsClient.listen()` (in `app/clients/polymarket_ws.py`) e un `AsyncIterator`
che blocca con `async for msg in self._ws`. Non puo girare nel tick cycle sincrono.

### Soluzione: background asyncio.Task

Aggiungere a `ExecutionEngine` un background task che:
1. Connette il WS client
2. Si sottoscrive ai token_id dei mercati attivi
3. Aggiorna un `dict[str, OrderBook]` in-memory ad ogni messaggio
4. Il tick cycle legge lo snapshot dal dict (non blocca)

### Implementazione in `app/execution/engine.py`

#### Nuovi attributi in `__init__`:

```python
from app.clients.polymarket_ws import PolymarketWsClient
from app.models.market import OrderBook, OrderBookLevel

# In __init__:
self._ws_client = PolymarketWsClient()
self._orderbook_cache: dict[str, OrderBook] = {}
self._ws_task: asyncio.Task[None] | None = None
```

#### Nuovo metodo `_ws_listener_loop`:

```python
async def _ws_listener_loop(self) -> None:
    """Background loop: maintain WS connection and update orderbook cache."""
    try:
        await self._ws_client.connect()
    except Exception as exc:
        logger.warning("ws_connect_failed_background", error=str(exc))
        return

    try:
        async for msg in self._ws_client.listen():
            self._process_ws_message(msg)
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.warning("ws_listener_error", error=str(exc))
    finally:
        await self._ws_client.disconnect()
```

#### Nuovo metodo `_process_ws_message`:

Parsing dei messaggi WS. Il formato Polymarket WS per orderbook updates e:
```json
{
  "asset_id": "<token_id>",
  "market": "<condition_id>",
  "bids": [{"price": "0.65", "size": "100.5"}, ...],
  "asks": [{"price": "0.67", "size": "50.0"}, ...],
  "timestamp": "1234567890"
}
```

```python
def _process_ws_message(self, msg: dict[str, Any]) -> None:
    """Parse WS message and update orderbook cache."""
    asset_id = msg.get("asset_id")
    if not asset_id:
        return

    bids_raw = msg.get("bids", [])
    asks_raw = msg.get("asks", [])

    bids = [OrderBookLevel(price=float(b["price"]), size=float(b["size"])) for b in bids_raw]
    asks = [OrderBookLevel(price=float(a["price"]), size=float(a["size"])) for a in asks_raw]

    spread = (asks[0].price - bids[0].price) if bids and asks else 0.0
    midpoint = (bids[0].price + asks[0].price) / 2 if bids and asks else 0.0

    market_id = self._token_to_market.get(asset_id, msg.get("market", ""))

    self._orderbook_cache[asset_id] = OrderBook(
        market_id=market_id,
        asset_id=asset_id,
        bids=bids,
        asks=asks,
        spread=round(spread, 4),
        midpoint=round(midpoint, 4),
    )
```

#### Avvio/stop del background task

Nel metodo `run()`, avviare il WS task PRIMA del loop principale:

```python
async def run(self, interval_seconds: int = 60) -> None:
    self._running = True
    # Start WS background listener
    self._ws_task = asyncio.create_task(self._ws_listener_loop())
    logger.info("engine_started", interval=interval_seconds)
    while self._running:
        # ... (tick loop invariato)
    # Cleanup
    if self._ws_task and not self._ws_task.done():
        self._ws_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._ws_task
```

Aggiungere `import contextlib` se non gia presente.

#### Sottoscrizione ai mercati

Dopo aver ottenuto i mercati nel tick (riga ~99-104 di `tick()`), aggiungere
la sottoscrizione ai nuovi asset_id non ancora sottoscritti:

```python
# Dopo: market_by_id = {m.id: m for m in markets}
# Subscribe nuovi asset_id al WS
if self._ws_client.is_connected:
    new_asset_ids = []
    for m in markets:
        for outcome in m.outcomes:
            if outcome.token_id and outcome.token_id not in self._ws_client._subscribed_assets:
                new_asset_ids.append(outcome.token_id)
                self._token_to_market[outcome.token_id] = m.id
    if new_asset_ids:
        try:
            await self._ws_client.subscribe(new_asset_ids)
        except Exception as exc:
            logger.warning("ws_subscribe_failed", error=str(exc))
```

#### Uso dell'orderbook nella valutazione

Nel blocco di `assess_batch` (riga ~122-125), passare l'orderbook data come
segnale esterno `orderbook_data`:

```python
# Prima di assess_batch, costruire orderbook_data per-market
for m in markets:
    for outcome in m.outcomes:
        ob = self._orderbook_cache.get(outcome.token_id)
        if ob:
            external_signals.setdefault(m.id, {})["orderbook_data"] = ob
            break  # un orderbook per market (YES outcome)
```

**Nota**: `assess()` accetta `orderbook_data: OrderBook | None` come kwarg diretto.
Quando `assess_batch` fa `**extra` spread, la chiave `orderbook_data` nel dict
viene passata correttamente come keyword argument.

---

## Task 2: GDELT rate limiting conservativo

### Problema attuale

`GdeltClient` (in `app/clients/gdelt_client.py`) ha `semaphore = 5` (5 richieste
concorrenti). Ma `_check_query()` in `GdeltService` fa 3 chiamate API per query
(article_search + timeline_volume + timeline_tone). Con 5 query tematiche, sono
15 chiamate in burst. GDELT free tier non tollera questo volume e risponde 429.

### Fix in `app/clients/gdelt_client.py`

Cambiare il default di `rate_limit` da 5 a 1:

```python
def __init__(
    self, rate_limit: int = 1, max_retries: int = 2, backoff: float = 2.0
) -> None:
```

Questo serializza le chiamate: una alla volta. Con retry + backoff gia presente,
i 429 residui vengono gestiti.

### Fix in `app/services/gdelt_service.py`

In `poll_watchlist()`, aggiungere un delay tra le query per evitare burst:

```python
async def poll_watchlist(self) -> list[GdeltEvent]:
    events: list[GdeltEvent] = []
    all_queries = self._build_queries()

    for query in all_queries:
        try:
            event = await self._check_query(query)
            if event:
                events.append(event)
        except Exception:
            logger.warning("gdelt_query_failed", query=query)
        # Delay tra query per rispettare rate limits GDELT free tier
        await asyncio.sleep(3)

    # ... resto invariato
```

Aggiungere `import asyncio` in cima al file se non presente.

### Fix in `config/config.yaml`

Aumentare `poll_interval_minutes` da 15 a 30:

```yaml
intelligence:
  gdelt:
    enabled: true          # abilitare per P2
    poll_interval_minutes: 30  # era 15, troppo aggressivo per free tier
```

Con 5 query x 3 API call x ~4 sec/call + 3 sec delay = ~35 sec per ciclo.
Un poll ogni 30 minuti e sostenibile senza 429.

---

## Task 3: Seed pattern nel vault Obsidian

### Prerequisito

- Obsidian deve essere aperto con il vault `_ObsidianKnowledge`
- Il plugin "Local REST API" deve essere attivo (porta 27123)

### Esecuzione

```bash
python scripts/seed_patterns.py
```

Questo script (gia esistente in `scripts/seed_patterns.py`) usa
`get_seed_patterns()` da `app/knowledge/pattern_templates.py` (28 pattern)
e `render_pattern_markdown()` per generare file .md con frontmatter YAML.

Il frontmatter generato da `render_pattern_markdown()` ha questo formato:
```yaml
---
type: recurring          # pattern_type
domain: geopolitics
confidence: 0.65
last_triggered: null
season: ""
actors: "USA, CHN"
trigger_condition: "GDELT: high volume..."
expected_outcome: "Markets related to..."
historical_accuracy: 0.62
status: active
tags:
  - trade
  - tariff
---
```

I file vengono scritti in:
`<vault>/Projects/PolymarketBot/patterns/<Domain>/<Pattern_Name>.md`

I 6 domini sono: Geopolitics (6), Politics (5), Economics (5), Crypto (4),
Sports (5), Cross_platform (3).

### NON fare

- Non creare pattern custom. I 28 seed sono gia sufficienti.
- Non modificare `pattern_templates.py` ne `seed_patterns.py`.
- Non modificare il formato frontmatter -- `ObsidianBridge.read_patterns()`
  legge esattamente questo formato.

### Verifica

Dopo l'esecuzione, verificare con MCP obsidian:
- La cartella `Projects/PolymarketBot/patterns/` contiene 6 sottocartelle
- Almeno 25+ file .md sono stati creati

### Config

Abilitare Obsidian in `config/config.yaml`:

```yaml
intelligence:
  obsidian:
    enabled: true
```

---

## Task 4: Pattern KG injection nel tick cycle

### Problema

Il `KnowledgeService.build_knowledge_context()` produce un `KnowledgeContext`
con `composite_signal: float` (0-1, media pesata dei pattern matchati).
Ma nessun codice nel tick cycle lo chiama ne inietta il risultato come
`pattern_kg_signal` in `external_signals`.

Il VAE (`app/valuation/engine.py`, riga 49) accetta gia `pattern_kg_signal: float | None`
come kwarg di `assess()`, e `assess_batch` lo passa via `**extra` spread.

### Soluzione

Aggiungere un nuovo metodo in `ExecutionEngine` e chiamarlo nel tick.

#### Nuovo metodo `_fetch_kg_signals`:

```python
async def _fetch_kg_signals(
    self,
    markets: list[Market],
    external_signals: dict[str, dict[str, float | None]],
) -> None:
    """Fetch pattern KG signals from Obsidian vault via KnowledgeService."""
    if self._knowledge_service is None:
        return
    for market in markets:
        try:
            ctx = await self._knowledge_service.build_knowledge_context(
                domain=market.category.value,
                event_text=market.question,
                keywords=market.tags[:5] if market.tags else None,
            )
            if ctx.composite_signal > 0:
                external_signals.setdefault(market.id, {})[
                    "pattern_kg_signal"
                ] = ctx.composite_signal
        except Exception as exc:
            logger.warning(
                "kg_signal_failed",
                market_id=market.id,
                error=str(exc),
            )
```

#### Modifiche a `__init__`:

Aggiungere parametro `knowledge_service`:

```python
def __init__(
    self,
    executor: OrderExecutor,
    risk_manager: RiskManager,
    circuit_breaker: CircuitBreaker,
    strategy_registry: StrategyRegistry,
    value_engine: Any = None,
    market_service: Any = None,
    trade_store: TradeStore | None = None,
    manifold_service: Any = None,
    intelligence_orchestrator: Any = None,
    knowledge_service: Any = None,        # <-- NUOVO
) -> None:
    # ... esistente ...
    self._knowledge_service = knowledge_service  # <-- NUOVO
```

#### Chiamata nel tick cycle

In `tick()`, dopo il blocco `_fetch_intelligence_signals` e prima di
`_fetch_manifold_signals` (riga ~115), aggiungere:

```python
# 2d. Fetch KG pattern signals from Obsidian
await self._fetch_kg_signals(markets, external_signals)
```

### Wiring in `dependencies.py`

In `get_execution_engine()`, creare e passare il `KnowledgeService`:

```python
async def get_execution_engine() -> ExecutionEngine:
    global _execution_engine
    if _execution_engine is None:
        # ... imports e setup esistenti ...

        # Knowledge service (pattern KG from Obsidian)
        knowledge_service = None
        if app_config.intelligence.obsidian.enabled:
            from app.services.knowledge_service import KnowledgeService
            knowledge_service = KnowledgeService()

        _execution_engine = ExecutionEngine(
            executor=executor,
            risk_manager=get_risk_manager(),
            circuit_breaker=get_circuit_breaker(),
            strategy_registry=get_strategy_registry(),
            value_engine=value_engine,
            market_service=get_market_service(),
            trade_store=store,
            manifold_service=manifold_service,
            intelligence_orchestrator=get_intelligence_orchestrator(),
            knowledge_service=knowledge_service,      # <-- NUOVO
        )
        await _execution_engine.restore_from_store()
    return _execution_engine
```

---

## Task 5: Config finale e verifica

### Aggiornare `config/config.yaml`

Stato finale della sezione intelligence:

```yaml
intelligence:
  gdelt:
    enabled: true
    poll_interval_minutes: 30
    watchlist:
      themes:
        - ELECTION
        - ECON_INFLATION
        - ECON_INTEREST_RATE
        - CLIMATE_CHANGE
        - WB_CONFLICT
      actors:
        - USA
        - RUS
        - CHN
        - EU
      countries:
        - US
        - RU
        - CN
        - UA
        - IL
  rss:
    enabled: true
    poll_interval_minutes: 30
    feeds:
      - name: BBC World
        url: https://feeds.bbci.co.uk/news/world/rss.xml
      - name: Al Jazeera
        url: https://www.aljazeera.com/xml/rss/all.xml
      - name: NPR News
        url: https://feeds.npr.org/1001/rss.xml
      - name: The Guardian World
        url: https://www.theguardian.com/world/rss
  obsidian:
    vault_path: "C:/Users/fgioa/OneDrive - SYNESIS CONSORTIUM/Desktop/PRO/_ObsidianKnowledge"
    patterns_path: Projects/PolymarketBot/patterns
    enabled: true
  manifold:
    enabled: false
```

### Verifica end-to-end

```bash
# 1. Seed patterns nel vault
python scripts/seed_patterns.py

# 2. Avviare il bot con fonti reali
python -m app.main

# 3. Verificare nel log (logs/bot.log):
#    - "intelligence_tick" appare (GDELT + RSS funzionano)
#    - "gdelt_poll_complete" con queries=5, nessun errore 429
#    - "patterns_loaded" appare (KG patterns caricati)
#    - "ws_connected" appare (se Polymarket WS raggiungibile)
#    - "tick_completed" mostra markets_assessed > 0
#    - Nessun traceback/exception critica

# 4. Se GDELT da 429: verificare che il retry + backoff gestisca senza crash
#    Il log dovra mostrare "gdelt_retry" e poi successo

# 5. Se WS non si connette (geoblocking): verificare graceful degradation
#    Il log dovra mostrare "ws_connect_failed_background" e il tick continua senza orderbook
```

### Criteri di successo

- [ ] WS background task parte e non blocca il tick cycle
- [ ] Se WS non disponibile, il tick continua senza crash
- [ ] GDELT non produce 429 con il nuovo rate limiting (semaphore=1, delay=3s, poll=30min)
- [ ] Pattern KG vengono caricati dal vault e `pattern_kg_signal` appare in `external_signals`
- [ ] Il VAE riceve `pattern_kg_signal` e lo usa nel calcolo fair value (visibile nel log `market_assessed`)
- [ ] RSS feed vengono fetchati senza errori
- [ ] Nessuna regressione: i test esistenti continuano a passare

---

## Skill da consultare

- `~/.claude/skills/vae-signal/SKILL.md` -- come i segnali esterni fluiscono nel VAE
- `~/.claude/skills/intelligence-source/SKILL.md` -- pattern per aggiungere fonti intelligence
- `~/.claude/skills/execution-modes/SKILL.md` -- tick cycle, come external_signals viene costruito
- `~/.claude/skills/config-system/SKILL.md` -- dual config env+YAML

## Note per l'agente

- `PolymarketWsClient` e GIA completo e testato. Non modificare `app/clients/polymarket_ws.py`.
- `KnowledgeService` e GIA completo. Non modificare `app/services/knowledge_service.py`.
- `ObsidianBridge` e GIA completo. Non modificare `app/knowledge/obsidian_bridge.py`.
- L'unico file con modifiche significative e `app/execution/engine.py` (WS task + KG injection).
- I test in `tests/test_execution/test_engine.py` costruiscono `ExecutionEngine` direttamente:
  aggiungere `knowledge_service=None` come default nel costruttore per non rompere i test esistenti.
- Non aggiungere dipendenze non gia in requirements.txt.
- Il WS puo fallire per geoblocking (Italia). Il fallimento deve essere silenzioso e non
  impedire il funzionamento del bot.
