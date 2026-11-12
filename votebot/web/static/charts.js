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

// Kennzahlen-Leiste unter einem Chart: items = [[Wert, Beschriftung], ...]
function renderFoot(el, items) {
  if (!el) return;
  el.innerHTML = (items || []).map(([v, k]) =>
    `<div class="cf"><b title="${escC(v)}">${escC(v)}</b><span>${escC(k)}</span></div>`).join("");
}

// --- generischer horizontaler Balken-Chart (Name + Wert oben, Balken darunter) ---
function renderBars(el, items, opts = {}) {
  const count = opts.count || 10;
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
    const fillStyle = `width:${pct}%;background:linear-gradient(90deg,${base},${light})`;
    row.innerHTML = `
      <span class="hbar-label" title="${escC(d.name)}"><span class="hbar-rank">${rank}</span>${escC(d.name)}</span>
      <span class="hbar-val">${d.votes}</span>
      <div class="hbar-track"><div class="hbar-fill" style="${fillStyle}"></div></div>`;
    row.addEventListener("mousemove", (ev) => showTip(ev, `<b>#${rank} ${escC(d.name)}</b><br>${d.votes} ${opts.unit || "Votes"}`));
    row.addEventListener("mouseleave", hideTip);
    el.appendChild(row);
  });
}

// Top-Spiele (Gesamt, aus dem Sheet)
function renderTopGames(el, standings) {
  renderBars(el, (standings || []).map(s => ({ name: s.name, votes: s.votes })),
    { count: 10, empty: "Noch keine Votes im Sheet." });
}

// Meistgevotete Spiele dieser Session/Stream (aus bot.stats.votes_by_game)
function renderSessionTop(el, byGame) {
  const items = Object.entries(byGame || {}).map(([name, votes]) => ({ name, votes }))
    .sort((a, b) => b.votes - a.votes);
  renderBars(el, items, { count: 10, empty: "Noch keine Votes in dieser Session." });
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
      <td class="vgames"><div>${games}</div></td>
    </tr>`;
  }).join("");

  el.innerHTML = `<table>
    <tr><th>#</th><th>User</th><th style="text-align:right">Votes</th><th style="text-align:right">Gewicht</th><th>Spiele</th></tr>
    ${body}
  </table>`;
}

// --- Verteilung nach Belohnung: schlanker Ring mit großer Zahl in der Mitte ---
function renderRewardDonut(el, byReward) {
  const entries = Object.entries(byReward || {}).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]);
  const total = entries.reduce((s, [, v]) => s + v, 0);
  if (!total) {
    el.classList.remove("donut");
    el.innerHTML = '<div class="empty">Noch keine Votes in dieser Session.</div>';
    return;
  }
  el.classList.add("donut");

  const size = 260, cx = size / 2, stroke = 15, r = 108, C = 2 * Math.PI * r;
  const many = entries.length > 1;
  // Runde Enden ragen je stroke/2 über den Strich hinaus. Damit sich Segmente
  // nicht überlappen, wird jedes um Strichbreite + Lücke gekürzt.
  const trim = many ? stroke + 5 : 0;
  // Sehr kleine Anteile bekommen eine Mindestlänge, damit sie als eigenes
  // Segment sichtbar bleiben; die übrigen teilen sich den Rest anteilig.
  const minSpan = trim + 4;
  const small = entries.filter(([, v]) => (v / total) * C < minSpan).length;
  const restTotal = entries.reduce((s, [, v]) => s + ((v / total) * C < minSpan ? 0 : v), 0);
  let pos = 0;
  const arcs = entries.map(([name, val], i) => {
    const frac = val / total;
    const color = rainbowAt(many ? i / (entries.length - 1) : 0.4);
    const span = !many ? C : (frac * C < minSpan ? minSpan : (val / restTotal) * (C - small * minSpan));
    const len = Math.max(span - trim, 0.01);
    const start = pos + (span - len) / 2;
    pos += span;
    const pct = frac * 100 < 1 ? "<1%" : Math.round(frac * 100) + "%";
    return { name, val, frac, color, len, start, pct };
  });

  const segs = arcs.map((a, i) =>
    `<circle class="seg" data-i="${i}" cx="${cx}" cy="${cx}" r="${r}" fill="none" stroke="${a.color}"
       stroke-width="${stroke}" stroke-linecap="${many ? "round" : "butt"}"
       stroke-dasharray="${a.len} ${C - a.len}" stroke-dashoffset="${-a.start}"></circle>`).join("");

  // Zahl so groß wie möglich: Schriftgröße richtet sich nach der Stellenzahl.
  const digits = String(total).length;
  const fs = digits <= 2 ? 104 : digits === 3 ? 84 : digits === 4 ? 64 : 50;

  const legend = arcs.map((a, i) =>
    `<div class="li" data-i="${i}">
       <div class="lrow">
         <span class="sw" style="background:${a.color}"></span>
         <span class="ln" title="${escC(a.name)}">${escC(a.name)}</span>
         <span class="lv">${a.val}</span>
         <span class="lp">${a.pct}</span>
       </div>
       <div class="lbar"><span style="width:${Math.max(a.frac * 100, 1.5)}%;background:${a.color}"></span></div>
     </div>`).join("");

  el.innerHTML = `
    <div class="donut-wrap">
      <svg viewBox="0 0 ${size} ${size}" role="img" aria-label="Vote-Verteilung nach Belohnung">
        <defs>
          <linearGradient id="dn-num" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0.1" stop-color="#ffffff"/><stop offset="0.55" stop-color="#dfe5ee"/><stop offset="1" stop-color="#97a2b6"/>
          </linearGradient>
          <radialGradient id="dn-disc" cx="50%" cy="22%" r="85%">
            <stop offset="0" stop-color="#ffffff" stop-opacity="0.16"/>
            <stop offset="0.55" stop-color="#ffffff" stop-opacity="0.04"/>
            <stop offset="1" stop-color="#000000" stop-opacity="0.16"/>
          </radialGradient>
          <linearGradient id="dn-rim" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stop-color="#ffffff" stop-opacity="0.55"/>
            <stop offset="0.5" stop-color="#ffffff" stop-opacity="0.08"/>
            <stop offset="1" stop-color="#ffffff" stop-opacity="0.28"/>
          </linearGradient>
        </defs>
        <!-- Glasscheibe in der Mitte mit Metallrand -->
        <circle cx="${cx}" cy="${cx}" r="${r - stroke / 2 - 9}" fill="url(#dn-disc)" stroke="url(#dn-rim)" stroke-width="1"/>
        <!-- Spur des Rings -->
        <circle cx="${cx}" cy="${cx}" r="${r}" fill="none" stroke="rgba(0,0,0,0.30)" stroke-width="${stroke}"/>
        <circle cx="${cx}" cy="${cx}" r="${r}" fill="none" stroke="rgba(255,255,255,0.05)" stroke-width="${stroke - 2}"/>
        <g class="segs" transform="rotate(-90 ${cx} ${cx})">${segs}</g>
        <text class="dn-num" x="${cx}" y="${cx - 4}" text-anchor="middle" dominant-baseline="central"
          fill="url(#dn-num)" font-size="${fs}">${total}</text>
        <text class="dn-cap" x="${cx}" y="${cx + fs / 2 + 12}" text-anchor="middle" dominant-baseline="central">VOTES</text>
      </svg>
      <div class="legend">${legend}</div>
    </div>`;

  // Segment und Legendenzeile heben sich gegenseitig hervor.
  const wrap = el.querySelector(".donut-wrap");
  const focus = (i) => {
    wrap.classList.toggle("has-focus", i !== null);
    wrap.querySelectorAll("[data-i]").forEach(n => n.classList.toggle("on", Number(n.dataset.i) === i));
  };
  wrap.querySelectorAll(".seg, .li").forEach((n) => {
    const i = Number(n.dataset.i), a = arcs[i];
    n.addEventListener("mouseenter", () => focus(i));
    n.addEventListener("mouseleave", () => { focus(null); hideTip(); });
    if (n.classList.contains("seg")) {
      n.addEventListener("mousemove", (ev) => showTip(ev, `<b>${escC(a.name)}</b><br>${a.val} Votes · ${a.pct}`));
    }
  });
}
