"""Validador de HTML de campo (C§38.4 ampliado; TEC-001, TEC-002, VIS-002, VIS-009, VIS-010).

Erros bloqueiam a exportação (TEC-011); avisos precisam ser conferidos e corrigidos ou justificados (TEC-012).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from html.parser import HTMLParser

from cardfactory.render.palette import OFFICIAL

ALLOWED_TAGS = {"div", "span", "b", "strong", "i", "em", "small", "p", "br", "hr", "ul", "ol", "li",
                "table", "tbody", "tr", "td", "th", "img"}
VOID_TAGS = {"br", "hr", "img"}
ALLOWED_ATTRS = {"style", "src", "alt", "colspan", "rowspan"}
UNSAFE_VALUE = re.compile(r"javascript:|vbscript:|expression\s*\(|@import", re.I)
FORBIDDEN_CSS = [
    (re.compile(r"url\s*\(", re.I), "ERROR", "CSS_EXTERNAL", "recurso externo no CSS (url())"),
    (re.compile(r"gradient\s*\(", re.I), "ERROR", "CSS_GRADIENT", "gradiente não permitido"),
    (re.compile(r"(box|text)-shadow", re.I), "ERROR", "CSS_SHADOW", "sombra não permitida"),
    (re.compile(r"animation|transition|@keyframes", re.I), "ERROR", "CSS_ANIMATION", "animação não permitida"),
    (re.compile(r"text-align\s*:\s*justify", re.I), "ERROR", "CSS_JUSTIFY", "texto justificado não permitido"),
    (re.compile(r"background", re.I), "ERROR", "CSS_BACKGROUND", "o campo não pode fixar fundo (VIS-010)"),
    (re.compile(r"position\s*:\s*(absolute|fixed)", re.I), "ERROR", "CSS_POSITION", "posicionamento absoluto"),
    (re.compile(r"font-family", re.I), "WARNING", "CSS_FONT", "fonte explícita: preferir fontes nativas"),
    (re.compile(r"(?<![-\w])width\s*:\s*\d{3,}px", re.I), "WARNING", "CSS_FIXED_WIDTH",
     "largura fixa incompatível com celular"),
    (re.compile(r"border(-left|-right)?\s*:\s*(?!0)[^;]*(double|dashed|dotted|groove|ridge|[3-9]px)", re.I),
     "WARNING", "CSS_ORNAMENT", "borda ornamental"),
]
AUTO_LABELS = re.compile(r"^\s*(resposta|essencial|complementar|complemento|ponto-chave)\s*:?\s*$", re.I)
HEX = re.compile(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b")
NAMED_COLOR = re.compile(r"color\s*:\s*(?!#|inherit|currentcolor)([a-z]+)", re.I)


@dataclass
class Finding:
    level: str   # ERROR | WARNING
    code: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"level": self.level, "code": self.code, "message": self.message}


class _Auditor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.findings: list[Finding] = []
        self.texts: list[str] = []
        self.styles: list[str] = []
        self.media: list[str] = []

    def err(self, code: str, msg: str, level: str = "ERROR") -> None:
        self.findings.append(Finding(level, code, msg))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in ALLOWED_TAGS:
            self.err("TAG_NOT_ALLOWED", f"tag não permitida: {tag}")
        for k, v in attrs:
            k, v = k.lower(), v or ""
            if k.startswith("on"):
                self.err("EVENT_ATTR", f"evento HTML não permitido: {k}")
            elif k not in ALLOWED_ATTRS:
                self.err("ATTR_NOT_ALLOWED", f"atributo não permitido: {k}", "WARNING")
            if UNSAFE_VALUE.search(v):
                self.err("UNSAFE_VALUE", "conteúdo inseguro em atributo")
            if k == "style":
                self.styles.append(v)
            if k == "src":
                if re.match(r"(?i)(https?:|data:|file:|//|/|[a-z]:\\)", v) or ".." in v:
                    self.err("EXTERNAL_MEDIA", "mídia externa, embutida ou fora da pasta de mídia")
                else:
                    self.media.append(v)
        if tag == "img" and not dict(attrs).get("src"):
            self.err("IMG_NO_SRC", "imagem sem arquivo")
        if tag not in VOID_TAGS:
            self.stack.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in VOID_TAGS:
            return
        if not self.stack or self.stack[-1] != tag:
            self.err("HTML_MALFORMED", f"fechamento inesperado: {tag}")
            return
        self.stack.pop()

    def handle_data(self, data: str) -> None:
        self.texts.append(data)

    def handle_comment(self, data: str) -> None:
        self.err("HTML_COMMENT", "comentário HTML no campo", "WARNING")

    def handle_decl(self, decl: str) -> None:
        self.err("HTML_DECL", "declaração HTML no campo")

    def handle_pi(self, data: str) -> None:
        self.err("HTML_DECL", "instrução de processamento no campo")


@dataclass
class FieldReport:
    findings: list[Finding] = field(default_factory=list)
    text: str = ""
    colors: set[str] = field(default_factory=set)
    media: list[str] = field(default_factory=list)

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "ERROR"]


def _is_emoji(ch: str) -> bool:
    cp = ord(ch)
    return (0x1F300 <= cp <= 0x1FAFF or 0x2600 <= cp <= 0x27BF or 0x1F000 <= cp <= 0x1F2FF) \
        and unicodedata.category(ch) == "So"


def validate_field(value: str) -> FieldReport:
    a = _Auditor()
    a.feed(value)
    a.close()
    if a.stack:
        a.err("HTML_MALFORMED", f"tags não fechadas: {a.stack}")
    if re.search(r"<\s*(script|iframe|object|embed|link|meta|style|form|input|svg|math)\b", value, re.I):
        a.err("SCRIPT_OR_EXTERNAL", "script, iframe ou elemento externo")
    colors = {c.upper() for c in HEX.findall(value)}
    extra = {c for c in colors if c not in OFFICIAL}
    if extra:
        a.err("COLOR_NOT_IN_PALETTE", f"cores fora da paleta oficial: {sorted(extra)}")
    for st in a.styles:
        for rx, level, code, msg in FORBIDDEN_CSS:
            if rx.search(st):
                a.err(code, msg, level)
        for name in NAMED_COLOR.findall(st):
            a.err("COLOR_NOT_IN_PALETTE", f"cor nomeada fora da paleta: {name}")
    text = " ".join(" ".join(a.texts).split())
    if any(_is_emoji(ch) for ch in text):
        a.err("EMOJI", "emoji decorativo", "WARNING")
    for t in a.texts:
        if AUTO_LABELS.match(t):
            a.err("AUTO_LABEL", f"rótulo automático: {t.strip()!r}", "WARNING")
    # dedup preservando ordem
    seen: set[tuple[str, str]] = set()
    uniq = [f for f in a.findings if not ((f.code, f.message) in seen or seen.add((f.code, f.message)))]
    return FieldReport(uniq, text, colors, a.media)


def normalized_text(value: str) -> str:
    return validate_field(value).text.lower()
