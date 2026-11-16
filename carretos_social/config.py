"""Carregamento da configuração (contas, marca, estratégia) e do ficheiro .env."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = Path(os.environ.get("CARRETOS_CONFIG_DIR", ROOT / "config"))
DATA_DIR = Path(os.environ.get("CARRETOS_DATA_DIR", ROOT / "data"))


def load_env(path: Path | None = None) -> None:
    """Lê um ficheiro .env simples (CHAVE=valor) sem dependências externas."""
    path = path or ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _yaml(name: str) -> dict:
    return yaml.safe_load((CONFIG_DIR / name).read_text(encoding="utf-8")) or {}


@dataclass
class Account:
    id: str
    platform: str
    name: str
    handle: str
    voice: str
    publish_mode: str = "auto"
    auto_approve: bool = False
    narrator: str = "generica"
    theme: str = "carretos"
    credentials: dict = field(default_factory=dict)

    def secret(self, key: str) -> str | None:
        env_name = self.credentials.get(key)
        return os.environ.get(env_name) if env_name else None


@lru_cache
def accounts() -> dict[str, Account]:
    return {a["id"]: Account(**a) for a in _yaml("accounts.yaml")["accounts"]}


@lru_cache
def _brand_base() -> dict:
    return _yaml("brand.yaml")


_ACTIVE_THEME: str | None = None


def set_theme(name: str | None) -> None:
    """Ativa a identidade visual de uma conta (ex.: 'pessoal' = preto e dourado, 'DAVID CARRETO')."""
    global _ACTIVE_THEME
    _ACTIVE_THEME = name


def brand() -> dict:
    """Configuração da marca com o tema visual ativo aplicado por cima (cores, fontes, assinatura)."""
    base = _brand_base()
    theme = (base.get("themes") or {}).get(_ACTIVE_THEME or "")
    if not theme:
        return base
    merged = dict(base)
    merged["visual"] = {**base["visual"], **{k: v for k, v in theme.items() if k != "colors"},
                        "colors": {**base["visual"]["colors"], **theme.get("colors", {})}}
    merged["signature"] = theme.get("signature") or base.get("company")
    return merged


@lru_cache
def strategy() -> dict:
    return _yaml("strategy.yaml")


def account(account_id: str) -> Account:
    try:
        acc = accounts()[account_id]
        set_theme(acc.theme)  # imagens e vídeos seguintes usam a identidade visual desta conta
        return acc
    except KeyError:
        raise SystemExit(f"Conta desconhecida: {account_id}. Opções: {', '.join(accounts())}")
