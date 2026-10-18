"""AI-Chat-Antworten via OpenAI mit optionaler DuckDuckGo-Websuche.
Extrahiert aus dem AI-Block der alten ``process_votes``.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime

from .logging_setup import get_logger

log = get_logger("votebot.ai")

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": (
                "Search the internet for real-time information, current events, or "
                "specific game details. Use this when the user asks about something "
                "recent or factual that you might not know."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query to send to the search engine.",
                    }
                },
                "required": ["query"],
            },
        },
    }
]


def _ddg_search(query: str) -> str:
    try:
        from ddgs import DDGS

        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=3, backend="html"))
        if results:
            return "\n".join(f"- {r['title']}: {r['body']}" for r in results)
        return "No results found."
    except Exception as e:  # noqa: BLE001
        log.warning("Web-Suche fehlgeschlagen: %s", e)
        return f"Search failed: {e}"


async def generate_ai_reply(api_key: str, model: str, user_input: str) -> str:
    """Erzeugt eine kurze Chatbot-Antwort (<400 Zeichen), ggf. mit Websuche."""
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=api_key)
    today = datetime.now().strftime("%Y-%m-%d")
    messages = [
        {
            "role": "system",
            "content": (
                f"You are a helpful Twitch chatbot. Today's date is {today}. "
                "If you need real-time info, use the search_web tool. Keep your FINAL "
                "answer brief and concise, under 400 characters."
            ),
        },
        {"role": "user", "content": user_input},
    ]

    first = await client.chat.completions.create(
        model=model, messages=messages, tools=_TOOLS, tool_choice="auto",
        max_tokens=150, temperature=0.7,
    )
    msg = first.choices[0].message

    if not msg.tool_calls:
        return (msg.content or "").strip()

    messages.append(msg)
    loop = asyncio.get_running_loop()
    for call in msg.tool_calls:
        if call.function.name == "search_web":
            args = json.loads(call.function.arguments)
            query = args.get("query", "")
            log.info("AI-Websuche: '%s'", query)
            result = await loop.run_in_executor(None, _ddg_search, query)
            messages.append({
                "tool_call_id": call.id,
                "role": "tool",
                "name": "search_web",
                "content": result,
            })

    final = await client.chat.completions.create(
        model=model, messages=messages, max_tokens=150, temperature=0.7,
    )
    return (final.choices[0].message.content or "").strip()
