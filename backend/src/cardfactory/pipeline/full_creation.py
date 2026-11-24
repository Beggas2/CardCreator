"""Grafo do modo "criação integral" (PIPELINE.md) com handlers da Fase 1.

Os handlers são reais em persistência, custo, prompts e estados, mas o conteúdo médico
ainda não é produzido: contratos completos (card.v2, auditorias) chegam nas fases 2–4.
Saídas desta fase carregam `phase: 1` para nunca serem confundidas com conteúdo validado.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select

from cardfactory.db import Database
from cardfactory.db.models import Card, CardStateEvent, CardVersion, Production
from cardfactory.orchestrator.engine import AwaitingHuman, TaskContext, TaskSpec
from cardfactory.prompts.registry import PromptRegistry
from cardfactory.providers.base import LLMRequest
from cardfactory.providers.gateway import LLMGateway

MODE = "FULL_CREATION"

# etapa → (papel do prompt, usa IA)
STAGES: list[tuple[str, str | None]] = [
    ("INVENTORY", None), ("RESEARCH", "researcher"), ("RETRIEVAL", None), ("EXTRACTION", "extractor"),
    ("PLANNING", "planner"), ("OBJECTIVES", "planner"), ("GENERATION", "creator"),
    ("AUDIT_SCI", "auditor_scientific"), ("AUDIT_PED", "auditor_pedagogical"), ("AUDIT_COV", "auditor_coverage"),
    ("CORRECTION", "resolver"), ("REAUDIT", "auditor_scientific"), ("DEDUP", "classifier"),
    ("TECH_VALIDATION", None), ("HUMAN_REVIEW", None), ("EXPORT", None),
]
DEPS: dict[str, list[str]] = {
    "RESEARCH": ["INVENTORY"], "RETRIEVAL": ["RESEARCH"], "EXTRACTION": ["RETRIEVAL"], "PLANNING": ["EXTRACTION"],
    "OBJECTIVES": ["PLANNING"], "GENERATION": ["OBJECTIVES"], "AUDIT_SCI": ["GENERATION"],
    "AUDIT_PED": ["GENERATION"], "AUDIT_COV": ["GENERATION"], "CORRECTION": ["AUDIT_SCI", "AUDIT_PED", "AUDIT_COV"],
    "REAUDIT": ["CORRECTION"], "DEDUP": ["REAUDIT"], "TECH_VALIDATION": ["DEDUP"], "HUMAN_REVIEW": ["TECH_VALIDATION"],
    "EXPORT": ["HUMAN_REVIEW"],
}
CRITICAL = {"AUDIT_SCI", "REAUDIT", "GENERATION", "CORRECTION", "EXTRACTION"}

STAGE_SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"},
                                                 "limitations": {"type": "array", "items": {"type": "string"}}},
                "required": ["ok", "limitations"]}
GEN_SCHEMA = {"type": "object", "required": ["cards", "limitations"], "properties": {
    "limitations": {"type": "array", "items": {"type": "string"}},
    "cards": {"type": "array", "items": {"type": "object", "required": ["front", "essential"], "properties": {
        "front": {"type": "string", "minLength": 1}, "essential": {"type": "string", "minLength": 1}}}}}}


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
        if role is None or stage == "GENERATION":
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

    async def retrieval(ctx: TaskContext) -> dict:
        return {"phase": 1, "documents": 0, "limitations": ["biblioteca de fontes chega na Fase 2"]}

    async def generation(ctx: TaskContext) -> dict:
        prd = _production(svc.db, ctx.run_id)
        if "card_ids" in ctx.checkpoint:  # retomada: cards já gravados
            return {"phase": 1, "card_ids": ctx.checkpoint["card_ids"]}
        parsed, call_id = await _ai_stage(svc, ctx, "creator", GEN_SCHEMA,
                                          f"Gere até {prd.target_cards} cards sobre: {prd.theme}")
        ids = []
        with svc.db.write() as s:
            for c in parsed["cards"][: prd.target_cards]:
                card = Card(project_id=prd.project_id, production_id=prd.id, state="GENERATED",
                            origin="MOCK" if svc.gateway.provider.name == "mock" else "GENERATED")
                s.add(card)
                s.flush()
                content = {"front": c["front"], "essential": c["essential"], "phase": 1}
                s.add(CardVersion(card_id=card.id, version_no=1, content=content, created_by_call_id=call_id,
                                  content_hash=hashlib.sha256(json.dumps(content, sort_keys=True).encode())
                                  .hexdigest()))
                s.add(CardStateEvent(card_id=card.id, from_state="DRAFT", to_state="GENERATED", actor=call_id,
                                     actor_type="AI", reason="geração"))
                ids.append(card.id)
        ctx.save_checkpoint({"card_ids": ids})
        return {"phase": 1, "card_ids": ids, "call_id": call_id, "limitations": parsed["limitations"]}

    async def tech_validation(ctx: TaskContext) -> dict:
        prd = _production(svc.db, ctx.run_id)
        problems = []
        with svc.db.session() as s:
            cards = list(s.execute(select(Card).where(Card.production_id == prd.id)).scalars())
            for c in cards:
                v = s.execute(select(CardVersion).where(CardVersion.card_id == c.id)
                              .order_by(CardVersion.version_no.desc()).limit(1)).scalar_one()
                if not v.content.get("front") or not v.content.get("essential"):
                    problems.append(c.id)
        return {"phase": 1, "checked": len(cards), "problems": problems}

    async def human_review(ctx: TaskContext) -> dict:
        raise AwaitingHuman("revisão humana obrigatória antes da exportação (APR-004)")

    async def export(ctx: TaskContext) -> dict:
        prd = _production(svc.db, ctx.run_id)
        with svc.db.session() as s:
            cards = [{"card_key": c.card_key, "state": c.state, "origin": c.origin}
                     for c in s.execute(select(Card).where(Card.production_id == prd.id)).scalars()]
        d = svc.exports_dir / ctx.run_id
        d.mkdir(parents=True, exist_ok=True)
        path = d / "manifesto_preliminar.json"
        path.write_text(json.dumps({"run_id": ctx.run_id, "phase": 1, "cards": cards,
                                    "aviso": "Manifesto preliminar. Exportação TSV para o Anki chega na Fase 3."},
                                   ensure_ascii=False, indent=2), encoding="utf-8")
        return {"phase": 1, "manifest": str(path), "cards": len(cards)}

    out.update({"fc.inventory": inventory, "fc.retrieval": retrieval, "fc.generation": generation,
                "fc.tech_validation": tech_validation, "fc.human_review": human_review, "fc.export": export})
    return out


def mock_responder(req: LLMRequest) -> dict:
    """Respostas determinísticas do provedor simulado para o grafo da Fase 1."""
    if req.schema_name == "card_v2":
        return {"limitations": ["conteúdo simulado"],
                "cards": [{"front": f"[SIMULADO] Pergunta {i + 1}?", "essential": f"[SIMULADO] Resposta {i + 1}"}
                          for i in range(3)]}
    return {"ok": True, "limitations": ["resposta simulada"]}
