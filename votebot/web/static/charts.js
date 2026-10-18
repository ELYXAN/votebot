// Eigenständige Diagramme (SVG/HTML, keine externen Abhängigkeiten).
// Farben: Top-Spiele als Einzel-Hue (Marken-Lila), Verteilung als validierte
// kategoriale Dark-Palette (dataviz-Referenz).

const CAT_COLORS = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"];
const CAT_LIGHT = ["#7ab8ff", "#ff8a5c", "#3fd9a0", "#ffc24d", "#ff86b0", "#39d05b", "#b9b0ff", "#ff9a9a"];

// --- gemeinsamer Tooltip ---
let _tip = null;
function tip() {
  if (!_tip) { _tip = document.createElement("div"); _tip.className = "viz-tip"; document.body.appendChild(_tip); }
  return _tip;
}
function showTip(ev, html) {
  const t = tip();
  t.innerHTML = html;
  t.style.left = ev.clientX + "px";
  t.style.top = ev.clientY + "px";
  t.style.opacity = "1";
}
function hideTip() { if (_tip) _tip.style.opacity = "0"; }

function escC(s) {
  return (s == null ? "" : String(s)).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// --- generischer horizontaler Balken-Chart (füllt das Widget vertikal) ---
function renderBars(el, items, opts = {}) {
  const count = opts.count || 14;
  const emptyText = opts.empty || "Noch keine Daten.";
  if (!items || !items.length) {
    el.classList.remove("bars");
    el.innerHTML = `<div class="empty">${escC(emptyText)}</div>`;
    return;
  }
  const data = items.slice(0, count);
  const max = Math.max(...data.map(d => d.votes), 1);
  el.classList.add("bars");
  el.innerHTML = "";
  data.forEach((d, i) => {
    const row = document.createElement("div");
    row.className = "hbar-row";
    const pct = Math.max((d.votes / max) * 100, 2);
    const rank = i + 1;
    row.innerHTML = `
      <span class="hbar-label" title="${escC(d.name)}"><span class="hbar-rank">${rank}</span>${escC(d.name)}</span>
      <div class="hbar-track"><div class="hbar-fill" style="width:${pct}%"></div></div>
      <span class="hbar-val">${d.votes}</span>`;
    row.addEventListener("mousemove", (ev) => showTip(ev, `<b>#${rank} ${escC(d.name)}</b><br>${d.votes} ${opts.unit || "Votes"}`));
    row.addEventListener("mouseleave", hideTip);
    el.appendChild(row);
  });
}

// Top-Spiele (Gesamt, aus dem Sheet)
function renderTopGames(el, standings) {
  renderBars(el, (standings || []).map(s => ({ name: s.name, votes: s.votes })),
    { count: 15, empty: "Noch keine Votes im Sheet." });
}

// Meistgevotete Spiele dieser Session/Stream (aus bot.stats.votes_by_game)
function renderSessionTop(el, byGame) {
  const items = Object.entries(byGame || {}).map(([name, votes]) => ({ name, votes }))
    .sort((a, b) => b.votes - a.votes);
  renderBars(el, items, { count: 15, empty: "Noch keine Votes in dieser Session." });
}

// --- Verteilung nach Belohnung: futuristischer Donut (kategorial) ---
function renderRewardDonut(el, byReward) {
  const entries = Object.entries(byReward || {}).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]);
  const total = entries.reduce((s, [, v]) => s + v, 0);
  if (!total) {
    el.innerHTML = '<div class="empty">Noch keine Votes in dieser Sitzung.</div>';
    return;
  }

  const size = 230, stroke = 26, cx = size / 2, r = (size - stroke) / 2 - 6, C = 2 * Math.PI * r;
  const gap = entries.length > 1 ? C * 0.012 : 0; // kleine Lücke zwischen Segmenten
  let offset = 0;

  const arcs = entries.map(([name, val], i) => {
    const frac = val / total;
    const base = CAT_COLORS[i % CAT_COLORS.length];
    const light = CAT_LIGHT[i % CAT_LIGHT.length];
    const dash = Math.max(frac * C - gap, 0.5);
    const seg = `<circle cx="${cx}" cy="${cx}" r="${r}" fill="none" stroke="url(#g${i})"
       stroke-width="${stroke}" stroke-linecap="round"
       stroke-dasharray="${dash} ${C - dash}" stroke-dashoffset="${-offset}"
       data-i="${i}" style="filter: drop-shadow(0 0 7px ${base}cc)"></circle>`;
    offset += frac * C;
    return { seg, name, val, base, light, frac };
  });

  const defs = arcs.map((a, i) =>
    `<linearGradient id="g${i}" x1="0%" y1="0%" x2="100%" y2="100%">
       <stop offset="0%" stop-color="${a.base}"/><stop offset="100%" stop-color="${a.light}"/>
     </linearGradient>`).join("");

  const legend = arcs.map(a =>
    `<div class="li"><span class="sw" style="color:${a.light};background:${a.base}"></span>
       <span class="ln">${escC(a.name)}</span>
       <span class="lv">${a.val} · ${Math.round(a.frac * 100)}%</span></div>`).join("");

  el.innerHTML = `
    <div class="donut-wrap">
      <svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
        <defs>${defs}</defs>
        <circle cx="${cx}" cy="${cx}" r="${r + stroke / 2 + 4}" fill="none" stroke="rgba(255,255,255,0.06)" stroke-width="1"/>
        <circle cx="${cx}" cy="${cx}" r="${r}" fill="none" stroke="rgba(255,255,255,0.05)" stroke-width="${stroke}"/>
        <circle cx="${cx}" cy="${cx}" r="${r - stroke / 2 - 4}" fill="none" stroke="rgba(255,255,255,0.06)" stroke-width="1"/>
        <g transform="rotate(-90 ${cx} ${cx})">${arcs.map(a => a.seg).join("")}</g>
        <text x="${cx}" y="${cx - 6}" text-anchor="middle" dominant-baseline="central"
          fill="#fff" font-size="46" font-weight="700" style="text-shadow:0 0 20px rgba(120,180,255,0.5)">${total}</text>
        <text x="${cx}" y="${cx + 24}" text-anchor="middle" dominant-baseline="central"
          fill="var(--muted)" font-size="11" letter-spacing="2">VOTES</text>
      </svg>
      <div class="legend">${legend}</div>
    </div>`;

  el.querySelectorAll("g circle").forEach((c) => {
    const a = arcs[Number(c.dataset.i)];
    c.style.cursor = "pointer";
    c.addEventListener("mousemove", (ev) => showTip(ev, `<b>${escC(a.name)}</b><br>${a.val} Votes · ${Math.round(a.frac * 100)}%`));
    c.addEventListener("mouseleave", hideTip);
  });
}
