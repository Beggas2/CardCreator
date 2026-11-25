import threading

import pytest

from cardfactory.db.models import Production, Project
from cardfactory.knowledge.dimensions import DIMENSIONS
from cardfactory.knowledge.service import Knowledge, KnowledgeError
from cardfactory.library.service import Library


@pytest.fixture
def ctx(db):
    with db.write() as s:
        p = Project(name="p")
        s.add(p)
        s.flush()
        prd = Production(project_id=p.id, mode="FULL_CREATION", theme="HAS")
        s.add(prd)
        s.flush()
        return p.id, prd.id


def _full_map(state="APPLICABLE_PENDING", just=""):
    return {c: (state, just) for c in DIMENSIONS}


def test_map_requires_all_57_and_justification(db, ctx):
    k = Knowledge(db)
    e = k.upsert_entity(ctx[0], "Hipertensão  arterial", synonyms=["HAS"])
    assert k.upsert_entity(ctx[0], "Hipertensão arterial", synonyms=["HA"]) == e
    with pytest.raises(KnowledgeError):
        k.set_map(e, {1: ("APPLICABLE_PENDING", "")})
    m = _full_map()
    m[7] = ("NOT_APPLICABLE", "")
    with pytest.raises(KnowledgeError):
        k.set_map(e, m)  # N/A sem justificativa
    m[7] = ("NOT_APPLICABLE", "anatomia não decide conduta neste tema")
    k.set_map(e, m)
    assert len(k.get_map(e)) == 57 and k.get_map(e)[7]["state"] == "NOT_APPLICABLE"


def test_compare_independent_map(db, ctx):
    k = Knowledge(db)
    e = k.upsert_entity(ctx[0], "Asma")
    k.set_map(e, _full_map())
    ind = _full_map()
    ind[21] = ("NOT_APPLICABLE", "sem padrão-ouro único")
    k.set_map(e, ind, origin="INDEPENDENT")
    diff = k.compare_maps(e)
    assert [d["code"] for d in diff] == [21] and diff[0]["name"] == "Padrão-ouro"


def test_objective_validation_and_coverage_report(db, ctx):
    k = Knowledge(db)
    with pytest.raises(KnowledgeError):
        k.add_objective(ctx[0], "Dose de X", production_id=ctx[1])  # sem propósito
    a = k.add_objective(ctx[0], "Reconhecer crise hipertensiva", production_id=ctx[1], purpose="decisão")
    k.add_objective(ctx[0], "Dose de anlodipino", production_id=ctx[1], purpose="segurança", depends_on=[a])
    k.add_objective(ctx[0], "Curiosidade histórica", production_id=ctx[1], necessity="OPTIONAL")
    k.add_objective(ctx[0], "Tema de outro deck", production_id=ctx[1], purpose="x", coverage_state="COVERED_ELSEWHERE")
    k.set_coverage(a, "COMPLETE")
    r = k.coverage_report(ctx[1])
    assert r["denominator"] == 2 and r["complete"] == 1 and r["complete_pct"] == 50.0
    empty = k.coverage_report("nenhuma")
    assert empty["denominator"] == 0 and empty["complete_pct"] is None


def test_objective_leases_are_exclusive_under_concurrency(db, ctx):
    k = Knowledge(db)
    ids = {k.add_objective(ctx[0], f"obj {i}", production_id=ctx[1], purpose="p") for i in range(30)}
    got: dict[str, list[str]] = {}

    def worker(name):
        got[name] = Knowledge(db).lease_objectives(ctx[1], name, limit=7)

    threads = [threading.Thread(target=worker, args=(f"w{i}",)) for i in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    leased = [o for v in got.values() for o in v]
    assert len(leased) == len(set(leased)) == 30 and set(leased) == ids
    k.release_objectives("w0", got["w0"])
    assert sorted(k.lease_objectives(ctx[1], "w9", limit=50)) == sorted(got["w0"])


def test_claims_evidence_and_verdicts(db, ctx, tmp_path):
    k, lib = Knowledge(db), Library(db, tmp_path)
    sid = lib.add_source(title_claimed="PCDT", source_tier="BR_OFFICIAL")
    doc = lib.register_found(lib.add_version(sid, validity_status="CURRENT"), None)
    lib.ingest(doc, "# Doses\nAnlodipino 5 mg uma vez ao dia, máximo 10 mg.".encode())
    sec = lib.sections(doc)[0]["id"]
    ev = lib.add_evidence(sec, "Anlodipino 5 mg uma vez ao dia")
    snippet = lib.add_evidence(sec, "máximo 10 mg", retrieved_via="SEARCH_SNIPPET")
    obj = k.add_objective(ctx[0], "Dose", production_id=ctx[1], purpose="segurança")
    c = k.add_claim("Dose inicial de anlodipino: 5 mg/dia", objective_id=obj, component="DOSE",
                    numeric={"value": 5, "unit": "mg/dia"})
    c2 = k.add_claim("Dose máxima 10 mg", objective_id=obj, component="DOSE", numeric={"value": 10, "unit": "mg"})
    assert set(k.claims_without_evidence([obj])) == {c, c2}
    k.link_evidence(c, ev)
    assert k.claims_without_evidence([obj]) == [c2]
    with pytest.raises(KnowledgeError):
        k.add_verdict(c, "CONFIRMED", "ok", [])
    with pytest.raises(KnowledgeError):
        k.add_verdict(c2, "CONFIRMED", "busca", [snippet])  # DOSE é crítica: trecho de busca não confirma
    assert k.add_verdict(c, "CONFIRMED", "trecho literal da seção de doses", [ev])
    with pytest.raises(KnowledgeError):
        k.add_claim("x", numeric={"value": 1})
    with pytest.raises(KnowledgeError):
        k.add_claim("x", component="POSOLOGIA")
