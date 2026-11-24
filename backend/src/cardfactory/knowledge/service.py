"""Conhecimento estruturado: entidades, mapa de 57 dimensões, objetivos, afirmações e evidências.

Garante COV-002/003/004/005/013, TEC-017 (reserva atômica de objetivos), SCI-013/022.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update

from cardfactory.db import Database
from cardfactory.db.models import (
    Claim,
    ClaimEvidence,
    ClaimVerdict,
    ClinicalEntity,
    DecisionPoint,
    EvidenceSpan,
    LearningObjective,
    MapDimension,
    ObjectiveDependency,
)
from cardfactory.knowledge.dimensions import (
    CLAIM_COMPONENTS,
    COVERAGE_STATES,
    CRITICALITY,
    DIMENSIONS,
    KNOWLEDGE_LEVELS,
    MAP_STATES,
    NECESSITY,
    NEGATION_KINDS,
    VERDICTS,
)


class KnowledgeError(Exception):
    pass


def _check(value: str | None, allowed: tuple[str, ...], name: str) -> None:
    if value is not None and value not in allowed:
        raise KnowledgeError(f"{name} inválido: {value} (permitidos: {', '.join(allowed)})")


class Knowledge:
    def __init__(self, db: Database):
        self.db = db

    # ------------------------------------------------------------ entidades e mapa
    def upsert_entity(self, project_id: str, name: str, *, synonyms: list[str] | None = None,
                      home_deck_path: str = "") -> str:
        name = " ".join(name.split())
        if not name:
            raise KnowledgeError("entidade sem nome")
        with self.db.write() as s:
            e = s.execute(select(ClinicalEntity).where(ClinicalEntity.project_id == project_id,
                                                       ClinicalEntity.name == name)).scalar_one_or_none()
            if e is None:
                e = ClinicalEntity(project_id=project_id, name=name, synonyms=synonyms or [],
                                   home_deck_path=home_deck_path)
                s.add(e)
                s.flush()
            else:
                e.synonyms = sorted(set(e.synonyms or []) | set(synonyms or []))
                e.home_deck_path = home_deck_path or e.home_deck_path
            return e.id

    def set_map(self, entity_id: str, dims: dict[int, tuple[str, str]], *, origin: str = "CREATOR",
                call_id: str | None = None) -> None:
        """Grava o mapa (código → (estado, justificativa)). Todas as 57 dimensões precisam estar classificadas."""
        _check(origin, ("CREATOR", "INDEPENDENT"), "origem do mapa")
        missing = sorted(set(DIMENSIONS) - set(dims))
        extra = sorted(set(dims) - set(DIMENSIONS))
        if missing or extra:
            raise KnowledgeError(f"mapa incompleto: faltam {missing}, desconhecidas {extra}")
        for code, (state, just) in dims.items():
            _check(state, MAP_STATES, f"estado da dimensão {code}")
            if state != "APPLICABLE_COVERED" and state != "APPLICABLE_PENDING" and not just.strip():
                raise KnowledgeError(f"dimensão {code} ({DIMENSIONS[code]}) em {state} exige justificativa")
        with self.db.write() as s:
            for row in s.execute(select(MapDimension).where(MapDimension.entity_id == entity_id,
                                                            MapDimension.map_origin == origin)).scalars():
                s.delete(row)
            s.flush()
            for code, (state, just) in sorted(dims.items()):
                s.add(MapDimension(entity_id=entity_id, dimension_code=code, state=state, justification=just,
                                   map_origin=origin, origin_call_id=call_id))

    def get_map(self, entity_id: str, origin: str = "CREATOR") -> dict[int, dict[str, str]]:
        with self.db.session() as s:
            rows = s.execute(select(MapDimension).where(MapDimension.entity_id == entity_id,
                                                        MapDimension.map_origin == origin)).scalars()
            return {r.dimension_code: {"name": DIMENSIONS[r.dimension_code], "state": r.state,
                                       "justification": r.justification} for r in rows}

    def compare_maps(self, entity_id: str) -> list[dict[str, Any]]:
        """COV-013: diferenças entre o mapa do criador e o mapa independente."""
        a, b = self.get_map(entity_id, "CREATOR"), self.get_map(entity_id, "INDEPENDENT")
        if not a or not b:
            raise KnowledgeError("os dois mapas precisam existir para comparar")
        return [{"code": c, "name": DIMENSIONS[c], "creator": a[c]["state"], "independent": b[c]["state"],
                 "creator_justification": a[c]["justification"], "independent_justification": b[c]["justification"]}
                for c in sorted(DIMENSIONS) if a[c]["state"] != b[c]["state"]]

    def add_decision_point(self, entity_id: str, description: str, condition_axis: str = "",
                           disposition_relevant: bool = False) -> str:
        with self.db.write() as s:
            d = DecisionPoint(entity_id=entity_id, description=description, condition_axis=condition_axis,
                              disposition_relevant=disposition_relevant)
            s.add(d)
            s.flush()
            return d.id

    # ------------------------------------------------------------ objetivos
    def add_objective(self, project_id: str, description: str, *, entity_id: str | None = None,
                      production_id: str | None = None, knowledge_level: str = "FACTUAL",
                      necessity: str = "REQUIRED", coverage_state: str = "ABSENT", purpose: str = "",
                      subtopic: str = "", knowledge_type: str = "", area: str = "", clinical_relevance: str = "MEDIUM",
                      exam_relevance: str = "UNKNOWN", planned_cards: int = 1, planned_rationale: str = "",
                      depends_on: list[str] | None = None, call_id: str | None = None) -> str:
        _check(knowledge_level, KNOWLEDGE_LEVELS, "nível")
        _check(necessity, NECESSITY, "necessidade")
        _check(coverage_state, COVERAGE_STATES, "estado de cobertura")
        if not description.strip():
            raise KnowledgeError("objetivo sem descrição")
        if necessity in ("REQUIRED", "RECOMMENDED") and not purpose.strip():
            raise KnowledgeError("objetivo obrigatório/recomendado exige propósito (COV-014)")
        if planned_cards < 0 or planned_cards > 20:
            raise KnowledgeError("quantidade planejada fora do intervalo 0–20")
        with self.db.write() as s:
            o = LearningObjective(project_id=project_id, production_id=production_id, entity_id=entity_id,
                                  description=description.strip(), knowledge_level=knowledge_level, necessity=necessity,
                                  coverage_state=coverage_state, purpose=purpose, subtopic=subtopic,
                                  knowledge_type=knowledge_type, area=area, clinical_relevance=clinical_relevance,
                                  exam_relevance=exam_relevance, planned_cards=planned_cards,
                                  planned_rationale=planned_rationale, origin_call_id=call_id)
            s.add(o)
            s.flush()
            for dep in depends_on or []:
                if s.get(LearningObjective, dep) is None:
                    raise KnowledgeError(f"dependência inexistente: {dep}")
                s.add(ObjectiveDependency(objective_id=o.id, depends_on_id=dep))
            return o.id

    def set_coverage(self, objective_id: str, state: str) -> None:
        _check(state, COVERAGE_STATES, "estado de cobertura")
        with self.db.write() as s:
            s.get(LearningObjective, objective_id).coverage_state = state

    def lease_objectives(self, production_id: str, owner: str, limit: int, lease_s: float = 900) -> list[str]:
        """TEC-017: reserva atômica de objetivos para um lote; lotes paralelos nunca recebem o mesmo objetivo."""
        now = datetime.now(UTC)
        out: list[str] = []
        with self.db.write() as s:  # BEGIN IMMEDIATE: um lote por vez decide
            cands = s.execute(select(LearningObjective.id).where(
                LearningObjective.production_id == production_id,
                LearningObjective.necessity.in_(["REQUIRED", "RECOMMENDED"]),
                LearningObjective.coverage_state.in_(["ABSENT", "PARTIAL", "INCORRECT", "OUTDATED"]),
                (LearningObjective.lease_owner.is_(None)) | (LearningObjective.lease_expires_at < now),
            ).order_by(LearningObjective.created_at).limit(limit)).scalars().all()
            for oid in cands:
                res = s.execute(update(LearningObjective).where(
                    LearningObjective.id == oid,
                    (LearningObjective.lease_owner.is_(None)) | (LearningObjective.lease_expires_at < now),
                ).values(lease_owner=owner, lease_expires_at=now + timedelta(seconds=lease_s)))
                if res.rowcount == 1:
                    out.append(oid)
        return out

    def release_objectives(self, owner: str, objective_ids: list[str]) -> None:
        with self.db.write() as s:
            s.execute(update(LearningObjective).where(LearningObjective.id.in_(objective_ids),
                                                      LearningObjective.lease_owner == owner)
                      .values(lease_owner=None, lease_expires_at=None))

    def coverage_report(self, production_id: str) -> dict[str, Any]:
        """COV-005: contagens por estado com denominador explícito; percentuais só com denominador > 0."""
        with self.db.session() as s:
            rows = s.execute(select(LearningObjective.necessity, LearningObjective.coverage_state, func.count())
                             .where(LearningObjective.production_id == production_id)
                             .group_by(LearningObjective.necessity, LearningObjective.coverage_state)).all()
        by_state: dict[str, int] = {}
        relevant = complete = 0
        for nec, st, n in rows:
            by_state[st] = by_state.get(st, 0) + n
            if nec in ("REQUIRED", "RECOMMENDED") and st not in ("NOT_APPLICABLE", "COVERED_ELSEWHERE"):
                relevant += n
                complete += n if st == "COMPLETE" else 0
        return {"by_state": by_state, "denominator": relevant, "complete": complete,
                "complete_pct": round(100 * complete / relevant, 1) if relevant else None,
                "denominator_definition": "objetivos obrigatórios e recomendados, excluídos os não aplicáveis "
                                          "e os cobertos em outro deck"}

    # ------------------------------------------------------------ afirmações e evidências
    def add_claim(self, text: str, *, objective_id: str | None = None, entity_id: str | None = None,
                  card_version_id: str | None = None, component: str = "OTHER", population: str = "",
                  scenario: str = "", criticality: str = "NORMAL", negation_kind: str | None = None,
                  numeric: dict[str, Any] | None = None, call_id: str | None = None) -> str:
        _check(component, CLAIM_COMPONENTS, "componente")
        _check(criticality, CRITICALITY, "criticidade")
        _check(negation_kind, NEGATION_KINDS, "tipo de negação")
        if not text.strip():
            raise KnowledgeError("afirmação vazia")
        if component in ("DOSE", "CUTOFF", "INTERVAL", "DURATION") and criticality == "NORMAL":
            criticality = "HIGH"  # números clínicos nunca são de baixa criticidade
        if numeric is not None and not {"value", "unit"} <= set(numeric):
            raise KnowledgeError("afirmação numérica exige valor e unidade")
        with self.db.write() as s:
            c = Claim(text=text.strip(), objective_id=objective_id, entity_id=entity_id,
                      card_version_id=card_version_id, component=component, population=population, scenario=scenario,
                      criticality=criticality, negation_kind=negation_kind, numeric=numeric, origin_call_id=call_id)
            s.add(c)
            s.flush()
            return c.id

    def link_evidence(self, claim_id: str, evidence_span_id: str, supports: str = "SUPPORTS") -> None:
        _check(supports, ("SUPPORTS", "CONTRADICTS", "PARTIAL", "CONTEXT_ONLY"), "relação")
        with self.db.write() as s:
            if s.get(Claim, claim_id) is None or s.get(EvidenceSpan, evidence_span_id) is None:
                raise KnowledgeError("afirmação ou evidência inexistente")
            if s.get(ClaimEvidence, (claim_id, evidence_span_id)) is None:
                s.add(ClaimEvidence(claim_id=claim_id, evidence_span_id=evidence_span_id, supports=supports))

    def add_verdict(self, claim_id: str, verdict: str, rationale: str, evidence_ids: list[str], *,
                    audit_ref: str = "", call_id: str | None = None) -> str:
        """Append-only. CONFIRMED exige evidência documental vinculada (não trecho de busca)."""
        _check(verdict, VERDICTS, "veredito")
        with self.db.write() as s:
            if verdict == "CONFIRMED":
                if not evidence_ids:
                    raise KnowledgeError("CONFIRMADA exige evidência")
                for eid in evidence_ids:
                    ev = s.get(EvidenceSpan, eid)
                    if ev is None:
                        raise KnowledgeError(f"evidência inexistente: {eid}")
                    claim = s.get(Claim, claim_id)
                    if ev.retrieved_via == "SEARCH_SNIPPET" and claim.criticality != "NORMAL":
                        raise KnowledgeError("trecho de busca não confirma afirmação crítica (SCI-023)")
            v = ClaimVerdict(claim_id=claim_id, verdict=verdict, rationale=rationale, evidence_ids=evidence_ids,
                             audit_ref=audit_ref, origin_call_id=call_id)
            s.add(v)
            s.flush()
            return v.id

    def claims_without_evidence(self, objective_ids: list[str]) -> list[str]:
        with self.db.session() as s:
            q = select(Claim.id).where(Claim.objective_id.in_(objective_ids)).where(
                ~select(ClaimEvidence.claim_id).where(ClaimEvidence.claim_id == Claim.id,
                                                      ClaimEvidence.supports.in_(["SUPPORTS", "PARTIAL"]))
                .exists())
            return list(s.execute(q).scalars())

    # ------------------------------------------------------------ consulta
    def overview(self, project_id: str) -> list[dict[str, Any]]:
        with self.db.session() as s:
            out = []
            for e in s.execute(select(ClinicalEntity).where(ClinicalEntity.project_id == project_id)
                               .order_by(ClinicalEntity.name)).scalars():
                states = dict(s.execute(select(MapDimension.state, func.count()).where(
                    MapDimension.entity_id == e.id, MapDimension.map_origin == "CREATOR")
                    .group_by(MapDimension.state)).all())
                objs = s.execute(select(func.count()).select_from(LearningObjective)
                                 .where(LearningObjective.entity_id == e.id)).scalar_one()
                dps = s.execute(select(func.count()).select_from(DecisionPoint)
                                .where(DecisionPoint.entity_id == e.id)).scalar_one()
                out.append({"id": e.id, "name": e.name, "synonyms": e.synonyms, "home_deck_path": e.home_deck_path,
                            "map_states": states, "objectives": objs, "decision_points": dps})
            return out

    def objectives(self, *, project_id: str | None = None, production_id: str | None = None) -> list[dict[str, Any]]:
        with self.db.session() as s:
            q = select(LearningObjective).order_by(LearningObjective.created_at)
            if project_id:
                q = q.where(LearningObjective.project_id == project_id)
            if production_id:
                q = q.where(LearningObjective.production_id == production_id)
            return [{"id": o.id, "entity_id": o.entity_id, "description": o.description, "subtopic": o.subtopic,
                     "knowledge_level": o.knowledge_level, "necessity": o.necessity,
                     "coverage_state": o.coverage_state, "purpose": o.purpose, "planned_cards": o.planned_cards,
                     "planned_rationale": o.planned_rationale, "leased": o.lease_owner is not None}
                    for o in s.execute(q).scalars()]
