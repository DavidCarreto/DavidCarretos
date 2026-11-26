"""Cartão do link nos posts do LinkedIn só com texto + link.

A Posts API do LinkedIn NÃO lê o site sozinha: para aparecer o cartão, o post tem de ir como "artigo" com
título, descrição e miniatura (carregada pela Images API). Por isso:
- links do carretos.pt (e subdomínios): título, descrição e imagem definidos no Carretos Studio
  (⚙ Configurar → "Cartão dos links carretos.pt"; cada rascunho pode mudar os seus);
- links de outros sites: lidos automaticamente (og:title/og:image; as imagens SVG são ignoradas, como no LinkedIn).
"""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

from . import config as _cfg

ASSET = Path(__file__).parent / "assets" / "link-card-carretos.png"
OWN_DOMAINS = ("carretos.pt",)
DEFAULTS = {"title": "Carreto's Group",
            "description": "Especialistas Mercedes-Benz em Almada, Cacém, Lisboa, Mafra e Santarém. "
                           "Revisões com preço na hora, online."}
LINKEDIN = ("linkedin_member", "linkedin_org")
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif")          # formatos aceites pela Images API do LinkedIn


def _cfg_path() -> Path:
    return _cfg.DATA_DIR / "link_card.json"


def settings() -> dict:
    try:
        saved = json.loads(_cfg_path().read_text(encoding="utf-8")) if _cfg_path().exists() else {}
    except (OSError, ValueError):
        saved = {}
    return {**DEFAULTS, **{k: v for k, v in saved.items() if v}}


def save_settings(**fields) -> None:
    cur = {}
    try:
        cur = json.loads(_cfg_path().read_text(encoding="utf-8")) if _cfg_path().exists() else {}
    except (OSError, ValueError):
        pass
    cur.update(fields)
    _cfg.DATA_DIR.mkdir(parents=True, exist_ok=True)
    _cfg_path().write_text(json.dumps(cur, ensure_ascii=False), encoding="utf-8")


def custom_default_image() -> Path | None:
    for ext in IMAGE_EXT:
        p = _cfg.DATA_DIR / f"link_card{ext}"
        if p.exists():
            return p
    return None


def default_image() -> Path:
    return custom_default_image() or ASSET


def post_image_dir() -> Path:
    return _cfg.DATA_DIR / "link_cards"


def post_image(pid: int) -> Path | None:
    for ext in IMAGE_EXT:
        p = post_image_dir() / f"{pid}{ext}"
        if p.exists():
            return p
    return None


def own_domain(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in OWN_DOMAINS)


def _get(row, key, default=None):
    try:
        v = row[key]
    except (KeyError, IndexError):
        return default
    return default if v is None else v


def overrides(row) -> dict:
    try:
        return json.loads(_get(row, "script", "") or "{}").get("link_card") or {}
    except ValueError:
        return {}


def for_post(row, platform: str) -> dict | None:
    """Cartão que o post vai levar, ou None (não é LinkedIn, tem imagem/vídeo, ou não tem link).
    mode "proprio": título/descrição/imagem definidos aqui; mode "auto": lidos do site na altura."""
    if platform not in LINKEDIN or json.loads(_get(row, "media_ids", "") or "[]"):
        return None
    from .scheduler import caption_with_tags
    from .web.linkpreview import first_url
    url = first_url(caption_with_tags(row))
    if not url:
        return None
    ov, own = overrides(row), own_domain(url)
    pid = _get(row, "id")
    img = post_image(pid) if pid else None
    if not (own or ov or img):
        return {"mode": "auto", "url": url, "domain": _domain(url)}
    s = settings() if own else {"title": "", "description": ""}
    return {"mode": "proprio", "url": url, "domain": _domain(url),
            "title": (ov.get("title") or s["title"]).strip(), "description": (ov.get("description") or s["description"]).strip(),
            "image": str(img or (default_image() if own else "")) or None, "custom": bool(ov or img)}


def _domain(url: str) -> str:
    return (urlparse(url).hostname or "").removeprefix("www.")


def resolve(card: dict) -> dict:
    """Para publicar: completa um cartão "auto" lendo o site (título, descrição e imagem em bytes)."""
    if card["mode"] == "proprio":
        data = Path(card["image"]).read_bytes() if card.get("image") else None
        return {**card, "image_bytes": data}
    from .web import linkpreview
    pv = linkpreview.preview(card["url"])
    data = None
    if pv.get("image"):
        try:
            data = linkpreview.fetch_image(pv["image"])
        except Exception:  # noqa: BLE001
            data = None
    return {**card, "title": pv.get("title") or card["domain"], "description": pv.get("description") or "",
            "image_bytes": data}


def text_problems(row, platform: str) -> list[str]:
    """Palavras proibidas e [PREENCHER] também valem para o título e a descrição do cartão."""
    card = for_post(row, platform)
    if not card or card["mode"] != "proprio":
        return []
    from .content.guard import found_terms
    txt = f"{card['title']}\n{card['description']}"
    out = [f"cartão do link: {w}" for _, w in found_terms(_get(row, "account_id", ""), txt)]
    if "[PREENCHER" in txt:
        out.append("cartão do link por preencher ([PREENCHER…])")
    if not card["title"]:
        out.append("cartão do link sem título")
    return out


def warnings(row, platform: str) -> list[str]:
    """Avisos (não bloqueiam): o post vai como artigo sem título nem imagem."""
    card = for_post(row, platform)
    if not card:
        return []
    if card["mode"] == "proprio":
        return [] if card.get("image") else ["cartão do link sem imagem – carregue uma em (mudar)"]
    from .web.linkpreview import cached
    hit = cached(card["url"])
    if hit and not hit.get("title") and not hit.get("image"):
        return ["cartão do link: o site não deixa ler o link – defina o título e a imagem do cartão em (mudar)"]
    if hit and not hit.get("image"):
        return ["cartão do link sem imagem (o site não tem imagem PNG/JPG) – pode carregar uma em (mudar)"]
    return []
