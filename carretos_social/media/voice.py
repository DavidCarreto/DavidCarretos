"""Narração (texto → voz), gratuita e local.

Dois motores:
  piper       voz genérica portuguesa de Portugal (rápida; ~60 MB, descarregada na 1.ª utilização)
  chatterbox  a TUA voz, clonada a partir de uma gravação de referência (Chatterbox Multilingual,
              código aberto MIT, uso comercial permitido). Mais lento em CPU.

Os narradores estão definidos em config/brand.yaml (secção `narrators`) e cada conta escolhe o seu
em config/accounts.yaml (`narrator`). Se o clone não estiver disponível (sem gravação ou sem o pacote
instalado), o sistema usa automaticamente a voz genérica e avisa.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import wave
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

import requests

from ..config import DATA_DIR, ROOT, brand

PIPER_VOICE = os.environ.get("PIPER_VOICE", "pt_PT-tugão-medium")
MODELS = ROOT / "models" / "piper"
HF = "https://huggingface.co/rhasspy/piper-voices/resolve/main"
DEFAULT_NARRATOR = {"engine": "piper", "voice": PIPER_VOICE}


# ------------------------------------------------------------------ narradores
def narrator(name: str | None) -> dict:
    narrators = brand().get("narrators", {})
    cfg = dict(narrators.get(name or "", {}) or DEFAULT_NARRATOR)
    if cfg.get("engine") == "chatterbox":
        problem = clone_problem(cfg)
        if problem:
            print(f"⚠️  Narrador '{name}' indisponível ({problem}); a usar a voz genérica.")
            return dict(narrators.get("generica", DEFAULT_NARRATOR))
    return cfg


def clone_problem(cfg: dict) -> str | None:
    sample = _path(cfg.get("sample", ""))
    if not sample or not sample.exists():
        return f"falta a gravação de referência {cfg.get('sample')} — corre `carretos voice-setup <gravação>`"
    try:
        import chatterbox  # noqa: F401  # type: ignore
    except ImportError:
        return "pacote chatterbox-tts não instalado (pip install chatterbox-tts)"
    return None


def _path(p: str) -> Path | None:
    if not p:
        return None
    path = Path(p)
    return path if path.is_absolute() else ROOT / path


# ------------------------------------------------------------------ piper
def _voice_url(name: str, suffix: str) -> str:
    lang, speaker, quality = name.split("-")
    family = lang.split("_")[0]
    return f"{HF}/{family}/{lang}/{quote(speaker)}/{quality}/{quote(name)}{suffix}"


def ensure_voice(name: str = PIPER_VOICE) -> Path:
    MODELS.mkdir(parents=True, exist_ok=True)
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
    return MODELS / f"{name}.onnx"


@lru_cache
def _piper(name: str):
    from piper import PiperVoice  # type: ignore
    return PiperVoice.load(str(ensure_voice(name)))


def _speak_piper(text: str, out: Path, speed: float, name: str) -> None:
    from piper import SynthesisConfig  # type: ignore
    with wave.open(str(out), "wb") as w:
        _piper(name).synthesize_wav(text, w, syn_config=SynthesisConfig(length_scale=1 / speed))


# ------------------------------------------------------------------ chatterbox (clone)
@lru_cache
def _chatterbox():
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    import torch  # type: ignore
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS  # type: ignore
    device = "cuda" if torch.cuda.is_available() else ("mps" if torch.backends.mps.is_available() else "cpu")
    torch.set_num_threads(max(1, os.cpu_count() or 1))
    print(f"A carregar o clone de voz (Chatterbox, {device})...")
    return ChatterboxMultilingualTTS.from_pretrained(device=torch.device(device))


def _sentences(text: str, max_chars: int = 220) -> list[str]:
    parts = re.split(r"(?<=[.!?…])\s+", text.strip())
    out: list[str] = []
    for p in parts:
        while len(p) > max_chars:  # frases muito longas: corta numa vírgula
            cut = p.rfind(",", 0, max_chars)
            cut = cut if cut > 40 else max_chars
            out.append(p[:cut + 1].strip())
            p = p[cut + 1:].strip()
        if p:
            out.append(p)
    return out


def _speak_chatterbox(text: str, out: Path, speed: float, cfg: dict) -> None:
    import torch  # type: ignore
    import torchaudio as ta  # type: ignore
    model = _chatterbox()
    sample = str(_path(cfg["sample"]))
    chunks = []
    pause = torch.zeros(1, int(model.sr * 0.18))
    for sentence in _sentences(text):
        wav = model.generate(sentence, language_id=cfg.get("language", "pt"), audio_prompt_path=sample,
                             exaggeration=float(cfg.get("exaggeration", 0.5)),
                             cfg_weight=float(cfg.get("cfg_weight", 0.5)),
                             temperature=float(cfg.get("temperature", 0.8)))
        chunks += [wav.cpu(), pause]
    raw = out.with_suffix(".raw.wav")
    ta.save(str(raw), torch.cat(chunks[:-1], dim=1), model.sr)
    # acelera ligeiramente sem mudar o tom e corta silêncios nas pontas
    tempo = max(0.5, min(2.0, speed))
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(raw), "-af",
                    f"atempo={tempo},silenceremove=start_periods=1:start_threshold=-45dB,"
                    "areverse,silenceremove=start_periods=1:start_threshold=-45dB,areverse",
                    str(out)], check=True)
    raw.unlink(missing_ok=True)


# ------------------------------------------------------------------ API
def duration(path: str | Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate())


def speak(text: str, out: str | Path, speed: float = 1.0, narrator_name: str | None = None) -> float:
    """Gera a narração em WAV e devolve a duração (s). Resultados em cache (texto+voz+velocidade)."""
    out = Path(out)
    cfg = narrator(narrator_name)
    key = hashlib.sha1(f"{sorted(cfg.items())}|{speed}|{text}".encode()).hexdigest()[:16]
    cache = DATA_DIR / "cache" / "tts" / f"{key}.wav"
    if not cache.exists():
        cache.parent.mkdir(parents=True, exist_ok=True)
        if cfg.get("engine") == "chatterbox":
            _speak_chatterbox(text, cache, speed, cfg)
        else:
            _speak_piper(text, cache, speed, cfg.get("voice", PIPER_VOICE))
    shutil.copy(cache, out)
    return duration(out)


def silence(seconds: float, out: str | Path) -> float:
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=22050:cl=mono",
                    "-t", f"{seconds:.3f}", str(out)], check=True)
    return seconds


def prepare_sample(src: str | Path, out: str | Path, max_seconds: float = 25.0) -> dict:
    """Prepara a gravação de referência: mono 24 kHz, sem ruído de fundo, volume normalizado e
    só a parte com fala (até max_seconds — o Chatterbox precisa de ~10–25 s limpos)."""
    from .video_editor import detect_speech, probe
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp.wav")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", "24000",
                    "-af", "highpass=f=80,lowpass=f=12000,afftdn=nf=-25,loudnorm=I=-18:TP=-2",
                    str(tmp)], check=True)
    ranges = detect_speech(tmp, noise_db=-38, min_silence=0.6, pad=0.15)
    keep, total = [], 0.0
    for s, e in ranges:  # junta blocos de fala até max_seconds
        if total >= max_seconds:
            break
        e = min(e, s + (max_seconds - total))
        keep.append((s, e))
        total += e - s
    select = "+".join(f"between(t,{s:.2f},{e:.2f})" for s, e in keep)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(tmp), "-af",
                    f"aselect='{select}',asetpts=N/SR/TB", str(out)], check=True)
    tmp.unlink(missing_ok=True)
    original = probe(src).duration if Path(src).suffix.lower() in (".mp4", ".mov", ".m4v") else None
    return {"sample": str(out), "speech_seconds": round(duration(out), 1), "original_seconds": original}
