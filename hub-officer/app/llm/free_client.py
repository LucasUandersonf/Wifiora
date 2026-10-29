"""IAs gratuitas (ou locais) por HTTP no formato OpenAI — sem SDK extra.

Rotas no formato `provedor:modelo`, separadas por "|", tentadas em ordem. Se uma devolver limite de
uso (429), erro do servidor ou demorar demais, a próxima é usada e a primeira descansa pelo tempo
pedido em `Retry-After` (ou 60 s). Assim o escritório segue trabalhando quando um plano grátis esgota.

Provedores conhecidos (confira os limites atuais no painel de cada um — mudam com frequência):
  groq        https://api.groq.com/openai/v1                         (GROQ_API_KEY)
  gemini      https://generativelanguage.googleapis.com/v1beta/openai (GEMINI_API_KEY)
  openrouter  https://openrouter.ai/api/v1                           (OPENROUTER_API_KEY; use modelos ":free")
  ollama      http://localhost:11434/v1                              (OLLAMA_BASE_URL; roda na sua máquina)
  openai      https://api.openai.com/v1                              (OPENAI_API_KEY; pago)
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

import httpx

from app.config import Settings
from app.llm.base import LLMClient, LLMError, LLMRequest, LLMResult

log = logging.getLogger(__name__)

PRESETS: dict[str, str] = {
    "groq": "https://api.groq.com/openai/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "openrouter": "https://openrouter.ai/api/v1",
    "ollama": "http://localhost:11434/v1",
    "openai": "https://api.openai.com/v1",
}
# Provedores cujo uso, nos planos gratuitos, não gera cobrança (Gemini: só sem faturamento ativado).
FREE_PROVIDERS = {"groq", "gemini", "ollama"}
RETRYABLE = {408, 409, 425, 429, 500, 502, 503, 504}


@dataclass
class Route:
    provider: str
    model: str
    base_url: str
    api_key: str | None
    cooldown_until: float = 0.0

    @property
    def label(self) -> str:
        return f"{self.provider}:{self.model}"

    @property
    def free(self) -> bool:
        return self.provider in FREE_PROVIDERS or (self.provider == "openrouter" and (self.model.endswith(":free") or self.model == "openrouter/free"))


def parse_routes(spec: str, settings: Settings) -> list[Route]:
    keys = {
        "groq": settings.groq_api_key,
        "gemini": settings.gemini_api_key,
        "openrouter": settings.openrouter_api_key,
        "openai": settings.openai_api_key,
        "ollama": None,
    }
    routes: list[Route] = []
    for item in [x.strip() for x in spec.split("|") if x.strip()]:
        provider, _, model = item.partition(":")
        provider = provider.lower()
        if provider not in PRESETS or not model:
            raise LLMError(f"rota de LLM inválida: {item!r} (use provedor:modelo, provedores: {', '.join(PRESETS)})")
        base = settings.ollama_base_url if provider == "ollama" else PRESETS[provider]
        if provider != "ollama" and not keys[provider]:
            log.warning("rota %s ignorada: chave %s_API_KEY não configurada", item, provider.upper())
            continue
        routes.append(Route(provider, model, base.rstrip("/"), keys[provider]))
    return routes


class FreeLLMClient(LLMClient):
    provider = "free"

    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.routes = {
            "default": parse_routes(settings.free_llm_routes, settings),
            "strategic": parse_routes(settings.free_llm_routes_strategic, settings) if settings.free_llm_routes_strategic else [],
        }
        if not self.routes["default"]:
            raise LLMError("nenhuma rota de IA gratuita utilizável: configure FREE_LLM_ROUTES e as chaves dos provedores")
        self.timeout = settings.free_llm_timeout_seconds
        self.max_tokens = settings.free_llm_max_tokens
        self._transport = transport

    def routes_for(self, tier: str) -> list[Route]:
        own = self.routes["strategic"] if tier == "strategic" else []
        return own + [r for r in self.routes["default"] if r not in own]

    def is_free(self, model_label: str) -> bool:
        return any(r.label == model_label and r.free for rs in self.routes.values() for r in rs)

    async def complete(self, req: LLMRequest) -> LLMResult:
        tier = req.tier
        errors: list[str] = []
        now = time.monotonic()
        candidates = [r for r in self.routes_for(tier) if r.cooldown_until <= now] or self.routes_for(tier)
        for route in candidates:
            try:
                return await self._call(route, req)
            except _Retryable as e:
                route.cooldown_until = time.monotonic() + e.wait
                errors.append(f"{route.label}: {e}")
                log.warning("IA %s indisponível (%s); tentando a próxima", route.label, e)
        raise LLMError("todas as rotas de IA falharam: " + "; ".join(errors))

    async def _call(self, route: Route, req: LLMRequest) -> LLMResult:
        headers = {"Content-Type": "application/json"}
        if route.api_key:
            headers["Authorization"] = f"Bearer {route.api_key}"
        if route.provider == "openrouter":
            headers["X-Title"] = "GEO Office"
        body = {
            "model": route.model,
            "max_tokens": min(req.max_tokens, self.max_tokens),
            "temperature": 0.2,
            "messages": [{"role": "system", "content": req.system}, {"role": "user", "content": req.prompt}],
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self._transport) as c:
                r = await c.post(f"{route.base_url}/chat/completions", json=body, headers=headers)
        except (httpx.TimeoutException, httpx.TransportError) as e:
            raise _Retryable(f"rede/tempo esgotado: {e.__class__.__name__}", 30) from e
        if r.status_code in RETRYABLE:
            raise _Retryable(f"HTTP {r.status_code}", _retry_after(r))
        if r.status_code >= 400:
            # 401/403/404: chave ou modelo errado — não adianta repetir nesta rota, mas outras podem servir.
            raise _Retryable(f"HTTP {r.status_code}: {r.text[:200]}", 3600)
        data = r.json()
        choices = data.get("choices") or []
        text = ((choices[0].get("message") or {}).get("content") if choices else None) or ""
        if not text.strip():
            raise _Retryable("resposta vazia", 30)
        usage = data.get("usage") or {}
        return LLMResult(
            text=text,
            provider=route.provider,
            model=route.label,
            input_tokens=int(usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
            stop_reason=choices[0].get("finish_reason"),
        )


class _Retryable(Exception):
    def __init__(self, msg: str, wait: float) -> None:
        super().__init__(msg)
        self.wait = wait


def _retry_after(r: httpx.Response) -> float:
    try:
        return min(3600.0, max(5.0, float(r.headers.get("retry-after", "60"))))
    except ValueError:
        return 60.0


async def check_routes(settings: Settings) -> list[dict[str, object]]:
    """Teste rápido de cada rota (usado pelo painel/CLI): responde? quanto demora?"""
    client = FreeLLMClient(settings)
    out = []
    for route in client.routes_for("strategic"):
        t0 = time.monotonic()
        try:
            res = await asyncio.wait_for(
                client._call(route, LLMRequest(system="Responda só OK.", prompt="OK?", model=route.model, kind="ping", max_tokens=5)), timeout=30
            )
            out.append({"route": route.label, "ok": True, "seconds": round(time.monotonic() - t0, 2), "free": route.free, "reply": res.text[:20]})
        except Exception as e:
            out.append({"route": route.label, "ok": False, "error": str(e)[:200], "free": route.free})
    return out


if __name__ == "__main__":  # python -m app.llm.free_client  → testa cada rota configurada
    import json

    from app.config import get_settings

    print(json.dumps(asyncio.run(check_routes(get_settings())), ensure_ascii=False, indent=2))
