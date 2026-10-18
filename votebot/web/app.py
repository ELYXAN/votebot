"""FastAPI-Anwendung: Setup-Wizard, Dashboard, OAuth-Callback und WebSocket-Log.

Keine Secrets verlassen den Server unmaskiert; das Frontend bekommt nur
``config.public_state``.
"""
from __future__ import annotations

import asyncio
import os
import secrets
import time
from contextlib import asynccontextmanager

import aiohttp
from fastapi import FastAPI, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .. import config as cfg_mod
from .. import logging_setup, twitch
from ..bot import VoteBot
from ..logging_setup import get_logger

log = get_logger("votebot.web")

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(HERE, "static")
TEMPLATE_DIR = os.path.join(HERE, "templates")


class AppState:
    def __init__(self) -> None:
        self.cfg: dict = cfg_mod.load_config()
        self.bot = VoteBot(self.cfg)
        # pending OAuth: state -> {"account": ..., "ts": ...}
        self.oauth_pending: dict[str, dict] = {}


state = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging_setup.set_loop(asyncio.get_running_loop())
    log.info("Votebot-Dashboard bereit auf http://%s:%d", cfg_mod.WEB_HOST, cfg_mod.WEB_PORT)
    yield
    await state.bot.stop()


app = FastAPI(title="Votebot", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# --- Seiten --------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def index():
    if not cfg_mod.is_setup_complete(state.cfg):
        return RedirectResponse("/setup")
    return FileResponse(os.path.join(TEMPLATE_DIR, "index.html"))


@app.get("/setup", response_class=HTMLResponse)
async def setup_page():
    return FileResponse(os.path.join(TEMPLATE_DIR, "setup.html"))


# --- Zustand -------------------------------------------------------------
@app.get("/api/state")
async def api_state():
    pub = cfg_mod.public_state(state.cfg)
    pub["bot"] = state.bot.status()
    return pub


# --- Twitch-App ----------------------------------------------------------
@app.post("/api/twitch/app")
async def set_twitch_app(payload: dict):
    client_id = (payload.get("client_id") or "").strip()
    client_secret = (payload.get("client_secret") or "").strip()
    if not client_id:
        return JSONResponse({"error": "client_id erforderlich."}, status_code=400)
    # Leeres Secret = bestehendes behalten (wurde bereits einmal gespeichert).
    if not client_secret and not state.cfg["twitch"].get("client_secret"):
        return JSONResponse({"error": "client_secret erforderlich."}, status_code=400)
    state.cfg["twitch"]["client_id"] = client_id
    if client_secret:
        state.cfg["twitch"]["client_secret"] = client_secret
    cfg_mod.save_config(state.cfg)
    log.info("Twitch-App gespeichert (Client-ID: %s…).", client_id[:6])
    return {"ok": True, "redirect_uri": state.cfg["redirect_uri"]}


# --- Weitergabe / Bundle (nur Entwickler-Modus sinnvoll) ----------------
@app.post("/api/dev/bundle")
async def dev_bundle_create(payload: dict):
    if not cfg_mod.is_twitch_app_configured(state.cfg):
        return JSONResponse({"error": "Bitte zuerst die Twitch-App einrichten."}, status_code=400)
    include_sheets = bool(payload.get("include_sheets", False))
    has_sa = os.path.exists(cfg_mod.service_account_path(state.cfg))
    sheets_bundled = include_sheets and has_sa
    cfg_mod.write_bundle(
        state.cfg["twitch"]["client_id"],
        state.cfg["twitch"]["client_secret"],
        sheets_bundled,
    )
    log.info("Weitergabe-Bundle erstellt (Service-Account mitliefern: %s).", sheets_bundled)
    include = ["app_credentials.json", "run.py", "start.sh", "start.bat",
               "requirements.txt", "README.md", "votebot/"]
    if sheets_bundled:
        include.append("service_account.json")
    return {
        "ok": True,
        "sheets_bundled": sheets_bundled,
        "sheets_requested": include_sheets,
        "service_account_present": has_sa,
        "include": include,
        "exclude": ["config.json", "Vote_IDs.csv", "inaccurate_games.csv", ".venv/"],
    }


@app.delete("/api/dev/bundle")
async def dev_bundle_delete():
    removed = cfg_mod.remove_bundle()
    return {"ok": True, "removed": removed}


# --- OAuth ---------------------------------------------------------------
@app.get("/api/oauth/start")
async def oauth_start(account: str = "broadcaster"):
    if account not in ("broadcaster", "chat_bot"):
        return JSONResponse({"error": "unbekannter Account"}, status_code=400)
    if not cfg_mod.is_twitch_app_configured(state.cfg):
        return JSONResponse({"error": "Bitte zuerst die Twitch-App eintragen."}, status_code=400)
    st = secrets.token_urlsafe(24)
    state.oauth_pending[st] = {"account": account, "ts": time.time()}
    url = twitch.build_auth_url(state.cfg, account, st)
    return {"url": url}


@app.get("/oauth/callback", response_class=HTMLResponse)
async def oauth_callback(request: Request):
    params = request.query_params
    code = params.get("code")
    st = params.get("state")
    error = params.get("error_description") or params.get("error")

    if error:
        return _callback_html(False, f"Twitch meldete: {error}")
    pending = state.oauth_pending.pop(st, None) if st else None
    if not code or not pending:
        return _callback_html(False, "Ungültiger oder abgelaufener Login-Vorgang.")

    account = pending["account"]
    try:
        async with aiohttp.ClientSession() as session:
            await twitch.exchange_code(session, state.cfg, account, code)
    except Exception as e:  # noqa: BLE001
        log.error("OAuth-Austausch fehlgeschlagen: %s", e)
        return _callback_html(False, f"Login fehlgeschlagen: {e}")

    login = state.cfg[account].get("login", "?")
    return _callback_html(True, f"Account '{login}' verknüpft. Du kannst dieses Fenster schließen.")


# --- Chat-Modus ----------------------------------------------------------
@app.post("/api/chat/mode")
async def set_chat_mode(payload: dict):
    use_broadcaster = bool(payload.get("use_broadcaster", True))
    state.cfg["chat_bot"]["use_broadcaster"] = use_broadcaster
    if use_broadcaster:
        # separaten Bot-Account vergessen
        for f in ("access_token", "refresh_token", "token_expiry", "user_id", "login"):
            state.cfg["chat_bot"][f] = ""
    cfg_mod.save_config(state.cfg)
    return {"ok": True}


# --- Rewards -------------------------------------------------------------
@app.get("/api/rewards/existing")
async def rewards_existing():
    try:
        async with aiohttp.ClientSession() as session:
            rewards = await twitch.get_custom_rewards(session, state.cfg, only_manageable=True)
        return {"ok": True, "rewards": [
            {"id": r["id"], "title": r["title"], "cost": r.get("cost", 0)} for r in rewards
        ]}
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


@app.post("/api/rewards/create")
async def rewards_create(payload: dict):
    title = (payload.get("title") or "").strip()
    kind = payload.get("kind", "vote")
    cost = int(payload.get("cost", 100))
    weight = int(payload.get("weight", 1))
    if not title:
        return JSONResponse({"error": "Titel erforderlich."}, status_code=400)
    try:
        async with aiohttp.ClientSession() as session:
            # Vote braucht den Spielnamen, AI braucht die Frage -> immer Eingabe nötig.
            reward = await twitch.create_custom_reward(
                session, state.cfg, title, cost, prompt=payload.get("prompt", ""),
                require_input=True,
            )
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": str(e)}, status_code=400)

    entry = {"reward_id": reward["id"], "title": reward["title"], "kind": kind}
    if kind == "vote":
        entry["weight"] = weight
    _upsert_reward(entry)
    return {"ok": True, "reward": entry}


@app.post("/api/rewards/link")
async def rewards_link(payload: dict):
    """Verknüpft einen bereits existierenden (verwaltbaren) Reward."""
    rid = payload.get("reward_id")
    if not rid:
        return JSONResponse({"error": "reward_id erforderlich."}, status_code=400)
    entry = {"reward_id": rid, "title": payload.get("title", ""), "kind": payload.get("kind", "vote")}
    if entry["kind"] == "vote":
        entry["weight"] = int(payload.get("weight", 1))
    _upsert_reward(entry)
    return {"ok": True, "reward": entry}


@app.delete("/api/rewards/{reward_id}")
async def rewards_delete(reward_id: str, delete_on_twitch: bool = False):
    state.cfg["rewards"] = [r for r in state.cfg["rewards"] if r.get("reward_id") != reward_id]
    cfg_mod.save_config(state.cfg)
    if delete_on_twitch:
        try:
            async with aiohttp.ClientSession() as session:
                await twitch.delete_custom_reward(session, state.cfg, reward_id)
        except Exception as e:  # noqa: BLE001
            return JSONResponse({"ok": True, "warning": f"Twitch-Löschung fehlgeschlagen: {e}"})
    return {"ok": True}


def _upsert_reward(entry: dict) -> None:
    rewards = state.cfg.setdefault("rewards", [])
    for i, r in enumerate(rewards):
        if r.get("reward_id") == entry["reward_id"]:
            rewards[i] = entry
            break
    else:
        rewards.append(entry)
    cfg_mod.save_config(state.cfg)


# --- Google Sheets -------------------------------------------------------
@app.post("/api/sheets/upload")
async def sheets_upload(file: UploadFile):
    content = await file.read()
    # Validieren, dass es eine Service-Account-JSON ist.
    try:
        import json as _json

        data = _json.loads(content)
        if data.get("type") != "service_account" or "client_email" not in data:
            return JSONResponse({"error": "Das ist keine Service-Account-JSON."}, status_code=400)
    except Exception:
        return JSONResponse({"error": "Datei ist kein gültiges JSON."}, status_code=400)

    with open(cfg_mod.service_account_path(state.cfg), "wb") as f:
        f.write(content)
    log.info("Service-Account-JSON gespeichert (%s).", data.get("client_email"))
    return {"ok": True, "client_email": data.get("client_email")}


@app.post("/api/sheets/config")
async def sheets_config(payload: dict):
    from ..sheets import extract_spreadsheet_id

    sid = extract_spreadsheet_id(payload.get("spreadsheet_id", ""))
    state.cfg["sheets"]["spreadsheet_id"] = sid
    if "worksheet_index" in payload:
        state.cfg["sheets"]["worksheet_index"] = int(payload.get("worksheet_index", 0))
    cfg_mod.save_config(state.cfg)
    return {"ok": True, "spreadsheet_id": sid}


@app.post("/api/sheets/test")
async def sheets_test():
    result = await state.bot.sheets.test_connection(state.cfg)
    status = 200 if result.get("ok") else 400
    return JSONResponse(result, status_code=status)


@app.get("/api/sheets/standings")
async def sheets_standings():
    try:
        if not state.bot.sheets.ready:
            await state.bot.sheets.connect(state.cfg)
        standings = await state.bot.sheets.get_standings()
        return {"ok": True, "standings": standings}
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


# --- OpenAI / Matching / sonstige Einstellungen --------------------------
@app.post("/api/openai")
async def set_openai(payload: dict):
    if "api_key" in payload:
        key = (payload.get("api_key") or "").strip()
        if key:  # leere Eingabe lässt bestehenden Key unangetastet
            state.cfg["openai"]["api_key"] = key
    if payload.get("model"):
        state.cfg["openai"]["model"] = payload["model"].strip()
    cfg_mod.save_config(state.cfg)
    return {"ok": True}


@app.post("/api/settings")
async def set_settings(payload: dict):
    if "min_match_score" in payload:
        state.cfg["matching"]["min_match_score"] = int(payload["min_match_score"])
    if "manual_vote_user" in payload:
        state.cfg["manual_vote_user"] = (payload["manual_vote_user"] or "Dashboard").strip()
    cfg_mod.save_config(state.cfg)
    return {"ok": True}


# --- Bot-Steuerung -------------------------------------------------------
@app.post("/api/bot/start")
async def bot_start():
    if not cfg_mod.is_setup_complete(state.cfg):
        return JSONResponse({"error": "Setup ist noch nicht abgeschlossen."}, status_code=400)
    try:
        await state.bot.start()
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": str(e)}, status_code=400)
    return {"ok": True, "running": state.bot.running}


@app.post("/api/bot/stop")
async def bot_stop():
    await state.bot.stop()
    return {"ok": True, "running": state.bot.running}


@app.post("/api/vote/manual")
async def vote_manual(payload: dict):
    game = (payload.get("game") or "").strip()
    count = int(payload.get("count", 1))
    if not game:
        return JSONResponse({"error": "Spielname erforderlich."}, status_code=400)
    if not state.bot.running:
        return JSONResponse({"error": "Bot läuft nicht - bitte zuerst starten."}, status_code=400)
    state.bot.enqueue_manual(game, count)
    return {"ok": True}


# --- WebSocket: Live-Log + Status ---------------------------------------
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    queue = logging_setup.subscribe()
    try:
        # Verlauf + initialer Status.
        await ws.send_json({"type": "history", "logs": logging_setup.recent()})
        await ws.send_json({"type": "status", "data": _full_status()})
        while True:
            try:
                entry = await asyncio.wait_for(queue.get(), timeout=2.0)
                await ws.send_json({"type": "log", "data": entry})
            except asyncio.TimeoutError:
                await ws.send_json({"type": "status", "data": _full_status()})
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        pass
    finally:
        logging_setup.unsubscribe(queue)


def _full_status() -> dict:
    pub = cfg_mod.public_state(state.cfg)
    pub["bot"] = state.bot.status()
    return pub


def _callback_html(ok: bool, message: str) -> HTMLResponse:
    color = "#39d353" if ok else "#f85149"
    icon = "✓" if ok else "✕"
    html = f"""<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Twitch-Login</title>
<style>
  body {{ margin:0; font-family: system-ui, sans-serif; background:#0d1117; color:#e6edf3;
         display:flex; align-items:center; justify-content:center; height:100vh; }}
  .card {{ text-align:center; padding:2.5rem 3rem; background:#161b22; border:1px solid #30363d;
          border-radius:14px; max-width:420px; }}
  .icon {{ font-size:3rem; color:{color}; }}
  p {{ color:#8b949e; line-height:1.5; }}
  button {{ margin-top:1rem; background:#9147ff; color:#fff; border:0; padding:.6rem 1.2rem;
           border-radius:8px; font-size:1rem; cursor:pointer; }}
</style></head><body>
  <div class="card">
    <div class="icon">{icon}</div>
    <h2>{'Erfolgreich verknüpft' if ok else 'Login fehlgeschlagen'}</h2>
    <p>{message}</p>
    <button onclick="closeOrBack()">Weiter zum Setup</button>
  </div>
  <script>
    try {{ if (window.opener) {{ window.opener.postMessage({{votebotOAuth:true, ok:{str(ok).lower()}}}, '*'); }} }} catch (e) {{}}
    function closeOrBack() {{ try {{ window.close(); }} catch(e) {{}} window.location = '/setup'; }}
    setTimeout(() => {{ try {{ if (window.opener) window.close(); }} catch(e) {{}} }}, 1500);
  </script>
</body></html>"""
    return HTMLResponse(html)
