"""Processo worker dedicado (OFFICE_ROLE=worker): só agentes + scheduler, sem HTTP.

Uso no Railway com dois serviços: `web` (OFFICE_ROLE=api) e `worker` (OFFICE_ROLE=worker),
compartilhando PostgreSQL e Redis.
"""

from __future__ import annotations

import asyncio
import logging
import signal

from app.config import get_settings
from app.core.office import Office
from app.db import dispose_db, init_db


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    await init_db()
    office = Office(settings)
    await office.start(run_agents=True)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()
    await office.stop()
    await dispose_db()


if __name__ == "__main__":
    asyncio.run(main())
