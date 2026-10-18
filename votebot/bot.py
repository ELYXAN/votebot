"""Kern-Bot: pollt Channel-Point-Redemptions, matcht Spielnamen, verbucht Votes
im Sheet, sendet Chat-Benachrichtigungen und beantwortet AI-Rewards.

Als start-/stopbare Tasks im laufenden Event-Loop (vom Web-Dashboard gesteuert).
"""
from __future__ import annotations

import asyncio
import time

import aiohttp
from rapidfuzz import process as fuzz_process

from . import ai, config as cfg_mod, twitch
from .logging_setup import get_logger
from .sheets import GoogleSheets

log = get_logger("votebot.bot")


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
        self.recent_votes: list[dict] = []
        self.stats = {"votes_processed": 0, "ai_answered": 0, "started_at": None}

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

                    found_new = False
                    for reward in rewards:
                        rid = reward["reward_id"]
                        try:
                            redemptions = await twitch.get_redemptions(session, self.cfg, rid)
                        except twitch.TwitchError:
                            break  # Token-Problem -> nächster Zyklus
                        for entry in redemptions:
                            vid = entry.get("id")
                            if vid in self.processed_ids:
                                continue
                            found_new = True
                            self.processed_ids.add(vid)
                            kind = reward.get("kind", "vote")
                            await self.queue.put({
                                "entry": entry,
                                "kind": kind,
                                "weight": int(reward.get("weight", 1)) if kind == "vote" else 0,
                                "reward_id": rid,
                                "reward_title": reward.get("title", ""),
                            })
                            log.info("Neuer Vote von %s: '%s' (%s).",
                                     entry.get("user_name"), entry.get("user_input", ""),
                                     reward.get("title", kind))
                        await asyncio.sleep(0.4)

                    await asyncio.sleep(0.5 if found_new else 2.0)
                except aiohttp.ClientConnectorError as e:
                    log.warning("Verbindungsfehler im Listener: %s - warte 15s.", e)
                    await asyncio.sleep(15)
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # noqa: BLE001
                    log.error("Unerwarteter Fehler im Listener: %s", e)
                    await asyncio.sleep(10)

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
        await self._notify_vote(session, user, match, result)

        self.stats["votes_processed"] += 1
        self._record_vote(user, match, result)
        await self._finish_redemption(session, kind, reward_id, vote_id)

    def _fuzzy_match(self, user_input: str) -> str | None:
        games = self.sheets.games_list
        if not games or not user_input:
            return None
        cutoff = self.cfg.get("matching", {}).get("min_match_score", 80)
        lower = [g.lower() for g in games]
        res = fuzz_process.extractOne(user_input.lower(), lower, score_cutoff=cutoff)
        if not res:
            log.info("Kein ausreichendes Match für '%s' (Cutoff %d).", user_input, cutoff)
            return None
        _, score, idx = res
        match = games[idx]
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
            "sheets_ready": self.sheets.ready,
            "queue_size": self.queue.qsize(),
            "stats": dict(self.stats),
            "recent_votes": list(self.recent_votes),
            "games_count": len(self.sheets.games_list),
        }
