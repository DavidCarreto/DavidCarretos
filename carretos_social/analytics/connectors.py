"""Recolha de métricas de cada plataforma.

Cada conector devolve uma lista de dicionários normalizados:
  remote_id, published_at, format, caption, views, reach, likes, comments, shares, saves
e, se disponível, o número de seguidores da conta.

Plataformas sem API de métricas (Facebook pessoal; LinkedIn pessoal sem a permissão
de analytics) podem ser alimentadas por importação de CSV — ver `import_csv`.
"""
from __future__ import annotations

from ..linkedin_connect import rest as li_rest

import csv
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from ..config import Account
from ..http import ApiError, request

GRAPH = "https://graph.facebook.com/" + os.environ.get("META_GRAPH_VERSION", "v21.0")
TIKTOK = "https://open.tiktokapis.com/v2"
LINKEDIN = "https://api.linkedin.com/rest"


def _linkedin_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",           # a versão da API é posta por li_rest()
        "X-Restli-Protocol-Version": "2.0.0",
    }


class NotConfigured(RuntimeError):
    pass


def _need(acc: Account, *keys: str) -> list[str]:
    values = [acc.secret(k) for k in keys]
    if not all(values):
        missing = [acc.credentials.get(k, k) for k, v in zip(keys, values) if not v]
        raise NotConfigured(f"{acc.id}: faltam credenciais ({', '.join(missing)}) no .env")
    return values  # type: ignore[return-value]


# ---------------------------------------------------------------- Instagram
def fetch_instagram(acc: Account, limit: int = 50) -> dict:
    token, user_id = _need(acc, "access_token_env", "user_id_env")
    profile = request("GET", f"{GRAPH}/{user_id}", params={
        "fields": "followers_count,media_count,username", "access_token": token}).json()
    media = request("GET", f"{GRAPH}/{user_id}/media", params={
        "fields": "id,caption,media_type,media_product_type,timestamp,like_count,comments_count,permalink",
        "limit": limit, "access_token": token}).json().get("data", [])
    posts = []
    for m in media:
        insights = {}
        try:
            data = request("GET", f"{GRAPH}/{m['id']}/insights", params={
                "metric": "views,reach,saved,shares", "access_token": token}).json()["data"]
            insights = {d["name"]: d["values"][0]["value"] for d in data}
        except (ApiError, KeyError, IndexError):
            pass  # publicações antigas ou tipos sem insights
        fmt = {"REELS": "reel", "CAROUSEL_ALBUM": "carousel"}.get(
            m.get("media_product_type") if m.get("media_product_type") == "REELS" else m.get("media_type"), "image")
        posts.append({
            "remote_id": m["id"], "published_at": m["timestamp"], "format": fmt,
            "caption": m.get("caption", ""), "views": insights.get("views", 0),
            "reach": insights.get("reach", 0), "likes": m.get("like_count", 0),
            "comments": m.get("comments_count", 0), "shares": insights.get("shares", 0),
            "saves": insights.get("saved", 0),
        })
    return {"followers": profile.get("followers_count"), "posts": posts}


# ---------------------------------------------------------------- TikTok
def fetch_tiktok(acc: Account, limit: int = 20) -> dict:
    (token,) = _need(acc, "access_token_env")
    from ..tiktok_connect import SCOPES
    if not {"user.info.stats", "video.list"} <= set(SCOPES):
        # a app TikTok só tem rascunhos (user.info.basic + video.upload): as métricas precisam de mais autorizações
        raise NotConfigured("métricas do TikTok precisam das autorizações user.info.stats e video.list "
                            "(não pedidas: a app só envia rascunhos). Use a importação de CSV do TikTok Studio.")
    headers = {"Authorization": f"Bearer {token}"}
    user = request("GET", f"{TIKTOK}/user/info/", headers=headers,
                   params={"fields": "follower_count,video_count,display_name"}).json()
    videos = request("POST", f"{TIKTOK}/video/list/", headers=headers,
                     params={"fields": "id,title,video_description,create_time,view_count,like_count,comment_count,share_count"},
                     json={"max_count": min(limit, 20)}).json().get("data", {}).get("videos", [])
    posts = [{
        "remote_id": v["id"],
        "published_at": datetime.fromtimestamp(v["create_time"], tz=timezone.utc).isoformat(),
        "format": "video", "caption": v.get("video_description") or v.get("title", ""),
        "views": v.get("view_count", 0), "reach": v.get("view_count", 0),
        "likes": v.get("like_count", 0), "comments": v.get("comment_count", 0),
        "shares": v.get("share_count", 0), "saves": 0,
    } for v in videos]
    return {"followers": user.get("data", {}).get("user", {}).get("follower_count"), "posts": posts}


# ---------------------------------------------------------------- LinkedIn
def fetch_linkedin(acc: Account, limit: int = 100) -> dict:      # 100 = máximo por página da Posts API
    token, author = _need(acc, "access_token_env", "author_urn_env")
    if acc.platform == "linkedin_member":
        # ler os posts/estatísticas de um perfil pessoal exige r_member_social, que o LinkedIn só dá a parceiros
        raise NotConfigured("métricas do perfil pessoal do LinkedIn precisam da autorização r_member_social, que o "
                            "LinkedIn só dá a parceiros aprovados. Veja-as no LinkedIn ou importe o CSV.")
    headers = _linkedin_headers(token)
    posts_resp = li_rest("GET", f"{LINKEDIN}/posts", headers=headers,
                         params={"q": "author", "author": author, "count": limit}).json()
    posts = []
    stats_by_share: dict = {}
    followers = None
    if acc.platform == "linkedin_org":
        try:
            stats = li_rest("GET", f"{LINKEDIN}/organizationalEntityShareStatistics", headers=headers,
                            params={"q": "organizationalEntity", "organizationalEntity": author}).json()
            for el in stats.get("elements", []):
                key = el.get("share") or el.get("ugcPost")
                if key:
                    stats_by_share[key] = el.get("totalShareStatistics", {})
        except ApiError:
            pass
        from ..linkedin_connect import followers as li_followers   # o mesmo valor da pré-visualização (1.517)
        followers = li_followers(acc)
    for p in posts_resp.get("elements", []):
        s = stats_by_share.get(p["id"], {})
        content = p.get("content") or {}
        fmt = "video" if "media" in content and "video" in str(content).lower() else (
            "image" if content else "text")
        posts.append({
            "remote_id": p["id"],
            "published_at": datetime.fromtimestamp(p.get("publishedAt", p.get("createdAt", 0)) / 1000,
                                                   tz=timezone.utc).isoformat(),
            "format": fmt, "caption": p.get("commentary", ""),
            "views": s.get("impressionCount", 0), "reach": s.get("uniqueImpressionsCount", 0),
            "likes": s.get("likeCount", 0), "comments": s.get("commentCount", 0),
            "shares": s.get("shareCount", 0), "saves": 0,
        })
    return {"followers": followers, "posts": posts}


FETCHERS = {
    "instagram": fetch_instagram,
    "tiktok": fetch_tiktok,
    "linkedin_member": fetch_linkedin,
    "linkedin_org": fetch_linkedin,
}


def fetch(acc: Account) -> dict:
    fn = FETCHERS.get(acc.platform)
    if not fn:
        raise NotConfigured(f"{acc.id}: {acc.platform} não tem API de métricas — usa `carretos import-csv`.")
    return fn(acc)


# ---------------------------------------------------------------- CSV
CSV_ALIASES = {
    "remote_id": ["remote_id", "id", "post id", "post_id", "url", "link"],
    "published_at": ["published_at", "date", "data", "publish time", "created", "hora de publicação"],
    "caption": ["caption", "description", "descrição", "legenda", "title", "texto"],
    "format": ["format", "type", "tipo", "post type"],
    "views": ["views", "visualizações", "impressions", "impressões", "plays", "reproduções"],
    "reach": ["reach", "alcance", "unique impressions"],
    "likes": ["likes", "gostos", "reactions", "reações", "gosto"],
    "comments": ["comments", "comentários"],
    "shares": ["shares", "partilhas", "reposts"],
    "saves": ["saves", "guardados", "saved"],
}


def import_csv(path: Path) -> list[dict]:
    """Importa um CSV exportado de qualquer plataforma (Meta Business Suite, LinkedIn, TikTok Studio)."""
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        return []
    lower = {h.lower().strip(): h for h in rows[0]}
    mapping = {}
    for field, aliases in CSV_ALIASES.items():
        for alias in aliases:
            if alias in lower:
                mapping[field] = lower[alias]
                break
    out = []
    for i, r in enumerate(rows):
        item = {}
        for field, col in mapping.items():
            val = (r.get(col) or "").strip()
            if field in ("views", "reach", "likes", "comments", "shares", "saves"):
                digits = re.sub(r"[^\d]", "", val.split(".")[0] if re.fullmatch(r"\d+\.0+", val) else val)
                val = int(digits) if digits else 0
            item[field] = val
        item.setdefault("remote_id", f"csv-{path.stem}-{i}")
        item.setdefault("format", "video")
        out.append(item)
    return out
