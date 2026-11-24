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
