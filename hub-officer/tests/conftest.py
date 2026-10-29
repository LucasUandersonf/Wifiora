from __future__ import annotations

import os
import tempfile

import pytest_asyncio

# Arquivo, não ":memory:": em memória o SQLAlchemy compartilha UMA conexão entre todas as
# sessões concorrentes dos agentes, e as transações se atropelam (não reflete produção).
_DB_DIR = tempfile.mkdtemp(prefix="geo-office-test-")

os.environ.update(
    DATABASE_URL=f"sqlite+aiosqlite:///{_DB_DIR}/test.db",
    REDIS_URL="",
    LLM_PROVIDER="mock",
    OFFICE_ROLE="all",
    OFFICE_AUTOSTART="false",
    FOUNDER_TOKEN="test-token",
    ALLOW_WEB_FETCH="false",
    MOCK_LATENCY_SECONDS="0",
)

from app.config import get_settings
from app.core.office import Office
from app.db import dispose_db, init_db


@pytest_asyncio.fixture
async def office():
    get_settings.cache_clear()
    await dispose_db()
    db_file = os.path.join(_DB_DIR, "test.db")
    if os.path.exists(db_file):
        os.remove(db_file)
    await init_db()
    o = Office(get_settings())
    o.fast_retry = True
    await o.start(run_agents=True, run_scheduler=False)
    yield o
    await o.stop()
    await dispose_db()
