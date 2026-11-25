import logging

from cardfactory.security.secrets import REDACTED, RedactingFilter, redact

KEY = "sk-or-v1-abcdefghijklmnopqrstuvwxyz012345"


def test_redact_patterns():
    assert KEY not in redact(f"erro com {KEY} no texto")
    assert redact("Authorization: Bearer abc.def") == f"Authorization: Bearer {REDACTED}"
    assert redact("sem segredo") == "sem segredo"
    assert redact("") == ""


def test_redact_env_key_even_without_pattern(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "custom-secret-value-123")
    assert "custom-secret-value-123" not in redact("vazou custom-secret-value-123")


def test_log_filter_redacts_args():
    rec = logging.LogRecord("x", logging.INFO, __file__, 1, "chave=%s", (KEY,), None)
    RedactingFilter().filter(rec)
    assert KEY not in rec.getMessage() and REDACTED in rec.getMessage()
