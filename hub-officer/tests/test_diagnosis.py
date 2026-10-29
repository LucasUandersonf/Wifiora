"""Diagnóstico de Visibilidade em IA: produto de entrada da agência."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.core import diagnosis as dg

H = {"X-Founder-Token": "test-token"}


def test_mentions_and_parsing():
    assert dg.mentions("Recomendo a Loja Ágil e a Outra.", [], "Loja Agil", None)
    assert not dg.mentions("Recomendo a Lojaágil.", [], "Loja Agil", None)
    assert dg.mentions("veja em", ["https://www.lojaagil.com.br/precos"], "X", "lojaagil.com.br")
    comps = dg.parse_competitors("Concorrente A - a.com.br\nConcorrente B\n\n")
    assert comps == [{"name": "Concorrente A", "site": "a.com.br"}, {"name": "Concorrente B", "site": ""}]


def test_robots_and_html_signals():
    robots = "User-agent: *\nDisallow: /admin\n\nUser-agent: GPTBot\nDisallow: /\n"
    acc = dg.robots_ai_access(robots)
    assert acc["GPTBot"] is False and acc["ClaudeBot"] is True
    assert all(dg.robots_ai_access("User-agent: *\nDisallow:\n").values())
    assert not any(dg.robots_ai_access("User-agent: *\nDisallow: /\n").values())
    html = '<title>Loja</title><meta name="description" content="x"><script type="application/ld+json">{"@graph":[{"@type":"Organization"},{"@type":["Product"]}]}</script>'
    sig = dg.html_signals(html)
    assert sig["jsonld_types"] == ["Organization", "Product"] and sig["title"] == "Loja"
    tech = {"checked": True, "checks": {k: True for k, _, _ in dg.TECH_CHECKS}}
    assert dg.tech_score(tech) == 100 and dg.overall(0.5, 100) == 70 and dg.overall(0.2, None) == 20


@pytest.mark.asyncio
async def test_full_diagnosis_and_report(office):
    d = await dg.create(office, brand="Loja Exemplo", site="lojaexemplo.invalid", category="loja de suplementos online", city="São Paulo",
                        competitors="Rival Um - rivalum.invalid\nRival Dois")
    d = await dg.run(office, d.id)
    assert d.status == "done", d.error
    assert len(d.queries) == 10 and d.mode == "parametric"
    assert set(d.visibility["share"]) == {"Loja Exemplo", "Rival Um", "Rival Dois"}
    assert d.scores["technical"] is None and d.scores["overall"] == d.scores["visibility"]  # domínio de demonstração: técnico não verificado
    assert d.plan["quick_wins"] and d.cost_usd >= 0

    from app.main import app

    app.state.office = office
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get(f"/relatorio/{d.token}")
        assert r.status_code == 200 and "Loja Exemplo" in r.text and "Pergunta por pergunta" in r.text and r.headers["x-robots-tag"].startswith("noindex")
        assert (await c.get("/relatorio/nao-existe")).status_code == 404
        listing = (await c.get("/api/office/diagnoses", headers=H)).json()
        assert listing[0]["report"] == f"/relatorio/{d.token}"
        made = (await c.post("/api/control/diagnoses", json={"brand": "Outra", "category": "pet shop"}, headers=H)).json()
        assert made["report"].startswith("/relatorio/")
        assert "Disallow: /relatorio/" in (await c.get("/robots.txt")).text
