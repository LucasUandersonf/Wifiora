"""Setor Financeiro & Performance."""

from __future__ import annotations

from typing import Any

from app.agents.specialist import SpecialistAgent
from app.models import Objective, Task


class UnitEconomicsAgent(SpecialistAgent):
    agent_id = "finance.unit_economics"
    title = "Unit Economics & Financial Agent"
    sector = "finance"
    task_kind = "unit_economics"
    skill_names = ("cost_report",)
    mission = "Monitorar custos (tokens, Railway, domínios), receitas reais e projetadas, margem, ROI e runway. Defender o caixa."

    async def execute(self, task: Task, deps: dict[str, dict[str, Any]], objective: Objective) -> dict[str, Any]:
        report = await self.use("cost_report")
        metrics = {
            "cash": report["cash"],
            "burn_per_day": report["burn_per_day"],
            "runway_days": report["runway_days"],
            "month_spend": report["month"]["total"],
            "month_budget": report["month"]["budget"],
            "month_budget_used": round(report["month"]["total"] / report["month"]["budget"], 4) if report["month"]["budget"] else None,
            "llm_today": report["today"]["llm"],
            "cost_per_published_entity": report["cost_per_published_entity"],
            "revenue_real": report["revenue"]["real"],
            "revenue_projected": report["revenue"]["projected"],
            "margin": report["margin"],
            "top_cost_agents": sorted(report["by_agent"], key=lambda a: -a["cost"])[:5],
        }
        from app.core import viability

        verdicts = [{"hub": v["hub"], "verdict": v["verdict"], "days_live": v["days_live"], "reasons": v["reasons"]} for v in await viability.latest()]
        if verdicts:
            metrics["viability"] = verdicts
        if metrics["month_budget_used"] and metrics["month_budget_used"] > 0.8:
            await self.office.alert("warning", self.agent_id, f"{metrics['month_budget_used']:.0%} do orçamento mensal consumido")
        analysis = await self.think(
            "unit_economics",
            self.task_prompt(task, objective, f"Métricas:\n{self.dumps(metrics)}\nRetorne JSON: assessment, recommendations [..], risks [..]."),
            context={"metrics": metrics},
            objective_id=task.objective_id,
            task_id=task.id,
        )
        return {"metrics": metrics, "analysis": analysis}


class GrowthAgent(SpecialistAgent):
    agent_id = "finance.growth"
    title = "Growth & Monetization Agent"
    sector = "finance"
    task_kind = "growth_plan"
    mission = "Identificar canais de monetização: CPL (leads), afiliados por cadastro/venda aprovada, perfis premium verificados, relatórios setoriais e API semântica paga."

    async def execute(self, task: Task, deps: dict[str, dict[str, Any]], objective: Objective) -> dict[str, Any]:
        prompt = self.task_prompt(
            task,
            objective,
            "Modelo de monetização em camadas: (1) CPL & afiliados B2B; (2) Verified Premium Profiles (SaaS); (3) API semântica paga.\n"
            "Retorne JSON: opportunities [{channel (cpl|affiliate|premium_profile|api|report|sponsorship), title, "
            "est_monthly_usd (estimativa conservadora), confidence (0-0.9), first_step}]. "
            "Estimativas são hipóteses: seja conservador e explique premissas em first_step.",
        )
        return await self.think("growth_plan", prompt, context={"niche": objective.niche}, objective_id=task.objective_id, task_id=task.id)
