import json

import pytest
from sqlalchemy import select

from cardfactory.db.models import Card, CardVersion, Project, Question
from cardfactory.importers.anki import AnkiImporter, parse_export
from cardfactory.importers.questions import import_questions, split_for

EXPORT = (
    "#separator:tab\n#html:true\n#guid column:1\n#notetype column:2\n#deck column:3\n#tags column:6\n"
    "g1\tBasic\tIGOR::Cardio\t<b>Qual</b> a dose?\t50 mg\tcardio has\n"
    "g2\tBasic\tIGOR::Cardio\t\"Frente com\ttab e \"\"aspas\"\"\"\tVerso\t\n"
    "g3\tBasic\tIGOR::Cardio\tFrente <script>x</script>\tVerso\t\n"
    "g4\tBasic\tIGOR::Cardio\tSó frente\n"
    "g1\tBasic\tIGOR::Cardio\tOutra\tnota\t\n"
    "\tBasic\tIGOR::Neuro\tSem guid\tVerso <img src=\"a.png\">\t\n"
)


@pytest.fixture
def project(db) -> str:
    with db.write() as s:
        p = Project(name="p")
        s.add(p)
        s.flush()
        return p.id


def test_parse_export_reports_every_problem():
    p = parse_export(EXPORT.encode())
    assert p.format_detected == "anki-guid" and p.separator == "\t" and len(p.rows) == 6
    r = {(row.line, row.guid): row for row in p.rows}
    assert r[(8, "g2")].fields[0] == 'Frente com\ttab e "aspas"'
    assert "HTML perigoso" in " ".join(r[(9, "g3")].problems)
    assert any("colunas" in x for x in r[(10, "g4")].problems)
    assert "GUID repetido no arquivo" in r[(7, "g1")].problems
    assert "GUID vazio" in r[(12, "")].problems
    assert r[(7, "g1")].tags == ["cardio", "has"]


def test_import_creates_cards_preserving_guid_and_quarantining(db, project):
    rep = AnkiImporter(db).import_export(project, EXPORT.encode(), filename="cardio.txt", author="Tassiane")
    assert rep["notes_read"] == 6 and rep["created"] == 6 and rep["problem_rows_total"] == 5
    with db.session() as s:
        cards = list(s.execute(select(Card)).scalars())
    assert sorted(c.anki_guid for c in cards if c.anki_guid) == ["g2", "g3", "g4"]
    assert sum(c.quarantine for c in cards) == 5
    assert all(c.origin == "IMPORTED" for c in cards)


def test_reimport_versions_only_changed_notes(db, project):
    imp = AnkiImporter(db)
    base = "#separator:tab\n#guid column:1\n#deck column:2\ng1\tD\tF1\tV1\ng2\tD\tF2\tV2\n"
    imp.import_export(project, base.encode())
    rep = imp.import_export(project, base.replace("V2", "V2 corrigido").encode())
    assert (rep["created"], rep["updated"], rep["unchanged"]) == (0, 1, 1)
    with db.session() as s:
        c = s.execute(select(Card).where(Card.anki_guid == "g2")).scalar_one()
        vs = list(s.execute(select(CardVersion).where(CardVersion.card_id == c.id)).scalars())
    assert sorted(v.version_no for v in vs) == [1, 2]


def test_import_without_headers_and_semicolon():
    p = parse_export("Frente;Verso\nA;B\n".encode("cp1252"))
    assert p.separator == ";" and p.format_detected == "texto-delimitado" and len(p.rows) == 2


def test_import_non_utf8_reported():
    p = parse_export("#separator:tab\nCoração\tVálvula\n".encode("cp1252"))
    assert p.rows[0].fields[0] == "Coração" and "Windows-1252" in p.problems[0]


QUESTIONS = [
    {"banca": "X", "ano": "2024", "prova": "R1", "numero": "1", "enunciado": "Qual a conduta?",
     "alternativas": ["a", "b", "c", "d"], "gabarito": "B"},
    {"banca": "X", "ano": "2024", "prova": "R1", "numero": "2", "enunciado": "Outra?",
     "alternativas": {"A": "1", "B": "2"}, "gabarito": "E"},
    {"banca": "X", "ano": "abc", "prova": "R1", "numero": "3", "enunciado": "Terceira?"},
    {"banca": "X"},
]


def test_import_questions_json(db, project):
    data = json.dumps(QUESTIONS).encode()
    rep = import_questions(db, project, data, filename="q.json")
    assert rep["read"] == 4 and rep["created"] == 3
    assert {p["problem"].split(":")[0] for p in rep["problems"]} >= {"gabarito E não está entre as alternativas",
                                                                       "ano inválido", "sem enunciado nem número"}
    assert import_questions(db, project, data, filename="q.json")["duplicates"] == 3
    with db.session() as s:
        q1 = s.execute(select(Question).where(Question.number == "1")).scalar_one()
    assert q1.options == {"A": "a", "B": "b", "C": "c", "D": "d"} and q1.key_final is None


def test_import_questions_csv_aliases(db, project):
    csv_data = "Banca;Ano;Número;Enunciado;Alternativas;Gabarito;Anulada\nY;2023;7;Pergunta?;a||b;A;sim\n"
    rep = import_questions(db, project, csv_data.encode(), filename="q.csv")
    assert rep["created"] == 1
    with db.session() as s:
        q = s.execute(select(Question)).scalar_one()
    assert q.annulled and q.options == {"A": "a", "B": "b"} and q.year == 2023


def test_split_is_deterministic_and_proportional():
    import hashlib
    hs = [hashlib.sha256(str(i).encode()).hexdigest() for i in range(2000)]
    ev = sum(split_for(h, 20) == "EVALUATION" for h in hs)
    assert 300 < ev < 500
    assert [split_for(h, 20) for h in hs[:50]] == [split_for(h, 20) for h in hs[:50]]
