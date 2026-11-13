// Dashboard-Logik: WebSocket-Log/Status, Bot-Steuerung, Rewards, Votes, Einstellungen.

let ws = null;
let running = false;

function connectWS() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === "history") { appendLogs(msg.logs); }
    else if (msg.type === "log") { appendLogs([msg.data]); }
    else if (msg.type === "status") { applyStatus(msg.data); }
  };
  ws.onclose = () => { setTimeout(connectWS, 2000); };
}

// Fügt Log-Zeilen in einem Rutsch ein: Scrollposition einmal messen, alle
// Zeilen gemeinsam einhängen, einmal scrollen. So kostet auch der Verlauf
// beim Laden (bis zu 500 Zeilen) nur eine Layout-Berechnung.
function appendLogs(entries) {
  if (!entries || !entries.length) return;
  const box = $("log");
  const atBottom = box.scrollTop + box.clientHeight >= box.scrollHeight - 30;
  const frag = document.createDocumentFragment();
  for (const entry of entries) {
    const line = document.createElement("div");
    line.className = "line " + entry.level;
    line.innerHTML = `<span class="t">${esc(entry.time)}</span><span class="lvl">${esc(entry.level)}</span><span class="m">${esc(entry.message)}</span>`;
    frag.appendChild(line);
  }
  box.appendChild(frag);
  while (box.childElementCount > 600) box.removeChild(box.firstChild);
  if (atBottom) box.scrollTop = box.scrollHeight;
}

function clearLog() { $("log").innerHTML = ""; }

// Der Server schickt alle 2 Sekunden den kompletten Status. Damit der Browser
// nicht jedes Mal alle Widgets neu aufbaut und neu zeichnet, wird jedes Widget
// nur angefasst, wenn sich seine Daten geändert haben.
const _lastData = {};
function changed(key, data) {
  const sig = JSON.stringify(data);
  if (_lastData[key] === sig) return false;
  _lastData[key] = sig;
  return true;
}
function setText(id, value) {
  const el = $(id), text = String(value);
  if (el.textContent !== text) el.textContent = text;
}

// --- Kennzahlen-Kacheln oben ---
// Speisen sich aus zwei Quellen: dem Status (Session) und der Rangliste aus
// dem Sheet (Gesamtwerte). Beide rufen renderKpis() auf, sobald sie Neues haben.
const _kpi = { status: null, standings: null, sessionSeen: false };
const fmtNum = (n) => Number(n || 0).toLocaleString("de-DE");
function setKpi(id, value) { setText(id, fmtNum(value)); }

function renderKpis() {
  const bot = (_kpi.status && _kpi.status.bot) || {};
  const st = bot.stats || {};

  // Votes · Session: gewichtete Votes (ein Super Vote zählt mit seinem Gewicht),
  // also dieselbe Einheit wie im Sheet. Darunter die Zahl der Einlösungen.
  const sessionVotes = Object.values(st.votes_by_game || {}).reduce((a, b) => a + b, 0);
  const redeemed = st.votes_processed || 0;
  setKpi("st-votes", sessionVotes);
  setText("sub-votes", redeemed ? `aus ${fmtNum(redeemed)} ${redeemed === 1 ? "Einlösung" : "Einlösungen"}` : "in dieser Session");

  const voters = Object.entries(st.voters || {});
  setKpi("st-voters", voters.length);
  const top = voters.sort((a, b) => (b[1].weight || 0) - (a[1].weight || 0))[0];
  setText("sub-voters", top ? `aktivster: ${top[0]} (${fmtNum(top[1].weight)})` : "in dieser Session");

  const standings = _kpi.standings;
  if (standings) {
    const voted = standings.filter(g => Number(g.votes) > 0);
    setKpi("st-total", voted.reduce((a, g) => a + Number(g.votes), 0));
    setKpi("st-games", standings.length);
    setText("sub-games", voted.length ? `davon ${fmtNum(voted.length)} mit Votes` : "im Google Sheet");
  } else {
    setKpi("st-games", bot.games_count || 0);
  }
  // Alle Kacheln teilen sich eine Schriftgröße: sie richtet sich nach der
  // längsten Zahl (style.css rechnet mit --kpi-chars). Der Tausenderpunkt ist
  // schmal und zählt nur halb.
  const kpis = document.querySelector(".kpis");
  const width = (text) => text.replace(/\./g, "").length + (text.split(".").length - 1) * 0.5;
  const chars = String(Math.max(3, ...[...kpis.querySelectorAll(".v")].map(v => width(v.textContent))));
  if (kpis.style.getPropertyValue("--kpi-chars") !== chars) kpis.style.setProperty("--kpi-chars", chars);
}

function applyStatus(s) {
  const bot = s.bot || {};
  running = bot.running;
  if (changed("pill", [running, bot.push_live])) {
    const pill = $("bot-pill");
    pill.className = "pill " + (running ? "run" : "stop");
    // "Echtzeit" = Votes kommen per Twitch-Push, "Abfrage" = Rückfall auf Sekundentakt.
    const mode = !running ? "gestoppt" : (bot.push_live ? "läuft · Echtzeit" : "läuft · Abfrage");
    pill.title = !running ? "" : (bot.push_live
      ? "Votes kommen in Echtzeit über Twitch EventSub an."
      : "Echtzeit-Verbindung steht gerade nicht. Votes werden alle 2 Sekunden abgefragt.");
    pill.innerHTML = `<span class="dot ${running ? "ok" : "off"}"></span> ${mode}`;
  }
  setText("btn-toggle", running ? "⏸ Stoppen" : "▶ Starten");
  setText("channel-label", s.broadcaster.login ? "Kanal: " + s.broadcaster.login : "");

  const st = bot.stats || {};
  _kpi.status = s;
  renderKpis();

  const byReward = st.votes_by_reward || {};
  if (changed("donut", byReward)) renderRewardDonut($("chart-rewards"), byReward);

  const byGame = st.votes_by_game || {};
  const voters = st.voters || {};
  if (changed("session", [byGame, Object.keys(voters).length])) {
    // Ein neuer Vote ändert auch die Gesamt-Rangliste. Der Server hat sie
    // schon aktualisiert, der Abruf löst also keinen Sheets-Zugriff aus.
    if (_kpi.sessionSeen) loadStandings();
    _kpi.sessionSeen = true;
    renderSessionTop($("chart-session"), byGame);
    const sesGames = Object.keys(byGame).length;
    renderFoot($("foot-session"), sesGames ? [
      [Object.values(byGame).reduce((a, b) => a + b, 0), "Votes"],
      [sesGames, "Spiele"],
      [Object.keys(voters).length, "Voter"],
    ] : []);
  }
  if (changed("voters", voters)) {
    renderVoters($("voters"), voters);
    const vc = Object.keys(voters).length;
    setText("voters-count", vc ? `${vc} Voter` : "");
  }
  const rewards = s.rewards || [];
  if (changed("rewards", rewards)) renderRewards(rewards);

  // Warnung, wenn der Chat-Account keine Schreib-Berechtigung hat.
  const needsReauth = s.status && s.status.chat && !s.status.chat_scope;
  $("scope-warn").classList.toggle("hidden", !needsReauth);

  // Einstellungen vorbefüllen (nur initial, nicht bei jedem Tick überschreiben).
  if (!window._settingsInit) {
    $("set-score").value = (s.matching && s.matching.min_match_score) || 80;
    $("set-manual-user").value = s.manual_vote_user || "Dashboard";
    $("set-autostart").checked = !!s.autostart_bot;
    $("set-model").value = (s.openai && s.openai.model) || "gpt-4o";
    $("key-set-label").textContent = s.openai && s.openai.api_key_set ? "(gesetzt)" : "(nicht gesetzt)";
    window._settingsInit = true;
  }
}

async function toggleBot() {
  const btn = $("btn-toggle");
  btn.disabled = true;
  try {
    await api(running ? "/api/bot/stop" : "/api/bot/start", "POST");
  } catch (e) { alert(e.message); }
  btn.disabled = false;
}

// --- Top-Spiele-Chart (Gesamt, aus dem Sheet) ---
// fresh=true liest direkt aus dem Sheet (Aktualisieren-Knopf), sonst darf der
// Server einen wenige Sekunden alten Stand liefern.
async function loadStandings(fresh = false) {
  try {
    const { standings } = await api("/api/sheets/standings" + (fresh ? "?fresh=1" : ""));
    _kpi.standings = standings || [];
    renderKpis();
    if (!changed("standings", standings)) return;  // unverändert -> nichts neu zeichnen
    renderTopGames($("chart-top"), standings);
    const voted = (standings || []).filter(s => Number(s.votes) > 0);
    renderFoot($("foot-top"), voted.length ? [
      [voted.reduce((a, s) => a + Number(s.votes), 0), "Votes gesamt"],
      [voted.length, "Spiele mit Votes"],
    ] : []);
    renderQuickPicks(voted.slice(0, 8).map(s => s.name));
  } catch (e) {
    delete _lastData.standings;  // nach einem Fehler beim nächsten Erfolg wieder zeichnen
    renderFoot($("foot-top"), []);
    $("chart-top").classList.remove("bars");
    $("chart-top").innerHTML = `<div class="empty">${esc(e.message)}</div>`;
  }
}

async function resetStats() {
  if (!confirm("Session-Statistiken (Session-Votes, Verteilung, Zähler) zurücksetzen?")) return;
  try { await api("/api/stats/reset", "POST"); } catch (e) { alert(e.message); }
}

// --- Manueller Vote ---
// Schnellauswahl: Klick auf ein Top-Spiel trägt den Namen ins Feld ein.
function renderQuickPicks(names) {
  const wrap = $("mv-quick");
  wrap.innerHTML = "";
  names.forEach(name => {
    const b = document.createElement("button");
    b.type = "button"; b.className = "secondary"; b.textContent = name; b.title = name;
    b.onclick = () => { $("mv-game").value = name; $("mv-game").focus(); };
    wrap.appendChild(b);
  });
}

async function manualVote() {
  const game = $("mv-game").value.trim();
  const count = Number($("mv-count").value) || 1;
  if (!game) return showMsg("msg-mv", "Spielname fehlt.", "err");
  try {
    await api("/api/vote/manual", "POST", { game, count });
    showMsg("msg-mv", `Vote für "${game}" (+${count}) eingereiht.`, "ok");
    $("mv-game").value = "";
    setTimeout(loadStandings, 2500); // nach Verarbeitung Ranking aktualisieren
  } catch (e) { showMsg("msg-mv", e.message, "err"); }
}

// --- Neues Spiel ins Sheet aufnehmen ---
async function addGame() {
  const input = $("ng-name"), btn = $("btn-add-game");
  const name = input.value.trim();
  if (!name) return showMsg("msg-ng", "Spielname fehlt.", "err");
  btn.disabled = true;
  showMsg("msg-ng", "Wird eingetragen…", "info");
  try {
    const system = $("ng-system"), notes = $("ng-notes");
    const res = await api("/api/sheets/games", "POST", { name, system: system.value, notes: notes.value.trim() });
    showMsg("msg-ng", `"${res.added[0]}" wurde ins Sheet aufgenommen.`, "ok");
    input.value = "";
    notes.value = "";
    system.value = "";
    system.dispatchEvent(new Event("change"));  // Anzeige des Auswahlfelds nachziehen
    loadStandings();  // Rangliste und Kennzahlen nachziehen
  } catch (e) { showMsg("msg-ng", e.message, "err"); }
  btn.disabled = false;
  input.focus();
}

// --- Rewards ---
function renderRewards(rewards) {
  const wrap = $("reward-list");
  if (!rewards.length) { wrap.innerHTML = '<p class="muted">Keine Belohnungen verknüpft.</p>'; return; }
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

function onNewKind() {
  const isAi = $("nr-kind").value === "ai";
  $("nr-weight-wrap").classList.toggle("hidden", isAi);
}

async function createReward() {
  const kind = $("nr-kind").value;
  const body = {
    title: $("nr-title").value.trim(),
    kind,
    cost: Number($("nr-cost").value) || 500,
  };
  if (kind === "vote") body.weight = Number($("nr-weight").value) || 1;
  if (!body.title) return showMsg("msg-reward", "Name fehlt.", "err");
  try {
    await api("/api/rewards/create", "POST", body);
    showMsg("msg-reward", `Belohnung "${body.title}" angelegt.`, "ok");
    $("nr-title").value = "";
  } catch (e) { showMsg("msg-reward", e.message, "err"); }
}

async function removeReward(id) {
  if (!confirm("Belohnung aus Tally entfernen? (Die Twitch-Belohnung bleibt bestehen.)")) return;
  try { await api(`/api/rewards/${encodeURIComponent(id)}`, "DELETE"); }
  catch (e) { alert(e.message); }
}

// --- Einstellungen ---
async function saveSettings() {
  try {
    await api("/api/settings", "POST", {
      min_match_score: Number($("set-score").value),
      manual_vote_user: $("set-manual-user").value.trim(),
      autostart_bot: $("set-autostart").checked,
    });
    showMsg("msg-settings", "Gespeichert.", "ok");
  } catch (e) { showMsg("msg-settings", e.message, "err"); }
}

async function saveOpenAI() {
  try {
    const body = { model: $("set-model").value.trim() };
    const key = $("set-key").value.trim();
    if (key) body.api_key = key;
    await api("/api/openai", "POST", body);
    showMsg("msg-ai2", "AI-Einstellungen gespeichert.", "ok");
    $("set-key").value = "";
  } catch (e) { showMsg("msg-ai2", e.message, "err"); }
}

async function testSheet() {
  showMsg("msg-ai2", "Teste Sheet-Verbindung…", "info");
  try {
    const res = await fetch("/api/sheets/test", { method: "POST" });
    const data = await res.json();
    if (data.ok) showMsg("msg-ai2", `✓ Verbunden mit "${data.spreadsheet_title}".`, "ok");
    else showMsg("msg-ai2", data.error + (data.service_account_email ? ` – Sheet mit ${data.service_account_email} geteilt?` : ""), "err");
  } catch (e) { showMsg("msg-ai2", e.message, "err"); }
}

// --- Start ---
connectWS();
loadStandings();
setInterval(loadStandings, 20000); // Ranking regelmäßig auffrischen
