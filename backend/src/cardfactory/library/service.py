"""Biblioteca científica (BIB-001..008, SCI-006/007/011).

- Fonte (identidade lógica) → versão (datas e vigência separadas) → documento (bytes, estado) → seções.
- Bytes ficam num armazenamento endereçado por SHA-256, imutável.
- Uma evidência só existe se o trecho citado estiver literalmente na seção (proteção contra citação inventada).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select, text

from cardfactory.db import Database
from cardfactory.db.models import (
    Document,
    DocumentEvent,
    DocumentSection,
    EvidenceSpan,
    Source,
    SourceVersion,
)
from cardfactory.library.parsing import ParseResult, detect_mime, parse_document

SOURCE_TIERS = ("BR_OFFICIAL", "BR_SOCIETY", "INTL_SOCIETY", "SYSTEMATIC_REVIEW", "PRIMARY_STUDY",
                "SECONDARY_CLINICAL", "NOT_ACCEPTED", "UNCLASSIFIED")
VALIDITY = ("CURRENT", "SUPERSEDED", "REVOKED", "UNCERTAIN")
ACCESS_STATES = ("FOUND", "RETRIEVED", "PARTIALLY_READ", "VERIFIED", "UNAVAILABLE", "OUTDATED", "VALIDITY_UNCERTAIN")
TRANSITIONS: dict[str, set[str]] = {
    "FOUND": {"RETRIEVED", "PARTIALLY_READ", "UNAVAILABLE"},
    "RETRIEVED": {"PARTIALLY_READ", "VERIFIED", "OUTDATED", "VALIDITY_UNCERTAIN", "UNAVAILABLE"},
    "PARTIALLY_READ": {"RETRIEVED", "VERIFIED", "OUTDATED", "VALIDITY_UNCERTAIN"},
    "VERIFIED": {"OUTDATED", "VALIDITY_UNCERTAIN"},
    "UNAVAILABLE": {"FOUND", "RETRIEVED", "PARTIALLY_READ"},
    "VALIDITY_UNCERTAIN": {"VERIFIED", "OUTDATED"},
    "OUTDATED": set(),
}
READ_STATES = ("RETRIEVED", "PARTIALLY_READ", "VERIFIED", "VALIDITY_UNCERTAIN", "OUTDATED")
MAX_QUOTE_CHARS = 1500
DATE_RE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")


class LibraryError(Exception):
    pass


class EvidenceNotFoundError(LibraryError):
    """O trecho citado não existe na seção indicada."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _date(v: str | None, field_name: str) -> str | None:
    if v in (None, ""):
        return None
    if not DATE_RE.match(v):
        raise LibraryError(f"{field_name} deve ser AAAA, AAAA-MM ou AAAA-MM-DD")
    return v


def _ws_map(s: str) -> tuple[str, list[int]]:
    """Texto com espaços colapsados + mapa de índice normalizado → índice original."""
    out, idx, prev_space = [], [], False
    for i, ch in enumerate(s):
        if ch.isspace():
            if prev_space:
                continue
            out.append(" ")
            prev_space = True
        else:
            out.append(ch)
            prev_space = False
        idx.append(i)
    return "".join(out), idx


def locate_quote(section_text: str, quote: str) -> tuple[int, int] | None:
    """Posição do trecho no texto original, tolerando só diferenças de espaço em branco."""
    q = " ".join(quote.split())
    if not q:
        return None
    i = section_text.find(quote)
    if i >= 0:
        return i, i + len(quote)
    norm, idx = _ws_map(section_text)
    j = norm.find(q)
    if j < 0:
        return None
    return idx[j], idx[j + len(q) - 1] + 1


def fts_query(terms: str) -> str:
    """Converte texto livre em consulta FTS5 segura (cada termo entre aspas, todos obrigatórios)."""
    tokens = re.findall(r"[\wÀ-ÿ%./-]+", terms, flags=re.UNICODE)
    return " ".join('"' + t.replace('"', '""') + '"' for t in tokens[:20])


@dataclass
class IngestResult:
    document_id: str
    state: str
    sections: int
    warnings: list[str]
    duplicate_of: str | None = None


class Library:
    def __init__(self, db: Database, blob_dir: Path):
        self.db = db
        self.blob_dir = blob_dir

    # ------------------------------------------------------------ fontes e versões
    def add_source(self, *, title_claimed: str, institution: str = "", source_tier: str = "UNCLASSIFIED",
                   doc_type: str = "", url: str | None = None, doi: str | None = None, created_by: str = "system",
                   notes: str = "") -> str:
        if source_tier not in SOURCE_TIERS:
            raise LibraryError(f"nível de fonte inválido: {source_tier}")
        with self.db.write() as s:
            src = Source(title_claimed=title_claimed.strip(), institution=institution.strip(), source_tier=source_tier,
                         doc_type=doc_type, url=url, doi=doi, created_by=created_by, notes=notes)
            s.add(src)
            s.flush()
            return src.id

    def add_version(self, source_id: str, *, version_label: str = "", published_at: str | None = None,
                    page_updated_at: str | None = None, effective_from: str | None = None,
                    effective_to: str | None = None, validity_status: str = "UNCERTAIN",
                    supersedes_version_id: str | None = None, population: str = "", context: str = "") -> str:
        """Datas de publicação, atualização de página e vigência ficam separadas (SCI-007)."""
        if validity_status not in VALIDITY:
            raise LibraryError(f"vigência inválida: {validity_status}")
        with self.db.write() as s:
            if s.get(Source, source_id) is None:
                raise LibraryError("fonte inexistente")
            v = SourceVersion(source_id=source_id, version_label=version_label,
                              published_at=_date(published_at, "published_at"),
                              page_updated_at=_date(page_updated_at, "page_updated_at"),
                              effective_from=_date(effective_from, "effective_from"),
                              effective_to=_date(effective_to, "effective_to"), validity_status=validity_status,
                              supersedes_version_id=supersedes_version_id, population=population, context=context)
            s.add(v)
            s.flush()
            if supersedes_version_id:
                old = s.get(SourceVersion, supersedes_version_id)
                if old is None or old.source_id != source_id:
                    raise LibraryError("versão substituída deve ser da mesma fonte")
                old.validity_status = "SUPERSEDED"
            return v.id

    def update_source(self, source_id: str, **fields: Any) -> None:
        allowed = {"title_confirmed", "institution", "source_tier", "doc_type", "doi", "url", "license",
                   "rights_status", "notes"}
        bad = set(fields) - allowed
        if bad:
            raise LibraryError(f"campos não editáveis: {sorted(bad)}")
        if "source_tier" in fields and fields["source_tier"] not in SOURCE_TIERS:
            raise LibraryError("nível de fonte inválido")
        with self.db.write() as s:
            src = s.get(Source, source_id)
            if src is None:
                raise LibraryError("fonte inexistente")
            for k, v in fields.items():
                setattr(src, k, v)

    # ------------------------------------------------------------ documentos
    def register_found(self, source_version_id: str, fetch_url: str | None, actor: str = "system") -> str:
        """Documento localizado mas ainda não lido (ex.: candidato do pesquisador)."""
        with self.db.write() as s:
            d = Document(source_version_id=source_version_id, access_state="FOUND", fetch_url=fetch_url)
            s.add(d)
            s.flush()
            s.add(DocumentEvent(document_id=d.id, from_state="", to_state="FOUND", actor=actor, reason="registrado"))
            return d.id

    def _store_blob(self, data: bytes, digest: str, mime: str) -> Path:
        ext = {"application/pdf": ".pdf", "text/html": ".html"}.get(mime, ".txt")
        path = self.blob_dir / digest[:2] / f"{digest}{ext}"
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_bytes(data)
            tmp.replace(path)
        return path

    def ingest(self, document_id: str, data: bytes, *, declared_mime: str | None = None, filename: str = "",
               origin: str = "FETCH", fetch_url: str | None = None, actor: str = "system") -> IngestResult:
        """Grava bytes, lê seções e define o estado: RETRIEVED (leitura completa) ou PARTIALLY_READ."""
        if not data:
            raise LibraryError("documento vazio")
        digest = sha256_bytes(data)
        mime = detect_mime(data, declared_mime, filename)
        parsed: ParseResult = parse_document(data, mime, declared_mime)
        blob = self._store_blob(data, digest, mime)
        with self.db.write() as s:
            d = s.get(Document, document_id)
            if d is None:
                raise LibraryError("documento inexistente")
            if s.execute(select(DocumentSection.id).where(DocumentSection.document_id == d.id)).first():
                raise LibraryError("documento já lido; registre uma nova versão para conteúdo diferente")
            dup = s.execute(select(Document.id).where(Document.content_hash == digest, Document.id != d.id)
                            .limit(1)).scalar_one_or_none()
            for i, sec in enumerate(parsed.sections):
                s.add(DocumentSection(document_id=d.id, ordinal=i, path=sec.path[:500], kind=sec.kind,
                                      page_from=sec.page_from, page_to=sec.page_to, text=sec.text,
                                      parse_quality=sec.parse_quality))
            new_state = "RETRIEVED" if parsed.complete else ("PARTIALLY_READ" if parsed.sections else "UNAVAILABLE")
            self._transition(s, d, new_state, actor, "; ".join(parsed.warnings) or "leitura completa")
            d.content_hash = digest
            d.blob_path = str(blob)
            d.mime = mime
            d.size_bytes = len(data)
            d.pages = parsed.pages
            d.accessed_at = datetime.now(UTC)
            d.origin = origin
            d.fetch_url = fetch_url or d.fetch_url
            d.parse_report = {"warnings": parsed.warnings, "sections": len(parsed.sections), "title": parsed.title}
            d.pending_reason = "; ".join(parsed.warnings) or None
            if parsed.title:
                src = s.get(Source, s.get(SourceVersion, d.source_version_id).source_id)
                if not src.title_confirmed:
                    src.title_confirmed = parsed.title[:500]
            return IngestResult(d.id, new_state, len(parsed.sections), parsed.warnings, dup)

    def mark_unavailable(self, document_id: str, reason: str, actor: str = "system") -> None:
        """SCI-011: fonte indisponível fica registrada com o motivo; nunca vira 'inexistente'."""
        with self.db.write() as s:
            d = s.get(Document, document_id)
            self._transition(s, d, "UNAVAILABLE", actor, reason)
            d.pending_reason = reason

    def set_state(self, document_id: str, state: str, actor: str, reason: str) -> None:
        if not actor:
            raise LibraryError("transição exige autor")
        with self.db.write() as s:
            self._transition(s, s.get(Document, document_id), state, actor, reason)

    @staticmethod
    def _transition(s, d: Document | None, new: str, actor: str, reason: str) -> None:
        if d is None:
            raise LibraryError("documento inexistente")
        if new not in ACCESS_STATES:
            raise LibraryError(f"estado inválido: {new}")
        if new != d.access_state and new not in TRANSITIONS[d.access_state]:
            raise LibraryError(f"transição inválida: {d.access_state} → {new}")
        if new == "VERIFIED" and not s.execute(select(DocumentSection.id).where(
                DocumentSection.document_id == d.id)).first():
            raise LibraryError("documento sem seções lidas não pode ser conferido")
        s.add(DocumentEvent(document_id=d.id, from_state=d.access_state, to_state=new, actor=actor,
                            reason=reason[:2000]))
        d.access_state = new

    # ------------------------------------------------------------ evidências
    def add_evidence(self, section_id: str, quote: str, *, retrieved_via: str = "DOCUMENT",
                     call_id: str | None = None) -> str:
        quote = quote.strip()
        if not quote:
            raise EvidenceNotFoundError("trecho vazio")
        if len(quote) > MAX_QUOTE_CHARS:
            raise LibraryError(f"trecho com mais de {MAX_QUOTE_CHARS} caracteres; cite só o necessário")
        with self.db.write() as s:
            sec = s.get(DocumentSection, section_id)
            if sec is None:
                raise EvidenceNotFoundError("seção inexistente")
            doc = s.get(Document, sec.document_id)
            if doc.access_state not in READ_STATES:
                raise LibraryError(f"documento em {doc.access_state} não sustenta evidência")
            pos = locate_quote(sec.text, quote)
            if pos is None:
                raise EvidenceNotFoundError("o trecho citado não está na seção indicada")
            ev = EvidenceSpan(section_id=section_id, quote=sec.text[pos[0]:pos[1]], char_start=pos[0],
                              char_end=pos[1], retrieved_via=retrieved_via, created_by_call_id=call_id)
            s.add(ev)
            s.flush()
            return ev.id

    def evidence(self, evidence_id: str) -> dict[str, Any]:
        with self.db.session() as s:
            ev = s.get(EvidenceSpan, evidence_id)
            sec = s.get(DocumentSection, ev.section_id)
            doc = s.get(Document, sec.document_id)
            ver = s.get(SourceVersion, doc.source_version_id)
            src = s.get(Source, ver.source_id)
            return {"id": ev.id, "quote": ev.quote, "section_path": sec.path, "page": sec.page_from,
                    "document_id": doc.id, "access_state": doc.access_state, "source_id": src.id,
                    "title": src.title_confirmed or src.title_claimed, "institution": src.institution,
                    "tier": src.source_tier, "published_at": ver.published_at, "validity": ver.validity_status,
                    "retrieved_via": ev.retrieved_via}

    # ------------------------------------------------------------ busca (BIB-005/007)
    def search(self, terms: str, *, institution: str | None = None, tier: str | None = None,
               validity: str | None = None, year: str | None = None, document_id: str | None = None,
               limit: int = 20) -> list[dict[str, Any]]:
        q = fts_query(terms)
        if not q:
            return []
        sql = ("SELECT f.section_id, f.document_id, snippet(document_section_fts, -1, '[', ']', '…', 24) AS snip, "
               "bm25(document_section_fts) AS score, sec.path, sec.page_from, sec.kind, sec.parse_quality, "
               "d.access_state, v.published_at, v.validity_status, v.version_label, src.id AS source_id, "
               "COALESCE(src.title_confirmed, src.title_claimed) AS title, src.institution, src.source_tier "
               "FROM document_section_fts f JOIN document_section sec ON sec.id = f.section_id "
               "JOIN document d ON d.id = f.document_id JOIN source_version v ON v.id = d.source_version_id "
               "JOIN source src ON src.id = v.source_id WHERE document_section_fts MATCH :q")
        params: dict[str, Any] = {"q": q, "limit": max(1, min(limit, 200))}
        if institution:
            sql += " AND src.institution LIKE :inst"
            params["inst"] = f"%{institution}%"
        if tier:
            sql += " AND src.source_tier = :tier"
            params["tier"] = tier
        if validity:
            sql += " AND v.validity_status = :val"
            params["val"] = validity
        if year:
            sql += " AND v.published_at LIKE :year"
            params["year"] = f"{year}%"
        if document_id:
            sql += " AND f.document_id = :doc"
            params["doc"] = document_id
        sql += " ORDER BY score LIMIT :limit"
        with self.db.session() as s:
            return [dict(r._mapping) for r in s.execute(text(sql), params)]

    def sections(self, document_id: str) -> list[dict[str, Any]]:
        with self.db.session() as s:
            rows = s.execute(select(DocumentSection).where(DocumentSection.document_id == document_id)
                             .order_by(DocumentSection.ordinal)).scalars()
            return [{"id": r.id, "ordinal": r.ordinal, "path": r.path, "kind": r.kind, "page_from": r.page_from,
                     "parse_quality": r.parse_quality, "text": r.text} for r in rows]

    def list_sources(self) -> list[dict[str, Any]]:
        with self.db.session() as s:
            out = []
            for src in s.execute(select(Source).order_by(Source.created_at.desc())).scalars():
                versions = []
                for v in s.execute(select(SourceVersion).where(SourceVersion.source_id == src.id)
                                   .order_by(SourceVersion.created_at)).scalars():
                    docs = [{"id": d.id, "access_state": d.access_state, "mime": d.mime, "pages": d.pages,
                             "size_bytes": d.size_bytes, "fetch_url": d.fetch_url, "origin": d.origin,
                             "pending_reason": d.pending_reason, "content_hash": d.content_hash}
                            for d in s.execute(select(Document).where(Document.source_version_id == v.id)).scalars()]
                    versions.append({"id": v.id, "version_label": v.version_label, "published_at": v.published_at,
                                     "page_updated_at": v.page_updated_at, "effective_from": v.effective_from,
                                     "effective_to": v.effective_to, "validity_status": v.validity_status,
                                     "supersedes_version_id": v.supersedes_version_id, "population": v.population,
                                     "documents": docs})
                out.append({"id": src.id, "title_claimed": src.title_claimed, "title_confirmed": src.title_confirmed,
                            "institution": src.institution, "source_tier": src.source_tier, "doc_type": src.doc_type,
                            "url": src.url, "doi": src.doi, "rights_status": src.rights_status, "notes": src.notes,
                            "versions": versions})
            return out
