"""API do Radar de Ondas: leitura para o painel e decisões do fundador sobre as ações propostas."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import get_office, require_founder
from app.core.office import Office
from app.db import session_scope
from app.models import Directive, Objective, PlayAction, Signal, Task, Wave, WaveSnapshot

read = APIRouter(prefix="/api/office", tags=["radar"], dependencies=[Depends(require_founder)])
write = APIRouter(prefix="/api/control", tags=["radar"], dependencies=[Depends(require_founder)])

STAGE_ORDER = {"sinal": 0, "emergente": 1, "crescendo": 2, "mainstream": 3, "saturada": 4}


@read.get("/radar")
async def radar(office: Office = Depends(get_office)) -> dict[str, Any]:
    async with session_scope() as s:
        waves = list((await s.execute(select(Wave).where(Wave.status != "archived"))).scalars())
        snaps = list((await s.execute(select(WaveSnapshot).order_by(WaveSnapshot.created_at))).scalars())
        signals = list((await s.execute(select(Signal).order_by(Signal.created_at.desc()).limit(60))).scalars())
        plays = list((await s.execute(select(PlayAction).order_by(PlayAction.created_at.desc()).limit(80))).scalars())
        last = (
            await s.execute(select(Objective).where(Objective.kind == "radar", Objective.final_report.is_not(None)).order_by(Objective.created_at.desc()).limit(1))
        ).scalar_one_or_none()
        active = (await s.execute(select(Objective.id).where(Objective.kind == "radar", Objective.status.in_(("planning", "active", "consolidating"))).limit(1))).first()
        scan = (
            await s.execute(select(Task).where(Task.kind == "signal_scan", Task.output.is_not(None)).order_by(Task.updated_at.desc()).limit(1))
        ).scalar_one_or_none()
        titles = {x.url: {"url": x.url, "title": x.title, "source": x.source} for x in (await s.execute(select(Signal))).scalars()}
    gov = await office.gov.snapshot()
    by_wave: dict[str, list[dict[str, Any]]] = {}
    for sn in snaps:
        by_wave.setdefault(sn.wave_id, []).append({"at": sn.created_at, "stage": sn.stage, "impact": sn.impact, "urgency": sn.urgency, "evidence": sn.evidence_count})
    wave_names = {w.id: w.name for w in waves}
    return {
        "settings": {"enabled": gov["radar_enabled"], "interval_seconds": gov["radar_interval_seconds"], "provider": office.llm.client.provider},
        "running": bool(active),
        "brief": {"text": last.final_report.get("summary"), "at": last.final_report.get("closed_at"), "counts": {k: last.final_report.get(k) for k in ("signals", "waves", "plays")}} if last else None,
        "waves": sorted(
            [
                {
                    "id": w.id, "slug": w.slug, "name": w.name, "thesis": w.thesis, "stage": w.stage, "impact": w.impact, "urgency": w.urgency,
                    "confidence": w.confidence, "window": w.window, "relevance": w.relevance, "status": w.status, "demo": w.demo,
                    "evidence": [titles.get(u, {"url": u, "title": u, "source": ""}) for u in (w.evidence or [])][-6:][::-1],
                    "evidence_count": len(w.evidence or []), "history": by_wave.get(w.id, [])[-12:], "updated_at": w.updated_at,
                }
                for w in waves
            ],
            key=lambda w: (-STAGE_ORDER.get(w["stage"], 0), -(w["impact"] * w["urgency"])),
        ),
        "plays": [
            {
                "id": p.id, "wave": wave_names.get(p.wave_id or "", "—"), "title": p.title, "action": p.action, "why": p.why, "first_step": p.first_step,
                "effort": p.effort, "est_cost_usd": p.est_cost_usd, "deadline_days": p.deadline_days, "requires_spend": p.requires_spend,
                "status": p.status, "demo": p.demo, "created_at": p.created_at,
            }
            for p in plays
        ],
        "signals": [
            {"url": x.url, "title": x.title, "source": x.source, "summary": x.summary, "topics": x.topics, "relevance": x.relevance,
             "found_via": x.found_via, "published_at": x.published_at, "created_at": x.created_at, "demo": x.demo}
            for x in signals
        ],
        "sources": {
            "feed_health": (scan.output or {}).get("feed_health", []) if scan else [],
            "search_errors": (scan.output or {}).get("search_errors", []) if scan else [],
            "mode": (scan.output or {}).get("mode") if scan else None,
        },
    }


@write.post("/radar/sweep")
async def sweep(office: Office = Depends(get_office)) -> dict[str, Any]:
    await office.trigger_radar("founder")
    return {"ok": True, "message": "varredura encomendada ao CVO (ignorada se já houver uma em andamento)"}


class PlayDecision(BaseModel):
    status: str = Field(pattern="^(approved|rejected|done)$")
    spend_limit_usd: float | None = Field(default=None, ge=0)


@write.post("/plays/{play_id}")
async def decide_play(play_id: str, body: PlayDecision, office: Office = Depends(get_office)) -> dict[str, Any]:
    async with session_scope() as s:
        p = await s.get(PlayAction, play_id)
        if p is None:
            raise HTTPException(404, "ação não encontrada")
        if body.status == "approved" and p.status != "approved":
            limit = body.spend_limit_usd if body.spend_limit_usd is not None else p.est_cost_usd
            spend = f" Gasto autorizado pelo fundador: até US$ {limit:.0f}." if p.requires_spend else " Sem gasto extra."
            d = Directive(text=f"[Radar] {p.title}: {p.action} Primeiro passo: {p.first_step}.{spend}"[:2000])
            s.add(d)
            await s.flush()
            p.directive_id = d.id
        if body.status in ("rejected", "done") and p.directive_id:
            d = await s.get(Directive, p.directive_id)
            if d:
                d.active = False  # ação encerrada não deve continuar orientando o CVO
        p.status = body.status
        p.decided_at = datetime.now(UTC)
        title = p.title
    await office.emit("play_decided", title=title, status=body.status)
    return {"ok": True}


@write.post("/waves/{wave_id}/archive")
async def archive_wave(wave_id: str) -> dict[str, Any]:
    async with session_scope() as s:
        w = await s.get(Wave, wave_id)
        if w is None:
            raise HTTPException(404, "onda não encontrada")
        w.status = "archived"
    return {"ok": True}
