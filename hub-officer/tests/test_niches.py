"""Catálogo de nichos: semeado no banco, rodízio pelo CVO, controles do fundador e bloqueio editorial."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core import niches
from app.db import session_scope
from app.models import Hub, Objective

H = {"X-Founder-Token": "test-token"}


@pytest.mark.asyncio
async def test_catalog_seeded_and_playbook(office):
    rows = await niches.all_niches()
    assert [n.slug for n in rows][:3] == ["financas-pessoais", "planos-de-saude", "educacao"]
    assert len(rows) == len(niches.CATALOG) and next(n for n in rows if n.slug == "apostas").status == "bloqueado"
    text = await niches.playbook()
    assert "Banco Central" in text and "FORA DO MAPA: Apostas" in text and "YMYL" in text
    assert niches.match("Finanças pessoais: cartões e contas", rows).slug == "financas-pessoais"
    assert "não substitui orientação profissional" in await niches.rules_for("Emagrecimento e suplementos")


@pytest.mark.asyncio
async def test_cycle_uses_catalog_and_rotates(office):
    await office.trigger_cycle("test")
    assert await office.wait_idle(timeout=60)
    async with session_scope() as s:
        obj = (await s.execute(select(Objective).where(Objective.kind == "production"))).scalars().first()
        hub = (await s.execute(select(Hub))).scalar_one()
    assert obj.niche_slug == "financas-pessoais" and hub.niche_slug == "financas-pessoais"
    assert "Banco Central" in obj.plan["niche_rules"]
    # finanças já tem hub publicado: com rodízio, o próximo ciclo vai para planos de saúde
    nxt = await niches.resolve_focus("Finanças pessoais", rotation=True)
    assert nxt.slug == "planos-de-saude"
    assert (await niches.resolve_focus("Finanças pessoais", rotation=False)).slug == "financas-pessoais"


@pytest.mark.asyncio
async def test_founder_controls(office):
    from app.main import app

    app.state.office = office
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        panel = (await c.get("/api/office/niches", headers=H)).json()
        assert panel["next"] == "financas-pessoais" and len(panel["criteria"]) == 4
        assert (await c.patch("/api/control/niches/apostas", json={"status": "ativo"}, headers=H)).status_code == 409
        assert (await c.patch("/api/control/niches/educacao", json={"status": "pausado"}, headers=H)).status_code == 200
        assert (await c.post("/api/control/niches/educacao/focus", headers=H)).status_code == 409  # pausado não entra em foco
        r = await c.post("/api/control/niches/saude-mental/focus", headers=H)
        assert r.json()["focus"] == "Saúde mental"
        assert (await c.patch("/api/control/niches/entretenimento", json={"rank": 2}, headers=H)).json()["rank"] == 2
        panel = (await c.get("/api/office/niches", headers=H)).json()
    assert panel["next"] == "saude-mental"
