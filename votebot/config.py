"""Konfiguration: Schema, Laden/Speichern, Migration und Status-Helfer.

Die Config wird komplett über das Web-Dashboard verwaltet - der Nutzer muss
diese Datei niemals von Hand bearbeiten. Secrets landen nie im Log und werden
nie unmaskiert ans Frontend gesendet (siehe ``public_state``).
"""
from __future__ import annotations

import copy
import json
import os
import threading
from datetime import datetime, timedelta
from typing import Any

# --- Pfade ---------------------------------------------------------------
# Alle veränderlichen Dateien liegen neben der config.json im Projektordner.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
SERVICE_ACCOUNT_FILE = os.path.join(BASE_DIR, "service_account.json")
VOTE_IDS_FILE = os.path.join(BASE_DIR, "Vote_IDs.csv")
INACCURATE_GAMES_FILE = os.path.join(BASE_DIR, "inaccurate_games.csv")

# Bundle-Datei für die Weitergabe: enthält die Twitch-App-Zugangsdaten des
# Erstellers. Ist sie vorhanden, läuft Votebot im "End-User-Modus" und blendet
# den Twitch-Developer-Console-Schritt aus (die App wird mitgeliefert).
BUNDLE_FILE = os.path.join(BASE_DIR, "app_credentials.json")

SCHEMA_VERSION = 2

# Feste Loopback-URL - muss exakt so in der Twitch-Developer-Konsole als
# OAuth-Redirect-URL eingetragen werden.
WEB_HOST = "localhost"
WEB_PORT = 17563
REDIRECT_URI = f"http://{WEB_HOST}:{WEB_PORT}/oauth/callback"

# Scopes pro Account-Typ.
# Der Broadcaster kann (im Standardmodus) auch den Chat bedienen, daher braucht
# sein Token zusätzlich die Chat-Schreib-Scopes.
BROADCASTER_SCOPES = "channel:read:redemptions channel:manage:redemptions user:write:chat user:bot"
CHAT_BOT_SCOPES = "user:write:chat user:bot chat:edit"

DEFAULT_CONFIG: dict[str, Any] = {
    "schema_version": SCHEMA_VERSION,
    "twitch": {"client_id": "", "client_secret": ""},
    "redirect_uri": REDIRECT_URI,
    "broadcaster": {
        "login": "",
        "user_id": "",
        "access_token": "",
        "refresh_token": "",
        "token_expiry": "",
        "scopes": BROADCASTER_SCOPES,
        "granted_scopes": [],
    },
    "chat_bot": {
        "use_broadcaster": True,  # Chat über den Broadcaster-Account senden
        "login": "",
        "user_id": "",
        "access_token": "",
        "refresh_token": "",
        "token_expiry": "",
        "scopes": CHAT_BOT_SCOPES,
        "granted_scopes": [],
    },
    # Liste statt fixer Keys -> jederzeit erweiterbar.
    # kind: "vote" (zählt ins Sheet) oder "ai" (OpenAI-Antwort im Chat).
    "rewards": [],
    "sheets": {
        "service_account_file": "service_account.json",
        "spreadsheet_id": "",
        "worksheet_index": 0,
    },
    "matching": {"min_match_score": 80},
    "openai": {"api_key": "", "model": "gpt-4o"},
    # Anzeigename für manuell über das Dashboard abgegebene Votes.
    "manual_vote_user": "Dashboard",
}

SECRET_PATHS = (
    ("twitch", "client_secret"),
    ("openai", "api_key"),
)

_lock = threading.Lock()


# --- Bundle / Betriebsmodus ---------------------------------------------

def load_bundle() -> dict | None:
    """Lädt die mitgelieferte App-Bundle-Datei (falls vorhanden)."""
    if not os.path.exists(BUNDLE_FILE):
        return None
    try:
        with open(BUNDLE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def app_mode() -> str:
    """'enduser' wenn eine Bundle-Datei mit Twitch-Zugangsdaten mitgeliefert
    wurde, sonst 'developer'."""
    bundle = load_bundle()
    if bundle and bundle.get("twitch", {}).get("client_id"):
        return "enduser"
    return "developer"


def is_sheets_bundled() -> bool:
    """True, wenn ein Service-Account mitgeliefert wird (End-User müssen keinen
    eigenen hochladen)."""
    bundle = load_bundle()
    return bool(bundle and bundle.get("sheets_bundled") and os.path.exists(SERVICE_ACCOUNT_FILE))


def write_bundle(client_id: str, client_secret: str, sheets_bundled: bool) -> None:
    data = {
        "twitch": {"client_id": client_id, "client_secret": client_secret},
        "sheets_bundled": bool(sheets_bundled),
    }
    with open(BUNDLE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


def remove_bundle() -> bool:
    if os.path.exists(BUNDLE_FILE):
        os.remove(BUNDLE_FILE)
        return True
    return False


def read_service_account_email(cfg: dict) -> str | None:
    """client_email aus der Service-Account-JSON (ohne sheets-Modul zu importieren)."""
    path = service_account_path(cfg)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f).get("client_email")
    except Exception:
        return None


def _deep_merge_defaults(cfg: dict, defaults: dict) -> dict:
    """Ergänzt fehlende Default-Keys rekursiv, ohne vorhandene Werte zu überschreiben."""
    for key, value in defaults.items():
        if key not in cfg:
            cfg[key] = copy.deepcopy(value)
        elif isinstance(value, dict) and isinstance(cfg.get(key), dict):
            _deep_merge_defaults(cfg[key], value)
    return cfg


def _migrate_v1(old: dict) -> dict:
    """Übernimmt eine alte (zwei-App-)config.json best-effort ins neue Schema."""
    cfg = copy.deepcopy(DEFAULT_CONFIG)

    old_streamer = old.get("streamer", {}) or {}
    old_bot = old.get("chat_bot", {}) or {}

    # Eine App: client_id/secret vom Streamer übernehmen.
    cfg["twitch"]["client_id"] = old_streamer.get("client_id", "")
    cfg["twitch"]["client_secret"] = old_streamer.get("client_secret", "")

    for field in ("access_token", "refresh_token", "token_expiry"):
        cfg["broadcaster"][field] = old_streamer.get(field, "")
    cfg["broadcaster"]["login"] = old.get("twitch_username", "")
    cfg["broadcaster"]["user_id"] = old.get("broadcaster_id", "")

    # Chat-Bot nur übernehmen, wenn eigene Tokens existierten.
    if old_bot.get("access_token"):
        cfg["chat_bot"]["use_broadcaster"] = False
        for field in ("access_token", "refresh_token", "token_expiry"):
            cfg["chat_bot"][field] = old_bot.get(field, "")
        cfg["chat_bot"]["user_id"] = old_bot.get("user_id", "")

    # Alte fixe Reward-Keys -> Liste.
    old_rewards = old.get("rewards", {}) or {}
    reward_defs = [
        ("normal_vote", "Normaler Vote", "vote", 1),
        ("super_vote", "Super Vote", "vote", old.get("super_vote_weight", 10)),
        ("ultra_vote", "Ultra Vote", "vote", old.get("ultra_vote_weight", 25)),
        ("ai_chat", "AI Chat", "ai", 0),
    ]
    for key, title, kind, weight in reward_defs:
        rid = old_rewards.get(key)
        if rid:
            entry = {"reward_id": rid, "title": title, "kind": kind}
            if kind == "vote":
                entry["weight"] = int(weight) if weight else 1
            cfg["rewards"].append(entry)

    cfg["sheets"]["spreadsheet_id"] = old.get("spreadsheet_id", "")
    cfg["matching"]["min_match_score"] = old.get("min_match_score", 80)
    cfg["openai"]["api_key"] = old.get("openai_api_key", "")
    cfg["openai"]["model"] = old.get("openai_model", "gpt-4o")

    cfg["schema_version"] = SCHEMA_VERSION
    return cfg


def load_config() -> dict:
    """Lädt die Config, migriert alte Versionen und ergänzt fehlende Defaults."""
    if not os.path.exists(CONFIG_FILE):
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        save_config(cfg)
        return cfg

    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        loaded = json.load(f)

    # Alte Struktur erkennen (hatte 'streamer' statt 'twitch').
    if "streamer" in loaded or loaded.get("schema_version") is None:
        if "twitch" not in loaded:
            loaded = _migrate_v1(loaded)

    cfg = _deep_merge_defaults(loaded, DEFAULT_CONFIG)
    # redirect_uri immer auf aktuellen Wert ziehen (Port könnte sich geändert haben).
    cfg["redirect_uri"] = REDIRECT_URI
    # Scopes sind von der App vorgegeben, nicht vom Nutzer -> immer aktualisieren,
    # damit ein erneuter Login die neuesten Berechtigungen anfordert.
    cfg["broadcaster"]["scopes"] = BROADCASTER_SCOPES
    cfg["chat_bot"]["scopes"] = CHAT_BOT_SCOPES
    _apply_bundle(cfg)
    save_config(cfg)
    return cfg


def _apply_bundle(cfg: dict) -> None:
    """Im End-User-Modus die mitgelieferten Twitch-Zugangsdaten übernehmen."""
    bundle = load_bundle()
    if not bundle:
        return
    tw = bundle.get("twitch", {})
    if tw.get("client_id"):
        cfg["twitch"]["client_id"] = tw["client_id"]
    if tw.get("client_secret"):
        cfg["twitch"]["client_secret"] = tw["client_secret"]


def save_config(cfg: dict) -> None:
    """Speichert die Config atomar."""
    with _lock:
        tmp = CONFIG_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4, ensure_ascii=False)
        os.replace(tmp, CONFIG_FILE)


# --- Status-Helfer -------------------------------------------------------

def service_account_path(cfg: dict) -> str:
    """Absoluter Pfad zur Service-Account-JSON."""
    name = cfg.get("sheets", {}).get("service_account_file") or "service_account.json"
    if os.path.isabs(name):
        return name
    return os.path.join(BASE_DIR, name)


def is_twitch_app_configured(cfg: dict) -> bool:
    t = cfg.get("twitch", {})
    return bool(t.get("client_id") and t.get("client_secret"))


def is_broadcaster_linked(cfg: dict) -> bool:
    b = cfg.get("broadcaster", {})
    return bool(b.get("access_token") and b.get("user_id"))


def is_chat_ready(cfg: dict) -> bool:
    if cfg.get("chat_bot", {}).get("use_broadcaster"):
        return is_broadcaster_linked(cfg)
    return bool(cfg.get("chat_bot", {}).get("access_token"))


def chat_send_account(cfg: dict) -> str:
    return "broadcaster" if cfg.get("chat_bot", {}).get("use_broadcaster") else "chat_bot"


def chat_scope_ok(cfg: dict) -> bool:
    """True, wenn das Konto, das in den Chat schreibt, den Scope 'user:write:chat'
    tatsächlich erteilt bekommen hat."""
    acc = cfg.get(chat_send_account(cfg), {})
    if not acc.get("access_token"):
        return False
    return "user:write:chat" in (acc.get("granted_scopes") or [])


def is_sheets_configured(cfg: dict) -> bool:
    s = cfg.get("sheets", {})
    return bool(s.get("spreadsheet_id") and os.path.exists(service_account_path(cfg)))


def is_setup_complete(cfg: dict) -> bool:
    """Minimal lauffähig: App + Broadcaster + mind. ein Reward + Sheets."""
    return (
        is_twitch_app_configured(cfg)
        and is_broadcaster_linked(cfg)
        and is_sheets_configured(cfg)
        and len(cfg.get("rewards", [])) > 0
    )


def setup_status(cfg: dict) -> dict:
    """Pro-Schritt-Status für den Wizard/Dashboard."""
    return {
        "twitch_app": is_twitch_app_configured(cfg),
        "broadcaster": is_broadcaster_linked(cfg),
        "chat": is_chat_ready(cfg),
        "chat_scope": chat_scope_ok(cfg),
        "rewards": len(cfg.get("rewards", [])) > 0,
        "sheets": is_sheets_configured(cfg),
        "openai": bool(cfg.get("openai", {}).get("api_key")),
        "complete": is_setup_complete(cfg),
    }


def public_state(cfg: dict) -> dict:
    """Für das Frontend aufbereiteter Zustand - OHNE Secrets/Tokens.

    Secrets werden nur als Boolean ("gesetzt: ja/nein") offengelegt.
    """
    mode = app_mode()
    sheets_bundled = is_sheets_bundled()
    return {
        "schema_version": cfg.get("schema_version"),
        "redirect_uri": cfg.get("redirect_uri"),
        "mode": mode,
        "bundle": {
            "twitch": mode == "enduser",
            "sheets": sheets_bundled,
        },
        "twitch": {
            "client_id": cfg.get("twitch", {}).get("client_id", ""),
            "client_secret_set": bool(cfg.get("twitch", {}).get("client_secret")),
        },
        "broadcaster": {
            "login": cfg.get("broadcaster", {}).get("login", ""),
            "user_id": cfg.get("broadcaster", {}).get("user_id", ""),
            "linked": is_broadcaster_linked(cfg),
        },
        "chat_bot": {
            "use_broadcaster": cfg.get("chat_bot", {}).get("use_broadcaster", True),
            "login": cfg.get("chat_bot", {}).get("login", ""),
            "linked": bool(cfg.get("chat_bot", {}).get("access_token")),
        },
        "rewards": cfg.get("rewards", []),
        "sheets": {
            "spreadsheet_id": cfg.get("sheets", {}).get("spreadsheet_id", ""),
            "worksheet_index": cfg.get("sheets", {}).get("worksheet_index", 0),
            "service_account_set": os.path.exists(service_account_path(cfg)),
            "service_account_email": read_service_account_email(cfg),
            "bundled": sheets_bundled,
        },
        "matching": cfg.get("matching", {}),
        "openai": {
            "model": cfg.get("openai", {}).get("model", "gpt-4o"),
            "api_key_set": bool(cfg.get("openai", {}).get("api_key")),
        },
        "manual_vote_user": cfg.get("manual_vote_user", "Dashboard"),
        "status": setup_status(cfg),
    }


# --- Token-Zeit-Helfer (von bot/twitch genutzt) --------------------------

def token_expiry_iso(expires_in: int) -> str:
    return (datetime.now() + timedelta(seconds=int(expires_in or 3600))).isoformat()
