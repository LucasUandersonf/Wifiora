"""Habilidades de vendas sênior: playbooks carregam, cada tarefa recebe só o que precisa e chegam ao prompt do LLM."""

from __future__ import annotations

import pytest

from app.core import sales, sales_skills


def test_catalog_and_task_selection():
    ids = {s["id"] for s in sales_skills.catalog()}
    assert len(ids) == 14 and all(n in ids for names in sales_skills.TASKS.values() for n in names)
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
