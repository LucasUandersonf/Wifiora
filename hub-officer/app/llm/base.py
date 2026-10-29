from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any


class LLMError(Exception):
    pass


class LLMRefusal(LLMError):
    pass


class BudgetExceeded(LLMError):
    pass


class DailyQuotaReached(BudgetExceeded):
    """Limite diário de chamadas (planos gratuitos) atingido: o escritório descansa até o dia seguinte."""


@dataclass
class LLMRequest:
    system: str
    prompt: str
    model: str
    kind: str  # rótulo semântico da chamada (usado pelo mock e pelo ledger)
    max_tokens: int = 16000
    effort: str = "medium"  # low | medium | high
    tier: str = "worker"  # strategic | worker | judge (rotas grátis podem priorizar um modelo melhor no strategic)
    context: dict[str, Any] = field(default_factory=dict)  # dados estruturados auxiliares (mock)


@dataclass
class LLMResult:
    text: str
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str | None = None


@dataclass
class SearchResult:
    """Resposta de um assistente com busca na web (para medir citações/Share of Voice)."""

    text: str
    urls: list[str]  # citadas na resposta
    seen_urls: list[str] = field(default_factory=list)  # apareceram nos resultados da busca
    results: list[dict] = field(default_factory=list)  # [{url, title, page_age}] dos resultados
    input_tokens: int = 0
    output_tokens: int = 0
    searches: int = 0


class LLMClient(abc.ABC):
    provider: str = "abstract"

    @abc.abstractmethod
    async def complete(self, req: LLMRequest) -> LLMResult: ...
