"""Etapas de pesquisa com provedor simulado roteirizado: regras de contrato e de evidência."""

import pytest
from sqlalchemy import select

from cardfactory.db.models import Claim, Document, LearningObjective, Production, Project, Task
from cardfactory.knowledge.dimensions import DIMENSIONS
from cardfactory.knowledge.service import Knowledge
from cardfactory.library.service import Library
from cardfactory.orchestrator.engine import Orchestrator, TaskSpec
from cardfactory.pipeline import research as rs
from cardfactory.prompts.registry import PromptRegistry
from cardfactory.providers.gateway import LLMGateway
from cardfactory.providers.mock import MockProvider, Scripted
from tests.unit.test_prompt_registry import ROOT

DOC = b"<h1>PCDT</h1><h2>Tratamento</h2><p>Losartana 50 mg uma vez ao dia em adultos.</p>"


async def nosleep(_):
    return None


@pytest.fixture
def env(db, finance, budget, tmp_path):
    with db.write() as s:
        p = Project(name="p")
        s.add(p)
        s.flush()
        prd = Production(project_id=p.id, mode="FULL_CREATION", theme="HAS")
        s.add(prd)
        s.flush()
        prd_id = prd.id
    reg = PromptRegistry(db, ROOT / "prompts", ROOT / "docs" / "normative")
    reg.import_library()
    mock = MockProvider()
    fetched: list[str] = []

    async def fetcher(url):
        fetched.append(url)
        if "fora" in url:
            raise RuntimeError("HTTP 404")
        return DOC, "text/html", url

    svc = rs.ResearchServices(db, LLMGateway(db, finance, mock, sleep=nosleep), reg, Library(db, tmp_path),
                              Knowledge(db), fetcher, {"default": "mock/creator-a"})
    return {"db": db, "svc": svc, "mock": mock, "prd": prd_id, "budget": budget, "fetched": fetched}


def _run(env, stages, handlers):
    o = Orchestrator(env["db"], handlers, backoff_base=0)
    graph = [TaskSpec(s, s, s.lower(), {"budget_ids": [env["budget"]]}, deps=[stages[i - 1]] if i else [])
             for i, s in enumerate(stages)]
    run = o.create_run(env["prd"], "FULL_CREATION", graph)
    o.start(run)
    return o, run


def _wrap(env, fn):
    async def h(ctx):
        return await fn(env["svc"], ctx)
    return h


def _states(db, run):
    with db.session() as s:
        return {t.stage: (t.state, t.output, t.last_error) for t in s.execute(select(Task).where(Task.run_id == run))
                .scalars()}


def _candidates(*urls):
    return {"searches": ["q"], "unavailable": [], "limitations": [], "candidates": [
        {"title_claimed": f"Doc {i}", "institution": "MS", "url": u, "doc_type": "PCDT", "year_claimed": "2024",
         "tier_claimed": "BR_OFFICIAL", "why_relevant": "x"} for i, u in enumerate(urls)]}


async def test_research_requires_retrieval(env):
    """BIB-008: candidatos listados não bastam; sem documento lido a etapa aguarda o humano."""
    env["mock"].enqueue(Scripted(payload=_candidates("https://gov.example/fora")))
    o, run = _run(env, ["RESEARCH", "RETRIEVAL"], {"research": _wrap(env, rs.research),
                                                   "retrieval": _wrap(env, rs.retrieval)})
    assert await o.run_until_idle(run) == "PAUSED"
    st = _states(env["db"], run)
    assert st["RESEARCH"][0] == "SUCCEEDED" and st["RETRIEVAL"][0] == "AWAITING_HUMAN"
    with env["db"].session() as s:
        d = s.execute(select(Document)).scalar_one()
    assert d.access_state == "UNAVAILABLE" and "404" in d.pending_reason


async def test_research_cache_and_url_dedup(env):
    env["mock"].enqueue(Scripted(payload=_candidates("https://gov.example/a", "https://gov.example/a", "ftp://x")))
    o, run = _run(env, ["RESEARCH", "RETRIEVAL"], {"research": _wrap(env, rs.research),
                                                   "retrieval": _wrap(env, rs.retrieval)})
    assert await o.run_until_idle(run) == "COMPLETED"
    out = _states(env["db"], run)["RESEARCH"][1]
    assert len(set(out["document_ids"])) == 1 and env["fetched"] == ["https://gov.example/a"]
    o2, run2 = _run(env, ["RESEARCH"], {"research": _wrap(env, rs.research)})
    assert await o2.run_until_idle(run2) == "COMPLETED"
    assert _states(env["db"], run2)["RESEARCH"][1]["from_cache"] is True
    assert len(env["mock"].calls) == 1


async def test_extraction_rejects_invented_quotes(env):
    env["mock"].enqueue(Scripted(payload=_candidates("https://gov.example/a")))
    good = {"quote": "Losartana 50 mg uma vez ao dia", "text": "Losartana 50 mg/dia em adultos", "component": "DOSE",
            "criticality": "HIGH", "numeric_value": 50, "numeric_unit": "mg/dia", "numeric_operator": "="}
    bad = {**good, "quote": "Losartana 100 mg uma vez ao dia", "text": "dose inventada"}
    base = {"population": "adultos", "scenario": "", "negation_kind": None, "conditions": []}

    def responder(req):
        if "unreadable_sections" in req.response_schema["properties"]:
            sid = req.messages[-1]["content"].split('<untrusted_document id="')[1].split('"')[0]
            return {"claims": [{**base, **good, "section_id": sid}, {**base, **bad, "section_id": sid},
                               {**base, **good, "section_id": "sec_outro"}],
                    "unreadable_sections": [], "limitations": []}
        raise AssertionError("inesperado")

    env["mock"].responder = responder
    o, run = _run(env, ["RESEARCH", "RETRIEVAL", "EXTRACTION"],
                  {"research": _wrap(env, rs.research), "retrieval": _wrap(env, rs.retrieval),
                   "extraction": _wrap(env, rs.extraction)})
    assert await o.run_until_idle(run) == "COMPLETED"
    out = _states(env["db"], run)["EXTRACTION"][1]
    assert out["claims"] == 1 and out["rejected_total"] == 2
    assert {r["reason"] for r in out["rejected"]} == {"o trecho citado não está na seção indicada",
                                                      "seção fora do lote"}
    with env["db"].session() as s:
        c = s.execute(select(Claim)).scalar_one()
    assert c.numeric == {"value": 50, "unit": "mg/dia", "operator": "="} and c.criticality == "HIGH"
    # O prompt do extrator recebeu o documento como dado não confiável.
    assert '<untrusted_document id="sec_' in env["mock"].calls[-1].messages[-1]["content"]


def _plan(claim_ids, dims=None, objectives=None):
    dims = dims if dims is not None else [{"code": c, "state": "APPLICABLE_PENDING", "justification": ""}
                                          for c in DIMENSIONS]
    return {"entities": [{"name": "HAS", "synonyms": [], "home_deck_path": "IGOR::Cardio", "dimensions": dims,
                          "decision_points": [{"description": "urgência x emergência", "condition_axis": "GRAVIDADE",
                                               "disposition_relevant": True}]}],
            "objectives": objectives if objectives is not None else [
                {"ref": "o1", "entity": "HAS", "subtopic": "", "description": "Dose de losartana",
                 "knowledge_level": "FACTUAL", "knowledge_type": "dose", "necessity": "REQUIRED",
                 "purpose": "segurança", "clinical_relevance": "HIGH", "coverage_state": "ABSENT",
                 "claim_ids": claim_ids + ["clm_inventada"], "depends_on": [], "planned_cards": 1,
                 "planned_rationale": "uma dose"},
                {"ref": "o2", "entity": "HAS", "subtopic": "", "description": "Sem evidência",
                 "knowledge_level": "FACTUAL", "knowledge_type": "x", "necessity": "REQUIRED", "purpose": "x",
                 "clinical_relevance": "LOW", "coverage_state": "ABSENT", "claim_ids": [], "depends_on": ["o1"],
                 "planned_cards": 1, "planned_rationale": ""}],
            "limitations": []}


async def _seed_claim(env):
    lib, k = env["svc"].library, env["svc"].knowledge
    doc = lib.register_found(lib.add_version(lib.add_source(title_claimed="PCDT")), None)
    lib.ingest(doc, DOC)
    ev = lib.add_evidence(lib.sections(doc)[-1]["id"], "Losartana 50 mg")
    cid = k.add_claim("Losartana 50 mg/dia", component="DOSE", numeric={"value": 50, "unit": "mg/dia"})
    k.link_evidence(cid, ev)
    return cid


async def test_planning_and_objectives(env):
    cid = await _seed_claim(env)
    env["mock"].enqueue(Scripted(payload=_plan([cid])))

    async def fake_extraction(ctx):
        return {"claim_ids": [cid]}

    o, run = _run(env, ["EXTRACTION", "PLANNING", "OBJECTIVES"],
                  {"extraction": fake_extraction, "planning": _wrap(env, rs.planning),
                   "objectives": _wrap(env, rs.objectives)})
    assert await o.run_until_idle(run) == "COMPLETED"
    st = _states(env["db"], run)
    assert st["PLANNING"][1]["unknown_claim_refs"] == ["clm_inventada"]
    assert len(st["OBJECTIVES"][1]["ready"]) == 1 and len(st["OBJECTIVES"][1]["pending_research"]) == 1
    with env["db"].session() as s:
        states = {o.description: o.coverage_state for o in s.execute(select(LearningObjective)).scalars()}
    assert states == {"Dose de losartana": "ABSENT", "Sem evidência": "NOT_VERIFIABLE"}
    # Planejamento usou o prompt do planejador com a lista de dimensões e só IDs fornecidos.
    content = env["mock"].calls[-1].messages[-1]["content"]
    assert "57. Integração clínica" in content and cid in content


async def test_planning_incomplete_map_is_terminal(env):
    cid = await _seed_claim(env)
    dims = [{"code": c, "state": "APPLICABLE_PENDING", "justification": ""} for c in list(DIMENSIONS)[:56]]
    dims.append({"code": 1, "state": "APPLICABLE_PENDING", "justification": ""})  # 57 itens, código repetido
    env["mock"].enqueue(Scripted(payload=_plan([cid], dims=dims)))

    async def fake_extraction(ctx):
        return {"claim_ids": [cid]}

    o, run = _run(env, ["EXTRACTION", "PLANNING"], {"extraction": fake_extraction,
                                                    "planning": _wrap(env, rs.planning)})
    assert await o.run_until_idle(run) == "FAILED"
    st = _states(env["db"], run)["PLANNING"]
    assert st[0] == "FAILED" and "57 dimensões" in st[2]
    assert len(env["mock"].calls) == 1  # violação de contrato não é repetida


async def test_uploaded_mode_skips_research(env):
    lib = env["svc"].library
    doc = lib.register_found(lib.add_version(lib.add_source(title_claimed="PDF enviado")), None)
    lib.ingest(doc, DOC, origin="USER_UPLOAD")
    with env["db"].write() as s:
        prd = s.get(Production, env["prd"])
        prd.research_mode = "UPLOADED"
        prd.scope = {"document_ids": [doc]}
    o, run = _run(env, ["RESEARCH", "RETRIEVAL"], {"research": _wrap(env, rs.research),
                                                   "retrieval": _wrap(env, rs.retrieval)})
    assert await o.run_until_idle(run) == "COMPLETED"
    st = _states(env["db"], run)
    assert st["RETRIEVAL"][1]["readable"] == [doc] and env["mock"].calls == []
