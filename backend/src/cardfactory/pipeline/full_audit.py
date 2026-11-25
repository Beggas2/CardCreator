"""Modo "auditoria integral" de um deck existente (E§ modos de operação; AUD-001…AUD-010).

Diferenças em relação à criação integral:
- não há planejamento nem geração: o INVENTÁRIO vincula à produção os cards já existentes (importados ou não);
- a pesquisa, a leitura e a extração montam o acervo de evidências do tema; os auditores recebem, para cada
  card sem afirmações vinculadas, os trechos do acervo mais próximos (seleção lexical, sem custo);
- auditorias, correção (cards legados são convertidos para card.v2 quando corrigidos), reauditoria,
  deduplicação, validação técnica, revisão humana e exportação são as mesmas etapas da criação integral.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from cardfactory.db.models import Card, CardStateEvent, CardVersion
from cardfactory.orchestrator.engine import AwaitingHuman, TaskContext, TaskSpec
from cardfactory.pipeline import full_creation as fc
from cardfactory.pipeline.research import production_of

MODE = "FULL_AUDIT"

STAGES: list[tuple[str, str | None]] = [
    ("INVENTORY", None), ("RESEARCH", "researcher"), ("RETRIEVAL", None), ("EXTRACTION", "extractor"),
    ("AUDIT_SCI", "auditor_scientific"), ("AUDIT_PED", "auditor_pedagogical"), ("AUDIT_SEC", "auditor_security"),
    ("AUDIT_COV", "auditor_coverage"), ("CORRECTION", "corrector"), ("REAUDIT", "auditor_scientific"),
    ("DEDUP", "contradiction"), ("TECH_VALIDATION", None), ("HUMAN_REVIEW", None), ("EXPORT", None),
]
DEPS: dict[str, list[str]] = {
    "RESEARCH": ["INVENTORY"], "RETRIEVAL": ["RESEARCH"], "EXTRACTION": ["RETRIEVAL"],
    "AUDIT_SCI": ["EXTRACTION"], "AUDIT_PED": ["INVENTORY"], "AUDIT_SEC": ["INVENTORY"], "AUDIT_COV": ["EXTRACTION"],
    "CORRECTION": ["AUDIT_SCI", "AUDIT_PED", "AUDIT_SEC", "AUDIT_COV"], "REAUDIT": ["CORRECTION"],
    "DEDUP": ["REAUDIT"], "TECH_VALIDATION": ["DEDUP"], "HUMAN_REVIEW": ["TECH_VALIDATION"],
    "EXPORT": ["HUMAN_REVIEW"],
}


def graph(budget_ids: list[str]) -> list[TaskSpec]:
    return [TaskSpec(stage, stage, "fa.inventory" if stage == "INVENTORY" else f"fc.{stage.lower()}",
                     {"budget_ids": budget_ids}, deps=DEPS.get(stage, []), priority=i)
            for i, (stage, _) in enumerate(STAGES)]


def select_cards(db, project_id: str, scope: dict[str, Any]) -> list[str]:
    """Cards do projeto escolhidos pelo escopo: `card_ids`, `import_batch_ids` e/ou prefixo de `deck_prefix`.
    Sem filtro, todos os cards não rejeitados do projeto."""
    card_ids = scope.get("card_ids") or []
    batches = scope.get("import_batch_ids") or []
    prefix = (scope.get("deck_prefix") or "").strip()
    with db.session() as s:
        q = select(Card).where(Card.project_id == project_id, Card.state != "REJECTED").order_by(Card.created_at)
        if card_ids:
            q = q.where(Card.id.in_(card_ids))
        if batches:
            q = q.where(Card.import_batch_id.in_(batches))
        out = []
        for c in s.execute(q).scalars():
            if prefix:
                v = s.execute(select(CardVersion.deck_path).where(CardVersion.card_id == c.id)
                              .order_by(CardVersion.version_no.desc()).limit(1)).scalar_one()
                if not (v == prefix or v.startswith(prefix + "::")):
                    continue
            out.append(c.id)
        return out


def handlers(svc: fc.Services) -> dict[str, Any]:
    out = fc.handlers(svc)

    async def inventory(ctx: TaskContext) -> dict:
        """Vincula os cards escolhidos a esta produção. Nada é apagado nem alterado no conteúdo."""
        prd = production_of(svc.db, ctx.run_id)
        ids = select_cards(svc.db, prd.project_id, prd.scope or {})
        if not ids:
            raise AwaitingHuman("nenhum card corresponde ao escopo da auditoria")
        legacy = 0
        with svc.db.write() as s:
            for cid in ids:
                card = s.get(Card, cid)
                if card.production_id != prd.id:
                    s.add(CardStateEvent(card_id=cid, from_state=card.state, to_state=card.state,
                                         actor=f"run:{ctx.run_id}", actor_type="SYSTEM",
                                         reason=f"incluído na auditoria integral {prd.id} (antes: "
                                                f"{card.production_id or 'sem produção'})"))
                    card.production_id = prd.id
                v = s.execute(select(CardVersion.schema_version).where(CardVersion.card_id == cid)
                              .order_by(CardVersion.version_no.desc()).limit(1)).scalar_one()
                legacy += v != "2.1"
        return {"cards": len(ids), "legacy": legacy, "card_v2": len(ids) - legacy}

    out["fa.inventory"] = inventory
    return out
