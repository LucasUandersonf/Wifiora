"""Tabela de preços (USD por 1M tokens: entrada, saída). Atualize conforme as tabelas oficiais."""

from __future__ import annotations

PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    # Anthropic
    "claude-fable-5-1": (10.00, 50.00),
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
    # OpenAI
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    # Google
    "gemini-2.5-pro": (1.25, 10.00),
    "gemini-2.5-flash": (0.30, 2.50),
}

DEFAULT_PRICE = (4.00, 20.00)  # conservador: usa o preço de um modelo de topo quando desconhecido


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    pin, pout = PRICES_PER_MTOK.get(model, DEFAULT_PRICE)
    return round(input_tokens / 1_000_000 * pin + output_tokens / 1_000_000 * pout, 6)
