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
        # anyOf em vez de type: [string, null] + enum: o validador estrito da Anthropic recusa a forma combinada.
        return {"anyOf": [{"type": "string", "enum": list(values)}, {"type": "null"}]}
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
        "numeric_operator": enum(("=", "<", "≤", ">", "≥", "range"), nullable=True),
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

# ------------------------------------------------------------------ card.v2 (CONTRACTS.md §1)
COGNITIVE_TYPES = tuple("ABCDEFGHIJKL")
LAYOUTS = ("direct", "list", "criteria", "comparison", "score", "mechanism", "algorithm", "pharmacology", "case",
           "negative", "image", "integration")
SEMANTICS = ("concept", "conduct", "diagnosis", "value", "risk", "neutral", "complement", "reference", "divergence")
ROLES = ("essential", "understanding", "complement")
BLOCKS = ("paragraph", "list", "ordered_list", "table", "comparison", "sequence", "formula")
COMBINATION_RULES = ("all", "any", "at_least_n", "major_minor", "mutually_exclusive")
FRONT_EMPHASIS = ("none", "retrieval_object")

SEGMENT = obj({
    "text": STR,
    "semantic": enum(SEMANTICS),
    "retrieval_target": {"type": "boolean"},
    "italic": {"type": "boolean"},  # só nomenclatura científica, termos estrangeiros e convenções (C§18.3)
    "claim_ids": arr(STR),
})
ITEM = obj({
    "segments": arr(SEGMENT),             # blocos de texto (paragraph, list, ordered_list, sequence, formula)
    "cells": arr(obj({"segments": arr(SEGMENT)})),  # blocos tabulares (table, comparison): uma linha
})
BLOCK = obj({
    "role": enum(ROLES),
    "block": enum(BLOCKS),
    "title": NSTR,
    "header": {"type": ["array", "null"], "items": STR},   # cabeçalho de colunas (table, comparison)
    "items": arr(ITEM, minItems=1),
    "combination_rule": enum(COMBINATION_RULES, nullable=True),
    "combination_n": {"type": ["integer", "null"], "minimum": 1},
    "combination_text": NSTR,
})
CARD_V2_MODEL = obj({
    "objective_ids": arr(STR),
    "deck_path": arr(STR, minItems=1),
    "cognitive_type": enum(COGNITIVE_TYPES),
    "layout": enum(LAYOUTS),
    "front": obj({"segments": arr(obj({"text": STR, "emphasis": enum(FRONT_EMPHASIS), "italic": {"type": "boolean"}}),
                                  minItems=1),
                  "align": enum(("auto", "center", "left"))}),
    "minimal_answer": STR,
    "answer": arr(BLOCK, minItems=1),
    "short_reference": {"type": ["object", "null"], "additionalProperties": False,
                        "properties": {"source_ids": arr(STR), "display": STR},
                        "required": ["source_ids", "display"]},
    "tags": arr(STR),
    "claims": arr(obj({"claim_id": STR, "text": STR, "component": enum(CLAIM_COMPONENTS),
                       "criticality": enum(CRITICALITY), "population": STR})),
    "evidence_span_ids": arr(STR),
    "media_requests": arr(obj({"finding": STR, "desired_source": STR, "purpose": STR})),
    "limitations": LIMITATIONS,
})
SYSTEM_FIELDS = {
    "schema_version": {"type": "string", "const": "2.1"},
    "card_key": STR,
    "anki_guid": NSTR,
    "images": arr(obj({"file": STR, "alt": STR, "side": enum(("front", "back"))})),
    "validation_status": enum(("pending", "valid", "invalid")),
}
CARD_V2 = obj({**SYSTEM_FIELDS, **CARD_V2_MODEL["properties"]})

GENERATION_BATCH_V1 = obj({
    "cards": arr(CARD_V2_MODEL),
    "unverified_claims": arr(obj({"text": STR, "objective_id": STR, "reason": STR})),
    "limitations": LIMITATIONS,
})

# ------------------------------------------------------------------ auditoria (Fase 4)
DEFECT_CATEGORIES = ("SCIENTIFIC_ERROR", "OUTDATED", "UNRESOLVED_UNCERTAINTY", "IMPRECISION", "AMBIGUITY", "GAP",
                     "OMITTED_CONTRAINDICATION", "NUMERIC_ERROR", "PHARMACOLOGY_ERROR", "UNIDENTIFIED_DIVERGENCE",
                     "PEDAGOGICAL", "GRANULARITY", "REDUNDANCY", "CONTRADICTION", "ALLOCATION", "VISUAL", "TECHNICAL",
                     "REGRESSION", "TRACEABILITY")  # R§36.1 (19)
SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "OBSERVATION")
PED_DIMENSIONS = ("clarity", "independence", "retrieval", "self_assessment", "granularity", "cognitive_load",
                  "redundancy", "causality", "discrimination", "transfer", "application", "cognitive_type", "front",
                  "essential", "complements", "visual", "ergonomics")  # PED-016 (17)
OPERATIONS = ("KEEP", "UPDATE_CONTENT", "UPDATE_FRONT", "UPDATE_PEDAGOGY", "UPDATE_STYLE", "MOVE", "CREATE", "SPLIT",
              "MERGE_REVIEW", "REVIEW_DELETE", "QUARANTINE", "REVIEW_REQUIRED")  # R§37
SIMILARITY_KINDS = ("USEFUL_REDUNDANCY", "UNNECESSARY_REDUNDANCY", "INTEGRATION", "CONTRADICTION",
                    "LEGITIMATE_DIVERGENCE", "NEW_CONTEXT_APPLICATION", "CONTRAST", "UNRELATED")  # DED-001
VERDICT_VALUES = ("CONFIRMED", "INCORRECT", "OUTDATED", "INCOMPLETE", "AMBIGUOUS", "CONTEXT_DEPENDENT", "DIVERGENT",
                  "NOT_VERIFIED", "NOT_APPLICABLE")

DEFECT = obj({"card_ref": STR, "category": enum(DEFECT_CATEGORIES), "severity": enum(SEVERITIES),
              "description": STR, "evidence_span_ids": arr(STR)})

SCI_AUDIT_V1 = obj({
    "claims": arr(obj({"card_ref": STR, "claim_ref": STR, "text": STR, "component": enum(CLAIM_COMPONENTS),
                       "criticality": enum(CRITICALITY), "verdict": enum(VERDICT_VALUES),
                       "evidence_span_ids": arr(STR), "rationale": STR, "needs_more_evidence": {"type": "boolean"}})),
    "defects": arr(DEFECT),
    "research_requests": arr(obj({"card_ref": STR, "question": STR})),
    "limitations": LIMITATIONS,
})
PED_AUDIT_V1 = obj({
    "cards": arr(obj({
        "card_ref": STR,
        "findings": arr(obj({"dimension": enum(PED_DIMENSIONS),
                             "status": enum(("ADEQUATE", "PROBLEM", "NOT_APPLICABLE")), "note": STR}),
                        minItems=17, maxItems=17),
        "operation": enum(OPERATIONS),
        "justification": STR,
    })),
    "defects": arr(DEFECT),
    "limitations": LIMITATIONS,
})
SEC_AUDIT_V1 = obj({
    "risks": arr(DEFECT),
    "injection_signals": arr(obj({"source_ref": STR, "excerpt": STR})),
    "third_party_content": arr(obj({"card_ref": STR, "note": STR})),
    "personal_data": arr(obj({"card_ref": STR, "note": STR})),
    "limitations": LIMITATIONS,
})
COV_AUDIT_V1 = obj({
    "entities": arr(obj({
        "name": STR,
        "dimensions": arr(obj({"code": {"type": "integer", "minimum": 1, "maximum": 57}, "state": enum(MAP_STATES),
                               "justification": STR}), minItems=57, maxItems=57),
    })),
    "objectives": arr(obj({"objective_ref": STR, "coverage_state": enum(COVERAGE_STATES), "card_refs": arr(STR),
                           "note": STR})),
    "gaps": arr(obj({"description": STR, "necessity": enum(NECESSITY), "dimension_code": {"type": ["integer", "null"]},
                     "suggested_card": STR})),
    "self_sufficiency": arr(obj({"question": STR, "answer": enum(("YES", "PARTIAL", "NO", "NOT_VERIFIABLE")),
                                 "note": STR})),
    "limitations": LIMITATIONS,
})
CONTRADICTION_V1 = obj({
    "pairs": arr(obj({"pair_ref": STR, "kind": enum(SIMILARITY_KINDS), "population_a": STR, "population_b": STR,
                      "scenario_a": STR, "scenario_b": STR, "rationale": STR,
                      "proposal": enum(("KEEP", "MERGE_REVIEW", "REVIEW_DELETE", "REVIEW_REQUIRED"))})),
    "limitations": LIMITATIONS,
})
CORRECTION_V1 = obj({
    "corrections": arr(obj({"card_ref": STR, "operation": enum(OPERATIONS), "defect_ids": arr(STR),
                            "justification": STR, "objective_change": enum(("EQUIVALENT", "SUBSTANTIAL")),
                            "card": {"anyOf": [CARD_V2_MODEL, {"type": "null"}]}})),
    "limitations": LIMITATIONS,
})

CONTRACTS: dict[str, dict[str, Any]] = {
    "sci_audit.v1": SCI_AUDIT_V1,
    "ped_audit.v1": PED_AUDIT_V1,
    "sec_audit.v1": SEC_AUDIT_V1,
    "cov_audit.v1": COV_AUDIT_V1,
    "contradiction.v1": CONTRADICTION_V1,
    "correction.v1": CORRECTION_V1,
    "research_result.v1": RESEARCH_RESULT_V1,
    "extraction.v1": EXTRACTION_V1,
    "plan.v1": PLAN_V1,
    "card.v2": CARD_V2,
    "generation_batch.v1": GENERATION_BATCH_V1,
}


def schema_name(contract: str) -> str:
    return contract.replace(".", "_")
