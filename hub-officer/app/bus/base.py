"""Contrato do barramento de mensagens inter-agentes.

Dois canais distintos:
  * Filas ponto-a-ponto (`send`/`consume`): trabalho endereçado a um agente. Com Redis são
    listas (LPUSH/BRPOP) — sobrevivem a restart do worker e permitem várias réplicas
    consumindo a mesma fila (competing consumers).
  * Broadcast (`broadcast`/`listen`): eventos de telemetria para o dashboard (fan-out, sem garantia).
"""

from __future__ import annotations

import abc
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class Envelope(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    type: str  # ex.: objective.assign, task.assign, review.request, task.approved ...
    sender: str
    recipient: str
    payload: dict[str, Any] = Field(default_factory=dict)
    objective_id: str | None = None
    task_id: str | None = None
    summary: str = ""
    attempt: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class MessageBus(abc.ABC):
    name: str = "abstract"

    async def start(self) -> None:  # pragma: no cover - default no-op
        return None

    async def close(self) -> None:  # pragma: no cover - default no-op
        return None

    @abc.abstractmethod
    async def send(self, envelope: Envelope) -> None: ...

    @abc.abstractmethod
    def consume(self, recipient: str) -> AsyncIterator[Envelope]: ...

    @abc.abstractmethod
    async def broadcast(self, event: dict[str, Any]) -> None: ...

    @abc.abstractmethod
    def listen(self) -> AsyncIterator[dict[str, Any]]: ...

    @abc.abstractmethod
    async def queue_depths(self) -> dict[str, int]: ...

    @abc.abstractmethod
    async def purge(self) -> int:
        """Descarta todas as mensagens pendentes (kill switch). Retorna quantas foram removidas."""

    async def ping(self) -> bool:
        return True
