"""ORQ-004: matar o processo com SIGKILL no meio da execução não perde tarefas concluídas."""

import asyncio
import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest
from sqlalchemy import select

from cardfactory.db import Database, make_engine
from cardfactory.db.migrate import upgrade
from cardfactory.db.models import Production, Project, Task
from cardfactory.orchestrator.engine import Orchestrator, TaskSpec

CHILD = textwrap.dedent("""
    import asyncio, sys, time
    from cardfactory.db import Database, make_engine
    from cardfactory.orchestrator.engine import Orchestrator
    db = Database(make_engine(sys.argv[1]))
    async def fast(ctx):
        return {"done": ctx.input["n"]}
    async def slow(ctx):
        ctx.save_checkpoint({"step": 1})
        print("SLOW_STARTED", flush=True)
        await asyncio.sleep(60)
        return {}
    o = Orchestrator(db, {"fast": fast, "slow": slow}, worker_id="child", lease_s=600)
    asyncio.run(o.run_until_idle(sys.argv[2], concurrency=1))
""")


@pytest.mark.skipif(not hasattr(signal, "SIGKILL"), reason="SIGKILL indisponível")
def test_crash_recovery(tmp_path: Path):
    path = tmp_path / "crash.sqlite"
    upgrade(path)
    db = Database(make_engine(path))
    with db.write() as s:
        p = Project(name="p")
        s.add(p)
        s.flush()
        prd = Production(project_id=p.id, mode="M", theme="t")
        s.add(prd)
        s.flush()
        prd_id = prd.id
    o = Orchestrator(db, {}, worker_id="parent")
    run = o.create_run(prd_id, "M", [TaskSpec("a", "S", "fast", {"n": "a"}, priority=1),
                                     TaskSpec("b", "S", "slow", deps=["a"])])
    o.start(run)

    script = tmp_path / "child.py"
    script.write_text(CHILD, encoding="utf-8")
    proc = subprocess.Popen([sys.executable, str(script), str(path), run], stdout=subprocess.PIPE, text=True,
                            env={**os.environ, "PYTHONUNBUFFERED": "1"})
    try:
        deadline = time.time() + 30
        line = ""
        while time.time() < deadline and "SLOW_STARTED" not in line:
            line = proc.stdout.readline()
        assert "SLOW_STARTED" in line
        proc.send_signal(signal.SIGKILL)
        proc.wait(10)
    finally:
        if proc.poll() is None:
            proc.kill()

    with db.session() as s:
        tasks = {t.idempotency_key.split(":")[1]: t for t in s.execute(select(Task)).scalars()}
    assert tasks["a"].state == "SUCCEEDED" and tasks["a"].output == {"done": "a"}
    assert tasks["b"].state == "RUNNING" and tasks["b"].checkpoint == {"step": 1}

    ran: list[str] = []

    async def fast(ctx):
        ran.append("a")
        return {}

    async def slow(ctx):
        ran.append(f"b:{ctx.checkpoint.get('step')}")
        return {"resumed": True}

    o2 = Orchestrator(db, {"fast": fast, "slow": slow}, worker_id="restart")
    assert o2.recover(all_running=True) == 1
    assert asyncio.run(o2.run_until_idle(run)) == "COMPLETED"
    assert ran == ["b:1"]  # "a" não foi reexecutada; "b" retomou do checkpoint
