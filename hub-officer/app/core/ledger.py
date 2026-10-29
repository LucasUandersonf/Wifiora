"""Livro-caixa do escritório: custos (LLM/infra/domínio), receitas e métricas de sustentabilidade."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from app.config import Settings
from app.core.governance import Governance
from app.db import session_scope
from app.models import CostEntry, Entity, Hub, RevenueEntry


def _day_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(UTC)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _month_start(now: datetime | None = None) -> datetime:
    return _day_start(now).replace(day=1)


class Ledger:
    def __init__(self, settings: Settings, governance: Governance) -> None:
        self.settings = settings
        self.gov = governance

    # ---------------------------------------------------------------- escrita
    async def record_llm(self, **fields: Any) -> None:
        async with session_scope() as s:
            s.add(CostEntry(category="llm", **fields))

    async def record_cost(self, category: str, amount_usd: float, description: str, **fields: Any) -> None:
        async with session_scope() as s:
            s.add(CostEntry(category=category, amount_usd=amount_usd, description=description, **fields))

    async def record_revenue(self, stream: str, amount_usd: float, description: str = "", projected: bool = False, hub_id: str | None = None) -> None:
        async with session_scope() as s:
            s.add(RevenueEntry(stream=stream, amount_usd=amount_usd, description=description, projected=projected, hub_id=hub_id))

    async def accrue_fixed_costs(self) -> None:
        """Rateia custos fixos mensais (Railway, domínios) por dia. Idempotente por dia."""
        today = _day_start()
        key = f"accrual:{today.date().isoformat()}"
        async with session_scope() as s:
            exists = (await s.execute(select(CostEntry.id).where(CostEntry.description.like(f"{key}%")).limit(1))).first()
            if exists:
                return
            s.add(CostEntry(category="infra", amount_usd=round(self.settings.infra_monthly_cost_usd / 30, 4), description=f"{key}:railway"))
            s.add(CostEntry(category="domain", amount_usd=round(self.settings.domain_monthly_cost_usd / 30, 4), description=f"{key}:domains"))

    # ---------------------------------------------------------------- leitura
    async def _sum_costs(self, since: datetime, category: str | None = None) -> float:
        async with session_scope() as s:
            q = select(func.coalesce(func.sum(CostEntry.amount_usd), 0.0)).where(CostEntry.created_at >= since)
            if category:
                q = q.where(CostEntry.category == category)
            return float((await s.execute(q)).scalar_one())

    async def llm_spend_today(self) -> float:
        return await self._sum_costs(_day_start(), "llm")

    async def llm_calls_today(self) -> int:
        async with session_scope() as s:
            q = select(func.count(CostEntry.id)).where(CostEntry.created_at >= _day_start(), CostEntry.category == "llm")
            return int((await s.execute(q)).scalar_one())

    async def llm_budget_exhausted(self) -> bool:
        budget = float(await self.gov.get("daily_llm_budget_usd"))
        return await self.llm_spend_today() >= budget

    async def summary(self) -> dict[str, Any]:
        now = datetime.now(UTC)
        day, month = _day_start(now), _month_start(now)
        gov = await self.gov.snapshot()
        async with session_scope() as s:
            total_cost = float((await s.execute(select(func.coalesce(func.sum(CostEntry.amount_usd), 0.0)))).scalar_one())
            sim_cost = float(
                (await s.execute(select(func.coalesce(func.sum(CostEntry.amount_usd), 0.0)).where(CostEntry.simulated.is_(True)))).scalar_one()
            )
            rev_rows = (
                await s.execute(
                    select(RevenueEntry.projected, func.coalesce(func.sum(RevenueEntry.amount_usd), 0.0)).group_by(RevenueEntry.projected)
                )
            ).all()
            by_cat = (
                await s.execute(
                    select(CostEntry.category, func.sum(CostEntry.amount_usd)).where(CostEntry.created_at >= month).group_by(CostEntry.category)
                )
            ).all()
            by_agent = (
                await s.execute(
                    select(CostEntry.agent_id, func.sum(CostEntry.amount_usd), func.sum(CostEntry.input_tokens + CostEntry.output_tokens))
                    .where(CostEntry.category == "llm")
                    .group_by(CostEntry.agent_id)
                )
            ).all()
            published_entities = int(
                (await s.execute(select(func.count(Entity.id)).where(Entity.status == "published"))).scalar_one()
            )
            published_hubs = int((await s.execute(select(func.count(Hub.id)).where(Hub.status == "published"))).scalar_one())

            # série diária dos últimos 14 dias
            since = day - timedelta(days=13)
            daily_rows = (await s.execute(select(CostEntry.created_at, CostEntry.amount_usd).where(CostEntry.created_at >= since))).all()

        revenue_real = next((float(v) for p, v in rev_rows if not p), 0.0)
        revenue_projected = next((float(v) for p, v in rev_rows if p), 0.0)
        month_cost = sum(float(v or 0) for _, v in by_cat)
        today_llm = await self.llm_spend_today()
        today_total = await self._sum_costs(day)

        daily: dict[str, float] = {(since + timedelta(days=i)).date().isoformat(): 0.0 for i in range(14)}
        for created_at, amount in daily_rows:
            key = created_at.date().isoformat()
            if key in daily:
                daily[key] += float(amount)

        cash = self.settings.starting_cash_usd + revenue_real - total_cost
        burn_per_day = month_cost / max(1, now.day)
        runway_days = None if burn_per_day <= 0 else round(cash / burn_per_day, 1)
        margin = None if revenue_real <= 0 else round((revenue_real - total_cost) / revenue_real, 4)

        return {
            "currency": "USD",
            "today": {"llm": round(today_llm, 4), "total": round(today_total, 4), "llm_budget": gov["daily_llm_budget_usd"]},
            "month": {
                "total": round(month_cost, 4),
                "budget": gov["monthly_budget_usd"],
                "by_category": {c: round(float(v or 0), 4) for c, v in by_cat},
            },
            "lifetime": {"cost": round(total_cost, 4), "simulated_cost": round(sim_cost, 4)},
            "revenue": {"real": round(revenue_real, 2), "projected": round(revenue_projected, 2)},
            "cash": round(cash, 2),
            "starting_cash": self.settings.starting_cash_usd,
            "burn_per_day": round(burn_per_day, 4),
            "runway_days": runway_days,
            "margin": margin,
            "cost_per_published_entity": round(total_cost / published_entities, 4) if published_entities else None,
            "published_hubs": published_hubs,
            "by_agent": [
                {"agent_id": a or "system", "cost": round(float(c or 0), 4), "tokens": int(t or 0)} for a, c, t in by_agent
            ],
            "daily": [{"date": d, "cost": round(v, 4)} for d, v in daily.items()],
        }
