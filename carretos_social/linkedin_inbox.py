"""Comentários nos posts da PÁGINA LinkedIn Carretos Group (2.ª app, Community Management API).

De N em N minutos (LINKEDIN_COMMENTS_MINUTES, 60 por omissão) o agendador lê os comentários novos dos posts da
página dos últimos 30 dias (GET /rest/socialActions/{post}/comments) e passa-os ao mesmo fluxo
das respostas do Instagram/Facebook (inbox.process): categoria, resposta proposta ou enviada, avisos.
Responde como página: POST /rest/socialActions/{comentário}/comments com actor = página e parentComment.

Guarda só o necessário: URN do comentário, URN de quem comentou, texto, data e o post. Não lê perfis.
Não responde a comentários da própria página nem a comentários anteriores à ativação.
O perfil pessoal fica de fora: o LinkedIn só dá a leitura (r_member_social) a parceiros aprovados.

Limites do Nível de Desenvolvimento da Community Management API (documentação do LinkedIn, "Increasing Access"):
500 pedidos por app e 100 pedidos por membro em 24 h (repõem à meia-noite UTC). Todos os pedidos da página saem
com o token do David, por isso os comentários têm um ORÇAMENTO diário próprio (LINKEDIN_COMMENTS_DAILY_CALLS, 60
por omissão), deixando margem para publicar e para as métricas: a lista de posts é lida de 6 em 6 horas e, em cada
leitura, só se veem tantos posts quantos o orçamento deixa (os mais recentes primeiro; os outros em rotação).
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
SCOPES_HELP = ("o LinkedIn recusou o acesso aos comentários (403). Volte a 'Ligar a página da empresa' em Contas "
               "(o Carretos Studio pede agora também r_organization_social_feed e w_organization_social_feed) e "
               "aceite as autorizações; a app da página tem de ter a Community Management API.")


def interval_minutes() -> int:
    try:
        return max(15, int(os.environ.get("LINKEDIN_COMMENTS_MINUTES", "60")))
    except ValueError:
        return 60


def daily_budget() -> int:
    try:
        return max(10, min(90, int(os.environ.get("LINKEDIN_COMMENTS_DAILY_CALLS", "60"))))
    except ValueError:
        return 60


class BudgetExceeded(RuntimeError):
    """Orçamento diário de pedidos ao LinkedIn para os comentários esgotado (repõe à meia-noite UTC)."""


def _budget_path():
    from . import config as _cfg
    return _cfg.DATA_DIR / "linkedin_orcamento.json"


def _today() -> str:
    from datetime import timezone
    return datetime.now(timezone.utc).date().isoformat()


def _budget_state() -> dict:
    import json
    try:
        st = json.loads(_budget_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st = {}
    if st.get("day") != _today():
        st = {"day": _today(), "calls": 0, "rot": st.get("rot", 0), "posts": st.get("posts", []),
              "posts_at": st.get("posts_at", 0)}
    return st


def _budget_save(st: dict) -> None:
    import json
    _budget_path().parent.mkdir(parents=True, exist_ok=True)
    _budget_path().write_text(json.dumps(st), encoding="utf-8")


def calls_today() -> int:
    return _budget_state().get("calls", 0)


def _spend(n: int = 1, force: bool = False) -> None:
    st = _budget_state()
    if not force and st["calls"] + n > daily_budget():
        raise BudgetExceeded(f"limite diário de {daily_budget()} pedidos para os comentários atingido "
                             "(o LinkedIn dá 100 por dia a cada membro no Nível de Desenvolvimento); continua amanhã")
    st["calls"] += n
    _budget_save(st)


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


def _call(method: str, url: str, acc: Account, force: bool = False, **kw):
    """Pedido ao LinkedIn, contado no orçamento diário (force=True: responder a um comentário aprovado à mão
    conta mas nunca é bloqueado)."""
    from .http import ApiError
    _spend(1, force=force)
    try:
        return rest(method, url, headers=_h(acc), retries=1, timeout=30, **kw)
    except ApiError as exc:
        if "-> 403" in str(exc):
            raise ApiError(SCOPES_HELP + f" Detalhe: {str(exc)[:300]}") from exc
        raise


def recent_posts(acc: Account, days: int = 30) -> list[str]:
    """Posts da página dos últimos 30 dias (mais recentes primeiro). A lista é lida de 6 em 6 horas."""
    st = _budget_state()
    limit = (time.time() - days * 86400) * 1000
    if time.time() - st.get("posts_at", 0) > 6 * 3600 or not st.get("posts"):
        data = _call("GET", f"{REST}/posts", acc, params={"q": "author", "author": _org(acc), "count": 30,
                                                          "sortBy": "CREATED"}).json()
        st = _budget_state()
        st["posts"] = [[p["id"], p.get("publishedAt") or p.get("createdAt") or 0]
                       for p in data.get("elements", []) if p.get("id")]
        st["posts_at"] = time.time()
        _budget_save(st)
    return [pid for pid, t in sorted(st["posts"], key=lambda x: -x[1]) if t >= limit]


def posts_this_round(posts: list[str]) -> list[str]:
    """Quantos posts ver nesta leitura, para o orçamento chegar até à meia-noite UTC: o mais recente sempre que
    possível e os outros em rotação."""
    from datetime import timezone
    if not posts:
        return []
    st = _budget_state()
    now = datetime.now(timezone.utc)
    secs_left = (now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1) - now).total_seconds()
    rounds_left = max(1, int(secs_left // (interval_minutes() * 60)) + 1)
    reserve = 6                                          # para verificar respostas e responder
    allowance = max(0, (daily_budget() - reserve - st["calls"]) // rounds_left)
    allowance = min(len(posts), max(1 if st["calls"] < daily_budget() - reserve else 0, allowance))
    if allowance == 0:
        return []
    chosen = [posts[0]]
    rest_posts = posts[1:]
    if rest_posts and allowance > 1:
        start = st.get("rot", 0) % len(rest_posts)
        rot = (rest_posts[start:] + rest_posts[:start])[:allowance - 1]
        chosen += rot
        st["rot"] = start + len(rot)
        _budget_save(st)
    return chosen


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
    r = _call("POST", f"{REST}/socialActions/{quote(comment_urn, safe='')}/comments", acc, force=True, json=body)
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
    try:
        posts = recent_posts(acc)
        checking = posts if include_old else posts_this_round(posts)
    except BudgetExceeded as exc:
        return [f"LinkedIn comentários: {exc}"]
    new_ids, seen = [], 0
    with connect() as conn:
        for post in checking:
            try:
                found = comments(acc, post)
            except BudgetExceeded:
                break
            for c in found:
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
    lines = [f"LinkedIn comentários: {len(checking)} de {len(posts)} posts (30 dias) vistos, {seen} comentários lidos, "
             f"{len(new_ids)} novos · pedidos hoje {calls_today()}/{daily_budget()}"]
    for iid in new_ids:
        lines.append(f"LinkedIn comentário #{iid}: {inbox.process(iid, force_propose=include_old)}")
    return lines


_last_fail_alert = 0.0


def poll_safe() -> list[str]:
    """Para o agendador: nunca rebenta; se a leitura falhar, avisa no Telegram (no máximo de 6 em 6 horas)."""
    global _last_fail_alert
    try:
        return poll()
    except BudgetExceeded as exc:
        return [f"LinkedIn comentários: {exc}"]
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
