"""TikTok em modo "rascunho na app TikTok" (Content Posting API, scope video.upload).

A TikTok não aprova o Direct Post para ferramentas internas que publicam nas próprias contas, por isso o
Carretos Studio NUNCA publica em público no TikTok: envia o conteúdo para os rascunhos/caixa de entrada da
app TikTok e o David revê e publica lá.

- Vídeo: POST /post/publish/inbox/video/init/ (FILE_UPLOAD por blocos; PULL_FROM_URL se TIKTOK_PULL_FROM_URL=sim
  e o domínio estiver verificado na TikTok). Este pedido não aceita legenda nem capa: a legenda pronta é enviada
  ao David (email + Telegram + dashboard, com "Copiar legenda").
- Carrossel de fotos: POST /post/publish/content/init/ com post_mode=MEDIA_UPLOAD e media_type=PHOTO (título,
  descrição e capa vão já com o rascunho; as fotos vão por PULL_FROM_URL a partir do servidor).
- Estado: /post/publish/status/fetch/ até "SEND_TO_USER_INBOX" (rascunho entregue).
- Se a TikTok recusar o rascunho (ex.: app ainda não aprovada), o erro fica completo e o post segue em modo
  assistido (vai para o telemóvel).
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from ..http import ApiError, request
from .base import PublishRequest, PublishResult, Publisher

API = "https://open.tiktokapis.com/v2"
CHUNK = 10 * 1024 * 1024
DRAFT_NOTE = "Enviado para os rascunhos do TikTok – falta publicar na app"
DONE = ("SEND_TO_USER_INBOX", "PUBLISH_COMPLETE")


def _yes(env: str) -> bool:
    return os.environ.get(env, "").strip().lower() in ("1", "sim", "yes", "true")


class TikTokPublisher(Publisher):
    """Envia para os rascunhos da app TikTok (nunca publica em público)."""

    def publish(self, req: PublishRequest) -> PublishResult:
        from ..tiktok_connect import ensure_fresh
        try:
            token = ensure_fresh(req.account)          # o token da TikTok dura 24 h: renova-se sozinho
            self.h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"}
            videos = [m for m in req.media if m.lower().endswith((".mp4", ".mov"))]
            if videos:
                publish_id = self._video(Path(videos[0]))
                kind = "video"
            else:
                images = [m for m in req.media if m.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))]
                if not images:
                    raise ApiError("O TikTok só aceita um vídeo ou fotos.")
                publish_id = self._photos(images, req)
                kind = "photo"
            self._wait(publish_id)
        except Exception as exc:  # noqa: BLE001 — a TikTok recusou: segue em modo assistido
            from .assist import AssistPublisher
            res = AssistPublisher().publish(req)
            return PublishResult(remote_id=res.remote_id, status="assist_sent",
                                 note=f"A TikTok recusou o rascunho: {exc} → enviado para o telemóvel (modo assistido).")
        if kind == "video":
            _send_caption(req)
            note = f"{DRAFT_NOTE}. Legenda e capa a definir na app TikTok (abra a notificação da TikTok para continuar)."
        else:
            note = f"{DRAFT_NOTE}. Abra a notificação da TikTok para rever e publicar."
        return PublishResult(remote_id=publish_id, status="tiktok_draft", note=note)

    # ---------------------------------------------------------------- vídeo (sem legenda nem capa)
    def _video(self, video: Path) -> str:
        if _yes("TIKTOK_PULL_FROM_URL"):
            from .media_host import public_url
            source = {"source": "PULL_FROM_URL", "video_url": public_url(video)}
            return request("POST", f"{API}/post/publish/inbox/video/init/", headers=self.h,
                           json={"source_info": source}).json()["data"]["publish_id"]
        size = video.stat().st_size
        chunk = size if size <= CHUNK else CHUNK
        count = max(1, size // chunk)
        init = request("POST", f"{API}/post/publish/inbox/video/init/", headers=self.h, json={
            "source_info": {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk,
                            "total_chunk_count": count}}).json()["data"]
        data = video.read_bytes()
        for i in range(count):
            start = i * chunk
            end = size - 1 if i == count - 1 else start + chunk - 1   # o último bloco leva o resto
            request("PUT", init["upload_url"], headers={
                "Content-Type": "video/mp4", "Content-Range": f"bytes {start}-{end}/{size}",
                "Content-Length": str(end - start + 1)}, data=data[start:end + 1], timeout=900)
        return init["publish_id"]

    # ---------------------------------------------------------------- carrossel de fotos (com legenda)
    def _photos(self, images: list[str], req: PublishRequest) -> str:
        from .media_host import public_url
        urls = [public_url(p) for p in images[:35]]
        title = (req.title or req.caption.split("\n", 1)[0])[:90]
        body = {"post_info": {"title": title, "description": req.caption[:4000]},
                "source_info": {"source": "PULL_FROM_URL", "photo_cover_index": 0, "photo_images": urls},
                "post_mode": "MEDIA_UPLOAD", "media_type": "PHOTO"}
        return request("POST", f"{API}/post/publish/content/init/", headers=self.h, json=body).json()["data"]["publish_id"]

    def _wait(self, publish_id: str, timeout: int = 600) -> None:
        start = time.time()
        while time.time() - start < timeout:
            st = request("POST", f"{API}/post/publish/status/fetch/", headers=self.h,
                         json={"publish_id": publish_id}).json().get("data", {})
            if st.get("status") in DONE:
                return
            if st.get("status") == "FAILED":
                raise ApiError(f"TikTok: {st.get('fail_reason') or st}")
            time.sleep(5)
        raise ApiError("A TikTok demorou demasiado a receber o rascunho (mais de 10 minutos).")


def _send_caption(req: PublishRequest) -> None:
    """O rascunho de vídeo não leva legenda: envia-a pronta ao David (email e Telegram)."""
    from .. import notify
    text = (f"Legenda para o TikTok ({req.account.name} · @{req.account.handle}).\n"
            "O vídeo já está nos rascunhos da app TikTok: abra a notificação da TikTok, cole esta legenda, "
            f"escolha a capa e publique.\n\n{req.caption}")
    try:
        notify.send("📣 Carretos Studio · " + text)
    except Exception:  # noqa: BLE001
        pass
    try:
        from ..web import mailer
        to = os.environ.get("TIKTOK_CAPTION_EMAIL") or _admin_emails()
        if to and mailer.configured():
            mailer.send(to, f"Legenda para o TikTok · @{req.account.handle}", text)
    except Exception:  # noqa: BLE001
        pass


def _admin_emails() -> str:
    from ..db import connect
    with connect() as conn:
        rows = conn.execute("SELECT email FROM users WHERE is_admin=1 AND active=1 AND email IS NOT NULL").fetchall()
    return ",".join(r["email"] for r in rows if r["email"])
