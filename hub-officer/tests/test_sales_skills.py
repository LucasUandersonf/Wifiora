"""Habilidades de vendas sênior: playbooks carregam, cada tarefa recebe só o que precisa e chegam ao prompt do LLM."""

from __future__ import annotations

import pytest

from app.core import sales, sales_skills


def test_catalog_and_task_selection():
    ids = {s["id"] for s in sales_skills.catalog()}
    assert len(ids) == 18 and all(n in ids for names in sales_skills.TASKS.values() for n in names)
    first = sales_skills.for_task("first_touch")
    assert "Operating principles" in first and "Relevance" in first and "Harvard" not in first
    assert "Harvard" in sales_skills.for_task("negotiate")
    assert "Never cold-message on WhatsApp" in sales_skills.for_task("followup")


def test_pipeline_metrics_small_sample_uses_default():
    m = sales.pipeline_metrics({"contatado": 8, "proposta": 2}, monthly_price_brl=800)
    assert m["contacted_to_engaged"] == {"rate": 0.2, "sample": 10, "reliable": False}
    f = m["forecast_brl_month"]
    assert f["probability_source"] == "default" and f["likely"] == 240.0 and f["conservative"] < f["likely"]


@pytest.mark.asyncio
async def test_skills_reach_the_prompt(office, monkeypatch):
    monkeypatch.setattr(sales, "in_send_window", lambda now=None: True)
    seen: list[str] = []
    orig = office.llm.complete_json

    async def spy(**kw):
        seen.append(kw.get("system", ""))
        return await orig(**kw)

    monkeypatch.setattr(office.llm, "complete_json", spy)
    await sales.tick(office, force=True)
    assert any("SENIOR SALES PLAYBOOK" in s and "Specificity" in s for s in seen)


def test_two_options_and_action_plan():
    from datetime import datetime

    from app.core import insighta

    o = {"founders_brl": 800.0, "founders_remaining": 3, "pro_brl": 1290.0, "basic_brl": 490.0}
    opts = insighta.two_options(o)
    assert list(opts) == ["ideal", "enxuta"] and opts["ideal"]["plano"] == "Pro Founders" and opts["enxuta"]["plano"] == "Basic"
    assert insighta.two_options({**o, "founders_remaining": 0})["ideal"]["plano"] == "Pro"
    plan = insighta.action_plan(14, datetime(2026, 11, 2, 10, 0))
    assert [s["data"] for s in plan] == ["02/11", "04/11", "07/11", "09/11", "15/11"]


@pytest.mark.asyncio
async def test_insighta_answer_qualifies_or_disqualifies(office, monkeypatch):
    from sqlalchemy import select

    from app.core import insighta
    from app.db import session_scope
    from app.models import EmailLog, Prospect

    monkeypatch.setattr(office.settings, "business", "insighta")
    monkeypatch.setattr(sales, "in_send_window", lambda now=None: True)
    await sales.tick(office, force=True)  # 3 clínicas de demonstração contatadas
    async with session_scope() as s:
        ps = list((await s.execute(select(Prospect).order_by(Prospect.company))).scalars())
    assert len(ps) == 3 and all(p.status == "contatado" for p in ps)

    verdicts = iter([{"qualified": True, "reason": "glosas altas", "body": ""}, {"qualified": False, "reason": "uma profissional só", "body": ""}])

    async def fake(**kw):
        return next(verdicts)

    monkeypatch.setattr(office.llm, "complete_json", fake)
    await insighta.answer(office, ps[0], "Temos muitas glosas, como funciona?")
    await insighta.answer(office, ps[1], "Sou só eu atendendo, quanto custa?")
    async with session_scope() as s:
        a, b = await s.get(Prospect, ps[0].id), await s.get(Prospect, ps[1].id)
        mails = {e.prospect_id: e.body for e in (await s.execute(select(EmailLog).where(EmailLog.kind == "resposta"))).scalars()}
    assert a.status == "proposta" and "handover" in a.notes
    assert "Pro Founders" in mails[a.id] or "Pro (" in mails[a.id]
    assert "plano de ação" in mails[a.id] and "utm_source=escritorio" in mails[a.id] and "Basic" in mails[a.id]
    assert b.status == "desqualificado" and "signup" not in mails[b.id] and "uma profissional só" in b.notes
