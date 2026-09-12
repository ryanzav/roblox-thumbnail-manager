/* Static dashboard: reads docs/data CSVs + latest.json, renders cards,
   leaderboard, charts, lineage, and full creative history. */

const PALETTE = ["#2f6fed", "#1d8a4e", "#c0392b", "#8e44ad", "#d68910",
                 "#16a085", "#7f8c8d", "#2c3e50", "#e67e22", "#27ae60"];

function parseCSV(text) {
  const rows = [];
  let row = [], field = "", inQuotes = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (inQuotes) {
      if (c === '"') {
        if (text[i + 1] === '"') { field += '"'; i++; }
        else inQuotes = false;
      } else field += c;
    } else if (c === '"') inQuotes = true;
    else if (c === ",") { row.push(field); field = ""; }
    else if (c === "\n" || c === "\r") {
      if (c === "\r" && text[i + 1] === "\n") i++;
      row.push(field); field = "";
      if (row.length > 1 || row[0] !== "") rows.push(row);
      row = [];
    } else field += c;
  }
  if (field !== "" || row.length) { row.push(field); rows.push(row); }
  if (!rows.length) return [];
  const header = rows[0];
  return rows.slice(1).map(r =>
    Object.fromEntries(header.map((h, i) => [h, r[i] ?? ""])));
}

const CHART_PICK_KEY = "chartSeries";

// Retired creatives the viewer has pinned onto the charts, remembered per
// browser. Storage can throw (private windows, blocked site data), so every
// access is guarded and the page works with nothing stored.
function loadPicked() {
  try {
    return new Set(JSON.parse(localStorage.getItem(CHART_PICK_KEY) || "[]"));
  } catch (e) {
    return new Set();
  }
}

function savePicked(picked) {
  try {
    localStorage.setItem(CHART_PICK_KEY, JSON.stringify([...picked]));
  } catch (e) {
    /* not fatal: the selection simply will not survive a reload */
  }
}

let picked = loadPicked();
let chartSource = { metrics: [], thumbs: [] };
const chartInstances = {};

const fmtInt = v => v === "" || v == null ? "—" : Number(v).toLocaleString();
const fmtPct = v => v === "" || v == null ? "—" : (Number(v) * 100).toFixed(2) + "%";
const fmtMin = v => v === "" || v == null ? "—" : Number(v).toFixed(1) + " min";
const fmtDate = v => !v ? "—" : new Date(v).toLocaleString();

async function fetchText(url) {
  const resp = await fetch(url + "?t=" + Date.now());
  if (!resp.ok) throw new Error(url + " -> " + resp.status);
  return resp.text();
}

async function main() {
  let metrics = [], thumbs = [], latest = {}, queue = [];
  try { metrics = parseCSV(await fetchText("data/metrics.csv")); } catch (e) { console.warn(e); }
  try { thumbs = parseCSV(await fetchText("data/thumbnails.csv")); } catch (e) { console.warn(e); }
  try { latest = JSON.parse(await fetchText("data/latest.json")); } catch (e) { console.warn(e); }
  try { queue = JSON.parse(await fetchText("data/queue.json")); } catch (e) { console.warn(e); }

  const latestByKey = {};
  for (const m of metrics) {
    const key = m.thumbnail_key || m.roblox_asset_id;
    if (!latestByKey[key] || m.timestamp >= latestByKey[key].timestamp) latestByKey[key] = m;
  }

  renderGeneratedAt(latest);
  renderOverview(latest, thumbs, latestByKey);
  renderGateBanner(latest, latestByKey, thumbs);
  renderActiveCards(thumbs, latestByKey);
  renderQueue(queue);
  renderLeaderboard(thumbs, latestByKey);
  chartSource = { metrics, thumbs };
  renderCharts(metrics, thumbs);
  renderLineage(thumbs);
  renderHistory(thumbs, metrics, latestByKey);
}

function relativeAge(then, now = Date.now()) {
  const mins = Math.floor((now - then) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} minute${mins === 1 ? "" : "s"} ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.floor(hours / 24);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}

function renderGeneratedAt(latest) {
  const el = document.getElementById("generated-at");
  const foot = document.getElementById("generated-footer");
  if (!latest.last_update) {
    el.textContent = "No data generated yet.";
    if (foot) foot.textContent = "";
    return;
  }
  const when = new Date(latest.last_update);
  const age = Date.now() - when.getTime();
  // Runs are scheduled every 6 hours; well past that means something stalled.
  const stale = age > 8 * 3600 * 1000;
  const text = `Generated ${when.toLocaleString()} · ${relativeAge(when.getTime())}`;
  el.innerHTML = stale
    ? `${text} <span class="stale">— no recent run</span>`
    : text;
  if (foot) foot.textContent = `Page data generated ${when.toISOString()} (UTC).`;
}

function activeThumbs(thumbs) {
  return thumbs.filter(t => t.status === "active");
}

function renderOverview(latest, thumbs, latestByKey) {
  const el = document.getElementById("overview");
  const stats = [
    ["Active thumbnails", `${latest.active_count ?? activeThumbs(thumbs).length} / ${latest.target_active ?? 5}`],
    ["Queue", `${latest.queue_size ?? 0} candidates`],
    ["Best current qPTR", latest.best_qptr != null ? fmtPct(latest.best_qptr) : "—"],
    ["Evaluation", latest.evaluation_status || "—"],
  ];
  el.innerHTML = stats.map(([label, value]) =>
    `<div class="stat"><div class="label">${label}</div><div class="value">${value}</div></div>`).join("");
}

function renderGateBanner(latest, latestByKey, thumbs) {
  const gate = latest.gate_impressions ?? 1000;
  const below = activeThumbs(thumbs).filter(t => {
    const m = latestByKey[t.thumbnail_key];
    return !m || m.impressions === "" || Number(m.impressions) < gate;
  });
  const el = document.getElementById("gate-banner");
  if (below.length && activeThumbs(thumbs).length) {
    el.innerHTML = `<div class="banner"><strong>Evaluation paused:</strong>
      All active thumbnails must reach ${gate.toLocaleString()} impressions.
      Waiting on: ${below.map(t => t.thumbnail_key).join(", ")}</div>`;
  } else {
    el.innerHTML = "";
  }
}

function chartToggleHTML(t, alwaysOn) {
  const checked = alwaysOn || picked.has(t.thumbnail_key) ? " checked" : "";
  const disabled = alwaysOn ? " disabled" : "";
  const note = alwaysOn ? "Charted (active)" : "Show in charts";
  return `<label class="chart-toggle"${alwaysOn ? ' title="Active thumbnails are always charted"' : ""}>
    <input type="checkbox" data-chart-key="${t.thumbnail_key}"${checked}${disabled}>
    <span>${note}</span>
  </label>`;
}

function cardHTML(t, m, opts = {}) {
  const img = t.filename
    ? `<img src="images/thumbnails/${t.filename}" alt="${t.thumbnail_key}"
        onerror="this.outerHTML='<div class=&quot;no-image&quot;>no image</div>'">`
    : `<div class="no-image">no image</div>`;
  const rows = [
    ["Impressions", fmtInt(m?.impressions)],
    ["Qualified Plays", fmtInt(m?.qualified_plays)],
    ["Qualified PTR", fmtPct(m?.qualified_ptr)],
    ["7-day qPTR", fmtPct(m?.l7_qualified_ptr)],
    ["Average Playtime", fmtMin(m?.average_session_minutes)],
    ["Winning Segments", fmtInt(m?.winning_segments)],
    ["Activated", fmtDate(t.activated_at)],
  ];
  if (opts.history) {
    rows.push(["Deactivated", fmtDate(t.deactivated_at)]);
    if (opts.bestQptr != null) rows.push(["Best qPTR", fmtPct(opts.bestQptr)]);
  }
  return `<div class="card">
    ${img}
    <div class="body">
      <div class="status ${t.status}">${(t.status || "").toUpperCase()}</div>
      <div class="desc">${t.description || t.thumbnail_key}</div>
      <table>${rows.map(([k, v]) => `<tr><td class="muted">${k}</td><td>${v}</td></tr>`).join("")}</table>
      <div class="lineage-note">
        ${t.thumbnail_key}${t.roblox_asset_id ? " · asset " + t.roblox_asset_id : ""}
        ${t.source_thumbnail_id ? "<br>Source: " + t.source_thumbnail_id : ""}
      </div>
      ${opts.chartToggle ? chartToggleHTML(t, opts.alwaysCharted) : ""}
    </div>
  </div>`;
}

function renderActiveCards(thumbs, latestByKey) {
  const el = document.getElementById("active-cards");
  const active = activeThumbs(thumbs);
  el.innerHTML = active.length
    ? active.map(t => cardHTML(t, latestByKey[t.thumbnail_key])).join("")
    : `<p class="muted">No active thumbnails tracked yet.</p>`;
}

function renderQueue(queue) {
  document.getElementById("queue-count").textContent =
    queue.length ? `(${queue.length})` : "";
  const el = document.getElementById("queue-cards");
  if (!queue.length) {
    el.innerHTML = `<p class="muted">Queue is empty — no candidates generated yet.</p>`;
    return;
  }
  el.innerHTML = queue.map(c => `<div class="card">
    <img src="${c.url || `images/queue/${c.filename}`}" alt="${c.filename}"
      onerror="this.outerHTML='<div class=&quot;no-image&quot;>no image</div>'">
    <div class="body">
      <div class="status queued">QUEUED</div>
      <div class="desc">${c.filename}</div>
      <table>
        <tr><td class="muted">Generated</td><td>${fmtDate(c.generated_at)}</td></tr>
        <tr><td class="muted">Model</td><td>${c.model || "—"}</td></tr>
        <tr><td class="muted">Source</td><td>${c.source_thumbnail_id || "—"}</td></tr>
      </table>
      ${c.prompt ? `<details class="prompt"><summary>Prompt</summary>${c.prompt}</details>` : ""}
    </div>
  </div>`).join("");
}

function renderLeaderboard(thumbs, latestByKey) {
  const tbody = document.querySelector("#leaderboard tbody");
  const rows = activeThumbs(thumbs)
    .map(t => ({ t, m: latestByKey[t.thumbnail_key] }))
    .sort((a, b) => (Number(b.m?.qualified_ptr) || 0) - (Number(a.m?.qualified_ptr) || 0));
  tbody.innerHTML = rows.length
    ? rows.map((r, i) => `<tr>
        <td>${i + 1}</td><td>${r.t.thumbnail_key}</td>
        <td>${fmtInt(r.m?.impressions)}</td><td>${fmtPct(r.m?.qualified_ptr)}</td>
      </tr>`).join("")
    : `<tr><td colspan="4" class="muted">No data yet.</td></tr>`;
}

// A single reusable tooltip node, created lazily and parked on the body so it
// can overflow the chart's own box.
function chartTooltipEl() {
  let el = document.getElementById("chart-tooltip");
  if (!el) {
    el = document.createElement("div");
    el.id = "chart-tooltip";
    el.className = "chart-tooltip";
    document.body.appendChild(el);
  }
  return el;
}

// Chart.js draws its own tooltip on the canvas, which cannot hold an image, so
// hover is rendered as HTML instead.
function imageTooltip(images, percent) {
  return (context) => {
    const el = chartTooltipEl();
    const { chart, tooltip } = context;
    if (!tooltip.opacity) {
      el.style.opacity = "0";
      return;
    }
    const point = tooltip.dataPoints && tooltip.dataPoints[0];
    if (!point) return;

    const key = point.dataset.label;
    const value = percent
      ? `${point.parsed.y.toFixed(2)}%`
      : Number(point.parsed.y).toLocaleString();
    const when = new Date(point.parsed.x).toLocaleString(undefined, {
      month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
    });
    const src = images[key];

    el.innerHTML = `
      ${src ? `<img src="${src}" alt="${key}" onerror="this.remove()">` : ""}
      <div class="tip-body">
        <div class="tip-key" style="color:${point.dataset.borderColor}">${key}</div>
        <div class="tip-value">${value}</div>
        <div class="tip-when">${when}</div>
      </div>`;

    const box = chart.canvas.getBoundingClientRect();
    el.style.opacity = "1";
    el.style.left = `${box.left + window.scrollX + tooltip.caretX + 12}px`;
    el.style.top = `${box.top + window.scrollY + tooltip.caretY - 12}px`;
  };
}

function renderCharts(metrics, thumbs) {
  if (typeof Chart === "undefined" || !metrics.length) return;

  const timestamps = [...new Set(metrics.map(m => m.timestamp))].sort();
  // Only chart the current active set. Every retired creative stays in the
  // history section below; plotting all of them at once (20+ series) made the
  // lines unreadable and told you nothing about the thumbnails serving now.
  const active = new Set(thumbs.filter(t => t.status === "active")
                               .map(t => t.thumbnail_key));
  const keys = [...new Set(metrics.map(m => m.thumbnail_key || m.roblox_asset_id))]
    .filter(k => active.has(k) || picked.has(k) || (active.size === 0 && !picked.size));

  const byKeyTime = {};
  for (const m of metrics)
    byKeyTime[(m.thumbnail_key || m.roblox_asset_id) + "|" + m.timestamp] = m;

  // Every run records a snapshot for every tracked creative, active or not, so
  // a thumbnail retired days ago still has rows up to today. Those rows are a
  // rolling 30-day window, not current performance, so each series is bounded
  // to the span the creative was actually serving.
  // Archived images are served from docs/, queued ones from the repository.
  const images = {};
  for (const t of thumbs) {
    if (t.filename) images[t.thumbnail_key] = `images/thumbnails/${t.filename}`;
  }

  const lifespan = {};
  for (const t of thumbs) {
    const from = t.activated_at ? new Date(t.activated_at).getTime() : -Infinity;
    const to = t.deactivated_at ? new Date(t.deactivated_at).getTime() : Infinity;
    lifespan[t.thumbnail_key] = { from, to };
  }

  const mk = (canvasId, field, { percent = false } = {}) => {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    // Chart.js refuses a canvas that still owns a chart, so the previous
    // instance must go before a re-render.
    if (chartInstances[canvasId]) chartInstances[canvasId].destroy();
    const datasets = keys.map((k, i) => ({
      label: k,
      // {x, y} points rather than a value per category slot: snapshots are
      // taken at irregular intervals, and an evenly-spaced category axis put
      // a day with 32 runs beside a day with 4 at the same width, so nothing
      // sat under the date it was actually recorded on.
      data: timestamps.reduce((points, ts) => {
        const at = new Date(ts).getTime();
        const span = lifespan[k];
        // Dropped entirely rather than nulled, so the line stops at
        // deactivation instead of being bridged across by spanGaps.
        if (span && (at < span.from || at > span.to)) return points;
        const m = byKeyTime[k + "|" + ts];
        // A blank cell means Roblox reported nothing for that snapshot; it is
        // a gap in knowledge, not a zero, so it must not be drawn as one.
        const raw = m ? m[field] : null;
        const y = raw === "" || raw == null ? null : Number(raw) * (percent ? 100 : 1);
        points.push({ x: at, y });
        return points;
      }, []),
      borderColor: PALETTE[i % PALETTE.length],
      backgroundColor: PALETTE[i % PALETTE.length],
      borderWidth: 2,
      spanGaps: true,
      tension: 0.25,
      pointRadius: 2,
      pointHoverRadius: 4,
    }));

    chartInstances[canvasId] = new Chart(canvas, {
      type: "line",
      data: { datasets },
      options: {
        maintainAspectRatio: false,
        // "nearest" so hovering a trace identifies that creative; "index"
        // would report every series at once, leaving no single image to show.
        interaction: { mode: "nearest", intersect: false },
        plugins: {
          legend: { position: "bottom", labels: { boxWidth: 12, usePointStyle: true } },
          tooltip: {
            enabled: false,
            external: imageTooltip(images, percent),
          },
        },
        scales: {
          x: {
            type: "time",
            time: { unit: "day", tooltipFormat: "MMM d, h:mm a" },
            ticks: { autoSkip: true, maxTicksLimit: 10, maxRotation: 0 },
          },
          y: percent
            // qPTR differences that matter are fractions of a point, so the
            // axis is not pinned to zero - that would flatten every series
            // into one indistinguishable band.
            ? { ticks: { callback: v => `${Number(v).toFixed(2)}%` } }
            : { beginAtZero: true, ticks: { callback: v => Number(v).toLocaleString() } },
        },
      },
    });
  };

  mk("chart-qptr", "qualified_ptr", { percent: true });
  mk("chart-impressions", "impressions");
  mk("chart-plays", "qualified_plays");
}

function renderLineage(thumbs) {
  const el = document.getElementById("lineage");
  if (!thumbs.length) { el.textContent = "No creatives tracked yet."; return; }
  const children = {};
  const known = new Set(thumbs.map(t => t.thumbnail_key));
  const roots = [];
  for (const t of thumbs) {
    if (t.source_thumbnail_id && known.has(t.source_thumbnail_id)) {
      (children[t.source_thumbnail_id] ??= []).push(t.thumbnail_key);
    } else roots.push(t.thumbnail_key);
  }
  const lines = [];
  const walk = (key, prefix, isLast, isRoot) => {
    lines.push(isRoot ? key : prefix + (isLast ? "└── " : "├── ") + key);
    const kids = children[key] || [];
    kids.forEach((k, i) => walk(
      k,
      isRoot ? "   " : prefix + (isLast ? "       " : "│      "),
      i === kids.length - 1, false));
  };
  roots.forEach(r => walk(r, "", true, true));
  el.textContent = lines.join("\n");
}

function renderHistory(thumbs, metrics, latestByKey) {
  const el = document.getElementById("history-cards");
  if (!thumbs.length) {
    el.innerHTML = `<p class="muted">No creative history yet.</p>`;
    return;
  }
  el.innerHTML = thumbs.map(t => {
    const mine = metrics.filter(m => (m.thumbnail_key || m.roblox_asset_id) === t.thumbnail_key);
    const best = mine.reduce((acc, m) =>
      m.qualified_ptr !== "" && (acc == null || Number(m.qualified_ptr) > acc)
        ? Number(m.qualified_ptr) : acc, null);
    return cardHTML(t, latestByKey[t.thumbnail_key], {
      history: true, bestQptr: best,
      chartToggle: true, alwaysCharted: t.status === "active",
    });
  }).join("");

  // One delegated listener survives re-renders of the card markup.
  el.onchange = (event) => {
    const box = event.target.closest("input[data-chart-key]");
    if (!box) return;
    const key = box.dataset.chartKey;
    if (box.checked) picked.add(key);
    else picked.delete(key);
    savePicked(picked);
    renderCharts(chartSource.metrics, chartSource.thumbs);
  };
}

main();
