"""Logótipo e assinatura das imagens geradas, por marca (tema da conta: pessoal / carretos / auron).

- pessoal (redes do David): sem logótipo, assinatura "David Carreto".
- carretos (Carretos Group): logótipo oficial CARRETO'S GROUP (branco, do site), sem o nome do David.
- auron: logótipo carregado pelo David (até lá, "AURON" em texto, em cima), sem o nome do David.
Cada imagem leva o nome UMA só vez (logótipo/marca em cima OU assinatura por baixo da frase).
Mudam-se em ⚙ Configurar → "Logótipo e assinatura das imagens".
"""
from __future__ import annotations

import json
from pathlib import Path

from .. import config as _cfg

ASSETS = Path(__file__).resolve().parent.parent / "assets"
BRANDS = {
    "pessoal": {"label": "David Carreto (contas pessoais)", "logo": None, "signature": "David Carreto"},
    "carretos": {"label": "Carretos Group", "logo": ASSETS / "carretos-logo-branco.png", "signature": ""},
    "auron": {"label": "AURON", "logo": None, "signature": ""},        # "AURON" só em cima (uma vez)
}
IMAGE_EXT = (".png", ".jpg", ".jpeg")


def _path() -> Path:
    return _cfg.DATA_DIR / "marcas_imagem.json"


def _saved() -> dict:
    try:
        return json.loads(_path().read_text(encoding="utf-8")) if _path().exists() else {}
    except (OSError, ValueError):
        return {}


def custom_logo(theme: str) -> Path | None:
    for ext in IMAGE_EXT:
        p = _cfg.DATA_DIR / "marcas" / f"{theme}-logo{ext}"
        if p.exists():
            return p
    return None


def get(theme: str | None) -> dict | None:
    """{logo: Path|None, signature: str, custom_logo: bool} da marca, ou None se a marca não é conhecida."""
    if theme not in BRANDS:
        return None
    base, saved = BRANDS[theme], _saved().get(theme, {})
    logo = custom_logo(theme)
    if not logo and not saved.get("no_logo"):
        logo = base["logo"] if base["logo"] and Path(base["logo"]).exists() else None
    return {"label": base["label"], "logo": logo, "custom_logo": bool(custom_logo(theme)),
            "no_logo": bool(saved.get("no_logo")),
            "signature": saved["signature"] if "signature" in saved else base["signature"]}


def save(theme: str, **fields) -> None:
    data = _saved()
    data.setdefault(theme, {}).update(fields)
    _cfg.DATA_DIR.mkdir(parents=True, exist_ok=True)
    _path().write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def save_logo(theme: str, data: bytes, ext: str) -> None:
    old = custom_logo(theme)
    if old:
        old.unlink()
    folder = _cfg.DATA_DIR / "marcas"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{theme}-logo{ext}").write_bytes(data)
    save(theme, no_logo=False)


def reset_logo(theme: str) -> None:
    old = custom_logo(theme)
    if old:
        old.unlink()
    save(theme, no_logo=False)
