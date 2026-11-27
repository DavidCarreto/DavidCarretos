"""Ligar o LinkedIn (dashboard → Contas → "Ligar com o LinkedIn").

- Perfil pessoal: "Sign In with LinkedIn using OpenID Connect" + "Share on LinkedIn" (w_member_social).
- Página da Carretos Group: precisa da "Community Management API" (w_organization_social), que o LinkedIn
  só deixa ter numa app SÓ para ela e tem de aprovar. Até lá a página fica em modo assistido.
Chaves em ⚙ Configurar: app do perfil (LINKEDIN_CLIENT_ID/SECRET), 2.ª app da página
(LINKEDIN_ORG_CLIENT_ID/SECRET) e, depois da aprovação, LINKEDIN_ORG_API=sim.
Guia: docs/GUIA_LINKEDIN.md. Os tokens duram ~60 dias: o dashboard avisa para voltar a ligar.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta
from urllib.parse import urlencode

from . import config as _cfg
from .config import Account, _yes, accounts, save_account_override
from .http import request

AUTH = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN = "https://www.linkedin.com/oauth/v2/accessToken"
REST = "https://api.linkedin.com/rest"
MEMBER_SCOPES = ["openid", "profile", "w_member_social"]
# *_feed: ler e escrever comentários/reações da página (socialActions), pedidos pela Community Management API
ORG_SCOPES = ["w_organization_social", "r_organization_social", "rw_organization_admin",
              "r_organization_social_feed", "w_organization_social_feed"]


APPS = {"perfil": ("LINKEDIN_CLIENT_ID", "LINKEDIN_CLIENT_SECRET"),
        "pagina": ("LINKEDIN_ORG_CLIENT_ID", "LINKEDIN_ORG_CLIENT_SECRET")}


def configured(app: str = "perfil") -> bool:
    cid, secret = APPS[app]
    return bool(os.environ.get(cid) and os.environ.get(secret))


def org_enabled() -> bool:
    """Página da empresa: 2.ª app configurada e Community Management API aprovada."""
    return configured("pagina") and _yes("LINKEDIN_ORG_API")


def _months_back(n: int, start: datetime | None = None) -> str:
    d = (start or datetime.now()).replace(day=1)
    for _ in range(n):
        d = (d - timedelta(days=1)).replace(day=1)
    return d.strftime("%Y%m")


def _valid(v: str) -> bool:
    """AAAAMM dos últimos 11 meses (o LinkedIn desliga cada versão ao fim de ~1 ano)."""
    return bool(re.fullmatch(r"\d{6}", v or "")) and _months_back(11) <= v <= datetime.now().strftime("%Y%m")


def api_version() -> str:
    """Versão da API REST do LinkedIn (cabeçalho LinkedIn-Version, AAAAMM), usada em TODOS os pedidos (perfil e
    página). Ordem: LINKEDIN_VERSION do .env, se ainda for recente; a última que funcionou (guardada); senão a
    de há 2 meses. Um LINKEDIN_VERSION antigo (ex.: 202510 copiado do .env.example) é ignorado."""
    env = os.environ.get("LINKEDIN_VERSION", "").strip()
    if _valid(env):
        return env
    try:
        saved = (_cfg.DATA_DIR / "linkedin_version.txt").read_text().strip()
        if _valid(saved):
            return saved
    except OSError:
        pass
    return _months_back(2)


def rest(method: str, url: str, headers: dict | None = None, **kwargs):
    """Pedido à API REST do LinkedIn com a versão certa. Se o LinkedIn responder que a versão não está ativa
    (426 NONEXISTENT_VERSION), tenta as dos meses anteriores e guarda a que funcionar."""
    from .http import ApiError
    headers = {"X-Restli-Protocol-Version": "2.0.0", **(headers or {})}
    version = api_version()
    for _ in range(12):
        headers["LinkedIn-Version"] = version
        try:
            resp = request(method, url, headers=headers, **kwargs)
        except ApiError as exc:
            if "NONEXISTENT_VERSION" not in str(exc) and "-> 426" not in str(exc):
                raise
            version = _months_back(1, datetime.strptime(version, "%Y%m"))
            continue
        if version != api_version():
            _cfg.DATA_DIR.mkdir(parents=True, exist_ok=True)
            (_cfg.DATA_DIR / "linkedin_version.txt").write_text(version)
        return resp
    raise ApiError("O LinkedIn não aceitou nenhuma versão da API dos últimos 12 meses.")


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def login_url(redirect_uri: str, state: str, app: str = "perfil") -> str:
    scopes = MEMBER_SCOPES if app == "perfil" else ORG_SCOPES
    return AUTH + "?" + urlencode({"response_type": "code", "client_id": os.environ[APPS[app][0]],
                                   "redirect_uri": redirect_uri, "state": state, "scope": " ".join(scopes)})


def exchange(code: str, redirect_uri: str, app: str = "perfil") -> dict:
    cid, secret = APPS[app]
    return request("POST", TOKEN, data={
        "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
        "client_id": os.environ[cid], "client_secret": os.environ[secret]}).json()


def member(token: str) -> dict:
    return request("GET", "https://api.linkedin.com/v2/userinfo", headers={"Authorization": f"Bearer {token}"}).json()


def organizations(token: str) -> list[dict]:
    """Páginas de empresa de que o utilizador é administrador (só com a Community Management API)."""
    data = rest("GET", f"{REST}/organizationAcls", headers=_headers(token),
                   params={"q": "roleAssignee", "role": "ADMINISTRATOR", "state": "APPROVED"}).json()
    out = []
    for el in data.get("elements", []):
        urn = el.get("organization", "")
        oid = urn.rsplit(":", 1)[-1]
        try:
            name = rest("GET", f"{REST}/organizations/{oid}", headers=_headers(token), retries=1).json() \
                .get("localizedName", "")
        except Exception:  # noqa: BLE001
            name = ""
        out.append({"urn": urn, "id": oid, "name": name or urn, "assignee": el.get("roleAssignee", "")})
    return out


class WrongAccount(ValueError):
    """A autorização foi dada com outra conta LinkedIn (não guardar nada)."""


def _retry_msg(who: str) -> str:
    return (f"Está com {who}. Termine a sessão no LinkedIn, entre com a conta David Carreto e tente outra vez.")


def _path():
    return _cfg.DATA_DIR / "linkedin.json"


def saved() -> dict:
    try:
        return json.loads(_path().read_text(encoding="utf-8")) if _path().exists() else {}
    except (OSError, ValueError):
        return {}


def _save(**fields) -> dict:
    info = {**saved(), **fields}
    _cfg.DATA_DIR.mkdir(parents=True, exist_ok=True)
    _path().write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
    _path().chmod(0o600)                                   # tem tokens: só o utilizador da app lê
    return info


def _expires(token_data: dict) -> str:
    return (datetime.now() + timedelta(seconds=int(token_data.get("expires_in") or 60 * 86400))).date().isoformat()


def connect_member(token_data: dict) -> tuple[dict[str, str], dict]:
    """App do perfil: liga o LinkedIn pessoal. Devolve (variáveis .env, info)."""
    token = token_data["access_token"]
    me = member(token)
    acc = accounts()["li_davidcarreto"]
    # proteção contra conta errada: tem de ser a mesma conta do perfil já ligado (se houver)
    expected = (saved().get("member_sub") or (acc.secret("author_urn_env") or "").rsplit(":", 1)[-1]).strip()
    if expected and me.get("sub") != expected:
        raise WrongAccount(_retry_msg(f"a conta LinkedIn «{me.get('name') or 'desconhecida'}»"))
    expires = _expires(token_data)
    updates = {acc.credentials["access_token_env"]: token, acc.credentials["author_urn_env"]: f"urn:li:person:{me['sub']}"}
    save_account_override(acc.id, status="ligada", meta_name=me.get("name", ""), token_expires=expires,
                          linked_at=datetime.now().isoformat(timespec="minutes"))
    info = _save(name=me.get("name", ""), member_sub=me.get("sub", ""),
                 at=datetime.now().isoformat(timespec="minutes"), expires=expires)
    return updates, info


def connect_org(token_data: dict) -> tuple[dict[str, str], dict]:
    """2.ª app (Community Management API): encontra as páginas e liga a da Carretos Group (se for clara)."""
    token = token_data["access_token"]
    orgs = organizations(token)
    # proteção contra conta errada: a conta autorizada tem de ser administradora da página Carretos Group
    # (esta app não tem acesso ao nome da conta; uma conta errada não administra a página)
    if not any("carretos" in o["name"].lower() for o in orgs):
        raise WrongAccount(_retry_msg("uma conta LinkedIn que não é administradora da página Carretos Group"
                                      + (f" (administra: {', '.join(o['name'] for o in orgs)})" if orgs else "")))
    assignee = next((o.get("assignee") for o in orgs if "carretos" in o["name"].lower()), "")
    member_urn = f"urn:li:person:{saved().get('member_sub')}" if saved().get("member_sub") else ""
    info = _save(orgs=orgs, org_token=token, org_expires=_expires(token_data),
                 org_at=datetime.now().isoformat(timespec="minutes"), org_assignee=assignee,
                 org_same_as_member=bool(member_urn and assignee == member_urn))
    updates: dict[str, str] = {}
    if len(orgs) == 1 or any("carretos" in o["name"].lower() for o in orgs):
        org = next((o for o in orgs if "carretos" in o["name"].lower()), orgs[0])
        updates = link_org(org["urn"], info)
    return updates, info


def link_org(urn: str, info: dict | None = None) -> dict[str, str]:
    info = info or saved()
    org = next((o for o in info.get("orgs", []) if o["urn"] == urn), None)
    if not org or not info.get("org_token"):
        raise ValueError("Essa página não está na lista autorizada. Volte a 'Ligar a página da empresa'.")
    acc = accounts()["li_carretosgroup"]
    save_account_override(acc.id, status="ligada", handle=acc.handle or org["name"], meta_name=f"Página «{org['name']}»",
                          token_expires=info.get("org_expires"), linked_at=datetime.now().isoformat(timespec="minutes"))
    return {acc.credentials["access_token_env"]: info["org_token"], acc.credentials["author_urn_env"]: urn}


def test(acc: Account) -> tuple[bool, str]:
    token = acc.secret("access_token_env")
    try:
        if acc.platform == "linkedin_member":
            return True, f"LinkedIn de {member(token).get('name', '?')} ✓"
        oid = (acc.secret("author_urn_env") or "").rsplit(":", 1)[-1]
        r = rest("GET", f"{REST}/organizations/{oid}", headers=_headers(token), retries=1).json()
        return True, f"Página LinkedIn «{r.get('localizedName', oid)}» ✓"
    except Exception as exc:  # noqa: BLE001
        return False, f"a ligação falhou: {exc}"


def followers(acc: Account) -> int | None:
    """Nº de seguidores da página (para a pré-visualização). Guardado 24 h; None se a API não o der."""
    info = saved()
    at = info.get("org_followers_at", "")
    if at and datetime.fromisoformat(at) > datetime.now() - timedelta(hours=24):
        return info.get("org_followers")
    token, urn = acc.secret("access_token_env"), acc.secret("author_urn_env") or ""
    if not token or not urn:
        return None
    n = None
    try:
        from urllib.parse import quote
        r = rest("GET", f"{REST}/networkSizes/{quote(urn, safe='')}", headers=_headers(token),
                 params={"edgeType": "COMPANY_FOLLOWED_BY_MEMBER"}, retries=1, timeout=8).json()
        n = int(r["firstDegreeSize"]) if "firstDegreeSize" in r else None
    except Exception:  # noqa: BLE001
        n = None
    _save(org_followers=n, org_followers_at=datetime.now().isoformat(timespec="minutes"))
    return n
