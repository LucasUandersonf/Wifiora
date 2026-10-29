"""Skills operacionais: finanças, infraestrutura e auditoria GEO."""

from __future__ import annotations

import os
from urllib.parse import urlparse
import time
from typing import Any

from sqlalchemy import text

from app.db import session_scope
from app.skills.base import Skill, SkillError


class CostReportSkill(Skill):
    name = "cost_report"
    description = "Resumo financeiro do ledger: gasto diário/mensal, por agente, caixa, burn e runway."
    sectors = ("finance", "orchestrator")

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        if not self.office:
            raise SkillError("cost_report requer o escritório")
        return await self.office.ledger.summary()


class HealthCheckSkill(Skill):
    name = "infra_health"
    description = "Verifica saúde de PostgreSQL, barramento (Redis) e metadados do deploy Railway."
    sectors = ("tech",)

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        checks: dict[str, Any] = {}
        t0 = time.perf_counter()
        try:
            async with session_scope() as s:
                await s.execute(text("SELECT 1"))
            checks["database"] = {"ok": True, "latency_ms": round((time.perf_counter() - t0) * 1000, 1)}
        except Exception as e:
            checks["database"] = {"ok": False, "error": str(e)}
        if self.office:
            t1 = time.perf_counter()
            ok = await self.office.bus.ping()
            checks["bus"] = {"ok": ok, "backend": self.office.bus.name, "latency_ms": round((time.perf_counter() - t1) * 1000, 1)}
            checks["queues"] = await self.office.bus.queue_depths()
        checks["deploy"] = {
            "platform": "railway" if os.getenv("RAILWAY_ENVIRONMENT_NAME") else "local",
            "environment": os.getenv("RAILWAY_ENVIRONMENT_NAME"),
            "service": os.getenv("RAILWAY_SERVICE_NAME"),
            "commit": os.getenv("RAILWAY_GIT_COMMIT_SHA"),
            "public_domain": os.getenv("RAILWAY_PUBLIC_DOMAIN"),
        }
        checks["all_ok"] = all(v.get("ok", True) for v in checks.values() if isinstance(v, dict) and "ok" in v)
        return checks


class PageRenderSkill(Skill):
    name = "page_render"
    description = "Renderiza a página SSR de um hub e mede tamanho/presença de JSON-LD (orçamento de performance para crawlers de LLM)."
    sectors = ("tech",)

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        from app.web.render import render_hub_page

        html = await render_hub_page(kwargs["hub_id"], include_drafts=True, page_config=kwargs.get("page_config"))
        if html is None:
            raise SkillError("hub não encontrado")
        size = len(html.encode("utf-8"))
        graph = _page_graph_stats(html)
        return {
            "graph_nodes": graph["nodes"],
            "graph_dangling": graph["dangling"],
            "has_downloads": 'id="dados"' in html,
            "html_bytes": size,
            "has_jsonld": '<script type="application/ld+json">' in html,
            "script_tags": html.count("<script") - html.count('<script type="application/ld+json"'),
            "has_meta_description": 'name="description"' in html,
        }


def _page_graph_stats(html: str) -> dict[str, Any]:
    """Junta todos os blocos JSON-LD da página e conta nós e pontas soltas (referências sem nó)."""
    import json
    import re

    from app.skills.builtin.jsonld import graph_stats

    blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    graph: list[Any] = []
    for b in blocks:
        try:
            doc = json.loads(b.replace("<\\/", "</"))
        except ValueError:
            return {"nodes": 0, "dangling": ["<json-ld inválido>"]}
        graph.extend(doc.get("@graph", [doc]))
    return graph_stats({"@graph": graph})


class DataDistributionSkill(Skill):
    """Confere se os arquivos em lote e o grafo do site estão saudáveis e quem está baixando."""

    name = "data_distribution_check"
    description = "Gera os arquivos de dados (JSON/JSONL/CSV/grafo), confere pontas soltas no grafo e resume os acessos de robôs de IA."
    sectors = ("tech",)

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        from app.core import bots
        from app.core import knowledge as kg
        from app.skills.builtin.jsonld import graph_stats

        site = await kg.load_site()
        graph = graph_stats(await kg.knowledge_graph(site))
        files_ok, problems = 0, []
        for h, ents in site.hubs:
            try:
                kg.hub_json(h, ents), kg.hub_jsonl(h, ents), kg.hub_csv(h, ents), kg.hub_markdown(h, ents)
                files_ok += 1
            except Exception as exc:
                problems.append(f"{h.slug}: {exc}")
        hits = await bots.summary(days=7)
        return {
            "hubs": len(site.hubs),
            "hubs_with_files": files_ok,
            "graph_nodes": graph["nodes"],
            "graph_edges": graph["edges"],
            "graph_dangling": graph["dangling"][:20],
            "problems": problems,
            "bot_hits_7d": hits["total"],
            "bot_data_downloads_7d": hits["data_downloads"],
            "bots_7d": [b["bot"] for b in hits["bots"]],
            "ok": not problems and not graph["dangling"],
        }


class GeoCitationAuditSkill(Skill):
    """Mede o Share of Voice: faz as perguntas-alvo a um assistente de IA e verifica se o portal aparece.

    * Modo `web` (provedor Anthropic): o assistente responde COM busca na web; contamos as respostas
      que citam uma URL do nosso domínio (e, à parte, as em que ele ao menos viu o portal nos resultados).
    * Modo `parametric` (outros provedores): só o conhecimento interno do modelo — serve de linha de base.
    """

    name = "geo_citation_audit"
    description = "Envia consultas-alvo a um assistente de IA (com busca na web quando disponível) e calcula o Share of Voice do portal."
    sectors = ("research", "orchestrator")

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        if not self.office:
            raise SkillError("geo_citation_audit requer o escritório")
        st = self.office.settings
        queries: list[str] = kwargs.get("queries", [])[:10]
        domain = (urlparse(st.public_base_url).hostname or "").removeprefix("www.")
        brand = st.brand_name.lower()
        llm = self.office.llm
        results, cited_n, seen_n = [], 0, 0
        web = llm.can_search and llm.client.provider == "anthropic"
        for q in queries:
            if web:
                res = await llm.search(prompt=q, agent_id=kwargs.get("agent_id"))
                ours = [u for u in res.urls if domain and domain in (urlparse(u).hostname or "")]
                seen = [u for u in res.seen_urls if domain and domain in (urlparse(u).hostname or "")]
                cited = bool(ours)
                seen_n += int(bool(seen) or cited)
                results.append({"query": q, "cited": cited, "seen": bool(seen) or cited, "our_urls": ours[:5], "top_sources": res.urls[:5]})
            else:
                res = await llm.complete(kind="geo.audit", system="Você é um assistente de busca. Responda citando fontes.", prompt=q, tier="judge", agent_id=kwargs.get("agent_id"))
                cited = (domain and domain in res.text.lower()) or brand in res.text.lower()
                results.append({"query": q, "cited": bool(cited)})
            cited_n += int(bool(results[-1]["cited"]))
        n = len(queries) or 1
        return {
            "mode": "web" if web else "parametric",
            "share_of_voice": round(cited_n / n, 3) if queries else 0.0,
            "seen_rate": round(seen_n / n, 3) if (queries and web) else None,
            "results": results,
        }
