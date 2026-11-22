"""Ligar as contas TikTok (dashboard → Contas → "Ligar esta conta"): Content Posting API (Direct Post).

- Cada conta autoriza à parte (pessoal, Carreto Clips, Carretos Group): antes de carregar em "Ligar", é preciso
  estar com ESSA conta aberta em tiktok.com.
- O token de acesso dura 24 horas: é renovado sozinho com o "refresh token" (que dura ~1 ano).
- Enquanto a TikTok não auditar a app, só se pode publicar em privado (SELF_ONLY): até lá os posts públicos
  seguem em modo assistido (TIKTOK_AUDITED=sim em ⚙ Configurar depois da auditoria).
Chaves em ⚙ Configurar: TIKTOK_CLIENT_KEY e TIKTOK_CLIENT_SECRET. Guia: docs/GUIA_TIKTOK.md.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from urllib.parse import urlencode

from .config import Account, _yes, account_overrides, save_account_override
from .http import request

AUTH = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN = "https://open.tiktokapis.com/v2/oauth/token/"
API = "https://open.tiktokapis.com/v2"
SCOPES = ["user.info.basic", "video.publish", "video.upload"]


def configured() -> bool:
    return bool(os.environ.get("TIKTOK_CLIENT_KEY") and os.environ.get("TIKTOK_CLIENT_SECRET"))


def audited() -> bool:
    return _yes("TIKTOK_AUDITED")


def login_url(redirect_uri: str, state: str) -> str:
    return AUTH + "?" + urlencode({"client_key": os.environ["TIKTOK_CLIENT_KEY"], "scope": ",".join(SCOPES),
                                   "response_type": "code", "redirect_uri": redirect_uri, "state": state})


def _token(data: dict) -> dict:
    r = request("POST", TOKEN, data={"client_key": os.environ["TIKTOK_CLIENT_KEY"],
                                     "client_secret": os.environ["TIKTOK_CLIENT_SECRET"], **data},
                headers={"Content-Type": "application/x-www-form-urlencoded"}).json()
    if r.get("error") or not r.get("access_token"):
        raise RuntimeError(f"TikTok recusou: {r.get('error_description') or r.get('error') or r}")
    return r


def exchange(code: str, redirect_uri: str) -> dict:
    return _token({"code": code, "grant_type": "authorization_code", "redirect_uri": redirect_uri})


def user_info(token: str) -> dict:
    r = request("GET", f"{API}/user/info/", params={"fields": "open_id,display_name,username"},
                headers={"Authorization": f"Bearer {token}"}).json()
    return (r.get("data") or {}).get("user") or {}


def _expiry(seconds) -> str:
    return (datetime.now() + timedelta(seconds=int(seconds or 0))).isoformat(timespec="seconds")


def link(acc: Account, tok: dict) -> dict[str, str]:
    """Liga a conta com o resultado da autorização. Devolve as variáveis a guardar no .env."""
    user = user_info(tok["access_token"])
    save_account_override(acc.id, status="ligada", handle=user.get("username") or acc.handle,
                          meta_name=user.get("display_name") or user.get("username") or "",
                          access_expires=_expiry(tok.get("expires_in", 86400)),
                          refresh_expires=_expiry(tok.get("refresh_expires_in", 365 * 86400))[:10],
                          linked_at=datetime.now().isoformat(timespec="minutes"))
    return {acc.credentials["access_token_env"]: tok["access_token"],
            acc.credentials["refresh_token_env"]: tok.get("refresh_token", "")}


def ensure_fresh(acc: Account) -> str:
    """Token válido para publicar/testar: renova-o se faltar menos de 10 minutos (o da TikTok dura 24 h)."""
    from .envfile import set_env
    token = acc.secret("access_token_env")
    exp = (account_overrides().get(acc.id) or {}).get("access_expires")
    if token and exp and datetime.fromisoformat(exp) > datetime.now() + timedelta(minutes=10):
        return token
    refresh = acc.secret("refresh_token_env")
    if not refresh:
        raise RuntimeError(f"{acc.name}: por ligar (Contas → Ligar esta conta)")
    tok = _token({"grant_type": "refresh_token", "refresh_token": refresh})
    set_env({acc.credentials["access_token_env"]: tok["access_token"],
             acc.credentials["refresh_token_env"]: tok.get("refresh_token", refresh)})
    save_account_override(acc.id, access_expires=_expiry(tok.get("expires_in", 86400)),
                          refresh_expires=_expiry(tok.get("refresh_expires_in", 365 * 86400))[:10])
    return tok["access_token"]


def test(acc: Account) -> tuple[bool, str]:
    try:
        user = user_info(ensure_fresh(acc))
        note = "" if audited() else " (app por auditar: só publica em privado; os posts públicos vão para o telemóvel)"
        return True, f"TikTok @{user.get('username') or user.get('display_name') or '?'} ✓{note}"
    except Exception as exc:  # noqa: BLE001
        return False, f"a ligação falhou: {exc}"


def unlink(acc: Account) -> dict[str, str]:
    save_account_override(acc.id, status="desligada", access_expires=None, refresh_expires=None, linked_at=None)
    return {env: "" for env in acc.credentials.values()}
