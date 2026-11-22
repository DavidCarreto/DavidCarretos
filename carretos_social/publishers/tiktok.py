"""Publicação no TikTok (Content Posting API — Direct Post).

Nota: enquanto a app TikTok não passar a auditoria, o TikTok só permite publicar como
privado (SELF_ONLY). Define TIKTOK_PRIVACY=PUBLIC_TO_EVERYONE depois de aprovada.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from ..http import ApiError, request
from .base import PublishRequest, PublishResult, Publisher

API = "https://open.tiktokapis.com/v2"
CHUNK = 10 * 1024 * 1024


class TikTokPublisher(Publisher):
    def publish(self, req: PublishRequest) -> PublishResult:
        from ..tiktok_connect import ensure_fresh
        token = ensure_fresh(req.account)          # o token da TikTok dura 24 h: renova-se sozinho
        if not token:
            raise RuntimeError(f"{req.account.id}: falta o token TikTok no .env")
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"}
        creator = request("POST", f"{API}/post/publish/creator_info/query/", headers=headers).json()["data"]
        privacy = os.environ.get("TIKTOK_PRIVACY", "SELF_ONLY")
        if privacy not in creator.get("privacy_level_options", [privacy]):
            privacy = creator["privacy_level_options"][0]

        video = Path(req.media[0])
        # a duração máxima depende da conta (3, 5 ou 10 min): validar antes de enviar
        max_sec = creator.get("max_video_post_duration_sec")
        if max_sec:
            from ..media.video_editor import probe
            secs = probe(video).duration
            if secs > float(max_sec) + 0.5:
                raise ApiError(f"vídeo com {secs:.0f} s; esta conta TikTok só aceita até {int(max_sec)} s")
        size = video.stat().st_size
        chunk = size if size <= CHUNK else CHUNK
        count = max(1, size // chunk) if size > CHUNK else 1
        init = request("POST", f"{API}/post/publish/video/init/", headers=headers, json={
            "post_info": {
                "title": req.caption[:2200], "privacy_level": privacy,
                "disable_comment": False, "disable_duet": False, "disable_stitch": False,
                "video_cover_timestamp_ms": 1000,
            },
            "source_info": {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk,
                            "total_chunk_count": count},
        }).json()["data"]
        data = video.read_bytes()
        for i in range(count):
            start = i * chunk
            end = size - 1 if i == count - 1 else start + chunk - 1   # último bloco leva o resto
            request("PUT", init["upload_url"], headers={
                "Content-Type": "video/mp4", "Content-Range": f"bytes {start}-{end}/{size}",
                "Content-Length": str(end - start + 1)}, data=data[start:end + 1], timeout=900)
        return self._wait(init["publish_id"], headers, privacy)

    def _wait(self, publish_id: str, headers: dict, privacy: str, timeout: int = 900) -> PublishResult:
        start = time.time()
        while time.time() - start < timeout:
            st = request("POST", f"{API}/post/publish/status/fetch/", headers=headers,
                         json={"publish_id": publish_id}).json()["data"]
            if st["status"] == "PUBLISH_COMPLETE":
                ids = st.get("publicaly_available_post_id") or st.get("publicly_available_post_id") or []
                return PublishResult(remote_id=str(ids[0]) if ids else publish_id,
                                     note=f"privacidade: {privacy}")
            if st["status"] == "FAILED":
                raise ApiError(f"TikTok falhou: {st.get('fail_reason')}")
            time.sleep(6)
        raise ApiError("TikTok demorou demasiado a processar")

