"""Serializadores de importação do Anki e verificação de ida e volta (C§31, C§38.3, C§38.5, R§43; TEC-003..007).

Sempre por `csv.writer` (nunca concatenação manual). Uma linha física por nota, UTF-8 sem BOM.
"""

from __future__ import annotations

import csv
import io
import secrets
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from cardfactory.validation.html import validate_field

FORMATS = ("anki_tsv_v2", "anki_tsv_noguid", "anki_simple")
HEADERS: dict[str, list[str]] = {
    "anki_tsv_v2": ["#separator:tab", "#html:true", "#guid column:1", "#notetype column:2", "#deck column:3",
                    "#tags column:6"],
    "anki_tsv_noguid": ["#separator:tab", "#html:true", "#notetype:{notetype}", "#deck column:3", "#tags column:4"],
    "anki_simple": ["#separator:semicolon", "#html:true"],
}
DELIM = {"anki_tsv_v2": "\t", "anki_tsv_noguid": "\t", "anki_simple": ";"}
COLUMNS = {"anki_tsv_v2": 6, "anki_tsv_noguid": 4, "anki_simple": 2}
# Algoritmo de GUID do Anki (base91 de 64 bits aleatórios), usado só quando o GUID vazio não for possível (AMB-08).
_B91 = ("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!#$%&()*+,-./:;<=>?@[]^_`{|}~")


class SerializationError(ValueError):
    pass


@dataclass(frozen=True)
class Note:
    card_key: str
    guid: str            # "" = nota nova; o Anki gera o GUID na importação (verificado: TEC-008)
    notetype: str
    deck: str            # "IGOR::Área::Tema"
    front: str
    back: str
    tags: tuple[str, ...]


def anki_guid() -> str:
    n = secrets.randbits(64)
    out = ""
    while n:
        n, r = divmod(n, len(_B91))
        out = _B91[r] + out
    return out or _B91[0]


def _row(fmt: str, n: Note) -> list[str]:
    tags = " ".join(n.tags)
    if fmt == "anki_tsv_v2":
        return [n.guid, n.notetype, n.deck, n.front, n.back, tags]
    if fmt == "anki_tsv_noguid":
        return [n.front, n.back, n.deck, tags]
    return [n.front, n.back]


def serialize(fmt: str, notes: list[Note]) -> bytes:
    if fmt not in FORMATS:
        raise SerializationError(f"formato desconhecido: {fmt}")
    if fmt == "anki_tsv_noguid" and len({n.notetype for n in notes}) > 1:
        raise SerializationError("formato sem GUID aceita um único tipo de nota por arquivo")
    if fmt == "anki_tsv_noguid" and any(n.guid for n in notes):
        raise SerializationError("notas com GUID existente não podem ir no formato sem GUID (perderiam a identidade)")
    if fmt == "anki_simple" and any(n.guid for n in notes):
        raise SerializationError("formato simplificado nunca é usado para notas com identidade (C§31.5)")
    buf = io.StringIO(newline="")
    notetype = notes[0].notetype if notes else "Basic"
    for h in HEADERS[fmt]:
        buf.write(h.format(notetype=notetype) + "\n")
    w = csv.writer(buf, delimiter=DELIM[fmt], quotechar='"', quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
    for n in notes:
        row = _row(fmt, n)
        if len(row) != COLUMNS[fmt]:
            raise SerializationError("registro com número incorreto de campos")
        if any(ch in f for f in row for ch in ("\n", "\r", "\t")):
            raise SerializationError(f"caractere físico indevido em campo ({n.card_key})")
        if any(" " in t or not t for t in n.tags):
            raise SerializationError(f"tag inválida em {n.card_key}")
        w.writerow(row)
    return buf.getvalue().encode("utf-8")


@dataclass
class ParsedFile:
    headers: dict[str, str]
    rows: list[tuple[int, list[str]]]
    errors: list[str] = field(default_factory=list)


def parse(data: bytes, fmt: str) -> ParsedFile:
    errors: list[str] = []
    if data.startswith(b"\xef\xbb\xbf"):
        errors.append("arquivo com BOM")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as e:
        return ParsedFile({}, [], [f"codificação inválida: {e}"])
    lines = text.split("\n")
    headers: dict[str, str] = {}
    i = 0
    while i < len(lines) and lines[i].startswith("#"):
        k, sep, v = lines[i][1:].partition(":")
        if sep:
            headers[k.strip().lower()] = v.strip()
        i += 1
    rows: list[tuple[int, list[str]]] = []
    for no, line in enumerate(lines[i:], start=i + 1):
        if not line:
            continue
        try:
            fields = next(csv.reader([line], delimiter=DELIM[fmt], quotechar='"', strict=True))
        except csv.Error as e:
            errors.append(f"linha {no}: {e}")
            continue
        rows.append((no, fields))
    return ParsedFile(headers, rows, errors)


def round_trip(data: bytes, fmt: str, notes: list[Note]) -> list[str]:
    """TEC-007: reabre o arquivo e compara campo a campo com o que deveria ter sido gravado."""
    p = parse(data, fmt)
    errs = list(p.errors)
    expected_headers = {}
    for h in HEADERS[fmt]:
        k, _, v = h[1:].partition(":")
        expected_headers[k.lower()] = v.format(notetype=notes[0].notetype if notes else "Basic")
    if p.headers != expected_headers:
        errs.append(f"cabeçalhos divergentes: {p.headers} ≠ {expected_headers}")
    if len(p.rows) != len(notes):
        errs.append(f"contagem divergente: {len(p.rows)} linhas para {len(notes)} notas")
    for (no, fields), n in zip(p.rows, notes, strict=False):
        exp = _row(fmt, n)
        if len(fields) != len(exp):
            errs.append(f"linha {no}: {len(fields)} campos (esperado {len(exp)})")
            continue
        for a, b in zip(fields, exp, strict=True):
            if a != b:
                errs.append(f"linha {no}: campo divergente após releitura ({n.card_key})")
                break
    return errs


def validate_file(data: bytes, fmt: str, *, deck_prefix: str = "IGOR", notetypes: set[str] | None = None,
                  existing_guids: set[str] | None = None, media_files: set[str] | None = None
                  ) -> dict[str, Any]:
    """Validador estrutural de arquivo (C§38.4 ampliado). Retorna erros bloqueantes e alertas."""
    p = parse(data, fmt)
    errors, warnings = list(p.errors), []
    for h in HEADERS[fmt]:
        k, _, v = h[1:].partition(":")
        if "{" not in v and p.headers.get(k.lower(), "").lower() != v.lower():
            errors.append(f"cabeçalho inválido: #{k}")
    guids: list[str] = []
    for no, f in p.rows:
        if len(f) != COLUMNS[fmt]:
            errors.append(f"linha {no}: {len(f)} campos")
            continue
        if fmt == "anki_tsv_v2":
            guid, notetype, deck, front, back, _tags = f
        elif fmt == "anki_tsv_noguid":
            front, back, deck, _tags = f
            guid, notetype = "", p.headers.get("notetype", "")
        else:
            front, back = f
            guid, notetype, deck = "", "", f"{deck_prefix}::"
        if not front.strip() or not back.strip():
            errors.append(f"linha {no}: campo vazio")
        if not deck.startswith(f"{deck_prefix}::"):
            errors.append(f"linha {no}: deck inválido")
        if notetypes is not None and fmt != "anki_simple" and notetype not in notetypes:
            errors.append(f"linha {no}: tipo de nota desconhecido")
        if guid:
            guids.append(guid)
            if any(c.isspace() for c in guid):
                errors.append(f"linha {no}: GUID inválido")
            if existing_guids is not None and guid not in existing_guids:
                errors.append(f"linha {no}: GUID não pertence à coleção (atualização sem nota original)")
        for side, value in (("frente", front), ("verso", back)):
            rep = validate_field(value)
            errors += [f"linha {no} {side}: {x.message}" for x in rep.errors]
            warnings += [f"linha {no} {side}: {x.message}" for x in rep.findings if x.level == "WARNING"]
            if media_files is not None:
                errors += [f"linha {no}: mídia inexistente {m}" for m in rep.media if m not in media_files]
    for g, c in Counter(guids).items():
        if c > 1:
            errors.append(f"GUID duplicado: {g}")
    return {"errors": errors, "warnings": warnings, "notes": len(p.rows)}
