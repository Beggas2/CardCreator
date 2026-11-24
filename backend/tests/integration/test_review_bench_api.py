"""API da mesa de revisão e do laboratório com provedor simulado (sem rede, sem custo)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cardfactory.api.app import create_app
from cardfactory.cards.samples import SAMPLES
from cardfactory.config import Settings
from cardfactory.pipeline import full_creation
from cardfactory.providers.mock import MockProvider


@pytest.fixture
def env(tmp_path: Path):
    prov = MockProvider(responder=full_creation.mock_responder)
    with TestClient(create_app(Settings(data_dir=tmp_path), providers={"mock": prov})) as c:
        yield c, prov


def test_review_flow_over_api(env):
    c, _ = env
    c.post("/api/productions", json={"theme": "x"})
    pid = c.get("/api/projects").json()[0]["id"]
    card = c.post("/api/cards", json={"project_id": pid, "card": SAMPLES["direct"], "author": "Autora"})
    assert card.status_code == 200, card.text
    q = c.get(f"/api/review/queue?project_id={pid}").json()
    cid = q[0]["id"]
    assert {r["code"] for r in c.get("/api/review/reasons").json()} >= {"SCIENTIFIC_ERROR", "TOO_DENSE"}
    r = c.post(f"/api/review/cards/{cid}/decision", json={"decision": "APPROVE", "actor": "R", "duration_ms": 5000})
    assert r.status_code == 200 and r.json()["state"] == "HUMAN_APPROVED"
    assert c.get(f"/api/review/queue?project_id={pid}").json() == []  # aprovados saem da fila
    assert c.post(f"/api/review/cards/{cid}/undo", json={"actor": "R"}).status_code == 200
    bad = c.post(f"/api/review/cards/{cid}/decision", json={"decision": "REJECT", "actor": "R"})
    assert bad.status_code == 400 and "motivo" in bad.json()["detail"]
    assert c.get("/api/review/insights").json()["decisions"] == {}  # aprovação desfeita não conta


def test_benchmark_ai_subject_with_mock(env):
    c, prov = env
    c.post("/api/bench/sets/load")
    r = c.post("/api/bench/runs", json={"set_name": "KNOWN_DEFECTS", "split": "dev",
                                        "subject": "auditor_scientific", "actor": "t"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["metrics"]["detection"]["n"] == 6
    assert all(q.schema_name == "sci_audit_v1" for q in prov.calls)
    run = c.get(f"/api/bench/runs/{body['run_id']}").json()
    assert run["prompt_hashes"]["auditor_scientific"] and run["cost_usd"] == "0"
    paid = c.post("/api/bench/runs", json={"set_name": "KNOWN_DEFECTS", "subject": "auditor_scientific",
                                           "actor": "t", "provider": "openrouter"})
    assert paid.status_code == 400
