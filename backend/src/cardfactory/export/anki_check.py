"""Teste de importação em coleção Anki descartável (TEC-008; AMB-08).

Usa o pacote oficial `anki` (pylib) quando instalado; sem ele, o status é NOT_AVAILABLE e nunca se
alega importação testada. A coleção é criada numa pasta temporária e apagada ao final.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any

from cardfactory.export.tsv import Note


def available() -> bool:
    try:
        import anki.collection  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


def import_test(path: Path, notes: list[Note], *, media_dir: Path | None = None) -> dict[str, Any]:
    if not available():
        return {"status": "NOT_TESTED", "detail": "pacote 'anki' não instalado: importação não testada"}
    from anki.collection import Collection, ImportCsvRequest

    tmp = Path(tempfile.mkdtemp(prefix="cf_anki_"))
    col = None
    try:
        col = Collection(str(tmp / "descartavel.anki2"))
        md = col.get_csv_metadata(path=str(path), delimiter=None)
        col.import_csv(ImportCsvRequest(path=str(path), metadata=md))
        found = {}
        for nid in col.find_notes(""):
            n = col.get_note(nid)
            key = next((t[4:] for t in n.tags if t.startswith("cf::")), None)
            found[key] = (n, col.decks.name(n.cards()[0].did))
        problems = []
        for exp in notes:
            got = found.get(exp.card_key)
            if got is None:
                problems.append(f"{exp.card_key}: nota não encontrada após importação")
                continue
            n, deck = got
            if n.fields[0] != exp.front or n.fields[1] != exp.back:
                problems.append(f"{exp.card_key}: campos divergentes após importação")
            if deck != exp.deck:
                problems.append(f"{exp.card_key}: deck {deck!r} ≠ {exp.deck!r}")
            if exp.guid and n.guid != exp.guid:
                problems.append(f"{exp.card_key}: GUID alterado na importação")
            if set(n.tags) != set(exp.tags):
                problems.append(f"{exp.card_key}: tags divergentes")
        if len(found) != len(notes):
            problems.append(f"{len(found)} notas na coleção para {len(notes)} exportadas")
        return {"status": "FAILED" if problems else "PASSED", "detail": problems[:50],
                "notes_in_collection": len(found)}
    except Exception as e:  # noqa: BLE001
        return {"status": "FAILED", "detail": [f"erro na importação: {type(e).__name__}: {e}"]}
    finally:
        if col is not None:
            col.close()
        shutil.rmtree(tmp, ignore_errors=True)
