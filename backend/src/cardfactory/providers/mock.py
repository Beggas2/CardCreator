"""Provedor simulado determinístico e roteirizável (PRV-001). Nunca acessa a rede e nunca cobra."""

from __future__ import annotations

import asyncio
import json
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from cardfactory.providers.base import (
    CostRecord,
    KeyStatus,
    LLMRequest,
    LLMResult,
    ModelInfo,
    ProviderError,
    Usage,
)

MOCK_MODELS = [
    ModelInfo("mock/creator-a", "Mock Criador A", {"prompt": "0", "completion": "0"}, 128000, 16000,
              ["structured_outputs", "response_format", "reasoning", "tools"], ["text"]),
    ModelInfo("mock/auditor-b", "Mock Auditor B", {"prompt": "0", "completion": "0"}, 128000, 16000,
              ["structured_outputs", "response_format", "tools"], ["text", "file"]),
]


@dataclass
class Scripted:
    """Uma resposta roteirizada. `kind` controla o cenário."""

    kind: str = "ok"  # ok | invalid_json | truncated | rate_limited | server_error | timeout | billing | model_swap
    payload: Any = None
    cost_usd: str = "0"
    served_model: str | None = None
    retry_after_s: float | None = None
    delay_s: float = 0.0


@dataclass
class MockProvider:
    name: str = "mock"
    paid: bool = False
    script: deque[Scripted] = field(default_factory=deque)
    responder: Callable[[LLMRequest], Any] | None = None
    calls: list[LLMRequest] = field(default_factory=list)
    _gen: int = 0

    def enqueue(self, *items: Scripted) -> None:
        self.script.extend(items)

    async def catalog(self) -> list[ModelInfo]:
        return list(MOCK_MODELS)

    async def complete(self, req: LLMRequest) -> LLMResult:
        self.calls.append(req)
        self._gen += 1
        gen_id = f"mock-gen-{self._gen}"
        step = self.script.popleft() if self.script else Scripted()
        if step.delay_s:
            await asyncio.sleep(step.delay_s)
        served = step.served_model or req.model_id
        payload = step.payload
        if payload is None:
            payload = self.responder(req) if self.responder else {"ok": True, "limitations": []}
        text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        usage = Usage(len(json.dumps(req.messages)) // 4, len(text) // 4, 0, 0, Decimal(step.cost_usd))
        k = step.kind
        if k == "ok" or k == "model_swap":
            return LLMResult("ok", text, served, "mock", gen_id, "stop", usage, latency_ms=1)
        if k == "invalid_json":
            return LLMResult("ok", "{isto não é json", served, "mock", gen_id, "stop", usage, latency_ms=1)
        if k == "truncated":
            return LLMResult("truncated", text[: max(1, len(text) // 2)], served, "mock", gen_id, "length", usage)
        if k == "rate_limited":
            return LLMResult("error", generation_id=None, usage=Usage(cost_usd=Decimal(0)),
                             error=ProviderError("rate_limited", "429 simulado", 429, step.retry_after_s,
                                                 "rate_limit_exceeded"))
        if k == "server_error":
            return LLMResult("error", usage=Usage(cost_usd=Decimal(0)),
                             error=ProviderError("transient", "502 simulado", 502, None, "provider_unavailable"))
        if k == "billing":
            return LLMResult("error", usage=Usage(cost_usd=Decimal(0)),
                             error=ProviderError("pre_generation", "402 simulado", 402, None, "payment_required"))
        if k == "permanent":
            return LLMResult("error", usage=Usage(cost_usd=Decimal(0)),
                             error=ProviderError("pre_generation", "400 simulado", 400, None, "invalid_request"))
        if k == "timeout":
            return LLMResult("uncertain", generation_id=None,
                             error=ProviderError("uncertain", "timeout após envio (simulado)"))
        raise ValueError(f"cenário desconhecido: {k}")

    async def lookup_cost(self, generation_id: str) -> CostRecord | None:
        return CostRecord(Decimal(0), None, "mock", "stop", False)

    async def key_status(self) -> KeyStatus | None:
        return None
