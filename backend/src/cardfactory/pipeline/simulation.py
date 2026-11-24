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
        return {"limitations": ["conteúdo simulado"],
                "cards": [{"front": f"[SIMULADO] Pergunta {i + 1}?", "essential": f"[SIMULADO] Resposta {i + 1}"}
                          for i in range(3)]}
    return {"ok": True, "limitations": ["resposta simulada"]}
