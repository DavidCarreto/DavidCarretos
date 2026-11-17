"""Publicação no Instagram (Graph API — conta Profissional/Criador ligada a uma Página do Facebook).

Reels são enviados diretamente do disco (upload resumable); imagens, carrosséis e capas
precisam de URL público (ver media_host.py).
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from ..http import ApiError, request
from .base import PublishRequest, PublishResult, Publisher
from ..meta_connect import graph_version
from .media_host import public_url

VERSION = graph_version()                 # nunca abaixo da v24 (ver meta_connect.graph_version)
GRAPH = f"https://graph.facebook.com/{VERSION}"


class InstagramPublisher(Publisher):
    def publish(self, req: PublishRequest) -> PublishResult:
        token = req.account.secret("access_token_env")
        user_id = req.account.secret("user_id_env")
        if not token or not user_id:
            raise RuntimeError(f"{req.account.id}: faltam IG token/user id no .env")
        self.token, self.user_id = token, user_id
        if req.format in ("reel", "video"):
            creation = self._reel(req)
        elif req.format == "carousel":
            creation = self._carousel(req)
        else:
            creation = self._container(image_url=public_url(req.media[0]), caption=req.caption)
        self._wait(creation)
        published = request("POST", f"{GRAPH}/{user_id}/media_publish",
                            data={"creation_id": creation, "access_token": token}).json()
        media_id = published["id"]
        link = request("GET", f"{GRAPH}/{media_id}", params={"fields": "permalink", "access_token": token}).json()
        return PublishResult(remote_id=media_id, url=link.get("permalink"))

    def _container(self, **fields) -> str:
        fields["access_token"] = self.token
        return request("POST", f"{GRAPH}/{self.user_id}/media", data=fields).json()["id"]

    def _reel(self, req: PublishRequest) -> str:
        video = Path(req.media[0])
        fields = {"media_type": "REELS", "upload_type": "resumable", "caption": req.caption,
                  "share_to_feed": "true", "access_token": self.token}
        if req.cover:
            try:
                fields["cover_url"] = public_url(req.cover)
            except Exception:  # noqa: BLE001 — sem alojamento, usa o 1.º frame
                pass
        resp = request("POST", f"{GRAPH}/{self.user_id}/media", data=fields).json()
        container, upload_uri = resp["id"], resp["uri"]
        request("POST", upload_uri, headers={
            "Authorization": f"OAuth {self.token}", "offset": "0", "file_size": str(video.stat().st_size),
        }, data=video.read_bytes(), timeout=900)
        return container

    def _carousel(self, req: PublishRequest) -> str:
        children = []
        for path in req.media[:10]:
            is_video = path.endswith(".mp4")
            fields = {"is_carousel_item": "true"}
            fields["media_type" if is_video else "image_url"] = "VIDEO" if is_video else public_url(path)
            if is_video:
                fields["video_url"] = public_url(path)
            cid = self._container(**fields)
            self._wait(cid)
            children.append(cid)
        return self._container(media_type="CAROUSEL", children=",".join(children), caption=req.caption)

    def _wait(self, container: str, timeout: int = 900) -> None:
        start = time.time()
        while time.time() - start < timeout:
            status = request("GET", f"{GRAPH}/{container}", params={
                "fields": "status_code,status", "access_token": self.token}).json()
            code = status.get("status_code")
            if code in ("FINISHED", "PUBLISHED"):
                return
            if code in ("ERROR", "EXPIRED"):
                raise ApiError(f"Instagram rejeitou o ficheiro: {status.get('status')}")
            time.sleep(8)
        raise ApiError("Instagram demorou demasiado a processar o vídeo")
