"""Setor Radar de Ondas: vigia novidades de IA, GEO, anúncios e compras dentro das IAs, e propõe posicionamento."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.agents.specialist import SpecialistAgent
from app.core.executor import slugify
from app.db import session_scope
from app.models import WAVE_STAGES, Objective, PlayAction, Signal, Task, Wave
from app.skills.builtin.radar import url_hash

TOPICS = {
    "anuncios_em_ia": "anúncios e publicidade dentro de assistentes de IA",
    "compras_agenticas": "compras e checkout feitos por agentes de IA",
    "geo_busca_ia": "GEO, busca por IA, citações e tráfego vindo de IAs",
    "crawlers_e_acesso": "robôs das IAs, robots.txt, llms.txt, acordos de acesso a conteúdo",
    "dados_estruturados": "Schema.org, feeds de produto, protocolos de dados para IAs",
    "modelos_e_plataformas": "lançamentos de modelos e plataformas relevantes",
    "regulacao": "regulação de IA, privacidade e publicidade",
    "mercado_brasil": "adoção de IA por empresas e consumidores no Brasil",
    "rag_e_grafos": "RAG, ingestão de datasets abertos, grafos de conhecimento e entidades (Wikidata, Knowledge Graph)",
    "receita_publishers": "pagamentos de IAs a publishers: revenue share, licenciamento de conteúdo, pay-per-crawl, afiliados em respostas",
}

BUSINESS = (
    "Nosso negócio: um Hub Semântico de dados estruturados e verificados (com fonte oficial) sobre produtos e "
    "serviços no Brasil — finanças pessoais, planos de saúde, educação, saúde mental, suplementos regularizados, "
    "cursos online e tecnologia B2B — feito para ser citado por assistentes de IA. Ganhamos com leads, afiliados, "
    "perfis verificados e uma API paga de dados."
)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


class SignalHunterAgent(SpecialistAgent):
    agent_id = "radar.signals"
    title = "Signal Hunter (Caçador de Sinais)"
    sector = "radar"
    task_kind = "signal_scan"
    skill_names = ("feed_reader", "signal_search")
    mission = "Encontrar, em fontes reais, novidades sobre IA como novo canal de busca e compra: anúncios em IAs, compras agênticas, GEO, crawlers e dados estruturados."

    async def execute(self, task: Task, deps: dict[str, dict[str, Any]], objective: Objective) -> dict[str, Any]:
        st = self.office.settings
        live = self.office.llm.client.provider != "mock"
        items: list[dict[str, Any]] = []
        health: list[dict[str, Any]] = []
        errors: list[str] = []
        if live:
            if st.allow_web_fetch and st.radar_feed_list:
                fr = await self.use("feed_reader", feeds=st.radar_feed_list, max_age_days=14)
                items += fr["items"]
                health = fr["feed_health"]
            if self.office.llm.can_search:
                ss = await self.use("signal_search", queries=st.radar_query_list, agent_id=self.agent_id)
                items += ss["items"]
                errors = ss["errors"]
        else:
            from app.llm.mock import DEMO_SIGNALS

            items = [dict(i) for i in DEMO_SIGNALS]

        # Remove duplicados e o que já está no banco (economiza tokens e evita contar 2x a mesma notícia).
        uniq: dict[str, dict[str, Any]] = {}
        for it in items:
            if str(it.get("url", "")).startswith(("http://", "https://")):
                uniq.setdefault(url_hash(it["url"]), it)
        async with session_scope() as s:
            known = set((await s.execute(select(Signal.url_hash).where(Signal.url_hash.in_(list(uniq))))).scalars()) if uniq else set()
        candidates = [it for h, it in uniq.items() if h not in known][:60]
        base = {"feed_health": health, "search_errors": errors[:10], "mode": "live" if live else "demo", "candidates": len(candidates), "already_known": len(known)}
        if not candidates:
            return {**base, "signals": [], "notes": "nenhum sinal novo nesta varredura"}

        listing = "\n".join(f"[{n}] {c.get('title') or '(sem título)'} — {c.get('source')} — {str(c.get('summary') or '')[:220]}" for n, c in enumerate(candidates))
        triage = await self.think(
            "signal_triage",
            self.task_prompt(
                task,
                objective,
                f"{BUSINESS}\nTemas acompanhados: {TOPICS}\n\nItens encontrados (use APENAS estes índices):\n{listing}\n\n"
                'Selecione os itens relevantes. Retorne JSON: {"selected": [{"index": n, "topics": [chaves dos temas], '
                '"relevance": 0.0-1.0, "summary_pt": "1-2 frases em português simples sobre o que aconteceu"}]}. '
                "Ignore opinião sem fato novo, propaganda e repetição. Não invente nada que não esteja no título/resumo.",
            ),
            context={"candidates": candidates},
            task_id=task.id,
            objective_id=task.objective_id,
        )
        signals: list[dict[str, Any]] = []
        for sel in triage.get("selected") or []:
            idx = sel.get("index")
            if not isinstance(idx, int) or not 0 <= idx < len(candidates):
                continue  # índice inexistente = item inventado: descarta
            c = candidates[idx]
            rel = max(0.0, min(1.0, float(sel.get("relevance") or 0)))
            if rel < 0.4:
                continue
            pub = c.get("published_at")
            signals.append({
                "url": c["url"],
                "title": c.get("title") or c["url"],
                "source": c.get("source") or "",
                "summary": str(sel.get("summary_pt") or c.get("summary") or "")[:600],
                "topics": [t for t in (sel.get("topics") or []) if t in TOPICS],
                "relevance": rel,
                "found_via": c.get("found_via") or ("feed" if c.get("published_at") else "search") if live else "demo",
                "published_at": pub.isoformat() if isinstance(pub, datetime) else pub,
            })
        return {**base, "signals": signals}


class WaveAnalystAgent(SpecialistAgent):
    agent_id = "radar.waves"
    title = "Wave Analyst (Analista de Ondas)"
    sector = "radar"
    task_kind = "wave_analysis"
    mission = "Agrupar sinais em ondas (tendências), dizer em que fase cada uma está e quanto ela importa para o nosso negócio, sempre com evidência."

    async def execute(self, task: Task, deps: dict[str, dict[str, Any]], objective: Objective) -> dict[str, Any]:
        new = deps.get("signal_scan", {}).get("signals") or []
        if not new:
            # Semana calma: sem sinal novo, as ondas ficam como estão (e não gastamos com IA).
            return {"waves": [], "dropped_evidence": 0, "notes": "sem sinais novos; ondas mantidas"}
        since = datetime.now(UTC) - timedelta(days=45)
        async with session_scope() as s:
            recent = list((await s.execute(select(Signal).where(Signal.created_at >= since).order_by(Signal.created_at.desc()).limit(80))).scalars())
            waves = list((await s.execute(select(Wave).where(Wave.status != "archived"))).scalars())
        pool = {sig["url"]: sig.get("title", "") for sig in new} | {r.url: r.title for r in recent}
        if not pool:
            return {"waves": [], "dropped_evidence": 0, "notes": "sem sinais para analisar"}
        listing = "\n".join(f"- {t} <{u}>" for u, t in list(pool.items())[:120])
        existing = [{"slug": w.slug, "name": w.name, "stage": w.stage, "impact": w.impact, "urgency": w.urgency} for w in waves]
        out = await self.think(
            "wave_analysis",
            self.task_prompt(
                task,
                objective,
                f"{BUSINESS}\nOndas já acompanhadas (reaproveite o slug se for o mesmo tema): {existing}\n\n"
                f"Sinais disponíveis (a evidência só pode usar estas URLs):\n{listing}\n\n"
                f"Agrupe os sinais em ondas. Fases possíveis: {list(WAVE_STAGES)} (sinal = poucos indícios; mainstream = já é padrão). "
                'Retorne JSON: {"waves": [{"slug", "name", "thesis" (o que está mudando, 1-2 frases), "stage", '
                '"impact" (0-1, efeito no nosso negócio), "urgency" (0-1, quão cedo agir), "confidence" (0-1, força da evidência; >0.9 só com anúncio oficial), '
                '"window" (ex.: "agora", "3-6 meses"), "relevance_for_us" (por que importa para o hub, em linguagem simples), '
                '"evidence": [URLs da lista]}]}. Não crie onda sem evidência.',
            ),
            context={"signals": new, "existing": existing},
            task_id=task.id,
            objective_id=task.objective_id,
        )
        cleaned, dropped = [], 0
        for w in out.get("waves") or []:
            ev = [u for u in (w.get("evidence") or []) if u in pool]
            dropped += len(w.get("evidence") or []) - len(ev)
            stage = str(w.get("stage") or "sinal").lower()
            cleaned.append({
                "slug": slugify(w.get("slug") or w.get("name") or "onda"),
                "name": str(w.get("name") or w.get("slug") or "Onda")[:200],
                "thesis": str(w.get("thesis") or "")[:1000],
                "stage": stage if stage in WAVE_STAGES else "sinal",
                "impact": max(0.0, min(1.0, float(w.get("impact") or 0))),
                "urgency": max(0.0, min(1.0, float(w.get("urgency") or 0))),
                "confidence": max(0.0, min(1.0, float(w.get("confidence") or 0))),
                "window": str(w.get("window") or "")[:120],
                "relevance_for_us": str(w.get("relevance_for_us") or "")[:1000],
                "evidence": ev,
            })
        return {"waves": cleaned, "dropped_evidence": dropped}


class PositioningStrategistAgent(SpecialistAgent):
    agent_id = "radar.strategy"
    title = "Positioning Strategist (Estrategista de Posicionamento)"
    sector = "radar"
    task_kind = "positioning_plan"
    skill_names = ("cost_report",)
    mission = "Transformar as ondas mais importantes em ações concretas, baratas e rápidas para estarmos bem posicionados antes de a onda chegar."

    async def execute(self, task: Task, deps: dict[str, dict[str, Any]], objective: Objective) -> dict[str, Any]:
        analyzed = deps.get("wave_analysis", {}).get("waves") or []
        async with session_scope() as s:
            db_waves = list((await s.execute(select(Wave).where(Wave.status != "archived"))).scalars())
        if not analyzed:
            hot = sorted(db_waves, key=lambda w: -(w.impact * w.urgency))[:3]
            names = ", ".join(f"{w.name} ({w.stage})" for w in hot)
            return {"plays": [], "brief": (
                "Sem novidades relevantes desde a última varredura. "
                + (f"As ondas acompanhadas seguem como estavam; as mais quentes são: {names}. " if hot else "Ainda não há ondas acompanhadas. ")
                + "As ações já propostas continuam valendo no painel do radar."
            )}
        async with session_scope() as s:
            open_plays = [p.title for p in (await s.execute(select(PlayAction).where(PlayAction.status.in_(("proposed", "approved"))))).scalars()]
        by_slug = {w.slug: {"slug": w.slug, "name": w.name, "stage": w.stage, "impact": w.impact, "urgency": w.urgency, "window": w.window, "thesis": w.thesis} for w in db_waves}
        by_slug.update({w["slug"]: w for w in analyzed})
        if not by_slug:
            return {"plays": [], "brief": "Ainda não há ondas suficientes para propor ações. O radar segue observando."}
        top = sorted(by_slug.values(), key=lambda w: -(w["impact"] * w["urgency"]))[:6]
        finance = await self.use("cost_report")
        out = await self.think(
            "positioning_plan",
            self.task_prompt(
                task,
                objective,
                f"{BUSINESS}\nCaixa atual: US$ {finance['cash']} · gasto do mês: US$ {finance['month']['total']}\n"
                f"Ondas prioritárias: {top}\nAções já propostas/aprovadas (não repita): {open_plays}\n\n"
                'Proponha até 5 ações de posicionamento. Retorne JSON: {"plays": [{"wave_slug", "title", "action" (o que fazer), '
                '"why" (o ganho esperado), "first_step" (algo que dá para fazer esta semana), "effort" (baixo|medio|alto), '
                '"est_cost_usd" (estimativa conservadora; 0 se não gasta), "deadline_days"}], '
                '"brief": "boletim para o fundador em linguagem bem simples (5 a 8 frases): o que mudou no mundo da IA, o que importa e o que sugerimos"}. '
                "Prefira ações baratas e reversíveis. Nada que viole regras de plataformas ou leis.",
            ),
            context={"waves": top},
            task_id=task.id,
            objective_id=task.objective_id,
        )
        plays = []
        for p in out.get("plays") or []:
            if p.get("wave_slug") not in by_slug or not p.get("title"):
                continue
            cost = max(0.0, float(p.get("est_cost_usd") or 0))
            effort = str(p.get("effort") or "medio").lower().replace("é", "e")
            plays.append({
                "wave_slug": p["wave_slug"],
                "title": str(p["title"])[:300],
                "action": str(p.get("action") or "")[:2000],
                "why": str(p.get("why") or "")[:1000],
                "first_step": str(p.get("first_step") or "")[:1000],
                "effort": effort if effort in ("baixo", "medio", "alto") else "medio",
                "est_cost_usd": cost,
                "requires_spend": cost > 0,
                "deadline_days": int(p["deadline_days"]) if str(p.get("deadline_days") or "").isdigit() else None,
            })
        return {"plays": plays, "brief": str(out.get("brief") or "")[:3000]}
