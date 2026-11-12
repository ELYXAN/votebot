#!/usr/bin/env python3
"""Votebot-Starter: konfiguriert Logging, startet den Webserver und öffnet den
Browser auf dem Dashboard. Für Endnutzer der einzige Einstiegspunkt."""
from __future__ import annotations

import os
import socket
import threading
import time
import webbrowser

import uvicorn

from votebot import config as cfg_mod
from votebot import logging_setup


def _open_browser(url: str) -> None:
    time.sleep(1.5)
    try:
        webbrowser.open(url)
    except Exception:
        pass


def _already_running() -> bool:
    """True, wenn auf dem Dashboard-Port schon etwas lauscht (Tally läuft bereits)."""
    try:
        with socket.create_connection((cfg_mod.WEB_HOST, cfg_mod.WEB_PORT), timeout=1):
            return True
    except OSError:
        return False


def main() -> None:
    logging_setup.configure()
    url = f"http://{cfg_mod.WEB_HOST}:{cfg_mod.WEB_PORT}"

    # Zweiter Start (z. B. Doppelklick auf die Verknüpfung): nur das Dashboard öffnen.
    if _already_running():
        print(f"Tally läuft bereits - öffne {url}")
        if not os.environ.get("VOTEBOT_NO_BROWSER"):
            webbrowser.open(url)
        return

    print("=" * 60)
    print("  Tally - Twitch Vote Tracker")
    print(f"  Dashboard: {url}")
    print("  (Zum Beenden hier Strg+C drücken.)")
    print("=" * 60)

    # Im Hintergrunddienst (systemd) keinen Browser öffnen.
    if not os.environ.get("VOTEBOT_NO_BROWSER"):
        threading.Thread(target=_open_browser, args=(url,), daemon=True).start()

    uvicorn.run(
        "votebot.web.app:app",
        host=cfg_mod.WEB_HOST,
        port=cfg_mod.WEB_PORT,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
