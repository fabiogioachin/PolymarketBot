# S5b — Dashboard operativa: widget minori + cache bust

| **Modello consigliato** | **Effort** | **Wave** | **Parallelizzabile con** |
|--------------------------|-----------|----------|---------------------------|
| **Sonnet 4.6** (200K context) | **basso** | W5 | **S5a** (scope file disgiunti) |

**Perché Sonnet 4.6:** extend SSE payload + 3 widget incrementali (link, tile counter, sparkline column). Specs chiare. Pattern vanilla JS già assimilato dalla dashboard esistente. Context 200K abbondante.

**Parallelizzazione con S5a:** zero overlap. S5b modifica `static/index.html`, `static/js/app.js`, `static/css/style.css` (root). S5a scrive in `static/dss/*` (directory separata).

---

## Obiettivo

Estendere dashboard operativo esistente (porta **5174**) con: link "Apri DSS" verso **:5175**, sparkline volatility nelle righe posizioni aperte, tile "Whale alerts (1h)" nell'header. **NO Chart.js** (mantiene vanilla JS coerente).

## Dipendenze

**S4b committed** (external_signals popolati, `ValuationResult` ha `realized_volatility`).
**S5a consigliato** (link ha senso con DSS up).

## File master

- [../00-decisions.md](../00-decisions.md) — tile nel dashboard deve collegare a **D5** (DSS architettura)

## File da leggere all'avvio

- [static/index.html](static/index.html)
- [static/js/app.js](static/js/app.js) (`renderPositions` a **riga ~311**, NON 191-307 come erroneamente citato in piani precedenti)
- [static/css/style.css](static/css/style.css) (design tokens)
- [docker/nginx.conf](docker/nginx.conf) (**path corretto, NON `nginx/nginx.conf`**)
- [app/monitoring/dashboard.py](app/monitoring/dashboard.py) (SSE stream `_build_full_state`)

## Skills / Agenti / MCP

- Skill [.claude/skills/api-dashboard/SKILL.md](.claude/skills/api-dashboard/SKILL.md)
- Agente `frontend-specialist`, `backend-specialist` (per SSE extend)
- MCP `mcp__Claude_in_Chrome__*` per smoke test

---

## Step esecutivi

**STEP 1 — SSE payload extend** (backend). In [app/monitoring/dashboard.py](app/monitoring/dashboard.py) `_build_full_state()`: per ogni posizione aperta, includi `realized_volatility` e `price_history_last_60min` (array di 60 float, uno per minuto). Mantieni backward compat (campi opzionali).

**STEP 2 — Link DSS** (frontend). In [static/index.html](static/index.html) header aggiungi:
```html
<a href="http://localhost:5175/dss.html" target="_blank" class="btn-dss" 
   title="Decision Support — sempre disponibile anche con backend spento">
  📊 Open DSS Artifact
</a>
```

**STEP 3 — Sparkline volatility**. In [static/js/app.js](static/js/app.js) `renderPositions()` (riga ~311):
- Aggiungi colonna "Vol 1h" che mostra `realized_volatility` formattato + sparkline ASCII
- Riusa funzione `renderSparkline` da S5a (duplicala inline per indipendenza, è 5 righe)
- Color code cella: verde `<0.01`, giallo `0.01-0.03`, rosso `>0.03`

**STEP 4 — Whale alerts counter** (header). Nel blocco metrics aggiungi tile "🐋 Whales (1h)":
```javascript
async function refreshWhaleCounter() {
  const r = await fetch('/api/v1/intelligence/whales?since=1h');
  const whales = await r.json();
  document.getElementById('m-whales-1h').textContent = whales.length;
}
setInterval(refreshWhaleCounter, 30_000);
```

**STEP 5 — Cache bust** (lesson 2026-04-15).
- In [static/index.html](static/index.html) incrementa `?v=N` su TUTTI `<script>` e `<link>` a `?v=14`
- In [docker/nginx.conf](docker/nginx.conf) verifica presenza `Cache-Control: no-store` per `/static/`. Se manca, aggiungi.

**STEP 6 — CSS**. In [static/css/style.css](static/css/style.css) aggiungi:
```css
.btn-dss { /* ... */ }
.sparkline-cell { font-family: monospace; letter-spacing: -1px; }
.vol-green { color: var(--success); }
.vol-yellow { color: var(--warning); }
.vol-red { color: var(--danger); }
.whale-counter { /* tile style */ }
```
Segui design tokens esistenti (GitHub dark palette).

**STEP 7 — Browser MCP smoke test**.
```bash
docker compose --profile full down
docker compose --profile full up -d --build
sleep 30
# Via mcp__Claude_in_Chrome__navigate:
# 1. Apri http://localhost:5174
# 2. Verifica tile "Whales" header, link DSS, colonna Vol nelle posizioni
# 3. Click link DSS → apre :5175 in nuovo tab
# 4. Hard reload: check network tab → app.js?v=14 caricato (no 304)
```

---

## Verification

```bash
python -m pytest tests/ -q                    # atteso: 730+ pass (nessuna regressione)
python -m ruff check app/
docker compose --profile full down && docker compose --profile full up -d --build
sleep 30
curl http://localhost:5174 | grep 'v=14'                           # cache bust verificato
curl http://localhost:8000/api/v1/dashboard/stream | head -50      # SSE include realized_volatility
# Browser MCP smoke test (vedi STEP 7)
```

## Commit message proposto

```
feat(dashboard): DSS link + volatility sparkline + whale counter (Phase 13 S5b)

- SSE payload includes realized_volatility + price_history_60min per open position
- Header: link to DSS artifact on :5175 + whale alerts counter (1h, refresh 30s)
- Positions table: Vol 1h column with ASCII sparkline (▁▂▃▄▅▆▇█) and color coding
- Cache bust: static asset version bumped to v=14 (lesson 2026-04-15)
- Browser MCP smoke test: both dashboards operational
```

## Handoff — Phase 13 DONE

Checklist finale:
- Dashboard operativo (:5174): tile whale, link DSS, sparkline vol posizioni ✓
- DSS artifact (:5175): fresh quando full profile, stale con banner quando dss-only ✓
- Cache-Control corretto su `/static/` (no stale JS) ✓
- `pytest tests/ -q`: 730+ pass, 0 fail ✓
- `ruff check` clean, `mypy` clean ✓
- Browser MCP smoke test: entrambi i frontend operativi ✓

Phase 13 complete. Prossima: **Phase 14 — WebSocket trade stream + wallet clustering** (vedi `00-decisions.md` Open items).
