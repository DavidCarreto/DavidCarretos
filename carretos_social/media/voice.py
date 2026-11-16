"""Narração (texto → voz), gratuita e local.

Dois motores:
  piper       voz genérica portuguesa de Portugal (rápida; ~60 MB, descarregada na 1.ª utilização)
  conversion  a TUA voz com sotaque de Portugal: o Piper diz o texto com pronúncia PT-PT e o
              conversor Chatterbox VC aplica o teu timbre (gravação de referência). Recomendado.
  chatterbox  clone direto (Chatterbox Multilingual). Mais natural, mas o sotaque tende para o
              português do Brasil. Mais lento em CPU.
  (Chatterbox: código aberto MIT, uso comercial permitido.)

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

# descarrega modelos por HTTP normal (mais compatível com proxies/firewalls)
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

PIPER_VOICE = os.environ.get("PIPER_VOICE", "pt_PT-tugão-medium")
MODELS = ROOT / "models" / "piper"
HF = "https://huggingface.co/rhasspy/piper-voices/resolve/main"
DEFAULT_NARRATOR = {"engine": "piper", "voice": PIPER_VOICE}


# ------------------------------------------------------------------ narradores
def narrator(name: str | None) -> dict:
    narrators = brand().get("narrators", {})
    cfg = dict(narrators.get(name or "", {}) or DEFAULT_NARRATOR)
    if cfg.get("engine") == "elevenlabs" and not os.environ.get("ELEVENLABS_API_KEY"):
        print(f"⚠️  Narrador '{name}' (ElevenLabs) sem chave; a usar a voz genérica.")
        return dict(narrators.get("generica", DEFAULT_NARRATOR))
    if cfg.get("engine") in ("chatterbox", "conversion"):
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
    return ChatterboxMultilingualTTS.from_pretrained(device=device)  # texto: "cpu" | "mps" | "cuda"


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


# ------------------------------------------------------------------ conversão (sotaque PT-PT + o teu timbre)
@lru_cache
def _vc():
    from chatterbox.vc import ChatterboxVC  # type: ignore
    print("A carregar o conversor de voz (Chatterbox VC)...")
    return ChatterboxVC.from_pretrained(_device())


def _device() -> str:
    import torch  # type: ignore
    return "cuda" if torch.cuda.is_available() else ("mps" if torch.backends.mps.is_available() else "cpu")


def _speak_conversion(text: str, out: Path, speed: float, cfg: dict) -> None:
    """A voz portuguesa de Portugal (Piper) diz o texto com a pronúncia certa e o conversor
    transforma o timbre na voz da gravação de referência."""
    import torchaudio as ta  # type: ignore
    base = out.with_suffix(".base.wav")
    _speak_piper(text, base, speed, cfg.get("base_voice", PIPER_VOICE))
    wav = _vc().generate(str(base), target_voice_path=str(_path(cfg["sample"])))
    ta.save(str(out), wav.cpu(), _vc().sr)
    base.unlink(missing_ok=True)


# ------------------------------------------------------------------ ElevenLabs (pago, opcional)
def _speak_elevenlabs(text: str, out: Path, speed: float, cfg: dict) -> None:
    """Voz clonada na ElevenLabs (plano pago). Requer ELEVENLABS_API_KEY e o voice_id do clone."""
    key = os.environ.get("ELEVENLABS_API_KEY")
    voice_id = cfg.get("voice_id") or os.environ.get("ELEVENLABS_VOICE_ID")
    if not key or not voice_id:
        raise RuntimeError("ElevenLabs não configurado: falta ELEVENLABS_API_KEY ou voice_id")
    from ..http import request
    resp = request("POST", f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                   params={"output_format": "mp3_44100_128"},
                   headers={"xi-api-key": key, "Content-Type": "application/json"},
                   json={"text": text, "model_id": cfg.get("model", "eleven_multilingual_v2"),
                         "voice_settings": {"stability": float(cfg.get("stability", 0.5)),
                                            "similarity_boost": float(cfg.get("similarity", 0.85)),
                                            "style": float(cfg.get("style", 0.2)),
                                            "use_speaker_boost": True}}, timeout=180)
    mp3 = out.with_suffix(".mp3")
    mp3.write_bytes(resp.content)
    tempo = max(0.5, min(2.0, speed))
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(mp3), "-af", f"atempo={tempo}", "-ar", "44100",
                    str(out)], check=True)
    mp3.unlink(missing_ok=True)


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
        elif cfg.get("engine") == "conversion":
            _speak_conversion(text, cache, speed, cfg)
        elif cfg.get("engine") == "elevenlabs":
            _speak_elevenlabs(text, cache, speed, cfg)
        else:
            _speak_piper(text, cache, speed, cfg.get("voice", PIPER_VOICE))
    shutil.copy(cache, out)
    return duration(out)


def silence(seconds: float, out: str | Path) -> float:
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=22050:cl=mono",
                    "-t", f"{seconds:.3f}", str(out)], check=True)
    return seconds


def _load_mono(path, sr: int):
    import numpy as np
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(sr),
                          "-af", "highpass=f=60", "-f", "f32le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).copy()


def _speaker_encoder():
    """Codificador de voz do Chatterbox (para medir semelhança de timbre). None se indisponível."""
    try:
        import torch  # type: ignore
        from chatterbox.models.voice_encoder import VoiceEncoder  # type: ignore
        from huggingface_hub import hf_hub_download  # type: ignore
    except ImportError:
        return None
    ve = VoiceEncoder()
    ve.load_state_dict(torch.load(hf_hub_download("ResembleAI/chatterbox", "ve.pt"), map_location="cpu"))
    return ve.eval()


def prepare_sample(src: str | Path, out: str | Path, max_seconds: float = 10.0) -> dict:
    """Prepara a gravação de referência para o clone.

    - SEM redução de ruído nem filtros fortes (medido: os filtros reduziam a semelhança do timbre
      de 0,92 para 0,83); só remove graves muito baixos e normaliza o pico.
    - Junta só os trechos com fala e escolhe a janela de `max_seconds` (o conversor usa 10 s)
      cuja voz é mais representativa de toda a gravação.
    """
    import numpy as np
    import soundfile as sf  # type: ignore
    from .video_editor import detect_speech
    sr = 24000
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    audio = _load_mono(src, sr)
    tmp = out.with_suffix(".tmp.wav")
    sf.write(tmp, audio, sr)
    ranges = detect_speech(tmp, noise_db=-38, min_silence=0.6, pad=0.15)
    tmp.unlink(missing_ok=True)
    speech = np.concatenate([audio[int(s * sr):int(e * sr)] for s, e in ranges]) if ranges else audio
    win = int(max_seconds * sr)
    best, score = speech[:win], None
    ve = _speaker_encoder() if len(speech) > win * 1.5 else None
    if ve is not None:
        import librosa  # type: ignore

        def emb(w):
            e = ve.embeds_from_wavs([librosa.resample(w, orig_sr=sr, target_sr=16000)], sample_rate=16000)[0]
            return e / np.linalg.norm(e)
        whole = emb(speech)
        step = int(2 * sr)
        for start in range(0, len(speech) - win + 1, step):
            cand = speech[start:start + win]
            sim = float(emb(cand) @ whole)
            if score is None or sim > score:
                best, score = cand, sim
    best = best / max(1e-6, float(np.abs(best).max())) * 0.89  # pico a -1 dB
    sf.write(out, best, sr)
    return {"sample": str(out), "speech_seconds": round(len(best) / sr, 1),
            "total_speech_seconds": round(len(speech) / sr, 1),
            "representativeness": round(score, 3) if score is not None else None}


def collect_voice(folder: str | Path, reference: str | Path, out_dir: str | Path, threshold: float = 0.82,
                  window: float = 4.0) -> dict:
    """Percorre vídeos/áudios de uma pasta e guarda SÓ os trechos em que fala a pessoa da referência.

    Cada janela de `window` segundos é comparada com a voz de referência (codificador de voz);
    janelas com semelhança >= threshold são juntadas e exportadas como WAV (24 kHz) em out_dir.
    Devolve um relatório por ficheiro. Serve para preparar material de treino/clonagem.
    """
    import numpy as np
    import soundfile as sf  # type: ignore
    ve = _speaker_encoder()
    if ve is None:
        raise RuntimeError("Precisa do chatterbox-tts instalado para verificar a voz.")
    import librosa  # type: ignore
    sr = 16000

    def emb(w):
        e = ve.embeds_from_wavs([w], sample_rate=sr)[0]
        return e / np.linalg.norm(e)

    ref = emb(_load_mono(reference, sr))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    exts = {".mp4", ".mov", ".m4v", ".m4a", ".mp3", ".wav", ".webm"}
    report = {}
    for f in sorted(p for p in Path(folder).iterdir() if p.suffix.lower() in exts):
        try:
            audio = _load_mono(f, sr)
        except subprocess.CalledProcessError:
            report[f.name] = {"erro": "sem áudio"}
            continue
        win, step = int(window * sr), int(window * sr / 2)
        keep, sims = [], []
        for start in range(0, max(1, len(audio) - win + 1), step):
            seg = audio[start:start + win]
            if float(np.sqrt((seg ** 2).mean())) < 0.01:
                continue
            s = float(emb(seg) @ ref)
            sims.append(s)
            if s >= threshold:
                keep.append((start, start + win))
        merged: list[list[int]] = []
        for s, e in keep:
            if merged and s <= merged[-1][1]:
                merged[-1][1] = e
            else:
                merged.append([s, e])
        secs = sum(e - s for s, e in merged) / sr
        if merged:
            clip = np.concatenate([audio[s:e] for s, e in merged])
            clip24 = librosa.resample(clip, orig_sr=sr, target_sr=24000)
            sf.write(out_dir / f"{f.stem}.wav", clip24, 24000)
        report[f.name] = {"duracao": round(len(audio) / sr, 1), "fala_tua_s": round(secs, 1),
                          "semelhanca_max": round(max(sims), 2) if sims else None,
                          "semelhanca_media": round(float(np.mean(sims)), 2) if sims else None}
    return report
