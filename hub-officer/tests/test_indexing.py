"""IndexNow Semântico: avisa na hora só o que mudou (e o que depende disso no grafo)."""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select

from app.config import get_settings
from app.core.indexing import affected_paths, announce
from app.db import session_scope
from app.models import Entity, IndexPing


def test_affected_paths_cover_graph_neighbours():
    paths = affected_paths("erps", ["alfa"], ["alfa-ltda"])
    assert paths[0] == "/hub/erps/alfa"
    for p in ("/hub/erps", "/hub/erps/data.jsonl", "/hub/erps/data.csv", "/empresa/alfa-ltda", "/conceitos", "/knowledge-graph.jsonld"):
        assert p in paths
    assert "/" not in paths and "/" in affected_paths("erps", [], new_hub=True)


@pytest.mark.asyncio
async def test_indexnow_payload(office, monkeypatch):
    sent: dict = {}

    async def fake_post(self, url, json=None, **kw):
        sent.update(url=url, body=json)
        return httpx.Response(202)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    st = get_settings().model_copy(update={"indexnow_key": "abc123", "public_base_url": "https://hub.exemplo.com.br"})
    res = await announce(st, hub_slug="erps", entity_slugs=["alfa"], demo=False, org_slugs=["alfa-ltda"], reason="data_change", changed={"alfa": ["preco_mensal_brl"]})
    assert res["indexnow"] == "HTTP 202"
    assert sent["body"]["host"] == "hub.exemplo.com.br" and sent["body"]["keyLocation"].endswith("/indexnow-key.txt")
    assert "https://hub.exemplo.com.br/hub/erps/alfa" in sent["body"]["urlList"]
    # demonstração nunca vai para buscadores
    sent.clear()
    res = await announce(st, hub_slug="erps", entity_slugs=["alfa"], demo=True)
    assert not sent and res["indexnow"].startswith("skipped")


@pytest.mark.asyncio
async def test_price_change_is_pushed_immediately(office):
    await office.trigger_cycle("test")
    assert await office.wait_idle(timeout=60)
    async with session_scope() as s:
        pings = list((await s.execute(select(IndexPing))).scalars())
        assert [p.reason for p in pings] == ["publish"]
        ent = (await s.execute(select(Entity).order_by(Entity.name))).scalars().first()
        slug = ent.slug
        ent.attributes = {**ent.attributes, "preco_mensal_brl": 1.0}  # simula preço antigo no banco

    await office.trigger_cycle("test")
    assert await office.wait_idle(timeout=60)
    async with session_scope() as s:
        pings = list((await s.execute(select(IndexPing).order_by(IndexPing.created_at))).scalars())
    changes = [p for p in pings if p.reason == "data_change"]
    assert len(changes) == 1 and changes[0].changed_fields == {slug: ["preco_mensal_brl"]}
    assert f"/hub/{changes[0].hub_slug}/{slug}" in changes[0].urls and any(u.startswith("/empresa/") for u in changes[0].urls)
    assert changes[0].lag_seconds is not None and changes[0].lag_seconds < 60
    assert [p.reason for p in pings].count("publish") == 1  # o fim do ciclo não reanuncia o que já foi avisado
