"""Entrada HTTP (FastAPI). Em OFFICE_ROLE=all também sobe os agentes no mesmo processo."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import agency, control, dashboard, datasets, newsletter, portal_admin, public, radar, v1
from app.config import get_settings
from app.core import bots
from app.core.office import Office
from app.db import dispose_db, init_db

WEB = Path(__file__).parent / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if settings.founder_token == "change-me" and settings.app_env == "production":
        raise RuntimeError("Defina FOUNDER_TOKEN antes de rodar em produção.")
    await init_db()
    office = Office(settings)
    run_agents = settings.runs_agents and settings.office_autostart
    await office.start(run_agents=run_agents)
    app.state.office = office
    try:
        yield
    finally:
        await bots.COUNTER.flush()
        await office.stop()
        await dispose_db()


app = FastAPI(title="GEO Office — Escritório Virtual Autônomo", version="0.1.0", lifespan=lifespan)
app.include_router(dashboard.router)
app.include_router(control.router)
app.include_router(portal_admin.read)
app.include_router(portal_admin.write)
app.include_router(radar.read)
app.include_router(radar.write)
app.include_router(v1.router)
app.include_router(agency.router)
app.include_router(newsletter.router)
app.include_router(datasets.router)  # antes de public: /hub/{slug}/data.csv etc.
app.include_router(public.router)


_BACKGROUND: set[asyncio.Task] = set()


@app.middleware("http")
async def count_ai_bots(request: Request, call_next):
    """Conta acessos de robôs de IA às páginas e arquivos de dados (só respostas 2xx/304)."""
    response = await call_next(request)
    ok = request.method == "GET" and (response.status_code < 300 or response.status_code == 304)
    if ok and bots.COUNTER.add(request.headers.get("user-agent"), request.url.path) and bots.COUNTER.due():
        task = asyncio.create_task(bots.COUNTER.flush())
        _BACKGROUND.add(task)  # sem referência, o asyncio pode descartar a tarefa no meio
        task.add_done_callback(_BACKGROUND.discard)
    return response


app.mount("/static", StaticFiles(directory=WEB / "static"), name="static")


@app.get("/healthz", include_in_schema=False)
async def healthz() -> dict:
    office: Office = app.state.office
    return {"ok": True, "bus": office.bus.name, "bus_ok": await office.bus.ping(), "llm": office.llm.client.provider}


@app.get("/office", include_in_schema=False)
async def office_page() -> FileResponse:
    return FileResponse(WEB / "static" / "office.html", headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex"})


@app.get("/radar", include_in_schema=False)
async def radar_page() -> FileResponse:
    return FileResponse(WEB / "static" / "radar.html", headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex"})


@app.get("/dashboard", include_in_schema=False)
async def dashboard_page() -> FileResponse:
    return FileResponse(WEB / "static" / "dashboard.html", headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex"})
