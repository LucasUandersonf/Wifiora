"""Conselho: os bots debatem, o CVO fecha a ata e só o permitido é aplicado sozinho."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core import council
from app.db import session_scope
from app.models import ApprovalRequest, CostEntry, Directive, Meeting


@pytest.mark.asyncio
async def test_meeting_debate_and_memo(office):
    await office.trigger_cycle("test")
    assert await office.wait_idle(timeout=60)

    m = await council.convene(office, council.WEEKLY_TOPIC, trigger="semanal")
    assert m.status == "done", m.error
    r1 = [r for r in m.rounds if r["round"] == 1]
    r2 = [r for r in m.rounds if r["round"] == 2]
    assert len(r1) == len(council.MEMBERS) == len(r2)
    assert any(not rep["agree"] for r in r2 for rep in r["output"]["replies"])  # houve discordância (Juno)
    assert m.memo["profit_outlook"] == "incerto" and len(m.memo["scenarios"]) == 3 and m.memo["founder_tasks"]

    async with session_scope() as s:
        dirs = [d.text for d in (await s.execute(select(Directive).where(Directive.active.is_(True)))).scalars()]
        approvals = list((await s.execute(select(ApprovalRequest).where(ApprovalRequest.kind == "council_proposal"))).scalars())
        calls = (await s.execute(select(CostEntry).where(CostEntry.task_id == m.id))).scalars().all()
    assert sum(d.startswith(council.DIRECTIVE_PREFIX) for d in dirs) == 2  # autonomia 1: diretrizes valem na hora
    assert len(approvals) == 1 and approvals[0].amount_usd == 15  # gasto sempre vai para o fundador
    assert len(calls) == 2 * len(council.MEMBERS) + 1

    from app.main import app

    app.state.office = office
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        h = {"X-Founder-Token": "test-token"}
        r = await c.post(f"/api/control/approvals/{approvals[0].id}", json={"approve": True}, headers=h)
        assert r.status_code == 200
        listing = (await c.get("/api/office/council", headers=h)).json()
    assert listing[0]["id"] == m.id and listing[0]["memo"]["decisions"]
    async with session_scope() as s:
        assert (await s.execute(select(Directive).where(Directive.text.like("[Aprovado pelo fundador]%")))).scalars().first()


@pytest.mark.asyncio
async def test_autonomy_zero_sends_everything_for_approval(office):
    await office.gov.set("autonomy_level", 0)
    m = await council.convene(office, "Teste de autonomia")
    assert m.status == "done" and m.applied["directives"] == [] and len(m.applied["approvals"]) == 3
    async with session_scope() as s:
        assert (await s.execute(select(Meeting))).scalars().first()
