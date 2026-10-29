"""IAs gratuitas: rodízio entre provedores, custo zero e descanso ao atingir a cota diária."""

from __future__ import annotations

import httpx
import pytest

from app.config import get_settings
from app.llm.base import LLMRequest
from app.llm.free_client import FreeLLMClient, parse_routes


def _settings(**kw):
    base = {"groq_api_key": "g", "gemini_api_key": "m", "openrouter_api_key": None,
            "free_llm_routes": "groq:llama-3.3-70b-versatile|gemini:gemini-2.5-flash|openrouter:openrouter/free"}
    return get_settings().model_copy(update={**base, **kw})


def test_routes_skip_missing_keys():
    routes = parse_routes(_settings().free_llm_routes, _settings())
    assert [r.label for r in routes] == ["groq:llama-3.3-70b-versatile", "gemini:gemini-2.5-flash"]  # sem chave do OpenRouter
    assert all(r.free for r in routes)


@pytest.mark.asyncio
async def test_fallback_on_rate_limit():
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.url.host)
        if "groq" in req.url.host:
            return httpx.Response(429, headers={"retry-after": "120"}, json={"error": "rate"})
        body = req.read().decode()
        assert '"max_tokens":4096' in body.replace(" ", "")  # respeita o teto dos planos grátis
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 10, "completion_tokens": 3}})

    client = FreeLLMClient(_settings(), transport=httpx.MockTransport(handler))
    req = LLMRequest(system="s", prompt="p", model="x", kind="k", max_tokens=16000)
    res = await client.complete(req)
    assert res.model == "gemini:gemini-2.5-flash" and res.text == '{"ok": true}'
    assert calls == ["api.groq.com", "generativelanguage.googleapis.com"]
    await client.complete(req)  # o Groq está "descansando": vai direto ao Gemini
    assert calls[-1] == "generativelanguage.googleapis.com" and calls.count("api.groq.com") == 1


@pytest.mark.asyncio
async def test_daily_quota_rests_until_tomorrow(office):
    from app.llm.base import DailyQuotaReached

    office.settings = office.settings.model_copy(update={"llm_daily_call_limit": 1})
    office.llm.settings = office.settings
    await office.llm.complete(kind="market_research", system="s", prompt="p")
    with pytest.raises(DailyQuotaReached):
        await office.llm.complete(kind="market_research", system="s", prompt="p")

    from app.bus.base import Envelope

    agent = next(iter(office.agents.values()))
    await office.handle_budget_block(agent, Envelope(type="noop", sender="t", recipient=agent.agent_id), DailyQuotaReached("limite"))
    assert office.resting() and not await office.gov.get("paused")  # descansa sem pedir aprovação
