"""Mesa de revisão humana (Fase 5; APR-004, APR-005, INT-005).

- Aprovação humana é distinta da aprovação automática e só é aceita sem bloqueio aberto (APR-002/003).
- Toda decisão é append-only; desfazer é uma decisão UNDO que restaura o estado anterior.
- Pedido de alteração vira defeito de origem HUMAN, que a etapa de correção pode tratar.
- Propostas de IA (exclusão, fusão, mover, dividir...) só têm efeito com decisão humana; exclusão aceita
  vira estado REJECTED: a nota nunca é apagada e a exportação não remove nada.
- Lições editoriais são escritas por humanos e só entram num prompt por ação humana explícita (versão nova).
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy import select

from cardfactory.audit.service import AuditService, latest_version
from cardfactory.db import Database
from cardfactory.db.models import Card, CardVersion, Defect, EditorialLesson, Operation, ReviewDecision

# Motivos tipificados da revisão → categoria de defeito (R§36.1) usada quando o humano pede alteração.
REASONS: dict[str, tuple[str, str]] = {
    "SCIENTIFIC_ERROR": ("SCIENTIFIC_ERROR", "Erro científico"),
    "OUTDATED": ("OUTDATED", "Conteúdo desatualizado"),
    "NUMERIC": ("NUMERIC_ERROR", "Número, unidade ou operador"),
    "MISSING_CONDITION": ("OMITTED_CONTRAINDICATION", "Condição ou contraindicação omitida"),
    "AMBIGUOUS_FRONT": ("AMBIGUITY", "Frente ambígua ou dependente de contexto"),
    "ANSWER_IN_COMPLEMENT": ("PEDAGOGICAL", "Resposta exigida está no complemento"),
    "GRANULARITY": ("GRANULARITY", "Granularidade inadequada"),
    "REDUNDANT": ("REDUNDANCY", "Redundante com outro card"),
    "TOO_DENSE": ("PEDAGOGICAL", "Denso demais / carga cognitiva"),
    "VISUAL": ("VISUAL", "Cor, negrito ou layout"),
    "SOURCE": ("TRACEABILITY", "Fonte ausente ou que não sustenta"),
    "OUT_OF_SCOPE": ("ALLOCATION", "Fora do escopo ou deck errado"),
    "OTHER": ("PEDAGOGICAL", "Outro (ver nota)"),
}
DECISIONS = ("APPROVE", "REJECT", "REQUEST_CHANGES", "RELEASE_QUARANTINE")
PROPOSAL_KINDS = ("MOVE", "CREATE", "SPLIT", "MERGE_REVIEW", "REVIEW_DELETE", "REVIEW_REQUIRED", "QUARANTINE",
                  "UPDATE_CONTENT", "UPDATE_FRONT", "UPDATE_PEDAGOGY", "UPDATE_STYLE", "KEEP")
QUEUE_ORDER = {"PENDING_HUMAN": 0, "QUARANTINE": 1, "CORRECTED": 2, "AUTO_APPROVED": 3, "IN_AUDIT": 4,
               "GENERATED": 5, "IMPORTED": 6, "DRAFT": 7, "HUMAN_APPROVED": 8, "REJECTED": 9}


class ReviewError(Exception):
    pass


class ReviewService:
    def __init__(self, db: Database):
        self.db = db
        self.audit = AuditService(db)

    # ------------------------------------------------------------------ fila
    def queue(self, *, project_id: str | None = None, production_id: str | None = None, state: str | None = None,
              deck: str = "", include_done: bool = False, limit: int = 200) -> list[dict[str, Any]]:
        with self.db.session() as s:
            q = select(Card)
            if project_id:
                q = q.where(Card.project_id == project_id)
            if production_id:
                q = q.where(Card.production_id == production_id)
            if state:
                q = q.where(Card.state == state)
            elif not include_done:
                q = q.where(Card.state.not_in(["HUMAN_APPROVED", "REJECTED", "READY_FOR_EXPORT",
                                               "COMMERCIALLY_RELEASED"]))
            rows = []
            for c in s.execute(q).scalars():
                v = latest_version(s, c.id)
                if deck and not (v.deck_path == deck or v.deck_path.startswith(deck + "::")):
                    continue
                open_def = Counter(s.execute(select(Defect.severity).where(
                    Defect.card_id == c.id, Defect.status.in_(["OPEN", "ESCALATED"]))).scalars())
                pending_ops = s.execute(select(Operation.id).where(
                    Operation.card_id == c.id, Operation.status == "AWAITING_HUMAN")).scalars().all()
                ds = list(s.execute(select(ReviewDecision).where(ReviewDecision.card_id == c.id)).scalars())
                decided = {d.operation_id for d in ds if d.operation_id and not _undone(d, ds)}
                rows.append({"id": c.id, "card_key": c.card_key, "state": c.state, "quarantine": c.quarantine,
                             "origin": c.origin, "deck_path": v.deck_path, "version_no": v.version_no,
                             "schema_version": v.schema_version, "layout": v.layout,
                             "cognitive_type": v.cognitive_type, "front": _front_text(v),
                             "open_defects": dict(open_def),
                             "pending_proposals": len([o for o in pending_ops if o not in decided]),
                             "created_at": c.created_at.isoformat()})
        rows.sort(key=lambda r: (QUEUE_ORDER.get(r["state"], 5), -sum(
            r["open_defects"].get(k, 0) for k in ("CRITICAL", "HIGH")), r["created_at"]))
        return rows[:limit]

    def detail(self, card_id: str) -> dict[str, Any]:
        """Tudo o que a revisora precisa numa tela: bloqueios, defeitos, afirmações, propostas e decisões."""
        with self.db.session() as s:
            card = s.get(Card, card_id)
            if card is None:
                raise ReviewError("card inexistente")
            ops = list(s.execute(select(Operation).where(Operation.card_id == card_id)
                                 .order_by(Operation.created_at)).scalars())
            decisions = list(s.execute(select(ReviewDecision).where(ReviewDecision.card_id == card_id)
                                       .order_by(ReviewDecision.created_at)).scalars())
            decided = {d.operation_id: d.decision for d in decisions if d.operation_id and not _undone(d, decisions)}
            proposals = [{"id": o.id, "kind": o.kind, "actor": o.actor, "actor_type": o.actor_type,
                          "justification": o.justification, "related_card_ids": o.related_card_ids,
                          "decision": decided.get(o.id), "created_at": o.created_at.isoformat()}
                         for o in ops if o.status == "AWAITING_HUMAN"]
            hist = [_decision_row(d) for d in decisions]
        return {"blockers": self.audit.blockers(card_id, include_human=False),
                "defects": self.audit.defects(card_id=card_id), "claims": self.audit.claim_verdicts(card_id),
                "proposals": proposals, "decisions": hist}

    # ------------------------------------------------------------------ decisões
    def decide(self, card_id: str, decision: str, *, actor: str, reasons: list[str] | None = None, note: str = "",
               duration_ms: int | None = None, started_version_no: int | None = None) -> dict[str, Any]:
        reasons = list(reasons or [])
        if decision not in DECISIONS:
            raise ReviewError(f"decisão inválida: {decision}")
        if not actor.strip():
            raise ReviewError("a decisão humana exige o nome de quem revisou")
        bad = [r for r in reasons if r not in REASONS]
        if bad:
            raise ReviewError(f"motivo desconhecido: {bad}")
        if decision in ("REJECT", "REQUEST_CHANGES") and not reasons:
            raise ReviewError("rejeição e pedido de alteração exigem ao menos um motivo")
        if decision == "RELEASE_QUARANTINE" and not note.strip():
            raise ReviewError("retirar da quarentena exige nota")
        with self.db.session() as s:
            card = s.get(Card, card_id)
            if card is None:
                raise ReviewError("card inexistente")
            prev = card.state
            v = latest_version(s, card_id)
        if decision == "APPROVE":
            blockers = self.audit.blockers(card_id, include_human=False)
            if blockers:
                raise ReviewError("aprovação recusada; resolva antes: " + "; ".join(blockers))
            new = "HUMAN_APPROVED"
        elif decision == "REJECT":
            new = "REJECTED"
        elif decision == "RELEASE_QUARANTINE":
            new = "PENDING_HUMAN"
        else:
            new = "PENDING_HUMAN"
        created: list[str] = []
        if decision == "REQUEST_CHANGES":
            for r in reasons:
                cat, label = REASONS[r]
                did = self.audit.add_defect(card_id=card_id, production_id=None, category=cat, severity="MEDIUM",
                                      description=f"revisão humana ({actor}): {label}" + (f" · {note}" if note else ""),
                                      origin="HUMAN")
                if did:
                    created.append(did)
        edited = started_version_no is not None and v.version_no > started_version_no
        with self.db.write() as s:
            card = s.get(Card, card_id)
            from cardfactory.db.models import CardStateEvent
            if card.state != new:
                s.add(CardStateEvent(card_id=card_id, from_state=card.state, to_state=new, actor=actor,
                                     actor_type="HUMAN", reason=f"{decision}: {', '.join(reasons)} {note}".strip()))
                card.state = new
            if decision == "RELEASE_QUARANTINE":
                card.quarantine = False
            d = ReviewDecision(card_id=card_id, card_version_id=v.id, decision=decision, reasons=reasons, note=note,
                               actor=actor, duration_ms=duration_ms, edited=edited, previous_state=prev,
                               new_state=new, defect_ids=created)
            s.add(d)
            s.flush()
            return {"decision_id": d.id, "state": new, "edited": edited}

    def decide_proposal(self, operation_id: str, accept: bool, *, actor: str, note: str = "") -> dict[str, Any]:
        if not actor.strip():
            raise ReviewError("a decisão humana exige o nome de quem revisou")
        with self.db.session() as s:
            op = s.get(Operation, operation_id)
            if op is None or op.status != "AWAITING_HUMAN":
                raise ReviewError("proposta inexistente ou que não aguarda decisão")
            card = s.get(Card, op.card_id)
            prev, kind, card_id = card.state, op.kind, card.id
            v = latest_version(s, card_id)
            decisions = list(s.execute(select(ReviewDecision).where(ReviewDecision.operation_id == operation_id))
                             .scalars())
            all_dec = list(s.execute(select(ReviewDecision).where(ReviewDecision.card_id == card_id)).scalars())
            if any(not _undone(d, all_dec) for d in decisions):
                raise ReviewError("proposta já decidida (desfaça a decisão anterior para mudar)")
        new = prev
        if accept and kind in ("REVIEW_DELETE", "MERGE_REVIEW"):
            new = "REJECTED"  # INT-005: a nota nunca é apagada; fica fora das próximas exportações
        elif accept and kind == "QUARANTINE":
            new = "QUARANTINE"
        with self.db.write() as s:
            from cardfactory.db.models import CardStateEvent
            card = s.get(Card, card_id)
            if new != prev:
                s.add(CardStateEvent(card_id=card_id, from_state=prev, to_state=new, actor=actor, actor_type="HUMAN",
                                     reason=f"proposta {kind} aceita: {note}".strip()))
                card.state = new
                card.quarantine = card.quarantine or new == "QUARANTINE"
            d = ReviewDecision(card_id=card_id, card_version_id=v.id, operation_id=operation_id,
                               decision="ACCEPT" if accept else "DECLINE", note=note, actor=actor,
                               previous_state=prev, new_state=new)
            s.add(d)
            s.flush()
            needs_edit = accept and kind in ("MOVE", "SPLIT", "CREATE", "UPDATE_CONTENT", "UPDATE_FRONT",
                                             "UPDATE_PEDAGOGY", "UPDATE_STYLE", "REVIEW_REQUIRED")
            return {"decision_id": d.id, "state": new,
                    "note": "aceita: faça a alteração na edição do card (nada é aplicado automaticamente)"
                    if needs_edit else ""}

    def undo(self, card_id: str, *, actor: str) -> dict[str, Any]:
        """Desfaz a última decisão ainda válida do card, restaurando o estado anterior a ela."""
        if not actor.strip():
            raise ReviewError("desfazer exige o nome de quem revisou")
        with self.db.session() as s:
            ds = list(s.execute(select(ReviewDecision).where(ReviewDecision.card_id == card_id)
                                .order_by(ReviewDecision.created_at)).scalars())
        live = [d for d in ds if d.decision != "UNDO" and not _undone(d, ds)]
        if not live:
            raise ReviewError("nada a desfazer")
        last = live[-1]
        with self.db.write() as s:
            from cardfactory.db.models import CardStateEvent
            card = s.get(Card, card_id)
            if card.state != last.previous_state:
                s.add(CardStateEvent(card_id=card_id, from_state=card.state, to_state=last.previous_state,
                                     actor=actor, actor_type="HUMAN", reason=f"desfeita a decisão {last.decision}"))
                card.state = last.previous_state
            if last.decision == "RELEASE_QUARANTINE":
                card.quarantine = True
            if last.decision == "REQUEST_CHANGES":  # os defeitos criados por esta decisão deixam de valer
                for did in last.defect_ids or []:
                    d = s.get(Defect, did)
                    if d is not None and d.status == "OPEN":
                        d.status, d.resolution_note = "JUSTIFIED", f"{actor}: decisão de revisão desfeita"
            u = ReviewDecision(card_id=card_id, card_version_id=last.card_version_id, decision="UNDO",
                               actor=actor, undoes_id=last.id, previous_state=card.state,
                               new_state=last.previous_state)
            s.add(u)
            s.flush()
            return {"decision_id": u.id, "undone": last.id, "state": last.previous_state}

    # ------------------------------------------------------------------ aprendizado editorial e métricas
    def insights(self, *, project_id: str | None = None) -> dict[str, Any]:
        with self.db.session() as s:
            q = select(ReviewDecision, CardVersion.layout, CardVersion.cognitive_type).join(
                CardVersion, CardVersion.id == ReviewDecision.card_version_id, isouter=True)
            if project_id:
                q = q.join(Card, Card.id == ReviewDecision.card_id).where(Card.project_id == project_id)
            rows = s.execute(q.order_by(ReviewDecision.created_at)).all()
        all_d = [r[0] for r in rows]
        live = [(d, lay, ct) for d, lay, ct in rows if d.decision != "UNDO" and not _undone(d, all_d)
                and d.operation_id is None]
        by_decision = Counter(d.decision for d, _, _ in live)
        reasons = Counter(r for d, _, _ in live for r in d.reasons)
        by_layout: dict[str, Counter] = {}
        for d, lay, _ in live:
            for r in d.reasons:
                by_layout.setdefault(lay or "legado", Counter())[r] += 1
        durations = sorted(d.duration_ms for d, _, _ in live if d.duration_ms)
        approved = by_decision.get("APPROVE", 0)
        judged = approved + by_decision.get("REJECT", 0) + by_decision.get("REQUEST_CHANGES", 0)
        return {"decisions": dict(by_decision), "judged": judged,
                "approval_rate": round(approved / judged, 3) if judged else None,
                "approved_with_edit": sum(1 for d, _, _ in live if d.decision == "APPROVE" and d.edited),
                "median_review_seconds": round(durations[len(durations) // 2] / 1000, 1) if durations else None,
                "reasons": [{"code": k, "label": REASONS[k][1], "count": n} for k, n in reasons.most_common()],
                "reasons_by_layout": {k: dict(v) for k, v in by_layout.items()},
                "note": "Frequências das decisões humanas. Não são metas nem pontuação; servem para escrever lições."}

    def add_lesson(self, text: str, *, actor: str, reason_codes: list[str] | None = None,
                   decision_ids: list[str] | None = None) -> str:
        if not text.strip() or not actor.strip():
            raise ReviewError("lição exige texto e autor")
        with self.db.write() as s:
            les = EditorialLesson(text=text.strip(), actor=actor, reason_codes=reason_codes or [],
                                  source_decision_ids=decision_ids or [])
            s.add(les)
            s.flush()
            return les.id

    def lessons(self) -> list[dict[str, Any]]:
        with self.db.session() as s:
            return [{"id": x.id, "text": x.text, "reason_codes": x.reason_codes, "status": x.status, "actor": x.actor,
                     "prompt_version_id": x.prompt_version_id, "created_at": x.created_at.isoformat()}
                    for x in s.execute(select(EditorialLesson).order_by(EditorialLesson.created_at.desc())).scalars()]

    def set_lesson(self, lesson_id: str, status: str, *, actor: str) -> None:
        if status not in ("ACCEPTED", "DISCARDED", "PROPOSED"):
            raise ReviewError("estado inválido")
        with self.db.write() as s:
            les = s.get(EditorialLesson, lesson_id)
            if les is None:
                raise ReviewError("lição inexistente")
            if les.status == "PROMOTED":
                raise ReviewError("lição já incorporada ao prompt; edite o prompt para mudar")
            les.status = status

    def promote_lessons(self, registry, *, actor: str) -> dict[str, Any]:
        """Acrescenta as lições ACEITAS à política editorial como nova versão (reversível na tela Prompts)."""
        if not actor.strip():
            raise ReviewError("incorporar lições exige autor")
        with self.db.session() as s:
            ids_texts = [(x.id, x.text) for x in s.execute(select(EditorialLesson).where(
                EditorialLesson.status == "ACCEPTED").order_by(EditorialLesson.created_at)).scalars()]
        if not ids_texts:
            raise ReviewError("nenhuma lição aceita para incorporar")
        current = registry.active_text("policy:editorial")
        block = "\n\n## Lições da revisão humana\n\n<!-- req: PED-017 -->\n" + "\n".join(
            f"- {t}" for _, t in ids_texts) + "\n"
        vid = registry.edit("policy:editorial", current.rstrip("\n") + block, author=actor,
                            note=f"incorpora {len(ids_texts)} lição(ões) da revisão humana")
        with self.db.write() as s:
            for lid, _ in ids_texts:
                les = s.get(EditorialLesson, lid)
                les.status, les.prompt_version_id = "PROMOTED", vid
        return {"prompt_version_id": vid, "lessons": len(ids_texts)}


def _undone(d: ReviewDecision, all_decisions: list[ReviewDecision]) -> bool:
    return any(x.decision == "UNDO" and x.undoes_id == d.id for x in all_decisions)


def _decision_row(d: ReviewDecision) -> dict[str, Any]:
    return {"id": d.id, "decision": d.decision, "reasons": d.reasons, "note": d.note, "actor": d.actor,
            "operation_id": d.operation_id, "edited": d.edited, "previous_state": d.previous_state,
            "new_state": d.new_state, "undoes_id": d.undoes_id, "duration_ms": d.duration_ms,
            "created_at": d.created_at.isoformat()}


def _front_text(v: CardVersion) -> str:
    from cardfactory.audit.text import front_plain
    try:
        return front_plain(v.content)[:200]
    except (KeyError, TypeError):
        return ""
