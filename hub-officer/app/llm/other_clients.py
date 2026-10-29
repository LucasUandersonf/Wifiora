"""Provedores alternativos (OpenAI / Gemini). Dependências opcionais — instale `openai` ou `google-genai`."""

from __future__ import annotations

from app.llm.base import LLMClient, LLMError, LLMRequest, LLMResult


class OpenAIClient(LLMClient):
    provider = "openai"

    def __init__(self, api_key: str | None, model: str) -> None:
        try:
            from openai import AsyncOpenAI
        except ImportError as e:  # pragma: no cover
            raise LLMError("pip install openai para usar LLM_PROVIDER=openai") from e
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model

    async def complete(self, req: LLMRequest) -> LLMResult:
        resp = await self.client.chat.completions.create(
            model=self.model,
            max_tokens=min(req.max_tokens, 16000),
            messages=[{"role": "system", "content": req.system}, {"role": "user", "content": req.prompt}],
        )
        usage = resp.usage
        return LLMResult(
            text=resp.choices[0].message.content or "",
            provider=self.provider,
            model=self.model,
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
        )


class GeminiClient(LLMClient):
    provider = "gemini"

    def __init__(self, api_key: str | None, model: str) -> None:
        try:
            from google import genai
        except ImportError as e:  # pragma: no cover
            raise LLMError("pip install google-genai para usar LLM_PROVIDER=gemini") from e
        self.client = genai.Client(api_key=api_key)
        self.model = model

    async def complete(self, req: LLMRequest) -> LLMResult:
        from google.genai import types

        resp = await self.client.aio.models.generate_content(
            model=self.model,
            contents=req.prompt,
            config=types.GenerateContentConfig(system_instruction=req.system, max_output_tokens=req.max_tokens),
        )
        meta = resp.usage_metadata
        return LLMResult(
            text=resp.text or "",
            provider=self.provider,
            model=self.model,
            input_tokens=getattr(meta, "prompt_token_count", 0) or 0,
            output_tokens=getattr(meta, "candidates_token_count", 0) or 0,
        )
