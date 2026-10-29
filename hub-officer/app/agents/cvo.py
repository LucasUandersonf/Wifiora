"""Chief Virtual Officer — CEO autônomo do escritório.

Responsabilidades:
  * ciclo estratégico: lê KPIs, caixa, diretrizes do fundador e hubs existentes -> define objetivo;
  * planeja fases e distribui briefings aos Scouts setoriais;
  * consolida relatórios setoriais e decide a execução (publicar hub, pedir aprovação, abortar);
  * trata escalonamentos e decisões do fundador (human-in-the-loop).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select

from app.agents.base import BaseAgent
from app.bus.base import Envelope
from app.db import session_scope
from app.models import ApprovalRequest, ApprovalStatus, Entity, Hub, Objective, ObjectiveStatus, Wave

ACTIVE_STATUSES = (ObjectiveStatus.PLANNING.value, ObjectiveStatus.ACTIVE.value, ObjectiveStatus.CONSOLIDATING.value)

DEFAULT_PHASES = [
    {"phase": 1, "assignments": [
        {"sector": "research", "brief": "Mapear o nicho, desenhar o schema e extrair dados verificados dos principais fornecedores."},
        {"sector": "finance", "brief": "Atualizar unit economics e mapear monetização do nicho."},
    ]},
    {"phase": 2, "assignments": [
        {"sector": "tech", "brief": "Gerar a página SSR do hub com JSON-LD e validar a infraestrutura."},
    ]},
]


class ChiefVirtualOfficer(BaseAgent):
    agent_id = "cvo"
    title = "Chief Virtual Officer (CVO)"
    sector = "executive"
    role = "orchestrator"
    tier = "strategic"
    skill_names = ("cost_report",)
    mission = (
        "Operar e escalar de forma autônoma e lucrativa uma empresa de GEO / Hub Semântico de Dados Estruturados, "
        "em nichos brasileiros com volume de busca e empresas que pagam por cliente. Priorizar o que aumenta citações por LLMs e receita, "
        "respeitando orçamento e diretrizes do fundador."
    )

    @property
    def scouts(self) -> dict[str, str]:
        return self.office.scouts_by_sector

    # ------------------------------------------------------------ ciclo
    async def on_cycle_start(self, env: Envelope) -> None:
        async with session_scope() as s:
            active = (
                await s.execute(select(Objective.id).where(Objective.status.in_(ACTIVE_STATUSES), Objective.kind == "production").limit(1))
            ).first()
            if active:
                self.log.info("ciclo ignorado: objetivo %s ainda ativo", active[0])
                return
            hubs = [
                {"slug": h.slug, "title": h.title, "status": h.status, "entities": n}
                for h, n in (
                    await s.execute(select(Hub, func.count(Entity.id)).outerjoin(Entity, Entity.hub_id == Hub.id).group_by(Hub.id))
                ).all()
            ]
            recent = [
                {"title": o.title, "status": o.status}
                for o in (await s.execute(select(Objective).where(Objective.kind == "production").order_by(Objective.created_at.desc()).limit(5))).scalars()
            ]
            waves = [
                {"onda": w.name, "fase": w.stage, "impacto": w.impact, "urgencia": w.urgency, "janela": w.window}
                for w in (await s.execute(select(Wave).where(Wave.status != "archived").order_by((Wave.impact * Wave.urgency).desc()).limit(5))).scalars()
            ]

        await self.office.ledger.accrue_fixed_costs()
        finance = await self.use("cost_report")
        gov = await self.office.gov.snapshot()
        directives = await self.office.gov.active_directives()
        from app.core import niches

        requested = env.payload.get("niche")
        niche = await niches.resolve_focus(requested or gov["focus_niche"], rotation=bool(gov["niche_rotation"]) and not requested)
        focus = niches.label(niche) if niche else (requested or gov["focus_niche"])
        niche_map = await niches.playbook()
        niche_rules = await niches.rules_for(niche.slug if niche else focus)

        plan = await self.think(
            "cvo.plan",
            (
                f"Nicho deste ciclo (catálogo + rodízio): {focus}\n"
                f"{niche_map}\n"
                f"Diretrizes do fundador: {directives or 'nenhuma'}\n"
                f"Nível de autonomia: {gov['autonomy_level']}\n"
                f"Finanças: caixa US$ {finance['cash']}, gasto mês US$ {finance['month']['total']} de US$ {finance['month']['budget']}, "
                f"runway {finance['runway_days']} dias, receita real US$ {finance['revenue']['real']}\n"
                f"Hubs existentes: {hubs}\nObjetivos recentes: {recent}\n"
                f"Ondas de mercado monitoradas pelo Radar (considere ao escolher nicho e prioridades): {waves or 'nenhuma ainda'}\n"
                f"Setores disponíveis (scouts): {list(self.scouts)}\n\n"
                "Defina o PRÓXIMO objetivo de maior ROI. Retorne JSON: {title, niche, rationale, "
                "kpis {..}, phases: [{phase: n, assignments: [{sector, brief}]}]}. "
                "Regras: 'research' sempre antes de 'tech' (a página depende dos dados); 'finance' pode rodar em paralelo."
            ),
            context={"niche": focus},
        )
        phases = self._sanitize_phases(plan.get("phases") or [])
        async with session_scope() as s:
            obj = Objective(
                kind="production",
                title=str(plan.get("title") or f"Hub: {focus}")[:300],
                rationale=str(plan.get("rationale", "")),
                niche=(niche.name if niche else str(plan.get("niche") or focus))[:200],
                niche_slug=niche.slug if niche else None,
                status=ObjectiveStatus.ACTIVE.value,
                plan={"kpis": plan.get("kpis", {}), "phases": phases, "triggered_by": env.sender, "niche_rules": niche_rules},
                current_phase=phases[0]["phase"],
            )
            s.add(obj)
        await self.office.emit("objective", objective_id=obj.id, title=obj.title, status=obj.status)
        await self._dispatch_phase(obj.id)

    async def on_radar_start(self, env: Envelope) -> None:
        """Encomenda uma varredura ao Radar de Ondas (roda em paralelo aos ciclos de produção)."""
        if "radar" not in self.scouts:
            return
        async with session_scope() as s:
            busy = (
                await s.execute(select(Objective.id).where(Objective.kind == "radar", Objective.status.in_(ACTIVE_STATUSES)).limit(1))
            ).first()
            if busy:
                return
            obj = Objective(
                kind="radar",
                title="Varredura do Radar de Ondas",
                niche="IA como canal de busca e compra",
                rationale="Vigiar novidades de IA, GEO, anúncios e compras em assistentes para nos posicionarmos antes da onda.",
                status=ObjectiveStatus.ACTIVE.value,
                plan={"phases": [{"phase": 1, "assignments": [{"sector": "radar", "brief": "Coletar sinais, atualizar as ondas e propor ações de posicionamento com boletim para o fundador."}]}], "triggered_by": env.sender},
                current_phase=1,
            )
            s.add(obj)
        await self.office.emit("objective", objective_id=obj.id, title=obj.title, status=obj.status)
        await self._dispatch_phase(obj.id)

    def _sanitize_phases(self, phases: list[dict[str, Any]]) -> list[dict[str, Any]]:
        valid = []
        for ph in phases:
            assigns = [a for a in ph.get("assignments", []) if a.get("sector") in self.scouts and a.get("sector") != "radar"]
            if assigns:
                valid.append({"phase": int(ph.get("phase", len(valid) + 1)), "assignments": assigns})
        valid.sort(key=lambda p: p["phase"])
        sectors_by_phase = {a["sector"]: p["phase"] for p in valid for a in p["assignments"]}
        if "research" not in sectors_by_phase:
            return DEFAULT_PHASES
        # tech depende de research: empurra tech para uma fase posterior se necessário
        if "tech" in sectors_by_phase and sectors_by_phase["tech"] <= sectors_by_phase["research"]:
            tech = next(a for p in valid for a in p["assignments"] if a["sector"] == "tech")
            for p in valid:
                p["assignments"] = [a for a in p["assignments"] if a["sector"] != "tech"]
            valid = [p for p in valid if p["assignments"]]
            valid.append({"phase": sectors_by_phase["research"] + 1, "assignments": [tech]})
            valid.sort(key=lambda p: p["phase"])
        # renumera 1..n
        for i, p in enumerate(valid, start=1):
            p["phase"] = i
        return valid

    async def _dispatch_phase(self, objective_id: str) -> None:
        async with session_scope() as s:
            obj = await s.get(Objective, objective_id)
            assert obj is not None
            phase = next((p for p in obj.plan["phases"] if p["phase"] == obj.current_phase), None)
            title, niche, reports = obj.title, obj.niche, dict(obj.sector_reports or {})
        if phase is None:
            await self._consolidate(objective_id)
            return
        for a in phase["assignments"]:
            await self.send(
                self.scouts[a["sector"]],
                "objective.assign",
                {"objective_title": title, "niche": niche, "brief": a["brief"], "phase": phase["phase"], "prior_reports": reports},
                objective_id=objective_id,
                summary=f"fase {phase['phase']} → {a['sector']}: {a['brief'][:80]}",
            )

    # ---------------------------------------------------- relatórios dos scouts
    async def on_sector_report(self, env: Envelope) -> None:
        sector = env.payload.get("sector")
        async with session_scope() as s:
            obj = await s.get(Objective, env.objective_id)
            if obj is None or obj.status not in ACTIVE_STATUSES:
                return
            reports = dict(obj.sector_reports or {})
            if sector in reports:
                return  # duplicado
            reports[sector] = env.payload
            obj.sector_reports = reports
            phase = next(p for p in obj.plan["phases"] if p["phase"] == obj.current_phase)
            phase_sectors = {a["sector"] for a in phase["assignments"]}
            phase_done = phase_sectors <= set(reports)
            research_failed = sector == "research" and env.payload.get("status") == "failed"
            if phase_done and not research_failed:
                obj.current_phase += 1
            objective_id = obj.id
        if research_failed:
            await self._fail(objective_id, "setor de pesquisa não entregou dados aprovados")
        elif phase_done:
            await self._dispatch_phase(objective_id)

    async def _close_radar(self, objective_id: str) -> None:
        async with session_scope() as s:
            obj = await s.get(Objective, objective_id)
            assert obj is not None
            report = (obj.sector_reports or {}).get("radar", {})
            outputs = report.get("outputs", {})
            brief = (outputs.get("positioning_plan") or {}).get("brief") or "Varredura concluída sem boletim."
            obj.final_report = {
                "summary": brief,
                "decision": "radar",
                "signals": len((outputs.get("signal_scan") or {}).get("signals") or []),
                "waves": len((outputs.get("wave_analysis") or {}).get("waves") or []),
                "plays": len((outputs.get("positioning_plan") or {}).get("plays") or []),
                "closed_at": datetime.now(UTC).isoformat(),
            }
            obj.status = ObjectiveStatus.COMPLETED.value if report.get("status") != "failed" else ObjectiveStatus.FAILED.value
            status, title = obj.status, obj.title
        await self.office.emit("objective", objective_id=objective_id, title=title, status=status)
        await self.office.alert("info", "radar", f"Boletim do radar: {brief[:400]}")

    async def _consolidate(self, objective_id: str) -> None:
        async with session_scope() as s:
            obj = await s.get(Objective, objective_id)
            assert obj is not None
            is_radar = obj.kind == "radar"
        if is_radar:
            await self._close_radar(objective_id)
            return
        async with session_scope() as s:
            obj = await s.get(Objective, objective_id)
            assert obj is not None
            obj.status = ObjectiveStatus.CONSOLIDATING.value
            reports, kpis, hub_id, title = obj.sector_reports, obj.plan.get("kpis", {}), obj.hub_id, obj.title
            validated = 0
            if hub_id:
                validated = int(
                    (await s.execute(select(func.count(Entity.id)).where(Entity.hub_id == hub_id, Entity.validated.is_(True)))).scalar_one()
                )
        gov = await self.office.gov.snapshot()
        decision = await self.think(
            "cvo.consolidate",
            (
                f"Objetivo: {title}\nKPIs planejados: {kpis}\nEntidades validadas no hub: {validated}\n"
                f"Relatórios setoriais:\n{self.dumps(reports, 14000)}\n\n"
                "Consolide e decida. Retorne JSON: {summary, decision ('publish'|'hold'|'discard'), highlights [..], risks [..], next_focus}."
            ),
            objective_id=objective_id,
        )
        choice = decision.get("decision", "hold")
        quality_ok = bool(hub_id) and validated > 0 and all(r.get("status") != "failed" for r in reports.values())
        final_status = ObjectiveStatus.COMPLETED.value
        executed: list[str] = []

        if choice == "publish" and quality_ok:
            if gov["autonomy_level"] >= 1:
                n = await self.office.executor.publish_hub(hub_id)
                executed.append(f"hub publicado com {n} entidades")
            else:
                await self._request_approval(
                    "publish_hub", f"Publicar hub: {title}", {"hub_id": hub_id, "summary": decision.get("summary")}, objective_id
                )
                final_status = ObjectiveStatus.AWAITING_APPROVAL.value
                executed.append("publicação aguardando aprovação do fundador")
        elif choice == "publish":
            executed.append("publicação bloqueada pelo gate de qualidade (sem entidades validadas ou setor falhou)")

        async with session_scope() as s:
            obj = await s.get(Objective, objective_id)
            assert obj is not None
            obj.final_report = {**decision, "executed": executed, "validated_entities": validated, "closed_at": datetime.now(UTC).isoformat()}
            obj.status = final_status
        await self.office.emit("objective", objective_id=objective_id, title=title, status=final_status)
        if decision.get("next_focus"):
            await self.office.alert("info", self.agent_id, f"Ciclo encerrado: {decision.get('summary', '')} Próximo foco: {decision['next_focus']}")

    async def _fail(self, objective_id: str, reason: str) -> None:
        async with session_scope() as s:
            obj = await s.get(Objective, objective_id)
            if obj:
                obj.status = ObjectiveStatus.FAILED.value
                obj.final_report = {"summary": reason, "decision": "discard"}
        await self.office.alert("warning", self.agent_id, f"Objetivo encerrado sem sucesso: {reason}")
        await self.office.emit("objective", objective_id=objective_id, status=ObjectiveStatus.FAILED.value)

    async def _request_approval(self, kind: str, title: str, details: dict[str, Any], objective_id: str | None, amount: float | None = None) -> None:
        async with session_scope() as s:
            s.add(ApprovalRequest(kind=kind, title=title, details=details, amount_usd=amount, requested_by=self.agent_id, objective_id=objective_id))
        await self.office.emit("approval_requested", kind=kind, title=title)

    # ------------------------------------------------------- escalonamentos
    async def on_task_escalated(self, env: Envelope) -> None:
        await self.office.alert("warning", self.agent_id, f"Tarefa escalonada após revisões: {env.summary}. Feedback: {env.payload.get('feedback', '')[:300]}")
        await self._request_approval("escalated_task", env.summary or "Tarefa escalonada", env.payload, env.objective_id)

    # ---------------------------------------------- decisões do fundador
    async def on_founder_decision(self, env: Envelope) -> None:
        async with session_scope() as s:
            req = await s.get(ApprovalRequest, env.payload.get("approval_id"))
            if req is None:
                return
            kind, status, details, objective_id = req.kind, req.status, req.details, req.objective_id
        if kind == "publish_hub" and objective_id:
            async with session_scope() as s:
                obj = await s.get(Objective, objective_id)
                if obj and obj.status == ObjectiveStatus.AWAITING_APPROVAL.value:
                    obj.status = ObjectiveStatus.COMPLETED.value
            if status == ApprovalStatus.APPROVED.value:
                await self.office.executor.publish_hub(details["hub_id"])
        await self.office.emit("founder_decision", kind=kind, status=status)
