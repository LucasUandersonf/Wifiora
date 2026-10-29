"""Portal público: payloads, formulários, revisão humana, leads -> receita e API paga."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db import session_scope
from app.models import ApiClient, CorrectionRequest, Entity, Hub, Lead, RevenueEntry

FOUNDER = {"X-Founder-Token": "test-token"}


@pytest.fixture
async def client(office):
    from app.main import app

    app.state.office = office  # reaproveita o escritório da fixture (sem lifespan)
    await office.trigger_cycle("test")
    assert await office.wait_idle(timeout=60)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _first_entity() -> tuple[str, str, str]:
    async with session_scope() as s:
        hub = (await s.execute(select(Hub))).scalar_one()
        ent = (await s.execute(select(Entity).order_by(Entity.name))).scalars().first()
        return hub.slug, ent.slug, ent.id


@pytest.mark.asyncio
async def test_pages_and_institutional(client):
    hub, ent, _ = await _first_entity()
    r = await client.get(f"/hub/{hub}")
    assert r.status_code == 200 and "Verificado em" in r.text and "noindex" in r.text  # hub de demonstração
    r = await client.get(f"/hub/{hub}/{ent}")
    assert r.status_code == 200 and "Solicitar demonstração" in r.text
    for slug in ("sobre", "metodologia", "politica-editorial", "termos", "privacidade", "correcoes"):
        assert (await client.get(f"/{slug}")).status_code == 200
    data = (await client.get(f"/api/public/pages/hub/{hub}")).json()
    assert data["jsonld"]["@graph"] and data["entities"]
    site = (await client.get("/api/public/site")).json()
    assert site["hubs"] and "metodologia" in site["institutional"]


@pytest.mark.asyncio
async def test_lead_flow_becomes_real_revenue(client):
    hub, ent, _ = await _first_entity()
    r = await client.post("/forms/lead", data={"hub_slug": hub, "entity_slug": ent, "name": "Ana", "email": "ana@empresa.com.br", "consent": "1"})
    assert r.status_code == 303
    bad = await client.post("/api/public/leads", json={"hub_slug": hub, "entity_slug": ent, "name": "Ana", "email": "ana@empresa.com.br", "consent": False})
    assert bad.status_code == 422  # sem consentimento LGPD não grava
    spam = await client.post("/api/public/leads", json={"hub_slug": hub, "entity_slug": ent, "name": "Bot", "email": "x@y.zz", "consent": True, "website": "spam"})
    assert spam.status_code == 200
    async with session_scope() as s:
        leads = list((await s.execute(select(Lead))).scalars())
    assert len(leads) == 1
    r = await client.post(f"/api/control/leads/{leads[0].id}", json={"status": "won", "value_usd": 80}, headers=FOUNDER)
    assert r.status_code == 200
    async with session_scope() as s:
        rev = list((await s.execute(select(RevenueEntry).where(RevenueEntry.projected.is_(False)))).scalars())
    assert [x.amount_usd for x in rev] == [80]


@pytest.mark.asyncio
async def test_correction_and_human_review(client):
    hub, ent, ent_id = await _first_entity()
    r = await client.post("/forms/correction", data={"name": "Fornecedor", "email": "a@b.com", "message": "Preço mudou", "evidence_url": "https://x.com/precos", "hub_slug": hub, "entity_slug": ent})
    assert r.status_code == 303
    async with session_scope() as s:
        assert (await s.execute(select(CorrectionRequest))).scalar_one().status == "open"
    r = await client.post(f"/api/control/entities/{ent_id}/review", json={"reviewer": "Lucas (fundador)"}, headers=FOUNDER)
    assert r.status_code == 200
    page = (await client.get(f"/api/public/pages/entity/{hub}/{ent}")).json()
    assert page["entity"]["human_reviewed_by"] == "Lucas (fundador)"
    webpage = next(n for n in page["jsonld"]["@graph"] if n["@type"] == "WebPage")
    assert webpage["reviewedBy"]["name"] == "Lucas (fundador)" and webpage["lastReviewed"]


@pytest.mark.asyncio
async def test_paid_api_key_and_quota(client):
    r = await client.post("/api/control/api-clients", json={"name": "Cliente X", "daily_quota": 2}, headers=FOUNDER)
    key = r.json()["api_key"]
    assert (await client.get("/api/v1/hubs")).status_code == 401
    assert (await client.get("/api/v1/hubs", headers={"X-API-Key": key})).status_code == 200
    # hubs de demonstração não são vendidos pela API
    assert (await client.get("/api/v1/entities", headers={"X-API-Key": key})).json() == []
    assert (await client.get("/api/v1/hubs", headers={"X-API-Key": key})).status_code == 429
    async with session_scope() as s:
        c = (await s.execute(select(ApiClient))).scalar_one()
    assert c.key_hash != key and c.total_requests == 2
