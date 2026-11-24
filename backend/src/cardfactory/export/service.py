"""Exportação versionada para o Anki (C§31, C§41, R§43, R§50; TEC-003..011, TEC-018, INT-002/005/011/013).

- Só gera arquivos de nota: nunca exclui, nunca toca agendamento, intervalos ou histórico de revisões.
- Bloqueios: card em quarentena, erro de validação aberto ou estado não aprovado (exceto prévia rotulada).
- Antes de liberar: reabre o arquivo e compara campo a campo (round-trip) e roda o validador de arquivo.
- Cada exportação tem rótulo de versão, hashes, diff exato em relação à anterior e manifesto.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from cardfactory.audit.service import AuditService
from cardfactory.db import Database
from cardfactory.db.models import (
    Card,
    CardVersion,
    ExportRun,
    MediaAsset,
    Operation,
    ValidationFinding,
)
from cardfactory.export.tsv import FORMATS, Note, round_trip, serialize, validate_file
from cardfactory.render.renderer import RENDERER_VERSION, render

APPROVED_STATES = {"HUMAN_APPROVED", "READY_FOR_EXPORT", "COMMERCIALLY_RELEASED"}
NEVER_EXPORT = {"QUARANTINE", "REJECTED"}
EXT = {"anki_tsv_v2": "txt", "anki_tsv_noguid": "txt", "anki_simple": "txt"}


class ExportError(ValueError):
    pass


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Exporter:
    def __init__(self, db: Database, exports_dir: Path, media_dir: Path, *, deck_prefix: str = "IGOR"):
        self.db = db
        self.exports_dir = exports_dir
        self.media_dir = media_dir
        self.deck_prefix = deck_prefix

    def export(self, project_id: str, fmt: str = "anki_tsv_v2", *, production_id: str | None = None,
               card_ids: list[str] | None = None, preview: bool = False, actor: str = "",
               test_import: bool = False) -> dict[str, Any]:
        if fmt not in FORMATS:
            raise ExportError(f"formato desconhecido: {fmt}")
        selected, skipped = self._select(project_id, production_id, card_ids, preview)
        notes = [n for n, _ in selected]
        blocked = [s for s in skipped if s["blocking"]]
        with self.db.session() as s:
            prev = s.execute(select(ExportRun).where(ExportRun.project_id == project_id, ExportRun.format == fmt,
                                                     ExportRun.state == "READY")
                             .order_by(ExportRun.created_at.desc()).limit(1)).scalar_one_or_none()
            n_runs = s.execute(select(func.count()).select_from(ExportRun).where(
                ExportRun.project_id == project_id, ExportRun.format == fmt)).scalar_one()
            prev_versions = dict(prev.card_versions) if prev else {}
            prev_id = prev.id if prev else None
        label = f"v{n_runs + 1}" + ("-previa" if preview else "")
        run_id_hint = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        out_dir = self.exports_dir / project_id / f"{run_id_hint}_{fmt}_{label}"
        report: dict[str, Any] = {"errors": [], "warnings": []}
        files: list[dict[str, Any]] = []
        versions = {meta["card_key"]: meta["version_no"] for _, meta in selected}
        round_ok = False
        state = "BLOCKED"
        if fmt == "anki_tsv_noguid" and any(n.guid for n in notes):
            report["errors"].append("há notas com GUID existente: use o formato principal (com GUID)")
        elif fmt == "anki_simple" and any(n.guid for n in notes):
            report["errors"].append("formato simplificado não serve para notas com identidade (C§31.5)")
        if not notes:
            report["errors"].append("nenhum card exportável no recorte")
        media = sorted({im for _, meta in selected for im in meta["images"]})
        missing_media = [m for m in media if not (self.media_dir / m).is_file()]
        if missing_media:
            report["errors"].append(f"mídia inexistente apresentada como disponível: {missing_media}")
        data = b""
        if not report["errors"]:
            data = serialize(fmt, notes)
            rt = round_trip(data, fmt, notes)
            vf = validate_file(data, fmt, deck_prefix=self.deck_prefix, media_files=set(media))
            report["errors"] += rt + vf["errors"]
            report["warnings"] += vf["warnings"]
            round_ok = not rt
            state = "READY" if not report["errors"] else "BLOCKED"
        out_dir.mkdir(parents=True, exist_ok=True)
        prefix = "PREVIA_NAO_REVISADA_" if preview else ""
        if state == "READY":
            name = f"{prefix}DECK_{fmt}_{label}.{EXT[fmt]}"
            (out_dir / name).write_bytes(data)
            files.append({"name": name, "sha256": _sha(data), "bytes": len(data), "notes": len(notes),
                          "kind": "DECK"})
            if media:
                (out_dir / "media").mkdir(exist_ok=True)
                for m in media:
                    shutil.copy2(self.media_dir / m, out_dir / "media" / m)
                    files.append({"name": f"media/{m}", "sha256": _sha((self.media_dir / m).read_bytes()),
                                  "kind": "MEDIA"})
        diff = {
            "added": sorted(k for k in versions if k not in prev_versions),
            "changed": sorted(k for k, v in versions.items() if k in prev_versions and prev_versions[k] != v),
            "unchanged": sorted(k for k, v in versions.items() if prev_versions.get(k) == v),
            "absent_since_previous": sorted(k for k in prev_versions if k not in versions),
        }
        pending = self._pending(selected)
        if pending and state == "READY":
            body = "\n".join(f"{p['card_key']}\t{p['kind']}\t{p['detail']}" for p in pending) + "\n"
            name = f"{prefix}PENDENCIAS_{label}.tsv"
            (out_dir / name).write_text("card_key\ttipo\tdetalhe\n" + body, encoding="utf-8")
            files.append({"name": name, "sha256": _sha((out_dir / name).read_bytes()), "kind": "PENDING"})
        with self.db.write() as s:
            run = ExportRun(project_id=project_id, production_id=production_id, mode="PREVIEW" if preview else "DECK",
                            format=fmt, version_label=label, state=state, card_versions=versions,
                            round_trip_ok=round_ok, previous_export_id=prev_id, diff=diff, created_by=actor)
            s.add(run)
            s.flush()
            export_id = run.id
            for e in report["errors"]:
                s.add(ValidationFinding(export_run_id=run.id, code="EXPORT", level="ERROR", message=e[:2000]))
        if state == "READY" and test_import:
            from cardfactory.export.anki_check import import_test
            res = import_test(out_dir / files[0]["name"], notes, media_dir=out_dir / "media")
            report["import_test"] = res
            with self.db.write() as s:
                s.get(ExportRun, export_id).import_tested = res["status"]
        manifest = {
            "manifest_version": "manifest.v1", "export_id": export_id, "project_id": project_id,
            "production_id": production_id, "format": fmt, "version_label": label, "state": state,
            "preview_not_reviewed": preview, "created_at": datetime.now(UTC).isoformat(), "created_by": actor,
            "renderer_version": RENDERER_VERSION, "files": files,
            "counts": {"selected": len(selected) + len(skipped), "exported": len(notes) if state == "READY" else 0,
                       "new_notes": sum(1 for n in notes if not n.guid),
                       "updates": sum(1 for n in notes if n.guid), "skipped": len(skipped), "blocked": len(blocked)},
            "skipped": skipped, "diff_vs_previous": diff, "previous_export_id": prev_id,
            "operations": self._operations([meta["card_id"] for _, meta in selected]),
            "pending": pending, "sources": sorted({sid for _, meta in selected for sid in meta["source_ids"]}),
            "media": media, "round_trip_ok": round_ok,
            "import_tested": report.get("import_test", {}).get("status", "NOT_TESTED"),
            "errors": report["errors"], "warnings": report["warnings"][:500],
            "notes": ["Notas novas vão com GUID vazio: o Anki gera o GUID na importação; reexporte a coleção "
                      "para reconciliar pelo card_key na tag cf::<card_key> (INT-002).",
                      "Nenhuma nota é excluída por esta exportação; exclusões aparecem só como propostas (INT-005).",
                      "Agendamento, intervalos e histórico de revisões não são alterados (INT-013)."],
        }
        mbytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode()
        (out_dir / f"{prefix}manifesto_{label}.json").write_bytes(mbytes)
        files_all = [*files, {"name": f"{prefix}manifesto_{label}.json", "sha256": _sha(mbytes), "kind": "MANIFEST"}]
        with self.db.write() as s:
            run = s.get(ExportRun, export_id)
            run.files = files_all
            run.report = {"dir": str(out_dir), **manifest["counts"], "errors": report["errors"][:200],
                          "warnings": len(report["warnings"]), "import_tested": manifest["import_tested"]}
        return {"export_id": export_id, "dir": str(out_dir), **manifest, "files": files_all}

    # ------------------------------------------------------------------ internos
    def _select(self, project_id: str, production_id: str | None, card_ids: list[str] | None,
                preview: bool) -> tuple[list[tuple[Note, dict[str, Any]]], list[dict[str, Any]]]:
        selected: list[tuple[Note, dict[str, Any]]] = []
        skipped: list[dict[str, Any]] = []
        with self.db.session() as s:
            q = select(Card).where(Card.project_id == project_id).order_by(Card.created_at)
            if production_id:
                q = q.where(Card.production_id == production_id)
            if card_ids:
                q = q.where(Card.id.in_(card_ids))
            rows = []
            for card in s.execute(q).scalars():
                v = s.execute(select(CardVersion).where(CardVersion.card_id == card.id)
                              .order_by(CardVersion.version_no.desc()).limit(1)).scalar_one()
                rows.append((card, v))
            # Ordem didática inicial (COV-017): deck → ordem didática → criação. Não altera agendamento.
            rows.sort(key=lambda cv: (cv[1].deck_path, cv[1].didactic_order if cv[1].didactic_order is not None
                                      else 10**6, cv[0].created_at))
            for card, v in rows:
                why = None
                blocking = False
                if v.schema_version != "2.1":
                    why = "card legado importado sem conversão para card.v2 (nada a exportar)"
                elif card.state in NEVER_EXPORT or card.quarantine:
                    why, blocking = f"estado {card.state}", True
                elif not preview and card.state not in APPROVED_STATES:
                    why, blocking = f"estado {card.state}: exige aprovação humana antes da exportação (APR-004)", True
                else:
                    errs = s.execute(select(ValidationFinding.message).where(
                        ValidationFinding.card_version_id == v.id, ValidationFinding.level == "ERROR",
                        ValidationFinding.status == "OPEN")).scalars().all()
                    if errs:
                        why, blocking = "erros de validação abertos: " + "; ".join(errs[:3]), True
                gate: list[str] = []
                if not why:
                    # APR-002/APR-003: portão não compensatório. Na prévia o card sai, mas o bloqueio vai ao manifesto.
                    gate = AuditService(self.db).blockers(card.id, include_human=False)
                    if gate and not preview:
                        why, blocking = "portão de liberação: " + "; ".join(gate), True
                if why:
                    skipped.append({"card_key": card.card_key, "card_id": card.id, "reason": why,
                                    "blocking": blocking})
                    continue
                r = render(v.content)
                tags = tuple(dict.fromkeys([*v.tags, f"cf::{card.card_key}"]))
                note = Note(card.card_key, card.anki_guid or "", card.notetype, v.deck_path, r.front, r.back, tags)
                meta = {"card_key": card.card_key, "card_id": card.id, "version_no": v.version_no,
                        "images": [im["file"] for im in v.content.get("images", [])],
                        "source_ids": (v.content.get("short_reference") or {}).get("source_ids", []), "gate": gate}
                selected.append((note, meta))
        return selected, skipped

    def _pending(self, selected: list[tuple[Note, dict[str, Any]]]) -> list[dict[str, Any]]:
        out = []
        ids = [m["card_id"] for _, m in selected]
        with self.db.session() as s:
            for _, meta in selected:
                out += [{"card_key": meta["card_key"], "kind": "BLOQUEIO", "detail": g} for g in meta.get("gate", [])]
                v = s.execute(select(CardVersion).where(CardVersion.card_id == meta["card_id"])
                              .order_by(CardVersion.version_no.desc()).limit(1)).scalar_one()
                for f in s.execute(select(ValidationFinding).where(ValidationFinding.card_version_id == v.id,
                                                                   ValidationFinding.status == "OPEN")).scalars():
                    out.append({"card_key": meta["card_key"], "kind": f"ALERTA:{f.code}", "detail": f.message})
            for m in s.execute(select(MediaAsset).where(MediaAsset.card_id.in_(ids),
                                                        MediaAsset.status == "PENDING")).scalars():
                key = next(mm["card_key"] for _, mm in selected if mm["card_id"] == m.card_id)
                out.append({"card_key": key, "kind": "MIDIA_PENDENTE", "detail": m.finding})
        return out

    def _operations(self, card_ids: list[str]) -> list[dict[str, Any]]:
        with self.db.session() as s:
            ops = s.execute(select(Operation, Card.card_key).join(Card, Card.id == Operation.card_id).where(
                Operation.card_id.in_(card_ids), Operation.kind.in_(["MOVE", "REVIEW_DELETE", "MERGE_REVIEW",
                                                                     "SPLIT", "QUARANTINE", "REVIEW_REQUIRED"])))
            return [{"card_key": k, "kind": o.kind, "status": o.status, "justification": o.justification}
                    for o, k in ops]

    def list(self, project_id: str | None = None) -> list[dict[str, Any]]:
        with self.db.session() as s:
            q = select(ExportRun).order_by(ExportRun.created_at.desc()).limit(100)
            if project_id:
                q = q.where(ExportRun.project_id == project_id)
            return [self._row(r) for r in s.execute(q).scalars()]

    def get(self, export_id: str) -> dict[str, Any]:
        with self.db.session() as s:
            r = s.get(ExportRun, export_id)
            if r is None:
                raise ExportError("exportação não encontrada")
            return {**self._row(r), "diff": r.diff, "card_versions": r.card_versions}

    def file_path(self, export_id: str, name: str) -> Path:
        with self.db.session() as s:
            r = s.get(ExportRun, export_id)
            if r is None or name not in {f["name"] for f in r.files}:
                raise ExportError("arquivo não pertence a esta exportação")
            path = Path(r.report["dir"]) / name
        if not path.resolve().is_relative_to(self.exports_dir.resolve()):
            raise ExportError("caminho fora da pasta de exportações")
        return path

    @staticmethod
    def _row(r: ExportRun) -> dict[str, Any]:
        return {"id": r.id, "project_id": r.project_id, "production_id": r.production_id, "mode": r.mode,
                "format": r.format, "version_label": r.version_label, "state": r.state, "files": r.files,
                "round_trip_ok": r.round_trip_ok, "import_tested": r.import_tested, "report": r.report,
                "previous_export_id": r.previous_export_id, "created_at": r.created_at.isoformat()}
