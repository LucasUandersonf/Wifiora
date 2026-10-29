"""Conselho da agência: os agentes discutem o negócio entre si, como numa reunião de sócios.

Rodadas:
  1. Posição — cada conselheiro lê o MESMO pacote de fatos (números reais do banco) e defende uma tese,
     com ideias concretas para faturar.
  2. Réplica — cada um lê os outros, concorda ou contesta (a Juno é a advogada do diabo).
  3. Ata — o Atlas (CVO) fecha: dá lucro?, cenários com premissas explícitas, decisões e pedidos ao fundador.

Autonomia (governança `autonomy_level`):
  0 → tudo vira pedido de aprovação;  1 ou 2 → diretrizes e troca de foco valem na hora.
  Gasto de dinheiro e tarefas comerciais (vender, assinar contrato) SEMPRE vão para o fundador.
O LLM nunca escreve no banco: a ata é validada e aplicada por código determinístico.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from app.db import session_scope
from app.llm.base import BudgetExceeded
from app.models import (
    ApprovalRequest,
    CostEntry,
    Directive,
    Entity,
    Hub,
    Lead,
    Meeting,
    MonetizationOpportunity,
    PlayAction,
    Wave,
)

if TYPE_CHECKING:
    from app.core.office import Office

log = logging.getLogger(__name__)

CHAIR = "cvo"
# Conselheiros: quem fala e com que chapéu.
MEMBERS: dict[str, tuple[str, str]] = {
    "research.market": ("Mercator", "mercado: há demanda pagante? quais nichos e compradores B2B valem mais"),
    "finance.growth": ("Nash", "receita: como vender e cobrar já (leads, perfil verificado, API, serviço de agência GEO)"),
    "finance.unit_economics": ("Gauss", "números: custo, caixa, ponto de equilíbrio; corta o que não se paga"),
    "radar.strategy": ("Odisseu", "timing: que ondas de IA abrem ou fecham janelas de receita"),
    "quality.score": ("Juno", "advogada do diabo: aponta números sem base, riscos legais e quebra de confiança editorial"),
}
DIRECTIVE_PREFIX = "[Conselho]"
MAX_COUNCIL_DIRECTIVES = 5
DECISION_TYPES = ("diretriz", "foco_nicho")
_LOCK = asyncio.Lock()

RULES = (
    "Regras da reunião: (1) use SÓ os números do pacote FATOS; qualquer número novo é hipótese e deve vir com a premissa; "
    "(2) seja direto e concreto (quem faz o quê, quanto custa); (3) discorde quando os fatos não sustentarem a tese; "
    "(4) proibido vender posição em ranking ou recomendação (política editorial); (5) português do Brasil; "
    "(6) os bots não assinam contratos nem cobram clientes: vendas são tarefas do fundador."
)


def _iso(v: Any) -> Any:
    return v.isoformat() if isinstance(v, datetime) else v


async def facts(office: Office) -> dict[str, Any]:
    """Pacote de fatos — o mesmo para todos os conselheiros."""
    from app.core import bots, viability

    fin = await office.ledger.summary()
    gov = await office.gov.snapshot()
    async with session_scope() as s:
        hubs = list((await s.execute(select(Hub).where(Hub.status == "published"))).scalars())
        ents = int((await s.execute(select(func.count(Entity.id)).where(Entity.status == "published"))).scalar_one())
        leads = dict((await s.execute(select(Lead.status, func.count()).group_by(Lead.status))).all())
        waves = list((await s.execute(select(Wave).where(Wave.status != "archived").order_by((Wave.impact * Wave.urgency).desc()).limit(5))).scalars())
        opps = list((await s.execute(select(MonetizationOpportunity).order_by((MonetizationOpportunity.est_monthly_usd * MonetizationOpportunity.confidence).desc()).limit(5))).scalars())
        plays = list((await s.execute(select(PlayAction).where(PlayAction.status == "proposed").limit(5))).scalars())
    hits = await bots.summary(days=30)
    return {
        "data": datetime.now(UTC).date().isoformat(),
        "modo_ia": office.llm.client.provider,
        "dados_de_demonstracao": any(h.demo_data for h in hubs),
        "financeiro_usd": {
            "caixa": fin["cash"], "custo_mes": fin["month"]["total"], "orcamento_mes": fin["month"]["budget"],
            "gasto_por_dia": fin["burn_per_day"], "folego_dias": fin["runway_days"],
            "receita_real_total": fin["revenue"]["real"], "receita_projetada_ponderada": fin["revenue"]["projected"],
        },
        "produto": {
            "hubs_publicados": [{"titulo": h.title, "nicho": h.niche, "share_of_voice": h.share_of_voice, "demo": h.demo_data} for h in hubs],
            "fichas_publicadas": ents,
            "foco_atual": gov["focus_niche"],
        },
        "tracao": {"leads_por_status": leads, "robos_ia_30d": hits["total"], "downloads_dados_30d": hits["data_downloads"], "robos": [b["bot"] for b in hits["bots"]][:8]},
        "viabilidade": [{"hub": v["title"], "veredito": v["verdict"], "dia": v["days_live"], "motivos": v["reasons"]} for v in await viability.latest()],
        "ondas_do_radar": [{"onda": w.name, "fase": w.stage, "impacto": w.impact, "urgencia": w.urgency, "janela": w.window} for w in waves],
        "oportunidades_estimadas": [{"canal": o.channel, "titulo": o.title, "usd_mes_estimado": o.est_monthly_usd, "confianca": o.confidence} for o in opps],
        "acoes_do_radar_pendentes": [p.title for p in plays],
        "diretrizes_ativas": await office.gov.active_directives(),
        "nichos": await _niche_facts(),
        "comercial": await _sales_facts(office),
        "restricoes": [
            "IAs gratuitas no início: poucas chamadas por dia, sem busca na web",
            "vendas e contratos são feitos pelo fundador (operação humana inicial)",
            "ranking só por critérios objetivos; empresa paga não sobe de posição",
        ],
    }


async def _sales_facts(office: Office) -> dict[str, Any]:
    from app.core import sales

    s = await sales.summary(office)
    return {"ligado": s["enabled"], "funil": s["funnel"], "receita_mensal_brl": s["mrr_brl"], "precos_brl": s["prices"],
            "emails_hoje": s["sent_today"], "integracoes": s["health"], "clientes": len(s["clients"])}


async def _niche_facts() -> list[dict[str, Any]]:
    from app.core import niches

    cov = await niches.coverage()
    return [
        {"nicho": n.name, "status": n.status, "prioridade": n.rank, "fonte_oficial": n.official_source, "receita": n.revenue,
         "avaliacao": n.scores, "hubs_publicados": cov.get(n.slug, {}).get("published", 0)}
        for n in await niches.all_niches()
    ]


def _members(office: Office) -> list[str]:
    return [aid for aid in MEMBERS if aid in office.agents]


async def _ask(office: Office, agent_id: str, kind: str, prompt: str, meeting_id: str, *, context: dict[str, Any] | None = None, tier: str = "worker") -> dict[str, Any]:
    agent = office.agents.get(agent_id)
    system = agent.system_prompt if agent else "Você é o CVO de um escritório virtual autônomo."
    return await office.llm.complete_json(kind=kind, system=system, prompt=prompt, tier=tier, agent_id=agent_id, task_id=meeting_id, context=context or {})


async def _say(office: Office, sender: str, recipient: str, summary: str) -> None:
    """Fala na reunião: aparece no escritório virtual como mensagem entre agentes."""
    await office.emit("message", id=None, type="council.speech", sender=sender, recipient=recipient, summary=summary[:300])


def _clean_memo(memo: dict[str, Any]) -> dict[str, Any]:
    outlook = memo.get("profit_outlook")
    memo["profit_outlook"] = outlook if outlook in ("provavel", "incerto", "improvavel") else "incerto"
    memo["decisions"] = [d for d in (memo.get("decisions") or []) if isinstance(d, dict) and d.get("type") in DECISION_TYPES and str(d.get("text") or "").strip()][:3]
    memo["proposals_for_founder"] = [p for p in (memo.get("proposals_for_founder") or []) if isinstance(p, dict) and str(p.get("title") or "").strip()][:5]
    memo["founder_tasks"] = [str(t) for t in (memo.get("founder_tasks") or []) if str(t).strip()][:6]
    memo["scenarios"] = [sc for sc in (memo.get("scenarios") or []) if isinstance(sc, dict)][:3]
    memo["dissent"] = [d for d in (memo.get("dissent") or []) if isinstance(d, dict)][:5]
    return memo


async def _apply(office: Office, meeting: Meeting, memo: dict[str, Any]) -> dict[str, Any]:
    """Aplica a ata dentro da autonomia permitida. Retorna o que foi feito."""
    autonomy = int(await office.gov.get("autonomy_level"))
    stamp = datetime.now(UTC).strftime("%d/%m")
    applied: dict[str, Any] = {"directives": [], "focus": None, "approvals": [], "autonomy_level": autonomy}
    to_approve = list(memo["proposals_for_founder"])
    async with session_scope() as s:
        for d in memo["decisions"]:
            text = str(d["text"]).strip()[:500]
            if autonomy == 0:
                to_approve.append({"title": text, "cost_usd": 0, "why": d.get("why", ""), "type": d["type"]})
            elif d["type"] == "foco_nicho":
                applied["focus"] = text[:200]
            else:
                s.add(Directive(text=f"{DIRECTIVE_PREFIX} {stamp}: {text}"))
                applied["directives"].append(text)
        for p in to_approve:
            req = ApprovalRequest(
                kind="council_proposal",
                title=f"Conselho propõe: {str(p['title'])[:250]}",
                details={"meeting_id": meeting.id, **{k: p.get(k) for k in ("title", "why", "type", "cost_usd")}},
                amount_usd=float(p.get("cost_usd") or 0) or None,
                requested_by="council",
            )
            s.add(req)
            applied["approvals"].append(p["title"])
        await s.flush()
        # Mantém só as diretrizes mais recentes do Conselho ativas (evita acúmulo de ordens velhas).
        council = list((await s.execute(select(Directive).where(Directive.active.is_(True), Directive.text.like(f"{DIRECTIVE_PREFIX}%")).order_by(Directive.created_at.desc()))).scalars())
        for old in council[MAX_COUNCIL_DIRECTIVES:]:
            old.active = False
    if applied["focus"]:
        await office.gov.set("focus_niche", applied["focus"], updated_by="council")
    if applied["approvals"]:
        await office.emit("approval_requested", kind="council_proposal", count=len(applied["approvals"]))
    return applied


async def convene(office: Office, topic: str, *, trigger: str = "manual") -> Meeting:
    """Roda uma reunião completa. Uma por vez; se houver outra em andamento, devolve a que está rodando."""
    if _LOCK.locked():
        async with session_scope() as s:
            running = (await s.execute(select(Meeting).where(Meeting.status == "running").order_by(Meeting.created_at.desc()))).scalars().first()
            if running:
                return running
    async with _LOCK:
        members = _members(office)
        async with session_scope() as s:
            meeting = Meeting(topic=topic[:500], trigger=trigger, participants=[CHAIR, *members])
            s.add(meeting)
        await office.emit("council", status="started", meeting_id=meeting.id, topic=topic)
        rounds: list[dict[str, Any]] = []
        try:
            pack = await facts(office)
            fatos = json.dumps(pack, ensure_ascii=False, default=_iso)[:9000]
            await _say(office, CHAIR, "founder", f"Abrindo reunião do Conselho: {topic}")

            # Rodada 1: posições (em paralelo — cada um pensa sozinho antes de ouvir os outros)
            async def position(aid: str) -> dict[str, Any]:
                name, hat = MEMBERS[aid]
                out = await _ask(
                    office, aid, "council.position",
                    f"REUNIÃO DO CONSELHO — tema: {topic}\nSeu papel: {name}, {hat}.\n{RULES}\n\nFATOS:\n{fatos}\n\n"
                    "Retorne JSON: {position (2-4 frases com sua tese), evidence [fatos do pacote que sustentam], "
                    "ideas [{title, type (diretriz|foco_nicho|gasto|fundador), detail, cost_usd, expected_impact}], risks [..], confidence (0-1)}.",
                    meeting.id, context={"agent": aid, "topic": topic},
                )
                await _say(office, aid, CHAIR, str(out.get("position") or "")[:300])
                return {"round": 1, "agent": aid, "name": name, "output": out}

            rounds += await asyncio.gather(*(position(a) for a in members))
            await _save(meeting.id, rounds=rounds)

            # Rodada 2: réplicas (cada um lê os demais)
            board = json.dumps([{"agente": r["name"], "id": r["agent"], "posicao": r["output"].get("position"), "ideias": [i.get("title") for i in r["output"].get("ideas") or []]} for r in rounds], ensure_ascii=False)[:7000]

            async def reply(aid: str) -> dict[str, Any]:
                name, hat = MEMBERS[aid]
                out = await _ask(
                    office, aid, "council.reply",
                    f"REUNIÃO DO CONSELHO — tema: {topic}\nSeu papel: {name}, {hat}.\n{RULES}\n\nPOSIÇÕES DOS COLEGAS:\n{board}\n\n"
                    "Responda aos colegas. Retorne JSON: {replies [{to (id do colega), agree (true/false), point}], "
                    "revised_position (sua tese depois de ouvir todos), keep_ideas [títulos que você apoia]}.",
                    meeting.id, context={"agent": aid, "members": members},
                )
                for r in (out.get("replies") or [])[:2]:
                    if isinstance(r, dict) and r.get("to") in MEMBERS:
                        await _say(office, aid, r["to"], ("Concordo: " if r.get("agree") else "Discordo: ") + str(r.get("point") or ""))
                return {"round": 2, "agent": aid, "name": name, "output": out}

            rounds += await asyncio.gather(*(reply(a) for a in members))
            await _save(meeting.id, rounds=rounds)

            # Ata do CVO
            debate = json.dumps([{"rodada": r["round"], "agente": r["name"], "fala": r["output"]} for r in rounds], ensure_ascii=False)[:14000]
            memo = await _ask(
                office, CHAIR, "council.synthesis",
                f"Você preside o Conselho. Tema: {topic}\n{RULES}\n\nFATOS:\n{fatos}\n\nDEBATE:\n{debate}\n\n"
                "Feche a ata. Retorne JSON: {profit_outlook (provavel|incerto|improvavel), why, "
                "scenarios [{name (pessimista|base|otimista), revenue_usd_month_12 (número), cost_usd_month (número), breakeven_month (número ou null), assumptions [..]}], "
                "decisions [{type (diretriz|foco_nicho), text, why}] (no máximo 3, sem gasto, aplicadas pelo escritório), "
                "proposals_for_founder [{title, cost_usd, why, type (gasto|fundador)}], founder_tasks [tarefas comerciais para o fundador], "
                "dissent [{agent, point}] (quem discordou e de quê), next_topic}.",
                meeting.id, context={"facts": pack, "rounds": rounds}, tier="strategic",
            )
            memo = _clean_memo(memo)
            await _say(office, CHAIR, "founder", f"Ata: lucro {memo['profit_outlook']}. {str(memo.get('why') or '')[:200]}")
            async with session_scope() as s:
                m = await s.get(Meeting, meeting.id)
                assert m is not None
                applied = await _apply(office, m, memo)
                cost = (await s.execute(select(func.coalesce(func.sum(CostEntry.amount_usd), 0.0)).where(CostEntry.task_id == meeting.id))).scalar_one()
                m.memo, m.applied, m.status, m.finished_at, m.cost_usd = memo, applied, "done", datetime.now(UTC), round(float(cost), 6)
                meeting = m
            await office.alert("info", "council", f"Conselho: “{topic[:80]}” — lucro {memo['profit_outlook']}; {len(applied['directives'])} diretriz(es), {len(applied['approvals'])} pedido(s) para você.")
            await office.emit("council", status="done", meeting_id=meeting.id, outlook=memo["profit_outlook"])
        except Exception as e:
            budget = isinstance(e, BudgetExceeded)
            if not budget:
                log.exception("reunião do conselho falhou")
            msg = f"sem orçamento/cota de IA no momento ({e})" if budget else str(e)
            async with session_scope() as s:
                m = await s.get(Meeting, meeting.id)
                if m:
                    m.status, m.error, m.finished_at, m.rounds = "failed", msg[:2000], datetime.now(UTC), rounds
                    meeting = m
            await office.emit("council", status="failed", meeting_id=meeting.id)
        return meeting


async def _save(meeting_id: str, **fields: Any) -> None:
    async with session_scope() as s:
        m = await s.get(Meeting, meeting_id)
        if m:
            for k, v in fields.items():
                setattr(m, k, v)


def meeting_out(m: Meeting, *, full: bool = False) -> dict[str, Any]:
    out = {
        "id": m.id, "topic": m.topic, "trigger": m.trigger, "status": m.status, "created_at": m.created_at, "finished_at": m.finished_at,
        "outlook": (m.memo or {}).get("profit_outlook"), "cost_usd": m.cost_usd, "error": m.error,
        "names": {CHAIR: "Atlas", **{k: v[0] for k, v in MEMBERS.items()}},
    }
    if full:
        out.update(rounds=m.rounds, memo=m.memo, applied=m.applied, participants=m.participants)
    return out


WEEKLY_TOPIC = "Revisão semanal: a empresa vai dar lucro? O que fazer nas próximas semanas para faturar e capitalizar?"
