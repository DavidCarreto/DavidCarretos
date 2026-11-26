"""Publicação no LinkedIn (Posts API) — perfil pessoal (w_member_social) e página da empresa
(w_organization_social, requer Community Management API aprovada)."""
from __future__ import annotations

from ..linkedin_connect import rest as li_rest

import os
import re
from pathlib import Path
from urllib.parse import quote

from ..http import request
from .base import PublishRequest, PublishResult, Publisher, PublishStepError

API = "https://api.linkedin.com/rest"


class LinkedInPublisher(Publisher):
    def publish(self, req: PublishRequest) -> PublishResult:
        token = req.account.secret("access_token_env")
        author = req.account.secret("author_urn_env")
        if not token or not author:
            raise RuntimeError(f"{req.account.id}: faltam token/URN LinkedIn no .env")
        self.h = {"Authorization": f"Bearer {token}",          # a versão da API é posta por li_rest()
                  "X-Restli-Protocol-Version": "2.0.0", "Content-Type": "application/json"}
        self.author = author
        body = {
            "author": author, "commentary": _escape(req.caption), "visibility": "PUBLIC",
            "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [],
                             "thirdPartyDistributionChannels": []},
            "lifecycleState": "PUBLISHED", "isReshareDisabledByAuthor": False,
        }
        if req.media:
            if req.format in ("video", "reel"):
                body["content"] = {"media": {"id": self._video(req.media[0], req.cover), "title": req.title[:200]}}
            elif req.format == "carousel" and len(req.media) > 1:
                body["content"] = {"multiImage": {"images": [{"id": self._image(p)} for p in req.media[:20]]}}
            else:
                body["content"] = {"media": {"id": self._image(req.media[0])}}
        elif req.article:
            # a Posts API não lê o site: o cartão do link vai como artigo com título, descrição e miniatura
            art = {"source": req.article["url"], "title": (req.article.get("title") or req.article["url"])[:400]}
            if req.article.get("description"):
                art["description"] = req.article["description"][:4086]
            if req.article.get("image_bytes"):
                art["thumbnail"] = self._image_bytes(req.article["image_bytes"], "imagem do cartão do link")
            body["content"] = {"article": art}
        try:
            resp = li_rest("POST", f"{API}/posts", headers=self.h, json=body)
        except Exception as exc:  # noqa: BLE001
            raise PublishStepError("criar o post no LinkedIn (Posts API)", exc) from exc
        urn = resp.headers.get("x-restli-id", "")
        return PublishResult(remote_id=urn, url=f"https://www.linkedin.com/feed/update/{quote(urn)}/")

    def _image(self, path: str) -> str:
        return self._image_bytes(Path(path).read_bytes(), "imagem do post")

    def _image_bytes(self, data: bytes, what: str = "imagem") -> str:
        try:
            init = li_rest("POST", f"{API}/images?action=initializeUpload", headers=self.h,
                           json={"initializeUploadRequest": {"owner": self.author}}).json()["value"]
        except Exception as exc:  # noqa: BLE001
            raise PublishStepError(f"preparar o envio da {what} (Images API)", exc) from exc
        try:
            request("PUT", init["uploadUrl"], headers={"Authorization": self.h["Authorization"]}, data=data)
        except Exception as exc:  # noqa: BLE001
            raise PublishStepError(f"enviar a {what} para o LinkedIn", exc) from exc
        self._wait_available(init["image"])
        return init["image"]

    def _wait_available(self, urn: str, seconds: int = 30) -> None:
        """O LinkedIn processa a imagem depois do envio; usá-la antes de estar pronta pode ser recusado."""
        import time
        end = time.time() + seconds
        while time.time() < end:
            try:
                st = li_rest("GET", f"{API}/images/{quote(urn, safe='')}", headers=self.h, retries=1).json().get("status")
            except Exception:  # noqa: BLE001
                return                                  # sem estado: segue (não é motivo para falhar)
            if st == "AVAILABLE":
                return
            if st == "PROCESSING_FAILED":
                raise PublishStepError(f"processar a imagem no LinkedIn", RuntimeError("o LinkedIn não aceitou a imagem"))
            time.sleep(2)

    def _video(self, path: str, cover: str | None) -> str:
        data = Path(path).read_bytes()
        init = li_rest("POST", f"{API}/videos?action=initializeUpload", headers=self.h, json={
            "initializeUploadRequest": {"owner": self.author, "fileSizeBytes": len(data),
                                        "uploadCaptions": False, "uploadThumbnail": bool(cover)}}).json()["value"]
        etags = []
        for part in init["uploadInstructions"]:
            r = request("PUT", part["uploadUrl"], headers={"Content-Type": "application/octet-stream"},
                        data=data[part["firstByte"]:part["lastByte"] + 1], timeout=900)
            etags.append(r.headers.get("etag", "").strip('"'))
        if cover and init.get("thumbnailUploadUrl"):
            request("PUT", init["thumbnailUploadUrl"], headers={"Content-Type": "image/jpeg"},
                    data=Path(cover).read_bytes())
        li_rest("POST", f"{API}/videos?action=finalizeUpload", headers=self.h, json={
            "finalizeUploadRequest": {"video": init["video"], "uploadToken": init.get("uploadToken", ""),
                                      "uploadedPartIds": etags}})
        return init["video"]


def _escape(text: str) -> str:
    """O campo commentary usa 'little text': estes caracteres têm de ser escapados."""
    for ch in "\\|{}@[]()<>#*_~":
        text = text.replace(ch, "\\" + ch)
    # hashtags clicáveis
    return re.sub(r"\\#(\w+)", lambda m: "{hashtag|\\#|" + m.group(1) + "}", text)
