import asyncio

import pytest

from cardfactory.db.models import Production, Project, Task
from cardfactory.orchestrator.engine import (
    AwaitingHuman,
    ContractViolation,
    NotImplementedStage,
    Orchestrator,
    OrchestratorError,
    TaskSpec,
)
from cardfactory.providers.base import LLMRequest
from cardfactory.providers.gateway import LLMGateway
from cardfactory.providers.mock import MockProvider, Scripted


@pytest.fixture
def production(db) -> str:
    with db.write() as s:
        p = Project(name="p")
        s.add(p)
        s.flush()
        prd = Production(project_id=p.id, mode="FULL_CREATION", theme="t")
        s.add(prd)
        s.flush()
        return prd.id


def _states(db, run_id) -> dict[str, str]:
    from sqlalchemy import select
    with db.session() as s:
        return {t.idempotency_key.split(":", 1)[1]: t.state
                for t in s.execute(select(Task).where(Task.run_id == run_id)).scalars()}


def _orch(db, handlers, **kw) -> Orchestrator:
    return Orchestrator(db, handlers, backoff_base=0.0, idle_poll_s=0.0, **kw)


async def test_dependencies_run_in_order(db, production):
    order: list[str] = []

    async def h(ctx):
        order.append(ctx.input["n"])
        return {"n": ctx.input["n"], "deps": ctx.dep_outputs()}

    o = _orch(db, {"x": h})
    run = o.create_run(production, "FULL_CREATION", [
        TaskSpec("c", "S", "x", {"n": "c"}, deps=["a", "b"]),
        TaskSpec("a", "S", "x", {"n": "a"}),
        TaskSpec("b", "S", "x", {"n": "b"}, deps=["a"]),
    ])
    o.start(run)
    assert await o.run_until_idle(run) == "COMPLETED"
    assert order == ["a", "b", "c"]


def test_cycle_rejected(db, production):
    o = _orch(db, {})
    with pytest.raises(OrchestratorError):
        o.create_run(production, "M", [TaskSpec("a", "S", "x", deps=["b"]), TaskSpec("b", "S", "x", deps=["a"])])


def test_add_tasks_idempotent(db, production):
    o = _orch(db, {})
    run = o.create_run(production, "M", [TaskSpec("a", "S", "x")])
    assert o.add_tasks(run, [TaskSpec("a", "S", "x")]) == o.add_tasks(run, [TaskSpec("a", "S", "x")])
    assert len(_states(db, run)) == 1


async def test_retry_then_fail(db, production):
    calls = 0

    async def flaky(ctx):
        nonlocal calls
        calls += 1
        raise RuntimeError("falhou")

    o = _orch(db, {"x": flaky})
    run = o.create_run(production, "M", [TaskSpec("a", "S", "x", max_attempts=3)])
    o.start(run)
    assert await o.run_until_idle(run) == "FAILED"
    assert calls == 3 and _states(db, run) == {"a": "FAILED"}


async def test_not_implemented_is_terminal(db, production):
    async def ni(ctx):
        raise NotImplementedStage("NOT_IMPLEMENTED: modo X")

    o = _orch(db, {"x": ni})
    run = o.create_run(production, "M", [TaskSpec("a", "S", "x"), TaskSpec("b", "S", "missing_handler")])
    o.start(run)
    assert await o.run_until_idle(run) == "FAILED"
    assert _states(db, run) == {"a": "FAILED", "b": "FAILED"}


async def test_pause_and_resume(db, production):
    o_ref: list[Orchestrator] = []
    seen: list[str] = []

    async def h(ctx):
        seen.append(ctx.input["n"])
        if ctx.input["n"] == "a":
            o_ref[0].pause(ctx.run_id)
        return {}

    o = _orch(db, {"x": h})
    o_ref.append(o)
    run = o.create_run(production, "M", [TaskSpec("a", "S", "x", {"n": "a"}),
                                         TaskSpec("b", "S", "x", {"n": "b"}, deps=["a"])])
    o.start(run)
    assert await o.run_until_idle(run, concurrency=1) == "PAUSED"
    assert seen == ["a"] and _states(db, run) == {"a": "SUCCEEDED", "b": "PENDING"}
    o.resume(run)
    assert await o.run_until_idle(run) == "COMPLETED" and seen == ["a", "b"]


async def test_cancel(db, production):
    o = _orch(db, {})
    run = o.create_run(production, "M", [TaskSpec("a", "S", "x"), TaskSpec("b", "S", "x", deps=["a"])])
    o.start(run)
    o.cancel(run)
    assert _states(db, run) == {"a": "CANCELLED", "b": "CANCELLED"}
    assert await o.run_until_idle(run) == "CANCELLED"


async def test_recover_orphaned_running(db, production):
    async def h(ctx):
        return {"ok": True}

    o1 = _orch(db, {"x": h}, worker_id="w1")
    run = o1.create_run(production, "M", [TaskSpec("a", "S", "x")])
    o1.start(run)
    [t] = o1.claim(run, 1)  # simula processo morto depois de reivindicar
    o2 = _orch(db, {"x": h}, worker_id="w2")
    assert o2.recover() == 0  # lease ainda válido
    assert o2.recover(all_running=True) == 1
    assert await o2.run_until_idle(run) == "COMPLETED"
    # O resultado do processo antigo, se chegasse agora, seria descartado.
    assert o1._finish(t.id, "SUCCEEDED", output={}) == "LOST"


async def test_awaiting_human_blocks_completion(db, production):
    async def h(ctx):
        raise AwaitingHuman("precisa de revisão")

    o = _orch(db, {"x": h})
    run = o.create_run(production, "M", [TaskSpec("a", "S", "x"), TaskSpec("opt", "S", "ok", required=False)])
    o.start(run)
    assert await o.run_until_idle(run) == "PAUSED"
    o.skip(next(iter(_task_ids(db, run, "AWAITING_HUMAN"))), "revisado manualmente")
    o.resume(run)
    assert await o.run_until_idle(run) == "COMPLETED"


def _task_ids(db, run, state):
    from sqlalchemy import select
    with db.session() as s:
        return [t.id for t in s.execute(select(Task).where(Task.run_id == run, Task.state == state)).scalars()]


async def test_deck_not_done_with_pending(db, production):
    """ORQ-005: a execução não conclui com tarefa obrigatória bloqueada por dependência."""
    async def fail(ctx):
        raise NotImplementedStage("x")

    async def ok(ctx):
        return {}

    o = _orch(db, {"f": fail, "ok": ok})
    run = o.create_run(production, "M", [TaskSpec("a", "S", "f", required=False), TaskSpec("b", "S", "ok", deps=["a"])])
    o.start(run)
    assert await o.run_until_idle(run) == "PAUSED"
    assert _states(db, run)["b"] == "PENDING"


async def test_uncertain_call_marks_task_and_reprocess_uses_new_keys(db, finance, budget, production):
    mock = MockProvider()

    async def nosleep(_):
        return None

    gw = LLMGateway(db, finance, mock, sleep=nosleep)

    async def gen(ctx):
        r = await gw.call(LLMRequest("mock/creator-a", [{"role": "user", "content": "x"}], 100,
                                     ctx.call_key("gen")), budget_ids=[budget], task_id=ctx.task_id)
        return {"text": r.text}

    o = _orch(db, {"gen": gen})
    run = o.create_run(production, "M", [TaskSpec("a", "GENERATION", "gen"), TaskSpec("b", "S", "gen", deps=["a"])])
    o.start(run)
    mock.enqueue(Scripted("timeout"))
    assert await o.run_until_idle(run) == "PAUSED"
    [unc] = _task_ids(db, run, "UNCERTAIN")
    # Recuperar não reexecuta UNCERTAIN; recolocar a mesma tarefa repetiria a mesma chave e o gateway bloquearia.
    assert o.recover(all_running=True) == 0
    new = o.reprocess(unc, reason="decisão humana após conferir custo")
    o.resume(run)
    assert await o.run_until_idle(run) == "COMPLETED"
    assert len(mock.calls) == 3
    assert new in _task_ids(db, run, "SUCCEEDED")


async def test_budget_exhaustion_pauses_run_without_consuming_attempt(db, finance, production):
    finance.set_fx_rate("5.00")
    tiny = finance.create_budget("PROJECT", "mini", "0.00000001")
    paid = MockProvider(name="mp", paid=True)

    async def nosleep(_):
        return None

    gw = LLMGateway(db, finance, paid, sleep=nosleep)
    await gw.sync_catalog()
    finance.authorize_spend(tiny, "0.00000001", granted_by="teste")

    async def gen(ctx):
        await gw.call(LLMRequest("mock/creator-a", [{"role": "user", "content": "x" * 100}], 1000, ctx.call_key("g")),
                      budget_ids=[tiny], task_id=ctx.task_id)
        return {}

    o = _orch(db, {"gen": gen})
    run = o.create_run(production, "M", [TaskSpec("a", "S", "gen")])
    o.start(run)
    # Preço do catálogo simulado é zero: a chamada cabe. Forçamos um orçamento esgotado por ajuste manual.
    finance.manual_adjust(tiny, "1", author="teste", note="consumo externo")
    assert await o.run_until_idle(run) == "PAUSED_BUDGET"
    assert paid.calls == []
    from sqlalchemy import select
    with db.session() as s:
        t = s.execute(select(Task).where(Task.run_id == run)).scalar_one()
        assert t.state == "READY" and t.attempts == 0


async def test_concurrency_limit(db, production):
    active = peak = 0

    async def h(ctx):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return {}

    o = _orch(db, {"x": h})
    run = o.create_run(production, "M", [TaskSpec(f"t{i}", "S", "x") for i in range(8)])
    o.start(run)
    assert await o.run_until_idle(run, concurrency=3) == "COMPLETED"
    assert peak == 3


async def test_dependent_sees_output_of_reprocessed_task(db, production):
    calls = {"a": 0}

    async def a(ctx):
        calls["a"] += 1
        if calls["a"] == 1:
            raise ContractViolation("falha na primeira vez")
        return {"v": 42}

    async def b(ctx):
        return {"got": (ctx.dep_outputs().get("a") or {}).get("v")}

    o = _orch(db, {"a": a, "b": b})
    run = o.create_run(production, "FULL_CREATION", [TaskSpec("a", "A", "a", {}), TaskSpec("b", "B", "b", {},
                                                                                          deps=["a"])])
    o.start(run)
    await o.run_until_idle(run)
    from sqlalchemy import select
    with db.session() as s:
        failed = s.execute(select(Task).where(Task.run_id == run, Task.stage == "A")).scalar_one()
    o.reprocess(failed.id)
    o.resume(run)
    assert await o.run_until_idle(run) == "COMPLETED"
    with db.session() as s:
        out = s.execute(select(Task).where(Task.run_id == run, Task.stage == "B")).scalar_one().output
    assert out == {"got": 42}
