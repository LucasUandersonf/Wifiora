"""Comercial automático: o funil inteiro sem operação humana (modo demonstração, e-mails simulados)."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.core import mailer, sales
from app.db import session_scope
from app.models import AgentState, Client, EmailLog, Prospect, RevenueEntry

H = {"X-Founder-Token": "test-token"}


def test_guards():
    assert sales.corporate_emails("fale: contato@loja.com.br, joao@gmail.com, vendas@sp.loja.com.br", "loja.com.br") == ["contato@loja.com.br", "vendas@sp.loja.com.br"]
    assert sales.blocked("produto.mercadolivre.com.br") and not sales.blocked("lojaboa.com.br")
    seg = datetime(2026, 10, 26, 14, 0, tzinfo=UTC)  # segunda, 11h em São Paulo
    assert sales.in_send_window(seg) and not sales.in_send_window(seg + timedelta(days=5))  # sábado
    assert not sales.in_send_window(datetime(2026, 10, 26, 23, 0, tzinfo=UTC))  # 20h em SP


@pytest.fixture
def window(monkeypatch):
    monkeypatch.setattr(sales, "in_send_window", lambda now=None: True)


@pytest.mark.asyncio
async def test_full_funnel(office, window, monkeypatch):
    async with session_scope() as s:
        assert (await s.get(AgentState, sales.CLOSER)).sector == "comercial"

    out = await sales.tick(office, force=True)
    assert out["novas_empresas"] == 3 and out["diagnosticos"] == 3 and out["envios"]["primeiro"] == 3
    async with session_scope() as s:
        ps = list((await s.execute(select(Prospect))).scalars())
        logs = list((await s.execute(select(EmailLog).where(EmailLog.direction == "out"))).scalars())
    assert all(p.status == "contatado" and p.touches == 1 for p in ps)
    assert all(e.status == "simulated" and "/descadastrar/" in e.body and "/relatorio/" in e.body for e in logs)

    # resposta interessada -> proposta automática
    p = ps[0]
    assert await sales.handle_reply(office, p.email, "Re: diagnóstico", "Tenho interesse, quanto custa?") == "interessado"
    async with session_scope() as s:
        assert (await s.get(Prospect, p.id)).status == "proposta"

    # recusa e descadastro entram na supressão
    assert await sales.handle_reply(office, ps[1].email, "Re", "Não tenho interesse, obrigado.") == "nao"
    assert await sales.handle_reply(office, ps[2].email, "Re", "Por favor, remova meu e-mail da lista.") == "descadastrar"
    assert await mailer.suppressed(ps[2].email)

    # pagamento confirmado pelo Stripe -> cliente, receita real, kit e e-mail de boas-vindas
    secret = "whsec_test"
    office.settings = office.settings.model_copy(update={"stripe_webhook_secret": secret, "price_mensal_brl": 1490.0})
    event = {"type": "checkout.session.completed", "data": {"object": {"client_reference_id": p.token, "amount_total": 149000, "mode": "subscription", "customer": "cus_1"}}}
    body = json.dumps(event).encode()
    ts = str(int(time.time()))
    sig = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()

    from app.main import app

    app.state.office = office
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        bad = await c.post("/webhooks/stripe", content=body, headers={"stripe-signature": f"t={ts},v1=errado"})
        assert bad.status_code == 400
        ok = await c.post("/webhooks/stripe", content=body, headers={"stripe-signature": f"t={ts},v1={sig}"})
        assert ok.json()["result"] == "cliente ativado (mensal)"
        async with session_scope() as s:
            cl = (await s.execute(select(Client))).scalar_one()
            rev = (await s.execute(select(func.sum(RevenueEntry.amount_usd)).where(RevenueEntry.stream == "agencia", RevenueEntry.projected.is_(False)))).scalar_one()
        assert cl.mrr_brl == 1490 and cl.kit["faq"] and "GPTBot" in cl.kit["robots_txt"] and rev == round(1490 / office.settings.brl_per_usd, 2)
        page = await c.get(f"/cliente/{cl.token}")
        assert page.status_code == 200 and "Kit de GEO" in page.text and "[CONFIRMAR" in page.text
        prop = await c.get(f"/proposta/{p.token}")
        assert prop.status_code == 200 and "Acompanhamento mensal" in prop.text
        un = await c.post(f"/descadastrar/{ps[1].token}")
        assert un.status_code == 200 and "não receberá" in un.text
        panel = (await c.get("/api/office/sales", headers=H)).json()
        assert panel["mrr_brl"] == 1490 and panel["funnel"]["cliente"] == 1 and panel["health"]["smtp"] is False

    # relatório mensal quando vence
    async with session_scope() as s:
        row = await s.get(Client, cl.id)
        row.next_report_at = datetime.now(UTC) - timedelta(minutes=1)
    assert await sales.monthly(office) == 1
    async with session_scope() as s:
        row = await s.get(Client, cl.id)
        assert len(row.diagnoses) == 2


@pytest.mark.asyncio
async def test_daily_cap_and_followups(office, window):
    await office.gov.set("sales_daily_email_cap", 1)
    await sales.discover(office)
    await sales.diagnose(office)
    sent = await sales.outreach(office)
    assert sent["primeiro"] == 1  # limite diário respeitado
    # follow-up só depois de 4 dias
    async with session_scope() as s:
        p = (await s.execute(select(Prospect).where(Prospect.status == "contatado"))).scalar_one()
        p.last_contact_at = datetime.now(UTC) - timedelta(days=5)
    await office.gov.set("sales_daily_email_cap", 10)
    sent = await sales.outreach(office)
    assert sent["followup"] == 1


@pytest.mark.asyncio
async def test_inbound_request(office, window):
    from app.main import app

    app.state.office = office
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.get("/diagnostico-gratis")).status_code == 200
        r = await c.post("/diagnostico-gratis", data={"company": "Loja Boa", "site": "lojaboa.invalid", "segment": "loja de vinhos", "email": "dono@lojaboa.invalid", "consent": "1"})
        assert r.status_code == 303
        bad = await c.post("/diagnostico-gratis", data={"company": "X", "segment": "abc", "email": "x@y.zz"})
        assert bad.status_code == 422
    await sales.diagnose(office)
    sent = await sales.outreach(office)
    assert sent["primeiro"] == 1
    async with session_scope() as s:
        log = (await s.execute(select(EmailLog).where(EmailLog.to_addr == "dono@lojaboa.invalid"))).scalar_one()
    assert "Você pediu este diagnóstico" in log.body
