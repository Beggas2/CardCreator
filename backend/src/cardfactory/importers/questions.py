"""Importação de questões de prova (QST-001, QST-008).

Questões são separadas de forma determinística em PLANNING e EVALUATION; as de avaliação
nunca devem alimentar o planejamento (evita "estudar para a prova" e medir na mesma prova).
O gabarito importado é preliminar até conferência: não é autoridade médica (QST-004).
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import unicodedata
from typing import Any

from sqlalchemy import select

from cardfactory.db import Database
from cardfactory.db.models import ImportBatch, Question

FIELDS = ("exam_board", "year", "institution", "exam", "number", "stem", "options", "key_preliminary", "key_final",
          "annulled", "source")
ALIASES = {"banca": "exam_board", "ano": "year", "instituicao": "institution", "prova": "exam", "numero": "number",
           "enunciado": "stem", "alternativas": "options", "gabarito": "key_preliminary",
           "gabarito_preliminar": "key_preliminary", "gabarito_definitivo": "key_final", "anulada": "annulled",
           "fonte": "source"}


def _key(k: str) -> str:
    k = unicodedata.normalize("NFKD", k.strip().lower()).encode("ascii", "ignore").decode().replace(" ", "_")
    return ALIASES.get(k, k)


def _norm(t: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", t or "").split()).lower()


def _options(v: Any) -> dict[str, str]:
    if isinstance(v, dict):
        return {str(k).strip().upper(): str(x) for k, x in v.items()}
    if isinstance(v, list):
        return {chr(65 + i): str(x) for i, x in enumerate(v)}
    if isinstance(v, str) and v.strip():
        try:
            return _options(json.loads(v))
        except json.JSONDecodeError:
            parts = [p.strip() for p in v.split("||") if p.strip()]
            return {chr(65 + i): p for i, p in enumerate(parts)}
    return {}


def split_for(content_hash: str, evaluation_pct: int) -> str:
    return "EVALUATION" if int(content_hash[:8], 16) % 100 < evaluation_pct else "PLANNING"


def parse_questions(data: bytes, filename: str = "") -> list[dict[str, Any]]:
    text = data.decode("utf-8-sig")
    if filename.lower().endswith(".json") or text.lstrip().startswith(("[", "{")):
        raw = json.loads(text)
        items = raw if isinstance(raw, list) else raw.get("questions", [])
    else:
        sample = text[:4000]
        delim = ";" if sample.count(";") > sample.count(",") else ","
        items = list(csv.DictReader(io.StringIO(text), delimiter=delim))
    return [{_key(k): v for k, v in it.items() if k} for it in items]


def import_questions(db: Database, project_id: str, data: bytes, *, filename: str = "", author: str = "",
                     evaluation_pct: int = 20) -> dict[str, Any]:
    if not 0 <= evaluation_pct <= 90:
        raise ValueError("percentual de avaliação deve ficar entre 0 e 90")
    items = parse_questions(data, filename)
    created, duplicates, problems = 0, 0, []
    splits = {"PLANNING": 0, "EVALUATION": 0}
    with db.write() as s:
        batch = ImportBatch(project_id=project_id, kind="QUESTIONS", filename=filename,
                            content_hash=hashlib.sha256(data).hexdigest(), format_detected="json" if
                            filename.lower().endswith(".json") else "csv", created_by=author)
        s.add(batch)
        s.flush()
        for i, it in enumerate(items, start=1):
            opts = _options(it.get("options"))
            stem = (it.get("stem") or "").strip()
            if not stem and not it.get("number"):
                problems.append({"item": i, "problem": "sem enunciado nem número"})
                continue
            key_prelim = (str(it.get("key_preliminary") or "").strip().upper() or None)
            if key_prelim and opts and key_prelim not in opts:
                problems.append({"item": i, "problem": f"gabarito {key_prelim} não está entre as alternativas"})
            year = it.get("year")
            try:
                year = int(year) if year not in (None, "") else None
            except (TypeError, ValueError):
                problems.append({"item": i, "problem": f"ano inválido: {year}"})
                year = None
            ident = "|".join([_norm(str(it.get("exam_board") or "")), str(year or ""), _norm(str(it.get("exam") or "")),
                              _norm(str(it.get("number") or "")), _norm(stem), json.dumps(sorted(opts.items()))])
            h = hashlib.sha256(ident.encode()).hexdigest()
            exists = select(Question.id).where(Question.project_id == project_id, Question.content_hash == h)
            if s.execute(exists).first():
                duplicates += 1
                continue
            split = split_for(h, evaluation_pct)
            annulled = str(it.get("annulled") or "").strip().lower() in ("1", "true", "sim", "s", "yes")
            s.add(Question(project_id=project_id, import_batch_id=batch.id, exam_board=str(it.get("exam_board") or ""),
                           year=year, institution=str(it.get("institution") or ""), exam=str(it.get("exam") or ""),
                           number=str(it.get("number") or ""), stem=stem or None, options=opts,
                           key_preliminary=key_prelim,
                           key_final=(str(it.get("key_final") or "").strip().upper() or None), annulled=annulled,
                           source=str(it.get("source") or ""), split=split, content_hash=h))
            splits[split] += 1
            created += 1
        report = {"read": len(items), "created": created, "duplicates": duplicates, "problems": problems,
                  "splits": splits, "evaluation_pct": evaluation_pct,
                  "aviso": "Gabaritos importados são preliminares e não são autoridade médica."}
        batch.report = report
        return {"import_batch_id": batch.id, **report}
