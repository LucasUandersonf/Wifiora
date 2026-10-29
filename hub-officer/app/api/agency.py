"""Páginas públicas da agência: pedido de diagnóstico grátis, proposta, descadastro, página do cliente e webhook de pagamento."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select

from app.api.public import LIMITER, _client_ip
from app.core import mailer, sales
from app.db import session_scope
from app.models import Client, Diagnosis, Prospect
from app.web.render import TEMPLATES, site_context

log = logging.getLogger(__name__)
router = APIRouter(tags=["agência"])
PRIVATE = {"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow"}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _ctx(request: Request) -> dict[str, Any]:
    st = request.app.state.office.settings
    return {**site_context(), "agency": st.agency_name, "prices": {"diagnostico": st.price_diagnostico_brl, "mensal": st.price_mensal_brl}}


def _brl(v: float) -> str:
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


TEMPLATES.filters["brl"] = _brl


@router.get("/diagnostico-gratis", response_class=HTMLResponse)
async def landing(request: Request, enviado: str | None = None) -> Response:
    return HTMLResponse(TEMPLATES.get_template("agency_landing.html").render(sent=enviado, **_ctx(request)), headers={"Cache-Control": "no-store"})


@router.post("/diagnostico-gratis", include_in_schema=False)
async def landing_post(request: Request) -> Response:
    form = {k: str(v).strip() for k, v in (await request.form()).items()}
    if form.get("website"):  # honeypot
        return RedirectResponse("/diagnostico-gratis?enviado=1", status_code=303)
    if not EMAIL_RE.match(form.get("email", "")) or len(form.get("company", "")) < 2 or len(form.get("segment", "")) < 3:
        raise HTTPException(422, "preencha empresa, segmento e um e-mail válido")
    if form.get("consent") not in ("1", "on", "true"):
        raise HTTPException(422, "é preciso autorizar o envio do diagnóstico por e-mail")
    if not LIMITER.allow(f"diag:{_client_ip(request)}"):
        raise HTTPException(429, "muitos pedidos; tente novamente mais tarde")
    office = request.app.state.office
    await sales.inbound(office, company=form["company"], site=form.get("site", ""), segment=form["segment"], city=form.get("city", ""), email=form["email"], name=form.get("name", ""))
    await office.alert("info", sales.PROSPECTOR, f"Pedido de diagnóstico pelo site: {form['company']}.")
    return RedirectResponse("/diagnostico-gratis?enviado=1", status_code=303)


async def _prospect(token: str) -> Prospect:
    async with session_scope() as s:
        p = (await s.execute(select(Prospect).where(Prospect.token == token))).scalar_one_or_none()
    if p is None:
        raise HTTPException(404, "link inválido")
    return p


@router.get("/proposta/{token}", response_class=HTMLResponse, include_in_schema=False)
async def proposal(token: str, request: Request) -> Response:
    p = await _prospect(token)
    office = request.app.state.office
    async with session_scope() as s:
        d = await s.get(Diagnosis, p.diagnosis_id) if p.diagnosis_id else None
    links = {"diagnostico": sales.payment_link(office, p, "diagnostico"), "mensal": sales.payment_link(office, p, "mensal")}
    html = TEMPLATES.get_template("agency_proposal.html").render(p=p, d=d, links=links, **_ctx(request))
    return HTMLResponse(html, headers=PRIVATE)


@router.get("/descadastrar/{token}", response_class=HTMLResponse, include_in_schema=False)
async def unsubscribe_page(token: str, request: Request) -> Response:
    p = await _prospect(token)
    return HTMLResponse(TEMPLATES.get_template("agency_unsubscribe.html").render(p=p, done=False, **_ctx(request)), headers=PRIVATE)


@router.post("/descadastrar/{token}", response_class=HTMLResponse, include_in_schema=False)
async def unsubscribe(token: str, request: Request) -> Response:
    """Também atende ao "List-Unsubscribe-Post" (descadastro com um clique do provedor de e-mail)."""
    p = await _prospect(token)
    await mailer.suppress(p.email, "pediu descadastro")
    async with session_scope() as s:
        row = await s.get(Prospect, p.id)
        if row and row.status != "cliente":
            row.status = "descadastrado"
    return HTMLResponse(TEMPLATES.get_template("agency_unsubscribe.html").render(p=p, done=True, **_ctx(request)), headers=PRIVATE)


@router.get("/cliente/{token}", response_class=HTMLResponse, include_in_schema=False)
async def client_page(token: str, request: Request) -> Response:
    async with session_scope() as s:
        c = (await s.execute(select(Client).where(Client.token == token))).scalar_one_or_none()
        if c is None:
            raise HTTPException(404, "link inválido")
        reports = list((await s.execute(select(Diagnosis).where(Diagnosis.id.in_(c.diagnoses or [])).order_by(Diagnosis.created_at))).scalars())
    kit = c.kit or {}
    html = TEMPLATES.get_template("agency_client.html").render(
        c=c, kit=kit, reports=reports,
        org_ld=json.dumps(kit.get("organization_jsonld") or {}, ensure_ascii=False, indent=2),
        faq_ld=json.dumps(kit.get("faq_jsonld") or {}, ensure_ascii=False, indent=2), **_ctx(request),
    )
    return HTMLResponse(html, headers=PRIVATE)


@router.post("/webhooks/stripe", include_in_schema=False)
async def stripe_webhook(request: Request) -> dict[str, Any]:
    office = request.app.state.office
    secret = office.settings.stripe_webhook_secret
    payload = await request.body()
    if not secret or not sales.verify_stripe(payload, request.headers.get("stripe-signature", ""), secret):
        raise HTTPException(400, "assinatura inválida")
    result = await sales.handle_stripe(office, json.loads(payload))
    log.info("webhook stripe: %s", result)
    return {"ok": True, "result": result}
