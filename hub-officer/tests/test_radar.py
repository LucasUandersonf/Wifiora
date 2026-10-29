"""Radar de Ondas: varredura completa, evidência obrigatória e ação aprovada virando diretriz."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db import session_scope
from app.models import Directive, Objective, PlayAction, Signal, Wave, WaveSnapshot

FOUNDER = {"X-Founder-Token": "test-token"}


async def _sweep(office) -> None:
    await office.trigger_radar("test")
    assert await office.wait_idle(timeout=60)


@pytest.mark.asyncio
async def test_radar_sweep_end_to_end(office):
    await _sweep(office)
    async with session_scope() as s:
        obj = (await s.execute(select(Objective).where(Objective.kind == "radar"))).scalar_one()
        signals = list((await s.execute(select(Signal))).scalars())
        waves = list((await s.execute(select(Wave))).scalars())
        plays = list((await s.execute(select(PlayAction))).scalars())
        snaps = list((await s.execute(select(WaveSnapshot))).scalars())
    assert obj.status == "completed" and "Boletim" in obj.final_report["summary"]
    assert signals and all(x.demo and x.url.startswith("https://") for x in signals)
    assert waves and all(w.evidence for w in waves) and len(snaps) == len(waves)
    assert plays and all(p.status == "proposed" for p in plays)
    # varredura não bloqueia o ciclo de produção, e a segunda varredura não duplica sinais
    await office.trigger_cycle("test")
    await _sweep(office)
    async with session_scope() as s:
        assert len(list((await s.execute(select(Signal))).scalars())) == len(signals)
        prod = (await s.execute(select(Objective).where(Objective.kind == "production"))).scalar_one()
        quiet = (await s.execute(select(Objective).where(Objective.kind == "radar").order_by(Objective.created_at.desc()))).scalars().first()
    assert prod.status == "completed"
    # semana calma: sem sinal novo, a varredura fecha com boletim honesto e sem reprovação
    assert quiet.status == "completed" and quiet.final_report["summary"].startswith("Sem novidades")


@pytest.mark.asyncio
async def test_wave_analyst_drops_invented_evidence(office):
    from app.agents.specialists.radar import WaveAnalystAgent

    agent = office.agents["radar.waves"]
    assert isinstance(agent, WaveAnalystAgent)

    async def fake_think(kind, prompt, **kw):
        return {"waves": [{"slug": "x", "name": "X", "stage": "emergente", "impact": 0.5, "urgency": 0.5, "confidence": 0.99,
                           "evidence": ["https://real.com/a", "https://inventado.com/b"]}]}

    agent.think = fake_think  # type: ignore[method-assign]
    out = await agent.execute(
        type("T", (), {"objective_id": "o", "id": "t", "title": "t", "brief": "", "feedback": None, "status": "in_progress"})(),
        {"signal_scan": {"signals": [{"url": "https://real.com/a", "title": "A"}]}},
        type("O", (), {"title": "o", "niche": "n"})(),
    )
    assert out["waves"][0]["evidence"] == ["https://real.com/a"] and out["dropped_evidence"] == 1


@pytest.mark.asyncio
async def test_approved_play_becomes_directive_for_cvo(office):
    from app.main import app

    app.state.office = office
    await _sweep(office)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        data = (await c.get("/api/office/radar", headers=FOUNDER)).json()
        assert data["waves"] and data["plays"] and data["brief"]["text"]
        play = data["plays"][0]
        assert (await c.post(f"/api/control/plays/{play['id']}", json={"status": "approved"}, headers=FOUNDER)).status_code == 200
        async with session_scope() as s:
            d = (await s.execute(select(Directive))).scalar_one()
        assert d.active and d.text.startswith("[Radar]")
        assert d.text in await office.gov.active_directives()
        await c.post(f"/api/control/plays/{play['id']}", json={"status": "done"}, headers=FOUNDER)
        assert d.text not in await office.gov.active_directives()
