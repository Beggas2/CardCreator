"""Cards de exemplo, um por layout, para testes, galeria de preview e inspeção visual (VIS-013, VIS-014).

Conteúdo [EXEMPLO] e fictício (condição X, fármaco Z): serve só para exercitar a apresentação.
"""

from __future__ import annotations

from typing import Any

from cardfactory.cards.model import block, seg


def _card(layout: str, ctype: str, front: str, answer: list[dict[str, Any]], minimal: str, *,
          obj_front: str | None = None, ref: str | None = None,
          claims: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    fsegs = [{"text": front, "emphasis": "none", "italic": False}]
    if obj_front:
        fsegs = [{"text": front, "emphasis": "none", "italic": False},
                 {"text": obj_front, "emphasis": "retrieval_object", "italic": False},
                 {"text": "?", "emphasis": "none", "italic": False}]
    return {"objective_ids": ["obj_exemplo"], "deck_path": ["IGOR", "Exemplos", layout.capitalize()],
            "cognitive_type": ctype, "layout": layout, "front": {"segments": fsegs, "align": "auto"},
            "minimal_answer": minimal, "answer": answer,
            "short_reference": {"source_ids": [], "display": ref} if ref else None,
            "tags": ["exemplo", f"layout::{layout}"],
            "claims": claims or [{"claim_id": "clm_x", "text": "[EXEMPLO] afirmação fictícia", "component": "OTHER",
                                  "criticality": "NORMAL", "population": "adultos"}],
            "evidence_span_ids": [], "media_requests": [], "limitations": ["[EXEMPLO] conteúdo fictício"]}


C = ["clm_x"]
SAMPLES: dict[str, dict[str, Any]] = {
    "direct": _card("direct", "A", "[EXEMPLO] Qual é o diagnóstico mais provável de ", [
        block("essential", "paragraph", [[seg("Condição X", "diagnosis", True, C)]]),
        block("understanding", "paragraph", [[seg("O achado Y define a condição quando associado a "),
                                              seg("febre ≥ 38 °C", "value", False, C), seg(".")]]),
    ], "Condição X", obj_front="febre com achado Y"),
    "list": _card("list", "B", "[EXEMPLO] Quais são as três causas principais da condição X?", [
        block("essential", "list", [[seg("Causa A", "concept", True, C)], [seg("Causa B", "concept", True, C)],
                                    [seg("Causa C", "concept", True, C)]]),
        block("complement", "paragraph", [[seg("Mnemônico fictício: ABC.")]]),
    ], "A, B e C"),
    "criteria": _card("criteria", "C", "[EXEMPLO] Quais critérios definem a condição X grave em adultos?", [
        block("essential", "list", [
            [seg("Pressão sistólica "), seg("< 90 mmHg", "value", True, C)],
            [seg("Lactato "), seg("> 4 mmol/L", "value", True, C)],
            [seg("Necessidade de "), seg("vasopressor", "conduct", True, C)]], rule="at_least_n", n=2),
    ], "Dois de três critérios", ref="Fonte fictícia, 2025"),
    "comparison": _card("comparison", "D", "[EXEMPLO] Como diferenciar a condição X da condição W?", [
        block("essential", "comparison", [
            [[seg("Início")], [seg("súbito", "concept", True, C)], [seg("insidioso", "concept", True, C)]],
            [[seg("Febre")], [seg("presente")], [seg("ausente")]],
            [[seg("Achado-chave")], [seg("sinal Y", "diagnosis", True, C)], [seg("sinal V", "diagnosis", True, C)]],
        ], header=["", "Condição X", "Condição W"], tabular=True),
    ], "Início súbito e sinal Y na X"),
    "score": _card("score", "E", "[EXEMPLO] Como se calcula o escore fictício Z?", [
        block("essential", "table", [
            [[seg("Idade ≥ 65 anos")], [seg("1 ponto", "value", True, C)]],
            [[seg("Confusão")], [seg("1 ponto", "value", True, C)]],
            [[seg("Ureia elevada")], [seg("2 pontos", "value", True, C)]],
        ], header=["Componente", "Pontos"], tabular=True),
        block("understanding", "paragraph", [[seg("Soma ≥ 3 indica "), seg("alto risco", "risk", False, C),
                                              seg(".")]]),
    ], "Soma dos componentes"),
    "mechanism": _card("mechanism", "F", "[EXEMPLO] Qual é o mecanismo do fármaco Z?", [
        block("essential", "paragraph", [[seg("Inibe a enzima Q", "concept", True, C)]]),
        block("understanding", "sequence", [[seg("menos substrato")], [seg("menor produção de P")],
                                            [seg("redução do sintoma")]]),
    ], "Inibição da enzima Q"),
    "algorithm": _card("algorithm", "G", "[EXEMPLO] Qual é a sequência inicial de conduta na condição X instável?", [
        block("essential", "ordered_list", [
            [seg("Garantir via aérea", "conduct", True, C)],
            [seg("Acesso venoso e "), seg("cristaloide 30 mL/kg", "value", True, C)],
            [seg("Reavaliar em "), seg("1 hora", "value", False, C)],
            [seg("Escalonar para "), seg("UTI", "conduct", True, C)]]),
    ], "Via aérea, volume, reavaliação, UTI"),
    "pharmacology": _card("pharmacology", "H", "[EXEMPLO] Qual é a dose do fármaco Z na condição X em adultos?", [
        block("essential", "paragraph", [[seg("5 mg", "value", True, C), seg(" por via oral, "),
                                          seg("uma vez ao dia", "value", True, C)]]),
        block("understanding", "paragraph", [[seg("Evitar se "), seg("clearance < 30 mL/min", "risk", False, C),
                                              seg(".")]]),
    ], "5 mg VO 1x/dia", ref="Fonte fictícia, 2024",
        claims=[{"claim_id": "clm_x", "text": "[EXEMPLO] fármaco Z 5 mg/dia", "component": "DOSE",
                 "criticality": "HIGH", "population": "adultos"}]),
    "case": _card("case", "I", "[EXEMPLO] Homem de 60 anos com febre, achado Y e pressão 85/50 mmHg há 2 horas. "
                  "Qual é a conduta inicial?", [
        block("essential", "paragraph",
              [[seg("Iniciar volume e antimicrobiano na primeira hora", "conduct", True, C)]]),
        block("understanding", "list", [[seg("Hipotensão "), seg("< 90 mmHg", "value", False, C)],
                                        [seg("Achado Y indica foco provável")]], title="Achados que justificam"),
    ], "Volume e antimicrobiano"),
    "negative": _card("negative", "J", "[EXEMPLO] Em qual situação o fármaco Z é contraindicado?", [
        block("essential", "paragraph", [[seg("Gestação", "risk", True, C)]]),
        block("understanding", "paragraph", [[seg("Alternativa: "), seg("fármaco W", "conduct", False, C), seg(".")]]),
    ], "Gestação"),
    "image": _card("image", "K", "[EXEMPLO] Qual achado está indicado na imagem?", [
        block("essential", "paragraph", [[seg("Sinal Y", "diagnosis", True, C)]]),
    ], "Sinal Y"),
    "integration": _card("integration", "L", "[EXEMPLO] Paciente com condição X e escore Z = 3: qual é o destino?", [
        block("essential", "paragraph", [[seg("Internação em UTI", "conduct", True, C)]]),
        block("understanding", "paragraph", [[seg("Escore ≥ 3 corresponde a "), seg("alto risco", "risk", False, C),
                                              seg(".")]]),
        block("complement", "paragraph", [[seg("Integra os cards de escore e de conduta inicial.")]]),
    ], "UTI"),
}
