from __future__ import annotations

from app.bus.base import MessageBus
from app.bus.memory import InMemoryBus
from app.config import Settings


def build_bus(settings: Settings) -> MessageBus:
    if settings.redis_url:
        from app.bus.redis_bus import RedisBus

        return RedisBus(settings.redis_url)
    if settings.office_role != "all":
        raise RuntimeError("OFFICE_ROLE=api/worker exige REDIS_URL (processos separados precisam de barramento compartilhado).")
    return InMemoryBus()
