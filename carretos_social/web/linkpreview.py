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


def _meta(page: str, *names: str) -> str:
    for name in names:
        for pat in (rf'<meta[^>]+(?:property|name)=["\']{re.escape(name)}["\'][^>]*content=["\']([^"\']*)["\']',
                    rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]*(?:property|name)=["\']{re.escape(name)}["\']'):
            m = re.search(pat, page, re.I)
            if m and m.group(1).strip():
                return html.unescape(m.group(1).strip())
    return ""


def preview(url: str) -> dict:
    """{url, domain, title, description, image} (vazios se não for possível ler a página)."""
    if not url:
        return {}
    path = _cfg.DATA_DIR / "og_cache.json"
    try:
        cache = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError):
        cache = {}
    hit = cache.get(url)
    if hit and time.time() - hit.get("_at", 0) < CACHE_HOURS * 3600:
        return hit
    domain = (urlparse(url).hostname or "").removeprefix("www.")
    data = {"url": url, "domain": domain, "title": "", "description": "", "image": "", "_at": time.time()}
    try:
        final, page = _safe_get(url)
        title = _meta(page, "og:title", "twitter:title")
        if not title:
            m = re.search(r"<title[^>]*>(.*?)</title>", page, re.I | re.S)
            title = html.unescape(m.group(1).strip()) if m else ""
        img = _meta(page, "og:image", "twitter:image")
        data.update(title=title[:200], description=_meta(page, "og:description", "description")[:300],
                    image=urljoin(final, img) if img else "")
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
