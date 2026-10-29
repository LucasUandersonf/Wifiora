"""Monta o grafo semântico a partir do banco — fonte única para HTML, API pública, arquivos em lote e portal.

Grafo de conhecimento do nicho:
    Produto ──manufacturer──> Empresa (página /empresa/<slug>, CNPJ, sameAs site/Wikidata)
       │──keywords──────────> Conceito (DefinedTerm compartilhado: "Simples Nacional", "Emissão de NF-e"…)
       │──isRelatedTo───────> Integração (DefinedTerm: "Pix", "SEFAZ"…)
       └──isSimilarTo───────> outros produtos do mesmo hub (alternativas)
Os nós usam @id estáveis, então o mesmo conceito ou empresa conecta produtos de hubs diferentes.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import func, select

from app.config import get_settings
from app.db import session_scope
from app.models import Entity, EntityVersion, Hub
from app.skills.builtin.jsonld import (
    concept_node,
    editorial_review,
    entity_jsonld,
    entity_page_jsonld,
    evaluate_criteria,
    hub_dataset_jsonld,
    org_node,
    ref,
    term_set_node,
)

GRAPH_ROLES = ("concept", "integrations", "feature", "none")
_SPLIT = re.compile(r"\s*[,;|/]\s*")


def base_url() -> str:
    return get_settings().public_base_url.rstrip("/")


def entity_url(hub: Hub, entity: Entity) -> str:
    return f"{base_url()}/hub/{hub.slug}/{entity.slug}"


def product_id(hub: Hub, entity: Entity) -> str:
    return entity_url(hub, entity) + "#product"


def criteria_results(hub: Hub, entity: Entity) -> list[dict[str, Any]]:
    return evaluate_criteria((hub.schema_template or {}).get("review_criteria") or [], entity.attributes or {})


def _fields(hub: Hub) -> dict[str, dict[str, Any]]:
    return {f["name"]: f for f in ((hub.schema_template or {}).get("fields") or []) if f.get("name")}


def _humanize(field: str) -> str:
    return field.replace("_", " ").strip().capitalize()


def graph_parts(hub: Hub, entity: Entity) -> dict[str, list[str]]:
    """Separa os atributos da ficha em recursos, conceitos e integrações conforme o papel de cada campo."""
    fields = _fields(hub)
    out: dict[str, list[str]] = {"features": [], "concepts": [], "integrations": []}
    for name, value in (entity.attributes or {}).items():
        spec = fields.get(name, {})
        role = spec.get("graph_role") or ("feature" if isinstance(value, bool) else "none")
        if role == "feature" and value is True:
            label = spec.get("concept_label") or _humanize(name)
            out["features"].append(label)
            out["concepts"].append(label)
        elif role in ("concept", "integrations") and value not in (None, "", []):
            items = value if isinstance(value, list) else _SPLIT.split(str(value))
            clean = [re.sub(r"\s+", " ", str(i)).strip() for i in items if str(i).strip()]
            out["concepts" if role == "concept" else "integrations"].extend(clean)
    for k in out:
        out[k] = list(dict.fromkeys(out[k]))
    return out


def _org(hub: Hub, entity: Entity) -> dict[str, Any] | None:
    site = (entity.attributes or {}).get("site_oficial")
    return org_node(base_url(), entity.provider or None, site=site)


def entity_node(hub: Hub, entity: Entity, *, similar: list[Entity] | None = None, with_context: bool = False) -> dict[str, Any]:
    template = {k: v for k, v in ((hub.schema_template or {}).get("jsonld_template") or {}).items() if k not in ("@context", "@type")}
    base = base_url()
    review = editorial_review(criteria_results(hub, entity), org_id=f"{base}/#org", date=entity.verified_at or entity.updated_at)
    parts = graph_parts(hub, entity)
    org = _org(hub, entity)
    return entity_jsonld(
        name=entity.name,
        schema_type=entity.schema_type,
        attributes={k: v for k, v in (entity.attributes or {}).items() if not isinstance(v, list)},
        sources=entity.sources or [],
        template=template,
        url=entity_url(hub, entity),
        date_modified=entity.updated_at,
        provider=entity.provider or None,
        category=hub.niche,
        review=review,
        with_context=with_context,
        manufacturer=ref(org) if org else None,
        features=parts["features"],
        keywords=[ref(concept_node(base, c)) for c in parts["concepts"]],
        related=[ref(concept_node(base, i, kind="integration")) for i in parts["integrations"]],
        similar=[{"@id": product_id(hub, s)} for s in (similar or []) if s.id != entity.id],
    )


def support_nodes(hub: Hub, entities: list[Entity]) -> list[dict[str, Any]]:
    """Nós que fecham as referências dos produtos: empresas, conceitos, integrações e o conjunto de termos."""
    base = base_url()
    nodes: dict[str, dict[str, Any]] = {}
    for e in entities:
        org = _org(hub, e)
        if org:
            nodes.setdefault(org["@id"], org)
        parts = graph_parts(hub, e)
        for c in parts["concepts"]:
            n = concept_node(base, c)
            nodes.setdefault(n["@id"], n)
        for i in parts["integrations"]:
            n = concept_node(base, i, kind="integration")
            nodes.setdefault(n["@id"], n)
    if any(n["@type"] == "DefinedTerm" for n in nodes.values()):
        ts = term_set_node(base, get_settings().brand_name)
        nodes[ts["@id"]] = ts
    return list(nodes.values())


def _sibling_stub(hub: Hub, e: Entity) -> dict[str, Any]:
    types = [e.schema_type] + (["Product"] if e.schema_type != "Product" else [])
    stub: dict[str, Any] = {"@type": types, "@id": product_id(hub, e), "name": e.name, "url": entity_url(hub, e)}
    if "SoftwareApplication" in types:
        stub["applicationCategory"] = "BusinessApplication"
    return stub


async def hub_graph(hub: Hub, entities: list[Entity], page: dict[str, Any] | None = None, *, distributions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    page = page if page is not None else (hub.page_config or {})
    async with session_scope() as s:
        first_seen, versions = (
            await s.execute(
                select(func.min(EntityVersion.created_at), func.count(EntityVersion.id))
                .join(Entity, Entity.id == EntityVersion.entity_id)
                .where(Entity.hub_id == hub.id)
            )
        ).one()
    last_mod = max((e.updated_at for e in entities), default=hub.updated_at)
    extra = support_nodes(hub, entities)
    # Conceitos usados por 2+ produtos descrevem o assunto do dataset.
    counts: dict[str, int] = {}
    for e in entities:
        for c in graph_parts(hub, e)["concepts"]:
            counts[c] = counts.get(c, 0) + 1
    about = [ref(concept_node(base_url(), c)) for c, n in sorted(counts.items(), key=lambda x: -x[1]) if n >= 2][:10]
    return hub_dataset_jsonld(
        hub={"slug": hub.slug, "title": hub.title, "description": hub.description, "fields": list(_fields(hub))},
        entities=[entity_node(hub, e, similar=entities) for e in entities],
        base_url=base_url(),
        brand=get_settings().brand_name,
        date_modified=last_mod,
        faq=page.get("faq"),
        keywords=(hub.research or {}).get("target_queries"),
        temporal_start=first_seen,
        version=versions or None,
        extra_nodes=extra,
        distributions=distributions,
        about=about or None,
    )


def entity_graph(hub: Hub, entity: Entity, siblings: list[Entity] | None = None) -> dict[str, Any]:
    siblings = [s for s in (siblings or []) if s.id != entity.id]
    return entity_page_jsonld(
        entity=entity_node(hub, entity, similar=siblings),
        hub={"slug": hub.slug, "title": hub.title},
        base_url=base_url(),
        brand=get_settings().brand_name,
        reviewed_by=entity.human_reviewed_by,
        last_reviewed=entity.human_reviewed_at,
        extra_nodes=support_nodes(hub, [entity]) + [_sibling_stub(hub, s) for s in siblings],
    )
