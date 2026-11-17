"""Alojamento público de ficheiros.

O Instagram (imagens/carrosséis/capas) exige um URL público para cada ficheiro.
Opções (variável MEDIA_HOST no .env):
  s3      -> envia para um bucket S3/Cloudflare R2 (pip install boto3)
  folder  -> copia para uma pasta já servida por um site teu (MEDIA_FOLDER + MEDIA_BASE_URL)
"""
from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path


def public_url(path: str | Path) -> str:
    path = Path(path)
    digest = hashlib.sha1(path.read_bytes()).hexdigest()[:12]
    key = f"carretos/{digest}-{path.name}"
    host = os.environ.get("MEDIA_HOST", "folder")
    if host == "s3" and not os.environ.get("S3_BUCKET"):
        host = "folder"                      # sem bucket configurado: usa o próprio servidor (/publico/)
    base = os.environ.get("MEDIA_BASE_URL", "").rstrip("/")
    if host == "s3":
        import boto3  # type: ignore

        s3 = boto3.client("s3", endpoint_url=os.environ.get("S3_ENDPOINT_URL") or None)
        bucket = os.environ["S3_BUCKET"]
        ctype = "video/mp4" if path.suffix == ".mp4" else "image/jpeg"
        s3.upload_file(str(path), bucket, key, ExtraArgs={"ContentType": ctype})
        return f"{base or f'https://{bucket}.s3.amazonaws.com'}/{key}"
    folder = os.environ.get("MEDIA_FOLDER")
    if not folder or not base:
        # por defeito: o próprio servidor, em <endereço do dashboard>/publico/ (nomes impossíveis de adivinhar)
        from ..config import DATA_DIR, ROOT
        addr = ROOT / "ENDERECO_DASHBOARD.txt"
        if not addr.exists() or not addr.read_text().strip().startswith("https://"):
            raise RuntimeError("Sem endereço público: falta ENDERECO_DASHBOARD.txt (https://…) ou MEDIA_BASE_URL")
        folder, base = str(DATA_DIR / "publico"), addr.read_text().strip().rstrip("/") + "/publico"
        key = f"{hashlib.sha256(path.read_bytes() + os.environ.get('DASHBOARD_SECRET', 'cs').encode()).hexdigest()[:32]}{path.suffix.lower()}"
        _cleanup(Path(folder))
    dest = Path(folder) / key
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(path, dest)
    return f"{base}/{key}"


def _cleanup(folder: Path, days: int = 7) -> None:
    """Os ficheiros públicos só são precisos enquanto a rede os vai buscar: apaga os com mais de 7 dias."""
    import time
    if not folder.exists():
        return
    limit = time.time() - days * 86400
    for f in folder.glob("*"):
        if f.is_file() and f.stat().st_mtime < limit:
            f.unlink(missing_ok=True)
