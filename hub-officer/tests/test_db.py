"""Migração leve: colunas novas em tabelas antigas são adicionadas sozinhas na subida."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.db import get_engine, init_db


@pytest.mark.asyncio
async def test_missing_column_is_added(office):
    async with get_engine().begin() as conn:
        await conn.execute(text("DROP INDEX ix_bot_hits_hub"))
        await conn.execute(text('ALTER TABLE bot_hits DROP COLUMN "hub"'))
    await init_db()
    async with get_engine().begin() as conn:
        cols = [r[1] for r in (await conn.execute(text("PRAGMA table_info(bot_hits)"))).all()]
        idx = [r[1] for r in (await conn.execute(text("PRAGMA index_list(bot_hits)"))).all()]
    assert "hub" in cols and "ix_bot_hits_hub" in idx
