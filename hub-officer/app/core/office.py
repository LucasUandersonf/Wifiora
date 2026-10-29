"""Runtime do escritório: conecta barramento, LLM, skills, governança e agentes; roda o scheduler."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select

from app.agents.base import BaseAgent
from app.bus.base import Envelope, MessageBus
from app.bus.factory import build_bus
from app.config import Settings
from app.core.executor import Executor
from app.core.governance import Governance
from app.core.ledger import Ledger
from app.db import session_scope
from app.llm.base import DailyQuotaReached, LLMClient
from app.llm.gateway import LLMGateway
from app.models import AgentMessage, Alert, ApprovalRequest, ApprovalStatus, Objective
from app.skills.base import SkillRegistry

log = logging.getLogger("office")


class Office:
    def __init__(self, settings: Settings, *, bus: MessageBus | None = None, llm_client: LLMClient | None = None) -> None:
        self.settings = settings
        self.gov = Governance(settings)
        self.ledger = Ledger(settings, self.gov)
        self.llm = LLMGateway(settings, self.ledger, llm_client)
        self.bus = bus or build_bus(settings)
        self.skills = SkillRegistry(self).discover()
        self.executor = Executor(self)
        self.agents: dict[str, BaseAgent] = {}
        self.scouts_by_sector: dict[str, str] = {}
        self.fast_retry = False  # testes: sem backoff
        self.quota_rest_until: datetime | None = None
        self._tasks: list[asyncio.Task[Any]] = []
        self.background: set[asyncio.Task[Any]] = set()  # tarefas avulsas (mantém referência até terminar)
        self.content_audit: dict[str, Any] | None = None  # última auditoria GEO da landing da Insighta (Argos)
        self.started_at: datetime | None = None

    # ------------------------------------------------------------ lifecycle
    async def start(self, *, run_agents: bool = True, run_scheduler: bool = True) -> None:
        from app.agents.org import build_org

        from app.core import niches

        await self.bus.start()
        await niches.seed()
        from app.core import sales

        await sales.register_personas()
        if self.settings.business == "insighta":
            from app.core import insighta_content

            await insighta_content.register_personas()
            from app.core import newsletter

            await newsletter.register_personas()
        agents, self.scouts_by_sector = build_org(self)
        self.agents = {a.agent_id: a for a in agents}
        self.started_at = datetime.now(UTC)
        if not run_agents:
            return
        for a in agents:
            await a.register()
            self._tasks.append(asyncio.create_task(self._supervise(a), name=f"agent:{a.agent_id}"))
        if run_scheduler:
            self._tasks.append(asyncio.create_task(self._scheduler(), name="scheduler"))
            self._tasks.append(asyncio.create_task(self._radar_scheduler(), name="radar-scheduler"))
            self._tasks.append(asyncio.create_task(self._viability_scheduler(), name="viability-scheduler"))
            self._tasks.append(asyncio.create_task(self._sales_scheduler(), name="sales-scheduler"))
            self._tasks.append(asyncio.create_task(self._content_scheduler(), name="content-scheduler"))
            self._tasks.append(asyncio.create_task(self._newsletter_scheduler(), name="newsletter-scheduler"))
        log.info("escritório online: %d agentes, LLM=%s, bus=%s", len(agents), self.llm.client.provider, self.bus.name)

    def spawn(self, coro: Any) -> asyncio.Task[Any]:
        """Tarefa de fundo rastreada (cancelada no shutdown)."""
        t = asyncio.create_task(coro)
        self._tasks.append(t)
        t.add_done_callback(lambda done: self._tasks.remove(done) if done in self._tasks else None)
        return t

    async def _supervise(self, agent: BaseAgent) -> None:
        """Reinicia o loop do agente se ele cair (ex.: queda de conexão com o Redis)."""
        while True:
            try:
                await agent.run()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("loop do agente %s caiu; reiniciando em 2s", agent.agent_id)
                await asyncio.sleep(2)

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t
        self._tasks.clear()
        await self.bus.close()

    # ---------------------------------------------------------- mensageria
    async def dispatch(self, env: Envelope) -> None:
        """Ponto único de envio: persiste (auditoria), entrega e publica telemetria."""
        async with session_scope() as s:
            s.add(
                AgentMessage(
                    id=env.id,
                    type=env.type,
                    sender=env.sender,
                    recipient=env.recipient,
                    objective_id=env.objective_id,
                    task_id=env.task_id,
                    summary=env.summary[:1000],
                    payload=env.payload,
                    created_at=env.created_at,
                )
            )
        await self.bus.send(env)
        await self.emit("message", id=env.id, type=env.type, sender=env.sender, recipient=env.recipient, summary=env.summary[:300])

    async def emit(self, event: str, **data: Any) -> None:
        try:
            await self.bus.broadcast({"event": event, "at": datetime.now(UTC).isoformat(), **data})
        except Exception:
            log.debug("falha no broadcast", exc_info=True)

    async def trigger_radar(self, by: str = "scheduler") -> None:
        await self.dispatch(Envelope(type="radar.start", sender=by, recipient="cvo", summary="encomendar varredura do Radar de Ondas"))

    async def _radar_scheduler(self) -> None:
        await asyncio.sleep(20)
        while True:
            try:
                gov = await self.gov.snapshot()
                if gov["radar_enabled"] and not gov["paused"] and not self.resting():
                    await self.trigger_radar("scheduler")  # o CVO ignora se já houver varredura em andamento
            except Exception:
                log.exception("erro no agendador do radar")
            await asyncio.sleep(max(600, int(await self.gov.get("radar_interval_seconds"))))

    async def _viability_scheduler(self) -> None:
        """Veredito semanal do Gauss: confere de hora em hora se a semana já tem veredito (idempotente)."""
        from app.core import viability

        await asyncio.sleep(60)
        while True:
            try:
                if self.settings.viability_enabled and not await self.gov.get("paused") and not self.resting():
                    fresh = await viability.run(self)
                    if fresh and self.settings.council_weekly:
                        # semana nova: o Conselho se reúne com o veredito em mãos
                        from app.core import council

                        bad = [r["title"] for r in fresh if r["verdict"] in ("pivotar", "encerrar") and not r["demo"]]
                        topic = council.WEEKLY_TOPIC + (f" Atenção: {', '.join(bad)} com veredito ruim." if bad else "")
                        await council.convene(self, topic, trigger="semanal")
            except Exception:
                log.exception("erro no veredito de viabilidade")
            await asyncio.sleep(3600)

    async def _sales_scheduler(self) -> None:
        """Comercial automático: uma volta do funil a cada `sales_interval_seconds` (se ligado no painel)."""
        from app.core import sales

        await asyncio.sleep(90)
        while True:
            try:
                if not await self.gov.get("paused") and not self.resting() and await self.gov.get("sales_enabled"):
                    await sales.tick(self)
            except Exception:  # noqa: BLE001
                log.exception("erro no comercial automático")
            await asyncio.sleep(max(300, self.settings.sales_interval_seconds))

    async def _content_scheduler(self) -> None:
        """Conteúdo & GEO da Insighta: 1 rascunho para aprovação + auditoria da landing a cada `content_interval_hours`."""
        from app.core import insighta_content

        await asyncio.sleep(120)
        while True:
            try:
                if not await self.gov.get("paused") and not self.resting():
                    await insighta_content.tick(self)
            except Exception:  # noqa: BLE001
                log.exception("erro no time de conteúdo")
            await asyncio.sleep(max(3600, self.settings.content_interval_hours * 3600))

    async def _newsletter_scheduler(self) -> None:
        """Boletim: monta a edição da semana (uma por semana) e envia a aprovada na janela, em lotes — confere a cada hora."""
        from app.core import newsletter

        await asyncio.sleep(150)
        while True:
            try:
                if not await self.gov.get("paused") and not self.resting():
                    await newsletter.tick(self)
            except Exception:  # noqa: BLE001
                log.exception("erro no boletim")
            await asyncio.sleep(3600)

    async def trigger_cycle(self, by: str = "scheduler", niche: str | None = None) -> None:
        await self.dispatch(Envelope(type="cycle.start", sender=by, recipient="cvo", payload={"niche": niche} if niche else {}, summary="iniciar ciclo estratégico"))

    # ---------------------------------------------------------- governança
    async def wait_if_paused(self) -> None:
        while await self.gov.get("paused") or self.resting():
            await asyncio.sleep(2)

    def resting(self) -> bool:
        """Cota diária de IA esgotada: descansa até a virada do dia (UTC), sem pedir aprovação."""
        return self.quota_rest_until is not None and datetime.now(UTC) < self.quota_rest_until

    async def alert(self, level: str, source: str, message: str) -> None:
        async with session_scope() as s:
            s.add(Alert(level=level, source=source, message=message[:4000]))
        await self.emit("alert", level=level, source=source, message=message[:500])
        if self.settings.alert_webhook_url and level in ("warning", "critical"):
            try:
                async with httpx.AsyncClient(timeout=10) as c:
                    await c.post(self.settings.alert_webhook_url, json={"text": f"[{level.upper()}] {source}: {message[:1500]}", "content": f"[{level.upper()}] {source}: {message[:1500]}"})
            except httpx.HTTPError:
                log.warning("falha ao enviar webhook de alerta")

    async def handle_budget_block(self, agent: BaseAgent, env: Envelope, exc: Exception) -> None:
        """Orçamento diário estourou: pausa o escritório, pede aprovação e devolve a mensagem à fila.
        Cota diária de chamadas (planos grátis): só descansa até amanhã e retoma sozinho."""
        if isinstance(exc, DailyQuotaReached):
            tomorrow = (datetime.now(UTC) + timedelta(days=1)).replace(hour=0, minute=1, second=0, microsecond=0)
            if not self.resting():
                self.quota_rest_until = tomorrow
                await self.alert("info", "budget_guard", f"{exc}. Escritório descansando até {tomorrow:%d/%m %H:%M} UTC; retoma sozinho.")
            await self.bus.send(env)
            return
        await self.gov.set("paused", True, updated_by="system:budget_guard")
        async with session_scope() as s:
            pending = (
                await s.execute(
                    select(ApprovalRequest.id).where(ApprovalRequest.kind == "budget_increase", ApprovalRequest.status == ApprovalStatus.PENDING.value).limit(1)
                )
            ).first()
            if not pending:
                current = float(await self.gov.get("daily_llm_budget_usd"))
                s.add(
                    ApprovalRequest(
                        kind="budget_increase",
                        title=f"Orçamento diário de LLM esgotado (US$ {current:.2f}). Aprovar +50%?",
                        details={"current": current, "proposed": round(current * 1.5, 2), "blocked_agent": agent.agent_id},
                        amount_usd=round(current * 0.5, 2),
                        requested_by="system:budget_guard",
                    )
                )
        await self.alert("critical", "budget_guard", f"{exc}. Escritório pausado até decisão do fundador.")
        await self.bus.send(env)

    # ------------------------------------------------------------ scheduler
    async def _scheduler(self) -> None:
        await asyncio.sleep(5)
        while True:
            try:
                await self.ledger.accrue_fixed_costs()
                if not await self.gov.get("paused") and not self.resting():
                    async with session_scope() as s:
                        active = (
                            await s.execute(
                                select(Objective.id)
                                .where(Objective.status.in_(("planning", "active", "consolidating")), Objective.kind == "production")
                                .limit(1)
                            )
                        ).first()
                    if not active:
                        await self.trigger_cycle("scheduler")
            except Exception:
                log.exception("erro no scheduler")
            await asyncio.sleep(max(30, int(await self.gov.get("cycle_interval_seconds"))))

    # ---------------------------------------------------------------- testes
    async def wait_idle(self, timeout: float = 30.0, settle: float = 0.3) -> bool:
        """Espera o barramento em memória esvaziar e todos os agentes ficarem ociosos."""
        from app.bus.memory import InMemoryBus

        assert isinstance(self.bus, InMemoryBus), "wait_idle só funciona com o barramento em memória"
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        stable = 0
        while loop.time() < deadline:
            idle = await self.bus.drained() and all(a.status == "idle" for a in self.agents.values())
            stable = stable + 1 if idle else 0
            if stable >= 3:
                return True
            await asyncio.sleep(settle / 3)
        return False
