"""Adaptador OpenRouter (Chat Completions, ADR-0007). Ver docs/providers/OPENROUTER.md.

Nenhum ID de modelo é codificado aqui. Chamadas só ocorrem via `LLMGateway`, que exige
reserva de orçamento e autorização de gasto antes de invocar `complete`.
"""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Any

import httpx

from cardfactory.finance.money import D
from cardfactory.providers.base import (
    CostRecord,
    KeyStatus,
    LLMRequest,
    LLMResult,
    ModelInfo,
    ProviderError,
    Usage,
)
from cardfactory.security.secrets import auth_via_proxy, get_api_key, redact

BASE_URL = "https://openrouter.ai/api/v1"
APP_TITLE = "CardFactory"  # cabeçalho genérico, sem dados pessoais


def _retry_after(resp: httpx.Response) -> float | None:
    v = resp.headers.get("Retry-After")
    if not v:
        return None
    try:
        return max(0.0, float(v))
    except ValueError:
        return None


def classify_http_error(status: int, body: dict[str, Any] | None, resp: httpx.Response | None) -> ProviderError:
    err = (body or {}).get("error") or {}
    msg = redact(str(err.get("message") or f"HTTP {status}"))
    etype = (err.get("metadata") or {}).get("error_type")
    ra = _retry_after(resp) if resp is not None else None
    if status == 429:
        return ProviderError("rate_limited", msg, status, ra, etype)
    if status == 503:  # nenhum provedor atende antes da geração
        return ProviderError("rate_limited" if ra else "transient", msg, status, ra, etype)
    if status == 402:
        return ProviderError("pre_generation", msg, status, ra, etype or "payment_required")
    if status in (400, 401, 403, 404, 413, 422):
        return ProviderError("pre_generation", msg, status, None, etype)
    # 408, 500, 502, 504, 524 e desconhecidos: não sabemos se houve geração cobrada.
    return ProviderError("uncertain", msg, status, ra, etype)


def build_body(req: LLMRequest) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": req.model_id,
        "messages": req.messages,
        "max_tokens": req.max_output_tokens,
    }
    if req.temperature is not None:
        body["temperature"] = req.temperature
    if req.response_schema is not None:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": req.schema_name, "strict": True, "schema": req.response_schema},
        }
    r = req.routing
    provider: dict[str, Any] = {
        "allow_fallbacks": r.allow_fallbacks,
        "require_parameters": r.require_parameters,
        "data_collection": r.data_collection,
    }
    if r.order:
        provider["order"] = r.order
    if r.only:
        provider["only"] = r.only
    if r.max_price:
        provider["max_price"] = r.max_price
    body["provider"] = provider
    if req.reasoning:
        body["reasoning"] = req.reasoning
    if req.web_search:
        body["tools"] = [{"type": "openrouter:web_search", "parameters": req.web_search}]
    return body


def parse_completion(data: dict[str, Any], headers: httpx.Headers | None = None) -> LLMResult:
    gen_id = data.get("id") or (headers.get("X-Generation-Id") if headers else None)
    u = data.get("usage") or {}
    usage = Usage(
        tokens_in=u.get("prompt_tokens"),
        tokens_out=u.get("completion_tokens"),
        tokens_cached=(u.get("prompt_tokens_details") or {}).get("cached_tokens"),
        tokens_reasoning=(u.get("completion_tokens_details") or {}).get("reasoning_tokens"),
        cost_usd=D(u["cost"]) if u.get("cost") is not None else None,
    )
    if "error" in data and not data.get("choices"):
        err = data["error"] or {}
        return LLMResult("uncertain", generation_id=gen_id, usage=usage,
                         error=ProviderError("uncertain", redact(str(err.get("message", "erro após cabeçalho"))),
                                             err.get("code")))
    choice = (data.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    finish = choice.get("finish_reason")
    citations = [a.get("url_citation", {}) for a in (msg.get("annotations") or []) if a.get("type") == "url_citation"]
    base = dict(output_text=msg.get("content"), served_model=data.get("model"), served_provider=data.get("provider"),
                generation_id=gen_id, finish_reason=finish, usage=usage, citations=citations)
    if finish == "length":
        return LLMResult("truncated", **base)
    if finish == "error":
        return LLMResult("uncertain", error=ProviderError("uncertain", "erro durante a geração"), **base)
    return LLMResult("ok", **base)


def parse_model(m: dict[str, Any]) -> ModelInfo:
    arch = m.get("architecture") or {}
    top = m.get("top_provider") or {}
    return ModelInfo(
        model_id=m["id"],
        name=m.get("name", m["id"]),
        pricing={k: str(v) for k, v in (m.get("pricing") or {}).items() if not isinstance(v, (dict, list))},
        context_length=m.get("context_length") or top.get("context_length"),
        max_completion_tokens=top.get("max_completion_tokens"),
        supported_parameters=list(m.get("supported_parameters") or []),
        input_modalities=list(arch.get("input_modalities") or []),
        raw=m,
    )


class OpenRouterProvider:
    name = "openrouter"
    paid = True

    def __init__(self, api_key: str | None = None, base_url: str = BASE_URL,
                 transport: httpx.AsyncBaseTransport | None = None):
        self._key = api_key or get_api_key()
        self._base = base_url.rstrip("/")
        self._transport = transport

    def _client(self, timeout: float) -> httpx.AsyncClient:
        headers = {"X-OpenRouter-Title": APP_TITLE}
        if self._key:
            headers["Authorization"] = f"Bearer {self._key}"
        elif not auth_via_proxy():
            raise RuntimeError("OPENROUTER_API_KEY não configurada")
        return httpx.AsyncClient(base_url=self._base, headers=headers, timeout=timeout, transport=self._transport)

    async def catalog(self) -> list[ModelInfo]:
        async with self._client(60) as c:
            r = await c.get("/models")
            r.raise_for_status()
            return [parse_model(m) for m in r.json().get("data", [])]

    async def complete(self, req: LLMRequest) -> LLMResult:
        t0 = time.monotonic()
        try:
            async with self._client(req.timeout_s) as c:
                resp = await c.post("/chat/completions", json=build_body(req))
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            # Falha de conexão: a requisição não chegou ao servidor.
            return LLMResult("error", error=ProviderError("pre_generation", f"conexão: {type(e).__name__}"))
        except httpx.TimeoutException as e:
            return LLMResult("uncertain", error=ProviderError("uncertain", f"timeout após envio: {type(e).__name__}"))
        except httpx.HTTPError as e:
            return LLMResult("uncertain", error=ProviderError("uncertain", redact(f"erro de transporte: {e}")))
        latency = int((time.monotonic() - t0) * 1000)
        try:
            data = resp.json()
        except ValueError:
            data = None
        if resp.status_code != 200:
            res = LLMResult("error" if resp.status_code in (400, 401, 402, 403, 404, 413, 422, 429, 503)
                            else "uncertain", error=classify_http_error(resp.status_code, data, resp))
            res.generation_id = resp.headers.get("X-Generation-Id")
            res.latency_ms = latency
            return res
        if not isinstance(data, dict):
            return LLMResult("uncertain", error=ProviderError("uncertain", "resposta 200 sem JSON"),
                             generation_id=resp.headers.get("X-Generation-Id"), latency_ms=latency)
        result = parse_completion(data, resp.headers)
        result.latency_ms = latency
        return result

    async def lookup_cost(self, generation_id: str) -> CostRecord | None:
        async with self._client(30) as c:
            r = await c.get("/generation", params={"id": generation_id})
            if r.status_code == 404:
                return None
            r.raise_for_status()
            d = r.json().get("data") or {}
            return CostRecord(
                total_cost_usd=D(d["total_cost"]) if d.get("total_cost") is not None else None,
                served_model=d.get("model"), served_provider=d.get("provider_name"),
                finish_reason=d.get("finish_reason"), cancelled=d.get("cancelled"), raw=d)

    async def key_status(self) -> KeyStatus | None:
        async with self._client(30) as c:
            r = await c.get("/key")
            r.raise_for_status()
            d = r.json().get("data") or {}

            def opt(v: Any) -> Decimal | None:
                return D(v) if v is not None else None

            return KeyStatus(opt(d.get("limit")), opt(d.get("limit_remaining")), opt(d.get("usage")), d)
