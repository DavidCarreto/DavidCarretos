"""Ligar as Páginas de Facebook e as contas de Instagram pela Meta ("Ligar com o Facebook" no dashboard).

Fluxo:
  1. O administrador entra com o Facebook (OAuth) e autoriza as Páginas/Instagrams.
  2. Troca-se o código por um token de utilizador de longa duração e pedem-se as Páginas
     (/me/accounts): cada Página traz o seu token (que não expira enquanto o utilizador não mudar
     a palavra-passe nem retirar o acesso) e, se tiver, o Instagram profissional ligado.
  3. No dashboard escolhe-se que Página/Instagram corresponde a cada conta do Carretos Studio.
     Os tokens vão para o .env do servidor (nunca são mostrados) e a conta passa a "ligada".

Precisa de uma app da Meta (developers.facebook.com) com META_APP_ID e META_APP_SECRET em ⚙ Configurar
(ver docs/GUIA_META.md). Este sistema NÃO usa nenhuma API Google.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime

from .config import DATA_DIR, Account, accounts, save_account_override
from .http import request

SCOPES = ["pages_show_list", "pages_read_engagement", "pages_manage_posts", "business_management",
          "instagram_basic", "instagram_content_publish", "instagram_manage_insights"]
MIN_VERSION = 24


def graph_version() -> str:
    """Versão da Graph API: a do .env, mas nunca abaixo da v24 (as antigas deixam de funcionar)."""
    v = os.environ.get("META_GRAPH_VERSION", "")
    m = re.match(r"v?(\d+)", v)
    return v if m and int(m.group(1)) >= MIN_VERSION else f"v{MIN_VERSION}.0"


def graph() -> str:
    return f"https://graph.facebook.com/{graph_version()}"


def configured() -> bool:
    return bool(os.environ.get("META_APP_ID") and os.environ.get("META_APP_SECRET"))


def login_url(redirect_uri: str, state: str) -> str:
    from urllib.parse import urlencode
    params = {"client_id": os.environ["META_APP_ID"], "redirect_uri": redirect_uri, "state": state,
              "response_type": "code"}
    if os.environ.get("META_LOGIN_CONFIG_ID"):          # "Facebook Login for Business" (configuração)
        params["config_id"] = os.environ["META_LOGIN_CONFIG_ID"]
        params["override_default_response_type"] = "true"
    else:
        params["scope"] = ",".join(SCOPES)
    return f"https://www.facebook.com/{graph_version()}/dialog/oauth?{urlencode(params)}"


def exchange_code(code: str, redirect_uri: str) -> str:
    """Código → token de utilizador de longa duração (~60 dias; os das Páginas que dele vêm não expiram).
    A validade fica em LAST_EXPIRES_IN (usada nos Instagrams sem Página, que publicam com este token)."""
    global LAST_EXPIRES_IN
    app_id, secret = os.environ["META_APP_ID"], os.environ["META_APP_SECRET"]
    short = request("GET", f"{graph()}/oauth/access_token", params={
        "client_id": app_id, "client_secret": secret, "redirect_uri": redirect_uri, "code": code}).json()
    long = request("GET", f"{graph()}/oauth/access_token", params={
        "grant_type": "fb_exchange_token", "client_id": app_id, "client_secret": secret,
        "fb_exchange_token": short["access_token"]}).json()
    LAST_EXPIRES_IN = int(long.get("expires_in") or 60 * 86400)
    return long["access_token"]


LAST_EXPIRES_IN = 60 * 86400


PAGE_FIELDS = "id,name,access_token,tasks,instagram_business_account{id,username,name}"


def _paged(url: str, params: dict | None) -> list[dict]:
    out = []
    while url:
        data = request("GET", url, params=params).json()
        out += data.get("data", [])
        url = (data.get("paging") or {}).get("next")
        params = None                                      # o "next" já traz os parâmetros
    return out


def discover(user_token: str) -> dict:
    """Páginas e Instagrams a que o utilizador deu acesso, de TODOS os portefólios (ex.: "Carreto's" e
    "RibaMotor"), com o token de cada Página e o Instagram ligado (se houver)."""
    me = request("GET", f"{graph()}/me", params={"fields": "id,name", "access_token": user_token}).json()
    pages: dict[str, dict] = {}
    errors: list[str] = []

    def add(p: dict, business: str = "") -> None:
        cur = pages.get(p["id"]) or {"id": p["id"], "name": p.get("name", ""), "token": "", "tasks": [],
                                     "ig": None, "business": ""}
        if p.get("access_token") and not cur["token"]:
            cur["token"] = p["access_token"]
        ig = p.get("instagram_business_account")
        if ig and not cur["ig"]:
            cur["ig"] = {"id": ig["id"], "username": ig.get("username", "")}
        cur["tasks"] = cur["tasks"] or p.get("tasks", [])
        cur["business"] = cur["business"] or business
        pages[p["id"]] = cur

    for p in _paged(f"{graph()}/me/accounts", {"fields": PAGE_FIELDS, "limit": 100, "access_token": user_token}):
        add(p)
    # Páginas dos portefólios empresariais (business_management): podem não vir em /me/accounts
    try:
        businesses = _paged(f"{graph()}/me/businesses", {"fields": "id,name", "limit": 100,
                                                          "access_token": user_token})
    except Exception as exc:  # noqa: BLE001
        businesses = []
        errors.append(f"portefólios: {str(exc)[:120]}")
    for biz in businesses:
        for edge in ("owned_pages", "client_pages"):
            try:
                for p in _paged(f"{graph()}/{biz['id']}/{edge}", {"fields": PAGE_FIELDS, "limit": 100,
                                                                   "access_token": user_token}):
                    add(p, biz.get("name", ""))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{biz.get('name')}/{edge}: {str(exc)[:120]}")
    # Página sem token (vista pelo portefólio): tentar pedir o token diretamente
    for p in pages.values():
        if not p["token"]:
            try:
                r = request("GET", f"{graph()}/{p['id']}", retries=1,
                            params={"fields": "access_token,instagram_business_account{id,username}",
                                    "access_token": user_token}).json()
                p["token"] = r.get("access_token", "")
                if r.get("instagram_business_account") and not p["ig"]:
                    ig = r["instagram_business_account"]
                    p["ig"] = {"id": ig["id"], "username": ig.get("username", "")}
            except Exception:  # noqa: BLE001
                pass
    # Instagrams do portefólio SEM Página de Facebook (ex.: @davidcarretos e @carretoclips no "Carreto's"):
    # publicam pelo id do Instagram com o token de utilizador (instagram_content_publish)
    with_page = {p["ig"]["id"] for p in pages.values() if p.get("ig")}
    igs: dict[str, dict] = {}
    for biz in businesses:
        for edge in ("owned_instagram_accounts", "instagram_accounts"):
            try:
                for ig in _paged(f"{graph()}/{biz['id']}/{edge}", {"fields": "id,username", "limit": 100,
                                                                   "access_token": user_token}):
                    if ig.get("id") and ig["id"] not in with_page and ig["id"] not in igs:
                        igs[ig["id"]] = {"id": ig["id"], "username": ig.get("username", ""),
                                         "business": biz.get("name", "")}
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{biz.get('name')}/{edge}: {str(exc)[:120]}")
    expires = datetime.now().timestamp() + LAST_EXPIRES_IN
    found = {"user": me.get("name", ""), "user_id": me.get("id", ""),
             "at": datetime.now().isoformat(timespec="minutes"), "businesses": [b.get("name", "") for b in businesses],
             "pages": sorted(pages.values(), key=lambda p: (p["business"], p["name"].lower())),
             "igs": sorted(igs.values(), key=lambda i: i["username"].lower()), "errors": errors,
             "user_token": user_token,                 # só no servidor (ficheiro 600); nunca mostrado
             "user_token_expires": datetime.fromtimestamp(expires).date().isoformat()}
    _save(found)
    return found


def _path():
    return DATA_DIR / "meta.json"


def _save(found: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    p = _path()
    p.write_text(json.dumps(found, ensure_ascii=False), encoding="utf-8")
    p.chmod(0o600)                                         # tem tokens: só o utilizador da app lê


def discovered() -> dict:
    try:
        return json.loads(_path().read_text(encoding="utf-8")) if _path().exists() else {}
    except (OSError, ValueError):
        return {}


def options_for(acc: Account, found: dict | None = None) -> list[dict]:
    """Escolhas possíveis para uma conta: Páginas (contas facebook_page) ou Instagrams (contas instagram)."""
    found = found if found is not None else discovered()
    out = []
    for p in found.get("pages", []):
        biz = f" · portefólio {p['business']}" if p.get("business") else ""
        warn = "" if p.get("token") else " · ⚠ sem acesso de publicação"
        if acc.platform == "facebook_page":
            out.append({"value": f"page:{p['id']}", "label": f"Página «{p['name']}»{biz}{warn}", "name": p["name"],
                        "id": p["id"], "ok": bool(p.get("token"))})
        elif acc.platform == "instagram" and p.get("ig"):
            out.append({"value": f"ig:{p['ig']['id']}",
                        "label": f"Instagram @{p['ig']['username']} (Página «{p['name']}»{biz}){warn}",
                        "name": p["ig"]["username"], "id": p["ig"]["id"], "ok": bool(p.get("token"))})
    if acc.platform == "instagram":
        for ig in found.get("igs", []):
            biz = f" · portefólio {ig['business']}" if ig.get("business") else ""
            out.append({"value": f"igb:{ig['id']}", "label": f"Instagram @{ig['username']}{biz} (sem Página)",
                        "name": ig["username"], "id": ig["id"], "ok": bool(found.get("user_token"))})
    return out


def suggestion(acc: Account, found: dict | None = None) -> str:
    """Escolha provável (mesmo @ no Instagram; nome parecido na Página)."""
    opts = options_for(acc, found)
    for o in opts:                                          # id conhecido (accounts.yaml → meta_id)
        if acc.meta_id and o["id"] == acc.meta_id:
            return o["value"]
    handle = (acc.handle or "").lower().lstrip("@")
    for o in opts:
        if handle and o["name"].lower().lstrip("@") == handle:
            return o["value"]
    if acc.platform == "facebook_page":
        words = [w for w in re.findall(r"\w{4,}", acc.name.lower()) if w not in ("página", "facebook")]
        best, score = "", 0
        for o in opts:                                      # o nome da Página que mais palavras partilha
            n = sum(1 for w in words if w in o["name"].lower())
            if n > score:
                best, score = o["value"], n
        return best
    return ""


def link(acc: Account, choice: str, found: dict | None = None) -> dict[str, str]:
    """Liga a conta à Página/Instagram escolhido. Devolve as variáveis a guardar no .env."""
    found = found if found is not None else discovered()
    kind, _, ident = choice.partition(":")
    if kind == "igb" and acc.platform == "instagram":
        ig = next((i for i in found.get("igs", []) if i["id"] == ident), None)
        if not ig or not found.get("user_token"):
            raise ValueError("Esse Instagram não está na lista autorizada. Volte a 'Ligar com o Facebook'.")
        save_account_override(acc.id, status="ligada", handle=ig["username"] or acc.handle,
                              meta_name=f"@{ig['username']} · sem Página (portefólio {ig.get('business') or '?'})",
                              token_expires=found.get("user_token_expires"),
                              linked_at=datetime.now().isoformat(timespec="minutes"))
        return {acc.credentials["access_token_env"]: found["user_token"], acc.credentials["user_id_env"]: ident}
    for p in found.get("pages", []):
        if ((kind == "page" and p["id"] == ident) or (kind == "ig" and (p.get("ig") or {}).get("id") == ident)) \
                and not p.get("token"):
            raise ValueError(f"sem acesso de publicação à Página «{p['name']}»: no portefólio "
                             f"{p.get('business') or 'da Página'}, dê-se a função de administrador da Página e volte a "
                             "'Ligar com o Facebook'")
        if kind == "page" and p["id"] == ident and acc.platform == "facebook_page":
            updates = {acc.credentials["access_token_env"]: p["token"], acc.credentials["page_id_env"]: p["id"]}
            save_account_override(acc.id, status="ligada", handle=acc.handle or p["name"], meta_name=p["name"],
                                  linked_at=datetime.now().isoformat(timespec="minutes"))
            return updates
        if kind == "ig" and p.get("ig") and p["ig"]["id"] == ident and acc.platform == "instagram":
            updates = {acc.credentials["access_token_env"]: p["token"], acc.credentials["user_id_env"]: ident}
            save_account_override(acc.id, status="ligada", handle=p["ig"]["username"] or acc.handle,
                                  meta_name=f"@{p['ig']['username']} · Página «{p['name']}»",
                                  linked_at=datetime.now().isoformat(timespec="minutes"))
            return updates
    raise ValueError("Essa Página/Instagram não está na lista autorizada. Volte a 'Ligar com o Facebook'.")


def unlink(acc: Account) -> dict[str, str]:
    save_account_override(acc.id, status="desligada", linked_at=None, meta_name=None, token_expires=None)
    return {env: "" for env in acc.credentials.values()}


def test(acc: Account) -> tuple[bool, str]:
    """Confirma que o token funciona (nome da Página / @ do Instagram)."""
    token = acc.secret("access_token_env")
    try:
        if acc.platform == "facebook_page":
            r = request("GET", f"{graph()}/{acc.secret('page_id_env')}", retries=1,
                        params={"fields": "name", "access_token": token}).json()
            return True, f"Página «{r.get('name')}» ✓"
        if acc.platform == "instagram":
            r = request("GET", f"{graph()}/{acc.secret('user_id_env')}", retries=1,
                        params={"fields": "username", "access_token": token}).json()
            return True, f"Instagram @{r.get('username')} ✓"
    except Exception as exc:  # noqa: BLE001
        return False, f"a ligação falhou: {str(exc)[:200]}"
    return False, "esta rede não se liga pela Meta"


def meta_accounts() -> list[Account]:
    return [a for a in accounts().values() if a.platform in ("instagram", "facebook_page")]
