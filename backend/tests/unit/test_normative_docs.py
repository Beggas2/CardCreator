"""PRM-001: documentos normativos preservados byte a byte."""

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
NORMATIVE = ROOT / "docs" / "normative"


def test_normative_docs_hash():
    sums = (NORMATIVE / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    assert len(sums) == 2
    for line in sums:
        expected, name = line.split("  ", 1)
        actual = hashlib.sha256((NORMATIVE / name).read_bytes()).hexdigest()
        assert actual == expected, f"{name} foi alterado"


def test_normative_docs_keep_crlf():
    for name in ("Prompt Criação.txt", "Prompt Revisor.txt"):
        assert b"\r\n" in (NORMATIVE / name).read_bytes()
