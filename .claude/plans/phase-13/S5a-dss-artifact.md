# S5a — DSS Live Artifact (standalone)

| **Modello consigliato** | **Effort** | **Wave** | **Parallelizzabile con** |
|--------------------------|-----------|----------|---------------------------|
| **Opus 4.7** (1M context) | **alto** | W5 | **S5b** (scope file disgiunti) |

**Perché Opus 4.7:** frontend standalone single-file con 4 dimensioni di complessità: (1) CORS fetch cross-origin, (2) WebSocket management, (3) localStorage cache con graceful degradation, (4) sparkline ASCII rendering. Nessun build tool. 1M context permette analisi simultanea di pattern HTML/CSS/JS esistenti + schema snapshot + API references per non sbagliare contratto dati.

**Parallelizzazione con S5b:** zero overlap. S5a scrive in `static/dss/*` (directory nuova). S5b modifica `static/index.html`, `static/js/app.js`, `static/css/style.css` (root esistente).

---

## Obiettivo

Creare `static/dss/dss.html` + `dss.js` + `dss.css` — Decision Support System frontend che gira su nginx profile `dss-only`, fetcha direttamente `clob.polymarket.com` + subgraph + `intelligence_snapshot.json`.

## Dipendenze

**S4a committed** (schema snapshot + profilo dss-only).
**S4b consigliato ma non bloccante** (il DSS può leggere snapshot anche senza whale_pressure computed — i campi saranno vuoti ma il layout funziona).

## File master

- [../00-decisions.md](../00-decisions.md) — **D5** (architettura DSS dati, CORS verdict)

## File da leggere all'avvio

- [static/index.html](static/index.html), [static/js/app.js](static/js/app.js), [static/css/style.css](static/css/style.css) (pattern vanilla JS, design tokens da riusare)
- [app/models/dss_snapshot.py](app/models/dss_snapshot.py) (schema JSON contratto dati — da S4a)
- [docker/docker-compose.yml](docker/docker-compose.yml), [docker/nginx-dss.conf](docker/nginx-dss.conf) (da S4a)

## Skills / Agenti / MCP

- Skill [.claude/skills/api-dashboard/SKILL.md](.claude/skills/api-dashboard/SKILL.md)
- Agente `frontend-specialist`, `code-reviewer`
- MCP `mcp__Claude_in_Chrome__*` per smoke test browser

**Codex-First candidate.** Frontend vanilla JS puro, zero build tool — delegabile a Codex con spec chiari, mentre orchestrator verifica via browser MCP in parallelo.

---

## Step esecutivi

**STEP 1 — HTML shell.** Crea `static/dss/dss.html`:
- Single-file OR split in `dss.html` + `dss.css` + `dss.js`
- Layout: header con stato snapshot (fresh/stale/missing), 4 sezioni collassabili:
  1. **Monitored Markets** — tabella con `edge_dynamic`, `realized_vol`, recommendation, sparkline ASCII del prezzo (da CLOB fetch)
  2. **Whale Feed Live** — feed real-time trades da CLOB + badge insider/pre-res dal snapshot
  3. **Popular Markets + Leaderboard** — tab interno 2 sottosezioni
  4. **VAE Signal Breakdown** — per market monitored, breakdown contributi pesati al fair_value (11 signals)
- Dark theme coerente con `static/css/style.css` (riusa CSS variables).

**STEP 2 — Data layer (`dss.js`).**
```javascript
async function fetchSnapshot() {
  try {
    const r = await fetch('./intelligence_snapshot.json', {cache: 'no-store'});
    if (!r.ok) throw new Error('fetch fail');
    const data = await r.json();
    localStorage.setItem('last_snapshot', JSON.stringify(data));
    localStorage.setItem('last_fetch_ts', Date.now().toString());
    return {data, stale: false};
  } catch (e) {
    const cached = localStorage.getItem('last_snapshot');
    if (!cached) return {data: null, stale: true, empty: true};
    return {data: JSON.parse(cached), stale: true};
  }
}

async function fetchClobPrice(marketId) {
  // CORS aperto verificato (Codex review)
  const r = await fetch(`https://clob.polymarket.com/book?token_id=${marketId}`);
  return r.json();
}

// WebSocket per ticker real-time
const ws = new WebSocket('wss://ws-subscriptions-clob.polymarket.com/ws/market');
ws.onmessage = (ev) => updateTicker(JSON.parse(ev.data));
```

Polling: snapshot ogni 5 min, CLOB prices ogni 30s, WS real-time per market selezionato.

**STEP 3 — Sparkline ASCII.**
```javascript
function renderSparkline(prices) {
  const chars = ['▁','▂','▃','▄','▅','▆','▇','█'];
  const min = Math.min(...prices), max = Math.max(...prices);
  const range = max - min || 1;
  return prices.map(p => chars[Math.floor(((p - min) / range) * 7)]).join('');
}
```
Inline nella tabella Monitored Markets. Zero dipendenze esterne.

**STEP 4 — localStorage cache.** Schema: `{"last_snapshot": JSON, "last_fetch_ts": ts, "api_key_subgraph": "?"}`. Solo ultimo snapshot (no accumulation). Size <500KB garantito dal cap di S4a (<200KB).

**STEP 5 — Config externalization.** Endpoint CLOB/subgraph/path snapshot hardcoded in `dss.js` con override via localStorage `dss_config`.

**STEP 6 — Banner stato snapshot.**
```
✅ Intelligence fresh (updated 2m ago)
⚠️ Intelligence stale (last update 47m ago — backend may be down)
❌ No intelligence data (first run? start backend with `docker compose --profile full up`)
```

**STEP 7 — Accessibility + responsive.** Viewport meta, ARIA labels, keyboard nav modali. Stack verticale <768px.

**STEP 8 — Browser MCP smoke test.**
```bash
docker compose --profile dss-only up -d
# Via mcp__Claude_in_Chrome__navigate, read_console_messages:
# 1. Naviga http://localhost:5175/dss.html
# 2. Verifica banner stato, 4 sezioni popolate, WS connesso (network tab)
# 3. Verifica sparkline renderizzate
# Poi scenario "backend off":
docker compose --profile full down
docker compose --profile dss-only up -d
# Ricarica: CLOB prices ancora live (CORS), snapshot legge localStorage (stale banner)
```

---

## Verification

```bash
docker compose --profile dss-only up -d
curl http://localhost:5175/dss.html | head -20
curl http://localhost:5175/intelligence_snapshot.json | python -c "import json, sys; print(json.load(sys.stdin).get('generated_at'))"
# Browser MCP smoke test (vedi STEP 8)
```

## Commit message proposto

```
feat(dss): Decision Support System Live Artifact (Phase 13 S5a)

- static/dss/{dss.html,dss.js,dss.css} single-page DSS
- Direct fetch CLOB (CORS open, verified) + Subgraph + intelligence_snapshot.json
- WebSocket clob ticker for selected markets
- localStorage cache for offline snapshot (graceful degradation)
- Sparkline ASCII (▁▂▃▄▅▆▇█) — zero chart library dependencies
- 4 sections: monitored markets, whale feed, popular+leaderboard, VAE breakdown
- Served via frontend-dss on port 5175 (docker profile dss-only)
- Browser MCP smoke tested: works with backend ON and OFF
```

## Handoff

- DSS accessibile su `http://localhost:5175` anche con backend Python off
- Snapshot fresh quando full profile up (<5 min age)
- Stale banner visible quando dss-only
- CORS fetch verified in browser network tab
- WS connesso e riceve tick
