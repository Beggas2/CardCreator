"""Gateway com provedor simulado: nenhum teste acessa a rede ou gasta créditos."""

from decimal import Decimal

import pytest
from sqlalchemy import select

from cardfactory.db.models import BudgetLedger, LLMCall
from cardfactory.finance.budget import SpendNotAuthorizedError
from cardfactory.providers.base import LLMRequest, RoutingPolicy
from cardfactory.providers.gateway import (
    CallFailedError,
    LLMGateway,
    ModelMismatchError,
    UncertainCallError,
    backoff_delay,
)
from cardfactory.providers.mock import MockProvider, Scripted

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"],
          "additionalProperties": True}


def _req(key: str = "k1", **kw) -> LLMRequest:
    return LLMRequest(model_id="mock/creator-a", messages=[{"role": "user", "content": "oi"}],
                      max_output_tokens=200, idempotency_key=key, response_schema=SCHEMA, **kw)


async def _nosleep(_s: float) -> None:
    return None


@pytest.fixture
def mock() -> MockProvider:
    return MockProvider()


@pytest.fixture
def gw(db, finance, mock) -> LLMGateway:
    return LLMGateway(db, finance, mock, sleep=_nosleep)


def _calls(db) -> list[LLMCall]:
    with db.session() as s:
        return list(s.execute(select(LLMCall)).scalars())


async def test_ok_validates_schema(gw, budget, db):
    r = await gw.call(_req(), budget_ids=[budget])
    assert r.status == "ok" and r.parsed == {"ok": True, "limitations": []}
    [c] = _calls(db)
    assert c.state == "SUCCEEDED" and c.cost_usd == "0.00000000"
    assert finance_reserved_zero(db, budget)


def finance_reserved_zero(db, budget_id) -> bool:
    from cardfactory.finance.budget import FinanceService
    st = FinanceService(db).status(budget_id)
    return st.reserved_brl == 0


async def test_invalid_json_gets_one_repair(gw, mock, budget, db):
    mock.enqueue(Scripted("invalid_json"), Scripted("ok"))
    r = await gw.call(_req(), budget_ids=[budget])
    assert r.status == "ok"
    states = sorted(c.state for c in _calls(db))
    assert states == ["INVALID_OUTPUT", "SUCCEEDED"]
    # O reparo inclui a resposta anterior e o erro de validação.
    assert len(mock.calls[1].messages) == 3
    assert "schema" in mock.calls[1].messages[-1]["content"]


async def test_invalid_twice_fails_without_more_spend(gw, mock, budget, db):
    mock.enqueue(Scripted("invalid_json"), Scripted("invalid_json"))
    with pytest.raises(CallFailedError) as e:
        await gw.call(_req(), budget_ids=[budget])
    assert not e.value.retryable
    assert len(mock.calls) == 2


async def test_repair_works_even_without_unbilled_retries(db, finance, mock, budget):
    gw = LLMGateway(db, finance, mock, max_unbilled_retries=0, sleep=_nosleep)
    mock.enqueue(Scripted("invalid_json"), Scripted("ok"))
    assert (await gw.call(_req(), budget_ids=[budget])).status == "ok"


async def test_truncated_is_reported(gw, mock, budget):
    mock.enqueue(Scripted("truncated"))
    r = await gw.call(_req(), budget_ids=[budget])
    assert r.status == "truncated" and r.parsed is None


async def test_rate_limited_retries_with_backoff(db, finance, mock, budget):
    slept: list[float] = []

    async def sleep(s):
        slept.append(s)

    gw = LLMGateway(db, finance, mock, sleep=sleep)
    mock.enqueue(Scripted("rate_limited", retry_after_s=2), Scripted("server_error"), Scripted("ok"))
    r = await gw.call(_req(), budget_ids=[budget])
    assert r.status == "ok"
    assert len(slept) == 2 and 2 <= slept[0] <= 2.5
    states = [c.state for c in _calls(db)]
    assert states.count("FAILED_UNBILLED") == 2
    keys = {c.idempotency_key for c in _calls(db)}
    assert keys == {"k1", "k1#r1", "k1#r2"}


async def test_rate_limited_gives_up(db, finance, mock, budget):
    gw = LLMGateway(db, finance, mock, max_unbilled_retries=2, sleep=_nosleep)
    mock.enqueue(*[Scripted("rate_limited")] * 5)
    with pytest.raises(CallFailedError) as e:
        await gw.call(_req(), budget_ids=[budget])
    assert e.value.retryable
    assert len(mock.calls) == 3
    # Depois de falhas sem cobrança, a mesma chave lógica pode ser tentada de novo.
    mock.script.clear()
    assert (await gw.call(_req(), budget_ids=[budget])).status == "ok"
    assert len(mock.calls) == 4


async def test_permanent_error_not_retried(gw, mock, budget):
    mock.enqueue(Scripted("permanent"))
    with pytest.raises(CallFailedError) as e:
        await gw.call(_req(), budget_ids=[budget])
    assert not e.value.retryable and len(mock.calls) == 1


async def test_timeout_is_uncertain_and_never_repeated(gw, mock, budget, db, finance):
    mock.enqueue(Scripted("timeout"))
    with pytest.raises(UncertainCallError):
        await gw.call(_req(), budget_ids=[budget])
    [c] = _calls(db)
    assert c.state == "UNCERTAIN" and c.cost_usd is None
    # Mesma chave: não reenvia (PRV-007).
    with pytest.raises(UncertainCallError):
        await gw.call(_req(), budget_ids=[budget])
    assert len(mock.calls) == 1
    assert [p["id"] for p in finance.pending_reconciliation()] == [c.id]


async def test_reconcile_confirms_uncertain(gw, mock, budget, db, finance):
    mock.enqueue(Scripted("timeout"))
    with pytest.raises(UncertainCallError):
        await gw.call(_req(), budget_ids=[budget])
    # O simulado não devolve generation_id em timeout: nada a reconciliar automaticamente.
    assert await gw.reconcile() == {"reconciled": 0, "pending": 1}
    with db.write() as s:
        s.execute(select(LLMCall)).scalar_one().generation_id = "mock-gen-1"
    assert await gw.reconcile() == {"reconciled": 1, "pending": 0}
    [c] = _calls(db)
    assert c.state == "RECONCILED" and c.cost_usd is not None
    assert finance.status(budget).reserved_brl == 0


async def test_model_swap_is_blocked(gw, mock, budget, db):
    mock.enqueue(Scripted("model_swap", served_model="mock/other-model"))
    with pytest.raises(ModelMismatchError):
        await gw.call(_req(), budget_ids=[budget])
    [c] = _calls(db)
    assert c.state == "FAILED_BILLED" and c.model_mismatch


async def test_model_swap_allowed_when_fallbacks_on_and_not_critical(gw, mock, budget, db):
    mock.enqueue(Scripted("model_swap", served_model="mock/other-model"))
    r = await gw.call(_req(routing=RoutingPolicy(allow_fallbacks=True)), budget_ids=[budget])
    assert r.status == "ok"
    assert _calls(db)[0].model_mismatch


async def test_model_swap_blocked_when_critical_even_with_fallbacks(gw, mock, budget):
    mock.enqueue(Scripted("model_swap", served_model="mock/other-model"))
    with pytest.raises(ModelMismatchError):
        await gw.call(_req(routing=RoutingPolicy(allow_fallbacks=True)), budget_ids=[budget], critical=True)


async def test_dated_slug_is_same_model(gw, mock, budget, db):
    mock.enqueue(Scripted("ok", served_model="mock/creator-a-20260101"))
    assert (await gw.call(_req(), budget_ids=[budget])).status == "ok"
    assert not _calls(db)[0].model_mismatch


async def test_idempotent_replay_does_not_call_again(gw, mock, budget):
    r1 = await gw.call(_req(), budget_ids=[budget])
    r2 = await gw.call(_req(), budget_ids=[budget])
    assert r1.call_id == r2.call_id and r2.parsed == r1.parsed
    assert len(mock.calls) == 1


async def test_replay_after_repair_returns_repaired_output(gw, mock, budget):
    mock.enqueue(Scripted("invalid_json"), Scripted("ok", payload={"ok": False}))
    await gw.call(_req(), budget_ids=[budget])
    r = await gw.call(_req(), budget_ids=[budget])
    assert r.parsed == {"ok": False} and len(mock.calls) == 2


async def test_paid_provider_requires_authorization(db, finance, budget):
    paid = MockProvider(name="mockpaid", paid=True)
    gw = LLMGateway(db, finance, paid, sleep=_nosleep)
    await gw.sync_catalog()
    # Catálogo do simulado tem preço 0, mas o provedor é pago: exige autorização expressa.
    with pytest.raises(SpendNotAuthorizedError):
        await gw.call(_req(), budget_ids=[budget])
    assert paid.calls == [] and _calls(db) == []
    finance.authorize_spend(budget, "1", granted_by="teste")
    assert (await gw.call(_req("k2"), budget_ids=[budget])).status == "ok"
    assert len(paid.calls) == 1


async def test_paid_provider_without_pricing_is_blocked(db, finance, budget):
    from cardfactory.finance.budget import UnsafeEstimateError
    paid = MockProvider(name="mockpaid", paid=True)
    gw = LLMGateway(db, finance, paid, sleep=_nosleep)
    finance.authorize_spend(budget, "1", granted_by="teste")
    with pytest.raises(UnsafeEstimateError):
        await gw.call(_req(), budget_ids=[budget])
    assert paid.calls == []


async def test_cost_confirmed_in_ledger(db, finance, budget):
    paid = MockProvider(name="mockpaid", paid=True)
    gw = LLMGateway(db, finance, paid, sleep=_nosleep)
    await gw.sync_catalog()
    finance.authorize_spend(budget, "5", granted_by="teste")
    paid.enqueue(Scripted("ok", cost_usd="0.002"))
    await gw.call(_req(), budget_ids=[budget])
    st = finance.status(budget)
    assert st.reserved_brl == 0
    assert st.confirmed_brl == Decimal("0.002") * Decimal("5.00") * Decimal("1.10")
    with db.session() as s:
        kinds = sorted(x.kind for x in s.execute(select(BudgetLedger)).scalars())
    assert kinds == ["CONFIRM", "RELEASE", "RESERVE"]


def test_backoff_bounds():
    for a in range(8):
        assert 0 <= backoff_delay(a, base=1, cap=10) <= 10
    assert 30 <= backoff_delay(0, retry_after=30) <= 30.5
    assert backoff_delay(0, cap=60, retry_after=999) <= 60.5
