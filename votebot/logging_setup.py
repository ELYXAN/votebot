"""Zentrales Logging: schreibt in einen Ringpuffer und broadcastet live an
verbundene WebSocket-Clients. Ersetzt die ``print()``-Ausgaben des alten Skripts.
"""
from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import datetime
from typing import Any

MAX_BUFFER = 500

# Ringpuffer der letzten Log-Zeilen (für neu verbundene Clients).
_buffer: deque[dict] = deque(maxlen=MAX_BUFFER)
_subscribers: set[asyncio.Queue] = set()
_loop: asyncio.AbstractEventLoop | None = None


def set_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Merkt sich den Event-Loop, damit Logs aus Threads zugestellt werden können."""
    global _loop
    _loop = loop


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue()
    _subscribers.add(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    _subscribers.discard(q)


def recent() -> list[dict]:
    return list(_buffer)


def _dispatch(record: dict) -> None:
    _buffer.append(record)
    for q in list(_subscribers):
        try:
            q.put_nowait(record)
        except asyncio.QueueFull:
            pass


class DashboardHandler(logging.Handler):
    """Leitet Log-Records thread-sicher an die WebSocket-Subscriber weiter."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
        except Exception:
            msg = record.getMessage()
        entry = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": msg,
        }
        if _loop is not None and _loop.is_running():
            _loop.call_soon_threadsafe(_dispatch, entry)
        else:
            _dispatch(entry)


def configure(level: int = logging.INFO) -> logging.Logger:
    """Konfiguriert Root-Logger mit Konsole + Dashboard-Handler (idempotent)."""
    root = logging.getLogger()
    root.setLevel(level)

    if not any(isinstance(h, DashboardHandler) for h in root.handlers):
        fmt = logging.Formatter("%(message)s")

        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%H:%M:%S"))
        root.addHandler(console)

        dash = DashboardHandler()
        dash.setFormatter(fmt)
        root.addHandler(dash)

    # Fremd-Logger (uvicorn access etc.) nicht ins Dashboard spammen.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)
    logging.getLogger("gspread").setLevel(logging.WARNING)
    return logging.getLogger("votebot")


def get_logger(name: str = "votebot") -> logging.Logger:
    return logging.getLogger(name)
