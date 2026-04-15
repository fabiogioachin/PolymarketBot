---
name: Prompt PD — Fix Intelligence/Knowledge data persistence
description: Diagnosi e fix del flusso dati che blocca il popolamento di Intelligence tab e Knowledge tab nel dashboard. Tre blocchi distinti: seed pattern mancante, IntelligenceOrchestrator non persistente tra tick, Risk KB vuoto all'avvio.
type: project
---

## Obiettivo

Identificare e correggere perche' le schede Intelligence e Knowledge del dashboard rimangono vuote nonostante i fix di Phase 11. Il problema ha tre radici distinte: i pattern KG non esistono ancora nel vault (seed mai eseguito), le anomalie dell'IntelligenceOrchestrator si perdono al restart, e il Risk KB non si popola abbastanza velocemente.

## Contesto

### Architettura rilevante

Il sistema ha due canali di persistenza delle informazioni strategiche:

1. **SQLite Risk KB** (`data/risk_kb.db`, `app/knowledge/risk_kb.py`) -- popola la Knowledge tab via `GET /api/v1/knowledge/strategies` e `GET /api/v1/knowledge/risks`. Viene scritto nel tick cycle di `ExecutionEngine` (step 5c in `app/execution/engine.py`, funzione `tick()`) ogni volta che un segnale viene generato da una strategia.

2. **Obsidian vault** (`app/knowledge/obsidian_bridge.py`) -- popola il `pattern_kg_signal` del VAE e persiste eventi GDELT. Acceduto via `KnowledgeService` (`app/services/knowledge_service.py`). Comunicazione via Obsidian REST API sulla porta 27123 (MCP server `obsidian` gia' configurato nell'ambiente).

### Problemi diagnosticati (da analisi del codice)

**Problema A — Pattern vault vuoto (ROOT CAUSE piu' probabile):**
`scripts/seed_patterns.py` non e' mai stato eseguito. La funzione `_fetch_kg_signals()` in `engine.py` chiama `knowledge_service.build_knowledge_context()` che internamente chiama `bridge.read_patterns(domain)` -- cartella `Projects/PolymarketBot/Patterns/{domain}` nel vault e' vuota -- `composite_signal` e' sempre 0.0. Il `pattern_kg_signal` (peso 0.10 nel VAE) non contribuisce mai.

**Problema B — IntelligenceOrchestrator state non persistente:**
`get_recent_anomalies()` legge `_anomaly_history` in-memory (lista in `IntelligenceOrchestrator.__init__`). Questa lista si azzera ad ogni restart del server FastAPI. La Intelligence tab mostra vuoto se il bot e' stato riavviato di recente e il prossimo tick GDELT non e' ancora arrivato (intervallo: 60 minuti).

Nota implementativa: `IntelligenceOrchestrator.__init__` (linea 17-28 di `intelligence_orchestrator.py`) non accetta nessun parametro per storage/persistenza. Per aggiungere persistenza servira' una modifica al costruttore (aggiungere un parametro `anomaly_store` o `trade_store`) E alla factory in `dependencies.py` che lo istanzia.

**Problema C — Risk KB vuoto all'avvio:**
Il Risk KB si popola solo durante il tick cycle quando ci sono segnali generati dalle strategie (step 5c in `engine.py`). Se il bot e' appena partito, il dashboard mostra "No data" fino al primo tick che produce segnali. Non c'e' nessuna query di debug che mostri quante righe esistono nel DB.

**Problema D — Knowledge tab JS mostra vuoto senza diagnostica:**
`GET /api/v1/knowledge/strategies` ritorna lista vuota se Risk KB ha 0 righe. Il frontend mostra "No strategies active yet" (gia' un messaggio decente -- vedi `app.js` linea 642-643) ma non distingue tra "vault non raggiungibile" e "vault vuoto" e "bot non ha ancora fatto un tick".

**Verifica rapida — Obsidian enabled nel config:**
`config/config.yaml` ha gia' `intelligence.obsidian.enabled: true` (linea 93). Non e' questo il problema. Tuttavia l'endpoint diagnostico (Fix 2) dovrebbe comunque riportare questo flag per completezza.

### File rilevanti

```
app/core/dependencies.py          — wiring knowledge_service (linee 184-187) + intelligence_orchestrator
app/services/knowledge_service.py — KnowledgeService (read_patterns, write_event, build_knowledge_context)
app/services/intelligence_orchestrator.py — tick() + _process_event() + _anomaly_history (linee 17-28 per __init__)
app/knowledge/obsidian_bridge.py  — HTTP bridge verso Obsidian REST API (port 27123)
app/knowledge/risk_kb.py          — SQLite RiskKnowledgeBase (upsert, get_all)
app/execution/engine.py           — tick(): step 2c _fetch_kg_signals, step 5c risk_kb upsert
app/api/v1/intelligence.py        — GET /intelligence/news, /anomalies, /watchlist
app/api/v1/knowledge.py           — GET /knowledge/strategies, /knowledge/risks
static/js/app.js                  — loadIntelligence(), loadKnowledge() JS functions
scripts/seed_patterns.py          — script da eseguire per popolare il vault (MAI eseguito)
config/config.yaml                — intelligence.obsidian.enabled (gia' true)
```

### Stack e convenzioni

- Python 3.11, FastAPI, async/await, aiosqlite
- Obsidian REST API: http://localhost:27123 (porta MCP), Bearer token in `.env` come `OBSIDIAN_API_KEY`
- `KnowledgeService` disabilitato se `app_config.intelligence.obsidian.enabled == false`
- `ObsidianBridge.write_note()` ritorna `False` se `not self._enabled` — silenziosamente
- Test: pytest + respx per mock HTTP. Nessun mock database (SQLite in-memory reale)
- Skill da consultare: `intelligence-source`, `api-dashboard`, `obsidian-kg`

## Vincoli

- Non modificare la struttura dei modelli Pydantic esistenti (`MarketKnowledge`, `AnomalyReport`, `NewsItem`)
- Non cambiare la firma pubblica di `assess_batch()` nel VAE
- Non toccare `config/config.yaml` direttamente — usare `config/config.example.yaml` come riferimento per la documentazione delle chiavi
- `scripts/seed_patterns.py` deve essere eseguito manualmente dopo il fix, non in automatico all'avvio
- Obsidian vault path: `C:\Users\fgioa\OneDrive - SYNESIS CONSORTIUM\Desktop\PRO\_ObsidianKnowledge`

## Output atteso

### Fix 1 — Endpoint diagnostico DB state

Aggiungere `GET /api/v1/knowledge/debug` che ritorna:
```json
{
  "risk_kb_rows": "<int>",
  "obsidian_enabled": "<bool>",
  "obsidian_reachable": "<bool>",
  "pattern_folders": ["politics", "economics", "..."],
  "pattern_counts": {"politics": 0, "economics": 0, "...": 0},
  "last_intelligence_tick": "<iso> | null",
  "anomaly_history_length": "<int>"
}
```
Questo endpoint permette di distinguere "vault non raggiungibile" da "vault vuoto" da "bot non ha ancora fatto un tick".

Nota: per il check `obsidian_reachable`, usare un HTTP GET a `http://localhost:27123/vault/` con timeout breve (2s). Non usare l'MCP server per questo check a runtime -- l'MCP e' per lo sviluppatore, l'endpoint e' per il dashboard.

### Fix 2 — Graceful fallback nel frontend

Nel file `static/js/app.js`, le funzioni `loadKnowledge()` e `loadIntelligence()` devono mostrare un messaggio contestuale:
- Se la risposta HTTP e' 200 ma la lista e' vuota: "Nessun dato disponibile — attendi il prossimo tick del bot oppure esegui `scripts/seed_patterns.py`"
- Se la risposta e' 4xx/5xx: mostrare il codice errore

Nota: `loadKnowledge()` ha gia' messaggi empty-state decenti (linee 642-643 e 671-672 di `app.js`). Valutare se i messaggi esistenti sono sufficienti o se vanno arricchiti con il suggerimento su `seed_patterns.py`.

### Fix 3 — Persistenza anomalie su SQLite

`IntelligenceOrchestrator._anomaly_history` e' in-memory e si perde al restart. Implementare:

1. **Schema tabella** `intelligence_events` in `data/trades.db` (usare TradeStore — gia' ha il pattern di persistenza stato):
   ```sql
   CREATE TABLE IF NOT EXISTS intelligence_events (
       id INTEGER PRIMARY KEY AUTOINCREMENT,
       detected_at TEXT NOT NULL,
       total_anomalies INTEGER DEFAULT 0,
       events_json TEXT DEFAULT '[]',
       news_json TEXT DEFAULT '[]',
       created_at TEXT DEFAULT CURRENT_TIMESTAMP
   )
   ```
   I campi `events_json` e `news_json` contengono `json.dumps()` delle liste serializzate con `.model_dump()`.

2. **Modifica al costruttore** di `IntelligenceOrchestrator`: aggiungere un parametro opzionale `trade_store: TradeStore | None = None`. Al `__init__`, se `trade_store` e' fornito, caricare gli ultimi 100 report dalla tabella per popolare `_anomaly_history`.

3. **Modifica alla factory** in `dependencies.py`: passare il `trade_store` all'`IntelligenceOrchestrator` quando lo si crea.

4. **Salvataggio**: in `IntelligenceOrchestrator.tick()`, dopo `self._anomaly_history.append(report)`, salvare il report nel DB.

### Test richiesti

1. **Test unitario per `GET /api/v1/knowledge/debug`** — verifica struttura risposta, tutti i campi presenti, tipi corretti
2. **Test che `GET /api/v1/knowledge/strategies` ritorna lista non vuota** quando il Risk KB contiene almeno un record con `strategy_applied` popolato (nota: un test simile esiste gia' in `tests/test_knowledge/test_risk_kb.py` linea 231-236 — verificare se e' sufficiente o se serve un test dedicato per il contesto integration)
3. **Test che `IntelligenceOrchestrator._anomaly_history` venga ripristinata al restart**: creare un `TradeStore(":memory:")`, salvare un `AnomalyReport` tramite `tick()`, creare un nuovo `IntelligenceOrchestrator` con lo stesso store, verificare che `get_recent_anomalies()` ritorna il report salvato

## Note

- Eseguire `scripts/seed_patterns.py` PRIMA di testare il pattern_kg_signal
- Il vault Obsidian deve essere aperto in Obsidian desktop per esporre il REST API server sulla porta 27123
- Skill da consultare prima di scrivere codice: `intelligence-source` (SKILL.md in `.claude/skills/intelligence-source/`), `api-dashboard`, `obsidian-kg` (SKILL.md in `.claude/skills/obsidian-kg/`)
- L'agente test-writer deve scrivere test separati per ogni fix, non un test monolitico
- Dopo ogni modifica: eseguire `pytest tests/test_services/test_intelligence_orchestrator.py tests/test_knowledge/ tests/test_api/ -v` e verificare 0 failures
