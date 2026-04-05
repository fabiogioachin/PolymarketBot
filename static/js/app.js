/**
 * PolymarketBot Dashboard — Frontend Logic
 * Vanilla JS, no external dependencies.
 * Data flow: SSE from /api/v1/dashboard/stream
 */

const API_BASE = "/api/v1/dashboard";
const SSE_RECONNECT_MS = 3000;

let currentTab = "trading";
let eventSource = null;

// ── Utility ──────────────────────────────────────────────────────────

function formatNum(val, decimals = 2) {
  if (val === null || val === undefined) return "\u2014";
  return Number(val).toFixed(decimals);
}

function setLastUpdated() {
  const el = document.getElementById("last-updated");
  if (el) el.textContent = "Updated " + new Date().toLocaleTimeString();
}

async function apiFetch(path) {
  const resp = await fetch(API_BASE + path);
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  return resp.json();
}

function showError(tabId, msg) {
  const banner = document.getElementById(`error-${tabId}`);
  if (banner) {
    banner.textContent = "Error: " + msg;
    banner.style.display = "block";
  }
}

function clearError(tabId) {
  const banner = document.getElementById(`error-${tabId}`);
  if (banner) banner.style.display = "none";
}

function truncate(str, maxLen) {
  if (!str) return "\u2014";
  return str.length > maxLen ? str.slice(0, maxLen) + "\u2026" : str;
}

function escapeHtml(str) {
  if (!str) return "";
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

// ── SSE Connection ───────────────────────────────────────────────────

function setSseStatus(connected) {
  const dot = document.getElementById("sse-dot");
  const label = document.getElementById("sse-label");
  if (dot) {
    dot.className = "status-dot" + (connected ? " running" : " tripped");
  }
  if (label) {
    label.textContent = connected ? "Live" : "Disconnected";
  }
}

function connectSSE() {
  if (eventSource) {
    eventSource.close();
  }

  eventSource = new EventSource(API_BASE + "/stream");

  eventSource.onopen = function () {
    setSseStatus(true);
    clearError("trading");
  };

  eventSource.onmessage = function (event) {
    try {
      const state = JSON.parse(event.data);
      handleSseState(state);
    } catch (err) {
      console.error("SSE parse error:", err);
    }
  };

  eventSource.onerror = function () {
    setSseStatus(false);
    eventSource.close();
    eventSource = null;
    setTimeout(connectSSE, SSE_RECONNECT_MS);
  };
}

function handleSseState(state) {
  clearError("trading");

  if (state.overview) {
    renderOverview(state.overview);
  }
  if (state.positions) {
    var posData = state.positions.positions || state.positions;
    renderPositions(posData);
  }
  if (state.trades) {
    renderTradeLog(state.trades);
  }

  setLastUpdated();
}

// ── Tab Switching ─────────────────────────────────────────────────────

function switchTab(tabId) {
  currentTab = tabId;

  document.querySelectorAll(".tab-btn").forEach(function (btn) {
    btn.classList.toggle("active", btn.dataset.tab === tabId);
  });

  document.querySelectorAll(".tab-content").forEach(function (pane) {
    pane.classList.toggle("active", pane.id === "tab-" + tabId);
  });

  // Config tab still uses fetch (static data, doesn't need SSE)
  if (tabId === "config") {
    loadConfig();
  }
}

// ── Trading Tab — Rendering ──────────────────────────────────────────

function renderOverview(data) {
  var bot = data.bot || {};
  var m = data.metrics || {};
  var cb = data.circuit_breaker || {};

  // Status dot
  var dot = document.getElementById("status-dot");
  var statusLabel = document.getElementById("status-label");
  if (dot) {
    dot.className = "status-dot" + (bot.running ? " running" : "") + (cb.tripped ? " tripped" : "");
  }
  if (statusLabel) {
    var modeText = bot.mode ? bot.mode.replace("_", " ") : "offline";
    statusLabel.textContent = bot.running ? "Running (" + modeText + ")" : "Stopped (" + modeText + ")";
  }

  // Metric cards
  set("m-total-trades", m.total_trades != null ? m.total_trades : 0);
  set("m-daily-pnl", (m.daily_pnl >= 0 ? "+" : "") + formatNum(m.daily_pnl) + " EUR");
  set("m-win-rate", formatNum(m.win_rate) + "%");
  set("m-equity", formatNum(m.equity) + " EUR");
  set("m-positions", m.open_positions != null ? m.open_positions : 0);
  set("m-cb-status", cb.tripped ? "TRIPPED" : "Normal");
  set("m-tick-count", bot.tick_count != null ? bot.tick_count : 0);

  // Color win-rate
  var wrEl = document.getElementById("m-win-rate");
  if (wrEl) wrEl.className = "metric-value " + (m.win_rate >= 50 ? "positive" : "negative");

  // Color daily pnl
  var pnlEl = document.getElementById("m-daily-pnl");
  if (pnlEl) pnlEl.className = "metric-value " + (m.daily_pnl >= 0 ? "positive" : "negative");

  // Circuit breaker color
  var cbEl = document.getElementById("m-cb-status");
  if (cbEl) cbEl.className = "metric-value " + (cb.tripped ? "negative" : "positive");
}

// ── Detail Popup ────────────────────────────────────────────────────

// Store data for popup access
var _positionsData = [];
var _tradesData = [];

function formatDate(iso) {
  if (!iso) return "\u2014";
  return iso.replace("T", " ").slice(0, 16);
}

function showPopup(data) {
  // Remove existing popup
  closePopup();

  var pnl = Number(data.pnl || data.unrealized_pnl || 0);
  var pnlCls = pnl > 0 ? "positive" : pnl < 0 ? "negative" : "";
  var pnlSign = pnl > 0 ? "+" : "";
  var question = data.question || "Market #" + (data.market_id || "?");
  var isClose = data.type === "close";
  var decision = data.decision || ((data.side || "") + " " + (data.outcome || ""));
  var costBasis = data.cost_basis || Number(data.size_eur || 0);

  var fields = "";

  // Decision
  fields += '<div class="popup-field"><div class="popup-field-label">Decision</div>' +
    '<div class="popup-field-value">' + escapeHtml(decision.trim() || data.side || "\u2014") + '</div></div>';

  // Strategy
  fields += '<div class="popup-field"><div class="popup-field-label">Strategy</div>' +
    '<div class="popup-field-value">' + escapeHtml(data.strategy || "\u2014") + '</div></div>';

  // Price
  if (data.avg_price) {
    fields += '<div class="popup-field"><div class="popup-field-label">Entry Price</div>' +
      '<div class="popup-field-value">' + formatNum(data.avg_price, 4) + '</div></div>';
  }
  if (data.current_price) {
    fields += '<div class="popup-field"><div class="popup-field-label">Current Price</div>' +
      '<div class="popup-field-value">' + formatNum(data.current_price, 4) + '</div></div>';
  } else if (data.price) {
    fields += '<div class="popup-field"><div class="popup-field-label">Price</div>' +
      '<div class="popup-field-value">' + formatNum(data.price, 4) + '</div></div>';
  }

  // Size
  fields += '<div class="popup-field"><div class="popup-field-label">Size</div>' +
    '<div class="popup-field-value">' + formatNum(costBasis, 2) + ' EUR</div></div>';

  // P&L
  fields += '<div class="popup-field"><div class="popup-field-label">' + (isClose ? "Realized P&L" : "Unrealized P&L") + '</div>' +
    '<div class="popup-field-value ' + pnlCls + '">' + pnlSign + formatNum(pnl, 4) + ' EUR</div></div>';

  // Edge
  var edge = data.edge_at_entry || data.edge || 0;
  fields += '<div class="popup-field"><div class="popup-field-label">Edge</div>' +
    '<div class="popup-field-value">' + formatNum(edge, 4) + '</div></div>';

  // Category
  if (data.category) {
    fields += '<div class="popup-field"><div class="popup-field-label">Category</div>' +
      '<div class="popup-field-value">' + escapeHtml(data.category) + '</div></div>';
  }

  // Expiry
  if (data.end_date) {
    fields += '<div class="popup-field"><div class="popup-field-label">Expiry</div>' +
      '<div class="popup-field-value">' + formatDate(data.end_date) + '</div></div>';
  }

  // Volume
  if (data.volume) {
    fields += '<div class="popup-field"><div class="popup-field-label">Volume</div>' +
      '<div class="popup-field-value">$' + formatNum(data.volume, 0) + '</div></div>';
  }
  if (data.volume_24h) {
    fields += '<div class="popup-field"><div class="popup-field-label">24h Volume</div>' +
      '<div class="popup-field-value">$' + formatNum(data.volume_24h, 0) + '</div></div>';
  }

  // Opened / Timestamp
  var when = data.opened_at || data.timestamp || "";
  if (when) {
    fields += '<div class="popup-field"><div class="popup-field-label">' + (isClose ? "Closed" : "Opened") + '</div>' +
      '<div class="popup-field-value">' + formatDate(when) + '</div></div>';
  }

  // Resolution
  if (data.resolution_source) {
    fields += '<div class="popup-field" style="grid-column:1/-1"><div class="popup-field-label">Resolution Source</div>' +
      '<div class="popup-field-value" style="font-family:var(--font-ui);font-size:12px">' + escapeHtml(data.resolution_source) + '</div></div>';
  }

  var reasoning = data.reasoning || "";
  var reasoningHtml = reasoning
    ? '<div class="popup-reasoning"><strong>Reasoning:</strong> ' + escapeHtml(reasoning) + '</div>'
    : '';

  var overlay = document.createElement("div");
  overlay.className = "popup-overlay";
  overlay.onclick = function (e) { if (e.target === overlay) closePopup(); };
  overlay.innerHTML =
    '<div class="popup-card">' +
      '<div class="popup-header">' +
        '<div class="popup-title">' + escapeHtml(question) + '</div>' +
        '<button class="popup-close" onclick="closePopup()">&times;</button>' +
      '</div>' +
      '<div class="popup-body">' +
        '<div class="popup-grid">' + fields + '</div>' +
        reasoningHtml +
      '</div>' +
    '</div>';
  document.body.appendChild(overlay);

  // ESC to close
  document.addEventListener("keydown", _popupEsc);
}

function _popupEsc(e) {
  if (e.key === "Escape") closePopup();
}

function closePopup() {
  var el = document.querySelector(".popup-overlay");
  if (el) el.remove();
  document.removeEventListener("keydown", _popupEsc);
}

// ── Positions Panel ──────────────────────────────────────────────────

function renderPositions(positions) {
  _positionsData = positions || [];
  var tbody = document.getElementById("positions-tbody");
  var totalEl = document.getElementById("positions-total");
  if (!tbody) return;

  if (!positions || positions.length === 0) {
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-muted);padding:20px">No open positions</td></tr>';
    if (totalEl) totalEl.textContent = "";
    return;
  }

  var totalPnl = 0;

  tbody.innerHTML = positions
    .map(function (p, idx) {
      var pnl = Number(p.unrealized_pnl || 0);
      totalPnl += pnl;
      var pnlCls = pnl > 0 ? "positive" : pnl < 0 ? "negative" : "";
      var sign = pnl > 0 ? "+" : "";
      var question = p.question || "Market #" + p.market_id;
      var catBadge = p.category ? '<span class="badge badge-blue" style="font-size:10px;margin-left:4px">' + escapeHtml(p.category) + '</span>' : '';
      var pnlPct = p.cost_basis > 0 ? (pnl / p.cost_basis * 100) : 0;
      var pnlPctStr = (pnlPct >= 0 ? "+" : "") + formatNum(pnlPct, 1) + "%";
      var decision = p.decision || (p.side + " " + (p.outcome || ""));
      var decisionCls = (p.outcome || "").toLowerCase() === "yes" ? "positive" : "negative";

      return '<tr style="cursor:pointer" onclick="showPopup(_positionsData[' + idx + '])">' +
        '<td style="max-width:280px"><strong>' + escapeHtml(truncate(question, 50)) + '</strong>' + catBadge + '</td>' +
        '<td><span class="badge badge-blue">' + escapeHtml(p.strategy) + '</span>' +
          ' <span class="metric-value ' + decisionCls + '" style="font-size:12px">' + escapeHtml(decision) + '</span></td>' +
        '<td>' + formatNum(p.avg_price, 3) + ' &rarr; ' + formatNum(p.current_price, 3) + '</td>' +
        '<td>' + formatNum(p.cost_basis, 2) + '</td>' +
        '<td class="metric-value ' + pnlCls + '" style="font-size:13px">' + sign + formatNum(pnl, 4) + ' <span style="font-size:11px;opacity:0.7">(' + pnlPctStr + ')</span></td>' +
        '<td style="font-size:11px;color:var(--text-muted)">edge ' + formatNum(p.edge_at_entry, 3) + '</td>' +
        '</tr>';
    })
    .join("");

  if (totalEl) {
    var totalCls = totalPnl > 0 ? "positive" : totalPnl < 0 ? "negative" : "";
    var totalSign = totalPnl > 0 ? "+" : "";
    totalEl.innerHTML = 'Unrealized P&L: <span class="metric-value ' + totalCls + '" style="font-size:13px">' +
      totalSign + formatNum(totalPnl, 4) + ' EUR</span>';
  }
}

// ── Trade Log ────────────────────────────────────────────────────────

function renderTradeLog(data) {
  var trades = data.trades || [];
  _tradesData = trades;
  var total = data.total || 0;
  var tbody = document.getElementById("trade-log-tbody");
  var totalEl = document.getElementById("trade-log-total");
  if (totalEl) totalEl.textContent = total;
  if (!tbody) return;

  if (trades.length === 0) {
    tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--text-muted);padding:20px">No trades yet</td></tr>';
    return;
  }

  tbody.innerHTML = trades
    .map(function (t, idx) {
      var pnl = Number(t.pnl || 0);
      var edge = Number(t.edge || 0);
      var isClose = t.type === "close";
      var pnlCls = pnl > 0 ? "positive" : pnl < 0 ? "negative" : "";
      var sign = pnl > 0 ? "+" : "";
      var typeBadge = isClose ? "badge-red" : "badge-blue";
      var typeLabel = isClose ? "exit" : (t.strategy || "\u2014");
      var pnlDisplay = isClose
        ? sign + pnl.toFixed(4) + " EUR"
        : formatNum(t.size_eur, 2) + " EUR";
      var question = t.question || "";
      var sideLabel = t.side || "";

      var decisionLabel = escapeHtml(sideLabel) + (t.side === "BUY" ? " Yes" : " No");
      var decisionCls = sideLabel === "BUY" ? "positive" : "negative";

      return '<tr style="cursor:pointer" onclick="showPopup(_tradesData[' + idx + '])">' +
        '<td style="max-width:250px">' +
          '<div><strong>' + escapeHtml(truncate(question, 45)) + '</strong></div>' +
          '<div style="font-size:11px;color:var(--text-muted)">' +
            formatDate(t.timestamp) + ' @ ' + formatNum(t.price, 3) +
          '</div>' +
        '</td>' +
        '<td class="label"><span class="badge ' + typeBadge + '">' + escapeHtml(typeLabel) + '</span>' +
          (isClose
            ? ' <span style="color:var(--text-muted);font-size:11px">' + escapeHtml(truncate(t.reasoning, 35)) + '</span>'
            : ' <span class="metric-value ' + decisionCls + '" style="font-size:12px">' + decisionLabel + '</span>') +
        '</td>' +
        '<td class="metric-value ' + (isClose ? pnlCls : '') + '" style="font-size:13px">' + pnlDisplay + '</td>' +
        '<td>' + formatNum(edge, 4) + '</td>' +
        '</tr>';
    })
    .join("");
}

// ── Config Tab ────────────────────────────────────────────────────────

async function loadConfig() {
  clearError("config");
  try {
    var config = await apiFetch("/config");
    renderConfig(config);
  } catch (err) {
    showError("config", err.message);
  }
}

function renderConfig(cfg) {
  // Strategies
  var stratList = document.getElementById("cfg-strategies-enabled");
  if (stratList && cfg.strategies) {
    stratList.innerHTML = (cfg.strategies.enabled || [])
      .map(function (s) { return '<span class="tag">' + escapeHtml(s) + '</span>'; })
      .join("");
  }

  // Risk params
  renderConfigTable("cfg-risk-table", cfg.risk || {}, {
    max_exposure_pct: "Max Exposure",
    max_single_position_eur: "Max Position (EUR)",
    daily_loss_limit_eur: "Daily Loss Limit (EUR)",
    fixed_fraction_pct: "Fixed Fraction",
    max_positions: "Max Positions",
  });

  // Valuation weights
  var weights = cfg.valuation ? cfg.valuation.weights || {} : {};
  renderConfigTable("cfg-weights-table", weights, {
    base_rate: "Base Rate",
    rule_analysis: "Rule Analysis",
    microstructure: "Microstructure",
    cross_market: "Cross Market",
    event_signal: "Event Signal",
    pattern_kg: "Pattern KG",
    temporal: "Temporal",
    crowd_calibration: "Crowd Calibration",
  });

  // Valuation thresholds
  var thresholds = cfg.valuation ? cfg.valuation.thresholds || {} : {};
  renderConfigTable("cfg-thresholds-table", thresholds, {
    min_edge: "Min Edge",
    min_confidence: "Min Confidence",
    strong_edge: "Strong Edge",
  });

  // LLM
  renderConfigTable("cfg-llm-table", {
    enabled: cfg.llm ? cfg.llm.enabled : undefined,
    model: cfg.llm ? cfg.llm.model : undefined,
    triggers: cfg.llm ? (cfg.llm.triggers || []).join(", ") : undefined,
  }, {
    enabled: "Enabled",
    model: "Model",
    triggers: "Triggers",
  });

  // Intelligence
  renderConfigTable("cfg-intel-table", {
    gdelt_enabled: cfg.intelligence ? cfg.intelligence.gdelt_enabled : undefined,
    rss_enabled: cfg.intelligence ? cfg.intelligence.rss_enabled : undefined,
  }, {
    gdelt_enabled: "GDELT",
    rss_enabled: "RSS Feeds",
  });
}

function renderConfigTable(tableId, data, labelMap) {
  var el = document.getElementById(tableId);
  if (!el) return;
  el.innerHTML = Object.entries(labelMap)
    .map(function (entry) {
      var key = entry[0];
      var label = entry[1];
      var val = data[key];
      var display = val === undefined ? "\u2014" : String(val);
      return '<div class="config-row">' +
        '<span class="config-key">' + escapeHtml(label) + '</span>' +
        '<span class="config-val">' + escapeHtml(display) + '</span>' +
        '</div>';
    })
    .join("");
}

// ── Helpers ───────────────────────────────────────────────────────────

function set(id, value) {
  var el = document.getElementById(id);
  if (el) el.textContent = value;
}

// ── Init ──────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", function () {
  // Tab buttons
  document.querySelectorAll(".tab-btn").forEach(function (btn) {
    btn.addEventListener("click", function () { switchTab(btn.dataset.tab); });
  });

  // Start SSE connection
  connectSSE();
});
