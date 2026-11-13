"""Publicação no LinkedIn (Posts API) — perfil pessoal (w_member_social) e página da empresa
(w_organization_social, requer Community Management API aprovada)."""
from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import quote

from ..http import request
from .base import PublishRequest, PublishResult, Publisher

API = "https://api.linkedin.com/rest"


class LinkedInPublisher(Publisher):
    def publish(self, req: PublishRequest) -> PublishResult:
        token = req.account.secret("access_token_env")
        author = req.account.secret("author_urn_env")
        if not token or not author:
            raise RuntimeError(f"{req.account.id}: faltam token/URN LinkedIn no .env")
        self.h = {"Authorization": f"Bearer {token}",
                  "LinkedIn-Version": os.environ.get("LINKEDIN_VERSION", "202510"),
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
        resp = request("POST", f"{API}/posts", headers=self.h, json=body)
        urn = resp.headers.get("x-restli-id", "")
        return PublishResult(remote_id=urn, url=f"https://www.linkedin.com/feed/update/{quote(urn)}/")

    def _image(self, path: str) -> str:
        init = request("POST", f"{API}/images?action=initializeUpload", headers=self.h,
                       json={"initializeUploadRequest": {"owner": self.author}}).json()["value"]
        request("PUT", init["uploadUrl"], headers={"Authorization": self.h["Authorization"]},
                data=Path(path).read_bytes())
        return init["image"]

    def _video(self, path: str, cover: str | None) -> str:
        data = Path(path).read_bytes()
        init = request("POST", f"{API}/videos?action=initializeUpload", headers=self.h, json={
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
        request("POST", f"{API}/videos?action=finalizeUpload", headers=self.h, json={
            "finalizeUploadRequest": {"video": init["video"], "uploadToken": init.get("uploadToken", ""),
                                      "uploadedPartIds": etags}})
        return init["video"]


def _escape(text: str) -> str:
    """O campo commentary usa 'little text': estes caracteres têm de ser escapados."""
    for ch in "\\|{}@[]()<>#*_~":
        text = text.replace(ch, "\\" + ch)
    # hashtags clicáveis
    return re.sub(r"\\#(\w+)", lambda m: "{hashtag|\\#|" + m.group(1) + "}", text)
