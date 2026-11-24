"""Regras determinísticas do contrato card.v2 (CONTRACTS.md §1; TEC-015, PED-004, PED-010).

O JSON estruturado é a representação primária; o HTML é sempre derivado pelo renderizador.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any

import jsonschema

from cardfactory.contracts.schemas import CARD_V2, CARD_V2_MODEL, ROLES

SCHEMA_VERSION = "2.1"
HTML_TAG = re.compile(r"<\s*/?\s*[a-zA-Z!][^>]*>|&[a-zA-Z]+;|&#\d+;")
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
TABULAR = ("table", "comparison")
ROLE_ORDER = {r: i for i, r in enumerate(ROLES)}


class CardError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def segments_of(card: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """(bloco, segmento) para todo segmento do verso, inclusive células de tabela."""
    out = []
    for b in card.get("answer", []):
        for it in b.get("items", []):
            for sg in it.get("segments", []):
                out.append((b, sg))
            for cell in it.get("cells", []):
                for sg in cell.get("segments", []):
                    out.append((b, sg))
    return out


def front_text(card: dict[str, Any]) -> str:
    return "".join(s["text"] for s in card["front"]["segments"])


def structural_errors(card: dict[str, Any], *, full: bool = False) -> list[str]:
    """Erros que impedem aceitar o card (lista vazia = válido). Avisos pedagógicos ficam em validation/."""
    schema = CARD_V2 if full else CARD_V2_MODEL
    errs = [f"schema: {'/'.join(map(str, e.absolute_path)) or '(raiz)'}: {e.message}"
            for e in sorted(jsonschema.Draft202012Validator(schema).iter_errors(card), key=lambda e: list(e.path))]
    if errs:
        return errs
    if not any(b["role"] == "essential" for b in card["answer"]):
        errs.append("o verso precisa de pelo menos um bloco essencial (PED-010)")
    if not card["minimal_answer"].strip():
        errs.append("resposta mínima verificável vazia (PED-011)")
    if not front_text(card).strip():
        errs.append("frente vazia")
    texts = [s["text"] for s in card["front"]["segments"]] + [sg["text"] for _, sg in segments_of(card)]
    texts += [b["title"] or "" for b in card["answer"]] + [h for b in card["answer"] for h in (b["header"] or [])]
    texts += [card["minimal_answer"]]
    for t in texts:
        if HTML_TAG.search(t):
            errs.append(f"HTML ou entidade vindo do modelo não é aceito: {t[:60]!r}")
        if CONTROL.search(t) or "\t" in t:
            errs.append(f"caractere de controle ou tabulação no texto: {t[:60]!r}")
    known_claims = {c["claim_id"] for c in card["claims"]}
    for i, b in enumerate(card["answer"]):
        where = f"bloco {i + 1}"
        if b["role"] == "complement":
            for it in b["items"]:
                segs = it["segments"] + [sg for c in it["cells"] for sg in c["segments"]]
                if any(sg["retrieval_target"] for sg in segs):
                    errs.append(f"{where}: alvo de recuperação em complemento (PED-004)")
                    break
        if b["block"] in TABULAR:
            widths = {len(it["cells"]) for it in b["items"]}
            if 0 in widths:
                errs.append(f"{where}: linha de tabela sem células")
            if len(widths) > 1:
                errs.append(f"{where}: linhas com números diferentes de colunas")
            if b["header"] is not None and widths and len(b["header"]) != max(widths):
                errs.append(f"{where}: cabeçalho com número de colunas diferente das linhas")
            if any(it["segments"] for it in b["items"]):
                errs.append(f"{where}: tabela usa 'cells', não 'segments'")
        else:
            if any(not it["segments"] for it in b["items"]):
                errs.append(f"{where}: item sem texto")
            if any(it["cells"] for it in b["items"]) or b["header"]:
                errs.append(f"{where}: células/cabeçalho só em table ou comparison")
        if card["layout"] == "criteria" and b["role"] == "essential" and b["block"] != "formula" \
                and b["combination_rule"] is None:
            errs.append(f"{where}: critérios exigem regra de combinação visível (C§19.2)")
        if b["combination_rule"] == "at_least_n" and not b["combination_n"]:
            errs.append(f"{where}: regra 'pelo menos N' sem N")
        if b["combination_rule"] == "major_minor" and not (b["combination_text"] or "").strip():
            errs.append(f"{where}: regra maiores/menores precisa do texto da regra")
        for _, sg in [(b, s) for it in b["items"] for s in it["segments"] + [x for c in it["cells"]
                                                                              for x in c["segments"]]]:
            missing = [c for c in sg["claim_ids"] if known_claims and c not in known_claims]
            if missing:
                errs.append(f"{where}: segmento cita afirmação fora da lista do card: {missing}")
    return errs


def normalize(card: dict[str, Any]) -> dict[str, Any]:
    """Cópia com blocos na ordem essencial → compreensão → complemento (ordem estável dentro da camada)."""
    c = copy.deepcopy(card)
    c["answer"] = sorted(c["answer"], key=lambda b: ROLE_ORDER[b["role"]])
    return c


def to_stored(model_card: dict[str, Any], *, card_key: str, anki_guid: str | None = None,
              images: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    errs = structural_errors(model_card)
    if errs:
        raise CardError(errs)
    c = normalize(model_card)
    return {"schema_version": SCHEMA_VERSION, "card_key": card_key, "anki_guid": anki_guid,
            "images": images or [], "validation_status": "pending", **c}


def content_hash(content: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def seg(text: str, semantic: str = "neutral", target: bool = False, claims: list[str] | None = None,
        italic: bool = False) -> dict[str, Any]:
    """Atalho para testes, fixtures e cards escritos à mão."""
    return {"text": text, "semantic": semantic, "retrieval_target": target, "italic": italic,
            "claim_ids": claims or []}


def block(role: str, kind: str, items: list[list[dict[str, Any]]], *, title: str | None = None,
          rule: str | None = None, n: int | None = None, rule_text: str | None = None,
          header: list[str] | None = None, tabular: bool = False) -> dict[str, Any]:
    its = ([{"segments": [], "cells": [{"segments": cell} for cell in row]} for row in items] if tabular
           else [{"segments": row, "cells": []} for row in items])
    return {"role": role, "block": kind, "title": title, "header": header, "items": its, "combination_rule": rule,
            "combination_n": n, "combination_text": rule_text}
