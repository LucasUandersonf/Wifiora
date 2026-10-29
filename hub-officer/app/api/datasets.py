"""Dados para IAs: arquivos em lote (RAG direto), grafo de conhecimento e páginas de empresa/conceitos.

Incluído ANTES de `public.router`, porque `/hub/{slug}/{entity_slug}` capturaria `/hub/x/data.csv`.
Todos os arquivos: CORS aberto para GET, ETag/Last-Modified com 304 e licença CC BY 4.0 no cabeçalho.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from email.utils import format_datetime
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from pydantic import BaseModel, Field

from app.api.public import _portal_redirect
from app.config import get_settings
from app.core import bots
from app.core import knowledge as kg
from app.web.render import TEMPLATES, jsonld_script, load_hub, site_context

router = APIRouter(tags=["dados para IAs"])

FILE_HEADERS = {
    "Cache-Control": "public, max-age=900, stale-while-revalidate=86400",
    "Access-Control-Allow-Origin": "*",
    "Link": '<https://creativecommons.org/licenses/by/4.0/>; rel="license"',
    "X-Robots-Tag": "all",
}
PAGE_CACHE = {"Cache-Control": "public, max-age=300, stale-while-revalidate=3600"}


def _file(request: Request, body: str | bytes, media_type: str, last_modified: Any = None) -> Response:
    raw = body.encode() if isinstance(body, str) else body
    etag = '"' + hashlib.sha256(raw).hexdigest()[:32] + '"'
    headers = {**FILE_HEADERS, "ETag": etag}
    if last_modified is not None:
        headers["Last-Modified"] = format_datetime(last_modified if last_modified.tzinfo else last_modified.replace(tzinfo=__import__("datetime").UTC), usegmt=True)
    if etag in [t.strip() for t in request.headers.get("if-none-match", "").split(",")]:
        return Response(status_code=304, headers=headers)
    return Response(raw, media_type=media_type, headers=headers)


def _json(doc: Any) -> str:
    return json.dumps(doc, ensure_ascii=False, separators=(",", ":"), default=str)


async def _hub(slug: str):
    loaded = await load_hub(slug)
    if loaded is None or (kg.hide_demo() and loaded[0].demo_data):
        raise HTTPException(404, "hub não encontrado")
    return loaded


# ------------------------------------------------------------------ arquivos por hub
@router.get("/hub/{slug}/data.json")
async def hub_data_json(slug: str, request: Request) -> Response:
    h, ents = await _hub(slug)
    return _file(request, _json(kg.hub_json(h, ents)), "application/json", max((e.updated_at for e in ents), default=h.updated_at))


@router.get("/hub/{slug}/data.jsonl")
async def hub_data_jsonl(slug: str, request: Request) -> Response:
    h, ents = await _hub(slug)
    return _file(request, kg.hub_jsonl(h, ents), "application/x-ndjson; charset=utf-8", max((e.updated_at for e in ents), default=h.updated_at))


@router.get("/hub/{slug}/data.csv")
async def hub_data_csv(slug: str, request: Request) -> Response:
    h, ents = await _hub(slug)
    return _file(request, "﻿" + kg.hub_csv(h, ents), "text/csv; charset=utf-8", max((e.updated_at for e in ents), default=h.updated_at))


@router.get("/hub/{slug}/data.md")
async def hub_data_md(slug: str, request: Request) -> Response:
    h, ents = await _hub(slug)
    return _file(request, kg.hub_markdown(h, ents), "text/markdown; charset=utf-8", max((e.updated_at for e in ents), default=h.updated_at))


# ------------------------------------------------------------------ arquivos do site inteiro
@router.get("/data/catalog.jsonld")
async def catalog(request: Request) -> Response:
    site = await kg.load_site()
    return _file(request, _json(await kg.catalog_jsonld()), "application/ld+json", site.last_modified)


@router.get("/data/all.jsonl")
async def all_jsonl(request: Request) -> Response:
    site = await kg.load_site()
    return _file(request, await kg.all_jsonl(site), "application/x-ndjson; charset=utf-8", site.last_modified)


@router.get("/knowledge-graph.jsonld")
async def knowledge_graph(request: Request) -> Response:
    site = await kg.load_site()
    return _file(request, _json(await kg.knowledge_graph(site)), "application/ld+json", site.last_modified)


@router.get("/llms-full.txt")
async def llms_full(request: Request) -> Response:
    site = await kg.load_site()
    return _file(request, await kg.llms_full(site), "text/plain; charset=utf-8", site.last_modified)


# ------------------------------------------------------------------ beacon de robôs (portal Next.js)
class BotBeacon(BaseModel):
    user_agent: str = Field(max_length=500)
    path: str = Field(max_length=300)


@router.post("/api/public/bot-hit", include_in_schema=False)
async def bot_hit(body: BotBeacon, x_beacon_secret: str | None = Header(default=None)) -> dict[str, Any]:
    """O portal avisa quando um robô de IA leu uma página. Protegido pelo mesmo segredo da revalidação."""
    secret = get_settings().revalidate_secret
    if not secret or not hmac.compare_digest(x_beacon_secret or "", secret):
        raise HTTPException(401, "segredo inválido")
    bot = bots.COUNTER.add(body.user_agent, body.path)
    if bot and bots.COUNTER.due():
        await bots.COUNTER.flush()
    return {"bot": bot}


# ------------------------------------------------------------------ payloads para o portal
async def data_payload() -> dict[str, Any]:
    site = await kg.load_site()
    base = kg.base_url()
    return {
        "license": kg.LICENSE_ID,
        "site_files": [
            {"name": "Catálogo (DataCatalog)", "url": f"{base}/data/catalog.jsonld", "format": "JSON-LD"},
            {"name": "Grafo de conhecimento completo", "url": f"{base}/knowledge-graph.jsonld", "format": "JSON-LD"},
            {"name": "Todos os produtos, um bloco por linha", "url": f"{base}/data/all.jsonl", "format": "JSONL"},
            {"name": "Conteúdo completo em texto", "url": f"{base}/llms-full.txt", "format": "TXT"},
        ],
        "hubs": [
            {
                "slug": h.slug, "title": h.title, "records": len(ents), "demo_data": h.demo_data,
                "updated_at": kg._iso(max((e.updated_at for e in ents), default=h.updated_at)),
                "files": [{"name": d["name"], "url": d["contentUrl"], "format": d["encodingFormat"]} for d in kg.distributions(h)],
            }
            for h, ents in site.hubs
        ],
        "jsonld": await kg.catalog_jsonld(),
    }


@router.get("/api/public/pages/org/{slug}")
async def api_org(slug: str) -> dict[str, Any]:
    data = await kg.org_payload(slug)
    if data is None:
        raise HTTPException(404, "empresa não encontrada")
    return data


@router.get("/api/public/pages/concepts")
async def api_concepts() -> dict[str, Any]:
    return await kg.concepts_payload()


@router.get("/api/public/pages/data")
async def api_data() -> dict[str, Any]:
    return await data_payload()


# ------------------------------------------------------------------ HTML (fallback SSR)
@router.get("/relatorio/{token}.pdf", include_in_schema=False)
async def diagnosis_pdf(token: str, request: Request) -> Response:
    """PDF comercial do relatório (link secreto)."""
    from sqlalchemy import select

    from app.db import session_scope
    from app.models import Diagnosis
    from app.web.pdf import render

    async with session_scope() as s:
        d = (await s.execute(select(Diagnosis).where(Diagnosis.token == token))).scalar_one_or_none()
    if d is None or d.status != "done":
        raise HTTPException(404, "relatório não encontrado ou ainda em andamento")
    pdf = render(d, agency=request.app.state.office.settings.agency_name)
    name = re.sub(r"[^a-z0-9]+", "-", d.brand.lower()).strip("-") or "relatorio"
    return Response(pdf, media_type="application/pdf", headers={**PDF_HEADERS, "Content-Disposition": f'inline; filename="visibilidade-ia-{name}.pdf"'})


PDF_HEADERS = {"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow"}


@router.get("/relatorio/{token}", response_class=HTMLResponse, include_in_schema=False)
async def diagnosis_report(token: str) -> Response:
    """Relatório do Diagnóstico de Visibilidade em IA (link secreto, não indexado)."""
    from sqlalchemy import select

    from app.core.diagnosis import report_context
    from app.db import session_scope
    from app.models import Diagnosis

    async with session_scope() as s:
        d = (await s.execute(select(Diagnosis).where(Diagnosis.token == token))).scalar_one_or_none()
    if d is None:
        raise HTTPException(404, "relatório não encontrado")
    html = TEMPLATES.get_template("diagnosis.html").render(**report_context(d), **site_context())
    return HTMLResponse(html, headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow"})


@router.get("/empresa/{slug}", response_class=HTMLResponse)
async def org_page(slug: str) -> Response:
    if r := _portal_redirect(f"/empresa/{slug}"):
        return r
    data = await kg.org_payload(slug)
    if data is None:
        raise HTTPException(404, "empresa não encontrada")
    return HTMLResponse(TEMPLATES.get_template("org.html").render(**data, jsonld_text=jsonld_script(data["jsonld"]), **site_context()), headers=PAGE_CACHE)


@router.get("/conceitos", response_class=HTMLResponse)
async def concepts_page() -> Response:
    if r := _portal_redirect("/conceitos"):
        return r
    data = await kg.concepts_payload()
    return HTMLResponse(TEMPLATES.get_template("concepts.html").render(**data, jsonld_text=jsonld_script(data["jsonld"]), **site_context()), headers=PAGE_CACHE)


@router.get("/dados", response_class=HTMLResponse)
async def data_page() -> Response:
    if r := _portal_redirect("/dados"):
        return r
    data = await data_payload()
    return HTMLResponse(TEMPLATES.get_template("data.html").render(**data, jsonld_text=jsonld_script(data["jsonld"]), **site_context()), headers=PAGE_CACHE)
