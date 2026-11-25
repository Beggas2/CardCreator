"""Contrato independente de fornecedor (CONTRACTS.md §3, PRV-001)."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal, Protocol

ErrorClass = Literal["transient", "rate_limited", "permanent", "billing", "uncertain", "pre_generation"]
ResultStatus = Literal["ok", "truncated", "invalid_output", "error", "uncertain"]


@dataclass
class RoutingPolicy:
    allow_fallbacks: bool = False
    require_parameters: bool = True
    order: list[str] | None = None
    only: list[str] | None = None
    data_collection: str = "deny"
    max_price: dict[str, str] | None = None


@dataclass
class LLMRequest:
    model_id: str
    messages: list[dict[str, Any]]
    max_output_tokens: int
    idempotency_key: str
    response_schema: dict[str, Any] | None = None
    schema_name: str = "output"
    reasoning: dict[str, Any] | None = None
    web_search: dict[str, Any] | None = None
    routing: RoutingPolicy = field(default_factory=RoutingPolicy)
    timeout_s: float = 180.0
    temperature: float | None = None


@dataclass
class Usage:
    tokens_in: int | None = None
    tokens_out: int | None = None
    tokens_cached: int | None = None
    tokens_reasoning: int | None = None
    cost_usd: Decimal | None = None


@dataclass
class ProviderError:
    cls: ErrorClass
    message: str
    status: int | None = None
    retry_after_s: float | None = None
    error_type: str | None = None


@dataclass
class LLMResult:
    status: ResultStatus
    output_text: str | None = None
    served_model: str | None = None
    served_provider: str | None = None
    generation_id: str | None = None
    finish_reason: str | None = None
    usage: Usage = field(default_factory=Usage)
    citations: list[dict[str, Any]] = field(default_factory=list)
    error: ProviderError | None = None
    latency_ms: int | None = None


@dataclass
class ModelInfo:
    model_id: str
    name: str
    pricing: dict[str, str]
    context_length: int | None
    max_completion_tokens: int | None
    supported_parameters: list[str]
    input_modalities: list[str]
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def supports_structured(self) -> bool:
        return "structured_outputs" in self.supported_parameters or "response_format" in self.supported_parameters


@dataclass
class KeyStatus:
    limit_usd: Decimal | None
    limit_remaining_usd: Decimal | None
    usage_usd: Decimal | None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class CostRecord:
    total_cost_usd: Decimal | None
    served_model: str | None
    served_provider: str | None
    finish_reason: str | None
    cancelled: bool | None
    raw: dict[str, Any] = field(default_factory=dict)


class LLMProvider(Protocol):
    name: str
    paid: bool

    async def catalog(self) -> list[ModelInfo]: ...

    async def complete(self, req: LLMRequest) -> LLMResult: ...

    async def lookup_cost(self, generation_id: str) -> CostRecord | None: ...

    async def key_status(self) -> KeyStatus | None: ...
