"""Governança em runtime: parâmetros que o fundador pode alterar pelo dashboard sem redeploy.

Persistidos em `office_settings` e lidos com cache curto, para funcionar também quando API e
worker rodam em processos/serviços diferentes no Railway.
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import select

from app.config import Settings
from app.db import session_scope
from app.models import Directive, OfficeSetting

EDITABLE_KEYS = {
    "paused": bool,
    "autonomy_level": int,
    "daily_llm_budget_usd": float,
    "monthly_budget_usd": float,
    "focus_niche": str,
    "cycle_interval_seconds": int,
    "score_threshold": float,
    "radar_enabled": bool,
    "radar_interval_seconds": int,
    "niche_rotation": bool,
    "sales_enabled": bool,
    "sales_auto_send": bool,
    "sales_daily_email_cap": int,
    "content_enabled": bool,
    "newsletter_enabled": bool,
    "viability_bots_days": int,
    "viability_traction_days": int,
    "viability_revenue_days": int,
    "viability_min_leads": int,
}


class Governance:
    def __init__(self, settings: Settings, ttl_seconds: float = 3.0) -> None:
        self.settings = settings
        self.ttl = ttl_seconds
        self._cache: dict[str, Any] = {}
        self._loaded_at = 0.0

    def defaults(self) -> dict[str, Any]:
        s = self.settings
        return {
            "paused": False,
            "autonomy_level": s.autonomy_level,
            "daily_llm_budget_usd": s.daily_llm_budget_usd,
            "monthly_budget_usd": s.monthly_budget_usd,
            "focus_niche": s.default_niche,
            "cycle_interval_seconds": s.cycle_interval_seconds,
            "score_threshold": s.score_threshold,
            "radar_enabled": s.radar_enabled,
            "radar_interval_seconds": s.radar_interval_seconds,
            "niche_rotation": s.niche_rotation,
            "sales_enabled": s.sales_enabled,
            "sales_auto_send": s.sales_auto_send,
            "sales_daily_email_cap": s.sales_daily_email_cap,
            "content_enabled": s.content_enabled,
            "newsletter_enabled": s.newsletter_enabled,
            "viability_bots_days": s.viability_bots_days,
            "viability_traction_days": s.viability_traction_days,
            "viability_revenue_days": s.viability_revenue_days,
            "viability_min_leads": s.viability_min_leads,
        }

    async def snapshot(self, force: bool = False) -> dict[str, Any]:
        if force or time.monotonic() - self._loaded_at > self.ttl:
            values = self.defaults()
            async with session_scope() as s:
                rows = (await s.execute(select(OfficeSetting))).scalars().all()
                for row in rows:
                    if row.key in EDITABLE_KEYS:
                        values[row.key] = row.value.get("v")
            self._cache = values
            self._loaded_at = time.monotonic()
        return dict(self._cache)

    async def get(self, key: str) -> Any:
        return (await self.snapshot())[key]

    async def set(self, key: str, value: Any, updated_by: str = "founder") -> None:
        if key not in EDITABLE_KEYS:
            raise KeyError(f"configuração não editável: {key}")
        value = EDITABLE_KEYS[key](value)
        async with session_scope() as s:
            row = await s.get(OfficeSetting, key)
            if row is None:
                s.add(OfficeSetting(key=key, value={"v": value}, updated_by=updated_by))
            else:
                row.value = {"v": value}
                row.updated_by = updated_by
        await self.snapshot(force=True)

    async def active_directives(self) -> list[str]:
        async with session_scope() as s:
            rows = (await s.execute(select(Directive).where(Directive.active.is_(True)).order_by(Directive.created_at))).scalars()
            return [d.text for d in rows]
