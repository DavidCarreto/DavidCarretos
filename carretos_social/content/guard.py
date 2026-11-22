"""Palavras que não podem aparecer nas legendas (fora de links). Vêm da base de conhecimento:
  - "Palavras proibidas" de cada marca (ex.: AURON nas contas do David e da Carretos Group);
  - palavras das fichas "interno" e "em desenvolvimento" (ex.: OfficeGest, Carretos Care).
Os links não contam (auron.carretos.pt/schedule é o endereço real e pode aparecer).
"""
from __future__ import annotations

import re

URL = re.compile(r"(https?://\S+|\b[\w-]+(\.[\w-]+)+(/\S*)?)", re.I)


def found_terms(account_id: str, text: str) -> list[tuple[str, str]]:
    """[(palavra, aviso)] das palavras proibidas presentes no texto (fora de links)."""
    from .. import knowledge
    from ..config import facts_brand
    if not text:
        return []
    clean = URL.sub(" ", text)
    out, seen = [], set()
    for term, warning in knowledge.blocked_terms(facts_brand(account_id), account_id):
        if term.lower() in seen:
            continue
        if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", clean, re.I):
            out.append((term, warning))
            seen.add(term.lower())
    return out


def sanitize(account_id: str, text: str) -> str:
    """Depois da IA: troca uma palavra proibida por [PREENCHER] (fica bloqueado até alguém reescrever)."""
    for term, _ in found_terms(account_id, text):
        hint = "descreva o benefício sem o nome" if term.upper() == "AURON" else "retire"
        pattern = re.compile(rf"(?<![\w./]){re.escape(term)}(?![\w]|\.[a-z])", re.I)
        text = pattern.sub(f"[PREENCHER: {hint} {term}]", text)
    return text
