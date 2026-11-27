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


def send(text: str, buttons: list[tuple[str, str]] | None = None) -> None:
    """buttons: [(texto, link)] → botões por baixo da mensagem (abrem o dashboard). Os botões de link só são
    aceites pelo Telegram com endereços https públicos: se não for o caso, a mensagem segue sem botões."""
    if not enabled():
        print(f"[notificação] {text}")
        if buttons is not None:
            raise RuntimeError("Telegram não configurado (falta o token do bot ou o chat)")
        return
    if buttons:
        buttons = [(t, u) for t, u in buttons if u.startswith("https://") and "localhost" not in u
                   and "127.0.0.1" not in u] or None
    data = {"chat_id": os.environ["TELEGRAM_CHAT_ID"], "text": (PREFIX + text)[:4000]}
    if buttons:
        import json
        data["reply_markup"] = json.dumps({"inline_keyboard": [[{"text": t, "url": u} for t, u in buttons]]})
    request("POST", _api("sendMessage"), data=data)


def send_file(path: str | Path, caption: str = "") -> None:
    if not enabled():
        print(f"[notificação] ficheiro pronto: {path}")
        return
    path = Path(path)
    method, field = ("sendVideo", "video") if path.suffix == ".mp4" else ("sendDocument", "document")
    with open(path, "rb") as fh:
        request("POST", _api(method), data={"chat_id": os.environ["TELEGRAM_CHAT_ID"],
                                            "caption": (PREFIX + caption)[:1024]}, files={field: fh}, timeout=600)
