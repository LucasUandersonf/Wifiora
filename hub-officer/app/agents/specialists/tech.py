"""Setor de Engenharia & Plataforma."""

from __future__ import annotations

from typing import Any

from app.agents.specialist import SpecialistAgent
from app.db import session_scope
from app.models import Hub, Objective, Task


class FrontendAgent(SpecialistAgent):
    agent_id = "tech.frontend"
    title = "Next.js & Frontend Agent"
    sector = "tech"
    task_kind = "frontend_page"
    skill_names = ("page_render", "jsonld_validator")
    mission = "Gerar páginas SSR/SSG ultraleves (HTML semântico, zero scripts de terceiros, JSON-LD no head) otimizadas para crawlers de LLM e Core Web Vitals."

    async def execute(self, task: Task, deps: dict[str, dict[str, Any]], objective: Objective) -> dict[str, Any]:
        if not objective.hub_id:
            raise RuntimeError("objetivo sem hub — a pesquisa precisa ser aprovada antes da página")
        async with session_scope() as s:
            hub = await s.get(Hub, objective.hub_id)
            assert hub is not None
            hub_info = {"title": hub.title, "niche": hub.niche, "schema": hub.schema_template, "research": hub.research}
        prompt = self.task_prompt(
            task,
            objective,
            f"Hub: {self.dumps(hub_info, 5000)}\n\n"
            "Defina a configuração da página do hub. Retorne JSON: sections [..], table_columns [campos], "
            "faq [{q, a}] (perguntas que usuários fazem a assistentes de IA; respostas curtas e factuais), "
            "meta_description (<=160 chars), performance_budget {max_html_kb, third_party_scripts}.",
        )
        page = await self.think("frontend_page", prompt, objective_id=task.objective_id, task_id=task.id)
        render = await self.use("page_render", hub_id=objective.hub_id, page_config=page)
        return {"page": page, "render": render}


class DevOpsAgent(SpecialistAgent):
    agent_id = "tech.devops"
    title = "DevOps & Railway Agent"
    sector = "tech"
    task_kind = "devops_check"
    skill_names = ("infra_health", "data_distribution_check")
    mission = (
        "Garantir deploys saudáveis no Railway, banco e filas operando, domínios e integrações de API ativos, "
        "e que os arquivos de dados em lote e o grafo de conhecimento estejam íntegros e sendo lidos pelos robôs de IA."
    )

    async def execute(self, task: Task, deps: dict[str, dict[str, Any]], objective: Objective) -> dict[str, Any]:
        health = await self.use("infra_health")
        if not health.get("all_ok"):
            await self.office.alert("critical", self.agent_id, f"infraestrutura degradada: {health}")
        data = await self.use("data_distribution_check")
        if data.get("graph_dangling"):
            await self.office.alert("warning", self.agent_id, f"grafo de conhecimento com {len(data['graph_dangling'])} ponta(s) solta(s): {data['graph_dangling'][:3]}")
        analysis = await self.think(
            "devops_check",
            self.task_prompt(
                task,
                objective,
                f"Saúde atual:\n{self.dumps(health)}\nDados para IAs (arquivos, grafo, robôs nos últimos 7 dias):\n{self.dumps(data)}\n"
                "Retorne JSON: assessment, actions [..].",
            ),
            objective_id=task.objective_id,
            task_id=task.id,
        )
        return {"health": health, "data_distribution": data, "assessment": analysis.get("assessment"), "actions": analysis.get("actions", [])}
