// Eigenständige Diagramme (SVG/HTML, keine externen Abhängigkeiten).
// Farben: Top-Spiele als Einzel-Hue (Marken-Lila), Verteilung als validierte
// kategoriale Dark-Palette (dataviz-Referenz).

const CAT_COLORS = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"];

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

// --- Top-Spiele: horizontale Balken (Magnitude, ein Hue) ---
function renderTopGames(el, standings) {
  if (!standings || !standings.length) {
    el.innerHTML = '<div class="empty">Noch keine Votes im Sheet.</div>';
    return;
  }
  const data = standings.slice(0, 8);
  const max = Math.max(...data.map(d => d.votes), 1);
  el.innerHTML = "";
  data.forEach(d => {
    const row = document.createElement("div");
    row.className = "hbar-row";
    const pct = Math.max((d.votes / max) * 100, 2);
    row.innerHTML = `
      <span class="hbar-label" title="${escC(d.name)}">${escC(d.name)}</span>
      <div class="hbar-track"><div class="hbar-fill" style="width:${pct}%"></div></div>
      <span class="hbar-val">${d.votes}</span>`;
    row.addEventListener("mousemove", (ev) => showTip(ev, `<b>#${d.rank} ${escC(d.name)}</b><br>${d.votes} Votes`));
    row.addEventListener("mouseleave", hideTip);
    el.appendChild(row);
  });
}

// --- Verteilung nach Belohnung: Donut (kategorial) ---
function renderRewardDonut(el, byReward) {
  const entries = Object.entries(byReward || {}).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]);
  const total = entries.reduce((s, [, v]) => s + v, 0);
  if (!total) {
    el.innerHTML = '<div class="empty">Noch keine Votes in dieser Sitzung.</div>';
    return;
  }

  const size = 150, stroke = 22, r = (size - stroke) / 2, cx = size / 2, C = 2 * Math.PI * r;
  let offset = 0;
  const arcs = entries.map(([name, val], i) => {
    const frac = val / total;
    const color = CAT_COLORS[i % CAT_COLORS.length];
    const dash = frac * C;
    // 2px Lücke zwischen Segmenten (surface gap).
    const gap = total > 1 && entries.length > 1 ? 2 : 0;
    const seg = `<circle cx="${cx}" cy="${cx}" r="${r}" fill="none" stroke="${color}"
       stroke-width="${stroke}" stroke-dasharray="${Math.max(dash - gap, 0.5)} ${C - Math.max(dash - gap, 0.5)}"
       stroke-dashoffset="${-offset}" data-i="${i}"></circle>`;
    offset += dash;
    return { seg, name, val, color, frac };
  });

  const legend = arcs.map(a =>
    `<div class="li"><span class="sw" style="background:${a.color}"></span>
       <span class="ln">${escC(a.name)}</span>
       <span class="lv">${a.val} · ${Math.round(a.frac * 100)}%</span></div>`).join("");

  el.innerHTML = `
    <div class="donut-wrap">
      <svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" style="transform:rotate(-90deg)">
        ${arcs.map(a => a.seg).join("")}
        <text x="${cx}" y="${cx}" text-anchor="middle" dominant-baseline="central"
          transform="rotate(90 ${cx} ${cx})" fill="var(--text)" font-size="26" font-weight="600">${total}</text>
        <text x="${cx}" y="${cx + 20}" text-anchor="middle" dominant-baseline="central"
          transform="rotate(90 ${cx} ${cx})" fill="var(--muted)" font-size="10">Votes</text>
      </svg>
      <div class="legend">${legend}</div>
    </div>`;

  el.querySelectorAll("circle").forEach((c) => {
    const a = arcs[Number(c.dataset.i)];
    c.style.cursor = "pointer";
    c.addEventListener("mousemove", (ev) => showTip(ev, `<b>${escC(a.name)}</b><br>${a.val} Votes · ${Math.round(a.frac * 100)}%`));
    c.addEventListener("mouseleave", hideTip);
  });
}
