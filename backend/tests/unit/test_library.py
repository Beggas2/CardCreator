import pytest
from sqlalchemy import select

from cardfactory.db.models import DocumentEvent
from cardfactory.library.parsing import parse_html, parse_pdf, parse_text
from cardfactory.library.service import (
    EvidenceNotFoundError,
    Library,
    LibraryError,
    fts_query,
    locate_quote,
)
from tests.pdfgen import make_pdf

HTML = """<html><head><title>PCDT Hipertensão Arterial</title><script>alert(1)</script></head><body>
<nav>menu</nav>
<h1>Hipertensão</h1><p>Introdução ao tema.</p>
<h2>4 Tratamento</h2><p>Iniciar tratamento farmacológico quando PA ≥ 140/90 mmHg
em adultos com risco cardiovascular alto.</p><p>Nota de rodapé: valores em consultório.</p>
<h3>4.1 Doses</h3>
<table><tr><th>Fármaco</th><th>Dose</th></tr><tr><td>Losartana</td><td>50 mg/dia</td></tr></table>
<table><tr><td colspan=2>Mesclada</td></tr><tr><td>a</td><td>b</td></tr><tr><td>c</td></tr></table>
</body></html>"""


@pytest.fixture
def lib(db, tmp_path) -> Library:
    return Library(db, tmp_path / "blobs")


def _doc(lib: Library, **kw) -> str:
    sid = lib.add_source(title_claimed="PCDT HAS", institution="Ministério da Saúde", source_tier="BR_OFFICIAL")
    vid = lib.add_version(sid, published_at="2025-03", validity_status="CURRENT", **kw)
    return lib.register_found(vid, "https://example.gov.br/pcdt.html")


def test_parse_html_sections_and_tables():
    r = parse_html(HTML)
    assert r.title == "PCDT Hipertensão Arterial"
    paths = [s.path for s in r.sections]
    assert "Hipertensão > 4 Tratamento" in paths
    assert "Hipertensão > 4 Tratamento > 4.1 Doses > Tabela" in paths
    trat = next(s for s in r.sections if s.path == "Hipertensão > 4 Tratamento")
    assert "≥ 140/90 mmHg" in trat.text and "rodapé" in trat.text  # condições e rodapé preservados
    assert all("alert" not in s.text and "menu" not in s.text for s in r.sections)
    table = next(s for s in r.sections if s.kind == "TABLE" and s.parse_quality == "OK")
    assert "Losartana | 50 mg/dia" in table.text
    assert any(s.kind == "TABLE" and s.parse_quality == "UNCERTAIN" for s in r.sections)
    assert not r.complete


def test_parse_text_headings_and_long_split():
    long = "\n\n".join(f"Parágrafo {i} " + "x" * 500 for i in range(30))
    r = parse_text(f"# Título\nabc\n\n2.1 Diagnóstico clínico\n{long}")
    assert r.sections[0].path == "Título"
    parts = [s for s in r.sections if s.path.startswith("2.1 Diagnóstico")]
    assert len(parts) > 1 and all(len(s.text) <= 6000 for s in parts)
    assert "".join(s.text for s in parts).count("Parágrafo") == 30


def test_parse_pdf_text_and_scanned_page():
    pdf = make_pdf(["Tratamento: amoxicilina 50 mg/kg/dia dividido de 8/8 h por 10 dias.", ""])
    r = parse_pdf(pdf)
    assert r.pages == 2
    assert "50 mg/kg/dia" in r.sections[0].text and r.sections[0].page_from == 1
    assert r.sections[1].parse_quality == "FAILED" and "OCR pendente" in r.warnings[0]


def test_parse_pdf_garbage():
    assert parse_pdf(b"%PDF-1.4 lixo").sections == []


def test_ingest_states_and_events(lib, db):
    doc = _doc(lib)
    res = lib.ingest(doc, HTML.encode(), declared_mime="text/html; charset=utf-8")
    assert res.state == "PARTIALLY_READ" and res.warnings  # tabela irregular → leitura parcial
    with db.session() as s:
        ev = [(e.from_state, e.to_state) for e in s.execute(select(DocumentEvent)).scalars()]
    assert ev == [("", "FOUND"), ("FOUND", "PARTIALLY_READ")]
    src = lib.list_sources()[0]
    assert src["title_confirmed"] == "PCDT Hipertensão Arterial"
    with pytest.raises(LibraryError):
        lib.ingest(doc, b"outra coisa")  # conteúdo novo exige nova versão


def test_complete_text_is_retrieved_and_dedup_reported(lib):
    d1, d2 = _doc(lib), _doc(lib)
    assert lib.ingest(d1, b"# A\ntexto completo").state == "RETRIEVED"
    assert lib.ingest(d2, b"# A\ntexto completo").duplicate_of == d1


def test_invalid_transitions(lib):
    doc = _doc(lib)
    with pytest.raises(LibraryError):
        lib.set_state(doc, "VERIFIED", "t", "sem leitura")
    lib.mark_unavailable(doc, "paywall")
    assert lib.list_sources()[0]["versions"][0]["documents"][0]["pending_reason"] == "paywall"
    with pytest.raises(LibraryError):
        lib.set_state(doc, "OUTDATED", "t", "x")


def test_dates_validated_and_superseded(lib):
    sid = lib.add_source(title_claimed="Diretriz")
    with pytest.raises(LibraryError):
        lib.add_version(sid, published_at="março de 2020")
    v1 = lib.add_version(sid, published_at="2020", validity_status="CURRENT")
    lib.add_version(sid, published_at="2024-05-01", validity_status="CURRENT", supersedes_version_id=v1)
    vs = lib.list_sources()[0]["versions"]
    assert [v["validity_status"] for v in vs] == ["SUPERSEDED", "CURRENT"]


def test_evidence_must_exist_literally(lib):
    doc = _doc(lib)
    lib.ingest(doc, HTML.encode())
    sec = next(s for s in lib.sections(doc) if s["path"].endswith("4 Tratamento"))
    ev = lib.add_evidence(sec["id"], "PA ≥ 140/90 mmHg em adultos")  # quebra de linha no original
    e = lib.evidence(ev)
    assert e["quote"].startswith("PA ≥ 140/90 mmHg") and "\n" in e["quote"]
    assert e["tier"] == "BR_OFFICIAL" and e["validity"] == "CURRENT"
    with pytest.raises(EvidenceNotFoundError):
        lib.add_evidence(sec["id"], "PA ≥ 130/80 mmHg")  # número alterado não é aceito
    with pytest.raises(LibraryError):
        lib.add_evidence(sec["id"], "x" * 2000)


def test_evidence_requires_read_document(lib):
    doc = _doc(lib)
    lib.ingest(doc, b"# A\nlinha um")
    sec = lib.sections(doc)[0]["id"]
    lib.set_state(doc, "VERIFIED", "revisor", "conferido")
    assert lib.add_evidence(sec, "linha um")


def test_search_with_filters_and_accents(lib):
    doc = _doc(lib)
    lib.ingest(doc, HTML.encode())
    hits = lib.search("hipertensao tratamento")  # sem acento encontra com acento
    assert hits and hits[0]["title"] == "PCDT Hipertensão Arterial"
    assert "[" in hits[0]["snip"]
    assert lib.search("losartana", tier="BR_OFFICIAL", year="2025")
    assert lib.search("losartana", tier="INTL_SOCIETY") == []
    assert lib.search('"; DROP TABLE source; --') == []
    assert lib.search("") == []


def test_fts_query_quoting():
    assert fts_query('dose "máxima" OR x') == '"dose" "máxima" "OR" "x"'


def test_locate_quote_whitespace():
    assert locate_quote("a  b\nc", "a b c") == (0, 6)
    assert locate_quote("abc", "") is None
