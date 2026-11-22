"""Ligar o LinkedIn (dashboard → Contas → "Ligar com o LinkedIn").

- Perfil pessoal: "Sign In with LinkedIn using OpenID Connect" + "Share on LinkedIn" (w_member_social).
- Página da Carretos Group: precisa da "Community Management API" (w_organization_social), que o LinkedIn
  tem de aprovar. Até lá a página fica em modo assistido (o post vai para o telemóvel).
Chaves em ⚙ Configurar: LINKEDIN_CLIENT_ID, LINKEDIN_CLIENT_SECRET e, depois da aprovação, LINKEDIN_ORG_API=sim.
Guia: docs/GUIA_LINKEDIN.md. Os tokens duram ~60 dias: o dashboard avisa para voltar a ligar.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from urllib.parse import urlencode

from .config import DATA_DIR, Account, _yes, accounts, save_account_override
from .http import request

AUTH = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN = "https://www.linkedin.com/oauth/v2/accessToken"
REST = "https://api.linkedin.com/rest"
MEMBER_SCOPES = ["openid", "profile", "w_member_social"]
ORG_SCOPES = ["w_organization_social", "r_organization_social", "rw_organization_admin"]


def configured() -> bool:
    return bool(os.environ.get("LINKEDIN_CLIENT_ID") and os.environ.get("LINKEDIN_CLIENT_SECRET"))


def org_enabled() -> bool:
    return _yes("LINKEDIN_ORG_API")


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "LinkedIn-Version": os.environ.get("LINKEDIN_VERSION", "202510"),
            "X-Restli-Protocol-Version": "2.0.0"}


def login_url(redirect_uri: str, state: str) -> str:
    scopes = MEMBER_SCOPES + (ORG_SCOPES if org_enabled() else [])
    return AUTH + "?" + urlencode({"response_type": "code", "client_id": os.environ["LINKEDIN_CLIENT_ID"],
                                   "redirect_uri": redirect_uri, "state": state, "scope": " ".join(scopes)})


def exchange(code: str, redirect_uri: str) -> dict:
    return request("POST", TOKEN, data={
        "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
        "client_id": os.environ["LINKEDIN_CLIENT_ID"], "client_secret": os.environ["LINKEDIN_CLIENT_SECRET"]}).json()


def member(token: str) -> dict:
    return request("GET", "https://api.linkedin.com/v2/userinfo", headers={"Authorization": f"Bearer {token}"}).json()


def organizations(token: str) -> list[dict]:
    """Páginas de empresa de que o utilizador é administrador (só com a Community Management API)."""
    data = request("GET", f"{REST}/organizationAcls", headers=_headers(token),
                   params={"q": "roleAssignee", "role": "ADMINISTRATOR", "state": "APPROVED"}).json()
    out = []
    for el in data.get("elements", []):
        urn = el.get("organization", "")
        oid = urn.rsplit(":", 1)[-1]
        try:
            name = request("GET", f"{REST}/organizations/{oid}", headers=_headers(token), retries=1).json() \
                .get("localizedName", "")
        except Exception:  # noqa: BLE001
            name = ""
        out.append({"urn": urn, "id": oid, "name": name or urn})
    return out


def _path():
    return DATA_DIR / "linkedin.json"


def saved() -> dict:
    try:
        return json.loads(_path().read_text(encoding="utf-8")) if _path().exists() else {}
    except (OSError, ValueError):
        return {}


def connect_member(token_data: dict) -> tuple[dict[str, str], dict]:
    """Depois da autorização: liga o perfil pessoal e guarda as páginas encontradas. Devolve (variáveis .env, info)."""
    token = token_data["access_token"]
    me = member(token)
    acc = accounts()["li_davidcarreto"]
    expires = (datetime.now() + timedelta(seconds=int(token_data.get("expires_in") or 60 * 86400))).date().isoformat()
    updates = {acc.credentials["access_token_env"]: token, acc.credentials["author_urn_env"]: f"urn:li:person:{me['sub']}"}
    save_account_override(acc.id, status="ligada", meta_name=me.get("name", ""), token_expires=expires,
                          linked_at=datetime.now().isoformat(timespec="minutes"))
    scopes = set((token_data.get("scope") or "").replace(",", " ").split())
    orgs: list[dict] = []
    if org_enabled() and "w_organization_social" in scopes:
        orgs = organizations(token)
    info = {"name": me.get("name", ""), "orgs": orgs, "at": datetime.now().isoformat(timespec="minutes"),
            "expires": expires, "token": token}
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _path().write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
    _path().chmod(0o600)
    if len(orgs) == 1 or any("carretos" in o["name"].lower() for o in orgs):   # liga já a página da empresa
        org = next((o for o in orgs if "carretos" in o["name"].lower()), orgs[0])
        updates.update(link_org(org["urn"], info))
    return updates, info


def link_org(urn: str, info: dict | None = None) -> dict[str, str]:
    info = info or saved()
    org = next((o for o in info.get("orgs", []) if o["urn"] == urn), None)
    if not org or not info.get("token"):
        raise ValueError("Essa página não está na lista autorizada. Volte a 'Ligar com o LinkedIn'.")
    acc = accounts()["li_carretosgroup"]
    save_account_override(acc.id, status="ligada", handle=acc.handle or org["name"], meta_name=f"Página «{org['name']}»",
                          token_expires=info.get("expires"), linked_at=datetime.now().isoformat(timespec="minutes"))
    return {acc.credentials["access_token_env"]: info["token"], acc.credentials["author_urn_env"]: urn}


def test(acc: Account) -> tuple[bool, str]:
    token = acc.secret("access_token_env")
    try:
        if acc.platform == "linkedin_member":
            return True, f"LinkedIn de {member(token).get('name', '?')} ✓"
        oid = (acc.secret("author_urn_env") or "").rsplit(":", 1)[-1]
        r = request("GET", f"{REST}/organizations/{oid}", headers=_headers(token), retries=1).json()
        return True, f"Página LinkedIn «{r.get('localizedName', oid)}» ✓"
    except Exception as exc:  # noqa: BLE001
        return False, f"a ligação falhou: {exc}"
