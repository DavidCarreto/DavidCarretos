"""Avatar do David a falar (HeyGen, serviço PAGO — só é usado se HEYGEN_API_KEY estiver configurada).

Fluxo: guião → HeyGen gera o vídeo com o avatar e a voz clonada do David → o sistema descarrega-o e
aplica o mesmo acabamento dos outros vídeos (legendas karaoke douradas, música, assinatura, capa).

Configuração (.env): HEYGEN_API_KEY, HEYGEN_AVATAR_ID (o teu "digital twin"), HEYGEN_VOICE_ID (a tua voz).
Os vídeos realistas feitos com IA devem ser identificados como tal nas redes (o sistema avisa).
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from ..http import ApiError, request

API = "https://api.heygen.com"


def configured() -> bool:
    return all(os.environ.get(k) for k in ("HEYGEN_API_KEY", "HEYGEN_AVATAR_ID", "HEYGEN_VOICE_ID"))


def generate(script: str, out: str | Path, width: int = 1080, height: int = 1920, timeout: int = 1800) -> Path:
    if not configured():
        raise RuntimeError("HeyGen não configurado (HEYGEN_API_KEY, HEYGEN_AVATAR_ID, HEYGEN_VOICE_ID). "
                           "É um serviço pago: só ativar com aprovação.")
    headers = {"X-Api-Key": os.environ["HEYGEN_API_KEY"], "Content-Type": "application/json"}
    body = {
        "video_inputs": [{
            "character": {"type": "avatar", "avatar_id": os.environ["HEYGEN_AVATAR_ID"], "avatar_style": "normal"},
            "voice": {"type": "text", "input_text": script, "voice_id": os.environ["HEYGEN_VOICE_ID"]},
        }],
        "dimension": {"width": width, "height": height},
    }
    video_id = request("POST", f"{API}/v2/video/generate", headers=headers, json=body).json()["data"]["video_id"]
    start = time.time()
    while time.time() - start < timeout:
        st = request("GET", f"{API}/v1/video_status.get", headers=headers, params={"video_id": video_id}).json()["data"]
        if st.get("status") == "completed":
            out = Path(out)
            out.write_bytes(request("GET", st["video_url"], timeout=600).content)
            return out
        if st.get("status") == "failed":
            raise ApiError(f"HeyGen falhou: {st.get('error')}")
        time.sleep(15)
    raise ApiError("HeyGen demorou demasiado")
