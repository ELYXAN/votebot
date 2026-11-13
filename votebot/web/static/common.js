// Gemeinsame Helfer für Wizard & Dashboard.

async function api(path, method = "GET", body = null) {
  const opts = { method, headers: {} };
  if (body !== null) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  let data = {};
  try { data = await res.json(); } catch (e) {}
  if (!res.ok) {
    throw new Error(data.error || data.detail || `HTTP ${res.status}`);
  }
  return data;
}

function getState() { return api("/api/state"); }

function $(id) { return document.getElementById(id); }

function showMsg(id, text, kind = "info") {
  const el = $(id);
  if (!el) return;
  el.className = "msg " + kind;
  el.textContent = text;
}

function copyText(id) {
  const el = $(id);
  const text = el.textContent || el.value;
  navigator.clipboard.writeText(text).then(() => {
    const old = el.dataset.old;
    if (!old) el.dataset.old = "1";
  }).catch(() => {});
}

function esc(s) {
  return (s == null ? "" : String(s)).replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}

// --- Zahlenfelder mit eigenen Minus-/Plus-Knöpfen ---
// Ersetzt die winzigen Browser-Pfeile: jedes <input type="number"> bekommt
// links ein Minus und rechts ein Plus. min, max und step des Feldes gelten
// weiter; Gedrückthalten zählt fortlaufend. Später eingefügte Felder (z. B. im
// Einrichtungs-Assistenten) werden automatisch erfasst.
const STEP_ICONS = {
  "-1": '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3.5 8h9"/></svg>',
  "1": '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3.5 8h9M8 3.5v9"/></svg>',
};

function makeStepper(input) {
  if (input.dataset.stepper) return;
  input.dataset.stepper = "1";
  const wrap = document.createElement("div");
  wrap.className = "stepper";
  if (input.title) wrap.title = input.title;
  if (input.style.width) { wrap.style.width = input.style.width; input.style.width = ""; }
  input.parentNode.insertBefore(wrap, input);

  const num = (attr) => (input[attr] === "" ? null : Number(input[attr]));
  const btns = {};
  const sync = () => {
    const v = input.value === "" ? null : Number(input.value), min = num("min"), max = num("max");
    wrap.classList.toggle("disabled", input.disabled);
    btns[-1].disabled = input.disabled || (v !== null && min !== null && v <= min);
    btns[1].disabled = input.disabled || (v !== null && max !== null && v >= max);
  };
  const step = (dir) => {
    if (btns[dir].disabled) return;
    try { dir > 0 ? input.stepUp() : input.stepDown(); } catch (e) { return; }
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
    sync();
  };

  for (const dir of [-1, 1]) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "step";
    b.tabIndex = -1;  // Tastatur: Pfeiltasten im Feld selbst
    b.setAttribute("aria-label", dir > 0 ? "Erhöhen" : "Verringern");
    b.innerHTML = STEP_ICONS[dir];
    let wait = null, repeat = null;
    const stop = () => { clearTimeout(wait); clearInterval(repeat); wait = repeat = null; };
    b.addEventListener("pointerdown", (ev) => {
      if (ev.button !== 0) return;
      ev.preventDefault();  // Fokus bleibt, wo er ist
      stop();
      step(dir);
      wait = setTimeout(() => { repeat = setInterval(() => step(dir), 70); }, 380);
    });
    for (const type of ["pointerup", "pointerleave", "pointercancel"]) b.addEventListener(type, stop);
    btns[dir] = b;
  }
  wrap.append(btns[-1], input, btns[1]);
  input.addEventListener("input", sync);
  input.addEventListener("change", sync);
  wrap.addEventListener("pointerenter", sync);  // Wert kann per Skript geändert worden sein
  sync();
}

// --- Auswahlfelder im eigenen Design ---
// Ersetzt die Browser-Darstellung von <select>: ein Knopf im Stil der
// Eingabefelder und eine eigene Liste darunter. Das echte <select> bleibt
// unsichtbar im Dokument und behält Wert und change-Ereignis, sodass der
// übrige Code nichts davon merkt. Tastatur: Pfeile, Enter/Leertaste, Escape.
const DD_CHEVRON = '<svg class="dd-chev" viewBox="0 0 16 16" aria-hidden="true"><path d="M4 6.5l4 4 4-4"/></svg>';
const DD_CHECK = '<svg class="dd-check" viewBox="0 0 16 16" aria-hidden="true"><path d="M3.5 8.5l3 3 6-7"/></svg>';
let _ddSeq = 0;

function makeDropdown(select) {
  if (select.dataset.dropdown || select.multiple) return;
  select.dataset.dropdown = "1";
  const uid = "dd" + (++_ddSeq);
  const wrap = document.createElement("div");
  wrap.className = "dd";
  select.parentNode.insertBefore(wrap, select);
  select.classList.add("dd-native");
  select.tabIndex = -1;
  select.setAttribute("aria-hidden", "true");

  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "dd-btn";
  btn.setAttribute("aria-haspopup", "listbox");
  btn.setAttribute("aria-expanded", "false");
  btn.innerHTML = `<span class="dd-val"></span>${DD_CHEVRON}`;
  const list = document.createElement("div");
  list.className = "dd-list";
  list.id = uid + "-list";
  list.setAttribute("role", "listbox");
  btn.setAttribute("aria-controls", list.id);
  wrap.append(select, btn, list);

  let active = -1;  // per Tastatur/Maus markierter Eintrag
  const isOpen = () => wrap.classList.contains("open");
  const setActive = (i) => {
    active = i;
    list.querySelectorAll(".dd-opt").forEach((o, k) => o.classList.toggle("active", k === i));
    if (i >= 0) btn.setAttribute("aria-activedescendant", `${uid}-o${i}`);
    else btn.removeAttribute("aria-activedescendant");
  };
  // Knopftext und Liste aus dem aktuellen Stand des <select> aufbauen.
  const render = () => {
    const opts = [...select.options], cur = select.selectedIndex;
    btn.querySelector(".dd-val").textContent = cur >= 0 ? opts[cur].textContent : "";
    btn.disabled = select.disabled;
    list.innerHTML = opts.map((o, i) =>
      `<div class="dd-opt${i === cur ? " selected" : ""}${o.disabled ? " disabled" : ""}" id="${uid}-o${i}" role="option"
         data-i="${i}" aria-selected="${i === cur}"><span>${esc(o.textContent)}</span>${DD_CHECK}</div>`).join("");
  };
  const open = () => {
    if (select.disabled || isOpen()) return;
    render();
    wrap.classList.add("open");
    btn.setAttribute("aria-expanded", "true");
    setActive(select.selectedIndex);
  };
  const close = () => {
    wrap.classList.remove("open");
    btn.setAttribute("aria-expanded", "false");
    setActive(-1);
  };
  const choose = (i) => {
    const o = select.options[i];
    if (!o || o.disabled) return;
    const changed = select.selectedIndex !== i;
    select.selectedIndex = i;
    close();
    render();
    if (changed) {
      select.dispatchEvent(new Event("input", { bubbles: true }));
      select.dispatchEvent(new Event("change", { bubbles: true }));
    }
  };
  const move = (dir) => {
    const n = select.options.length;
    let i = active;
    for (let k = 0; k < n; k++) {
      i = (i + dir + n) % n;
      if (!select.options[i].disabled) { setActive(i); return; }
    }
  };

  btn.addEventListener("click", () => (isOpen() ? close() : open()));
  btn.addEventListener("keydown", (ev) => {
    const k = ev.key;
    if (!isOpen()) {
      if (k === "ArrowDown" || k === "ArrowUp") { ev.preventDefault(); open(); }
      return;  // Enter/Leertaste öffnen über das normale click-Ereignis
    }
    if (k === "ArrowDown") { ev.preventDefault(); move(1); }
    else if (k === "ArrowUp") { ev.preventDefault(); move(-1); }
    else if (k === "Home") { ev.preventDefault(); active = -1; move(1); }
    else if (k === "End") { ev.preventDefault(); active = 0; move(-1); }
    else if (k === "Enter" || k === " ") { ev.preventDefault(); choose(active); }
    else if (k === "Escape") { ev.preventDefault(); close(); }
    else if (k === "Tab") close();
  });
  list.addEventListener("pointermove", (ev) => {
    const o = ev.target.closest(".dd-opt");
    if (o && Number(o.dataset.i) !== active) setActive(Number(o.dataset.i));
  });
  list.addEventListener("click", (ev) => {
    const o = ev.target.closest(".dd-opt");
    if (o) { choose(Number(o.dataset.i)); btn.focus(); }
  });
  document.addEventListener("pointerdown", (ev) => { if (isOpen() && !wrap.contains(ev.target)) close(); });
  select.addEventListener("change", render);  // z. B. wenn ein Skript change auslöst
  render();
}

function enhanceControls(root) {
  if (root.matches && root.matches('input[type="number"]')) makeStepper(root);
  if (root.matches && root.matches("select")) makeDropdown(root);
  if (root.querySelectorAll) {
    root.querySelectorAll('input[type="number"]').forEach(makeStepper);
    root.querySelectorAll("select").forEach(makeDropdown);
  }
}

enhanceControls(document);
new MutationObserver((muts) => {
  for (const m of muts) m.addedNodes.forEach((n) => { if (n.nodeType === 1) enhanceControls(n); });
}).observe(document.documentElement, { childList: true, subtree: true });
