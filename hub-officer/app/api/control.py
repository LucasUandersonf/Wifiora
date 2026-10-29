"""Controle manual (override) do fundador — human-in-the-loop."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, update

from app.api.deps import get_office, require_founder
from app.bus.base import Envelope
from app.core.governance import EDITABLE_KEYS
from app.core.office import Office
from app.db import session_scope
from app.models import Alert, ApprovalRequest, ApprovalStatus, Directive, Objective, ObjectiveStatus, Task, TaskStatus

ACTIVE_OBJECTIVE_STATUSES = (ObjectiveStatus.PLANNING.value, ObjectiveStatus.ACTIVE.value, ObjectiveStatus.CONSOLIDATING.value)

router = APIRouter(prefix="/api/control", tags=["control"], dependencies=[Depends(require_founder)])


class CycleIn(BaseModel):
    niche: str | None = None


class DirectiveIn(BaseModel):
    text: str = Field(min_length=3, max_length=2000)


class DecisionIn(BaseModel):
    approve: bool
    note: str | None = None


class RevenueIn(BaseModel):
    stream: str = Field(pattern="^(cpl|affiliate|premium_profile|api|report|sponsorship|other)$")
    amount_usd: float = Field(gt=0)
    description: str = ""
    hub_id: str | None = None


@router.post("/cycle")
async def run_cycle(body: CycleIn, office: Office = Depends(get_office)) -> dict[str, Any]:
    await office.trigger_cycle("founder", niche=body.niche)
    return {"ok": True, "message": "ciclo solicitado ao CVO (ignorado se já houver objetivo ativo)"}


@router.post("/pause")
async def pause(office: Office = Depends(get_office)) -> dict[str, Any]:
    await office.gov.set("paused", True)
    await office.emit("office_paused", by="founder")
    return {"paused": True}


@router.post("/resume")
async def resume(office: Office = Depends(get_office)) -> dict[str, Any]:
    await office.gov.set("paused", False)
    await office.emit("office_resumed", by="founder")
    return {"paused": False}


@router.patch("/settings")
async def update_settings(body: dict[str, Any], office: Office = Depends(get_office)) -> dict[str, Any]:
    unknown = set(body) - set(EDITABLE_KEYS)
    if unknown:
        raise HTTPException(422, f"chaves não editáveis: {sorted(unknown)}")
    for k, v in body.items():
        await office.gov.set(k, v)
    await office.emit("settings_changed", keys=list(body))
    return await office.gov.snapshot(force=True)


@router.post("/directives")
async def add_directive(body: DirectiveIn, office: Office = Depends(get_office)) -> dict[str, Any]:
    async with session_scope() as s:
        d = Directive(text=body.text)
        s.add(d)
    await office.emit("directive", text=body.text)
    return {"id": d.id, "text": d.text}


@router.delete("/directives/{directive_id}")
async def remove_directive(directive_id: str) -> dict[str, Any]:
    async with session_scope() as s:
        d = await s.get(Directive, directive_id)
        if d is None:
            raise HTTPException(404, "diretriz não encontrada")
        d.active = False
    return {"ok": True}


@router.post("/approvals/{approval_id}")
async def decide(approval_id: str, body: DecisionIn, office: Office = Depends(get_office)) -> dict[str, Any]:
    async with session_scope() as s:
        req = await s.get(ApprovalRequest, approval_id)
        if req is None:
            raise HTTPException(404, "pedido não encontrado")
        if req.status != ApprovalStatus.PENDING.value:
            raise HTTPException(409, "pedido já decidido")
        req.status = (ApprovalStatus.APPROVED if body.approve else ApprovalStatus.REJECTED).value
        req.decision_note = body.note
        req.decided_at = datetime.now(UTC)
        kind, details = req.kind, req.details

    if kind == "budget_increase" and body.approve:
        await office.gov.set("daily_llm_budget_usd", details.get("proposed"))
        await office.gov.set("paused", False)
    elif kind == "budget_increase":
        await office.alert("info", "founder", "Aumento de orçamento negado — o escritório segue pausado até amanhã ou nova decisão.")
    elif kind == "council_proposal":
        if body.approve:
            async with session_scope() as s:
                s.add(Directive(text=f"[Aprovado pelo fundador] {details.get('title')}" + (f" — {body.note}" if body.note else "")))
        await office.emit("founder_decision", kind=kind, status="approved" if body.approve else "rejected")
    else:
        await office.dispatch(Envelope(type="founder.decision", sender="founder", recipient="cvo", payload={"approval_id": approval_id, "approve": body.approve}, summary=f"decisão do fundador: {'aprovado' if body.approve else 'rejeitado'}"))
    return {"ok": True, "status": "approved" if body.approve else "rejected"}


@router.post("/revenue")
async def add_revenue(body: RevenueIn, office: Office = Depends(get_office)) -> dict[str, Any]:
    await office.ledger.record_revenue(body.stream, body.amount_usd, body.description, projected=False, hub_id=body.hub_id)
    await office.emit("revenue", stream=body.stream, amount=body.amount_usd)
    return {"ok": True}


class NicheUpdate(BaseModel):
    status: str | None = Field(default=None, pattern="^(ativo|pausado|bloqueado)$")
    rank: int | None = Field(default=None, ge=1, le=99)


@router.patch("/niches/{slug}")
async def update_niche(slug: str, body: NicheUpdate, office: Office = Depends(get_office)) -> dict[str, Any]:
    from app.core import niches
    from app.models import Niche

    async with session_scope() as s:
        n = await s.get(Niche, slug)
        if n is None:
            raise HTTPException(404, "nicho não encontrado")
        if n.locked and body.status and body.status != "bloqueado":
            raise HTTPException(409, f"{n.name} está fora do mapa por decisão editorial e não pode ser ativado")
        if body.status:
            n.status = body.status
        if body.rank is not None:
            n.rank = body.rank
        out = niches.niche_out(n)
    await office.emit("settings_changed", keys=["niches"])
    return out


@router.post("/niches/{slug}/focus")
async def focus_niche(slug: str, office: Office = Depends(get_office)) -> dict[str, Any]:
    """Põe o nicho em foco: o próximo ciclo do CVO trabalha nele."""
    from app.models import Niche

    async with session_scope() as s:
        n = await s.get(Niche, slug)
        if n is None:
            raise HTTPException(404, "nicho não encontrado")
        if n.status != "ativo":
            raise HTTPException(409, "ative o nicho antes de colocá-lo em foco")
        name = n.name
    await office.gov.set("focus_niche", name, updated_by="founder")
    await office.emit("settings_changed", keys=["focus_niche"])
    return {"ok": True, "focus": name}


class DiagnosisIn(BaseModel):
    brand: str = Field(min_length=2, max_length=200)
    site: str = Field(default="", max_length=500)
    category: str = Field(min_length=3, max_length=300)
    city: str = Field(default="", max_length=120)
    competitors: str | list[Any] = Field(default="")
    contact: str = Field(default="", max_length=300)
    engines: list[str] | None = None  # chatgpt | claude | perplexity (só as configuradas são usadas)
    query_count: int | None = Field(default=None, ge=5, le=50)


@router.post("/diagnoses")
async def new_diagnosis(body: DiagnosisIn, office: Office = Depends(get_office)) -> dict[str, Any]:
    """Cria um Diagnóstico de Visibilidade em IA (roda em segundo plano)."""
    from app.core import diagnosis

    d = await diagnosis.create(office, **body.model_dump())
    diagnosis.start(office, d)
    return {"id": d.id, "report": f"/relatorio/{d.token}"}


class CouncilIn(BaseModel):
    topic: str = Field(min_length=5, max_length=500)


@router.post("/council")
async def convene_council(body: CouncilIn, office: Office = Depends(get_office)) -> dict[str, Any]:
    """Convoca uma reunião do Conselho (roda em segundo plano; acompanhe no painel e no escritório)."""
    from app.core import council

    task = asyncio.create_task(council.convene(office, body.topic, trigger="manual"))
    office.background.add(task)
    task.add_done_callback(office.background.discard)
    return {"ok": True, "topic": body.topic}


@router.post("/content/run")
async def content_run(office: Office = Depends(get_office)) -> dict[str, Any]:
    """Escreve agora o próximo rascunho da pauta e audita a landing da Insighta."""
    from app.core import insighta_content

    return await insighta_content.tick(office, force=True)


class ContentDecision(BaseModel):
    approve: bool
    note: str = Field(default="", max_length=1000)


@router.post("/content/{piece_id}/decide")
async def content_decide(piece_id: str, body: ContentDecision) -> dict[str, Any]:
    """Fundador aprova ou rejeita um rascunho (nada vai ao ar sem isso)."""
    from app.core import insighta_content

    p = await insighta_content.decide(piece_id, body.approve, body.note)
    if p is None:
        raise HTTPException(404, "conteúdo não encontrado")
    return {"id": p.id, "status": p.status}


@router.post("/sales/run")
async def sales_run(office: Office = Depends(get_office)) -> dict[str, Any]:
    """Roda agora uma volta do funil comercial (mesmo com o comercial desligado, para testar)."""
    from app.core import sales

    return await sales.tick(office, force=True)


@router.post("/viability/run")
async def run_viability(office: Office = Depends(get_office)) -> dict[str, Any]:
    """Refaz agora o veredito da semana (o Gauss também roda sozinho toda semana)."""
    from app.core import viability

    return {"ok": True, "hubs": await viability.run(office, force=True)}


@router.post("/alerts/{alert_id}/ack")
async def ack_alert(alert_id: str) -> dict[str, Any]:
    async with session_scope() as s:
        a = await s.get(Alert, alert_id)
        if a is None:
            raise HTTPException(404, "alerta não encontrado")
        a.acknowledged = True
    return {"ok": True}


@router.post("/objectives/{objective_id}/cancel")
async def cancel_objective(objective_id: str, office: Office = Depends(get_office)) -> dict[str, Any]:
    async with session_scope() as s:
        obj = await s.get(Objective, objective_id)
        if obj is None:
            raise HTTPException(404, "objetivo não encontrado")
        obj.status = ObjectiveStatus.CANCELLED.value
        await s.execute(
            update(Task)
            .where(Task.objective_id == objective_id, Task.status.not_in([st.value for st in TaskStatus if st.terminal]))
            .values(status=TaskStatus.CANCELLED.value, error="cancelado pelo fundador")
        )
    await office.emit("objective", objective_id=objective_id, status="cancelled")
    return {"ok": True}


@router.post("/kill")
async def kill_switch(office: Office = Depends(get_office)) -> dict[str, Any]:
    """Parada de emergência: pausa todos os agentes, cancela o ciclo ativo e esvazia as filas."""
    await office.gov.set("paused", True, updated_by="founder:kill_switch")
    cancelled: list[str] = []
    async with session_scope() as s:
        active = (await s.execute(select(Objective).where(Objective.status.in_(ACTIVE_OBJECTIVE_STATUSES)))).scalars().all()
        for obj in active:
            obj.status = ObjectiveStatus.CANCELLED.value
            cancelled.append(obj.id)
        if cancelled:
            await s.execute(
                update(Task)
                .where(Task.objective_id.in_(cancelled), Task.status.not_in([st.value for st in TaskStatus if st.terminal]))
                .values(status=TaskStatus.CANCELLED.value, error="kill switch do fundador")
            )
    purged = await office.bus.purge()
    await office.alert("critical", "founder", f"Kill switch acionado: {len(cancelled)} objetivo(s) cancelado(s), {purged} mensagem(ns) descartada(s).")
    await office.emit("office_paused", by="kill_switch")
    return {"paused": True, "cancelled_objectives": cancelled, "purged_messages": purged}
