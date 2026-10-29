"""Páginas públicas do boletim: assinatura (opt-in duplo), confirmação, saída, arquivo de edições e webhook do provedor."""

from __future__ import annotations

import hmac
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select

from app.api.agency import EMAIL_RE
from app.api.public import LIMITER, _client_ip
from app.core import newsletter as nl
from app.db import session_scope
from app.models import Edition
from app.web.render import TEMPLATES

router = APIRouter(tags=["boletim"])
PRIVATE = {"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow"}
PUBLIC = {"Cache-Control": "public, max-age=600"}


def _page(request: Request, **ctx: Any) -> str:
    st = request.app.state.office.settings
    base = nl.base_url(request.app.state.office)
    return TEMPLATES.get_template("newsletter_page.html").render(
        name=st.newsletter_name, tagline=st.newsletter_tagline, base=base, consent=nl.CONSENT_TEXT.format(name=st.newsletter_name),
        page_title=ctx.pop("page_title", st.newsletter_name), page_description=ctx.pop("page_description", st.newsletter_tagline), **ctx)


async def _published() -> list[Edition]:
    async with session_scope() as s:
        return list((await s.execute(select(Edition).where(Edition.status.in_(("enviado", "enviando"))).order_by(Edition.number.desc()))).scalars())


@router.get("/boletim", response_class=HTMLResponse)
async def signup_page(request: Request, enviado: str | None = None) -> Response:
    eds = await _published()
    html = _page(request, mode="signup", sent=enviado, editions=eds, canonical=f"{nl.base_url(request.app.state.office)}/boletim",
                 robots="noindex,nofollow" if enviado else None)
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


@router.post("/boletim", include_in_schema=False)
async def signup_post(request: Request) -> Response:
    form = {k: str(v).strip() for k, v in (await request.form()).items()}
    if form.get("website"):  # honeypot
        return RedirectResponse("/boletim?enviado=seu%20e-mail", status_code=303)
    email = form.get("email", "").lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(422, "informe um e-mail válido")
    if form.get("consent") not in ("1", "on", "true"):
        raise HTTPException(422, "é preciso marcar a autorização para receber o boletim")
    if not LIMITER.allow(f"boletim:{_client_ip(request)}"):
        raise HTTPException(429, "muitas tentativas; tente novamente mais tarde")
    await nl.subscribe(request.app.state.office, email=email, name=form.get("name", ""), role=form.get("role", ""),
                       organization=form.get("organization", ""), source="site", ip=_client_ip(request))
    return RedirectResponse(f"/boletim?enviado={email}", status_code=303)


# GET só mostra o botão: leitores de link (antivírus do Outlook) abrem URLs sozinhos e não podem confirmar/descadastrar por alguém.
@router.get("/boletim/confirmar/{token}", response_class=HTMLResponse, include_in_schema=False)
async def confirm_page(token: str, request: Request) -> Response:
    return HTMLResponse(_page(request, mode="message", heading="Confirmar inscrição", message="Clique para confirmar que quer receber o boletim neste e-mail.",
                              form_action=f"/boletim/confirmar/{token}", button="Confirmar inscrição", robots="noindex,nofollow"), headers=PRIVATE)


@router.post("/boletim/confirmar/{token}", response_class=HTMLResponse, include_in_schema=False)
async def confirm_post(token: str, request: Request) -> Response:
    sub = await nl.confirm(token)
    if sub is None:
        raise HTTPException(404, "link inválido")
    ok = sub.status == "ativo"
    return HTMLResponse(_page(request, mode="message", heading="Inscrição confirmada" if ok else "Inscrição", ok=ok, robots="noindex,nofollow",
                              message=f"Pronto: {sub.email} vai receber a próxima edição." if ok else "Esta inscrição não está ativa."), headers=PRIVATE)


@router.get("/boletim/sair/{token}", response_class=HTMLResponse, include_in_schema=False)
async def unsubscribe_page(token: str, request: Request) -> Response:
    return HTMLResponse(_page(request, mode="message", heading="Cancelar inscrição", message="Não quer mais receber o boletim?",
                              form_action=f"/boletim/sair/{token}", button="Cancelar inscrição", robots="noindex,nofollow"), headers=PRIVATE)


@router.post("/boletim/sair/{token}", response_class=HTMLResponse, include_in_schema=False)
async def unsubscribe_post(token: str, request: Request) -> Response:
    """Também atende o descadastro de um clique do Gmail/Outlook (List-Unsubscribe-Post)."""
    sub = await nl.unsubscribe(token)
    if sub is None:
        raise HTTPException(404, "link inválido")
    return HTMLResponse(_page(request, mode="message", heading="Inscrição cancelada", ok=True, robots="noindex,nofollow",
                              message=f"{sub.email} não receberá mais o boletim."), headers=PRIVATE)


@router.post("/webhooks/boletim", include_in_schema=False)
async def provider_webhook(request: Request, token: str = "") -> dict[str, Any]:
    """Bounces, reclamações e descadastros do provedor de envio (Brevo/SES/SendGrid via adaptador simples)."""
    secret = request.app.state.office.settings.newsletter_webhook_secret
    given = token or request.headers.get("x-webhook-token", "")
    if not secret or not hmac.compare_digest(given, secret):
        raise HTTPException(401, "token inválido")
    try:
        payload = json.loads(await request.body() or b"{}")
    except ValueError as e:
        raise HTTPException(400, "corpo inválido") from e
    events = payload if isinstance(payload, list) else [payload]
    return {"processados": await nl.provider_event([e for e in events if isinstance(e, dict)])}


@router.get("/boletim/{slug}", response_class=HTMLResponse)
async def edition_page(slug: str, request: Request) -> Response:
    """Versão web da edição (pública e indexável: cada edição também vira conteúdo de autoridade para buscadores e IAs)."""
    office = request.app.state.office
    async with session_scope() as s:
        e = (await s.execute(select(Edition).where(Edition.slug == slug))).scalar_one_or_none()
    if e is None or e.status not in ("enviado", "enviando"):
        raise HTTPException(404, "edição não encontrada")
    url = f"{nl.base_url(office)}/boletim/{slug}"
    ld = {"@context": "https://schema.org", "@type": "NewsArticle", "headline": e.subject, "description": e.preheader, "inLanguage": "pt-BR", "url": url,
          "datePublished": (e.sent_at or e.approved_at or e.created_at).date().isoformat(),
          "isPartOf": {"@type": "Periodical", "name": office.settings.newsletter_name, "url": f"{nl.base_url(office)}/boletim"},
          "publisher": {"@type": "Organization", "name": "Insighta"}}
    ld_json = json.dumps(ld, ensure_ascii=False).replace("</", "<\\/")
    head_extra = f'<link rel="canonical" href="{url}">\n<script type="application/ld+json">{ld_json}</script>\n</head>'
    html = TEMPLATES.get_template("newsletter_email.html").render(**nl.render_context(office, e, web=True)).replace("</head>", head_extra, 1)
    return HTMLResponse(html, headers=PUBLIC)
