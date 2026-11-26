"""Pré-visualização de links (título, descrição, imagem e domínio, das etiquetas Open Graph da página), para a
pré-visualização ao estilo do LinkedIn. Só endereços públicos (protege a rede interna do servidor), tempo e
tamanho limitados, e guardado em cache 24 h (data/og_cache.json)."""
from __future__ import annotations

import html
import ipaddress
import json
import re
import socket
import time
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from .. import config as _cfg

URL_RE = re.compile(r"(https?://[^\s<>\"]+|(?<![@\w.])[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:pt|com|org|net|io|eu|app)\b(?:/[^\s<>\"]*)?)", re.I)
MAX_BYTES = 512 * 1024
CACHE_HOURS = 24


def first_url(text: str) -> str:
    m = URL_RE.search(text or "")
    if not m:
        return ""
    url = m.group(1).rstrip(".,;:!?)»")
    return url if url.lower().startswith("http") else "https://" + url


def _public(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            return False
    return True


def _safe_get(url: str, hops: int = 3) -> tuple[str, str]:
    """(url final, html) só de endereços públicos http/https, seguindo até 3 redirecionamentos verificados."""
    import requests
    for _ in range(hops + 1):
        p = urlparse(url)
        if p.scheme not in ("http", "https") or not p.hostname or (p.port and p.port not in (80, 443)):
            raise ValueError("endereço não permitido")
        if not _public(p.hostname):
            raise ValueError("endereço não público")
        r = requests.get(url, timeout=5, allow_redirects=False, stream=True,
                         headers={"User-Agent": "Mozilla/5.0 (CarretosStudio link preview)"})
        if r.is_redirect or r.status_code in (301, 302, 303, 307, 308):
            url = urljoin(url, r.headers.get("location", ""))
            continue
        body = b""
        for chunk in r.iter_content(65536):
            body += chunk
            if len(body) > MAX_BYTES:
                break
        return url, body.decode(r.encoding or "utf-8", errors="replace")
    raise ValueError("demasiados redirecionamentos")


class _Head(HTMLParser):
    """Lê as etiquetas <meta>, <link rel=icon> e <title> com um leitor de HTML a sério (aspas simples ou duplas,
    apóstrofos, &#39;, atributos por qualquer ordem)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, list[str]] = {}
        self.icons: list[tuple[str, str, str]] = []           # (rel, sizes, href)
        self.title, self._in_title = "", False

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "meta":
            key = (a.get("property") or a.get("name") or a.get("itemprop") or "").strip().lower()
            if key and a.get("content", "").strip():
                self.meta.setdefault(key, []).append(a["content"].strip())
        elif tag == "link" and "icon" in a.get("rel", "").lower() and a.get("href"):
            self.icons.append((a["rel"].lower(), a.get("sizes", ""), a["href"]))
        elif tag == "title" and not self.title:
            self._in_title = True

    def handle_data(self, data):
        if self._in_title:
            self.title += data

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False


def _head(page: str) -> _Head:
    h = _Head()
    try:
        h.feed(page)
    except Exception:  # noqa: BLE001
        pass
    return h


def _meta(page: str, *names: str) -> str:
    h = _head(page)
    for name in names:
        if h.meta.get(name.lower()):
            return h.meta[name.lower()][0]
    return ""


def _best_icon(h: _Head) -> str:
    """Ícone maior do site (apple-touch-icon / icon com tamanho), usado quando não há og:image."""
    def size(icon):
        m = re.match(r"(\d+)x\d+", icon[1])
        return (int(m.group(1)) if m else (180 if "apple" in icon[0] else 16))
    return max(h.icons, key=size)[2] if h.icons else ""


CACHE_VERSION = 2          # mudar quando a leitura muda (ignora o que ficou guardado com a leitura antiga)


def preview(url: str, fresh: bool = False) -> dict:
    """{url, domain, title, description, image, sources} (vazios se não for possível ler a página)."""
    if not url:
        return {}
    path = _cfg.DATA_DIR / "og_cache.json"
    try:
        cache = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError):
        cache = {}
    hit = cache.get(url)
    if (hit and not fresh and hit.get("_v") == CACHE_VERSION
            and time.time() - hit.get("_at", 0) < CACHE_HOURS * 3600):
        return hit
    domain = (urlparse(url).hostname or "").removeprefix("www.")
    data = {"url": url, "domain": domain, "title": "", "description": "", "image": "", "sources": {},
            "_at": time.time(), "_v": CACHE_VERSION}
    try:
        final, page = _safe_get(url)
        h = _head(page)
        first = lambda *ks: next(((k, h.meta[k][0]) for k in ks if h.meta.get(k)), ("", ""))  # noqa: E731
        tk, title = first("og:title", "twitter:title")
        if not title and h.title.strip():
            tk, title = "<title>", h.title.strip()
        ik, img = first("og:image", "og:image:url", "og:image:secure_url", "twitter:image", "twitter:image:src")
        if not img and _best_icon(h):
            ik, img = "ícone do site", _best_icon(h)
        data.update(title=" ".join(title.split())[:200], description=first("og:description", "description")[1][:300],
                    image=urljoin(final, img) if img else "",
                    sources={"title": tk, "image": ik, "og_images": [urljoin(final, x) for x in h.meta.get("og:image", [])][:5],
                             "icons": [urljoin(final, i[2]) for i in h.icons][:5]})
    except Exception as exc:  # noqa: BLE001
        data["error"] = str(exc)[:200]
    cache[url] = data
    _cfg.DATA_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(list(cache.items())[-200:]), ensure_ascii=False), encoding="utf-8")
    return data


_TOKEN_RE = re.compile(r"(https?://[^\s<>\"]+|#[^\s#.,;:!?()\[\]{}<>\"']+)")


def li_html(text: str) -> str:
    """Texto como o LinkedIn o mostra: escapado, com hashtags e links a azul (sem links reais clicáveis)."""
    out, pos = [], 0
    for m in _TOKEN_RE.finditer(text or ""):
        out.append(html.escape(text[pos:m.start()]))
        out.append(f'<span class="li-blue">{html.escape(m.group(1))}</span>')
        pos = m.end()
    out.append(html.escape((text or "")[pos:]))
    return "".join(out)
