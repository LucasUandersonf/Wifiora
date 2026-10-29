"""Setor de Pesquisa, Inteligência & GEO."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select

from app.agents.specialist import SpecialistAgent
from app.core import niches
from app.db import session_scope
from app.models import Hub, Objective, Task
from app.skills.builtin.jsonld import entity_jsonld, validate_jsonld
from app.skills.builtin.web import only_digits, valid_cnpj

# O mapa de nichos vem do catálogo (app/core/niches.py), editável pelo painel.


class MarketResearchAgent(SpecialistAgent):
    agent_id = "research.market"
    title = "Market Research Agent"
    sector = "research"
    task_kind = "market_research"
    skill_names = ("geo_citation_audit",)
    mission = "Mapear nichos com volume no Brasil onde LLMs alucinam e existe dado oficial para verificar e definir as entidades e consultas-alvo do hub."

    async def execute(self, task: Task, deps: dict[str, dict[str, Any]], objective: Objective) -> dict[str, Any]:
        async with session_scope() as s:
            hubs = (await s.execute(select(Hub.slug, Hub.title, Hub.status, Hub.research))).all()
        existing = [{"slug": h.slug, "title": h.title, "status": h.status} for h in hubs]
        prompt = self.task_prompt(
            task,
            objective,
            f"{await niches.playbook()}\nHubs já existentes (não duplique; amplie ou escolha subnicho): {existing}\n\n"
            "Retorne JSON com: niche, hub_title, hub_slug (kebab-case), entity_type (tipo Schema.org), "
            "hallucination_pain, target_queries (5-10 perguntas reais de usuários), "
            "candidate_entities [{name, website, pricing_url?, cnpj?}] (5-15 fornecedores reais e verificáveis), "
            "monetization_signals [..].",
        )
        out = await self.think("market_research", prompt, context={"niche": objective.niche}, objective_id=task.objective_id, task_id=task.id)

        # Feedback loop GEO: mede Share of Voice dos hubs publicados (fora do modo mock).
        published = [h for h in hubs if h.status == "published" and (h.research or {}).get("target_queries")]
        if published and self.office.llm.client.provider != "mock" and "geo_citation_audit" in self.skills:
            h = published[0]
            out["geo_audit"] = {"hub": h.slug, **await self.use("geo_citation_audit", queries=h.research["target_queries"], agent_id=self.agent_id)}
        return out


class SchemaOntologyAgent(SpecialistAgent):
    agent_id = "research.schema"
    title = "Schema & Ontology Specialist"
    sector = "research"
    task_kind = "schema_design"
    skill_names = ("jsonld_validator", "jsonld_generator")
    mission = "Projetar esquemas JSON-LD (Schema.org: Dataset, Product, SoftwareApplication, Review, TechArticle, Organization) aninhados e fáceis de extrair por LLMs."

    async def execute(self, task: Task, deps: dict[str, dict[str, Any]], objective: Objective) -> dict[str, Any]:
        research = deps.get("market_research", {})
        prompt = self.task_prompt(
            task,
            objective,
            f"Pesquisa de mercado aprovada:\n{self.dumps(research, 4000)}\n\n"
            "Projete o schema das entidades do hub. Retorne JSON com: entity_schema_type, "
            "fields [{name (snake_case pt-BR), type (number|integer|boolean|string|url|list), schema_property, required, "
            "graph_role (feature = sim/não que vira recurso; concept = valores que viram conceitos compartilhados, ex.: regimes; "
            "integrations = lista de sistemas com que o produto integra; none), concept_label (nome curto do recurso, para feature), "
            "rank (opcional, só em campos numéricos objetivos: asc = menor é melhor, ex. preço; desc = maior é melhor), rank_label (título do ranking)}]. "
            "Inclua um campo 'integracoes' (list, graph_role integrations): o grafo de conhecimento liga produtos a empresas, "
            "conceitos e integrações. "
            'jsonld_template (objeto com "@context": "https://schema.org", "@type" e propriedades fixas), dataset_strategy, '
            "review_criteria [{label (frase curta em pt-BR), field (um dos fields), op (eq|lte|gte|contains|present), value}] "
            "— 3 a 6 critérios OBJETIVOS e relevantes para quem compra (nada de opinião ou nota).",
        )
        out = await self.think("schema_design", prompt, objective_id=task.objective_id, task_id=task.id)
        tpl = out.get("jsonld_template") or {}
        sample_attrs = {f.get("name", "campo"): 1 for f in (out.get("fields") or [])}
        sample = entity_jsonld(
            name="Entidade de Exemplo",
            schema_type=out.get("entity_schema_type") or tpl.get("@type") or "Thing",
            attributes=sample_attrs,
            sources=[{"url": "https://exemplo.org"}],
            template={k: v for k, v in tpl.items() if k not in ("@context", "@type")},
        )
        out["validation"] = {"problems": validate_jsonld(sample)}
        return out


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


class DataExtractionAgent(SpecialistAgent):
    agent_id = "research.extraction"
    title = "Data Extraction & Validation Agent"
    sector = "research"
    task_kind = "data_extraction"
    skill_names = ("web_fetch_many", "data_validator", "cnpj_lookup", "wikidata_by_cnpj")
    mission = "Coletar, limpar e validar dados exatos de fontes oficiais. Nunca preencher um valor sem citação literal da fonte."

    async def execute(self, task: Task, deps: dict[str, dict[str, Any]], objective: Objective) -> dict[str, Any]:
        research = deps.get("market_research", {})
        schema = deps.get("schema_design", {})
        candidates = research.get("candidate_entities") or []
        fields = schema.get("fields") or []
        required = [f["name"] for f in fields if f.get("required") and f.get("name")]

        live = self.office.llm.client.provider != "mock" and self.office.settings.allow_web_fetch
        pages: list[dict[str, Any]] = []
        if live and candidates:
            urls = []
            for c in candidates[:15]:
                urls += [u for u in (c.get("pricing_url"), c.get("website")) if u]
            pages = (await self.use("web_fetch_many", urls=list(dict.fromkeys(urls))[:25]))["pages"]
        ok_pages = [p for p in pages if "text" in p]
        evidence = "\n\n".join(f"### FONTE {p['url']}\n{p['text'][:6000]}" for p in ok_pages)

        prompt = self.task_prompt(
            task,
            objective,
            f"Campos do schema: {self.dumps(fields, 3000)}\nEntidades candidatas: {self.dumps(candidates, 3000)}\n"
            + (f"\nCONTEÚDO COLETADO (única fonte de verdade permitida):\n{evidence[:60000]}\n" if evidence else "")
            + "\nExtraia as entidades. Para CADA valor, inclua em sources uma citação literal (quote) copiada do conteúdo "
            "coletado que contenha o valor exato. Valor sem evidência = null. Se o CNPJ do fornecedor aparecer no conteúdo "
            "(ex.: rodapé), inclua attributes.cnpj com a citação. Retorne JSON: "
            "{entities: [{name, attributes: {campo: valor}, sources: [{url, quote}], confidence}], notes}.",
        )
        out = await self.think(
            "data_extraction",
            prompt,
            context={"feedback": task.feedback, "candidates": candidates},
            objective_id=task.objective_id,
            task_id=task.id,
        )
        entities = out.get("entities") or []

        # Anti-alucinação: a citação precisa existir literalmente na página baixada.
        if live:
            page_text = {p["url"]: _norm(p["text"]) for p in ok_pages}
            all_text = " ".join(page_text.values())
            for e in entities:
                verified = []
                for src in e.get("sources") or []:
                    if _norm(src.get("quote", ""))[:300] and _norm(src.get("quote", ""))[:300] in page_text.get(src.get("url"), all_text):
                        verified.append({**src, "verified": True})
                e["sources"] = verified

        # Cadastro público do fornecedor (CNPJ -> razão social, cidade/UF) para a Organization no JSON-LD.
        cand_cnpj = {c.get("name"): c.get("cnpj") for c in candidates if c.get("cnpj")}
        for e in entities:
            cnpj = only_digits((e.get("attributes") or {}).get("cnpj") or cand_cnpj.get(e.get("name")) or "")
            if not valid_cnpj(cnpj):
                (e.get("attributes") or {}).pop("cnpj", None)
                continue
            e.setdefault("attributes", {})["cnpj"] = cnpj
            if live:
                try:
                    e["provider"] = await self.use("cnpj_lookup", cnpj=cnpj)
                except Exception as err:
                    self.log.info("CNPJ %s sem cadastro: %s", cnpj, err)
                    e["provider"] = {"cnpj": cnpj}
                try:  # âncora no grafo público: só com CNPJ idêntico no Wikidata
                    qid = (await self.use("wikidata_by_cnpj", cnpj=cnpj)).get("wikidata")
                    if qid:
                        e["provider"]["wikidata"] = qid
                except Exception as err:
                    self.log.info("Wikidata indisponível para %s: %s", cnpj, err)
        for e in entities:
            e.setdefault("provider", e.get("provider") or {})

        validation = await self.use("data_validator", entities=entities, required_fields=required)
        return {
            "entities": entities,
            "validation": validation,
            "mode": "live" if live else "demo",
            "fetched_pages": len(ok_pages),
            "fetch_errors": [p for p in pages if "error" in p][:10],
            "notes": out.get("notes"),
        }
