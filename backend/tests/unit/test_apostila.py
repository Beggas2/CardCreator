"""Apostila em PDF: recorte de páginas, figuras com legenda, marca d'água e figura ligada ao card."""

import copy
import io
import random
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import select

from cardfactory.cards.samples import SAMPLES
from cardfactory.cards.service import CardService
from cardfactory.db.models import CardVersion, MediaAsset, Project
from cardfactory.library.apostila import (
    ApostilaError,
    _captions,
    extract_figures,
    import_apostila,
    parse_pages,
    subset_pdf,
)
from cardfactory.library.parsing import _repeated_lines
from cardfactory.library.service import Library


def _pdf(n: int) -> bytes:
    # Ruído: imagens que não comprimem a quase nada (ícones minúsculos são descartados de propósito).
    pages = [Image.frombytes("RGB", (400, 300), random.Random(i).randbytes(400 * 300 * 3)) for i in range(n)]
    buf = io.BytesIO()
    pages[0].save(buf, format="PDF", save_all=True, append_images=pages[1:])
    return buf.getvalue()


def test_parse_pages_and_subset():
    assert parse_pages("2-3,5", 6) == [2, 3, 5]
    with pytest.raises(ApostilaError):
        parse_pages("5-9", 6)
    sub, pages = subset_pdf(_pdf(6), "2-3")
    assert pages == [2, 3] and sub.startswith(b"%PDF")


def test_captions_only_at_line_start():
    text = "O túnel (Figura 73) é típico.\nFIG. 73: Túnel (burrow).\nFIGURA 74 - Lesão abdominal"
    assert _captions(text) == [("73", "Túnel (burrow)."), ("74", "Lesão abdominal")]


def test_figures_keep_original_page_and_skip_repeated(tmp_path: Path):
    sub, pages = subset_pdf(_pdf(4), "2-4")
    figs = extract_figures(sub, tmp_path, prefix="apt", original_pages=pages)
    assert [f.page for f in figs] == [2, 3, 4]
    assert all((tmp_path / f.file).is_file() for f in figs)


def test_repeated_lines_removed():
    pages = [f"usuario@exemplo.com | canal\nconteúdo {i}" for i in range(4)]
    assert _repeated_lines(pages) == {"usuario@exemplo.com | canal"}
    assert _repeated_lines(pages[:2]) == set()


def test_import_apostila_registers_secondary_source(db, tmp_path: Path):
    lib = Library(db, tmp_path / "blobs")
    with pytest.raises(ApostilaError):
        import_apostila(lib, tmp_path / "media", _pdf(3), pages="7-8", title="Apostila")
    out = import_apostila(lib, tmp_path / "media", _pdf(3), pages="2-3", title="Apostila DER", year="2024")
    assert len(out["figures"]) == 2 and out["figures"][0]["page"] == 2
    src = lib.list_sources()[0]
    assert src["source_tier"] == "SECONDARY_CLINICAL"


def test_card_uses_apostila_figure_only_when_file_exists(db, tmp_path: Path):
    with db.write() as s:
        p = Project(name="p")
        s.add(p)
        s.flush()
        pid = p.id
    media = tmp_path / "media"
    media.mkdir()
    (media / "apt_p112_abc.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    cs = CardService(db, media)
    card = copy.deepcopy(SAMPLES["direct"])
    card["media_requests"] = [
        {"finding": "túnel escabiótico", "desired_source": "figura:apt_p112_abc.png", "purpose": "reconhecer"},
        {"finding": "nódulo", "desired_source": "figura:../segredo.png", "purpose": "reconhecer"},
        {"finding": "crostas", "desired_source": "atlas", "purpose": "reconhecer"}]
    cid = cs.create(pid, card)
    with db.session() as s:
        v = s.execute(select(CardVersion).where(CardVersion.card_id == cid)).scalar_one()
        assert v.content["images"] == [{"file": "apt_p112_abc.png", "alt": "túnel escabiótico", "side": "back"}]
        assets = {m.finding: m.status for m in s.execute(select(MediaAsset)).scalars()}
    assert assets == {"túnel escabiótico": "OBTAINED", "nódulo": "PENDING", "crostas": "PENDING"}
