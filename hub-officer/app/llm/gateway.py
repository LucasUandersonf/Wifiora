"""Gateway único de LLM: roteia por tier, aplica guarda de orçamento, contabiliza custo e faz parse de JSON."""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any

from app.config import Settings
from app.llm.base import BudgetExceeded, DailyQuotaReached, LLMClient, LLMError, LLMRequest, LLMResult, SearchResult
from app.llm.pricing import cost_usd

if TYPE_CHECKING:
    from app.core.ledger import Ledger

log = logging.getLogger(__name__)

# Taxa por busca na web (estimativa: US$ 10 por 1.000 buscas — confira a tabela oficial).
WEB_SEARCH_USD = 0.01

EFFORT_BY_TIER = {"strategic": "high", "worker": "medium", "judge": "low"}

JSON_INSTRUCTION = (
    "\n\nResponda APENAS com um objeto JSON válido (sem markdown, sem texto fora do JSON). "
    "Nunca invente números, preços ou fatos: se não houver evidência, use null e explique em 'notes'."
)


def build_client(settings: Settings) -> LLMClient:
    provider = settings.llm_provider.lower()
    if provider == "free":
        from app.llm.free_client import FreeLLMClient

        return FreeLLMClient(settings)
    if provider == "anthropic":
        from app.llm.anthropic_client import AnthropicClient

        return AnthropicClient(settings.anthropic_api_key)
    if provider == "openai":
        from app.llm.other_clients import OpenAIClient

        return OpenAIClient(settings.openai_api_key, settings.openai_model)
    if provider == "gemini":
        from app.llm.other_clients import GeminiClient

        return GeminiClient(settings.gemini_api_key, settings.gemini_model)
    from app.llm.mock import MockLLM

    return MockLLM(settings.mock_latency_seconds)


def parse_json(text: str) -> dict[str, Any]:
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise LLMError("resposta do LLM não contém JSON") from None
        data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise LLMError("JSON do LLM não é um objeto")
    return data


class LLMGateway:
    def __init__(self, settings: Settings, ledger: Ledger, client: LLMClient | None = None) -> None:
        self.settings = settings
        self.ledger = ledger
        self.client = client or build_client(settings)

    def model_for(self, tier: str) -> str:
        if self.client.provider == "free":
            return f"rodizio:{tier}"  # a rota real (provedor:modelo) volta em LLMResult.model
        if self.client.provider == "openai":
            return self.settings.openai_model
        if self.client.provider == "gemini":
            return self.settings.gemini_model
        return {
            "strategic": self.settings.model_strategic,
            "judge": self.settings.model_judge,
        }.get(tier, self.settings.model_worker)

    async def complete(
        self,
        *,
        kind: str,
        system: str,
        prompt: str,
        tier: str = "worker",
        agent_id: str | None = None,
        objective_id: str | None = None,
        task_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> LLMResult:
        await self._guard()
        model = self.model_for(tier)
        req = LLMRequest(
            system=system,
            prompt=prompt,
            model=model,
            kind=kind,
            max_tokens=self.settings.llm_max_tokens,
            effort=EFFORT_BY_TIER.get(tier, "medium"),
            tier=tier,
            context=context or {},
        )
        result = await self.client.complete(req)

        simulated = self.client.provider == "mock"
        amount = self._cost(result)
        if simulated and not self.settings.mock_simulate_cost:
            amount = 0.0
        await self.ledger.record_llm(
            agent_id=agent_id,
            objective_id=objective_id,
            task_id=task_id,
            provider=result.provider,
            model=result.model,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            amount_usd=amount,
            simulated=simulated,
            description=kind,
        )
        return result

    async def _guard(self) -> None:
        if await self.ledger.llm_budget_exhausted():
            raise BudgetExceeded("orçamento diário de LLM esgotado — aguardando aprovação do fundador")
        limit = self.settings.llm_daily_call_limit
        if limit and await self.ledger.llm_calls_today() >= limit:
            raise DailyQuotaReached(f"limite diário de {limit} chamadas de IA atingido")

    def _cost(self, result: LLMResult) -> float:
        if self.client.provider == "free":
            if self.client.is_free(result.model):  # type: ignore[attr-defined]
                return 0.0
            return cost_usd(result.model.partition(":")[2], result.input_tokens, result.output_tokens)
        return cost_usd(result.model, result.input_tokens, result.output_tokens)

    @property
    def can_search(self) -> bool:
        return hasattr(self.client, "search")

    async def search(self, *, prompt: str, agent_id: str | None = None, max_uses: int = 3) -> SearchResult:
        if not self.can_search:
            raise LLMError(f"o provedor {self.client.provider} não suporta busca na web neste sistema")
        await self._guard()
        model = self.model_for("judge")
        res = await self.client.search(prompt=prompt, model=model, max_uses=max_uses)
        amount = cost_usd(model, res.input_tokens, res.output_tokens) + res.searches * WEB_SEARCH_USD
        await self.ledger.record_llm(
            agent_id=agent_id, provider=self.client.provider, model=model, input_tokens=res.input_tokens,
            output_tokens=res.output_tokens, amount_usd=round(amount, 6), simulated=False, description=f"geo.audit ({res.searches} buscas)",
        )
        return res

    async def complete_json(self, *, retries: int = 1, **kwargs: Any) -> dict[str, Any]:
        kwargs["prompt"] = kwargs["prompt"] + JSON_INSTRUCTION
        last_err: Exception | None = None
        for attempt in range(retries + 1):
            result = await self.complete(**kwargs)
            try:
                return parse_json(result.text)
            except (LLMError, json.JSONDecodeError) as e:
                last_err = e
                log.warning("JSON inválido em %s (tentativa %s): %s", kwargs.get("kind"), attempt + 1, e)
        raise LLMError(f"falha ao obter JSON válido: {last_err}")
