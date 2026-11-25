"""Etapa 1 de ponta a ponta com o provedor simulado: preparo único, Rodada A por criador e Rodada B."""

import asyncio
from pathlib import Path

from sqlalchemy import select

from cardfactory.benchmark import experiment_run as er
from cardfactory.config import Settings
from cardfactory.db.models import Card, Production
from cardfactory.pipeline import full_creation
from cardfactory.pipeline.simulation import mock_fetcher
from cardfactory.providers.mock import MockProvider


def test_round_a_and_b_with_mock(db, finance, budget, tmp_path: Path):
    env = er.build_env(Settings(data_dir=tmp_path), db, MockProvider(responder=full_creation.mock_responder),
                       fetcher=mock_fetcher)
    prep = asyncio.run(er.prepare(env, theme="Escabiose", support_model="mock/auditor-b", budget_id=budget))
    assert prep["state"] == "COMPLETED", prep
    objs = er.pick_objectives(env, prep["production_id"], 5)
    assert objs and len(objs) <= 5
    a = asyncio.run(er.round_a(env, pilot_production_id=prep["production_id"], objective_ids=objs,
                               creators=["mock/creator-a", "mock/creator-c"], auditor="mock/auditor-b",
                               budget_id=budget))
    assert [r["status"] for r in a["results"]] == ["ok", "ok"], a
    with db.session() as s:
        for r in a["results"]:
            assert r["cards"] > 0 and r["audit"]["cards"] == r["cards"]
            n = s.query(Card).filter(Card.production_id == r["production_id"]).count()
            assert n == r["cards"]  # cada criador na sua produção
            assert s.get(Production, r["production_id"]).scope["creator"] == r["model"]
        assert s.execute(select(Card).where(Card.production_id == prep["production_id"])).first() is None
    b = asyncio.run(er.round_b(env, auditors=["mock/auditor-b"], budget_id=budget, actor="teste"))
    assert "error" not in b[0] and b[0]["metrics"]["items"] > 0, b
