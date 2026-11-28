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

from . import config as _cfg
from .config import Account, accounts
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
    return _cfg.DATA_DIR / "respostas.json"


def settings() -> dict:
    try:
        return json.loads(_settings_path().read_text(encoding="utf-8")) if _settings_path().exists() else {}
    except (OSError, ValueError):
        return {}


def account_settings(acc_id: str) -> dict:
    """enabled: responder (ou propor) nesta conta; mode: "propor" (eu aprovo) ou "auto" (responde sozinho)."""
    # regra do David: todos os comentários vão ao Telegram e nada é publicado sem aprovação
    return {"enabled": True, "private": True, "mode": "propor", **(settings().get(acc_id) or {})}


def save_account_settings(acc_id: str, **fields) -> None:
    data = settings()
    data.setdefault(acc_id, {}).update(fields)
    _cfg.DATA_DIR.mkdir(parents=True, exist_ok=True)
    _settings_path().write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def eligible_accounts() -> list[Account]:
    return [a for a in accounts().values()
            if a.platform in ("instagram", "facebook_page", "linkedin_org") and a.has_credentials]


# ------------------------------------------------------------------ respostas fixas (candidaturas e parcerias)
def candidatura_email() -> str:
    return os.environ.get("CANDIDATURAS_EMAIL", "").strip() or "rh@carretos.pt"


def parcerias_email() -> str:
    return os.environ.get("PARCERIAS_EMAIL_PUBLICO", "").strip() or "davidcarreto@carretos.pt"


def parcerias_avisos() -> list[str]:
    raw = os.environ.get("PARCERIAS_AVISOS_EMAILS", "").strip() or "davidcarreto@carretos.pt,marcia.palmeirao@carretos.pt"
    return [e.strip() for e in raw.replace(";", ",").split(",") if "@" in e]


def fixed_reply(intent: str, lang: str = "pt") -> str:
    if (lang or "pt").lower()[:2] not in ("pt", ""):
        if intent == "candidatura":
            return (f"Thank you for your interest in joining Carretos Group! Please send your CV to {candidatura_email()}, "
                    "with the role and the workshop you are interested in. Good luck!")
        if intent == "parceria":
            return (f"Thank you for reaching out! For partnership proposals, please send us the details at "
                    f"{parcerias_email()} and we will reply with all due attention.")
    if intent == "candidatura":
        return (f"Obrigado pelo interesse em juntar-se à Carretos Group! Envie o seu CV para {candidatura_email()}, "
                "com a função e a oficina que lhe interessam. Boa sorte!")
    if intent == "parceria":
        return (f"Obrigado pelo contacto! Para propostas de parceria, envie-nos os detalhes para {parcerias_email()}, "
                "que respondemos com toda a atenção.")
    return ""


def has_contacts(text: str) -> bool:
    """O comentário tem um telefone ou um email? (não se repetem na resposta e avisa-se pelo Telegram)"""
    import re
    t = text or ""
    return bool(re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", t) or re.search(r"(?:\+?351[\s.-]?)?\b9\d(?:[\s.-]?\d){7}\b", t)
                or re.search(r"\b2\d(?:[\s.-]?\d){7}\b", t))


NETWORK_NAME = {"instagram": "Instagram", "facebook": "Facebook", "linkedin": "LinkedIn"}


def post_link(row) -> str:
    """Link para a publicação comentada (LinkedIn: o URN da publicação; Meta: o dashboard)."""
    from .routine import dashboard_url
    ctx = ((row["context"] or "") if row is not None else "").split("|", 1)[0]
    if ctx.startswith("urn:li:"):
        return f"https://www.linkedin.com/feed/update/{ctx}/"
    return dashboard_url("/mensagens")


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
    path = _cfg.DATA_DIR / "webhooks.json"
    try:
        items = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    except (OSError, ValueError):
        items = []
    items.insert(0, {"at": now(), "signature_ok": signature_ok, "object": (payload or {}).get("object"),
                     "entries": entries})
    _cfg.DATA_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items[:100], ensure_ascii=False), encoding="utf-8")


def recent_events() -> list[dict]:
    path = _cfg.DATA_DIR / "webhooks.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    except (OSError, ValueError):
        return []


def receive(payload: dict, background: bool = True) -> list[int]:
    """Guarda os eventos novos e responde (em segundo plano, para o webhook responder logo à Meta)."""
    return receive_items(parse(payload), background)


def receive_items(items: list[dict], background: bool = True) -> list[int]:
    ids = []
    with connect() as conn:
        for e in items:
            if conn.execute("SELECT 1 FROM inbox WHERE external_id=?", (e["external_id"],)).fetchone():
                continue                                          # a Meta pode reenviar o mesmo evento
            status, note = "novo", None
            if e["author_id"] and e["author_id"] == e["own"]:
                status, note = "ignorado", "escrito pela própria conta"
            elif is_own(e["author_id"], e["author"]):
                # outra conta nossa: avisa e espera pela aprovação como os outros (só a própria conta é ignorada);
                # em «Responder sozinho» é ignorado, para as contas não se responderem umas às outras
                note = "comentário de outra conta ligada ao Carretos Studio"
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


def answered_elsewhere(acc: Account, row) -> str | None:
    """A conta já respondeu fora do Carretos Studio (ManyChat, Meta Business Suite, uma pessoa)?
    Devolve o texto dessa resposta ("" se não o conseguir ler) ou None se não houver resposta (ou na dúvida)."""
    if acc.platform.startswith("linkedin"):
        from .linkedin_inbox import page_reply_text
        return page_reply_text(acc, row["external_id"])
    from .http import request
    from .meta_connect import graph
    token = acc.secret("access_token_env")
    mine = own_ids() | {str(acc.secret("page_id_env") or ""), str(acc.secret("user_id_env") or "")}
    handles = own_handles()
    try:
        if row["kind"] == "comment":
            edge = "replies" if acc.platform == "instagram" else "comments"
            fields = "from,username,text" if acc.platform == "instagram" else "from,message"
            data = request("GET", f"{graph()}/{row['external_id']}/{edge}", retries=1,
                           params={"fields": fields, "limit": 25, "access_token": token}).json()
            for c in data.get("data", []):
                frm = c.get("from") or {}
                if str(frm.get("id", "")) in mine or (c.get("username") or frm.get("username") or "").lower() in handles:
                    return (c.get("message") or c.get("text") or "").strip()
            return None
        platform = "instagram" if acc.platform == "instagram" else "messenger"
        data = request("GET", f"{graph()}/me/conversations", retries=1, params={
            "platform": platform, "user_id": row["author_id"], "access_token": token,
            "fields": "messages.limit(5){from,created_time,message}"}).json()
        for conv in data.get("data", []):
            msgs = (conv.get("messages") or {}).get("data", [])
            if msgs and str((msgs[0].get("from") or {}).get("id", "")) in mine:   # a mais recente é nossa
                return (msgs[0].get("message") or "").strip()
    except Exception:  # noqa: BLE001
        return None
    return None


def already_answered(acc: Account, row) -> bool:
    return answered_elsewhere(acc, row) is not None


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
    if res.get("intent") in ("candidatura", "parceria"):
        # respostas fixas: nunca pedem CV/dados no comentário, não confirmam vagas nem falam de condições
        res["reply"], res["private_reply"] = fixed_reply(res["intent"], res.get("lang") or "pt"), ""
    elif res.get("intent") != "spam" and res.get("reply") and wa not in res["reply"] and res["intent"] != "elogio" \
            and (getattr(acc, "voice", "") != "pessoal" or res.get("intent") in ("preco", "marcacao")):
        # conta pessoal do David: o WhatsApp da empresa só em assuntos de oficina
        res["reply"] = f"{res['reply']} {wa}"
    if acc.platform.startswith("linkedin"):
        res["private_reply"] = ""                                 # no LinkedIn não há mensagem privada pela API
    if res.get("intent") == "elogio":
        res["private_reply"] = ""
    return personalize(acc, kind, author, res)


# ------------------------------------------------------------------ identificar quem comentou
import re as _re

_GREETING = _re.compile(r"^\s*(ol[áa]|oi|bom dia|boa tarde|boa noite|hi|hello|hey|dear|good (morning|afternoon|evening)"
                        r"|hola|buenos d[ií]as|bonjour)\b[^!.,\n]{0,30}[!.,]?\s*", _re.I)


def _hello(lang: str, name: str = "") -> str:
    """Saudação na língua do comentário."""
    l = (lang or "pt").lower()[:2]
    word = {"pt": "Olá", "en": "Hi", "es": "Hola", "fr": "Bonjour", "it": "Ciao", "de": "Hallo"}.get(l, "Hi" if l else "Olá")
    return f"{word} {name}!" if name else f"{word}!"


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
        hello = _hello(res.get("lang"), f"@{author}")
    elif acc.platform.startswith("linkedin"):
        # a API não dá o nome de quem comentou (só o URN): a resposta fica no fio do comentário, sem nome
        res["reply"] = _GREETING.sub("", res["reply"], count=1)
        res["reply"] = res["reply"][:1].upper() + res["reply"][1:]
        hello = _hello(res.get("lang"))
    elif acc.platform == "facebook_page":
        name = first_name(author)
        hello = _hello(res.get("lang"), name)
        if kind == "comment":
            body = _GREETING.sub("", res["reply"], count=1)
            res["reply"] = f"{hello} {body[:1].upper() + body[1:]}".strip()
    else:
        hello = _hello(res.get("lang"))
    if res.get("private_reply"):
        body = _GREETING.sub("", res["private_reply"], count=1)
        res["private_reply"] = f"{hello} {body[:1].upper() + body[1:]}".strip()
    return res


def _recent_auto_dm(conn, acc_id: str, author_id: str) -> bool:
    limit = (datetime.now() - timedelta(hours=24)).isoformat(timespec="seconds")
    return bool(conn.execute(
        "SELECT 1 FROM inbox WHERE account_id=? AND author_id=? AND kind='message' AND status='respondido' "
        "AND replied_at >= ?", (acc_id, author_id, limit)).fetchone())


def process(item_id: int, wait: int = 0, force_propose: bool = False) -> str:
    if wait:
        import time
        time.sleep(wait)
    with connect() as conn:
        row = conn.execute("SELECT * FROM inbox WHERE id=?", (item_id,)).fetchone()
        if not row or row["status"] != "novo":
            return row["status"] if row else "?"
        acc = accounts().get(row["account_id"])
        if not acc or (not account_settings(acc.id)["enabled"] and not force_propose):
            conn.execute("UPDATE inbox SET status='desligado', note=? WHERE id=?",
                         ("respostas automáticas desligadas nesta conta", item_id))
            return "desligado"
        if (row["note"] or "").startswith("comentário de outra conta") and account_settings(acc.id).get("mode") == "auto":
            conn.execute("UPDATE inbox SET status='ignorado', note=? WHERE id=?",
                         ("conta nossa (em «Responder sozinho» não se responde a contas ligadas)", item_id))
            return "ignorado"
        if row["kind"] == "message" and _recent_auto_dm(conn, acc.id, row["author_id"]):
            conn.execute("UPDATE inbox SET status='ignorado', note=? WHERE id=?",
                         ("já respondeu a esta pessoa nas últimas 24 h (a conversa segue no WhatsApp)", item_id))
            return "ignorado"
    if row["kind"] == "message" and getattr(acc, "voice", "") == "pessoal":
        # conta pessoal do David: mensagens privadas só com aviso no Telegram, sem proposta de resposta
        with connect() as conn:
            conn.execute("UPDATE inbox SET status='aviso', note=? WHERE id=?",
                         ("mensagem privada na conta pessoal: só aviso, sem proposta", item_id))
        _notify_dm(acc, row, item_id)
        return "aviso"
    other = answered_elsewhere(acc, row)
    if other is not None:
        with connect() as conn:
            conn.execute("UPDATE inbox SET status='ignorado', reply=?, note=? WHERE id=?",
                         (other or None, "já respondido fora do Carretos Studio (outra automação ou uma pessoa)", item_id))
        _notify_elsewhere(acc, row, item_id, other)
        return "ignorado"
    res = compose(acc, row["kind"], row["text"] or "", row["author"] or "")
    intent = res.get("intent")
    mode = account_settings(acc.id).get("mode", "auto")
    contacts = has_contacts(row["text"] or "")
    status, note = "respondido", res.get("error")
    try:
        if intent == "spam" or not res.get("reply"):
            # vem também ao Telegram, com a proposta de ignorar (o David decide)
            status, note = "proposta", "spam (proposta: ignorar)" if intent == "spam" else "sem resposta proposta"
        elif intent in ("parceria", "reclamacao") or res.get("alert") or mode == "propor" or force_propose:
            # parcerias, reclamações e urgências nunca saem sozinhas; no modo "propor" nada sai sem aprovação
            status, note = "proposta", ("parceria: espera sempre pela aprovação" if intent == "parceria" else
                                        "à espera de aprovação" + (" (reclamação/urgência)" if intent == "reclamacao"
                                                                   or res.get("alert") else ""))
        else:
            _send(acc, row, res)
    except Exception as exc:  # noqa: BLE001
        status, note = "erro", str(exc)
    if contacts:
        note = ((note + " · ") if note else "") + "o comentário tem telefone/email (não repetido na resposta)"
    with connect() as conn:
        conn.execute("UPDATE inbox SET intent=?, reply=?, private_reply=?, status=?, note=?, replied_at=? WHERE id=?",
                     (res.get("intent"), res.get("reply"), res.get("private_reply"), status, note,
                      now() if status == "respondido" else None, item_id))
    _notify(acc, row, res, status, note, contacts, item_id)
    return status


def approve(item_id: int, text: str | None = None, user_id: int | None = None, via: str = "dashboard") -> str:
    """Envia uma resposta proposta (com o texto editado, se houver)."""
    with connect() as conn:
        row = conn.execute("SELECT * FROM inbox WHERE id=?", (item_id,)).fetchone()
    if not row or row["status"] not in ("proposta", "erro"):
        raise ValueError("Esta resposta já não está à espera de aprovação.")
    acc = accounts().get(row["account_id"])
    reply = (text if text is not None else row["reply"] or "").strip()
    if not reply:
        raise ValueError("A resposta está vazia.")
    from .content.guard import found_terms
    bad = [w for _, w in found_terms(acc.id, reply)]
    if bad or "[PREENCHER" in reply:
        raise ValueError("A resposta tem palavras proibidas ou partes por preencher: " + "; ".join(bad or ["[PREENCHER]"]))
    if row["kind"] == "comment" and comment_exists(acc, row) is False:
        mark_deleted(item_id, acc, row)
        raise ValueError("O comentário foi apagado pelo autor: não enviei nada.")
    if already_answered(acc, row):
        with connect() as conn:
            conn.execute("UPDATE inbox SET status='ignorado', note=? WHERE id=?",
                         ("já respondido por outra pessoa ou automação", item_id))
        raise ValueError("Já tinha sido respondido por outra pessoa: não enviei.")
    # só sai o texto aprovado: nunca uma mensagem privada extra (com texto não revisto)
    _send(acc, row, {"reply": reply, "private_reply": ""})
    via = via if via in ("dashboard", "telegram") else "dashboard"
    who = ""
    with connect() as conn:
        if user_id:
            u = conn.execute("SELECT name, username FROM users WHERE id=?", (user_id,)).fetchone()
            who = (u["name"] or u["username"]) if u else f"utilizador {user_id}"
        conn.execute("UPDATE inbox SET reply=?, status='respondido', note=?, replied_at=?, approved_by=?, approved_via=? "
                     "WHERE id=?", (reply, f"aprovado por {who or '?'} ({'botão do Telegram' if via == 'telegram' else 'dashboard'})",
                                    now(), user_id, via, item_id))
    _log_aviso(item_id, acc.name, NETWORK_NAME.get(row["network"] or "", ""),
               f"resposta aprovada por {who or '?'} via {via} e enviada", True)
    return "respondido"


def comment_exists(acc: Account, row) -> bool | None:
    """O comentário ainda existe na rede? False = apagado; None = não foi possível confirmar."""
    try:
        if acc.platform.startswith("linkedin"):
            from .linkedin_inbox import comment_exists as li_exists
            return li_exists(acc, row["external_id"], row["context"] or "")
        from .http import ApiError, request
        from .meta_connect import graph
        try:
            request("GET", f"{graph()}/{row['external_id']}", retries=1,
                    params={"fields": "id", "access_token": acc.secret("access_token_env")})
            return True
        except ApiError as exc:
            msg = str(exc)
            if "does not exist" in msg or '"code":100' in msg.replace(" ", "") or "-> 404" in msg:
                return False
            return None
    except Exception:  # noqa: BLE001
        return None


def mark_deleted(item_id: int, acc: Account, row) -> None:
    """Comentário apagado pelo autor: deixa de esperar pela aprovação e avisa no Telegram."""
    with connect() as conn:
        conn.execute("UPDATE inbox SET status='apagado', note=? WHERE id=?", ("apagado pelo autor", item_id))
    try:
        from . import notify
        rede = NETWORK_NAME.get(row["network"] or "", row["network"] or "")
        notify.send(f"🗑 Comentário #{item_id} apagado pelo autor · {acc.name} ({rede}): «{(row['text'] or '')[:200]}»\n"
                    "Já não precisa de decidir nada.")
    except Exception:  # noqa: BLE001
        pass
    _log_aviso(item_id, acc.name, NETWORK_NAME.get(row["network"] or "", ""), "apagado pelo autor", True)


RETENTION_DAYS = 365      # política de privacidade: comentários e mensagens guardados no máximo 12 meses


def purge_old(days: int = RETENTION_DAYS) -> int:
    """Apaga os comentários e mensagens com mais de 12 meses (política de privacidade). Devolve quantos apagou."""
    limit = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    with connect() as conn:
        n = conn.execute("DELETE FROM inbox WHERE created_at < ?", (limit,)).rowcount
    return n


def ignore(item_id: int) -> None:
    with connect() as conn:
        conn.execute("UPDATE inbox SET status='ignorado', note=? WHERE id=? AND status IN ('proposta','erro','novo')",
                     ("ignorado no dashboard", item_id))


def _send(acc: Account, row, res: dict) -> None:
    if acc.platform.startswith("linkedin"):
        from .linkedin_inbox import reply as li_reply
        ctx = row["context"] or ""
        li_reply(acc, row["external_id"], res["reply"], parent=ctx.split("|", 1)[1] if "|" in ctx else "")
        return
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


INTENT_NAME = {"elogio": "elogio", "preco": "preço", "marcacao": "marcação", "pergunta": "pergunta",
               "candidatura": "candidatura", "parceria": "parceria", "reclamacao": "reclamação", "spam": "spam",
               "outro": "outro"}


def _who(row) -> str:
    if row["network"] == "linkedin":
        return (row["author"] or "um membro do LinkedIn (o LinkedIn não dá o nome)")
    a = (row["author"] or "").strip()
    if not a:
        return "desconhecido"
    return f"@{a.lstrip('@')}" if row["network"] == "instagram" else a


def _notify(acc: Account, row, res: dict, status: str, note, contacts: bool, item_id: int) -> None:
    """Um aviso no Telegram por CADA comentário novo (todas as categorias, spam incluído), com os botões
    Aprovar / Editar / Ignorar quando está à espera de decisão. Parcerias: também o email de aviso."""
    from . import notify
    from .routine import dashboard_url
    rede = NETWORK_NAME.get(row["network"] or "", row["network"] or "")
    intent = res.get("intent") or "outro"
    cat = "spam (proposta: ignorar)" if intent == "spam" else INTENT_NAME.get(intent, intent)
    item_url = dashboard_url(f"/mensagens/item/{item_id}")
    buttons = [("✓ Aprovar", item_url + "?acao=aprovar"), ("✎ Editar", item_url + "?acao=editar"),
               ("✕ Ignorar", item_url + "?acao=ignorar")] if status in ("proposta", "erro") else None
    head = {"candidatura": "🧑‍🔧 Candidatura", "parceria": "🤝 Pedido de parceria", "reclamacao": "⚠️ Reclamação",
            "spam": "🚫 Spam"}.get(intent, "💬 Comentário novo")
    lines = [f"{head} · {acc.name} ({rede})",
             f"Quem: {_who(row)}",
             f"Comentário: «{(row['text'] or '')[:500]}»",
             f"Categoria: {cat}"]
    if contacts:
        lines.append("⚠️ Tem telefone/email: não é repetido na resposta.")
    if status == "respondido":
        lines.append(f"Resposta já enviada (conta em «Responder sozinho»): {res.get('reply')}")
    elif intent == "spam" or not res.get("reply"):
        lines.append("Proposta: ignorar (não responder)")
    else:
        lines.append(f"Resposta proposta: {res.get('reply')}")
    if status == "erro":
        lines.append(f"Erro: {note}")
    lines.append(f"Publicação: {post_link(row)}")
    ok, err = True, ""
    try:
        notify.send("\n".join(lines), buttons=buttons)
    except Exception as exc:  # noqa: BLE001
        ok, err = False, str(exc)
    _log_aviso(item_id, acc.name, rede, cat, ok, err)
    if intent == "parceria":
        _email_parceria(acc, row, rede)


def _notify_elsewhere(acc: Account, row, item_id: int, other: str) -> None:
    """Houve resposta fora do Carretos Studio: avisa (sem botões) para o David saber."""
    from . import notify
    rede = NETWORK_NAME.get(row["network"] or "", row["network"] or "")
    ok, err = True, ""
    try:
        notify.send(f"ℹ️ Já respondido fora do Carretos Studio · {acc.name} ({rede})\nQuem: {_who(row)}\n"
                    f"Comentário: «{(row['text'] or '')[:400]}»\n"
                    f"Resposta publicada por outra automação/pessoa: «{(other or '(não foi possível ler o texto)')[:400]}»\n"
                    f"Publicação: {post_link(row)}")
    except Exception as exc:  # noqa: BLE001
        ok, err = False, str(exc)
    _log_aviso(item_id, acc.name, rede, "já respondido fora do Studio", ok, err)


def _notify_dm(acc: Account, row, item_id: int) -> None:
    from . import notify
    rede = NETWORK_NAME.get(row["network"] or "", row["network"] or "")
    ok, err = True, ""
    try:
        notify.send(f"✉️ Mensagem privada · {acc.name} ({rede})\nQuem: {_who(row)}\n«{(row['text'] or '')[:500]}»\n"
                    "(Conta pessoal: sem proposta de resposta; responda na app.)")
    except Exception as exc:  # noqa: BLE001
        ok, err = False, str(exc)
    _log_aviso(item_id, acc.name, rede, "mensagem privada (só aviso)", ok, err)


def _log_aviso(item_id: int, conta: str, rede: str, cat: str, ok: bool, err: str = "") -> None:
    """Uma linha por aviso (enviado ou falhado): no registo do processo e em data/avisos_comentarios.jsonl
    (⚙ Configurar → Registos)."""
    from .redact import redact
    line = (f"aviso Telegram comentário #{item_id} ({conta} · {rede} · {cat}): "
            + ("enviado" if ok else f"FALHOU — {redact(err)[:300]}"))
    print(datetime.now().strftime("%H:%M"), line, flush=True)
    try:
        path = _cfg.DATA_DIR / "avisos_comentarios.jsonl"
        _cfg.DATA_DIR.mkdir(parents=True, exist_ok=True)
        rows = path.read_text(encoding="utf-8").splitlines()[-299:] if path.exists() else []
        rows.append(json.dumps({"at": now(), "linha": line, "ok": ok}, ensure_ascii=False))
        path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    except OSError:
        pass


def avisos_log(limit: int = 50) -> list[dict]:
    try:
        rows = [json.loads(x) for x in (_cfg.DATA_DIR / "avisos_comentarios.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    except (OSError, ValueError):
        return []
    return rows[-limit:][::-1]


def _email_parceria(acc: Account, row, rede: str) -> None:
    from .web import mailer
    if not mailer.configured():
        return
    body = (f"Chegou um pedido de parceria num comentário do {rede} ({acc.name}).\n\n"
            f"Excerto: «{(row['text'] or '')[:500]}»\n\nPublicação: {post_link(row)}\n\n"
            "A resposta proposta está no Carretos Studio → Mensagens, à espera de aprovação (nunca sai sozinha).")
    for to in parcerias_avisos():
        try:
            mailer.send(to, f"Pedido de parceria no {rede}", body)
        except Exception:  # noqa: BLE001
            pass


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


# ------------------------------------------------------------------ Páginas de Facebook: ir buscar os comentários
def fb_interval_minutes() -> int:
    try:
        return max(2, int(os.environ.get("FACEBOOK_COMMENTS_MINUTES", "5")))
    except ValueError:
        return 5


def _fb_state_path():
    return _cfg.DATA_DIR / "facebook_leitura.json"


def poll_facebook_pages(force: bool = False) -> list[str]:
    """Além dos avisos (webhooks) da Meta, vai buscar os comentários recentes das Páginas de Facebook e das contas
    Instagram ligadas
    (posts dos últimos 30 dias) e trata os novos como se tivessem chegado pelo webhook (mesmo id: não duplica).
    Só comentários depois de a conta estar ligada; os da própria Página não contam."""
    from .http import request
    from .meta_connect import graph
    try:
        st = json.loads(_fb_state_path().read_text(encoding="utf-8")) if _fb_state_path().exists() else {}
    except (OSError, ValueError):
        st = {}
    import time as _t
    if not force and _t.time() - st.get("last_poll", 0) < fb_interval_minutes() * 60:
        return []
    st["last_poll"] = _t.time()
    lines = []
    since_30d = int(_t.time() - 30 * 86400)
    for acc in eligible_accounts():
        if acc.platform not in ("facebook_page", "instagram"):
            continue
        cfg = account_settings(acc.id)
        if not cfg.get("enabled"):
            continue
        first = st.setdefault("since", {}).setdefault(acc.id, now())      # 1.ª leitura: só daqui para a frente
        since = max(first, cfg.get("enabled_at") or first)
        token = acc.secret("access_token_env")
        if acc.platform == "instagram":
            lines.append(_poll_instagram(acc, token, since, since_30d))
            continue
        pid = page_id_for(acc)
        if not pid or not token:
            continue
        try:
            fields = ("id,created_time,comments.limit(50).order(reverse_chronological){id,message,created_time,from,"
                      "comments.limit(25){id,message,created_time,from}}")
            # as 15 publicações mais recentes, mesmo que antigas (um comentário novo num post antigo também conta)
            data = request("GET", f"{graph()}/{pid}/posts", retries=1, params={
                "fields": fields, "limit": 15, "access_token": token}).json().get("data", [])
        except Exception as exc:  # noqa: BLE001
            from .redact import redact
            lines.append(f"Facebook comentários {acc.name}: erro — {redact(str(exc))[:300]}")
            continue
        items = []
        for post in data:
            for c in ((post.get("comments") or {}).get("data") or []):
                for cc in [c] + (((c.get("comments") or {}).get("data")) or []):
                    frm = cc.get("from") or {}
                    when = (cc.get("created_time") or "")[:19]
                    if not cc.get("id") or str(frm.get("id", "")) == str(pid) or (when and when < since[:19]):
                        continue
                    items.append({"account_id": acc.id, "network": "facebook", "kind": "comment",
                                  "external_id": cc["id"], "author_id": str(frm.get("id", "")),
                                  "author": frm.get("name", ""), "text": cc.get("message", ""),
                                  "context": post.get("id", ""), "own": str(pid)})
        new = receive_items(items, background=False)
        lines.append(f"Facebook comentários {acc.name}: {len(data)} posts lidos, {len(new)} comentário(s) novo(s)")
    _cfg.DATA_DIR.mkdir(parents=True, exist_ok=True)
    _fb_state_path().write_text(json.dumps(st), encoding="utf-8")
    return lines


def _poll_instagram(acc: Account, token: str, since: str, since_30d: int) -> str:
    """Comentários (e respostas) novos nas 15 publicações mais recentes de uma conta Instagram ligada (mesmo que a
    publicação seja antiga); os da própria conta não contam; o mesmo id do webhook, por isso nunca duplica."""
    from .http import request
    from .meta_connect import graph
    ig = acc.secret("user_id_env")
    if not ig or not token:
        return f"Instagram comentários {acc.name}: sem conta ligada"
    try:
        fields = ("id,timestamp,comments.limit(50){id,text,timestamp,username,from,"
                  "replies.limit(25){id,text,timestamp,username,from}}")
        data = request("GET", f"{graph()}/{ig}/media", retries=1, params={
            "fields": fields, "limit": 15, "access_token": token}).json().get("data", [])
    except Exception as exc:  # noqa: BLE001
        from .redact import redact
        return f"Instagram comentários {acc.name}: erro — {redact(str(exc))[:300]}"
    own_user = (acc.handle or "").lower().lstrip("@")
    items = []
    for media in data:
        # todas as publicações recentes (15), mesmo antigas: o que conta é a data do COMENTÁRIO
        for c in ((media.get("comments") or {}).get("data") or []):
            for cc in [c] + (((c.get("replies") or {}).get("data")) or []):
                frm = cc.get("from") or {}
                user = (cc.get("username") or frm.get("username") or "").lower()
                when = (cc.get("timestamp") or "")[:19]
                if not cc.get("id") or str(frm.get("id", "")) == str(ig) or (own_user and user == own_user) \
                        or (when and when < since[:19]):
                    continue
                items.append({"account_id": acc.id, "network": "instagram", "kind": "comment",
                              "external_id": cc["id"], "author_id": str(frm.get("id", "")), "author": user,
                              "text": cc.get("text", ""), "context": media.get("id", ""), "own": str(ig)})
    new = receive_items(items, background=False)
    return f"Instagram comentários {acc.name}: {len(data)} publicações lidas, {len(new)} comentário(s) novo(s)"


def meta_diagnose() -> dict:
    """Diagnóstico dos avisos da Meta (só leitura): campos subscritos na app (objeto page/instagram) e, por
    Página, se a app está instalada (subscribed_apps) e com que campos, e as autorizações do token."""
    from .http import request
    from .meta_connect import graph
    app_id, secret = os.environ.get("META_APP_ID", ""), os.environ.get("META_APP_SECRET", "")
    out: dict = {"app": {}, "pages": [], "at": now()}
    app_token = f"{app_id}|{secret}" if app_id and secret else ""
    if app_token:
        try:
            subs = request("GET", f"{graph()}/{app_id}/subscriptions", retries=1,
                           params={"access_token": app_token}).json().get("data", [])
            out["app"] = {s.get("object"): {"active": s.get("active"), "fields": [f.get("name") for f in s.get("fields", [])],
                                            "callback": s.get("callback_url", "")} for s in subs}
        except Exception as exc:  # noqa: BLE001
            out["app_error"] = str(exc)[:300]
    for acc in eligible_accounts():
        if acc.platform not in ("facebook_page", "instagram"):
            continue
        row = {"account": acc.name, "platform": acc.platform}
        pid, token = page_id_for(acc), acc.secret("access_token_env")
        row["page_id"] = pid or ""
        try:
            apps = request("GET", f"{graph()}/{pid}/subscribed_apps", retries=1,
                           params={"access_token": token}).json().get("data", []) if pid else []
            mine = next((a for a in apps if str(a.get("id")) == str(app_id)), None)
            row["installed"] = bool(mine)
            row["fields"] = (mine or {}).get("subscribed_fields", [])
            # TODAS as apps instaladas na Página (ex.: ManyChat): nome, id e campos (só leitura)
            row["apps"] = [{"name": a.get("name", "?"), "id": str(a.get("id", "")),
                            "fields": a.get("subscribed_fields", []), "ours": str(a.get("id")) == str(app_id)}
                           for a in apps]
        except Exception as exc:  # noqa: BLE001
            row["error"] = str(exc)[:300]
        if app_token and token:
            try:
                d = request("GET", f"{graph()}/debug_token", retries=1,
                            params={"input_token": token, "access_token": app_token}).json().get("data", {})
                scopes = set(d.get("scopes", []))
                need = {"pages_manage_metadata", "pages_read_user_content", "pages_manage_engagement",
                        "pages_read_engagement", "pages_show_list"} | (
                    {"pages_messaging"} if acc.platform == "facebook_page" else {"instagram_manage_comments"})
                row["missing"] = sorted(need - scopes)
                row["token_type"] = d.get("type", "")
            except Exception as exc:  # noqa: BLE001
                row["token_error"] = str(exc)[:200]
        out["pages"].append(row)
    _cfg.DATA_DIR.mkdir(parents=True, exist_ok=True)
    (_cfg.DATA_DIR / "meta_diagnostico.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


def last_meta_diagnose() -> dict:
    try:
        return json.loads((_cfg.DATA_DIR / "meta_diagnostico.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


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
