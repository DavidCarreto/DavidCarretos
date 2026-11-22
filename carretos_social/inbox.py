"""Respostas automáticas a comentários e mensagens (Instagram e Páginas de Facebook), a encaminhar para o
assistente do WhatsApp (preço, orçamento, serviços e marcação, 24 horas).

Fluxo: a Meta entrega cada comentário/mensagem no webhook (/webhooks/meta) → fica na caixa de entrada (tabela
inbox) → se as respostas automáticas estiverem ligadas nessa conta, a IA classifica e escreve uma resposta curta
(com o link do WhatsApp) → resposta pública ao comentário (+ mensagem privada, se ligado) ou resposta à mensagem.

Proteções: desligado por defeito em cada conta; nunca responde à própria conta; uma resposta por comentário;
nas mensagens privadas, uma resposta automática por pessoa em 24 h (a conversa segue no WhatsApp); spam e
ofensas não são respondidos; reclamações e urgências avisam o David pelo Telegram.
Atenção: com a app da Meta em modo de desenvolvimento só chegam eventos de quem tem função na app.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
from datetime import datetime, timedelta

from .config import DATA_DIR, Account, accounts
from .db import connect, now

DEFAULT_WHATSAPP = "https://wa.me/351211454646"
FALLBACK = {
    "comment": "Obrigado pelo seu comentário! Para saber o preço, pedir orçamento ou marcar, fale connosco no "
               "WhatsApp: {wa} (resposta imediata, 24 horas).",
    "private": "Olá! Obrigado pelo comentário. No nosso WhatsApp tem resposta imediata, 24 horas, com preço, "
               "orçamento e marcação: {wa}",
    "message": "Olá! Obrigado pela mensagem. Para uma resposta imediata (preço, orçamento e marcação, 24 horas), "
               "fale connosco no WhatsApp: {wa}",
}


# ------------------------------------------------------------------ definições por conta
def _settings_path():
    return DATA_DIR / "respostas.json"


def settings() -> dict:
    try:
        return json.loads(_settings_path().read_text(encoding="utf-8")) if _settings_path().exists() else {}
    except (OSError, ValueError):
        return {}


def account_settings(acc_id: str) -> dict:
    return {"enabled": False, "private": True, **(settings().get(acc_id) or {})}


def save_account_settings(acc_id: str, **fields) -> None:
    data = settings()
    data.setdefault(acc_id, {}).update(fields)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _settings_path().write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def eligible_accounts() -> list[Account]:
    return [a for a in accounts().values() if a.platform in ("instagram", "facebook_page") and a.has_credentials]


def whatsapp_link(acc: Account) -> str:
    """Link do WhatsApp da base de conhecimento da marca (ficha de contacto com wa.me), senão o da Carretos."""
    try:
        from . import knowledge
        from .config import facts_brand
        for i in knowledge.for_brand(facts_brand(acc.id), acc.id):
            if i["section"] == "contactos" and i["status"] == "publicavel" and "wa.me" in (i["value"] or ""):
                return i["value"]
    except Exception:  # noqa: BLE001
        pass
    return os.environ.get("INBOX_WHATSAPP_LINK", DEFAULT_WHATSAPP)


# ------------------------------------------------------------------ webhook
def verify_token() -> str:
    """Token de verificação do webhook (gerado uma vez e guardado no .env)."""
    tok = os.environ.get("META_WEBHOOK_VERIFY_TOKEN")
    if not tok:
        import secrets
        from .envfile import set_env
        tok = "cs-" + secrets.token_urlsafe(18)
        set_env({"META_WEBHOOK_VERIFY_TOKEN": tok})
    return tok


def valid_signature(body: bytes, header: str) -> bool:
    secret = os.environ.get("META_APP_SECRET", "")
    if not secret or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.split("=", 1)[1])


def own_ids() -> set[str]:
    """Ids de todas as Páginas e Instagrams ligados ao Carretos Studio (para nunca responder a contas nossas)."""
    ids: set[str] = set()
    for a in eligible_accounts():
        for key in ("page_id_env", "user_id_env"):
            if a.secret(key):
                ids.add(str(a.secret(key)))
    try:
        from .meta_connect import discovered
        for p in discovered().get("pages", []):
            ids.add(str(p["id"]))
            if p.get("ig"):
                ids.add(str(p["ig"]["id"]))
    except Exception:  # noqa: BLE001
        pass
    return ids


def own_handles() -> set[str]:
    out = {"davidcarretos", "carretoclips", "carretos_group", "_auron_2026"}
    for a in accounts().values():
        if a.platform in ("instagram", "facebook_page") and a.handle:
            out.add(a.handle.lower().lstrip("@"))
    try:
        from .meta_connect import discovered
        for p in discovered().get("pages", []):
            out.add((p.get("name") or "").lower())
            if p.get("ig") and p["ig"].get("username"):
                out.add(p["ig"]["username"].lower())
    except Exception:  # noqa: BLE001
        pass
    out.discard("")
    return out


def is_own(author_id: str, author: str) -> bool:
    return (bool(author_id) and author_id in own_ids()) or ((author or "").lower().lstrip("@") in own_handles())


def _account_for(network: str, entry_id: str) -> Account | None:
    for a in eligible_accounts():
        if network == "facebook" and a.platform == "facebook_page" and a.secret("page_id_env") == entry_id:
            return a
        if network == "instagram" and a.platform == "instagram" and a.secret("user_id_env") == entry_id:
            return a
    return None


def parse(payload: dict) -> list[dict]:
    """Eventos de um webhook da Meta → [{account_id, network, kind, external_id, author_id, author, text, context}]."""
    obj = payload.get("object")
    network = "instagram" if obj == "instagram" else "facebook" if obj == "page" else ""
    out = []
    for entry in payload.get("entry", []) or []:
        acc = _account_for(network, str(entry.get("id", "")))
        own = str(entry.get("id", ""))
        for ch in entry.get("changes", []) or []:
            v = ch.get("value") or {}
            if network == "facebook" and ch.get("field") == "feed" and v.get("item") == "comment" and v.get("verb") == "add":
                frm = v.get("from") or {}
                out.append({"account_id": acc.id if acc else None, "network": network, "kind": "comment",
                            "external_id": v.get("comment_id"), "author_id": str(frm.get("id", "")),
                            "author": frm.get("name", ""), "text": v.get("message", ""),
                            "context": v.get("post_id", ""), "own": own})
            elif network == "instagram" and ch.get("field") == "comments":
                frm = v.get("from") or {}
                out.append({"account_id": acc.id if acc else None, "network": network, "kind": "comment",
                            "external_id": v.get("id"), "author_id": str(frm.get("id", "")),
                            "author": frm.get("username", ""), "text": v.get("text", ""),
                            "context": (v.get("media") or {}).get("id", ""), "own": own})
        for m in entry.get("messaging", []) or []:
            msg = m.get("message") or {}
            if not msg or msg.get("is_echo") or not msg.get("text"):
                continue
            # a conta é a do DESTINATÁRIO (quando duas contas nossas conversam, a Meta avisa as duas)
            recipient = str((m.get("recipient") or {}).get("id", ""))
            racc = _account_for(network, recipient) or (acc if recipient in ("", own) else None)
            out.append({"account_id": racc.id if racc else None, "network": network, "kind": "message",
                        "external_id": msg.get("mid"), "author_id": str((m.get("sender") or {}).get("id", "")),
                        "author": "", "text": msg.get("text", ""), "context": "", "own": recipient or own})
    return [e for e in out if e["external_id"]]


def log_event(payload: dict | None, signature_ok: bool) -> None:
    """Guarda um resumo dos últimos 100 avisos recebidos da Meta (sem tokens) para diagnóstico."""
    entries = []
    for e in (payload or {}).get("entry", []) or []:
        changes = [{"field": c.get("field"), "item": (c.get("value") or {}).get("item"),
                    "verb": (c.get("value") or {}).get("verb"),
                    "from": ((c.get("value") or {}).get("from") or {}).get("name")
                    or ((c.get("value") or {}).get("from") or {}).get("username"),
                    "text": ((c.get("value") or {}).get("message") or (c.get("value") or {}).get("text") or "")[:120]}
                   for c in e.get("changes", []) or []]
        msgs = [{"sender": str((m.get("sender") or {}).get("id", "")), "recipient": str((m.get("recipient") or {}).get("id", "")),
                 "echo": bool((m.get("message") or {}).get("is_echo")),
                 "text": ((m.get("message") or {}).get("text") or "")[:120]} for m in e.get("messaging", []) or []]
        entries.append({"id": str(e.get("id", "")), "changes": changes, "messaging": msgs})
    path = DATA_DIR / "webhooks.json"
    try:
        items = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    except (OSError, ValueError):
        items = []
    items.insert(0, {"at": now(), "signature_ok": signature_ok, "object": (payload or {}).get("object"),
                     "entries": entries})
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items[:100], ensure_ascii=False), encoding="utf-8")


def recent_events() -> list[dict]:
    path = DATA_DIR / "webhooks.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    except (OSError, ValueError):
        return []


def receive(payload: dict, background: bool = True) -> list[int]:
    """Guarda os eventos novos e responde (em segundo plano, para o webhook responder logo à Meta)."""
    ids = []
    with connect() as conn:
        for e in parse(payload):
            if conn.execute("SELECT 1 FROM inbox WHERE external_id=?", (e["external_id"],)).fetchone():
                continue                                          # a Meta pode reenviar o mesmo evento
            status, note = "novo", None
            if e["author_id"] and e["author_id"] == e["own"]:
                status, note = "ignorado", "escrito pela própria conta"
            elif is_own(e["author_id"], e["author"]):
                status, note = "ignorado", "conta nossa (não se responde a contas ligadas ao Carretos Studio)"
            elif not e["account_id"]:
                status, note = "ignorado", "conta não ligada no Carretos Studio"
            ids.append(conn.execute(
                "INSERT INTO inbox(account_id, network, kind, external_id, author_id, author, text, context, status, "
                "note, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (e["account_id"], e["network"], e["kind"], e["external_id"], e["author_id"], e["author"], e["text"],
                 e["context"], status, note, now())).lastrowid)
    for iid in ids:
        if background:
            threading.Thread(target=process, args=(iid, delay()), daemon=True).start()
        else:
            process(iid)
    return ids


def delay() -> int:
    """Segundos de espera antes de responder (para ver se o Business Suite ou alguém da equipa já respondeu)."""
    try:
        return max(0, int(os.environ.get("INBOX_DELAY_SECONDS", "60")))
    except ValueError:
        return 60


def process_pending() -> int:
    """No arranque do dashboard: responde aos eventos que ficaram por tratar (ex.: reinício durante a espera)."""
    limit = (datetime.now() - timedelta(hours=24)).isoformat(timespec="seconds")
    with connect() as conn:
        ids = [r["id"] for r in conn.execute("SELECT id FROM inbox WHERE status='novo' AND created_at >= ?", (limit,))]
    for iid in ids:
        threading.Thread(target=process, args=(iid, 5), daemon=True).start()
    return len(ids)


def already_answered(acc: Account, row) -> bool:
    """A conta já respondeu (automação do Meta Business Suite ou uma pessoa)? Em caso de dúvida, False."""
    from .http import request
    from .meta_connect import graph
    token = acc.secret("access_token_env")
    mine = own_ids() | {str(acc.secret("page_id_env") or ""), str(acc.secret("user_id_env") or "")}
    handles = own_handles()
    try:
        if row["kind"] == "comment":
            edge = "replies" if acc.platform == "instagram" else "comments"
            data = request("GET", f"{graph()}/{row['external_id']}/{edge}", retries=1,
                           params={"fields": "from,username", "limit": 25, "access_token": token}).json()
            for c in data.get("data", []):
                frm = c.get("from") or {}
                if str(frm.get("id", "")) in mine or (c.get("username") or frm.get("username") or "").lower() in handles:
                    return True
            return False
        platform = "instagram" if acc.platform == "instagram" else "messenger"
        data = request("GET", f"{graph()}/me/conversations", retries=1, params={
            "platform": platform, "user_id": row["author_id"], "access_token": token,
            "fields": "messages.limit(5){from,created_time}"}).json()
        for conv in data.get("data", []):
            msgs = (conv.get("messages") or {}).get("data", [])
            if msgs and str((msgs[0].get("from") or {}).get("id", "")) in mine:   # a mais recente é nossa
                return True
    except Exception:  # noqa: BLE001
        return False
    return False


# ------------------------------------------------------------------ decidir e responder
def compose(acc: Account, kind: str, text: str, author: str = "") -> dict:
    """Resposta proposta (IA; sem chave ou com erro, uma resposta-padrão). Não envia nada."""
    from .content.guard import sanitize
    wa = whatsapp_link(acc)
    res = None
    if os.environ.get("SOCIAL_ANTHROPIC_API_KEY"):
        try:
            from .content.ai import inbox_reply
            res = inbox_reply(acc, kind, text, author, wa)
        except Exception as exc:  # noqa: BLE001
            res = {"intent": "outro", "reply": "", "private_reply": "", "alert": False, "error": str(exc)}
    if not res or (not res.get("reply") and res.get("intent") not in ("spam",)):
        base = {"intent": (res or {}).get("intent", "outro"), "alert": bool((res or {}).get("alert"))}
        res = {**base, "reply": FALLBACK["comment" if kind == "comment" else "message"].format(wa=wa),
               "private_reply": FALLBACK["private"].format(wa=wa) if kind == "comment" else "",
               "error": (res or {}).get("error")}
    for k in ("reply", "private_reply"):
        txt = sanitize(acc.id, (res.get(k) or "").strip())
        res[k] = "" if "[PREENCHER" in txt else txt              # nunca enviar um marcador por preencher
    if res.get("intent") != "spam" and res.get("reply") and wa not in res["reply"] and res["intent"] != "elogio":
        res["reply"] = f"{res['reply']} {wa}"
    return personalize(acc, kind, author, res)


# ------------------------------------------------------------------ identificar quem comentou
import re as _re

_GREETING = _re.compile(r"^\s*(ol[áa]|oi|bom dia|boa tarde|boa noite)\b[^!.,\n]{0,30}[!.,]?\s*", _re.I)


def first_name(name: str) -> str:
    """Primeiro nome de quem comentou no Facebook (ex.: "joão silva" → "João"); vazio se não parecer um nome."""
    token = (name or "").strip().split(" ")[0] if name else ""
    return token[:1].upper() + token[1:].lower() if token.isalpha() and 1 < len(token) <= 20 else ""


def personalize(acc: Account, kind: str, author: str, res: dict) -> dict:
    """Comentários: a resposta pública começa por @username (Instagram) ou "Olá {primeiro nome}!" (Facebook);
    a mensagem privada começa com a saudação. Spam/ofensas não têm resposta, logo nunca levam o nome.
    (Facebook: a API deixa uma Página mencionar outras Páginas, não pessoas; por isso usa-se o primeiro nome.)"""
    if res.get("intent") == "spam" or not res.get("reply"):
        return {**res, "reply": "", "private_reply": ""}
    author = (author or "").strip().lstrip("@")
    if acc.platform == "instagram" and author:
        body = _re.sub(rf"^\s*@{_re.escape(author)}\b[\s,:]*", "", res["reply"], flags=_re.I)
        body = _GREETING.sub("", body, count=1)
        res["reply"] = f"@{author} {body[:1].upper() + body[1:]}".strip()
        hello = f"Olá @{author}!"
    elif acc.platform == "facebook_page":
        name = first_name(author)
        hello = f"Olá {name}!" if name else "Olá!"
        if kind == "comment":
            body = _GREETING.sub("", res["reply"], count=1)
            res["reply"] = f"{hello} {body[:1].upper() + body[1:]}".strip()
    else:
        hello = "Olá!"
    if res.get("private_reply"):
        body = _GREETING.sub("", res["private_reply"], count=1)
        res["private_reply"] = f"{hello} {body[:1].upper() + body[1:]}".strip()
    return res


def _recent_auto_dm(conn, acc_id: str, author_id: str) -> bool:
    limit = (datetime.now() - timedelta(hours=24)).isoformat(timespec="seconds")
    return bool(conn.execute(
        "SELECT 1 FROM inbox WHERE account_id=? AND author_id=? AND kind='message' AND status='respondido' "
        "AND replied_at >= ?", (acc_id, author_id, limit)).fetchone())


def process(item_id: int, wait: int = 0) -> str:
    if wait:
        import time
        time.sleep(wait)
    with connect() as conn:
        row = conn.execute("SELECT * FROM inbox WHERE id=?", (item_id,)).fetchone()
        if not row or row["status"] != "novo":
            return row["status"] if row else "?"
        acc = accounts().get(row["account_id"])
        if not acc or not account_settings(acc.id)["enabled"]:
            conn.execute("UPDATE inbox SET status='desligado', note=? WHERE id=?",
                         ("respostas automáticas desligadas nesta conta", item_id))
            return "desligado"
        if row["kind"] == "message" and _recent_auto_dm(conn, acc.id, row["author_id"]):
            conn.execute("UPDATE inbox SET status='ignorado', note=? WHERE id=?",
                         ("já respondeu a esta pessoa nas últimas 24 h (a conversa segue no WhatsApp)", item_id))
            return "ignorado"
    if already_answered(acc, row):
        with connect() as conn:
            conn.execute("UPDATE inbox SET status='ignorado', note=? WHERE id=?",
                         ("já respondido por outra automação (ex.: Meta Business Suite) ou por uma pessoa", item_id))
        return "ignorado"
    res = compose(acc, row["kind"], row["text"] or "", row["author"] or "")
    status, note = "respondido", res.get("error")
    try:
        if res.get("intent") == "spam" or not res.get("reply"):
            status, note = "ignorado", "spam ou sem resposta necessária"
        else:
            _send(acc, row, res)
    except Exception as exc:  # noqa: BLE001
        status, note = "erro", str(exc)
    with connect() as conn:
        conn.execute("UPDATE inbox SET intent=?, reply=?, private_reply=?, status=?, note=?, replied_at=? WHERE id=?",
                     (res.get("intent"), res.get("reply"), res.get("private_reply"), status, note,
                      now() if status == "respondido" else None, item_id))
    if res.get("alert") or status == "erro":
        _alert(acc, row, res, status, note)
    return status


def _send(acc: Account, row, res: dict) -> None:
    from .http import request
    from .meta_connect import graph
    token = acc.secret("access_token_env")
    if row["kind"] == "comment":
        edge = "replies" if acc.platform == "instagram" else "comments"
        request("POST", f"{graph()}/{row['external_id']}/{edge}", data={"message": res["reply"], "access_token": token})
        if res.get("private_reply") and account_settings(acc.id)["private"]:
            request("POST", f"{graph()}/me/messages", json={
                "recipient": {"comment_id": row["external_id"]}, "message": {"text": res["private_reply"]}},
                params={"access_token": token})
    else:
        request("POST", f"{graph()}/me/messages", json={
            "recipient": {"id": row["author_id"]}, "messaging_type": "RESPONSE", "message": {"text": res["reply"]}},
            params={"access_token": token})


def _alert(acc: Account, row, res: dict, status: str, note) -> None:
    from . import notify
    from .routine import dashboard_url
    what = "Comentário" if row["kind"] == "comment" else "Mensagem"
    head = "⚠️ Resposta automática falhou" if status == "erro" else f"👀 {what} a ver ({res.get('intent')})"
    try:
        notify.send(f"{head} em {acc.name}:\n«{(row['text'] or '')[:400]}»\n"
                    + (f"Resposta enviada: {res.get('reply')}\n" if status == "respondido" else f"Erro: {note}\n")
                    + dashboard_url("/mensagens"))
    except Exception:  # noqa: BLE001
        pass


# ------------------------------------------------------------------ ativar na Meta
def page_id_for(acc: Account) -> str | None:
    if acc.platform == "facebook_page":
        return acc.secret("page_id_env")
    from .meta_connect import discovered
    ig = acc.secret("user_id_env")
    return next((p["id"] for p in discovered().get("pages", []) if (p.get("ig") or {}).get("id") == ig), None)


def subscribe(acc: Account) -> str:
    """Subscreve a Página (a da conta, ou a ligada ao Instagram) para a Meta enviar comentários e mensagens."""
    from .http import request
    from .meta_connect import graph
    pid = page_id_for(acc)
    if not pid:
        raise ValueError("não encontrei a Página ligada a esta conta (volte a 'Ligar com o Facebook')")
    request("POST", f"{graph()}/{pid}/subscribed_apps",
            data={"subscribed_fields": "feed,messages", "access_token": acc.secret("access_token_env")})
    save_account_settings(acc.id, subscribed_at=now())
    return pid
