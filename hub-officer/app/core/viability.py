"""Painel de Viabilidade: o veredito semanal do Gauss para cada hub publicado.

Metas aprovadas pelo fundador (editáveis em governança):
  • até o dia 30  — robôs de IA leram o hub (páginas ou arquivos);
  • até o dia 90  — o portal foi citado por uma IA (Share of Voice > 0) e chegaram pedidos de demonstração;
  • até o dia 180 — a receita do hub nos últimos 30 dias cobre o custo do hub no mesmo período.

O cálculo é determinístico (sem LLM): números do banco contra metas. O sistema só RECOMENDA —
encerrar ou mudar de nicho é sempre decisão do fundador.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from app.db import session_scope
from app.models import BotHit, CostEntry, Hub, Lead, Objective, RevenueEntry, ViabilityReport

if TYPE_CHECKING:
    from app.core.office import Office

log = logging.getLogger(__name__)
SOURCE = "finance.unit_economics"  # o Gauss assina o veredito

VERDICTS = {
    "aquecendo": "Cedo demais para julgar: acompanhando as primeiras metas.",
    "continuar": "Todas as metas vencidas foram cumpridas.",
    "ajustar": "Uma meta ficou para trás: corrigir antes da próxima.",
    "pivotar": "O hub não se paga do jeito atual: trocar o nicho ou a forma de cobrar.",
    "encerrar": "Sem tração e sem receita no prazo: recomendo pausar este nicho (decisão do fundador).",
}

ACTIONS = {
    "robos": "Conferir domínio, robots.txt, sitemap e IndexNow; ver a seção “Dados para IAs” do painel.",
    "citacao": "Rodar “Medir” (Share of Voice) e reforçar FAQ e dados das perguntas-alvo deste hub.",
    "leads": "Revisar chamadas para demonstração e contatar diretamente os fornecedores do hub.",
    "receita_pivot": "Testar outra forma de cobrar: perfil verificado, API ou relatório setorial.",
    "receita_stop": "Pausar novos ciclos neste nicho e realocar o orçamento para o próximo da fila.",
}


def _aware(dt: datetime | None) -> datetime | None:
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=UTC)


def iso_week(now: datetime) -> str:
    y, w, _ = now.isocalendar()
    return f"{y}-W{w:02d}"


async def _hub_costs(s: Any, hub: Hub, since: datetime, live_hubs: int) -> float:
    llm = (
        await s.execute(
            select(func.coalesce(func.sum(CostEntry.amount_usd), 0.0))
            .join(Objective, Objective.id == CostEntry.objective_id)
            .where(Objective.hub_id == hub.id, CostEntry.created_at >= since)
        )
    ).scalar_one()
    fixed = (
        await s.execute(
            select(func.coalesce(func.sum(CostEntry.amount_usd), 0.0)).where(
                CostEntry.objective_id.is_(None), CostEntry.category.in_(("infra", "domain")), CostEntry.created_at >= since
            )
        )
    ).scalar_one()
    return float(llm) + float(fixed) / max(1, live_hubs)  # custo fixo dividido igualmente entre os hubs no ar


async def metrics_for(hub: Hub, *, now: datetime, live_hubs: int) -> dict[str, Any]:
    published = _aware(hub.published_at) or now
    month_ago = now - timedelta(days=30)
    async with session_scope() as s:
        bot_rows = (
            await s.execute(select(BotHit.bot, BotHit.kind, func.sum(BotHit.hits)).where(BotHit.hub == hub.slug).group_by(BotHit.bot, BotHit.kind))
        ).all()
        leads = (await s.execute(select(Lead.status, func.count()).where(Lead.hub_slug == hub.slug).group_by(Lead.status))).all()
        revenue_30d = (
            await s.execute(
                select(func.coalesce(func.sum(RevenueEntry.amount_usd), 0.0)).where(
                    RevenueEntry.hub_id == hub.id, RevenueEntry.projected.is_(False), RevenueEntry.created_at >= month_ago
                )
            )
        ).scalar_one()
        revenue_total = (
            await s.execute(select(func.coalesce(func.sum(RevenueEntry.amount_usd), 0.0)).where(RevenueEntry.hub_id == hub.id, RevenueEntry.projected.is_(False)))
        ).scalar_one()
        cost_30d = await _hub_costs(s, hub, month_ago, live_hubs)
    by_kind: dict[str, int] = {}
    for _, kind, n in bot_rows:
        by_kind[kind] = by_kind.get(kind, 0) + int(n)
    lead_counts = {st: int(n) for st, n in leads}
    return {
        "days_live": max(0, (now - published).days),
        "bot_hits": sum(by_kind.values()),
        "bot_data_downloads": by_kind.get("data", 0) + by_kind.get("graph", 0),
        "bots": sorted({b for b, _, _ in bot_rows}),
        "share_of_voice": hub.share_of_voice,
        "leads": sum(lead_counts.values()),
        "leads_won": lead_counts.get("won", 0),
        "revenue_30d": round(float(revenue_30d), 2),
        "revenue_total": round(float(revenue_total), 2),
        "cost_30d": round(cost_30d, 2),
    }


def judge(m: dict[str, Any], targets: dict[str, int]) -> dict[str, Any]:
    """Compara as métricas com as metas e devolve marcos, veredito, motivos e ações."""
    day = m["days_live"]

    def status(ok: bool, due: int) -> str:
        return "cumprida" if ok else ("perdida" if day >= due else "em_andamento")

    sov = m["share_of_voice"]
    milestones = [
        {"key": "robos", "label": "Robôs de IA leram o hub", "due_day": targets["bots_days"],
         "status": status(m["bot_hits"] > 0, targets["bots_days"]), "detail": f"{m['bot_hits']} acesso(s) de robôs; {', '.join(m['bots']) or 'nenhum'}"},
        {"key": "citacao", "label": "Citado por uma IA (Share of Voice > 0)", "due_day": targets["traction_days"],
         "status": status(bool(sov), targets["traction_days"]), "detail": "nunca medido" if sov is None else f"Share of Voice {sov:.0%}"},
        {"key": "leads", "label": f"Pelo menos {targets['min_leads']} pedido(s) de demonstração", "due_day": targets["traction_days"],
         "status": status(m["leads"] >= targets["min_leads"], targets["traction_days"]), "detail": f"{m['leads']} pedido(s), {m['leads_won']} pago(s)"},
        {"key": "receita", "label": "Receita de 30 dias cobre o custo de 30 dias", "due_day": targets["revenue_days"],
         "status": status(m["revenue_30d"] > 0 and m["revenue_30d"] >= m["cost_30d"], targets["revenue_days"]),
         "detail": f"receita US$ {m['revenue_30d']:.2f} × custo US$ {m['cost_30d']:.2f}"},
    ]
    missed = {x["key"] for x in milestones if x["status"] == "perdida"}
    traction_ok = not ({"citacao", "leads"} & missed)
    if "receita" in missed:
        verdict = "pivotar" if traction_ok else "encerrar"
    elif {"citacao", "leads"} <= missed:
        verdict = "pivotar"
    elif missed:
        verdict = "ajustar"
    elif day < targets["bots_days"]:
        verdict = "aquecendo"
    else:
        verdict = "continuar"
    reasons = [f"{x['label']}: {x['detail']} (meta do dia {x['due_day']})" for x in milestones if x["status"] == "perdida"]
    actions = [ACTIONS[k] for k in ("robos", "citacao", "leads") if k in missed]
    if "receita" in missed:
        actions.append(ACTIONS["receita_pivot" if verdict == "pivotar" else "receita_stop"])
    if verdict == "pivotar" and "receita" not in missed:
        actions.append("Trocar de nicho: o CVO pode puxar o próximo nicho da fila de oportunidades.")
    nxt = next((x for x in milestones if x["status"] == "em_andamento"), None)
    return {
        "milestones": milestones,
        "verdict": verdict,
        "summary": VERDICTS[verdict],
        "reasons": reasons,
        "actions": actions,
        "next_milestone": {"label": nxt["label"], "in_days": max(0, nxt["due_day"] - day)} if nxt else None,
    }


async def targets(office: Office) -> dict[str, int]:
    g = await office.gov.snapshot()
    return {
        "bots_days": int(g["viability_bots_days"]),
        "traction_days": int(g["viability_traction_days"]),
        "revenue_days": int(g["viability_revenue_days"]),
        "min_leads": int(g["viability_min_leads"]),
    }


async def run(office: Office, *, force: bool = False, now: datetime | None = None) -> list[dict[str, Any]]:
    """Gera (ou refaz, com force) o veredito da semana para cada hub publicado."""
    now = now or datetime.now(UTC)
    week = iso_week(now)
    tg = await targets(office)
    async with session_scope() as s:
        hubs = list((await s.execute(select(Hub).where(Hub.status == "published"))).scalars())
        done = set((await s.execute(select(ViabilityReport.hub_id).where(ViabilityReport.week == week))).scalars())
    live = len([h for h in hubs if not h.demo_data]) or len(hubs)
    out: list[dict[str, Any]] = []
    for hub in hubs:
        if hub.id in done and not force:
            continue
        m = await metrics_for(hub, now=now, live_hubs=live)
        j = judge(m, tg)
        async with session_scope() as s:
            row = (await s.execute(select(ViabilityReport).where(ViabilityReport.hub_id == hub.id, ViabilityReport.week == week))).scalar_one_or_none()
            if row is None:
                row = ViabilityReport(hub_id=hub.id, hub_slug=hub.slug, week=week, verdict=j["verdict"])
                s.add(row)
            row.days_live, row.metrics, row.milestones = m["days_live"], m, j["milestones"]
            row.verdict, row.reasons, row.actions, row.demo = j["verdict"], j["reasons"], j["actions"], hub.demo_data
        out.append({"hub": hub.slug, "title": hub.title, "demo": hub.demo_data, "metrics": m, **j})
        if j["verdict"] in ("ajustar", "pivotar", "encerrar") and not hub.demo_data:
            level = "critical" if j["verdict"] == "encerrar" else "warning"
            await office.alert(level, SOURCE, f"Viabilidade de “{hub.title}” (dia {m['days_live']}): {j['verdict'].upper()}. " + " ".join(j["reasons"][:2]))
    if out:
        await office.emit("viability", hubs=len(out), verdicts={r["hub"]: r["verdict"] for r in out})
    return out


async def latest() -> list[dict[str, Any]]:
    """Último veredito de cada hub, para o painel e para o Gauss."""
    async with session_scope() as s:
        rows = list((await s.execute(select(ViabilityReport).order_by(ViabilityReport.created_at.desc()))).scalars())
        titles = {h.id: h.title for h in (await s.execute(select(Hub))).scalars()}
    seen: set[str] = set()
    out = []
    for r in rows:
        if r.hub_id in seen:
            continue
        seen.add(r.hub_id)
        history = [x.verdict for x in rows if x.hub_id == r.hub_id][:8][::-1]
        out.append({
            "hub": r.hub_slug, "title": titles.get(r.hub_id, r.hub_slug), "week": r.week, "days_live": r.days_live, "demo": r.demo,
            "verdict": r.verdict, "summary": VERDICTS.get(r.verdict, ""), "metrics": r.metrics, "milestones": r.milestones,
            "reasons": r.reasons, "actions": r.actions, "history": history, "at": r.created_at,
        })
    return out
