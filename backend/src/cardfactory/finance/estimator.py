"""Estimativa do custo máximo de uma chamada antes da execução (COST_CONTROL.md §3, FIN-003)."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from cardfactory.finance.money import ZERO, D

# Limite superior conservador quando não há tokenizer: 1 token a cada 2,5 caracteres.
CHARS_PER_TOKEN_UPPER = Decimal("2.5")


@dataclass
class CostEstimate:
    max_usd: Decimal
    safe: bool
    basis: dict = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)


def upper_bound_tokens(text_chars: int) -> int:
    return int((Decimal(text_chars) / CHARS_PER_TOKEN_UPPER).to_integral_value(rounding="ROUND_CEILING")) + 16


def estimate_call(
    pricing: dict | None,
    *,
    input_chars: int,
    max_output_tokens: int,
    web_searches: int = 0,
    web_search_price_usd: Decimal | None = None,
    ocr_pages: int = 0,
    ocr_price_per_page_usd: Decimal | None = None,
    repair_attempts: int = 1,
    free_provider: bool = False,
) -> CostEstimate:
    """Retorna o teto de custo. `safe=False` quando algum termo não pode ser estimado.

    `pricing` segue o catálogo OpenRouter: valores em USD por token (strings).
    Cache não reduz o teto. Raciocínio é cobrado como saída e cabe no max_output_tokens.
    """
    if free_provider:
        return CostEstimate(ZERO, True, {"provider": "mock"})
    reasons: list[str] = []
    if not pricing or "prompt" not in pricing or "completion" not in pricing:
        return CostEstimate(ZERO, False, {}, ["preço do modelo ausente no catálogo"])
    try:
        p_in = D(pricing["prompt"])
        p_out = max(D(pricing["completion"]), D(pricing.get("internal_reasoning", "0")))
        p_req = D(pricing.get("request", "0"))
    except Exception:  # noqa: BLE001
        return CostEstimate(ZERO, False, {}, ["preço do modelo ilegível"])
    if p_in < 0 or p_out < 0:
        return CostEstimate(ZERO, False, {}, ["preço variável/negativo no catálogo"])

    tokens_in = upper_bound_tokens(input_chars)
    one_call = p_req + p_in * tokens_in + p_out * max_output_tokens
    total = one_call * (1 + repair_attempts)
    if web_searches:
        if web_search_price_usd is None:
            reasons.append("preço de pesquisa web desconhecido")
        else:
            total += web_search_price_usd * web_searches
    if ocr_pages:
        if ocr_price_per_page_usd is None:
            reasons.append("preço de OCR desconhecido")
        else:
            total += ocr_price_per_page_usd * ocr_pages
    basis = {
        "tokens_in_upper": tokens_in,
        "max_output_tokens": max_output_tokens,
        "price_in": str(p_in),
        "price_out": str(p_out),
        "price_request": str(p_req),
        "repair_attempts": repair_attempts,
        "web_searches": web_searches,
        "ocr_pages": ocr_pages,
    }
    return CostEstimate(total, not reasons, basis, reasons)
