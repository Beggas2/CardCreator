"""API local + pipeline ponta a ponta com provedor simulado (sem rede, sem custo)."""


import json
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cardfactory.api.app import create_app
from cardfactory.config import Settings
from cardfactory.pipeline import full_creation
from cardfactory.providers.mock import MockProvider

FAKE_KEY = "sk-or-v1-NAOREALNAOREALNAOREAL0123456789"


@pytest.fixture
def client(tmp_path: Path):
    app = create_app(Settings(data_dir=tmp_path), providers={"mock": MockProvider(
        responder=full_creation.mock_responder)})
    with TestClient(app) as c:
        yield c


def _wait(client, run_id, states, timeout=20.0):
    import time
    end = time.time() + timeout
    while time.time() < end:
        r = client.get(f"/api/runs/{run_id}").json()
        if r["state"] in states and not r["active"]:
            return r
        time.sleep(0.05)
    raise AssertionError(f"execução não chegou a {states}: {r['state']} {r['tasks']}")


def test_health_and_dashboard(client):
    h = client.get("/api/health").json()
    assert h["ok"] and h["providers"] == ["mock"]
    d = client.get("/api/dashboard").json()
    assert d["projects"] == 0 and d["pending_reconciliation"] == 0


def test_rejects_foreign_host_and_origin(client):
    assert client.get("/api/health", headers={"host": "evil.example"}).status_code == 403
    assert client.post("/api/fx", json={"rate": "5"}, headers={"origin": "http://evil.example"}).status_code == 403
    assert client.get("/api/health", headers={"origin": "http://localhost:5173"}).status_code == 200


def test_full_creation_pipeline_with_mock(client, tmp_path):
    r = client.post("/api/productions", json={"theme": "Hipertensão arterial", "target_cards": 3}).json()
    run = r["run_id"]
    assert client.post(f"/api/runs/{run}/start").status_code == 200
    detail = _wait(client, run, {"PAUSED"})
    states = {t["key"]: t["state"] for t in detail["task_list"]}
    assert states["HUMAN_REVIEW"] == "AWAITING_HUMAN" and states["EXPORT"] == "PENDING"
    assert all(states[s] == "SUCCEEDED" for s, _ in full_creation.STAGES[:14])

    cards = client.get("/api/cards").json()
    assert len(cards) == 3 and all(c["origin"] == "MOCK" for c in cards)
    calls = client.get("/api/calls").json()
    ai_stages = [s for s, role in full_creation.STAGES if role]
    assert sorted(c["stage"] for c in calls) == sorted(ai_stages)
    assert all(c["prompt_hash"] and c["state"] == "SUCCEEDED" for c in calls)

    # Revisão humana registrada → exportação do manifesto preliminar.
    hr = next(t for t in detail["task_list"] if t["key"] == "HUMAN_REVIEW")
    assert client.post(f"/api/tasks/{hr['id']}/skip", json={"reason": "revisado no teste"}).status_code == 200
    client.post(f"/api/runs/{run}/resume")
    done = _wait(client, run, {"COMPLETED"})
    export = next(t for t in done["task_list"] if t["key"] == "EXPORT")
    manifest = json.loads(Path(export["output"]["manifest"]).read_text(encoding="utf-8"))
    assert len(manifest["cards"]) == 3 and "Fase 3" in manifest["aviso"]


def test_paid_production_requires_explicit_models_and_budget(tmp_path):
    app = create_app(Settings(data_dir=tmp_path), providers={"mock": MockProvider(),
                                                             "openrouter": MockProvider(name="openrouter", paid=True)})
    with TestClient(app) as c:
        r = c.post("/api/productions", json={"theme": "x", "provider": "openrouter"})
        assert r.status_code == 400 and "modelo" in r.json()["detail"]
        r = c.post("/api/productions", json={"theme": "x", "provider": "openrouter", "models": {"default": "a/b"}})
        assert r.status_code == 400 and "orçamento" in r.json()["detail"]


def test_paid_run_without_authorization_pauses_without_calling(tmp_path):
    paid = MockProvider(name="openrouter", paid=True, responder=full_creation.mock_responder)
    app = create_app(Settings(data_dir=tmp_path), providers={"openrouter": paid})
    with TestClient(app) as c:
        c.post("/api/fx", json={"rate": "5.00"})
        bid = c.post("/api/budgets", json={"scope": "PROJECT", "scope_ref": "p", "limit_brl": "100"}).json()["id"]
        c.post("/api/models/sync/openrouter")
        run = c.post("/api/productions", json={"theme": "x", "provider": "openrouter", "budget_id": bid,
                                               "models": {"default": "mock/creator-a"}}).json()["run_id"]
        c.post(f"/api/runs/{run}/start")
        r = _wait(c, run, {"PAUSED_BUDGET"})
        assert "SpendNotAuthorized" in r["note"]
        assert paid.calls == []


def test_budget_and_authorization_endpoints(client):
    client.post("/api/fx", json={"rate": "5.10", "margin": "0.10"})
    bid = client.post("/api/budgets", json={"scope": "PROJECT", "scope_ref": "p", "limit_brl": "100"}).json()["id"]
    split = client.post(f"/api/budgets/{bid}/seed-experiment").json()
    assert "experiment" in split
    assert client.post("/api/authorizations", json={"budget_id": bid, "amount_brl": "10", "granted_by": ""}) \
        .status_code == 409
    aid = client.post("/api/authorizations", json={"budget_id": bid, "amount_brl": "10",
                                                   "granted_by": "Tassiane"}).json()["id"]
    b = client.get("/api/budgets").json()
    assert b["fx"]["rate"].startswith("5.1") and [a["id"] for a in b["authorizations"]] == [aid]
    client.delete(f"/api/authorizations/{aid}")
    assert client.get("/api/budgets").json()["authorizations"] == []


def test_prompt_endpoints(client):
    p = client.get("/api/prompts").json()
    assert len(p["prompts"]) == 16 and all(v == [] for v in p["coverage"].values())
    vs = client.get("/api/prompts/role:planner/versions").json()
    v2 = client.put("/api/prompts/role:planner", json={"body": "novo\n", "author": "t"}).json()["version_id"]
    assert "+novo" in client.get("/api/prompts-diff", params={"a": vs[0]["id"], "b": v2}).json()["diff"]
    client.post(f"/api/prompts/role:planner/restore/{vs[0]['id']}", json={"author": "t"})
    c = client.get("/api/prompts-compose/creator").json()
    assert c["missing_required"] == [] and c["contract"] == "card.v2"


def test_api_key_never_leaks(tmp_path, monkeypatch, caplog):
    """SEC-001: a chave não aparece em respostas, logs ou arquivos de dados."""
    monkeypatch.setenv("OPENROUTER_API_KEY", FAKE_KEY)
    from cardfactory.config import load_settings
    monkeypatch.setenv("CARDFACTORY_DATA_DIR", str(tmp_path))
    settings = load_settings()
    assert settings.openrouter_configured and FAKE_KEY not in repr(settings)
    caplog.set_level(logging.DEBUG)
    app = create_app(settings)
    with TestClient(app) as c:
        bodies = [c.get(u).text for u in ("/api/health", "/api/dashboard", "/api/budgets", "/api/prompts",
                                          "/api/calls", "/api/models")]
        logging.getLogger("x").error("falha com %s", FAKE_KEY)
    assert all(FAKE_KEY not in b for b in bodies)
    assert FAKE_KEY not in caplog.text
    for f in tmp_path.rglob("*"):
        if f.is_file():
            assert FAKE_KEY.encode() not in f.read_bytes(), f


def test_not_implemented_endpoint(client):
    r = client.get("/api/not-implemented/audit-mode-b")
    assert r.status_code == 501 and r.json()["status"] == "NOT_IMPLEMENTED"


def test_cli_refuses_public_bind():
    from cardfactory.cli import main
    assert main(["serve", "--host", "0.0.0.0"]) == 2




def test_cli_backup_and_check(tmp_path, monkeypatch, capsys):
    from cardfactory.cli import main
    monkeypatch.setenv("CARDFACTORY_DATA_DIR", str(tmp_path))
    assert main(["migrate"]) == 0
    assert main(["check"]) == 0
    assert main(["backup"]) == 0
    assert len(list((tmp_path / "backups").glob("*.sqlite"))) == 1
    assert "ERRO" not in capsys.readouterr().out
