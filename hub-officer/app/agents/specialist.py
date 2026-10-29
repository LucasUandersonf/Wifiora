"""Base dos especialistas: recebem tarefa, executam com skills + LLM e submetem ao Score Agent."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.agents.base import BaseAgent
from app.bus.base import Envelope
from app.db import session_scope
from app.models import Objective, Task, TaskStatus

EVALUATOR_ID = "quality.score"


class SpecialistAgent(BaseAgent):
    role = "specialist"
    task_kind: str = "generic"

    async def on_task_assign(self, env: Envelope) -> None:
        await self._work(env)

    async def on_task_revise(self, env: Envelope) -> None:
        await self._work(env)

    async def _work(self, env: Envelope) -> None:
        task = await self.get_task(env.task_id or "")
        if task is None or TaskStatus(task.status).terminal:
            return
        await self.update_task(task.id, status=TaskStatus.IN_PROGRESS)
        deps = await self._dependency_outputs(task)
        objective = await self._objective(task.objective_id)
        output = await self.execute(task, deps, objective)
        await self.update_task(task.id, status=TaskStatus.IN_REVIEW, output=output, error=None)
        await self.send(EVALUATOR_ID, "review.request", objective_id=task.objective_id, task_id=task.id, summary=f"revisar: {task.title}")

    async def execute(self, task: Task, deps: dict[str, dict[str, Any]], objective: Objective) -> dict[str, Any]:
        raise NotImplementedError

    # ---------------------------------------------------------------- helpers
    @staticmethod
    async def _objective(objective_id: str) -> Objective:
        async with session_scope() as s:
            obj = await s.get(Objective, objective_id)
            assert obj is not None
            return obj

    @staticmethod
    async def _dependency_outputs(task: Task) -> dict[str, dict[str, Any]]:
        """Saídas aprovadas desta e de fases anteriores do objetivo, indexadas por `kind`."""
        async with session_scope() as s:
            rows = (
                await s.execute(
                    select(Task).where(Task.objective_id == task.objective_id, Task.status == TaskStatus.APPROVED.value).order_by(Task.updated_at)
                )
            ).scalars()
            return {t.kind: t.output or {} for t in rows}

    def task_prompt(self, task: Task, objective: Objective, extra: str = "") -> str:
        parts = [
            f"Objetivo estratégico do CVO: {objective.title}",
            f"Nicho: {objective.niche}",
            *([rules] if (rules := (getattr(objective, "plan", None) or {}).get("niche_rules")) else []),
            f"Tarefa: {task.title}",
            f"Briefing do Scout: {task.brief}",
        ]
        if task.feedback and task.status != TaskStatus.APPROVED.value:
            parts.append(f"ATENÇÃO — feedback do Score Agent da tentativa anterior (corrija tudo): {task.feedback}")
        if extra:
            parts.append(extra)
        return "\n".join(parts)
