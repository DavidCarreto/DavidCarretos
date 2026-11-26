"""Recetor de email mínimo do Carretos Studio (porta 25), só para os avisos de mensagens do LinkedIn.

O Hotmail do David redireciona os emails do LinkedIn sobre mensagens para um endereço SECRETO deste servidor
(ex.: linkedin-a1b2c3d4e5@carretosstudio.duckdns.org). Este recetor:
- só aceita esse endereço (qualquer outro é recusado com 550) e só com o aviso ligado em ⚙ Configurar;
- mensagens até 2 MB, tempo limite por ligação, no máximo 5 emails por ligação;
- não guarda os emails: passa-os a linkedin_mail.handle_message (aviso no Telegram) e descarta-os.
Sem dependências externas (asyncio). Corre como serviço carretos-correio (deploy/ativar_correio.sh).
"""
from __future__ import annotations

import asyncio
import email
import os
import re

MAX_BYTES = 2 * 1024 * 1024
TIMEOUT = 60
MAX_MSGS = 5


def _allowed(addr: str) -> bool:
    from . import linkedin_mail
    from .envfile import reload_env
    try:
        reload_env()                      # o endereço e o "ligado/desligado" mudam-se no dashboard
    except Exception:  # noqa: BLE001
        pass
    want = linkedin_mail.receive_address(create=False)
    return bool(want) and linkedin_mail.enabled() and addr.strip().lower() == want.lower()


def _addr(arg: str) -> str:
    m = re.search(r"<([^>]*)>", arg)
    return (m.group(1) if m else arg.split(":", 1)[-1]).strip()


async def _session(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    def send(line: str) -> None:
        writer.write((line + "\r\n").encode())

    async def readline() -> bytes:
        return await asyncio.wait_for(reader.readline(), TIMEOUT)

    rcpts: list[str] = []
    count = 0
    send("220 carretos-studio ESMTP")
    try:
        while True:
            await writer.drain()
            raw = await readline()
            if not raw:
                break
            if len(raw) > 1000:
                send("500 5.5.2 linha demasiado longa")
                break
            line = raw.decode("latin-1").rstrip("\r\n")
            cmd = line[:4].upper()
            if cmd in ("EHLO",):
                send("250-carretos-studio")
                send(f"250-SIZE {MAX_BYTES}")
                send("250 8BITMIME")
            elif cmd == "HELO":
                send("250 carretos-studio")
            elif cmd == "MAIL":
                rcpts = []
                send("250 2.1.0 OK")
            elif cmd == "RCPT":
                addr = _addr(line)
                if _allowed(addr):
                    rcpts.append(addr)
                    send("250 2.1.5 OK")
                else:
                    send("550 5.1.1 endereco desconhecido")
            elif cmd == "DATA":
                if not rcpts:
                    send("503 5.5.1 sem destinatario")
                    continue
                send("354 termine com <CRLF>.<CRLF>")
                await writer.drain()
                chunks, size, too_big = [], 0, False
                while True:
                    part = await readline()
                    if not part or part in (b".\r\n", b".\n"):
                        break
                    if part.startswith(b".."):
                        part = part[1:]
                    size += len(part)
                    if size > MAX_BYTES:
                        too_big = True
                    elif not too_big:
                        chunks.append(part)
                if too_big:
                    send("552 5.3.4 mensagem demasiado grande")
                else:
                    try:
                        from .linkedin_mail import handle_message
                        handle_message(email.message_from_bytes(b"".join(chunks)))
                    except Exception as exc:  # noqa: BLE001
                        print("correio: erro ao tratar o email:", exc, flush=True)
                    send("250 2.0.0 OK")
                rcpts = []
                count += 1
                if count >= MAX_MSGS:
                    send("421 4.7.0 demasiadas mensagens nesta ligacao")
                    break
            elif cmd == "RSET":
                rcpts = []
                send("250 OK")
            elif cmd == "NOOP":
                send("250 OK")
            elif cmd == "QUIT":
                send("221 2.0.0 adeus")
                break
            else:
                send("502 5.5.2 comando nao suportado")
    except (asyncio.TimeoutError, ConnectionError):
        pass
    finally:
        try:
            await writer.drain()
            writer.close()
        except Exception:  # noqa: BLE001
            pass


def run(host: str = "0.0.0.0", port: int | None = None) -> None:
    port = port or int(os.environ.get("CORREIO_PORTA") or 25)

    async def main():
        server = await asyncio.start_server(_session, host, port, limit=2048)
        print(f"Recetor de email do Carretos Studio a escutar na porta {port}", flush=True)
        async with server:
            await server.serve_forever()
    asyncio.run(main())
