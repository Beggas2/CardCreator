"""Importação de exports de texto do Anki com validação inicial (TEC-014, INT-001, COV-018).

- Reconhece os cabeçalhos do Anki (`#separator`, `#html`, `#guid column`, `#notetype column`,
  `#deck column`, `#tags column`, `#columns`).
- Nenhuma linha é descartada em silêncio: problemas viram itens do relatório e o card vai para quarentena.
- O GUID existente é preservado exatamente e nunca reutilizado para outra nota.
- Reimportar o mesmo GUID cria nova versão só se o conteúdo mudou; o card nunca é apagado.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select

from cardfactory.db import Database
from cardfactory.db.models import Card, CardStateEvent, CardVersion, ImportBatch

SEPARATORS = {"tab": "\t", "comma": ",", "semicolon": ";", "pipe": "|", "space": " ", "colon": ":"}
DANGEROUS_HTML = re.compile(r"<\s*(script|iframe|object|embed|link|meta|style)\b|\son\w+\s*=|javascript:",
                            re.IGNORECASE)
MEDIA_RE = re.compile(r"<img[^>]+src=[\"']?([^\"' >]+)|\[sound:([^\]]+)\]", re.IGNORECASE)


@dataclass
class AnkiRow:
    line: int
    fields: list[str]
    guid: str | None
    notetype: str | None
    deck: str | None
    tags: list[str]
    problems: list[str] = field(default_factory=list)


@dataclass
class ParsedExport:
    headers: dict[str, str]
    separator: str
    html: bool
    rows: list[AnkiRow]
    bom: bool
    physical_lines: int
    format_detected: str
    problems: list[str] = field(default_factory=list)


def _sep(value: str) -> str:
    v = value.strip().lower()
    if v in SEPARATORS:
        return SEPARATORS[v]
    if len(value) == 1:
        return value
    raise ValueError(f"separador desconhecido: {value!r}")


def _sniff(sample: str) -> str:
    counts = {s: sample.count(s) for s in ("\t", ";", ",")}
    return max(counts, key=counts.get) if any(counts.values()) else "\t"


def parse_export(data: bytes) -> ParsedExport:
    bom = data.startswith(b"\xef\xbb\xbf")
    try:
        text = data.decode("utf-8-sig")
        problems = []
    except UnicodeDecodeError:
        text = data.decode("cp1252", errors="replace")
        problems = ["arquivo não é UTF-8; lido como Windows-1252 (verifique acentos)"]
    if bom:
        problems.append("arquivo com BOM UTF-8")
    lines = text.splitlines(keepends=True)
    headers: dict[str, str] = {}
    body_start = 0
    for i, ln in enumerate(lines):
        if ln.startswith("#") and ":" in ln:
            k, _, v = ln[1:].rstrip("\r\n").partition(":")
            headers[k.strip().lower()] = v
            body_start = i + 1
        else:
            break
    body = "".join(lines[body_start:])
    sep = _sep(headers["separator"]) if "separator" in headers else _sniff(body[:5000])
    html = headers.get("html", "true").strip().lower() == "true"

    def col(name: str) -> int | None:
        v = headers.get(f"{name} column")
        return int(v) - 1 if v and v.strip().isdigit() else None

    gcol, ncol, dcol, tcol = col("guid"), col("notetype"), col("deck"), col("tags")
    meta_cols = {c for c in (gcol, ncol, dcol, tcol) if c is not None}
    reader = csv.reader(io.StringIO(body), delimiter=sep, quotechar='"', strict=False)
    rows: list[AnkiRow] = []
    widths: Counter[int] = Counter()
    line_no = body_start
    for rec in reader:
        line_no_start = line_no + 1
        line_no = body_start + reader.line_num
        if not rec or all(not f.strip() for f in rec):
            continue
        widths[len(rec)] += 1

        def get(c: int | None, rec: list[str] = rec) -> str | None:
            return rec[c] if c is not None and c < len(rec) else None

        content = [f for i, f in enumerate(rec) if i not in meta_cols]
        tags_raw = get(tcol) or ""
        rows.append(AnkiRow(line_no_start, content, get(gcol), get(ncol), get(dcol), tags_raw.split()))
    expected = widths.most_common(1)[0][0] if widths else 0
    guid_counts = Counter(r.guid for r in rows if r.guid)
    content_counts = Counter(tuple(r.fields[:2]) for r in rows)
    for r in rows:
        width = len(r.fields) + len([c for c in meta_cols])
        if width != expected:
            r.problems.append(f"número de colunas {width} difere do padrão {expected}")
        if gcol is not None and not r.guid:
            r.problems.append("GUID vazio")
        if r.guid and guid_counts[r.guid] > 1:
            r.problems.append("GUID repetido no arquivo")
        if len(r.fields) < 2 or not r.fields[0].strip():
            r.problems.append("frente vazia")
        elif not r.fields[1].strip():
            r.problems.append("verso vazio")
        if content_counts[tuple(r.fields[:2])] > 1:
            r.problems.append("conteúdo idêntico a outra nota do arquivo")
        if any(DANGEROUS_HTML.search(f) for f in r.fields):
            r.problems.append("HTML perigoso (script, iframe, eventos ou javascript:)")
    fmt = ("anki-guid" if gcol is not None else "anki-sem-guid") if headers else "texto-delimitado"
    return ParsedExport(headers, sep, html, rows, bom, len(lines), fmt, problems)


def _content(row: AnkiRow, html: bool) -> dict[str, Any]:
    media = sorted({m[0] or m[1] for f in row.fields for m in MEDIA_RE.findall(f)})
    return {"legacy": True, "source_guid": row.guid, "html": html, "front_html": row.fields[0] if row.fields else "",
            "back_html": row.fields[1] if len(row.fields) > 1 else "", "extra_fields": row.fields[2:],
            "media_refs": media, "parse_problems": row.problems}


def _hash(content: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class AnkiImporter:
    def __init__(self, db: Database):
        self.db = db

    def import_export(self, project_id: str, data: bytes, *, filename: str = "", author: str = "") -> dict[str, Any]:
        parsed = parse_export(data)
        digest = hashlib.sha256(data).hexdigest()
        created = updated = unchanged = quarantined = 0
        with self.db.write() as s:
            batch = ImportBatch(project_id=project_id, kind="ANKI_EXPORT", filename=filename, content_hash=digest,
                                format_detected=parsed.format_detected, created_by=author)
            s.add(batch)
            s.flush()
            for row in parsed.rows:
                content = _content(row, parsed.html)
                h = _hash(content)
                card = None
                if row.guid and "GUID repetido no arquivo" not in row.problems:
                    card = s.execute(select(Card).where(Card.project_id == project_id, Card.anki_guid == row.guid)) \
                        .scalar_one_or_none()
                if card is not None:
                    last = s.execute(select(CardVersion).where(CardVersion.card_id == card.id)
                                     .order_by(CardVersion.version_no.desc()).limit(1)).scalar_one()
                    if last.content_hash == h and last.deck_path == (row.deck or "") and last.tags == row.tags:
                        unchanged += 1
                        continue
                    n = s.execute(select(func.max(CardVersion.version_no)).where(CardVersion.card_id == card.id)) \
                        .scalar_one()
                    s.add(CardVersion(card_id=card.id, version_no=n + 1, schema_version="legacy", content=content,
                                      deck_path=row.deck or "", tags=row.tags, author_type="IMPORT",
                                      objective_change="UNKNOWN", content_hash=h))
                    updated += 1
                    continue
                bad = bool(row.problems)
                guid = row.guid if row.guid and "GUID repetido no arquivo" not in row.problems else None
                card = Card(project_id=project_id, anki_guid=guid, notetype=row.notetype or "Basic",
                            state="QUARANTINE" if bad else "IMPORTED", quarantine=bad, origin="IMPORTED",
                            import_batch_id=batch.id)
                s.add(card)
                s.flush()
                s.add(CardVersion(card_id=card.id, version_no=1, schema_version="legacy", content=content,
                                  deck_path=row.deck or "", tags=row.tags, author_type="IMPORT", content_hash=h))
                s.add(CardStateEvent(card_id=card.id, from_state="", to_state=card.state, actor=author or "import",
                                     actor_type="HUMAN" if author else "SYSTEM",
                                     reason="; ".join(row.problems) or f"importado de {filename or 'export'}"))
                created += 1
                quarantined += bad
            problem_rows = [{"line": r.line, "guid": r.guid, "problems": r.problems} for r in parsed.rows if r.problems]
            report = {
                "format": parsed.format_detected, "headers": parsed.headers,
                "separator": {"\t": "tab"}.get(parsed.separator, parsed.separator), "html": parsed.html,
                "bom": parsed.bom, "physical_lines": parsed.physical_lines, "notes_read": len(parsed.rows),
                "created": created, "updated": updated, "unchanged": unchanged, "quarantined": quarantined,
                "file_problems": parsed.problems, "problem_rows": problem_rows[:500],
                "problem_rows_total": len(problem_rows),
                "decks": dict(Counter(r.deck or "(sem deck)" for r in parsed.rows).most_common(50)),
                "notetypes": dict(Counter(r.notetype or "(não informado)" for r in parsed.rows)),
                "media_refs": sum(1 for r in parsed.rows if _content(r, parsed.html)["media_refs"]),
            }
            # Reconciliação de contagens (INT-009): toda nota lida tem destino declarado.
            if created + updated + unchanged != len(parsed.rows):
                raise RuntimeError("contagens da importação não fecham; importação desfeita")
            batch.report = report
            return {"import_batch_id": batch.id, **report}
