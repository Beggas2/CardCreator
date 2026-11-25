"""Renderizador determinístico card.v2 → HTML (VIS-001..012, TEC-001, PED-004, PED-010, ADR-0006).

Função pura: o mesmo card e a mesma paleta produzem sempre o mesmo HTML, sem chamadas de IA.
- Cor vem de `semantic`; negrito vem de `retrieval_target` (AMB-06). Texto neutro herda a cor do tema.
- O renderizador nunca define fundo (VIS-010) nem rótulos automáticos (VIS-009).
- Só emite tags da allowlist (TEC-001), estilos inline e atributos entre aspas simples.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Any

from cardfactory.cards.model import TABULAR, front_text, normalize
from cardfactory.render.palette import DARK, Palette

RENDERER_VERSION = "1.0.0"

# Tokens tipográficos e de espaçamento (C§18.1, C§18.5)
FS_FRONT = "115%"
FS_CORE = "125%"
FS_TITLE = "105%"
FS_COMPLEMENT = "90%"
FS_REFERENCE = "85%"
LINE_HEIGHT = "1.4"
SP_TITLE = "0.3em"      # título → descrição (0,2–0,4em)
SP_ITEM = "0.35em"      # elementos relacionados (0,3–0,5em)
SP_BLOCK = "0.8em"      # blocos independentes (0,7–1em) e complemento (~0,8em)
SHORT_FRONT = 100       # caracteres: perguntas curtas podem ser centralizadas (C§18.4)
SHORT_CORE = 80         # resposta nuclear curta recebe destaque de tamanho
SHORT_SEQUENCE = 70
CORE_LAYOUTS = {"direct", "negative", "case", "integration", "image", "mechanism", "pharmacology"}
LEFT_FRONT_LAYOUTS = {"case"}
RULE_TEXT = {"all": "Todos os critérios são necessários.", "any": "Basta um dos critérios.",
             "mutually_exclusive": "Critérios mutuamente exclusivos."}


@dataclass(frozen=True)
class Rendered:
    front: str
    back: str
    renderer_version: str = RENDERER_VERSION
    palette: str = "dark"


def _esc(text: str) -> str:
    return html.escape(text, quote=False).replace("\n", "<br>")


def _attr(text: str) -> str:
    return html.escape(text, quote=True)


def _style(**props: str | None) -> str:
    parts = [f"{k.replace('_', '-')}:{v}" for k, v in props.items() if v]
    return f" style='{';'.join(parts)}'" if parts else ""


def _segment(sg: dict[str, Any], pal: Palette, *, complement: bool = False) -> str:
    color = pal.semantic(sg["semantic"])
    if complement and sg["semantic"] not in ("value", "risk"):
        color = None  # dentro do complemento herda o cinza do bloco
    weight = "700" if sg["retrieval_target"] else None
    text = _esc(sg["text"])
    if sg.get("italic"):
        text = f"<i>{text}</i>"
    style = _style(color=color, font_weight=weight)
    return f"<span{style}>{text}</span>" if style else text


def _segments(segs: list[dict[str, Any]], pal: Palette, complement: bool) -> str:
    return "".join(_segment(s, pal, complement=complement) for s in segs)


def _plain(segs: list[dict[str, Any]]) -> str:
    return "".join(s["text"] for s in segs)


def _images(card: dict[str, Any], side: str) -> str:
    return "".join(f"<div{_style(margin_top=SP_BLOCK)}><img src='{_attr(im['file'])}' alt='{_attr(im['alt'])}'"
                   f"{_style(max_width='100%', height='auto')}></div>"
                   for im in card.get("images", []) if im["side"] == side)


def render_front(card: dict[str, Any], pal: Palette = DARK) -> str:
    align = card["front"]["align"]
    if align == "auto":
        short = len(front_text(card)) <= SHORT_FRONT and card["layout"] not in LEFT_FRONT_LAYOUTS
        align = "center" if short else "left"
    parts = []
    for s in card["front"]["segments"]:
        text = _esc(s["text"])
        if s.get("italic"):
            text = f"<i>{text}</i>"
        color = pal.blue if s["emphasis"] == "retrieval_object" else None
        parts.append(f"<span{_style(color=color)}>{text}</span>" if color else text)
    return (f"<div{_style(font_size=FS_FRONT, line_height=LINE_HEIGHT, text_align=align)}>{''.join(parts)}</div>"
            + _images(card, "front"))


def _is_core(card: dict[str, Any], b: dict[str, Any], index: int) -> bool:
    if index != 0 or b["role"] != "essential" or b["block"] != "paragraph" or len(b["items"]) != 1 or b["title"]:
        return False
    return card["layout"] in CORE_LAYOUTS and len(_plain(b["items"][0]["segments"])) <= SHORT_CORE


def _rule_line(b: dict[str, Any], after_title: bool) -> str:
    rule = b["combination_rule"]
    if rule is None:
        return ""
    text = b["combination_text"] or (f"Pelo menos {b['combination_n']} dos critérios." if rule == "at_least_n"
                                     else RULE_TEXT.get(rule, ""))
    return f"<div{_style(margin_top=SP_TITLE if after_title else None)}>{_esc(text)}</div>" if text else ""


def _numeric_column(rows: list[dict[str, Any]], col: int) -> bool:
    segs = [sg for r in rows for sg in r["cells"][col]["segments"] if sg["text"].strip()]
    return bool(segs) and all(sg["semantic"] == "value" for sg in segs)


def _table(b: dict[str, Any], pal: Palette, complement: bool) -> str:
    ncols = len(b["items"][0]["cells"])
    right = [ncols > 1 and c > 0 and _numeric_column(b["items"], c) for c in range(ncols)]
    pad = "0.2em 0.5em 0.2em 0"
    rows = []
    if b["header"]:
        head_color = pal.complement if complement else pal.blue
        ths = []
        for i, h in enumerate(b["header"]):
            st = _style(text_align="right" if right[i] else "left", padding=pad, font_weight="400",
                        color=head_color, border_bottom=f"1px solid {pal.separator}")
            ths.append(f"<th{st}>{_esc(h)}</th>")
        rows.append(f"<tr>{''.join(ths)}</tr>")
    for it in b["items"]:
        tds = []
        for i, c in enumerate(it["cells"]):
            st = _style(text_align="right" if right[i] else None, padding=pad, vertical_align="top",
                        overflow_wrap="anywhere")
            tds.append(f"<td{st}>{_segments(c['segments'], pal, complement)}</td>")
        rows.append(f"<tr>{''.join(tds)}</tr>")
    st = _style(width="100%", border_collapse="collapse", margin_top=SP_TITLE if b["title"] else None)
    return f"<table{st}><tbody>{''.join(rows)}</tbody></table>"


def _items(b: dict[str, Any], pal: Palette, complement: bool, first_margin: str | None) -> str:
    kind = b["block"]
    its = [_segments(it["segments"], pal, complement) for it in b["items"]]
    if kind in ("list", "ordered_list"):
        tag = "ol" if kind == "ordered_list" else "ul"  # numeração só com ordem real (VIS-012)
        lis = "".join(f"<li{_style(margin_top=SP_ITEM if i else None)}>{x}</li>" for i, x in enumerate(its))
        return f"<{tag}{_style(margin=f'{first_margin or 0} 0 0 0', padding_left='1.3em')}>{lis}</{tag}>"
    if kind == "sequence":
        plain = " → ".join(_plain(it["segments"]) for it in b["items"])
        if len(plain) <= SHORT_SEQUENCE:
            return f"<div{_style(margin_top=first_margin)}>{' → '.join(its)}</div>"
        return "".join(f"<div{_style(margin_top=SP_ITEM if i else first_margin)}>{'→ ' if i else ''}{x}</div>"
                       for i, x in enumerate(its))
    if kind == "formula":
        return "".join(f"<div{_style(margin_top=SP_ITEM if i else first_margin, text_align='center',
                                     font_size='110%')}>{x}</div>" for i, x in enumerate(its))
    return "".join(f"<div{_style(margin_top=SP_ITEM if i else first_margin)}>{x}</div>" for i, x in enumerate(its))


def _block(card: dict[str, Any], b: dict[str, Any], index: int, pal: Palette) -> str:
    complement = b["role"] == "complement"
    wrapper = {"margin_top": SP_BLOCK if index else None}
    if complement:
        wrapper.update(color=pal.complement, font_size=FS_COMPLEMENT)
    if _is_core(card, b, index):
        inner = _segments(b["items"][0]["segments"], pal, False)
        return f"<div{_style(text_align='center', font_size=FS_CORE)}>{inner}</div>"
    head = ""
    if b["title"]:
        head = f"<div{_style(color=None if complement else pal.blue, font_size=FS_TITLE)}>{_esc(b['title'])}</div>"
    head += _rule_line(b, bool(head))
    first = SP_TITLE if head else None
    body = _table(b, pal, complement) if b["block"] in TABULAR else _items(b, pal, complement, first)
    return f"<div{_style(**wrapper)}>{head}{body}</div>"


def render_back(card: dict[str, Any], pal: Palette = DARK) -> str:
    c = normalize(card)
    blocks = "".join(_block(c, b, i, pal) for i, b in enumerate(c["answer"]))
    ref = c.get("short_reference")
    if ref and ref["display"].strip():
        blocks += (f"<div{_style(margin_top=SP_BLOCK, color=pal.complement, font_size=FS_REFERENCE)}>"
                   f"{_esc(ref['display'])}</div>")
    return f"<div{_style(line_height=LINE_HEIGHT, text_align='left')}>{blocks}{_images(c, 'back')}</div>"


def render(card: dict[str, Any], pal: Palette = DARK) -> Rendered:
    return Rendered(render_front(card, pal), render_back(card, pal), RENDERER_VERSION, pal.name)
