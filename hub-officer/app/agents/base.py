"""Agente base: loop de consumo do barramento, despacho por tipo de mensagem, resiliência e telemetria.

Convenção: uma mensagem do tipo `task.assign` é tratada pelo método `on_task_assign`.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from app.bus.base import Envelope
from app.db import session_scope
from app.llm.base import BudgetExceeded
from app.models import AgentState, Task, TaskStatus
from app.skills.base import Skill, SkillError

if TYPE_CHECKING:
    from app.core.office import Office

MAX_DELIVERY_ATTEMPTS = 3


class BaseAgent:
    agent_id: str = "agent"
    title: str = "Agente"
    sector: str = "general"
    role: str = "specialist"  # orchestrator | scout | specialist | evaluator
    tier: str = "worker"  # tier de modelo no LLMGateway
    skill_names: tuple[str, ...] = ()
    mission: str = ""

    def __init__(self, office: Office) -> None:
        self.office = office
        self.log = logging.getLogger(f"agent.{self.agent_id}")
        self.status = "idle"
        self.processed = 0
        self.failures = 0
        available = set(office.skills.names())
        self.skills: dict[str, Skill] = {n: office.skills.get(n) for n in self.skill_names if n in available}

    # ------------------------------------------------------------------ prompt
    @property
    def system_prompt(self) -> str:
        return (
            f"Você é {self.title} ({self.agent_id}) no setor '{self.sector}' de um escritório virtual autônomo "
            f"que opera um Hub Semântico de Dados Estruturados para GEO (Generative Engine Optimization) no Brasil.\n"
            f"Missão: {self.mission}\n"
            "Princípios inegociáveis: (1) taxa zero de alucinação — todo dado precisa de fonte verificável; "
            "(2) concisão e estrutura legível por máquinas; (3) sustentabilidade financeira — evite trabalho sem retorno; "
            "(4) conformidade com LGPD e regras de coleta (robots.txt)."
        )

    # --------------------------------------------------------------- lifecycle
    async def register(self) -> None:
        async with session_scope() as s:
            row = await s.get(AgentState, self.agent_id)
            if row is None:
                row = AgentState(agent_id=self.agent_id, title=self.title, sector=self.sector, role=self.role)
                s.add(row)
            row.title, row.sector, row.role = self.title, self.sector, self.role
            row.skills = sorted(self.skills)
            row.status = "idle"
            row.current_task_id = None
            row.current_activity = ""
            self.processed, self.failures = row.processed or 0, row.failures or 0

    async def run(self) -> None:
        self.log.info("agente online")
        async for env in self.office.bus.consume(self.agent_id):
            await self.office.wait_if_paused()
            await self._process(env)

    async def _process(self, env: Envelope) -> None:
        handler = getattr(self, "on_" + env.type.replace(".", "_"), None)
        if handler is None:
            self.log.warning("sem handler para %s", env.type)
            return
        await self.set_status("working", activity=env.summary or env.type, task_id=env.task_id)
        try:
            await handler(env)
            self.processed += 1
        except BudgetExceeded as e:
            await self.office.handle_budget_block(self, env, e)
        except Exception as e:
            self.failures += 1
            self.log.exception("falha ao processar %s", env.type)
            await self.on_error(env, e)
        finally:
            await self.set_status("idle")

    async def on_error(self, env: Envelope, exc: Exception) -> None:
        """Retry com backoff; esgotadas as tentativas, a tarefa falha e o dono (scout) é avisado."""
        if env.attempt + 1 < MAX_DELIVERY_ATTEMPTS:
            await asyncio.sleep(min(30, 2 ** (env.attempt + 1)) if not self.office.fast_retry else 0)
            retry = env.model_copy(update={"attempt": env.attempt + 1})
            await self.office.bus.send(retry)
            return
        await self.office.alert("warning", self.agent_id, f"{env.type} falhou após {MAX_DELIVERY_ATTEMPTS} tentativas: {exc}")
        if env.task_id:
            task = await self.update_task(env.task_id, status=TaskStatus.FAILED, error=str(exc)[:2000])
            if task:
                await self.send(task.owner_id, "task.failed", {"error": str(exc)[:500]}, objective_id=task.objective_id, task_id=task.id, summary=f"falhou: {task.title}")

    # ----------------------------------------------------------------- helpers
    async def set_status(self, status: str, *, activity: str = "", task_id: str | None = None) -> None:
        self.status = status
        async with session_scope() as s:
            row = await s.get(AgentState, self.agent_id)
            if row:
                row.status = status
                row.current_activity = activity[:500]
                row.current_task_id = task_id
                row.processed = self.processed
                row.failures = self.failures
        await self.office.emit("agent_status", agent_id=self.agent_id, status=status, activity=activity[:200], task_id=task_id)

    async def think(
        self,
        kind: str,
        prompt: str,
        *,
        context: dict[str, Any] | None = None,
        objective_id: str | None = None,
        task_id: str | None = None,
        tier: str | None = None,
    ) -> dict[str, Any]:
        return await self.office.llm.complete_json(
            kind=kind,
            system=self.system_prompt,
            prompt=prompt,
            tier=tier or self.tier,
            agent_id=self.agent_id,
            objective_id=objective_id,
            task_id=task_id,
            context=context,
        )

    async def use(self, skill: str, **kwargs: Any) -> dict[str, Any]:
        if skill not in self.skills:
            raise SkillError(f"{self.agent_id} não possui a skill {skill}")
        await self.office.emit("skill", agent_id=self.agent_id, skill=skill)
        return await self.skills[skill].run(**kwargs)

    async def send(
        self,
        recipient: str,
        type_: str,
        payload: dict[str, Any] | None = None,
        *,
        objective_id: str | None = None,
        task_id: str | None = None,
        summary: str = "",
    ) -> None:
        await self.office.dispatch(
            Envelope(type=type_, sender=self.agent_id, recipient=recipient, payload=payload or {}, objective_id=objective_id, task_id=task_id, summary=summary)
        )

    @staticmethod
    def dumps(obj: Any, limit: int = 12000) -> str:
        text = json.dumps(obj, ensure_ascii=False, default=str, indent=1)
        return text if len(text) <= limit else text[:limit] + "\n…(truncado)"

    # -------------------------------------------------------------- task store
    @staticmethod
    async def get_task(task_id: str) -> Task | None:
        async with session_scope() as s:
            return await s.get(Task, task_id)

    @staticmethod
    async def update_task(task_id: str, **fields: Any) -> Task | None:
        async with session_scope() as s:
            task = await s.get(Task, task_id)
            if task is None:
                return None
            for k, v in fields.items():
                setattr(task, k, v.value if isinstance(v, TaskStatus) else v)
            return task

    @staticmethod
    async def objective_tasks(objective_id: str, sector: str | None = None) -> list[Task]:
        async with session_scope() as s:
            q = select(Task).where(Task.objective_id == objective_id)
            if sector:
                q = q.where(Task.sector == sector)
            return list((await s.execute(q.order_by(Task.created_at))).scalars())
