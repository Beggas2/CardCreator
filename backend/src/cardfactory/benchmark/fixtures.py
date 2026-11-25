"""Conjuntos do benchmark (BENCHMARK_PROTOCOL §1–2).

- KNOWN_DEFECTS: cards fictícios ([EXEMPLO]) com um defeito plantado e gabarito (categorias aceitas e gravidade
  mínima), mais os 12 exemplos limpos, que devem receber KEEP. Cada item traz as afirmações "verificadas" que o
  auditor usa como referência. Split dev/eval alternado e fixo.
- REFERENCE: os 40 cards da proprietária (benchmarks/reference). Escabiose = dev, Kawasaki = eval. Não há
  gabarito de defeito: não se presume que estejam corretos; o relatório mostra o que cada auditor apontou.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

from cardfactory.cards.model import seg
from cardfactory.cards.samples import SAMPLES

REFERENCE_DIR = Path(__file__).resolve().parents[4] / "benchmarks" / "reference"
SEVERITY_RANK = {"OBSERVATION": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}

DOSE_CLAIM = {"text": "[EXEMPLO] fármaco Z 5 mg por via oral uma vez ao dia em adultos; "
                      "evitar se clearance < 30 mL/min",
              "component": "DOSE", "criticality": "HIGH", "population": "adultos",
              "numeric": {"value": 5, "unit": "mg", "operator": "="}}
GENERIC_CLAIM = {"text": "[EXEMPLO] afirmação fictícia", "component": "OTHER", "criticality": "NORMAL",
                 "population": "adultos", "numeric": None}


def _ess(card: dict[str, Any]) -> dict[str, Any]:
    return next(b for b in card["answer"] if b["role"] == "essential")


def _front(card: dict[str, Any], text: str) -> None:
    card["front"]["segments"] = [{"text": text, "emphasis": "none", "italic": False}]


def _planted() -> list[tuple[str, dict[str, Any], dict[str, Any], dict[str, Any]]]:
    """(chave, card, afirmações de referência, gabarito)."""
    out = []
    ph = SAMPLES["pharmacology"]

    c = copy.deepcopy(ph)
    _ess(c)["items"][0]["segments"][0]["text"] = "50 mg"
    out.append(("dose_errada", c, {"clm_x": DOSE_CLAIM},
                {"categories": ["NUMERIC_ERROR", "SCIENTIFIC_ERROR", "PHARMACOLOGY_ERROR"], "min_severity": "HIGH"}))

    c = copy.deepcopy(ph)
    _ess(c)["items"][0]["segments"][0]["text"] = "5 µg"
    out.append(("unidade_trocada", c, {"clm_x": DOSE_CLAIM},
                {"categories": ["NUMERIC_ERROR", "PHARMACOLOGY_ERROR", "SCIENTIFIC_ERROR"], "min_severity": "HIGH"}))

    c = copy.deepcopy(SAMPLES["criteria"])
    _ess(c)["items"][0]["segments"][1]["text"] = "≤ 90 mmHg"
    claims = {"clm_x": {**GENERIC_CLAIM, "text": "[EXEMPLO] critério: pressão sistólica < 90 mmHg; lactato > 4 mmol/L",
                        "component": "CUTOFF", "criticality": "HIGH",
                        "numeric": {"value": 90, "unit": "mmHg", "operator": "<"}}}
    out.append(("operador_trocado", c, claims,
                {"categories": ["NUMERIC_ERROR", "IMPRECISION", "SCIENTIFIC_ERROR"], "min_severity": "MEDIUM"}))

    c = copy.deepcopy(ph)
    c["answer"] = [b for b in c["answer"] if b["role"] == "essential"]  # remove a ressalva de clearance
    out.append(("contraindicacao_omitida", c, {"clm_x": DOSE_CLAIM},
                {"categories": ["OMITTED_CONTRAINDICATION", "SCIENTIFIC_ERROR"], "min_severity": "HIGH"}))

    c = copy.deepcopy(ph)
    _front(c, "[EXEMPLO] Qual é a dose do fármaco Z na condição X em crianças?")
    out.append(("outra_populacao", c, {"clm_x": DOSE_CLAIM},
                {"categories": ["SCIENTIFIC_ERROR", "PHARMACOLOGY_ERROR", "IMPRECISION"], "min_severity": "HIGH"}))

    c = copy.deepcopy(ph)
    _ess(c)["items"][0]["segments"] = [seg("Fármaco Z 0,5 mg/kg: adulto de 70 kg recebe 3,5 mg", "value", True,
                                           ["clm_x"])]
    out.append(("aritmetica_dose", c, {"clm_x": DOSE_CLAIM},
                {"categories": ["NUMERIC_ERROR", "PHARMACOLOGY_ERROR"], "min_severity": "HIGH"}))

    c = copy.deepcopy(SAMPLES["direct"])
    _front(c, "[EXEMPLO] Nesse caso, qual é o diagnóstico mais provável?")
    out.append(("pergunta_ambigua", c, {"clm_x": GENERIC_CLAIM},
                {"categories": ["PEDAGOGICAL", "AMBIGUITY"], "min_severity": "MEDIUM"}))

    c = copy.deepcopy(SAMPLES["algorithm"])
    _ess(c)["items"] = [{"segments": [seg("Investigar e tratar conforme protocolo", "conduct", True, ["clm_x"])],
                         "cells": []}]
    out.append(("conduta_generica", c, {"clm_x": GENERIC_CLAIM},
                {"categories": ["PEDAGOGICAL", "IMPRECISION", "GAP"], "min_severity": "MEDIUM"}))

    c = copy.deepcopy(ph)
    ess = _ess(c)
    moved = copy.deepcopy(ess["items"])
    for it in moved:
        for sg in it["segments"]:
            sg["retrieval_target"] = False
            if sg["semantic"] == "value":
                sg["semantic"] = "complement"
    ess["items"] = [{"segments": [seg("ver complemento", "neutral", True)], "cells": []}]
    c["answer"].append({"role": "complement", "block": "paragraph", "title": None, "header": None, "items": moved,
                        "combination_rule": None, "combination_n": None, "combination_text": None})
    out.append(("essencial_no_complemento", c, {"clm_x": DOSE_CLAIM},
                {"categories": ["PEDAGOGICAL"], "min_severity": "MEDIUM"}))

    c = copy.deepcopy(SAMPLES["mechanism"])
    c["answer"].append({"role": "complement", "block": "paragraph", "title": None, "header": None,
                        "items": [{"segments": [seg("Iniciar em até 7 dias após o diagnóstico.", "complement")],
                                   "cells": []}],
                        "combination_rule": None, "combination_n": None, "combination_text": None})
    out.append(("prazo_inventado", c, {"clm_x": GENERIC_CLAIM},
                {"categories": ["TRACEABILITY", "IMPRECISION", "SCIENTIFIC_ERROR", "NUMERIC_ERROR"],
                 "min_severity": "MEDIUM"}))

    c = copy.deepcopy(SAMPLES["direct"])
    first = _ess(c)["items"][0]["segments"]
    _front(c, "[EXEMPLO] " + "".join(sg["text"] for sg in first) + ": qual é o diagnóstico?")
    out.append(("resposta_na_frente", c, {"clm_x": GENERIC_CLAIM},
                {"categories": ["PEDAGOGICAL", "REDUNDANCY"], "min_severity": "MEDIUM"}))
    return out


def known_defects() -> list[dict[str, Any]]:
    items = []
    for i, (key, card, claims, expected) in enumerate(_planted()):
        items.append({"item_key": f"defeito:{key}", "split": "dev" if i % 2 == 0 else "eval",
                      "content": {"card": card, "claims": claims}, "expected": {"kind": "DEFECT", **expected}})
    for i, (name, card) in enumerate(SAMPLES.items()):
        claims = {"clm_x": DOSE_CLAIM if name == "pharmacology" else GENERIC_CLAIM}
        items.append({"item_key": f"limpo:{name}", "split": "dev" if i % 2 == 0 else "eval",
                      "content": {"card": copy.deepcopy(card), "claims": claims},
                      "expected": {"kind": "CLEAN", "operation": "KEEP"}})
    return items


def reference_items() -> list[dict[str, Any]]:
    """Notas do export do Anki da proprietária como conteúdo legado (HTML), sem gabarito de defeito."""
    items = []
    for f in sorted(REFERENCE_DIR.glob("*.txt")):
        split = "dev" if "escabiose" in f.name else "eval"
        rows = [ln for ln in f.read_text(encoding="utf-8").splitlines() if ln and not ln.startswith("#")]
        for n, ln in enumerate(rows, 1):
            cols = ln.split("\t")
            layout = (re.search(r"Layout::(\w+)", cols[5]) or [None, ""])[1] if len(cols) > 5 else ""
            items.append({"item_key": f"ref:{f.stem}:{n:02d}", "split": split,
                          "content": {"card": {"legacy": True, "html": True, "front_html": cols[3],
                                               "back_html": cols[4], "extra_fields": [], "media_refs": []},
                                      "deck": cols[2], "tags": cols[5].split() if len(cols) > 5 else [],
                                      "cognitive_type": layout},
                          "expected": {"kind": "REFERENCE", "note": "exemplo positivo candidato; não presumido "
                                                                    "livre de erros"}})
    return items
