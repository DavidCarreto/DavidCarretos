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
    group: str = "david"
    status: str = ""                 # "por_ligar" = ainda sem handle/tokens
    meta_id: str = ""                # id da Página/Instagram na Meta (ajuda a ligação a reconhecê-lo)
    credentials: dict = field(default_factory=dict)

    def secret(self, key: str) -> str | None:
        env_name = self.credentials.get(key)
        return os.environ.get(env_name) if env_name else None

    @property
    def has_credentials(self) -> bool:
        return bool(self.credentials) and all(self.secret(k) for k in self.credentials)

    @property
    def mode(self) -> str:
        """Modo efetivo: 'assist' (telemóvel), 'draft' (rascunho na app TikTok) ou 'auto' (publica sozinho)."""
        if self.platform == "tiktok" and self.has_credentials:
            return "draft"
        return "assist" if self.assist_reason else "auto"

    @property
    def assist_reason(self) -> str:
        """Porque é que esta conta publica em modo assistido (vazio = publica sozinha)."""
        if self.platform == "facebook_profile":
            return "A Meta não deixa publicar em perfis pessoais: vai para o telemóvel, para publicar à mão."
        if self.publish_mode == "assist":
            return "Configurada em modo assistido."
        if self.platform == "tiktok" and not self.has_credentials:
            return "TikTok por ligar: até lá os posts vão para o telemóvel."
        if self.platform == "linkedin_org" and not (_yes("LINKEDIN_ORG_API") and self.has_credentials):
            return ("O LinkedIn ainda não aprovou a Community Management API (necessária para publicar na página): "
                    "vai para o telemóvel.")
        return ""

    @property
    def connected(self) -> bool:
        """Conta ligada: não está 'por ligar' e tem as credenciais (o modo assistido não precisa)."""
        if self.status == "por_ligar":
            return False
        if self.mode in ("assist", "draft"):
            return True
        return self.has_credentials

    @property
    def label(self) -> str:
        return self.name + ("" if self.connected else " · por ligar")


@lru_cache
def account_overrides() -> dict:
    """Dados das contas ligadas no dashboard (data/contas.json): handle e estado vindos da Meta, etc."""
    import json
    p = DATA_DIR / "contas.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except (OSError, ValueError):
        return {}


def save_account_override(account_id: str, **fields) -> None:
    import json
    data = account_overrides()
    data.setdefault(account_id, {}).update(fields)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "contas.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def accounts() -> dict[str, Account]:
    over = account_overrides()
    out = {}
    for a in _yaml("accounts.yaml")["accounts"]:
        o = over.get(a["id"]) or {}
        a = dict(a)
        if o.get("handle"):
            a["handle"] = o["handle"]
        if o.get("status") == "ligada" and a.get("status") == "por_ligar":
            a["status"] = ""                 # ligada no dashboard: deixa de estar "por ligar"
        out[a["id"]] = Account(**a)
    return out


def _yes(env: str) -> bool:
    return os.environ.get(env, "").strip().lower() in ("1", "sim", "s", "yes", "true")


@lru_cache
def groups() -> list[dict]:
    """Grupos de contas (ordem de apresentação): [{"id","name","short"}]."""
    return _yaml("accounts.yaml").get("groups") or [{"id": "david", "name": "Redes do David Carreto",
                                                    "short": "David Carreto"}]


def group_of(account_id: str) -> dict:
    acc = accounts().get(account_id)
    gid = acc.group if acc else "david"
    return next((g for g in groups() if g["id"] == gid), {"id": gid, "name": gid, "short": gid})


def facts_brand(account_id: str | None = None, group_id: str | None = None) -> str:
    """Que lista de factos/tom usar: 'geral' (David + Carretos Group) ou a da marca do grupo (ex.: 'auron')."""
    if account_id and not group_id:
        acc = accounts().get(account_id)
        group_id = acc.group if acc else None
    g = next((g for g in groups() if g["id"] == group_id), None) if group_id else None
    return (g or {}).get("facts") or "geral"


def facts_brands() -> list[dict]:
    """Listas de factos existentes: [{"id","name","groups"}], 'geral' primeiro."""
    out: dict[str, dict] = {}
    for g in groups():
        b = g.get("facts") or "geral"
        item = out.setdefault(b, {"id": b, "name": "", "groups": []})
        item["groups"].append(g["short"])
    for b in out.values():
        b["name"] = " + ".join(b["groups"])
    return list(out.values())


def accounts_by_group() -> list[tuple[dict, list[Account]]]:
    return [(g, [a for a in accounts().values() if a.group == g["id"]]) for g in groups()]


@lru_cache
def _brand_base() -> dict:
    return _yaml("brand.yaml")


_ACTIVE_THEME: str | None = None


def set_theme(name: str | None) -> None:
    """Ativa a identidade visual de uma conta (ex.: 'pessoal' = preto e dourado, 'DAVID CARRETO')."""
    global _ACTIVE_THEME
    _ACTIVE_THEME = name


def brand() -> dict:
    """Configuração da marca com o tema visual ativo aplicado por cima (cores, fontes, assinatura) e o logótipo
    e a assinatura das imagens escolhidos em ⚙ Configurar (media/brand_assets.py)."""
    base = _brand_base()
    theme = (base.get("themes") or {}).get(_ACTIVE_THEME or "")
    if theme is None and _ACTIVE_THEME not in ("carretos", "pessoal", "auron"):
        return base
    theme = theme or {}
    merged = dict(base)
    merged["visual"] = {**base["visual"], **{k: v for k, v in theme.items() if k != "colors"},
                        "colors": {**base["visual"]["colors"], **theme.get("colors", {})}}
    if theme:                             # (tema "carretos" vazio: sem assinatura em texto, como antes)
        merged["signature"] = theme.get("signature") or base.get("company")
    from .media import brand_assets
    ident = brand_assets.get(_ACTIVE_THEME)
    if ident:
        merged["visual"]["logo"] = str(ident["logo"]) if ident["logo"] else ""
        merged["visual"]["quote_author"] = ident["signature"]      # "" = sem assinatura por baixo da frase
        if ident.get("accent"):                                    # cor de destaque escolhida em ⚙ Configurar
            merged["visual"]["colors"] = {**merged["visual"]["colors"], "accent": ident["accent"]}
        merged["theme_id"] = _ACTIVE_THEME
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
