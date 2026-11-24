"""Varreduras determinísticas de auditoria (SCI-015/016, SCI-029, PED-002, PED-012, COV-009).

Apontam candidatos a defeito; nenhuma regra aqui substitui a auditoria científica nem toma decisão clínica.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from cardfactory.audit.text import back_plain, block_texts, front_plain, is_v2

DEICTICS = ("nesse caso", "neste caso", "nesse contexto", "desse medicamento", "deste medicamento", "esse paciente",
            "este paciente", "essa doença", "esta doença", "esse fármaco", "este fármaco", "conforme acima",
            "citado acima", "mencionado acima", "o mesmo", "a mesma", "card anterior", "questão anterior")
AMBIGUOUS_ACRONYMS = {
    "PCR": "proteína C reativa, parada cardiorrespiratória ou reação em cadeia da polimerase",
    "IC": "insuficiência cardíaca, insuficiência coronariana ou intervalo de confiança",
    "IRA": "insuficiência renal aguda ou insuficiência respiratória aguda",
    "AR": "artrite reumatoide ou ar ambiente",
    "EAP": "edema agudo de pulmão ou outra expansão",
    "DP": "diálise peritoneal, desvio-padrão ou doença de Parkinson",
    "TC": "tomografia computadorizada ou tempo de coagulação",
    "IM": "intramuscular ou infarto do miocárdio",
}
MASS = {"g": 1e6, "mg": 1e3, "mcg": 1.0, "µg": 1.0, "ug": 1.0, "ng": 1e-3}
NUM = r"(\d+(?:[.,]\d+)?)"


@dataclass
class Hit:
    category: str
    severity: str
    description: str


def _f(x: str) -> float:
    return float(x.replace(",", "."))


def _words(t: str) -> set[str]:
    return {w for w in re.findall(r"\w+", t.lower()) if len(w) > 2}


def scan_deictics(content: dict[str, Any]) -> list[Hit]:
    low = front_plain(content).lower()
    found = [d for d in DEICTICS if re.search(rf"(?<!\w){re.escape(d)}(?!\w)", low)]
    return [Hit("PEDAGOGICAL", "MEDIUM", f"frente depende de contexto externo ({', '.join(found)}) (PED-002)")] \
        if found else []


def scan_acronyms(content: dict[str, Any]) -> list[Hit]:
    text = front_plain(content) + " " + back_plain(content)
    out = []
    for ac, meanings in AMBIGUOUS_ACRONYMS.items():
        if re.search(rf"(?<![\w-]){ac}(?![\w-])", text) and not re.search(rf"\({ac}\)|{ac} \(", text):
            out.append(Hit("AMBIGUITY", "LOW", f"sigla ambígua {ac} sem definição no card ({meanings}) (SCI-029)"))
    return out


def scan_redundancy(content: dict[str, Any]) -> list[Hit]:
    """PED-012: dois trechos do mesmo card quase idênticos (Jaccard ≥ 0,8 com ≥ 4 palavras)."""
    items = [(r, _words(t)) for r, t in block_texts(content) if len(_words(t)) >= 4]
    items.append(("front", _words(front_plain(content))))
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            a, b = items[i][1], items[j][1]
            if len(a) >= 4 and len(b) >= 4 and len(a & b) / len(a | b) >= 0.8:
                where = "a frente" if "front" in (items[i][0], items[j][0]) else "dois trechos do verso"
                return [Hit("REDUNDANCY", "LOW", f"redundância interna: {where} repetem o mesmo conteúdo (PED-012)")]
    return []


def scan_score_sum(content: dict[str, Any]) -> list[Hit]:
    """COV-009: limiar de interpretação maior que a pontuação máxima possível do escore."""
    if not is_v2(content) or content["layout"] != "score":
        return []
    total = 0.0
    found = False
    for b in content["answer"]:
        if b["block"] in ("table", "comparison"):
            for it in b["items"]:
                pts = [_f(m) for c in it["cells"][1:] for m in re.findall(
                    NUM + r"\s*pontos?", "".join(sg["text"] for sg in c["segments"]))]
                if pts:
                    total += max(pts)
                    found = True
    if not found:
        return []
    out = []
    for m in re.finditer(r"(?:soma|escore|pontua\w*|total)[^.;\d]{0,20}(?:≥|>=|>|maior que)\s*" + NUM,
                         back_plain(content), re.I):
        if _f(m.group(1)) > total:
            out.append(Hit("NUMERIC_ERROR", "HIGH", f"limiar {m.group(1)} acima da pontuação máxima possível "
                                                    f"({total:g}) (COV-009)"))
    return out


def scan_dose_arithmetic(content: dict[str, Any]) -> list[Hit]:
    """SCI-016: recalcula dose por peso e vazão quando o próprio card traz os termos do cálculo."""
    out = []
    for _, t in block_texts(content) + [("front", front_plain(content))]:
        per_kg = re.search(NUM + r"\s*(g|mg|mcg|µg|ug)/kg(?!/)", t)
        weight = re.search(NUM + r"\s*kg\b", re.sub(r"/kg", "", t))
        if per_kg and weight:
            unit = per_kg.group(2)
            for m in re.finditer(NUM + r"\s*(g|mg|mcg|µg|ug)\b(?!/)", t):
                if m.start() == per_kg.start():
                    continue
                expected = _f(per_kg.group(1)) * MASS[unit] * _f(weight.group(1))
                got = _f(m.group(1)) * MASS[m.group(2)]
                if expected and abs(got - expected) / expected > 0.01:
                    out.append(Hit("NUMERIC_ERROR", "CRITICAL",
                                   f"dose total {m.group(0)} não confere com {per_kg.group(0)} × {weight.group(0)} "
                                   f"(esperado {expected / MASS[m.group(2)]:g} {m.group(2)}) (SCI-016)"))
                break
        rate = re.search(NUM + r"\s*(mcg|µg|ug|mg)/kg/min", t)
        conc = re.search(NUM + r"\s*(mcg|µg|ug|mg)/mL", t)
        flow = re.search(NUM + r"\s*mL/h", t)
        if rate and conc and flow and weight:
            dose_mcg_min = _f(rate.group(1)) * MASS[rate.group(2)] * _f(weight.group(1))
            conc_mcg_ml = _f(conc.group(1)) * MASS[conc.group(2)]
            expected = dose_mcg_min * 60 / conc_mcg_ml
            if abs(_f(flow.group(1)) - expected) / expected > 0.02:
                out.append(Hit("NUMERIC_ERROR", "CRITICAL", f"vazão {flow.group(0)} não confere com o cálculo "
                                                            f"({expected:.1f} mL/h) (SCI-016)"))
    return out


def scan_claim_numbers(content: dict[str, Any], claims: dict[str, dict[str, Any]]) -> list[Hit]:
    """SCI-015: o número mostrado no card precisa ser o da afirmação verificada que ele cita (valor e unidade)."""
    if not is_v2(content):
        return []
    out = []
    for b in content["answer"]:
        for it in b["items"]:
            segs = it["segments"] + [sg for c in it["cells"] for sg in c["segments"]]
            for sg in segs:
                if sg["semantic"] != "value":
                    continue
                for cid in sg["claim_ids"]:
                    num = (claims.get(cid) or {}).get("numeric")
                    if not num or num.get("value") is None:
                        continue
                    nums = [_f(x) for x in re.findall(NUM, sg["text"])]
                    if nums and not any(abs(n - float(num["value"])) < 1e-9 for n in nums):
                        ref = f"{num['value']} {num.get('unit', '')}"
                        unit_tok = re.split(r"[/\s]", (num.get("unit") or "").strip().lower())[0]
                        if unit_tok and re.search(rf"(?<!\w){re.escape(unit_tok)}(?!\w)", sg["text"].lower()):
                            msg = f"valor '{sg['text']}' difere da afirmação verificada ({ref})"
                            out.append(Hit("NUMERIC_ERROR", "CRITICAL", msg))
                        else:
                            # Sem a unidade da afirmação, o número pode ser outra grandeza (ex.: dias 1, 2 e 8
                            # citando a afirmação da dose em mg/kg): pede conferência, não bloqueia como erro.
                            out.append(Hit("TRACEABILITY", "MEDIUM", f"valor '{sg['text']}' cita afirmação numérica "
                                                                     f"de outra grandeza ({ref}); conferir vínculo"))
                    unit = (num.get("unit") or "").split("/")[0].strip()
                    if unit in MASS and nums:
                        shown = re.findall(r"\b(g|mg|mcg|µg|ug|ng)\b", sg["text"])
                        if shown and shown[0] != unit and MASS.get(shown[0]) != MASS[unit]:
                            out.append(Hit("NUMERIC_ERROR", "CRITICAL", f"unidade '{shown[0]}' difere da afirmação "
                                                                        f"verificada ('{unit}') (SCI-015)"))
    return out


def scan_answer_in_front(content: dict[str, Any]) -> list[Hit]:
    """PED-001: um alvo de recuperação do essencial aparece literalmente na frente (a pergunta entrega a resposta)."""
    if not is_v2(content):
        return []
    front = " ".join(front_plain(content).lower().split())
    for b in content["answer"]:
        if b["role"] != "essential":
            continue
        for it in b["items"]:
            for sg in it.get("segments", []):
                t = " ".join(sg["text"].lower().split()).strip(" .,;:")
                if sg.get("retrieval_target") and len(t) >= 6 and re.search(rf"(?<!\w){re.escape(t)}(?!\w)", front):
                    return [Hit("PEDAGOGICAL", "MEDIUM", f"a frente já contém o alvo '{sg['text']}' (PED-001)")]
    return []


def scan_all(content: dict[str, Any], claims: dict[str, dict[str, Any]] | None = None) -> list[Hit]:
    return (scan_deictics(content) + scan_acronyms(content) + scan_redundancy(content) + scan_score_sum(content)
            + scan_dose_arithmetic(content) + scan_claim_numbers(content, claims or {})
            + scan_answer_in_front(content))
