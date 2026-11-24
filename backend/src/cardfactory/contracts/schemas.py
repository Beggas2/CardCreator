"""Contratos de saída dos papéis de IA (CONTRACTS.md §2), em JSON Schema compatível com modo estrito.

Modo estrito exige `additionalProperties: false` e todas as propriedades em `required`;
campos opcionais usam tipo com `null`. Nenhum contrato tem campo de confiança numérica (AUD-006).
"""

from __future__ import annotations

from typing import Any

from cardfactory.knowledge.dimensions import (
    CLAIM_COMPONENTS,
    COVERAGE_STATES,
    CRITICALITY,
    KNOWLEDGE_LEVELS,
    MAP_STATES,
    NECESSITY,
    NEGATION_KINDS,
)


def obj(props: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "properties": props, "required": list(props)}


def arr(items: dict[str, Any], **kw: Any) -> dict[str, Any]:
    return {"type": "array", "items": items, **kw}


STR = {"type": "string"}
NSTR = {"type": ["string", "null"]}
LIMITATIONS = arr(STR)


def enum(values: tuple[str, ...], nullable: bool = False) -> dict[str, Any]:
    if nullable:
        return {"type": ["string", "null"], "enum": [*values, None]}
    return {"type": "string", "enum": list(values)}


RESEARCH_RESULT_V1 = obj({
    "searches": arr(STR),
    "candidates": arr(obj({
        "title_claimed": STR,
        "institution": STR,
        "url": STR,
        "doc_type": STR,
        "year_claimed": NSTR,
        "tier_claimed": enum(("BR_OFFICIAL", "BR_SOCIETY", "INTL_SOCIETY", "SYSTEMATIC_REVIEW", "PRIMARY_STUDY",
                              "SECONDARY_CLINICAL", "NOT_ACCEPTED")),
        "why_relevant": STR,
    }), maxItems=25),
    "unavailable": arr(obj({"description": STR, "reason": STR})),
    "limitations": LIMITATIONS,
})

EXTRACTION_V1 = obj({
    "claims": arr(obj({
        "section_id": STR,
        "quote": STR,
        "text": STR,
        "component": enum(CLAIM_COMPONENTS),
        "population": STR,
        "scenario": STR,
        "criticality": enum(CRITICALITY),
        "negation_kind": enum(NEGATION_KINDS, nullable=True),
        "numeric_value": {"type": ["number", "null"]},
        "numeric_unit": NSTR,
        "numeric_operator": {"type": ["string", "null"], "enum": ["=", "<", "≤", ">", "≥", "range", None]},
        "conditions": arr(STR),
    })),
    "unreadable_sections": arr(obj({"section_id": STR, "reason": STR})),
    "limitations": LIMITATIONS,
})

PLAN_V1 = obj({
    "entities": arr(obj({
        "name": STR,
        "synonyms": arr(STR),
        "home_deck_path": STR,
        "dimensions": arr(obj({"code": {"type": "integer", "minimum": 1, "maximum": 57},
                               "state": enum(MAP_STATES), "justification": STR}), minItems=57, maxItems=57),
        "decision_points": arr(obj({"description": STR, "condition_axis": STR, "disposition_relevant":
                                    {"type": "boolean"}})),
    }), minItems=1),
    "objectives": arr(obj({
        "ref": STR,
        "entity": STR,
        "subtopic": STR,
        "description": STR,
        "knowledge_level": enum(KNOWLEDGE_LEVELS),
        "knowledge_type": STR,
        "necessity": enum(NECESSITY),
        "purpose": STR,
        "clinical_relevance": enum(("HIGH", "MEDIUM", "LOW")),
        "coverage_state": enum(COVERAGE_STATES),
        "claim_ids": arr(STR),
        "depends_on": arr(STR),
        "planned_cards": {"type": "integer", "minimum": 0, "maximum": 20},
        "planned_rationale": STR,
    })),
    "limitations": LIMITATIONS,
})

CONTRACTS: dict[str, dict[str, Any]] = {
    "research_result.v1": RESEARCH_RESULT_V1,
    "extraction.v1": EXTRACTION_V1,
    "plan.v1": PLAN_V1,
}


def schema_name(contract: str) -> str:
    return contract.replace(".", "_")
