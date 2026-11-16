"""Criação de vídeos do zero, sem gravar nada.

  tema ──► guião em cenas (IA) ──► narração PT-PT (Piper) ──► fundos (a tua biblioteca / Pexels / marca)
       ──► cenas animadas (títulos, listas, números, citações, CTA) ──► legendas, logótipo, música ──► MP4 + capa

Tipos de cena (campo "type"):
  hook   texto grande palavra a palavra (primeiros 2–3 s)
  text   título + texto curto
  list   pontos que aparecem um a um
  stat   número grande a contar (ex.: "5" oficinas, "98%")
  quote  frase/lição em destaque
  media  só imagem/vídeo de fundo com legenda pequena (rodapé)
  cta    chamada à ação final (seguir, comentar, marcar)

O storyboard é um JSON (gerado pela IA ou escrito à mão — ver exemplos/storyboard_exemplo.json).
"""
from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

from ..config import brand
from . import stock, voice
from .image_gen import _fit_text, _font, _gradient, _hex, _wrap
from .video_editor import EditOptions, VideoError, best_frame, probe, render

FPS = 30


# ------------------------------------------------------------------ animação
def ease_out(t: float) -> float:
    t = min(max(t, 0.0), 1.0)
    return 1 - (1 - t) ** 3


def ease_back(t: float) -> float:
    t = min(max(t, 0.0), 1.0)
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2


class Overlay:
    """Desenha a camada de texto animado de uma cena, frame a frame."""

    def __init__(self, scene: dict, W: int, H: int, duration: float, handle: str, has_media: bool):
        self.s, self.W, self.H, self.d = scene, W, H, duration
        self.handle = handle
        v = brand()["visual"]["colors"]
        self.white, self.accent = _hex(v["text"]), _hex(v["accent"])
        self.silver, self.dark = _hex(v["secondary"]), _hex(v["primary"])
        self.margin = int(W * 0.08)
        self.base = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        if has_media:  # escurece o fundo para o texto se ler bem
            shade = 0 if scene["type"] == "media" else 110
            self.base.alpha_composite(Image.new("RGBA", (W, H), (*self.dark[:3], shade)))
            self.base.alpha_composite(_gradient((W, H), start=0.5, bottom_alpha=200))
        self.static_after = {"list": duration, "stat": 1.4}.get(scene["type"], 1.0)
        self._cache_static: bytes | None = None

    # -- utilitários
    def _text_block(self, d, text, size, y, color=None, bold=True, max_h=None, center=True, alpha=255):
        font, lines, fs = _fit_text(d, text, bold, self.W - 2 * self.margin, max_h or int(self.H * 0.3), size)
        for line in lines:
            w = d.textlength(line, font=font)
            x = (self.W - w) / 2 if center else self.margin
            col = (*(color or self.white)[:3], alpha)
            d.text((x + 3, y + 4), line, font=font, fill=(0, 0, 0, int(alpha * 0.45)))
            d.text((x, y), line, font=font, fill=col)
            y += int(fs * 1.12)
        return y

    def frame(self, t: float) -> bytes:
        if t >= self.static_after:
            if self._cache_static is None:
                self._cache_static = self._draw(self.static_after + 10).tobytes()
            return self._cache_static
        return self._draw(t).tobytes()

    def _draw(self, t: float) -> Image.Image:
        img = self.base.copy()
        layer = Image.new("RGBA", (self.W, self.H), (0, 0, 0, 0))
        getattr(self, f"_{self.s['type']}", self._text)(ImageDraw.Draw(layer), t, layer)
        img.alpha_composite(layer)
        return img

    # -- tipos de cena
    def _hook(self, d, t, layer):
        text = (self.s.get("title") or self.s.get("voiceover", "")).upper()
        font, lines, fs = _fit_text(d, text, True, self.W - 2 * self.margin, int(self.H * 0.32), int(self.W * 0.13))
        words_total = sum(len(l.split()) for l in lines)
        shown = t / 0.08  # palavras por segundo ≈ 12
        highlight = {w.lower().strip(".,!?") for w in (self.s.get("highlight") or [text.split()[-1]])}
        y = int(self.H * 0.40) - len(lines) * int(fs * 1.1) // 2
        idx = 0
        for line in lines:
            words = line.split()
            x = (self.W - d.textlength(line, font=font)) / 2
            for w in words:
                k = shown - idx
                if k > 0:
                    sc = 0.6 + 0.4 * ease_back(min(k, 1.0))
                    col = self.accent if w.lower().strip(".,!?") in highlight else self.white
                    self._word(layer, w, font, fs, x, y, sc, col)
                x += d.textlength(w + " ", font=font)
                idx += 1
            y += int(fs * 1.1)
        _ = words_total

    def _word(self, layer, word, font, fs, x, y, scale, color):
        if scale >= 0.999:
            d = ImageDraw.Draw(layer)
            d.text((x + 3, y + 5), word, font=font, fill=(0, 0, 0, 120))
            d.text((x, y), word, font=font, fill=color)
            return
        tmp_font = _font(True, max(8, int(fs * scale)))
        d = ImageDraw.Draw(layer)
        w_full = d.textlength(word, font=font)
        w_now = d.textlength(word, font=tmp_font)
        ox, oy = x + (w_full - w_now) / 2, y + (fs - tmp_font.size) / 2
        d.text((ox, oy), word, font=tmp_font, fill=color)

    def _text(self, d, t, layer):
        p = ease_out(t / 0.6)
        dy = int((1 - p) * self.H * 0.04)
        a = int(255 * p)
        y = int(self.H * 0.22) + dy
        if self.s.get("kicker"):
            kf = _font(True, int(self.W * 0.035))
            label = self.s["kicker"].upper()
            tw = d.textlength(label, font=kf)
            pad = int(kf.size * 0.5)
            x = (self.W - tw) / 2 - pad
            d.rounded_rectangle((x, y, x + tw + 2 * pad, y + kf.size + 2 * pad), radius=pad,
                                fill=(*self.accent[:3], a))
            d.text((x + pad, y + pad * 0.8), label, font=kf, fill=(255, 255, 255, a))
            y += kf.size + 3 * pad
        y = self._text_block(d, self.s.get("title", ""), int(self.W * 0.095), y, alpha=a)
        if self.s.get("body"):
            self._text_block(d, self.s["body"], int(self.W * 0.06), y + int(self.H * 0.02), self.silver,
                             bold=False, alpha=a)

    def _list(self, d, t, layer):
        items = self.s.get("items") or []
        y = int(self.H * 0.17)
        if self.s.get("title"):
            pt = ease_out(t / 0.5)
            y = self._text_block(d, self.s["title"], int(self.W * 0.095), y, alpha=int(255 * pt)) + int(self.H * 0.03)
        n = max(1, len(items))
        span = max(0.5, self.d * 0.75 - 0.4)
        f = _font(True, int(self.W * 0.07) if len(items) <= 4 else int(self.W * 0.058))
        for i, item in enumerate(items):
            start = 0.4 + i * span / n
            p = ease_out((t - start) / 0.4)
            if p <= 0:
                continue
            a = int(255 * p)
            x0 = self.margin - int((1 - p) * self.W * 0.08)
            r = int(f.size * 0.75)
            cy = y + f.size // 2 + 4
            d.ellipse((x0, cy - r, x0 + 2 * r, cy + r), fill=(*self.accent[:3], a))
            num = str(i + 1)
            d.text((x0 + r - d.textlength(num, font=f) / 2, cy - f.size * 0.6), num, font=f, fill=(255, 255, 255, a))
            lines = _wrap(d, item, f, self.W - 2 * self.margin - 3 * r)
            ly = y
            for line in lines:
                d.text((x0 + 3 * r + 3, ly + 4), line, font=f, fill=(0, 0, 0, int(a * 0.45)))
                d.text((x0 + 3 * r, ly), line, font=f, fill=(*self.white[:3], a))
                ly += int(f.size * 1.15)
            y = max(ly, cy + r) + int(self.H * 0.025)

    def _stat(self, d, t, layer):
        raw = str(self.s.get("value", "0"))
        m = re.search(r"\d+(?:[.,\s]\d+)*", raw)
        p = ease_out(t / 1.2)
        if m:
            target = float(re.sub(r"[.\s]", "", m.group()).replace(",", "."))
            cur = target * p
            num = f"{cur:,.0f}".replace(",", " ") if target >= 10 or target.is_integer() else f"{cur:.1f}"
            shown = raw[:m.start()] + num + raw[m.end():]
        else:
            shown = raw
        sc = 0.85 + 0.15 * ease_back(t / 0.5)
        size = int(self.W * 0.30 * sc)
        font = _font(True, size)
        while d.textlength(shown, font=font) > self.W - 2 * self.margin and size > 40:
            size -= 8
            font = _font(True, size)
        y = int(self.H * 0.28)
        w = d.textlength(shown, font=font)
        d.text(((self.W - w) / 2 + 4, y + 6), shown, font=font, fill=(0, 0, 0, 120))
        d.text(((self.W - w) / 2, y), shown, font=font, fill=self.accent)
        a = int(255 * ease_out((t - 0.3) / 0.5))
        self._text_block(d, self.s.get("title", ""), int(self.W * 0.085), y + int(size * 1.15), alpha=a)

    def _quote(self, d, t, layer):
        p = ease_out(t / 0.7)
        a = int(255 * p)
        qf = _font(True, int(self.W * 0.3))
        d.text((self.margin, int(self.H * 0.12)), "“", font=qf, fill=(*self.accent[:3], a))
        y = self._text_block(d, self.s.get("title", ""), int(self.W * 0.08), int(self.H * 0.28), center=False,
                             alpha=a)
        if self.s.get("body"):
            af = _font(False, int(self.W * 0.04))
            d.text((self.margin, y + int(self.H * 0.02)), "— " + self.s["body"], font=af,
                   fill=(*self.silver[:3], a))

    def _media(self, d, t, layer):
        if not self.s.get("title"):
            return
        p = ease_out(t / 0.5)
        f = _font(True, int(self.W * 0.045))
        text = self.s["title"]
        lines = _wrap(d, text, f, self.W - 2 * self.margin - 40)
        h = len(lines) * int(f.size * 1.2) + 30
        y = int(self.H * 0.16) - int((1 - p) * 40)
        w = max(d.textlength(l, font=f) for l in lines) + 40
        d.rounded_rectangle((self.margin, y, self.margin + w, y + h), radius=18,
                            fill=(*self.dark[:3], int(200 * p)))
        d.rectangle((self.margin, y, self.margin + 8, y + h), fill=(*self.accent[:3], int(255 * p)))
        ty = y + 15
        for line in lines:
            d.text((self.margin + 28, ty), line, font=f, fill=(*self.white[:3], int(255 * p)))
            ty += int(f.size * 1.2)

    def _cta(self, d, t, layer):
        p = ease_out(t / 0.6)
        a = int(255 * p)
        y = self._text_block(d, self.s.get("title") or "Segue para mais", int(self.W * 0.10), int(self.H * 0.30),
                             alpha=a)
        if self.handle:
            pulse = 1 + 0.04 * math.sin(t * 6) if t > 0.6 else ease_back(t / 0.6)
            hf = _font(True, max(10, int(self.W * 0.065 * pulse)))
            label = f"@{self.handle}"
            tw = d.textlength(label, font=hf)
            pad = int(hf.size * 0.45)
            x = (self.W - tw) / 2
            yy = y + int(self.H * 0.03)
            d.rounded_rectangle((x - 2 * pad, yy - pad, x + tw + 2 * pad, yy + hf.size + pad * 1.6),
                                radius=hf.size, fill=(*self.accent[:3], a))
            d.text((x, yy), label, font=hf, fill=(255, 255, 255, a))
        if self.s.get("body"):
            self._text_block(d, self.s["body"], int(self.W * 0.055), int(self.H * 0.58), self.silver, bold=False,
                             alpha=a)


# ------------------------------------------------------------------ cenas
def _run_scene(scene: dict, bg: Path, wav: Path, duration: float, W: int, H: int, out: Path, handle: str,
               has_media: bool) -> Path:
    frames = int(round(duration * FPS))
    is_video = bg.suffix.lower() in stock.VIDEO_EXT
    if is_video:
        src = ["-stream_loop", "-1", "-t", f"{duration + 0.5:.3f}", "-i", str(bg)]
        start = float(scene.get("media_start", 0) or 0)
        if start:
            src = ["-ss", f"{start:.2f}"] + src
        bgf = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,fps={FPS},"
               f"eq=saturation=1.08:contrast=1.04[bg]")
    else:
        src = ["-loop", "1", "-framerate", str(FPS), "-t", f"{duration + 0.5:.3f}", "-i", str(bg)]
        zin = scene.get("zoom", "in") != "out"
        z = f"1+0.12*on/{frames}" if zin else f"1.12-0.12*on/{frames}"
        bgf = (f"[0:v]scale={W * 2}:{H * 2}:force_original_aspect_ratio=increase,crop={W * 2}:{H * 2},"
               f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps={FPS},setsar=1[bg]")
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *src,
           "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-i", str(wav),
           "-filter_complex", f"{bgf};[bg][1:v]overlay=0:0:format=auto,format=yuv420p[v];"
                              f"[2:a]aresample=48000,apad,atrim=0:{duration:.3f}[a]",
           "-map", "[v]", "-map", "[a]", "-t", f"{duration:.3f}", "-r", str(FPS),
           "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", "-ac", "2", str(out)]
    ov = Overlay(scene, W, H, duration, handle, has_media)
    with tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=err)
        try:
            for i in range(frames):
                proc.stdin.write(ov.frame(i / FPS))
            proc.stdin.close()
        except BrokenPipeError:
            pass
        code = proc.wait()
        if code != 0:
            err.seek(0)
            raise VideoError(f"Falhou a cena {scene.get('type')}: {err.read().decode()[-1500:]}")
    return out


def _subtitle_segments(scene: dict, offset: float, speech: float) -> list[dict]:
    text = scene.get("voiceover", "").strip()
    words = text.split()
    if not words or scene["type"] in ("hook", "cta", "stat") or speech <= 0:
        return []
    total = sum(len(w) + 1 for w in words)
    t, out = offset + 0.15, []
    for w in words:
        dt = speech * (len(w) + 1) / total
        out.append({"start": t, "end": t + dt, "word": w})
        t += dt
    return [{"start": out[0]["start"], "end": out[-1]["end"], "text": text, "words": out}]


def create_video(storyboard: dict, out_dir: str | Path, *, size: tuple[int, int] = (1080, 1920), handle: str = "",
                 narration: bool = True, voice_speed: float = 1.08, subtitles: bool = True,
                 music: str | None = "auto", stock_footage: bool = True, max_seconds: float | None = None,
                 narrator: str | None = None) -> dict:
    """Constrói o vídeo final a partir de um storyboard. Devolve caminhos e metadados."""
    W, H = size
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    import unicodedata
    plain = unicodedata.normalize("NFKD", storyboard.get("title") or "video").encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "_", plain.lower())[:40].strip("_") or "video"
    tmp = Path(tempfile.mkdtemp(prefix="create_"))
    used: set[str] = set()
    parts, subs, offset, log = [], [], 0.0, []
    for i, scene in enumerate(storyboard["scenes"]):
        scene.setdefault("type", "text")
        wav = tmp / f"s{i:02d}.wav"
        text = scene.get("voiceover", "").strip()
        speech = voice.speak(text, wav, voice_speed, narrator) if (narration and text) else 0.0
        if not speech:
            # sem narração: tempo de leitura do texto no ecrã (~2,5 palavras/s, mínimo 2,5 s)
            on_screen = " ".join([scene.get("title", ""), scene.get("body", ""), *scene.get("items", [])])
            voice.silence(float(scene.get("seconds") or max(2.5, len(on_screen.split()) / 2.5 + 1.0)), wav)
        duration = max(speech + 0.35, float(scene.get("seconds", 0) or 0), 1.6 if speech else voice.duration(wav))

        bg, has_media = None, False
        query = scene.get("visual") or scene.get("footage_query") or ""
        if scene.get("media_path") and Path(scene["media_path"]).exists():
            bg = Path(scene["media_path"])
        elif query and (stock_footage or scene["type"] == "media"):
            bg = stock.find_visual(query, used=used)
        if bg:
            used.add(str(bg))
            has_media = True
            log.append(f"cena {i + 1} ({scene['type']}): fundo {bg.name}")
        else:
            bg = stock.brand_background(size)
            log.append(f"cena {i + 1} ({scene['type']}): fundo da marca")

        part = _run_scene(scene, bg, wav, duration, W, H, tmp / f"s{i:02d}.mp4", handle, has_media)
        parts.append(part)
        subs += _subtitle_segments(scene, offset, speech)
        offset += duration

    lst = tmp / "list.txt"
    lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts))
    joined = tmp / "joined.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy",
                    str(joined)], check=True)

    final = out_dir / f"{slug}_{W}x{H}.mp4"
    render(joined, final, EditOptions(width=W, height=H, fill="crop", subtitles=subs if subtitles else None,
                                      music=music, music_volume=0.12, max_seconds=max_seconds,
                                      intro_outro=True))
    # capa: frame da cena com mais impacto (gancho) sem legendas
    frame = out_dir / f"{slug}_frame.jpg"
    try:
        best_frame(parts[1] if len(parts) > 1 else parts[0], frame, samples=8)
    except VideoError:
        frame = None
    shutil.rmtree(tmp, ignore_errors=True)
    return {"video": str(final), "cover_frame": str(frame) if frame else None, "duration": round(probe(final).duration, 2),
            "title": storyboard.get("title"), "caption": storyboard.get("caption"),
            "hashtags": storyboard.get("hashtags", []), "cover_text": storyboard.get("cover_text"), "steps": log}


def storyboard_from_post(post: dict, extra: dict) -> dict:
    """Converte um guião gerado por `carretos generate` num storyboard (sem nova chamada à IA)."""
    scenes = [{"type": "hook", "title": post.get("hook") or post.get("title"), "voiceover": post.get("hook") or ""}]
    for s in extra.get("script", [])[1:]:
        scenes.append({"type": "text", "title": s.get("voice_or_text", "")[:80], "voiceover": s.get("voice_or_text", ""),
                       "visual": s.get("visual", "")})
    scenes.append({"type": "cta", "title": "Segue para mais", "voiceover": "Segue para mais."})
    return {"title": post.get("title"), "caption": post.get("caption"), "hashtags": json.loads(post.get("hashtags") or "[]"),
            "cover_text": extra.get("cover_text"), "scenes": scenes}
