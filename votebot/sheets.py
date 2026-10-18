"""Google-Sheets-Anbindung. Kapselt Verbindung, Spiele-Cache, Rangberechnung
und Sortierung. Blockierende gspread-Aufrufe laufen über ``asyncio.to_thread``,
damit der Event-Loop nicht blockiert wird.
"""
from __future__ import annotations

import asyncio
import json
import time

import gspread
from google.oauth2.service_account import Credentials

from . import config as cfg_mod
from .logging_setup import get_logger

log = get_logger("votebot.sheets")

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
VOTE_COLUMN = "Votes"
GAME_COLUMN = "Game"


def service_account_email(cfg: dict) -> str | None:
    """Liest die client_email aus der Service-Account-JSON (für 'Sheet teilen')."""
    path = cfg_mod.service_account_path(cfg)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f).get("client_email")
    except Exception:
        return None


def extract_spreadsheet_id(value: str) -> str:
    """Akzeptiert sowohl eine reine ID als auch eine volle Google-Sheets-URL."""
    value = (value or "").strip()
    if "/spreadsheets/d/" in value:
        part = value.split("/spreadsheets/d/", 1)[1]
        return part.split("/", 1)[0]
    return value


class GoogleSheets:
    def __init__(self) -> None:
        self.spreadsheet = None
        self.worksheet = None
        self.games_list: list[str] = []
        self.last_cache_update: float = 0
        self.cache_validity: int = 300

    @property
    def ready(self) -> bool:
        return self.worksheet is not None

    def _client(self, cfg: dict):
        creds = Credentials.from_service_account_file(
            cfg_mod.service_account_path(cfg), scopes=SCOPES
        )
        return gspread.authorize(creds)

    async def connect(self, cfg: dict) -> None:
        def _do():
            client = self._client(cfg)
            sid = extract_spreadsheet_id(cfg["sheets"]["spreadsheet_id"])
            ss = client.open_by_key(sid)
            ws = ss.get_worksheet(cfg["sheets"].get("worksheet_index", 0))
            return ss, ws

        self.spreadsheet, self.worksheet = await asyncio.to_thread(_do)
        await self.ensure_header()
        await self.update_games_cache()
        log.info("Google-Sheets-Verbindung hergestellt.")

    async def ensure_header(self) -> None:
        """Legt bei leerem Blatt die Kopfzeile 'Votes | Game' an."""
        def _do():
            values = self.worksheet.get("A1:B1")
            if not values or not values[0] or not any(values[0]):
                self.worksheet.update(range_name="A1:B1", values=[[VOTE_COLUMN, GAME_COLUMN]])
                return True
            return False

        created = await asyncio.to_thread(_do)
        if created:
            log.info("Leeres Blatt erkannt - Kopfzeile 'Votes | Game' angelegt.")

    async def update_games_cache(self) -> None:
        def _do():
            data = self.worksheet.get("B2:B")
            return [row[0] for row in data if row and row[0].strip()]

        self.games_list = await asyncio.to_thread(_do)
        self.last_cache_update = time.time()
        log.info("Spiele-Cache aktualisiert (%d Spiele).", len(self.games_list))

    async def get_standings(self) -> list[dict]:
        """Liefert [{rank, votes, name}] absteigend nach Votes."""
        def _do():
            data = self.worksheet.get("A2:B", value_render_option="UNFORMATTED_VALUE")
            rows = []
            for r in data:
                if len(r) >= 2 and str(r[1]).strip():
                    try:
                        votes = int(r[0]) if str(r[0]).strip() else 0
                    except (ValueError, TypeError):
                        votes = 0
                    rows.append({"votes": votes, "name": str(r[1]).strip()})
            return rows

        rows = await asyncio.to_thread(_do)
        rows.sort(key=lambda x: (-x["votes"], x["name"]))
        for i, row in enumerate(rows, start=1):
            row["rank"] = i
        return rows

    async def register_vote(self, match: str, weight: int) -> dict:
        """Verbucht einen Vote für ``match``: liest Stand, berechnet neuen Rang,
        schreibt die Zelle und sortiert das Blatt. Gibt Infos für die Chat-Nachricht
        zurück (sendet selbst NICHT)."""
        def _do():
            data = self.worksheet.get("A2:B", value_render_option="UNFORMATTED_VALUE")
            games = []
            cell_row = None
            current = 0
            for idx, r in enumerate(data, start=2):
                if len(r) >= 2 and str(r[1]).strip():
                    try:
                        v = int(r[0]) if str(r[0]).strip() else 0
                    except (ValueError, TypeError):
                        v = 0
                    name = str(r[1]).strip()
                    games.append({"votes": v, "name": name})
                    if name == match:
                        cell_row = idx
                        current = v

            # Alten Rang bestimmen.
            old_sorted = sorted(games, key=lambda x: (-x["votes"], x["name"]))
            old_rank = next((i for i, g in enumerate(old_sorted, 1) if g["name"] == match), 0)

            new_votes = current + weight

            # Neuen Stand lokal simulieren.
            found = False
            for g in games:
                if g["name"] == match:
                    g["votes"] = new_votes
                    found = True
            if not found:
                games.append({"votes": new_votes, "name": match})

            new_sorted = sorted(games, key=lambda x: (-x["votes"], x["name"]))
            new_rank = next((i for i, g in enumerate(new_sorted, 1) if g["name"] == match), 0)

            # Zelle schreiben (oder neue Zeile anhängen).
            if cell_row:
                self.worksheet.update_cell(cell_row, 1, new_votes)
            else:
                self.worksheet.append_row([new_votes, match])

            # Gesamtes Blatt sortiert zurückschreiben.
            self._write_sorted(new_sorted)

            return {
                "new_votes": new_votes,
                "added": weight,
                "rank": new_rank,
                "old_rank": old_rank,
                "games": [g["name"] for g in new_sorted],
            }

        result = await asyncio.to_thread(_do)
        # Spiele-Cache direkt aus dem neu sortierten Stand aktualisieren.
        self.games_list = result.pop("games")
        self.last_cache_update = time.time()
        return result

    def _write_sorted(self, sorted_games: list[dict]) -> None:
        """(läuft bereits im Thread) Schreibt Kopfzeile + sortierte Daten ab A1."""
        values = [[VOTE_COLUMN, GAME_COLUMN]]
        values += [[g["votes"], g["name"]] for g in sorted_games]
        end = gspread.utils.rowcol_to_a1(len(values), 2)
        self.worksheet.update(range_name=f"A1:{end}", values=values)

    async def test_connection(self, cfg: dict) -> dict:
        """Prüft Zugriff ohne dauerhaften State. Für den 'Verbindung testen'-Button."""
        try:
            def _do():
                client = self._client(cfg)
                sid = extract_spreadsheet_id(cfg["sheets"]["spreadsheet_id"])
                ss = client.open_by_key(sid)
                ws = ss.get_worksheet(cfg["sheets"].get("worksheet_index", 0))
                return ss.title, ws.title

            title, ws_title = await asyncio.to_thread(_do)
            return {"ok": True, "spreadsheet_title": title, "worksheet_title": ws_title,
                    "service_account_email": service_account_email(cfg)}
        except Exception as e:
            return {"ok": False, "error": str(e),
                    "service_account_email": service_account_email(cfg)}
