# BROWSER-TEST-REPORT

Data: 2026-04-15
Modalita bot: dry_run
App URL: http://localhost:8000 (API) / http://localhost:5174 (frontend)
Condizioni testate: cold start + running bot (entrambe)

---

## Sintesi

| Area | Cold Start | Running Bot | Note |
|------|------------|-------------|------|
| App health | OK | OK | status:"ok", version:"0.1.0" |
| Intelligence | Vuota (API: 0 anomalie) | Parziale (API: 1 entry, 0 actual) | /news 404, tab senza chiamate API |
| Knowledge | Vuota | Vuota | strategies=[], risks=[] dopo 1454 tick — BUG |
| Prezzi Polymarket | Reali | Reali | sum Yes+No=1.000, IDs reali, fee_rate=0 |
| VAE edge | Non verificabile (segnali non esposti) | Non verificabile | rule_analysis unico segnale in trade log |
| Trade simulate | 50 trade open (rule_edge) | 52 trade (+2 tick) | horizon=null, order_price mancante |
| Rule parser | Funzionante | Funzionante | risk_level invece di clarity_score |
| Circuit breaker | Inattivo | Inattivo | daily_pnl=0, no realized losses |
| Warm-up vs Bug | tick_count=1452 → dati devono esistere | Bug confermato: KB vuoto | knowledge/strategies,risks sempre [] |

---

## STEP 0 — Prerequisiti

### Stato iniziale (cold start)
- `running`: false
- `mode`: dry_run
- `tick_count`: 1452
- `started_at`: null
- `circuit_breaker_tripped`: false
- `positions`: 5
- `daily_pnl`: 0.0

### Condizioni di test
`running: false` → test eseguito in **cold start**. Poiché `tick_count=1452`, il DB contiene
dati pre-esistenti (non è primo avvio assoluto). Applicate le regole "avvii successivi" della
tabella warm-up. Successivamente avviato il bot (`POST /bot/start`) per testare la condizione
"running bot" (tick_count salito a 1453→1454).

---

## STEP 1 — Health check e config

### 1a Health
```json
{"status":"ok","version":"0.1.0","app":"polymarket-bot"}
```
**Esito**: OK

### 1b Config attivo (valori per validazioni dinamiche)
```json
{
  "strategies.enabled": ["value_edge","arbitrage","rule_edge","event_driven","resolution"],
  "risk.max_exposure_pct": 50.0,
  "risk.max_positions": 25,
  "risk.fixed_fraction_pct": 5.0,
  "risk.daily_loss_limit_eur": "15%",
  "valuation.weights": {
    "base_rate": 0.15, "rule_analysis": 0.15, "microstructure": 0.15,
    "cross_market": 0.10, "event_signal": 0.15, "pattern_kg": 0.10,
    "temporal": 0.05, "crowd_calibration": 0.05, "cross_platform": 0.10
  },
  "valuation.thresholds": {
    "min_edge": 0.05, "min_edge_short": 0.03, "min_edge_medium": 0.05,
    "min_edge_long": 0.10, "min_edge_super_long": 0.15, "min_confidence": 0.30
  },
  "intelligence.gdelt_enabled": true,
  "intelligence.rss_enabled": true,
  "llm.enabled": false
}
```

---

## STEP 2 — Dashboard screenshot

**URL**: http://localhost:5174/

**Tab visibili**: Trading ✓, Config ✓, Intelligence ✓, Knowledge ✓

**Cold start (running=false, tick_count=1452)**:
- Header: "PolymarketBot — Stopped (dry run) — Live Updated 10:19:13 AM"
- TOTAL TRADES: 50 | DAILY P&L: +0.00 EUR | WIN RATE: 100.00% | EQUITY: 151.59 EUR
- OPEN POSITIONS: 5 | CIRCUIT BREAKER: Normal | TICK COUNT: 1452
- Posizioni aperte: 5 mercati (tutti rule_edge BUY Yes)
- Recent trades: 4 visibili (tutti "Will Claude 5 released by April 30, 2026?", rule_edge)

**Running bot (tick_count=1454)**:
- Header: "Running (dry run) — Live Updated 10:27:02 AM"
- TOTAL TRADES: 52 | EQUITY: 143.49 EUR | Unrealized P&L: -8.0998 EUR
- Il P&L unrealizzato è visibile in rosso per 4/5 posizioni
- Posizione Claude 5 (1363116): +0.6780 (+12.2%) — unica in gain

---

## STEP 3 — Intelligence tab

### 3a Visivo
**Cold start e running bot**: tab mostra 3 panel tutti in **empty state**:
- EVENT TIMELINE: "Event timeline will appear here once the intelligence pipeline is active."
- GDELT ANOMALIES: "GDELT anomaly detection results will appear here."
- RSS FEED ACTIVITY: "RSS feed headlines and parsed signals will appear here."

Il tab **non chiama mai nessuna API** al click (confermato in STEP 10). La scheda non è
integrata con gli endpoint intelligence nel frontend.

### 3b Anomalie
- **Cold start**: `[]` (0 anomalie)
- **Running bot (dopo 1 tick)**: 1 entry, ma `total_anomalies: 0, events: [], news_items: []`
  ```json
  [{"detected_at":"2026-04-15T08:26:23.391627Z","events":[],"news_items":[],"total_anomalies":0}]
  ```
- **Valutazione**: Il record anomalie esiste dopo il tick (GDELT ha eseguito), ma non ha
  rilevato eventi rilevanti. Comportamento corretto per warm-up.

### 3c News
**Endpoint `/api/v1/intelligence/news`**: **404 Not Found** — l'endpoint non esiste nel router.
Non presente in OpenAPI spec. Documentato come bug di spec (o endpoint rimosso/rinominato).

### 3d Watchlist (verifica dinamica)
```json
{
  "themes": ["ELECTION","ECON_INFLATION","WB_CONFLICT"],
  "actors": ["USA","RUS","CHN","EU"],
  "countries": ["US","RU","CN","UA","IL"]
}
```
- Temi restituiti: ELECTION, ECON_INFLATION, WB_CONFLICT (3)
- Attori restituiti: USA, RUS, CHN, EU (4)
- Paesi restituiti: US, RU, CN, UA, IL (5)
- `gdelt_enabled` in config: **true**
- Coerenza config ↔ watchlist: **OK** — `gdelt_enabled: true` e watchlist ha 3 temi ≥ 1 ✓

---

## STEP 4 — Knowledge tab

### 4a Visivo
**Cold start e running bot**: tab mostra 3 panel tutti in **empty state**:
- RISK PROFILES: "Market risk profiles from the Knowledge Base will appear here."
- PATTERN LIBRARY: "Historical patterns and their hit rates will appear here."
- OBSIDIAN KNOWLEDGE GRAPH: "Connected KG nodes from Obsidian will appear here."

Il tab **non chiama mai nessuna API** al click (confermato in STEP 10).

### 4b Strategies
- **Cold start**: `[]`
- **Running bot (tick_count=1454)**: `[]`
- **Valutazione**: **BUG** — con tick_count=1452 all'avvio (DB pre-esistente), `knowledge/strategies`
  dovrebbe restituire dati. Nessuna strategia mappata dopo 1454 tick = bug di persistenza o restore.

### 4c Risks
- **Cold start**: `[]`
- **Running bot**: `[]`
- Distribuzione LOW/MEDIUM/HIGH: nessuna (array vuoto)
- **Valutazione**: **BUG** — stesso problema di knowledge/strategies.

### 4d Debug endpoint
**Endpoint `/api/v1/knowledge/debug`**: **404 Not Found** — non presente nel router.
Endpoints knowledge disponibili: `/knowledge/strategies`, `/knowledge/risks`,
`/knowledge/market/{market_id}`, `/knowledge/market/{market_id}/notes`.

---

## STEP 5 — Mercati reali

| ID | Question (troncata) | Yes | No | Sum | Horizon | End Date | fee_rate |
|----|---------------------|-----|----|-----|---------|----------|---------|
| 1363116 | Will Claude 5 be released by April 30, 2026? | 0.032 | 0.968 | 1.000 | long | 2026-04-30 | 0 |
| 1985979 | Will highest temp in Munich be 17°C on April 16? | 0.345 | 0.655 | 1.000 | short | 2026-04-16 | 0 |
| 1965359 | Will highest temp in Ankara be 13°C or below... | 0.001 | 0.999 | 1.000 | short | 2026-04-15 | 0 |
| 1960304 | Parks vs. Akugue: Set 1 Games O/U 8.5 | N/D | N/D | N/D | medium | 2026-04-21 | 0 |

**ID check**: Nessun ID inizia con "demo-" → **PREZZI REALI da API Gamma Polymarket** ✓

**Criteri validazione prezzi**:
- Sum Yes+No = 1.000 su tutti i mercati verificabili ✓
- Prezzi variano tra mercati (0.001, 0.032, 0.345) → non mock ✓
- fee_rate = 0 su tutti (Polymarket 0% geo-fee) ✓
- end_date presente su tutti e 4 i mercati (non null)

---

## STEP 6 — Verifica edge VAE (calcolo manuale)

### Mercato 1: 1363116 — "Will Claude 5 be released by April 30, 2026?"
- `market_price` al trade time: 0.029 (da trade log "@ 0.029", fill=0.0285)
- `market_price` attuale da API Gamma: 0.032
- Prezzi reali? **Sì** — sum=1.000, ID reale, varia nel tempo (0.029→0.032)
- Segnali disponibili nel trade log:
  - `rule_analysis` = 0.417 (da reasoning "Original confidence: 0.417")
  - Altri segnali (base_rate, event_signal, crowd_calibration, microstructure...): **non esposti dall'API**
- Pesi rinormalizzati (solo rule_analysis): weight_total = 0.1500
- Calcolo manuale (solo rule_analysis attivo):
  - fair_value = 0.4170
  - edge = 0.3880
  - temporal_factor = 0.7500 (stima: 15 giorni rimasti su 30, decay lineare)
  - scaled_edge = 0.2910
  - fee_adjusted_edge = 0.2910 (fee_rate=0)
- `edge_at_entry` osservato nel sistema: 0.0325
- **Corrispondenza**: NO — delta = 0.2585
- **Spiegazione divergenza**: Il sistema usa più segnali VAE (almeno base_rate + event_signal +
  crowd_calibration) che non sono esposti nel trade log. Con più segnali attivi con valori vicini
  a market_price, il fair_value scende significativamente. La verifica completa richiede accesso
  ai valori dei singoli segnali al momento del trade, che non sono persistiti nel log.

### Mercato 2: 1985979 — "Munich 17°C on April 16?"
- `market_price` (Yes): 0.345
- Prezzi reali? **Sì** — sum=1.000, ID reale
- Nessun trade in log per questo mercato → non usato dalla strategia rule_edge attiva
- Calcolo: non eseguibile (nessun dato di segnale disponibile per questo mercato)
- **Esito**: "Verifica formula senza riscontro dal sistema" — mercato non scambiato

---

## STEP 7 — Rule parser

### Mercato 1: 1363116
- `resolution_source`: "Ap" (Associated Press)
- `conditions`: 4 condizioni
  1. Risolve "Yes" se Claude 5 disponibile al pubblico entro April 30, 2026 11:59 PM ET
  2. Deve essere publicly accessible (beta aperta o waitlist aperta) — closed beta NON sufficiente
  3. Claude 5 = prodotto esplicitamente nominato Claude 5 (o successore di Claude 4)
  4. Fonte primaria: informazioni ufficiali Anthropic
- `deadline`: 2026-04-30T00:00:00Z ✓ (corrisponde a end_date del mercato)
- `risk_level`: "clear_rules" (nota: il campo si chiama `risk_level`, non `clarity_score`)
- `ambiguities`: [] (nessuna ambiguità rilevata)
- `edge_cases`: [] (nessun edge case)
- `raw_text`: presente (947 caratteri)
- Varianti numeriche: ✓ (Claude 5.0, Claude 4.5, Claude 4)
- Varianti temporali: ✓ (April 30, 2026, 11:59 PM ET)
- Varianti condizionali (OR/AND): ✓ (open beta OR rolling waitlist)

### Mercato 2: 1985979
- `resolution_source`: "Ap"
- `conditions`: 5 condizioni (temperatura °C Munich Airport, Wunderground, finalizzazione dati)
- `deadline`: 2026-04-16T12:00:00Z ✓
- `risk_level`: "clear_rules"
- `ambiguities`: []
- `edge_cases`: []
- Varianti numeriche: ✓ (17°C, gradi interi)
- Varianti temporali: ✓ (16 Apr '26, finalizzazione dati)

**Nota spec vs realtà**: Il campo `clarity_score` (0-1) non esiste nella risposta. Il parser
usa `risk_level` (enum: "clear_rules", "ambiguous", "complex") che è semanticamente equivalente
ma non produce un valore numerico continuo. Il valore 0.417 nel trade reasoning sembra essere
calcolato internamente dalla strategia, non esposto nell'endpoint `/rules`.

---

## STEP 8 — Trade simulate

### Trade log (cold start — 50 trade, tutti open BUY)
| Timestamp | Market ID | Type | Side | Price (fill) | Edge | Size EUR | Strategy |
|-----------|-----------|------|------|-------------|------|----------|----------|
| 08:26:23 | 1132827 | open | BUY | 0.0635 | 0.0383 | 1.04 | rule_edge |
| 08:26:23 | 645700 | open | BUY | 0.0008 | 0.0300 | 0.08 | rule_edge |
| 07:01:24 | 1363116 | open | BUY | 0.0285 | 0.0325 | 1.10 | rule_edge |
| 07:00:23 | 1363116 | open | BUY | 0.0285 | 0.0325 | 1.10 | rule_edge |
| ... (46 trade precedenti) | | | | | | | rule_edge |

**Osservazioni**:
- Unica strategia presente: `rule_edge` (49 open + 1 exit — strategia di uscita)
- Le strategie value_edge, arbitrage, event_driven, resolution **non hanno prodotto trade**
- Campo `horizon` (time_horizon): **null su tutti i trade** — non persistito nel log
- Campo `order_price`: **assente** dal trade log — verifica spread non diretta

### Spread check
- **New running-bot trades** (08:26:23):
  - Market 1132827: fill=0.0635, current_price=0.061 → fill > market_price ✓
  - Market 645700: fill=0.0008, current_price=0.0005 → fill > market_price ✓
- **Precedenti cold-start trades** (market 1363116): fill=0.0285 vs "@ 0.029" in dashboard
  → 0.0285 < 0.029 → spread apparentemente non applicato o applicato in modo inverso ⚠️
  (l'assenza di `order_price` nel log impedisce verifica definitiva)
- Quanti trade hanno spread correttamente applicato: 2/2 verificabili nei running-bot trades ✓

### Posizioni aperte (cold start)
| Market ID | Outcome | Cost Basis | Avg Price | Current Price | Unrealized P&L | Strategy |
|-----------|---------|------------|-----------|---------------|----------------|----------|
| 645700 | Yes | 0.08 EUR | 0.0008 | 0.0005 | 0 (-36%) | rule_edge |
| 1132827 | Yes | 1.14 EUR | 0.0695 | 0.063 | 0 (-8.3%) | rule_edge |
| 1940758 | Yes | 40.80 EUR | 0.0214 | 0.017 | 0 (-20.6%) | rule_edge |
| 1423698 | Yes | 0.39 EUR | 0.0008 | 0.0005 | 0 (-34.6%) | rule_edge |
| 1363116 | Yes | 5.56 EUR | 0.0285 | 0.0285 | 0 (+0%) | rule_edge |

**Nota**: unrealized_pnl = 0 nel cold start dall'API positions (prezzi non aggiornati).
Dopo il primo tick del running bot, unrealized P&L mostrato nella dashboard: -8.0998 EUR.

### Metriche aggregate (cold start → running bot)
| Metrica | Cold Start | Running Bot |
|---------|------------|-------------|
| equity | 151.59 EUR | 143.49 EUR |
| daily_pnl | 0.00 EUR | 0.00 EUR |
| win_rate | 100.00% | 100.00% |
| total_trades | 50 | 52 |
| open_positions | 5 | 5 |
| circuit_breaker.tripped | false | false |
| circuit_breaker.consecutive_losses | 0 | 0 |
| circuit_breaker.daily_drawdown_pct | 0 | 0 |

---

## STEP 9 — Bot status e circuit breaker

**Cold start**:
```json
{"running":false,"mode":"dry_run","tick_count":1452,"started_at":null,"positions":5,"daily_pnl":0.0,"circuit_breaker_tripped":false}
```

**Running bot**:
```json
{"running":true,"mode":"dry_run","tick_count":1454,"started_at":"2026-04-15T08:26:23.157859+00:00","positions":5,"daily_pnl":0,"circuit_breaker_tripped":false}
```

**Coerenza con STEP 8c**: ✓
- `circuit_breaker.tripped: false` ↔ `consecutive_losses=0, daily_drawdown_pct=0`
- Il circuit breaker è correttamente inattivo: nessun trade chiuso, win_rate=100%, daily_pnl=0
- L'unrealized P&L di -8.10 EUR (5.4% dell'equity) non triggera il CB (corretto: CB scatta
  su perdite realizzate o drawdown pari al 15% dell'equity ≈ 22.74 EUR)

---

## STEP 10 — Network requests dashboard

| Scheda | Endpoint chiamati | Status | Note |
|--------|-------------------|--------|------|
| (page load) | `/api/v1/dashboard/stream` | 200 | SSE stream, aperto al caricamento |
| Trading | nessuno (tab click) | — | Dati via SSE |
| Config | `/api/v1/dashboard/config` | 200 | Fetch on-demand al click ✓ |
| Intelligence | **nessuno** | — | **BUG: nessuna chiamata API al click** |
| Knowledge | **nessuno** | — | **BUG: nessuna chiamata API al click** |

**Architettura rilevata**: Il frontend è SSE-first. Al caricamento apre `dashboard/stream` e
rimane in ascolto. Config usa REST fetch on-demand. Intelligence e Knowledge **non hanno fetch
implementate nel JS** (`app.js`) — i panel mostrano sempre empty state indipendentemente dai dati
disponibili nell'API.

---

## Problemi rilevati

| # | Area | Problema | Gravità | Warm-up o Bug? | Note |
|---|------|----------|---------|----------------|------|
| 1 | Frontend | Intelligence tab: nessuna chiamata API al click | HIGH | Bug | `app.js` non ha fetch per `/intelligence/*` |
| 2 | Frontend | Knowledge tab: nessuna chiamata API al click | HIGH | Bug | `app.js` non ha fetch per `/knowledge/*` |
| 3 | Knowledge API | `knowledge/strategies` restituisce `[]` con tick_count=1454 | HIGH | Bug | DB pre-esistente, non warm-up |
| 4 | Knowledge API | `knowledge/risks` restituisce `[]` con tick_count=1454 | HIGH | Bug | Stessa causa di #3 |
| 5 | API | `/api/v1/intelligence/news` restituisce 404 | MEDIUM | Bug (endpoint mancante) | Non presente in OpenAPI spec |
| 6 | API | `/api/v1/knowledge/debug` restituisce 404 | MEDIUM | Bug (endpoint mancante) | Non presente in OpenAPI spec |
| 7 | Strategie | Solo `rule_edge` esegue trade su 5 strategie abilitate | MEDIUM | Da investigare | value_edge, arbitrage, event_driven, resolution: 0 trade |
| 8 | Trade log | Campo `horizon` null su tutti i trade | LOW | Bug | time_horizon non persistito nel TradeRecord |
| 9 | Trade log | Campo `order_price` assente | LOW | Design gap | Impedisce verifica diretta spread |
| 10 | Prezzi posizioni | unrealized_pnl=0 in cold start (non aggiornato) | LOW | Warm-up | Si aggiorna al primo tick running |
| 11 | VAE | Segnali non esposti nell'API — solo rule_analysis visibile via reasoning | LOW | Design | Verifica formula VAE non completamente verificabile dall'esterno |
| 12 | Intelligence anomalie | Record anomalia presente ma vuoto (total_anomalies=0) | INFO | Warm-up/normale | GDELT ha eseguito ma nessun evento rilevante |

---

## Conclusioni

### Edge: reale o simulato?
**Prezzi di mercato: REALI** — gli ID mercati sono IDs reali di Polymarket (non "demo-"),
i prezzi Yes+No sommano a 1.000, variano tra mercati e nel tempo (1363116: 0.029→0.032 in
poche ore). L'API Gamma di Polymarket è raggiungibile e restituisce prezzi live.

**Segnali VAE: PARZIALI** — solo rule_analysis (0.15) è verificabile dal trade reasoning.
Microstructure (WS geobloccato), pattern_kg (Obsidian non seeded), cross_platform (Manifold
disabilitato), cross_market (correlazioni non disponibili) sono quasi certamente None, il che
significa ~50-60% del peso teorico è rinormalizzato. Il calcolo manuale con solo rule_analysis
produce edge=0.291 vs 0.0325 osservato: la divergenza conferma che altri segnali sono attivi
(base_rate, event_signal, crowd_calibration) ma non esposti nell'API.

### Intelligence: popolamento corretto?
**Parzialmente**. La watchlist è corretta e coerente con la config (gdelt_enabled=true → temi
presenti ✓). L'anomaly detection GDELT ha eseguito correttamente (1 record dopo 1 tick). Il
problema principale è il **frontend**: le schede Intelligence e Knowledge non chiamano mai le
API di backend, quindi i panel rimangono sempre in empty state. I dati esistono nell'API ma
non vengono mai consumati dal frontend.

### Trade: coerenti con mercato reale?
**Parzialmente**. I prezzi di entrata sono reali (da API Gamma). Il circuit breaker funziona
correttamente (non triggera su sole perdite unrealizzate). Win_rate=100% con 0 close è
matematicamente corretto. Problemi:
- Solo `rule_edge` produce segnali (4 strategie abilitate non eseguono mai)
- Campo `horizon` null impedisce verifica budget pools per orizzonte
- `order_price` non persistito, impedisce verifica spread completa
- Unrealized P&L di -8.10 EUR con posizioni in perdita del 20-36%: nessun exit triggato
  (possibile problema nel position monitor — TP/SL non scattano o sono configurati altrimenti)

### Stato complessivo del sistema
**Parzialmente funzionante** con problemi significativi:

**Funzionante**: API REST (health, markets, bot control, dashboard, rules), SSE stream, bot
execution (dry_run), rule_edge strategy, market price feed (API Gamma reale), circuit breaker
logic, GDELT anomaly detection, watchlist.

**Non funzionante o da correggere**:
1. Frontend Intelligence/Knowledge: empty state permanente (mancano le fetch in app.js)
2. knowledge/strategies e knowledge/risks: sempre vuoti (bug di persistenza/restore KB)
3. intelligence/news e knowledge/debug: endpoint non implementati
4. Solo rule_edge esegue: le altre 4 strategie non producono segnali
5. Posizioni in perdita elevata (fino a -36%) non gestite dall'exit monitor

I problemi 1, 3 e 4 non sono warm-up ma **bug strutturali** da investigare.
