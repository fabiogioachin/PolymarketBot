# PolymarketBot - Admin Implementation Plan

Guida completa per l'admin al primo avvio, dalla configurazione alla simulazione live.

---

## Indice

1. [Pre-requisiti](#1-pre-requisiti)
2. [Configurazione .env](#2-configurazione-env)
3. [Primo avvio e verifica](#3-primo-avvio-e-verifica)
4. [Cosa funziona SENZA LLM](#4-cosa-funziona-senza-llm)
5. [Quando e come viene usata la Claude API](#5-quando-e-come-viene-usata-la-claude-api)
6. [Simulazione dry-run (zero soldi reali)](#6-simulazione-dry-run-zero-soldi-reali)
7. [Telegram Bot: creazione e configurazione](#7-telegram-bot-creazione-e-configurazione)
8. [Obsidian Knowledge Graph: setup](#8-obsidian-knowledge-graph-setup)
9. [La questione Italia e Polymarket](#9-la-questione-italia-e-polymarket)
10. [Architettura denaro reale: come funziona il funding](#10-architettura-denaro-reale-come-funziona-il-funding)
11. [Passaggio a trading live](#11-passaggio-a-trading-live)
12. [Checklist admin post-setup](#12-checklist-admin-post-setup)

---

## 1. Pre-requisiti

### Software necessario
- Python 3.11+ (verificare con `python --version`)
- Git
- Un browser per la dashboard (`http://localhost:8000/static/index.html`)
- (Opzionale) Obsidian con plugin Local REST API
- (Opzionale) Docker Desktop (per deployment containerizzato)

### Installazione dipendenze

```bash
# Clona e installa
cd PolyMarket
pip install httpx websockets pydantic pydantic-settings pyyaml structlog aiosqlite feedparser
pip install fastapi uvicorn
pip install pyarrow  # per backtesting Parquet I/O
pip install ruff pytest pytest-asyncio respx  # dev/test
```

### Struttura configurazione
- **`.env`** — segreti (API key, token). Mai committato in git.
- **`config/config.yaml`** — parametri tunabili (soglie, pesi, strategie). Committabile.
- Se `config.yaml` non esiste, il sistema usa i default da `config/config.example.yaml`.

---

## 2. Configurazione .env

Copia il template e compila:

```bash
cp .env.example .env
```

### Configurazione minima per dry-run (nessuna API key richiesta)

```env
APP_ENV=development
LOG_LEVEL=INFO
DRY_RUN=true
```

Questo e' sufficiente per avviare il bot in modalita' simulazione. Il Value Engine, le strategie e il risk manager funzionano tutti senza API key esterne.

### Configurazione progressiva

| Variabile | Quando serve | Come ottenerla |
|---|---|---|
| `ANTHROPIC_API_KEY` | Solo se abiliti LLM enrichment | console.anthropic.com > API Keys |
| `TELEGRAM_BOT_TOKEN` | Per ricevere alert su Telegram | @BotFather su Telegram (vedi sezione 7) |
| `TELEGRAM_CHAT_ID` | Per ricevere alert su Telegram | @userinfobot o via API (vedi sezione 7) |
| `OBSIDIAN_API_KEY` | Per connessione Obsidian KG live | Plugin "Local REST API" in Obsidian |
| `POLYMARKET_API_KEY` | Solo per trading LIVE reale | Polymarket CLOB API (vedi sezione 10) |
| `POLYMARKET_SECRET` | Solo per trading LIVE reale | Polymarket CLOB API |
| `POLYMARKET_PASSPHRASE` | Solo per trading LIVE reale | Polymarket CLOB API |
| `POLYMARKET_FUNDER` | Solo per trading LIVE reale | Il tuo wallet address |

**Per iniziare a testare, NON serve nessuna API key.** Avvia con il `.env` minimo.

---

## 3. Primo avvio e verifica

### Avvio

```bash
# Avvio diretto (sviluppo locale — API + dashboard su porta 8000)
uvicorn app.main:app --host 0.0.0.0 --port 8000

# Oppure con Docker (backend:8000 + frontend/nginx:80)
docker compose -f docker/docker-compose.yml up --build
# Dashboard: http://localhost (porta 80, via nginx)
# API: http://localhost:8000 (diretto al backend)
```

### Verifica che tutto funzioni

```bash
# Health check
curl http://localhost:8000/api/v1/health

# Dashboard (aprire nel browser)
# http://localhost:8000/static/index.html

# Configurazione corrente
curl http://localhost:8000/api/v1/dashboard/config

# Lista mercati (richiede connessione internet, chiama API Polymarket pubblica)
curl http://localhost:8000/api/v1/markets

# Test suite
python -m pytest tests/ -q
```

### Cosa aspettarsi
- `/health` risponde con `{"status": "ok"}`
- `/markets` restituisce mercati reali da Polymarket (API pubblica, no auth)
- La dashboard mostra le 4 tab (Trading, Config, Intelligence, Knowledge)
- I log vengono scritti in `logs/` in formato JSON

---

## 4. Cosa funziona SENZA LLM

Il sistema e' stato progettato con il principio "LLM minimal". La Claude API e' un **arricchimento opzionale**, non una dipendenza.

### Funziona completamente senza LLM

| Componente | Descrizione |
|---|---|
| **Value Assessment Engine** | Calcola fair value con 7 segnali pesati (base rate, rule analysis, microstructure, cross-market, event signal, KG pattern, crowd calibration, temporal decay) |
| **6 strategie su 7** | value_edge, arbitrage, rule_edge, event_driven, sentiment, resolution — tutte autonome |
| **Intelligence Pipeline** | GDELT DOC API (gratuita, illimitata) + RSS feeds + Federal Register — anomaly detection automatica |
| **Obsidian KG** | Pattern matching basato su keyword, nessun LLM coinvolto |
| **Risk Manager** | Position sizing, exposure limits, circuit breaker — tutto deterministico |
| **Execution Engine** | Tick loop completo: scan > assess > strategy > risk > execute |
| **Backtesting** | Replay storico, simulator con slippage/fee, reporter con Sharpe/drawdown |
| **Dashboard + Telegram** | Monitoring completo |
| **Market Scanner** | Classificazione per dominio, rule parsing, risk classification |

### Richiede LLM (opzionale)

| Componente | Quando scatta | Cosa fa |
|---|---|---|
| **knowledge_driven strategy** | Quando ha pattern KG forti ma il Value Engine non ha edge chiaro | Chiede a Claude di "connettere i punti" tra pattern, eventi e mercato |
| **LLM enrichment** (endpoint `/intelligence/enrich`) | Trigger configurabili: `anomaly`, `new_market`, `daily_digest`, `manual_request` | Analisi deep-dive di un mercato specifico con contesto completo |

### Stima costi LLM (se attivato)

- Modello default: `claude-sonnet-4-6` (rapporto costo/prestazione ottimale)
- Limite giornaliero: 20 chiamate/giorno (configurabile in `config.yaml`)
- Ogni chiamata: ~1000 token input + ~500 token output
- **Costo stimato**: ~$0.005/chiamata = ~$0.10/giorno = ~$3/mese
- Con limite a 20 call/day, il costo massimo e' ~$3/mese
- Puoi disabilitarlo completamente: `llm.enabled: false` in config.yaml

**Raccomandazione**: inizia SENZA LLM. Attivalo dopo 1-2 settimane di dry-run per valutare se aggiunge valore rispetto ai soli segnali quantitativi.

---

## 5. Quando e come viene usata la Claude API

### Trigger configurabili (in `config.yaml`)

```yaml
llm:
  enabled: false  # default: OFF
  triggers:
    - anomaly       # GDELT rileva anomalia (volume spike, tone shift)
    - new_market     # nuovo mercato appare su Polymarket
    - daily_digest   # riassunto giornaliero
  max_daily_calls: 20
  model: claude-sonnet-4-6
```

### Flusso di una chiamata LLM

1. Un trigger scatta (es. GDELT rileva volume spike 3x su "NATO")
2. Il sistema raccoglie contesto: mercati correlati, pattern KG, eventi recenti
3. Costruisce un prompt strutturato e lo invia a Claude
4. Claude risponde con: probabilita' stimata, fattori chiave, risk flag
5. La risposta viene parsata e usata come segnale aggiuntivo nel Value Engine
6. Il segnale LLM ha peso configurabile (default: 0% se disabilitato)

### Come attivare

1. Ottieni API key da https://console.anthropic.com/settings/keys
2. Aggiungi nel `.env`: `ANTHROPIC_API_KEY=sk-ant-...`
3. In `config.yaml`, cambia `llm.enabled: true`
4. Oppure via API: `PUT /api/v1/config/triggers` con `llm_enabled: true`

---

## 6. Simulazione dry-run (zero soldi reali)

### Come funziona

Il dry-run e' la modalita' default. Il sistema:
- Si connette alle API **pubbliche** di Polymarket (no auth) per leggere mercati e prezzi
- Esegue l'intero pipeline: valutazione, strategie, risk check
- Simula ordini con un bilancio virtuale di **150 USDC**
- Traccia posizioni, P&L, equity curve — tutto simulato
- Scrive log dettagliati con reasoning per ogni trade

### Avvio simulazione

```bash
# 1. Assicurati che DRY_RUN=true nel .env

# 2. Avvia il server
uvicorn app.main:app --port 8000

# 3. Il bot NON parte automaticamente. Per avviarlo:
curl -X POST http://localhost:8000/api/v1/bot/start

# 4. Controlla lo stato
curl http://localhost:8000/api/v1/bot/status

# 5. Guarda i risultati nella dashboard
# http://localhost:8000/static/index.html
```

### Cosa osservare durante il dry-run

1. **Dashboard > Trading**: equity curve, trade log con reasoning
2. **Logs**: `logs/` contiene ogni decisione in JSON strutturato
3. **API**: `GET /api/v1/bot/status` per tick count, P&L, posizioni
4. **Metriche**: win rate, Sharpe, drawdown — stesse metriche del live

### Quanto tempo lasciarlo girare

- **1-3 giorni**: verifica che il pipeline funzioni end-to-end
- **1-2 settimane**: accumula abbastanza trade per metriche significative
- **1 mese**: dati sufficienti per backtesting comparison

### Backtesting su dati storici

```bash
# 1. Scarica dati storici (richiede internet)
python scripts/fetch_historical.py --days 30 --output data/backtest

# 2. I dati vengono salvati in formato Parquet in data/backtest/

# 3. Il backtest puo' essere avviato via API
curl -X POST http://localhost:8000/api/v1/backtest/run \
  -H "Content-Type: application/json" \
  -d '{"starting_capital": 150, "max_positions": 10}'
```

---

## 7. Telegram Bot: creazione e configurazione

### Step 1: Crea il bot

1. Apri Telegram e cerca **@BotFather**
2. Invia `/newbot`
3. Scegli un nome (es. "PolymarketBot Alerts")
4. Scegli un username (es. `polymarket_alerts_bot`)
5. BotFather risponde con il **token**: `123456789:ABCdefGHI...`
6. Salva il token nel `.env`: `TELEGRAM_BOT_TOKEN=123456789:ABCdefGHI...`

### Step 2: Ottieni il tuo chat_id

1. Cerca **@userinfobot** su Telegram e avvialo
2. Ti risponde con il tuo **ID** (un numero, es. `987654321`)
3. Salva nel `.env`: `TELEGRAM_CHAT_ID=987654321`

Alternativa: invia un messaggio al tuo bot, poi chiama:
```bash
curl "https://api.telegram.org/bot<TOKEN>/getUpdates"
```
Troverai il `chat.id` nella risposta.

### Step 3: Verifica

```bash
# Riavvia il server dopo aver aggiornato .env
# Il bot inviera' alert quando:
# - Un trade viene eseguito (edge > 10%)
# - Il circuit breaker scatta
# - Il daily summary viene generato
```

### Comandi Telegram disponibili

| Comando | Descrizione |
|---|---|
| `/status` | Stato del bot (running, mode, ticks, P&L) |
| `/positions` | Posizioni aperte |
| `/pnl` | Riepilogo P&L giornaliero e totale |
| `/watchlist` | Watchlist GDELT attiva |
| `/help` | Lista comandi |

### Configurazione alert

Le regole di alert sono configurabili via API o dashboard:

```bash
# Vedi regole attuali
curl http://localhost:8000/api/v1/config/alerts

# Modifica (es. alert solo per edge > 15%)
curl -X PUT http://localhost:8000/api/v1/config/alerts \
  -H "Content-Type: application/json" \
  -d '{"telegram_enabled": true, "rules": [
    {"type": "trade_executed", "enabled": true, "min_edge": 0.15},
    {"type": "circuit_breaker", "enabled": true},
    {"type": "daily_summary", "enabled": true}
  ]}'
```

---

## 8. Obsidian Knowledge Graph: setup

### Pre-requisiti

1. Obsidian installato con il vault in:
   `C:/Users/fgioa/OneDrive - SYNESIS CONSORTIUM/Desktop/PRO/_ObsidianKnowledge`
2. Plugin **Local REST API** installato e attivo in Obsidian

### Setup struttura vault

```bash
# Crea directory e MOC
python scripts/setup_vault.py

# Genera 25 pattern seed (geopolitics, politics, economics, crypto, sports)
python scripts/seed_patterns.py
```

### Configurazione connessione

1. In Obsidian, apri Settings > Local REST API
2. Copia l'**API Key** mostrata
3. Aggiungi nel `.env`:
   ```
   OBSIDIAN_API_KEY=<la-tua-key>
   OBSIDIAN_API_URL=http://127.0.0.1:27123
   ```
4. Verifica: i pattern vengono letti dal bot e usati nel KnowledgeService

### Cosa fa il KG nel sistema

- Legge pattern per dominio e li matcha con eventi correnti
- Scrive nuovi eventi/scoperte nel vault
- Aggiorna la confidence dei pattern basandosi sui risultati
- Ruota pattern stagionali in StandBy

### Funziona anche senza Obsidian?

Si'. Se l'Obsidian bridge non e' connesso, il sistema funziona normalmente — i segnali `pattern_kg` saranno semplicemente assenti dal Value Engine.

---

## 9. La questione Italia e Polymarket

### Stato attuale

Polymarket **non e' accessibile dall'Italia** per il trading. L'account e' collegato a Google ma le transazioni richiedono un wallet Polygon che potrebbe essere geo-bloccato.

### Opzioni disponibili

| Opzione | Rischio | Note |
|---|---|---|
| **Dry-run permanente** (attuale) | Zero | Il bot analizza mercati reali ma non piazza ordini. Tutto il valore intellettuale (pattern, analisi, KG) si accumula. |
| **VPN + Polymarket** | Medio-alto | Violazione potenziale dei ToS di Polymarket. Se scoperti, account e fondi bloccati. Rischio legale italiano non chiaro. |
| **Predict Street** (previsto 9/4/2026) | Basso | Piattaforma EU-compliant in fase di lancio. Il nostro LiveExecutor e' un placeholder pronto per essere collegato. |
| **Altre piattaforme EU** | Variabile | Augur, Gnosis, o piattaforme regolamentate EU che emergono |

### Strategia raccomandata

1. **Ora**: dry-run su Polymarket. Accumula dati, valida strategie, affina pattern.
2. **Aprile 2026**: verifica il lancio di Predict Street. Se accessibile dall'Italia, collegalo.
3. **Nel frattempo**: il sistema produce valore anche senza trading live:
   - Knowledge Graph cresce con pattern validati
   - Intelligence pipeline monitora eventi
   - Backtesting valida strategie su dati storici
   - L'intero sistema e' pronto per il "go live" in un giorno

### Regime fiscale (se si arriva al live)

- Redditi da prediction market: classificazione ancora incerta in Italia
- Probabilmente "redditi diversi" (art. 67 TUIR) — aliquota progressiva
- Wallet Polygon/USDC: obblighi dichiarativi (Quadro RW, IVCA 0.2%)
- **Raccomandazione**: consultare un commercialista specializzato in crypto prima del live

---

## 10. Architettura denaro reale: come funziona il funding

### Come Polymarket gestisce i fondi

```
EUR (banca) --> Exchange (es. Coinbase) --> USDC (stablecoin) --> Polygon Network --> Polymarket CLOB
```

### Step concreti (quando sara' il momento)

1. **Acquista USDC** su un exchange (Coinbase, Kraken, Binance)
   - Deposito EUR via bonifico SEPA
   - Compra USDC (stablecoin 1:1 con USD)
   - Costo: ~0.5-1% fee di exchange

2. **Trasferisci USDC su Polygon**
   - Da exchange, withdrawal su rete Polygon (non Ethereum — gas bassissimo)
   - Indirizzo: il wallet connesso a Polymarket
   - Costo: ~$0.01-0.10 in gas fee su Polygon

3. **Deposita su Polymarket CLOB**
   - L'USDC su Polygon e' gia' utilizzabile dal CLOB
   - Il bot usa l'API CLOB per piazzare ordini
   - I fondi restano nel tuo wallet Polygon (non-custodial)

### Sicurezza

| Aspetto | Dettaglio |
|---|---|
| **Custodia** | Non-custodial: i fondi restano nel TUO wallet Polygon. Polymarket non ha accesso diretto. |
| **Chiavi API** | Le API key CLOB permettono solo trading, non withdrawal. Anche se compromesse, i fondi non possono essere trasferiti fuori. |
| **Importo consigliato** | 100-200 EUR massimo (come da piano). Mai piu' di quanto sei disposto a perdere. |
| **Circuit breaker** | Il bot si ferma automaticamente dopo 3 perdite consecutive o 15% drawdown giornaliero. |
| **Dry-run prima** | Obbligatorio: almeno 2 settimane di dry-run prima di qualsiasi denaro reale. |

### Credenziali necessarie per il live

```env
# Ottieni da: https://docs.polymarket.com/#clob-api
POLYMARKET_API_KEY=<clob-api-key>
POLYMARKET_SECRET=<clob-secret>
POLYMARKET_PASSPHRASE=<clob-passphrase>
POLYMARKET_FUNDER=<il-tuo-wallet-polygon-address>
```

**Attualmente NON necessarie.** Il LiveExecutor e' un placeholder che rifiuta tutti gli ordini con il messaggio "awaiting platform launch".

---

## 11. Passaggio a trading live

### Prerequisiti (tutti devono essere veri)

- [ ] Almeno 2 settimane di dry-run con metriche positive
- [ ] Win rate > 50% in dry-run
- [ ] Circuit breaker testato (ha scattato almeno una volta in dry-run)
- [ ] Piattaforma accessibile dall'Italia (Predict Street o alternativa)
- [ ] Regime fiscale chiarito con commercialista
- [ ] Telegram alert funzionante
- [ ] USDC depositato su Polygon (100-200 EUR max)

### Attivazione

```bash
# 1. Nel .env, cambia:
DRY_RUN=false

# 2. Aggiungi credenziali Polymarket (o piattaforma alternativa)

# 3. Prima in shadow mode (esegue dry-run + live in parallelo, compara risultati):
curl -X POST http://localhost:8000/api/v1/bot/mode/shadow

# 4. Dopo 1 settimana di shadow positivo, passa a live:
curl -X POST http://localhost:8000/api/v1/bot/mode/live
```

### Parametri di rischio (gia' configurati)

```yaml
risk:
  max_exposure_pct: 50.0      # massimo 50% del capitale deployato
  max_single_position_eur: 25  # massimo 25 EUR per posizione
  daily_loss_limit_eur: 20     # stop dopo 20 EUR persi in un giorno
  fixed_fraction_pct: 5.0      # 5% del capitale per trade (5-10 EUR)
  max_positions: 10            # massimo 10 posizioni aperte
  circuit_breaker:
    consecutive_losses: 3       # stop dopo 3 perdite di fila
    daily_drawdown_pct: 15.0    # stop se drawdown > 15%
    cooldown_minutes: 60        # pausa di 1 ora dopo il trip
```

---

## 12. Checklist admin post-setup

### Immediato (Giorno 1)

- [ ] Copiare `.env.example` in `.env` con configurazione minima
- [ ] Avviare uvicorn e verificare `/health`
- [ ] Aprire dashboard nel browser
- [ ] Chiamare `GET /markets` per verificare connessione API Polymarket
- [ ] Avviare dry-run: `POST /bot/start`
- [ ] Verificare nei log che il tick cycle funziona

### Prima settimana

- [ ] Creare bot Telegram e configurare alert
- [ ] Setup struttura Obsidian vault (`scripts/setup_vault.py`)
- [ ] Generare pattern seed (`scripts/seed_patterns.py`)
- [ ] Configurare plugin Obsidian Local REST API
- [ ] Lanciare fetch storico (`scripts/fetch_historical.py`)
- [ ] Eseguire primo backtest e analizzare risultati
- [ ] Personalizzare soglie in `config/config.yaml` se necessario

### Seconda settimana

- [ ] Analizzare metriche dry-run (win rate, Sharpe, drawdown)
- [ ] Decidere se attivare LLM enrichment
- [ ] Revisionare pattern Obsidian e curare manualmente quelli rilevanti
- [ ] Monitorare intelligence pipeline (GDELT anomaly, RSS)

### Quando/se si va live

- [ ] Consultare commercialista per regime fiscale
- [ ] Verificare accessibilita' piattaforma dall'Italia
- [ ] Depositare importo minimo (100 EUR)
- [ ] Shadow mode per 1 settimana
- [ ] Live mode solo dopo shadow positivo

---

## Note finali

Il sistema e' progettato per produrre valore anche **senza trading live**:
- Il Knowledge Graph cresce e migliora nel tempo
- I pattern validati in dry-run sono riutilizzabili su qualsiasi piattaforma
- L'intelligence pipeline monitora eventi indipendentemente dal trading
- Il backtesting permette di testare nuove strategie senza rischio

L'obiettivo primario non e' fare soldi subito, ma costruire un **sistema di intelligence** che comprende i mercati di previsione meglio della media.
