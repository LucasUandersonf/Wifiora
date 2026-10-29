"""Quality Scout / Score Agent — porteiro de qualidade de todas as entregas.

Nota final = 0.6 × rubrica determinística + 0.4 × juiz LLM (alinhamento estratégico, clareza).
Qualquer check bloqueante reprovado => reprovação, mesmo com nota alta.
Reprovado: volta ao especialista com feedback (até MAX_REVISIONS). Depois disso: escalonado ao CVO.
"""

from __future__ import annotations

from sqlalchemy import func, select

from app.agents.base import BaseAgent
from app.agents.rubrics import run_rubric
from app.bus.base import Envelope
from app.db import session_scope
from app.models import AgentState, Evaluation, Task, TaskStatus

DET_WEIGHT, LLM_WEIGHT = 0.6, 0.4


class ScoreAgent(BaseAgent):
    agent_id = "quality.score"
    title = "Quality Scout / Score Agent"
    sector = "quality"
    role = "evaluator"
    tier = "judge"
    mission = "Avaliar cada entrega com rigor: precisão dos dados, conformidade estrutural e alinhamento com a estratégia do CVO e as diretrizes do fundador."

    async def on_review_request(self, env: Envelope) -> None:
        task = await self.get_task(env.task_id or "")
        if task is None or task.status != TaskStatus.IN_REVIEW.value:
            return
        output = task.output or {}
        det_score, checks = run_rubric(task.kind, output)
        blocking_failed = [c for c in checks if c.blocking and not c.passed]

        llm_score, llm_feedback = None, ""
        try:
            directives = await self.office.gov.active_directives()
            judge = await self.think(
                "evaluation.judge",
                (
                    f"Avalie a entrega da tarefa '{task.title}' (tipo {task.kind}).\n"
                    f"Briefing: {task.brief}\n"
                    f"Diretrizes do fundador: {directives or 'nenhuma'}\n"
                    f"Checks determinísticos: {[c.as_dict() for c in checks]}\n"
                    f"Saída do especialista:\n{self.dumps(output, 8000)}\n\n"
                    'Retorne {"score": 0.0-1.0, "feedback": "instruções objetivas de correção ou elogio curto"}.'
                ),
                context={"deterministic_score": det_score, "kind": task.kind},
                objective_id=task.objective_id,
                task_id=task.id,
            )
            llm_score = max(0.0, min(1.0, float(judge.get("score", 0))))
            llm_feedback = str(judge.get("feedback", ""))
        except Exception as e:
            self.log.warning("juiz LLM indisponível: %s", e)

        score = det_score if llm_score is None else round(DET_WEIGHT * det_score + LLM_WEIGHT * llm_score, 4)
        threshold = float(await self.office.gov.get("score_threshold"))
        passed = score >= threshold and not blocking_failed

        failed_desc = [f"{c.name}{f' ({c.detail})' if c.detail else ''}" for c in checks if not c.passed]
        feedback = "; ".join(filter(None, [("Checks reprovados: " + ", ".join(failed_desc)) if failed_desc else "", llm_feedback]))

        async with session_scope() as s:
            s.add(
                Evaluation(
                    task_id=task.id,
                    evaluator_id=self.agent_id,
                    score=score,
                    deterministic_score=det_score,
                    llm_score=llm_score,
                    passed=passed,
                    checks=[c.as_dict() for c in checks],
                    feedback=feedback,
                )
            )
        await self._refresh_agent_avg(task.assignee_id)
        await self.office.emit("evaluation", task_id=task.id, kind=task.kind, score=score, passed=passed, assignee=task.assignee_id)

        if passed:
            await self.update_task(task.id, status=TaskStatus.APPROVED, last_score=score, feedback=feedback)
            await self.send(task.owner_id, "task.approved", {"score": score}, objective_id=task.objective_id, task_id=task.id, summary=f"aprovada ({score:.2f}): {task.title}")
        elif task.revisions < self.office.settings.max_revisions:
            await self.update_task(task.id, status=TaskStatus.REVISION, last_score=score, feedback=feedback, revisions=task.revisions + 1)
            await self.send(
                task.assignee_id,
                "task.revise",
                {"feedback": feedback, "score": score},
                objective_id=task.objective_id,
                task_id=task.id,
                summary=f"revisão {task.revisions + 1} ({score:.2f}): {task.title}",
            )
        else:
            await self.update_task(task.id, status=TaskStatus.ESCALATED, last_score=score, feedback=feedback)
            await self.send(task.owner_id, "task.escalated", {"score": score, "feedback": feedback}, objective_id=task.objective_id, task_id=task.id, summary=f"escalonada: {task.title}")

    async def _refresh_agent_avg(self, agent_id: str) -> None:
        async with session_scope() as s:
            avg = (
                await s.execute(select(func.avg(Evaluation.score)).join(Task, Task.id == Evaluation.task_id).where(Task.assignee_id == agent_id))
            ).scalar_one()
            row = await s.get(AgentState, agent_id)
            if row is not None and avg is not None:
                row.avg_score = round(float(avg), 4)
