"""Adaptador OpenRouter com transporte simulado (httpx.MockTransport). Nenhuma rede real."""

import json
from decimal import Decimal

import httpx
import pytest

from cardfactory.providers.base import LLMRequest, RoutingPolicy
from cardfactory.providers.openrouter import (
    OpenRouterProvider,
    build_body,
    classify_http_error,
    parse_completion,
    parse_model,
)

FAKE_KEY = "sk-or-v1-TESTKEYNOTREAL0000000000"


def _req(**kw) -> LLMRequest:
    base = dict(model_id="vendor/model-x", messages=[{"role": "user", "content": "oi"}], max_output_tokens=100,
                idempotency_key="k")
    base.update(kw)
    return LLMRequest(**base)


def _provider(handler) -> tuple[OpenRouterProvider, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def h(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    return OpenRouterProvider(api_key=FAKE_KEY, transport=httpx.MockTransport(h)), seen


COMPLETION = {
    "id": "gen-123", "model": "vendor/model-x", "provider": "SomeHost",
    "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": '{"ok": true}',
                 "annotations": [{"type": "url_citation", "url_citation": {"url": "https://ex.org", "title": "t"}}]}}],
    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.00012,
              "prompt_tokens_details": {"cached_tokens": 2}, "completion_tokens_details": {"reasoning_tokens": 1}},
}


def test_build_body_defaults_are_strict():
    b = build_body(_req(response_schema={"type": "object"}, schema_name="card"))
    assert b["model"] == "vendor/model-x" and b["max_tokens"] == 100
    assert b["response_format"]["json_schema"] == {"name": "card", "strict": True, "schema": {"type": "object"}}
    assert b["provider"] == {"allow_fallbacks": False, "require_parameters": True, "data_collection": "deny"}
    assert "tools" not in b and "temperature" not in b and "reasoning" not in b


def test_build_body_web_search_and_routing():
    b = build_body(_req(web_search={"max_results": 3}, reasoning={"effort": "high"}, temperature=0.2,
                        routing=RoutingPolicy(order=["A"], only=["A", "B"], max_price={"prompt": "1"})))
    assert b["tools"] == [{"type": "openrouter:web_search", "parameters": {"max_results": 3}}]
    assert b["reasoning"] == {"effort": "high"} and b["temperature"] == 0.2
    assert b["provider"]["order"] == ["A"] and b["provider"]["only"] == ["A", "B"]
    assert b["provider"]["max_price"] == {"prompt": "1"}


def test_parse_completion_ok():
    r = parse_completion(COMPLETION)
    assert r.status == "ok" and r.output_text == '{"ok": true}'
    assert r.generation_id == "gen-123" and r.served_model == "vendor/model-x"
    assert r.usage.cost_usd == Decimal("0.00012") and r.usage.tokens_cached == 2 and r.usage.tokens_reasoning == 1
    assert r.citations == [{"url": "https://ex.org", "title": "t"}]


def test_parse_completion_truncated_and_midstream_error():
    d = json.loads(json.dumps(COMPLETION))
    d["choices"][0]["finish_reason"] = "length"
    assert parse_completion(d).status == "truncated"
    d["choices"][0]["finish_reason"] = "error"
    assert parse_completion(d).status == "uncertain"
    e = parse_completion({"id": "gen-9", "error": {"message": "falhou", "code": 502}})
    assert e.status == "uncertain" and e.generation_id == "gen-9"


@pytest.mark.parametrize(("status", "cls"), [
    (429, "rate_limited"), (503, "transient"), (402, "pre_generation"), (400, "pre_generation"),
    (401, "pre_generation"), (404, "pre_generation"), (500, "uncertain"), (502, "uncertain"),
    (408, "uncertain"), (524, "uncertain"),
])
def test_classify_http_error(status, cls):
    assert classify_http_error(status, {"error": {"message": "x"}}, None).cls == cls


def test_classify_503_with_retry_after_is_rate_limited():
    resp = httpx.Response(503, headers={"Retry-After": "7"})
    e = classify_http_error(503, None, resp)
    assert e.cls == "rate_limited" and e.retry_after_s == 7


def test_error_message_is_redacted():
    e = classify_http_error(400, {"error": {"message": f"bad key {FAKE_KEY}"}}, None)
    assert FAKE_KEY not in e.message and "[REDACTED]" in e.message


def test_parse_model():
    m = parse_model({"id": "v/m", "name": "M", "context_length": 1000,
                     "pricing": {"prompt": "0.000001", "completion": 0.000002, "extra": {"x": 1}},
                     "top_provider": {"max_completion_tokens": 500},
                     "supported_parameters": ["structured_outputs"], "architecture": {"input_modalities": ["text"]}})
    assert m.pricing == {"prompt": "0.000001", "completion": "2e-06"}
    assert m.max_completion_tokens == 500 and m.supports_structured


async def test_complete_sends_auth_and_parses():
    p, seen = _provider(lambda r: httpx.Response(200, json=COMPLETION))
    r = await p.complete(_req())
    assert r.status == "ok" and r.latency_ms is not None
    [req] = seen
    assert req.url.path.endswith("/chat/completions")
    assert req.headers["Authorization"] == f"Bearer {FAKE_KEY}"
    assert json.loads(req.content)["provider"]["allow_fallbacks"] is False


async def test_complete_http_errors():
    p, _ = _provider(lambda r: httpx.Response(429, json={"error": {"message": "slow"}}, headers={"Retry-After": "3"}))
    r = await p.complete(_req())
    assert r.status == "error" and r.error.cls == "rate_limited" and r.error.retry_after_s == 3
    p, _ = _provider(lambda r: httpx.Response(502, json={"error": {"message": "bad gw"}},
                                              headers={"X-Generation-Id": "gen-x"}))
    r = await p.complete(_req())
    assert r.status == "uncertain" and r.generation_id == "gen-x"
    p, _ = _provider(lambda r: httpx.Response(200, text="não é json"))
    assert (await p.complete(_req())).status == "uncertain"


async def test_complete_transport_errors():
    def connect_fail(r):
        raise httpx.ConnectError("recusado")

    def read_timeout(r):
        raise httpx.ReadTimeout("lento")

    p, _ = _provider(connect_fail)
    r = await p.complete(_req())
    assert r.status == "error" and r.error.cls == "pre_generation"
    p, _ = _provider(read_timeout)
    assert (await p.complete(_req())).status == "uncertain"


async def test_catalog_lookup_cost_and_key():
    def h(r: httpx.Request) -> httpx.Response:
        if r.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "v/m", "pricing": {"prompt": "0"}}]})
        if r.url.path.endswith("/generation"):
            if r.url.params["id"] == "missing":
                return httpx.Response(404)
            return httpx.Response(200, json={"data": {"total_cost": 0.5, "model": "v/m", "provider_name": "H",
                                                      "finish_reason": "stop", "cancelled": False}})
        if r.url.path.endswith("/key"):
            return httpx.Response(200, json={"data": {"limit": 10, "limit_remaining": 7.5, "usage": 2.5}})
        return httpx.Response(404)

    p, _ = _provider(h)
    [m] = await p.catalog()
    assert m.model_id == "v/m"
    c = await p.lookup_cost("gen-1")
    assert c.total_cost_usd == Decimal("0.5") and c.served_provider == "H"
    assert await p.lookup_cost("missing") is None
    k = await p.key_status()
    assert k.limit_remaining_usd == Decimal("7.5")


async def test_no_key_refuses_to_call(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr("cardfactory.providers.openrouter.get_api_key", lambda: None)
    p = OpenRouterProvider(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=COMPLETION)))
    with pytest.raises(RuntimeError):
        await p.complete(_req())


def test_auth_via_proxy_sends_no_key(monkeypatch):
    from cardfactory.providers.openrouter import OpenRouterProvider

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_AUTH_VIA_PROXY", "1")
    c = OpenRouterProvider(api_key=None)
    c._key = None
    assert "Authorization" not in c._client(5).headers
    monkeypatch.delenv("OPENROUTER_AUTH_VIA_PROXY")
    with pytest.raises(RuntimeError):
        c._client(5)


async def test_grammar_too_large_retries_with_schema_in_prompt(monkeypatch):
    import httpx as hx

    from cardfactory.providers.base import LLMRequest
    from cardfactory.providers.openrouter import OpenRouterProvider

    seen = []

    def handler(request):
        body = __import__("json").loads(request.content)
        grammar = "response_format" in body
        seen.append(grammar)
        if grammar:
            return hx.Response(400, json={"error": {"code": 400, "message": "Provider returned error", "metadata": {
                "raw": "The compiled grammar is too large, which would cause performance issues."}}})
        return hx.Response(200, json={"id": "gen-1", "model": "m", "choices": [
            {"finish_reason": "stop", "message": {"content": "{}"}}], "usage": {}})

    p = OpenRouterProvider(api_key="k", transport=hx.MockTransport(handler))
    r = await p.complete(LLMRequest(model_id="m", messages=[], max_output_tokens=10, idempotency_key="k",
                                    response_schema={"type": "object"}, schema_name="s"))
    assert seen == [True, False] and r.status == "ok"


async def test_no_structured_endpoint_retries_with_schema_in_prompt():
    import json as js

    import httpx as hx

    from cardfactory.providers.base import LLMRequest
    from cardfactory.providers.openrouter import OpenRouterProvider

    seen = []

    def handler(request):
        body = js.loads(request.content)
        seen.append(("response_format" in body, "JSON Schema" in body["messages"][-1]["content"]))
        if "response_format" in body:
            return hx.Response(404, json={"error": {"code": 404, "message": "No endpoints found that can handle "
                                                                            "the requested parameters."}})
        return hx.Response(200, json={"id": "gen-1", "model": "m", "choices": [
            {"finish_reason": "stop", "message": {"content": "{}"}}], "usage": {}})

    p = OpenRouterProvider(api_key="k", transport=hx.MockTransport(handler))
    r = await p.complete(LLMRequest(model_id="m", messages=[], max_output_tokens=10, idempotency_key="k",
                                    response_schema={"type": "object"}, schema_name="s"))
    assert seen == [(True, True), (False, True)] and r.status == "ok"
