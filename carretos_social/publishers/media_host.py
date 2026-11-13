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
        raise RuntimeError("Configura MEDIA_HOST=s3 (S3_BUCKET) ou MEDIA_FOLDER + MEDIA_BASE_URL no .env")
    dest = Path(folder) / key
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(path, dest)
    return f"{base}/{key}"
