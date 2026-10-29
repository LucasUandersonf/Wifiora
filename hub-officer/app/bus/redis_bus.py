"""Barramento Redis — produção (Railway). Filas duráveis em listas + Pub/Sub para telemetria."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import redis.asyncio as redis

from app.bus.base import Envelope, MessageBus

log = logging.getLogger(__name__)

QUEUE_PREFIX = "office:q:"
EVENTS_CHANNEL = "office:events"
BRPOP_TIMEOUT = 5
# O socket precisa esperar mais que o BRPOP bloqueante; senão o cliente aborta a leitura.
SOCKET_TIMEOUT = BRPOP_TIMEOUT + 10


class RedisBus(MessageBus):
    name = "redis"

    def __init__(self, url: str) -> None:
        self._url = url
        self._r: redis.Redis | None = None

    @property
    def r(self) -> redis.Redis:
        if self._r is None:
            self._r = redis.from_url(
                self._url,
                decode_responses=True,
                health_check_interval=30,
                socket_timeout=SOCKET_TIMEOUT,
                socket_connect_timeout=10,
                retry_on_timeout=True,
            )
        return self._r

    async def start(self) -> None:
        await self.r.ping()

    async def close(self) -> None:
        if self._r is not None:
            await self._r.aclose()
            self._r = None

    async def ping(self) -> bool:
        try:
            return bool(await self.r.ping())
        except Exception:
            return False

    async def send(self, envelope: Envelope) -> None:
        await self.r.lpush(QUEUE_PREFIX + envelope.recipient, envelope.model_dump_json())

    async def consume(self, recipient: str) -> AsyncIterator[Envelope]:
        key = QUEUE_PREFIX + recipient
        backoff = 1.0
        while True:
            try:
                item = await self.r.brpop([key], timeout=BRPOP_TIMEOUT)
                backoff = 1.0
            except (redis.ConnectionError, redis.TimeoutError, OSError) as e:
                log.warning("Redis indisponível na fila %s (%s); nova tentativa em %.0fs", key, e, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)
                continue
            if item is None:
                continue
            _, raw = item
            try:
                env = Envelope.model_validate_json(raw)
            except Exception:
                log.exception("Envelope inválido descartado da fila %s", key)
                continue
            yield env

    async def broadcast(self, event: dict[str, Any]) -> None:
        await self.r.publish(EVENTS_CHANNEL, json.dumps(event, default=str))

    async def listen(self) -> AsyncIterator[dict[str, Any]]:
        pubsub = self.r.pubsub()
        await pubsub.subscribe(EVENTS_CHANNEL)
        try:
            async for msg in pubsub.listen():
                if msg.get("type") == "message":
                    try:
                        yield json.loads(msg["data"])
                    except json.JSONDecodeError:
                        continue
        finally:
            await pubsub.unsubscribe(EVENTS_CHANNEL)
            await pubsub.aclose()

    async def purge(self) -> int:
        removed = 0
        async for key in self.r.scan_iter(match=QUEUE_PREFIX + "*"):
            removed += await self.r.llen(key)
            await self.r.delete(key)
        return removed

    async def queue_depths(self) -> dict[str, int]:
        depths: dict[str, int] = {}
        async for key in self.r.scan_iter(match=QUEUE_PREFIX + "*"):
            depths[key[len(QUEUE_PREFIX) :]] = await self.r.llen(key)
        return depths
