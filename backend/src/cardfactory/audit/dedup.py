"""Deduplicação em camadas (DED-002..005): hash, normalização, lexical, objetivo e números conflitantes.

Só gera candidatos. Nunca exclui nada (DED-003); a classificação da relação é da IA ou do humano.
Escopo: toda a coleção do projeto, inclusive outros subdecks.
"""

from __future__ import annotations

import hashlib
import re
from itertools import combinations
from typing import Any

from sqlalchemy import select

from cardfactory.audit.service import card_claim_ids, latest_version
from cardfactory.audit.text import normalized
from cardfactory.db import Database
from cardfactory.db.models import Card, Claim, SimilarityPair

JACCARD_CANDIDATE = 0.4
STOP = {"qual", "quais", "que", "com", "para", "por", "uma", "dos", "das", "nos", "nas", "como", "quando", "sobre",
        "entre", "mais", "menos", "ser", "são", "não", "sem", "seu", "sua", "pela", "pelo", "este", "esta", "isso"}


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"\w+", text) if len(w) > 2 and w not in STOP}


def candidates(db: Database, project_id: str, focus_card_ids: list[str] | None = None) -> list[dict[str, Any]]:
    with db.session() as s:
        cards = list(s.execute(select(Card).where(Card.project_id == project_id,
                                                  Card.state.not_in(["REJECTED"]))).scalars())
        info = {}
        for c in cards:
            v = latest_version(s, c.id)
            norm = normalized(v.content)
            objs = v.content.get("objective_ids", []) if isinstance(v.content.get("objective_ids"), list) else []
            claims = list(s.execute(select(Claim).where(Claim.id.in_(card_claim_ids(s, v)))).scalars())
            info[c.id] = {"hash": hashlib.sha256(norm.encode()).hexdigest(), "tokens": _tokens(norm),
                          "objective": objs[0] if objs else None,
                          "numeric": [(cl.entity_id, cl.component, cl.population.strip().lower(), cl.numeric)
                                      for cl in claims if cl.numeric]}
    focus = set(focus_card_ids) if focus_card_ids else None
    out = []
    for a, b in combinations(sorted(info), 2):
        if focus is not None and a not in focus and b not in focus:
            continue
        ia, ib = info[a], info[b]
        if ia["hash"] == ib["hash"]:
            out.append({"a": a, "b": b, "layer": "NORMALIZED", "score": "1.00"})
            continue
        union = ia["tokens"] | ib["tokens"]
        jac = len(ia["tokens"] & ib["tokens"]) / len(union) if union else 0
        if jac >= JACCARD_CANDIDATE:
            out.append({"a": a, "b": b, "layer": "LEXICAL", "score": f"{jac:.2f}"})
            continue
        conflict = [(x, y) for x in ia["numeric"] for y in ib["numeric"]
                    if x[1] == y[1] and x[0] and x[0] == y[0] and x[3].get("unit") == y[3].get("unit")
                    and x[3].get("value") != y[3].get("value")]
        if conflict:  # DED-004: mesma entidade e componente, números diferentes (população vai para a IA, DED-005)
            out.append({"a": a, "b": b, "layer": "NUMERIC", "score": ""})
            continue
        if ia["objective"] and ia["objective"] == ib["objective"]:
            out.append({"a": a, "b": b, "layer": "OBJECTIVE", "score": ""})
    return out


def store(db: Database, project_id: str, cands: list[dict[str, Any]]) -> list[str]:
    ids = []
    with db.write() as s:
        for c in cands:
            p = s.execute(select(SimilarityPair).where(SimilarityPair.card_a_id == c["a"],
                                                       SimilarityPair.card_b_id == c["b"])).scalar_one_or_none()
            if p is None:
                p = SimilarityPair(project_id=project_id, card_a_id=c["a"], card_b_id=c["b"], layer=c["layer"],
                                   score=c["score"])
                s.add(p)
                s.flush()
            ids.append(p.id)
    return ids
