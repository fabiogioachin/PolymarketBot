// DSS — Decision Support System (vanilla JS, zero deps)
// Phase 13 S5a — served by nginx :5175, must work with backend OFF.

(() => {
  "use strict";

  // ── Config (override via localStorage 'dss_config' = JSON) ──────────
  const DEFAULT_CONFIG = {
    snapshot_path: "./intelligence_snapshot.json",
    snapshot_poll_ms: 5 * 60 * 1000,        // 5 min
    clob_base: "https://clob.polymarket.com",
    clob_poll_ms: 30 * 1000,                 // 30 s
    ws_url: "wss://ws-subscriptions-clob.polymarket.com/ws/market",
    ws_reconnect_initial_ms: 1000,
    ws_reconnect_max_ms: 30 * 1000,
    fresh_threshold_minutes: 10,
    sparkline_points: 30,
  };

  function loadConfig() {
    try {
      const override = JSON.parse(localStorage.getItem("dss_config") || "{}");
      return { ...DEFAULT_CONFIG, ...override };
    } catch {
      return { ...DEFAULT_CONFIG };
    }
  }

  const CFG = loadConfig();

  // ── State ───────────────────────────────────────────────────────────
  const state = {
    snapshot: null,
    snapshotStale: false,
    lastFetchTs: 0,
    selectedMarketId: null,
    clobBookCache: new Map(),       // tokenId -> {midpoint, history:[]}
    ws: null,
    wsBackoff: CFG.ws_reconnect_initial_ms,
  };

  // ── ASCII sparkline ────────────────────────────────────────────────
  const SPARK_CHARS = ["▁", "▂", "▃", "▄", "▅", "▆", "▇", "█"];
  function renderSparkline(prices) {
    if (!Array.isArray(prices) || prices.length === 0) return "";
    const min = Math.min(...prices);
    const max = Math.max(...prices);
    const range = max - min || 1;
    return prices
      .map((p) => SPARK_CHARS[Math.floor(((p - min) / range) * 7)])
      .join("");
  }

  // ── Banner / freshness ─────────────────────────────────────────────
  // PURE function — no DOM, no fetch. Exposed on window for testability.
  // Decides 4-tier staleness state given age in seconds.
  function getStalenessState(ageSeconds) {
    if (ageSeconds === null || ageSeconds === undefined || ageSeconds < 0) {
      return { level: "unknown", label: "No snapshot available", color: "gray", icon: "⚪" };
    }
    if (ageSeconds < 360) {  // < 6 min
      return {
        level: "fresh",
        label: `Updated ${Math.floor(ageSeconds)}s ago`,
        color: "green",
        icon: "🟢",
      };
    }
    if (ageSeconds < 600) {  // < 10 min
      return {
        level: "aging",
        label: `Aging — ${Math.floor(ageSeconds / 60)}m old`,
        color: "yellow",
        icon: "🟡",
      };
    }
    if (ageSeconds < 1800) {  // < 30 min
      return {
        level: "stale",
        label: `Stale — ${Math.floor(ageSeconds / 60)}m old`,
        color: "orange",
        icon: "🟠",
      };
    }
    return {
      level: "offline",
      label: `BACKEND OFFLINE — last update ${Math.floor(ageSeconds / 60)}m ago`,
      color: "red",
      icon: "🔴",
    };
  }
  // Expose for external testing (e.g. console / standalone unit test runner)
  window.getStalenessState = getStalenessState;

  // Compute age in seconds from snapshot.generated_at (ISO string).
  // Returns null when snapshot or generated_at is missing/invalid → triggers 'unknown' level.
  function snapshotAgeSeconds(snapshot) {
    if (!snapshot || !snapshot.generated_at) return null;
    const t = Date.parse(snapshot.generated_at);
    if (Number.isNaN(t)) return null;
    return Math.max(0, (Date.now() - t) / 1000);
  }

  const BANNER_LEVEL_CLASSES = [
    "banner-fresh",
    "banner-aging",
    "banner-stale",
    "banner-offline",
    "banner-unknown",
    "banner-missing", // legacy class kept for cleanup safety
  ];

  function updateBanner() {
    const el = document.getElementById("snapshot-banner");
    if (!el) return;

    const ageSeconds = snapshotAgeSeconds(state.snapshot);
    const stateInfo = getStalenessState(ageSeconds);

    // Reset classes, apply level-specific class
    el.classList.remove(...BANNER_LEVEL_CLASSES);
    el.classList.add(`banner-${stateInfo.level}`);

    // Render: icon + label, plus help text injected as sibling for stale/offline
    el.textContent = `${stateInfo.icon} ${stateInfo.label}`;

    // Manage help text node — sibling appended after the banner (sticky header area)
    let helpEl = document.getElementById("snapshot-banner-help");
    const needsHelp = stateInfo.level === "offline" || stateInfo.level === "stale";
    if (needsHelp) {
      if (!helpEl) {
        helpEl = document.createElement("div");
        helpEl.id = "snapshot-banner-help";
        helpEl.className = "banner-help";
        // Insert after banner element
        el.insertAdjacentElement("afterend", helpEl);
      }
      helpEl.textContent = "Run `POST /api/v1/bot/start` or check backend logs.";
    } else if (helpEl) {
      helpEl.remove();
    }
  }

  // ── Snapshot fetch + cache ─────────────────────────────────────────
  async function fetchSnapshot() {
    try {
      const r = await fetch(CFG.snapshot_path, { cache: "no-store" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      try {
        localStorage.setItem("last_snapshot", JSON.stringify(data));
        localStorage.setItem("last_fetch_ts", Date.now().toString());
      } catch (e) {
        console.warn("[DSS] localStorage write failed (quota?):", e);
      }
      state.snapshot = data;
      state.snapshotStale = false;
      state.lastFetchTs = Date.now();
      return { data, stale: false };
    } catch (e) {
      console.warn("[DSS] snapshot fetch failed, falling back to cache:", e);
      const cached = localStorage.getItem("last_snapshot");
      if (!cached) {
        state.snapshot = null;
        state.snapshotStale = true;
        return { data: null, stale: true, empty: true };
      }
      try {
        state.snapshot = JSON.parse(cached);
      } catch {
        state.snapshot = null;
        state.snapshotStale = true;
        return { data: null, stale: true, empty: true };
      }
      state.snapshotStale = true;
      state.lastFetchTs = Number(localStorage.getItem("last_fetch_ts") || "0");
      return { data: state.snapshot, stale: true };
    }
  }

  // ── CLOB direct fetch (CORS open per Codex review) ─────────────────
  async function fetchClobBook(tokenId) {
    if (!tokenId) return null;
    try {
      const r = await fetch(`${CFG.clob_base}/book?token_id=${encodeURIComponent(tokenId)}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return await r.json();
    } catch (e) {
      console.warn("[DSS] CLOB fetch failed for", tokenId, e);
      return null;
    }
  }

  function midpointFromBook(book) {
    if (!book || !Array.isArray(book.bids) || !Array.isArray(book.asks)) return null;
    if (book.bids.length === 0 || book.asks.length === 0) return null;
    const topBid = parseFloat(book.bids[book.bids.length - 1]?.price ?? book.bids[0]?.price);
    const topAsk = parseFloat(book.asks[0]?.price);
    if (!Number.isFinite(topBid) || !Number.isFinite(topAsk)) return null;
    return (topBid + topAsk) / 2;
  }

  function pushPrice(tokenId, price) {
    if (!Number.isFinite(price)) return;
    let entry = state.clobBookCache.get(tokenId);
    if (!entry) {
      entry = { midpoint: price, history: [] };
      state.clobBookCache.set(tokenId, entry);
    }
    entry.midpoint = price;
    entry.history.push(price);
    if (entry.history.length > CFG.sparkline_points) {
      entry.history.splice(0, entry.history.length - CFG.sparkline_points);
    }
  }

  async function refreshClobPrices() {
    if (!state.snapshot || !Array.isArray(state.snapshot.monitored_markets)) return;
    const ids = state.snapshot.monitored_markets
      .slice(0, 20)
      .map((m) => m.market_id)
      .filter(Boolean);

    await Promise.all(
      ids.map(async (id) => {
        const book = await fetchClobBook(id);
        const mid = midpointFromBook(book);
        if (mid !== null) pushPrice(id, mid);
      })
    );
    renderMarkets();
  }

  // ── WebSocket (CLOB ticker for selected market) ────────────────────
  function setWsPill(stateName) {
    const pill = document.getElementById("ws-pill");
    if (!pill) return;
    pill.classList.remove("ws-on", "ws-off", "ws-connecting");
    if (stateName === "open") {
      pill.classList.add("ws-on");
      pill.textContent = "WS live";
    } else if (stateName === "connecting") {
      pill.classList.add("ws-connecting");
      pill.textContent = "WS connecting…";
    } else {
      pill.classList.add("ws-off");
      pill.textContent = "WS off";
    }
  }

  function openWs() {
    if (!state.selectedMarketId) return;
    if (state.ws) {
      try { state.ws.close(); } catch {}
      state.ws = null;
    }
    setWsPill("connecting");
    let ws;
    try {
      ws = new WebSocket(CFG.ws_url);
    } catch (e) {
      console.warn("[DSS] WS construct failed:", e);
      scheduleWsReconnect();
      return;
    }
    state.ws = ws;

    ws.onopen = () => {
      state.wsBackoff = CFG.ws_reconnect_initial_ms;
      setWsPill("open");
      try {
        ws.send(JSON.stringify({
          type: "subscribe",
          channel: "market",
          markets: [state.selectedMarketId],
        }));
      } catch (e) {
        console.warn("[DSS] WS subscribe send failed:", e);
      }
    };

    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        const id = msg.market || msg.market_id || state.selectedMarketId;
        const price =
          parseFloat(msg.price) ||
          parseFloat(msg.midpoint) ||
          parseFloat(msg.last_price);
        if (Number.isFinite(price)) {
          pushPrice(id, price);
          renderMarkets();
        }
      } catch {
        // ignore non-JSON or malformed frames
      }
    };

    ws.onerror = (e) => {
      console.warn("[DSS] WS error:", e);
    };

    ws.onclose = () => {
      setWsPill("off");
      scheduleWsReconnect();
    };
  }

  function scheduleWsReconnect() {
    const delay = state.wsBackoff;
    state.wsBackoff = Math.min(delay * 2, CFG.ws_reconnect_max_ms);
    setTimeout(() => {
      if (state.selectedMarketId) openWs();
    }, delay);
  }

  // ── Rendering ──────────────────────────────────────────────────────
  function fmtNum(v, digits = 4) {
    if (v === null || v === undefined || Number.isNaN(v)) return "—";
    const n = Number(v);
    if (!Number.isFinite(n)) return "—";
    return n.toFixed(digits);
  }

  function fmtPct(v, digits = 2) {
    if (v === null || v === undefined || Number.isNaN(v)) return "—";
    const n = Number(v);
    if (!Number.isFinite(n)) return "—";
    return `${(n * 100).toFixed(digits)}%`;
  }

  function fmtUsd(v) {
    if (v === null || v === undefined || Number.isNaN(v)) return "—";
    const n = Number(v);
    if (!Number.isFinite(n)) return "—";
    if (Math.abs(n) >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
    if (Math.abs(n) >= 1_000) return `$${(n / 1_000).toFixed(1)}k`;
    return `$${n.toFixed(0)}`;
  }

  function shortAddr(addr) {
    if (!addr || typeof addr !== "string") return "—";
    if (addr.length <= 12) return addr;
    return `${addr.slice(0, 6)}…${addr.slice(-4)}`;
  }

  function shortMarket(id) {
    if (!id || typeof id !== "string") return "—";
    if (id.length <= 14) return id;
    return `${id.slice(0, 8)}…${id.slice(-4)}`;
  }

  function volClass(v) {
    if (!Number.isFinite(v)) return "";
    if (v < 0.01) return "vol-green";
    if (v < 0.03) return "vol-yellow";
    return "vol-red";
  }

  function escapeHtml(s) {
    if (s === null || s === undefined) return "";
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function renderMarkets() {
    const tbody = document.getElementById("tbody-markets");
    const count = document.getElementById("count-markets");
    if (!tbody || !count) return;
    const markets = state.snapshot?.monitored_markets || [];
    count.textContent = String(markets.length);

    if (markets.length === 0) {
      tbody.innerHTML = `<tr><td colspan="8" class="empty">No monitored markets in snapshot.</td></tr>`;
      return;
    }

    tbody.innerHTML = markets
      .map((m) => {
        const cache = state.clobBookCache.get(m.market_id);
        const spark = cache ? renderSparkline(cache.history) : "";
        const livePrice = cache?.midpoint;
        const vol = m.realized_volatility;
        const reco = m.recommendation || "—";
        const recoClass = reco.includes("BUY")
          ? "reco-buy"
          : reco.includes("SELL")
          ? "reco-sell"
          : "reco-hold";
        const outcomes = m.outcomes || {};
        // Case-insensitive lookup so backend can ship "Yes"/"YES"/"yes" etc.
        const findPrice = (label) => {
          const target = label.toLowerCase();
          for (const k of Object.keys(outcomes)) {
            if (k.toLowerCase() === target) return outcomes[k];
          }
          return null;
        };
        const yesPrice = findPrice("yes");
        const noPrice = findPrice("no");
        // Fallback: market_price is the YES probability by Polymarket convention.
        const yesShown = yesPrice ?? livePrice ?? m.market_price;
        const noShown = noPrice ?? (yesShown != null ? 1 - yesShown : null);
        return `
          <tr data-market-id="${escapeHtml(m.market_id)}">
            <td title="${escapeHtml(m.question)}">${escapeHtml((m.question || shortMarket(m.market_id)).slice(0, 60))}</td>
            <td class="num side-buy">${fmtNum(yesShown, 3)}</td>
            <td class="num side-sell">${fmtNum(noShown, 3)}</td>
            <td class="num">${fmtNum(m.fair_value, 3)}</td>
            <td class="num ${m.edge_dynamic > 0 ? "pos" : m.edge_dynamic < 0 ? "neg" : ""}">${fmtPct(m.edge_dynamic)}</td>
            <td class="num ${volClass(vol)}">${fmtPct(vol, 2)}</td>
            <td><span class="reco ${recoClass}">${escapeHtml(reco)}</span></td>
            <td class="sparkline-cell" title="Last ${cache?.history.length || 0} CLOB midpoints">${escapeHtml(spark)}</td>
          </tr>
        `;
      })
      .join("");
  }

  function renderWhales() {
    const tbody = document.getElementById("tbody-whales");
    const count = document.getElementById("count-whales");
    if (!tbody || !count) return;

    const whales = [
      ...(state.snapshot?.recent_whales || []),
      ...(state.snapshot?.recent_insiders || []).map((w) => ({ ...w, _insider: true })),
    ].sort((a, b) => Date.parse(b.timestamp) - Date.parse(a.timestamp));

    count.textContent = String(whales.length);

    if (whales.length === 0) {
      tbody.innerHTML = `<tr><td colspan="6" class="empty">No whale/insider activity in snapshot.</td></tr>`;
      return;
    }

    tbody.innerHTML = whales
      .slice(0, 100)
      .map((w) => {
        const sideClass = (w.side || "").toUpperCase() === "BUY" ? "side-buy" : "side-sell";
        const flags = [];
        if (w._insider || w.is_pre_resolution) flags.push(`<span class="badge badge-insider">insider</span>`);
        if (w.size_usd >= 1_000_000) flags.push(`<span class="badge badge-mega">$1M+</span>`);
        else if (w.size_usd >= 100_000) flags.push(`<span class="badge badge-whale">whale</span>`);
        const marketLabel = w.question
          ? w.question.slice(0, 60)
          : shortMarket(w.market_id);
        const marketTitle = w.question
          ? `${w.question} (${w.market_id})`
          : w.market_id;
        return `
          <tr>
            <td>${escapeHtml(new Date(w.timestamp).toLocaleTimeString())}</td>
            <td title="${escapeHtml(marketTitle)}">${escapeHtml(marketLabel)}</td>
            <td><code>${escapeHtml(shortAddr(w.wallet_address))}</code></td>
            <td><span class="${sideClass}">${escapeHtml(w.side || "—")}</span>${w.outcome ? ` <span class="outcome-badge">${escapeHtml(w.outcome)}</span>` : ""}</td>
            <td class="num">${fmtUsd(w.size_usd)}</td>
            <td>${flags.join(" ") || "—"}</td>
          </tr>
        `;
      })
      .join("");
  }

  function renderPopular() {
    const tbody = document.getElementById("tbody-popular");
    if (!tbody) return;
    const items = state.snapshot?.popular_markets_top20 || [];
    if (items.length === 0) {
      tbody.innerHTML = `<tr><td colspan="4" class="empty">No popular markets in snapshot.</td></tr>`;
      return;
    }
    tbody.innerHTML = items
      .map((m, i) => `
        <tr>
          <td>${i + 1}</td>
          <td title="${escapeHtml(m.question || m.title || "")}">${escapeHtml((m.question || m.title || shortMarket(m.market_id || m.id)).slice(0, 60))}</td>
          <td class="num">${fmtUsd(m.volume_24h ?? m.volume24h)}</td>
          <td class="num">${fmtUsd(m.liquidity)}</td>
        </tr>
      `)
      .join("");
  }

  function renderLeaderboard() {
    const tbody = document.getElementById("tbody-leaderboard");
    if (!tbody) return;
    const items = state.snapshot?.leaderboard_top50 || [];
    if (items.length === 0) {
      tbody.innerHTML = `<tr><td colspan="4" class="empty">No leaderboard data in snapshot.</td></tr>`;
      return;
    }
    tbody.innerHTML = items
      .map((t, i) => `
        <tr>
          <td>${i + 1}</td>
          <td><code>${escapeHtml(shortAddr(t.wallet_address || t.address))}</code></td>
          <td class="num">${fmtUsd(t.total_pnl ?? t.totalPnl)}</td>
          <td class="num">${fmtUsd(t.weekly_pnl ?? t.weeklyPnl)}</td>
        </tr>
      `)
      .join("");
  }

  function renderVae() {
    const tbody = document.getElementById("tbody-vae");
    const hint = document.getElementById("vae-hint");
    const select = document.getElementById("vae-market-select");
    if (!tbody || !hint || !select) return;

    const weights = state.snapshot?.weights || {};
    const markets = state.snapshot?.monitored_markets || [];

    // Populate select if needed
    const currentOpts = Array.from(select.options).map((o) => o.value).join(",");
    const newOpts = ["", ...markets.map((m) => m.market_id)].join(",");
    if (currentOpts !== newOpts) {
      select.innerHTML =
        `<option value="">—</option>` +
        markets
          .map((m) => `<option value="${escapeHtml(m.market_id)}">${escapeHtml((m.question || m.market_id).slice(0, 60))}</option>`)
          .join("");
      if (state.selectedMarketId) {
        select.value = state.selectedMarketId;
      }
    }

    const market = markets.find((m) => m.market_id === state.selectedMarketId);
    if (!market) {
      hint.textContent = "— select a monitored market";
      tbody.innerHTML = `<tr><td colspan="3" class="empty">No market selected.</td></tr>`;
      return;
    }

    hint.textContent = `${market.question?.slice(0, 60) || market.market_id}`;
    const rows = Object.entries(weights).map(([sig, w]) => {
      let note = "";
      if (sig === "whale_pressure") note = "0.5 = neutral, >0.5 = BUY pressure";
      else if (sig === "insider_pressure") note = "centered on market_price ±0.05";
      else if (sig === "cross_platform") note = "0 unless Manifold satellite enabled";
      return `
        <tr>
          <td><code>${escapeHtml(sig)}</code></td>
          <td class="num">${fmtNum(w, 3)}</td>
          <td class="muted small">${escapeHtml(note)}</td>
        </tr>
      `;
    });
    rows.push(`
      <tr class="row-total">
        <td><strong>fair_value</strong></td>
        <td class="num"><strong>${fmtNum(market.fair_value, 4)}</strong></td>
        <td class="muted small">edge_central=${fmtPct(market.edge_central)} | edge_dynamic=${fmtPct(market.edge_dynamic)}</td>
      </tr>
    `);
    tbody.innerHTML = rows.join("");
  }

  function renderAll() {
    updateBanner();
    renderMarkets();
    renderWhales();
    renderPopular();
    renderLeaderboard();
    renderVae();
  }

  // ── Interaction ────────────────────────────────────────────────────
  function setupCollapsibles() {
    document.querySelectorAll(".collapsible .card-head").forEach((btn) => {
      btn.addEventListener("click", () => toggleCollapsible(btn));
      btn.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          toggleCollapsible(btn);
        }
      });
    });
  }

  function toggleCollapsible(btn) {
    const expanded = btn.getAttribute("aria-expanded") === "true";
    btn.setAttribute("aria-expanded", String(!expanded));
    const bodyId = btn.getAttribute("aria-controls");
    const body = document.getElementById(bodyId);
    if (body) body.style.display = expanded ? "none" : "";
    const chev = btn.querySelector(".chev");
    if (chev) chev.textContent = expanded ? "▸" : "▾";
  }

  function setupTabs() {
    const tablist = document.querySelector(".tabs");
    if (!tablist) return;
    const buttons = Array.from(tablist.querySelectorAll(".tab-btn"));
    buttons.forEach((btn, idx) => {
      btn.addEventListener("click", () => activateTab(btn));
      btn.addEventListener("keydown", (e) => {
        if (e.key === "ArrowRight") {
          e.preventDefault();
          activateTab(buttons[(idx + 1) % buttons.length]);
        } else if (e.key === "ArrowLeft") {
          e.preventDefault();
          activateTab(buttons[(idx - 1 + buttons.length) % buttons.length]);
        }
      });
    });
  }

  function activateTab(btn) {
    const targetTab = btn.getAttribute("data-tab");
    document.querySelectorAll(".tab-btn").forEach((b) => {
      const active = b === btn;
      b.classList.toggle("active", active);
      b.setAttribute("aria-selected", String(active));
    });
    document.querySelectorAll(".tab-panel").forEach((p) => {
      p.classList.toggle("active", p.getAttribute("data-panel") === targetTab);
    });
  }

  function setupVaeSelect() {
    const select = document.getElementById("vae-market-select");
    if (!select) return;
    select.addEventListener("change", () => {
      state.selectedMarketId = select.value || null;
      renderVae();
      if (state.selectedMarketId) openWs();
    });
  }

  // ── Boot ───────────────────────────────────────────────────────────
  async function boot() {
    setupCollapsibles();
    setupTabs();
    setupVaeSelect();
    setWsPill("off");

    await fetchSnapshot();
    renderAll();
    refreshClobPrices().catch((e) => console.warn("[DSS] initial CLOB refresh failed:", e));

    setInterval(async () => {
      await fetchSnapshot();
      renderAll();
    }, CFG.snapshot_poll_ms);

    setInterval(() => {
      refreshClobPrices().catch((e) => console.warn("[DSS] CLOB refresh failed:", e));
    }, CFG.clob_poll_ms);

    // Re-evaluate staleness every 10s so banner level escalates without a fetch
    setInterval(updateBanner, 10 * 1000);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
