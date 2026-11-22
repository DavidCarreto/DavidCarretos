"""Modo assistido: para plataformas sem API de publicação (Facebook pessoal).

Cria uma pasta com tudo pronto (vídeo/imagem, capa, legenda.txt) e envia para o telemóvel.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from .. import notify
from ..config import DATA_DIR
from .base import PublishRequest, PublishResult, Publisher


class AssistPublisher(Publisher):
    def publish(self, req: PublishRequest) -> PublishResult:
        folder = DATA_DIR / "prontos_a_publicar" / f"{req.account.id}_{req.title or 'post'}".replace(" ", "_")[:80]
        folder.mkdir(parents=True, exist_ok=True)
        for p in req.media + ([req.cover] if req.cover else []):
            shutil.copy(p, folder / Path(p).name)
        (folder / "legenda.txt").write_text(req.caption, encoding="utf-8")
        from ..routine import dashboard_url
        notify.send(f"📲 Hora de publicar em {req.account.name}:\n\n{req.caption}\n\n"
                    f"Legenda para copiar, ficheiros e \"Já publiquei\": {dashboard_url('/manual')}")
        for p in req.media:
            notify.send_file(p, caption=f"{req.account.name} — {req.title}")
        return PublishResult(remote_id=f"assist:{folder.name}", note=f"pacote em {folder}", status="assist_sent")
