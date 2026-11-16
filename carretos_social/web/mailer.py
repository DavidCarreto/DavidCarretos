"""Envio de emails do dashboard (convites e reposição de palavra-passe) por SMTP.

Usa uma conta de email PRÓPRIA deste sistema (variáveis SMTP_*), configurada no ⚙ do dashboard.
NÃO usar a palavra-passe de aplicação "carretos-avaliacoes" (pertence ao sistema de avaliações Google).
Os assuntos começam por "Redes Sociais ·" (os assuntos "[Carretos] …" são do outro sistema).
"""
from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage

PREFIX = "Redes Sociais · "


def configured() -> bool:
    return all(os.environ.get(k) for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD"))


def send(to: str, subject: str, body: str) -> None:
    if not configured():
        raise RuntimeError("Envio de email não configurado (SMTP).")
    msg = EmailMessage()
    msg["From"] = os.environ.get("SMTP_FROM") or os.environ["SMTP_USER"]
    msg["To"] = to
    msg["Subject"] = PREFIX + subject
    msg.set_content(body)
    host, port = os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT") or 587)
    ctx = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=ctx, timeout=30) as s:
            s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.starttls(context=ctx)
            s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
            s.send_message(msg)
