"""Leitura local de documentos em seções (BIB-004/005). Nada aqui chama IA ou rede.

Seções preservam a ordem do documento e o texto integral (com rodapés e unidades);
o que não puder ser lido com segurança vira seção FAILED/UNCERTAIN e pendência.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

MAX_SECTION_CHARS = 6000
MIN_PAGE_CHARS = 40  # página com menos texto provavelmente é imagem (escaneada)


@dataclass
class ParsedSection:
    path: str
    text: str
    kind: str = "TEXT"
    page_from: int | None = None
    page_to: int | None = None
    parse_quality: str = "OK"


@dataclass
class ParseResult:
    sections: list[ParsedSection]
    pages: int | None = None
    title: str | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return bool(self.sections) and all(s.parse_quality == "OK" for s in self.sections)


def _norm_ws(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace(" ", " ")
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _split_long(path: str, text: str, **kw) -> list[ParsedSection]:
    """Divide textos longos em parágrafos inteiros, nunca no meio de uma frase."""
    if len(text) <= MAX_SECTION_CHARS:
        return [ParsedSection(path, text, **kw)]
    out, buf, part = [], [], 1
    for para in text.split("\n\n"):
        if buf and sum(len(p) for p in buf) + len(para) > MAX_SECTION_CHARS:
            out.append(ParsedSection(f"{path} (parte {part})", "\n\n".join(buf), **kw))
            buf, part = [], part + 1
        buf.append(para)
    if buf:
        out.append(ParsedSection(f"{path} (parte {part})" if part > 1 else path, "\n\n".join(buf), **kw))
    return out


HEADING_RE = re.compile(r"^(#{1,6}\s+.+|\d{1,2}(\.\d{1,2}){0,3}\.?\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ].{2,120})$")


def parse_text(data: str) -> ParseResult:
    text = _norm_ws(data)
    if not text:
        return ParseResult([], warnings=["documento vazio"])
    sections: list[ParsedSection] = []
    heading = "Início"
    buf: list[str] = []

    def flush():
        body = "\n".join(buf).strip()
        if body:
            sections.extend(_split_long(heading, body))

    for line in text.split("\n"):
        if HEADING_RE.match(line.strip()):
            flush()
            heading, buf = line.strip().lstrip("#").strip(), []
        else:
            buf.append(line)
    flush()
    title = next((s.path for s in sections if s.path != "Início"), None)
    return ParseResult(sections, title=title)


class _HTMLSections(HTMLParser):
    SKIP = {"script", "style", "noscript", "nav", "footer", "header", "svg", "form", "button", "iframe"}
    BLOCK = {"p", "div", "li", "br", "section", "article", "blockquote", "dd", "dt", "tr", "pre"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.sections: list[ParsedSection] = []
        self.stack: list[str] = []  # títulos h1..h6 ativos
        self.buf: list[str] = []
        self.skip = 0
        self.heading_level: int | None = None
        self.heading_buf: list[str] = []
        self.title: str | None = None
        self.in_title = False
        self.table_depth = 0
        self.table_rows: list[list[str]] = []
        self.row: list[str] | None = None
        self.cell: list[str] | None = None

    def _path(self) -> str:
        return " > ".join(self.stack) or "Início"

    def _flush(self):
        body = _norm_ws("".join(self.buf))
        if body:
            self.sections.extend(_split_long(self._path(), body))
        self.buf = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
            return
        if self.skip:
            return
        if tag == "title":
            self.in_title = True
        elif re.fullmatch(r"h[1-6]", tag):
            self._flush()
            self.heading_level = int(tag[1])
            self.heading_buf = []
        elif tag == "table":
            if self.table_depth == 0:
                self._flush()
                self.table_rows = []
            self.table_depth += 1
        elif tag == "tr" and self.table_depth:
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []
        elif tag in self.BLOCK:
            self.buf.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if tag == "title":
            self.in_title = False
        elif re.fullmatch(r"h[1-6]", tag) and self.heading_level is not None:
            text = _norm_ws("".join(self.heading_buf))
            level = self.heading_level
            self.stack = self.stack[: level - 1] + [text] if text else self.stack
            self.heading_level = None
        elif tag in ("td", "th") and self.cell is not None and self.row is not None:
            self.row.append(_norm_ws("".join(self.cell)))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if any(self.row):
                self.table_rows.append(self.row)
            self.row = None
        elif tag == "table" and self.table_depth:
            self.table_depth -= 1
            if self.table_depth == 0 and self.table_rows:
                widths = {len(r) for r in self.table_rows}
                text = "\n".join(" | ".join(r) for r in self.table_rows)
                # Tabelas com células mescladas/irregulares não são interpretadas com segurança.
                quality = "OK" if len(widths) == 1 else "UNCERTAIN"
                self.sections.append(ParsedSection(f"{self._path()} > Tabela", text, kind="TABLE",
                                                   parse_quality=quality))
                self.table_rows = []
        elif tag in self.BLOCK:
            self.buf.append("\n")

    def handle_data(self, data):
        if self.skip:
            return
        if self.in_title:
            self.title = (self.title or "") + data.strip()
        elif self.heading_level is not None:
            self.heading_buf.append(data)
        elif self.cell is not None:
            self.cell.append(data)
        elif not self.table_depth:
            self.buf.append(data)

    def close(self):
        super().close()
        self._flush()


def parse_html(data: str) -> ParseResult:
    p = _HTMLSections()
    p.feed(data)
    p.close()
    warnings = [f"tabela com estrutura irregular em '{s.path}'" for s in p.sections if s.parse_quality != "OK"]
    return ParseResult(p.sections, title=(p.title or None), warnings=warnings)


def parse_pdf(data: bytes) -> ParseResult:
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as e:  # noqa: BLE001
        return ParseResult([], warnings=[f"PDF ilegível: {type(e).__name__}"])
    if reader.is_encrypted:
        return ParseResult([], warnings=["PDF protegido por senha"])
    sections, warnings = [], []
    for i, page in enumerate(reader.pages, start=1):
        try:
            text = _norm_ws(page.extract_text() or "")
        except Exception as e:  # noqa: BLE001
            text, warnings = "", warnings + [f"página {i}: falha de extração ({type(e).__name__})"]
        if len(text) < MIN_PAGE_CHARS:
            sections.append(ParsedSection(f"p. {i}", text, page_from=i, page_to=i, parse_quality="FAILED"))
            warnings.append(f"página {i} sem texto extraível (possivelmente escaneada; OCR pendente)")
        else:
            sections.extend(_split_long(f"p. {i}", text, page_from=i, page_to=i))
    title = None
    meta = reader.metadata
    if meta is not None and meta.title:
        title = str(meta.title)
    return ParseResult(sections, pages=len(reader.pages), title=title, warnings=warnings)


def detect_mime(data: bytes, declared: str | None = None, filename: str = "") -> str:
    head = data[:1024].lstrip().lower()
    if data.startswith(b"%PDF"):
        return "application/pdf"
    if head.startswith((b"<!doctype html", b"<html")) or b"<body" in head:
        return "text/html"
    if declared:
        base = declared.split(";")[0].strip().lower()
        if base in ("text/html", "application/xhtml+xml"):
            return "text/html"
        if base in ("text/plain", "text/markdown", "application/pdf"):
            return base
    if filename.lower().endswith((".htm", ".html")):
        return "text/html"
    return "text/plain"


def decode_text(data: bytes, declared: str | None = None) -> str:
    charset = None
    if declared and "charset=" in declared.lower():
        charset = declared.lower().split("charset=")[1].split(";")[0].strip()
    for enc in [charset, "utf-8-sig", "cp1252", "latin-1"]:
        if not enc:
            continue
        try:
            return data.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode("utf-8", errors="replace")


def parse_document(data: bytes, mime: str, declared: str | None = None) -> ParseResult:
    if mime == "application/pdf":
        return parse_pdf(data)
    text = decode_text(data, declared)
    if mime == "text/html":
        return parse_html(text)
    return parse_text(text)
