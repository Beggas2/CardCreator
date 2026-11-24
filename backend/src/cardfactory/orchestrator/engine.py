"""Orquestrador persistente (ORQ-001..005). Ver PIPELINE.md.

- Estado vive no SQLite: encerrar o app não perde tarefas concluídas (commit por tarefa).
- Tarefas são reivindicadas com lease; leases vencidos voltam a READY na recuperação.
- Reexecutar uma tarefa é seguro porque o gateway deduplica chamadas pela chave
  idempotente derivada do id da tarefa; uma chamada que pode ter sido cobrada vira UNCERTAIN.
- `UNCERTAIN` nunca é reexecutada automaticamente.
- Falta de orçamento ou de autorização pausa a execução (PAUSED_BUDGET) sem consumir tentativa.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from cardfactory.db import Database
from cardfactory.db.models import Run, Task, TaskDependency
from cardfactory.finance.budget import BudgetExceededError, SpendNotAuthorizedError, UnsafeEstimateError
from cardfactory.ids import new_id
from cardfactory.providers.gateway import CallFailedError, ModelMismatchError, UncertainCallError, backoff_delay

log = logging.getLogger(__name__)

DONE = ("SUCCEEDED", "SKIPPED_REUSED")
BLOCKING = ("FAILED", "UNCERTAIN", "AWAITING_HUMAN", "CANCELLED")
ACTIVE_RUN = ("RUNNING",)


class AwaitingHuman(Exception):  # noqa: N818 - sinal, não erro
    """Handler precisa de decisão humana para seguir."""


class NotImplementedStage(Exception):  # noqa: N818
    """Etapa ou modo declarado mas não implementado: falha explícita, nunca resultado fictício."""


class ContractViolation(Exception):  # noqa: N818
    """Saída de IA válida no schema mas que viola regra do contrato; repetir daria o mesmo resultado."""


class OrchestratorError(Exception):
    pass


@dataclass
class TaskSpec:
    key: str
    stage: str
    kind: str
    input: dict[str, Any] = field(default_factory=dict)
    deps: list[str] = field(default_factory=list)  # chaves de outras TaskSpec da mesma execução
    required: bool = True
    priority: int = 100
    max_attempts: int = 3


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


class TaskContext:
    def __init__(self, orch: Orchestrator, task: Task):
        self._orch = orch
        self.task_id = task.id
        self.run_id = task.run_id
        self.stage = task.stage
        self.kind = task.kind
        self.input: dict[str, Any] = dict(task.input or {})
        self.checkpoint: dict[str, Any] = dict(task.checkpoint or {})
        self.attempt = task.attempts

    def call_key(self, name: str) -> str:
        """Chave idempotente estável para uma chamada de IA desta tarefa."""
        return f"{self.task_id}:{name}"

    def save_checkpoint(self, data: dict[str, Any]) -> None:
        self.checkpoint = dict(data)
        with self._orch.db.write() as s:
            s.get(Task, self.task_id).checkpoint = self.checkpoint

    def dep_outputs(self) -> dict[str, Any]:
        """Saídas das dependências, por chave lógica."""
        with self._orch.db.session() as s:
            rows = s.execute(select(Task).join(TaskDependency, TaskDependency.depends_on_task_id == Task.id)
                             .where(TaskDependency.task_id == self.task_id)).scalars()
            # Tarefa reprocessada tem chave "<run>:<ETAPA>#n"; a dependente continua pedindo pela etapa.
            return {t.idempotency_key.split(":", 1)[1].split("#", 1)[0]: t.output for t in rows}

    def spawn(self, specs: list[TaskSpec]) -> list[str]:
        """Expande o grafo dinamicamente (ex.: lotes de geração)."""
        return self._orch.add_tasks(self.run_id, specs)


Handler = Callable[[TaskContext], Awaitable[dict[str, Any] | None]]


class Orchestrator:
    def __init__(self, db: Database, handlers: dict[str, Handler], *, worker_id: str | None = None,
                 lease_s: float = 120.0, backoff_base: float = 2.0, idle_poll_s: float = 0.5):
        self.db = db
        self.handlers = handlers
        self.worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}:{new_id()[-6:]}"
        self.lease_s = lease_s
        self.backoff_base = backoff_base
        self.idle_poll_s = idle_poll_s

    # ------------------------------------------------------------ criação
    def create_run(self, production_id: str, mode: str, specs: list[TaskSpec], note: str = "") -> str:
        with self.db.write() as s:
            run = Run(production_id=production_id, mode=mode, state="PENDING", note=note)
            s.add(run)
            s.flush()
            run_id = run.id
        self.add_tasks(run_id, specs)
        return run_id

    def add_tasks(self, run_id: str, specs: list[TaskSpec]) -> list[str]:
        with self.db.write() as s:
            existing = {t.idempotency_key: t.id for t in
                        s.execute(select(Task).where(Task.run_id == run_id)).scalars()}
            ids: dict[str, str] = {}
            for sp in specs:
                ikey = f"{run_id}:{sp.key}"
                if ikey in existing:  # idempotente: adicionar de novo não duplica
                    ids[sp.key] = existing[ikey]
                    continue
                t = Task(run_id=run_id, stage=sp.stage, kind=sp.kind, input=sp.input, required=sp.required,
                         priority=sp.priority, max_attempts=sp.max_attempts, idempotency_key=ikey, state="PENDING")
                s.add(t)
                s.flush()
                ids[sp.key] = t.id
                existing[ikey] = t.id
            for sp in specs:
                for d in sp.deps:
                    dep_id = ids.get(d) or existing.get(f"{run_id}:{d}")
                    if dep_id is None:
                        raise OrchestratorError(f"dependência desconhecida: {d}")
                    if s.get(TaskDependency, (ids[sp.key], dep_id)) is None:
                        s.add(TaskDependency(task_id=ids[sp.key], depends_on_task_id=dep_id))
            self._check_acyclic(s, run_id)
            return [ids[sp.key] for sp in specs]

    @staticmethod
    def _check_acyclic(s, run_id: str) -> None:
        tasks = list(s.execute(select(Task.id).where(Task.run_id == run_id)).scalars())
        edges: dict[str, list[str]] = {t: [] for t in tasks}
        for d in s.execute(select(TaskDependency).join(Task, Task.id == TaskDependency.task_id)
                           .where(Task.run_id == run_id)).scalars():
            edges.setdefault(d.task_id, []).append(d.depends_on_task_id)
        state: dict[str, int] = {}

        def visit(n: str) -> None:
            state[n] = 1
            for m in edges.get(n, []):
                if state.get(m) == 1:
                    raise OrchestratorError("o grafo de tarefas tem ciclo")
                if m not in state:
                    visit(m)
            state[n] = 2

        for n in tasks:
            if n not in state:
                visit(n)

    # ------------------------------------------------------------ controle (ORQ-003)
    def _set_run(self, run_id: str, allowed: tuple[str, ...], new: str, note: str | None = None) -> None:
        with self.db.write() as s:
            run = s.get(Run, run_id)
            if run is None:
                raise OrchestratorError("execução inexistente")
            if run.state not in allowed:
                raise OrchestratorError(f"não é possível passar de {run.state} para {new}")
            run.state = new
            if new == "RUNNING" and run.started_at is None:
                run.started_at = _now()
            if note is not None:
                run.note = note

    def start(self, run_id: str) -> None:
        self._set_run(run_id, ("PENDING",), "RUNNING")

    def pause(self, run_id: str) -> None:
        self._set_run(run_id, ("RUNNING",), "PAUSED")

    def resume(self, run_id: str) -> None:
        self._set_run(run_id, ("PAUSED", "PAUSED_BUDGET", "FAILED"), "RUNNING", note="")

    def cancel(self, run_id: str) -> None:
        with self.db.write() as s:
            run = s.get(Run, run_id)
            if run.state in ("COMPLETED", "CANCELLED"):
                raise OrchestratorError(f"execução já está em {run.state}")
            run.state = "CANCELLED"
            run.finished_at = _now()
            for t in s.execute(select(Task).where(Task.run_id == run_id,
                                                  Task.state.in_(["PENDING", "READY"]))).scalars():
                t.state = "CANCELLED"

    def reprocess(self, task_id: str, *, reason: str = "reprocessamento") -> str:
        """Cria uma tarefa nova equivalente; dependentes passam a depender dela. A antiga fica no histórico.

        Para tarefas UNCERTAIN isto é a decisão explícita de tentar de novo; o custo da tentativa
        anterior continua pendente de reconciliação.
        """
        with self.db.write() as s:
            old = s.get(Task, task_id)
            if old is None:
                raise OrchestratorError("tarefa inexistente")
            if old.state in ("RUNNING", "PENDING", "READY"):
                raise OrchestratorError(f"tarefa em {old.state} não pode ser reprocessada")
            n = 2
            base = old.idempotency_key.split("#", 1)[0]
            while s.execute(select(Task.id).where(Task.idempotency_key == f"{base}#{n}")).first():
                n += 1
            new = Task(run_id=old.run_id, batch_id=old.batch_id, stage=old.stage, kind=old.kind,
                       input=dict(old.input or {}), required=old.required, priority=old.priority,
                       max_attempts=old.max_attempts, idempotency_key=f"{base}#{n}", state="PENDING")
            s.add(new)
            s.flush()
            for d in s.execute(select(TaskDependency).where(TaskDependency.task_id == old.id)).scalars():
                s.add(TaskDependency(task_id=new.id, depends_on_task_id=d.depends_on_task_id))
            for d in list(s.execute(select(TaskDependency).where(TaskDependency.depends_on_task_id == old.id))
                          .scalars()):
                dependent = s.get(Task, d.task_id)
                if dependent.state in ("PENDING", "READY", "CANCELLED", "FAILED"):
                    s.delete(d)
                    s.flush()
                    s.add(TaskDependency(task_id=d.task_id, depends_on_task_id=new.id))
            old.last_error = (old.last_error or "") + f" | substituída por {new.id}: {reason}"
            old.required = False  # a obrigação passa para a nova tarefa
            return new.id

    def skip(self, task_id: str, reason: str) -> None:
        """Decisão humana de reutilizar/dispensar o resultado (ex.: UNCERTAIN aceito)."""
        with self.db.write() as s:
            t = s.get(Task, task_id)
            if t.state not in BLOCKING:
                raise OrchestratorError(f"tarefa em {t.state} não pode ser dispensada")
            t.state = "SKIPPED_REUSED"
            t.last_error = (t.last_error or "") + f" | dispensada: {reason}"
            t.finished_at = _now()

    # ------------------------------------------------------------ recuperação (ORQ-004)
    def recover(self, *, all_running: bool = False) -> int:
        """Devolve a READY tarefas RUNNING com lease vencido (ou todas, na inicialização do app)."""
        now = _now()
        n = 0
        with self.db.write() as s:
            for t in s.execute(select(Task).where(Task.state == "RUNNING")).scalars():
                exp = _aware(t.lease_expires_at)
                if all_running or exp is None or exp <= now:
                    t.state = "READY"
                    t.lease_owner = None
                    t.lease_expires_at = None
                    t.last_error = (t.last_error or "") + " | recuperada após interrupção"
                    n += 1
        return n

    # ------------------------------------------------------------ agendamento
    def _promote(self, s, run_id: str) -> None:
        pending = list(s.execute(select(Task).where(Task.run_id == run_id, Task.state == "PENDING")).scalars())
        for t in pending:
            deps = list(s.execute(select(Task.state).join(TaskDependency, TaskDependency.depends_on_task_id == Task.id)
                                  .where(TaskDependency.task_id == t.id)).scalars())
            if all(d in DONE for d in deps):
                t.state = "READY"

    def claim(self, run_id: str, limit: int) -> list[Task]:
        now = _now()
        with self.db.write() as s:
            run = s.get(Run, run_id)
            if run is None or run.state not in ACTIVE_RUN:
                return []
            self._promote(s, run_id)
            ready = s.execute(select(Task).where(Task.run_id == run_id, Task.state == "READY")
                              .order_by(Task.priority, Task.created_at)).scalars()
            out = []
            for t in ready:
                nb = _aware(t.not_before)
                if nb is not None and nb > now:
                    continue
                t.state = "RUNNING"
                t.lease_owner = self.worker_id
                t.lease_expires_at = now + timedelta(seconds=self.lease_s)
                t.started_at = t.started_at or now
                t.attempts += 1
                out.append(t)
                if len(out) >= limit:
                    break
            return out

    def _renew(self, task_id: str) -> bool:
        with self.db.write() as s:
            t = s.get(Task, task_id)
            if t.state != "RUNNING" or t.lease_owner != self.worker_id:
                return False
            t.lease_expires_at = _now() + timedelta(seconds=self.lease_s)
            return True

    async def _heartbeat(self, task_id: str) -> None:
        while True:
            await asyncio.sleep(self.lease_s / 3)
            if not self._renew(task_id):
                return

    # ------------------------------------------------------------ execução de uma tarefa
    async def execute(self, task: Task) -> str:
        handler = self.handlers.get(task.kind)
        ctx = TaskContext(self, task)
        hb = asyncio.create_task(self._heartbeat(task.id))
        try:
            if handler is None:
                raise NotImplementedStage(f"NOT_IMPLEMENTED: nenhum handler para '{task.kind}'")
            output = await handler(ctx)
            return self._finish(task.id, "SUCCEEDED", output=output or {})
        except UncertainCallError as e:
            return self._finish(task.id, "UNCERTAIN", error=str(e))
        except (BudgetExceededError, SpendNotAuthorizedError, UnsafeEstimateError) as e:
            return self._pause_for_budget(task.id, f"{type(e).__name__}: {e}")
        except AwaitingHuman as e:
            return self._finish(task.id, "AWAITING_HUMAN", error=str(e))
        except NotImplementedStage as e:
            return self._finish(task.id, "FAILED", error=str(e), terminal=True)
        except (ModelMismatchError, ContractViolation) as e:
            return self._finish(task.id, "FAILED", error=f"{type(e).__name__}: {e}", terminal=True)
        except CallFailedError as e:
            return self._fail_or_retry(task.id, str(e), retryable=e.retryable, retry_after=e.retry_after_s)
        except Exception as e:  # noqa: BLE001 - toda falha vira estado persistido
            log.exception("tarefa %s falhou", task.id)
            return self._fail_or_retry(task.id, f"{type(e).__name__}: {e}", retryable=True)
        finally:
            hb.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await hb

    def _owned(self, s, task_id: str) -> Task | None:
        t = s.get(Task, task_id)
        if t is None or t.state != "RUNNING" or t.lease_owner != self.worker_id:
            log.warning("lease da tarefa %s perdido; resultado descartado", task_id)
            return None
        return t

    def _finish(self, task_id: str, state: str, *, output: dict | None = None, error: str | None = None,
                terminal: bool = False) -> str:
        with self.db.write() as s:
            t = self._owned(s, task_id)
            if t is None:
                return "LOST"
            t.state = state
            if output is not None:
                t.output = output
            if error:
                t.last_error = error[:4000]
            if terminal:
                t.max_attempts = t.attempts
            t.lease_owner = None
            t.lease_expires_at = None
            t.finished_at = _now()
            return state

    def _fail_or_retry(self, task_id: str, error: str, *, retryable: bool, retry_after: float | None = None) -> str:
        with self.db.write() as s:
            t = self._owned(s, task_id)
            if t is None:
                return "LOST"
            t.last_error = error[:4000]
            t.lease_owner = None
            t.lease_expires_at = None
            if retryable and t.attempts < t.max_attempts:
                t.state = "READY"
                t.not_before = _now() + timedelta(seconds=backoff_delay(t.attempts - 1, self.backoff_base,
                                                                        retry_after=retry_after))
                return "READY"
            t.state = "FAILED"
            t.finished_at = _now()
            return "FAILED"

    def _pause_for_budget(self, task_id: str, reason: str) -> str:
        with self.db.write() as s:
            t = self._owned(s, task_id)
            if t is None:
                return "LOST"
            t.state = "READY"
            t.attempts = max(0, t.attempts - 1)  # falta de orçamento não consome tentativa
            t.last_error = reason[:4000]
            t.lease_owner = None
            t.lease_expires_at = None
            run = s.get(Run, t.run_id)
            if run.state == "RUNNING":
                run.state = "PAUSED_BUDGET"
                run.note = reason[:1000]
            return "PAUSED_BUDGET"

    # ------------------------------------------------------------ laço
    async def run_until_idle(self, run_id: str, concurrency: int = 2, *, max_wait_s: float = 30.0) -> str:
        """Executa até não haver trabalho possível; devolve o estado final da execução."""
        running: dict[str, asyncio.Task] = {}
        while True:
            free = concurrency - len(running)
            if free > 0:
                for t in self.claim(run_id, free):
                    running[t.id] = asyncio.create_task(self.execute(t))
            if running:
                done, _ = await asyncio.wait(running.values(), return_when=asyncio.FIRST_COMPLETED)
                for tid in [k for k, v in running.items() if v in done]:
                    running.pop(tid)
                continue
            wait = self._next_wakeup(run_id)
            if wait is None or wait > max_wait_s:
                break
            await asyncio.sleep(max(wait, 0.0))
        return self.finalize(run_id)

    def _next_wakeup(self, run_id: str) -> float | None:
        with self.db.session() as s:
            run = s.get(Run, run_id)
            if run.state not in ACTIVE_RUN:
                return None
            rows = list(s.execute(select(Task.not_before).where(Task.run_id == run_id, Task.state == "READY"))
                        .scalars())
        if not rows:
            return None
        now = _now()
        return min(((_aware(nb) - now).total_seconds() if nb else 0.0) for nb in rows)

    def finalize(self, run_id: str) -> str:
        """Gate de conclusão (ORQ-005): COMPLETED só sem tarefas obrigatórias pendentes."""
        with self.db.write() as s:
            run = s.get(Run, run_id)
            if run.state != "RUNNING":
                return run.state
            self._promote(s, run_id)
            req = list(s.execute(select(Task).where(Task.run_id == run_id, Task.required.is_(True))).scalars())
            if all(t.state in DONE for t in req):
                run.state = "COMPLETED"
                run.finished_at = _now()
                return run.state
            if any(t.state == "FAILED" for t in req):
                run.state = "FAILED"
                run.note = "tarefa obrigatória falhou"
            elif any(t.state in ("UNCERTAIN", "AWAITING_HUMAN") for t in req):
                run.state = "PAUSED"
                run.note = "aguardando decisão: tarefa incerta ou revisão humana"
            elif any(t.state in ("READY",) for t in req):
                return run.state  # ainda há trabalho com espera longa (backoff)
            else:
                run.state = "PAUSED"
                run.note = "tarefas bloqueadas por dependências não concluídas"
            return run.state

    def summary(self, run_id: str) -> dict[str, Any]:
        with self.db.session() as s:
            run = s.get(Run, run_id)
            counts: dict[str, int] = {}
            for st in s.execute(select(Task.state).where(Task.run_id == run_id)).scalars():
                counts[st] = counts.get(st, 0) + 1
            return {"id": run.id, "state": run.state, "mode": run.mode, "note": run.note, "tasks": counts}
