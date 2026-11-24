"""Identificadores ULID (ordenáveis, estáveis, texto) sem dependência externa."""

import os
import time

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_id(prefix: str = "") -> str:
    ts = int(time.time() * 1000)
    rnd = int.from_bytes(os.urandom(10), "big")
    value = (ts << 80) | rnd
    chars = []
    for _ in range(26):
        chars.append(_ALPHABET[value & 31])
        value >>= 5
    ulid = "".join(reversed(chars))
    return f"{prefix}_{ulid}" if prefix else ulid
