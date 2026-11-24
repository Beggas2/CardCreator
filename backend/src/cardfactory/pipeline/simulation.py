"""Respostas e documentos do modo simulado. Tudo é marcado como [SIMULADO] e nunca é conteúdo médico real."""

from __future__ import annotations

import re
from typing import Any

from cardfactory.knowledge.dimensions import DIMENSIONS
from cardfactory.providers.base import LLMRequest

SIM_URL = "https://simulado.invalid/documento-de-teste"
SIM_DOC = """<html><head><title>[SIMULADO] Documento de teste</title></head><body>
<h1>[SIMULADO] Documento de teste</h1>
<p>Este texto existe apenas para exercitar o fluxo do CardFactory sem custo. Não é conteúdo médico.</p>
<h2>1 Definição</h2><p>[SIMULADO] A condição X é definida pela presença do achado Y.</p>
<h2>2 Tratamento</h2><p>[SIMULADO] O fármaco Z é usado na dose de 5 mg uma vez ao dia em adultos.</p>
</body></html>"""

SECTION_RE = re.compile(r'<untrusted_document id="([^"]+)">\n\[[^\n]*\]\n(.*?)\n</untrusted_document>', re.S)
CLAIM_RE = re.compile(r"^- (clm_\w+) ", re.M)
GEN_OBJ_RE = re.compile(r"^- (obj_\w+) \| ", re.M)
GEN_CLAIM_RE = re.compile(
    r"^- (clm_\w+) \| objetivo (obj_\w+) \| (\w+) \| (\w+) \| população: ([^|]*?)"
    r"(?: \| numérico: [^|]*)? \| (.*)$", re.M)
GEN_SRC_RE = re.compile(r"^- (src_\w+) \| (.*)$", re.M)
GEN_SPAN_RE = re.compile(r'<untrusted_document id="(ev_\w+)">\n\[afirmação (clm_\w+)\]')
MAX_RE = re.compile(r"no máximo (\d+) cards")


async def mock_fetcher(url: str) -> tuple[bytes, str | None, str]:
    if url != SIM_URL:
        raise RuntimeError("o modo simulado não acessa a internet")
    return SIM_DOC.encode(), "text/html; charset=utf-8", url


def _props(req: LLMRequest) -> set[str]:
    return set(((req.response_schema or {}).get("properties") or {}).keys())


def mock_responder(req: LLMRequest) -> dict[str, Any]:
    props = _props(req)
    user = req.messages[-1]["content"] if req.messages else ""
    audit = AUDIT_MOCKS.get(req.schema_name or "")
    if audit is not None:
        return audit(user)
    if "candidates" in props:
        return {"searches": ["[SIMULADO] busca"], "candidates": [{
            "title_claimed": "[SIMULADO] Documento de teste", "institution": "CardFactory (simulação)",
            "url": SIM_URL, "doc_type": "simulação", "year_claimed": None, "tier_claimed": "NOT_ACCEPTED",
            "why_relevant": "exercita o fluxo sem custo"}], "unavailable": [], "limitations": ["resposta simulada"]}
    if "unreadable_sections" in props:
        claims = []
        for sid, text in SECTION_RE.findall(user):
            lines = [ln.strip() for ln in text.split("\n")]
            sentence = next((ln for ln in lines if "[SIMULADO]" in ln and len(ln) > 20), None)
            if sentence:
                numeric = "mg" in sentence
                claims.append({"section_id": sid, "quote": sentence, "text": sentence,
                               "component": "DOSE" if numeric else "OTHER", "population": "adultos" if numeric else "",
                               "scenario": "", "criticality": "HIGH" if numeric else "NORMAL", "negation_kind": None,
                               "numeric_value": 5 if numeric else None, "numeric_unit": "mg/dia" if numeric else None,
                               "numeric_operator": "=" if numeric else None, "conditions": []})
        return {"claims": claims, "unreadable_sections": [], "limitations": ["resposta simulada"]}
    if "entities" in props:
        claim_ids = CLAIM_RE.findall(user)
        dims = [{"code": c, "state": "APPLICABLE_PENDING" if c in (1, 29) else "NOT_APPLICABLE",
                 "justification": "" if c in (1, 29) else "[SIMULADO] fora do escopo do teste"} for c in DIMENSIONS]
        return {"entities": [{"name": "[SIMULADO] Condição X", "synonyms": [], "home_deck_path": "IGOR::Simulado",
                              "dimensions": dims, "decision_points": []}],
                "objectives": [{"ref": f"o{i}", "entity": "[SIMULADO] Condição X", "subtopic": "",
                                "description": f"[SIMULADO] Objetivo {i + 1}", "knowledge_level": "FACTUAL",
                                "knowledge_type": "fato", "necessity": "REQUIRED", "purpose": "teste do fluxo",
                                "clinical_relevance": "LOW", "coverage_state": "ABSENT", "claim_ids": [cid],
                                "depends_on": [], "planned_cards": 1, "planned_rationale": "simulação"}
                               for i, cid in enumerate(claim_ids)],
                "limitations": ["resposta simulada"]}
    if "cards" in props:
        return _mock_cards(user)
    return {"ok": True, "limitations": ["resposta simulada"]}


def _mock_cards(user: str) -> dict[str, Any]:
    """Um card card.v2 [SIMULADO] por objetivo, citando só IDs recebidos (exercita validação e renderização)."""
    claims: dict[str, list[tuple[str, str, str, str]]] = {}
    for cid, oid, comp, crit, _pop, text in GEN_CLAIM_RE.findall(user):
        claims.setdefault(oid, []).append((cid, comp, crit, text.strip()))
    spans: dict[str, list[str]] = {}
    for sid, cid in GEN_SPAN_RE.findall(user):
        spans.setdefault(cid, []).append(sid)
    sources = GEN_SRC_RE.findall(user)
    limit = int(m.group(1)) if (m := MAX_RE.search(user)) else 3
    cards = []
    for i, oid in enumerate(GEN_OBJ_RE.findall(user)[:limit]):
        cl = claims.get(oid)
        if not cl:
            continue
        cid, comp, crit, text = cl[0]
        numeric = comp in ("DOSE", "CUTOFF", "INTERVAL", "DURATION")
        target = {"text": "fármaco Z 5 mg uma vez ao dia" if numeric else "achado Y",
                  "semantic": "value" if numeric else "diagnosis", "retrieval_target": True, "italic": False,
                  "claim_ids": [cid]}
        cards.append({
            "objective_ids": [oid], "deck_path": ["IGOR", "Simulado"], "cognitive_type": "H" if numeric else "A",
            "layout": "pharmacology" if numeric else "direct",
            "front": {"segments": [{"text": f"[SIMULADO] Pergunta {i + 1}: qual é "
                                    f"{'a dose do fármaco Z em adultos' if numeric else 'o achado que define X'}?",
                                    "emphasis": "none", "italic": False}], "align": "auto"},
            "minimal_answer": target["text"],
            "answer": [{"role": "essential", "block": "paragraph", "title": None, "header": None,
                        "items": [{"segments": [target], "cells": []}], "combination_rule": None,
                        "combination_n": None, "combination_text": None},
                       {"role": "complement", "block": "paragraph", "title": None, "header": None,
                        "items": [{"segments": [{"text": "[SIMULADO] Conteúdo de teste, não é medicina.",
                                                 "semantic": "complement", "retrieval_target": False,
                                                 "italic": False, "claim_ids": []}], "cells": []}],
                        "combination_rule": None, "combination_n": None, "combination_text": None}],
            "short_reference": {"source_ids": [sources[0][0]], "display": "[SIMULADO] Documento de teste"}
            if sources else None,
            "tags": ["simulado"], "claims": [{"claim_id": cid, "text": text, "component": comp, "criticality": crit,
                                              "population": "adultos" if numeric else ""}],
            "evidence_span_ids": spans.get(cid, [])[:1], "media_requests": [], "limitations": ["conteúdo simulado"]})
    return {"cards": cards, "unverified_claims": [], "limitations": ["resposta simulada"]}


# ---------------------------------------------------------------------------- auditorias simuladas (Fase 4)
CARD_HDR_RE = re.compile(r"^### card (\S+)$", re.M)
AUD_CLAIM_RE = re.compile(r"^- (clm_\w+) \| (\w+) \| (\w+) \| população: ", re.M)
CURRENT_RE = re.compile(r"^Conteúdo atual \(card\.v2\):\n(\{.*\})$", re.M)
DEFECT_ID_RE = re.compile(r"^  - (def_\w+) \| ", re.M)
POOL_RE = re.compile(r'<untrusted_document id="(ev_\w+)">\n\[trecho da fonte\]')
PAIR_RE = re.compile(r"^### par (\S+) ", re.M)
COV_OBJ_RE = re.compile(r"^- (obj_\w+) \| (\w+) \| ", re.M)
FIXED_MARK = "[corrigido]"
SYSTEM_FIELDS = ("schema_version", "card_key", "anki_guid", "images", "validation_status")


def _sections(user: str) -> list[tuple[str, str]]:
    """(card_key, texto do bloco) para cada "### card" do pedido."""
    heads = list(CARD_HDR_RE.finditer(user))
    return [(m.group(1), user[m.end():heads[i + 1].start() if i + 1 < len(heads) else len(user)])
            for i, m in enumerate(heads)]


def _mock_sci(user: str) -> dict[str, Any]:
    """Confirma cada afirmação citada com as evidências recebidas. O primeiro card ainda sem a marca de correção
    recebe um defeito MEDIUM de imprecisão, para exercitar correção → reauditoria → FIXED sem custo."""
    claims, defects = [], []
    for key, body in _sections(user):
        spans: dict[str, list[str]] = {}
        for sid, cid in GEN_SPAN_RE.findall(body):
            spans.setdefault(cid, []).append(sid)
        pool = POOL_RE.findall(body)
        if pool and not AUD_CLAIM_RE.findall(body):  # deck importado: afirmação nova sustentada pelo acervo
            claims.append({"card_ref": key, "claim_ref": "novo:1", "text": "[SIMULADO] afirmação extraída do card",
                           "component": "OTHER", "criticality": "NORMAL", "verdict": "CONFIRMED",
                           "evidence_span_ids": pool[:1], "rationale": "[SIMULADO] trecho do acervo",
                           "needs_more_evidence": False})
        for cid, comp, crit in AUD_CLAIM_RE.findall(body):
            ev = spans.get(cid, [])
            claims.append({"card_ref": key, "claim_ref": cid, "text": "[SIMULADO]", "component": comp,
                           "criticality": crit, "verdict": "CONFIRMED" if ev else "NOT_VERIFIED",
                           "evidence_span_ids": ev, "rationale": "[SIMULADO] verificação de teste",
                           "needs_more_evidence": not ev})
        if not defects and FIXED_MARK not in body and "[SIMULADO]" in body:
            defects.append({"card_ref": key, "category": "IMPRECISION", "severity": "MEDIUM",
                            "description": "[SIMULADO] complemento impreciso (defeito de teste)",
                            "evidence_span_ids": []})
    return {"claims": claims, "defects": defects, "research_requests": [], "limitations": ["resposta simulada"]}


def _mock_ped(user: str) -> dict[str, Any]:
    from cardfactory.contracts.schemas import PED_DIMENSIONS
    return {"cards": [{"card_ref": key, "findings": [{"dimension": d, "status": "ADEQUATE", "note": ""}
                                                     for d in PED_DIMENSIONS],
                       "operation": "KEEP", "justification": "[SIMULADO] sem problema pedagógico"}
                      for key, _ in _sections(user)],
            "defects": [], "limitations": ["resposta simulada"]}


def _mock_sec(user: str) -> dict[str, Any]:
    return {"risks": [], "injection_signals": [], "third_party_content": [], "personal_data": [],
            "limitations": ["resposta simulada"]}


def _mock_cov(user: str) -> dict[str, Any]:
    dims = [{"code": c, "state": "APPLICABLE_PENDING" if c in (1, 29) else "NOT_APPLICABLE",
             "justification": "" if c in (1, 29) else "[SIMULADO] fora do escopo do teste"} for c in DIMENSIONS]
    return {"entities": [{"name": "[SIMULADO] Condição X", "dimensions": dims}],
            "objectives": [{"objective_ref": oid, "coverage_state": "COMPLETE", "card_refs": [], "note": "[SIMULADO]"}
                           for oid, _ in COV_OBJ_RE.findall(user)],
            "gaps": [], "self_sufficiency": [{"question": "[SIMULADO] O deck basta para o objetivo?",
                                              "answer": "NOT_VERIFIABLE", "note": "simulação"}],
            "limitations": ["resposta simulada"]}


def _mock_correction(user: str) -> dict[str, Any]:
    """Acrescenta a marca de correção ao primeiro complemento do card e devolve card.v2 válido."""
    import json
    out = []
    for key, body in _sections(user):
        m = CURRENT_RE.search(body)
        ids = DEFECT_ID_RE.findall(body)
        if not m:
            out.append({"card_ref": key, "operation": "REVIEW_REQUIRED", "defect_ids": ids,
                        "justification": "[SIMULADO] card legado: conversão exige humano", "objective_change":
                        "EQUIVALENT", "card": None})
            continue
        card = {k: v for k, v in json.loads(m.group(1)).items() if k not in SYSTEM_FIELDS}
        card.setdefault("limitations", [])
        for b in card["answer"]:
            if b["role"] == "complement" and b["items"] and b["items"][0]["segments"]:
                b["items"][0]["segments"][-1]["text"] += f" {FIXED_MARK}"
                break
        out.append({"card_ref": key, "operation": "UPDATE_CONTENT", "defect_ids": ids,
                    "justification": "[SIMULADO] correção mínima de teste", "objective_change": "EQUIVALENT",
                    "card": card})
    return {"corrections": out, "limitations": ["resposta simulada"]}


def _mock_contradiction(user: str) -> dict[str, Any]:
    return {"pairs": [{"pair_ref": pid, "kind": "UNRELATED", "population_a": "", "population_b": "", "scenario_a": "",
                       "scenario_b": "", "rationale": "[SIMULADO] sem relação", "proposal": "KEEP"}
                      for pid in PAIR_RE.findall(user)], "limitations": ["resposta simulada"]}


AUDIT_MOCKS = {"sci_audit_v1": _mock_sci, "ped_audit_v1": _mock_ped, "sec_audit_v1": _mock_sec,
               "cov_audit_v1": _mock_cov, "correction_v1": _mock_correction, "contradiction_v1": _mock_contradiction}
