"""Barramento em memória — desenvolvimento local e testes (processo único)."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator
from typing import Any

from app.bus.base import Envelope, MessageBus


class InMemoryBus(MessageBus):
    name = "memory"

    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue[Envelope]] = defaultdict(asyncio.Queue)
        self._listeners: set[asyncio.Queue[dict[str, Any]]] = set()

    async def send(self, envelope: Envelope) -> None:
        await self._queues[envelope.recipient].put(envelope)

    async def consume(self, recipient: str) -> AsyncIterator[Envelope]:
        queue = self._queues[recipient]
        while True:
            env = await queue.get()
            try:
                yield env
            finally:
                queue.task_done()

    async def broadcast(self, event: dict[str, Any]) -> None:
        for q in list(self._listeners):
            if q.qsize() < 1000:  # listener lento não derruba o escritório
                q.put_nowait(event)

    async def listen(self) -> AsyncIterator[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._listeners.add(q)
        try:
            while True:
                yield await q.get()
        finally:
            self._listeners.discard(q)

    async def queue_depths(self) -> dict[str, int]:
        return {k: q.qsize() for k, q in self._queues.items()}

    async def purge(self) -> int:
        removed = 0
        for q in self._queues.values():
            while not q.empty():
                q.get_nowait()
                q.task_done()
                removed += 1
        return removed

    async def drained(self) -> bool:
        return all(q.qsize() == 0 and q._unfinished_tasks == 0 for q in self._queues.values())
