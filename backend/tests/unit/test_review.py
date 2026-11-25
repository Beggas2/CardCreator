"""Fase 5: mesa de revisão (APR-004, APR-002, INT-005), desfazer, propostas e aprendizado editorial (PED-017)."""

import copy
from pathlib import Path

import pytest
from sqlalchemy import select

from cardfactory.audit.service import AuditService
from cardfactory.cards.samples import SAMPLES
from cardfactory.cards.service import CardService
from cardfactory.db.models import Card, Defect, Project
from cardfactory.prompts.registry import PromptRegistry
from cardfactory.review.service import ReviewError, ReviewService

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def env(db, tmp_path: Path):
    with db.write() as s:
        p = Project(name="p")
        s.add(p)
        s.flush()
        pid = p.id
    cs = CardService(db, tmp_path / "media")
    return {"db": db, "cs": cs, "rv": ReviewService(db), "aud": AuditService(db), "pid": pid,
            "cid": cs.create(pid, copy.deepcopy(SAMPLES["direct"]))}


def _state(env):
    with env["db"].session() as s:
        return s.get(Card, env["cid"]).state


def test_approval_is_refused_while_blocked_and_undo_restores(env):
    rv, cid = env["rv"], env["cid"]
    env["aud"].add_defect(card_id=cid, production_id=None, category="IMPRECISION", severity="HIGH", description="x")
    with pytest.raises(ReviewError, match="aprovação recusada"):
        rv.decide(cid, "APPROVE", actor="Revisora")
    with pytest.raises(ReviewError):
        rv.decide(cid, "APPROVE", actor=" ")  # aprovação humana exige nome
    d = env["aud"].defects(card_id=cid)[0]
    env["aud"].set_defect(d["id"], "JUSTIFIED", note="ok no contexto", actor="Revisora")
    before = _state(env)
    out = rv.decide(cid, "APPROVE", actor="Revisora", duration_ms=12000, started_version_no=1)
    assert out["state"] == "HUMAN_APPROVED" and not out["edited"]
    rv.undo(cid, actor="Revisora")
    assert _state(env) == before
    with pytest.raises(ReviewError):
        rv.undo(cid, actor="Revisora")  # a aprovação já foi desfeita; a decisão anterior é a única
    hist = rv.detail(cid)["decisions"]
    assert [h["decision"] for h in hist] == ["APPROVE", "UNDO"]


def test_request_changes_creates_human_defect_and_reject_keeps_card(env):
    rv, cid = env["rv"], env["cid"]
    with pytest.raises(ReviewError):
        rv.decide(cid, "REQUEST_CHANGES", actor="R")  # motivo obrigatório
    rv.decide(cid, "REQUEST_CHANGES", actor="R", reasons=["AMBIGUOUS_FRONT"], note="falta população")
    with env["db"].session() as s:
        d = s.execute(select(Defect).where(Defect.card_id == cid)).scalar_one()
        assert d.origin == "HUMAN" and d.category == "AMBIGUITY" and d.status == "OPEN"
    rv.undo(cid, actor="R")
    with env["db"].session() as s:
        assert s.execute(select(Defect.status).where(Defect.card_id == cid)).scalar_one() == "JUSTIFIED"
    rv.decide(cid, "REJECT", actor="R", reasons=["REDUNDANT"])
    assert _state(env) == "REJECTED"
    with env["db"].session() as s:
        assert s.get(Card, cid) is not None  # nunca apagado


def test_proposals_need_human_and_delete_becomes_rejected(env):
    rv, cs, cid = env["rv"], env["cs"], env["cid"]
    other = cs.create(env["pid"], copy.deepcopy(SAMPLES["list"]))
    cs.propose(cid, "REVIEW_DELETE", actor="call_x", actor_type="AI", justification="duplicado", related=[other])
    cs.propose(other, "MOVE", actor="call_x", actor_type="AI", justification="deck errado")
    p = rv.detail(cid)["proposals"][0]
    assert p["kind"] == "REVIEW_DELETE" and p["decision"] is None and _state(env) != "REJECTED"
    rv.decide_proposal(p["id"], True, actor="R", note="confirmado")
    assert _state(env) == "REJECTED"
    with pytest.raises(ReviewError):
        rv.decide_proposal(p["id"], False, actor="R")  # já decidida
    rv.undo(cid, actor="R")
    assert _state(env) != "REJECTED"
    move = rv.detail(other)["proposals"][0]
    out = rv.decide_proposal(move["id"], True, actor="R")
    assert "nada é aplicado automaticamente" in out["note"]
    q = {r["id"]: r for r in rv.queue(project_id=env["pid"])}
    assert q[cid]["pending_proposals"] == 1 and q[other]["pending_proposals"] == 0


def test_insights_and_lesson_promotion_create_prompt_version(env, db):
    rv, cs = env["rv"], env["cs"]
    for name in ("list", "criteria"):
        c = cs.create(env["pid"], copy.deepcopy(SAMPLES[name]))
        rv.decide(c, "REQUEST_CHANGES", actor="R", reasons=["TOO_DENSE"], duration_ms=20000)
    rv.decide(env["cid"], "APPROVE", actor="R", duration_ms=8000)
    ins = rv.insights(project_id=env["pid"])
    assert ins["judged"] == 3 and ins["approval_rate"] == pytest.approx(0.333, abs=0.001)
    assert ins["reasons"][0] == {"code": "TOO_DENSE", "label": "Denso demais / carga cognitiva", "count": 2}
    reg = PromptRegistry(db, ROOT / "prompts", ROOT / "docs" / "normative")
    reg.import_library()
    lid = rv.add_lesson("Listas de critérios: destacar só o número que discrimina.", actor="R",
                        reason_codes=["TOO_DENSE"])
    with pytest.raises(ReviewError):
        rv.promote_lessons(reg, actor="R")  # só lições aceitas entram
    rv.set_lesson(lid, "ACCEPTED", actor="R")
    out = rv.promote_lessons(reg, actor="R")
    assert "destacar só o número" in reg.active_text("policy:editorial")
    assert reg.versions("policy:editorial")[0]["id"] == out["prompt_version_id"]
    assert rv.lessons()[0]["status"] == "PROMOTED"
    assert reg.coverage_report() == {r: [] for r in reg.manifest.roles}
