"""API local (FastAPI). Escuta só em 127.0.0.1; rejeita Host/Origin externos (SEC-004, DNS rebinding).

Nenhum endpoint devolve a chave de API; só o fato de ela estar configurada.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import func, select

from cardfactory.config import REPO_ROOT, Settings, load_settings
from cardfactory.db import Database, make_engine
from cardfactory.db.migrate import upgrade
from cardfactory.db.models import (
    Budget,
    BudgetLedger,
    Card,
    LLMCall,
    ModelCatalogEntry,
    Production,
    Project,
    Run,
    Task,
)
from cardfactory.finance.budget import BudgetError, FinanceService
from cardfactory.orchestrator.engine import Orchestrator, OrchestratorError
from cardfactory.pipeline import full_creation
from cardfactory.prompts.registry import PromptError, PromptRegistry
from cardfactory.providers.base import LLMProvider
from cardfactory.providers.gateway import LLMGateway
from cardfactory.providers.mock import MockProvider
from cardfactory.security.secrets import install_log_redaction

log = logging.getLogger(__name__)
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "testserver"}


@dataclass
class AppState:
    settings: Settings
    db: Database
    finance: FinanceService
    registry: PromptRegistry
    providers: dict[str, LLMProvider]
    gateways: dict[str, LLMGateway] = field(default_factory=dict)
    running: dict[str, asyncio.Task] = field(default_factory=dict)

    def gateway(self, provider: str) -> LLMGateway:
        if provider not in self.providers:
            raise HTTPException(400, f"provedor '{provider}' indisponível")
        if provider not in self.gateways:
            self.gateways[provider] = LLMGateway(self.db, self.finance, self.providers[provider])
        return self.gateways[provider]


def _host_ok(value: str | None) -> bool:
    if not value:
        return False
    host = value.split("://", 1)[-1].split("/", 1)[0].rsplit(":", 1)[0].strip("[]")
    return host in ALLOWED_HOSTS


def create_app(settings: Settings | None = None, providers: dict[str, LLMProvider] | None = None) -> FastAPI:
    settings = settings or load_settings()
    install_log_redaction()
    upgrade(settings.db_path)
    db = Database(make_engine(settings.db_path))
    finance = FinanceService(db)
    registry = PromptRegistry(db, settings.prompts_dir, settings.normative_dir)
    if providers is None:
        providers = {"mock": MockProvider(responder=full_creation.mock_responder)}
        if settings.openrouter_configured:
            from cardfactory.providers.openrouter import OpenRouterProvider
            providers["openrouter"] = OpenRouterProvider()
    st = AppState(settings, db, finance, registry, providers)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        registry.import_library()
        orch = Orchestrator(db, {})
        recovered = orch.recover(all_running=True)
        if recovered:
            log.warning("%d tarefas interrompidas voltaram para a fila", recovered)
        yield
        for t in st.running.values():
            t.cancel()

    app = FastAPI(title="CardFactory", version="0.1.0", lifespan=lifespan)
    app.state.cf = st

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        if not _host_ok(request.headers.get("host")):
            return JSONResponse({"detail": "host não permitido"}, status_code=403)
        origin = request.headers.get("origin")
        if origin and not _host_ok(origin):
            return JSONResponse({"detail": "origem não permitida"}, status_code=403)
        return await call_next(request)

    @app.exception_handler(BudgetError)
    async def budget_err(_r, e: BudgetError):
        return JSONResponse({"detail": str(e), "kind": type(e).__name__}, status_code=409)

    @app.exception_handler(OrchestratorError)
    async def orch_err(_r, e: OrchestratorError):
        return JSONResponse({"detail": str(e)}, status_code=409)

    @app.exception_handler(PromptError)
    async def prompt_err(_r, e: PromptError):
        return JSONResponse({"detail": str(e)}, status_code=400)

    _routes(app, st)
    _static(app)
    return app


# ---------------------------------------------------------------------------- modelos de entrada
class BudgetIn(BaseModel):
    scope: str
    scope_ref: str
    limit_brl: str
    label: str = ""
    parent_budget_id: str | None = None


class FxIn(BaseModel):
    rate: str
    margin: str = "0.10"
    source: str = "manual"


class AuthorizationIn(BaseModel):
    budget_id: str
    amount_brl: str
    granted_by: str
    note: str = ""


class PromptEditIn(BaseModel):
    body: str
    author: str
    note: str = ""


class AuthorIn(BaseModel):
    author: str
    new_key: str | None = None


class ProductionIn(BaseModel):
    project_name: str = "Projeto de demonstração"
    theme: str
    target_cards: int = 3
    provider: str = "mock"
    budget_id: str | None = None
    models: dict[str, str] = {}


class SkipIn(BaseModel):
    reason: str


def _run_row(s, r: Run) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for state in s.execute(select(Task.state).where(Task.run_id == r.id)).scalars():
        counts[state] = counts.get(state, 0) + 1
    prd = s.get(Production, r.production_id)
    return {"id": r.id, "mode": r.mode, "state": r.state, "note": r.note, "theme": prd.theme if prd else "",
            "provider": prd.provider if prd else "", "created_at": r.created_at.isoformat(),
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None, "tasks": counts}


def _routes(app: FastAPI, st: AppState) -> None:  # noqa: C901 - lista plana de rotas
    db, finance, registry = st.db, st.finance, st.registry

    # ------------------------------------------------------------ saúde e painel
    @app.get("/api/health")
    def health():
        return {"ok": True, "providers": sorted(st.providers),
                "openrouter_configured": st.settings.openrouter_configured}

    @app.get("/api/dashboard")
    def dashboard():
        with db.session() as s:
            def count(model, *where):
                return s.execute(select(func.count()).select_from(model).where(*where)).scalar_one()

            runs = {k: v for k, v in s.execute(select(Run.state, func.count()).group_by(Run.state)).all()}
            tasks = {k: v for k, v in s.execute(select(Task.state, func.count()).group_by(Task.state)).all()}
            cards = {k: v for k, v in s.execute(select(Card.state, func.count()).group_by(Card.state)).all()}
            calls = {k: v for k, v in s.execute(select(LLMCall.state, func.count()).group_by(LLMCall.state)).all()}
            recent = [_run_row(s, r) for r in s.execute(select(Run).order_by(Run.created_at.desc()).limit(5)).scalars()]
            return {
                "projects": count(Project), "productions": count(Production), "runs": runs, "tasks": tasks,
                "cards": cards, "cards_mock": count(Card, Card.origin == "MOCK"), "calls": calls,
                "budgets": finance.all_status(), "pending_reconciliation": len(finance.pending_reconciliation()),
                "fx": _fx(s), "openrouter_configured": st.settings.openrouter_configured, "recent_runs": recent,
            }

    def _fx(s):
        fx = finance.latest_fx(s)
        return None if fx is None else {"rate": fx.rate, "margin": fx.margin, "source": fx.source,
                                        "valid_on": str(fx.valid_on)}

    # ------------------------------------------------------------ orçamento
    @app.get("/api/budgets")
    def budgets():
        with db.session() as s:
            auths = finance.active_authorizations(s, [b.id for b in s.execute(select(Budget)).scalars()])
            return {"budgets": finance.all_status(), "fx": _fx(s),
                    "authorizations": [{"id": a.id, "budget_id": a.scope_budget_id, "amount_brl": a.amount_brl,
                                        "granted_by": a.granted_by, "note": a.note} for a in auths],
                    "pending_reconciliation": finance.pending_reconciliation()}

    @app.post("/api/budgets")
    def create_budget(b: BudgetIn):
        return {"id": finance.create_budget(b.scope, b.scope_ref, b.limit_brl, b.label, b.parent_budget_id)}

    @app.post("/api/budgets/{budget_id}/seed-experiment")
    def seed(budget_id: str):
        return finance.seed_experiment(budget_id)

    @app.post("/api/fx")
    def set_fx(f: FxIn):
        return {"id": finance.set_fx_rate(f.rate, f.margin, f.source)}

    @app.post("/api/authorizations")
    def authorize(a: AuthorizationIn):
        return {"id": finance.authorize_spend(a.budget_id, a.amount_brl, a.granted_by, a.note)}

    @app.delete("/api/authorizations/{auth_id}")
    def revoke(auth_id: str):
        finance.revoke_authorization(auth_id)
        return {"ok": True}

    @app.get("/api/ledger")
    def ledger(budget_id: str | None = None, limit: int = 200):
        with db.session() as s:
            qy = select(BudgetLedger).order_by(BudgetLedger.created_at.desc()).limit(min(limit, 1000))
            if budget_id:
                qy = qy.where(BudgetLedger.budget_id == budget_id)
            return [{"id": e.id, "budget_id": e.budget_id, "call_id": e.llm_call_id, "kind": e.kind,
                     "amount_usd": e.amount_usd, "amount_brl": e.amount_brl, "note": e.note,
                     "created_at": e.created_at.isoformat()} for e in s.execute(qy).scalars()]

    @app.get("/api/calls")
    def calls(limit: int = 100, run_id: str | None = None):
        with db.session() as s:
            qy = select(LLMCall).order_by(LLMCall.created_at.desc()).limit(min(limit, 500))
            if run_id:
                qy = qy.join(Task, Task.id == LLMCall.task_id).where(Task.run_id == run_id)
            rows = s.execute(qy).scalars()
            return [{"id": c.id, "task_id": c.task_id, "stage": c.stage, "provider": c.provider,
                     "requested_model": c.requested_model, "served_model": c.served_model, "state": c.state,
                     "model_mismatch": c.model_mismatch, "tokens_in": c.tokens_in, "tokens_out": c.tokens_out,
                     "estimated_max_usd": c.estimated_max_usd, "cost_usd": c.cost_usd, "latency_ms": c.latency_ms,
                     "prompt_hash": c.prompt_hash, "error": c.error, "created_at": c.created_at.isoformat()}
                    for c in rows]

    @app.post("/api/reconcile/{provider}")
    async def reconcile(provider: str):
        return await st.gateway(provider).reconcile()

    # ------------------------------------------------------------ modelos
    @app.get("/api/models")
    def models(provider: str | None = None):
        with db.session() as s:
            qy = select(ModelCatalogEntry).order_by(ModelCatalogEntry.fetched_at.desc())
            if provider:
                qy = qy.where(ModelCatalogEntry.provider == provider)
            seen, out = set(), []
            for m in s.execute(qy).scalars():
                if (m.provider, m.model_id) in seen:
                    continue
                seen.add((m.provider, m.model_id))
                out.append({"provider": m.provider, "model_id": m.model_id, "name": m.name, "pricing": m.pricing,
                            "context_length": m.context_length, "supported_parameters": m.supported_parameters,
                            "fetched_at": m.fetched_at.isoformat()})
            return out

    @app.post("/api/models/sync/{provider}")
    async def sync_models(provider: str):
        """Consulta o catálogo (endpoint gratuito; não gera cobrança)."""
        return {"models": await st.gateway(provider).sync_catalog()}

    # ------------------------------------------------------------ prompts
    @app.get("/api/prompts")
    def prompts():
        return {"prompts": registry.list_prompts(), "coverage": registry.coverage_report(),
                "roles": {k: {"policies": v.policies, "contract": v.contract, "required": v.required,
                              "normative": v.normative} for k, v in registry.manifest.roles.items()}}

    @app.get("/api/prompts/{key}/versions")
    def prompt_versions(key: str):
        return registry.versions(key)

    @app.put("/api/prompts/{key}")
    def prompt_edit(key: str, e: PromptEditIn):
        return {"version_id": registry.edit(key, e.body, e.author, e.note)}

    @app.post("/api/prompts/{key}/duplicate")
    def prompt_dup(key: str, a: AuthorIn):
        if not a.new_key:
            raise HTTPException(400, "new_key obrigatório")
        return {"version_id": registry.duplicate(key, a.new_key, a.author)}

    @app.post("/api/prompts/{key}/restore/{version_id}")
    def prompt_restore(key: str, version_id: str, a: AuthorIn):
        return {"version_id": registry.restore(key, version_id, a.author)}

    @app.post("/api/prompts/{key}/activate/{version_id}")
    def prompt_activate(key: str, version_id: str):
        registry.activate(key, version_id)
        return {"ok": True}

    @app.get("/api/prompts-diff")
    def prompt_diff(a: str, b: str):
        return {"diff": registry.diff(a, b)}

    @app.get("/api/prompts-compose/{role}")
    def prompt_compose(role: str, variant: str = "specialized"):
        c = registry.compose(role, variant)
        return {"role": c.role, "variant": c.variant, "hash": c.hash, "version_ids": c.version_ids,
                "req_ids": c.req_ids, "missing_required": c.missing_required, "contract": c.contract,
                "chars": len(c.text), "text": c.text}

    # ------------------------------------------------------------ produções e execuções
    def _orchestrator(provider: str, models: dict[str, str]) -> Orchestrator:
        svc = full_creation.Services(db, st.gateway(provider), registry, models,
                                     st.settings.data_dir / "exports")
        return Orchestrator(db, full_creation.handlers(svc))

    def _models_for(provider: str, given: dict[str, str]) -> dict[str, str]:
        if given:
            return given
        if provider == "mock":
            return {"default": "mock/creator-a", **{s: "mock/auditor-b" for s, _ in full_creation.STAGES
                                                     if s.startswith("AUDIT") or s == "REAUDIT"}}
        raise HTTPException(400, "informe o modelo de cada etapa; nenhum ID de modelo é presumido")

    @app.post("/api/productions")
    def create_production(p: ProductionIn):
        if p.provider not in st.providers:
            raise HTTPException(400, f"provedor '{p.provider}' indisponível")
        models = _models_for(p.provider, p.models)
        with db.write() as s:
            prj = s.execute(select(Project).where(Project.name == p.project_name)).scalar_one_or_none()
            if prj is None:
                prj = Project(name=p.project_name)
                s.add(prj)
                s.flush()
            prd = Production(project_id=prj.id, mode=full_creation.MODE, theme=p.theme,
                             target_cards=p.target_cards, provider=p.provider,
                             scope={"models": models})
            s.add(prd)
            s.flush()
            prd_id = prd.id
        budget_id = p.budget_id
        if budget_id is None:
            if p.provider != "mock":
                raise HTTPException(400, "produção com provedor pago exige orçamento explícito")
            with db.session() as s:
                b = s.execute(select(Budget).where(Budget.scope == "PROJECT", Budget.scope_ref == "mock")) \
                    .scalar_one_or_none()
            budget_id = b.id if b else finance.create_budget("PROJECT", "mock", "0", "Simulações (sem custo)")
        orch = _orchestrator(p.provider, models)
        run_id = orch.create_run(prd_id, full_creation.MODE, full_creation.graph([budget_id]))
        return {"production_id": prd_id, "run_id": run_id}

    def _launch(run_id: str) -> None:
        with db.session() as s:
            run = s.get(Run, run_id)
            if run is None:
                raise HTTPException(404, "execução inexistente")
            prd = s.get(Production, run.production_id)
        if run_id in st.running and not st.running[run_id].done():
            return
        orch = _orchestrator(prd.provider, (prd.scope or {}).get("models") or _models_for(prd.provider, {}))
        st.running[run_id] = asyncio.create_task(orch.run_until_idle(run_id, concurrency=prd.concurrency))

    @app.get("/api/runs")
    def runs(limit: int = 50):
        with db.session() as s:
            return [_run_row(s, r) for r in
                    s.execute(select(Run).order_by(Run.created_at.desc()).limit(min(limit, 500))).scalars()]

    @app.get("/api/runs/{run_id}")
    def run_detail(run_id: str):
        with db.session() as s:
            r = s.get(Run, run_id)
            if r is None:
                raise HTTPException(404, "execução inexistente")
            tasks = s.execute(select(Task).where(Task.run_id == run_id).order_by(Task.priority, Task.created_at))
            return {**_run_row(s, r), "active": run_id in st.running and not st.running[run_id].done(),
                    "task_list": [{"id": t.id, "key": t.idempotency_key.split(":", 1)[1], "stage": t.stage,
                                   "kind": t.kind, "state": t.state, "attempts": t.attempts,
                                   "max_attempts": t.max_attempts, "required": t.required,
                                   "last_error": t.last_error, "output": t.output,
                                   "started_at": t.started_at.isoformat() if t.started_at else None,
                                   "finished_at": t.finished_at.isoformat() if t.finished_at else None}
                                  for t in tasks.scalars()]}

    @app.post("/api/runs/{run_id}/start")
    async def run_start(run_id: str):
        Orchestrator(db, {}).start(run_id)
        _launch(run_id)
        return {"ok": True}

    @app.post("/api/runs/{run_id}/pause")
    def run_pause(run_id: str):
        Orchestrator(db, {}).pause(run_id)
        return {"ok": True}

    @app.post("/api/runs/{run_id}/resume")
    async def run_resume(run_id: str):
        Orchestrator(db, {}).resume(run_id)
        _launch(run_id)
        return {"ok": True}

    @app.post("/api/runs/{run_id}/cancel")
    def run_cancel(run_id: str):
        Orchestrator(db, {}).cancel(run_id)
        return {"ok": True}

    @app.post("/api/tasks/{task_id}/reprocess")
    def task_reprocess(task_id: str):
        return {"task_id": Orchestrator(db, {}).reprocess(task_id)}

    @app.post("/api/tasks/{task_id}/skip")
    def task_skip(task_id: str, body: SkipIn):
        Orchestrator(db, {}).skip(task_id, body.reason)
        return {"ok": True}

    @app.get("/api/cards")
    def cards(production_id: str | None = None, limit: int = 200):
        from cardfactory.db.models import CardVersion
        with db.session() as s:
            qy = select(Card).order_by(Card.created_at.desc()).limit(min(limit, 1000))
            if production_id:
                qy = qy.where(Card.production_id == production_id)
            out = []
            for c in s.execute(qy).scalars():
                v = s.execute(select(CardVersion).where(CardVersion.card_id == c.id)
                              .order_by(CardVersion.version_no.desc()).limit(1)).scalar_one_or_none()
                out.append({"id": c.id, "card_key": c.card_key, "state": c.state, "origin": c.origin,
                            "production_id": c.production_id, "version": v.version_no if v else None,
                            "content": v.content if v else None})
            return out

    @app.get("/api/not-implemented/{feature}")
    def not_implemented(feature: str):
        return JSONResponse({"status": "NOT_IMPLEMENTED", "feature": feature}, status_code=501)



def _static(app: FastAPI) -> None:
    dist = REPO_ROOT / "frontend" / "dist"
    if not (dist / "index.html").is_file():
        @app.get("/")
        def no_ui():
            return JSONResponse({"detail": "interface não compilada; rode `npm run build` em frontend/"})
        return
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404)
        f = (dist / path).resolve()
        if path and f.is_file() and dist.resolve() in f.parents:
            return FileResponse(f)
        return FileResponse(dist / "index.html")


def app_factory() -> FastAPI:  # uvicorn --factory
    return create_app()


__all__ = ["create_app", "app_factory"]
