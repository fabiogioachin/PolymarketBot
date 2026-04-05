"""Populate Obsidian vault with PolymarketBot project knowledge."""

import json
import os
import urllib.parse
import urllib.request

# Load API key
with open(os.path.expanduser("~/.claude/settings.json")) as f:
    data = json.load(f)
    KEY = data["mcpServers"]["obsidian"]["env"]["OBSIDIAN_API_KEY"]

BASE = "http://127.0.0.1:27123"


def put_note(path: str, content: str) -> None:
    encoded = urllib.parse.quote(path, safe="/")
    req = urllib.request.Request(
        f"{BASE}/vault/{encoded}",
        data=content.encode("utf-8"),
        method="PUT",
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "text/markdown"},
    )
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        print(f"  OK: {path}")
    except Exception as e:
        print(f"  FAIL: {path} -> {e}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Knowledge/ notes — reusable concepts
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

NOTES = {
    # ── Knowledge/Trading/ ──────────────────────────────────
    "Knowledge/Trading/Prediction Markets.md": """\
---
type: concept
domain: [Trading, Finance]
aliases: [mercati predittivi, prediction market, event contracts]
created: 2026-04-04
---

# Prediction Markets

## Cos'e

Mercati dove si scambiano contratti il cui valore dipende dall'esito di eventi futuri. Ogni contratto YES/NO vale 0-1 USDC e risolve a 0 o 1.

## Come funziona

- Prezzo YES = probabilita implicita dell'evento
- YES + NO = 1.0 (in assenza di fee). Deviazioni = arbitraggio
- Risoluzione basata su fonti predefinite (regole del mercato)
- On-chain su Polygon (Polymarket), CLOB per ordini limit

### Vantaggi per trading automatizzato
- Meno efficiente di equities/crypto (meno smart money)
- Fee basse o zero su categorie geopolitiche
- Edge misurabile: fair_value vs market_price
- Mercati binari semplificano il modello

## Collegato a

- [[Strategie Polymarket]] — strategie di trading su prediction markets
- [[PolymarketBot]] — implementazione di trading bot
- [[Value Assessment]] — stima del fair value
""",

    "Knowledge/Trading/Value Assessment.md": """\
---
type: concept
domain: [Trading, Quantitative Finance]
aliases: [fair value estimation, valuation engine, value engine]
created: 2026-04-05
---

# Value Assessment

## Cos'e

Stima del fair value di un contratto predittivo combinando 8 segnali indipendenti con pesi configurabili. Il core del [[PolymarketBot]].

## Come funziona

### 8 segnali pesati (totale = 1.0)
| Segnale | Peso | Fonte |
|---------|------|-------|
| Base rate | 15% | Risoluzioni storiche per categoria |
| Rule analysis | 15% | Chiarezza/favorevolezza regole |
| Microstructure | 20% | Orderbook: spread, depth, liquidita |
| Cross-market | 10% | Correlazioni tra mercati |
| Event signal | 15% | GDELT anomalie, news |
| Pattern KG | 10% | Pattern Obsidian Knowledge Graph |
| Temporal | 10% | Decay temporale verso scadenza |
| Crowd calibration | 5% | Bias storico della folla |

### Formula
fair_value = weighted_sum / weight_total (solo segnali disponibili)
edge = fair_value - market_price
fee_adjusted_edge = edge * temporal_factor - fee_rate

### Recommendation
- STRONG_BUY: fee_adjusted_edge >= 0.15
- BUY: fee_adjusted_edge >= 0.05
- HOLD: edge sotto soglia o confidence bassa
- SELL/STRONG_SELL: edge negativo (market overpriced)

## Collegato a

- [[PolymarketBot]] — progetto che implementa questo engine
- [[Strategie Polymarket]] — consumano l'output del value engine
- [[Prediction Markets]] — il mercato sottostante
- [[Position Sizing]] — usa confidence per scalare la size
""",

    "Knowledge/Trading/Position Sizing.md": """\
---
type: concept
domain: [Trading, Risk Management]
aliases: [dimensionamento posizioni, Kelly criterion, fixed fraction]
created: 2026-04-05
---

# Position Sizing

## Cos'e

Algoritmi per determinare quanto capitale allocare per singolo trade, bilanciando rendimento atteso e rischio di rovina.

## Come funziona

### Metodi implementati
1. **Fixed Fraction** (default): 5% del capitale per trade, cap a 25 EUR
2. **Kelly Criterion**: f* = (p*b - q) / b, poi half-Kelly per sicurezza
3. **Confidence-scaled**: mappa confidence del segnale (0-1) a fraction (50-100% del fixed fraction)

### Limiti di rischio
- Max esposizione totale: 50% del capitale
- Max singola posizione: 25 EUR
- Max posizioni aperte: 10
- Daily loss limit: 20 EUR
- Circuit breaker: 3 loss consecutive O 15% drawdown

### Razionale half-Kelly
Kelly puro e troppo aggressivo per capitale piccolo (150 EUR). Half-Kelly riduce varianza del ~50% perdendo solo ~25% del rendimento atteso.

## Collegato a

- [[Value Assessment]] — la confidence alimenta il sizing
- [[Circuit Breaker Pattern]] — halt se i limiti vengono superati
- [[Strategie Polymarket]] — le strategie generano i segnali da dimensionare
""",

    # ── Knowledge/Tech/ ─────────────────────────────────────
    "Knowledge/Tech/Circuit Breaker Pattern.md": """\
---
type: concept
domain: [Tech, Trading, Risk Management]
aliases: [circuit breaker, interruttore automatico]
created: 2026-04-05
---

# Circuit Breaker Pattern

## Cos'e

Meccanismo di protezione che interrompe automaticamente il trading quando si verificano condizioni di perdita anomala, prevenendo la rovina del capitale.

## Come funziona

### Trigger
- N perdite consecutive (default: 3)
- Drawdown giornaliero oltre soglia (default: 15%)

### Comportamento
- Quando scatta: blocca tutti i nuovi ordini
- Cooldown configurabile (default: 60 minuti)
- Reset automatico a mezzanotte UTC (nuovo giorno di trading)
- Alert via Telegram quando scatta

### Usato in
- [[PolymarketBot]] — con parametri: 3 loss, 15% drawdown, 60min cooldown

## Collegato a

- [[Position Sizing]] — complementare: sizing previene, breaker reagisce
- [[Value Assessment]] — il breaker non valuta edge, solo P&L
""",

    "Knowledge/Tech/Token Bucket Rate Limiting.md": """\
---
type: concept
domain: [Tech, API Design]
aliases: [token bucket, rate limiter, rate limiting]
created: 2026-04-05
---

# Token Bucket Rate Limiting

## Cos'e

Algoritmo di rate limiting che permette burst controllati mantenendo un rate medio massimo. Superiore al semaforo (Semaphore) che limita solo la concorrenza, non il rate.

## Come funziona

- Bucket con N token (N = rate per secondo)
- Ogni richiesta consuma 1 token
- Token si ricaricano a rate costante (N/sec)
- Se bucket vuoto: await fino al prossimo token
- Burst: fino a N richieste istantanee (1 secondo di accumulo)

### Semaphore vs Token Bucket
- Semaphore(10): max 10 richieste concurrent, ma se completano in 1ms puoi fare 1000/sec
- TokenBucket(10): max 10 richieste/secondo, indipendente dalla latenza

### Usato in
- [[PolymarketBot]] — rate limiting su Gamma API e CLOB API (10 req/sec default)

## Collegato a

- [[Prediction Markets]] — le API Polymarket richiedono rate limiting
""",

    "Knowledge/Tech/GDELT.md": """\
---
type: concept
domain: [Tech, Intelligence, Data]
aliases: [GDELT Project, Global Database of Events]
created: 2026-04-05
---

# GDELT

## Cos'e

Database globale di eventi, linguaggio e tono dei media mondiali. Monitora broadcast, print e web news in 100+ lingue in near-realtime.

## Come funziona

### API utilizzate
- **DOC 2.0**: ricerca articoli per tema, attore, paese (gratis, rate limited)
- **GeoJSON**: eventi geolocalizzati per area
- **BigQuery**: accesso completo (gratis con account Google)

### Metriche chiave
- **Volume**: conteggio articoli per tema/attore nel tempo
- **Tone**: sentiment medio degli articoli (-10 a +10)
- **GCAM**: 2000+ dimensioni emotive e tematiche

### Pattern di anomalia
- Volume spike: 2x la media mobile 7 giorni
- Tone shift: 1.5 punti dalla baseline

### Usato in
- [[PolymarketBot]] — watchlist tematica (ELECTION, INFLATION, CONFLICT, ecc.)

## Collegato a

- [[Value Assessment]] — alimenta il segnale event_signal (peso 15%)
- [[Prediction Markets]] — gli eventi GDELT muovono i mercati predittivi
""",

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Projects/ notes — project-specific
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    "Projects/PolymarketBot/Decisions/Value Engine as Core.md": """\
---
type: decision
project: "[[PolymarketBot]]"
status: active
domain: [Trading, Architecture]
created: 2026-04-04
---

# Value Engine as Core

## Contesto

Il bot necessita di un meccanismo centrale per decidere se tradare. Le alternative erano: rule-based puro, ML-driven, o value assessment.

## Decisione

Il **Value Assessment Engine** e il core: tutto il resto (strategie, intelligence, KG) e input o output di questo motore. Il prezzo puo essere mispriced anche senza eventi — il value engine valuta sempre.

## Alternative considerate

1. **Rule-based puro**: fragile, non scala con nuovi domini
2. **ML-driven**: richiede dati storici che non abbiamo, black box
3. **Value assessment** (scelto): trasparente, componibile, funziona anche con pochi dati

## Conseguenze

- 8 segnali indipendenti con pesi configurabili
- Ogni strategia riceve il ValuationResult, non inventa il suo
- Nuovi segnali = nuovi pesi, non nuova architettura
- LLM usato solo come trigger supplementare, mai come decisore

## Collegato a

- [[Value Assessment]] — il concetto implementato
- [[Strategie Polymarket]] — consumano l'output
""",

    "Projects/PolymarketBot/Decisions/Multi-leg Arbitrage.md": """\
---
type: decision
project: "[[PolymarketBot]]"
status: active
domain: [Trading, Architecture]
created: 2026-04-05
---

# Multi-leg Arbitrage

## Contesto

L'arbitraggio YES+NO richiede l'acquisto di entrambi i token simultaneamente. Il protocollo strategia originale supportava solo Signal singolo.

## Decisione

BaseStrategy.evaluate ritorna `Signal | list[Signal] | None`. L'arbitrage strategy ritorna una lista di 2 Signal (YES leg + NO leg). L'execution engine normalizza tutto a lista.

## Alternative considerate

1. **Signal singolo con flag**: hacky, non estensibile
2. **Strategia che esegue direttamente**: viola separation of concerns
3. **Lista di Signal** (scelto): pulito, compatibile con strategie single-signal

## Conseguenze

- Ogni strategia puo ritornare N segnali (pair trading, hedging futuro)
- L'engine non assume mai Signal singolo
- Risk check applicato per-leg, non per-gruppo (migliorabile in futuro)

## Collegato a

- [[Strategie Polymarket]] — arbitrage e la strategia multi-leg
- [[Value Assessment]] — fornisce i prezzi per entrambi i leg
""",

    "Projects/PolymarketBot/Decisions/Daily Reset Architecture.md": """\
---
type: decision
project: "[[PolymarketBot]]"
status: active
domain: [Trading, Risk Management]
created: 2026-04-05
---

# Daily Reset Architecture

## Contesto

RiskManager e CircuitBreaker hanno limiti giornalieri (daily P&L, drawdown). Senza reset, dopo un giorno negativo il bot si blocca permanentemente.

## Decisione

BotService lancia un task asincrono `_daily_reset_loop` che dorme fino a mezzanotte UTC, poi resetta daily_pnl e circuit breaker con il capitale corrente.

## Alternative considerate

1. **Cron esterno**: aggiunge dipendenza, puo fallire silenziosamente
2. **Check ad ogni tick**: overhead, e il reset deve avvenire a un orario preciso
3. **asyncio.sleep fino a mezzanotte** (scelto): zero dipendenze, preciso, self-contained

## Conseguenze

- Il bot si auto-resetta ogni giorno a 00:00 UTC
- Il circuit breaker riparte con il capitale aggiornato (non quello iniziale)
- Se il bot viene riavviato intra-day, il reset avviene al prossimo midnight

## Collegato a

- [[Circuit Breaker Pattern]] — il breaker che viene resettato
- [[Position Sizing]] — il daily_pnl che viene azzerato
""",

    # ── Issues ──────────────────────────────────────────────
    "Projects/PolymarketBot/Issues/Review Bug Batch 2026-04-05.md": """\
---
type: issue
project: "[[PolymarketBot]]"
status: resolved
severity: high
domain: [Trading, Architecture]
created: 2026-04-05
---

# Review Bug Batch 2026-04-05

## Problema

11 bug trovati nella revisione completa del progetto. 3 P0 (crash/money loss), 5 P1 (incorrect behavior), 3 P2 (profitability).

## Causa

Sviluppo fase per fase senza integration testing end-to-end. Ogni modulo funzionava isolatamente ma l'assemblaggio aveva gap critici.

## Workaround

Tutti i bug corretti in sessione 8.1. I 3 piu critici:
1. **Order price = edge**: Signal non portava market_price, engine usava edge (~0.05) come prezzo ordine
2. **get_filtered_markets inesistente**: engine chiamava metodo mai implementato
3. **SELL token sbagliato**: vendere NO = bullish su YES (opposto dell'intento)

Test da 516 a 598, tutti verdi.

## Collegato a

- [[PolymarketBot]] — progetto affetto
- [[Value Assessment]] — il value engine era corretto, il problema era nel consumo dei risultati
""",

    # ── Tools ───────────────────────────────────────────────
    "Projects/PolymarketBot/Tools/Polymarket API.md": """\
---
type: tool
domain: [Trading, API]
project: "[[PolymarketBot]]"
url: "https://gamma-api.polymarket.com"
version: ""
created: 2026-04-04
---

# Polymarket API

## Cos'e

Due API principali per interagire con Polymarket:
- **Gamma API**: dati mercati, prezzi, metadata (REST)
- **CLOB API**: orderbook, ordini, posizioni (REST + WebSocket)

## Come si usa nel progetto

- `polymarket_rest.py`: client async con token bucket rate limiting (10 req/sec)
- `polymarket_clob.py`: mode-aware (dry_run simula fill, live non implementato)
- `polymarket_ws.py`: WebSocket per orderbook real-time con reconnect

### Gotcha
- outcomePrices e clobTokenIds sono stringhe JSON dentro JSON (non array diretti)
- Fee 0% su geopolitics/politics, fino a 7.2% su crypto
- Rate limit: ~10 req/sec prima di 429

## Collegato a

- [[Prediction Markets]] — il mercato accessibile via API
- [[Token Bucket Rate Limiting]] — rate limiting applicato
- [[PolymarketBot]] — progetto che usa queste API
""",
}

print(f"Creating {len(NOTES)} notes...")
for path, content in NOTES.items():
    put_note(path, content)

print("\nDone!")
