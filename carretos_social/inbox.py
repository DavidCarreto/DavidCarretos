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
            out.append({"account_id": acc.id if acc else None, "network": network, "kind": "message",
                        "external_id": msg.get("mid"), "author_id": str((m.get("sender") or {}).get("id", "")),
                        "author": "", "text": msg.get("text", ""), "context": "", "own": own})
    return [e for e in out if e["external_id"]]


def receive(payload: dict, background: bool = True) -> list[int]:
    """Guarda os eventos novos e responde (em segundo plano, para o webhook responder logo à Meta)."""
    ids = []
    with connect() as conn:
        for e in parse(payload):
            if conn.execute("SELECT 1 FROM inbox WHERE external_id=?", (e["external_id"],)).fetchone():
                continue                                          # a Meta pode reenviar o mesmo evento
            status, note = "novo", None
            if not e["account_id"]:
                status, note = "ignorado", "conta não ligada no Carretos Studio"
            elif e["author_id"] and e["author_id"] == e["own"]:
                status, note = "ignorado", "escrito pela própria conta"
            ids.append(conn.execute(
                "INSERT INTO inbox(account_id, network, kind, external_id, author_id, author, text, context, status, "
                "note, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (e["account_id"], e["network"], e["kind"], e["external_id"], e["author_id"], e["author"], e["text"],
                 e["context"], status, note, now())).lastrowid)
    for iid in ids:
        if background:
            threading.Thread(target=process, args=(iid,), daemon=True).start()
        else:
            process(iid)
    return ids


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
    return res


def _recent_auto_dm(conn, acc_id: str, author_id: str) -> bool:
    limit = (datetime.now() - timedelta(hours=24)).isoformat(timespec="seconds")
    return bool(conn.execute(
        "SELECT 1 FROM inbox WHERE account_id=? AND author_id=? AND kind='message' AND status='respondido' "
        "AND replied_at >= ?", (acc_id, author_id, limit)).fetchone())


def process(item_id: int) -> str:
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
