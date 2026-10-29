"""Executor: transforma entregas aprovadas em estado real do negócio (hubs, entidades, oportunidades).

Separar "decidir" (agentes) de "executar" (código determinístico) é o que torna o sistema auditável:
nenhum LLM escreve diretamente no banco de produção.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from app.db import session_scope
from app.models import (
    WAVE_STAGES,
    Entity,
    EntityVersion,
    Hub,
    MonetizationOpportunity,
    Objective,
    PlayAction,
    RevenueEntry,
    Signal,
    Task,
    Wave,
    WaveSnapshot,
)
from app.core.indexing import announce
from app.core.semantic import entity_graph
from app.skills.builtin.jsonld import org_slug
from app.skills.builtin.radar import url_hash

if TYPE_CHECKING:
    from app.core.office import Office

log = logging.getLogger(__name__)


def slugify(s: str) -> str:
    s = s.lower()
    for a, b in (("áàãâä", "a"), ("éèêë", "e"), ("íìîï", "i"), ("óòõôö", "o"), ("úùûü", "u"), ("ç", "c")):
        s = re.sub(f"[{a}]", b, s)
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:120] or "item"


class Executor:
    def __init__(self, office: Office) -> None:
        self.office = office

    async def stage(self, task: Task) -> None:
        handler = getattr(self, f"_stage_{task.kind}", None)
        if handler:
            await handler(task, task.output or {})
            await self.office.emit("staged", kind=task.kind, task_id=task.id)

    # ------------------------------------------------------------- staging
    async def _stage_market_research(self, task: Task, out: dict[str, Any]) -> None:
        slug = slugify(out.get("hub_slug") or out.get("hub_title") or out.get("niche") or "hub")
        async with session_scope() as s:
            obj = await s.get(Objective, task.objective_id)
            hub = (await s.execute(select(Hub).where(Hub.slug == slug))).scalar_one_or_none()
            if hub is None:
                hub = Hub(slug=slug, title=out.get("hub_title") or slug, niche=out.get("niche") or (obj.niche if obj else ""))
                s.add(hub)
            hub.research = out
            if obj and obj.niche_slug:
                hub.niche_slug = obj.niche_slug
            hub.entity_type = out.get("entity_type") or hub.entity_type
            hub.description = out.get("hallucination_pain") or hub.description
            hub.demo_data = self.office.llm.client.provider == "mock"
            await s.flush()
            if obj:
                obj.hub_id = hub.id
            audit = out.get("geo_audit") or {}
            if audit.get("hub") and audit.get("share_of_voice") is not None:
                audited = (await s.execute(select(Hub).where(Hub.slug == audit["hub"]))).scalar_one_or_none()
                if audited:
                    audited.share_of_voice = float(audit["share_of_voice"])

    async def _stage_schema_design(self, task: Task, out: dict[str, Any]) -> None:
        async with session_scope() as s:
            hub = await self._objective_hub(s, task)
            if hub:
                hub.schema_template = out
                if out.get("entity_schema_type"):
                    hub.entity_type = out["entity_schema_type"]

    async def _stage_data_extraction(self, task: Task, out: dict[str, Any]) -> None:
        detected_at = datetime.now(UTC)
        validation = out.get("validation") or {}
        per_entity = {p["name"]: p["grounding_ratio"] for p in validation.get("per_entity", [])}
        critical_by_entity = {i["entity"] for i in validation.get("issues", []) if i["severity"] == "critical"}
        live_changes: dict[str, list[str]] = {}  # fichas já publicadas cujo valor mudou -> aviso imediato
        orgs: list[str] = []
        async with session_scope() as s:
            hub = await self._objective_hub(s, task)
            if hub is None:
                return
            hub_slug, hub_live, demo = hub.slug, hub.status == "published", hub.demo_data
            for e in out.get("entities") or []:
                name = str(e.get("name") or "").strip()
                if not name:
                    continue
                eslug = slugify(name)
                attrs = {k: v for k, v in (e.get("attributes") or {}).items() if v is not None}
                sources = [
                    {**src, "retrieved_at": datetime.now(UTC).isoformat()}
                    for src in e.get("sources") or []
                    if str(src.get("url", "")).startswith(("http://", "https://"))  # bloqueia javascript:/data: em hrefs públicos
                ]
                ent = (await s.execute(select(Entity).where(Entity.hub_id == hub.id, Entity.slug == eslug))).scalar_one_or_none()
                now = datetime.now(UTC)
                provider = {k: v for k, v in (e.get("provider") or {}).items() if v}
                changed: list[str]
                if ent is None:
                    ent = Entity(hub_id=hub.id, slug=eslug, name=name, schema_type=hub.entity_type, version=1)
                    s.add(ent)
                    changed = sorted(attrs)
                else:
                    changed = sorted(k for k in set(attrs) | set(ent.attributes) if attrs.get(k) != ent.attributes.get(k))
                    if not changed:
                        # Reverificado sem mudanças: só renova a data (sinal de dado "vivo").
                        ent.verified_at = now
                        ent.sources = sources or ent.sources
                        if provider:
                            ent.provider = provider
                        continue
                    ent.version += 1
                    if hub_live and ent.status == "published":
                        live_changes[eslug] = changed
                        orgs.append(org_slug(provider or ent.provider) or "")
                    # Valor mudou: o especialista conferiu a versão anterior, então o selo cai.
                    ent.human_reviewed_by = ent.human_reviewed_at = ent.human_review_note = None
                ent.attributes = attrs
                ent.sources = sources
                ent.provider = provider or ent.provider or {}
                ent.verified_at = now
                ent.confidence = float(e.get("confidence") or 0)
                ent.grounding_ratio = float(per_entity.get(name, 0))
                ent.validated = name not in critical_by_entity and ent.grounding_ratio >= 0.8
                await s.flush()
                ent.jsonld = entity_graph(hub, ent)
                s.add(EntityVersion(entity_id=ent.id, version=ent.version, attributes=attrs, changed_fields=changed, source_task_id=task.id))
        if live_changes:
            # IndexNow Semântico: a mudança sai para o portal e os buscadores agora, sem esperar o fim do ciclo.
            await self.announce(hub_slug, list(live_changes), demo, org_slugs=orgs, reason="data_change", changed=live_changes, changed_at=detected_at)

    async def _stage_frontend_page(self, task: Task, out: dict[str, Any]) -> None:
        async with session_scope() as s:
            hub = await self._objective_hub(s, task)
            if hub:
                hub.page_config = out.get("page") or {}

    async def _stage_growth_plan(self, task: Task, out: dict[str, Any]) -> None:
        async with session_scope() as s:
            hub = await self._objective_hub(s, task)
            for op in out.get("opportunities") or []:
                est = float(op.get("est_monthly_usd") or 0)
                conf = float(op.get("confidence") or 0.5)
                s.add(MonetizationOpportunity(hub_id=hub.id if hub else None, channel=str(op.get("channel", "other"))[:32], title=str(op.get("title", ""))[:300], est_monthly_usd=est, confidence=conf, details=op))
                if est > 0:
                    # projeção ponderada por confiança — nunca contabilizada como receita real
                    s.add(RevenueEntry(stream=str(op.get("channel", "other"))[:32], amount_usd=round(est * conf, 2), projected=True, hub_id=hub.id if hub else None, description=str(op.get("title", ""))[:300]))

    # ------------------------------------------------------------- radar de ondas
    async def _stage_signal_scan(self, task: Task, out: dict[str, Any]) -> None:
        demo = out.get("mode") == "demo"
        async with session_scope() as s:
            for sig in out.get("signals") or []:
                h = url_hash(sig["url"])
                if (await s.execute(select(Signal.id).where(Signal.url_hash == h))).first():
                    continue
                pub = sig.get("published_at")
                s.add(Signal(
                    url=sig["url"][:1000], url_hash=h, title=str(sig.get("title") or "")[:500], source=str(sig.get("source") or "")[:200],
                    summary=sig.get("summary") or "", topics=sig.get("topics") or [], relevance=float(sig.get("relevance") or 0),
                    found_via=sig.get("found_via") or "search", demo=demo,
                    published_at=datetime.fromisoformat(pub) if isinstance(pub, str) else None,
                ))

    async def _stage_wave_analysis(self, task: Task, out: dict[str, Any]) -> None:
        hot: list[str] = []
        async with session_scope() as s:
            demo = bool((await s.execute(select(Signal.id).where(Signal.demo.is_(True)).limit(1))).first())
            for w in out.get("waves") or []:
                if not w.get("evidence"):
                    continue
                wave = (await s.execute(select(Wave).where(Wave.slug == w["slug"]))).scalar_one_or_none()
                was_stage = wave.stage if wave else None
                if wave is None:
                    wave = Wave(slug=w["slug"], name=w["name"], demo=demo)
                    s.add(wave)
                wave.name, wave.thesis, wave.stage = w["name"], w["thesis"], w["stage"]
                wave.impact, wave.urgency, wave.confidence = w["impact"], w["urgency"], w["confidence"]
                wave.window, wave.relevance = w["window"], w["relevance_for_us"]
                wave.evidence = list(dict.fromkeys((wave.evidence or []) + w["evidence"]))[-50:]
                await s.flush()
                s.add(WaveSnapshot(wave_id=wave.id, stage=wave.stage, impact=wave.impact, urgency=wave.urgency, confidence=wave.confidence, evidence_count=len(wave.evidence)))
                rising = was_stage is not None and WAVE_STAGES.index(wave.stage) > WAVE_STAGES.index(was_stage)
                if (wave.impact >= 0.7 and wave.urgency >= 0.7) or rising:
                    hot.append(f"{wave.name} ({wave.stage}{', subiu de fase' if rising else ''})")
        if hot:
            await self.office.alert("warning", "radar", "Onda quente no radar: " + "; ".join(hot) + ". Veja as ações sugeridas em /radar.")

    async def _stage_positioning_plan(self, task: Task, out: dict[str, Any]) -> None:
        async with session_scope() as s:
            for p in out.get("plays") or []:
                wave = (await s.execute(select(Wave).where(Wave.slug == p["wave_slug"]))).scalar_one_or_none()
                dup = (await s.execute(select(PlayAction.id).where(PlayAction.title == p["title"], PlayAction.status.in_(("proposed", "approved"))))).first()
                if dup:
                    continue
                s.add(PlayAction(
                    wave_id=wave.id if wave else None, title=p["title"], action=p["action"], why=p["why"], first_step=p["first_step"],
                    effort=p["effort"], est_cost_usd=p["est_cost_usd"], requires_spend=p["requires_spend"], deadline_days=p.get("deadline_days"),
                    demo=bool(wave.demo) if wave else False,
                ))

    # ------------------------------------------------------------- publish
    async def publish_hub(self, hub_id: str | None) -> int:
        if not hub_id:
            return 0
        async with session_scope() as s:
            hub = await s.get(Hub, hub_id)
            if hub is None:
                return 0
            ents = (await s.execute(select(Entity).where(Entity.hub_id == hub_id, Entity.validated.is_(True)))).scalars().all()
            fresh = [e for e in ents if e.status != "published"]  # mudanças nas já publicadas foram avisadas na extração
            for e in ents:
                e.status = "published"
            new_hub = hub.status != "published"
            hub.status = "published"
            hub.published_at = hub.published_at or datetime.now(UTC)
            count = len(ents)
            slug, demo = hub.slug, hub.demo_data
            entity_slugs, orgs = [e.slug for e in fresh], [org_slug(e.provider) or "" for e in fresh]
        await self.office.emit("hub_published", hub_id=hub_id, entities=count)
        if fresh or new_hub:
            await self.announce(slug, entity_slugs, demo, org_slugs=orgs, reason="publish", new_hub=new_hub)
        return count

    async def announce(self, hub_slug: str, entity_slugs: list[str], demo: bool, **kw: Any) -> None:
        """Avisa o portal (revalidação) e os buscadores (IndexNow) — nunca derruba a publicação."""
        try:
            res = await announce(self.office.settings, hub_slug=hub_slug, entity_slugs=entity_slugs, demo=demo, **kw)
            await self.office.emit("announced", hub=hub_slug, **res)
        except Exception:
            log.exception("falha ao anunciar hub %s", hub_slug)

    @staticmethod
    async def _objective_hub(s: Any, task: Task) -> Hub | None:
        obj = await s.get(Objective, task.objective_id)
        return await s.get(Hub, obj.hub_id) if obj and obj.hub_id else None
