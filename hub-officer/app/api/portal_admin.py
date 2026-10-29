"""Gestão do portal pelo fundador: revisão humana das fichas, correções, leads e clientes da API."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import get_office, require_founder
from app.core.office import Office
from app.core.semantic import entity_graph
from app.skills.builtin.jsonld import org_slug
from app.db import session_scope
from app.models import ApiClient, CorrectionRequest, Entity, Hub, Lead

read = APIRouter(prefix="/api/office", tags=["portal"], dependencies=[Depends(require_founder)])
write = APIRouter(prefix="/api/control", tags=["portal"], dependencies=[Depends(require_founder)])


def _row(obj: Any, *fields: str) -> dict[str, Any]:
    return {f: getattr(obj, f) for f in fields}


# ------------------------------------------------------------------ revisão humana
@read.get("/entities")
async def entities(review: str = "pending", limit: int = 100) -> list[dict[str, Any]]:
    """review=pending: fichas validadas pela máquina e ainda sem selo humano; reviewed; all."""
    async with session_scope() as s:
        q = select(Entity, Hub.slug, Hub.title).join(Hub, Hub.id == Entity.hub_id).where(Entity.validated.is_(True))
        if review == "pending":
            q = q.where(Entity.human_reviewed_at.is_(None))
        elif review == "reviewed":
            q = q.where(Entity.human_reviewed_at.is_not(None))
        rows = (await s.execute(q.order_by(Entity.updated_at.desc()).limit(min(limit, 500)))).all()
        return [
            {
                **_row(e, "id", "slug", "name", "status", "grounding_ratio", "version", "verified_at", "human_reviewed_by", "human_reviewed_at", "attributes"),
                "hub_slug": hs,
                "hub_title": ht,
                "sources": [src.get("url") for src in (e.sources or [])][:3],
            }
            for e, hs, ht in rows
        ]


class ReviewIn(BaseModel):
    reviewer: str = Field(min_length=2, max_length=120)
    note: str | None = Field(default=None, max_length=2000)


async def _touch_entity(office: Office, entity_id: str, reason: str = "review", **fields: Any) -> Entity:
    async with session_scope() as s:
        ent = await s.get(Entity, entity_id)
        if ent is None:
            raise HTTPException(404, "ficha não encontrada")
        for k, v in fields.items():
            setattr(ent, k, v)
        hub = await s.get(Hub, ent.hub_id)
        assert hub is not None
        ent.jsonld = entity_graph(hub, ent)
        hub_slug, demo, slug, org = hub.slug, hub.demo_data, ent.slug, org_slug(ent.provider)
    await office.executor.announce(hub_slug, [slug], demo, org_slugs=[org or ""], reason=reason)
    return ent


@write.post("/entities/{entity_id}/review")
async def approve_entity(entity_id: str, body: ReviewIn, office: Office = Depends(get_office)) -> dict[str, Any]:
    ent = await _touch_entity(office, entity_id, human_reviewed_by=body.reviewer, human_reviewed_at=datetime.now(UTC), human_review_note=body.note)
    await office.emit("entity_reviewed", entity=ent.name, reviewer=body.reviewer)
    return {"ok": True, "entity": ent.name}


@write.delete("/entities/{entity_id}/review")
async def revoke_review(entity_id: str, office: Office = Depends(get_office)) -> dict[str, Any]:
    ent = await _touch_entity(office, entity_id, human_reviewed_by=None, human_reviewed_at=None, human_review_note=None)
    return {"ok": True, "entity": ent.name}


@write.post("/entities/{entity_id}/unpublish")
async def unpublish_entity(entity_id: str, office: Office = Depends(get_office)) -> dict[str, Any]:
    """Tira uma ficha do ar (ex.: correção procedente ainda não refeita pelos agentes)."""
    ent = await _touch_entity(office, entity_id, reason="unpublish", status="draft")
    await office.alert("info", "founder", f"Ficha {ent.name} retirada do ar.")
    return {"ok": True}


# ------------------------------------------------------------------ correções
@read.get("/corrections")
async def corrections(status: str | None = "open") -> list[dict[str, Any]]:
    async with session_scope() as s:
        q = select(CorrectionRequest).order_by(CorrectionRequest.created_at.desc()).limit(200)
        if status:
            q = q.where(CorrectionRequest.status == status)
        return [
            _row(c, "id", "hub_slug", "entity_slug", "name", "email", "company", "message", "evidence_url", "status", "resolution_note", "created_at")
            for c in (await s.execute(q)).scalars()
        ]


class CorrectionDecision(BaseModel):
    status: str = Field(pattern="^(resolved|rejected)$")
    note: str | None = Field(default=None, max_length=2000)


@write.post("/corrections/{correction_id}")
async def decide_correction(correction_id: str, body: CorrectionDecision) -> dict[str, Any]:
    async with session_scope() as s:
        c = await s.get(CorrectionRequest, correction_id)
        if c is None:
            raise HTTPException(404, "pedido não encontrado")
        c.status, c.resolution_note = body.status, body.note
    return {"ok": True}


# ------------------------------------------------------------------ leads
@read.get("/leads")
async def leads(status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    async with session_scope() as s:
        q = select(Lead).order_by(Lead.created_at.desc()).limit(min(limit, 500))
        if status:
            q = q.where(Lead.status == status)
        return [
            _row(x, "id", "hub_slug", "entity_slug", "entity_name", "name", "email", "phone", "company", "company_size", "message", "consent", "status", "value_usd", "created_at")
            for x in (await s.execute(q)).scalars()
        ]


class LeadUpdate(BaseModel):
    status: str = Field(pattern="^(new|sent|won|discarded)$")
    value_usd: float | None = Field(default=None, ge=0)


@write.post("/leads/{lead_id}")
async def update_lead(lead_id: str, body: LeadUpdate, office: Office = Depends(get_office)) -> dict[str, Any]:
    async with session_scope() as s:
        lead = await s.get(Lead, lead_id)
        if lead is None:
            raise HTTPException(404, "lead não encontrado")
        was_won = lead.status == "won"
        lead.status = body.status
        if body.value_usd is not None:
            lead.value_usd = body.value_usd
        entity, hub_slug, value = lead.entity_name, lead.hub_slug, lead.value_usd
    if body.status == "won" and not was_won and value:
        # Lead pago pelo fornecedor = receita real (Camada 1: CPL)
        async with session_scope() as s:
            hub_id = (await s.execute(select(Hub.id).where(Hub.slug == hub_slug))).scalar_one_or_none()
        await office.ledger.record_revenue("cpl", value, f"Lead para {entity}", projected=False, hub_id=hub_id)
    return {"ok": True}


# ------------------------------------------------------------------ clientes da API
def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


class ApiClientIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    email: str | None = Field(default=None, max_length=200)
    plan: str = Field(default="starter", max_length=32)
    daily_quota: int = Field(default=1000, ge=1, le=1_000_000)
    monthly_price_usd: float = Field(default=0, ge=0)


@read.get("/api-clients")
async def api_clients() -> list[dict[str, Any]]:
    async with session_scope() as s:
        rows = (await s.execute(select(ApiClient).order_by(ApiClient.created_at.desc()))).scalars()
        return [
            _row(c, "id", "name", "email", "key_prefix", "plan", "daily_quota", "monthly_price_usd", "active", "usage_day", "usage_count", "total_requests", "created_at", "last_used_at")
            for c in rows
        ]


@write.post("/api-clients")
async def create_api_client(body: ApiClientIn) -> dict[str, Any]:
    key = "geo_" + secrets.token_urlsafe(24)
    async with session_scope() as s:
        c = ApiClient(**body.model_dump(), key_prefix=key[:12], key_hash=hash_key(key))
        s.add(c)
    # A chave completa só aparece aqui, uma vez. Guardamos apenas o hash.
    return {"id": c.id, "api_key": key, "warning": "Copie a chave agora: ela não será mostrada de novo."}


@write.delete("/api-clients/{client_id}")
async def revoke_api_client(client_id: str) -> dict[str, Any]:
    async with session_scope() as s:
        c = await s.get(ApiClient, client_id)
        if c is None:
            raise HTTPException(404, "cliente não encontrado")
        c.active = False
    return {"ok": True}


# ------------------------------------------------------------------ auditoria GEO sob demanda
@write.post("/hubs/{slug}/geo-audit")
async def run_geo_audit(slug: str, office: Office = Depends(get_office)) -> dict[str, Any]:
    """Mede agora o Share of Voice de um hub (em segundo plano; resultado chega como alerta)."""
    async with session_scope() as s:
        hub = (await s.execute(select(Hub).where(Hub.slug == slug))).scalar_one_or_none()
        if hub is None:
            raise HTTPException(404, "hub não encontrado")
        queries = (hub.research or {}).get("target_queries") or []
    if not queries:
        raise HTTPException(422, "hub sem consultas-alvo (target_queries) definidas pela pesquisa")

    async def job() -> None:
        try:
            res = await office.skills.get("geo_citation_audit").run(queries=queries, agent_id="founder")
            async with session_scope() as s:
                h = (await s.execute(select(Hub).where(Hub.slug == slug))).scalar_one()
                h.share_of_voice = res["share_of_voice"]
                r = dict(h.research or {})
                r["last_geo_audit"] = {**res, "at": datetime.now(UTC).isoformat()}
                h.research = r
            await office.alert("info", "geo_audit", f"Share of Voice de {slug}: {res['share_of_voice']:.0%} das {len(queries)} perguntas citam o portal (modo {res['mode']}).")
        except Exception as e:
            await office.alert("warning", "geo_audit", f"Auditoria GEO de {slug} falhou: {e}")

    office.spawn(job())
    return {"ok": True, "queries": len(queries), "message": "auditoria iniciada; o resultado chega como alerta"}
