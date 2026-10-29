"""Motores de IA do rastreador: fazem a pergunta como um consumidor faria e devolvem texto + fontes.

  chatgpt     → OpenAI Responses API com a ferramenta de busca na web (OPENAI_API_KEY)
  claude      → Anthropic Messages API com busca na web (ANTHROPIC_API_KEY)
  perplexity  → Perplexity Sonar (busca embutida, devolve citações) (PERPLEXITY_API_KEY)
  simulado    → o LLM configurado no escritório, sem busca (IA gratuita/mock) — é estimativa

Atenção: a resposta da API não é idêntica à do aplicativo (que personaliza por usuário e histórico);
serve como amostra padronizada e repetível. Custos por chamada são ESTIMATIVAS — confira as tabelas oficiais.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import httpx

from app.llm.pricing import cost_usd

if TYPE_CHECKING:
    from app.core.office import Office

LABELS = {"chatgpt": "ChatGPT", "claude": "Claude", "perplexity": "Perplexity", "simulado": "IA (estimativa)"}
SEARCH_FEE_USD = {"chatgpt": 0.01, "claude": 0.01, "perplexity": 0.005, "simulado": 0.0}  # estimativa por pergunta
SYSTEM = "Você é um assistente respondendo a um consumidor no Brasil. Recomende marcas e empresas específicas quando souber, citando sites."


@dataclass
class Answer:
    engine: str
    text: str
    urls: list[str] = field(default_factory=list)
    cost_usd: float = 0.0
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0


def available(office: Office) -> list[str]:
    st = office.settings
    out = []
    if st.openai_api_key:
        out.append("chatgpt")
    if st.anthropic_api_key or office.llm.client.provider == "anthropic":
        out.append("claude")
    if st.perplexity_api_key:
        out.append("perplexity")
    return out or ["simulado"]


def _urls(text: str) -> list[str]:
    return re.findall(r"https?://[^\s)\]\"'>]+", text or "")


async def ask_chatgpt(office: Office, q: str, transport: httpx.AsyncBaseTransport | None = None) -> Answer:
    st = office.settings
    body = {"model": st.tracker_openai_model, "input": q, "instructions": SYSTEM, "tools": [{"type": st.tracker_openai_search_tool}]}
    async with httpx.AsyncClient(timeout=90, transport=transport) as c:
        r = await c.post("https://api.openai.com/v1/responses", json=body, headers={"Authorization": f"Bearer {st.openai_api_key}"})
    r.raise_for_status()
    data = r.json()
    texts, urls = [], []
    for item in data.get("output") or []:
        parts = (item.get("content") or []) if isinstance(item, dict) else []
        for part in parts:
            if part.get("type") == "output_text":
                texts.append(part.get("text") or "")
                urls += [a.get("url") for a in part.get("annotations") or [] if a.get("url")]
    usage = data.get("usage") or {}
    i, o = int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0)
    text = "\n".join(texts)
    return Answer("chatgpt", text, list(dict.fromkeys(urls + _urls(text))), cost_usd(st.tracker_openai_model, i, o) + SEARCH_FEE_USD["chatgpt"], st.tracker_openai_model, i, o)


async def ask_perplexity(office: Office, q: str, transport: httpx.AsyncBaseTransport | None = None) -> Answer:
    st = office.settings
    body = {"model": st.tracker_perplexity_model, "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": q}]}
    async with httpx.AsyncClient(timeout=90, transport=transport) as c:
        r = await c.post("https://api.perplexity.ai/chat/completions", json=body, headers={"Authorization": f"Bearer {st.perplexity_api_key}"})
    r.raise_for_status()
    data = r.json()
    text = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    urls = [u for u in data.get("citations") or [] if isinstance(u, str)] + [s.get("url") for s in data.get("search_results") or [] if isinstance(s, dict) and s.get("url")]
    usage = data.get("usage") or {}
    i, o = int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)
    return Answer("perplexity", text, list(dict.fromkeys(urls + _urls(text))), cost_usd(st.tracker_perplexity_model, i, o) + SEARCH_FEE_USD["perplexity"], st.tracker_perplexity_model, i, o)


async def ask_claude(office: Office, q: str) -> Answer:
    from app.llm.anthropic_client import AnthropicClient

    st = office.settings
    client = office.llm.client if office.llm.client.provider == "anthropic" else AnthropicClient(st.anthropic_api_key)
    res = await client.search(prompt=f"{SYSTEM}\n\nPergunta do consumidor: {q}", model=st.model_judge, max_uses=3)  # type: ignore[attr-defined]
    return Answer("claude", res.text, list(dict.fromkeys(res.urls + res.seen_urls)),
                  cost_usd(st.model_judge, res.input_tokens, res.output_tokens) + res.searches * SEARCH_FEE_USD["claude"], st.model_judge, res.input_tokens, res.output_tokens)


async def ask_simulated(office: Office, q: str, context: dict[str, Any], task_id: str | None) -> Answer:
    res = await office.llm.complete(kind="diagnosis.answer", system=SYSTEM, prompt=q, tier="judge", agent_id="research.market", task_id=task_id, context=context)
    return Answer("simulado", res.text, _urls(res.text), 0.0, res.model)  # custo já lançado pelo gateway


async def ask(office: Office, engine: str, q: str, *, context: dict[str, Any], task_id: str | None) -> Answer:
    if engine == "chatgpt":
        ans = await ask_chatgpt(office, q)
    elif engine == "perplexity":
        ans = await ask_perplexity(office, q)
    elif engine == "claude":
        ans = await ask_claude(office, q)
    else:
        return await ask_simulated(office, q, context, task_id)
    await office.ledger.record_llm(agent_id="research.market", task_id=task_id, provider=engine, model=ans.model, input_tokens=ans.input_tokens,
                                   output_tokens=ans.output_tokens, amount_usd=round(ans.cost_usd, 6), simulated=False, description=f"rastreador {engine}")
    return ans


def estimate_cost(engines: list[str], queries: int) -> float:
    """Estimativa grosseira por relatório (perguntas × motores), para o painel e a precificação."""
    per = {"chatgpt": 0.02, "claude": 0.03, "perplexity": 0.01, "simulado": 0.0}
    return round(sum(per.get(e, 0.02) for e in engines) * queries, 2)
