"""IndexNow Semântico: avisar (push) em vez de esperar o robô passar (pull).

Quando um dado muda, anunciamos só o que mudou — e tudo o que depende dele no grafo: a ficha, a página
do hub, a página da empresa, os arquivos em lote e o grafo completo. Dois destinos:
  1. Portal Next.js: revalidação sob demanda (a página nova fica no ar em segundos).
  2. IndexNow (api.indexnow.org): repassado a Bing, Yandex, Naver, Seznam e Yep. O índice do Bing
     alimenta buscas de vários assistentes. Google e OpenAI NÃO recebem IndexNow; para eles valem o
     sitemap com <lastmod> e os arquivos com ETag/Last-Modified.

Hubs com dados de demonstração nunca são anunciados aos buscadores.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import Settings
from app.db import session_scope
from app.models import IndexPing

log = logging.getLogger(__name__)

INDEXNOW_ENDPOINT = "https://api.indexnow.org/indexnow"
MAX_URLS = 10_000  # limite do protocolo por envio
DATA_FILES = ("data.jsonld", "data.jsonl", "data.json", "data.csv", "data.md")
SITE_FILES = ["/knowledge-graph.jsonld", "/data/all.jsonl", "/data/catalog.jsonld", "/llms-full.txt"]


def _is_public_host(url: str) -> bool:
    host = urlparse(url).hostname or ""
    return bool(host) and host not in ("localhost", "127.0.0.1") and not host.endswith((".local", ".internal", ".invalid"))


def affected_paths(hub_slug: str, entity_slugs: list[str], org_slugs: list[str] | None = None, *, new_hub: bool = False) -> list[str]:
    """Tudo o que muda quando estas fichas mudam (o "raio" da mudança no grafo)."""
    paths = [f"/hub/{hub_slug}/{e}" for e in entity_slugs]
    paths += [f"/hub/{hub_slug}"] + [f"/hub/{hub_slug}/{f}" for f in DATA_FILES]
    paths += [f"/empresa/{o}" for o in dict.fromkeys(org_slugs or []) if o]
    paths += ["/conceitos", "/dados", *SITE_FILES]
    if new_hub:
        paths += ["/", "/hubs"]
    return list(dict.fromkeys(paths))


async def announce(
    settings: Settings,
    *,
    hub_slug: str,
    entity_slugs: list[str],
    demo: bool,
    org_slugs: list[str] | None = None,
    reason: str = "publish",
    changed: dict[str, list[str]] | None = None,
    changed_at: datetime | None = None,
    new_hub: bool = False,
) -> dict[str, Any]:
    paths = affected_paths(hub_slug, entity_slugs, org_slugs, new_hub=new_hub)
    result: dict[str, Any] = {"revalidated": False, "indexnow": "skipped", "urls": len(paths), "reason": reason}

    if settings.portal_url and settings.revalidate_secret:
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.post(
                    settings.portal_url.rstrip("/") + "/api/revalidate",
                    json={"paths": paths + ["/sitemap.xml", "/llms.txt"]},
                    headers={"x-revalidate-secret": settings.revalidate_secret},
                )
            result["revalidated"] = r.status_code < 300
        except httpx.HTTPError as e:
            log.warning("falha ao revalidar portal: %s", e)

    base = settings.public_base_url.rstrip("/")
    if demo:
        result["indexnow"] = "skipped: dados de demonstração"
    elif not settings.indexnow_key:
        result["indexnow"] = "skipped: INDEXNOW_KEY não configurada"
    elif not _is_public_host(base):
        result["indexnow"] = "skipped: PUBLIC_BASE_URL não é um domínio público"
    else:
        body = {
            "host": urlparse(base).hostname,
            "key": settings.indexnow_key,
            "keyLocation": f"{base}/indexnow-key.txt",
            "urlList": [base + p for p in paths][:MAX_URLS],
        }
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.post(INDEXNOW_ENDPOINT, json=body)
            # 200/202 = aceito; 403 = chave não confere; 422 = URL fora do host; 429 = envios demais
            result["indexnow"] = f"HTTP {r.status_code}"
        except httpx.HTTPError as e:
            result["indexnow"] = f"erro: {e}"

    now = datetime.now(UTC)
    if changed_at is not None:
        ca = changed_at if changed_at.tzinfo else changed_at.replace(tzinfo=UTC)
        result["lag_seconds"] = round((now - ca).total_seconds(), 1)
    try:
        async with session_scope() as s:
            s.add(IndexPing(
                hub_slug=hub_slug, reason=reason, urls=paths, changed_fields=changed or {}, revalidated=result["revalidated"],
                indexnow=str(result["indexnow"])[:200], lag_seconds=result.get("lag_seconds"),
            ))
    except Exception:
        log.exception("falha ao registrar ping")
    return result
