"""API local (FastAPI). Escuta só em 127.0.0.1; rejeita Host/Origin externos (SEC-004, DNS rebinding).

Nenhum endpoint devolve a chave de API; só o fato de ela estar configurada.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import func, select

from cardfactory.audit.service import AuditError, AuditService
from cardfactory.benchmark import experiment
from cardfactory.benchmark.service import BenchmarkError, BenchmarkService
from cardfactory.cards.model import CardError, structural_errors
from cardfactory.cards.samples import SAMPLES
from cardfactory.cards.service import CardService, CardServiceError
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
from cardfactory.export.service import Exporter, ExportError
from cardfactory.finance.budget import BudgetError, FinanceService
from cardfactory.importers.anki import AnkiImporter
from cardfactory.importers.questions import import_questions
from cardfactory.knowledge.service import Knowledge, KnowledgeError
from cardfactory.library.apostila import ApostilaError, import_apostila
from cardfactory.library.service import Library, LibraryError
from cardfactory.orchestrator.engine import Orchestrator, OrchestratorError
from cardfactory.pipeline import full_audit, full_creation
from cardfactory.pipeline.simulation import mock_fetcher
from cardfactory.prompts.registry import PromptError, PromptRegistry
from cardfactory.providers.base import LLMProvider
from cardfactory.providers.gateway import LLMGateway
from cardfactory.providers.mock import MockProvider
from cardfactory.render.palette import PALETTES, contrast
from cardfactory.render.renderer import render
from cardfactory.review.service import REASONS as REVIEW_REASONS
from cardfactory.review.service import ReviewError, ReviewService
from cardfactory.security.fetch import FetchBlockedError, FetchFailedError, safe_fetch
from cardfactory.security.secrets import install_log_redaction
from cardfactory.validation.card_checks import check_card

log = logging.getLogger(__name__)
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "testserver"}


@dataclass
class AppState:
    settings: Settings
    db: Database
    finance: FinanceService
    registry: PromptRegistry
    providers: dict[str, LLMProvider]
    library: Library
    knowledge: Knowledge
    cards: CardService | None = None
    exporter: Exporter | None = None
    fetcher: Any = None  # injetável nos testes; padrão: download seguro
    gateways: dict[str, LLMGateway] = field(default_factory=dict)
    running: dict[str, asyncio.Task] = field(default_factory=dict)

    def gateway(self, provider: str) -> LLMGateway:
        if provider not in self.providers:
            raise HTTPException(400, f"provedor '{provider}' indisponível")
        if provider not in self.gateways:
            self.gateways[provider] = LLMGateway(self.db, self.finance, self.providers[provider])
        return self.gateways[provider]


async def _safe_fetcher(url: str) -> tuple[bytes, str | None, str]:
    r = await safe_fetch(url)
    return r.data, r.content_type, r.final_url


def httpx_errors() -> type[Exception]:
    import httpx

    return httpx.HTTPError


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
    st = AppState(settings, db, finance, registry, providers, Library(db, settings.data_dir / "blobs"), Knowledge(db))
    st.cards = CardService(db, settings.media_dir, deck_prefix=settings.deck_prefix)
    st.exporter = Exporter(db, settings.exports_dir, settings.media_dir, deck_prefix=settings.deck_prefix)

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

    @app.exception_handler(LibraryError)
    async def lib_err(_r, e: LibraryError):
        return JSONResponse({"detail": str(e)}, status_code=400)

    @app.exception_handler(KnowledgeError)
    async def kn_err(_r, e: KnowledgeError):
        return JSONResponse({"detail": str(e)}, status_code=400)

    @app.exception_handler(PromptError)
    async def prompt_err(_r, e: PromptError):
        return JSONResponse({"detail": str(e)}, status_code=400)

    @app.exception_handler(CardError)
    async def card_err(_r, e: CardError):
        return JSONResponse({"detail": str(e), "errors": e.errors}, status_code=400)

    @app.exception_handler(CardServiceError)
    async def card_svc_err(_r, e: CardServiceError):
        return JSONResponse({"detail": str(e)}, status_code=400)

    @app.exception_handler(ExportError)
    async def export_err(_r, e: ExportError):
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


MODES = {full_creation.MODE: full_creation, full_audit.MODE: full_audit}


class ProductionIn(BaseModel):
    project_name: str = "Projeto de demonstração"
    theme: str
    target_cards: int = 3
    provider: str = "mock"
    budget_id: str | None = None
    models: dict[str, str] = {}
    research_mode: str = "HYBRID"  # AUTONOMOUS | UPLOADED | HYBRID (BIB-001)
    document_ids: list[str] = []
    # Apostila como fonte principal (UPLOADED): checagem barata de diretrizes posteriores na web (opcional).
    update_check_since: str | None = None
    update_check_max_sources: int = 2
    web_search_max_results: int = 3
    mode: str = "FULL_CREATION"  # FULL_CREATION | FULL_AUDIT
    # Escopo da auditoria integral (FULL_AUDIT): cards escolhidos por id, lote de importação e/ou deck.
    card_ids: list[str] = []
    import_batch_ids: list[str] = []
    deck_prefix: str = ""


class DefectStatusIn(BaseModel):
    status: str
    note: str
    actor: str


class ReviewIn(BaseModel):
    decision: str
    actor: str
    reasons: list[str] = []
    note: str = ""
    duration_ms: int | None = None
    started_version_no: int | None = None


class ProposalIn(BaseModel):
    accept: bool
    actor: str
    note: str = ""


class ActorIn(BaseModel):
    actor: str


class LessonIn(BaseModel):
    text: str
    actor: str
    reason_codes: list[str] = []
    decision_ids: list[str] = []


class LessonStatusIn(BaseModel):
    status: str
    actor: str


class BenchRunIn(BaseModel):
    set_name: str
    split: str = "dev"
    subject: str = "DETERMINISTIC"
    actor: str
    purpose: str = ""
    provider: str = "mock"
    models: dict[str, str] = {}
    budget_id: str | None = None


class CompareIn(BaseModel):
    question: str
    card_version_ids: list[str]
    origins: list[str] = []


class CompareDecisionIn(BaseModel):
    choice: str
    actor: str
    justification: str
    ranking: list[str] = []


class SkipIn(BaseModel):
    reason: str


class CardIn(BaseModel):
    project_id: str
    card: dict[str, Any]
    author: str


class CardEditIn(BaseModel):
    card: dict[str, Any]
    author: str
    note: str = ""
    kind: str = "UPDATE_CONTENT"
    objective_change: str = "EQUIVALENT"


HUMAN_STATES = {"HUMAN_APPROVED", "QUARANTINE", "REJECTED", "PENDING_HUMAN"}


class CardStateIn(BaseModel):
    state: str
    author: str
    reason: str


class RollbackIn(BaseModel):
    version_no: int
    author: str
    reason: str


class JustifyIn(BaseModel):
    justification: str
    author: str


class RenderIn(BaseModel):
    card: dict[str, Any]


class ExportIn(BaseModel):
    project_id: str
    format: str = "anki_tsv_v2"
    production_id: str | None = None
    card_ids: list[str] | None = None
    preview: bool = False
    author: str = ""
    test_import: bool = False


class SourceIn(BaseModel):
    title_claimed: str
    institution: str = ""
    source_tier: str = "UNCLASSIFIED"
    doc_type: str = ""
    url: str | None = None
    doi: str | None = None
    created_by: str = "usuário"
    notes: str = ""


class VersionIn(BaseModel):
    version_label: str = ""
    published_at: str | None = None
    page_updated_at: str | None = None
    effective_from: str | None = None
    effective_to: str | None = None
    validity_status: str = "UNCERTAIN"
    supersedes_version_id: str | None = None
    population: str = ""
    context: str = ""


class FetchIn(BaseModel):
    url: str


class StateIn(BaseModel):
    state: str
    actor: str
    reason: str = ""


class EvidenceIn(BaseModel):
    section_id: str
    quote: str


class ProjectIn(BaseModel):
    name: str
    area: str = ""


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

    @app.get("/api/experiment/plan")
    def experiment_plan(budget_brl: str = "15", cap_usd_m: str | None = None):
        """Etapa 1: candidatos por família e custo estimado a partir do catálogo sincronizado (sem custo)."""
        caps = {"creator": Decimal(cap_usd_m), "auditor_scientific": Decimal(cap_usd_m)} if cap_usd_m else None
        p = experiment.plan_from_db(db, finance, budget_brl=Decimal(budget_brl), caps=caps)
        return p | {"markdown": experiment.to_markdown(p)}

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
        fetcher = mock_fetcher if provider == "mock" else (st.fetcher or _safe_fetcher)
        svc = full_creation.Services(db, st.gateway(provider), registry, models, st.settings.exports_dir,
                                     st.library, st.knowledge, fetcher, st.settings.media_dir,
                                     st.settings.deck_prefix)
        return Orchestrator(db, full_audit.handlers(svc))  # superconjunto: criação e auditoria integrais

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
            if p.research_mode not in ("AUTONOMOUS", "UPLOADED", "HYBRID"):
                raise HTTPException(400, "modo de pesquisa inválido")
            if p.research_mode == "UPLOADED" and not p.document_ids:
                raise HTTPException(400, "modo documentos enviados exige ao menos um documento")
            if p.mode not in MODES:
                raise HTTPException(400, f"modo desconhecido: {p.mode}")
            scope = {"models": models, "document_ids": p.document_ids}
            if p.research_mode == "UPLOADED" and p.update_check_since:
                scope |= {"update_check": {"since": p.update_check_since,
                                           "max_sources": max(1, min(p.update_check_max_sources, 5))},
                          "web_search": {"max_results": max(1, min(p.web_search_max_results, 10))}}
            if p.mode == full_audit.MODE:
                scope |= {"card_ids": p.card_ids, "import_batch_ids": p.import_batch_ids,
                          "deck_prefix": p.deck_prefix}
            prd = Production(project_id=prj.id, mode=p.mode, theme=p.theme,
                             target_cards=p.target_cards, provider=p.provider, research_mode=p.research_mode,
                             scope=scope)
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
        run_id = orch.create_run(prd_id, p.mode, MODES[p.mode].graph([budget_id]))
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

    # ------------------------------------------------------------ cards (Fase 3)
    cs, ex = st.cards, st.exporter

    @app.get("/api/cards")
    def cards(production_id: str | None = None, project_id: str | None = None, state: str | None = None,
              limit: int = 200):
        return cs.list(project_id=project_id, production_id=production_id, state=state, limit=min(limit, 1000))

    @app.get("/api/cards/{card_id}")
    def card_get(card_id: str):
        return cs.get(card_id)

    # ------------------------------------------------------------ auditoria (Fase 4)
    aud = AuditService(db)

    @app.get("/api/productions")
    def productions(project_id: str | None = None):
        with db.session() as s:
            q = select(Production).order_by(Production.created_at.desc()).limit(200)
            if project_id:
                q = q.where(Production.project_id == project_id)
            return [{"id": p.id, "project_id": p.project_id, "mode": p.mode, "theme": p.theme,
                     "provider": p.provider, "created_at": p.created_at.isoformat()} for p in s.execute(q).scalars()]

    @app.get("/api/productions/{production_id}/audit-report")
    def audit_report(production_id: str):
        with db.session() as s:
            if s.get(Production, production_id) is None:
                raise HTTPException(404, "produção inexistente")
        return aud.report(production_id)

    @app.get("/api/defects")
    def defects(production_id: str | None = None, card_id: str | None = None, status: str | None = None):
        return aud.defects(production_id=production_id, card_id=card_id, status=status)

    @app.post("/api/defects/{defect_id}/status")
    def defect_status(defect_id: str, b: DefectStatusIn):
        try:
            aud.set_defect(defect_id, b.status, note=b.note, actor=b.actor)
        except AuditError as e:
            raise HTTPException(400, str(e)) from e
        return {"ok": True}

    @app.get("/api/cards/{card_id}/claims")
    def card_claims(card_id: str):
        return aud.claim_verdicts(card_id)

    @app.get("/api/cards/{card_id}/blockers")
    def card_blockers(card_id: str):
        return {"blockers": aud.blockers(card_id)}

    # ------------------------------------------------------------ revisão humana (Fase 5)
    rv = ReviewService(db)
    bench = BenchmarkService(db, registry)

    def _rv(fn, *a, **k):
        try:
            return fn(*a, **k)
        except ReviewError as e:
            raise HTTPException(400, str(e)) from e

    @app.get("/api/review/queue")
    def review_queue(project_id: str | None = None, production_id: str | None = None, state: str | None = None,
                     deck: str = "", include_done: bool = False):
        return rv.queue(project_id=project_id, production_id=production_id, state=state, deck=deck,
                        include_done=include_done)

    @app.get("/api/review/reasons")
    def review_reasons():
        return [{"code": k, "label": v[1], "category": v[0]} for k, v in REVIEW_REASONS.items()]

    @app.get("/api/review/cards/{card_id}")
    def review_detail(card_id: str):
        return _rv(rv.detail, card_id)

    @app.post("/api/review/cards/{card_id}/decision")
    def review_decide(card_id: str, b: ReviewIn):
        return _rv(rv.decide, card_id, b.decision, actor=b.actor, reasons=b.reasons, note=b.note,
                   duration_ms=b.duration_ms, started_version_no=b.started_version_no)

    @app.post("/api/review/cards/{card_id}/undo")
    def review_undo(card_id: str, b: ActorIn):
        return _rv(rv.undo, card_id, actor=b.actor)

    @app.post("/api/review/proposals/{operation_id}")
    def review_proposal(operation_id: str, b: ProposalIn):
        return _rv(rv.decide_proposal, operation_id, b.accept, actor=b.actor, note=b.note)

    @app.get("/api/review/insights")
    def review_insights(project_id: str | None = None):
        return rv.insights(project_id=project_id)

    @app.get("/api/review/lessons")
    def review_lessons():
        return rv.lessons()

    @app.post("/api/review/lessons")
    def review_add_lesson(b: LessonIn):
        return {"id": _rv(rv.add_lesson, b.text, actor=b.actor, reason_codes=b.reason_codes,
                          decision_ids=b.decision_ids)}

    @app.post("/api/review/lessons/{lesson_id}/status")
    def review_lesson_status(lesson_id: str, b: LessonStatusIn):
        _rv(rv.set_lesson, lesson_id, b.status, actor=b.actor)
        return {"ok": True}

    @app.post("/api/review/lessons/promote")
    def review_promote(b: ActorIn):
        return _rv(rv.promote_lessons, registry, actor=b.actor)

    # ------------------------------------------------------------ laboratório (Fase 5)
    def _bm(fn, *a, **k):
        try:
            return fn(*a, **k)
        except BenchmarkError as e:
            raise HTTPException(400, str(e)) from e

    @app.post("/api/bench/sets/load")
    def bench_load():
        return bench.load_sets()

    @app.get("/api/bench/summary")
    def bench_summary():
        return bench.summary()

    @app.get("/api/bench/items")
    def bench_items(set_name: str, split: str = "dev", actor: str = "", purpose: str = ""):
        return _bm(bench.items, set_name, split, actor=actor, purpose=purpose)

    @app.post("/api/bench/runs")
    async def bench_run(b: BenchRunIn):
        gw, budget_ids = None, []
        if b.subject != "DETERMINISTIC":
            if b.provider != "mock" and not b.budget_id:
                raise HTTPException(400, "benchmark com provedor pago exige orçamento explícito")
            gw = st.gateway(b.provider)
            if b.budget_id:
                budget_ids = [b.budget_id]
            else:
                with db.session() as s:
                    bud = s.execute(select(Budget).where(Budget.scope == "PROJECT", Budget.scope_ref == "mock")) \
                        .scalar_one_or_none()
                budget_ids = [bud.id if bud else finance.create_budget("PROJECT", "mock", "0",
                                                                       "Simulações (sem custo)")]
        models = b.models or ({"default": "mock/auditor-b"} if b.provider == "mock" else {})
        try:
            return await bench.run(b.set_name, b.split, b.subject, actor=b.actor, purpose=b.purpose, gateway=gw,
                                   provider="" if gw is None else b.provider,
                                   models={} if gw is None else models, budget_ids=budget_ids)
        except BenchmarkError as e:
            raise HTTPException(400, str(e)) from e

    @app.get("/api/bench/runs")
    def bench_runs():
        return bench.runs()

    @app.get("/api/bench/runs/{run_id}")
    def bench_run_detail(run_id: str):
        return _bm(bench.run_detail, run_id)

    @app.get("/api/bench/comparisons")
    def bench_comparisons():
        return bench.comparisons()

    @app.post("/api/bench/comparisons")
    def bench_compare(b: CompareIn):
        return {"id": _bm(bench.create_comparison, b.question, b.card_version_ids, b.origins or None)}

    @app.get("/api/bench/comparisons/{cid}")
    def bench_comparison(cid: str):
        return _bm(bench.comparison, cid)

    @app.post("/api/bench/comparisons/{cid}/decision")
    def bench_compare_decide(cid: str, b: CompareDecisionIn):
        return _bm(bench.decide_comparison, cid, b.choice, actor=b.actor, justification=b.justification,
                   ranking=b.ranking)

    @app.get("/api/similarity")
    def similarity(project_id: str | None = None, status: str | None = None):
        from cardfactory.db.models import SimilarityPair
        with db.session() as s:
            q = select(SimilarityPair).order_by(SimilarityPair.created_at.desc()).limit(500)
            if project_id:
                q = q.where(SimilarityPair.project_id == project_id)
            if status:
                q = q.where(SimilarityPair.status == status)
            keys = dict(s.execute(select(Card.id, Card.card_key)).all())
            return [{"id": p.id, "card_a": keys.get(p.card_a_id), "card_b": keys.get(p.card_b_id),
                     "card_a_id": p.card_a_id, "card_b_id": p.card_b_id, "layer": p.layer, "score": p.score,
                     "kind": p.kind, "proposal": p.proposal, "rationale": p.rationale, "status": p.status}
                    for p in s.execute(q).scalars()]

    @app.post("/api/cards")
    def card_create(body: CardIn):
        _project(body.project_id)
        if not body.author.strip():
            raise HTTPException(400, "informe o autor")
        cid = cs.create(body.project_id, body.card, origin="HUMAN", author_type="HUMAN", actor=body.author,
                        state="DRAFT")
        return {"id": cid}

    @app.post("/api/cards/{card_id}/versions")
    def card_edit(card_id: str, body: CardEditIn):
        return cs.new_version(card_id, body.card, kind=body.kind, author_type="HUMAN", actor=body.author,
                              note=body.note, objective_change=body.objective_change)

    @app.post("/api/cards/{card_id}/state")
    def card_state(card_id: str, body: CardStateIn):
        """Decisão humana mínima (aprovar, quarentena, rejeitar). A mesa de revisão completa chega na Fase 5."""
        if body.state not in HUMAN_STATES:
            raise HTTPException(400, f"estado deve ser um de {sorted(HUMAN_STATES)}")
        if not body.author.strip() or not body.reason.strip():
            raise HTTPException(400, "autor e motivo são obrigatórios")
        if body.state == "HUMAN_APPROVED" and cs.get(card_id)["schema_version"] != "2.1":
            raise HTTPException(400, "card legado precisa ser convertido para card.v2 antes da aprovação")
        cs.set_state(card_id, body.state, actor=body.author, actor_type="HUMAN", reason=body.reason)
        return {"ok": True}

    @app.post("/api/cards/{card_id}/rollback")
    def card_rollback(card_id: str, body: RollbackIn):
        return cs.rollback(card_id, body.version_no, actor=body.author, reason=body.reason)

    @app.get("/api/cards/{card_id}/diff")
    def card_diff(card_id: str, a: int, b: int):
        return cs.diff(card_id, a, b)

    @app.post("/api/cards/{card_id}/media/{asset_id}")
    async def card_media(card_id: str, asset_id: str, request: Request, alt: str, side: str = "back",
                         license: str = "", rights_verified: bool = False, author: str = ""):
        data = await request.body()
        return cs.attach_media(asset_id, data, alt=alt, side=side, license=license,
                               rights_verified=rights_verified, actor=author or "humano")

    @app.post("/api/findings/{finding_id}/justify")
    def finding_justify(finding_id: str, body: JustifyIn):
        cs.justify(finding_id, body.justification, actor=body.author)
        return {"ok": True}

    @app.post("/api/render")
    def render_preview(body: RenderIn):
        """Prévia de um card.v2 qualquer (não grava nada): HTML escuro/claro + achados."""
        errs = structural_errors(body.card)
        if errs:
            return {"ok": False, "errors": errs, "findings": [], "rendered": None}
        rendered = render(body.card)
        findings = check_card(body.card, rendered, deck_prefix=st.settings.deck_prefix)
        return {"ok": True, "errors": [], "findings": [f.as_dict() for f in findings],
                "rendered": cs.preview(body.card)}

    @app.get("/api/render/samples")
    def render_samples():
        return [{"layout": k, "card": c, "rendered": cs.preview(c),
                 "findings": [f.as_dict() for f in check_card(c, render(c), deck_prefix=st.settings.deck_prefix)]}
                for k, c in SAMPLES.items()]

    @app.get("/api/render/palettes")
    def render_palettes():
        return {name: {**{k: getattr(p, k) for k in ("background", "text", "complement", "blue", "amber", "red",
                                                      "separator")},
                       "contrast": {k: round(contrast(getattr(p, k), p.background), 2)
                                    for k in ("text", "complement", "blue", "amber", "red")}}
                for name, p in PALETTES.items()}

    # ------------------------------------------------------------ exportação (Fase 3)
    @app.post("/api/exports")
    def export_create(body: ExportIn):
        _project(body.project_id)
        return ex.export(body.project_id, body.format, production_id=body.production_id, card_ids=body.card_ids,
                         preview=body.preview, actor=body.author, test_import=body.test_import)

    @app.get("/api/exports")
    def export_list(project_id: str | None = None):
        return ex.list(project_id)

    @app.get("/api/exports/{export_id}")
    def export_get(export_id: str):
        return ex.get(export_id)

    @app.get("/api/exports/{export_id}/files/{name:path}")
    def export_file(export_id: str, name: str):
        path = ex.file_path(export_id, name)
        return FileResponse(path, filename=path.name)

    # ------------------------------------------------------------ projetos
    @app.get("/api/projects")
    def projects():
        with db.session() as s:
            return [{"id": p.id, "name": p.name, "area": p.area} for p in
                    s.execute(select(Project).order_by(Project.name)).scalars()]

    @app.post("/api/projects")
    def create_project(p: ProjectIn):
        with db.write() as s:
            if s.execute(select(Project).where(Project.name == p.name)).scalar_one_or_none():
                raise HTTPException(409, "já existe um projeto com esse nome")
            prj = Project(name=p.name, area=p.area)
            s.add(prj)
            s.flush()
            return {"id": prj.id}

    def _project(project_id: str) -> str:
        with db.session() as s:
            if s.get(Project, project_id) is None:
                raise HTTPException(404, "projeto inexistente")
        return project_id

    # ------------------------------------------------------------ biblioteca
    lib, kn = st.library, st.knowledge

    @app.get("/api/library/sources")
    def lib_sources():
        return lib.list_sources()

    @app.post("/api/library/sources")
    def lib_add_source(b: SourceIn):
        return {"id": lib.add_source(**b.model_dump())}

    @app.patch("/api/library/sources/{source_id}")
    def lib_update_source(source_id: str, fields: dict[str, Any]):
        lib.update_source(source_id, **fields)
        return {"ok": True}

    @app.post("/api/library/sources/{source_id}/versions")
    def lib_add_version(source_id: str, b: VersionIn):
        return {"id": lib.add_version(source_id, **b.model_dump())}

    @app.post("/api/library/versions/{version_id}/upload")
    async def lib_upload(version_id: str, request: Request, filename: str = "", actor: str = "usuário"):
        data = await request.body()
        if len(data) > 50 * 1024 * 1024:
            raise HTTPException(413, "arquivo maior que 50 MB")
        did = lib.register_found(version_id, None, actor=actor)
        res = lib.ingest(did, data, declared_mime=request.headers.get("content-type"), filename=filename,
                         origin="USER_UPLOAD", actor=actor)
        return res.__dict__

    @app.post("/api/library/apostila")
    async def lib_apostila(request: Request, pages: str, title: str, institution: str = "", year: str = "",
                           actor: str = "usuário"):
        """Recorte de páginas de uma apostila em PDF: texto como fonte secundária e figuras com legenda."""
        data = await request.body()
        if len(data) > 500 * 1024 * 1024:
            raise HTTPException(413, "arquivo maior que 500 MB")
        try:
            return import_apostila(lib, st.settings.media_dir, data, pages=pages, title=title,
                                   institution=institution, year=year or None, actor=actor)
        except ApostilaError as e:
            raise HTTPException(400, str(e)) from e

    @app.post("/api/library/versions/{version_id}/fetch")
    async def lib_fetch(version_id: str, b: FetchIn, actor: str = "usuário"):
        did = lib.register_found(version_id, b.url, actor=actor)
        try:
            data, ctype, final = await (st.fetcher or _safe_fetcher)(b.url)
        except (FetchBlockedError, FetchFailedError, httpx_errors()) as e:
            lib.mark_unavailable(did, f"{type(e).__name__}: {e}", actor=actor)
            raise HTTPException(422, f"não foi possível baixar: {e}") from e
        return lib.ingest(did, data, declared_mime=ctype, fetch_url=final, actor=actor).__dict__

    @app.get("/api/library/documents/{document_id}/sections")
    def lib_sections(document_id: str):
        return lib.sections(document_id)

    @app.post("/api/library/documents/{document_id}/state")
    def lib_state(document_id: str, b: StateIn):
        lib.set_state(document_id, b.state, b.actor, b.reason)
        return {"ok": True}

    @app.get("/api/library/search")
    def lib_search(q: str, institution: str | None = None, tier: str | None = None, validity: str | None = None,
                   year: str | None = None, limit: int = 20):
        return lib.search(q, institution=institution, tier=tier, validity=validity, year=year, limit=limit)

    @app.post("/api/library/evidence")
    def lib_evidence(b: EvidenceIn):
        eid = lib.add_evidence(b.section_id, b.quote, retrieved_via="USER_UPLOAD")
        return lib.evidence(eid)

    # ------------------------------------------------------------ importações
    @app.post("/api/imports/anki")
    async def imp_anki(request: Request, project_id: str, filename: str = "", author: str = ""):
        return AnkiImporter(db).import_export(_project(project_id), await request.body(), filename=filename,
                                              author=author)

    @app.post("/api/imports/questions")
    async def imp_questions(request: Request, project_id: str, filename: str = "", author: str = "",
                            evaluation_pct: int = 20):
        try:
            return import_questions(db, _project(project_id), await request.body(), filename=filename,
                                    author=author, evaluation_pct=evaluation_pct)
        except (ValueError, UnicodeDecodeError) as e:
            raise HTTPException(400, f"arquivo inválido: {e}") from e

    @app.get("/api/imports")
    def imports(project_id: str | None = None):
        from cardfactory.db.models import ImportBatch
        with db.session() as s:
            q = select(ImportBatch).order_by(ImportBatch.created_at.desc()).limit(100)
            if project_id:
                q = q.where(ImportBatch.project_id == project_id)
            return [{"id": b.id, "kind": b.kind, "filename": b.filename, "format": b.format_detected,
                     "created_by": b.created_by, "created_at": b.created_at.isoformat(), "report": b.report}
                    for b in s.execute(q).scalars()]

    # ------------------------------------------------------------ conhecimento
    @app.get("/api/knowledge/entities")
    def kn_entities(project_id: str):
        return kn.overview(project_id)

    @app.get("/api/knowledge/entities/{entity_id}/map")
    def kn_map(entity_id: str, origin: str = "CREATOR"):
        return kn.get_map(entity_id, origin)

    @app.get("/api/knowledge/objectives")
    def kn_objectives(project_id: str | None = None, production_id: str | None = None):
        return kn.objectives(project_id=project_id, production_id=production_id)

    @app.get("/api/knowledge/coverage/{production_id}")
    def kn_coverage(production_id: str):
        return kn.coverage_report(production_id)

    @app.get("/api/knowledge/claims")
    def kn_claims(objective_id: str | None = None, limit: int = 200):
        from cardfactory.db.models import Claim, ClaimEvidence
        with db.session() as s:
            q = select(Claim).order_by(Claim.created_at.desc()).limit(min(limit, 1000))
            if objective_id:
                q = q.where(Claim.objective_id == objective_id)
            out = []
            for c in s.execute(q).scalars():
                evs = list(s.execute(select(ClaimEvidence.evidence_span_id).where(ClaimEvidence.claim_id == c.id))
                           .scalars())
                out.append({"id": c.id, "text": c.text, "component": c.component, "criticality": c.criticality,
                            "population": c.population, "numeric": c.numeric, "objective_id": c.objective_id,
                            "evidence": [lib.evidence(e) for e in evs]})
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
