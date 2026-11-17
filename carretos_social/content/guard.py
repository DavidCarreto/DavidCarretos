"""Termos proibidos nas legendas (config/brand.yaml → termos_proibidos).

- todas: fornecedores/sistemas internos e funcionalidades ainda não lançadas, em todas as marcas
  (deixam de ser bloqueados numa marca se estiverem nos factos dessa marca);
- por marca: ex. nas contas do David e da Carretos Group ("geral") não se usa o nome AURON.
Os links não contam (auron.carretos.pt/schedule é o endereço real e pode aparecer).
"""
from __future__ import annotations

import re

URL = re.compile(r"(https?://\S+|\b[\w-]+(\.[\w-]+)+(/\S*)?)", re.I)


def _terms(brand_id: str) -> tuple[list[str], list[str]]:
    from ..config import brand
    cfg = brand().get("termos_proibidos") or {}
    return list(cfg.get("todas") or []), list(cfg.get(brand_id) or [])


def found_terms(account_id: str, text: str) -> list[tuple[str, str]]:
    """[(termo, aviso)] dos termos proibidos presentes no texto (fora de links)."""
    from ..config import facts_brand
    from .ai import verified_facts
    if not text:
        return []
    brand_id = facts_brand(account_id)
    clean = URL.sub(" ", text)
    facts = " ".join(verified_facts(brand_id)).lower()
    everywhere, own = _terms(brand_id)
    out = []
    for t in own:
        if re.search(rf"(?<!\w){re.escape(t)}(?!\w)", clean, re.I):
            out.append((t, f"Nas contas da Carretos não se usa o nome {t}." if t.upper() == "AURON"
                        else f"Nestas contas não se usa \"{t}\"."))
    for t in everywhere:
        if t.lower() not in facts and re.search(rf"(?<!\w){re.escape(t)}(?!\w)", clean, re.I):
            out.append((t, f"Informação interna que não se publica: \"{t}\"."))
    return out


def sanitize(account_id: str, text: str) -> str:
    """Depois da IA: troca um termo proibido por [PREENCHER] (fica bloqueado até alguém reescrever)."""
    for term, _ in found_terms(account_id, text):
        hint = "descreva o benefício sem o nome" if term.upper() == "AURON" else "retire a informação interna"
        pattern = re.compile(rf"(?<![\w./]){re.escape(term)}(?![\w]|\.[a-z])", re.I)
        text = pattern.sub(f"[PREENCHER: {hint} {term}]", text)
    return text


def prompt_lines(brand_id: str) -> str:
    """Linhas para as instruções da IA."""
    everywhere, own = _terms(brand_id)
    lines = []
    if own:
        lines.append("- PALAVRAS PROIBIDAS nestas contas (nunca as escrevas, só podem aparecer dentro de um link): "
                     + ", ".join(own) + ". Em vez disso descreve o benefício.")
    if everywhere:
        lines.append("- Termos internos que nunca se publicam (salvo se estiverem nos factos): " + ", ".join(everywhere) + ".")
    return "\n".join(lines)
