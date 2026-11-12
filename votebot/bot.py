"""Kern-Bot: empfängt Channel-Point-Redemptions, matcht Spielnamen, verbucht
Votes im Sheet, sendet Chat-Benachrichtigungen und beantwortet AI-Rewards.

Neue Einlösungen kommen in Echtzeit über Twitch EventSub (WebSocket-Push).
Die Abfrage der offenen Einlösungen läuft als Sicherheitsnetz weiter: einmal
direkt nach jedem Verbindungsaufbau (holt alles nach, was währenddessen
einging), danach in großen Abständen. Fällt der Push aus, wird wie früher im
Sekundentakt abgefragt. Doppelte Zustellung verhindert ``processed_ids``.

Als start-/stopbare Tasks im laufenden Event-Loop (vom Web-Dashboard gesteuert).
"""
from __future__ import annotations

import asyncio
import json
import time

import aiohttp
from . import ai, config as cfg_mod, matching, twitch
from .logging_setup import get_logger
from .sheets import GoogleSheets

log = get_logger("votebot.bot")

# Abstand der Sicherheits-Abfrage, solange der Echtzeit-Push steht (Sekunden).
SAFETY_POLL_INTERVAL = 30.0


def load_processed_ids() -> set[str]:
    try:
        with open(cfg_mod.VOTE_IDS_FILE, "r", encoding="utf-8") as f:
            return {line.strip() for line in f if line.strip()}
    except FileNotFoundError:
        return set()


def save_processed_id(vote_id: str) -> None:
    with open(cfg_mod.VOTE_IDS_FILE, "a", encoding="utf-8") as f:
        f.write(f"{vote_id}\n")


def save_inaccurate_game(game_name: str) -> None:
    with open(cfg_mod.INACCURATE_GAMES_FILE, "a", encoding="utf-8") as f:
        f.write(f"{game_name} | Vote-Anzahl: 1\n")


class VoteBot:
    def __init__(self, cfg: dict) -> None:
        self.cfg = cfg
        self.sheets = GoogleSheets()
        self.queue: asyncio.Queue = asyncio.Queue()
        self.processed_ids: set[str] = load_processed_ids()
        self.running = False
        self._tasks: list[asyncio.Task] = []
        # True, solange die EventSub-Verbindung steht und abonniert ist.
        self.push_live = False
        # Weckt den Listener sofort für eine Nachhol-Abfrage.
        self._poll_now = asyncio.Event()
        self.recent_votes: list[dict] = []
        self.stats = {
            "votes_processed": 0,
            "ai_answered": 0,
            "started_at": None,
            "votes_by_reward": {},
            "votes_by_game": {},  # Session: Summe der Vote-Gewichte pro Spiel
            "voters": {},         # Session: pro User {count, weight, games:{game:weight}}
        }

    def reset_session_stats(self) -> None:
        """Setzt die Session-Statistiken zurück (z. B. zu Stream-Beginn)."""
        self.stats["votes_processed"] = 0
        self.stats["ai_answered"] = 0
        self.stats["votes_by_reward"] = {}
        self.stats["votes_by_game"] = {}
        self.stats["voters"] = {}
        self.recent_votes = []
        log.info("Session-Statistiken zurückgesetzt.")

    # --- Lebenszyklus ----------------------------------------------------
    async def start(self) -> None:
        if self.running:
            return
        log.info("Bot wird gestartet...")
        try:
            await self.sheets.connect(self.cfg)
        except Exception as e:  # noqa: BLE001
            log.error("Google Sheets konnte nicht verbunden werden: %s", e)
            raise

        self.running = True
        self.stats["started_at"] = time.time()
        self._tasks = [
            asyncio.create_task(self._listener(), name="votebot-listener"),
            asyncio.create_task(self._eventsub(), name="votebot-eventsub"),
            asyncio.create_task(self._processor(), name="votebot-processor"),
        ]
        log.info("Bot läuft - überwache Votes für Kanal '%s'.",
                 self.cfg["broadcaster"].get("login", "?"))

    async def stop(self) -> None:
        if not self.running:
            return
        log.info("Bot wird gestoppt...")
        self.running = False
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except asyncio.CancelledError:
                pass
        self._tasks = []
        self.push_live = False
        log.info("Bot gestoppt.")

    # --- Manueller Vote (vom Dashboard) ----------------------------------
    def enqueue_manual(self, game: str, count: int) -> None:
        entry = {
            "user_name": self.cfg.get("manual_vote_user", "Dashboard"),
            "user_input": game.strip(),
            "id": f"manual_{int(time.time() * 1000)}",
        }
        self.queue.put_nowait({"entry": entry, "kind": "manual", "weight": count, "reward_id": None})
        log.info("Manueller Vote eingereiht: '%s' (+%d).", game, count)

    # --- Listener --------------------------------------------------------
    def _vote_rewards(self) -> list[dict]:
        return [r for r in self.cfg.get("rewards", []) if r.get("reward_id")]

    async def _listener(self) -> None:
        async with aiohttp.ClientSession() as session:
            while self.running:
                try:
                    if not await twitch.ensure_valid_token(session, self.cfg, "broadcaster"):
                        log.warning("Broadcaster-Token ungültig - warte 60s.")
                        await asyncio.sleep(60)
                        continue

                    rewards = self._vote_rewards()
                    if not rewards:
                        await asyncio.sleep(10)
                        continue

                    # Alle Belohnungen gleichzeitig abfragen statt nacheinander.
                    results = await asyncio.gather(
                        *(twitch.get_redemptions(session, self.cfg, r["reward_id"]) for r in rewards),
                        return_exceptions=True,
                    )
                    found_new = False
                    for reward, redemptions in zip(rewards, results):
                        rid = reward["reward_id"]
                        if isinstance(redemptions, twitch.TwitchError):
                            break  # Token-Problem -> nächster Zyklus
                        if isinstance(redemptions, BaseException):
                            raise redemptions
                        for entry in redemptions:
                            if self._enqueue_redemption(reward, entry):
                                found_new = True

                    if self.push_live:
                        # Push liefert in Echtzeit - nur noch selten nachsehen,
                        # oder sofort, wenn die Verbindung neu aufgebaut wurde.
                        await self._wait_poll(SAFETY_POLL_INTERVAL)
                    else:
                        await self._wait_poll(0.5 if found_new else 2.0)
                except aiohttp.ClientConnectorError as e:
                    log.warning("Verbindungsfehler im Listener: %s - warte 15s.", e)
                    await asyncio.sleep(15)
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # noqa: BLE001
                    log.error("Unerwarteter Fehler im Listener: %s", e)
                    await asyncio.sleep(10)

    def _enqueue_redemption(self, reward: dict, entry: dict) -> bool:
        """Reiht eine Einlösung ein, sofern sie noch nicht gesehen wurde.
        Gemeinsamer Weg für Push und Abfrage (kein await -> keine Dubletten)."""
        vid = entry.get("id")
        if not vid or vid in self.processed_ids:
            return False
        self.processed_ids.add(vid)
        kind = reward.get("kind", "vote")
        self.queue.put_nowait({
            "entry": entry,
            "kind": kind,
            "weight": int(reward.get("weight", 1)) if kind == "vote" else 0,
            "reward_id": reward["reward_id"],
            "reward_title": reward.get("title", ""),
        })
        log.info("Neuer Vote von %s: '%s' (%s).",
                 entry.get("user_name"), entry.get("user_input", ""),
                 reward.get("title", kind))
        return True

    async def _wait_poll(self, delay: float) -> None:
        """Wartet ``delay`` Sekunden oder bis eine Nachhol-Abfrage angefordert wird."""
        try:
            await asyncio.wait_for(self._poll_now.wait(), timeout=delay)
        except asyncio.TimeoutError:
            pass
        self._poll_now.clear()

    # --- EventSub (Echtzeit-Push) ----------------------------------------
    async def _eventsub(self) -> None:
        """Hält die EventSub-WebSocket-Verbindung und baut sie bei Bedarf neu auf."""
        url = twitch.EVENTSUB_WS_URL
        backoff = 2.0
        async with aiohttp.ClientSession() as session:
            while self.running:
                try:
                    # Kehrt nur zurück, wenn Twitch einen Umzug auf eine neue URL verlangt.
                    url = await self._eventsub_session(session, url)
                    backoff = 2.0
                    continue
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # noqa: BLE001
                    if self.push_live:
                        log.warning("Echtzeit-Verbindung zu Twitch unterbrochen (%s) - "
                                    "frage solange im Sekundentakt ab.", str(e) or type(e).__name__)
                    else:
                        log.warning("Echtzeit-Verbindung zu Twitch nicht möglich (%s) - "
                                    "neuer Versuch in %.0fs.", str(e) or type(e).__name__, backoff)
                self.push_live = False
                self._poll_now.set()  # Listener sofort auf schnellen Takt umstellen
                url = twitch.EVENTSUB_WS_URL
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)

    async def _eventsub_session(self, session: aiohttp.ClientSession, url: str) -> str:
        """Eine WebSocket-Sitzung. Gibt die neue URL zurück, wenn Twitch einen
        Verbindungswechsel anfordert; wirft bei Abbruch oder Zeitüberschreitung."""
        # Bei einem von Twitch angeforderten Wechsel ziehen die Abos automatisch mit.
        subscribed = url != twitch.EVENTSUB_WS_URL
        timeout = 20.0
        ws = await session.ws_connect(url)
        try:
            while True:
                # Twitch sendet mindestens alle ``keepalive_timeout_seconds`` etwas.
                msg = await asyncio.wait_for(ws.receive(), timeout=timeout)
                if msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSING,
                                aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    raise ConnectionError(f"Verbindung geschlossen (Code {ws.close_code})")
                if msg.type != aiohttp.WSMsgType.TEXT:
                    continue
                data = json.loads(msg.data)
                mtype = data.get("metadata", {}).get("message_type")
                payload = data.get("payload", {})

                if mtype == "session_welcome":
                    ws_session = payload.get("session", {})
                    timeout = float(ws_session.get("keepalive_timeout_seconds") or 10) + 10.0
                    if not subscribed:
                        if not await twitch.ensure_valid_token(session, self.cfg, "broadcaster"):
                            raise twitch.TwitchError("Broadcaster-Token ungültig")
                        await twitch.eventsub_subscribe_redemptions(session, self.cfg, ws_session["id"])
                        subscribed = True
                    if not self.push_live:
                        log.info("Echtzeit-Verbindung zu Twitch steht - Votes kommen ohne Verzögerung an.")
                    self.push_live = True
                    # Einmal abfragen: holt nach, was vor/während des Aufbaus einging.
                    self._poll_now.set()
                elif mtype == "notification":
                    self._on_eventsub_notification(payload)
                elif mtype == "session_reconnect":
                    return payload.get("session", {}).get("reconnect_url") or twitch.EVENTSUB_WS_URL
                elif mtype == "revocation":
                    reason = payload.get("subscription", {}).get("status", "?")
                    raise ConnectionError(f"Abo von Twitch widerrufen ({reason})")
                # session_keepalive: nichts zu tun, hält nur den Timeout zurück.
        finally:
            # Schließen nie lange blockieren lassen (Gegenstelle antwortet evtl. nicht).
            try:
                await asyncio.wait_for(ws.close(), timeout=3)
            except Exception:  # noqa: BLE001
                pass

    def _on_eventsub_notification(self, payload: dict) -> None:
        if payload.get("subscription", {}).get("type") != twitch.REDEMPTION_ADD:
            return
        event = payload.get("event", {})
        # Wie die Abfrage nur offene Einlösungen verarbeiten.
        if str(event.get("status", "")).lower() != "unfulfilled":
            return
        reward_id = event.get("reward", {}).get("id")
        reward = next((r for r in self._vote_rewards() if r["reward_id"] == reward_id), None)
        if not reward:
            return  # Belohnung gehört nicht zu Tally
        self._enqueue_redemption(reward, {
            "id": event.get("id"),
            "user_name": event.get("user_name"),
            "user_login": event.get("user_login"),
            "user_id": event.get("user_id"),
            "user_input": event.get("user_input", ""),
        })

    # --- Processor -------------------------------------------------------
    async def _processor(self) -> None:
        async with aiohttp.ClientSession() as session:
            while self.running:
                try:
                    data = await self.queue.get()
                except asyncio.CancelledError:
                    raise
                try:
                    await self._handle_vote(session, data)
                except Exception as e:  # noqa: BLE001
                    log.error("Fehler bei Vote-Verarbeitung: %s", e)
                finally:
                    self.queue.task_done()

    async def _handle_vote(self, session: aiohttp.ClientSession, data: dict) -> None:
        entry = data["entry"]
        kind = data["kind"]
        reward_id = data.get("reward_id")
        vote_id = entry.get("id")
        user = entry.get("user_name") or data["entry"].get("user_name")
        user_input = (entry.get("user_input") or "").strip()

        if kind == "ai":
            await self._handle_ai(session, data, user, user_input, reward_id, vote_id)
            return

        if not self.sheets.ready:
            log.error("Sheet nicht verfügbar - Vote übersprungen.")
            return

        weight = int(data.get("weight", 1))

        # Spiele-Cache ggf. auffrischen.
        if time.time() - self.sheets.last_cache_update > self.sheets.cache_validity:
            await self.sheets.update_games_cache()

        match = self._fuzzy_match(user_input)
        if not match:
            log.info("Kein passendes Spiel für '%s' - als ungenau gespeichert.", user_input)
            save_inaccurate_game(user_input)
            await self._finish_redemption(session, kind, reward_id, vote_id)
            return

        result = await self.sheets.register_vote(match, weight)

        self.stats["votes_processed"] += 1
        label = data.get("reward_title") or ("Manuell" if kind == "manual" else "Vote")
        self.stats["votes_by_reward"][label] = self.stats["votes_by_reward"].get(label, 0) + 1
        self.stats["votes_by_game"][match] = self.stats["votes_by_game"].get(match, 0) + weight
        voter = self.stats["voters"].setdefault(str(user), {"count": 0, "weight": 0, "games": {}})
        voter["count"] += 1
        voter["weight"] += weight
        voter["games"][match] = voter["games"].get(match, 0) + weight
        self._record_vote(user, match, result)

        # Chat-Nachricht und Abschluss der Einlösung sind unabhängig -> gleichzeitig.
        outcomes = await asyncio.gather(
            self._notify_vote(session, user, match, result),
            self._finish_redemption(session, kind, reward_id, vote_id),
            return_exceptions=True,
        )
        for step, outcome in zip(("Chat-Nachricht", "Abschluss der Einlösung"), outcomes):
            if isinstance(outcome, Exception):
                log.error("Fehler bei %s nach verbuchtem Vote: %s", step, outcome)

    def _fuzzy_match(self, user_input: str) -> str | None:
        games = self.sheets.games_list
        if not games or not user_input:
            return None
        cutoff = self.cfg.get("matching", {}).get("min_match_score", 80)
        res = matching.best_match(user_input, games, cutoff)
        if not res:
            log.info("Kein ausreichendes Match für '%s' (Cutoff %d).", user_input, cutoff)
            return None
        match, score = res
        log.info("Match: '%s' (Score %.0f) für Eingabe '%s'.", match, score, user_input)
        return match

    async def _notify_vote(self, session, user, game, result) -> None:
        rank = result["rank"]
        old_rank = result["old_rank"]
        new_votes = result["new_votes"]
        added = result["added"]

        parts = [
            f"🗳️ @{user} hat für '{game}' gevotet!",
            f"(+{added})",
            f"➡️ Total: {new_votes} Votes",
        ]
        rank_info = f"🏆 Rang: #{rank}"
        if old_rank > 0 and rank < old_rank:
            rank_info += f" 📈 (hoch von #{old_rank}!)"
        elif old_rank == 0:
            rank_info += " ✨ (Neueinsteiger!)"
        parts.append(rank_info)
        await twitch.send_chat_message(session, self.cfg, " | ".join(parts))

    async def _handle_ai(self, session, data, user, user_input, reward_id, vote_id) -> None:
        api_key = self.cfg.get("openai", {}).get("api_key")
        if not api_key:
            log.error("AI-Reward empfangen, aber kein OpenAI-Key konfiguriert.")
            return
        try:
            model = self.cfg.get("openai", {}).get("model", "gpt-4o")
            reply = await ai.generate_ai_reply(api_key, model, user_input)
            await twitch.send_chat_message(session, self.cfg, f"🤖 @{user}: {reply}")
            self.stats["ai_answered"] += 1
        except Exception as e:  # noqa: BLE001
            log.error("Fehler bei OpenAI-Anfrage: %s", e)
            await twitch.send_chat_message(
                session, self.cfg, f"@{user} meine AI-Hirnzellen haben gerade Kurzschluss. 😵"
            )
        finally:
            await self._finish_redemption(session, "ai", reward_id, vote_id)

    async def _finish_redemption(self, session, kind, reward_id, vote_id) -> None:
        if kind == "manual" or not reward_id:
            return
        if await twitch.ensure_valid_token(session, self.cfg, "broadcaster"):
            if await twitch.fulfill_redemption(session, self.cfg, reward_id, vote_id):
                save_processed_id(vote_id)

    def _record_vote(self, user, game, result) -> None:
        self.recent_votes.insert(0, {
            "time": time.strftime("%H:%M:%S"),
            "user": user,
            "game": game,
            "added": result["added"],
            "total": result["new_votes"],
            "rank": result["rank"],
        })
        self.recent_votes = self.recent_votes[:25]

    # --- Status fürs Dashboard ------------------------------------------
    def status(self) -> dict:
        return {
            "running": self.running,
            "push_live": self.push_live,
            "sheets_ready": self.sheets.ready,
            "queue_size": self.queue.qsize(),
            "stats": dict(self.stats),
            "recent_votes": list(self.recent_votes),
            "games_count": len(self.sheets.games_list),
        }
