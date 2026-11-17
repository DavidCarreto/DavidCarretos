"""Publicação numa Página de Facebook (Graph API, token da Página obtido em "Ligar com o Facebook").

- imagem: POST /{page}/photos (ficheiro enviado diretamente)
- várias fotos: cada foto com published=false e depois um post com attached_media
- vídeo: Reel da Página (/video_reels: start → envio do ficheiro → finish), 3 a 90 s
- só texto: POST /{page}/feed
O perfil pessoal do Facebook NÃO se publica por API (vai para o telemóvel: modo assistido).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from ..http import ApiError, request
from ..meta_connect import graph, graph_version
from .base import PublishRequest, PublishResult, Publisher


class FacebookPagePublisher(Publisher):
    def publish(self, req: PublishRequest) -> PublishResult:
        self.token = req.account.secret("access_token_env")
        self.page = req.account.secret("page_id_env")
        if not self.token or not self.page:
            raise RuntimeError(f"{req.account.id}: Página por ligar (⚙ Contas → Ligar com o Facebook)")
        if req.format in ("reel", "video"):
            return self._reel(req)
        if req.format == "text" or not req.media:
            r = request("POST", f"{graph()}/{self.page}/feed",
                        data={"message": req.caption, "access_token": self.token}).json()
            return PublishResult(remote_id=r["id"], url=f"https://www.facebook.com/{r['id']}")
        if len(req.media) == 1:
            r = self._photo(req.media[0], caption=req.caption, published=True)
            return PublishResult(remote_id=r.get("post_id") or r["id"],
                                 url=f"https://www.facebook.com/{r.get('post_id') or r['id']}")
        ids = [self._photo(p, published=False)["id"] for p in req.media[:10]]
        r = request("POST", f"{graph()}/{self.page}/feed", data={
            "message": req.caption, "access_token": self.token,
            "attached_media": json.dumps([{"media_fbid": i} for i in ids])}).json()
        return PublishResult(remote_id=r["id"], url=f"https://www.facebook.com/{r['id']}")

    def _photo(self, path: str, caption: str = "", published: bool = True) -> dict:
        with open(path, "rb") as f:
            data = {"access_token": self.token, "published": "true" if published else "false"}
            if caption:
                data["caption"] = caption
            return request("POST", f"{graph()}/{self.page}/photos", data=data,
                           files={"source": (Path(path).name, f, "image/jpeg")}, timeout=300).json()

    def _reel(self, req: PublishRequest) -> PublishResult:
        video = Path(req.media[0])
        start = request("POST", f"{graph()}/{self.page}/video_reels",
                        data={"upload_phase": "start", "access_token": self.token}).json()
        vid = start["video_id"]
        upload_url = start.get("upload_url") or f"https://rupload.facebook.com/video-upload/{graph_version()}/{vid}"
        request("POST", upload_url, headers={"Authorization": f"OAuth {self.token}", "offset": "0",
                                             "file_size": str(video.stat().st_size)},
                data=video.read_bytes(), timeout=900)
        request("POST", f"{graph()}/{self.page}/video_reels", data={
            "upload_phase": "finish", "video_id": vid, "video_state": "PUBLISHED",
            "description": req.caption, "access_token": self.token})
        for _ in range(60):                                 # espera pelo processamento
            st = request("GET", f"{graph()}/{vid}", params={"fields": "status", "access_token": self.token}).json()
            status = (st.get("status") or {})
            if status.get("video_status") in ("ready", "published") or \
                    (status.get("publishing_phase") or {}).get("status") == "complete":
                break
            if status.get("video_status") == "error":
                raise ApiError(f"Facebook recusou o Reel: {json.dumps(status)[:300]}")
            time.sleep(10)
        return PublishResult(remote_id=vid, url=f"https://www.facebook.com/reel/{vid}")
