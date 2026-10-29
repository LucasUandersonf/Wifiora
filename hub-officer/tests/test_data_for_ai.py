"""Dados para IAs: arquivos em lote (RAG direto), grafo de conhecimento, páginas de empresa e conceitos."""

from __future__ import annotations

import csv
import io
import json

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db import session_scope
from app.models import Hub
from app.skills.builtin.jsonld import graph_stats, validate_jsonld


@pytest.fixture
async def client(office):
    from app.main import app

    app.state.office = office
    await office.trigger_cycle("test")
    assert await office.wait_idle(timeout=60)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _hub_slug() -> str:
    async with session_scope() as s:
        return (await s.execute(select(Hub))).scalar_one().slug


@pytest.mark.asyncio
async def test_bulk_files_per_hub(client):
    slug = await _hub_slug()
    r = await client.get(f"/hub/{slug}/data.json")
    assert r.status_code == 200 and r.headers["access-control-allow-origin"] == "*"
    data = r.json()
    assert data["dataset"]["license"] == "CC-BY-4.0" and data["records"]
    rec = data["records"][0]
    assert rec["id"].endswith("#product") and rec["sources"] and rec["organization"]["id"].endswith("#org")

    lines = (await client.get(f"/hub/{slug}/data.jsonl")).text.strip().splitlines()
    assert len(lines) == len(data["records"])
    chunk = json.loads(lines[0])
    assert chunk["text"] and "Verificado em" in chunk["text"] and chunk["metadata"]["attribution"]

    rows = list(csv.reader(io.StringIO((await client.get(f"/hub/{slug}/data.csv")).text.lstrip("﻿"))))
    assert rows[0][:3] == ["id", "nome", "empresa"] and len(rows) == len(data["records"]) + 1

    md = (await client.get(f"/hub/{slug}/data.md")).text
    assert md.startswith("# ") and "| Nome |" in md and "## Fontes" in md

    # ETag: segunda leitura sem mudança devolve 304 (robôs não baixam de novo à toa)
    r1 = await client.get(f"/hub/{slug}/data.csv")
    r2 = await client.get(f"/hub/{slug}/data.csv", headers={"If-None-Match": r1.headers["etag"]})
    assert r2.status_code == 304

    # a página do hub anuncia os arquivos e o Dataset lista as distribuições
    page = (await client.get(f"/api/public/pages/hub/{slug}")).json()
    ds = next(n for n in page["jsonld"]["@graph"] if n.get("@type") == "Dataset")
    assert {d["contentUrl"].rsplit("/", 1)[1] for d in ds["distribution"]} >= {"data.jsonl", "data.csv", "data.json"}
    assert page["downloads"]


@pytest.mark.asyncio
async def test_site_wide_graph_is_closed(client):
    kg = (await client.get("/knowledge-graph.jsonld")).json()
    stats = graph_stats(kg)
    assert stats["dangling"] == [] and stats["nodes"] > 5
    assert validate_jsonld(kg) == []
    types = {t for n in kg["@graph"] for t in ([n["@type"]] if isinstance(n["@type"], str) else n["@type"])}
    assert {"Dataset", "DataCatalog", "Organization", "DefinedTerm", "Product"} <= types

    cat = (await client.get("/data/catalog.jsonld")).json()
    assert graph_stats(cat)["dangling"] == []
    assert (await client.get("/data/all.jsonl")).text.count("\n") >= 1
    full = (await client.get("/llms-full.txt")).text
    assert "CC BY 4.0" in full and "Verificado em" in full
    assert "knowledge-graph.jsonld" in (await client.get("/llms.txt")).text


@pytest.mark.asyncio
async def test_org_and_concept_pages(client):
    concepts = (await client.get("/api/public/pages/concepts")).json()
    assert concepts["orgs"] and concepts["integrations"]
    assert graph_stats(concepts["jsonld"])["dangling"] == []

    org_slug = concepts["orgs"][0]["slug"]
    org = (await client.get(f"/api/public/pages/org/{org_slug}")).json()
    assert org["products"] and graph_stats(org["jsonld"])["dangling"] == []
    assert validate_jsonld(org["jsonld"]) == []

    for path in (f"/empresa/{org_slug}", "/conceitos", "/dados"):
        r = await client.get(path)
        assert r.status_code == 200 and "application/ld+json" in r.text, path
    assert (await client.get("/empresa/nao-existe")).status_code == 404

    sitemap = (await client.get("/sitemap.xml")).text
    assert f"/empresa/{org_slug}" in sitemap and "/dados" in sitemap


@pytest.mark.asyncio
async def test_ai_bot_counter_and_dashboard(client, monkeypatch):
    from app.config import get_settings
    from app.core.bots import classify_bot, path_kind

    assert classify_bot("Mozilla/5.0 (compatible; GPTBot/1.2; +https://openai.com/gptbot)") == "GPTBot"
    assert classify_bot("Mozilla/5.0 AppleWebKit Chrome/120") is None
    assert path_kind("/hub/x/data.jsonl") == "data" and path_kind("/knowledge-graph.jsonld") == "graph"

    slug = await _hub_slug()
    await client.get(f"/hub/{slug}/data.csv", headers={"User-Agent": "Mozilla/5.0 (compatible; ClaudeBot/1.0)"})
    await client.get("/knowledge-graph.jsonld", headers={"User-Agent": "PerplexityBot/1.0"})
    await client.get(f"/hub/{slug}", headers={"User-Agent": "Mozilla/5.0 Chrome/120"})  # humano: não conta

    # beacon do portal: sem segredo é recusado; com segredo conta
    monkeypatch.setenv("REVALIDATE_SECRET", "s3gredo")
    get_settings.cache_clear()
    assert (await client.post("/api/public/bot-hit", json={"user_agent": "GPTBot", "path": "/hub/x"})).status_code == 401
    r = await client.post("/api/public/bot-hit", json={"user_agent": "GPTBot/1.2", "path": f"/hub/{slug}"}, headers={"X-Beacon-Secret": "s3gredo"})
    assert r.json() == {"bot": "GPTBot"}

    data = (await client.get("/api/office/ai-data", headers={"X-Founder-Token": "test-token"})).json()
    bots = {b["bot"]: b for b in data["bots"]["bots"]}
    assert bots["ClaudeBot"]["data"] == 1 and bots["PerplexityBot"]["graph"] == 1 and bots["GPTBot"]["page"] == 1
    assert data["bots"]["data_downloads"] == 2 and data["graph"]["dangling"] == [] and data["graph"]["orgs"] >= 1
