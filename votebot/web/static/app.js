// Dashboard-Logik: WebSocket-Log/Status, Bot-Steuerung, Rewards, Votes, Einstellungen.

let ws = null;
let running = false;

function connectWS() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === "history") { msg.logs.forEach(appendLog); }
    else if (msg.type === "log") { appendLog(msg.data); }
    else if (msg.type === "status") { applyStatus(msg.data); }
  };
  ws.onclose = () => { setTimeout(connectWS, 2000); };
}

function appendLog(entry) {
  const box = $("log");
  const atBottom = box.scrollTop + box.clientHeight >= box.scrollHeight - 30;
  const line = document.createElement("div");
  line.className = "line " + entry.level;
  line.innerHTML = `<span class="t">${esc(entry.time)}</span><span class="lvl">${esc(entry.level)}</span><span class="m">${esc(entry.message)}</span>`;
  box.appendChild(line);
  while (box.childElementCount > 600) box.removeChild(box.firstChild);
  if (atBottom) box.scrollTop = box.scrollHeight;
}

function clearLog() { $("log").innerHTML = ""; }

function applyStatus(s) {
  const bot = s.bot || {};
  running = bot.running;
  const pill = $("bot-pill");
  pill.className = "pill " + (running ? "run" : "stop");
  pill.innerHTML = `<span class="dot ${running ? "ok" : "off"}"></span> ${running ? "läuft" : "gestoppt"}`;
  $("btn-toggle").textContent = running ? "⏸ Stoppen" : "▶ Starten";
  $("channel-label").textContent = s.broadcaster.login ? "Kanal: " + s.broadcaster.login : "";

  const st = bot.stats || {};
  $("st-votes").textContent = st.votes_processed || 0;
  $("st-ai").textContent = st.ai_answered || 0;
  $("st-queue").textContent = bot.queue_size || 0;
  $("st-games").textContent = bot.games_count || 0;

  renderRewardDonut($("chart-rewards"), st.votes_by_reward || {});
  renderSessionTop($("chart-session"), st.votes_by_game || {});
  const voters = st.voters || {};
  renderVoters($("voters"), voters);
  const vc = Object.keys(voters).length;
  $("voters-count").textContent = vc ? `${vc} Voter` : "";
  renderRewards(s.rewards || []);

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
async function loadStandings() {
  try {
    const { standings } = await api("/api/sheets/standings");
    renderTopGames($("chart-top"), standings);
  } catch (e) {
    $("chart-top").classList.remove("bars");
    $("chart-top").innerHTML = `<div class="empty">${esc(e.message)}</div>`;
  }
}

async function resetStats() {
  if (!confirm("Session-Statistiken (Session-Votes, Verteilung, Zähler) zurücksetzen?")) return;
  try { await api("/api/stats/reset", "POST"); } catch (e) { alert(e.message); }
}

// --- Manueller Vote ---
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
