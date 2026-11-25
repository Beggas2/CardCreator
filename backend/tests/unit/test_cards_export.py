"""Versionamento, rollback, ciclo de vida de achados, mídia e exportação versionada (INT-012, TEC-012, TEC-018,
INT-005, INT-011, INT-013, VIS-016)."""

import copy
import json
from pathlib import Path

import pytest
from sqlalchemy import select

from cardfactory.cards.model import block, seg
from cardfactory.cards.samples import SAMPLES
from cardfactory.cards.service import CardService, CardServiceError
from cardfactory.db.models import Card, CardVersion, Operation, Project, RenderedArtifact, ValidationFinding
from cardfactory.export import anki_check
from cardfactory.export.service import Exporter
from cardfactory.importers.anki import AnkiImporter

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


@pytest.fixture
def env(db, tmp_path: Path):
    with db.write() as s:
        p = Project(name="p")
        s.add(p)
        s.flush()
        pid = p.id
    cs = CardService(db, tmp_path / "media")
    ex = Exporter(db, tmp_path / "exports", tmp_path / "media")
    return {"db": db, "cs": cs, "ex": ex, "pid": pid, "tmp": tmp_path}


def approve(env, cid):
    env["cs"].set_state(cid, "HUMAN_APPROVED", actor="Revisora", actor_type="HUMAN", reason="teste")


def test_card_version_rollback(env):
    cs = env["cs"]
    cid = cs.create(env["pid"], SAMPLES["direct"])
    edited = copy.deepcopy(SAMPLES["direct"])
    edited["minimal_answer"] = "Condição X (editada)"
    assert cs.new_version(cid, edited, actor="Ana", note="ajuste")["version_no"] == 2
    assert cs.new_version(cid, edited, actor="Ana")["changed"] is False  # sem mudança, sem versão nova
    r = cs.rollback(cid, 1, actor="Ana", reason="voltar")
    assert r == {"version_no": 3, "restored_from_version": 1}
    got = cs.get(cid)
    assert [v["version_no"] for v in got["versions"]] == [1, 2, 3]
    assert got["versions"][0]["content_hash"] == got["versions"][2]["content_hash"]
    assert [o["kind"] for o in got["operations"]] == ["CREATE", "UPDATE_CONTENT", "ROLLBACK"]
    assert cs.diff(cid, 1, 3)["same_content"] and "editada" in cs.diff(cid, 1, 2)["unified"]
    with env["db"].session() as s:  # HTML derivado registrado para cada versão
        assert s.query(RenderedArtifact).count() == 3
    with pytest.raises(CardServiceError):
        cs.rollback(cid, 3, actor="Ana", reason="x")
    with pytest.raises(CardServiceError):
        cs.new_version(cid, edited, actor=" ")


def test_warning_lifecycle(env):
    cs = env["cs"]
    c = copy.deepcopy(SAMPLES["direct"])
    c["front"]["segments"] = [{"text": "Condição X", "emphasis": "none", "italic": False}]
    cid = cs.create(env["pid"], c)
    f = next(x for x in cs.get(cid)["findings"] if x["code"] == "FRONT_NOT_QUESTION")
    with pytest.raises(CardServiceError):
        cs.justify(f["id"], " ", actor="Ana")
    cs.justify(f["id"], "frente-título intencional para teste", actor="Ana")
    c2 = copy.deepcopy(c)
    c2["minimal_answer"] = "outra"
    cs.new_version(cid, c2, actor="Ana")
    f2 = next(x for x in cs.get(cid)["findings"] if x["code"] == "FRONT_NOT_QUESTION")
    assert f2["status"] == "JUSTIFIED"  # justificativa acompanha o mesmo alerta
    c3 = copy.deepcopy(c2)
    c3["answer"][0]["items"][0]["segments"][0]["claim_ids"] = []
    cs.new_version(cid, c3, actor="Ana")
    fixed = next(x for x in cs.get(cid)["findings"] if x["code"] == "TARGET_WITHOUT_CLAIM")
    assert fixed["status"] == "OPEN"
    cs.new_version(cid, SAMPLES["direct"], actor="Ana")
    with env["db"].session() as s:
        assert s.get(ValidationFinding, fixed["id"]).status == "FIXED"  # sumiu na versão seguinte
    assert "FRONT_NOT_QUESTION" not in {x["code"] for x in cs.get(cid)["findings"]}
    with env["db"].session() as s:
        old = s.execute(select(ValidationFinding).where(ValidationFinding.code == "FRONT_NOT_QUESTION")).scalars()
        assert {x.status for x in old} == {"JUSTIFIED"}  # histórico preservado


def test_blocking_error_cannot_be_justified(env):
    cs = env["cs"]
    cid = cs.create(env["pid"], dict(SAMPLES["direct"], deck_path=["Outro"]))
    err = next(x for x in cs.get(cid)["findings"] if x["level"] == "ERROR")
    with pytest.raises(CardServiceError):
        cs.justify(err["id"], "quero exportar", actor="Ana")


def test_media_requires_rights_and_real_image(env):
    cs = env["cs"]
    c = copy.deepcopy(SAMPLES["image"])
    c["media_requests"] = [{"finding": "sinal Y", "desired_source": "acervo próprio", "purpose": "reconhecer Y"}]
    cid = cs.create(env["pid"], c)
    asset = cs.get(cid)["media"][0]
    assert asset["status"] == "PENDING"
    with pytest.raises(CardServiceError):
        cs.attach_media(asset["id"], PNG, alt="Y", side="front", license="CC-BY", rights_verified=False, actor="A")
    with pytest.raises(CardServiceError):
        cs.attach_media(asset["id"], b"GIF?nope", alt="Y", side="front", license="CC-BY", rights_verified=True,
                        actor="A")
    res = cs.attach_media(asset["id"], PNG, alt="Y", side="front", license="CC-BY", rights_verified=True, actor="A")
    got = cs.get(cid)
    assert got["media"][0]["status"] == "OBTAINED" and res["file"] in got["rendered"]["dark"]["front"]
    assert "IMAGE_PENDING" not in {f["code"] for f in got["findings"]}


def test_export_gates_and_preview(env):
    cs, ex = env["cs"], env["ex"]
    ok = cs.create(env["pid"], SAMPLES["list"])
    bad = cs.create(env["pid"], dict(SAMPLES["direct"], deck_path=["Outro"]))
    q = cs.create(env["pid"], SAMPLES["negative"])
    cs.set_state(q, "QUARANTINE", actor="A", actor_type="HUMAN", reason="não verificável")
    r = ex.export(env["pid"])
    assert r["state"] == "BLOCKED" and r["counts"]["exported"] == 0  # nada aprovado
    assert not [f for f in r["files"] if f["kind"] == "DECK"]  # sem arquivos vazios (TEC-018)
    approve(env, ok)
    approve(env, bad)
    r = ex.export(env["pid"])
    reasons = {s["card_id"]: s["reason"] for s in r["skipped"]}
    assert r["state"] == "READY" and r["counts"]["exported"] == 1
    assert "erros de validação" in reasons[bad] and "QUARANTINE" in reasons[q]
    pv = ex.export(env["pid"], preview=True)
    assert pv["version_label"].endswith("-previa") and pv["preview_not_reviewed"]
    assert all(f["name"].startswith("PREVIA_NAO_REVISADA_") for f in pv["files"])


def test_export_versioned_diff_and_manifest(env):
    cs, ex = env["cs"], env["ex"]
    a = cs.create(env["pid"], SAMPLES["list"])
    b = cs.create(env["pid"], SAMPLES["criteria"])
    approve(env, a)
    approve(env, b)
    r1 = ex.export(env["pid"])
    assert r1["version_label"] == "v1" and sorted(r1["diff_vs_previous"]["added"]) == sorted(
        [cs.get(a)["card_key"], cs.get(b)["card_key"]])
    edited = copy.deepcopy(SAMPLES["list"])
    edited["minimal_answer"] = "A, B, C"
    cs.new_version(a, edited, actor="Ana")
    r2 = ex.export(env["pid"])
    assert r2["version_label"] == "v2" and r2["previous_export_id"] == r1["export_id"]
    assert r2["diff_vs_previous"]["changed"] == [cs.get(a)["card_key"]]
    assert r2["diff_vs_previous"]["unchanged"] == [cs.get(b)["card_key"]]
    d = Path(r2["dir"])
    manifest = json.loads(next(d.glob("manifesto_*.json")).read_text(encoding="utf-8"))
    assert manifest["round_trip_ok"] and manifest["counts"]["new_notes"] == 2
    deck = (d / next(f["name"] for f in manifest["files"] if f["kind"] == "DECK")).read_text(encoding="utf-8")
    lines = [ln for ln in deck.split("\n") if ln and not ln.startswith("#")]
    assert len(lines) == 2 and all(len(ln.split("\t")) == 6 for ln in lines)
    assert all(ln.startswith("\tBasic\tIGOR::Exemplos::") for ln in lines)  # nota nova: GUID vazio (INT-002)
    assert f"cf::{cs.get(a)['card_key']}" in deck
    assert ex.file_path(r2["export_id"], manifest["files"][0]["name"]).is_file()


def test_no_destructive_output_and_no_scheduler_fields(env):
    """INT-005 / INT-013: o exportador não tem operação de exclusão nem campos de agendamento."""
    import cardfactory.export.service as svc
    import cardfactory.export.tsv as tsv
    src = Path(svc.__file__).read_text(encoding="utf-8") + Path(tsv.__file__).read_text(encoding="utf-8")
    import re
    assert not re.search(r"\b(revlog|due|ivl|factor|reps|lapses)\b|unlink\(|rmtree|DELETE FROM|\.delete\(", src)
    assert tsv.COLUMNS["anki_tsv_v2"] == 6


def test_existing_guid_preserved_on_export(env):
    """C§31.3: nota existente mantém exatamente o GUID original, mesmo após conversão e edição."""
    db, cs = env["db"], env["cs"]
    AnkiImporter(db).import_export(env["pid"], b"#separator:tab\n#html:true\n#guid column:1\n#notetype column:2\n"
                                   b"#deck column:3\nO,x%9\tBasic\tIGOR::A\tFrente?\tVerso\n")
    with db.session() as s:
        card = s.execute(select(Card)).scalar_one()
    assert card.anki_guid == "O,x%9"
    with pytest.raises(CardServiceError):
        cs.new_version(card.id, SAMPLES["direct"], actor="Ana")
    # conversão explícita para card.v2 cria nova versão no mesmo card, mantendo o GUID
    with db.write() as s:
        last = s.execute(select(CardVersion).where(CardVersion.card_id == card.id)).scalar_one()
        last.schema_version = "2.1"  # simula conversão (Fase 4 terá o conversor assistido)
        last.content = {**SAMPLES["direct"], "schema_version": "2.1", "card_key": card.card_key,
                        "anki_guid": card.anki_guid, "images": [], "validation_status": "pending"}
    cs.new_version(card.id, SAMPLES["list"], actor="Ana")
    approve(env, card.id)
    r = env["ex"].export(env["pid"])
    assert r["state"] == "READY" and r["counts"]["updates"] == 1
    deck = Path(r["dir"]) / next(f["name"] for f in r["files"] if f["kind"] == "DECK")
    assert deck.read_text(encoding="utf-8").split("\n")[6].startswith("O,x%9\tBasic\t")
    with db.session() as s:
        assert s.query(Operation).filter(Operation.kind == "UPDATE_CONTENT").count() == 1


def test_missing_media_blocks_export(env):
    cs, ex = env["cs"], env["ex"]
    c = copy.deepcopy(SAMPLES["image"])
    c["media_requests"] = [{"finding": "Y", "desired_source": "x", "purpose": "y"}]
    cid = cs.create(env["pid"], c)
    res = cs.attach_media(cs.get(cid)["media"][0]["id"], PNG, alt="Y", side="back", license="CC0",
                          rights_verified=True, actor="A")
    approve(env, cid)
    (env["tmp"] / "media" / res["file"]).unlink()
    r = ex.export(env["pid"])
    assert r["state"] == "BLOCKED" and any("mídia inexistente" in e for e in r["errors"])


@pytest.mark.skipif(not anki_check.available(), reason="pacote 'anki' não instalado (teste opcional TEC-008)")
def test_it_anki_import_disposable(env):
    """TEC-008 / AMB-08: importação real numa coleção descartável; GUID vazio vira nota nova."""
    cs, ex = env["cs"], env["ex"]
    for k in ("direct", "criteria", "comparison", "score"):
        approve(env, cs.create(env["pid"], SAMPLES[k]))
    cid = cs.create(env["pid"], dict(SAMPLES["list"], answer=[block("essential", "paragraph", [[
        seg('Aspas "duplas", ; e < > &', "value", True, ["clm_x"])]])]))
    approve(env, cid)
    r = ex.export(env["pid"], test_import=True)
    assert r["import_tested"] == "PASSED", r
