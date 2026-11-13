// Eigenständige Diagramme (SVG/HTML, keine externen Abhängigkeiten).
// Farben: kräftige Verläufe in der Farbfolge des Marken-Regenbogens.

// Clean-Rainbow-Verlauf (identisch zum CSS --grad)
const GRAD_STOPS = ["#34d6c6", "#4a9eff", "#8b7bff", "#e46fd1", "#ff9a63"];
function _hx(h) { h = h.replace("#", ""); return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)]; }
function _hex(r, g, b) { return "#" + [r, g, b].map(v => Math.round(Math.max(0, Math.min(255, v))).toString(16).padStart(2, "0")).join(""); }
function _lerp(a, b, t) { const A = _hx(a), B = _hx(b); return _hex(A[0] + (B[0] - A[0]) * t, A[1] + (B[1] - A[1]) * t, A[2] + (B[2] - A[2]) * t); }
// Kräftige Variante für Diagramme (Balken, Donut): gleiche Farbfolge, volle Sättigung.
const VIVID_STOPS = ["#00f0d0", "#0a8bff", "#9a4dff", "#ff35b0", "#ff8a00", "#ffe62e"];
function rainbowAt(frac, stops = GRAD_STOPS) { frac = Math.max(0, Math.min(1, frac)); const n = stops.length - 1; const x = frac * n; const i = Math.min(Math.floor(x), n - 1); return _lerp(stops[i], stops[i + 1], x - i); }

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
    // Die Balken teilen sich einen kräftigen Regenbogen: jeder Balken zeigt
    // seinen Abschnitt davon als Verlauf, der nächste setzt dort fort.
    const from = rainbowAt(i / data.length, VIVID_STOPS), to = rainbowAt((i + 1) / data.length, VIVID_STOPS);
    const fillStyle = `width:${pct}%;background:linear-gradient(90deg,${from},${to})`;
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

// --- Verteilung nach Belohnung: breiter Ring aus Verlaufsflächen, Zahl in der Mitte ---
// Kräftige Farbpaare (Anfang -> Ende eines Segments). Die Reihenfolge ist so
// gewählt, dass benachbarte Segmente klar verschiedene Farbtöne haben.
const DONUT_COLORS = [
  ["#00f0d0", "#0a8bff"],  // Türkis -> Blau
  ["#b03dff", "#ff35b0"],  // Violett -> Pink
  ["#ff8a00", "#ffe62e"],  // Orange -> Gelb
  ["#b6f02e", "#17d97a"],  // Limette -> Grün
  ["#3f6dff", "#9a4dff"],  // Blau -> Violett
  ["#ff2f6d", "#ff8a3d"],  // Rot-Pink -> Orange
];

function renderRewardDonut(el, byReward) {
  const entries = Object.entries(byReward || {}).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]);
  const total = entries.reduce((s, [, v]) => s + v, 0);
  if (!total) {
    el.classList.remove("donut");
    el.innerHTML = '<div class="empty">Noch keine Votes in dieser Session.</div>';
    return;
  }
  el.classList.add("donut");

  // Ring: außen 124, innen 90 -> 34 breit. cr = Eckenradius der Flächen.
  const size = 260, cx = size / 2, ro = 124, ri = 90, rm = (ro + ri) / 2, cr = 5;
  const re = ri - 8;                      // Radius der feinen Farblinie in der Mitte
  const TAU = 2 * Math.PI, top = -Math.PI / 2;
  const many = entries.length > 1;
  const gap = many ? 4 / rm : 0;          // Lücke zwischen zwei Flächen (als Winkel)
  const inset = many ? cr / rm : 0;       // Platz für die runden Ecken an den Enden
  // Sehr kleine Anteile bekommen eine Mindestbreite, damit sie als eigene
  // Fläche sichtbar bleiben; die übrigen teilen sich den Rest anteilig.
  const minSpan = gap + 2 * inset + 5 / rm;
  const isSmall = (v) => many && (v / total) * TAU < minSpan;
  const small = entries.filter(([, v]) => isSmall(v)).length;
  const restTotal = entries.reduce((s, [, v]) => s + (isSmall(v) ? 0 : v), 0);

  const pt = (r, a) => `${(cx + r * Math.cos(a)).toFixed(2)} ${(cx + r * Math.sin(a)).toFixed(2)}`;
  const sector = (a0, a1) =>
    `M${pt(ro - cr, a0)} A${ro - cr} ${ro - cr} 0 0 1 ${pt(ro - cr, a1)} L${pt(ri + cr, a1)} A${ri + cr} ${ri + cr} 0 0 0 ${pt(ri + cr, a0)}Z`;

  let pos = top, defs = "";
  const arcs = entries.map(([name, val], i) => {
    const frac = val / total;
    const [c0, c1] = DONUT_COLORS[i % DONUT_COLORS.length];
    const span = !many ? TAU : (isSmall(val) ? minSpan : (val / restTotal) * (TAU - small * minSpan));
    const a0 = pos + gap / 2 + inset, a1 = Math.max(pos + span - gap / 2 - inset, a0 + 0.002);
    pos += span;
    // Ein geschlossener Ring läuft Farbe A -> B -> A, damit oben keine Naht entsteht.
    const colorAt = (t) => _lerp(c0, c1, many ? t : 1 - Math.abs(2 * t - 1));
    // Der Verlauf soll dem Bogen folgen. SVG kennt nur gerade Verläufe, deshalb
    // wird die Fläche in Stücke von höchstens 90° geteilt, jedes mit eigenem
    // Verlauf entlang seiner Sehne. Die Stücke überlappen sich leicht und haben
    // an der Nahtstelle dieselbe Farbe, so bleibt der Übergang unsichtbar.
    const n = Math.max(1, Math.ceil((a1 - a0) / (Math.PI / 2)));
    let paths = "", echo = "";
    for (let k = 0; k < n; k++) {
      const s = a0 + (a1 - a0) * k / n, e = a0 + (a1 - a0) * (k + 1) / n;
      const last = k === n - 1;
      const id = `dn-g-${i}-${k}`;
      const [x1, y1] = pt(rm, s).split(" "), [x2, y2] = pt(rm, e).split(" ");
      defs += `<linearGradient id="${id}" gradientUnits="userSpaceOnUse" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}">
        <stop offset="0" stop-color="${colorAt(k / n)}"/><stop offset="1" stop-color="${colorAt((k + 1) / n)}"/></linearGradient>`;
      const over = last && many ? 0 : (2 * cr + 2) / rm;
      echo += `<path d="M${pt(re, s)} A${re} ${re} 0 0 1 ${pt(re, e)}" stroke="url(#${id})"/>`;
      paths += `<path d="${sector(s, e + over)}" fill="url(#${id})" stroke="url(#${id})" stroke-width="${2 * cr}" stroke-linejoin="round"/>`;
    }
    const pct = frac * 100 < 1 ? "<1%" : Math.round(frac * 100) + "%";
    return { name, val, frac, c0, c1, paths, echo, pct };
  });

  const segs = arcs.map((a, i) => `<g class="seg" data-i="${i}">${a.paths}</g>`).join("");

  // Schriftgröße der Zahl richtet sich nach der Stellenzahl.
  const digits = String(total).length;
  const fs = digits <= 2 ? 70 : digits === 3 ? 58 : digits === 4 ? 46 : 38;

  const legend = arcs.map((a, i) => {
    const grad = `linear-gradient(90deg,${a.c0},${a.c1})`;
    return `<div class="li" data-i="${i}">
       <div class="lrow">
         <span class="sw" style="background:${grad}"></span>
         <span class="ln" title="${escC(a.name)}">${escC(a.name)}</span>
         <span class="lv">${a.val}</span>
         <span class="lp">${a.pct}</span>
       </div>
       <div class="lbar"><span style="width:${Math.max(a.frac * 100, 1.5)}%;background:${grad}"></span></div>
     </div>`;
  }).join("");

  el.innerHTML = `
    <div class="donut-wrap">
      <svg viewBox="0 0 ${size} ${size}" role="img" aria-label="Vote-Verteilung nach Belohnung">
        <defs>
          <linearGradient id="dn-num" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0.1" stop-color="#ffffff"/><stop offset="0.55" stop-color="#dfe5ee"/><stop offset="1" stop-color="#97a2b6"/>
          </linearGradient>
          <linearGradient id="dn-well" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stop-color="#05070c" stop-opacity="0.62"/>
            <stop offset="1" stop-color="#05070c" stop-opacity="0.30"/>
          </linearGradient>
          <linearGradient id="dn-wellrim" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stop-color="#000000" stop-opacity="0.55"/>
            <stop offset="0.6" stop-color="#ffffff" stop-opacity="0.04"/>
            <stop offset="1" stop-color="#ffffff" stop-opacity="0.26"/>
          </linearGradient>
          <linearGradient id="dn-gloss" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stop-color="#ffffff" stop-opacity="0.20"/>
            <stop offset="0.5" stop-color="#ffffff" stop-opacity="0"/>
            <stop offset="1" stop-color="#000000" stop-opacity="0.14"/>
          </linearGradient>
          ${defs}
        </defs>
        <!-- Mitte: dunkle, eingelassene Mulde; darum eine feine Linie in den Segmentfarben -->
        <circle cx="${cx}" cy="${cx}" r="${re - 7}" fill="url(#dn-well)" stroke="url(#dn-wellrim)" stroke-width="1.2"/>
        <g class="echo" fill="none" stroke-width="2.5" stroke-linecap="round">${arcs.map((a, i) => `<g data-i="${i}">${a.echo}</g>`).join("")}</g>
        <!-- Spur des Rings -->
        <circle cx="${cx}" cy="${cx}" r="${rm}" fill="none" stroke="rgba(0,0,0,0.30)" stroke-width="${ro - ri}"/>
        <g class="segs">${segs}</g>
        <!-- Glanz: oben etwas heller, unten etwas dunkler -->
        <circle cx="${cx}" cy="${cx}" r="${rm}" fill="none" stroke="url(#dn-gloss)" stroke-width="${ro - ri}" pointer-events="none"/>
        <text class="dn-num" x="${cx}" y="${cx - 5}" text-anchor="middle" dominant-baseline="central"
          fill="url(#dn-num)" font-size="${fs}">${total}</text>
        <text class="dn-cap" x="${cx}" y="${cx + fs / 2 + 9}" text-anchor="middle" dominant-baseline="central">VOTES</text>
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
