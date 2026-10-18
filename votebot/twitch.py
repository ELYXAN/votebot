"""Twitch-API: OAuth (eine App), Token-Management, User-Lookup, Rewards-CRUD
und Chat-Nachrichten. Alle Aufrufe nutzen die eine konfigurierte ``client_id``.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any

import aiohttp

from . import config as cfg_mod
from .logging_setup import get_logger

log = get_logger("votebot.twitch")

AUTH_BASE = "https://id.twitch.tv/oauth2/authorize"
TOKEN_URL = "https://id.twitch.tv/oauth2/token"
VALIDATE_URL = "https://id.twitch.tv/oauth2/validate"
HELIX = "https://api.twitch.tv/helix"


class TwitchError(Exception):
    pass


# --- OAuth ---------------------------------------------------------------

def build_auth_url(cfg: dict, account: str, state: str) -> str:
    scopes = cfg[account]["scopes"]
    client_id = cfg["twitch"]["client_id"]
    redirect = cfg["redirect_uri"]
    return (
        f"{AUTH_BASE}?response_type=code"
        f"&client_id={client_id}"
        f"&redirect_uri={redirect}"
        f"&scope={scopes.replace(' ', '+')}"
        f"&state={state}"
        f"&force_verify=true"
    )


async def exchange_code(session: aiohttp.ClientSession, cfg: dict, account: str, code: str) -> dict:
    """Tauscht einen Authorization-Code gegen Tokens und speichert sie in cfg[account]."""
    data = {
        "client_id": cfg["twitch"]["client_id"],
        "client_secret": cfg["twitch"]["client_secret"],
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": cfg["redirect_uri"],
    }
    async with session.post(TOKEN_URL, data=data) as resp:
        body = await resp.json()
        if resp.status != 200:
            raise TwitchError(f"Token-Austausch fehlgeschlagen ({resp.status}): {body}")

    cfg[account]["access_token"] = body["access_token"]
    cfg[account]["refresh_token"] = body.get("refresh_token", "")
    cfg[account]["token_expiry"] = cfg_mod.token_expiry_iso(body.get("expires_in", 3600))

    # User-Info direkt mitziehen (user_id + login).
    info = await get_user_info(session, cfg, body["access_token"])
    if info:
        cfg[account]["user_id"] = info["id"]
        cfg[account]["login"] = info["login"]

    cfg_mod.save_config(cfg)
    log.info("Account '%s' erfolgreich verknüpft (%s).", account, cfg[account].get("login", "?"))
    return body


def check_token_validity(cfg: dict, account: str) -> bool:
    acc = cfg.get(account, {})
    if not acc.get("access_token") or not acc.get("token_expiry"):
        return False
    try:
        expiry_str = acc["token_expiry"]
        if expiry_str.endswith("Z"):
            expiry_str = expiry_str[:-1] + "+00:00"
        expiry = datetime.fromisoformat(expiry_str)
        now = datetime.now(expiry.tzinfo)
        return now < (expiry - timedelta(seconds=60))
    except (ValueError, TypeError) as e:
        log.warning("Konnte Token-Ablauf für %s nicht parsen: %s", account, e)
        return False


async def refresh_token(session: aiohttp.ClientSession, cfg: dict, account: str) -> bool:
    rt = cfg.get(account, {}).get("refresh_token")
    if not rt:
        return False
    data = {
        "grant_type": "refresh_token",
        "refresh_token": rt,
        "client_id": cfg["twitch"]["client_id"],
        "client_secret": cfg["twitch"]["client_secret"],
    }
    try:
        async with session.post(TOKEN_URL, data=data) as resp:
            text = await resp.text()
            if resp.status == 200:
                body = await _json(text)
                cfg[account]["access_token"] = body["access_token"]
                if body.get("refresh_token"):
                    cfg[account]["refresh_token"] = body["refresh_token"]
                cfg[account]["token_expiry"] = cfg_mod.token_expiry_iso(body.get("expires_in", 3600))
                cfg_mod.save_config(cfg)
                log.info("Token für %s erneuert.", account)
                return True
            if resp.status in (400, 401) and "Invalid refresh token" in text:
                log.warning("Refresh-Token für %s ungültig - erneute Anmeldung nötig.", account)
                cfg[account]["access_token"] = ""
                cfg[account]["refresh_token"] = ""
                cfg[account]["token_expiry"] = ""
                cfg_mod.save_config(cfg)
            else:
                log.error("Token-Refresh für %s fehlgeschlagen (%s): %s", account, resp.status, text)
            return False
    except Exception as e:
        log.error("Ausnahme beim Token-Refresh für %s: %s", account, e)
        return False


async def ensure_valid_token(session: aiohttp.ClientSession, cfg: dict, account: str) -> bool:
    """Stellt ein gültiges Token sicher (prüfen + ggf. refreshen). Kein Browser-Flow."""
    if check_token_validity(cfg, account):
        return True
    if cfg.get(account, {}).get("refresh_token"):
        return await refresh_token(session, cfg, account)
    return False


# --- User / Broadcaster --------------------------------------------------

async def get_user_info(session: aiohttp.ClientSession, cfg: dict, access_token: str) -> dict | None:
    headers = {
        "Client-Id": cfg["twitch"]["client_id"],
        "Authorization": f"Bearer {access_token}",
    }
    async with session.get(f"{HELIX}/users", headers=headers) as resp:
        if resp.status != 200:
            log.error("Konnte User-Info nicht laden (%s): %s", resp.status, await resp.text())
            return None
        data = await resp.json()
        users = data.get("data", [])
        return users[0] if users else None


# --- Chat-Senden ---------------------------------------------------------

def _chat_account(cfg: dict) -> str:
    return "broadcaster" if cfg.get("chat_bot", {}).get("use_broadcaster") else "chat_bot"


async def send_chat_message(session: aiohttp.ClientSession, cfg: dict, message: str) -> bool:
    account = _chat_account(cfg)
    if not await ensure_valid_token(session, cfg, account):
        log.error("Chat-Token (%s) ungültig - Nachricht nicht gesendet.", account)
        return False

    sender_id = cfg[account].get("user_id")
    if not sender_id:
        info = await get_user_info(session, cfg, cfg[account]["access_token"])
        if info:
            sender_id = info["id"]
            cfg[account]["user_id"] = sender_id
            cfg_mod.save_config(cfg)

    if not sender_id:
        log.error("Keine Sender-User-ID für Chat ermittelbar.")
        return False

    headers = {
        "Authorization": f"Bearer {cfg[account]['access_token']}",
        "Client-Id": cfg["twitch"]["client_id"],
        "Content-Type": "application/json",
    }
    payload = {
        "broadcaster_id": cfg["broadcaster"]["user_id"],
        "sender_id": sender_id,
        "message": message,
    }
    async with session.post(f"{HELIX}/chat/messages", headers=headers, json=payload) as resp:
        if resp.status == 200:
            body = await resp.json()
            data = body.get("data", [{}])[0]
            if data.get("is_sent"):
                log.info("Chat: %s", message)
                return True
            log.warning("Chat-Nachricht abgelehnt: %s", data.get("drop_reason"))
            return False
        text = await resp.text()
        log.error("Chat-Senden fehlgeschlagen (%s): %s", resp.status, text)
        if "Missing scope" in text:
            log.error("-> Dem Account fehlt der Scope 'user:write:chat'. Bitte neu anmelden.")
        return False


# --- Channel Point Rewards ----------------------------------------------

async def get_custom_rewards(session: aiohttp.ClientSession, cfg: dict, only_manageable: bool = True) -> list[dict]:
    if not await ensure_valid_token(session, cfg, "broadcaster"):
        raise TwitchError("Broadcaster-Token ungültig.")
    headers = _broadcaster_headers(cfg)
    params = {
        "broadcaster_id": cfg["broadcaster"]["user_id"],
        "only_manageable_rewards": "true" if only_manageable else "false",
    }
    async with session.get(f"{HELIX}/channel_points/custom_rewards", headers=headers, params=params) as resp:
        if resp.status != 200:
            raise TwitchError(f"Rewards laden fehlgeschlagen ({resp.status}): {await resp.text()}")
        return (await resp.json()).get("data", [])


async def create_custom_reward(
    session: aiohttp.ClientSession,
    cfg: dict,
    title: str,
    cost: int,
    prompt: str = "",
    require_input: bool = True,
) -> dict:
    """Legt einen Reward an. Existiert bereits einer mit gleichem Titel, wird
    dieser zurückgegeben (keine Dublette)."""
    if not await ensure_valid_token(session, cfg, "broadcaster"):
        raise TwitchError("Broadcaster-Token ungültig.")

    # Dublette vermeiden.
    try:
        existing = await get_custom_rewards(session, cfg, only_manageable=True)
        for r in existing:
            if r.get("title", "").strip().lower() == title.strip().lower():
                log.info("Reward '%s' existiert bereits - wird wiederverwendet.", title)
                return r
    except TwitchError:
        pass

    headers = _broadcaster_headers(cfg, json=True)
    params = {"broadcaster_id": cfg["broadcaster"]["user_id"]}
    payload = {
        "title": title,
        "cost": int(cost),
        "prompt": prompt,
        "is_user_input_required": require_input,
    }
    async with session.post(
        f"{HELIX}/channel_points/custom_rewards", headers=headers, params=params, json=payload
    ) as resp:
        text = await resp.text()
        if resp.status in (200, 201):
            reward = (await _json(text)).get("data", [{}])[0]
            log.info("Reward '%s' angelegt (Kosten: %s).", title, cost)
            return reward
        if resp.status == 400 and "CREATE_CUSTOM_REWARD_DUPLICATE_REWARD" in text:
            raise TwitchError(f"Ein Reward mit dem Titel '{title}' existiert bereits auf Twitch.")
        if resp.status == 403:
            raise TwitchError(
                "Reward anlegen verweigert (403). Channel Points erfordern Affiliate/Partner-Status."
            )
        raise TwitchError(f"Reward anlegen fehlgeschlagen ({resp.status}): {text}")


async def delete_custom_reward(session: aiohttp.ClientSession, cfg: dict, reward_id: str) -> bool:
    if not await ensure_valid_token(session, cfg, "broadcaster"):
        raise TwitchError("Broadcaster-Token ungültig.")
    headers = _broadcaster_headers(cfg)
    params = {"broadcaster_id": cfg["broadcaster"]["user_id"], "id": reward_id}
    async with session.delete(
        f"{HELIX}/channel_points/custom_rewards", headers=headers, params=params
    ) as resp:
        if resp.status in (200, 204):
            return True
        log.warning("Reward löschen fehlgeschlagen (%s): %s", resp.status, await resp.text())
        return False


async def get_redemptions(
    session: aiohttp.ClientSession, cfg: dict, reward_id: str, status: str = "UNFULFILLED"
) -> list[dict]:
    headers = _broadcaster_headers(cfg)
    params = {
        "broadcaster_id": cfg["broadcaster"]["user_id"],
        "reward_id": reward_id,
        "status": status,
        "first": "50",
    }
    async with session.get(
        f"{HELIX}/channel_points/custom_rewards/redemptions", headers=headers, params=params
    ) as resp:
        if resp.status == 200:
            return (await resp.json()).get("data", [])
        if resp.status == 401:
            raise TwitchError("401")
        if resp.status == 403:
            log.error("Redemptions lesen verweigert (403) für Reward %s - falsche client_id?", reward_id)
            return []
        log.error("Redemptions lesen fehlgeschlagen (%s): %s", resp.status, await resp.text())
        return []


async def fulfill_redemption(
    session: aiohttp.ClientSession, cfg: dict, reward_id: str, redemption_id: str
) -> bool:
    headers = _broadcaster_headers(cfg, json=True)
    params = {
        "broadcaster_id": cfg["broadcaster"]["user_id"],
        "reward_id": reward_id,
        "id": redemption_id,
    }
    async with session.patch(
        f"{HELIX}/channel_points/custom_rewards/redemptions",
        headers=headers,
        params=params,
        json={"status": "FULFILLED"},
    ) as resp:
        text = await resp.text()
        if resp.status == 200:
            log.info("Redemption %s als FULFILLED markiert.", redemption_id)
            return True
        if resp.status == 400 and "already" in text.lower():
            return True
        log.error("Redemption %s fulfillen fehlgeschlagen (%s): %s", redemption_id, resp.status, text)
        return False


# --- intern --------------------------------------------------------------

def _broadcaster_headers(cfg: dict, json: bool = False) -> dict:
    h = {
        "Client-Id": cfg["twitch"]["client_id"],
        "Authorization": f"Bearer {cfg['broadcaster']['access_token']}",
    }
    if json:
        h["Content-Type"] = "application/json"
    return h


async def _json(text: str) -> dict:
    import json as _j

    return _j.loads(text) if text else {}
