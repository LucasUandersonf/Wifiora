"""Rankings objetivos: matemáticos, com empates honestos e blindados contra campos pagos."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.rankings import hub_rankings
from app.db import session_scope
from app.models import Entity, Hub
from app.skills.builtin.jsonld import graph_stats


def _hub(fields):
    return Hub(slug="h", title="H", niche="n", schema_template={"fields": fields})


def _ent(name, **attrs):
    return Entity(slug=name.lower(), name=name, schema_type="SoftwareApplication", attributes=attrs)


def test_ties_missing_and_vendor_fields():
    hub = _hub([
        {"name": "preco", "type": "number", "rank": "asc"},
        {"name": "desconto_premium", "type": "number", "rank": "desc", "source": "vendor"},  # informado pela empresa: fora
    ])
    ents = [_ent("A", preco=100, desconto_premium=50), _ent("B", preco=100), _ent("C", preco=80), _ent("D")]
    rk = hub_rankings(hub, ents)
    assert [r["key"] for r in rk] == ["campo-preco"]
    items = rk[0]["items"]
    assert [(i["name"], i["position"]) for i in items] == [("C", 1), ("A", 2), ("B", 2)]  # empate divide a posição
    assert rk[0]["missing"] == ["D"]
    assert hub_rankings(hub, [_ent("A", preco=1), _ent("B", preco=1)]) == []  # sem diferença, sem ranking


@pytest.mark.asyncio
async def test_hub_page_publishes_rankings(office):
    await office.trigger_cycle("test")
    assert await office.wait_idle(timeout=60)
    async with session_scope() as s:
        slug = (await s.execute(select(Hub))).scalar_one().slug
    from app.main import app

    app.state.office = office
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        data = (await c.get(f"/api/public/pages/hub/{slug}")).json()
        html = (await c.get(f"/hub/{slug}")).text
    keys = {r["key"] for r in data["rankings"]}
    assert "campo-preco_mensal_brl" in keys and "criterios" in keys
    lists = [n for n in data["jsonld"]["@graph"] if str(n.get("@id", "")).count("#ranking-")]
    assert lists and lists[0]["itemListOrder"].endswith("Ascending")
    assert graph_stats(data["jsonld"])["dangling"] == []
    assert 'id="rankings"' in html and "Nenhuma empresa paga" in html
