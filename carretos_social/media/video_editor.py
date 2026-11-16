"""Edição automática de vídeo com ffmpeg.

Pipeline (`auto_edit`):
  1. transcrição (faster-whisper, opcional)        -> legendas e escolha de cortes
  2. escolha dos melhores momentos (Claude, opcional) ou remoção de silêncios
  3. reenquadramento para o formato da plataforma (9:16, 4:5...) com fundo desfocado ou recorte
  4. legendas grandes "estilo Reels" + texto de gancho nos primeiros segundos
  5. logótipo, música de fundo, normalização de áudio (-14 LUFS)
  6. intro/outro da marca
  7. exportação H.264 de alta qualidade + escolha automática do melhor frame para a capa
"""
from __future__ import annotations

import json
import random
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageFilter, ImageStat

from ..config import ROOT, brand


class VideoError(RuntimeError):
    pass


def _run(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise VideoError(f"{' '.join(cmd[:3])}... falhou:\n{proc.stderr[-2000:]}")
    return proc.stderr + proc.stdout


def require_ffmpeg() -> None:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise VideoError("ffmpeg não está instalado (https://ffmpeg.org/download.html).")


# ------------------------------------------------------------------ informação
@dataclass
class VideoInfo:
    duration: float
    width: int
    height: int
    has_audio: bool
    fps: float = 30.0


def probe(path: str | Path, allow_audio_only: bool = False) -> VideoInfo:
    out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams",
                          "-show_format", str(path)], capture_output=True, text=True)
    if out.returncode != 0:
        raise VideoError(f"Não consegui ler {path}: {out.stderr}")
    data = json.loads(out.stdout)
    video = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
    if not video:
        if allow_audio_only and any(s["codec_type"] == "audio" for s in data["streams"]):
            return VideoInfo(duration=float(data["format"].get("duration", 0)), width=0, height=0, has_audio=True)
        raise VideoError(f"{path} não tem faixa de vídeo")
    w, h = int(video["width"]), int(video["height"])
    rotation = 0
    for sd in video.get("side_data_list", []):
        rotation = int(sd.get("rotation", 0) or 0)
    rotation = rotation or int(video.get("tags", {}).get("rotate", 0) or 0)
    if abs(rotation) in (90, 270):  # vídeos verticais de telemóvel
        w, h = h, w
    num, _, den = video.get("avg_frame_rate", "30/1").partition("/")
    fps = float(num) / float(den or 1) if float(den or 1) and float(num or 0) else 30.0
    return VideoInfo(
        duration=float(data["format"].get("duration", video.get("duration", 0))),
        width=w, height=h, fps=fps,
        has_audio=any(s["codec_type"] == "audio" for s in data["streams"]),
    )


# ------------------------------------------------------------------ transcrição
VOCAB = ("Mercedes-Benz, Carretos Group, Carreto Clips, David Carreto, oficina, AMG, OM651, OM654, "
         "M274, 7G-Tronic, 9G-Tronic, AIRMATIC, AdBlue, injetores, embraiagem, diagnóstico")


def load_audio(path: str | Path, sr: int = 16000):
    """Descodifica o áudio com ffmpeg para um array numpy mono (sem depender do PyAV)."""
    import numpy as np
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "s16le", "-ac", "1", "-ar", str(sr), "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0


_WHISPER_LOCK = __import__("threading").Lock()


@__import__("functools").lru_cache(maxsize=2)
def _whisper(size: str):
    """Modelo de reconhecimento de voz carregado uma só vez por processo (fica em memória)."""
    from faster_whisper import WhisperModel  # type: ignore
    return WhisperModel(size, device="auto", compute_type="int8")


def dictate(path: str | Path, language: str = "pt") -> str:
    """Ditado: transforma uma gravação curta (microfone do dashboard) em texto corrido.
    Definições rápidas (sem tempos por palavra, pesquisa simples): ~30% mais rápido que as legendas."""
    import os
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    model = _whisper(os.environ.get("WHISPER_MODEL", "small"))
    with _WHISPER_LOCK:
        segments, _ = model.transcribe(load_audio(path), language=language, beam_size=1, without_timestamps=True,
                                       vad_filter=True, condition_on_previous_text=False)
        # sem a lista técnica (VOCAB): no ditado fazia aparecer palavras que não foram ditas
        text = " ".join(seg.text.strip() for seg in segments)
    return fix_words(text).strip()


def preload_dictation() -> None:
    """Carrega o modelo de voz em memória (no arranque do dashboard), para o 1.º ditado não esperar."""
    import os
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    try:
        _whisper(os.environ.get("WHISPER_MODEL", "small"))
    except Exception:  # noqa: BLE001 — sem modelo/sem rede: carrega no 1.º pedido
        pass


def transcribe(path: str | Path, language: str = "pt", model_size: str | None = None) -> list[dict]:
    """Transcrição com tempos por palavra (faster-whisper, gratuito e local)."""
    import os
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError as exc:
        raise VideoError("Para legendas automáticas instala: pip install faster-whisper") from exc
    model = _whisper(model_size or os.environ.get("WHISPER_MODEL", "small"))
    with _WHISPER_LOCK:  # um pedido de cada vez (o modelo usa todos os processadores)
        segments, _ = model.transcribe(load_audio(path), language=language, word_timestamps=True, vad_filter=True,
                                       initial_prompt=VOCAB)
        segments = list(segments)
    out = []
    for s in segments:
        out.append({
            "start": round(float(s.start), 2), "end": round(float(s.end), 2), "text": fix_words(s.text.strip()),
            "words": [{"start": float(w.start), "end": float(w.end), "word": fix_words(w.word.strip())}
                      for w in (s.words or [])],
        })
    return out


def fix_words(text: str) -> str:
    """Corrige erros típicos do reconhecimento de voz em nomes próprios (brand.yaml → transcription_fixes)."""
    fixes = brand().get("transcription_fixes") or {}
    for wrong, right in fixes.items():
        text = re.sub(rf"(?i)\b{re.escape(wrong)}\b", right, text)
    return text


# ------------------------------------------------------------------ silêncios / cortes
def detect_speech(path: str | Path, noise_db: int = -32, min_silence: float = 0.45,
                  pad: float = 0.12) -> list[tuple[float, float]]:
    """Intervalos com som (remove pausas maiores que min_silence)."""
    info = probe(path, allow_audio_only=True)
    if not info.has_audio:
        return [(0.0, info.duration)]
    log = _run(["ffmpeg", "-hide_banner", "-i", str(path), "-af",
                f"silencedetect=noise={noise_db}dB:d={min_silence}", "-f", "null", "-"])
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", log)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", log)]
    keep, cursor = [], 0.0
    for s, e in zip(starts, ends + [info.duration] * (len(starts) - len(ends))):
        if s - cursor > 0.2:
            keep.append((max(0.0, cursor - pad), min(info.duration, s + pad)))
        cursor = e
    if info.duration - cursor > 0.2:
        keep.append((max(0.0, cursor - pad), info.duration))
    return _merge(keep) or [(0.0, info.duration)]


def _merge(ranges: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[list[float]] = []
    for s, e in sorted(ranges):
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [(round(s, 3), round(e, 3)) for s, e in out]


def cut(path: str | Path, ranges: list[tuple[float, float]], out: str | Path) -> Path:
    """Junta os intervalos indicados num único vídeo."""
    info = probe(path)
    parts, labels = [], []
    for i, (s, e) in enumerate(ranges):
        parts.append(f"[0:v]trim=start={s}:end={e},setpts=PTS-STARTPTS[v{i}]")
        labels.append(f"[v{i}]")
        if info.has_audio:
            parts.append(f"[0:a]atrim=start={s}:end={e},asetpts=PTS-STARTPTS[a{i}]")
            labels.append(f"[a{i}]")
    a = 1 if info.has_audio else 0
    graph = ";".join(parts) + f";{''.join(labels)}concat=n={len(ranges)}:v=1:a={a}[v]" + ("[a]" if a else "")
    cmd = ["ffmpeg", "-y", "-hide_banner", "-i", str(path), "-filter_complex", graph, "-map", "[v]"]
    if a:
        cmd += ["-map", "[a]", "-c:a", "aac", "-b:a", "192k"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "16", str(out)]
    _run(cmd)
    return Path(out)


def remap_segments(segments: list[dict], ranges: list[tuple[float, float]]) -> list[dict]:
    """Ajusta os tempos da transcrição à nova linha temporal depois dos cortes."""
    out, offset = [], 0.0
    for s, e in ranges:
        for seg in segments:
            words = [w for w in seg.get("words", []) if w["start"] >= s and w["end"] <= e + 0.05]
            if not words and not (seg["start"] >= s and seg["end"] <= e):
                continue
            shift = offset - s
            new_words = [{**w, "start": w["start"] + shift, "end": min(w["end"], e) + shift} for w in words]
            out.append({
                "start": max(seg["start"], s) + shift, "end": min(seg["end"], e) + shift,
                "text": " ".join(w["word"] for w in words) if words else seg["text"], "words": new_words,
            })
        offset += e - s
    return out


# ------------------------------------------------------------------ legendas (ASS)
def _ass_time(t: float) -> str:
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _ass_color(hex_color: str) -> str:
    hex_color = hex_color.lstrip("#")
    r, g, b = hex_color[0:2], hex_color[2:4], hex_color[4:6]
    return f"&H00{b}{g}{r}".upper()


def build_ass(segments: list[dict], width: int, height: int, hook_text: str = "",
              hook_seconds: float = 3.0, words_per_line: int = 3, duration: float = 0.0) -> str:
    v = brand()["visual"]
    font = Path(v["font_bold"]).stem.split("-")[0] or "Inter"
    accent = _ass_color(v["colors"]["accent"])
    size = int(width * 0.085)
    hook_size = int(width * 0.068)
    margin_v = int(height * 0.24)
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}",
        "WrapStyle: 0", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Sub,{font},{size},&H00FFFFFF,{accent},&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,"
        f"{max(4, size // 12)},2,2,60,60,{margin_v},1",
        f"Style: Hook,{font},{hook_size},&H00FFFFFF,&H00FFFFFF,&H00000000,{accent.replace('&H00', '&H20')},"
        f"-1,0,0,0,100,100,0,0,3,{max(10, hook_size // 4)},0,8,80,80,{int(height * 0.12)},1",
        f"Style: Sign,{font},{int(width * 0.03)},{accent},{accent},&H00000000,&H64000000,-1,0,0,0,100,100,"
        f"{int(width * 0.004)},0,1,0,1,3,0,{int(width * 0.06)},{int(height * 0.03)},1",
        f"Style: Line,{font},10,{accent},{accent},&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    signature = brand().get("signature")
    if duration and signature and not v.get("logo"):
        # assinatura discreta no canto inferior direito, sem riscas (pedido do David)
        end = _ass_time(duration + 1)
        lines.append(f"Dialogue: 2,{_ass_time(0)},{end},Sign,,0,0,0,,{_ass_escape(signature.upper())}")
    if hook_text:
        lines.append(f"Dialogue: 1,{_ass_time(0)},{_ass_time(hook_seconds)},Hook,,0,0,0,,"
                     f"{{\\fad(150,250)}}{_ass_escape(hook_text.upper())}")
    for seg in segments:
        words = seg.get("words") or _fake_words(seg)
        for i in range(0, len(words), words_per_line):
            chunk = words[i:i + words_per_line]
            start, end = chunk[0]["start"], chunk[-1]["end"]
            if i + words_per_line < len(words):
                end = max(end, words[i + words_per_line]["start"])
            # palavra a ser dita fica na cor de destaque (karaoke)
            text = "".join(
                f"{{\\kf{max(1, int((w['end'] - w['start']) * 100))}}}{_ass_escape(w['word'].upper())} "
                for w in chunk).strip()
            lines.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Sub,,0,0,0,,"
                         f"{{\\fscx92\\fscy92\\t(0,90,\\fscx100\\fscy100)}}{text}")
    return "\n".join(lines) + "\n"


def _fake_words(seg: dict) -> list[dict]:
    toks = seg["text"].split()
    if not toks:
        return []
    step = (seg["end"] - seg["start"]) / len(toks)
    return [{"start": seg["start"] + i * step, "end": seg["start"] + (i + 1) * step, "word": t}
            for i, t in enumerate(toks)]


_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️‍]+")


def _ass_escape(s: str) -> str:
    # o libass desenha emojis como quadrados: remove-os
    s = _EMOJI.sub("", s)
    return s.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ").strip()


def write_srt(segments: list[dict], out: str | Path) -> Path:
    def ts(t):
        h, rem = divmod(t, 3600)
        m, s = divmod(rem, 60)
        return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int((s % 1) * 1000):03d}"
    body = "\n".join(f"{i}\n{ts(s['start'])} --> {ts(s['end'])}\n{s['text']}\n"
                     for i, s in enumerate(segments, 1))
    Path(out).write_text(body, encoding="utf-8")
    return Path(out)


# ------------------------------------------------------------------ render final
@dataclass
class EditOptions:
    width: int = 1080
    height: int = 1920
    fill: str = "blur"                 # blur | crop
    max_seconds: float | None = None
    hook_text: str = ""
    subtitles: list[dict] | None = None
    logo: bool = True
    music: str | None = "auto"         # caminho, "auto" (aleatória de assets/music) ou None
    music_volume: float = 0.10
    intro_outro: bool = True
    speed: float = 1.0                 # 1.05–1.1 dá mais ritmo a vídeos falados
    extra: dict = field(default_factory=dict)


def _brand_path(key: str) -> Path | None:
    p = brand()["visual"].get(key)
    if not p:
        return None
    path = Path(p) if Path(p).is_absolute() else ROOT / p
    return path if path.exists() else None


def _pick_music(opt: EditOptions) -> Path | None:
    if not opt.music:
        return None
    if opt.music != "auto":
        return Path(opt.music)
    d = _brand_path("music_dir")
    tracks = sorted(d.glob("*.mp3")) + sorted(d.glob("*.m4a")) + sorted(d.glob("*.wav")) if d else []
    if tracks:
        return random.choice(tracks)
    # sem faixas próprias: música original gerada localmente (nunca sai um vídeo mudo)
    from ..config import DATA_DIR
    from .music import generate
    cached = DATA_DIR / "cache" / "musica_inspirador.m4a"
    return cached if cached.exists() else generate(cached, 120, "inspirador")


def render(src: str | Path, out: str | Path, opt: EditOptions) -> Path:
    """Reenquadra, legenda, aplica marca e exporta em alta qualidade."""
    info = probe(src)
    W, H = opt.width, opt.height
    tmp = Path(tempfile.mkdtemp(prefix="carretos_"))
    inputs = ["-i", str(src)]
    idx = 1

    if opt.fill == "crop":
        vchain = f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1"
    else:
        vchain = (f"[0:v]split[bgs][fgs];[bgs]scale={W}:{H}:force_original_aspect_ratio=increase,"
                  f"crop={W}:{H},boxblur=30:3,eq=brightness=-0.08[bg];"
                  f"[fgs]scale={W}:{H}:force_original_aspect_ratio=decrease[fg];"
                  f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1")
    if opt.speed != 1.0:
        vchain += f",setpts=PTS/{opt.speed}"
    vchain += ",fps=30"

    themed_frame = bool(brand().get("signature")) and not _brand_path("logo")
    if opt.subtitles is not None or opt.hook_text or themed_frame:
        segs = opt.subtitles or []
        if opt.speed != 1.0:
            segs = [{**s, "start": s["start"] / opt.speed, "end": s["end"] / opt.speed,
                     "words": [{**w, "start": w["start"] / opt.speed, "end": w["end"] / opt.speed}
                               for w in s.get("words", [])]} for s in segs]
        ass = tmp / "subs.ass"
        ass.write_text(build_ass(segs, W, H, opt.hook_text, duration=info.duration / opt.speed),
                       encoding="utf-8")
        fontsdir = str(Path(brand()["visual"]["font_bold"]).parent)
        vchain += f",subtitles='{_ff_path(ass)}':fontsdir='{_ff_path(fontsdir)}'"
    vchain += "[base]"
    graph = [vchain]
    last_v = "[base]"

    logo = _brand_path("logo") if opt.logo else None
    if logo:
        inputs += ["-i", str(logo)]
        lw = int(W * 0.16)
        graph.append(f"[{idx}:v]scale={lw}:-1,format=rgba,colorchannelmixer=aa=0.85[logo]")
        graph.append(f"{last_v}[logo]overlay=W-w-{int(W*0.05)}:{int(H*0.04)}[vlogo]")
        last_v = "[vlogo]"
        idx += 1

    audio_label = None
    if info.has_audio:
        a = "[0:a]" + (f"atempo={opt.speed}," if opt.speed != 1.0 else "") + \
            "loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[voice]"
        graph.append(a)
        audio_label = "[voice]"
    music = _pick_music(opt)
    if music:
        inputs += ["-stream_loop", "-1", "-i", str(music)]
        vol = opt.music_volume if info.has_audio else 0.6
        graph.append(f"[{idx}:a]volume={vol},aresample=48000[music]")
        if audio_label:
            graph.append("[voice]asplit[vkey][vmain]")
            graph.append("[music][vkey]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400[duck]")
            graph.append("[vmain][duck]amix=inputs=2:duration=first:normalize=0[mix]")
        else:
            graph.append("[music]anull[mix]")
        audio_label = "[mix]"
        idx += 1

    cmd = ["ffmpeg", "-y", "-hide_banner", *inputs, "-filter_complex", ";".join(graph), "-map", last_v]
    if audio_label:
        cmd += ["-map", audio_label, "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]
    duration = info.duration / opt.speed
    if opt.max_seconds and duration > opt.max_seconds:
        duration = opt.max_seconds
    cmd += ["-t", f"{duration:.3f}", "-c:v", "libx264", "-preset", "slow", "-crf", "18",
            "-profile:v", "high", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)]
    _run(cmd)

    if opt.intro_outro:
        intro, outro = _brand_path("intro_video"), _brand_path("outro_video")
        if intro or outro:
            _wrap_intro_outro(Path(out), intro, outro, W, H, tmp)
    shutil.rmtree(tmp, ignore_errors=True)
    return Path(out)


def _ff_path(p) -> str:
    return str(p).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def _normalize(src: Path, out: Path, W: int, H: int) -> Path:
    info = probe(src)
    cmd = ["ffmpeg", "-y", "-hide_banner", "-i", str(src)]
    if not info.has_audio:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
    cmd += ["-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,fps=30",
            "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-shortest", str(out)]
    _run(cmd)
    return out


def _wrap_intro_outro(main: Path, intro: Path | None, outro: Path | None, W: int, H: int, tmp: Path) -> None:
    parts = []
    if intro:
        parts.append(_normalize(intro, tmp / "intro.mp4", W, H))
    parts.append(_normalize(main, tmp / "main.mp4", W, H))
    if outro:
        parts.append(_normalize(outro, tmp / "outro.mp4", W, H))
    lst = tmp / "list.txt"
    lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts))
    joined = tmp / "joined.mp4"
    _run(["ffmpeg", "-y", "-hide_banner", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy",
          "-movflags", "+faststart", str(joined)])
    shutil.move(joined, main)


# ------------------------------------------------------------------ capa
def best_frame(path: str | Path, out: str | Path, samples: int = 24) -> Path:
    """Escolhe o frame mais nítido e bem exposto (evita frames tremidos/escuros) para a capa."""
    info = probe(path)
    tmp = Path(tempfile.mkdtemp(prefix="frames_"))
    best, best_score = None, -1.0
    # ignora os primeiros/últimos 5% (transições)
    for i in range(samples):
        t = info.duration * (0.05 + 0.9 * i / max(1, samples - 1))
        f = tmp / f"f{i:03d}.jpg"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", str(path), "-frames:v", "1",
                        "-q:v", "2", str(f)], capture_output=True)
        if not f.exists():
            continue
        img = Image.open(f).convert("L")
        img.thumbnail((480, 480))
        sharp = ImageStat.Stat(img.filter(ImageFilter.FIND_EDGES)).var[0]
        bright = ImageStat.Stat(img).mean[0]
        exposure = 1 - abs(bright - 128) / 128           # 1 = exposição ideal
        contrast = ImageStat.Stat(img).stddev[0] / 64
        score = sharp * (0.4 + exposure) * (0.5 + min(contrast, 1.5))
        if score > best_score:
            best, best_score = f, score
    if not best:
        raise VideoError("Não consegui extrair frames para a capa.")
    shutil.copy(best, out)
    shutil.rmtree(tmp, ignore_errors=True)
    return Path(out)


# ------------------------------------------------------------------ pipeline
def auto_edit(src: str | Path, out_dir: str | Path, *, width: int = 1080, height: int = 1920,
              target_seconds: int | None = 45, max_seconds: float | None = 90, hook_text: str = "",
              use_transcription: bool = True, use_ai: bool = True, goal: str = "",
              fill: str = "blur", music: str | None = "auto", speed: float = 1.0) -> dict:
    """Edita automaticamente um vídeo bruto. Devolve caminhos e metadados gerados."""
    require_ffmpeg()
    src, out_dir = Path(src), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = src.stem
    tmp = Path(tempfile.mkdtemp(prefix="edit_"))
    result: dict = {"source": str(src), "steps": []}

    segments: list[dict] | None = None
    if use_transcription:
        try:
            segments = transcribe(src)
            write_srt(segments, out_dir / f"{stem}.srt")
            result["steps"].append(f"transcrição: {len(segments)} segmentos")
        except VideoError as exc:
            result["steps"].append(f"sem legendas ({exc})")

    ranges = None
    if segments and use_ai and target_seconds:
        try:
            from ..content.ai import select_highlights
            sel = select_highlights([{k: s[k] for k in ("start", "end", "text")} for s in segments],
                                    target_seconds, goal)
            ranges = _merge([(c["start"], c["end"]) for c in sel["clips"] if c["end"] > c["start"]])
            hook_text = hook_text or sel.get("hook_text", "")
            result.update({k: sel.get(k) for k in ("title", "caption", "hashtags", "cover_text")})
            result["steps"].append(f"IA escolheu {len(ranges)} cortes")
        except Exception as exc:  # noqa: BLE001
            result["steps"].append(f"IA indisponível ({exc}); a usar remoção de silêncios")
    if not ranges:
        ranges = detect_speech(src)
        result["steps"].append(f"silêncios removidos: {len(ranges)} blocos mantidos")

    cut_path = cut(src, ranges, tmp / "cut.mp4")
    subs = remap_segments(segments, ranges) if segments else None

    final = out_dir / f"{stem}_{width}x{height}.mp4"
    render(cut_path, final, EditOptions(width=width, height=height, fill=fill, max_seconds=max_seconds,
                                        hook_text=hook_text, subtitles=subs, music=music, speed=speed))
    result["video"] = str(final)
    # frame da capa tirado do vídeo sem legendas/logótipo
    frame = best_frame(cut_path, out_dir / f"{stem}_frame.jpg")
    result["cover_frame"] = str(frame)
    result["duration"] = round(probe(final).duration, 2)
    result["hook_text"] = hook_text
    shutil.rmtree(tmp, ignore_errors=True)
    return result
