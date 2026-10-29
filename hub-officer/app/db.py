"""Engine/sessões assíncronas do SQLAlchemy."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import inspect, text

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


log = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine, _sessionmaker
    if _engine is None:
        url = get_settings().async_database_url
        kwargs: dict = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            if ":memory:" in url:
                raise RuntimeError("SQLite em memória não suporta agentes concorrentes; use um arquivo (sqlite+aiosqlite:///./office.db).")
            kwargs["connect_args"] = {"timeout": 30}  # espera o lock em vez de falhar com 'database is locked'
        else:
            kwargs.update(pool_size=10, max_overflow=10)
        _engine = create_async_engine(url, **kwargs)
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Sessão transacional: commit no sucesso, rollback em erro."""
    get_engine()
    assert _sessionmaker is not None
    async with _sessionmaker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_session() -> AsyncIterator[AsyncSession]:
    """Dependência FastAPI."""
    async with session_scope() as s:
        yield s


async def init_db() -> None:
    from app import models  # noqa: F401  (registra as tabelas)

    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        added = await conn.run_sync(_add_missing_columns)
    if added:
        log.warning("migração leve: colunas adicionadas %s", added)


def _add_missing_columns(sync_conn: Any) -> list[str]:
    """Migração leve: `create_all` cria tabelas novas, mas não colunas novas em tabelas que já existem.
    Aqui adicionamos as colunas que faltam (sempre como NULL, para não quebrar linhas antigas).
    Renomear ou remover colunas exige uma migração de verdade (Alembic)."""
    insp = inspect(sync_conn)
    added: list[str] = []
    for table in Base.metadata.sorted_tables:
        if not insp.has_table(table.name):
            continue
        existing = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name in existing:
                continue
            coltype = col.type.compile(dialect=sync_conn.dialect)
            sync_conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {coltype}'))
            added.append(f"{table.name}.{col.name}")
        for idx in table.indexes:  # índices das colunas recém-adicionadas
            if any(f"{table.name}.{c.name}" in added for c in idx.columns):
                idx.create(sync_conn, checkfirst=True)
    return added


async def dispose_db() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine, _sessionmaker = None, None
