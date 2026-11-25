"""Registro de auditorias e defeitos, decisão de estado, gate de liberação e relatório (AUD-007, AUD-014, SCI-021,
APR-002, APR-003, APR-005, INT-007, INT-009, TEC-019).

Tudo que é contado no relatório vem de consultas ao banco, nunca de texto do modelo.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy import func, select

from cardfactory.contracts.schemas import DEFECT_CATEGORIES, SEVERITIES
from cardfactory.db import Database
from cardfactory.db.models import (
    Audit,
    Card,
    CardStateEvent,
    CardVersion,
    Claim,
    ClaimVerdict,
    Defect,
    LearningObjective,
    Operation,
    ProductionVerdict,
    SimilarityPair,
    ValidationFinding,
)

BLOCKING_SEVERITIES = ("CRITICAL", "HIGH")
DISCLAIMER = ("Aprovação automática não é certificação médica. Cards só são liberados após revisão humana "
              "registrada e sem bloqueios (APR-005).")
MAGNITUDE_WARNING = 0.30


class AuditError(ValueError):
    pass


def latest_version(s, card_id: str) -> CardVersion:
    return s.execute(select(CardVersion).where(CardVersion.card_id == card_id)
                     .order_by(CardVersion.version_no.desc()).limit(1)).scalar_one()


def card_claim_ids(s, v: CardVersion) -> list[str]:
    ids = [c["claim_id"] for c in v.content.get("claims", [])] if isinstance(v.content.get("claims"), list) else []
    # Afirmações citadas só nos trechos (sem constar na lista "claims") também contam para a auditoria.
    for b in v.content.get("answer") or []:
        for it in b.get("items") or []:
            for sg in (it.get("segments") or []) + [x for c in it.get("cells") or [] for x in c.get("segments") or []]:
                ids += [i for i in sg.get("claim_ids") or [] if isinstance(i, str)]
    ids += list(s.execute(select(Claim.id).where(Claim.card_version_id.in_(
        select(CardVersion.id).where(CardVersion.card_id == v.card_id)))).scalars())
    return list(dict.fromkeys(ids))


def latest_verdicts(s, claim_ids: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for cid, verdict in s.execute(select(ClaimVerdict.claim_id, ClaimVerdict.verdict)
                                  .where(ClaimVerdict.claim_id.in_(claim_ids)).order_by(ClaimVerdict.created_at)):
        out[cid] = verdict
    return out


class AuditService:
    def __init__(self, db: Database):
        self.db = db

    # ------------------------------------------------------------------ escrita
    def record(self, kind: str, *, production_id: str | None, card_version_id: str | None = None,
               call_id: str | None = None, result: dict[str, Any] | None = None,
               context: dict[str, Any] | None = None) -> str:
        with self.db.write() as s:
            a = Audit(kind=kind, production_id=production_id, card_version_id=card_version_id, llm_call_id=call_id,
                      result=result or {}, context_manifest=context or {})
            s.add(a)
            s.flush()
            return a.id

    def add_defect(self, *, card_id: str | None, production_id: str | None, category: str, severity: str,
                   description: str, audit_id: str | None = None, evidence_ids: list[str] | None = None,
                   origin: str = "AI") -> str | None:
        if category not in DEFECT_CATEGORIES or severity not in SEVERITIES:
            raise AuditError(f"categoria/gravidade inválida: {category}/{severity}")
        with self.db.write() as s:
            dup = s.execute(select(Defect.id).where(Defect.card_id == card_id, Defect.category == category,
                                                    Defect.description == description,
                                                    Defect.status == "OPEN")).first()
            if dup:
                return None
            d = Defect(card_id=card_id, production_id=production_id, audit_id=audit_id or None, category=category,
                       severity=severity, description=description, evidence_ids=evidence_ids or [], origin=origin)
            s.add(d)
            s.flush()
            return d.id

    def set_defect(self, defect_id: str, status: str, *, note: str, actor: str) -> None:
        if status not in ("OPEN", "FIXED", "JUSTIFIED", "ESCALATED"):
            raise AuditError("estado de defeito inválido")
        with self.db.write() as s:
            d = s.get(Defect, defect_id)
            if d is None:
                raise AuditError("defeito não encontrado")
            if status == "JUSTIFIED" and d.severity == "CRITICAL":
                raise AuditError("defeito crítico não pode ser justificado: precisa ser corrigido (APR-002)")
            if not note.strip() or not actor.strip():
                raise AuditError("nota e autor são obrigatórios")
            d.status, d.resolution_note = status, f"{actor}: {note}"

    def set_verdict(self, production_id: str, target: str, dimension: str, status: str, detail: dict) -> None:
        with self.db.write() as s:
            s.add(ProductionVerdict(production_id=production_id, target=target, dimension=dimension, status=status,
                                    detail=detail))

    # ------------------------------------------------------------------ estado e gate
    def blockers(self, card_id: str, *, include_human: bool = True) -> list[str]:
        """APR-002: lista não compensatória de bloqueios (APR-003: nada compensa um bloqueio)."""
        with self.db.session() as s:
            card = s.get(Card, card_id)
            v = latest_version(s, card_id)
            out = []
            if card.quarantine or card.state == "QUARANTINE":
                out.append("card em quarentena")
            n = s.execute(select(func.count()).select_from(Defect).where(
                Defect.card_id == card_id, Defect.status.in_(["OPEN", "ESCALATED"]),
                Defect.severity == "CRITICAL")).scalar_one()
            if n:
                out.append(f"{n} defeito(s) crítico(s) aberto(s)")
            n = s.execute(select(func.count()).select_from(Defect).where(
                Defect.card_id == card_id, Defect.status.in_(["OPEN", "ESCALATED"]),
                Defect.severity == "HIGH")).scalar_one()
            if n:
                out.append(f"{n} defeito(s) de gravidade alta aberto(s)")
            ids = card_claim_ids(s, v)
            crit = list(s.execute(select(Claim.id).where(Claim.id.in_(ids), Claim.criticality == "CRITICAL"))
                        .scalars())
            verdicts = latest_verdicts(s, crit)
            unconfirmed = [c for c in crit if verdicts.get(c) != "CONFIRMED"]
            if unconfirmed:
                out.append(f"{len(unconfirmed)} afirmação(ões) crítica(s) sem CONFIRMADA (SCI-021)")
            errs = s.execute(select(func.count()).select_from(ValidationFinding).where(
                ValidationFinding.card_version_id == v.id, ValidationFinding.level == "ERROR",
                ValidationFinding.status == "OPEN")).scalar_one()
            if errs:
                out.append(f"{errs} erro(s) técnico(s) de validação")
            pair = s.execute(select(func.count()).select_from(SimilarityPair).where(
                (SimilarityPair.card_a_id == card_id) | (SimilarityPair.card_b_id == card_id),
                SimilarityPair.kind == "CONTRADICTION", SimilarityPair.status != "RESOLVED")).scalar_one()
            if pair:
                out.append("contradição com outro card não resolvida")
            if include_human and card.state not in ("HUMAN_APPROVED", "READY_FOR_EXPORT", "COMMERCIALLY_RELEASED"):
                out.append("revisão humana pendente (APR-004)")
            return out

    def decide_state(self, card_id: str, *, actor: str) -> str:
        """Depois da auditoria: QUARENTENA (crítica não verificada), PENDENTE HUMANO (com bloqueio) ou
        AUTO_APROVADO (sem bloqueio técnico ou científico; ainda exige revisão humana)."""
        with self.db.session() as s:
            card = s.get(Card, card_id)
            if card.state in ("HUMAN_APPROVED", "REJECTED"):
                return card.state
            v = latest_version(s, card_id)
            crit = list(s.execute(select(Claim.id).where(Claim.id.in_(card_claim_ids(s, v)),
                                                         Claim.criticality == "CRITICAL")).scalars())
            verdicts = latest_verdicts(s, crit)
            bad_critical = [c for c in crit if verdicts.get(c) in ("NOT_VERIFIED", "INCORRECT", "OUTDATED", None)]
            already_quarantined = card.quarantine
        blockers = self.blockers(card_id, include_human=False)
        if already_quarantined:  # quarentena vinda da importação ou de humano: só um humano a retira
            new, reason = "QUARANTINE", "; ".join(blockers) or "quarentena preexistente"
        elif bad_critical:
            new, reason = "QUARANTINE", "afirmação crítica não verificada ou incorreta (SCI-021)"
        elif blockers:
            new, reason = "PENDING_HUMAN", "; ".join(blockers)
        else:
            new, reason = "AUTO_APPROVED", "sem bloqueios após auditoria; aguarda revisão humana"
        with self.db.write() as s:
            card = s.get(Card, card_id)
            if card.state != new:
                s.add(CardStateEvent(card_id=card_id, from_state=card.state, to_state=new, actor=actor,
                                     actor_type="SYSTEM", reason=reason))
                card.state = new
                card.quarantine = card.quarantine or new == "QUARANTINE"
        return new

    # ------------------------------------------------------------------ leitura
    def defects(self, *, card_id: str | None = None, production_id: str | None = None,
                status: str | None = None) -> list[dict[str, Any]]:
        with self.db.session() as s:
            q = select(Defect, Card.card_key).outerjoin(Card, Card.id == Defect.card_id).order_by(Defect.created_at)
            if card_id:
                q = q.where(Defect.card_id == card_id)
            if production_id:
                q = q.where(Defect.production_id == production_id)
            if status:
                q = q.where(Defect.status == status)
            return [{"id": d.id, "card_id": d.card_id, "card_key": k, "category": d.category, "severity": d.severity,
                     "description": d.description, "status": d.status, "origin": d.origin,
                     "correction_attempts": d.correction_attempts, "evidence_ids": d.evidence_ids,
                     "resolution_note": d.resolution_note, "created_at": d.created_at.isoformat()}
                    for d, k in s.execute(q).all()]

    def claim_verdicts(self, card_id: str) -> list[dict[str, Any]]:
        with self.db.session() as s:
            v = latest_version(s, card_id)
            ids = card_claim_ids(s, v)
            claims = {c.id: c for c in s.execute(select(Claim).where(Claim.id.in_(ids))).scalars()}
            rows = list(s.execute(select(ClaimVerdict).where(ClaimVerdict.claim_id.in_(ids))
                                  .order_by(ClaimVerdict.created_at)).scalars())
            last: dict[str, ClaimVerdict] = {}
            for r in rows:
                last[r.claim_id] = r
            return [{"claim_id": cid, "text": claims[cid].text if cid in claims else "",
                     "criticality": claims[cid].criticality if cid in claims else "",
                     "verdict": last[cid].verdict if cid in last else None,
                     "rationale": last[cid].rationale if cid in last else "",
                     "evidence_ids": last[cid].evidence_ids if cid in last else []} for cid in ids]

    def report(self, production_id: str) -> dict[str, Any]:
        with self.db.session() as s:
            cards = list(s.execute(select(Card).where(Card.production_id == production_id)).scalars())
            ids = [c.id for c in cards]
            defects = list(s.execute(select(Defect).where(Defect.card_id.in_(ids) | (Defect.production_id ==
                                                                                      production_id))).scalars())
            ops = Counter(o for o in s.execute(select(Operation.kind).where(Operation.card_id.in_(ids))).scalars())
            changed = s.execute(select(func.count(func.distinct(Operation.card_id))).where(
                Operation.card_id.in_(ids), Operation.kind.like("UPDATE_%"))).scalar_one()
            imported = sum(1 for c in cards if c.origin == "IMPORTED")
            created = ops.get("CREATE", 0)
            proposed_deletes = ops.get("REVIEW_DELETE", 0)
            all_claims: list[str] = []
            for c in cards:
                all_claims += card_claim_ids(s, latest_version(s, c.id))
            verdicts = latest_verdicts(s, all_claims)
            verdict_counts = Counter(verdicts.get(c, "SEM_VEREDITO") for c in dict.fromkeys(all_claims))
            sims = Counter((p.layer, p.kind or "NÃO CLASSIFICADO") for p in s.execute(
                select(SimilarityPair).where(SimilarityPair.card_a_id.in_(ids) | SimilarityPair.card_b_id.in_(ids)))
                .scalars())
            pv = list(s.execute(select(ProductionVerdict).where(ProductionVerdict.production_id == production_id)
                                .order_by(ProductionVerdict.created_at)).scalars())
            objectives = Counter(s.execute(select(LearningObjective.coverage_state).where(
                LearningObjective.production_id == production_id)).scalars())
        dims: dict[str, dict[str, Any]] = {}
        for v in pv:  # último por (alvo, dimensão), nunca média (AUD-014)
            dims.setdefault(v.dimension, {})[v.target] = {"status": v.status, "detail": v.detail}
        base = max(1, len(cards))
        magnitude = changed / base
        warn = magnitude > MAGNITUDE_WARNING and changed > 0 and imported > 0  # INT-007: vale para deck existente
        open_def = [d for d in defects if d.status in ("OPEN", "ESCALATED")]
        return {
            "production_id": production_id,
            "cards": {"total": len(cards), "by_state": dict(Counter(c.state for c in cards))},
            "defects": {"total": len(defects), "open": len(open_def),
                        "by_severity_open": dict(Counter(d.severity for d in open_def)),
                        "by_category": dict(Counter(d.category for d in defects)),
                        "by_status": dict(Counter(d.status for d in defects))},
            "claims": {"total": len(set(all_claims)), "by_verdict": dict(verdict_counts)},
            "objectives": {"denominator": sum(objectives.values()), "by_state": dict(objectives)},
            "operations": dict(ops),
            "similarity": [{"layer": k[0], "kind": k[1], "count": n} for k, n in sims.items()],
            "magnitude": {"changed_cards": changed, "fraction": round(magnitude, 3),
                          "warning": warn,
                          "note": "mais de 30% do deck alterado: faça backup e revise por tipo de alteração (INT-007)"
                          if warn else ""},
            "final_state": {"original": imported, "created": created, "proposed_deletions": proposed_deletes,
                            "expected_after_import": imported + created,
                            "note": "exclusões são só propostas: nenhuma nota é removida pela exportação (INT-005)",
                            "reconciled": imported + created == len(cards)},
            "verdicts": dims,
            "disclaimer": DISCLAIMER,
        }
