"""Scouts setoriais (líderes): decompõem o objetivo em sub-tarefas, gerenciam dependências,
consolidam as entregas aprovadas e reportam ao CVO."""

from __future__ import annotations

from typing import Any

from app.agents.base import BaseAgent
from app.bus.base import Envelope
from app.db import session_scope
from app.models import Task, TaskStatus

CVO_ID = "cvo"


class ScoutAgent(BaseAgent):
    role = "scout"
    # agent_id do especialista -> task_kind (preenchido pelo organograma)
    specialists: dict[str, str] = {}

    def __init__(self, office: Any, specialists: dict[str, str]) -> None:
        super().__init__(office)
        self.specialists = specialists

    # ------------------------------------------------------------ decomposição
    async def on_objective_assign(self, env: Envelope) -> None:
        p = env.payload
        objective_id = env.objective_id or ""
        if await self.objective_tasks(objective_id, self.sector):
            return  # idempotência: o setor já recebeu este objetivo

        plan = await self.think(
            "scout.decompose",
            (
                f"Objetivo do CVO: {p.get('objective_title')}\nNicho: {p.get('niche')}\n"
                f"Briefing para o setor {self.sector}: {p.get('brief')}\n"
                f"Relatórios de fases anteriores: {self.dumps(p.get('prior_reports', {}), 6000)}\n"
                f"Especialistas disponíveis (agent_id -> tipo de tarefa): {self.specialists}\n\n"
                "Quebre o briefing em sub-tarefas executáveis (normalmente uma por especialista). Retorne JSON: "
                "{tasks: [{title, kind, assignee (agent_id), brief (instruções específicas e critérios de aceite), "
                "priority (1-10), depends_on [índices de tarefas desta lista]}], notes}."
            ),
            context={"sector": self.sector, "specialists": self.specialists},
            objective_id=objective_id,
        )
        specs = self._sanitize(plan.get("tasks") or [])

        created: list[Task] = []
        async with session_scope() as s:
            for spec in specs:
                t = Task(
                    objective_id=objective_id,
                    sector=self.sector,
                    kind=spec["kind"],
                    title=spec["title"][:300],
                    brief=spec.get("brief", "")[:4000],
                    owner_id=self.agent_id,
                    assignee_id=spec["assignee"],
                    priority=int(spec.get("priority", 5)),
                    context={"niche": p.get("niche"), "phase": p.get("phase")},
                )
                s.add(t)
                created.append(t)
            await s.flush()
            for t, spec in zip(created, specs, strict=True):
                t.depends_on = [created[i].id for i in spec.get("depends_on", []) if isinstance(i, int) and 0 <= i < len(created) and created[i] is not t]
        await self.office.emit("tasks_created", sector=self.sector, objective_id=objective_id, count=len(created))
        await self._dispatch_ready(objective_id)

    def _sanitize(self, raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Garante que toda tarefa vá para um especialista real do setor e que todo especialista seja usado."""
        kind_to_agent = {k: a for a, k in self.specialists.items()}
        clean: list[dict[str, Any]] = []
        for spec in raw:
            assignee = spec.get("assignee")
            if assignee not in self.specialists:
                assignee = kind_to_agent.get(spec.get("kind", ""))
            if not assignee:
                continue
            clean.append({**spec, "assignee": assignee, "kind": self.specialists[assignee], "title": spec.get("title") or self.specialists[assignee]})
        used = {c["assignee"] for c in clean}
        for agent_id, kind in self.specialists.items():
            if agent_id not in used:
                clean.append({"title": kind.replace("_", " ").title(), "kind": kind, "assignee": agent_id, "brief": "Tarefa padrão do especialista.", "depends_on": []})
        return clean

    async def _dispatch_ready(self, objective_id: str) -> None:
        tasks = await self.objective_tasks(objective_id, self.sector)
        status = {t.id: t.status for t in tasks}
        for t in sorted(tasks, key=lambda t: -t.priority):
            if t.status != TaskStatus.PENDING.value:
                continue
            dep_status = [status.get(d) for d in t.depends_on]
            if any(s in (TaskStatus.FAILED.value, TaskStatus.ESCALATED.value, TaskStatus.CANCELLED.value) for s in dep_status):
                await self.update_task(t.id, status=TaskStatus.CANCELLED, error="dependência não concluída")
                status[t.id] = TaskStatus.CANCELLED.value
                continue
            if all(s == TaskStatus.APPROVED.value for s in dep_status):
                await self.update_task(t.id, status=TaskStatus.ASSIGNED)
                await self.send(t.assignee_id, "task.assign", objective_id=objective_id, task_id=t.id, summary=f"executar: {t.title}")
        await self._check_completion(objective_id)

    # ----------------------------------------------------------- retornos
    async def on_task_approved(self, env: Envelope) -> None:
        task = await self.get_task(env.task_id or "")
        if task is None:
            return
        await self.office.executor.stage(task)
        await self._dispatch_ready(task.objective_id)

    async def on_task_escalated(self, env: Envelope) -> None:
        await self.send(CVO_ID, "task.escalated", env.payload, objective_id=env.objective_id, task_id=env.task_id, summary=env.summary)
        await self._dispatch_ready(env.objective_id or "")

    async def on_task_failed(self, env: Envelope) -> None:
        await self._dispatch_ready(env.objective_id or "")

    async def _check_completion(self, objective_id: str) -> None:
        tasks = await self.objective_tasks(objective_id, self.sector)
        if not tasks or not all(TaskStatus(t.status).terminal for t in tasks):
            return
        approved = [t for t in tasks if t.status == TaskStatus.APPROVED.value]
        report = {
            "sector": self.sector,
            "status": "ok" if len(approved) == len(tasks) else ("partial" if approved else "failed"),
            "tasks": [{"id": t.id, "kind": t.kind, "title": t.title, "status": t.status, "score": t.last_score} for t in tasks],
            "outputs": {t.kind: _digest(t.output or {}) for t in approved},
        }
        await self.send(CVO_ID, "sector.report", report, objective_id=objective_id, summary=f"relatório {self.sector}: {report['status']}")


def _digest(output: dict[str, Any]) -> dict[str, Any]:
    """Versão compacta da saída para o CVO (evita estourar contexto com listas enormes)."""
    out: dict[str, Any] = {}
    for k, v in output.items():
        if isinstance(v, list) and len(v) > 8:
            out[k] = v[:8] + [f"... +{len(v) - 8} itens"]
        else:
            out[k] = v
    return out


def make_scout(agent_id: str, title: str, sector: str, mission: str) -> type[ScoutAgent]:
    return type(f"{sector.title()}Scout", (ScoutAgent,), {"agent_id": agent_id, "title": title, "sector": sector, "mission": mission})
