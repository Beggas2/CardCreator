"""Acesso a segredos e redação de logs (SEC-001). A chave nunca sai deste módulo em texto claro."""

from __future__ import annotations

import logging
import os
import re

KEY_ENV = "OPENROUTER_API_KEY"
_KEYRING_SERVICE = "cardfactory"
_PATTERNS = [
    re.compile(r"sk-or-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"(?i)(authorization:\s*bearer\s+)[^\s\"']+"),
]
REDACTED = "[REDACTED]"


def auth_via_proxy() -> bool:
    """A chave é injetada por um proxy de saída (ex.: segredo de rede do ambiente); o app nunca a vê."""
    return os.environ.get("OPENROUTER_AUTH_VIA_PROXY") == "1"


def get_api_key(name: str = KEY_ENV) -> str | None:
    value = os.environ.get(name)
    if value:
        return value
    try:  # opcional: Windows Credential Manager / keychain
        import keyring  # type: ignore[import-not-found]

        return keyring.get_password(_KEYRING_SERVICE, name)
    except Exception:  # noqa: BLE001
        return None


def redact(text: str) -> str:
    if not text:
        return text
    key = os.environ.get(KEY_ENV)
    if key and len(key) >= 8:
        text = text.replace(key, REDACTED)
    for pat in _PATTERNS:
        text = pat.sub(lambda m: (m.group(1) if m.groups() else "") + REDACTED, text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001
            return True
        record.msg = redact(msg)
        record.args = ()
        return True


def install_log_redaction() -> None:
    root = logging.getLogger()
    f = RedactingFilter()
    root.addFilter(f)
    for h in root.handlers:
        h.addFilter(f)
