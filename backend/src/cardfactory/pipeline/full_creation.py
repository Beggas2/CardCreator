"""Grafo do modo "criação integral" (PIPELINE.md).

Reais: pesquisa, leitura, extração, planejamento e objetivos (Fase 2); geração card.v2, validação técnica
e exportação (Fase 3). Ainda simplificadas: auditorias, correção e deduplicação (Fase 4) — suas saídas
carregam `phase: 1` para nunca serem confundidas com auditoria real.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select

from cardfactory.cards.service import CardService
from cardfactory.db import Database
from cardfactory.db.models import Card, CardVersion, Production, ValidationFinding
from cardfactory.export.service import Exporter
from cardfactory.knowledge.service import Knowledge
from cardfactory.library.service import Library
from cardfactory.orchestrator.engine import AwaitingHuman, TaskContext, TaskSpec
from cardfactory.pipeline import generation as gen
from cardfactory.pipeline import research as rs
from cardfactory.pipeline.research import Fetcher, ResearchServices
from cardfactory.prompts.registry import PromptRegistry
from cardfactory.providers.base import LLMRequest
from cardfactory.providers.gateway import LLMGateway

MODE = "FULL_CREATION"

# etapa → (papel do prompt, usa IA)
STAGES: list[tuple[str, str | None]] = [
    ("INVENTORY", None), ("RESEARCH", "researcher"), ("RETRIEVAL", None), ("EXTRACTION", "extractor"),
    ("PLANNING", "planner"), ("OBJECTIVES", None), ("GENERATION", "creator"),
    ("AUDIT_SCI", "auditor_scientific"), ("AUDIT_PED", "auditor_pedagogical"), ("AUDIT_COV", "auditor_coverage"),
    ("CORRECTION", "creator"), ("REAUDIT", "auditor_scientific"), ("DEDUP", "contradiction"),
    ("TECH_VALIDATION", None), ("HUMAN_REVIEW", None), ("EXPORT", None),
]
DEPS: dict[str, list[str]] = {
    "RESEARCH": ["INVENTORY"], "RETRIEVAL": ["RESEARCH"], "EXTRACTION": ["RETRIEVAL"], "PLANNING": ["EXTRACTION"],
    "OBJECTIVES": ["PLANNING"], "GENERATION": ["OBJECTIVES"], "AUDIT_SCI": ["GENERATION"],
    "AUDIT_PED": ["GENERATION"], "AUDIT_COV": ["GENERATION"], "CORRECTION": ["AUDIT_SCI", "AUDIT_PED", "AUDIT_COV"],
    "REAUDIT": ["CORRECTION"], "DEDUP": ["REAUDIT"], "TECH_VALIDATION": ["DEDUP"], "HUMAN_REVIEW": ["TECH_VALIDATION"],
    "EXPORT": ["HUMAN_REVIEW"],
}
RESEARCH_STAGES = ("RESEARCH", "RETRIEVAL", "EXTRACTION", "PLANNING", "OBJECTIVES")
CRITICAL = {"AUDIT_SCI", "REAUDIT", "GENERATION", "CORRECTION", "EXTRACTION"}

STAGE_SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"},
                                                 "limitations": {"type": "array", "items": {"type": "string"}}},
                "required": ["ok", "limitations"]}


def graph(budget_ids: list[str]) -> list[TaskSpec]:
    return [TaskSpec(stage, stage, f"fc.{stage.lower()}", {"budget_ids": budget_ids}, deps=DEPS.get(stage, []),
                     priority=i) for i, (stage, _) in enumerate(STAGES)]


@dataclass
class Services:
    db: Database
    gateway: LLMGateway
    registry: PromptRegistry
    models: dict[str, str]  # etapa → model_id (nunca codificado no código: vem da configuração)
    exports_dir: Path
    library: Library | None = None
    knowledge: Knowledge | None = None
    fetcher: Fetcher | None = None
    media_dir: Path | None = None
    deck_prefix: str = "IGOR"

    def cards(self) -> CardService:
        return CardService(self.db, self.media_dir or self.exports_dir.parent / "media", deck_prefix=self.deck_prefix)

    def exporter(self) -> Exporter:
        return Exporter(self.db, self.exports_dir, self.media_dir or self.exports_dir.parent / "media",
                        deck_prefix=self.deck_prefix)

    def research(self) -> ResearchServices:
        if self.library is None or self.knowledge is None or self.fetcher is None:
            raise RuntimeError("serviços de pesquisa não configurados")
        return ResearchServices(self.db, self.gateway, self.registry, self.library, self.knowledge, self.fetcher,
                                self.models)


def _production(db: Database, run_id: str) -> Production:
    from cardfactory.db.models import Run
    with db.session() as s:
        run = s.get(Run, run_id)
        return s.get(Production, run.production_id)


async def _ai_stage(svc: Services, ctx: TaskContext, role: str, schema: dict, user: str) -> tuple[Any, str]:
    composed = svc.registry.compose(role)
    model = svc.models.get(ctx.stage) or svc.models.get("default")
    if not model:
        raise ValueError(f"nenhum modelo configurado para a etapa {ctx.stage}")
    req = LLMRequest(model_id=model, messages=[{"role": "system", "content": composed.text},
                                               {"role": "user", "content": user}],
                     max_output_tokens=2000, idempotency_key=ctx.call_key(ctx.stage.lower()),
                     response_schema=schema, schema_name=composed.contract.replace(".", "_"))
    r = await svc.gateway.call(req, budget_ids=ctx.input["budget_ids"], task_id=ctx.task_id, stage=ctx.stage,
                               prompt_version_ids=composed.version_ids, prompt_hash=composed.hash,
                               critical=ctx.stage in CRITICAL)
    if r.status != "ok":
        raise RuntimeError(f"saída {r.status} na etapa {ctx.stage}")
    return r.parsed, r.call_id


def handlers(svc: Services) -> dict[str, Any]:
    out: dict[str, Any] = {}

    for stage, role in STAGES:
        if role is None or stage in ("GENERATION", *RESEARCH_STAGES):
            continue

        def make(stage=stage, role=role):
            async def h(ctx: TaskContext) -> dict:
                prd = _production(svc.db, ctx.run_id)
                parsed, call_id = await _ai_stage(svc, ctx, role, STAGE_SCHEMA,
                                                  f"Etapa {stage} para o tema: {prd.theme}")
                return {"phase": 1, "call_id": call_id, "limitations": parsed.get("limitations", [])}
            return h

        out[f"fc.{stage.lower()}"] = make()

    async def inventory(ctx: TaskContext) -> dict:
        prd = _production(svc.db, ctx.run_id)
        with svc.db.session() as s:
            n = len(list(s.execute(select(Card.id).where(Card.project_id == prd.project_id)).scalars()))
        return {"phase": 1, "existing_cards": n}

    async def generation(ctx: TaskContext) -> dict:
        return await gen.generation(svc.research(), ctx, svc.cards())

    async def tech_validation(ctx: TaskContext) -> dict:
        """Validação técnica determinística (C§38): erros abertos ficam listados; nada é aprovado aqui."""
        prd = _production(svc.db, ctx.run_id)
        with svc.db.session() as s:
            cards = list(s.execute(select(Card).where(Card.production_id == prd.id)).scalars())
            with_errors, warnings = [], 0
            for c in cards:
                v = s.execute(select(CardVersion).where(CardVersion.card_id == c.id)
                              .order_by(CardVersion.version_no.desc()).limit(1)).scalar_one()
                levels = s.execute(select(ValidationFinding.level).where(
                    ValidationFinding.card_version_id == v.id, ValidationFinding.status == "OPEN")).scalars().all()
                if "ERROR" in levels:
                    with_errors.append(c.card_key)
                warnings += levels.count("WARNING")
        return {"checked": len(cards), "with_errors": with_errors, "open_warnings": warnings}

    async def human_review(ctx: TaskContext) -> dict:
        raise AwaitingHuman("revisão humana obrigatória antes da exportação (APR-004)")

    async def export(ctx: TaskContext) -> dict:
        """Exporta os cards da produção. Sem aprovação humana registrada, sai como prévia rotulada."""
        prd = _production(svc.db, ctx.run_id)
        res = svc.exporter().export(prd.project_id, "anki_tsv_v2", production_id=prd.id, preview=True,
                                    actor=f"run:{ctx.run_id}")
        manifest = next((f["name"] for f in res["files"] if f["kind"] == "MANIFEST"), None)
        return {"export_id": res["export_id"], "state": res["state"], "dir": res["dir"], "manifest": manifest,
                "counts": res["counts"], "errors": res["errors"][:20]}

    def research_handler(fn):
        async def h(ctx: TaskContext) -> dict:
            return await fn(svc.research(), ctx)
        return h

    for stage, fn in (("RESEARCH", rs.research), ("RETRIEVAL", rs.retrieval), ("EXTRACTION", rs.extraction),
                      ("PLANNING", rs.planning), ("OBJECTIVES", rs.objectives)):
        out[f"fc.{stage.lower()}"] = research_handler(fn)

    out.update({"fc.inventory": inventory, "fc.generation": generation,
                "fc.tech_validation": tech_validation, "fc.human_review": human_review, "fc.export": export})
    return out


from cardfactory.pipeline.simulation import mock_responder  # noqa: E402,F401  (reexportado)
