"""Execução da Etapa 1 do experimento (BENCHMARK_PROTOCOL §5), em três passos independentes:

1. `prepare`: pesquisa, leitura, extração e planejamento de um tema-piloto, uma vez só, com o modelo de apoio.
   O resultado (fontes, afirmações com trecho literal, objetivos) é o contexto comum da Rodada A.
2. `round_a`: cada criador recebe exatamente o mesmo prompt para os mesmos objetivos; os cards de cada um ficam
   numa produção própria e passam pela auditoria científica do mesmo auditor fixo e pelas varreduras.
3. `round_b`: auditores candidatos contra o conjunto de defeitos conhecidos (dev), via BenchmarkService.

Nada aqui escolhe modelo: os IDs vêm da lista aprovada pela proprietária. Toda chamada passa pelo gateway, com
orçamento e autorização; ao atingir o limite, a chamada é recusada antes de ser enviada.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from cardfactory.audit.service import AuditService
from cardfactory.config import Settings
from cardfactory.contracts.schemas import GENERATION_BATCH_V1, schema_name
from cardfactory.db import Database
from cardfactory.db.models import (
    Claim,
    ClaimEvidence,
    Defect,
    LearningObjective,
    LLMCall,
    Production,
    Project,
    Run,
    Task,
)
from cardfactory.finance.budget import FinanceService
from cardfactory.knowledge.service import Knowledge
from cardfactory.library.service import Library
from cardfactory.orchestrator.engine import ContractViolation, Orchestrator
from cardfactory.pipeline import audit as au
from cardfactory.pipeline import full_audit, full_creation
from cardfactory.pipeline import generation as gen
from cardfactory.prompts.registry import PromptRegistry
from cardfactory.providers.base import LLMProvider, LLMRequest
from cardfactory.providers.gateway import LLMGateway

PROJECT = "Experimento Etapa 1"
PREP_STAGES = ("INVENTORY", "RESEARCH", "RETRIEVAL", "EXTRACTION", "PLANNING", "OBJECTIVES")
MAX_CARDS_A = 10
SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "OBSERVATION")


@dataclass
class Env:
    settings: Settings
    db: Database
    finance: FinanceService
    registry: PromptRegistry
    library: Library
    knowledge: Knowledge
    gateway: LLMGateway
    fetcher: Any = None


def build_env(settings: Settings, db: Database, provider: LLMProvider, fetcher=None) -> Env:
    finance = FinanceService(db)
    registry = PromptRegistry(db, settings.prompts_dir, settings.normative_dir)
    registry.import_library()
    if fetcher is None:
        from cardfactory.security.fetch import safe_fetch

        async def fetcher(url: str):
            r = await safe_fetch(url)
            return r.data, r.content_type, r.final_url
    return Env(settings, db, finance, registry, Library(db, settings.data_dir / "blobs"), Knowledge(db),
               LLMGateway(db, finance, provider), fetcher)


def _services(env: Env, models: dict[str, str]) -> full_creation.Services:
    s = env.settings
    return full_creation.Services(env.db, env.gateway, env.registry, models, s.exports_dir, env.library,
                                  env.knowledge, env.fetcher, s.media_dir, s.deck_prefix)


@dataclass
class _Ctx:
    """Contexto mínimo de tarefa para chamar as etapas fora do grafo (mesmas regras, chaves próprias)."""
    run_id: str
    stage: str
    input: dict[str, Any]
    task_id: str | None = None  # fora do grafo: sem tarefa (chave estrangeira)
    checkpoint: dict[str, Any] = field(default_factory=dict)

    def call_key(self, name: str) -> str:
        return f"exp:{self.run_id}:{self.stage}:{name}"

    def save_checkpoint(self, data: dict[str, Any]) -> None:
        self.checkpoint = dict(data)

    def dep_outputs(self) -> dict[str, Any]:
        return {}


def _cost(db: Database, prefix: str) -> Decimal:
    with db.session() as s:
        rows = s.execute(select(LLMCall.cost_usd).where(LLMCall.idempotency_key.like(f"{prefix}%"))).scalars()
        return sum((Decimal(str(c)) for c in rows if c is not None), Decimal(0))


def _run_cost(db: Database, run_id: str) -> Decimal:
    """Custo das chamadas feitas pelas tarefas de uma execução do grafo (chaves por tarefa)."""
    with db.session() as s:
        rows = s.execute(select(LLMCall.cost_usd).join(Task, Task.id == LLMCall.task_id)
                         .where(Task.run_id == run_id)).scalars()
        return sum((Decimal(str(c)) for c in rows if c is not None), Decimal(0))


# ---------------------------------------------------------------------------- preparação
async def prepare(env: Env, *, theme: str, support_model: str, budget_id: str, web_search: dict | None = None,
                  web_search_price_usd: str | None = None, target_cards: int = 30,
                  research_model: str | None = None) -> dict[str, Any]:
    models = {"default": support_model} | ({"RESEARCH": research_model} if research_model else {})
    with env.db.write() as s:
        prj = s.execute(select(Project).where(Project.name == PROJECT)).scalar_one_or_none()
        if prj is None:
            prj = Project(name=PROJECT)
            s.add(prj)
            s.flush()
        scope: dict[str, Any] = {"models": models, "experiment": "etapa1-preparo"}
        if web_search:
            scope |= {"web_search": web_search, "web_search_price_usd": web_search_price_usd}
        prd = Production(project_id=prj.id, mode=full_creation.MODE, theme=theme, target_cards=target_cards,
                         provider=env.gateway.provider.name, research_mode="AUTONOMOUS", scope=scope)
        s.add(prd)
        s.flush()
        prd_id = prd.id
    orch = Orchestrator(env.db, full_audit.handlers(_services(env, models)))
    specs = [t for t in full_creation.graph([budget_id]) if t.stage in PREP_STAGES]
    run_id = orch.create_run(prd_id, full_creation.MODE, specs, note="Etapa 1: preparo do tema-piloto")
    orch.start(run_id)
    state = await orch.run_until_idle(run_id, concurrency=1)
    with env.db.session() as s:
        tasks = {t.stage: {"state": t.state, "error": t.last_error} for t in
                 s.execute(select(Task).where(Task.run_id == run_id)).scalars()}
    return {"production_id": prd_id, "run_id": run_id, "state": state, "tasks": tasks,
            "ready_objectives": ready_objectives(env, prd_id), "cost_usd": str(_run_cost(env.db, run_id))}


def ready_objectives(env: Env, prd_id: str) -> list[str]:
    """Objetivos obrigatórios/recomendados com ao menos uma afirmação sustentada por trecho."""
    with env.db.session() as s:
        objs = list(s.execute(select(LearningObjective).where(
            LearningObjective.production_id == prd_id,
            LearningObjective.necessity.in_(["REQUIRED", "RECOMMENDED"])).order_by(LearningObjective.created_at))
            .scalars())
        supported = set(s.execute(select(Claim.objective_id).join(ClaimEvidence, ClaimEvidence.claim_id == Claim.id)
                                  .where(Claim.objective_id.in_([o.id for o in objs]),
                                         ClaimEvidence.supports.in_(["SUPPORTS", "PARTIAL"]))).scalars())
        return [o.id for o in objs if o.id in supported]


def pick_objectives(env: Env, prd_id: str, n: int = 5) -> list[str]:
    """Escolha determinística e diversa: alterna tipos de conhecimento na ordem do plano."""
    ready = ready_objectives(env, prd_id)
    with env.db.session() as s:
        kinds = dict(s.execute(select(LearningObjective.id, LearningObjective.knowledge_type)
                               .where(LearningObjective.id.in_(ready))).all())
    groups: dict[str, list[str]] = {}
    for oid in ready:
        groups.setdefault(kinds.get(oid) or "", []).append(oid)
    out: list[str] = []
    while len(out) < n and any(groups.values()):
        for g in list(groups):
            if groups[g] and len(out) < n:
                out.append(groups[g].pop(0))
    return out


# ---------------------------------------------------------------------------- Rodada A
async def _one_creator(env: Env, pilot: Production, objective_ids: list[str], model: str, auditor: str,
                       budget_id: str) -> dict[str, Any]:
    with env.db.write() as s:
        sub = Production(project_id=pilot.project_id, mode=full_creation.MODE, theme=f"{pilot.theme} · A · {model}",
                         target_cards=MAX_CARDS_A, provider=pilot.provider, research_mode=pilot.research_mode,
                         scope={"experiment": "etapa1-A", "pilot_production_id": pilot.id, "creator": model,
                                "auditor": auditor, "objective_ids": objective_ids})
        s.add(sub)
        s.flush()
        run = Run(production_id=sub.id, mode="EXPERIMENT_A", state="RUNNING", note=f"Rodada A · {model}")
        s.add(run)
        s.flush()
        sub_id, run_id = sub.id, run.id
    svc = _services(env, {"GENERATION": model, "AUDIT_SCI": auditor})
    rs, cards = svc.research(), svc.cards()
    out: dict[str, Any] = {"model": model, "production_id": sub_id, "run_id": run_id, "status": None, "cards": 0,
                           "rejected": 0, "rejected_examples": [], "audit": None, "defects_open": {}}
    c = gen._context(rs, objective_ids)
    composed = env.registry.compose("creator")
    req = LLMRequest(model_id=model, messages=[{"role": "system", "content": composed.text},
                                               {"role": "user", "content": gen._prompt(pilot, c, cards.deck_prefix,
                                                                                       MAX_CARDS_A)}],
                     max_output_tokens=32000, idempotency_key=f"exp:{run_id}:GENERATION:a",
                     response_schema=GENERATION_BATCH_V1, schema_name=schema_name(composed.contract))
    t0 = time.monotonic()
    r = await env.gateway.call(req, budget_ids=[budget_id], stage="EXP_A_GENERATION",
                               prompt_version_ids=composed.version_ids, prompt_hash=composed.hash, critical=True)
    out["seconds"] = round(time.monotonic() - t0, 1)
    out["status"] = r.status
    if r.status != "ok":
        out["error"] = str(getattr(r, "error", "") or r.status)[:300]
    else:
        ids = set(objective_ids)
        for i, card in enumerate(r.parsed["cards"][:MAX_CARDS_A]):
            errs = gen._semantic_errors(card, c, ids)
            if errs:
                out["rejected"] += 1
                if len(out["rejected_examples"]) < 3:
                    out["rejected_examples"].append({"index": i, "errors": errs[:3]})
                continue
            cards.create(pilot.project_id, card, production_id=sub_id, origin="GENERATED", author_type="AI",
                         actor=r.call_id, call_id=r.call_id, didactic_order=out["cards"])
            out["cards"] += 1
        out["objectives_covered"] = len({o for cd in r.parsed["cards"] for o in cd.get("objective_ids", [])} & ids)
    if out["cards"]:
        with env.db.session() as s:
            sub_prd = s.get(Production, sub_id)
            s.expunge(sub_prd)
        try:
            out["audit"] = await au._scientific(rs, _Ctx(run_id, "AUDIT_SCI", {"budget_ids": [budget_id]}), sub_prd,
                                                au._cards(rs, sub_prd), AuditService(env.db), "sci")
        except ContractViolation as e:
            out["audit_error"] = str(e)[:300]
        with env.db.session() as s:
            out["defects_open"] = dict(s.execute(select(Defect.severity, func.count()).where(
                Defect.production_id == sub_id, Defect.status == "OPEN").group_by(Defect.severity)).all())
    with env.db.write() as s:
        s.get(Run, run_id).state = "COMPLETED"
    out["cost_usd"] = str(_cost(env.db, f"exp:{run_id}:"))
    return out


async def round_a(env: Env, *, pilot_production_id: str, objective_ids: list[str], creators: list[str],
                  auditor: str, budget_id: str) -> dict[str, Any]:
    with env.db.session() as s:
        pilot = s.get(Production, pilot_production_id)
        s.expunge(pilot)
    results = []
    for model in creators:
        try:
            results.append(await _one_creator(env, pilot, objective_ids, model, auditor, budget_id))
        except Exception as e:  # noqa: BLE001 - um criador que falha não derruba os outros; fica registrado
            results.append({"model": model, "status": "error", "error": f"{type(e).__name__}: {e}"[:300]})
    return {"objective_ids": objective_ids, "auditor": auditor, "results": results}


# ---------------------------------------------------------------------------- Rodada B
async def round_b(env: Env, *, auditors: list[str], budget_id: str, actor: str) -> list[dict[str, Any]]:
    from cardfactory.benchmark.service import BenchmarkService

    bench = BenchmarkService(env.db, env.registry)
    if not bench.summary()["sets"]:
        bench.load_sets()
    out = []
    for m in auditors:
        try:
            r = await bench.run("KNOWN_DEFECTS", "dev", "auditor_scientific", actor=actor, gateway=env.gateway,
                                provider=env.gateway.provider.name, models={"auditor_scientific": m},
                                budget_ids=[budget_id])
            out.append({"model": m, **r})
        except Exception as e:  # noqa: BLE001
            out.append({"model": m, "error": f"{type(e).__name__}: {e}"[:300]})
    return out


# ---------------------------------------------------------------------------- produção completa
async def full_run(env: Env, *, theme: str, models: dict[str, str], budget_id: str, target_cards: int,
                   web_search: dict | None = None, web_search_price_usd: str | None = None,
                   document_ids: list[str] | None = None, update_since: str | None = None) -> dict[str, Any]:
    """Uma produção de ponta a ponta pelo grafo normal (para na revisão humana obrigatória).

    Com document_ids, a produção usa só esses documentos (ex.: apostila) e, com update_since, faz a checagem
    de diretrizes posteriores na web."""
    with env.db.write() as s:
        prj = s.execute(select(Project).where(Project.name == PROJECT)).scalar_one_or_none()
        if prj is None:
            prj = Project(name=PROJECT)
            s.add(prj)
            s.flush()
        scope: dict[str, Any] = {"models": models, "experiment": "etapa1-completo"}
        if web_search:
            scope |= {"web_search": web_search, "web_search_price_usd": web_search_price_usd}
        mode = "AUTONOMOUS"
        if document_ids:
            mode = "UPLOADED"
            scope["document_ids"] = list(document_ids)
            if update_since:
                scope["update_check"] = {"since": update_since, "max_sources": 2}
        prd = Production(project_id=prj.id, mode=full_creation.MODE, theme=theme, target_cards=target_cards,
                         provider=env.gateway.provider.name, research_mode=mode, scope=scope)
        s.add(prd)
        s.flush()
        prd_id = prd.id
    orch = Orchestrator(env.db, full_audit.handlers(_services(env, models)))
    run_id = orch.create_run(prd_id, full_creation.MODE, full_creation.graph([budget_id]),
                             note="Etapa 1: produção completa curta")
    orch.start(run_id)
    state = await orch.run_until_idle(run_id, concurrency=2)
    with env.db.session() as s:
        tasks = {t.stage: {"state": t.state, "error": t.last_error, "output": t.output} for t in
                 s.execute(select(Task).where(Task.run_id == run_id)).scalars()}
    return {"production_id": prd_id, "run_id": run_id, "state": state, "tasks": tasks,
            "cost_usd": str(_run_cost(env.db, run_id))}
