"""Contador de robôs de IA: quem lê o portal, o quê e quando.

Acessos chegam por dois caminhos: o middleware do FastAPI (quando ele serve o site) e o beacon do
portal Next.js (POST /api/public/bot-hit com o segredo de revalidação). Contamos em memória e
gravamos em lote a cada FLUSH_SECONDS, para não escrever no banco a cada requisição.
"""

from __future__ import annotations

import asyncio
import time
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.db import session_scope
from app.models import BotHit

# Ordem importa: o primeiro padrão que aparecer no User-Agent define o robô.
BOTS: list[tuple[str, str]] = [
    ("OAI-SearchBot", "OAI-SearchBot"),
    ("ChatGPT-User", "ChatGPT-User"),
    ("GPTBot", "GPTBot"),
    ("Claude-SearchBot", "Claude-SearchBot"),
    ("Claude-User", "Claude-User"),
    ("ClaudeBot", "ClaudeBot"),
    ("Perplexity-User", "Perplexity-User"),
    ("PerplexityBot", "PerplexityBot"),
    ("Google-Extended", "Google-Extended"),
    ("Google-CloudVertexBot", "Google-Vertex"),
    ("Googlebot", "Googlebot"),
    ("bingbot", "Bingbot"),
    ("Applebot-Extended", "Applebot-Extended"),
    ("Applebot", "Applebot"),
    ("meta-externalagent", "Meta"),
    ("FacebookBot", "Meta"),
    ("Amazonbot", "Amazonbot"),
    ("Bytespider", "Bytespider"),
    ("CCBot", "CCBot"),
    ("cohere-ai", "Cohere"),
    ("DuckAssistBot", "DuckAssist"),
    ("MistralAI-User", "Mistral"),
]
FLUSH_SECONDS = 30


def classify_bot(user_agent: str | None) -> str | None:
    ua = (user_agent or "").lower()
    for pattern, name in BOTS:
        if pattern.lower() in ua:
            return name
    return None


def path_hub(path: str) -> str:
    parts = path.split("/")
    return parts[2][:120] if len(parts) > 2 and parts[1] == "hub" else ""


def path_kind(path: str) -> str:
    if path.endswith(("/data.json", "/data.jsonl", "/data.csv", "/data.md")) or path.startswith("/data/"):
        return "data"
    if path.endswith(".jsonld"):
        return "graph"
    if path.startswith("/llms"):
        return "llms"
    if path.startswith(("/hub", "/empresa", "/conceitos", "/dados")) or path == "/":
        return "page"
    return "other"


class BotCounter:
    def __init__(self) -> None:
        self.buffer: Counter[tuple[str, str, str, str]] = Counter()
        self.last_path: dict[tuple[str, str, str, str], str] = {}
        self.last_flush = time.monotonic()
        self._lock = asyncio.Lock()

    def add(self, user_agent: str | None, path: str) -> str | None:
        bot = classify_bot(user_agent)
        if bot is None:
            return None
        key = (datetime.now(UTC).date().isoformat(), bot, path_kind(path), path_hub(path))
        self.buffer[key] += 1
        self.last_path[key] = path[:300]
        return bot

    def due(self) -> bool:
        return bool(self.buffer) and time.monotonic() - self.last_flush >= FLUSH_SECONDS

    async def flush(self) -> int:
        async with self._lock:
            pending, paths = self.buffer, self.last_path
            self.buffer, self.last_path = Counter(), {}
            self.last_flush = time.monotonic()
            if not pending:
                return 0
            async with session_scope() as s:
                for (day, bot, kind, hub), n in pending.items():
                    q = select(BotHit).where(BotHit.day == day, BotHit.bot == bot, BotHit.kind == kind, BotHit.hub == hub)
                    row = (await s.execute(q)).scalar_one_or_none()
                    if row is None:
                        row = BotHit(day=day, bot=bot, kind=kind, hub=hub, hits=0)
                        s.add(row)
                    row.hits += n
                    row.last_path = paths.get((day, bot, kind, hub), "")
                    row.last_at = datetime.now(UTC)
            return sum(pending.values())


COUNTER = BotCounter()


async def summary(days: int = 30, hub: str | None = None) -> dict[str, Any]:
    await COUNTER.flush()
    since = (datetime.now(UTC) - timedelta(days=days)).date().isoformat()
    q = select(BotHit).where(BotHit.day >= since)
    if hub is not None:
        q = q.where(BotHit.hub == hub)
    async with session_scope() as s:
        rows = list((await s.execute(q)).scalars())
    by_bot: dict[str, dict[str, Any]] = {}
    for r in rows:
        b = by_bot.setdefault(r.bot, {"bot": r.bot, "total": 0, "page": 0, "data": 0, "graph": 0, "llms": 0, "other": 0, "last_at": None, "last_path": ""})
        b["total"] += r.hits
        b[r.kind] = b.get(r.kind, 0) + r.hits
        if b["last_at"] is None or r.last_at > b["last_at"]:
            b["last_at"], b["last_path"] = r.last_at, r.last_path
    bots = sorted(by_bot.values(), key=lambda b: -b["total"])
    return {
        "days": days,
        "total": sum(b["total"] for b in bots),
        "data_downloads": sum(b["data"] + b["graph"] for b in bots),
        "bots": bots,
    }
