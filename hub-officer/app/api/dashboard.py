"""API de leitura do dashboard executivo (protegida pelo token do fundador)."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import case, func, select

from app.api.deps import get_office, require_founder
from app.core.office import Office
from app.db import session_scope
from app.models import (
    AgentMessage,
    AgentState,
    Alert,
    ApprovalRequest,
    Directive,
    Entity,
    Evaluation,
    Hub,
    MonetizationOpportunity,
    Objective,
    Task,
)

router = APIRouter(prefix="/api/office", tags=["dashboard"], dependencies=[Depends(require_founder)])


def _row(obj: Any, *fields: str) -> dict[str, Any]:
    return {f: getattr(obj, f) for f in fields}


@router.get("/overview")
async def overview(office: Office = Depends(get_office)) -> dict[str, Any]:
    gov = await office.gov.snapshot(force=True)
    finance = await office.ledger.summary()
    async with session_scope() as s:
        task_counts = dict((await s.execute(select(Task.status, func.count()).group_by(Task.status))).all())
        hubs_total = (await s.execute(select(func.count(Hub.id)))).scalar_one()
        ents = (
            await s.execute(
                select(
                    func.count(Entity.id),
                    func.sum(case((Entity.validated.is_(True), 1), else_=0)),
                    func.avg(Entity.grounding_ratio),
                )
            )
        ).one()
        published_entities = (await s.execute(select(func.count(Entity.id)).where(Entity.status == "published"))).scalar_one()
        jsonld_bytes = sum(len(json.dumps(j, ensure_ascii=False)) for (j,) in (await s.execute(select(Entity.jsonld))).all())
        evals = (await s.execute(select(func.count(Evaluation.id), func.avg(Evaluation.score), func.sum(case((Evaluation.passed.is_(True), 1), else_=0))))).one()
        sov = (await s.execute(select(func.avg(Hub.share_of_voice)).where(Hub.share_of_voice.is_not(None)))).scalar_one()
        active = (
            await s.execute(select(Objective).where(Objective.status.in_(("planning", "active", "consolidating", "awaiting_approval"))).order_by(Objective.created_at.desc()).limit(1))
        ).scalar_one_or_none()
        pending_approvals = (await s.execute(select(func.count(ApprovalRequest.id)).where(ApprovalRequest.status == "pending"))).scalar_one()
        open_alerts = (await s.execute(select(func.count(Alert.id)).where(Alert.acknowledged.is_(False), Alert.level != "info"))).scalar_one()
        opp = (await s.execute(select(func.count(MonetizationOpportunity.id), func.sum(MonetizationOpportunity.est_monthly_usd * MonetizationOpportunity.confidence)))).one()

    eval_count = int(evals[0] or 0)
    return {
        "office": {
            **gov,
            "llm_provider": office.llm.client.provider,
            "models": {t: office.llm.model_for(t) for t in ("strategic", "worker", "judge")},
            "bus": office.bus.name,
            "role": office.settings.office_role,
            "started_at": office.started_at,
            "pending_approvals": pending_approvals,
            "open_alerts": open_alerts,
            "resting_until": office.quota_rest_until if office.resting() else None,
            "llm_calls_today": await office.ledger.llm_calls_today(),
            "llm_daily_call_limit": office.settings.llm_daily_call_limit,
        },
        "finance": finance,
        "business": {
            "hubs_total": hubs_total,
            "hubs_published": finance["published_hubs"],
            "entities_total": int(ents[0] or 0),
            "entities_validated": int(ents[1] or 0),
            "entities_published": published_entities,
            "avg_grounding": round(float(ents[2]), 3) if ents[2] is not None else None,
            "structured_data_kb": round(jsonld_bytes / 1024, 1),
            "share_of_voice": round(float(sov), 3) if sov is not None else None,
            "evaluations": eval_count,
            "avg_score": round(float(evals[1]), 3) if evals[1] is not None else None,
            "approval_rate": round(int(evals[2] or 0) / eval_count, 3) if eval_count else None,
            "opportunities": int(opp[0] or 0),
            "opportunities_weighted_usd": round(float(opp[1] or 0), 2),
        },
        "tasks": task_counts,
        "active_objective": _row(active, "id", "title", "status", "current_phase", "niche", "created_at") if active else None,
        "queues": await office.bus.queue_depths(),
    }


@router.get("/agents")
async def agents() -> list[dict[str, Any]]:
    async with session_scope() as s:
        rows = (await s.execute(select(AgentState).order_by(AgentState.sector, AgentState.role, AgentState.agent_id))).scalars()
        return [
            _row(a, "agent_id", "title", "sector", "role", "status", "current_task_id", "current_activity", "skills", "processed", "failures", "avg_score", "updated_at")
            for a in rows
        ]


@router.get("/tasks")
async def tasks(status: str | None = None, objective_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    async with session_scope() as s:
        q = select(Task).order_by(Task.updated_at.desc()).limit(min(limit, 500))
        if status:
            q = q.where(Task.status == status)
        if objective_id:
            q = q.where(Task.objective_id == objective_id)
        return [
            _row(t, "id", "objective_id", "sector", "kind", "title", "assignee_id", "owner_id", "status", "priority", "revisions", "last_score", "error", "updated_at")
            for t in (await s.execute(q)).scalars()
        ]


@router.get("/tasks/{task_id}")
async def task_detail(task_id: str) -> dict[str, Any]:
    async with session_scope() as s:
        t = await s.get(Task, task_id)
        if t is None:
            raise HTTPException(404, "tarefa não encontrada")
        evs = (await s.execute(select(Evaluation).where(Evaluation.task_id == task_id).order_by(Evaluation.created_at))).scalars()
        return {
            **_row(t, "id", "objective_id", "sector", "kind", "title", "brief", "assignee_id", "owner_id", "status", "depends_on", "output", "feedback", "revisions", "last_score", "error", "created_at", "updated_at"),
            "evaluations": [_row(e, "score", "deterministic_score", "llm_score", "passed", "checks", "feedback", "created_at") for e in evs],
        }


@router.get("/messages")
async def messages(limit: int = 100, agent: str | None = None, objective_id: str | None = None) -> list[dict[str, Any]]:
    async with session_scope() as s:
        q = select(AgentMessage).order_by(AgentMessage.created_at.desc()).limit(min(limit, 500))
        if agent:
            q = q.where((AgentMessage.sender == agent) | (AgentMessage.recipient == agent))
        if objective_id:
            q = q.where(AgentMessage.objective_id == objective_id)
        return [_row(m, "id", "type", "sender", "recipient", "summary", "objective_id", "task_id", "created_at") for m in (await s.execute(q)).scalars()]


@router.get("/objectives")
async def objectives(limit: int = 20) -> list[dict[str, Any]]:
    async with session_scope() as s:
        q = select(Objective).order_by(Objective.created_at.desc()).limit(min(limit, 100))
        return [
            {
                **_row(o, "id", "title", "niche", "rationale", "status", "current_phase", "plan", "final_report", "hub_id", "created_at", "updated_at"),
                "sector_status": {sector: r.get("status") for sector, r in (o.sector_reports or {}).items()},
            }
            for o in (await s.execute(q)).scalars()
        ]


@router.get("/finance")
async def finance(office: Office = Depends(get_office)) -> dict[str, Any]:
    return await office.ledger.summary()


@router.get("/hubs")
async def hubs() -> list[dict[str, Any]]:
    async with session_scope() as s:
        rows = (
            await s.execute(
                select(Hub, func.count(Entity.id), func.avg(Entity.grounding_ratio)).outerjoin(Entity, Entity.hub_id == Hub.id).group_by(Hub.id).order_by(Hub.created_at.desc())
            )
        ).all()
        return [
            {**_row(h, "id", "slug", "title", "niche", "status", "demo_data", "share_of_voice", "published_at", "updated_at"), "entities": n, "avg_grounding": round(float(g), 3) if g is not None else None}
            for h, n, g in rows
        ]


@router.get("/ai-data")
async def ai_data(days: int = 30) -> dict[str, Any]:
    """Dados para IAs: tamanho e integridade do grafo, arquivos publicados e robôs que leram o portal."""
    from app.core import bots
    from app.core import knowledge as kg
    from app.skills.builtin.jsonld import graph_stats

    site = await kg.load_site()
    graph = graph_stats(await kg.knowledge_graph(site))
    base = kg.base_url()
    return {
        "graph": {**graph, "dangling": graph["dangling"][:20], "orgs": len(kg.org_index(site)), "concepts": len(kg.concept_index(site))},
        "files": {
            "site": [f"{base}/knowledge-graph.jsonld", f"{base}/data/catalog.jsonld", f"{base}/data/all.jsonl", f"{base}/llms-full.txt"],
            "hubs": len(site.hubs),
            "per_hub": len(kg.FORMATS),
        },
        "bots": await bots.summary(days=days),
        "pings": await _recent_pings(),
    }


async def _recent_pings(limit: int = 15) -> dict[str, Any]:
    from app.models import IndexPing

    async with session_scope() as s:
        rows = list((await s.execute(select(IndexPing).order_by(IndexPing.created_at.desc()).limit(limit))).scalars())
        avg_lag = (await s.execute(select(func.avg(IndexPing.lag_seconds)).where(IndexPing.lag_seconds.is_not(None)))).scalar_one()
    return {
        "avg_lag_seconds": round(float(avg_lag), 1) if avg_lag is not None else None,
        "recent": [
            {"at": p.created_at, "hub": p.hub_slug, "reason": p.reason, "urls": len(p.urls or []), "changed": p.changed_fields,
             "revalidated": p.revalidated, "indexnow": p.indexnow, "lag_seconds": p.lag_seconds}
            for p in rows
        ],
    }


@router.get("/viability")
async def viability_panel(office: Office = Depends(get_office)) -> dict[str, Any]:
    from app.core import viability

    return {"targets": await viability.targets(office), "hubs": await viability.latest()}


@router.get("/niches")
async def niches_panel(office: Office = Depends(get_office)) -> dict[str, Any]:
    from app.core import niches, viability

    gov = await office.gov.snapshot()
    cov = await niches.coverage()
    nxt = await niches.resolve_focus(gov["focus_niche"], rotation=bool(gov["niche_rotation"]))
    verdicts: dict[str, str] = {}
    async with session_scope() as s:
        hub_niche = dict((await s.execute(select(Hub.slug, Hub.niche_slug))).all())
    for v in await viability.latest():
        if hub_niche.get(v["hub"]):
            verdicts.setdefault(hub_niche[v["hub"]], v["verdict"])
    return {
        "criteria": niches.CRITERIA,
        "focus": gov["focus_niche"],
        "rotation": gov["niche_rotation"],
        "next": nxt.slug if nxt else None,
        "niches": [{**niches.niche_out(n, cov), "verdict": verdicts.get(n.slug)} for n in await niches.all_niches()],
    }


@router.get("/tracker")
async def tracker_info(office: Office = Depends(get_office)) -> dict[str, Any]:
    from app.core import engines

    avail = engines.available(office)
    return {"available": avail, "labels": engines.LABELS, "default_queries": office.settings.tracker_default_queries,
            "cost_per_report": {n: engines.estimate_cost(avail, n) for n in (10, 20, 30, 50)}}


@router.get("/diagnoses")
async def diagnoses(limit: int = 30) -> list[dict[str, Any]]:
    from app.models import Diagnosis

    async with session_scope() as s:
        rows = (await s.execute(select(Diagnosis).order_by(Diagnosis.created_at.desc()).limit(limit))).scalars()
        return [
            {**_row(d, "id", "brand", "site", "category", "city", "competitors", "contact", "status", "mode", "scores", "error", "cost_usd", "created_at", "finished_at"),
             "report": f"/relatorio/{d.token}", "pdf": f"/relatorio/{d.token}.pdf", "engines_used": d.engines or [],
             "query_count": d.query_count, "gaps": len((d.visibility or {}).get("gaps") or [])}
            for d in rows
        ]


@router.get("/content")
async def content_panel(office: Office = Depends(get_office)) -> dict[str, Any]:
    from app.core import insighta_content

    return await insighta_content.summary(office)


@router.get("/content/{piece_id}.md")
async def content_markdown(piece_id: str, office: Office = Depends(get_office)) -> Response:
    """Página pronta para publicar no site da Insighta (Markdown + JSON-LD)."""
    from app.core import insighta_content
    from app.db import session_scope
    from app.models import ContentPiece

    async with session_scope() as s:
        p = await s.get(ContentPiece, piece_id)
    if p is None:
        raise HTTPException(404, "conteúdo não encontrado")
    return Response(insighta_content.export_markdown(office, p), media_type="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": f'inline; filename="{p.slug}.md"'})


@router.get("/sales")
async def sales_panel(office: Office = Depends(get_office)) -> dict[str, Any]:
    from app.core import sales

    return await sales.summary(office)


@router.get("/council")
async def council_list(limit: int = 10) -> list[dict[str, Any]]:
    from app.core.council import meeting_out
    from app.models import Meeting

    async with session_scope() as s:
        rows = (await s.execute(select(Meeting).order_by(Meeting.created_at.desc()).limit(limit))).scalars()
        return [meeting_out(m, full=True) for m in rows]


@router.get("/opportunities")
async def opportunities() -> list[dict[str, Any]]:
    async with session_scope() as s:
        q = select(MonetizationOpportunity).order_by((MonetizationOpportunity.est_monthly_usd * MonetizationOpportunity.confidence).desc()).limit(50)
        return [_row(o, "id", "channel", "title", "est_monthly_usd", "confidence", "status", "hub_id", "created_at") for o in (await s.execute(q)).scalars()]


@router.get("/alerts")
async def alerts(limit: int = 50) -> list[dict[str, Any]]:
    async with session_scope() as s:
        q = select(Alert).order_by(Alert.created_at.desc()).limit(min(limit, 200))
        return [_row(a, "id", "level", "source", "message", "acknowledged", "created_at") for a in (await s.execute(q)).scalars()]


@router.get("/approvals")
async def approvals(status: str | None = "pending") -> list[dict[str, Any]]:
    async with session_scope() as s:
        q = select(ApprovalRequest).order_by(ApprovalRequest.created_at.desc()).limit(100)
        if status:
            q = q.where(ApprovalRequest.status == status)
        return [_row(a, "id", "kind", "title", "details", "amount_usd", "requested_by", "status", "decision_note", "created_at", "decided_at") for a in (await s.execute(q)).scalars()]


@router.get("/directives")
async def directives() -> list[dict[str, Any]]:
    async with session_scope() as s:
        q = select(Directive).order_by(Directive.created_at.desc())
        return [_row(d, "id", "text", "active", "created_at") for d in (await s.execute(q)).scalars()]


@router.get("/skills")
async def skills(office: Office = Depends(get_office)) -> list[dict[str, Any]]:
    return office.skills.catalog()


@router.get("/stream")
async def stream(office: Office = Depends(get_office)) -> StreamingResponse:
    """Server-Sent Events com a telemetria em tempo real do barramento."""

    async def gen():
        yield "retry: 3000\n\n"
        events = office.bus.listen()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

        async def pump() -> None:
            async for e in events:
                await queue.put(e)

        pump_task = asyncio.create_task(pump())
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"data: {json.dumps(event, default=str, ensure_ascii=False)}\n\n"
                except TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            pump_task.cancel()

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
