"""Visão do site inteiro: grafo de conhecimento, páginas de empresa/conceitos e arquivos em lote para IAs.

Tudo sai do mesmo banco e das mesmas funções de `semantic.py`, então os @id são idênticos em HTML,
JSON-LD, JSONL, CSV e Markdown — uma IA que baixa o arquivo encontra os mesmos nós que lê na página.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select

from app.config import get_settings
from app.core.semantic import base_url, criteria_results, entity_node, entity_url, graph_parts, product_id, support_nodes
from app.db import session_scope
from app.models import Entity, Hub
from app.skills.builtin.jsonld import (
    SCHEMA_CONTEXT,
    _slug,
    breadcrumb,
    concept_node,
    org_node,
    org_slug,
    ref,
    term_set_node,
    website_node,
)

LICENSE = "https://creativecommons.org/licenses/by/4.0/"
LICENSE_ID = "CC-BY-4.0"


def hide_demo() -> bool:
    """Em produção, hubs de demonstração ficam fora do sitemap, llms.txt, listagens e arquivos em lote."""
    return get_settings().app_env == "production"


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _site_org() -> dict[str, Any]:
    st = get_settings()
    return {"@type": "Organization", "@id": f"{base_url()}/#org", "name": st.brand_name, "url": base_url() + "/"}


def attribution(hub: Hub, entity: Entity | None = None) -> str:
    brand = get_settings().brand_name
    where = entity_url(hub, entity) if entity else f"{base_url()}/hub/{hub.slug}"
    return f"Fonte: {brand} ({where}), licença CC BY 4.0."


@dataclass
class Site:
    hubs: list[tuple[Hub, list[Entity]]] = field(default_factory=list)

    @property
    def pairs(self) -> list[tuple[Hub, Entity]]:
        return [(h, e) for h, ents in self.hubs for e in ents]

    @property
    def last_modified(self) -> datetime | None:
        dates = [e.updated_at for _, e in self.pairs] + [h.updated_at for h, _ in self.hubs]
        return max(dates, default=None)


async def load_site() -> Site:
    async with session_scope() as s:
        q = select(Hub).where(Hub.status == "published").order_by(Hub.title)
        if hide_demo():
            q = q.where(Hub.demo_data.is_(False))
        hubs = list((await s.execute(q)).scalars())
        out = Site()
        for h in hubs:
            ents = list((await s.execute(select(Entity).where(Entity.hub_id == h.id, Entity.status == "published").order_by(Entity.name))).scalars())
            out.hubs.append((h, ents))
        return out


# ------------------------------------------------------------------ índices do grafo
def _org_info(hub: Hub, e: Entity) -> dict[str, Any] | None:
    node = org_node(base_url(), e.provider or None, site=(e.attributes or {}).get("site_oficial"))
    if node is None:
        return None
    return {"slug": org_slug(e.provider), "node": node}


def _product_ref(hub: Hub, e: Entity) -> dict[str, Any]:
    return {"hub": hub.slug, "hub_title": hub.title, "slug": e.slug, "name": e.name, "url": entity_url(hub, e), "demo_data": hub.demo_data}


def org_index(site: Site) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for h, e in site.pairs:
        info = _org_info(h, e)
        if info is None:
            continue
        row = out.setdefault(info["slug"], {"node": info["node"], "provider": e.provider or {}, "products": [], "concepts": [], "integrations": []})
        row["products"].append(_product_ref(h, e))
        parts = graph_parts(h, e)
        row["concepts"] = list(dict.fromkeys(row["concepts"] + parts["concepts"]))
        row["integrations"] = list(dict.fromkeys(row["integrations"] + parts["integrations"]))
    return out


def concept_index(site: Site) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for h, e in site.pairs:
        parts = graph_parts(h, e)
        org = _org_info(h, e)
        for kind, labels in (("concept", parts["concepts"]), ("integration", parts["integrations"])):
            for label in labels:
                row = out.setdefault(_slug(label), {"slug": _slug(label), "label": label, "kind": kind, "products": [], "orgs": []})
                row["products"].append(_product_ref(h, e))
                if org and org["slug"] not in row["orgs"]:
                    row["orgs"].append(org["slug"])
    return dict(sorted(out.items(), key=lambda kv: (-len(kv[1]["products"]), kv[1]["label"].lower())))


def _product_stub(hub: Hub, e: Entity, org: dict[str, Any] | None) -> dict[str, Any]:
    types = [e.schema_type] + (["Product"] if e.schema_type != "Product" else [])
    stub: dict[str, Any] = {"@type": types, "@id": product_id(hub, e), "name": e.name, "url": entity_url(hub, e)}
    if "SoftwareApplication" in types:
        stub["applicationCategory"] = "BusinessApplication"
    if org:
        stub["manufacturer"] = ref(org)
    return stub


# ------------------------------------------------------------------ páginas: empresa e conceitos
async def org_payload(slug: str) -> dict[str, Any] | None:
    site = await load_site()
    row = org_index(site).get(slug)
    if row is None:
        return None
    base, brand = base_url(), get_settings().brand_name
    org = row["node"]
    page_url = f"{base}/empresa/{slug}"
    pairs = {(p["hub"], p["slug"]) for p in row["products"]}
    stubs = [_product_stub(h, e, org) for h, e in site.pairs if (h.slug, e.slug) in pairs]
    concepts = [concept_node(base, c) for c in row["concepts"]] + [concept_node(base, i, kind="integration") for i in row["integrations"]]
    org_full = {**org, "knowsAbout": [ref(c) for c in concepts]} if concepts else org
    graph = [
        _site_org(),
        website_node(base, brand),
        {"@type": "ProfilePage", "@id": page_url, "url": page_url, "name": org["name"], "inLanguage": "pt-BR", "isPartOf": {"@id": f"{base}/#website"}, "mainEntity": ref(org)},
        org_full,
        {"@type": "ItemList", "@id": page_url + "#produtos", "name": f"Produtos de {org['name']}", "itemListElement": [{"@type": "ListItem", "position": i + 1, "item": ref(s)} for i, s in enumerate(stubs)]},
        *stubs,
        *concepts,
        *([term_set_node(base, brand)] if concepts else []),
        breadcrumb([("Início", base + "/"), ("Empresas", f"{base}/conceitos"), (org["name"], page_url)]),
    ]
    p = row["provider"]
    return {
        "org": {
            "slug": slug,
            "name": org["name"],
            "legal_name": p.get("razao_social"),
            "cnpj": p.get("cnpj"),
            "city": p.get("municipio"),
            "uf": p.get("uf"),
            "site": org.get("url"),
            "wikidata": p.get("wikidata"),
        },
        "products": row["products"],
        "concepts": row["concepts"],
        "integrations": row["integrations"],
        "demo_data": all(x["demo_data"] for x in row["products"]),
        "jsonld": {"@context": SCHEMA_CONTEXT, "@graph": graph},
    }


async def concepts_payload() -> dict[str, Any]:
    site = await load_site()
    idx = concept_index(site)
    orgs = org_index(site)
    base, brand = base_url(), get_settings().brand_name
    page_url = f"{base}/conceitos"
    terms = []
    for c in idx.values():
        node = concept_node(base, c["label"], kind=c["kind"])
        node["url"] = f"{page_url}#{c['slug']}"
        terms.append(node)
    term_set = {**term_set_node(base, brand), "hasDefinedTerm": terms} if terms else term_set_node(base, brand)
    graph = [
        _site_org(),
        website_node(base, brand),
        {"@type": "CollectionPage", "@id": page_url, "url": page_url, "name": f"Conceitos e integrações do {brand}", "inLanguage": "pt-BR", "isPartOf": {"@id": f"{base}/#website"}, "mainEntity": ref(term_set)},
        term_set,
        breadcrumb([("Início", base + "/"), ("Conceitos", page_url)]),
    ]
    return {
        "concepts": [c for c in idx.values() if c["kind"] == "concept"],
        "integrations": [c for c in idx.values() if c["kind"] == "integration"],
        "orgs": [{"slug": s, "name": r["node"]["name"], "products": len(r["products"])} for s, r in sorted(orgs.items(), key=lambda kv: kv[1]["node"]["name"].lower())],
        "jsonld": {"@context": SCHEMA_CONTEXT, "@graph": graph},
    }


# ------------------------------------------------------------------ grafo completo do site
async def knowledge_graph(site: Site | None = None) -> dict[str, Any]:
    """Todos os produtos, empresas, conceitos e datasets num só documento, sem pontas soltas."""
    site = site or await load_site()
    base, brand = base_url(), get_settings().brand_name
    nodes: dict[str, dict[str, Any]] = {}
    graph: list[dict[str, Any]] = [
        _site_org(),
        website_node(base, brand),
        catalog_node(site),
    ]
    for h, ents in site.hubs:
        graph.append(_dataset_stub(h, ents))
        for e in ents:
            node = entity_node(h, e, similar=ents)
            node["isPartOf"] = {"@id": f"{base}/hub/{h.slug}#dataset"}
            graph.append(node)
        for n in support_nodes(h, ents):
            nodes.setdefault(n["@id"], n)
    graph.extend(nodes.values())
    return {"@context": SCHEMA_CONTEXT, "@graph": graph}


def _dataset_stub(h: Hub, ents: list[Entity]) -> dict[str, Any]:
    base = base_url()
    hub_url = f"{base}/hub/{h.slug}"
    return {
        "@type": "Dataset",
        "@id": f"{hub_url}#dataset",
        "name": h.title,
        "description": h.description or h.title,
        "url": hub_url,
        "license": LICENSE,
        "isAccessibleForFree": True,
        "creator": {"@id": f"{base}/#org"},
        "dateModified": _iso(max((e.updated_at for e in ents), default=h.updated_at)),
        "includedInDataCatalog": {"@id": f"{base}/data/catalog.jsonld#catalog"},
        "distribution": distributions(h),
    }


def catalog_node(site: Site) -> dict[str, Any]:
    base, brand = base_url(), get_settings().brand_name
    return {
        "@type": "DataCatalog",
        "@id": f"{base}/data/catalog.jsonld#catalog",
        "name": f"Dados abertos do {brand}",
        "url": f"{base}/dados",
        "license": LICENSE,
        "publisher": {"@id": f"{base}/#org"},
        "dataset": [{"@id": f"{base}/hub/{h.slug}#dataset"} for h, _ in site.hubs],
    }


async def catalog_jsonld() -> dict[str, Any]:
    site = await load_site()
    base, brand = base_url(), get_settings().brand_name
    return {"@context": SCHEMA_CONTEXT, "@graph": [_site_org(), website_node(base, brand), catalog_node(site), *(_dataset_stub(h, e) for h, e in site.hubs)]}


# ------------------------------------------------------------------ arquivos em lote (RAG direto)
FORMATS = {
    "data.jsonld": ("application/ld+json", "Grafo Schema.org do hub"),
    "data.json": ("application/json", "Tabela em JSON (uma linha por produto)"),
    "data.jsonl": ("application/x-ndjson", "Um bloco autocontido por produto, pronto para RAG"),
    "data.csv": ("text/csv", "Tabela limpa em CSV (UTF-8)"),
    "data.md": ("text/markdown", "Tabela em Markdown com fontes"),
}


def distributions(h: Hub) -> list[dict[str, Any]]:
    hub_url = f"{base_url()}/hub/{h.slug}"
    return [
        {"@type": "DataDownload", "name": desc, "encodingFormat": mime, "contentUrl": f"{hub_url}/{name}", "license": LICENSE}
        for name, (mime, desc) in FORMATS.items()
    ]


def _columns(h: Hub, ents: list[Entity]) -> list[str]:
    fields = [f.get("name") for f in ((h.schema_template or {}).get("fields") or []) if f.get("name")]
    extra = sorted({k for e in ents for k in (e.attributes or {})} - set(fields))
    return fields + extra


def _cell(v: Any) -> Any:
    if isinstance(v, list):
        return "; ".join(str(i) for i in v)
    return v


def entity_record(h: Hub, e: Entity) -> dict[str, Any]:
    """Linha da tabela: atributos + empresa + proveniência, com os mesmos @id do grafo."""
    p = e.provider or {}
    org = _org_info(h, e)
    parts = graph_parts(h, e)
    known = [r for r in criteria_results(h, e) if r["passed"] is not None]
    return {
        "id": product_id(h, e),
        "hub": h.slug,
        "slug": e.slug,
        "name": e.name,
        "type": e.schema_type,
        "url": entity_url(h, e),
        "organization": {"id": org["node"]["@id"], "name": org["node"]["name"], "cnpj": p.get("cnpj"), "wikidata": p.get("wikidata")} if org else None,
        "attributes": e.attributes or {},
        "concepts": parts["concepts"],
        "integrations": parts["integrations"],
        "criteria": {"met": sum(1 for r in known if r["passed"]), "total": len(known)},
        "sources": [{"url": s.get("url"), "quote": s.get("quote"), "retrieved_at": s.get("retrieved_at")} for s in (e.sources or []) if s.get("url")],
        "grounding_ratio": e.grounding_ratio,
        "human_reviewed": bool(e.human_reviewed_at),
        "verified_at": _iso(e.verified_at or e.updated_at),
        "version": e.version,
        "updated_at": _iso(e.updated_at),
        "demo_data": h.demo_data,
    }


def _fmt(v: Any) -> str:
    if isinstance(v, bool):
        return "Sim" if v else "Não"
    if isinstance(v, list):
        return ", ".join(str(i) for i in v)
    return "—" if v in (None, "") else str(v)


def entity_text(h: Hub, e: Entity) -> str:
    """Texto curto e autocontido — o "chunk" que um sistema de RAG indexa sem precisar da página."""
    r = entity_record(h, e)
    org = r["organization"] or {}
    lines = [f"{e.name} — {h.title}."]
    if org:
        lines.append(f"Empresa: {org['name']}" + (f" (CNPJ {org['cnpj']})" if org.get("cnpj") else "") + ".")
    integration_fields = {f.get("name") for f in ((h.schema_template or {}).get("fields") or []) if f.get("graph_role") == "integrations"}
    for k, v in (e.attributes or {}).items():
        if k != "site_oficial" and k not in integration_fields:
            lines.append(f"{k.replace('_', ' ')}: {_fmt(v)}.")
    if r["integrations"]:
        lines.append("Integrações: " + ", ".join(r["integrations"]) + ".")
    lines.append(f"Verificado em {(r['verified_at'] or '')[:10]}; fontes: " + ", ".join(s["url"] for s in r["sources"]) + ".")
    if h.demo_data:
        lines.append("ATENÇÃO: dado de demonstração (fictício).")
    return " ".join(lines)


def hub_json(h: Hub, ents: list[Entity]) -> dict[str, Any]:
    return {
        "dataset": {
            "id": f"{base_url()}/hub/{h.slug}#dataset",
            "title": h.title,
            "niche": h.niche,
            "description": h.description,
            "url": f"{base_url()}/hub/{h.slug}",
            "license": LICENSE_ID,
            "attribution": attribution(h),
            "columns": _columns(h, ents),
            "updated_at": _iso(max((e.updated_at for e in ents), default=h.updated_at)),
            "demo_data": h.demo_data,
            "note": "Instantâneo atual e gratuito. Histórico de versões e busca entre hubs: API v1 (com chave).",
        },
        "records": [entity_record(h, e) for e in ents],
    }


def hub_jsonl(h: Hub, ents: list[Entity]) -> str:
    rows = []
    for e in ents:
        rec = entity_record(h, e)
        rows.append({"id": rec["id"], "text": entity_text(h, e), "metadata": {**rec, "license": LICENSE_ID, "attribution": attribution(h, e)}})
    return "".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in rows)


def hub_csv(h: Hub, ents: list[Entity]) -> str:
    cols = _columns(h, ents)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "nome", "empresa", "cnpj", *cols, "integracoes", "fontes", "verificado_em", "versao"])
    for e in ents:
        r = entity_record(h, e)
        org = r["organization"] or {}
        w.writerow([
            r["id"], e.name, org.get("name", ""), org.get("cnpj") or "",
            *[_cell((e.attributes or {}).get(c, "")) for c in cols],
            "; ".join(r["integrations"]), " ".join(s["url"] for s in r["sources"]), (r["verified_at"] or "")[:10], e.version,
        ])
    return buf.getvalue()


def _md(v: Any) -> str:
    return _fmt(v).replace("|", "\\|").replace("\n", " ")


def hub_markdown(h: Hub, ents: list[Entity]) -> str:
    cols = [c for c in _columns(h, ents) if c != "site_oficial"][:8]
    out = [f"# {h.title}", ""]
    if h.demo_data:
        out += ["> ATENÇÃO: dados de demonstração (fictícios).", ""]
    if h.description:
        out += [h.description, ""]
    out += [f"Licença CC BY 4.0. {attribution(h)}", ""]
    out.append("| Nome | Empresa | " + " | ".join(c.replace("_", " ") for c in cols) + " | Verificado em |")
    out.append("|" + "---|" * (len(cols) + 3))
    for e in ents:
        r = entity_record(h, e)
        org = (r["organization"] or {}).get("name", "—")
        out.append(f"| [{_md(e.name)}]({r['url']}) | {_md(org)} | " + " | ".join(_md((e.attributes or {}).get(c)) for c in cols) + f" | {(r['verified_at'] or '')[:10]} |")
    out += ["", "## Fontes", ""]
    for e in ents:
        for s in entity_record(h, e)["sources"]:
            out.append(f"- {e.name}: {s['url']}")
    return "\n".join(out) + "\n"


async def llms_full(site: Site | None = None) -> str:
    """Versão longa do llms.txt: todo o conteúdo verificado em texto corrido, um bloco por produto."""
    site = site or await load_site()
    st = get_settings()
    out = [f"# {st.brand_name} — conteúdo completo", "", f"> Dados estruturados e verificados. Licença CC BY 4.0. Catálogo: {base_url()}/data/catalog.jsonld", ""]
    for h, ents in site.hubs:
        out += [f"## {h.title}", "", f"URL: {base_url()}/hub/{h.slug} · Arquivos: {base_url()}/hub/{h.slug}/data.jsonl, data.csv, data.json", ""]
        out += [f"- {entity_text(h, e)}" for e in ents]
        out.append("")
    return "\n".join(out)


async def all_jsonl(site: Site | None = None) -> str:
    site = site or await load_site()
    return "".join(hub_jsonl(h, ents) for h, ents in site.hubs)
