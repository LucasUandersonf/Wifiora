"""API semântica paga (Camada 3 de monetização).

Autenticação: header `X-API-Key`. Cada cliente tem cota diária; o uso é contado por dia (UTC).
Diferenciais em relação aos dados abertos: busca entre hubs, histórico completo de versões,
filtro por data de atualização e JSON-LD por ficha.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import or_, select

from app.api.portal_admin import hash_key
from app.core.semantic import entity_graph
from app.db import session_scope
from app.models import ApiClient, Entity, EntityVersion, Hub

router = APIRouter(prefix="/api/v1", tags=["api v1 (paga)"])


async def api_client(x_api_key: str | None = Header(default=None)) -> str:
    if not x_api_key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "envie a chave no header X-API-Key")
    today = datetime.now(UTC).date().isoformat()
    async with session_scope() as s:
        c = (await s.execute(select(ApiClient).where(ApiClient.key_hash == hash_key(x_api_key)))).scalar_one_or_none()
        if c is None or not c.active:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "chave inválida ou revogada")
        if c.usage_day != today:
            c.usage_day, c.usage_count = today, 0
        if c.usage_count >= c.daily_quota:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, f"cota diária de {c.daily_quota} requisições atingida")
        c.usage_count += 1
        c.total_requests += 1
        c.last_used_at = datetime.now(UTC)
        return c.id


def _entity_out(hub: Hub, e: Entity, *, jsonld: bool) -> dict[str, Any]:
    out = {
        "hub": hub.slug,
        "slug": e.slug,
        "name": e.name,
        "type": e.schema_type,
        "attributes": e.attributes,
        "provider": e.provider,
        "sources": e.sources,
        "grounding_ratio": e.grounding_ratio,
        "human_reviewed": bool(e.human_reviewed_at),
        "verified_at": e.verified_at,
        "version": e.version,
        "updated_at": e.updated_at,
    }
    if jsonld:
        out["jsonld"] = entity_graph(hub, e)
    return out


def _published():
    return select(Entity, Hub).join(Hub, Hub.id == Entity.hub_id).where(Hub.status == "published", Entity.status == "published", Hub.demo_data.is_(False))


@router.get("/hubs")
async def hubs(_: str = Depends(api_client)) -> list[dict[str, Any]]:
    async with session_scope() as s:
        rows = (await s.execute(select(Hub).where(Hub.status == "published", Hub.demo_data.is_(False)).order_by(Hub.title))).scalars()
        return [{"slug": h.slug, "title": h.title, "niche": h.niche, "updated_at": h.updated_at} for h in rows]


@router.get("/entities")
async def search_entities(
    q: str | None = Query(default=None, max_length=100, description="busca por nome"),
    hub: str | None = None,
    updated_since: datetime | None = Query(default=None, description="ISO 8601"),
    jsonld: bool = False,
    limit: int = Query(default=50, le=200),
    _: str = Depends(api_client),
) -> list[dict[str, Any]]:
    stmt = _published()
    if q:
        stmt = stmt.where(or_(Entity.name.ilike(f"%{q}%"), Entity.slug.ilike(f"%{q}%")))
    if hub:
        stmt = stmt.where(Hub.slug == hub)
    if updated_since:
        stmt = stmt.where(Entity.updated_at >= updated_since)
    async with session_scope() as s:
        rows = (await s.execute(stmt.order_by(Entity.updated_at.desc()).limit(limit))).all()
        return [_entity_out(h, e, jsonld=jsonld) for e, h in rows]


@router.get("/entities/{hub_slug}/{entity_slug}/history")
async def entity_history(hub_slug: str, entity_slug: str, _: str = Depends(api_client)) -> dict[str, Any]:
    async with session_scope() as s:
        row = (await s.execute(_published().where(Hub.slug == hub_slug, Entity.slug == entity_slug))).first()
        if row is None:
            raise HTTPException(404, "ficha não encontrada")
        e, h = row
        versions = (await s.execute(select(EntityVersion).where(EntityVersion.entity_id == e.id).order_by(EntityVersion.version))).scalars()
        return {
            "entity": _entity_out(h, e, jsonld=True),
            "history": [{"version": v.version, "attributes": v.attributes, "changed_fields": v.changed_fields, "at": v.created_at} for v in versions],
        }
