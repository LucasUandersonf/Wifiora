"""Boletim executivo: opt-in duplo, curadoria só com fonte, aprovação do fundador, envio em lote e higiene da base."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core import mailer
from app.core import newsletter as nl
from app.db import session_scope
from app.models import Edition, EmailLog, Subscriber

H = {"X-Founder-Token": "test-token"}
NOW = datetime.now(UTC).strftime("%a, %d %b %Y %H:%M:%S +0000")
RSS = f"""<?xml version="1.0"?><rss version="2.0"><channel><title>ANS</title>
<item><title>ANS publica nova versão do padrão TISS</title><link>https://www.gov.br/ans/noticia-1</link><pubDate>{NOW}</pubDate><description>&lt;p&gt;Prazo de adequação&lt;/p&gt;</description></item>
<item><title>Operadoras terão novo prazo para autorização</title><link>https://www.gov.br/ans/noticia-2</link><pubDate>{NOW}</pubDate></item>
<item><title>Notícia antiga</title><link>https://www.gov.br/ans/velha</link><pubDate>Mon, 01 Jan 2024 10:00:00 +0000</pubDate></item>
</channel></rss>"""
ATOM = """<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Resolução sobre glosas</title><link href="https://in.gov.br/r-1"/><updated>2026-10-28T10:00:00Z</updated></entry></feed>"""


def test_parse_feeds():
    rss = nl.parse_feed(RSS, "gov.br")
    assert [i["link"] for i in rss][:2] == ["https://www.gov.br/ans/noticia-1", "https://www.gov.br/ans/noticia-2"] and rss[0]["summary"] == "Prazo de adequação"
    assert nl.parse_feed(ATOM, "in.gov.br")[0]["link"] == "https://in.gov.br/r-1"
    assert nl.parse_feed("<html>não é feed", "x") == []


def test_validate_drops_unsourced():
    items = [{"link": "https://fonte/1"}]
    content, notes = nl.validate({"headline": {"title": "T", "body": "Corte de 12%", "source_url": "https://inventado"},
                                  "chart": {"title": "G", "source_url": "https://fonte/1", "rows": [{"label": "A", "value": 1}]},
                                  "notes": [{"title": "N", "body": "b", "source_url": "https://outro"}]}, items)
    assert content["headline"] == {} and content["chart"] is None and content["notes"][0]["source_url"] is None
    assert any("manchete" in n for n in notes) and any("gráfico" in n for n in notes)


@pytest.mark.asyncio
async def test_full_newsletter_flow(office, monkeypatch):
    monkeypatch.setattr(office.settings, "business", "insighta")
    monkeypatch.setattr(office.settings, "newsletter_sources", "https://www.gov.br/ans/rss|https://in.gov.br/feed")
    monkeypatch.setattr(office.settings, "newsletter_webhook_secret", "hook")
    feeds = {"https://www.gov.br/ans/rss": RSS, "https://in.gov.br/feed": ATOM}
    transport = httpx.MockTransport(lambda r: httpx.Response(200, text=feeds.get(str(r.url), "")))

    from app.main import app

    app.state.office = office
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        # opt-in duplo: sem consentimento não entra; com consentimento fica pendente até confirmar (POST, não GET)
        assert (await c.post("/boletim", data={"email": "ana@clinica.com.br"})).status_code == 422
        r = await c.post("/boletim", data={"email": "ana@clinica.com.br", "name": "Ana", "role": "gestora", "consent": "1"})
        assert r.status_code == 303
        await c.post("/boletim", data={"email": "beto@hospital.com.br", "consent": "1"})
        await c.post("/boletim", data={"email": "nunca@confirmou.com.br", "consent": "1"})
        async with session_scope() as s:
            subs = {x.email: x for x in (await s.execute(select(Subscriber))).scalars()}
        assert all(x.status == "pendente" and "LGPD" in x.consent_text for x in subs.values())
        assert (await c.get(f"/boletim/confirmar/{subs['ana@clinica.com.br'].token}")).status_code == 200  # GET não confirma
        for e in ("ana@clinica.com.br", "beto@hospital.com.br"):
            assert (await c.post(f"/boletim/confirmar/{subs[e].token}")).status_code == 200

        # curadoria → redação → diagramação: só itens recentes, com fonte
        e = await nl.build(office, transport)
        assert e is not None and e.status == "rascunho" and len(e.items) == 3
        assert "https://www.gov.br/ans/velha" not in [i["link"] for i in e.items]
        assert await nl.build(office, transport) is None  # uma edição por semana
        html = (await c.get(f"/api/office/newsletter/{e.id}.html", headers=H)).text
        assert "<!--[if mso]>" in html and "Notas de bancada" in html and "Fonte:" in html and 'bgcolor="#673de6"' in html
        assert (await c.get(f"/boletim/{e.slug}")).status_code == 404  # não publicado antes do envio

        # nada sai sem aprovação; depois de aprovado, só para quem confirmou
        assert (await nl.send(office, force=True))["enviados"] == 0
        assert (await c.post(f"/api/control/newsletter/{e.id}/decide", json={"approve": True}, headers=H)).json()["status"] == "aprovado"
        out = (await c.post("/api/control/newsletter/send", headers=H)).json()
        assert out == {"enviados": 2, "fila": 0}
        async with session_scope() as s:
            logs = list((await s.execute(select(EmailLog).where(EmailLog.kind == f"boletim:{e.number}"))).scalars())
            ed = await s.get(Edition, e.id)
        assert sorted(x.to_addr for x in logs) == ["ana@clinica.com.br", "beto@hospital.com.br"] and ed.status == "enviado"
        assert (await nl.send(office, force=True))["enviados"] == 0  # não repete

        # versão web pública e indexável, com JSON-LD
        web = (await c.get(f"/boletim/{e.slug}")).text
        assert '"NewsArticle"' in web and "rel=\"canonical\"" in web and "Cancelar inscrição" not in web
        assert f"Edição {e.number}" in (await c.get("/boletim")).text

        # higiene: bounce e reclamação saem da base; descadastro de um clique
        assert (await c.post("/webhooks/boletim?token=errado", json={"event": "hard_bounce", "email": "beto@hospital.com.br"})).status_code == 401
        r = await c.post("/webhooks/boletim?token=hook", json=[{"event": "hard_bounce", "email": "beto@hospital.com.br"}, {"event": "spam", "email": "ana@clinica.com.br"}])
        assert r.json()["processados"] == 2 and await mailer.suppressed("beto@hospital.com.br")
        await c.post(f"/boletim/sair/{subs['nunca@confirmou.com.br'].token}")
        async with session_scope() as s:
            st = {x.email: x.status for x in (await s.execute(select(Subscriber))).scalars()}
        assert st == {"ana@clinica.com.br": "reclamacao", "beto@hospital.com.br": "bounce", "nunca@confirmou.com.br": "descadastrado"}
        panel = (await c.get("/api/office/newsletter", headers=H)).json()
        assert panel["editions"][0]["sent"] == 2 and panel["subscribers"]["bounce"] == 1


@pytest.mark.asyncio
async def test_week_without_news_uses_approved_guide(office, monkeypatch):
    from app.core import insighta_content as ic

    monkeypatch.setattr(office.settings, "business", "insighta")
    assert await nl.build(office) is None  # sem fontes e sem guia: não inventa edição
    await ic.tick(office, force=True)
    async with session_scope() as s:
        piece = (await s.execute(select(ic.ContentPiece).where(ic.ContentPiece.status == "rascunho"))).scalar_one()
    await ic.decide(piece.id, True)
    e = await nl.build(office)
    assert e is not None and e.content["headline"]["guide"] == piece.slug
    assert "Guia da semana" in nl.render_html(office, e)
