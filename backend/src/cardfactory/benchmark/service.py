"""Laboratório de benchmark (BENCHMARK_PROTOCOL): conjuntos com split fixo, eval selado, métricas por gabarito
com intervalo exato (Clopper-Pearson) e comparação cega com revelação só após a decisão gravada."""

from __future__ import annotations

import math
import random
import secrets
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from cardfactory.audit.deterministic import scan_all
from cardfactory.benchmark import fixtures
from cardfactory.benchmark.fixtures import SEVERITY_RANK
from cardfactory.contracts.schemas import PED_AUDIT_V1, SCI_AUDIT_V1, schema_name
from cardfactory.db import Database
from cardfactory.db.models import (
    BenchmarkItem,
    BenchmarkRun,
    BlindComparison,
    CardVersion,
    EvalAccess,
    LLMCall,
)
from cardfactory.ids import new_id
from cardfactory.providers.base import LLMRequest

SETS = {"KNOWN_DEFECTS": fixtures.known_defects, "REFERENCE": fixtures.reference_items}
SUBJECTS = ("DETERMINISTIC", "auditor_scientific", "auditor_pedagogical")
SCHEMAS = {"auditor_scientific": SCI_AUDIT_V1, "auditor_pedagogical": PED_AUDIT_V1}
BATCH = 3


class BenchmarkError(Exception):
    pass


# ---------------------------------------------------------------------------- estatística
def _binom_cdf(k: int, n: int, p: float) -> float:
    if p <= 0:
        return 1.0
    if p >= 1:
        return 0.0 if k < n else 1.0
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k + 1))


def clopper_pearson(k: int, n: int, alpha: float = 0.05) -> tuple[float, float] | None:
    """Intervalo exato para proporção (bisseção sobre a binomial; sem dependências)."""
    if n == 0:
        return None

    def solve(f) -> float:
        lo, hi = 0.0, 1.0
        for _ in range(60):
            mid = (lo + hi) / 2
            if f(mid):
                hi = mid
            else:
                lo = mid
        return (lo + hi) / 2

    lower = 0.0 if k == 0 else solve(lambda p: 1 - _binom_cdf(k - 1, n, p) >= alpha / 2)
    upper = 1.0 if k == n else solve(lambda p: _binom_cdf(k, n, p) <= alpha / 2)
    return round(lower, 4), round(upper, 4)


def _rate(k: int, n: int) -> dict[str, Any]:
    ci = clopper_pearson(k, n)
    return {"k": k, "n": n, "rate": round(k / n, 4) if n else None, "ci95": list(ci) if ci else None}


# ---------------------------------------------------------------------------- serviço
class BenchmarkService:
    def __init__(self, db: Database, registry=None):
        self.db = db
        self.registry = registry

    def load_sets(self) -> dict[str, dict[str, int]]:
        """Grava os conjuntos (idempotente). Um item existente nunca muda de split."""
        out: dict[str, dict[str, int]] = {}
        with self.db.write() as s:
            for name, build in SETS.items():
                created = 0
                for it in build():
                    row = s.execute(select(BenchmarkItem).where(BenchmarkItem.set_name == name,
                                                                BenchmarkItem.item_key == it["item_key"])) \
                        .scalar_one_or_none()
                    if row is None:
                        s.add(BenchmarkItem(set_name=name, item_key=it["item_key"], split=it["split"],
                                            content=it["content"], expected=it["expected"]))
                        created += 1
                out[name] = {"created": created}
        return out

    def summary(self) -> dict[str, Any]:
        with self.db.session() as s:
            rows = s.execute(select(BenchmarkItem.set_name, BenchmarkItem.split, func.count())
                             .group_by(BenchmarkItem.set_name, BenchmarkItem.split)).all()
            access = s.execute(select(EvalAccess.set_name, func.count()).group_by(EvalAccess.set_name)).all()
            log = [{"set": a.set_name, "purpose": a.purpose, "actor": a.actor, "run_id": a.run_id,
                    "at": a.created_at.isoformat()} for a in s.execute(
                select(EvalAccess).order_by(EvalAccess.created_at.desc()).limit(50)).scalars()]
        sets: dict[str, dict[str, int]] = {}
        for name, split, n in rows:
            sets.setdefault(name, {})[split] = n
        return {"sets": sets, "eval_accesses": dict(access), "eval_log": log}

    def items(self, set_name: str, split: str, *, actor: str = "", purpose: str = "") -> list[dict[str, Any]]:
        if split == "eval":
            self._log_eval(set_name, actor, purpose or "consulta de itens")
        with self.db.session() as s:
            return [{"id": i.id, "item_key": i.item_key, "split": i.split, "content": i.content,
                     "expected": i.expected} for i in s.execute(select(BenchmarkItem).where(
                         BenchmarkItem.set_name == set_name, BenchmarkItem.split == split)
                         .order_by(BenchmarkItem.item_key)).scalars()]

    def _log_eval(self, set_name: str, actor: str, purpose: str, run_id: str | None = None) -> None:
        if not actor.strip() or not purpose.strip():
            raise BenchmarkError("o split eval é selado: informe quem consulta e para quê")
        with self.db.write() as s:
            s.add(EvalAccess(set_name=set_name, purpose=purpose, actor=actor, run_id=run_id))

    async def run(self, set_name: str, split: str, subject: str, *, actor: str, purpose: str = "",
                  gateway=None, provider: str = "", models: dict[str, str] | None = None,
                  budget_ids: list[str] | None = None) -> dict[str, Any]:
        if set_name not in SETS or split not in ("dev", "eval") or subject not in SUBJECTS:
            raise BenchmarkError("conjunto, split ou sujeito inválido")
        models = models or {}
        run_id = new_id("bmr")
        if split == "eval":
            self._log_eval(set_name, actor, purpose, run_id)
        with self.db.session() as s:
            items = [(i.item_key, i.content, i.expected) for i in s.execute(select(BenchmarkItem).where(
                BenchmarkItem.set_name == set_name, BenchmarkItem.split == split)
                .order_by(BenchmarkItem.item_key)).scalars()]
        if not items:
            raise BenchmarkError("conjunto vazio: carregue os conjuntos antes")
        hashes: dict[str, str] = {}
        if subject == "DETERMINISTIC":
            found = {k: [{"category": h.category, "severity": h.severity, "description": h.description}
                         for h in scan_all(c["card"], c.get("claims") or {})] for k, c, _ in items}
        else:
            if gateway is None or self.registry is None:
                raise BenchmarkError("auditor de IA exige provedor configurado")
            model = models.get(subject) or models.get("default")
            if not model:
                raise BenchmarkError("informe o modelo do auditor; nenhum ID de modelo é presumido")
            found, hashes = await self._ai(run_id, subject, items, gateway, model, budget_ids or [])
        results = [{"item_key": k, "expected": e, "found": found.get(k, []),
                    "outcome": _outcome(e, found.get(k, []))} for k, _, e in items]
        metrics = _metrics(results)
        with self.db.session() as s:
            cost = sum((Decimal(c) for c in s.execute(select(LLMCall.cost_usd).where(
                LLMCall.idempotency_key.like(f"bench:{run_id}:%"))).scalars() if c), Decimal(0))
        with self.db.write() as s:
            s.add(BenchmarkRun(id=run_id, set_name=set_name, split=split, subject=subject, provider=provider,
                               models=models, prompt_hashes=hashes, results=results, metrics=metrics,
                               cost_usd=format(cost.normalize(), "f"), actor=actor))
        return {"run_id": run_id, "metrics": metrics, "results": results}

    async def _ai(self, run_id: str, role: str, items, gateway, model: str,
                  budget_ids: list[str]) -> tuple[dict[str, list[dict]], dict[str, str]]:
        from cardfactory.pipeline.audit import SELF_ASSESSMENT, _card_block
        composed = self.registry.compose(role)
        found: dict[str, list[dict]] = {}
        for b in range(0, len(items), BATCH):
            batch = items[b:b + BATCH]
            blocks = []
            for key, content, _ in batch:
                card = {k: v for k, v in content["card"].items() if k not in SELF_ASSESSMENT}
                claims = {cid: {"text": c["text"], "component": c["component"], "criticality": c["criticality"],
                                "population": c.get("population", ""), "numeric": c.get("numeric")}
                          for cid, c in (content.get("claims") or {}).items()}
                blocks.append(_card_block({"key": key, "content": card, "claims": claims, "spans": []}))
            user = ("Benchmark: audite cada card abaixo como faria na produção. As afirmações listadas são a "
                    "referência verificada.\n\n" + "\n\n".join(blocks))
            req = LLMRequest(model_id=model, messages=[{"role": "system", "content": composed.text},
                                                       {"role": "user", "content": user}],
                             max_output_tokens=24000, idempotency_key=f"bench:{run_id}:{role}:{b}",
                             response_schema=SCHEMAS[role], schema_name=schema_name(composed.contract))
            r = await gateway.call(req, budget_ids=budget_ids, stage=f"BENCH_{role}",
                                   prompt_version_ids=composed.version_ids, prompt_hash=composed.hash,
                                   critical=True)
            if r.status != "ok":
                raise BenchmarkError(f"saída {r.status} do auditor no benchmark")
            for d in r.parsed.get("defects", []):
                found.setdefault(d["card_ref"], []).append({"category": d["category"], "severity": d["severity"],
                                                            "description": d["description"]})
            if role == "auditor_pedagogical":
                for c in r.parsed.get("cards", []):
                    if c["operation"] != "KEEP":
                        found.setdefault(c["card_ref"], []).append({"category": "PEDAGOGICAL", "severity": "MEDIUM",
                                                                    "description": f"operação {c['operation']}"})
        return found, {role: composed.hash}

    def runs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.db.session() as s:
            return [{"id": r.id, "set": r.set_name, "split": r.split, "subject": r.subject, "provider": r.provider,
                     "models": r.models, "prompt_hashes": r.prompt_hashes, "metrics": r.metrics,
                     "cost_usd": r.cost_usd, "actor": r.actor, "created_at": r.created_at.isoformat()}
                    for r in s.execute(select(BenchmarkRun).order_by(BenchmarkRun.created_at.desc())
                                       .limit(limit)).scalars()]

    def run_detail(self, run_id: str) -> dict[str, Any]:
        with self.db.session() as s:
            r = s.get(BenchmarkRun, run_id)
            if r is None:
                raise BenchmarkError("execução inexistente")
            return {"id": r.id, "set": r.set_name, "split": r.split, "subject": r.subject, "metrics": r.metrics,
                    "results": r.results, "models": r.models, "prompt_hashes": r.prompt_hashes,
                    "cost_usd": r.cost_usd, "created_at": r.created_at.isoformat()}

    # ------------------------------------------------------------------ comparação cega
    def create_comparison(self, question: str, card_version_ids: list[str], origins: list[str] | None = None,
                          *, seed: int | None = None) -> str:
        if len(card_version_ids) < 2:
            raise BenchmarkError("a comparação cega exige ao menos duas versões")
        given = origins or ["" for _ in card_version_ids]
        origins = []
        with self.db.session() as s:
            from cardfactory.db.models import Card
            for vid, org in zip(card_version_ids, given, strict=True):
                v = s.get(CardVersion, vid)
                if v is None:
                    raise BenchmarkError(f"versão inexistente: {vid}")
                if not org:  # origem real registrada pelo sistema, revelada só depois da decisão
                    call = s.get(LLMCall, v.created_by_call_id) if v.created_by_call_id else None
                    model = (call.served_model or call.requested_model) if call else None
                    org = f"{s.get(Card, v.card_id).card_key} v{v.version_no} · {v.author_type}" + \
                        (f" · {model}" if model else "")
                origins.append(org)
        # Sem semente, a ordem e os rótulos vêm do gerador do sistema (imprevisíveis para quem avalia).
        rng = random.Random(seed) if seed is not None else secrets.SystemRandom()  # noqa: S311
        order = list(zip(card_version_ids, origins, strict=True))
        rng.shuffle(order)
        labels = rng.sample([chr(65 + i) for i in range(26)], len(order))
        items = [{"label": lab, "card_version_id": vid, "origin": org} for lab, (vid, org) in zip(labels, order,
                                                                                                   strict=True)]
        items.sort(key=lambda x: x["label"])
        with self.db.write() as s:
            c = BlindComparison(question=question, items=items)
            s.add(c)
            s.flush()
            return c.id

    def comparison(self, cid: str) -> dict[str, Any]:
        from cardfactory.render.palette import DARK
        from cardfactory.render.renderer import render
        with self.db.session() as s:
            c = s.get(BlindComparison, cid)
            if c is None:
                raise BenchmarkError("comparação inexistente")
            decided = c.decided_at is not None
            shown = []
            for it in c.items:
                v = s.get(CardVersion, it["card_version_id"])
                r = render(v.content, DARK) if v.schema_version == "2.1" else None
                row = {"label": it["label"], "front": r.front if r else v.content.get("front_html", ""),
                       "back": r.back if r else v.content.get("back_html", "")}
                if decided:  # revelação só depois da decisão gravada
                    row |= {"origin": it["origin"], "card_version_id": it["card_version_id"]}
                shown.append(row)
            return {"id": c.id, "question": c.question, "items": shown, "decided": decided, "choice": c.choice,
                    "ranking": c.ranking, "justification": c.justification, "actor": c.actor}

    def decide_comparison(self, cid: str, choice: str, *, actor: str, justification: str,
                          ranking: list[str] | None = None) -> dict[str, Any]:
        if not actor.strip() or not justification.strip():
            raise BenchmarkError("a decisão exige avaliador e justificativa")
        with self.db.write() as s:
            c = s.get(BlindComparison, cid)
            if c is None:
                raise BenchmarkError("comparação inexistente")
            if c.decided_at is not None:
                raise BenchmarkError("comparação já decidida")
            labels = {it["label"] for it in c.items}
            if choice not in labels | {"TIE"} or any(x not in labels for x in ranking or []):
                raise BenchmarkError("rótulo inválido")
            c.choice, c.ranking, c.justification, c.actor = choice, ranking or [], justification, actor
            c.decided_at = datetime.now(UTC)
        return self.comparison(cid)

    def comparisons(self) -> list[dict[str, Any]]:
        with self.db.session() as s:
            return [{"id": c.id, "question": c.question, "n": len(c.items), "decided": c.decided_at is not None,
                     "choice": c.choice, "created_at": c.created_at.isoformat()}
                    for c in s.execute(select(BlindComparison).order_by(BlindComparison.created_at.desc())
                                       .limit(100)).scalars()]


def _outcome(expected: dict[str, Any], found: list[dict[str, Any]]) -> str:
    relevant = [f for f in found if SEVERITY_RANK.get(f["severity"], 0) >= SEVERITY_RANK["MEDIUM"]]
    kind = expected.get("kind")
    if kind == "DEFECT":
        ok = any(f["category"] in expected["categories"]
                 and SEVERITY_RANK[f["severity"]] >= SEVERITY_RANK[expected["min_severity"]] for f in found)
        if ok:
            return "DETECTED"
        if any(f["category"] in expected["categories"] for f in found):
            return "DETECTED_LOW_SEVERITY"
        return "MISSED"
    if kind == "CLEAN":
        return "FALSE_ALARM" if relevant else "KEEP_OK"
    return "FLAGGED" if relevant else ("NOTED" if found else "NO_FINDINGS")


def _metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    defects = [r for r in results if r["expected"].get("kind") == "DEFECT"]
    clean = [r for r in results if r["expected"].get("kind") == "CLEAN"]
    refs = [r for r in results if r["expected"].get("kind") == "REFERENCE"]
    out: dict[str, Any] = {"items": len(results)}
    if defects:
        out["detection"] = _rate(sum(r["outcome"] == "DETECTED" for r in defects), len(defects))
        out["detected_low_severity"] = sum(r["outcome"] == "DETECTED_LOW_SEVERITY" for r in defects)
        out["missed"] = [r["item_key"] for r in defects if r["outcome"] == "MISSED"]
    if clean:
        out["false_alarm"] = _rate(sum(r["outcome"] == "FALSE_ALARM" for r in clean), len(clean))
    if refs:
        out["reference_flagged"] = sum(r["outcome"] == "FLAGGED" for r in refs)
        out["reference_noted"] = sum(r["outcome"] == "NOTED" for r in refs)
        out["note"] = "conjunto de referência sem gabarito: achados precisam de revisão humana"
    return out
