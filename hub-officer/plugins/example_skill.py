"""Exemplo de plugin: qualquer .py nesta pasta é carregado automaticamente no startup.

Para dar a skill a um agente, adicione o `name` em `skill_names` da classe do agente.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.skills.base import Skill


class SelicRateSkill(Skill):
    name = "selic_rate"
    description = "Consulta a taxa Selic vigente na API pública do Banco Central (SGS série 432)."
    sectors = ("finance", "research")

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        url = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.432/dados/ultimos/1?formato=json"
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(url)
            r.raise_for_status()
        last = r.json()[-1]
        return {"date": last["data"], "selic_pct": float(last["valor"])}
