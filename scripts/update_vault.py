"""Update Obsidian vault with decisions from the review session."""

import json
import os
import urllib.parse
import urllib.request

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
        urllib.request.urlopen(req, timeout=10)
        print(f"  OK: {path}")
    except Exception as e:
        print(f"  FAIL: {path} -> {e}")


def read_note(path: str) -> str | None:
    encoded = urllib.parse.quote(path, safe="/")
    req = urllib.request.Request(
        f"{BASE}/vault/{encoded}",
        headers={"Authorization": f"Bearer {KEY}", "Accept": "text/markdown"},
    )
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        return resp.read().decode()
    except Exception:
        return None


NOTES = {
    # ── New Decision: Realistic Simulation ──────────────────
    "Projects/PolymarketBot/Decisions/Realistic Dry-Run Simulation.md": """\
---
type: decision
project: "[[PolymarketBot]]"
status: active
domain: [Trading, Simulation]
created: 2026-04-05
---

# Realistic Dry-Run Simulation

## Contesto

La simulazione iniziale era falsa: fill istantanei senza slippage, P&L basato su oscillazioni di prezzo (non su vendita/risoluzione), stop-loss su rumore di mercato. Non rispecchiava la meccanica reale di Polymarket.

## Decisione

Riscrittura completa del CLOB simulato per rispecchiare la realta:
- Fill con slippage proporzionale alla size dell'ordine
- Size limitata al 10% della profondita dell'orderbook
- P&L realizzato SOLO su vendita secondaria o risoluzione del mercato
- No stop-loss su oscillazioni — i prediction markets sono eventi binari
- Resolution tracker: monitora mercati risolti, payout $1 o $0

## Alternative considerate

1. **Simulazione semplificata** (scartata): fill istantanei nascondono i costi reali
2. **Backtest su dati storici** (complementare, non sostitutivo): non testa il flusso live
3. **Simulazione realistica** (scelta): unica differenza dal live e la liquidita simulata vs reale

## Conseguenze

- Lo slippage riduce equity realmente (~1 EUR su 150 per sessione)
- Position exit basata su: take profit (+50%), edge reversed, near expiry (<12h)
- Il bot non puo piu "fare soldi" solo perche un prezzo oscilla di 0.001

## Collegato a

- [[Value Assessment]] — il motore che genera l'edge
- [[Prediction Markets]] — la meccanica di payout binario
- [[Position Sizing]] — il sizing ora tiene conto dello slippage
""",

    # ── New Decision: SSE Dashboard ─────────────────────────
    "Projects/PolymarketBot/Decisions/SSE Real-Time Dashboard.md": """\
---
type: decision
project: "[[PolymarketBot]]"
status: active
domain: [Architecture, Frontend]
created: 2026-04-05
---

# SSE Real-Time Dashboard

## Contesto

La dashboard usava polling ogni 10s con auto-refresh toggle. Dati non persistevano tra sessioni, posizioni non mostravano dettagli.

## Decisione

Server-Sent Events (SSE) per push unidirezionale dal server. Un endpoint `/stream` invia lo stato completo ad ogni tick. Il frontend si connette con EventSource, auto-reconnect dopo 3s.

## Alternative considerate

1. **Polling** (scartato): ritardo fino a 10s, traffico inutile, toggle manuale
2. **WebSocket bidirezionale** (overkill): il client non invia mai dati al server
3. **SSE** (scelto): unidirezionale, nativo browser, auto-reconnect, zero dipendenze

## Conseguenze

- Dashboard si aggiorna in <1s dal tick
- Indicatore "Live" verde nel header
- Nessun toggle auto-refresh necessario
- Persistenza SQLite per trades, posizioni, balance — sopravvive ai restart

## Collegato a

- [[PolymarketBot]] — progetto che implementa questa dashboard
""",

    # ── New Decision: Equity-Relative Risk Limits ───────────
    "Projects/PolymarketBot/Decisions/Equity-Relative Risk Limits.md": """\
---
type: decision
project: "[[PolymarketBot]]"
status: active
domain: [Trading, Risk Management]
created: 2026-04-05
---

# Equity-Relative Risk Limits

## Contesto

I limiti di rischio erano valori fissi in EUR (max_single=25 EUR, daily_loss=20 EUR). Con capitale variabile, i limiti fissi diventano troppo larghi o troppo stretti.

## Decisione

Il config YAML accetta sia valori fissi che percentuali dell'equity:
- `max_single_position_eur: "5%"` → 5% dell'equity corrente
- `daily_loss_limit_eur: 20.0` → fisso 20 EUR

Il RiskManager risolve le percentuali a runtime contro l'equity attuale.

## Alternative considerate

1. **Solo fissi** (scartato): non scala con l'equity
2. **Solo percentuali** (troppo rigido): a volte serve un cap fisso
3. **Ibrido** (scelto): il tipo del valore YAML determina il comportamento

## Conseguenze

- `_parse_limit("5%")` → (5.0, True); `_parse_limit(25.0)` → (25.0, False)
- I limiti si adattano automaticamente se l'equity cresce o cala
- Backward-compatible: valori numerici funzionano come prima

## Collegato a

- [[Position Sizing]] — il sizing usa gli stessi limiti risolti
- [[Circuit Breaker Pattern]] — il circuit breaker ha i suoi limiti separati (sempre %)
""",

    # ── New Knowledge: Prediction Market Simulation ─────────
    "Knowledge/Trading/Prediction Market Simulation.md": """\
---
type: concept
domain: [Trading, Simulation]
aliases: [dry-run simulation, paper trading prediction markets]
created: 2026-04-05
---

# Prediction Market Simulation

## Cos'e

Simulazione di trading su mercati predittivi che rispecchia la meccanica reale. Diversa dal paper trading di equities perche gli strumenti sono binari (payout $1 o $0).

## Come funziona

### Differenze chiave da equities paper trading
- **No stop-loss su oscillazioni**: un prediction market risolve a 0 o 1, le oscillazioni intermedie sono rumore
- **P&L solo su evento**: il profitto si realizza quando il mercato risolve o quando vendi sul secondario
- **Slippage reale**: ordini grandi muovono il prezzo proporzionalmente alla size
- **Liquidita limitata**: non puoi comprare 10000 shares su un mercato con $100 di volume

### Exit conditions corrette per prediction markets
1. Take profit: prezzo salito abbastanza per vendere con profitto sul secondario
2. Edge reversed: la valutazione ora dice che il fair value e inferiore all'entry
3. Near expiry: il mercato sta per risolvere e il prezzo non e in tuo favore
4. Resolution: il mercato ha risolto — payout automatico

### Anti-pattern da evitare
- Stop loss su -5%: su mercati a 0.03, una fluttuazione di 0.001 e il 3% ma non significa nulla
- P&L unrealizzato come metrica di performance: e solo indicativo
- Fill senza slippage: nasconde il costo reale di esecuzione

## Collegato a

- [[Prediction Markets]] — il mercato sottostante
- [[Position Sizing]] — il sizing deve tenere conto dello slippage
- [[PolymarketBot]] — implementazione concreta
""",
}

print(f"Updating {len(NOTES)} notes...")
for path, content in NOTES.items():
    put_note(path, content)

# Update MOC with new decisions
print("\nUpdating MOC links...")
moc = read_note("Projects/PolymarketBot/PolymarketBot.md")
if moc and "Realistic Dry-Run" not in moc:
    # Add new links to Collegato a section
    moc = moc.replace(
        "- [[Token Bucket Rate Limiting]] - rate limiting API",
        "- [[Token Bucket Rate Limiting]] - rate limiting API\n"
        "- [[Prediction Market Simulation]] - meccanica di simulazione realistica",
    )
    put_note("Projects/PolymarketBot/PolymarketBot.md", moc)

print("\nDone!")
