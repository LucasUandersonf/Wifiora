"""Organograma do escritório. Para adicionar um especialista: crie a classe e inclua-a em SECTORS."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.agents.base import BaseAgent
from app.agents.cvo import ChiefVirtualOfficer
from app.agents.evaluator import ScoreAgent
from app.agents.scout import make_scout
from app.agents.specialist import SpecialistAgent
from app.agents.specialists.finance import GrowthAgent, UnitEconomicsAgent
from app.agents.specialists.radar import PositioningStrategistAgent, SignalHunterAgent, WaveAnalystAgent
from app.agents.specialists.research import DataExtractionAgent, MarketResearchAgent, SchemaOntologyAgent
from app.agents.specialists.tech import DevOpsAgent, FrontendAgent

if TYPE_CHECKING:
    from app.core.office import Office

SECTORS: dict[str, dict] = {
    "research": {
        "scout_id": "scout.research",
        "title": "Data & Market Scout",
        "mission": "Liderar pesquisa, inteligência e GEO: escolher entidades, garantir schema impecável e dados com fonte.",
        "specialists": [MarketResearchAgent, SchemaOntologyAgent, DataExtractionAgent],
    },
    "tech": {
        "scout_id": "scout.tech",
        "title": "Tech Scout",
        "mission": "Liderar engenharia e plataforma: páginas ultraleves para LLMs e infraestrutura confiável no Railway.",
        "specialists": [FrontendAgent, DevOpsAgent],
    },
    "finance": {
        "scout_id": "scout.finance",
        "title": "Financial Scout",
        "mission": "Liderar finanças e performance: custo sob controle, ROI positivo e caminhos claros de monetização.",
        "specialists": [UnitEconomicsAgent, GrowthAgent],
    },
    "radar": {
        "scout_id": "scout.radar",
        "title": "Radar Scout (Ondas da IA)",
        "mission": "Liderar a inteligência de tendências: perceber cedo as ondas da IA (anúncios, compras agênticas, GEO) e posicionar a empresa antes delas.",
        "specialists": [SignalHunterAgent, WaveAnalystAgent, PositioningStrategistAgent],
    },
}


def build_org(office: Office) -> tuple[list[BaseAgent], dict[str, str]]:
    agents: list[BaseAgent] = [ChiefVirtualOfficer(office), ScoreAgent(office)]
    scouts_by_sector: dict[str, str] = {}
    for sector, spec in SECTORS.items():
        specialists: list[SpecialistAgent] = [cls(office) for cls in spec["specialists"]]
        scout_cls = make_scout(spec["scout_id"], spec["title"], sector, spec["mission"])
        agents.append(scout_cls(office, {s.agent_id: s.task_kind for s in specialists}))
        agents.extend(specialists)
        scouts_by_sector[sector] = spec["scout_id"]
    return agents, scouts_by_sector
