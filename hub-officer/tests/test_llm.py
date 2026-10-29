from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.llm.anthropic_client import AnthropicClient
from app.llm.base import LLMRefusal, LLMRequest
from app.llm.gateway import parse_json


def _fake_response(stop_reason: str, text: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        stop_reason=stop_reason,
        model="claude-opus-5-5",
        content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=120, output_tokens=40),
    )


def _client(resp: SimpleNamespace, captured: dict) -> AnthropicClient:
    c = AnthropicClient(api_key="sk-test")

    async def create(**kwargs):
        captured.update(kwargs)
        return resp

    c.client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))
    return c


@pytest.mark.asyncio
async def test_anthropic_request_shape_and_text_extraction():
    captured: dict = {}
    c = _client(_fake_response("end_turn", '{"ok": true}'), captured)
    res = await c.complete(LLMRequest(system="s", prompt="p", model="claude-opus-5-5", kind="k", effort="high"))
    assert res.text == '{"ok": true}' and res.input_tokens == 120
    assert captured["thinking"] == {"type": "adaptive"}
    assert captured["output_config"] == {"effort": "high"}
    assert captured["fallbacks"] == "default" and captured["betas"] == ["server-side-fallback-2026-07-01"]


@pytest.mark.asyncio
async def test_anthropic_refusal_raises():
    c = _client(_fake_response("refusal"), {})
    with pytest.raises(LLMRefusal):
        await c.complete(LLMRequest(system="s", prompt="p", model="claude-haiku-5-5", kind="k"))


def test_parse_json_handles_fences_and_prose():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('Aqui está:\n{"a": {"b": 2}}\nobrigado') == {"a": {"b": 2}}


@pytest.mark.asyncio
async def test_search_separates_seen_and_cited_urls_and_resumes_pause_turn():
    c = AnthropicClient(api_key="sk-test")
    seen = SimpleNamespace(type="web_search_tool_result", content=[SimpleNamespace(url="https://hub.com.br/hub/erps"), SimpleNamespace(url="https://outro.com")])
    cite = SimpleNamespace(type="text", text="Segundo o hub...", citations=[SimpleNamespace(url="https://hub.com.br/hub/erps")])
    usage = lambda n: SimpleNamespace(input_tokens=100, output_tokens=20, server_tool_use=SimpleNamespace(web_search_requests=n))
    responses = [
        SimpleNamespace(stop_reason="pause_turn", content=[seen], usage=usage(1)),
        SimpleNamespace(stop_reason="end_turn", content=[cite], usage=usage(1)),
    ]
    calls = []

    async def create(**kw):
        calls.append(kw)
        return responses[len(calls) - 1]

    c.client = SimpleNamespace(messages=SimpleNamespace(create=create))
    res = await c.search(prompt="melhor ERP?", model="claude-opus-5-5")
    assert len(calls) == 2 and calls[1]["messages"][-1]["role"] == "assistant"
    assert calls[0]["tools"][0]["type"] == "web_search_20260209"
    assert res.urls == ["https://hub.com.br/hub/erps"] and "https://outro.com" in res.seen_urls
    assert res.searches == 2 and res.input_tokens == 200


@pytest.mark.asyncio
async def test_announce_never_pings_search_engines_for_demo():
    from app.config import Settings
    from app.core.indexing import announce

    st = Settings(public_base_url="https://hub.com.br", indexnow_key="abc123")
    res = await announce(st, hub_slug="x", entity_slugs=[], demo=True)
    assert res["indexnow"].startswith("skipped") and res["revalidated"] is False
    st_local = Settings(public_base_url="http://localhost:8000", indexnow_key="abc123")
    assert "não é um domínio público" in (await announce(st_local, hub_slug="x", entity_slugs=[], demo=False))["indexnow"]
