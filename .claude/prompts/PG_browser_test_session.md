# PG — Browser Test Session: Dashboard, VAE, Trading

## Obiettivo

Eseguire una sessione di test completa del PolymarketBot usando esclusivamente il browser MCP
(claude-in-chrome). I test coprono quattro aree:

1. Popolamento schede Intelligence e Knowledge nella dashboard
2. Calcolo dell'edge (formula VAE completa con trasformazioni non-lineari per segnale)
3. Gestione trade simulate (prezzi, acquisti, vendite)
4. Verifica visiva rule parser per ogni mercato (condizioni, scadenza)

Il test DEVE essere eseguito in **due condizioni** distinte:
- **Cold start**: server avviato (`/health` OK), bot fermo (`/bot/status` → `running: false`)
- **Running bot**: dopo `POST /api/v1/bot/start`, attendi almeno 1 tick (`tick_count >= 1`)

Documenta entrambe le condizioni nel report. Se il bot era gia in running all'inizio del test,
documenta lo stato attuale come "running bot" e testa il cold start come "stato prima dell'avvio"
(tramite i dati disponibili).

Al termine, scrivi un report `BROWSER-TEST-REPORT.md` nella root del progetto
(`C:\Users\fgioa\OneDrive - SYNESIS CONSORTIUM\Desktop\PRO\PolyMarket\`).

---

## Contesto tecnico

### Stack e URL

- App: FastAPI 3.11, avviata su `http://localhost:8000` in modalita `dry_run`
- Dashboard SPA: `http://localhost:8000/` (vanilla JS, 4 schede: Trading, Config, Intelligence, Knowledge)
- SSE stream: `/api/v1/dashboard/stream`

### Endpoint da testare

| Endpoint | Scopo |
|----------|-------|
| `GET /api/v1/health` | Stato generale |
| `GET /api/v1/dashboard/overview` | Metriche bot (equity, P&L, win rate, tick count) |
| `GET /api/v1/dashboard/config` | Config attivo (strategies, risk, valuation weights, intelligence) |
| `GET /api/v1/dashboard/positions` | Posizioni aperte |
| `GET /api/v1/dashboard/trades` | Log trade |
| `GET /api/v1/intelligence/anomalies` | Report anomalie GDELT |
| `GET /api/v1/intelligence/news` | RSS news (max 30 item) |
| `GET /api/v1/intelligence/watchlist` | Temi/attori/paesi GDELT configurati |
| `GET /api/v1/knowledge/strategies` | Strategie per dominio con conteggio mercati |
| `GET /api/v1/knowledge/risks` | Profili di rischio per mercato |
| `GET /api/v1/knowledge/debug` | Diagnostica: risk_kb_rows, obsidian status, last_tick |
| `GET /api/v1/markets?limit=5` | Lista mercati live da Polymarket |
| `GET /api/v1/markets/{id}` | Dettaglio mercato + strategie applicabili |
| `GET /api/v1/markets/{id}/rules` | Regole di risoluzione parsate (RuleAnalysis) |
| `GET /api/v1/bot/status` | Stato running del bot |
| `POST /api/v1/bot/start` | Avvia il bot (per test running) |

### Formula VAE (Value Assessment Engine) — Trasformazioni reali per segnale

La formula NON e' un semplice `sum(signal * weight)`. Ogni segnale ha una trasformazione
specifica prima di entrare nella media pesata:

```
# ---- Per-signal transforms (dentro _compute_fair_value) ----

base_rate:           valore diretto (0-1)                    peso 0.15
rule_analysis:       valore diretto (0-1)                    peso 0.15
microstructure:      market_price + (score - 0.5) * 0.1      peso 0.15
                     poi clamp(0, 1)
cross_market:        market_price + signal * 0.15             peso 0.10
                     (signal range -1 to +1), poi clamp(0, 1)
event_signal:        clamp(0, 1) del valore diretto           peso 0.15
pattern_kg:          clamp(0, 1) del valore diretto           peso 0.10
cross_platform:      clamp(0, 1) del valore diretto           peso 0.10
crowd_calibration:   market_price + adjustment                peso 0.05
                     SOLO se adjustment != 0

# ---- Rinormalizzazione ----
# I segnali con valore None sono ESCLUSI: fair_value = weighted_sum / active_weight_total
# NON dividere per 1.0 (peso totale teorico)

# ---- Post-processing (DOPO _compute_fair_value) ----
fair_value = weighted_sum / weight_total     # rinormalizzato
edge = fair_value - market_price
scaled_edge = edge * temporal_factor         # temporal NON e' un segnale di probabilita
fee_adjusted_edge = scaled_edge - market.fee_rate   # fee_rate dal mercato, NON un fisso 0.02
```

**ATTENZIONE**: `temporal_factor` NON e' dentro `_compute_fair_value`. Scala l'edge
DOPO il calcolo del fair_value. Non trattarlo come un segnale di probabilita.

### Segnali attivi e inattivi

Con l'infrastruttura attuale, tipicamente attivi (~50% del peso totale):
- `base_rate` (0.15) — ResolutionDB storico
- `rule_analysis` (0.15) — RuleParser clarity score
- `crowd_calibration` (0.05) — se adjustment != 0 (richiede sample_size >= 20)
- `event_signal` (0.15) — GDELT + RSS (se relevance_score > 0.5)

Tipicamente inattivi (valore None, esclusi dalla formula con peso rinormalizzato):
- `microstructure` (0.15) — WS geobloccato, valore = None (NON zero)
- `pattern_kg` (0.10) — vault Obsidian non seeded, valore = None
- `cross_platform` (0.10) — Manifold disabilitato, valore = None
- `cross_market` (0.10) — richiede universe con correlazioni, puo essere None

### Struttura mercato

```python
class Outcome(BaseModel):
    token_id: str
    outcome: str   # "Yes" o "No"
    price: float   # prezzo live da API Gamma Polymarket

class Market(BaseModel):
    id: str
    question: str
    category: MarketCategory
    outcomes: list[Outcome]   # sempre 2: Yes + No (Polymarket e' solo binario)
    end_date: datetime | None  # None su ~60% dei mercati
    fee_rate: float
    resolution_rules: ResolutionRules
    time_horizon: str  # campo computed: SHORT/MEDIUM/LONG/SUPER_LONG
```

**Nota**: Polymarket supporta SOLO mercati binari (Yes/No). Non esistono mercati
multi-outcome su Polymarket — ogni outcome alternativo e' un mercato separato.

### Criteri edge reale vs simulato

- **Edge reale**: `market_price` viene da API Gamma di Polymarket (REST), non da dati mockati
- **Edge simulato (atteso)**: dato che ~50% dei segnali VAE sono None, il fair_value e'
  calcolato solo sui segnali attivi con pesi rinormalizzati. L'edge e' matematicamente
  corretto ma informativamente parziale.
- Il test DEVE verificare che `market_price` in `ValuationResult` corrisponda al prezzo
  dell'outcome "Yes" restituito da `GET /api/v1/markets/{id}`, non a un valore fisso (0.5).

### Validazione ID mercati

Se un `market_id` inizia con `"demo-"` o contiene pattern chiaramente non reali,
segnalalo come FALLBACK nel report: il sistema non sta usando l'API Gamma reale di
Polymarket ma dati di fallback. Questo invalida il test "prezzi reali".

---

## Vincoli

- Usa ESCLUSIVAMENTE strumenti MCP `claude-in-chrome` per ogni azione: `navigate`,
  `read_page`, `javascript_tool`, `read_network_requests`, `get_page_text`, `find`,
  `computer` (click/scroll)
- Non eseguire comandi Bash, non leggere file direttamente, non usare strumenti filesystem
- Il report finale deve essere scritto con il tool `Write` (unica eccezione al vincolo browser)
  nella path assoluta specificata nella sezione Output
- Non modificare nessun file del progetto
- Se un endpoint risponde con errore, documenta il codice HTTP e il messaggio nel report,
  poi prosegui con il prossimo step
- Tutti i criteri di validazione devono essere DINAMICI: leggi i valori attesi dal config
  o dalle API a runtime, mai hardcodare valori nel confronto

---

## Step-by-step

### STEP 0 — Prerequisiti: cold start vs running bot

**Questo step determina la modalita del test.**

**0a — Verifica stato attuale:**
**Tool:** `navigate` → `http://localhost:8000/api/v1/health`
**Tool:** `get_page_text`

Se l'app non risponde: scrivi "APP NON RAGGIUNGIBILE" nel report e fermati.

**Tool:** `navigate` → `http://localhost:8000/api/v1/bot/status`
**Tool:** `get_page_text`

**0b — Documenta lo stato cold start:**
Se `running: false`, esegui STEP 1-10 in questa condizione (cold start).
Poi avvia il bot con `POST /api/v1/bot/start` e ri-esegui gli step 3, 4, 5, 6, 8
per documentare il comportamento del running bot.

Se `running: true`, documenta lo stato attuale come "running bot" e annota nel report
che il test cold start non e' stato possibile (il bot era gia attivo).

Documenta nel report:
- `tick_count` iniziale
- `mode` (deve essere `dry_run`)
- `started_at` (null in cold start)
- `circuit_breaker_tripped`

---

### STEP 1 — Verifica app attiva e configurazione

**1a — Health check:**
**Tool:** `navigate` → `http://localhost:8000/api/v1/health`
**Tool:** `get_page_text`

Verifica che la risposta contenga `"status": "ok"` o equivalente.

**1b — Config attivo (per validazioni dinamiche successive):**
**Tool:** `navigate` → `http://localhost:8000/api/v1/dashboard/config`
**Tool:** `get_page_text`

Salva mentalmente (o con javascript_tool) i seguenti valori per i test successivi:
- `valuation.weights` — pesi VAE configurati
- `valuation.thresholds` — soglie min_edge per orizzonte
- `risk.max_exposure_pct`, `risk.max_positions`
- `intelligence.gdelt_enabled`, `intelligence.rss_enabled`
- `strategies.enabled` — lista strategie attive

Questi valori saranno usati come RIFERIMENTO per validazioni dinamiche negli step successivi.
Non usare mai valori hardcodati: confronta sempre con quanto letto qui.

---

### STEP 2 — Screenshot dashboard principale

**Tool:** `navigate` → `http://localhost:8000/`
**Tool:** `read_page` — screenshot + DOM

Documenta:
- Le 4 schede sono visibili (Trading, Config, Intelligence, Knowledge)?
- La scheda Trading mostra dati o placeholder?
- Quali metriche sono visibili (equity, P&L, win rate, tick count)?

---

### STEP 3 — Test scheda Intelligence (visivo + API)

**3a — Visivo:**
**Tool:** `find` → cerca elemento con `id` che contenga "intelligence" o testo "Intelligence"
**Tool:** `computer` → click sulla scheda Intelligence
**Tool:** `read_page` — screenshot dopo click

**3b — API anomalie:**
**Tool:** `navigate` → `http://localhost:8000/api/v1/intelligence/anomalies`
**Tool:** `get_page_text`

Documenta:
- La scheda mostra dati o empty-state?
- Numero di anomalie restituite dall'API (0 = nessuna, N = quante)
- Applica i criteri warm-up (vedi sezione "Criteri warm-up vs bug" sotto)

**3c — API news:**
**Tool:** `navigate` → `http://localhost:8000/api/v1/intelligence/news`
**Tool:** `get_page_text`

Documenta:
- Numero di RSS items restituiti
- `relevance_score` > 0 su almeno alcuni item? (se tutti 0.0, il calcolo rilevanza non funziona)
- Quali `source` compaiono?

**3d — API watchlist (verifica DINAMICA):**
**Tool:** `navigate` → `http://localhost:8000/api/v1/intelligence/watchlist`
**Tool:** `get_page_text`

L'endpoint restituisce `{themes: [...], actors: [...], countries: [...]}` letti direttamente
dal config YAML attivo. La verifica e' DINAMICA — non confrontare con valori hardcodati:

1. Verifica che `themes`, `actors`, `countries` siano array non vuoti
2. Verifica che la struttura sia coerente (3 campi presenti)
3. Verifica coerenza con STEP 1b: se `gdelt_enabled: true` nel dashboard/config,
   allora la watchlist DEVE avere almeno 1 tema. Se `gdelt_enabled: false`, la watchlist
   puo essere vuota (GDELT disabilitato).
4. Annota i valori restituiti — serviranno come riferimento per eventuali analisi future

---

### STEP 4 — Test scheda Knowledge (visivo + API)

**4a — Visivo:**
**Tool:** `navigate` → `http://localhost:8000/`
**Tool:** `computer` → click sulla scheda Knowledge
**Tool:** `read_page` — screenshot

**4b — API strategies:**
**Tool:** `navigate` → `http://localhost:8000/api/v1/knowledge/strategies`
**Tool:** `get_page_text`

Documenta:
- Numero di strategie mappate a mercati
- Applica i criteri warm-up (vedi sezione sotto)

**4c — API risks:**
**Tool:** `navigate` → `http://localhost:8000/api/v1/knowledge/risks`
**Tool:** `get_page_text`

Documenta:
- Numero di profili di rischio (LOW/MEDIUM/HIGH)
- Distribuzione per livello

**4d — API debug:**
**Tool:** `navigate` → `http://localhost:8000/api/v1/knowledge/debug`
**Tool:** `get_page_text`

Estrai e documenta ogni campo del JSON:
- `risk_kb_rows`: numero righe nel Risk KB
- `obsidian_enabled`: true/false
- `obsidian_reachable`: true/false
- `pattern_counts`: oggetto con conteggi per dominio
- `last_intelligence_tick`: timestamp ultimo tick o null
- `anomaly_history_length`: lunghezza storia anomalie

---

### STEP 5 — Recupero mercati reali da Polymarket

**Tool:** `navigate` → `http://localhost:8000/api/v1/markets?limit=5`
**Tool:** `get_page_text`

Estrai i campi di ALMENO 3 mercati:
- `id` — controlla se inizia con `"demo-"` (vedi "Validazione ID mercati" sopra)
- `question`, `category`, `status`
- `outcomes[].outcome` e `outcomes[].price` — i prezzi sono > 0 e sommano circa a 1.0?
- `end_date` — presente o null?
- `time_horizon` — quale valore computed?
- `fee_rate` — qual e' il valore?

Salva gli ID di almeno 2 mercati per i test successivi.
Se tutti gli ID iniziano con "demo-", segnala nel report: "MERCATI DI FALLBACK, NON API REALE".

---

### STEP 6 — Verifica edge: calcolo manuale dalla formula VAE reale

Per ciascuno dei 2 mercati selezionati nel STEP 5:

**6a — Dettaglio mercato:**
**Tool:** `navigate` → `http://localhost:8000/api/v1/markets/{market_id}`
**Tool:** `get_page_text`

Estrai `market_price_yes = outcomes[outcome=="Yes"].price`

**6b — Cerca dati VAE disponibili:**
Se il bot ha eseguito almeno un tick (STEP 0), controlla il trade log:
**Tool:** `navigate` → `http://localhost:8000/api/v1/dashboard/trades`
**Tool:** `get_page_text`

Se ci sono trade per uno dei mercati selezionati, estrai `price` (= fill_price) e `edge`
(= fee_adjusted_edge al momento del segnale).

**6c — Calcolo manuale con javascript_tool:**
Usando i dati raccolti, esegui il calcolo VAE manuale con `javascript_tool`.
Usa i pesi letti dal STEP 1b (`valuation.weights`):

```javascript
// Esempio di calcolo — adatta i valori ai dati reali raccolti
const market_price = /* outcomes[Yes].price dal STEP 6a */;
const weights = /* valuation.weights dal STEP 1b */;

// Segnali disponibili (sostituisci con i valori reali dal sistema)
// Per segnali inattivi (None nel sistema), NON includerli nel calcolo
let weighted_sum = 0;
let weight_total = 0;

// base_rate — valore diretto
const base_rate = /* valore dal sistema o stima 0.5 se non disponibile */;
if (base_rate !== null) {
    weighted_sum += weights.base_rate * base_rate;
    weight_total += weights.base_rate;
}

// rule_analysis — valore diretto
const rule_analysis = /* valore dal sistema */;
if (rule_analysis !== null) {
    weighted_sum += weights.rule_analysis * rule_analysis;
    weight_total += weights.rule_analysis;
}

// microstructure — trasformazione NON lineare
// Se score e' null/undefined, NON includerlo (peso rinormalizzato)
const micro_score = null; // tipicamente None (WS geobloccato)
if (micro_score !== null) {
    const micro_signal = Math.max(0, Math.min(1,
        market_price + (micro_score - 0.5) * 0.1));
    weighted_sum += weights.microstructure * micro_signal;
    weight_total += weights.microstructure;
}

// cross_market — trasformazione NON lineare
const cross_signal = null; // range -1 to +1, spesso None
if (cross_signal !== null) {
    const cross_prob = Math.max(0, Math.min(1,
        market_price + cross_signal * 0.15));
    weighted_sum += weights.cross_market * cross_prob;
    weight_total += weights.cross_market;
}

// event_signal — clamp diretto
const event = /* valore dal sistema */;
if (event !== null) {
    const event_prob = Math.max(0, Math.min(1, event));
    weighted_sum += weights.event_signal * event_prob;
    weight_total += weights.event_signal;
}

// crowd_calibration — SOLO se adjustment != 0
const crowd_adj = /* valore dal sistema */;
if (crowd_adj !== null && crowd_adj !== 0) {
    const adjusted_price = market_price + crowd_adj;
    weighted_sum += weights.crowd_calibration * adjusted_price;
    weight_total += weights.crowd_calibration;
}

// pattern_kg, cross_platform — tipicamente None
// NON includerli se null

const fair_value = weight_total > 0 ? weighted_sum / weight_total : market_price;
const edge = fair_value - market_price;
// temporal_factor: 0.5 se end_date=null, altrimenti calcolato
const temporal_factor = /* valore appropriato */;
const scaled_edge = edge * temporal_factor;
const fee_rate = /* market.fee_rate dal STEP 6a */;
const fee_adjusted_edge = scaled_edge - fee_rate;

JSON.stringify({
    fair_value: fair_value.toFixed(4),
    edge: edge.toFixed(4),
    scaled_edge: scaled_edge.toFixed(4),
    fee_adjusted_edge: fee_adjusted_edge.toFixed(4),
    weight_total: weight_total.toFixed(4),
    signals_active: /* conteggio segnali attivi */
}, null, 2);
```

**6d — Confronto:**
Confronta il risultato del calcolo manuale con l'edge presente nel trade log (se disponibile).
Documenta:
- I valori coincidono entro un margine ragionevole (< 0.005)?
- Se no, quale segnale causa la divergenza?
- Quanti segnali erano attivi? Il peso rinormalizzato e' corretto?

Se non ci sono trade per i mercati selezionati, documenta il calcolo come
"verifica formula senza riscontro dal sistema" e annota i segnali usati.

**6e — Verifica prezzi reali:**
Analizza i prezzi `outcomes[].price` restituiti. Criteri per "prezzo reale":
- Il prezzo Yes + prezzo No deve essere compreso tra 0.95 e 1.05
- Il prezzo non deve essere esattamente 0.5 su tutti i mercati (indicherebbe dati mock)
- I prezzi devono variare tra mercati diversi

---

### STEP 7 — Verifica rule parser: regole, condizioni

Per i 2 mercati selezionati:

**7a — API rules:**
**Tool:** `navigate` → `http://localhost:8000/api/v1/markets/{market_id}/rules`
**Tool:** `get_page_text`

Estrai dal JSON `RuleAnalysis`:
- `source`: chi risolve (es. "Associated Press", "Official Government Data")
- `conditions`: lista condizioni di risoluzione — sono presenti e non vuote?
- `deadline`: data scadenza — corrisponde a `end_date` del mercato?
- `raw_text`: il testo originale della regola Polymarket e' presente?
- `clarity_score` (o campo equivalente): valore tra 0-1

**7b — Verifica varianti:**
Controlla nei `conditions` se compaiono:
- Varianti numeriche (es. "above 50", "between X and Y", price ranges)
- Varianti temporali (es. "by end of 2025", "before April 15")
- Multiple condizioni OR/AND

Documenta se il parser identifica correttamente queste strutture.

**7c — Visivo dashboard mercati:**
**Tool:** `navigate` → `http://localhost:8000/`
**Tool:** `computer` → click scheda Trading
**Tool:** `read_page`

Le posizioni aperte mostrano quale `outcome` e' stato acquistato (Yes/No)?

---

### STEP 8 — Verifica trade simulate: prezzi, acquisti/vendite, logica

**8a — Log trade:**
**Tool:** `navigate` → `http://localhost:8000/api/v1/dashboard/trades`
**Tool:** `get_page_text`

Per ogni trade nel log documenta:
- `type`: "open" o "close" o "partial_exit"
- `side`: BUY o SELL
- `price`: prezzo di esecuzione (= fill_price, include slippage)
- `edge`: fee_adjusted_edge al momento del segnale
- `horizon`: orizzonte temporale del mercato
- `pnl`: P&L realizzato (solo per "close")

Verifica:
- Per trade di tipo "open" con side BUY: `price` (fill_price) deve essere >= al prezzo
  di mercato al momento del segnale. La logica di esecuzione applica spread simulato
  (`order.price * (1 + spread/2) + slippage`), quindi il fill_price e' SEMPRE > order.price
  per BUY. Se `price` e' esattamente uguale al prezzo di mercato, lo spread non funziona.
- Le close hanno `pnl` != 0

**8b — Posizioni aperte:**
**Tool:** `navigate` → `http://localhost:8000/api/v1/dashboard/positions`
**Tool:** `get_page_text`

Per ogni posizione documenta:
- `market_id`, `outcome` acquistato, `cost_basis`, `avg_price`, `current_price`
- `unrealized_pnl`
- `edge_at_entry`
- `strategy`

**8c — Metriche aggregate:**
**Tool:** `navigate` → `http://localhost:8000/api/v1/dashboard/overview`
**Tool:** `get_page_text`

Estrai: `equity`, `daily_pnl`, `win_rate`, `total_trades`, `open_positions`,
`circuit_breaker.tripped`, `circuit_breaker.consecutive_losses`

---

### STEP 9 — Verifica circuit breaker e controllo regole

**Tool:** `navigate` → `http://localhost:8000/api/v1/bot/status`
**Tool:** `get_page_text`

Documenta:
- `running`: il bot sta girando?
- `mode`: dry_run / shadow / live?
- `circuit_breaker_tripped`

Confronta `circuit_breaker` da STEP 8c con lo stato del bot. Coerenti?

---

### STEP 10 — Test network requests (XHR/fetch dalla dashboard)

**Tool:** `navigate` → `http://localhost:8000/`
**Tool:** `read_network_requests`

Avvia il monitoring delle richieste di rete, poi:
**Tool:** `computer` → click su ciascuna scheda (Trading, Intelligence, Knowledge, Config)
**Tool:** `read_network_requests` — verifica le chiamate fetch originate dal JS

Documenta:
- Quali endpoint vengono chiamati a ogni cambio scheda?
- Ci sono errori 4xx/5xx nelle risposte?
- Le chiamate Intelligence e Knowledge partono correttamente?

---

## Criteri warm-up vs bug

Usa questa tabella per distinguere tra stato normale di warm-up e veri bug.
Questi criteri si applicano a STEP 3 e STEP 4.

### Al primo avvio assoluto (nessun dato persistito):

| Dato | Warm-up (atteso) | Bug |
|------|-------------------|-----|
| `risk_kb_rows = 0` | Normale: nessun tick eseguito | Bug se `tick_count > 0` e `risk_kb_rows = 0` |
| `anomaly_history_length = 0` | Normale: GDELT non ha ancora eseguito | Bug se `last_intelligence_tick != null` ma `anomaly_history_length = 0` e nessun errore nel log |
| `strategies = []` | Normale: Risk KB vuoto pre-tick | Bug se tick ha eseguito con segnali |
| `news = []` | Normale: RSS non ha ancora eseguito | Bug se `rss_enabled: true` e `tick_count > 0` |

### Agli avvii successivi (dati persistiti su SQLite):

| Dato | Warm-up (atteso) | Bug |
|------|-------------------|-----|
| `risk_kb_rows > 0` | Atteso: recuperato da DB | Bug se 0 dopo restart con DB pre-esistente |
| `tick_count > 0` | Atteso: ripristinato da `trade_store` | Bug se 0 quando il DB ha trade |
| `anomaly_history_length` | Puo essere 0 (anomalie non persistite su DB) | Non e' un bug |
| `trades != []` | Atteso: trade log ripristinato da DB | Bug se vuoto con DB contenente trade |
| `positions != []` | Atteso: se c'erano posizioni aperte | Bug se perse dopo restart |

**Come discriminare**: controlla `tick_count` dal STEP 0 e `last_intelligence_tick` dal STEP 4d.
- Se `tick_count = 0` E `last_intelligence_tick = null` → primo avvio, tutto vuoto e' normale
- Se `tick_count > 0` E dati vuoti → possibile bug di persistenza o di restore

---

## Output atteso

Scrivi il report con il tool `Write` nel percorso:
`C:\Users\fgioa\OneDrive - SYNESIS CONSORTIUM\Desktop\PRO\PolyMarket\BROWSER-TEST-REPORT.md`

### Struttura del report

```markdown
# BROWSER-TEST-REPORT

Data: {data esecuzione}
Modalita bot: dry_run | {altro}
App URL: http://localhost:8000
Condizioni testate: cold start / running bot / entrambe

---

## Sintesi

| Area | Cold Start | Running Bot | Note |
|------|------------|-------------|------|
| App health | OK / ERRORE | OK / ERRORE | |
| Intelligence | Vuota / Popolata | Vuota / Popolata | N anomalie, N news |
| Knowledge | Vuota / Popolata | Vuota / Popolata | N strategie, N rischi |
| Prezzi Polymarket | Reali / Fallback | Reali / Fallback | somma Yes+No, ID check |
| VAE edge | Calcolo OK / Divergente | Calcolo OK / Divergente | formula verificata? |
| Trade simulate | N/A (pre-tick) | Coerenti / Problemi | fill_price, spread |
| Rule parser | Funzionante / Parziale | Funzionante / Parziale | |
| Circuit breaker | Inattivo | Attivo / Inattivo | |
| Warm-up vs Bug | {valutazione} | {valutazione} | criteri applicati |

---

## STEP 0 — Prerequisiti
### Stato iniziale
- running: {valore}
- mode: {valore}
- tick_count: {valore}
- started_at: {valore}
- circuit_breaker_tripped: {valore}

### Condizioni di test
{quale condizione e' stata testata e perche}

## STEP 1 — Health check e config
### 1a Health
{risultato verbatim JSON}
### 1b Config attivo
{valori chiave estratti per validazioni dinamiche}

## STEP 2 — Dashboard screenshot
{descrizione visuale + anomalie riscontrate}

## STEP 3 — Intelligence tab
### 3a Visivo
{screenshot description}
### 3b Anomalie
{JSON response + count + valutazione warm-up/bug}
### 3c News
{count, relevance distribution, sources}
### 3d Watchlist (verifica dinamica)
- Temi restituiti: {lista}
- Attori restituiti: {lista}
- Paesi restituiti: {lista}
- gdelt_enabled in config: {valore dal STEP 1b}
- Coerenza config <-> watchlist: {OK / PROBLEMA + spiegazione}

## STEP 4 — Knowledge tab
### 4a Visivo
{screenshot description}
### 4b Strategies
{count, lista + valutazione warm-up/bug}
### 4c Risks
{count, distribuzione LOW/MEDIUM/HIGH}
### 4d Debug endpoint
{ogni campo del JSON con valutazione warm-up/bug}

## STEP 5 — Mercati reali
{tabella con id, question, yes_price, no_price, sum, time_horizon, end_date, fee_rate}
ID check: {tutti reali / demo- prefix rilevato}

## STEP 6 — Verifica edge VAE (calcolo manuale)
### Mercato 1: {id}
- market_price (API Gamma): {valore}
- Prezzi reali? {si/no + motivazione}
- Segnali usati nel calcolo manuale: {lista con valori}
- Pesi rinormalizzati: {weight_total}
- Calcolo:
  - fair_value = {valore}
  - edge = {valore}
  - scaled_edge = {valore} (temporal_factor = {valore})
  - fee_adjusted_edge = {valore} (fee_rate = {valore})
- Edge nel trade log (se disponibile): {valore}
- Corrispondenza: {si/no/non verificabile + margine}
### Mercato 2: {id}
{stessa struttura}

## STEP 7 — Rule parser
### Mercato 1: {id}
- source: {valore}
- conditions: {lista}
- deadline: {valore}
- clarity_score: {valore}
- Varianti rilevate: {si/no + dettaglio}
### Mercato 2: {id}
{stessa struttura}

## STEP 8 — Trade simulate
### Trade log
{tabella: type, side, price (fill), edge, horizon, pnl}
### Spread check
- fill_price > order.price per BUY: {si/no}
- Quanti trade hanno spread correttamente applicato: {N/totale}
### Posizioni aperte
{tabella: market_id, outcome, cost_basis, avg_price, current_price, unrealized_pnl, strategy}
### Metriche aggregate
{equity, daily_pnl, win_rate, total_trades, open_positions, circuit_breaker}

## STEP 9 — Bot status e circuit breaker
{JSON status + coerenza con STEP 8c}

## STEP 10 — Network requests dashboard
{tabella: scheda, endpoint chiamati, status code, errori}

---

## Problemi rilevati

| # | Area | Problema | Gravita | Warm-up o Bug? | Note |
|---|------|----------|---------|----------------|------|
| 1 | ... | ... | HIGH/MEDIUM/LOW | Warm-up / Bug | |

---

## Conclusioni

### Edge: reale o simulato?
{risposta motivata basata su STEP 5+6, con riferimento al calcolo manuale}

### Intelligence: popolamento corretto?
{risposta motivata basata su STEP 3+4 + criteri warm-up}

### Trade: coerenti con mercato reale?
{risposta motivata basata su STEP 8}

### Stato complessivo del sistema
{valutazione: funzionante / parzialmente funzionante / problemi critici}
{Se problemi: sono warm-up (attesi) o bug (da investigare)?}
```

---

## Note

- I prezzi Polymarket possono essere 0.0 se la Gamma API e' down o ha rate-limited il bot.
  Documenta ma non interrompere il test.
- `relevance_score == 0.0` su TUTTI i news items indica che il calcolo rilevanza non funziona.
- Se le schede Intelligence e Knowledge non chiamano API al cambio tab (STEP 10),
  il frontend non le ha integrate.
- L'edge e' sempre "parzialmente simulato" con l'infrastruttura attuale (WS geobloccato,
  Obsidian non seeded, Manifold disabilitato). Il report deve distinguere tra:
  - "Prezzi di mercato reali" (Yes/No price da API Gamma) — dovrebbe essere sempre vero
  - "Segnali VAE completi" (tutti e 9 attivi) — non e' il caso attuale (~50%)
- Il `temporal_factor` per mercati senza `end_date` e' 0.5.
  Per mercati con `end_date` > 30 giorni e' 1.0.
  Per mercati con `end_date` < 30 giorni segue un decay lineare modulato per categoria.
