"""Fontes de imagens/vídeo para vídeos criados do zero (todas gratuitas).

Prioridade:
  1. A tua biblioteca (assets/library/): fotos e vídeos reais das oficinas, equipa, carros.
     O nome do ficheiro serve de etiqueta, ex.: "oficina_elevador_classe-c.jpg",
     "equipa_mecanicos_sorriso.mp4". Também podes usar assets/library/etiquetas.yaml.
  2. Banco de stock gratuito (uso comercial permitido):
       - Pexels, se PEXELS_API_KEY existir;
       - senão Pixabay, com PIXABAY_API_KEY (https://pixabay.com/api/docs/).
     Regras da Pixabay respeitadas: respostas da API em cache 24 h, ficheiros descarregados para o
     servidor (sem hotlink) e origem registada para aparecer no dashboard ("Imagens: Pixabay").
  3. Fundo animado com as cores da marca.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import re
import unicodedata
from pathlib import Path

import yaml

from ..config import DATA_DIR, ROOT
from ..http import request

LIBRARY = ROOT / "assets" / "library"
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}

# sinónimos PT/EN para encontrar ficheiros da biblioteca
SYNONYMS = {
    "workshop": ["oficina", "garagem", "garage"], "mechanic": ["mecanico", "mecanicos", "tecnico"],
    "engine": ["motor"], "car": ["carro", "viatura", "mercedes"], "team": ["equipa", "pessoas"],
    "tools": ["ferramentas", "chave"], "diagnosis": ["diagnostico", "computador", "scanner"],
    "leader": ["lideranca", "david", "reuniao"], "brake": ["travoes", "travao", "pastilhas"],
    "tire": ["pneus", "pneu", "jante"], "oil": ["oleo", "mudanca"], "office": ["escritorio"],
}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _tags_for(path: Path, extra: dict) -> set[str]:
    tags = set(_norm(path.stem).split()) | set(_norm(" ".join(extra.get(path.name, []))).split())
    for en, pts in SYNONYMS.items():
        if en in tags or tags & set(pts):
            tags |= {en, *pts}
    return tags


def library_match(query: str, want: str = "any", used: set[str] | None = None) -> Path | None:
    if not LIBRARY.exists():
        return None
    extra = {}
    tags_file = LIBRARY / "etiquetas.yaml"
    if tags_file.exists():
        extra = yaml.safe_load(tags_file.read_text(encoding="utf-8")) or {}
    words = set(_norm(query).split())
    for en, pts in SYNONYMS.items():
        if en in words or words & set(pts):
            words |= {en, *pts}
    best, best_score = None, 0
    for p in LIBRARY.rglob("*"):
        ext = p.suffix.lower()
        if want == "video" and ext not in VIDEO_EXT or want == "image" and ext not in IMAGE_EXT:
            continue
        if ext not in VIDEO_EXT | IMAGE_EXT:
            continue
        score = len(words & _tags_for(p, extra)) * 2 + (1 if ext in VIDEO_EXT else 0)
        if used and str(p) in used:
            score -= 3
        if score > best_score:
            best, best_score = p, score
    return best if best_score >= 2 else None


def pexels_video(query: str, min_height: int = 1280, used: set[str] | None = None) -> Path | None:
    key = os.environ.get("PEXELS_API_KEY")
    if not key or not query:
        return None
    cache = DATA_DIR / "stock"
    cache.mkdir(parents=True, exist_ok=True)
    try:
        data = request("GET", "https://api.pexels.com/videos/search", headers={"Authorization": key},
                       params={"query": query, "orientation": "portrait", "per_page": 10, "size": "medium"},
                       retries=2, timeout=30).json()
    except Exception:  # noqa: BLE001 — sem stock, usa fundo da marca
        return None
    for video in data.get("videos", []):
        if not 4 <= video.get("duration", 0) <= 60:
            continue
        files = sorted((f for f in video["video_files"] if f.get("file_type") == "video/mp4" and f.get("height")),
                       key=lambda f: f["height"])
        good = [f for f in files if f["height"] >= min_height and f["height"] <= 2160] or files[-1:]
        if not good:
            continue
        url = good[0]["link"]
        path = cache / f"pexels_{video['id']}_{good[0]['height']}.mp4"
        if used and str(path) in used:
            continue
        if not path.exists():
            path.write_bytes(request("GET", url, timeout=300).content)
        return path
    return None


def pexels_photo(query: str) -> Path | None:
    key = os.environ.get("PEXELS_API_KEY")
    if not key or not query:
        return None
    try:
        data = request("GET", "https://api.pexels.com/v1/search", headers={"Authorization": key},
                       params={"query": query, "orientation": "portrait", "per_page": 1}, retries=2,
                       timeout=30).json()
        photo = data["photos"][0]
    except Exception:  # noqa: BLE001
        return None
    cache = DATA_DIR / "stock"
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / f"pexels_photo_{photo['id']}.jpg"
    if not path.exists():
        path.write_bytes(request("GET", photo["src"]["large2x"], timeout=120).content)
    return path


# ------------------------------------------------------------------ Pixabay
PIXABAY_IMG = "https://pixabay.com/api/"
PIXABAY_VID = "https://pixabay.com/api/videos/"
CACHE_TTL = 24 * 3600  # a Pixabay pede cache de 24 h das respostas da API


def _stock_dir() -> Path:
    d = DATA_DIR / "stock"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cached_api(url: str, params: dict) -> dict:
    """Pedido à API com cache em disco durante 24 h (a chave não entra no nome do ficheiro)."""
    public = {k: v for k, v in params.items() if k != "key"}
    name = hashlib.sha1((url + json.dumps(public, sort_keys=True)).encode()).hexdigest()[:20]
    cache = _stock_dir() / "api_cache" / f"{name}.json"
    if cache.exists() and time.time() - cache.stat().st_mtime < CACHE_TTL:
        return json.loads(cache.read_text(encoding="utf-8"))
    data = request("GET", url, params=params, retries=2, timeout=30).json()
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(data), encoding="utf-8")
    return data


def _remember_source(path: Path, info: dict) -> None:
    path.with_suffix(path.suffix + ".json").write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")


def source_of(path: str | Path) -> dict | None:
    """Origem de um ficheiro de stock (ex.: {"fonte": "Pixabay", "pagina": ..., "autor": ...}) ou None."""
    side = Path(str(path) + ".json")
    if side.exists():
        try:
            return json.loads(side.read_text(encoding="utf-8"))
        except ValueError:
            return None
    name = Path(path).name
    if name.startswith("pexels_"):
        return {"fonte": "Pexels"}
    return None


def pixabay_video(query: str, min_height: int = 1280, used: set[str] | None = None) -> Path | None:
    key = os.environ.get("PIXABAY_API_KEY")
    if not key or not query:
        return None
    try:
        data = _cached_api(PIXABAY_VID, {"key": key, "q": query[:100], "safesearch": "true", "per_page": 20,
                                         "video_type": "film"})
    except Exception:  # noqa: BLE001 — sem stock, usa fundo da marca
        return None
    hits = sorted(data.get("hits", []),  # vertical primeiro (9:16), depois por qualidade
                  key=lambda h: (-(h["videos"].get("large", {}).get("height", 0) >=
                                   h["videos"].get("large", {}).get("width", 1)), -h.get("downloads", 0)))
    for h in hits:
        if not 4 <= h.get("duration", 0) <= 60:
            continue
        variants = [v for v in (h["videos"].get(k) for k in ("large", "medium", "small")) if v and v.get("url")]
        good = [v for v in variants if min(v["width"], v["height"]) >= 720] or variants
        if not good:
            continue
        v = good[0]
        path = _stock_dir() / f"pixabay_video_{h['id']}_{v['height']}.mp4"
        if used and str(path) in used:
            continue
        if not path.exists():  # sem hotlink: o ficheiro fica no servidor
            path.write_bytes(request("GET", v["url"], timeout=300).content)
            _remember_source(path, {"fonte": "Pixabay", "pagina": h.get("pageURL"), "autor": h.get("user"),
                                    "id": h["id"], "tipo": "video"})
        return path
    return None


def pixabay_photo(query: str, used: set[str] | None = None) -> Path | None:
    key = os.environ.get("PIXABAY_API_KEY")
    if not key or not query:
        return None
    try:
        data = _cached_api(PIXABAY_IMG, {"key": key, "q": query[:100], "image_type": "photo",
                                         "orientation": "vertical", "safesearch": "true", "per_page": 20,
                                         "min_height": 1600})
    except Exception:  # noqa: BLE001
        return None
    for h in data.get("hits", []):
        url = h.get("largeImageURL") or h.get("webformatURL")
        if not url:
            continue
        path = _stock_dir() / f"pixabay_photo_{h['id']}.jpg"
        if used and str(path) in used:
            continue
        if not path.exists():
            path.write_bytes(request("GET", url, timeout=120).content)
            _remember_source(path, {"fonte": "Pixabay", "pagina": h.get("pageURL"), "autor": h.get("user"),
                                    "id": h["id"], "tipo": "foto"})
        return path
    return None


def stock_provider() -> str | None:
    """Pexels se houver chave; senão Pixabay; senão nenhum (fundo da marca)."""
    if os.environ.get("PEXELS_API_KEY"):
        return "pexels"
    if os.environ.get("PIXABAY_API_KEY"):
        return "pixabay"
    return None


def find_visual(query: str, kind: str = "any", used: set[str] | None = None) -> Path | None:
    """Encontra o melhor fundo para uma cena: biblioteca → Pexels (se configurado) ou Pixabay → None."""
    found = library_match(query, kind, used)
    if found:
        return found
    provider = stock_provider()
    if provider == "pexels":
        if kind in ("any", "video"):
            found = pexels_video(query, used=used)
        if not found and kind in ("any", "image"):
            found = pexels_photo(query)
    elif provider == "pixabay":
        if kind in ("any", "video"):
            found = pixabay_video(query, used=used)
        if not found and kind in ("any", "image"):
            found = pixabay_photo(query, used=used)
    return found


def brand_background(size: tuple[int, int]) -> Path:
    from .image_gen import _background
    W, H = size
    key = hashlib.md5(f"{W}x{H}".encode()).hexdigest()[:8]
    path = DATA_DIR / "cache" / f"brand_bg_{key}.png"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        _background(None, (int(W * 1.2), int(H * 1.2))).convert("RGB").save(path)
    return path
