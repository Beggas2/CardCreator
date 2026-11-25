"""Apostila em PDF como fonte principal: recorte de páginas e figuras com legenda.

A apostila é material de estudo pessoal (fonte secundária). O recorte evita mandar o livro inteiro para a
extração; as figuras ficam na pasta de mídia e só entram num card quando o criador as pede pelo nome.
"""

from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Legenda no início da linha ("FIG. 73: Túnel"); citações no meio do texto ("(Figura 73)") não contam.
FIG_RE = re.compile(r"^\s*(?:FIG\.?|Figura|FIGURA)\s*(\d+[A-Z]?)\s*[:.\-–—]\s*([^\n]{0,200})", re.M)
MIN_SIDE_PX = 120
MIN_BYTES = 4000
LOGO_PAGE_SHARE = 0.3


class ApostilaError(ValueError):
    pass


def parse_pages(spec: str, total: int) -> list[int]:
    """'108-112,115' → páginas (1-based) dentro do documento."""
    pages: list[int] = []
    for part in (spec or "").replace(" ", "").split(","):
        if not part:
            continue
        a, _, b = part.partition("-")
        try:
            lo, hi = int(a), int(b or a)
        except ValueError as e:
            raise ApostilaError(f"intervalo de páginas inválido: {part}") from e
        if lo < 1 or hi < lo or hi > total:
            raise ApostilaError(f"intervalo {part} fora do documento (1–{total})")
        pages.extend(range(lo, hi + 1))
    if not pages:
        raise ApostilaError("informe as páginas, por exemplo 108-112")
    return list(dict.fromkeys(pages))


def subset_pdf(data: bytes, spec: str) -> tuple[bytes, list[int]]:
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        raise ApostilaError("PDF protegido por senha")
    pages = parse_pages(spec, len(reader.pages))
    w = PdfWriter()
    for p in pages:
        w.add_page(reader.pages[p - 1])
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue(), pages


@dataclass
class Figure:
    file: str
    page: int            # página na apostila original
    label: str | None    # ex.: "73"
    caption: str
    sha256: str

    def as_dict(self) -> dict[str, Any]:
        return {"file": self.file, "page": self.page, "label": self.label, "caption": self.caption,
                "sha256": self.sha256}


def _captions(text: str) -> list[tuple[str, str]]:
    out = []
    for m in FIG_RE.finditer(text or ""):
        cap = m.group(2).strip(" _")
        out.append((m.group(1), cap))
    return out


def extract_figures(data: bytes, media_dir: Path, *, prefix: str, original_pages: list[int] | None = None
                    ) -> list[Figure]:
    """Extrai as imagens de cada página com a legenda "FIG. N: ..." da mesma página (ou da seguinte).

    Ignora ícones pequenos, logotipos repetidos e a mesma imagem repetida em páginas seguidas.
    """
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    n_pages = len(reader.pages)
    texts = []
    found: list[tuple[int, str, bytes, str]] = []  # (índice da página, sha, bytes, extensão)
    for i, page in enumerate(reader.pages):
        try:
            texts.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001
            texts.append("")
        try:
            images = list(page.images)
        except Exception:  # noqa: BLE001
            images = []
        for im in images:
            raw = im.data
            try:
                w, h = im.image.size
            except Exception:  # noqa: BLE001
                w = h = 0
            if len(raw) < MIN_BYTES or min(w, h) < MIN_SIDE_PX:
                continue
            ext = Path(im.name).suffix.lower() or ".png"
            if ext not in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
                buf = io.BytesIO()
                im.image.save(buf, format="PNG")
                raw, ext = buf.getvalue(), ".png"
            found.append((i, hashlib.sha256(raw).hexdigest(), raw, ext))
    pages_by_sha: dict[str, set[int]] = {}
    for i, sha, _, _ in found:
        pages_by_sha.setdefault(sha, set()).add(i)
    caps = [_captions(t) for t in texts]
    used_caps: set[tuple[int, int]] = set()
    seen: set[str] = set()
    out: list[Figure] = []
    media_dir.mkdir(parents=True, exist_ok=True)
    for i, sha, raw, ext in found:
        if sha in seen:
            continue
        if len(pages_by_sha[sha]) >= 3 and len(pages_by_sha[sha]) / n_pages > LOGO_PAGE_SHARE:
            continue  # logotipo ou marca d'água repetida
        seen.add(sha)
        label, caption = None, ""
        for j in (i, i + 1, i - 1):  # a legenda costuma ficar na mesma página ou na seguinte
            if 0 <= j < n_pages:
                free = [(k, c) for k, c in enumerate(caps[j]) if (j, k) not in used_caps]
                if free:
                    k, (label, caption) = free[0]
                    used_caps.add((j, k))
                    break
        page = (original_pages[i] if original_pages and i < len(original_pages) else i + 1)
        name = f"{prefix}_p{page}_{sha[:10]}{ext}"
        (media_dir / name).write_bytes(raw)
        out.append(Figure(name, page, label, caption, sha))
    return out


def import_apostila(library, media_dir: Path, data: bytes, *, pages: str, title: str, institution: str = "",
                    year: str | None = None, actor: str = "usuário") -> dict[str, Any]:
    """Registra o recorte da apostila como fonte secundária, lê o texto e guarda as figuras com legenda."""
    from cardfactory.db.models import Document

    sub, original = subset_pdf(data, pages)
    sid = library.add_source(title_claimed=title, institution=institution, source_tier="SECONDARY_CLINICAL",
                             doc_type="apostila", created_by=actor,
                             notes=f"apostila de estudo pessoal, páginas {pages}")
    vid = library.add_version(sid, version_label=f"p. {pages}",
                              published_at=year if year and len(year) == 4 and year.isdigit() else None)
    did = library.register_found(vid, None, actor=actor)
    res = library.ingest(did, sub, declared_mime="application/pdf", filename=f"{title}.pdf", origin="USER_UPLOAD",
                         actor=actor)
    figs = extract_figures(sub, media_dir, prefix=f"apt_{did[-8:].lower()}", original_pages=original)
    with library.db.write() as s:
        d = s.get(Document, did)
        d.parse_report = {**(d.parse_report or {}), "figures": [f.as_dict() for f in figs],
                          "original_pages": original}
    return {"source_id": sid, "version_id": vid, "document_id": did, "state": res.state,
            "sections": res.sections, "warnings": res.warnings, "figures": [f.as_dict() for f in figs]}


def production_figures(db, document_ids: list[str]) -> list[dict[str, Any]]:
    from sqlalchemy import select

    from cardfactory.db.models import Document

    with db.session() as s:
        reports = s.execute(select(Document.parse_report).where(Document.id.in_(document_ids))).scalars().all()
    return [f for r in reports for f in ((r or {}).get("figures") or [])]
