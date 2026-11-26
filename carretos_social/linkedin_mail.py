"""Avisos de mensagens privadas do LinkedIn (só aviso, nunca responde).

A API de mensagens do LinkedIn só está aberta a parceiros. Por isso: o Hotmail do David redireciona os emails
de notificação do LinkedIn ("… enviou-lhe uma mensagem") para uma caixa do Carretos Studio:
- Microsoft 365 (recomendado): caixa partilhada (ex.: studio@carretos.pt) lida pela aplicação registada
  "Carretos Studio" (MS_TENANT_ID, MS_CLIENT_ID, MS_CLIENT_SECRET, LINKEDIN_EMAILS_CAIXA), que só tem acesso a ela;
- ou IMAP com utilizador e palavra-passe (SMTP_*/IMAP_* em ⚙), para fornecedores que ainda o permitem.
De N em N minutos o agendador lê essa caixa, só os emails do LinkedIn,
manda um aviso pelo Telegram (e o email de parcerias, se for o caso) e apaga o email.
Não guarda o conteúdo: só uma marca (hash) para não avisar duas vezes. Os outros emails da caixa não são tocados.
"""
from __future__ import annotations

import email
import hashlib
import imaplib
import json
import os
import re
import time
from email.header import decode_header, make_header
from email.utils import parseaddr

from . import config as _cfg

MSG_WORDS = re.compile(r"mensage|message|enviou-lhe|sent you|escreveu|inmail", re.I)
PARTNER_WORDS = re.compile(r"parceri|fornecedor|colabora|patroc|proposta comercial|partnership|sponsor", re.I)
JOB_WORDS = re.compile(r"candidat|emprego|\bvaga|\bcv\b|curr[ií]culo|trabalhar convosco|recrutamento|job", re.I)


def receive_address(create: bool = True) -> str:
    """Endereço secreto deste servidor que recebe os emails redirecionados (criado uma vez e guardado no .env)."""
    addr = os.environ.get("LINKEDIN_EMAIL_ENDERECO", "").strip()
    if addr or not create:
        return addr
    import secrets
    from urllib.parse import urlparse
    from .envfile import set_env
    from .routine import dashboard_url
    host = urlparse(dashboard_url("/")).hostname or ""
    if not host or host in ("localhost", "127.0.0.1"):
        return ""
    addr = f"linkedin-{secrets.token_hex(5)}@{host}"
    set_env({"LINKEDIN_EMAIL_ENDERECO": addr})
    return addr


def handle_message(msg) -> bool:
    """Um email recebido diretamente pelo servidor (recetor da porta 25): avisa se for de mensagem do LinkedIn."""
    info = parse(msg)
    if not info:
        return False
    h = hashlib.sha256((msg.get("Message-ID") or "").encode() + (msg.get("Date") or "").encode()).hexdigest()[:24]
    if h in set(_seen()):
        return False
    _alert(info)
    _remember(h)
    print(f"correio: aviso de mensagem do LinkedIn ({'página' if info['page'] else 'perfil'})", flush=True)
    return True


def enabled() -> bool:
    return os.environ.get("LINKEDIN_EMAILS_ATIVO", "").strip().lower() in ("sim", "s", "yes", "1", "true")


def imap_settings() -> dict:
    smtp = os.environ.get("SMTP_HOST", "")
    host = os.environ.get("IMAP_HOST", "").strip() or (re.sub(r"^smtp", "imap", smtp) if smtp.startswith("smtp") else smtp)
    return {"host": host, "port": int(os.environ.get("IMAP_PORT") or 993),
            "user": os.environ.get("IMAP_USER") or os.environ.get("SMTP_USER", ""),
            "password": os.environ.get("IMAP_PASSWORD") or os.environ.get("SMTP_PASSWORD", "")}


def _seen_path():
    return _cfg.DATA_DIR / "linkedin_emails_vistos.json"


def _seen() -> list[str]:
    try:
        return json.loads(_seen_path().read_text(encoding="utf-8")) if _seen_path().exists() else []
    except (OSError, ValueError):
        return []


def _remember(h: str) -> None:
    items = (_seen() + [h])[-500:]
    _cfg.DATA_DIR.mkdir(parents=True, exist_ok=True)
    _seen_path().write_text(json.dumps(items), encoding="utf-8")


def _text(msg) -> str:
    parts = []
    for part in (msg.walk() if msg.is_multipart() else [msg]):
        ctype = part.get_content_type()
        if ctype in ("text/plain", "text/html") and not part.get_filename():
            try:
                raw = part.get_payload(decode=True) or b""
                t = raw.decode(part.get_content_charset() or "utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                continue
            if ctype == "text/html":
                t = re.sub(r"<(script|style).*?</\1>", " ", t, flags=re.S | re.I)
                t = re.sub(r"<[^>]+>", " ", t)
            parts.append(t)
    import html
    return re.sub(r"[ \t\r\f\v]+", " ", html.unescape("\n".join(parts)))


def parse(msg) -> dict | None:
    """Aviso a partir de um email do LinkedIn (ou de um reencaminhado do Hotmail), ou None se não for de mensagem."""
    subject = str(make_header(decode_header(msg.get("Subject", ""))))
    sender = parseaddr(msg.get("From", ""))[1].lower()
    return parse_parts(subject, sender, _text(msg))


def _html_to_text(t: str) -> str:
    import html
    t = re.sub(r"<(script|style).*?</\1>", " ", t, flags=re.S | re.I)
    return re.sub(r"[ \t\r\f\v]+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t)))


def parse_parts(subject: str, sender: str, body: str) -> dict | None:
    sender = (sender or "").lower()
    from_linkedin = "linkedin.com" in sender or ("linkedin.com" in body.lower() and re.match(r"^\s*(fw|fwd|enc|reenc)", subject, re.I))
    if not from_linkedin or not MSG_WORDS.search(subject + " " + body[:600]):
        return None
    clean_subj = re.sub(r"^\s*((fw|fwd|enc|reenc|re)\s*:\s*)+", "", subject, flags=re.I).strip()
    name = ""
    for pat in (r"^(.+?) enviou-lhe", r"^(.+?) sent you", r"mensagem de (.+?)(?:$| na | para |:)", r"message from (.+?)(?:$| on |:)",
                r"^(.+?) escreveu"):
        m = re.search(pat, clean_subj, re.I)
        if m:
            name = m.group(1).strip(" .:-")[:60]
            break
    page = "Carretos Group" if re.search(r"carreto'?s group", subject + " " + body, re.I) else ""
    preview = _preview(body, clean_subj, name)
    link = next(iter(re.findall(r"https://www\.linkedin\.com/(?:messaging|comm/messaging|company/[^\s\"'<>]*inbox)[^\s\"'<>]*", body)),
                "https://www.linkedin.com/messaging/")
    snippet = " ".join(body.split())[:400]
    kind = "parceria" if PARTNER_WORDS.search(clean_subj + " " + snippet) else (
        "candidatura" if JOB_WORDS.search(clean_subj + " " + snippet) else "")
    return {"name": name, "subject": clean_subj[:160], "page": page, "link": link.split("?")[0], "kind": kind,
            "snippet": snippet, "preview": preview}


_BOILER = re.compile(r"linkedin|responder|reply|ver mensagem|view message|unsubscribe|anular a subscri|cancelar|"
                     r"definições|settings|privacidade|privacy|©|this email|este email|enviou-lhe|sent you|"
                     r"^(de|from|para|to|assunto|subject|enviado|sent|data|date)\s*:|https?://", re.I)


def _preview(body: str, subject: str, name: str) -> str:
    """Início da mensagem, se o LinkedIn o incluiu no email (a 1.ª linha de texto que não é do modelo do email)."""
    for ln in body.splitlines():
        t = " ".join(ln.split())
        if len(t) < 12 or t == subject or (name and t.strip(" .:").lower() == name.lower()) or _BOILER.search(t):
            continue
        return t[:200]
    return ""


# ------------------------------------------------------------------ Microsoft 365 (aplicação registada)
def graph_settings() -> dict:
    return {"tenant": os.environ.get("MS_TENANT_ID", "").strip(), "client": os.environ.get("MS_CLIENT_ID", "").strip(),
            "secret": os.environ.get("MS_CLIENT_SECRET", "").strip(),
            "mailbox": os.environ.get("LINKEDIN_EMAILS_CAIXA", "").strip()}


def graph_mode() -> bool:
    g = graph_settings()
    return all(g.values())


def _graph_token(g: dict) -> str:
    from .http import request
    return request("POST", f"https://login.microsoftonline.com/{g['tenant']}/oauth2/v2.0/token", retries=2, data={
        "client_id": g["client"], "client_secret": g["secret"], "grant_type": "client_credentials",
        "scope": "https://graph.microsoft.com/.default"}).json()["access_token"]


def _poll_graph() -> list[str]:
    """Caixa do Microsoft 365 lida pela aplicação "Carretos Studio" (só tem acesso a essa caixa)."""
    from urllib.parse import quote
    from .http import request
    g = graph_settings()
    h = {"Authorization": f"Bearer {_graph_token(g)}"}
    base = f"https://graph.microsoft.com/v1.0/users/{quote(g['mailbox'], safe='@')}"
    data = request("GET", f"{base}/mailFolders/inbox/messages", headers=h, retries=2, params={
        "$top": 50, "$select": "id,subject,from,body,internetMessageId,receivedDateTime",
        "$orderby": "receivedDateTime desc"}).json()
    seen, n = set(_seen()), 0
    for m in data.get("value", []):
        sender = ((m.get("from") or {}).get("emailAddress") or {}).get("address", "")
        body = (m.get("body") or {}).get("content", "")
        if (m.get("body") or {}).get("contentType", "").lower() == "html":
            body = _html_to_text(body)
        info = parse_parts(m.get("subject") or "", sender, body)
        if not info:
            continue                                   # outros emails não se tocam
        hsh = hashlib.sha256((m.get("internetMessageId") or m.get("id", "")).encode()).hexdigest()[:24]
        if hsh not in seen:
            _alert(info)
            _remember(hsh)
            n += 1
        request("DELETE", f"{base}/messages/{quote(m['id'])}", headers=h, retries=1)   # vai para "Itens eliminados"
    return [f"LinkedIn mensagens (email): {n} aviso(s)"] if n else []


def poll() -> list[str]:
    """Lê a caixa, avisa e apaga os emails de mensagem do LinkedIn. Devolve linhas para o registo (sem conteúdo)."""
    if not enabled():
        return []
    if graph_mode():
        return _poll_graph()
    if not os.environ.get("IMAP_USER"):
        return []                         # sem caixa dedicada: os emails chegam ao recetor do servidor (porta 25)
    s = imap_settings()
    if not (s["host"] and s["user"] and s["password"]):
        raise RuntimeError("falta o servidor de entrada (IMAP) ou o utilizador/palavra-passe do email do Carretos Studio")
    from . import notify
    seen, n_avisos = set(_seen()), 0
    box = imaplib.IMAP4_SSL(s["host"], s["port"], timeout=30)
    try:
        box.login(s["user"], s["password"])
        box.select("INBOX")
        typ, data = box.search(None, '(OR FROM "linkedin.com" TEXT "linkedin.com")')
        ids = (data[0] or b"").split()[-50:]
        for num in ids:
            typ, raw = box.fetch(num, "(RFC822)")
            if typ != "OK" or not raw or not raw[0]:
                continue
            msg = email.message_from_bytes(raw[0][1])
            h = hashlib.sha256((msg.get("Message-ID") or "").encode() + (msg.get("Date") or "").encode()).hexdigest()[:24]
            info = parse(msg)
            if not info:
                continue                                   # outros emails (mesmo do LinkedIn) não se tocam
            if h not in seen:
                _alert(info)
                _remember(h)
                n_avisos += 1
            box.store(num, "+FLAGS", "\\Deleted")          # aviso dado: o email sai da caixa
        box.expunge()
    finally:
        try:
            box.logout()
        except Exception:  # noqa: BLE001
            pass
    return [f"LinkedIn mensagens (email): {n_avisos} aviso(s)"] if n_avisos else []


def _alert(info: dict) -> None:
    from . import notify
    where = f"página {info['page']}" if info["page"] else "perfil do David"
    tag = "\n🤝 Parece um pedido de parceria." if info["kind"] == "parceria" else (
        "\n🧑‍🔧 Parece uma candidatura." if info["kind"] == "candidatura" else "")
    notify.send(f"💬 Nova mensagem no LinkedIn ({where}) de {info['name'] or 'alguém (o email não diz o nome)'}\n"
                + (f"«{info['preview']}»\n" if info.get("preview") else "")
                + f"{tag.strip() + chr(10) if tag else ''}Abrir: {info['link']}\n(O Carretos Studio não responde: responda no LinkedIn.)")
    if info["kind"] == "parceria":
        from .inbox import parcerias_avisos
        from .web import mailer
        if mailer.configured():
            for to in parcerias_avisos():
                try:
                    mailer.send(to, "Pedido de parceria por mensagem no LinkedIn",
                                f"Chegou uma mensagem no LinkedIn ({where}) que parece um pedido de parceria"
                                f"{' de ' + info['name'] if info['name'] else ''}.\n\nAssunto: {info['subject']}\n\n"
                                f"Abrir no LinkedIn: {info['link']}\n\n(O Carretos Studio não responde a mensagens "
                                "do LinkedIn: responda diretamente no LinkedIn.)")
                except Exception:  # noqa: BLE001
                    pass


_last_fail_alert = 0.0


def poll_safe() -> list[str]:
    global _last_fail_alert
    try:
        return poll()
    except Exception as exc:  # noqa: BLE001
        from .redact import redact
        msg = redact(str(exc))[:400]
        if time.time() - _last_fail_alert > 6 * 3600:
            _last_fail_alert = time.time()
            try:
                from . import notify
                notify.send(f"⚠️ Não consegui ler os avisos de mensagens do LinkedIn (caixa de email do Carretos Studio): {msg}")
            except Exception:  # noqa: BLE001
                pass
        return [f"LinkedIn mensagens (email): falhou — {msg}"]
