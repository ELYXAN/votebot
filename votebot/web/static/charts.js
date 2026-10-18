// Eigenständige Diagramme (SVG/HTML, keine externen Abhängigkeiten).
// Farben: Top-Spiele als Einzel-Hue (Marken-Lila), Verteilung als validierte
// kategoriale Dark-Palette (dataviz-Referenz).

// Clean-Rainbow-Verlauf (identisch zum CSS --grad)
const GRAD_STOPS = ["#34d6c6", "#4a9eff", "#8b7bff", "#e46fd1", "#ff9a63"];
function _hx(h) { h = h.replace("#", ""); return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)]; }
function _hex(r, g, b) { return "#" + [r, g, b].map(v => Math.round(Math.max(0, Math.min(255, v))).toString(16).padStart(2, "0")).join(""); }
function _lerp(a, b, t) { const A = _hx(a), B = _hx(b); return _hex(A[0] + (B[0] - A[0]) * t, A[1] + (B[1] - A[1]) * t, A[2] + (B[2] - A[2]) * t); }
function rainbowAt(frac) { frac = Math.max(0, Math.min(1, frac)); const n = GRAD_STOPS.length - 1; const x = frac * n; const i = Math.min(Math.floor(x), n - 1); return _lerp(GRAD_STOPS[i], GRAD_STOPS[i + 1], x - i); }
function lighten(hex, t) { return _lerp(hex, "#ffffff", t); }

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
    const base = rainbowAt(data.length > 1 ? i / (data.length - 1) : 0.15);
    const light = lighten(base, 0.3);
    const fillStyle = `width:${pct}%;background:linear-gradient(90deg,${base},${light});box-shadow:0 0 12px ${base}99`;
    row.innerHTML = `
      <span class="hbar-label" title="${escC(d.name)}"><span class="hbar-rank">${rank}</span>${escC(d.name)}</span>
      <div class="hbar-track"><div class="hbar-fill" style="${fillStyle}"></div></div>
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

// Voter dieser Session: wer hat wie oft für welche Spiele gevotet
function renderVoters(el, voters) {
  const rows = Object.entries(voters || {}).map(([user, v]) => ({
    user, count: v.count || 0, weight: v.weight || 0, games: v.games || {},
  })).sort((a, b) => b.weight - a.weight);

  if (!rows.length) {
    el.innerHTML = '<div class="empty">Noch keine Voter in dieser Session.</div>';
    return;
  }

  const body = rows.map((r, i) => {
    const games = Object.entries(r.games).sort((a, b) => b[1] - a[1])
      .map(([g, w]) => `<span class="gchip">${escC(g)} <b>${w}</b></span>`).join(" ");
    return `<tr>
      <td class="muted">${i + 1}</td>
      <td class="vuser">${escC(r.user)}</td>
      <td style="text-align:right">${r.count}</td>
      <td style="text-align:right">${r.weight}</td>
      <td class="vgames">${games}</td>
    </tr>`;
  }).join("");

  el.innerHTML = `<table>
    <tr><th>#</th><th>User</th><th style="text-align:right">Votes</th><th style="text-align:right">Gewicht</th><th>Spiele</th></tr>
    ${body}
  </table>`;
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
    const base = rainbowAt(entries.length > 1 ? i / (entries.length - 1) : 0.4);
    const light = lighten(base, 0.3);
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
