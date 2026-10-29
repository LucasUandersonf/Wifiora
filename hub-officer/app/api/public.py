"""Superfície pública do Hub Semântico — o que pessoas, buscadores e assistentes de IA consomem.

Dois modos:
  * Sem PORTAL_URL: o próprio FastAPI serve o site (HTML SSR, zero JS).
  * Com PORTAL_URL: o portal Next.js serve o site; as páginas HTML daqui redirecionam (301) para lá,
    e o Next.js consome os payloads de /api/public/pages/... (mesmo JSON-LD, mesmo conteúdo).
"""

from __future__ import annotations

import re
import time
from collections import defaultdict, deque
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.config import get_settings
from app.db import session_scope
from app.models import CorrectionRequest, Entity, Hub, Lead
from app.web.institutional import FOOTER_LINKS, institutional_page, institutional_slugs
from app.web.render import TEMPLATES, entity_payload, hub_payload, load_hub, render_entity_page, render_hub_page, site_context

router = APIRouter(tags=["public"])

CACHE = {"Cache-Control": "public, max-age=300, stale-while-revalidate=3600"}
AI_CRAWLERS = ["GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot", "Claude-SearchBot", "PerplexityBot", "Google-Extended", "Googlebot", "Bingbot"]
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ------------------------------------------------------------------ utilidades
def _portal_redirect(path: str) -> RedirectResponse | None:
    portal = get_settings().portal_url
    return RedirectResponse(portal.rstrip("/") + path, status_code=301) if portal else None


def _hide_demo() -> bool:
    """Em produção, hubs de demonstração ficam fora do sitemap, do llms.txt e da listagem."""
    return get_settings().app_env == "production"


async def _published_hubs() -> list[Hub]:
    async with session_scope() as s:
        q = select(Hub).where(Hub.status == "published").order_by(Hub.title)
        if _hide_demo():
            q = q.where(Hub.demo_data.is_(False))
        return list((await s.execute(q)).scalars())


class _RateLimiter:
    """Limite simples por IP e tipo de formulário (proteção básica contra spam/abuso)."""

    def __init__(self, limit: int, window_s: int) -> None:
        self.limit, self.window = limit, window_s
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        q = self.hits[key]
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        return True


LIMITER = _RateLimiter(limit=5, window_s=600)


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() or (request.client.host if request.client else "?")


# ------------------------------------------------------------------ HTML (fallback SSR)
@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def home() -> Response:
    return _portal_redirect("/") or await hubs_index()


@router.get("/hubs", response_class=HTMLResponse)
async def hubs_index() -> Response:
    if r := _portal_redirect("/hubs"):
        return r
    html = TEMPLATES.get_template("hubs.html").render(hubs=await _published_hubs(), **site_context())
    return HTMLResponse(html, headers=CACHE)


@router.get("/hub/{slug}", response_class=HTMLResponse)
async def hub_page(slug: str) -> Response:
    if r := _portal_redirect(f"/hub/{slug}"):
        return r
    html = await render_hub_page(slug)
    if html is None:
        raise HTTPException(404, "hub não encontrado")
    return HTMLResponse(html, headers=CACHE)


@router.get("/hub/{slug}/data.jsonld")
async def hub_jsonld(slug: str) -> Response:
    data = await hub_payload(slug)
    if data is None:
        raise HTTPException(404, "hub não encontrado")
    return JSONResponse(data["jsonld"], media_type="application/ld+json", headers=CACHE)


@router.get("/hub/{slug}/{entity_slug}", response_class=HTMLResponse)
async def entity_page(slug: str, entity_slug: str, enviado: str | None = None) -> Response:
    if r := _portal_redirect(f"/hub/{slug}/{entity_slug}"):
        return r
    html = await render_entity_page(slug, entity_slug, sent=enviado)
    if html is None:
        raise HTTPException(404, "empresa não encontrada")
    return HTMLResponse(html, headers={"Cache-Control": "no-store"} if enviado else CACHE)


def _make_institutional_route(slug: str) -> None:
    async def handler(request: Request, enviado: str | None = None) -> Response:
        if r := _portal_redirect(f"/{slug}"):
            return r
        page = institutional_page(slug)
        html = TEMPLATES.get_template("page.html").render(page=page, sent=enviado, prefill=dict(request.query_params), **site_context())
        return HTMLResponse(html, headers={"Cache-Control": "no-store"} if enviado else CACHE)

    router.add_api_route(f"/{slug}", handler, methods=["GET"], response_class=HTMLResponse, name=f"page_{slug}")


for _slug in institutional_slugs():
    _make_institutional_route(_slug)


# ------------------------------------------------------------------ formulários
class LeadIn(BaseModel):
    hub_slug: str = Field(max_length=120)
    entity_slug: str = Field(max_length=160)
    name: str = Field(min_length=2, max_length=160)
    email: str = Field(max_length=200)
    phone: str | None = Field(default=None, max_length=40)
    company: str | None = Field(default=None, max_length=200)
    company_size: str | None = Field(default=None, max_length=40)
    message: str | None = Field(default=None, max_length=2000)
    consent: bool = False
    website: str | None = None  # honeypot


class CorrectionIn(BaseModel):
    hub_slug: str | None = Field(default=None, max_length=120)
    entity_slug: str | None = Field(default=None, max_length=160)
    name: str = Field(min_length=2, max_length=160)
    email: str = Field(max_length=200)
    company: str | None = Field(default=None, max_length=200)
    message: str = Field(min_length=5, max_length=4000)
    evidence_url: str | None = Field(default=None, max_length=500)
    website: str | None = None  # honeypot


async def _read_body(request: Request) -> tuple[dict[str, Any], bool]:
    if request.headers.get("content-type", "").startswith("application/json"):
        return await request.json(), True
    form = await request.form()
    data: dict[str, Any] = {k: (str(v).strip() or None) for k, v in form.items()}
    data["consent"] = data.get("consent") in ("1", "on", "true")
    return data, False


async def _save_lead(body: LeadIn, request: Request) -> None:
    if body.website:
        return  # robô preencheu o honeypot: finge sucesso, não grava
    if not EMAIL_RE.match(body.email):
        raise HTTPException(422, "e-mail inválido")
    if not body.consent:
        raise HTTPException(422, "é preciso autorizar o envio dos dados ao fornecedor")
    if not LIMITER.allow(f"lead:{_client_ip(request)}"):
        raise HTTPException(429, "muitos envios; tente novamente em alguns minutos")
    loaded = await load_hub(body.hub_slug)
    ent = next((e for e in (loaded[1] if loaded else []) if e.slug == body.entity_slug), None)
    if ent is None:
        raise HTTPException(404, "empresa não encontrada")
    async with session_scope() as s:
        s.add(Lead(**body.model_dump(exclude={"website"}), entity_name=ent.name))
    office = request.app.state.office
    await office.emit("lead", entity=ent.name, hub=body.hub_slug)
    await office.alert("info", "portal", f"Novo pedido de demonstração para {ent.name} ({body.company or 'empresa não informada'}).")


async def _save_correction(body: CorrectionIn, request: Request) -> None:
    if body.website:
        return
    if not EMAIL_RE.match(body.email):
        raise HTTPException(422, "e-mail inválido")
    if body.evidence_url and not body.evidence_url.startswith(("http://", "https://")):
        raise HTTPException(422, "o link da fonte precisa começar com http:// ou https://")
    if not LIMITER.allow(f"correction:{_client_ip(request)}"):
        raise HTTPException(429, "muitos envios; tente novamente em alguns minutos")
    async with session_scope() as s:
        s.add(CorrectionRequest(**body.model_dump(exclude={"website"})))
    office = request.app.state.office
    await office.emit("correction", hub=body.hub_slug, entity=body.entity_slug)
    await office.alert("warning", "portal", f"Pedido de correção recebido{f' para {body.entity_slug}' if body.entity_slug else ''}: {body.message[:200]}")


@router.post("/forms/lead", include_in_schema=False)
async def form_lead(request: Request) -> Response:
    data, _ = await _read_body(request)
    body = LeadIn.model_validate(data)
    await _save_lead(body, request)
    return RedirectResponse(f"/hub/{body.hub_slug}/{body.entity_slug}?enviado=lead#demonstracao", status_code=303)


@router.post("/forms/correction", include_in_schema=False)
async def form_correction(request: Request) -> Response:
    data, _ = await _read_body(request)
    await _save_correction(CorrectionIn.model_validate(data), request)
    return RedirectResponse("/correcoes?enviado=correction", status_code=303)


@router.post("/api/public/leads")
async def api_lead(body: LeadIn, request: Request) -> dict[str, Any]:
    await _save_lead(body, request)
    return {"ok": True}


@router.post("/api/public/corrections")
async def api_correction(body: CorrectionIn, request: Request) -> dict[str, Any]:
    await _save_correction(body, request)
    return {"ok": True}


# ------------------------------------------------------------------ payloads para o portal Next.js
@router.get("/api/public/site")
async def api_site() -> dict[str, Any]:
    ctx = site_context()
    hubs = await _published_hubs()
    return {
        "brand": ctx["brand"],
        "base_url": ctx["base_url"],
        "footer_links": [{"label": label, "href": href} for label, href in FOOTER_LINKS],
        "hubs": [{"slug": h.slug, "title": h.title, "niche": h.niche, "description": h.description, "demo_data": h.demo_data, "updated_at": h.updated_at} for h in hubs],
        "institutional": institutional_slugs(),
    }


@router.get("/api/public/pages/hub/{slug}")
async def api_hub_page(slug: str) -> dict[str, Any]:
    data = await hub_payload(slug)
    if data is None:
        raise HTTPException(404, "hub não encontrado")
    return data


@router.get("/api/public/pages/entity/{slug}/{entity_slug}")
async def api_entity_page(slug: str, entity_slug: str) -> dict[str, Any]:
    data = await entity_payload(slug, entity_slug)
    if data is None:
        raise HTTPException(404, "empresa não encontrada")
    return data


@router.get("/api/public/pages/institutional/{slug}")
async def api_institutional(slug: str) -> dict[str, Any]:
    page = institutional_page(slug)
    if page is None:
        raise HTTPException(404, "página não encontrada")
    return page


# ------------------------------------------------------------------ dados abertos
@router.get("/api/public/hubs")
async def api_hubs() -> list[dict[str, Any]]:
    return [{"slug": h.slug, "title": h.title, "niche": h.niche, "updated_at": h.updated_at, "demo_data": h.demo_data} for h in await _published_hubs()]


@router.get("/api/public/hubs/{slug}")
async def api_hub(slug: str) -> dict[str, Any]:
    """Dados abertos (CC BY 4.0) de um hub. Acesso em volume e com histórico: API v1 com chave."""
    loaded = await load_hub(slug)
    if loaded is None:
        raise HTTPException(404, "hub não encontrado")
    hub, ents = loaded
    return {
        "hub": {"slug": hub.slug, "title": hub.title, "niche": hub.niche, "updated_at": hub.updated_at, "demo_data": hub.demo_data, "license": "CC-BY-4.0"},
        "entities": [
            {
                "slug": e.slug, "name": e.name, "type": e.schema_type, "attributes": e.attributes, "sources": e.sources,
                "grounding_ratio": e.grounding_ratio, "verified_at": e.verified_at, "human_reviewed": bool(e.human_reviewed_at),
                "version": e.version, "updated_at": e.updated_at,
            }
            for e in ents
        ],
    }


# ------------------------------------------------------------------ arquivos para buscadores e IAs
@router.get("/llms.txt", response_class=PlainTextResponse)
async def llms_txt() -> PlainTextResponse:
    st = get_settings()
    base = st.public_base_url.rstrip("/")
    lines = [
        f"# {st.brand_name}",
        "",
        "> Hub de dados estruturados e verificados sobre o mercado B2B brasileiro. Cada valor tem fonte oficial citada,",
        "> data de verificação e histórico de versões. Licença CC BY 4.0. Metodologia: " + f"{base}/metodologia",
        "",
        "## Hubs",
    ]
    for h in await _published_hubs():
        flag = " (dados de demonstração)" if h.demo_data else ""
        lines.append(f"- [{h.title}]({base}/hub/{h.slug}): {h.niche}{flag}. JSON-LD: {base}/hub/{h.slug}/data.jsonld")
    lines += [
        "",
        "## Dados em lote (CC BY 4.0)",
        f"- [Catálogo DataCatalog]({base}/data/catalog.jsonld)",
        f"- [Grafo de conhecimento completo]({base}/knowledge-graph.jsonld): produtos, empresas, conceitos e integrações com @id estáveis",
        f"- [Todos os produtos em JSONL]({base}/data/all.jsonl): um bloco autocontido por linha, com fonte e data",
        f"- [Conteúdo completo em texto]({base}/llms-full.txt)",
        f"- [Conceitos e empresas]({base}/conceitos)",
        "- Por hub: /hub/<slug>/data.json, data.jsonl, data.csv, data.md, data.jsonld",
    ]
    lines += ["", "## Sobre os dados", f"- [Metodologia]({base}/metodologia)", f"- [Política editorial]({base}/politica-editorial)", f"- [Índice JSON]({base}/api/public/hubs)"]
    return PlainTextResponse("\n".join(lines) + "\n", headers=CACHE)


@router.get("/sitemap.xml")
async def sitemap() -> Response:
    base = get_settings().public_base_url.rstrip("/")
    urls: list[tuple[str, str | None]] = [(f"{base}/", None), (f"{base}/hubs", None), (f"{base}/dados", None), (f"{base}/conceitos", None), (f"{base}/diagnostico-gratis", None)]
    urls += [(f"{base}/{s}", None) for s in institutional_slugs()]
    from app.core.knowledge import load_site, org_index

    urls += [(f"{base}/empresa/{slug}", None) for slug in org_index(await load_site())]
    async with session_scope() as s:
        for h in await _published_hubs():
            urls.append((f"{base}/hub/{h.slug}", h.updated_at.date().isoformat()))
            for e in (await s.execute(select(Entity).where(Entity.hub_id == h.id, Entity.status == "published"))).scalars():
                urls.append((f"{base}/hub/{h.slug}/{e.slug}", (e.verified_at or e.updated_at).date().isoformat()))
    body = "".join(f"<url><loc>{u}</loc>{f'<lastmod>{d}</lastmod>' if d else ''}</url>" for u, d in urls)
    xml = f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>'
    return Response(xml, media_type="application/xml", headers=CACHE)


@router.get("/robots.txt", response_class=PlainTextResponse)
async def robots() -> PlainTextResponse:
    base = get_settings().public_base_url.rstrip("/")
    rules = "".join(f"User-agent: {bot}\nAllow: /\nDisallow: /api/office/\nDisallow: /api/control/\n\n" for bot in AI_CRAWLERS)
    private = "Disallow: /api/office/\nDisallow: /api/control/\nDisallow: /api/v1/\nDisallow: /dashboard\nDisallow: /office\nDisallow: /radar\nDisallow: /forms/\nDisallow: /relatorio/\nDisallow: /proposta/\nDisallow: /cliente/\nDisallow: /descadastrar/\nDisallow: /webhooks/\n"
    return PlainTextResponse(f"{rules}User-agent: *\n{private}\nSitemap: {base}/sitemap.xml\n")


@router.get("/indexnow-key.txt", response_class=PlainTextResponse, include_in_schema=False)
async def indexnow_key() -> PlainTextResponse:
    key = get_settings().indexnow_key
    if not key:
        raise HTTPException(404, "IndexNow não configurado")
    return PlainTextResponse(key)
