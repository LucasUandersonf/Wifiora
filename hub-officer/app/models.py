"""Modelos de dados (ORM).

Três domínios:
  1. Operação do escritório: objetivos, tarefas, mensagens, avaliações, estado dos agentes.
  2. Finanças: custos (ledger), receitas, pedidos de aprovação orçamentária.
  3. Produto (Hub Semântico): hubs, entidades, histórico de versões (Dataset vivo).
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(UTC)


class TaskStatus(str, enum.Enum):
    PENDING = "pending"  # criada, aguardando dependências
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    IN_REVIEW = "in_review"
    REVISION = "revision"  # reprovada pelo Score Agent, voltou ao especialista
    APPROVED = "approved"
    ESCALATED = "escalated"  # excedeu revisões -> CVO/fundador
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def terminal(self) -> bool:
        return self in {TaskStatus.APPROVED, TaskStatus.ESCALATED, TaskStatus.FAILED, TaskStatus.CANCELLED}


class ObjectiveStatus(str, enum.Enum):
    PLANNING = "planning"
    ACTIVE = "active"
    CONSOLIDATING = "consolidating"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ApprovalStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


# --------------------------------------------------------------------------
# Operação
# --------------------------------------------------------------------------


class Objective(Base):
    __tablename__ = "objectives"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(300))
    # production = ciclo de produção do hub | radar = varredura do Radar de Ondas
    kind: Mapped[str] = mapped_column(String(16), default="production", index=True)
    rationale: Mapped[str] = mapped_column(Text, default="")
    niche: Mapped[str] = mapped_column(String(200), default="")
    niche_slug: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)  # nicho do catálogo
    status: Mapped[str] = mapped_column(String(32), default=ObjectiveStatus.PLANNING.value, index=True)
    plan: Mapped[dict] = mapped_column(JSON, default=dict)  # fases e atribuições setoriais
    current_phase: Mapped[int] = mapped_column(Integer, default=1)
    sector_reports: Mapped[dict] = mapped_column(JSON, default=dict)  # {sector: report}
    final_report: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    hub_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    tasks: Mapped[list[Task]] = relationship(back_populates="objective")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    objective_id: Mapped[str] = mapped_column(ForeignKey("objectives.id"), index=True)
    sector: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(64))  # ex.: market_research, data_extraction
    title: Mapped[str] = mapped_column(String(300))
    brief: Mapped[str] = mapped_column(Text, default="")
    owner_id: Mapped[str] = mapped_column(String(64))  # scout responsável
    assignee_id: Mapped[str] = mapped_column(String(64), index=True)  # especialista
    status: Mapped[str] = mapped_column(String(32), default=TaskStatus.PENDING.value, index=True)
    priority: Mapped[int] = mapped_column(Integer, default=5)
    depends_on: Mapped[list] = mapped_column(JSON, default=list)  # ids de tarefas
    context: Mapped[dict] = mapped_column(JSON, default=dict)
    output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    revisions: Mapped[int] = mapped_column(Integer, default=0)
    last_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    objective: Mapped[Objective] = relationship(back_populates="tasks")


class AgentMessage(Base):
    """Registro imutável de toda mensagem trafegada no barramento (trilha de auditoria)."""

    __tablename__ = "agent_messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    type: Mapped[str] = mapped_column(String(64), index=True)
    sender: Mapped[str] = mapped_column(String(64), index=True)
    recipient: Mapped[str] = mapped_column(String(64), index=True)
    objective_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    task_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class Evaluation(Base):
    __tablename__ = "evaluations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    evaluator_id: Mapped[str] = mapped_column(String(64))
    score: Mapped[float] = mapped_column(Float)
    deterministic_score: Mapped[float] = mapped_column(Float)
    llm_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    passed: Mapped[bool] = mapped_column(Boolean)
    checks: Mapped[list] = mapped_column(JSON, default=list)
    feedback: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AgentState(Base):
    """Heartbeat/estado do agente — permite que o processo da API leia o estado do worker."""

    __tablename__ = "agent_states"

    agent_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(120))
    sector: Mapped[str] = mapped_column(String(32))
    role: Mapped[str] = mapped_column(String(32))  # orchestrator | scout | specialist | evaluator
    status: Mapped[str] = mapped_column(String(32), default="idle")
    current_task_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    current_activity: Mapped[str] = mapped_column(Text, default="")
    skills: Mapped[list] = mapped_column(JSON, default=list)
    processed: Mapped[int] = mapped_column(Integer, default=0)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    avg_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class OfficeSetting(Base):
    """Configurações de governança mutáveis em runtime (override do fundador)."""

    __tablename__ = "office_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)
    updated_by: Mapped[str] = mapped_column(String(64), default="system")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Directive(Base):
    """Diretrizes do fundador — injetadas no planejamento do CVO e na avaliação do Score Agent."""

    __tablename__ = "directives"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    text: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    level: Mapped[str] = mapped_column(String(16), default="info")  # info | warning | critical
    source: Mapped[str] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


# --------------------------------------------------------------------------
# Finanças
# --------------------------------------------------------------------------


class CostEntry(Base):
    __tablename__ = "cost_entries"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    category: Mapped[str] = mapped_column(String(32), index=True)  # llm | infra | domain | tooling
    agent_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    objective_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    task_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    amount_usd: Mapped[float] = mapped_column(Float)
    simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class RevenueEntry(Base):
    __tablename__ = "revenue_entries"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    stream: Mapped[str] = mapped_column(String(32))  # cpl | affiliate | premium_profile | api | report | sponsorship
    amount_usd: Mapped[float] = mapped_column(Float)
    projected: Mapped[bool] = mapped_column(Boolean, default=False)  # projeção x receita real
    hub_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    description: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class ApprovalRequest(Base):
    """Pedido de intervenção humana: orçamento extra, publicação, mudança estratégica."""

    __tablename__ = "approval_requests"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    kind: Mapped[str] = mapped_column(String(32))  # budget_increase | publish_hub | escalated_task
    title: Mapped[str] = mapped_column(String(300))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    amount_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    requested_by: Mapped[str] = mapped_column(String(64))
    objective_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default=ApprovalStatus.PENDING.value, index=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MonetizationOpportunity(Base):
    __tablename__ = "monetization_opportunities"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    hub_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    channel: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(300))
    est_monthly_usd: Mapped[float] = mapped_column(Float, default=0)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="idea")  # idea | testing | live | dropped
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# --------------------------------------------------------------------------
# Produto: Hub Semântico
# --------------------------------------------------------------------------


class Hub(Base):
    __tablename__ = "hubs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(300))
    niche: Mapped[str] = mapped_column(String(200))
    niche_slug: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)  # nicho do catálogo
    description: Mapped[str] = mapped_column(Text, default="")
    entity_type: Mapped[str] = mapped_column(String(64), default="SoftwareApplication")
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft | published | archived
    schema_template: Mapped[dict] = mapped_column(JSON, default=dict)
    page_config: Mapped[dict] = mapped_column(JSON, default=dict)
    research: Mapped[dict] = mapped_column(JSON, default=dict)
    share_of_voice: Mapped[float | None] = mapped_column(Float, nullable=True)
    demo_data: Mapped[bool] = mapped_column(Boolean, default=False)  # gerado em modo mock
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    entities: Mapped[list[Entity]] = relationship(back_populates="hub", cascade="all, delete-orphan")


class Entity(Base):
    __tablename__ = "entities"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    hub_id: Mapped[str] = mapped_column(ForeignKey("hubs.id"), index=True)
    slug: Mapped[str] = mapped_column(String(160), index=True)
    name: Mapped[str] = mapped_column(String(300))
    schema_type: Mapped[str] = mapped_column(String(64), default="SoftwareApplication")
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)
    sources: Mapped[list] = mapped_column(JSON, default=list)  # [{url, quote, retrieved_at}]
    jsonld: Mapped[dict] = mapped_column(JSON, default=dict)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    grounding_ratio: Mapped[float] = mapped_column(Float, default=0.0)
    validated: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft | published
    version: Mapped[int] = mapped_column(Integer, default=1)
    # Empresa fornecedora (dados cadastrais públicos, ex.: BrasilAPI/CNPJ)
    provider: Mapped[dict] = mapped_column(JSON, default=dict)
    # Quando os valores foram conferidos contra a fonte pela última vez
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Revisão humana (selo "Validado por especialista")
    human_reviewed_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    human_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    human_review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    hub: Mapped[Hub] = relationship(back_populates="entities")


class EntityVersion(Base):
    """Histórico de mutação dos dados — fosso defensivo (Dataset vivo, com changelog)."""

    __tablename__ = "entity_versions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    attributes: Mapped[dict] = mapped_column(JSON)
    changed_fields: Mapped[list] = mapped_column(JSON, default=list)
    source_task_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# --------------------------------------------------------------------------
# Relacionamento com o público: correções, leads, clientes da API
# --------------------------------------------------------------------------


class CorrectionRequest(Base):
    """Pedido de correção enviado por uma empresa ou leitor (canal público)."""

    __tablename__ = "correction_requests"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    hub_slug: Mapped[str | None] = mapped_column(String(120), nullable=True)
    entity_slug: Mapped[str | None] = mapped_column(String(160), nullable=True)
    name: Mapped[str] = mapped_column(String(160))
    email: Mapped[str] = mapped_column(String(200))
    company: Mapped[str | None] = mapped_column(String(200), nullable=True)
    message: Mapped[str] = mapped_column(Text)
    evidence_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)  # open | resolved | rejected
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class Lead(Base):
    """Pedido de demonstração (Camada 1 de monetização: CPL/afiliados)."""

    __tablename__ = "leads"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    hub_slug: Mapped[str] = mapped_column(String(120), index=True)
    entity_slug: Mapped[str] = mapped_column(String(160), index=True)
    entity_name: Mapped[str] = mapped_column(String(300))
    name: Mapped[str] = mapped_column(String(160))
    email: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    company: Mapped[str | None] = mapped_column(String(200), nullable=True)
    company_size: Mapped[str | None] = mapped_column(String(40), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    consent: Mapped[bool] = mapped_column(Boolean, default=False)  # LGPD: aceite de compartilhamento com o fornecedor
    status: Mapped[str] = mapped_column(String(16), default="new", index=True)  # new | sent | won | discarded
    value_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class ApiClient(Base):
    """Cliente da API paga (Camada 3 de monetização). A chave é guardada só como hash."""

    __tablename__ = "api_clients"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    key_prefix: Mapped[str] = mapped_column(String(16), index=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    plan: Mapped[str] = mapped_column(String(32), default="starter")
    daily_quota: Mapped[int] = mapped_column(Integer, default=1000)
    monthly_price_usd: Mapped[float] = mapped_column(Float, default=0.0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    usage_day: Mapped[str | None] = mapped_column(String(10), nullable=True)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    total_requests: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# --------------------------------------------------------------------------
# Radar de Ondas: inteligência de tendências (IA, GEO, anúncios e compras em IAs)
# --------------------------------------------------------------------------

WAVE_STAGES = ("sinal", "emergente", "crescendo", "mainstream", "saturada")


class Signal(Base):
    """Uma notícia/anúncio real encontrado pelo radar (sempre com URL de origem)."""

    __tablename__ = "signals"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    url: Mapped[str] = mapped_column(String(1000))
    url_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(500))
    source: Mapped[str] = mapped_column(String(200), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    topics: Mapped[list] = mapped_column(JSON, default=list)
    relevance: Mapped[float] = mapped_column(Float, default=0.0)
    found_via: Mapped[str] = mapped_column(String(16), default="search")  # feed | search | demo
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class Wave(Base):
    """Uma tendência ("onda") acompanhada ao longo do tempo."""

    __tablename__ = "waves"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    thesis: Mapped[str] = mapped_column(Text, default="")
    stage: Mapped[str] = mapped_column(String(16), default="sinal")  # ver WAVE_STAGES
    impact: Mapped[float] = mapped_column(Float, default=0.0)  # quanto afeta o nosso negócio (0-1)
    urgency: Mapped[float] = mapped_column(Float, default=0.0)  # quão cedo precisamos agir (0-1)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)  # quão sólida é a evidência (0-1)
    window: Mapped[str] = mapped_column(String(120), default="")  # janela de oportunidade
    relevance: Mapped[str] = mapped_column(Text, default="")  # por que importa para nós
    evidence: Mapped[list] = mapped_column(JSON, default=list)  # URLs de sinais
    status: Mapped[str] = mapped_column(String(16), default="watching")  # watching | acting | archived
    demo: Mapped[bool] = mapped_column(Boolean, default=False)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class WaveSnapshot(Base):
    """Foto da onda a cada varredura — permite ver se ela está subindo ou perdendo força."""

    __tablename__ = "wave_snapshots"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    wave_id: Mapped[str] = mapped_column(ForeignKey("waves.id"), index=True)
    stage: Mapped[str] = mapped_column(String(16))
    impact: Mapped[float] = mapped_column(Float)
    urgency: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    evidence_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PlayAction(Base):
    """Ação de posicionamento proposta pelo radar. Aprovada pelo fundador, vira diretriz para o CVO."""

    __tablename__ = "play_actions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    wave_id: Mapped[str | None] = mapped_column(ForeignKey("waves.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(300))
    action: Mapped[str] = mapped_column(Text)
    why: Mapped[str] = mapped_column(Text, default="")
    first_step: Mapped[str] = mapped_column(Text, default="")
    effort: Mapped[str] = mapped_column(String(16), default="medio")  # baixo | medio | alto
    est_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    deadline_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    requires_spend: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="proposed", index=True)  # proposed | approved | rejected | done
    directive_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# --------------------------------------------------------------------------
# Dados para IAs: quais robôs leem o portal e o quê
# --------------------------------------------------------------------------
class BotHit(Base):
    """Contagem diária de acessos por robô e tipo de recurso (página, arquivo de dados, grafo, llms)."""

    __tablename__ = "bot_hits"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    day: Mapped[str] = mapped_column(String(10), index=True)  # AAAA-MM-DD (UTC)
    bot: Mapped[str] = mapped_column(String(40), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # page | data | graph | llms | other
    hub: Mapped[str] = mapped_column(String(120), default="", index=True)  # "" = páginas do site inteiro
    hits: Mapped[int] = mapped_column(Integer, default=0)
    last_path: Mapped[str] = mapped_column(String(300), default="")
    last_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IndexPing(Base):
    """Registro de cada aviso enviado (portal + IndexNow): o quê, por quê e quanto tempo depois da mudança."""

    __tablename__ = "index_pings"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    hub_slug: Mapped[str] = mapped_column(String(120), index=True)
    reason: Mapped[str] = mapped_column(String(32))  # publish | data_change | review | unpublish
    urls: Mapped[list] = mapped_column(JSON, default=list)
    changed_fields: Mapped[dict] = mapped_column(JSON, default=dict)  # {entity_slug: [campos]}
    revalidated: Mapped[bool] = mapped_column(Boolean, default=False)
    indexnow: Mapped[str] = mapped_column(String(200), default="")
    lag_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)  # da detecção da mudança até o aviso
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class ViabilityReport(Base):
    """Veredito semanal do Gauss para um hub: as metas foram cumpridas? continuar, ajustar, pivotar ou encerrar."""

    __tablename__ = "viability_reports"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    hub_id: Mapped[str] = mapped_column(String(32), index=True)
    hub_slug: Mapped[str] = mapped_column(String(120))
    week: Mapped[str] = mapped_column(String(10), index=True)  # AAAA-Www (ISO)
    days_live: Mapped[int] = mapped_column(Integer, default=0)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    milestones: Mapped[list] = mapped_column(JSON, default=list)
    verdict: Mapped[str] = mapped_column(String(16))  # aquecendo | continuar | ajustar | pivotar | encerrar
    reasons: Mapped[list] = mapped_column(JSON, default=list)
    actions: Mapped[list] = mapped_column(JSON, default=list)
    demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class Meeting(Base):
    """Reunião do Conselho: os agentes debatem um tema em rodadas e o CVO fecha uma ata com decisões."""

    __tablename__ = "meetings"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    topic: Mapped[str] = mapped_column(String(500))
    trigger: Mapped[str] = mapped_column(String(32), default="manual")  # manual | semanal | viabilidade
    status: Mapped[str] = mapped_column(String(16), default="running", index=True)  # running | done | failed
    participants: Mapped[list] = mapped_column(JSON, default=list)
    rounds: Mapped[list] = mapped_column(JSON, default=list)  # [{round, agent, name, output}]
    memo: Mapped[dict] = mapped_column(JSON, default=dict)  # ata do CVO
    applied: Mapped[dict] = mapped_column(JSON, default=dict)  # o que virou diretriz, foco ou pedido de aprovação
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Niche(Base):
    """Nicho do catálogo: onde a empresa atua, com fonte oficial, forma de ganhar dinheiro e avaliação."""

    __tablename__ = "niches"

    slug: Mapped[str] = mapped_column(String(80), primary_key=True)
    rank: Mapped[int] = mapped_column(Integer, default=50)  # prioridade (1 = primeiro)
    name: Mapped[str] = mapped_column(String(200))
    examples: Mapped[str] = mapped_column(Text, default="")
    official_source: Mapped[str] = mapped_column(Text, default="")
    source_urls: Mapped[list] = mapped_column(JSON, default=list)
    revenue: Mapped[str] = mapped_column(Text, default="")
    assessment: Mapped[str] = mapped_column(Text, default="")
    scores: Mapped[dict] = mapped_column(JSON, default=dict)  # volume | pagante | dado_oficial | risco
    ymyl: Mapped[bool] = mapped_column(Boolean, default=False)  # saúde/finanças: regras extras de cuidado
    star: Mapped[bool] = mapped_column(Boolean, default=False)
    rules: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="ativo", index=True)  # ativo | pausado | bloqueado
    locked: Mapped[bool] = mapped_column(Boolean, default=False)  # bloqueio editorial: não pode ser ativado
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Diagnosis(Base):
    """Diagnóstico de Visibilidade em IA de uma marca (produto de entrada da agência)."""

    __tablename__ = "diagnoses"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # link secreto do relatório
    brand: Mapped[str] = mapped_column(String(200))
    site: Mapped[str] = mapped_column(String(500), default="")
    category: Mapped[str] = mapped_column(String(300))
    city: Mapped[str] = mapped_column(String(120), default="")
    competitors: Mapped[list] = mapped_column(JSON, default=list)  # [{name, site}]
    contact: Mapped[str] = mapped_column(String(300), default="")  # para quem o relatório será enviado
    engines: Mapped[list | None] = mapped_column(JSON, nullable=True)  # chatgpt | claude | perplexity | simulado
    query_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="running", index=True)  # running | done | failed
    mode: Mapped[str] = mapped_column(String(16), default="")  # web | parametric
    queries: Mapped[list] = mapped_column(JSON, default=list)
    visibility: Mapped[dict] = mapped_column(JSON, default=dict)
    technical: Mapped[dict] = mapped_column(JSON, default=dict)
    plan: Mapped[dict] = mapped_column(JSON, default=dict)
    scores: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# --------------------------------------------------------------------------
# Comercial automático (agência): prospecção → diagnóstico → e-mail → proposta → pagamento → entrega
# --------------------------------------------------------------------------
PROSPECT_STATUSES = ("novo", "sem_contato", "diagnosticado", "contatado", "respondeu", "proposta", "cliente", "perdido", "descadastrado")


class Prospect(Base):
    __tablename__ = "prospects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # links de proposta e descadastro
    company: Mapped[str] = mapped_column(String(200))
    site: Mapped[str] = mapped_column(String(500), default="")
    domain: Mapped[str] = mapped_column(String(200), default="", index=True)
    email: Mapped[str] = mapped_column(String(200), default="", index=True)
    contact_name: Mapped[str] = mapped_column(String(160), default="")
    segment: Mapped[str] = mapped_column(String(300), default="")
    city: Mapped[str] = mapped_column(String(120), default="")
    source: Mapped[str] = mapped_column(String(16), default="busca")  # busca | maps | inbound | demo
    place_id: Mapped[str] = mapped_column(String(160), default="", index=True)  # Google Maps (único dado do Places guardado sem prazo)
    consent: Mapped[bool] = mapped_column(Boolean, default=False)  # pediu o diagnóstico pelo site
    status: Mapped[str] = mapped_column(String(16), default="novo", index=True)
    diagnosis_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    touches: Mapped[int] = mapped_column(Integer, default=0)  # e-mails enviados (inicial + follow-ups)
    last_contact_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class EmailLog(Base):
    __tablename__ = "email_log"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    prospect_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    direction: Mapped[str] = mapped_column(String(4))  # out | in
    kind: Mapped[str] = mapped_column(String(24), default="")  # primeiro | followup | resposta | boas_vindas | relatorio | entrada
    to_addr: Mapped[str] = mapped_column(String(200), default="")
    from_addr: Mapped[str] = mapped_column(String(200), default="")
    subject: Mapped[str] = mapped_column(String(300), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="sent")  # sent | simulated | failed | received
    intent: Mapped[str] = mapped_column(String(16), default="")  # classificação das respostas
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class Suppression(Base):
    """Nunca mais contatar (descadastro, recusa, devolução). Vale para o e-mail e para o domínio."""

    __tablename__ = "suppressions"

    value: Mapped[str] = mapped_column(String(200), primary_key=True)  # e-mail ou domínio, minúsculo
    reason: Mapped[str] = mapped_column(String(60), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # página do cliente
    prospect_id: Mapped[str] = mapped_column(String(32), index=True)
    company: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(200), default="")
    plan: Mapped[str] = mapped_column(String(24), default="mensal")  # diagnostico | mensal
    status: Mapped[str] = mapped_column(String(16), default="ativo", index=True)  # ativo | cancelado | concluido
    mrr_brl: Mapped[float] = mapped_column(Float, default=0.0)
    kit: Mapped[dict] = mapped_column(JSON, default=dict)  # entregáveis de GEO gerados
    diagnoses: Mapped[list] = mapped_column(JSON, default=list)  # ids dos diagnósticos (histórico mensal)
    payment_ref: Mapped[str] = mapped_column(String(200), default="")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    next_report_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ContentPiece(Base):
    """Página de conteúdo (blog GEO) da Insighta: pauta → rascunho (IA) → aprovado/rejeitado pelo fundador → publicado."""

    __tablename__ = "content_pieces"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    slug: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(300))
    keyword: Mapped[str] = mapped_column(String(200), default="")
    cluster: Mapped[str] = mapped_column(String(60), default="")  # glosa | faturamento | agenda | financeiro | gestao
    intent: Mapped[str] = mapped_column(String(16), default="problema")  # problema (→ calculadora) | solucao (→ teste grátis)
    brief: Mapped[str] = mapped_column(Text, default="")  # o que a página precisa cobrir e fontes oficiais permitidas
    status: Mapped[str] = mapped_column(String(16), default="pauta", index=True)  # pauta | rascunho | aprovado | rejeitado | publicado
    meta_description: Mapped[str] = mapped_column(String(300), default="")
    body_md: Mapped[str] = mapped_column(Text, default="")
    faq: Mapped[list] = mapped_column(JSON, default=list)
    sources: Mapped[list] = mapped_column(JSON, default=list)
    review_notes: Mapped[str] = mapped_column(Text, default="")  # alertas automáticos (números a conferir etc.)
    priority: Mapped[int] = mapped_column(Integer, default=50)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
