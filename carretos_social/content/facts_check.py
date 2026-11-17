"""Análise da lista de factos: em que legendas cada facto está a ser usado e contradições com as contas."""
from __future__ import annotations

import re

GENERIC = {"o", "a", "os", "as", "contas", "conta", "instagram", "tiktok", "linkedin", "facebook", "whatsapp",
           "david", "carreto", "carretos", "group", "mercedes", "mercedes-benz", "benz", "para", "link", "dono",
           "empresa", "principal", "clips"}
PLATFORMS = {"instagram": "instagram", "tiktok": "tiktok", "linkedin": "linkedin", "facebook": "facebook"}


def keys_of(fact: str) -> list[str]:
    """Partes distintivas de um facto (para procurar nas legendas): @contas, telefones, números com
    palavra (ex.: '5 oficinas') e nomes próprios (ex.: localidades)."""
    keys = set(h.lower() for h in re.findall(r"@[\w.]*\w", fact))
    keys |= {re.sub(r"\D", "", p) for p in re.findall(r"\b\d[\d ]{7,}\d\b", fact)}
    keys |= {m.lower() for m in re.findall(r"\b\d+\s+[a-zà-ú]{4,}", fact)}
    for i, w in enumerate(re.findall(r"\b[A-ZÀ-Ú][\wÀ-ú-]{3,}\b", fact)):
        if w.lower() not in GENERIC:
            keys.add(w.lower())
    return sorted(k for k in keys if k)


def usage(facts: list[str], captions: list[str]) -> list[dict]:
    low = [c.lower() for c in captions]
    digits = [re.sub(r"\D", "", c) for c in captions]
    out = []
    for f in facts:
        ks = keys_of(f)
        n = 0
        for c, d in zip(low, digits):
            if any((k in d) if k.isdigit() else (k in c) for k in ks):
                n += 1
        out.append({"fact": f, "terms": ks, "used": n})
    return out


def contradictions(facts: list[str], accounts: dict) -> list[str]:
    """Ex.: o facto diz 'Instagram @davidcarreto' mas a conta de Instagram configurada é 'davidcarretos'."""
    by_platform: dict[str, set[str]] = {}
    for acc in accounts.values():
        if acc.handle:
            base = next((v for k, v in PLATFORMS.items() if acc.platform.startswith(k)), acc.platform)
            by_platform.setdefault(base, set()).add(acc.handle.lower().lstrip("@"))
    import difflib
    warnings = []
    for f in facts:
        # segmentos "Instagram @a e @b; TikTok …": cada @conta fica com a última rede nomeada antes dela
        current = None
        for tok in re.findall(r"[A-Za-zÀ-ú]+|@[\w.]*\w", f):
            low = tok.lower()
            if low in PLATFORMS:
                current = PLATFORMS[low]
            elif tok.startswith("@") and current:
                h = low.lstrip("@")
                known = by_platform.get(current, set())
                if known and h not in known:
                    close = difflib.get_close_matches(h, sorted(known), n=1, cutoff=0.6)
                    hint = f" mas a conta de {current.capitalize()} configurada é @{close[0]}" if close else \
                        f" mas não há nenhuma conta de {current.capitalize()} com esse nome"
                    warnings.append(f"O facto diz \"{current.capitalize()} {tok}\"{hint}.")
    return warnings
