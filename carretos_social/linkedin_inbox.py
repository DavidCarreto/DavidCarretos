"""Comentários nos posts da PÁGINA LinkedIn Carretos Group (2.ª app, Community Management API).

De N em N minutos (LINKEDIN_COMMENTS_MINUTES, 10 por omissão) o agendador percorre os posts da página dos
últimos 30 dias, lê os comentários novos (GET /rest/socialActions/{post}/comments) e passa-os ao mesmo fluxo
das respostas do Instagram/Facebook (inbox.process): categoria, resposta proposta ou enviada, avisos.
Responde como página: POST /rest/socialActions/{comentário}/comments com actor = página e parentComment.

Guarda só o necessário: URN do comentário, URN de quem comentou, texto, data e o post. Não lê perfis.
Não responde a comentários da própria página nem a comentários anteriores à ativação.
O perfil pessoal fica de fora: o LinkedIn só dá a leitura (r_member_social) a parceiros aprovados.
"""
from __future__ import annotations

import os
import re
import time
from datetime import datetime, timedelta
from urllib.parse import quote

from .config import Account, accounts
from .linkedin_connect import REST, rest

ORG_ACCOUNT = "li_carretosgroup"
SCOPES_HELP = ("o LinkedIn recusou o acesso aos comentários (403). Confirme na 2.ª app (página) que a "
               "Community Management API está aprovada e volte a 'Ligar a página da empresa' em Contas; se o erro "
               "falar em r_organization_social_feed / w_organization_social_feed, essas autorizações têm de ser "
               "acrescentadas à app.")


def interval_minutes() -> int:
    try:
        return max(2, int(os.environ.get("LINKEDIN_COMMENTS_MINUTES", "10")))
    except ValueError:
        return 10


def org_account() -> Account | None:
    acc = accounts().get(ORG_ACCOUNT)
    return acc if acc and acc.has_credentials else None


def _h(acc: Account) -> dict:
    return {"Authorization": f"Bearer {acc.secret('access_token_env')}", "Content-Type": "application/json"}


def _org(acc: Account) -> str:
    return acc.secret("author_urn_env") or ""


def _thread(comment_urn: str) -> str:
    """urn:li:comment:(urn:li:activity:123,456) → urn:li:activity:123"""
    m = re.match(r"urn:li:comment:\((urn:li:[a-zA-Z]+:\d+),\d+\)", comment_urn or "")
    return m.group(1) if m else ""


def _call(method: str, url: str, acc: Account, **kw):
    from .http import ApiError
    try:
        return rest(method, url, headers=_h(acc), retries=1, timeout=30, **kw)
    except ApiError as exc:
        if "-> 403" in str(exc):
            raise ApiError(SCOPES_HELP + f" Detalhe: {str(exc)[:300]}") from exc
        raise


def recent_posts(acc: Account, days: int = 30) -> list[str]:
    data = _call("GET", f"{REST}/posts", acc, params={"q": "author", "author": _org(acc), "count": 50,
                                                      "sortBy": "CREATED"}).json()
    limit = (time.time() - days * 86400) * 1000
    return [p["id"] for p in data.get("elements", [])
            if (p.get("publishedAt") or p.get("createdAt") or 0) >= limit and p.get("id")]


def comments(acc: Account, post_urn: str) -> list[dict]:
    data = _call("GET", f"{REST}/socialActions/{quote(post_urn, safe='')}/comments", acc,
                 params={"count": 100}).json()
    out = []
    for c in data.get("elements", []):
        out.append({"urn": c.get("commentUrn") or "", "actor": c.get("actor") or (c.get("created") or {}).get("actor", ""),
                    "text": ((c.get("message") or {}).get("text") or "").strip(),
                    "time": int((c.get("created") or {}).get("time") or 0), "post": post_urn})
    return out


def page_replied(acc: Account, comment_urn: str) -> bool:
    """A página já respondeu a este comentário (alguém da equipa no LinkedIn)? Em caso de dúvida, False."""
    try:
        data = _call("GET", f"{REST}/socialActions/{quote(comment_urn, safe='')}/comments", acc,
                     params={"count": 50}).json()
        return any((c.get("actor") or "") == _org(acc) for c in data.get("elements", []))
    except Exception:  # noqa: BLE001
        return False


def reply(acc: Account, comment_urn: str, text: str) -> str:
    """Resposta da página no fio do comentário."""
    body = {"actor": _org(acc), "object": _thread(comment_urn), "parentComment": comment_urn,
            "message": {"text": text}}
    r = _call("POST", f"{REST}/socialActions/{quote(comment_urn, safe='')}/comments", acc, json=body)
    return r.headers.get("x-restli-id", "")


def poll(include_old: bool = False) -> list[str]:
    """Lê os comentários novos e trata-os. Devolve linhas para o registo do agendador (sem tokens).
    include_old=True (botão em Mensagens): traz também os anteriores à ativação, só como propostas."""
    from . import inbox
    from .db import connect, now
    acc = org_account()
    if not acc:
        return []
    st = inbox.account_settings(acc.id)
    if not st.get("enabled") and not include_old:
        return []
    since = st.get("enabled_at") or now()
    since_ms = datetime.fromisoformat(since[:19]).timestamp() * 1000
    posts = recent_posts(acc)
    new_ids, seen = [], 0
    with connect() as conn:
        for post in posts:
            for c in comments(acc, post):
                seen += 1
                if not c["urn"] or c["actor"] == _org(acc) or (c["time"] < since_ms and not include_old):
                    continue                      # da própria página, ou anterior à ativação
                if conn.execute("SELECT 1 FROM inbox WHERE external_id=?", (c["urn"],)).fetchone():
                    continue
                new_ids.append(conn.execute(
                    "INSERT INTO inbox(account_id, network, kind, external_id, author_id, author, text, context, "
                    "status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (acc.id, "linkedin", "comment", c["urn"], c["actor"], "", c["text"][:3000], post, "novo",
                     now())).lastrowid)
    lines = [f"LinkedIn comentários: {len(posts)} posts (30 dias), {seen} comentários lidos, {len(new_ids)} novos"]
    for iid in new_ids:
        lines.append(f"LinkedIn comentário #{iid}: {inbox.process(iid, force_propose=include_old)}")
    return lines


_last_fail_alert = 0.0


def poll_safe() -> list[str]:
    """Para o agendador: nunca rebenta; se a leitura falhar, avisa no Telegram (no máximo de 6 em 6 horas)."""
    global _last_fail_alert
    try:
        return poll()
    except Exception as exc:  # noqa: BLE001
        from .redact import redact
        msg = redact(str(exc))[:600]
        if time.time() - _last_fail_alert > 6 * 3600:
            _last_fail_alert = time.time()
            try:
                from . import notify
                notify.send(f"⚠️ Não consegui ler os comentários da página LinkedIn Carretos Group: {msg}")
            except Exception:  # noqa: BLE001
                pass
        return [f"LinkedIn comentários: falhou — {msg}"]
