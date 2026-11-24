"""Renderizador determinístico e validadores visuais (VIS-001..012, VIS-017, PED-004, PED-010, TEC-001, TEC-015)."""

import copy
import re

import pytest

from cardfactory.cards.model import CardError, block, normalize, seg, structural_errors, to_stored
from cardfactory.cards.samples import SAMPLES
from cardfactory.contracts.schemas import CARD_V2_MODEL, GENERATION_BATCH_V1
from cardfactory.render.palette import DARK, LIGHT, OFFICIAL, contrast
from cardfactory.render.renderer import render
from cardfactory.validation.card_checks import check_card
from cardfactory.validation.html import ALLOWED_TAGS, validate_field


def card(**over):
    c = copy.deepcopy(SAMPLES["direct"])
    c.update(over)
    return c


def codes(findings):
    return {f.code for f in findings}


@pytest.mark.parametrize("layout", sorted(SAMPLES))
def test_render_snapshot_each_type(layout):
    """PED-013: os 12 tipos renderizam HTML válido, sem erro bloqueante, com a mesma identidade visual."""
    c = SAMPLES[layout]
    assert structural_errors(c) == []
    r = render(c)
    for html in (r.front, r.back):
        rep = validate_field(html)
        assert rep.errors == [], rep.errors
        assert set(re.findall(r"<(\w+)", html)) <= ALLOWED_TAGS
        assert '"' not in re.sub(r">[^<]*<", "><", html)  # atributos sempre com aspas simples
    assert not [f for f in check_card(c, r) if f.level == "ERROR"]


def test_cognitive_types_cover_a_to_l():
    assert sorted(c["cognitive_type"] for c in SAMPLES.values()) == list("ABCDEFGHIJKL")


def test_render_deterministic():
    for c in SAMPLES.values():
        assert render(c) == render(copy.deepcopy(c))


def test_html_derived_from_json_reproducible():
    stored = to_stored(SAMPLES["criteria"], card_key="ck_1")
    assert render(stored) == render(SAMPLES["criteria"])


def test_palette_whitelist_and_no_background():
    for c in SAMPLES.values():
        r = render(c)
        html = r.front + r.back
        assert {h.upper() for h in re.findall(r"#[0-9a-fA-F]{6}", html)} <= OFFICIAL
        assert "background" not in html
        assert "justify" not in html


def test_semantic_color_map():
    assert DARK.semantic("concept") == DARK.semantic("conduct") == DARK.semantic("diagnosis") == "#7DD3FC"
    assert DARK.semantic("value") == "#FCD34D"
    assert DARK.semantic("risk") == "#FCA5A5"
    assert DARK.semantic("neutral") is None  # herda a cor do tema
    assert DARK.semantic("complement") == DARK.semantic("reference") == "#94A3B8"
    back = render(SAMPLES["negative"]).back
    assert "color:#FCA5A5;font-weight:700'>Gestação" in back  # núcleo de risco em vermelho, não azul


def test_bold_from_retrieval_target_only():
    back = render(SAMPLES["pharmacology"]).back
    assert back.count("font-weight:700") == 2  # dois alvos
    assert "<span style='color:#FCA5A5'>clearance" in back  # risco não alvo: cor sem negrito (AMB-06)
    assert "<b>" not in back and "<strong>" not in back


def test_typography_and_spacing_tokens():
    r = render(SAMPLES["direct"])
    assert "font-size:115%" in r.front and "line-height:1.4" in r.front
    assert "font-size:125%" in r.back  # resposta nuclear curta
    integ = render(SAMPLES["integration"]).back
    assert "margin-top:0.8em;color:#94A3B8;font-size:90%" in integ  # complemento
    case = render(SAMPLES["case"]).back
    assert "font-size:105%" in case and "margin:0.3em 0 0 0" in case  # título → descrição


def test_alignment_rules():
    assert "text-align:center" in render(SAMPLES["direct"]).front
    assert "text-align:left" in render(SAMPLES["case"]).front  # caso clínico longo
    back = render(SAMPLES["list"]).back
    assert back.startswith("<div style='line-height:1.4;text-align:left'>")
    assert "text-align:center" not in back


def test_list_numbering_only_with_real_order():
    assert "<ol" in render(SAMPLES["algorithm"]).back
    assert "<ol" not in render(SAMPLES["list"]).back and "<ul" in render(SAMPLES["list"]).back


def test_combination_rule_visible():
    assert "Pelo menos 2 dos critérios." in render(SAMPLES["criteria"]).back


def test_layers_order_and_essential_required():
    c = card(answer=list(reversed(SAMPLES["integration"]["answer"])))
    assert [b["role"] for b in normalize(c)["answer"]] == ["essential", "understanding", "complement"]
    back = render(c).back
    assert back.index("UTI") < back.index("Integra")
    no_ess = card(answer=[block("understanding", "paragraph", [[seg("x")]])])
    assert any("essencial" in e for e in structural_errors(no_ess))


def test_retrieval_target_forbidden_in_complement():
    """PED-004 / adversarial: informação essencial escondida no complemento."""
    c = card(answer=[SAMPLES["direct"]["answer"][0],
                     block("complement", "paragraph", [[seg("dose 5 mg", "value", True, ["clm_x"])]])])
    assert any("PED-004" in e for e in structural_errors(c))
    c2 = card(answer=[SAMPLES["direct"]["answer"][0],
                      block("complement", "paragraph", [[seg("dose 5 mg", "value", False, ["clm_x"])]])])
    assert "ESSENTIAL_IN_COMPLEMENT" in codes(check_card(c2, render(c2)))


def test_criteria_requires_combination_rule():
    c = copy.deepcopy(SAMPLES["criteria"])
    c["answer"][0]["combination_rule"] = None
    assert any("combinação" in e for e in structural_errors(c))


def test_model_html_rejected_and_text_escaped():
    """TEC-002 / adversarial: HTML vindo do modelo é rejeitado; < e > literais são escapados."""
    bad = card(answer=[block("essential", "paragraph", [[seg("<script>alert(1)</script>", "concept", True)]])])
    assert any("HTML" in e for e in structural_errors(bad))
    ok = card(answer=[block("essential", "paragraph", [[seg("PAS < 90 & FC > 120", "value", True, ["clm_x"])]])])
    back = render(ok).back
    assert "PAS &lt; 90 &amp; FC &gt; 120" in back and validate_field(back).errors == []


def test_schema_requires_limitations_and_no_confidence():
    """PRI-007 / AUD-006: limitations obrigatório; nenhum campo de confiança numérica."""
    assert "limitations" in CARD_V2_MODEL["required"] and "limitations" in GENERATION_BATCH_V1["required"]
    c = card()
    del c["limitations"]
    assert structural_errors(c)
    assert "confidence" not in str(CARD_V2_MODEL)


def test_to_stored_raises_with_all_errors():
    with pytest.raises(CardError) as e:
        to_stored(card(minimal_answer=" ", front={"segments": [], "align": "auto"}), card_key="k")
    assert e.value.errors


def test_table_rules():
    c = copy.deepcopy(SAMPLES["score"])
    c["answer"][0]["items"][1]["cells"].pop()
    assert any("colunas" in e for e in structural_errors(c))
    back = render(SAMPLES["score"]).back
    assert "width:100%" in back and "text-align:right" in back  # valores alinhados à direita
    assert "<th" in back and "<thead" not in back


def test_contrast_ratio_dark_and_light():
    """VIS-010 / VIS-017: todas as cores de texto passam 4,5:1 no fundo do respectivo tema."""
    for pal in (DARK, LIGHT):
        for k in ("text", "complement", "blue", "amber", "red"):
            assert contrast(getattr(pal, k), pal.background) >= 4.5, (pal.name, k)
        assert contrast(DARK.text, "#000000") >= 4.5
    assert contrast(DARK.blue, "#FFFFFF") < 4.5  # AMB-01: paleta escura não serve em fundo claro


def test_light_preview_uses_equivalent_semantics():
    r = render(SAMPLES["negative"], LIGHT)
    assert LIGHT.red in r.back and DARK.red not in r.back


def test_color_wall_and_too_many_colors_warnings():
    long_blue = seg("o tratamento consiste em uma longa explicação inteira colorida de azul sem critério algum",
                    "conduct", True, ["clm_x"])
    c = card(answer=[block("essential", "paragraph", [[long_blue]])])
    assert "COLOR_WALL" in codes(check_card(c, render(c)))
    three = card(answer=[block("essential", "paragraph", [[seg("A", "concept", True, ["clm_x"]), seg(" "),
                                                           seg("5 mg", "value", True, ["clm_x"]), seg(" "),
                                                           seg("risco", "risk", True, ["clm_x"])]])])
    assert "TOO_MANY_COLORS" in codes(check_card(three, render(three)))


def test_bold_excess_warning():
    segs = [seg(f"alvo {i} ", "concept", True, ["clm_x"]) for i in range(5)]
    c = card(answer=[block("essential", "paragraph", [segs])])
    assert "TOO_MUCH_BOLD" in codes(check_card(c, render(c)))


def test_front_scans():
    """PED-007 / C§38.4: pergunta, pergunta múltipla, unidade de recuperação."""
    def front(t):
        return {"segments": [{"text": t, "emphasis": "none", "italic": False}], "align": "auto"}
    assert "FRONT_NOT_QUESTION" in codes(check_card(card(front=front("Hipertensão")), None))
    assert "MULTI_QUESTION" in codes(check_card(card(front=front("Qual a dose? E a via?")), None))
    assert "RETRIEVAL_UNIT" in codes(check_card(card(front=front("Qual o diagnóstico e qual a conduta?")), None))


def test_vague_and_generic_terms_warn_without_blocking():
    """PED-006: alerta nunca reprova sozinho."""
    c = card(answer=[block("essential", "paragraph", [[seg("Avaliar", "conduct", True, ["clm_x"]),
                                                       seg(" se necessário em quadro grave")]])])
    f = check_card(c, render(c))
    assert {"VAGUE_TERMS", "GENERIC_CONDUCT"} <= codes(f)
    assert not [x for x in f if x.level == "ERROR"]


def test_deck_path_and_tags_errors():
    c = card(deck_path=["Outro", "X"], tags=["com espaço"])
    assert {"DECK_INVALID", "TAG_INVALID"} <= codes(check_card(c, render(c)))
    assert "DECK_INVALID" not in codes(check_card(c, render(c), deck_prefix="Outro"))


def test_image_card_without_media_warns():
    assert "IMAGE_PENDING" in codes(check_card(SAMPLES["image"], render(SAMPLES["image"])))
    c = copy.deepcopy(SAMPLES["image"])
    c["images"] = [{"file": "cf_abc.png", "alt": "sinal Y", "side": "front"}]
    r = render(c)
    assert "<img src='cf_abc.png' alt='sinal Y'" in r.front and validate_field(r.front).errors == []
