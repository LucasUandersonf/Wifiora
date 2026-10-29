"""Payloads das páginas públicas + renderização SSR (fallback em FastAPI).

O mesmo payload alimenta: (1) os templates Jinja servidos pelo FastAPI e (2) o portal Next.js
(via /api/public/...). Assim JSON-LD, colunas, selos e histórico nunca divergem entre os dois.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select

from app.config import get_settings
from app.core.knowledge import distributions
from app.core.rankings import hub_rankings, ranking_nodes
from app.core.semantic import criteria_results, entity_graph, hub_graph
from app.db import session_scope
from app.skills.builtin.jsonld import org_slug
from app.models import Entity, EntityVersion, Hub
from app.web.institutional import FOOTER_LINKS

TEMPLATES = Environment(loader=FileSystemLoader(Path(__file__).parent / "templates"), autoescape=select_autoescape(["html"]))


def jsonld_script(doc: dict[str, Any]) -> str:
    # Escapa "</" para impedir quebra do <script> por conteúdo coletado.
    return json.dumps(doc, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def _fmt(v: Any) -> str:
    if isinstance(v, bool):
        return "Sim" if v else "Não"
    if isinstance(v, float):
        return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return str(v)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _date_br(value: str | None) -> str:
    if not value:
        return "—"
    try:
        return datetime.fromisoformat(value).strftime("%d/%m/%Y")
    except ValueError:
        return value[:10]


TEMPLATES.filters["fmt"] = _fmt
TEMPLATES.filters["date_br"] = _date_br


def site_context() -> dict[str, Any]:
    st = get_settings()
    return {"base_url": st.public_base_url.rstrip("/"), "brand": st.brand_name, "footer_links": FOOTER_LINKS}


async def load_hub(hub_key: str, *, include_drafts: bool = False) -> tuple[Hub, list[Entity]] | None:
    async with session_scope() as s:
        hub = await s.get(Hub, hub_key) or (await s.execute(select(Hub).where(Hub.slug == hub_key))).scalar_one_or_none()
        if hub is None or (hub.status != "published" and not include_drafts):
            return None
        q = select(Entity).where(Entity.hub_id == hub.id).order_by(Entity.name)
        q = q.where(Entity.validated.is_(True)) if include_drafts else q.where(Entity.status == "published")
        return hub, list((await s.execute(q)).scalars())


def _hub_info(hub: Hub) -> dict[str, Any]:
    return {
        "slug": hub.slug,
        "title": hub.title,
        "niche": hub.niche,
        "description": hub.description,
        "demo_data": hub.demo_data,
        "updated_at": _iso(hub.updated_at),
        "published_at": _iso(hub.published_at),
    }


def _entity_summary(hub: Hub, e: Entity) -> dict[str, Any]:
    results = criteria_results(hub, e)
    known = [r for r in results if r["passed"] is not None]
    return {
        "slug": e.slug,
        "name": e.name,
        "attributes": e.attributes or {},
        "source_url": next((s.get("url") for s in (e.sources or []) if s.get("url")), None),
        "verified_at": _iso(e.verified_at or e.updated_at),
        "human_reviewed": bool(e.human_reviewed_at),
        "grounding_ratio": e.grounding_ratio,
        "criteria_met": sum(1 for r in known if r["passed"]),
        "criteria_total": len(known),
        "version": e.version,
    }


async def hub_payload(hub_key: str, *, include_drafts: bool = False, page_config: dict[str, Any] | None = None) -> dict[str, Any] | None:
    loaded = await load_hub(hub_key, include_drafts=include_drafts)
    if loaded is None:
        return None
    hub, entities = loaded
    page = page_config or hub.page_config or {}
    fields = [f.get("name") for f in ((hub.schema_template or {}).get("fields") or []) if f.get("name")]
    columns = [c for c in (page.get("table_columns") or fields[:6]) if c and c not in ("site_oficial",)]
    async with session_scope() as s:
        changes = (
            await s.execute(
                select(EntityVersion, Entity.name)
                .join(Entity, Entity.id == EntityVersion.entity_id)
                .where(Entity.hub_id == hub.id)
                .order_by(EntityVersion.created_at.desc())
                .limit(20)
            )
        ).all()
    rankings = hub_rankings(hub, entities)
    graph = await hub_graph(hub, entities, page, distributions=distributions(hub))
    graph["@graph"].extend(ranking_nodes(hub, entities, rankings))
    return {
        "hub": _hub_info(hub),
        "page": {
            "meta_description": page.get("meta_description") or hub.description,
            "faq": [f for f in (page.get("faq") or []) if f.get("q") and f.get("a")],
            "sections": page.get("sections") or [],
        },
        "columns": columns,
        "criteria": [c.get("label") for c in ((hub.schema_template or {}).get("review_criteria") or [])],
        "entities": [_entity_summary(hub, e) for e in entities],
        "changes": [{"entity": name, "version": v.version, "fields": v.changed_fields, "at": _iso(v.created_at)} for v, name in changes],
        "rankings": rankings,
        "jsonld": graph,
        "downloads": [{"name": d["name"], "url": d["contentUrl"], "file": d["contentUrl"].rsplit("/", 1)[1]} for d in distributions(hub)],
    }


async def entity_payload(hub_slug: str, entity_slug: str) -> dict[str, Any] | None:
    loaded = await load_hub(hub_slug)
    if loaded is None:
        return None
    hub, entities = loaded
    ent = next((e for e in entities if e.slug == entity_slug), None)
    if ent is None:
        return None
    async with session_scope() as s:
        versions = list((await s.execute(select(EntityVersion).where(EntityVersion.entity_id == ent.id).order_by(EntityVersion.version.desc()))).scalars())
    return {
        "hub": _hub_info(hub),
        "entity": {
            **_entity_summary(hub, ent),
            "schema_type": ent.schema_type,
            "sources": [{"url": s.get("url"), "quote": s.get("quote"), "retrieved_at": s.get("retrieved_at")} for s in (ent.sources or [])],
            "provider": ent.provider or {},
            "org_slug": org_slug(ent.provider),
            "human_reviewed_by": ent.human_reviewed_by,
            "human_reviewed_at": _iso(ent.human_reviewed_at),
            "criteria": criteria_results(hub, ent),
        },
        "versions": [{"version": v.version, "fields": v.changed_fields, "at": _iso(v.created_at)} for v in versions],
        "jsonld": entity_graph(hub, ent, entities),
    }


async def render_hub_page(hub_key: str, *, include_drafts: bool = False, page_config: dict[str, Any] | None = None) -> str | None:
    data = await hub_payload(hub_key, include_drafts=include_drafts, page_config=page_config)
    if data is None:
        return None
    return TEMPLATES.get_template("hub.html").render(**data, jsonld_text=jsonld_script(data["jsonld"]), **site_context())


async def render_entity_page(hub_slug: str, entity_slug: str, *, sent: str | None = None) -> str | None:
    data = await entity_payload(hub_slug, entity_slug)
    if data is None:
        return None
    return TEMPLATES.get_template("entity.html").render(**data, jsonld_text=jsonld_script(data["jsonld"]), sent=sent, **site_context())
