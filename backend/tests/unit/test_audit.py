"""Fase 4: varreduras determinísticas, portão de liberação não compensatório, limite de correções,
quarentena preservada e deduplicação sem exclusão (AUD-003, AUD-009, APR-002, APR-003, DED-003, SCI-016, PED-002)."""

import asyncio
import copy
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from cardfactory.audit import dedup
from cardfactory.audit.deterministic import scan_all
from cardfactory.audit.service import AuditError, AuditService
from cardfactory.cards.model import seg
from cardfactory.cards.samples import SAMPLES
from cardfactory.cards.service import CardService
from cardfactory.db.models import Card, Defect, Production, Project, Run, SimilarityPair
from cardfactory.export.service import Exporter
from cardfactory.pipeline import audit as au


@pytest.fixture
def env(db, tmp_path: Path):
    with db.write() as s:
        p = Project(name="p")
        s.add(p)
        s.flush()
        prd = Production(project_id=p.id, mode="FULL_AUDIT", theme="t")
        s.add(prd)
        s.flush()
        run = Run(production_id=prd.id, mode="FULL_AUDIT")
        s.add(run)
        s.flush()
        ids = {"pid": p.id, "prd": prd.id, "run": run.id}
    return {"db": db, "cs": CardService(db, tmp_path / "media"), "aud": AuditService(db),
            "ex": Exporter(db, tmp_path / "exports", tmp_path / "media"), **ids}


def _card(env, name="direct", **changes):
    c = copy.deepcopy(SAMPLES[name])
    c.update(changes)
    cid = env["cs"].create(env["pid"], c)
    with env["db"].write() as s:
        s.get(Card, cid).production_id = env["prd"]
    return cid


def test_samples_pass_deterministic_scans():
    for name, card in SAMPLES.items():
        assert scan_all(card, {}) == [], name


def test_deictic_front_and_dose_arithmetic_are_flagged():
    c = copy.deepcopy(SAMPLES["direct"])
    c["front"]["segments"] = [seg("Nesse caso, qual é o achado que define a condição?")]
    assert any(h.category == "PEDAGOGICAL" for h in scan_all(c, {}))
    c = copy.deepcopy(SAMPLES["direct"])
    c["answer"][0]["items"][0]["segments"] = [seg("Fármaco Z 10 mg/kg: criança de 20 kg recebe 400 mg.",
                                                  semantic="value", target=True)]
    hits = scan_all(c, {})
    assert any(h.category == "NUMERIC_ERROR" and h.severity == "CRITICAL" for h in hits), hits


def test_release_gate_is_non_compensatory(env):
    cid = _card(env)
    env["cs"].set_state(cid, "HUMAN_APPROVED", actor="Revisora", actor_type="HUMAN", reason="ok")
    env["aud"].add_defect(card_id=cid, production_id=env["prd"], category="IMPRECISION", severity="HIGH",
                          description="valor sem população")
    r = env["ex"].export(env["pid"], actor="t")
    assert r["counts"]["exported"] == 0 and r["counts"]["blocked"] == 1  # aprovação humana não compensa
    d = env["aud"].defects(card_id=cid)[0]
    with pytest.raises(AuditError):
        env["aud"].set_defect(d["id"], "JUSTIFIED", note="", actor="Revisora")  # nota obrigatória
    env["aud"].set_defect(d["id"], "JUSTIFIED", note="população explícita no complemento", actor="Revisora")
    assert env["ex"].export(env["pid"], actor="t")["counts"]["exported"] == 1


def test_critical_defect_cannot_be_justified_and_preview_lists_it(env):
    cid = _card(env)
    env["aud"].add_defect(card_id=cid, production_id=env["prd"], category="NUMERIC_ERROR", severity="CRITICAL",
                          description="dose errada")
    d = env["aud"].defects(card_id=cid)[0]
    with pytest.raises(AuditError):
        env["aud"].set_defect(d["id"], "JUSTIFIED", note="aceito", actor="Revisora")
    r = env["ex"].export(env["pid"], preview=True, actor="t")
    assert r["counts"]["exported"] == 1
    assert any(p["kind"] == "BLOQUEIO" and "crítico" in p["detail"] for p in r["pending"])


def test_import_quarantine_is_never_lifted_by_audit(env):
    cid = _card(env)
    with env["db"].write() as s:
        c = s.get(Card, cid)
        c.state, c.quarantine = "QUARANTINE", True
    assert env["aud"].decide_state(cid, actor="t") == "QUARANTINE"
    with env["db"].session() as s:
        assert s.get(Card, cid).quarantine


class _Ctx:
    def __init__(self, run_id):
        self.run_id, self.checkpoint, self.stage, self.task_id = run_id, {}, "CORRECTION", "t"
        self.input = {"budget_ids": []}

    def save_checkpoint(self, cp):
        self.checkpoint = cp


def test_correction_limit_escalates_without_calling_ai(env):
    cid = _card(env)
    env["aud"].add_defect(card_id=cid, production_id=env["prd"], category="IMPRECISION", severity="MEDIUM",
                          description="x")
    with env["db"].write() as s:
        s.execute(select(Defect)).scalar_one().correction_attempts = au.MAX_CORRECTIONS
    svc = SimpleNamespace(db=env["db"])  # sem gateway: qualquer chamada de IA falharia
    out = asyncio.run(au.correction(svc, _Ctx(env["run"]), env["cs"]))
    assert out["escalated"] == 1 and out.get("corrected", 0) == 0
    assert env["aud"].defects(card_id=cid)[0]["status"] == "ESCALATED"
    assert out["original_verdicts"]["scientific"] == "NOT_VERIFIED"  # sem auditoria científica registrada


def test_dedup_finds_candidates_and_never_deletes(env):
    a = _card(env)
    b = _card(env)  # conteúdo idêntico
    other = _card(env, "pharmacology")
    cands = dedup.candidates(env["db"], env["pid"], focus_card_ids=[a, b, other])
    pairs = {(c["a"], c["b"]) for c in cands} | {(c["b"], c["a"]) for c in cands}
    assert (a, b) in pairs
    ids = dedup.store(env["db"], env["pid"], cands)
    assert dedup.store(env["db"], env["pid"], cands) == ids  # idempotente
    with env["db"].session() as s:
        assert s.query(Card).count() == 3
        assert s.query(SimilarityPair).count() == len(ids)


def test_number_without_claim_unit_is_not_critical():
    from cardfactory.cards.model import seg as _seg

    c = copy.deepcopy(SAMPLES["pharmacology"])
    claims = {"cl1": {"numeric": {"value": 0.2, "unit": "mg/kg", "operator": "="}}}
    item = c["answer"][0]["items"][0]
    item["segments"] = [_seg("Dias 1, 2 e 8", semantic="value", target=True)]
    item["segments"][0]["claim_ids"] = ["cl1"]
    hits = scan_all(c, claims)
    assert not any(h.severity == "CRITICAL" for h in hits)
    assert any(h.category == "TRACEABILITY" for h in hits)
    item["segments"] = [_seg("0,5 mg/kg", semantic="value", target=True)]
    item["segments"][0]["claim_ids"] = ["cl1"]
    assert any(h.category == "NUMERIC_ERROR" and h.severity == "CRITICAL" for h in scan_all(c, claims))
