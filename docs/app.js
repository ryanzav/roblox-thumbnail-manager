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

  renderOverview(latest, thumbs, latestByKey);
  renderGateBanner(latest, latestByKey, thumbs);
  renderActiveCards(thumbs, latestByKey);
  renderQueue(queue);
  renderLeaderboard(thumbs, latestByKey);
  renderCharts(metrics);
  renderLineage(thumbs);
  renderHistory(thumbs, metrics, latestByKey);
}

function activeThumbs(thumbs) {
  return thumbs.filter(t => t.status === "active");
}

function renderOverview(latest, thumbs, latestByKey) {
  const el = document.getElementById("overview");
  const stats = [
    ["Last update", latest.last_update ? fmtDate(latest.last_update) : "No data yet"],
    ["Active thumbnails", `${latest.active_count ?? activeThumbs(thumbs).length} / ${latest.target_active ?? 5}`],
    ["Queue", `${latest.queue_size ?? 0} candidates`],
    ["Best current qPTR", latest.best_qptr != null ? fmtPct(latest.best_qptr) : "—"],
    ["Evaluation", latest.evaluation_status || "—"],
  ];
  const u = latest.usage;
  if (u && u.images_generated) {
    stats.push(["AI images", `${u.images_generated}`]);
    if (u.estimated_spend_usd) stats.push(["Est. spend", `$${u.estimated_spend_usd.toFixed(2)}`]);
    if (u.estimated_remaining_usd != null)
      stats.push(["Est. remaining", `$${u.estimated_remaining_usd.toFixed(2)}`]);
  }
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
        ${c.total_tokens ? `<tr><td class="muted">Tokens</td><td>${Number(c.total_tokens).toLocaleString()}</td></tr>` : ""}
        ${c.estimated_cost_usd ? `<tr><td class="muted">Est. cost</td><td>$${Number(c.estimated_cost_usd).toFixed(3)}</td></tr>` : ""}
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

function renderCharts(metrics) {
  if (typeof Chart === "undefined" || !metrics.length) return;
  const timestamps = [...new Set(metrics.map(m => m.timestamp))].sort();
  const keys = [...new Set(metrics.map(m => m.thumbnail_key || m.roblox_asset_id))];
  const byKeyTime = {};
  for (const m of metrics)
    byKeyTime[(m.thumbnail_key || m.roblox_asset_id) + "|" + m.timestamp] = m;

  const mk = (canvasId, field, scale) => {
    const datasets = keys.map((k, i) => ({
      label: k,
      data: timestamps.map(ts => {
        const m = byKeyTime[k + "|" + ts];
        return m && m[field] !== "" ? Number(m[field]) * scale : null;
      }),
      borderColor: PALETTE[i % PALETTE.length],
      backgroundColor: PALETTE[i % PALETTE.length],
      spanGaps: true,
      tension: 0.25,
      pointRadius: 2,
    }));
    new Chart(document.getElementById(canvasId), {
      type: "line",
      data: { labels: timestamps.map(t => new Date(t).toLocaleString()), datasets },
      options: {
        maintainAspectRatio: false,
        interaction: { mode: "nearest", intersect: false },
        scales: { y: { ticks: scale === 100 ? { callback: v => v + "%" } : {} } },
      },
    });
  };
  mk("chart-qptr", "qualified_ptr", 100);
  mk("chart-impressions", "impressions", 1);
  mk("chart-plays", "qualified_plays", 1);
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
    return cardHTML(t, latestByKey[t.thumbnail_key], { history: true, bestQptr: best });
  }).join("");
}

main();
