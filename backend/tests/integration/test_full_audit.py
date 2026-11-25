"""Modo auditoria integral de deck importado (FULL_AUDIT) com provedor simulado: contradição vira defeito e
proposta humana, nada é excluído, o auditor não vê a autoavaliação do criador (AUD-001, DED-003, APR-002)."""

import hashlib
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cardfactory.api.app import create_app
from cardfactory.audit.deterministic import scan_all
from cardfactory.config import Settings
from cardfactory.pipeline import full_creation
from cardfactory.providers.mock import MockProvider

REF = Path(__file__).resolve().parents[3] / "benchmarks" / "reference"
HDR = "#separator:tab\n#html:true\n#guid column:1\n#notetype column:2\n#deck column:3\n#tags column:6\n"
FRONT = "Qual é a dose de permetrina 5% na escabiose comum do adulto?"
BACK = "Aplicar do pescoço aos pés, remover após 8 a 14 horas e repetir em 7 dias."


def _contradiction_responder(req):
    out = full_creation.mock_responder(req)
    if req.schema_name == "contradiction_v1":
        for p in out["pairs"]:
            p.update(kind="CONTRADICTION", proposal="REVIEW_DELETE", rationale="[SIMULADO] intervalos diferentes")
    return out


@pytest.fixture
def env(tmp_path: Path):
    prov = MockProvider(responder=_contradiction_responder)
    app = create_app(Settings(data_dir=tmp_path), providers={"mock": prov})
    with TestClient(app) as c:
        yield c, prov


def _wait(client, run_id, states, timeout=30.0):
    end = time.time() + timeout
    while time.time() < end:
        r = client.get(f"/api/runs/{run_id}").json()
        if r["state"] in states and not r["active"]:
            return r
        time.sleep(0.05)
    raise AssertionError(f"execução não chegou a {states}: {r['state']}")


def test_full_audit_of_imported_deck(env):
    c, prov = env
    pid = c.post("/api/productions", json={"theme": "x", "target_cards": 1}).json()  # cria o projeto padrão
    project_id = next(p["id"] for p in c.get("/api/projects").json())
    rows = [f"g{i}\tBasic\tIGOR::Dermatologia::Escabiose\t{FRONT}\t{BACK.replace('7', str(7 + i))}\tref"
            for i in range(2)]
    imp = c.post(f"/api/imports/anki?project_id={project_id}&filename=t.txt&author=t",
                 content=(HDR + "\n".join(rows) + "\n").encode()).json()
    assert imp["created"] == 2 and imp["quarantined"] == 0
    before = len(c.get("/api/cards").json())

    r = c.post("/api/productions", json={"theme": "Escabiose", "mode": "FULL_AUDIT",
                                         "import_batch_ids": [imp["import_batch_id"]]}).json()
    assert pid["production_id"] != r["production_id"]
    c.post(f"/api/runs/{r['run_id']}/start")
    detail = _wait(c, r["run_id"], {"PAUSED"})
    tasks = {t["key"]: t for t in detail["task_list"]}
    assert "GENERATION" not in tasks and tasks["HUMAN_REVIEW"]["state"] == "AWAITING_HUMAN"
    assert tasks["INVENTORY"]["output"] == {"cards": 2, "legacy": 2, "card_v2": 0}
    assert tasks["DEDUP"]["output"]["contradictions"] >= 1 and tasks["DEDUP"]["output"]["proposals"] >= 1

    cards = c.get("/api/cards").json()
    assert len(cards) == before  # DED-003: nada é excluído
    defects = c.get(f"/api/defects?production_id={r['production_id']}").json()
    assert {d["category"] for d in defects if d["card_id"]} >= {"CONTRADICTION"}
    report = c.get(f"/api/productions/{r['production_id']}/audit-report").json()
    assert report["disclaimer"] and report["cards"]["total"] == 2
    sci = report["verdicts"]["scientific"]["ORIGINAL"]
    assert "cards_without_verified_claims" in sci["detail"]
    # Cards importados não têm afirmações: o auditor recebe trechos do acervo extraído nesta produção e a
    # afirmação nova só é confirmada com um desses trechos vinculado.
    claims = [x for card in c.get("/api/cards").json() for x in c.get(f"/api/cards/{card['id']}/claims").json()]
    confirmed = [x for x in claims if x["verdict"] == "CONFIRMED"]
    assert confirmed and all(x["evidence_ids"] for x in confirmed)
    sims = c.get(f"/api/similarity?project_id={project_id}").json()
    assert sims and all(s["status"] == "CLASSIFIED" and s["kind"] == "CONTRADICTION" for s in sims)
    for card_id in {d["card_id"] for d in defects if d["card_id"]}:
        assert c.get(f"/api/cards/{card_id}/blockers").json()["blockers"]


def test_auditors_never_see_creator_self_assessment(env):
    c, prov = env
    r = c.post("/api/productions", json={"theme": "Hipertensão", "target_cards": 2}).json()
    c.post(f"/api/runs/{r['run_id']}/start")
    _wait(c, r["run_id"], {"PAUSED"})
    audit_msgs = [q.messages[-1]["content"] for q in prov.calls if q.schema_name in
                  ("sci_audit_v1", "ped_audit_v1", "sec_audit_v1", "cov_audit_v1")]
    assert audit_msgs
    for m in audit_msgs:  # o gerador simulado escreve limitations=["conteúdo simulado"]
        assert "conteúdo simulado" not in m and "validation_status" not in m


def test_reference_cards_import_and_deterministic_scan(env):
    """Os 40 cards de referência entram como deck auditável; não se presume que estejam corretos."""
    c, _ = env
    assert hashlib.sha256((REF / "01_escabiose.txt").read_bytes()).hexdigest().startswith("1a87a601")
    c.post("/api/productions", json={"theme": "x", "target_cards": 1})
    project_id = next(p["id"] for p in c.get("/api/projects").json())
    total = 0
    for f in sorted(REF.glob("*.txt")):
        res = c.post(f"/api/imports/anki?project_id={project_id}&filename={f.name}&author=ref",
                     content=f.read_bytes()).json()
        assert res["notes_read"] == 20 and res["created"] == 20
        total += res["created"]
    assert total == 40
    hits = []
    for card in c.get("/api/cards").json():
        if card["schema_version"] != "2.1":
            content = c.get(f"/api/cards/{card['id']}").json()["content"]
            hits += [h.category for h in scan_all(content, {})]
    assert "AMBIGUITY" in hits  # PCR sem definição no card de Kawasaki incompleto
