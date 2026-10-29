from __future__ import annotations

import anthropic

from app.llm.base import LLMClient, LLMError, LLMRefusal, LLMRequest, LLMResult, SearchResult

# Modelos que aceitam o fallback server-side em caso de recusa por classificador de segurança.
_FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}


class AnthropicClient(LLMClient):
    provider = "anthropic"

    def __init__(self, api_key: str | None = None) -> None:
        # Sem api_key explícita o SDK resolve credenciais do ambiente (ANTHROPIC_API_KEY etc.).
        self.client = anthropic.AsyncAnthropic(api_key=api_key) if api_key else anthropic.AsyncAnthropic()

    async def complete(self, req: LLMRequest) -> LLMResult:
        kwargs: dict = {
            "model": req.model,
            "max_tokens": req.max_tokens,
            "system": req.system,
            "messages": [{"role": "user", "content": req.prompt}],
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": req.effort},
        }
        if req.model in _FALLBACK_MODELS:
            kwargs["betas"] = ["server-side-fallback-2026-07-01"]
            kwargs["fallbacks"] = "default"
        try:
            resp = await self.client.beta.messages.create(**kwargs)
        except anthropic.RateLimitError as e:
            raise LLMError(f"rate limit: {e}") from e
        except anthropic.APIStatusError as e:
            raise LLMError(f"anthropic {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise LLMError(f"falha de conexão: {e}") from e

        if resp.stop_reason == "refusal":
            raise LLMRefusal(f"modelo recusou a solicitação ({req.kind})")
        text = "".join(b.text for b in resp.content if b.type == "text")
        return LLMResult(
            text=text,
            provider=self.provider,
            model=resp.model,
            input_tokens=resp.usage.input_tokens or 0,
            output_tokens=resp.usage.output_tokens or 0,
            stop_reason=resp.stop_reason,
        )

    async def search(self, *, prompt: str, model: str, max_uses: int = 3) -> SearchResult:
        """Responde como um assistente com busca na web e devolve as URLs que ele consultou/citou."""
        messages: list[dict] = [{"role": "user", "content": prompt}]
        tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": max_uses}]
        urls: list[str] = []
        seen: list[str] = []
        results: list[dict] = []
        texts: list[str] = []
        tokens_in = tokens_out = searches = 0
        resp = None
        for _ in range(3):  # retoma pause_turn no máximo 2 vezes
            try:
                resp = await self.client.messages.create(
                    model=model, max_tokens=4000, messages=messages, tools=tools,
                    thinking={"type": "adaptive"}, output_config={"effort": "low"},
                )
            except anthropic.APIStatusError as e:
                raise LLMError(f"anthropic {e.status_code}: {e.message}") from e
            except anthropic.APIConnectionError as e:
                raise LLMError(f"falha de conexão: {e}") from e
            tokens_in += resp.usage.input_tokens or 0
            tokens_out += resp.usage.output_tokens or 0
            stu = getattr(resp.usage, "server_tool_use", None)
            searches += int(getattr(stu, "web_search_requests", 0) or 0)
            for block in resp.content:
                if block.type == "web_search_tool_result" and isinstance(block.content, list):
                    for r in block.content:
                        if getattr(r, "url", None):
                            seen.append(r.url)
                            results.append({"url": r.url, "title": getattr(r, "title", "") or "", "page_age": getattr(r, "page_age", None)})
                elif block.type == "text":
                    texts.append(block.text)
                    for c in getattr(block, "citations", None) or []:
                        if getattr(c, "url", None):
                            urls.append(c.url)
            if resp.stop_reason != "pause_turn":
                break
            messages = [*messages, {"role": "assistant", "content": resp.content}]
        if resp is not None and resp.stop_reason == "refusal":
            raise LLMRefusal("modelo recusou a busca")
        return SearchResult(text="".join(texts), urls=list(dict.fromkeys(urls)), seen_urls=list(dict.fromkeys(seen)), results=results, input_tokens=tokens_in, output_tokens=tokens_out, searches=searches)
