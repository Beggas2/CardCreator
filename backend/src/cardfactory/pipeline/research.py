"""Etapas de pesquisa e conhecimento (Fase 2): RESEARCH, RETRIEVAL, EXTRACTION, PLANNING, OBJECTIVES.

Regras centrais:
- O pesquisador só sugere candidatos; nada é confirmado sem recuperar o documento (BIB-008).
- Afirmações extraídas só entram com trecho literal conferido na seção (SCI-006).
- O planejador só pode vincular objetivos a afirmações que recebeu; o mapa precisa das 57 dimensões.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update

from cardfactory.contracts.schemas import EXTRACTION_V1, PLAN_V1, RESEARCH_RESULT_V1, schema_name
from cardfactory.db import Database
from cardfactory.db.models import (
    Card,
    Claim,
    ClaimEvidence,
    Document,
    DocumentSection,
    LearningObjective,
    Production,
    ResearchQuery,
    Run,
    Source,
    SourceVersion,
)
from cardfactory.knowledge.dimensions import DIMENSIONS
from cardfactory.knowledge.service import Knowledge, KnowledgeError
from cardfactory.library.service import READ_STATES, EvidenceNotFoundError, Library, LibraryError
from cardfactory.orchestrator.engine import AwaitingHuman, ContractViolation, TaskContext
from cardfactory.prompts.registry import PromptRegistry, wrap_untrusted
from cardfactory.providers.base import LLMRequest
from cardfactory.providers.gateway import LLMGateway

Fetcher = Callable[[str], Awaitable[tuple[bytes, str | None, str]]]  # url → (bytes, content-type, url final)
EXTRACTION_BATCH_CHARS = 12000
RESEARCH_CACHE_DAYS = 30


@dataclass
class ResearchServices:
    db: Database
    gateway: LLMGateway
    registry: PromptRegistry
    library: Library
    knowledge: Knowledge
    fetcher: Fetcher
    models: dict[str, str]


def production_of(db: Database, run_id: str) -> Production:
    with db.session() as s:
        return s.get(Production, s.get(Run, run_id).production_id)


async def call_role(svc: ResearchServices, ctx: TaskContext, role: str, schema: dict, user: str, key: str,
                    *, max_tokens: int = 6000, critical: bool = False,
                    web_search: dict | None = None, web_searches: int = 0, web_price: Any = None):
    composed = svc.registry.compose(role)
    if composed.missing_required:
        raise ContractViolation(f"prompt do papel {role} sem requisitos obrigatórios: {composed.missing_required}")
    model = svc.models.get(ctx.stage) or svc.models.get("default")
    if not model:
        raise ContractViolation(f"nenhum modelo configurado para a etapa {ctx.stage}")
    req = LLMRequest(model_id=model, messages=[{"role": "system", "content": composed.text},
                                               {"role": "user", "content": user}],
                     max_output_tokens=max_tokens, idempotency_key=ctx.call_key(key), response_schema=schema,
                     schema_name=schema_name(composed.contract), web_search=web_search)
    r = await svc.gateway.call(req, budget_ids=ctx.input["budget_ids"], task_id=ctx.task_id, stage=ctx.stage,
                               prompt_version_ids=composed.version_ids, prompt_hash=composed.hash,
                               critical=critical, web_searches=web_searches, web_search_price_usd=web_price)
    if r.status == "truncated":
        raise TruncatedOutputError(f"saída truncada do papel {role}; aumente o limite de saída ou reduza o lote")
    if r.status != "ok":
        raise ContractViolation(f"saída {r.status} do papel {role}; aumente o limite de saída ou reduza o lote")
    return r.parsed, r.call_id


class TruncatedOutputError(ContractViolation):
    """A resposta passou do limite de saída; quem chama pode dividir o lote."""


# ---------------------------------------------------------------------------- RESEARCH
async def research(svc: ResearchServices, ctx: TaskContext) -> dict:
    prd = production_of(svc.db, ctx.run_id)
    if prd.research_mode == "UPLOADED":
        return {"skipped": "modo somente documentos enviados", "document_ids": []}
    scope = prd.scope or {}
    query = f"{prd.theme} | {json.dumps(scope.get('research_scope') or {}, sort_keys=True, ensure_ascii=False)}"
    cache_key = hashlib.sha256(f"researcher|{query}".encode()).hexdigest()
    cutoff = datetime.now(UTC) - timedelta(days=RESEARCH_CACHE_DAYS)
    with svc.db.session() as s:
        cached = s.execute(select(ResearchQuery).where(ResearchQuery.cache_key == cache_key,
                                                       ResearchQuery.created_at >= cutoff)
                           .order_by(ResearchQuery.created_at.desc()).limit(1)).scalar_one_or_none()
        # Resultado sem nenhum candidato não é reaproveitado: costuma indicar pesquisa sem acesso à web.
        cached_result = cached.result if cached and cached.result.get("candidates") else None
    call_id = None
    if cached_result is not None:
        parsed = cached_result
    else:
        ws = scope.get("web_search")
        user = (f"Tema: {prd.theme}\nEscopo: {json.dumps(scope.get('research_scope') or {}, ensure_ascii=False)}\n"
                "Liste fontes primárias candidatas, priorizando as brasileiras oficiais. Informe só o que viu.")
        parsed, call_id = await call_role(svc, ctx, "researcher", RESEARCH_RESULT_V1, user, "research",
                                          web_search=ws, web_searches=int((ws or {}).get("max_uses", 1)) if ws else 0,
                                          web_price=scope.get("web_search_price_usd"))
        with svc.db.write() as s:
            s.add(ResearchQuery(production_id=prd.id, query=query, engine="researcher", filters={},
                                result=parsed, cost_call_id=call_id, cache_key=cache_key))
    doc_ids: list[str] = []
    for c in parsed["candidates"]:
        url = c["url"].strip()
        if not url.lower().startswith(("http://", "https://")):
            continue
        with svc.db.session() as s:
            existing = s.execute(select(Document.id).join(SourceVersion, SourceVersion.id == Document.source_version_id)
                                 .join(Source, Source.id == SourceVersion.source_id).where(Source.url == url)
                                 .limit(1)).scalar_one_or_none()
        if existing:
            doc_ids.append(existing)
            continue
        sid = svc.library.add_source(title_claimed=c["title_claimed"], institution=c["institution"],
                                     source_tier=c["tier_claimed"], doc_type=c["doc_type"], url=url,
                                     created_by="researcher", notes=f"Relevância declarada: {c['why_relevant']}")
        year = c.get("year_claimed")
        vid = svc.library.add_version(sid, version_label="declarada pelo pesquisador",
                                      published_at=year if year and len(year) == 4 and year.isdigit() else None)
        doc_ids.append(svc.library.register_found(vid, url, actor="researcher"))
    return {"call_id": call_id, "from_cache": cached_result is not None, "candidates": len(parsed["candidates"]),
            "document_ids": doc_ids, "unavailable": parsed["unavailable"], "limitations": parsed["limitations"]}


# ---------------------------------------------------------------------------- RETRIEVAL
async def retrieval(svc: ResearchServices, ctx: TaskContext) -> dict:
    prd = production_of(svc.db, ctx.run_id)
    found = list((ctx.dep_outputs().get("RESEARCH") or {}).get("document_ids") or [])
    uploaded = list((prd.scope or {}).get("document_ids") or [])
    readable, unavailable = [], []
    for did in dict.fromkeys(uploaded + found):
        with svc.db.session() as s:
            d = s.get(Document, did)
            state, url = (d.access_state, d.fetch_url) if d else (None, None)
        if state is None:
            continue
        if state in READ_STATES:
            readable.append(did)
            continue
        if state != "FOUND" or not url:
            unavailable.append({"document_id": did, "reason": f"estado {state}"})
            continue
        try:
            data, ctype, final_url = await svc.fetcher(url)
            res = svc.library.ingest(did, data, declared_mime=ctype, fetch_url=final_url, actor="retrieval")
        except Exception as e:  # noqa: BLE001 - toda falha vira pendência registrada, nunca "inexistente"
            reason = f"{type(e).__name__}: {e}"[:500]
            svc.library.mark_unavailable(did, reason, actor="retrieval")
            unavailable.append({"document_id": did, "reason": reason})
            continue
        if res.state in READ_STATES:
            readable.append(did)
        else:
            unavailable.append({"document_id": did, "reason": "; ".join(res.warnings) or res.state})
    if not readable:
        raise AwaitingHuman("nenhum documento pôde ser lido; envie PDFs na Biblioteca ou revise as fontes (BIB-008)")
    return {"readable": readable, "unavailable": unavailable}


# ---------------------------------------------------------------------------- EXTRACTION
def _batches(sections: list[DocumentSection]) -> list[list[DocumentSection]]:
    out, cur, size = [], [], 0
    for s in sections:
        if cur and size + len(s.text) > EXTRACTION_BATCH_CHARS:
            out.append(cur)
            cur, size = [], 0
        cur.append(s)
        size += len(s.text)
    if cur:
        out.append(cur)
    return out


async def extraction(svc: ResearchServices, ctx: TaskContext) -> dict:
    prd = production_of(svc.db, ctx.run_id)
    docs = (ctx.dep_outputs().get("RETRIEVAL") or {}).get("readable") or []
    done: dict[str, Any] = dict(ctx.checkpoint.get("done") or {})
    claim_ids: list[str] = list(ctx.checkpoint.get("claim_ids") or [])
    rejected: list[dict] = list(ctx.checkpoint.get("rejected") or [])
    for did in docs:
        with svc.db.session() as s:
            secs = list(s.execute(select(DocumentSection).where(DocumentSection.document_id == did,
                                                                DocumentSection.parse_quality != "FAILED")
                                  .order_by(DocumentSection.ordinal)).scalars())
        queue = [(f"{did}:{i}", batch) for i, batch in enumerate(_batches(secs))]
        while queue:
            bkey, batch = queue.pop(0)
            if bkey in done:
                continue
            ids = {s.id for s in batch}
            body = "\n\n".join(wrap_untrusted(s.id, f"[{s.path}]\n{s.text}") for s in batch)
            user = (f"Tema: {prd.theme}\nExtraia afirmações verificáveis relevantes ao tema. Para cada uma, copie "
                    f"o trecho literal (quote) da seção e informe o section_id.\n\n{body}")
            # Um lote de ~12 mil caracteres pode render dezenas de afirmações com trecho literal: 6 mil tokens
            # de saída truncavam na prática (Etapa 1, 24/11/2026). Se ainda truncar, o lote é dividido.
            try:
                parsed, call_id = await call_role(svc, ctx, "extractor", EXTRACTION_V1, user, f"extract:{bkey}",
                                                  critical=True, max_tokens=16000)
            except TruncatedOutputError:
                if len(batch) > 1:
                    half = len(batch) // 2
                    queue[:0] = [(f"{bkey}a", batch[:half]), (f"{bkey}b", batch[half:])]
                    continue
                rejected.append({"reason": "seção não processada: a extração truncou mesmo sozinha",
                                 "text": batch[0].path[:200]})
                done[bkey] = None
                ctx.save_checkpoint({"done": done, "claim_ids": claim_ids, "rejected": rejected})
                continue
            for c in parsed["claims"]:
                if c["section_id"] not in ids:
                    rejected.append({"reason": "seção fora do lote", "text": c["text"][:200]})
                    continue
                try:
                    ev = svc.library.add_evidence(c["section_id"], c["quote"], call_id=call_id)
                except (EvidenceNotFoundError, LibraryError) as e:
                    rejected.append({"reason": str(e), "text": c["text"][:200], "quote": c["quote"][:200]})
                    continue
                numeric = None
                if c.get("numeric_value") is not None and c.get("numeric_unit"):
                    numeric = {"value": c["numeric_value"], "unit": c["numeric_unit"],
                               "operator": c.get("numeric_operator") or "="}
                try:
                    cid = svc.knowledge.add_claim(
                        c["text"], component=c["component"], population=c["population"], scenario=c["scenario"],
                        criticality=c["criticality"], negation_kind=c.get("negation_kind"), numeric=numeric,
                        call_id=call_id)
                except KnowledgeError as e:
                    rejected.append({"reason": str(e), "text": c["text"][:200]})
                    continue
                svc.knowledge.link_evidence(cid, ev)
                claim_ids.append(cid)
            done[bkey] = call_id
            ctx.save_checkpoint({"done": done, "claim_ids": claim_ids, "rejected": rejected})
    if not claim_ids:
        raise AwaitingHuman("nenhuma afirmação com trecho conferido foi extraída dos documentos lidos")
    return {"claim_ids": claim_ids, "claims": len(claim_ids), "rejected": rejected[:200],
            "rejected_total": len(rejected), "batches": len(done)}


# ---------------------------------------------------------------------------- PLANNING
async def planning(svc: ResearchServices, ctx: TaskContext) -> dict:
    prd = production_of(svc.db, ctx.run_id)
    claim_ids = (ctx.dep_outputs().get("EXTRACTION") or {}).get("claim_ids") or []
    with svc.db.session() as s:
        claims = list(s.execute(select(Claim).where(Claim.id.in_(claim_ids))).scalars())
    listing = "\n".join(f"- {c.id} [{c.component}] {c.text}" + (f" (população: {c.population})" if c.population else "")
                        for c in claims[:400])
    dims = "\n".join(f"{k}. {v}" for k, v in DIMENSIONS.items())
    user = (f"Tema: {prd.theme}\nMeta aproximada de cards: {prd.target_cards}\n\nDimensões do mapa (classifique "
            f"todas as 57 para cada entidade):\n{dims}\n\nAfirmações verificadas disponíveis (use só estes IDs):\n"
            f"{listing}")
    # 57 dimensões com justificativa por entidade, mais o raciocínio do modelo: 16 mil tokens truncavam.
    parsed, call_id = await call_role(svc, ctx, "planner", PLAN_V1, user, "plan", max_tokens=48000)
    known = {c.id for c in claims}
    with svc.db.session() as s:
        project_cards = s.execute(select(func.count()).select_from(Card).where(
            Card.project_id == prd.project_id)).scalar_one()
    entity_ids: dict[str, str] = {}
    for e in parsed["entities"]:
        codes = [d["code"] for d in e["dimensions"]]
        if sorted(codes) != list(range(1, 58)):
            raise ContractViolation(f"mapa da entidade {e['name']} não tem as 57 dimensões exatamente uma vez")
        eid = svc.knowledge.upsert_entity(prd.project_id, e["name"], synonyms=e["synonyms"],
                                          home_deck_path=e["home_deck_path"])
        try:
            svc.knowledge.set_map(eid, {d["code"]: (d["state"], d["justification"]) for d in e["dimensions"]},
                                  call_id=call_id)
        except KnowledgeError as err:
            raise ContractViolation(str(err)) from err
        for dp in e["decision_points"]:
            svc.knowledge.add_decision_point(eid, dp["description"], dp["condition_axis"], dp["disposition_relevant"])
        entity_ids[e["name"]] = eid
    refs: dict[str, str] = {}
    dropped_claims: list[str] = []
    problems: list[str] = []
    for o in parsed["objectives"]:
        deps = [refs[d] for d in o["depends_on"] if d in refs]
        if o["coverage_state"] == "COVERED_ELSEWHERE" and not project_cards:
            # Sem nenhum card no projeto, "coberto em outro lugar" não tem onde estar (Etapa 1: o planejador
            # marcou os 20 objetivos assim e a produção parou sem gerar nada).
            problems.append(f"{o['ref']}: COVERED_ELSEWHERE sem cards no projeto; tratado como ABSENT")
            o = {**o, "coverage_state": "ABSENT"}
        try:
            oid = svc.knowledge.add_objective(
                prd.project_id, o["description"], entity_id=entity_ids.get(o["entity"]), production_id=prd.id,
                knowledge_level=o["knowledge_level"], necessity=o["necessity"], coverage_state=o["coverage_state"],
                purpose=o["purpose"], subtopic=o["subtopic"], knowledge_type=o["knowledge_type"],
                clinical_relevance=o["clinical_relevance"], planned_cards=o["planned_cards"],
                planned_rationale=o["planned_rationale"], depends_on=deps, call_id=call_id)
        except KnowledgeError as err:
            problems.append(f"{o['ref']}: {err}")
            continue
        refs[o["ref"]] = oid
        valid = [c for c in o["claim_ids"] if c in known]
        dropped_claims += [c for c in o["claim_ids"] if c not in known]
        if valid:
            with svc.db.write() as s:
                s.execute(update(Claim).where(Claim.id.in_(valid), Claim.objective_id.is_(None))
                          .values(objective_id=oid))
    if not refs:
        raise ContractViolation("o plano não produziu nenhum objetivo válido: " + "; ".join(problems[:5]))
    return {"call_id": call_id, "entities": list(entity_ids.values()), "objectives": len(refs),
            "unknown_claim_refs": dropped_claims[:100], "problems": problems, "limitations": parsed["limitations"]}


# ---------------------------------------------------------------------------- OBJECTIVES
async def objectives(svc: ResearchServices, ctx: TaskContext) -> dict:
    """Determinística: objetivo obrigatório/recomendado sem afirmação com evidência fica pendente de pesquisa."""
    prd = production_of(svc.db, ctx.run_id)
    with svc.db.session() as s:
        objs = list(s.execute(select(LearningObjective).where(
            LearningObjective.production_id == prd.id,
            LearningObjective.necessity.in_(["REQUIRED", "RECOMMENDED"]))).scalars())
        supported = set(s.execute(select(Claim.objective_id).join(ClaimEvidence, ClaimEvidence.claim_id == Claim.id)
                                  .where(Claim.objective_id.in_([o.id for o in objs]),
                                         ClaimEvidence.supports.in_(["SUPPORTS", "PARTIAL"]))).scalars())
    ready, pending = [], []
    for o in objs:
        if o.coverage_state in ("NOT_APPLICABLE", "COVERED_ELSEWHERE"):
            continue
        (ready if o.id in supported else pending).append(o.id)
    for oid in pending:
        svc.knowledge.set_coverage(oid, "NOT_VERIFIABLE")
    if not ready:
        raise AwaitingHuman("nenhum objetivo obrigatório tem afirmação com evidência; amplie a pesquisa")
    return {"ready": ready, "pending_research": pending, "coverage": svc.knowledge.coverage_report(prd.id)}
