import threading
from decimal import Decimal

import pytest

from cardfactory.db.models import LLMCall
from cardfactory.finance.budget import (
    BudgetExceededError,
    SpendNotAuthorizedError,
    UnsafeEstimateError,
)
from cardfactory.finance.estimator import CostEstimate


def _call(i: int) -> LLMCall:
    return LLMCall(provider="openrouter", requested_model="x/y", idempotency_key=f"k{i}")


def test_budget_seed_100(finance, budget):
    ids = finance.seed_experiment(budget)
    total = sum(finance.status(ids[k]).limit_brl for k in ids if k != "experiment")
    assert total == Decimal("100")
    assert finance.status(ids["experiment"]).limit_brl == Decimal("100")


def test_real_provider_requires_authorization(db, finance, budget):
    with pytest.raises(SpendNotAuthorizedError), db.write() as s:
        finance.reserve(s, _call(1), [budget], CostEstimate(Decimal("0.01"), True), paid_provider=True)


def test_reservation_respects_invariant_and_hierarchy(db, finance, budget):
    child = finance.create_budget("STAGE", "geracao", "10", parent_id=budget)
    finance.authorize_spend(budget, "100", "Tassiane")
    # 1 USD = 5 × 1,10 = R$ 5,50
    with db.write() as s:
        finance.reserve(s, _call(1), [child], CostEstimate(Decimal("1"), True), paid_provider=True)
    st = finance.status(child)
    assert st.reserved_brl == Decimal("5.5") and st.available_brl == Decimal("4.5")
    assert finance.status(budget).reserved_brl == Decimal("5.5")  # ancestral também reservado
    with pytest.raises(BudgetExceededError), db.write() as s:
        finance.reserve(s, _call(2), [child], CostEstimate(Decimal("1"), True), paid_provider=True)


def test_unsafe_estimate_blocks(db, finance, budget):
    with pytest.raises(UnsafeEstimateError), db.write() as s:
        finance.reserve(s, _call(1), [budget], CostEstimate(Decimal(0), False, reasons=["x"]), paid_provider=False)


def test_no_fx_blocks_paid(db, finance):
    b = finance.create_budget("PROJECT", "sem-fx", "10")
    finance.authorize_spend(b, "10", "Tassiane")
    with pytest.raises(UnsafeEstimateError), db.write() as s:
        finance.reserve(s, _call(1), [b], CostEstimate(Decimal("0.1"), True), paid_provider=True)


def test_authorization_amount_caps_spending(db, finance, budget):
    finance.authorize_spend(budget, "6", "Tassiane")
    with db.write() as s:
        finance.reserve(s, _call(1), [budget], CostEstimate(Decimal("1"), True), paid_provider=True)
    with pytest.raises(SpendNotAuthorizedError), db.write() as s:
        finance.reserve(s, _call(2), [budget], CostEstimate(Decimal("0.1"), True), paid_provider=True)


def test_revoked_authorization(db, finance, budget):
    a = finance.authorize_spend(budget, "50", "Tassiane")
    finance.revoke_authorization(a)
    with pytest.raises(SpendNotAuthorizedError), db.write() as s:
        finance.reserve(s, _call(1), [budget], CostEstimate(Decimal("0.1"), True), paid_provider=True)


def test_confirm_replaces_reservation_with_actual(db, finance, budget):
    finance.authorize_spend(budget, "100", "Tassiane")
    with db.write() as s:
        c = _call(1)
        finance.reserve(s, c, [budget], CostEstimate(Decimal("2"), True), paid_provider=True)
        cid = c.id
    with db.write() as s:
        finance.confirm(s, s.get(LLMCall, cid), Decimal("0.5"))
    st = finance.status(budget)
    assert st.reserved_brl == 0 and st.confirmed_brl == Decimal("2.75")
    with db.write() as s:  # idempotente
        finance.confirm(s, s.get(LLMCall, cid), Decimal("0.5"))
    assert finance.status(budget).confirmed_brl == Decimal("2.75")


def test_release_unbilled(db, finance, budget):
    finance.authorize_spend(budget, "100", "Tassiane")
    with db.write() as s:
        c = _call(1)
        finance.reserve(s, c, [budget], CostEstimate(Decimal("2"), True), paid_provider=True)
        finance.release_unbilled(s, c, "400")
    st = finance.status(budget)
    assert st.reserved_brl == 0 and st.confirmed_brl == 0


def test_budget_reservation_atomic(db, finance, budget):
    """FIN-002: N threads disputam um saldo que comporta exatamente 10 reservas."""
    b = finance.create_budget("STAGE", "disputa", "55", parent_id=budget)  # 10 × R$5,50
    finance.authorize_spend(budget, "100", "Tassiane")
    ok, fail = [], []

    def worker(i):
        try:
            with db.write() as s:
                finance.reserve(s, _call(100 + i), [b], CostEstimate(Decimal("1"), True), paid_provider=True)
            ok.append(i)
        except BudgetExceededError:
            fail.append(i)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(25)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(ok) == 10 and len(fail) == 15
    st = finance.status(b)
    assert st.reserved_brl == Decimal("55") and st.available_brl == 0
