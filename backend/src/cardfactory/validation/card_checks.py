"""Validação determinística de um card (C§38.1/38.2; TEC-011, TEC-012, PED-006, PED-007, VIS-004, VIS-005).

Erros bloqueiam; alertas nunca reprovam sozinhos (PED-006) e precisam ser corrigidos ou justificados.
Nenhuma regra aqui toma decisão clínica: só aponta candidatos a problema (C§38.2).
"""

from __future__ import annotations

import re
from typing import Any

from cardfactory.cards.model import front_text, segments_of, structural_errors
from cardfactory.render.renderer import Rendered
from cardfactory.validation.html import Finding, validate_field

VAGUE_TERMS = ("rápido", "importante", "significativo", "persistente", "prolongado", "precoce", "tardio", "elevado",
               "acentuado", "intenso", "volumoso", "maciço", "leve", "moderado", "grave", "alto risco", "baixo risco",
               "refratário", "falha", "piora", "melhora", "adequado", "controlado", "estável", "instável",
               "sintomático", "atípico")
GENERIC_CONDUCTS = ("solicitar imagem", "investigar", "drenar", "administrar antibiótico", "realizar suporte",
                    "avaliar", "individualizar", "quando indicado", "se necessário", "conforme protocolo",
                    "casos selecionados")
SIMPLE_LAYOUTS = {"direct", "negative", "case", "mechanism", "integration", "image"}
NORMATIVE_COMPONENTS = {"DOSE", "CUTOFF", "INTERVAL", "DURATION", "CRITERION", "CONTRAINDICATION", "CONDUCT"}
HIGHLIGHT = {"concept": "blue", "conduct": "blue", "diagnosis": "blue", "value": "amber", "divergence": "amber",
             "risk": "red"}
MAX_BACK_WORDS = 100
MAX_SENTENCE_WORDS = 30
COLOR_WALL_RATIO = 0.6
COLOR_WALL_MIN_CHARS = 150
COLOR_WALL_WORDS = 10
NUMBER = re.compile(r"\d")


def _w(code: str, msg: str) -> Finding:
    return Finding("WARNING", code, msg)


def _words(text: str) -> list[str]:
    return re.findall(r"\w+(?:[-/]\w+)*", text)


def _has_term(text: str, terms: tuple[str, ...]) -> list[str]:
    low = text.lower()
    return [t for t in terms if re.search(rf"(?<!\w){re.escape(t)}(?!\w)", low)]


def check_card(card: dict[str, Any], rendered: Rendered | None = None, *, deck_prefix: str = "IGOR") -> list[Finding]:
    out = [Finding("ERROR", "STRUCTURE", e) for e in structural_errors(card, full="card_key" in card)]
    if out:
        return out
    # ---- HTML derivado (erros técnicos C§38.1)
    if rendered is not None:
        for side, value in (("frente", rendered.front), ("verso", rendered.back)):
            rep = validate_field(value)
            if not rep.text.strip():
                out.append(Finding("ERROR", "EMPTY_FIELD", f"{side} vazia após renderização"))
            out += [Finding(f.level, f.code, f"{side}: {f.message}") for f in rep.findings]
    if card["deck_path"][0] != deck_prefix or any(not p.strip() or "::" in p for p in card["deck_path"]):
        out.append(Finding("ERROR", "DECK_INVALID", f"deck deve começar por {deck_prefix}:: e não ter níveis vazios"))
    for t in card["tags"]:
        if not t or re.search(r"\s", t):
            out.append(Finding("ERROR", "TAG_INVALID", f"tag inválida (vazia ou com espaço): {t!r}"))
    # ---- alertas pedagógicos (C§38.2)
    front = " ".join(front_text(card).split())
    if not front.endswith("?"):
        out.append(_w("FRONT_NOT_QUESTION", "frente não termina em pergunta (PED-007)"))
    if front.count("?") > 1:
        out.append(_w("MULTI_QUESTION", "possível pergunta múltipla"))
    if re.search(r"\be (como|quando|qual|quais|por que|o que)\b", front.lower()):
        out.append(_w("RETRIEVAL_UNIT", "revisar unidade de recuperação (duas perguntas ligadas por 'e')"))
    if re.search(r"(?i)^(fale|discorra|comente|descreva tudo)\b", front):
        out.append(_w("FRONT_OPEN", "frente aberta ('fale sobre')"))
    segs = segments_of(card)
    essential = [sg for b, sg in segs if b["role"] == "essential"]
    back_text = " ".join(sg["text"] for _, sg in segs)
    if len(_words(back_text)) > MAX_BACK_WORDS:
        out.append(_w("LONG_ANSWER", f"verso com mais de {MAX_BACK_WORDS} palavras: revisar densidade"))
    for sentence in re.split(r"(?<=[.;!?])\s+", back_text):
        if len(_words(sentence)) > MAX_SENTENCE_WORDS:
            out.append(_w("LONG_SENTENCE", f"frase com mais de {MAX_SENTENCE_WORDS} palavras"))
            break
    targets = sum(1 for _, sg in segs if sg["retrieval_target"])
    if targets == 0:
        out.append(_w("NO_TARGET", "nenhum alvo de recuperação marcado"))
    limit = 3 if card["layout"] in SIMPLE_LAYOUTS else 10
    if targets > limit:
        out.append(_w("TOO_MUCH_BOLD", f"{targets} alvos em negrito (referência: até {limit} neste layout)"))
    colors = {HIGHLIGHT[sg["semantic"]] for b, sg in segs if sg["semantic"] in HIGHLIGHT and b["role"] != "complement"}
    if len(colors) > 2:
        out.append(_w("TOO_MANY_COLORS", f"{len(colors)} cores de destaque: justificar funções distintas (VIS-004)"))
    colored = sum(len(sg["text"]) for b, sg in segs if sg["semantic"] in HIGHLIGHT)
    total = sum(len(sg["text"]) for _, sg in segs)
    long_colored = any(sg["semantic"] in HIGHLIGHT and len(_words(sg["text"])) > COLOR_WALL_WORDS for _, sg in segs)
    if long_colored or (total >= COLOR_WALL_MIN_CHARS and colored / total > COLOR_WALL_RATIO):
        out.append(_w("COLOR_WALL", "parede de cor: colorir expressões, não parágrafos"))
    ess_text = " ".join(sg["text"] for sg in essential)
    if vague := _has_term(ess_text, VAGUE_TERMS):
        out.append(_w("VAGUE_TERMS", f"termos possivelmente vagos no essencial: {', '.join(vague)}"))
    if generic := _has_term(ess_text, GENERIC_CONDUCTS):
        out.append(_w("GENERIC_CONDUCT", f"condutas possivelmente genéricas: {', '.join(generic)}"))
    if re.search(r"(?i)\bnão\b[^.;]*\b(não|nunca|nenhum|sem)\b", ess_text):
        out.append(_w("AMBIGUOUS_NEGATION", "possível negativa dupla ou ambígua"))
    for b, sg in segs:
        if b["role"] == "complement" and (sg["semantic"] in ("value", "risk") or
                                          (NUMBER.search(sg["text"]) and sg["claim_ids"])):
            out.append(_w("ESSENTIAL_IN_COMPLEMENT", "possível informação obrigatória no complemento (PED-004)"))
            break
    if card["layout"] in ("list", "criteria") and any(
            b["role"] == "essential" and b["block"] in ("list", "ordered_list") and b["combination_rule"] is None
            for b in card["answer"]) and card["cognitive_type"] == "C":
        out.append(_w("NO_COMBINATION_RULE", "lista de critérios sem regra de combinação"))
    if card["short_reference"] is None and any(c["component"] in NORMATIVE_COMPONENTS for c in card["claims"]):
        out.append(_w("NO_REFERENCE", "informação normativa sem referência curta"))
    if not card["objective_ids"]:
        out.append(_w("NO_OBJECTIVE", "card sem objetivo de aprendizagem vinculado"))
    if any(not sg["claim_ids"] for sg in essential if sg["retrieval_target"]):
        out.append(_w("TARGET_WITHOUT_CLAIM", "alvo de recuperação sem afirmação rastreável (SCI-013)"))
    if card["layout"] == "image" and not card.get("images"):
        out.append(_w("IMAGE_PENDING", "card de imagem sem arquivo validado: mídia pendente (VIS-016)"))
    numbers = [c for c in card["claims"] if c["component"] in ("DOSE", "CUTOFF") and not NUMBER.search(c["text"])]
    if numbers:
        out.append(_w("NUMERIC_INCONSISTENCY", "afirmação de dose/corte sem número no texto"))
    return out


def blocking(findings: list[Finding]) -> bool:
    return any(f.level == "ERROR" for f in findings)
