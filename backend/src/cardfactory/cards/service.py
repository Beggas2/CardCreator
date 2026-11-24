"""Cards estruturados: criação, versões append-only, rollback, HTML derivado, achados e mídia (INT-012, TEC-015).

- Toda alteração cria uma nova `card_version`; nada é sobrescrito nem apagado.
- Rollback = nova versão com o conteúdo de uma versão anterior (`restored_from_version`).
- O HTML é derivado do JSON e registrado em `rendered_artifact` para reprodutibilidade.
- Achados de validação têm ciclo de vida: OPEN → FIXED (sumiu na versão seguinte) ou JUSTIFIED (só alertas).
"""

from __future__ import annotations

import difflib
import hashlib
import json
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from cardfactory.cards.model import CardError, content_hash, structural_errors, to_stored
from cardfactory.db import Database
from cardfactory.db.models import (
    Card,
    CardObjective,
    CardStateEvent,
    CardVersion,
    LearningObjective,
    MediaAsset,
    Operation,
    RenderedArtifact,
    ValidationFinding,
)
from cardfactory.ids import new_id
from cardfactory.render.palette import DARK, PALETTES
from cardfactory.render.renderer import render
from cardfactory.validation.card_checks import check_card

OPERATIONS = ("KEEP", "UPDATE_CONTENT", "UPDATE_FRONT", "UPDATE_PEDAGOGY", "UPDATE_STYLE", "MOVE", "CREATE", "SPLIT",
              "MERGE_REVIEW", "REVIEW_DELETE", "QUARANTINE", "REVIEW_REQUIRED", "ROLLBACK")
IMAGE_MAGIC = {b"\x89PNG\r\n\x1a\n": ".png", b"\xff\xd8\xff": ".jpg", b"GIF87a": ".gif", b"GIF89a": ".gif"}
MAX_MEDIA_BYTES = 5 * 1024 * 1024


class CardServiceError(ValueError):
    pass


def _image_ext(data: bytes) -> str | None:
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return next((ext for magic, ext in IMAGE_MAGIC.items() if data.startswith(magic)), None)


class CardService:
    def __init__(self, db: Database, media_dir: Path, *, deck_prefix: str = "IGOR"):
        self.db = db
        self.media_dir = media_dir
        self.deck_prefix = deck_prefix

    # ------------------------------------------------------------------ escrita
    def create(self, project_id: str, model_card: dict[str, Any], *, production_id: str | None = None,
               origin: str = "GENERATED", author_type: str = "AI", actor: str = "system", call_id: str | None = None,
               state: str = "GENERATED", didactic_order: int | None = None) -> str:
        card_key = new_id("ck")
        stored = to_stored(model_card, card_key=card_key)
        with self.db.write() as s:
            card = Card(project_id=project_id, card_key=card_key, production_id=production_id, origin=origin,
                        state=state)
            s.add(card)
            s.flush()
            v = self._add_version(s, card, stored, 1, author_type=author_type, call_id=call_id,
                                  didactic_order=didactic_order, note="criação")
            s.add(Operation(card_id=card.id, kind="CREATE", to_version_id=v.id, actor=actor,
                            actor_type=author_type if author_type != "IMPORT" else "SYSTEM",
                            justification="card novo para objetivo(s) " + ", ".join(stored["objective_ids"])))
            s.add(CardStateEvent(card_id=card.id, from_state="DRAFT", to_state=state, actor=actor,
                                 actor_type=author_type if author_type in ("AI", "HUMAN") else "SYSTEM",
                                 reason="criação"))
            for mr in stored["media_requests"]:
                s.add(MediaAsset(card_id=card.id, finding=mr["finding"], desired_source=mr["desired_source"],
                                 purpose=mr["purpose"]))
            return card.id

    def new_version(self, card_id: str, content: dict[str, Any], *, kind: str = "UPDATE_CONTENT",
                    author_type: str = "HUMAN", actor: str, note: str = "", objective_change: str = "EQUIVALENT",
                    call_id: str | None = None) -> dict[str, Any]:
        if kind not in OPERATIONS:
            raise CardServiceError(f"operação desconhecida: {kind}")
        if author_type == "HUMAN" and not actor.strip():
            raise CardServiceError("edição humana exige autor")
        with self.db.write() as s:
            card = self._card(s, card_id)
            last = self._last(s, card.id)
            if last.schema_version != "2.1":
                raise CardServiceError("card legado: converta para card.v2 antes de editar")
            model = {k: v for k, v in content.items() if k not in ("schema_version", "card_key", "anki_guid",
                                                                     "images", "validation_status")}
            stored = to_stored(model, card_key=card.card_key, anki_guid=card.anki_guid,
                               images=content.get("images", last.content.get("images", [])))
            if content_hash(stored) == last.content_hash:
                return {"version_no": last.version_no, "changed": False}
            v = self._add_version(s, card, stored, last.version_no + 1, author_type=author_type, call_id=call_id,
                                  didactic_order=last.didactic_order, note=note, objective_change=objective_change)
            s.add(Operation(card_id=card.id, kind=kind, from_version_id=last.id, to_version_id=v.id, actor=actor,
                            actor_type=author_type, justification=note))
            return {"version_no": v.version_no, "changed": True, "version_id": v.id}

    def rollback(self, card_id: str, to_version_no: int, *, actor: str, reason: str) -> dict[str, Any]:
        if not actor.strip() or not reason.strip():
            raise CardServiceError("rollback exige autor e motivo")
        with self.db.write() as s:
            card = self._card(s, card_id)
            target = s.execute(select(CardVersion).where(CardVersion.card_id == card.id,
                                                         CardVersion.version_no == to_version_no)).scalar_one_or_none()
            if target is None:
                raise CardServiceError(f"versão {to_version_no} não existe")
            last = self._last(s, card.id)
            if target.id == last.id:
                raise CardServiceError("essa já é a versão atual")
            v = CardVersion(card_id=card.id, version_no=last.version_no + 1, schema_version=target.schema_version,
                            content=target.content, deck_path=target.deck_path, tags=target.tags,
                            author_type="HUMAN", objective_change=target.objective_change,
                            content_hash=target.content_hash, cognitive_type=target.cognitive_type,
                            layout=target.layout, didactic_order=target.didactic_order, note=reason,
                            restored_from_version=target.version_no)
            s.add(v)
            s.flush()
            for oid in s.execute(select(CardObjective).where(CardObjective.card_version_id == target.id)).scalars():
                s.add(CardObjective(card_version_id=v.id, objective_id=oid.objective_id, role=oid.role))
            if target.schema_version == "2.1":
                self._derive(s, v, last)
            s.add(Operation(card_id=card.id, kind="ROLLBACK", from_version_id=last.id, to_version_id=v.id,
                            actor=actor, actor_type="HUMAN", justification=reason))
            return {"version_no": v.version_no, "restored_from_version": target.version_no}

    def set_state(self, card_id: str, to_state: str, *, actor: str, actor_type: str, reason: str) -> None:
        with self.db.write() as s:
            card = self._card(s, card_id)
            s.add(CardStateEvent(card_id=card.id, from_state=card.state, to_state=to_state, actor=actor,
                                 actor_type=actor_type, reason=reason))
            card.state = to_state
            card.quarantine = to_state == "QUARANTINE"

    def justify(self, finding_id: str, justification: str, *, actor: str) -> None:
        if not justification.strip() or not actor.strip():
            raise CardServiceError("justificativa e autor são obrigatórios")
        with self.db.write() as s:
            f = s.get(ValidationFinding, finding_id)
            if f is None:
                raise CardServiceError("achado não encontrado")
            if f.level == "ERROR":
                raise CardServiceError("erro bloqueante não pode ser justificado: precisa ser corrigido (TEC-011)")
            f.status, f.justification, f.resolved_by = "JUSTIFIED", justification, actor

    def attach_media(self, asset_id: str, data: bytes, *, alt: str, side: str, license: str, rights_verified: bool,
                     actor: str) -> dict[str, Any]:
        """VIS-016: só imagem real, com direitos verificados, vira mídia do card."""
        if not rights_verified or not license.strip():
            raise CardServiceError("imagem só entra com licença informada e direitos verificados")
        if len(data) > MAX_MEDIA_BYTES:
            raise CardServiceError("imagem acima de 5 MB")
        ext = _image_ext(data)
        if ext is None:
            raise CardServiceError("arquivo não é PNG, JPEG, GIF ou WebP")
        if side not in ("front", "back"):
            raise CardServiceError("lado deve ser front ou back")
        digest = hashlib.sha256(data).hexdigest()
        name = f"cf_{digest[:24]}{ext}"
        self.media_dir.mkdir(parents=True, exist_ok=True)
        (self.media_dir / name).write_bytes(data)
        with self.db.write() as s:
            asset = s.get(MediaAsset, asset_id)
            if asset is None:
                raise CardServiceError("pedido de mídia não encontrado")
            asset.status, asset.file_name, asset.sha256 = "OBTAINED", name, digest
            asset.license, asset.rights_verified = license, True
            card_id = asset.card_id
            content = dict(self._last(s, card_id).content)
        images = [*content.get("images", []), {"file": name, "alt": alt, "side": side}]
        res = self.new_version(card_id, {**content, "images": images}, kind="UPDATE_STYLE", actor=actor,
                               note=f"imagem {name} anexada")
        return {"file": name, **res}

    # ------------------------------------------------------------------ leitura
    def get(self, card_id: str) -> dict[str, Any]:
        with self.db.session() as s:
            card = self._card(s, card_id)
            versions = list(s.execute(select(CardVersion).where(CardVersion.card_id == card.id)
                                      .order_by(CardVersion.version_no)).scalars())
            last = versions[-1]
            findings = list(s.execute(select(ValidationFinding).where(ValidationFinding.card_version_id == last.id)
                                      .order_by(ValidationFinding.level, ValidationFinding.code)).scalars())
            ops = list(s.execute(select(Operation).where(Operation.card_id == card.id)
                                 .order_by(Operation.created_at)).scalars())
            media = list(s.execute(select(MediaAsset).where(MediaAsset.card_id == card.id)).scalars())
            events = list(s.execute(select(CardStateEvent).where(CardStateEvent.card_id == card.id)
                                    .order_by(CardStateEvent.created_at)).scalars())
            vno = {v.id: v.version_no for v in versions}
            out = {
                "id": card.id, "card_key": card.card_key, "anki_guid": card.anki_guid, "state": card.state,
                "origin": card.origin, "notetype": card.notetype, "quarantine": card.quarantine,
                "production_id": card.production_id, "content": last.content, "schema_version": last.schema_version,
                "deck_path": last.deck_path, "tags": last.tags,
                "versions": [{"version_no": v.version_no, "author_type": v.author_type, "note": v.note,
                              "created_at": v.created_at.isoformat(), "content_hash": v.content_hash,
                              "restored_from_version": v.restored_from_version} for v in versions],
                "findings": [{"id": f.id, "level": f.level, "code": f.code, "message": f.message,
                              "status": f.status, "justification": f.justification} for f in findings],
                "operations": [{"kind": o.kind, "from": vno.get(o.from_version_id), "to": vno.get(o.to_version_id),
                                "actor": o.actor, "actor_type": o.actor_type, "justification": o.justification,
                                "status": o.status, "created_at": o.created_at.isoformat()} for o in ops],
                "media": [{"id": m.id, "status": m.status, "finding": m.finding, "purpose": m.purpose,
                           "desired_source": m.desired_source, "file_name": m.file_name, "license": m.license}
                          for m in media],
                "events": [{"from": e.from_state, "to": e.to_state, "actor": e.actor, "reason": e.reason,
                            "at": e.created_at.isoformat()} for e in events],
            }
        out["rendered"] = self.preview(out["content"]) if out["schema_version"] == "2.1" else None
        return out

    def preview(self, content: dict[str, Any]) -> dict[str, Any]:
        return {name: {"front": r.front, "back": r.back}
                for name, r in ((n, render(content, p)) for n, p in PALETTES.items())}

    def diff(self, card_id: str, a: int, b: int) -> dict[str, Any]:
        with self.db.session() as s:
            card = self._card(s, card_id)
            vs = {v.version_no: v for v in s.execute(select(CardVersion).where(
                CardVersion.card_id == card.id, CardVersion.version_no.in_([a, b]))).scalars()}
            if a not in vs or b not in vs:
                raise CardServiceError("versão inexistente")
            ja = json.dumps(vs[a].content, ensure_ascii=False, indent=1, sort_keys=True).splitlines()
            jb = json.dumps(vs[b].content, ensure_ascii=False, indent=1, sort_keys=True).splitlines()
            return {"a": a, "b": b, "unified": "\n".join(difflib.unified_diff(ja, jb, f"v{a}", f"v{b}", lineterm="")),
                    "same_content": vs[a].content_hash == vs[b].content_hash}

    def list(self, *, project_id: str | None = None, production_id: str | None = None, state: str | None = None,
             limit: int = 200) -> list[dict[str, Any]]:
        with self.db.session() as s:
            latest = select(CardVersion.card_id, func.max(CardVersion.version_no).label("n")) \
                .group_by(CardVersion.card_id).subquery()
            q = select(Card, CardVersion).join(latest, latest.c.card_id == Card.id) \
                .join(CardVersion, (CardVersion.card_id == Card.id) & (CardVersion.version_no == latest.c.n)) \
                .order_by(Card.created_at.desc()).limit(limit)
            if project_id:
                q = q.where(Card.project_id == project_id)
            if production_id:
                q = q.where(Card.production_id == production_id)
            if state:
                q = q.where(Card.state == state)
            rows = s.execute(q).all()
            open_counts = dict(s.execute(select(ValidationFinding.card_version_id, func.count()).where(
                ValidationFinding.status == "OPEN",
                ValidationFinding.card_version_id.in_([v.id for _, v in rows])).group_by(
                ValidationFinding.card_version_id)).all())
            errors = dict(s.execute(select(ValidationFinding.card_version_id, func.count()).where(
                ValidationFinding.status == "OPEN", ValidationFinding.level == "ERROR",
                ValidationFinding.card_version_id.in_([v.id for _, v in rows])).group_by(
                ValidationFinding.card_version_id)).all())
            return [{"id": c.id, "card_key": c.card_key, "state": c.state, "origin": c.origin,
                     "anki_guid": c.anki_guid, "version_no": v.version_no, "deck_path": v.deck_path,
                     "layout": v.layout, "cognitive_type": v.cognitive_type, "schema_version": v.schema_version,
                     "front_text": _front_text(v.content), "open_findings": open_counts.get(v.id, 0),
                     "open_errors": errors.get(v.id, 0), "production_id": c.production_id,
                     "created_at": c.created_at.isoformat()} for c, v in rows]

    # ------------------------------------------------------------------ internos
    def _card(self, s, card_id: str) -> Card:
        card = s.get(Card, card_id)
        if card is None:
            card = s.execute(select(Card).where(Card.card_key == card_id)).scalar_one_or_none()
        if card is None:
            raise CardServiceError("card não encontrado")
        return card

    def _last(self, s, card_id: str) -> CardVersion:
        return s.execute(select(CardVersion).where(CardVersion.card_id == card_id)
                         .order_by(CardVersion.version_no.desc()).limit(1)).scalar_one()

    def _add_version(self, s, card: Card, stored: dict[str, Any], version_no: int, *, author_type: str,
                     call_id: str | None, didactic_order: int | None, note: str,
                     objective_change: str = "EQUIVALENT") -> CardVersion:
        prev = self._last(s, card.id) if version_no > 1 else None
        v = CardVersion(card_id=card.id, version_no=version_no, schema_version="2.1", content=stored,
                        deck_path="::".join(stored["deck_path"]), tags=stored["tags"], author_type=author_type,
                        created_by_call_id=call_id, objective_change=objective_change,
                        content_hash=content_hash(stored), cognitive_type=stored["cognitive_type"],
                        layout=stored["layout"], didactic_order=didactic_order, note=note)
        s.add(v)
        s.flush()
        known = set(s.execute(select(LearningObjective.id).where(
            LearningObjective.id.in_(stored["objective_ids"]))).scalars())
        for i, oid in enumerate(dict.fromkeys(stored["objective_ids"])):
            if oid in known:
                s.add(CardObjective(card_version_id=v.id, objective_id=oid, role="PRIMARY" if i == 0 else "SECONDARY"))
        self._derive(s, v, prev)
        return v

    def _derive(self, s, v: CardVersion, prev: CardVersion | None) -> None:
        r = render(v.content, DARK)
        s.add(RenderedArtifact(card_version_id=v.id, renderer_version=r.renderer_version, palette=r.palette,
                               front_html=r.front, back_html=r.back,
                               html_hash=hashlib.sha256((r.front + "\x1f" + r.back).encode()).hexdigest()))
        findings = check_card(v.content, r, deck_prefix=self.deck_prefix)
        previous: dict[tuple[str, str], ValidationFinding] = {}
        if prev is not None:
            for f in s.execute(select(ValidationFinding).where(ValidationFinding.card_version_id == prev.id)):
                previous[(f[0].code, f[0].message)] = f[0]
        current = set()
        for f in findings:
            key = (f.code, f.message)
            current.add(key)
            old = previous.get(key)
            carried = old is not None and old.status == "JUSTIFIED" and f.level == "WARNING"
            s.add(ValidationFinding(card_version_id=v.id, code=f.code, level=f.level, message=f.message,
                                    status="JUSTIFIED" if carried else "OPEN",
                                    justification=old.justification if carried else "",
                                    resolved_by=old.resolved_by if carried else ""))
        for key, old in previous.items():
            if key not in current and old.status == "OPEN":
                old.status, old.resolved_by = "FIXED", "nova versão"


def _front_text(content: dict[str, Any]) -> str:
    if "front" in content and isinstance(content["front"], dict):
        return "".join(sg["text"] for sg in content["front"]["segments"])[:200]
    from cardfactory.validation.html import normalized_text
    return normalized_text(content.get("front_html", "") or content.get("front", ""))[:200]


__all__ = ["CardError", "CardService", "CardServiceError", "OPERATIONS", "structural_errors"]
