"""Narração (texto → voz) gratuita e local com Piper, voz portuguesa de Portugal.

O modelo (~60 MB) é descarregado automaticamente na primeira utilização para models/piper/.
Para usar outra voz, define PIPER_VOICE (nome do ficheiro .onnx, ex.: pt_PT-tugão-medium).
"""
from __future__ import annotations

import os
import subprocess
import wave
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

import requests

from ..config import ROOT

VOICE = os.environ.get("PIPER_VOICE", "pt_PT-tugão-medium")
MODELS = ROOT / "models" / "piper"
HF = "https://huggingface.co/rhasspy/piper-voices/resolve/main"


def _voice_url(name: str, suffix: str) -> str:
    lang, speaker, quality = name.split("-")
    family = lang.split("_")[0]
    return f"{HF}/{family}/{lang}/{quote(speaker)}/{quality}/{quote(name)}{suffix}"


def ensure_voice(name: str = VOICE) -> Path:
    MODELS.mkdir(parents=True, exist_ok=True)
    model = MODELS / f"{name}.onnx"
    for suffix in (".onnx.json", ".onnx"):
        path = MODELS / f"{name}{suffix}"
        if path.exists() and path.stat().st_size > 0:
            continue
        print(f"A descarregar a voz {name}{suffix} (só da primeira vez)...")
        with requests.get(_voice_url(name, suffix), stream=True, timeout=300) as r:
            r.raise_for_status()
            tmp = path.with_suffix(path.suffix + ".part")
            with open(tmp, "wb") as fh:
                for chunk in r.iter_content(1 << 20):
                    fh.write(chunk)
            tmp.rename(path)
    return model


@lru_cache
def _load(name: str = VOICE):
    from piper import PiperVoice  # type: ignore
    return PiperVoice.load(str(ensure_voice(name)))


def speak(text: str, out: str | Path, speed: float = 1.0) -> float:
    """Gera a narração em WAV e devolve a duração em segundos. speed>1 = mais rápido."""
    from piper import SynthesisConfig  # type: ignore
    out = Path(out)
    with wave.open(str(out), "wb") as w:
        _load().synthesize_wav(text, w, syn_config=SynthesisConfig(length_scale=1 / speed))
    with wave.open(str(out), "rb") as w:
        return w.getnframes() / float(w.getframerate())


def silence(seconds: float, out: str | Path) -> float:
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=22050:cl=mono",
                    "-t", f"{seconds:.3f}", str(out)], check=True)
    return seconds
