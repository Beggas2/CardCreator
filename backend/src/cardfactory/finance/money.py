"""Valores monetários em Decimal (ADR-0010)."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, getcontext

getcontext().prec = 28
QUANT = Decimal("0.00000001")
ZERO = Decimal("0")


def D(value: object) -> Decimal:  # noqa: N802 - nome curto intencional
    if value is None or value == "":
        return ZERO
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        value = repr(value)
    return Decimal(str(value))


def q(value: Decimal) -> str:
    return format(value.quantize(QUANT, rounding=ROUND_HALF_UP), "f")


def usd_to_brl(usd: Decimal, rate: Decimal, margin: Decimal) -> Decimal:
    """Converte com margem de câmbio/IOF/taxas: brl = usd × taxa × (1 + margem)."""
    return usd * rate * (Decimal(1) + margin)
