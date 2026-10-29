"""Rastreador de IA: várias IAs (ChatGPT, Perplexity, Claude), % de recomendação por marca e PDF."""

from __future__ import annotations

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.core import diagnosis as dg
from app.core import engines

H = {"X-Founder-Token": "test-token"}


@pytest.mark.asyncio
async def test_engine_parsers(office):
    office.settings = office.settings.model_copy(update={"openai_api_key": "sk", "perplexity_api_key": "pk"})

    def handler(req: httpx.Request) -> httpx.Response:
        if "openai" in req.url.host:
            body = req.read().decode()
            assert '"tools"' in body and "web_search" in body
            return httpx.Response(200, json={"output": [{"type": "message", "content": [{"type": "output_text", "text": "Recomendo a Loja Boa.",
                                  "annotations": [{"type": "url_citation", "url": "https://lojaboa.com.br/x"}]}]}], "usage": {"input_tokens": 50, "output_tokens": 20}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "Opções: Rival [1]"}}], "citations": ["https://rival.com.br"], "usage": {"prompt_tokens": 30, "completion_tokens": 10}})

    t = httpx.MockTransport(handler)
    a = await engines.ask_chatgpt(office, "melhor loja?", transport=t)
    assert a.text == "Recomendo a Loja Boa." and a.urls == ["https://lojaboa.com.br/x"] and a.cost_usd > 0
    p = await engines.ask_perplexity(office, "melhor loja?", transport=t)
    assert p.urls == ["https://rival.com.br"] and "Rival" in p.text
    assert engines.available(office)[:1] == ["chatgpt"] and "perplexity" in engines.available(office)


def test_summarize_multi_engine():
    answers = [
        {"query": "q1", "engine": "chatgpt", "mentioned": ["Marca"], "sources": [], "excerpt": "a"},
        {"query": "q1", "engine": "perplexity", "mentioned": ["Rival"], "sources": [], "excerpt": "b"},
        {"query": "q2", "engine": "chatgpt", "mentioned": [], "sources": [], "excerpt": ""},
        {"query": "q2", "engine": "perplexity", "mentioned": [], "sources": [], "excerpt": "", "error": "timeout"},
    ]
    v = dg.summarize(answers, "Marca", [{"name": "Rival", "site": ""}])
    assert v["answers"] == 3 and v["failed"] == 1
    assert v["share"] == {"Marca": round(1 / 3, 3), "Rival": round(1 / 3, 3)}
    assert v["by_engine"]["chatgpt"]["Marca"] == 0.5 and v["by_engine"]["perplexity"]["Rival"] == 1.0
    assert v["rows"][0]["mentioned"] == ["Marca", "Rival"] and v["open"] == ["q2"]


@pytest.mark.asyncio
async def test_report_with_n_queries_and_pdf(office):
    d = await dg.create(office, brand="Loja Exemplo", site="", category="pet shop online", competitors="Rival Um\nRival Dois", query_count=20, engines=["chatgpt"])
    assert d.engines == ["simulado"]  # sem chaves: cai na IA configurada
    d = await dg.run(office, d.id)
    assert d.status == "done" and len(d.queries) == 20 and d.visibility["answers"] == 20

    from app.main import app

    app.state.office = office
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get(f"/relatorio/{d.token}.pdf")
        assert r.status_code == 200 and r.headers["content-type"] == "application/pdf" and r.content[:4] == b"%PDF" and len(r.content) > 2000
        html = await c.get(f"/relatorio/{d.token}")
        assert "Baixar PDF" in html.text
        info = (await c.get("/api/office/tracker", headers=H)).json()
        assert info["available"] == ["simulado"] and "20" in {str(k) for k in info["cost_per_report"]}
