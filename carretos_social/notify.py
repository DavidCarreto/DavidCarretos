"""Notificações para o telemóvel do David via bot de Telegram (opcional).

Usado para: pedir aprovação de publicações, avisar falhas e enviar o "pacote pronto"
das contas sem API de publicação (Facebook pessoal) — vídeo + legenda para publicar em 1 toque.
Configura TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID no .env.
"""
from __future__ import annotations

import os
from pathlib import Path

from .http import request


# todas as mensagens deste sistema começam assim (distingue do sistema de avaliações)
PREFIX = "📣 Carretos Studio · "


def enabled() -> bool:
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"))


def _api(method: str) -> str:
    return f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/{method}"


def send(text: str) -> None:
    if not enabled():
        print(f"[notificação] {text}")
        return
    request("POST", _api("sendMessage"), data={"chat_id": os.environ["TELEGRAM_CHAT_ID"],
                                                "text": (PREFIX + text)[:4000]})


def send_file(path: str | Path, caption: str = "") -> None:
    if not enabled():
        print(f"[notificação] ficheiro pronto: {path}")
        return
    path = Path(path)
    method, field = ("sendVideo", "video") if path.suffix == ".mp4" else ("sendDocument", "document")
    with open(path, "rb") as fh:
        request("POST", _api(method), data={"chat_id": os.environ["TELEGRAM_CHAT_ID"],
                                            "caption": (PREFIX + caption)[:1024]}, files={field: fh}, timeout=600)
