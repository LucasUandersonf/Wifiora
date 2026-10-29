"""Coleta de sinais para o Radar de Ondas: feeds RSS/Atom e busca na web via assistente de IA.

Regra anti-alucinação: todo sinal nasce de uma URL que veio de fora (feed ou resultado de busca).
O LLM só classifica e resume itens dessa lista; nunca cria um sinal novo.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

import httpx

from app.skills.base import Skill, SkillError
from app.skills.builtin.web import USER_AGENT

ATOM = "{http://www.w3.org/2005/Atom}"


def url_hash(url: str) -> str:
    u = url.strip().split("#")[0].rstrip("/")
    u = re.sub(r"[?&]utm_[^&]+", "", u)
    return hashlib.sha256(u.lower().encode()).hexdigest()


def _date(text: str | None) -> datetime | None:
    if not text:
        return None
    text = text.strip()
    try:
        return parsedate_to_datetime(text).astimezone(UTC)
    except (TypeError, ValueError, IndexError):
        pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _clean(html: str | None, limit: int = 500) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()[:limit]


def parse_feed(xml_text: str, source: str) -> list[dict[str, Any]]:
    root = ET.fromstring(xml_text)
    items: list[dict[str, Any]] = []
    for it in root.iter("item"):  # RSS 2.0
        link = (it.findtext("link") or "").strip()
        if link:
            items.append({"url": link, "title": _clean(it.findtext("title"), 300), "summary": _clean(it.findtext("description")),
                          "published_at": _date(it.findtext("pubDate")), "source": source})
    for it in root.iter(f"{ATOM}entry"):  # Atom
        link_el = next((l for l in it.findall(f"{ATOM}link") if l.get("rel", "alternate") == "alternate"), None)
        link = (link_el.get("href") if link_el is not None else "") or ""
        if link:
            items.append({"url": link, "title": _clean(it.findtext(f"{ATOM}title"), 300),
                          "summary": _clean(it.findtext(f"{ATOM}summary") or it.findtext(f"{ATOM}content")),
                          "published_at": _date(it.findtext(f"{ATOM}updated") or it.findtext(f"{ATOM}published")), "source": source})
    return items


class FeedReaderSkill(Skill):
    name = "feed_reader"
    description = "Lê feeds RSS/Atom de notícias e devolve os itens recentes (com saúde de cada feed)."
    sectors = ("radar",)

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        feeds: list[str] = kwargs.get("feeds", [])
        max_age = timedelta(days=int(kwargs.get("max_age_days", 14)))
        now = datetime.now(UTC)
        health: list[dict[str, Any]] = []
        items: list[dict[str, Any]] = []
        sem = asyncio.Semaphore(4)

        async def one(url: str) -> None:
            async with sem:
                try:
                    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=20) as c:
                        r = await c.get(url)
                    r.raise_for_status()
                    if len(r.content) > 3_000_000:
                        raise SkillError("feed grande demais (>3 MB)")
                    got = parse_feed(r.text, urlparse(url).hostname or url)
                    fresh = [i for i in got if not i["published_at"] or now - i["published_at"] <= max_age]
                    items.extend(fresh)
                    health.append({"feed": url, "ok": True, "items": len(got), "recent": len(fresh)})
                except Exception as e:
                    health.append({"feed": url, "ok": False, "error": str(e)[:200]})

        await asyncio.gather(*(one(f) for f in feeds))
        return {"items": items, "feed_health": health}


class SignalSearchSkill(Skill):
    """Faz as consultas do radar a um assistente com busca na web e devolve os resultados encontrados."""

    name = "signal_search"
    description = "Busca notícias recentes na web (via assistente de IA com busca) para as consultas do radar."
    sectors = ("radar",)

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        if not self.office or not self.office.llm.can_search:
            raise SkillError("busca na web indisponível para este provedor de IA")
        queries: list[str] = kwargs.get("queries", [])[:12]
        items: list[dict[str, Any]] = []
        errors: list[str] = []
        for q in queries:
            try:
                res = await self.office.llm.search(
                    prompt=f"Quais são as notícias e anúncios oficiais mais recentes (últimas 2 semanas) sobre: {q}? Cite as fontes.",
                    agent_id=kwargs.get("agent_id"),
                    max_uses=2,
                )
            except Exception as e:
                errors.append(f"{q}: {e}")
                continue
            cited = set(res.urls)
            for r in res.results:
                items.append({
                    "url": r["url"], "title": (r.get("title") or "")[:300], "summary": "", "source": urlparse(r["url"]).hostname or "",
                    "published_at": None, "page_age": r.get("page_age"), "query": q, "cited": r["url"] in cited,
                })
        return {"items": items, "errors": errors}
