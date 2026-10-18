// Setup-Wizard-Steuerung (modusabhängig: Entwickler vs. End-User).

const ALL_LABELS = { 0: "Twitch-App", 1: "Streamer", 2: "Chat", 3: "Belohnungen", 4: "Google Sheet", 5: "AI", 6: "Fertig" };
const OPTIONAL = new Set([5, 6]); // dürfen ohne Pflichteingabe übersprungen werden
const STEP_HINT = {
  0: ["msg-app", "Bitte zuerst Client-ID und Client-Secret speichern."],
  1: ["msg-broadcaster", "Bitte zuerst mit deinem Streamer-Account anmelden."],
  2: ["msg-chat", "Bitte Chat-Account festlegen (bzw. Bot-Account anmelden)."],
  3: ["msg-rewards", "Bitte lege mindestens eine Belohnung an."],
  4: ["msg-sheet", "Bitte Google-Sheet verbinden (Link einfügen & speichern)."],
};

let activeSteps = [0, 1, 2, 3, 4, 5, 6];
let pos = 0;
let stateCache = null;

const PRESETS = [
  { id: "normal", title: "Normaler Vote", kind: "vote", cost: 100, weight: 1, checked: true },
  { id: "super", title: "Super Vote", kind: "vote", cost: 500, weight: 10, checked: true },
  { id: "ultra", title: "Ultra Vote", kind: "vote", cost: 1000, weight: 25, checked: false },
  { id: "ai", title: "AI Chat", kind: "ai", cost: 1000, weight: 0, checked: false },
];

function domStep() { return activeSteps[pos]; }

function stepDone(dom) {
  const s = stateCache.status;
  return { 0: s.twitch_app, 1: s.broadcaster, 2: s.chat, 3: s.rewards, 4: s.sheets, 5: true, 6: true }[dom];
}

function canReachPos(j) {
  for (let k = 0; k < j; k++) {
    const dom = activeSteps[k];
    if (!OPTIONAL.has(dom) && !stepDone(dom)) return false;
  }
  return true;
}

function renderSteps() {
  const wrap = $("steps");
  wrap.innerHTML = "";
  activeSteps.forEach((dom, i) => {
    const chip = document.createElement("div");
    chip.className = "step-chip" + (i === pos ? " active" : "") + (stepDone(dom) ? " done" : "");
    chip.innerHTML = `<span>${i + 1}</span> ${esc(ALL_LABELS[dom])}`;
    chip.onclick = () => gotoPos(i);
    wrap.appendChild(chip);
  });
}

function gotoPos(j) {
  j = Math.max(0, Math.min(activeSteps.length - 1, j));
  if (j > pos && !canReachPos(j)) {
    // Erstes unerledigtes Pflichtfeld markieren.
    for (let k = pos; k < j; k++) {
      const dom = activeSteps[k];
      if (!OPTIONAL.has(dom) && !stepDone(dom)) { pos = k; showStepHint(dom); break; }
    }
    applyPos();
    return;
  }
  pos = j;
  applyPos();
}

function applyPos() {
  const dom = domStep();
  document.querySelectorAll(".step").forEach(el => {
    el.classList.toggle("hidden", Number(el.dataset.step) !== dom);
  });
  $("nav-back").classList.toggle("hidden", pos === 0);
  const next = $("nav-next");
  const isLast = pos === activeSteps.length - 1;
  next.classList.toggle("hidden", isLast);
  const blocked = !OPTIONAL.has(dom) && !stepDone(dom);
  next.disabled = blocked;
  next.title = blocked ? (STEP_HINT[dom] ? STEP_HINT[dom][1] : "Bitte diesen Schritt abschließen.") : "";
  renderSteps();
  if (dom === 6) renderSummary();
  window.scrollTo(0, 0);
}

function nextStep() {
  const dom = domStep();
  if (!OPTIONAL.has(dom) && !stepDone(dom)) { showStepHint(dom); return; }
  gotoPos(pos + 1);
}
function prevStep() { gotoPos(pos - 1); }
// Rückwärtskompatibel (aus HTML-Buttons): zu einem DOM-Schritt springen.
function gotoStep(dom) { const i = activeSteps.indexOf(dom); if (i >= 0) gotoPos(i); }

function showStepHint(dom) {
  const h = STEP_HINT[dom];
  if (h) showMsg(h[0], h[1], "err");
}

async function refresh() {
  const prevDom = stateCache ? domStep() : null;
  stateCache = await getState();

  activeSteps = stateCache.mode === "enduser" ? [1, 2, 3, 4, 5, 6] : [0, 1, 2, 3, 4, 5, 6];
  if (prevDom !== null) { const i = activeSteps.indexOf(prevDom); pos = i >= 0 ? i : Math.min(pos, activeSteps.length - 1); }

  // Modus-Badge
  const badge = $("mode-badge");
  if (stateCache.mode === "developer") { badge.textContent = "Entwickler-Modus"; badge.classList.remove("hidden"); }
  else { badge.classList.add("hidden"); }

  // Felder vorbefüllen
  if ($("client_id")) $("client_id").value = stateCache.twitch.client_id || "";
  if (stateCache.twitch.client_secret_set && $("client_secret")) $("client_secret").placeholder = "•••••••• (gespeichert)";
  if ($("redirect-uri")) $("redirect-uri").textContent = stateCache.redirect_uri;
  $("spreadsheet_id").value = stateCache.sheets.spreadsheet_id || "";
  $("openai_model").value = stateCache.openai.model || "gpt-4o";
  if (stateCache.openai.api_key_set) $("openai_key").placeholder = "•••••••• (gespeichert)";

  updateOAuthStatus(stateCache.broadcaster.linked, stateCache.broadcaster.login, "broadcaster-status");
  updateOAuthStatus(stateCache.chat_bot.linked, stateCache.chat_bot.login, "bot-status");

  const mode = stateCache.chat_bot.use_broadcaster ? "broadcaster" : "bot";
  document.querySelectorAll("input[name=chatmode]").forEach(r => r.checked = r.value === mode);
  $("bot-login").classList.toggle("hidden", mode !== "bot");

  // Google-Sheets-Variante
  const bundled = stateCache.bundle.sheets;
  $("sheet-bundled").classList.toggle("hidden", !bundled);
  $("sheet-upload").classList.toggle("hidden", bundled);
  if (bundled && stateCache.sheets.service_account_email) $("sa-email").textContent = stateCache.sheets.service_account_email;
  if (stateCache.sheets.service_account_set && $("sa-status")) $("sa-status").textContent = "✓ JSON gespeichert";

  // Entwickler-Bundle-Karte
  $("dev-bundle").classList.toggle("hidden", stateCache.mode !== "developer");

  renderPresets();
  renderRewardList();
  renderSteps();
  applyPos();
  $("to-dashboard").classList.toggle("hidden", !stateCache.status.complete);
}

function updateOAuthStatus(linked, login, elId) {
  const el = $(elId);
  if (!el) return;
  el.className = "pill " + (linked ? "ok" : "off");
  el.innerHTML = `<span class="dot ${linked ? "ok" : "off"}"></span> ${linked ? "verknüpft: " + esc(login) : "nicht verknüpft"}`;
}

// --- Twitch-App ---
async function saveTwitchApp() {
  const client_id = $("client_id").value.trim();
  const client_secret = $("client_secret").value.trim();
  if (!client_id) return showMsg("msg-app", "Client-ID fehlt.", "err");
  if (!client_secret && !stateCache.twitch.client_secret_set)
    return showMsg("msg-app", "Client-Secret fehlt.", "err");
  try {
    const body = { client_id };
    if (client_secret) body.client_secret = client_secret;
    await api("/api/twitch/app", "POST", body);
    showMsg("msg-app", "Gespeichert!", "ok");
    await refresh();
    nextStep();
  } catch (e) { showMsg("msg-app", e.message, "err"); }
}

// --- OAuth ---
async function startOAuth(account) {
  try {
    const { url } = await api(`/api/oauth/start?account=${account}`);
    window.open(url, "votebot_oauth", "width=520,height=720");
  } catch (e) {
    showMsg(account === "broadcaster" ? "msg-broadcaster" : "msg-chat", e.message, "err");
  }
}

window.addEventListener("message", (ev) => {
  if (ev.data && ev.data.votebotOAuth) setTimeout(refresh, 400);
});

// --- Chat-Modus ---
async function onChatMode() {
  const mode = document.querySelector("input[name=chatmode]:checked").value;
  $("bot-login").classList.toggle("hidden", mode !== "bot");
  try { await api("/api/chat/mode", "POST", { use_broadcaster: mode === "broadcaster" }); await refresh(); }
  catch (e) { showMsg("msg-chat", e.message, "err"); }
}

// --- Rewards ---
function renderPresets() {
  const wrap = $("reward-presets");
  const existing = new Set((stateCache.rewards || []).map(r => r.title.toLowerCase()));
  wrap.innerHTML = "";
  PRESETS.forEach(p => {
    const already = existing.has(p.title.toLowerCase());
    const div = document.createElement("div");
    div.className = "reward-item";
    div.innerHTML = `
      <div class="row" style="gap:.6rem">
        <input type="checkbox" id="pre-${p.id}" ${p.checked && !already ? "checked" : ""} ${already ? "disabled" : ""}>
        <div class="meta">
          <span class="t">${esc(p.title)} <span class="tag ${p.kind === "ai" ? "ai" : ""}">${p.kind}</span></span>
          <span class="s">${already ? "bereits angelegt" : "Kosten/Gewicht anpassbar"}</span>
        </div>
      </div>
      <div class="row" style="gap:.4rem">
        <input type="text" id="pre-${p.id}-title" value="${esc(p.title)}" style="width:150px" ${already ? "disabled" : ""}>
        <input type="number" id="pre-${p.id}-cost" value="${p.cost}" title="Kosten (Punkte)" style="width:90px" ${already ? "disabled" : ""}>
        ${p.kind === "vote" ? `<input type="number" id="pre-${p.id}-weight" value="${p.weight}" title="Vote-Gewicht" style="width:70px" ${already ? "disabled" : ""}>` : ""}
      </div>`;
    wrap.appendChild(div);
  });
}

async function createPresetRewards() {
  const btn = $("btn-rewards");
  btn.disabled = true;
  let created = 0, errors = [];
  for (const p of PRESETS) {
    const cb = $(`pre-${p.id}`);
    if (!cb || !cb.checked || cb.disabled) continue;
    const body = { title: $(`pre-${p.id}-title`).value.trim(), kind: p.kind, cost: Number($(`pre-${p.id}-cost`).value) || p.cost };
    if (p.kind === "vote") body.weight = Number($(`pre-${p.id}-weight`).value) || 1;
    try { await api("/api/rewards/create", "POST", body); created++; }
    catch (e) { errors.push(`${body.title}: ${e.message}`); }
  }
  btn.disabled = false;
  await refresh();
  if (errors.length) showMsg("msg-rewards", `Angelegt: ${created}. Fehler: ${errors.join(" | ")}`, created ? "info" : "err");
  else showMsg("msg-rewards", `${created} Belohnung(en) angelegt.`, "ok");
}

function renderRewardList() {
  const wrap = $("reward-list");
  const rewards = stateCache.rewards || [];
  if (!rewards.length) { wrap.innerHTML = '<p class="muted">Noch keine.</p>'; return; }
  wrap.innerHTML = "";
  rewards.forEach(r => {
    const div = document.createElement("div");
    div.className = "reward-item";
    div.innerHTML = `
      <div class="meta">
        <span class="t">${esc(r.title)} <span class="tag ${r.kind === "ai" ? "ai" : ""}">${r.kind}</span></span>
        <span class="s">${r.kind === "vote" ? "Gewicht: " + (r.weight || 1) : "AI-Antwort"}</span>
      </div>
      <button class="small danger" onclick="removeReward('${esc(r.reward_id)}')">Entfernen</button>`;
    wrap.appendChild(div);
  });
}

async function removeReward(id) {
  if (!confirm("Belohnung aus Votebot entfernen? (Die Twitch-Belohnung bleibt bestehen.)")) return;
  try { await api(`/api/rewards/${encodeURIComponent(id)}`, "DELETE"); await refresh(); }
  catch (e) { showMsg("msg-rewards", e.message, "err"); }
}

// --- Google Sheets ---
function onFilePicked() {
  const file = $("sa-file").files[0];
  const drop = $("sa-drop");
  if (file) {
    $("sa-fname").textContent = file.name;
    $("sa-drop").querySelector(".fd-title").textContent = "Datei gewählt – jetzt hochladen";
    drop.classList.add("has-file");
  } else {
    drop.classList.remove("has-file");
  }
}

async function uploadServiceAccount() {
  const file = $("sa-file").files[0];
  if (!file) return showMsg("msg-sheet", "Bitte zuerst eine Datei wählen.", "err");
  const fd = new FormData();
  fd.append("file", file);
  try {
    const res = await fetch("/api/sheets/upload", { method: "POST", body: fd });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Upload fehlgeschlagen");
    $("sa-status").textContent = "✓ JSON gespeichert";
    showMsg("sa-share", `Teile dein Google-Sheet mit dieser E-Mail (Bearbeiter): ${data.client_email}`, "info");
  } catch (e) { showMsg("msg-sheet", e.message, "err"); }
}

async function saveSheet() {
  try {
    await api("/api/sheets/config", "POST", { spreadsheet_id: $("spreadsheet_id").value.trim() });
    showMsg("msg-sheet", "Gespeichert.", "ok");
    await refresh();
  } catch (e) { showMsg("msg-sheet", e.message, "err"); }
}

async function testSheet() {
  showMsg("msg-sheet", "Teste Verbindung…", "info");
  try {
    await api("/api/sheets/config", "POST", { spreadsheet_id: $("spreadsheet_id").value.trim() });
    const res = await fetch("/api/sheets/test", { method: "POST" });
    const data = await res.json();
    if (data.ok) showMsg("msg-sheet", `✓ Verbunden mit "${data.spreadsheet_title}" (Blatt: ${data.worksheet_title}).`, "ok");
    else {
      let hint = data.error;
      if (data.service_account_email) hint += ` – Sheet mit ${data.service_account_email} geteilt?`;
      showMsg("msg-sheet", hint, "err");
    }
    await refresh();
  } catch (e) { showMsg("msg-sheet", e.message, "err"); }
}

// --- OpenAI ---
async function saveOpenAI() {
  try {
    await api("/api/openai", "POST", { api_key: $("openai_key").value.trim(), model: $("openai_model").value.trim() });
    showMsg("msg-openai", "Gespeichert.", "ok");
    await refresh();
    nextStep();
  } catch (e) { showMsg("msg-openai", e.message, "err"); }
}

// --- Entwickler: Weitergabe-Bundle ---
async function createBundle() {
  try {
    const includeSheets = $("bundle-sheets").checked;
    const res = await api("/api/dev/bundle", "POST", { include_sheets: includeSheets });
    let warn = "";
    if (res.sheets_requested && !res.sheets_bundled)
      warn = " ⚠️ Kein Service-Account vorhanden – Sheets NICHT gebündelt. Richte zuerst Google Sheets ein.";
    showMsg("msg-bundle", "app_credentials.json erstellt." + warn, warn ? "info" : "ok");
    $("bundle-result").innerHTML = `
      <p class="muted" style="font-size:.85rem">Für die Weitergabe <b>diese Dateien mitgeben</b>:</p>
      <div class="code">${res.include.map(esc).join("  ·  ")}</div>
      <p class="muted" style="font-size:.85rem" class="mt"><b>Nicht</b> mitgeben (persönlich): ${res.exclude.map(esc).join(", ")}</p>
      <p class="muted" style="font-size:.85rem">Hinweis: Deine eigene Ansicht läuft nach einem Neuladen im End-User-Modus.
      Zum Weiterentwickeln <code>app_credentials.json</code> löschen oder „Bundle entfernen" klicken.</p>`;
  } catch (e) { showMsg("msg-bundle", e.message, "err"); }
}

async function deleteBundle() {
  try {
    await api("/api/dev/bundle", "DELETE");
    showMsg("msg-bundle", "Bundle entfernt – wieder Entwickler-Modus.", "ok");
    $("bundle-result").innerHTML = "";
    await refresh();
  } catch (e) { showMsg("msg-bundle", e.message, "err"); }
}

function renderSummary() {
  if (!stateCache) return;
  const s = stateCache.status;
  const item = (ok, label) => `<div class="row" style="gap:.5rem"><span class="dot ${ok ? "ok" : "off"}"></span> ${label}</div>`;
  $("final-summary").innerHTML =
    (stateCache.mode === "developer" ? item(s.twitch_app, "Twitch-App") : "") +
    item(s.broadcaster, "Streamer-Login") +
    item(s.chat, "Chat-Benachrichtigungen") +
    item(s.rewards, `Belohnungen (${(stateCache.rewards || []).length})`) +
    item(s.sheets, "Google Sheet") +
    item(s.openai, "AI-Chat (optional)");
}

// --- Start ---
(async function init() {
  await refresh();
  const s = stateCache.status;
  let dom = 6;
  if (stateCache.mode === "developer" && !s.twitch_app) dom = 0;
  else if (!s.broadcaster) dom = 1;
  else if (!s.rewards) dom = 3;
  else if (!s.sheets) dom = 4;
  gotoStep(dom);
})();
