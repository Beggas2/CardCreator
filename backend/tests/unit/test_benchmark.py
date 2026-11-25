"""Fase 5: conjuntos de benchmark, split eval selado, métricas com intervalo exato e comparação cega
(BENCHMARK_PROTOCOL §1–4)."""

import asyncio
import copy
from pathlib import Path

import pytest
from sqlalchemy import select

from cardfactory.benchmark.service import BenchmarkError, BenchmarkService, clopper_pearson
from cardfactory.cards.samples import SAMPLES
from cardfactory.cards.service import CardService
from cardfactory.db.models import CardVersion, Project


@pytest.fixture
def bench(db):
    b = BenchmarkService(db)
    b.load_sets()
    return b


def test_sets_load_idempotently_with_fixed_splits(bench):
    assert bench.load_sets() == {"KNOWN_DEFECTS": {"created": 0}, "REFERENCE": {"created": 0}}
    sets = bench.summary()["sets"]
    assert sets["REFERENCE"] == {"dev": 20, "eval": 20}
    assert sum(sets["KNOWN_DEFECTS"].values()) == 23  # 11 defeitos plantados + 12 cards limpos


def test_eval_split_is_sealed_and_logged(bench):
    with pytest.raises(BenchmarkError):
        bench.items("KNOWN_DEFECTS", "eval")
    with pytest.raises(BenchmarkError):
        asyncio.run(bench.run("KNOWN_DEFECTS", "eval", "DETERMINISTIC", actor="t"))
    bench.items("KNOWN_DEFECTS", "dev")  # dev não é registrado
    asyncio.run(bench.run("KNOWN_DEFECTS", "eval", "DETERMINISTIC", actor="t", purpose="confirmação final"))
    s = bench.summary()
    assert s["eval_accesses"] == {"KNOWN_DEFECTS": 1} and s["eval_log"][0]["purpose"] == "confirmação final"


def test_deterministic_run_metrics(bench):
    r = asyncio.run(bench.run("KNOWN_DEFECTS", "dev", "DETERMINISTIC", actor="t"))
    m = r["metrics"]
    assert m["false_alarm"]["k"] == 0 and m["false_alarm"]["n"] == 6
    assert m["detection"]["n"] == 6 and m["detection"]["k"] >= 3
    lo, hi = m["detection"]["ci95"]
    assert 0 < lo < m["detection"]["rate"] < hi < 1
    assert bench.runs()[0]["metrics"] == m
    ref = asyncio.run(bench.run("REFERENCE", "dev", "DETERMINISTIC", actor="t"))
    assert "sem gabarito" in ref["metrics"]["note"]


def test_ai_subject_requires_explicit_model(bench):
    with pytest.raises(BenchmarkError):
        asyncio.run(bench.run("KNOWN_DEFECTS", "dev", "auditor_scientific", actor="t"))


def test_clopper_pearson_known_values():
    assert clopper_pearson(0, 10) == (0.0, pytest.approx(0.3085, abs=1e-4))
    lo, hi = clopper_pearson(5, 10)
    assert lo == pytest.approx(0.1871, abs=1e-4) and hi == pytest.approx(0.8129, abs=1e-4)
    assert clopper_pearson(0, 0) is None


def test_blind_comparison_reveals_origin_only_after_decision(bench, db, tmp_path: Path):
    with db.write() as s:
        p = Project(name="p")
        s.add(p)
        s.flush()
        pid = p.id
    cs = CardService(db, tmp_path / "media")
    a = cs.create(pid, copy.deepcopy(SAMPLES["direct"]))
    b = cs.create(pid, copy.deepcopy(SAMPLES["case"]))
    with db.session() as s:
        vid_a = s.execute(select(CardVersion.id).where(CardVersion.card_id == a)).scalar_one()
        vid_b = s.execute(select(CardVersion.id).where(CardVersion.card_id == b)).scalar_one()
    cid = bench.create_comparison("Qual card ensina melhor?", [vid_a, vid_b], ["modelo-1", "modelo-2"])
    shown = bench.comparison(cid)
    assert not shown["decided"] and all("origin" not in it and "card_version_id" not in it for it in shown["items"])
    labels = [it["label"] for it in shown["items"]]
    with pytest.raises(BenchmarkError):
        bench.decide_comparison(cid, labels[0], actor="R", justification="")
    out = bench.decide_comparison(cid, labels[0], actor="R", justification="frente mais delimitada",
                                  ranking=labels)
    assert out["decided"] and {it["origin"] for it in out["items"]} == {"modelo-1", "modelo-2"}
    with pytest.raises(BenchmarkError):
        bench.decide_comparison(cid, labels[1], actor="R", justification="mudei")
