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
# Zusatzspalten für neu aufgenommene Spiele. Erkannt wird die Spalte an ihrer
# Überschrift (Groß-/Kleinschreibung egal); der erste Name wird beim Anlegen genutzt.
SYSTEM_COLUMN = "System"
SYSTEM_HEADERS = ("system", "plattform", "platform", "konsole")
NOTES_COLUMN = "Besonderheiten"
NOTES_HEADERS = ("besonderheiten", "besonderheit", "notizen", "anmerkungen", "hinweise")
# Platz-Spalte: Steht eine Spalte mit einer dieser Überschriften im Blatt, hält
# der Bot dort den aktuellen Platz jedes Spiels (1 = meiste Votes) aktuell. Es
# ist derselbe Platz, den er im Chat nennt. Angelegt wird die Spalte nicht.
# ("positon" ist die Schreibweise im bestehenden Sheet.)
POSITION_HEADERS = ("positon", "position", "platz", "rang", "pos", "#")
# Gelesen wird das ganze Blatt, damit beim Sortieren ganze Zeilen wandern.
TABLE_RANGE = "A1:ZZ"
# Sekunden, die eine gelesene Rangliste fürs Dashboard wiederverwendet wird.
STANDINGS_TTL = 10.0


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
        self._standings: list[dict] | None = None
        self._standings_at: float = 0
        # Votes und das Hinzufügen von Spielen lesen das Blatt, rechnen und
        # schreiben es zurück. Die Sperre verhindert, dass sich zwei solche
        # Abläufe überholen und einer die Änderung des anderen überschreibt.
        self._lock = asyncio.Lock()

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

    async def get_standings(self, fresh: bool = False) -> list[dict]:
        """Liefert [{rank, votes, name}] absteigend nach Votes.

        Der Stand wird kurz zwischengespeichert (``STANDINGS_TTL``) und nach jedem
        verbuchten Vote direkt aktualisiert. So lösen mehrere offene Dashboards
        oder das Neuladen nach einem Vote keinen eigenen Sheets-Abruf aus.
        ``fresh=True`` erzwingt das Lesen aus dem Sheet."""
        if (not fresh and self._standings is not None
                and time.time() - self._standings_at < STANDINGS_TTL):
            return [dict(r) for r in self._standings]

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
        self._set_standings(rows)
        return [dict(r) for r in self._standings]

    def _set_standings(self, sorted_rows: list[dict]) -> None:
        self._standings = [
            {"votes": g["votes"], "name": g["name"], "rank": i}
            for i, g in enumerate(sorted_rows, start=1)
        ]
        self._standings_at = time.time()

    # --- Blatt lesen/schreiben (laufen bereits im Thread) -------------------
    @staticmethod
    def _position_col(header: list) -> int | None:
        """Index der Platz-Spalte (siehe ``POSITION_HEADERS``) oder ``None``."""
        for i, h in enumerate(header):
            if i >= 2 and str(h).strip().casefold() in POSITION_HEADERS:
                return i
        return None

    def _read_table(self) -> tuple[list, list[list], bool, int]:
        """Liest das ganze Blatt in einem Aufruf.

        Rückgabe: ``(header, rows, clean, used_rows)``. ``rows`` sind die Zeilen
        mit Spielnamen in Blatt-Reihenfolge, jede auf die volle Tabellenbreite
        aufgefüllt, mit Votes als ganze Zahl in Spalte 0 und dem Namen ohne
        Rand-Leerzeichen in Spalte 1. Alle weiteren Spalten (System,
        Besonderheiten, ...) bleiben unverändert an ihrer Zeile hängen.

        ``clean``: Die Spalten Votes/Game (und die Platz-Spalte, falls
        vorhanden) enthalten exakt das, was ein Neuschreiben erzeugen würde
        (lückenlos ab Zeile 2, Votes als ganze Zahl, Namen ohne Rand-Leerzeichen,
        Platz = Zeilennummer in der Liste). Nur dann ist das Schreiben einer
        einzelnen Zelle gleichwertig zum kompletten Neuschreiben.
        ``used_rows``: Anzahl belegter Datenzeilen inkl. Leerzeilen dazwischen."""
        data = self.worksheet.get(TABLE_RANGE, value_render_option="UNFORMATTED_VALUE")
        header = list(data[0]) if data else []
        body = data[1:]
        width = max([2, len(header)] + [len(r) for r in body])
        pos_col = self._position_col(header)
        rows: list[list] = []
        clean = True
        for idx, r in enumerate(body, start=2):
            if len(r) >= 2 and str(r[1]).strip():
                raw_votes, raw_name = r[0], r[1]
                try:
                    votes = int(raw_votes) if str(raw_votes).strip() else 0
                except (ValueError, TypeError):
                    votes = 0
                name = str(raw_name).strip()
                if type(raw_votes) is not int or raw_name != name or idx != len(rows) + 2:
                    clean = False
                if pos_col is not None:
                    pos = r[pos_col] if len(r) > pos_col else ""
                    if type(pos) is not int or pos != len(rows) + 1:
                        clean = False
                rows.append([votes, name] + list(r[2:]) + [""] * (width - len(r)))
        return header, rows, clean, len(body)

    def _write_table(self, header: list, sorted_rows: list[list], clear_rows: int = 0) -> None:
        """Schreibt Kopfzeile + sortierte Zeilen ab A1 in voller Breite, sodass
        jede Zeile als Ganzes wandert und die Zusatzspalten bei ihrem Spiel
        bleiben. Die Platz-Spalte (falls vorhanden) wird dabei neu durchgezählt.
        ``clear_rows`` leert zusätzlich so viele Zeilen darunter.

        Hinweis: Geschrieben werden Werte. Stünde in einer Zusatzspalte eine
        Formel, würde sie beim ersten Umsortieren durch ihr Ergebnis ersetzt."""
        width = max([2, len(header)] + [len(r) for r in sorted_rows])
        head = list(header) + [""] * (width - len(header))
        if not str(head[0]).strip():
            head[0] = VOTE_COLUMN
        if not str(head[1]).strip():
            head[1] = GAME_COLUMN
        values = [head]
        values += [list(r) + [""] * (width - len(r)) for r in sorted_rows]
        pos_col = self._position_col(head)
        if pos_col is not None:
            for place, row in enumerate(values[1:], start=1):
                row[pos_col] = place
        values += [[""] * width] * max(clear_rows, 0)
        end = gspread.utils.rowcol_to_a1(len(values), width)
        self.worksheet.update(range_name=f"A1:{end}", values=values)

    @staticmethod
    def _sorted(rows: list[list]) -> list[list]:
        return sorted(rows, key=lambda r: (-r[0], r[1]))

    def _after_write(self, sorted_rows: list[list]) -> None:
        """Spiele-Cache und Rangliste direkt aus dem neu sortierten Stand setzen."""
        self.games_list = [r[1] for r in sorted_rows]
        self.last_cache_update = time.time()
        self._set_standings([{"votes": r[0], "name": r[1]} for r in sorted_rows])

    async def register_vote(self, match: str, weight: int) -> dict:
        """Verbucht einen Vote für ``match``: liest Stand, berechnet neuen Rang
        und schreibt das Ergebnis. Gibt Infos für die Chat-Nachricht zurück
        (sendet selbst NICHT).

        Pro Vote genau zwei Sheets-Aufrufe (Lesen + Schreiben). Ändert der Vote
        die Reihenfolge nicht und ist das Blatt bereits sauber sortiert, wird nur
        die eine Zelle geschrieben; sonst wird das Blatt sortiert neu geschrieben,
        und zwar ganze Zeilen, damit Zusatzspalten bei ihrem Spiel bleiben."""
        def _do():
            header, rows, clean, used_rows = self._read_table()
            hits = [i for i, r in enumerate(rows) if r[1] == match]
            current = rows[hits[-1]][0] if hits else 0

            # Alten Rang bestimmen.
            old_rank = next((i for i, r in enumerate(self._sorted(rows), 1) if r[1] == match), 0)

            new_votes = current + weight

            # Neuen Stand lokal simulieren.
            for i in hits:
                rows[i][0] = new_votes
            if not hits:
                width = len(rows[0]) if rows else max(2, len(header))
                rows.append([new_votes, match] + [""] * (width - 2))

            new_sorted = self._sorted(rows)
            new_rank = next((i for i, r in enumerate(new_sorted, 1) if r[1] == match), 0)

            if (len(hits) == 1 and clean
                    and [r[:2] for r in rows] == [r[:2] for r in new_sorted]):
                # Reihenfolge unverändert: nur die Vote-Zelle schreiben.
                self.worksheet.update_cell(hits[0] + 2, 1, new_votes)
            else:
                if not hits:
                    # Neues Spiel: Zeile anhängen (erweitert bei Bedarf das Blatt).
                    self.worksheet.append_row([new_votes, match])
                    used_rows += 1
                # Gesamtes Blatt sortiert zurückschreiben. Enthielt es Leer- oder
                # Restzeilen, werden die übrig bleibenden Zeilen darunter geleert,
                # damit kein veralteter Eintrag stehen bleibt.
                self._write_table(header, new_sorted, clear_rows=used_rows - len(new_sorted))

            return {
                "new_votes": new_votes,
                "added": weight,
                "rank": new_rank,
                "old_rank": old_rank,
                "sorted": new_sorted,
            }

        async with self._lock:
            result = await asyncio.to_thread(_do)
            self._after_write(result.pop("sorted"))
        return result

    async def add_games(self, games: list[dict]) -> dict:
        """Nimmt neue Spiele mit 0 Votes in das Blatt auf.

        ``games``: ``[{"name": ..., "system": ..., "notes": ...}]``; ``system``
        (Plattform) und ``notes`` (Besonderheiten) sind optional und landen in
        den Spalten mit der passenden Überschrift (siehe ``SYSTEM_HEADERS`` /
        ``NOTES_HEADERS``). Fehlt eine solche Spalte und ist ein Wert angegeben,
        wird sie rechts angelegt.

        Gibt ``{"added": [...], "existing": [...]}`` zurück. Ein Spiel gilt als
        vorhanden, wenn sein Name ohne Beachtung der Groß-/Kleinschreibung schon
        im Blatt steht; ``existing`` nennt dann die Schreibweise aus dem Blatt.
        Das Blatt bleibt wie nach einem Vote sortiert (Votes absteigend, dann
        Name), neue Spiele landen also alphabetisch zwischen den 0-Vote-Spielen."""
        wanted = []
        for g in games:
            name = str(g.get("name") or "").strip()
            if name:
                wanted.append((name, str(g.get("system") or "").strip(),
                               str(g.get("notes") or "").strip()))

        def _do():
            header, rows, _clean, used_rows = self._read_table()
            header = list(header)

            def column(aliases: tuple[str, ...], title: str, needed: bool) -> int | None:
                """Index der Spalte mit einer der Überschriften; legt sie bei Bedarf an."""
                for i, h in enumerate(header):
                    if i >= 2 and str(h).strip().casefold() in aliases:
                        return i
                if not needed:
                    return None
                while len(header) < 2:
                    header.append("")
                header.append(title)
                return len(header) - 1

            known = {r[1].casefold(): r[1] for r in rows}
            added, existing, new_rows = [], [], []
            for name, system, notes in wanted:
                key = name.casefold()
                if key in known:
                    if known[key] not in existing and known[key] not in added:
                        existing.append(known[key])
                    continue
                known[key] = name
                added.append(name)
                new_rows.append((name, system, notes))

            if not added:
                return added, existing, None

            sys_col = column(SYSTEM_HEADERS, SYSTEM_COLUMN, any(s for _, s, _ in new_rows))
            notes_col = column(NOTES_HEADERS, NOTES_COLUMN, any(n for _, _, n in new_rows))
            width = max([2, len(header)] + [len(r) for r in rows])
            rows = [r + [""] * (width - len(r)) for r in rows]
            for name, system, notes in new_rows:
                row = [0, name] + [""] * (width - 2)
                if sys_col is not None:
                    row[sys_col] = system
                if notes_col is not None:
                    row[notes_col] = notes
                rows.append(row)

            # Zeilen anhängen (erweitert bei Bedarf das Blatt), dann alles
            # sortiert zurückschreiben und übrig gebliebene Restzeilen leeren.
            self.worksheet.append_rows([[0, n] for n in added])
            new_sorted = self._sorted(rows)
            self._write_table(header, new_sorted,
                              clear_rows=used_rows + len(added) - len(new_sorted))
            return added, existing, new_sorted

        async with self._lock:
            added, existing, new_sorted = await asyncio.to_thread(_do)
            if new_sorted is not None:
                self._after_write(new_sorted)
        for name in added:
            log.info("Neues Spiel ins Sheet aufgenommen: %s", name)
        return {"added": added, "existing": existing}

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
