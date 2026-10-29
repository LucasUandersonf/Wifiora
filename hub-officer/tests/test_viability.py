"""Painel de Viabilidade: metas de 30/90/180 dias e o veredito semanal do Gauss."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core import viability
from app.core.viability import judge
from app.db import session_scope
from app.models import BotHit, Hub, Lead, RevenueEntry

T = {"bots_days": 30, "traction_days": 90, "revenue_days": 180, "min_leads": 1}


def _m(**kw):
    base = {"days_live": 0, "bot_hits": 0, "bot_data_downloads": 0, "bots": [], "share_of_voice": None, "leads": 0, "leads_won": 0,
            "revenue_30d": 0.0, "revenue_total": 0.0, "cost_30d": 5.0}
    return {**base, **kw}


def test_rules():
    assert judge(_m(days_live=10), T)["verdict"] == "aquecendo"
    assert judge(_m(days_live=40), T)["verdict"] == "ajustar"  # nenhum robô até o dia 30
    assert judge(_m(days_live=40, bot_hits=3, bots=["GPTBot"]), T)["verdict"] == "continuar"
    assert judge(_m(days_live=100, bot_hits=3), T)["verdict"] == "pivotar"  # sem citação e sem leads: trocar de nicho
    assert judge(_m(days_live=100, bot_hits=3, leads=2), T)["verdict"] == "ajustar"
    ok = dict(bot_hits=3, share_of_voice=0.2, leads=4)
    assert judge(_m(days_live=200, **ok, revenue_30d=2.0), T)["verdict"] == "pivotar"  # tem tração, falta monetizar
    assert judge(_m(days_live=200, **ok, revenue_30d=9.0), T)["verdict"] == "continuar"
    r = judge(_m(days_live=200, bot_hits=1), T)
    assert r["verdict"] == "encerrar" and r["actions"] and r["reasons"]


@pytest.mark.asyncio
async def test_weekly_run_uses_real_numbers(office):
    await office.trigger_cycle("test")
    assert await office.wait_idle(timeout=60)
    async with session_scope() as s:
        hub = (await s.execute(select(Hub))).scalar_one()
        hub.published_at = datetime.now(UTC) - timedelta(days=200)
        hub.share_of_voice = 0.3
        s.add(BotHit(day="2026-01-01", bot="GPTBot", kind="data", hub=hub.slug, hits=4))
        s.add(Lead(hub_slug=hub.slug, entity_slug="x", entity_name="X", name="Ana", email="a@b.com", consent=True, status="won", value_usd=40))
        s.add(RevenueEntry(stream="cpl", amount_usd=40, hub_id=hub.id))
        s.add(RevenueEntry(stream="cpl", amount_usd=999, hub_id=hub.id, projected=True))  # projeção não conta
        slug = hub.slug

    res = await viability.run(office)
    assert len(res) == 1 and res[0]["metrics"]["bot_data_downloads"] == 4 and res[0]["metrics"]["revenue_30d"] == 40
    assert res[0]["verdict"] in ("continuar", "pivotar")  # depende do custo simulado do ciclo
    assert await viability.run(office) == []  # já tem veredito nesta semana

    from app.main import app

    app.state.office = office
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        h = {"X-Founder-Token": "test-token"}
        r = (await c.post("/api/control/viability/run", headers=h)).json()
        assert r["hubs"][0]["hub"] == slug
        panel = (await c.get("/api/office/viability", headers=h)).json()
    assert panel["targets"]["traction_days"] == 90 and panel["hubs"][0]["milestones"][0]["status"] == "cumprida"
