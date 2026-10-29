"""Ciclo completo: CVO -> Scouts -> Especialistas -> Score Agent (com revisão) -> consolidação -> publicação."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.db import session_scope
from app.models import AgentMessage, CostEntry, Entity, Evaluation, Hub, Objective, Task


@pytest.mark.asyncio
async def test_full_cycle_publishes_validated_hub(office):
    await office.trigger_cycle("test")
    assert await office.wait_idle(timeout=60), "escritório não ficou ocioso"

    async with session_scope() as s:
        obj = (await s.execute(select(Objective))).scalar_one()
        tasks = list((await s.execute(select(Task))).scalars())
        hub = (await s.execute(select(Hub))).scalar_one()
        ents = list((await s.execute(select(Entity))).scalars())
        evals = list((await s.execute(select(Evaluation))).scalars())
        msgs = (await s.execute(select(func.count(AgentMessage.id)))).scalar_one()
        llm_cost = (await s.execute(select(func.count(CostEntry.id)).where(CostEntry.category == "llm"))).scalar_one()

    assert obj.status == "completed", obj.final_report
    assert {t.sector for t in tasks} == {"research", "finance", "tech"}
    assert all(t.status == "approved" for t in tasks), [(t.kind, t.status, t.feedback) for t in tasks]

    # o mock omite uma fonte na 1ª extração: Score Agent precisa reprovar e a revisão corrigir
    extraction = next(t for t in tasks if t.kind == "data_extraction")
    assert extraction.revisions == 1
    assert any(not e.passed for e in evals if e.task_id == extraction.id)

    assert hub.status == "published" and hub.demo_data is True
    assert len(ents) == 4 and all(e.validated and e.status == "published" for e in ents)
    assert all(e.grounding_ratio >= 0.8 for e in ents)
    assert msgs > 20 and llm_cost > 10


@pytest.mark.asyncio
async def test_budget_guard_pauses_office(office):
    await office.gov.set("daily_llm_budget_usd", 0.0)
    await office.trigger_cycle("test")
    await office.wait_idle(timeout=5)
    assert await office.gov.get("paused") is True


@pytest.mark.asyncio
async def test_published_pages_have_complete_valid_jsonld(office):
    from app.skills.builtin.jsonld import validate_jsonld
    from app.web.render import entity_payload, hub_payload

    await office.trigger_cycle("test")
    assert await office.wait_idle(timeout=60)
    async with session_scope() as s:
        hub = (await s.execute(select(Hub))).scalar_one()
        ent = (await s.execute(select(Entity).order_by(Entity.name))).scalars().first()

    hp = await hub_payload(hub.slug)
    assert validate_jsonld(hp["jsonld"]) == []
    types = {n["@type"] for n in hp["jsonld"]["@graph"] if isinstance(n["@type"], str)}
    assert {"Organization", "WebPage", "Dataset", "BreadcrumbList", "FAQPage"} <= types
    dataset = next(n for n in hp["jsonld"]["@graph"] if n["@type"] == "Dataset")
    item = dataset["mainEntity"]["itemListElement"][0]["item"]
    assert item["@type"] == ["SoftwareApplication", "Product"]
    # grafo conectado: fabricante é referência para o nó da empresa, que existe no mesmo grafo
    nodes = {n["@id"]: n for n in hp["jsonld"]["@graph"] if "@id" in n}
    org = nodes[item["manufacturer"]["@id"]]
    assert org["@type"] == "Organization" and "fictícia" in org["legalName"] and "/empresa/" in org["@id"]
    assert len(item["isSimilarTo"]) == 3  # as outras 3 empresas do hub
    concepts = [nodes[k["@id"]] for k in item["keywords"]]
    assert {"Simples Nacional", "Emissão de NF-e"} <= {c["name"] for c in concepts}
    assert all(nodes[r["@id"]]["termCode"] == "integracao" for r in item["isRelatedTo"])
    from app.skills.builtin.jsonld import graph_stats

    assert graph_stats(hp["jsonld"])["dangling"] == []
    assert item["review"]["@type"] == "Review" and "reviewRating" not in item["review"]
    assert hp["criteria"] and all("criteria_met" in e for e in hp["entities"])

    ep = await entity_payload(hub.slug, ent.slug)
    assert validate_jsonld(ep["jsonld"]) == []
    assert ep["entity"]["verified_at"] and ep["entity"]["criteria"]
