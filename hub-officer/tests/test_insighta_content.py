"""Time de Conteúdo & GEO da Insighta: pauta, rascunho com alertas, aprovação do fundador e página exportada."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.core import insighta_content as ic

H = {"X-Founder-Token": "test-token"}


def test_review_flags_catch_numbers_and_promises():
    flags = ic.review_flags("Clínicas perdem 12% do faturamento, R$ 4.500 por mês. Garantimos o resultado.")
    assert any("12%" in f for f in flags) and any("R$ 4.500" in f for f in flags) and any("promessa" in f for f in flags)
    assert ic.review_flags("Explique o fluxo do recurso de glosa.") == []


@pytest.mark.asyncio
async def test_content_flow(office, monkeypatch):
    monkeypatch.setattr(office.settings, "business", "insighta")
    monkeypatch.setattr(office.settings, "insighta_landing_url", None)
    assert (await ic.tick(office))["skipped"]  # desligado por padrão
    out = await ic.tick(office, force=True)
    assert out["rascunho"] == "O que é glosa médica e por que ela acontece"  # maior prioridade primeiro
    assert office.content_audit["checked"] is False  # sem domínio próprio, não audita

    from app.main import app

    app.state.office = office
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        panel = (await c.get("/api/office/content", headers=H)).json()
        draft = next(p for p in panel["pieces"] if p["status"] == "rascunho")
        assert panel["counts"]["pauta"] == len(ic.BACKLOG) - 1
        md = (await c.get(f"/api/office/content/{draft['id']}.md", headers=H)).text
        assert md.startswith("---") and '"FAQPage"' in md and '"Article"' in md and "utm_source=blog" in md and "#calculadora" in md
        r = await c.post(f"/api/control/content/{draft['id']}/decide", json={"approve": True}, headers=H)
        assert r.json()["status"] == "aprovado"
        assert (await c.get("/api/office/content", headers=H)).status_code == 200
        assert (await c.get("/api/office/content")).status_code == 401
