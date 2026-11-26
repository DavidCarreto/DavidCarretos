"""Tira tokens, chaves e palavras-passe de mensagens de erro e registos antes de os mostrar ou enviar."""
from __future__ import annotations

import os
import re

_SECRET_KEYS = re.compile(r"TOKEN|SECRET|KEY|PASSWORD|PASS\b|CODE", re.I)
_PATTERNS = [
    (re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/=\-]+", re.I), r"\1[oculto]"),
    (re.compile(r"((?:access_token|refresh_token|client_secret|code|token)=)[^&\s\"']+", re.I), r"\1[oculto]"),
    (re.compile(r"(\"(?:access_token|refresh_token|client_secret)\"\s*:\s*\")[^\"]+", re.I), r"\1[oculto]"),
]


def redact(text: str) -> str:
    text = str(text or "")
    for k, v in os.environ.items():
        if v and len(v) >= 8 and _SECRET_KEYS.search(k) and v in text:
            text = text.replace(v, "[oculto]")
    for pat, rep in _PATTERNS:
        text = pat.sub(rep, text)
    return text
