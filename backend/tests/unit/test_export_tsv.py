"""Serializadores, round-trip e validador de arquivo (TEC-003..007, TEC-011) + regressões técnicas do C§40."""

import csv
import io

import pytest

from cardfactory.export.tsv import Note, SerializationError, anki_guid, parse, round_trip, serialize, validate_file
from cardfactory.validation.html import validate_field


def note(i=1, front="Qual?", back="<div>Resposta</div>", guid="", tags=("t",), deck="IGOR::A::B", notetype="Basic"):
    return Note(f"ck_{i}", guid, notetype, deck, front, back, tuple(tags))


CORPUS = [
    note(1, "Qual a relação entre <b>A</b> &amp; B?", "<span style='color:#FCD34D'>&lt; 90 &gt; 60</span>"),
    note(2, 'Paciente diz "dor"; qual a conduta?', "Usar \"aspas\" e ; ponto e vírgula"),
    note(3, "Ação — ç, ã, é, 中文, µg/kg/min?", "≥ 1 mm; ≤ 2; ± 3"),
    note(4, "Entidade &nbsp; e &#x27; aspas simples?", "<div style='margin-top:0.8em'>bloco</div>", guid="Ab#1,x"),
]


def test_tsv_headers_no_bom_one_line_per_note():
    data = serialize("anki_tsv_v2", CORPUS)
    assert not data.startswith(b"\xef\xbb\xbf")
    text = data.decode()
    assert text.split("\n")[:6] == ["#separator:tab", "#html:true", "#guid column:1", "#notetype column:2",
                                    "#deck column:3", "#tags column:6"]
    assert len([ln for ln in text.split("\n")[6:] if ln]) == len(CORPUS)
    assert "\r" not in text


def test_round_trip_corpus():
    for fmt in ("anki_tsv_v2",):
        data = serialize(fmt, CORPUS)
        assert round_trip(data, fmt, CORPUS) == []
    simple = [n for n in CORPUS if not n.guid]
    for fmt in ("anki_tsv_noguid", "anki_simple"):
        data = serialize(fmt, simple)
        assert round_trip(data, fmt, simple) == []


def test_round_trip_detects_corruption():
    data = serialize("anki_tsv_v2", CORPUS)
    broken = data.replace(b"Resposta", b"Respost")
    assert round_trip(data.replace(b"\xc3\xa7", b"c"), "anki_tsv_v2", CORPUS)
    assert round_trip(broken, "anki_tsv_v2", [*CORPUS, note(9)])  # contagem


def test_physical_characters_rejected():
    for bad in ("a\tb", "a\nb", "a\rb"):
        with pytest.raises(SerializationError):
            serialize("anki_tsv_v2", [note(front=bad)])


def test_tsv_no_guid_format():
    data = serialize("anki_tsv_noguid", [note(notetype="Básico")]).decode()
    assert data.startswith("#separator:tab\n#html:true\n#notetype:Básico\n#deck column:3\n#tags column:4\n")
    with pytest.raises(SerializationError):
        serialize("anki_tsv_noguid", [note(guid="abc")])
    with pytest.raises(SerializationError):
        serialize("anki_tsv_noguid", [note(1), note(2, notetype="Outro")])


def test_simple_format_semicolon():
    n = note(front="A; B &amp; C?", back="x;y")
    data = serialize("anki_simple", [n])
    assert data.decode().startswith("#separator:semicolon\n#html:true\n")
    rows = parse(data, "anki_simple").rows
    assert rows[0][1] == ["A; B &amp; C?", "x;y"]
    with pytest.raises(SerializationError):
        serialize("anki_simple", [note(guid="g")])  # nunca para notas com identidade


def test_anki_guid_format():
    gs = {anki_guid() for _ in range(200)}
    assert len(gs) == 200 and all(1 <= len(g) <= 10 and not any(c.isspace() for c in g) for g in gs)


def test_validate_file_blocking_errors():
    ok = serialize("anki_tsv_v2", CORPUS[:3])
    assert validate_file(ok, "anki_tsv_v2")["errors"] == []
    assert any("BOM" in e for e in validate_file(b"\xef\xbb\xbf" + ok, "anki_tsv_v2")["errors"])
    assert any("cabeçalho" in e for e in validate_file(ok.replace(b"#tags column:6", b"#tags column:5"),
                                                        "anki_tsv_v2")["errors"])
    dup = serialize("anki_tsv_v2", [note(1, guid="g1"), note(2, guid="g1")])
    assert any("duplicado" in e for e in validate_file(dup, "anki_tsv_v2")["errors"])
    bad_deck = serialize("anki_tsv_v2", [note(deck="Outro::X")])
    assert any("deck" in e for e in validate_file(bad_deck, "anki_tsv_v2")["errors"])
    assert any("desconhecido" in e for e in validate_file(ok, "anki_tsv_v2", notetypes={"Cloze"})["errors"])
    upd = serialize("anki_tsv_v2", [note(guid="zz")])
    assert any("coleção" in e for e in validate_file(upd, "anki_tsv_v2", existing_guids={"aa"})["errors"])


# ---------------------------------------------------------------- regressões técnicas C§40 (1–9)
def test_reg_C01_html_entities():
    n = note(back="&lt;b&gt; não é tag; &amp; é e-comercial")
    data = serialize("anki_tsv_v2", [n])
    assert round_trip(data, "anki_tsv_v2", [n]) == []
    assert "&lt;b&gt;" in parse(data, "anki_tsv_v2").rows[0][1][4]


def test_reg_C02_double_quotes_do_not_truncate():
    n = note(front='"Começa com aspas" e tem "mais"?', back='fim com aspas"')
    data = serialize("anki_tsv_v2", [n])
    assert parse(data, "anki_tsv_v2").rows[0][1][3:5] == [n.front, n.back]


def test_reg_C03_no_ghost_notes_from_delimiters():
    n = note(front="a;b,c|d?", back="x y")  # separador de linha unicode não vira quebra física no TSV
    data = serialize("anki_tsv_v2", [n])
    assert len(parse(data, "anki_tsv_v2").rows) == 1


def test_reg_C04_comparison_chars_not_html():
    from cardfactory.cards.model import block, seg
    from cardfactory.cards.samples import SAMPLES
    from cardfactory.render.renderer import render
    c = dict(SAMPLES["direct"], answer=[block("essential", "paragraph", [[seg("<3 e >5 e a<b", "value", True)]])])
    back = render(c).back
    assert "&lt;3 e &gt;5 e a&lt;b" in back and validate_field(back).errors == []


def test_reg_C05_bom_detected():
    data = b"\xef\xbb\xbf" + serialize("anki_tsv_v2", [note()])
    assert any("BOM" in e for e in validate_file(data, "anki_tsv_v2")["errors"])


def test_reg_C06_color_outside_palette():
    assert validate_field("<span style='color:#22C55E'>verde</span>").errors
    assert validate_field("<span style='color:green'>verde</span>").errors
    assert validate_field("<span style='color:#7DD3FC'>ok</span>").errors == []


def test_reg_C07_guid_reuse_blocked():
    data = serialize("anki_tsv_v2", [note(1, guid="same"), note(2, guid="same")])
    assert any("duplicado" in e for e in validate_file(data, "anki_tsv_v2")["errors"])


def test_reg_C08_column_count():
    buf = io.StringIO()
    csv.writer(buf, delimiter="\t", lineterminator="\n").writerow(["g", "Basic", "IGOR::A", "f", "b"])
    data = ("#separator:tab\n#html:true\n#guid column:1\n#notetype column:2\n#deck column:3\n#tags column:6\n"
            + buf.getvalue()).encode()
    assert any("5 campos" in e for e in validate_file(data, "anki_tsv_v2")["errors"])


def test_reg_C09_html_unclosed_or_misnested():
    assert validate_field("<div><span>x</div></span>").errors
    assert validate_field("<div>x").errors
    assert validate_field("<ul><li>a</li></ul><br><hr><img src='a.png'>").errors == []


def test_forbidden_css_and_scripts():
    for bad in ("<div style='background:#101114'>x</div>", "<div style='box-shadow:0 0 1px #000000'>x</div>",
                "<div style='text-align:justify'>x</div>", "<div onclick='x()'>x</div>",
                "<script>x</script>", "<iframe src='x'></iframe>", "<img src='https://a/b.png'>",
                "<img src='data:image/png;base64,AA'>", "<div style='background-image:url(x)'>x</div>",
                "<a href='javascript:x'>x</a>"):
        assert validate_field(bad).errors, bad


def test_auto_labels_and_emoji_warn():
    rep = validate_field("<div>Resposta:</div><div>ok 🚀</div>")
    assert {f.code for f in rep.findings} >= {"AUTO_LABEL", "EMOJI"} and rep.errors == []
