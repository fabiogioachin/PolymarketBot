# P1 -- Demo Mode: bot operativo con dati sintetici

## Obiettivo

Rendere il bot eseguibile end-to-end in `dry_run` mode senza dipendenze esterne.
Al termine di questa sessione: `python -m app.main` parte, il tick cycle gira,
il dashboard mostra metriche, e la config viene letta da `config/config.yaml`.

## Prerequisiti

- Python 3.11+, dipendenze installate (`pip install -r requirements.txt`)
- Nessun servizio esterno richiesto (no Obsidian REST API, no Polymarket WS, no GDELT)
- Vault Obsidian non necessario (intelligence.obsidian.enabled = false in demo)

## Contesto architetturale

Il bot ha 3 execution mode (`app/core/yaml_config.py` campo `execution.mode`):
- `dry_run` (default) -- simula ordini con `DryRunExecutor` + `PolymarketClobClient` in-memory
- `shadow` -- ordini reali loggati ma non eseguiti
- `live` -- ordini reali via CLOB API

In questa sessione lavoriamo SOLO su `dry_run`. Il `PolymarketClobClient`
(in `app/clients/polymarket_clob.py`) simula fills con slippage.

### File coinvolti (scope esclusivo)

**Da creare:**
- `config/config.yaml` (copia da `config/config.example.yaml`, con tuning demo)
- `scripts/ingest_resolutions.py` (popola `ResolutionDB` con dati sintetici)

**Da modificare:**
- `.gitignore` (aggiungere `config/config.yaml`)
- `app/services/market_service.py` (fallback mercati demo se API Polymarket non risponde)
- `app/core/dependencies.py` (graceful degradation se Obsidian/GDELT/RSS non disponibili)

**Da NON toccare:**
- `app/execution/engine.py`, `app/valuation/engine.py` -- gia funzionanti
- `app/clients/polymarket_ws.py` -- sara gestito in P2
- `app/services/intelligence_orchestrator.py` -- sara gestito in P2

---

## Task 1: Config reale + .gitignore

### 1a. Creare `config/config.yaml`

Copiare `config/config.example.yaml` e applicare queste modifiche per demo mode:

```yaml
app:
  dry_run: true

execution:
  mode: dry_run
  tick_interval_seconds: 30  # tick piu rapido per demo

intelligence:
  gdelt:
    enabled: false       # nessuna chiamata GDELT in demo
  rss:
    enabled: false       # nessuna chiamata RSS in demo
  obsidian:
    enabled: false       # nessun vault Obsidian in demo
  manifold:
    enabled: false       # gia disabilitato di default
```

Tutti gli altri valori (risk, valuation weights, strategies, telegram, llm)
restano quelli di `config.example.yaml`.

### 1b. Aggiungere a `.gitignore`

Aggiungere questa riga sotto il blocco "# Environment" (dopo `.env`):

```
config/config.yaml
```

Il file `config.yaml` contiene configurazione locale e non deve entrare nel repo.

---

## Task 2: Script `scripts/ingest_resolutions.py`

Creare uno script che popola `ResolutionDB` (`app/valuation/db.py`) con dati
sintetici per dare al `BaseRateAnalyzer` una base statistica su cui calcolare priors.

### Specifiche

- Usa `ResolutionDB.add_resolution()` che accetta `MarketResolution` (da `app/models/valuation.py`)
- `add_resolution()` usa `INSERT OR REPLACE` -- e idempotente, rieseguire e sicuro
- Lo schema `MarketResolution` ha questi campi:
  ```python
  class MarketResolution(BaseModel):
      market_id: str
      category: str          # "politics", "geopolitics", "economics", "crypto", "sports"
      question: str
      final_price: float     # 0.0 = resolved NO, 1.0 = resolved YES
      resolved_yes: bool
      resolution_date: datetime | None
      volume: float
      source: str = "polymarket"
  ```
- Genera almeno 50 risoluzioni plausibili, distribuite tra le 5 categorie principali
  (`politics`, `geopolitics`, `economics`, `crypto`, `sports`)
- `final_price` deve essere 0.0 o 1.0 (mercati risolti)
- Distribuzione realistica: ~55% YES, ~45% NO (base rate storica Polymarket)
- `source` = `"synthetic"` per distinguerli da dati reali futuri
- `volume` tra 10_000 e 500_000 (range realistico)
- `resolution_date` negli ultimi 6 mesi

### Pattern da seguire

Lo script `scripts/fetch_historical.py` gia esistente mostra il pattern:
`sys.path.insert(0, ...)`, `asyncio.run()`, argparse opzionale.

```python
"""Ingest synthetic resolution data for demo mode.

Populates ResolutionDB with realistic market resolutions
so that BaseRateAnalyzer has statistical priors.

Usage:
    python scripts/ingest_resolutions.py
"""
```

### Verifica

Dopo l'esecuzione:
- `data/resolutions.db` esiste e contiene 50+ righe
- `SELECT COUNT(*) FROM market_resolutions WHERE source = 'synthetic'` >= 50
- `SELECT category, COUNT(*) FROM market_resolutions GROUP BY category` mostra tutte e 5 le categorie

---

## Task 3: Mercati demo in `MarketService`

Il `MarketService.get_filtered_markets()` chiama l'API REST di Polymarket.
Se l'API non risponde (offline, rate limited, errore di rete), il tick cycle
si blocca con 0 mercati e non produce nessun segnale.

### Modifica richiesta

In `app/services/market_service.py`, nel metodo `get_filtered_markets()`:

1. Wrappare la chiamata API in try/except
2. Se fallisce, loggare un warning e ritornare una lista di 5-10 mercati demo statici

I mercati demo devono essere istanze valide di `Market` (da `app/models/market.py`)
con:
- `id`: stringa univoca (es. `"demo-politics-1"`)
- `question`: domanda plausibile
- `category`: un `MarketCategory` valido
- `outcomes`: lista di 2 `Outcome` con `token_id`, `outcome` ("Yes"/"No"), `price`
  - I `token_id` devono essere stringhe univoche (es. `"demo-token-politics-1-yes"`)
  - I prezzi YES+NO devono sommare a ~1.0 (es. 0.65 + 0.35)
- `end_date`: nel futuro (7-30 giorni da `datetime.now(tz=UTC)`)
- `volume`: > 0 (es. 50_000)
- `liquidity`: > 0 (es. 10_000)
- `status`: `MarketStatus.ACTIVE`

### NON fare

- Non creare un provider/factory separato. Basta un `_demo_markets()` privato inline.
- Non modificare la firma pubblica di `get_filtered_markets()`.

---

## Task 4: Graceful degradation in `dependencies.py`

Il file `app/core/dependencies.py` crea i singleton. Alcuni dipendono da servizi
esterni che in demo mode sono disabilitati.

### Verificare che:

1. `get_intelligence_orchestrator()` -- funziona anche se GDELT/RSS sono disabilitati
   (il flag `enabled: false` dovrebbe bastare, ma verificare che il codice non
   crashi al primo `tick()` quando i servizi sono off)
2. `get_execution_engine()` -- il parametro `intelligence_orchestrator` e passato
   solo se GDELT o RSS sono abilitati; altrimenti `None`
3. L'app parte senza errori con tutti i servizi intelligence disabilitati

Se qualcosa crasha, fixare con guard clauses minimali.

---

## Task 5: Smoke test end-to-end

### Sequenza di verifica

```bash
# 1. Popolare resolution DB
python scripts/ingest_resolutions.py

# 2. Avviare il bot
python -m app.main

# 3. Verificare nel log (logs/bot.log):
#    - "engine_started" appare
#    - "tick_completed" appare almeno 1 volta entro 60s
#    - Nessun traceback/exception non gestita
#    - markets_scanned > 0 (demo markets se API offline)
#    - markets_assessed > 0

# 4. Verificare dashboard
#    - GET http://localhost:8000/api/v1/health -> 200
#    - GET http://localhost:8000/api/v1/dashboard/state -> 200 con dati
```

### Criteri di successo

- [ ] `python -m app.main` parte senza crash
- [ ] Almeno 1 tick completo nel log con `markets_assessed > 0`
- [ ] `ResolutionDB` ha dati sintetici
- [ ] `config/config.yaml` esiste e NON e in git (`git status` non lo mostra come tracked)
- [ ] Dashboard risponde su `/api/v1/health`

---

## Skill da consultare

- `~/.claude/skills/config-system/SKILL.md` -- come funziona il dual config (env + YAML)
- `~/.claude/skills/execution-modes/SKILL.md` -- dry_run mode, tick cycle, position management

## Note per l'agente

- Questo e un progetto Python con `structlog` (JSON format). Tutti i log vanno con `logger.info()`, `logger.warning()`, etc.
- Non aggiungere dipendenze npm/pip non gia in requirements.txt
- I mercati demo sono un FALLBACK, non un replacement. Se l'API Polymarket risponde, usare i dati reali.
- Non toccare il ValuationEngine ne l'ExecutionEngine -- sono gia testati e funzionanti.
