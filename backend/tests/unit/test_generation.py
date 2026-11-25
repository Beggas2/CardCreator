"""Etapa GENERATION com card.v2 (TEC-016, TEC-017, SCI-013): só cita o que recebeu, reduz lote truncado, retoma."""

import pytest
from sqlalchemy import select

from cardfactory.cards.service import CardService
from cardfactory.db.models import Card, CardVersion, LearningObjective, Production, Project, Task
from cardfactory.knowledge.service import Knowledge
from cardfactory.library.service import Library
from cardfactory.orchestrator.engine import Orchestrator, TaskSpec
from cardfactory.pipeline import generation as gen
from cardfactory.pipeline import research as rs
from cardfactory.pipeline.simulation import mock_fetcher, mock_responder
from cardfactory.prompts.registry import PromptRegistry
from cardfactory.providers.gateway import LLMGateway
from cardfactory.providers.mock import MockProvider, Scripted
from tests.unit.test_prompt_registry import ROOT

STAGES = ["RESEARCH", "RETRIEVAL", "EXTRACTION", "PLANNING", "OBJECTIVES", "GENERATION"]


async def nosleep(_):
    return None


@pytest.fixture
def env(db, finance, budget, tmp_path):
    with db.write() as s:
        p = Project(name="p")
        s.add(p)
        s.flush()
        prd = Production(project_id=p.id, mode="FULL_CREATION", theme="[SIMULADO]", target_cards=10, batch_size=2)
        s.add(prd)
        s.flush()
        prd_id = prd.id
    reg = PromptRegistry(db, ROOT / "prompts", ROOT / "docs" / "normative")
    reg.import_library()
    mock = MockProvider(responder=mock_responder)
    svc = rs.ResearchServices(db, LLMGateway(db, finance, mock, sleep=nosleep), reg, Library(db, tmp_path),
                              Knowledge(db), mock_fetcher, {"default": "mock/creator-a"})
    cards = CardService(db, tmp_path / "media")
    return {"db": db, "svc": svc, "mock": mock, "prd": prd_id, "budget": budget, "cards": cards}


def _handlers(env):
    def wrap(fn):
        async def h(ctx):
            return await fn(env["svc"], ctx)
        return h

    async def g(ctx):
        return await gen.generation(env["svc"], ctx, env["cards"])

    return {"research": wrap(rs.research), "retrieval": wrap(rs.retrieval), "extraction": wrap(rs.extraction),
            "planning": wrap(rs.planning), "objectives": wrap(rs.objectives), "generation": g}


async def _run(env):
    o = Orchestrator(env["db"], _handlers(env), backoff_base=0)
    graph = [TaskSpec(s, s, s.lower(), {"budget_ids": [env["budget"]]}, deps=[STAGES[i - 1]] if i else [])
             for i, s in enumerate(STAGES)]
    run = o.create_run(env["prd"], "FULL_CREATION", graph)
    o.start(run)
    state = await o.run_until_idle(run)
    with env["db"].session() as s:
        t = s.execute(select(Task).where(Task.run_id == run, Task.stage == "GENERATION")).scalar_one()
        return state, t.state, t.output, t.last_error


async def test_generation_creates_valid_cards_and_releases_leases(env):
    state, tstate, out, _ = await _run(env)
    assert state == "COMPLETED" and tstate == "SUCCEEDED"
    assert len(out["card_ids"]) == 2 and out["rejected"] == []
    with env["db"].session() as s:
        objs = list(s.execute(select(LearningObjective)).scalars())
        assert all(o.lease_owner is None and o.coverage_state == "PARTIAL" for o in objs)
        v = s.execute(select(CardVersion)).scalars().first()
        assert v.schema_version == "2.1" and v.created_by_call_id and v.layout in ("direct", "pharmacology")
        assert all(c.origin == "MOCK" for c in s.execute(select(Card)).scalars())
    gen_call = env["mock"].calls[-1]
    assert "<untrusted_document id=\"ev_" in gen_call.messages[-1]["content"]


async def test_generation_rejects_cards_citing_unknown_ids(env):
    def responder(req):
        out = mock_responder(req)
        if "unverified_claims" in req.response_schema["properties"]:
            out["cards"][0]["claims"][0]["claim_id"] = "clm_inventada"
            out["cards"][0]["answer"][0]["items"][0]["segments"][0]["claim_ids"] = ["clm_inventada"]
            out["cards"].append({**out["cards"][0], "objective_ids": ["obj_de_outro_lote"]})
        return out

    env["mock"].responder = responder
    state, tstate, out, err = await _run(env)
    assert tstate == "FAILED" and "nenhum card válido" in err  # nada gravado em silêncio
    with env["db"].session() as s:
        assert s.execute(select(Card)).first() is None


async def test_generation_shrinks_batch_on_truncation(env):
    """TEC-016: saída truncada → lote dividido ao meio e nova chamada (chave diferente)."""
    mock = env["mock"]
    original = mock.complete
    gen_keys: list[str] = []

    async def complete(req):
        if "unverified_claims" in (req.response_schema or {}).get("properties", {}):
            gen_keys.append(req.idempotency_key)
            if len(gen_keys) == 1:
                mock.enqueue(Scripted(kind="truncated"))
        return await original(req)

    mock.complete = complete
    with env["db"].write() as s:
        s.get(Production, env["prd"]).batch_size = 4  # lote de 2 objetivos → truncado → lote de 1
    state, tstate, out, err = await _run(env)
    assert tstate == "SUCCEEDED", err
    assert any("truncado" in x for x in out["limitations"])
    assert len(gen_keys) == 3 and gen_keys[0].endswith(".s2") and gen_keys[1].endswith(".s1")
    assert len(out["card_ids"]) == 2
