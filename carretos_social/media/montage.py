"""Montagem de vários vídeos num só: melhores trechos + imagens encaixadas (b-roll) + legendas + música.

  vídeos → transcrição → IA escolhe trechos e ordem → corta e junta (9:16) → encaixa fotos/vídeos
        da biblioteca por cima enquanto a voz continua → legendas karaoke, música por baixo, assinatura → capa
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import stock
from .video_editor import (EditOptions, VideoError, best_frame, detect_speech, probe, render, require_ffmpeg,
                           transcribe)

FPS = 30


def _norm_clip(src: Path, start: float, end: float, out: Path, W: int, H: int, fill: str) -> Path:
    """Corta um trecho e normaliza-o (W×H, 30 fps, áudio estéreo 48 kHz) para se poder juntar."""
    info = probe(src)
    if fill == "crop":
        vf = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,fps={FPS}"
    else:
        vf = (f"split[a][b];[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=30:3[bg];"
              f"[b]scale={W}:{H}:force_original_aspect_ratio=decrease[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,"
              f"setsar=1,fps={FPS}")
    cmd = ["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", str(src)]
    if not info.has_audio:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
    cmd += ["-filter_complex", f"[0:v]{vf}[v]", "-map", "[v]", "-map", "0:a" if info.has_audio else "1:a",
            "-shortest", "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", str(out)]
    subprocess.run(cmd, check=True)
    return out


def _broll_clip(visual: Path, seconds: float, out: Path, W: int, H: int) -> Path:
    """Prepara uma imagem (com zoom lento) ou vídeo de b-roll com a duração exata, sem áudio."""
    frames = int(seconds * FPS)
    if visual.suffix.lower() in stock.VIDEO_EXT:
        src = ["-stream_loop", "-1", "-t", f"{seconds:.3f}", "-i", str(visual)]
        vf = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,fps={FPS}"
    else:
        src = ["-loop", "1", "-framerate", str(FPS), "-t", f"{seconds:.3f}", "-i", str(visual)]
        vf = (f"scale={W * 2}:{H * 2}:force_original_aspect_ratio=increase,crop={W * 2}:{H * 2},"
              f"zoompan=z='1+0.10*on/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps={FPS},"
              f"setsar=1")
    subprocess.run(["ffmpeg", "-y", "-v", "error", *src, "-vf", vf + ",format=yuv420p", "-an", "-t",
                    f"{seconds:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", str(out)], check=True)
    return out


def _words_in(segments: list[dict], start: float, end: float, shift: float) -> list[dict]:
    out = []
    for seg in segments:
        words = [w for w in seg.get("words", []) if w["start"] >= start - 0.05 and w["end"] <= end + 0.05]
        if words:
            out.append({"start": words[0]["start"] + shift, "end": words[-1]["end"] + shift,
                        "text": " ".join(w["word"] for w in words),
                        "words": [{**w, "start": w["start"] + shift, "end": w["end"] + shift} for w in words]})
    return out


def montage(files: list[str | Path], out_dir: str | Path, *, acc=None, width: int = 1080, height: int = 1920,
            target_seconds: int = 45, goal: str = "", use_ai: bool = True, broll: bool = True,
            fill: str = "crop", music: str | None = "auto", max_seconds: float | None = None,
            library: list[str] | None = None) -> dict:
    require_ffmpeg()
    files = [Path(f) for f in files]
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="montage_"))
    W, H = width, height
    result: dict = {"steps": []}

    transcripts = []
    for i, f in enumerate(files):
        try:
            transcripts.append(transcribe(f))
        except VideoError:
            transcripts.append([])
    result["steps"].append("transcrição de " + ", ".join(f"{f.name} ({len(t)} frases)" for f, t in zip(files, transcripts)))

    plan = None
    if use_ai and acc is not None and any(transcripts):
        from ..content.ai import plan_montage
        clips = [{"clip": i, "name": f.name, "duracao": round(probe(f).duration, 1),
                  "segments": [{k: s[k] for k in ("start", "end", "text")} for s in t]}
                 for i, (f, t) in enumerate(zip(files, transcripts))]
        plan = plan_montage(acc, clips, target_seconds, goal, library)
        result.update({k: plan.get(k) for k in ("title", "caption", "hashtags", "cover_text", "hook_text")})
        result["steps"].append(f"IA escolheu {len(plan['segments'])} trechos e {len(plan['broll'])} imagens a meio")
    pieces = []
    if plan:
        for s in plan["segments"]:
            i = int(s["clip"])
            if 0 <= i < len(files) and s["end"] > s["start"]:
                d = probe(files[i]).duration
                pieces.append((i, max(0.0, s["start"] - 0.1), min(d, s["end"] + 0.15)))
    if not pieces:  # sem IA: junta a fala de cada vídeo pela ordem dada
        for i, f in enumerate(files):
            pieces += [(i, s, e) for s, e in detect_speech(f)]
        result["steps"].append("sem IA: juntei as partes com fala, por ordem")

    parts, subs, offset = [], [], 0.0
    for k, (i, s, e) in enumerate(pieces):
        part = _norm_clip(files[i], s, e, tmp / f"p{k:02d}.mp4", W, H, fill)
        dur = probe(part).duration
        subs += _words_in(transcripts[i], s, e, offset - s)
        parts.append(part)
        offset += dur
    lst = tmp / "list.txt"
    lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts))
    timeline = tmp / "timeline.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy",
                    str(timeline)], check=True)

    # b-roll por cima, com a voz a continuar
    inserts = []
    if broll and plan:
        used: set[str] = set()
        for b in plan.get("broll", []):
            at, secs = float(b["at"]), max(1.5, min(4.5, float(b["seconds"])))
            if at < 2.5 or at + secs > offset - 1:  # nunca tapar o gancho nem o fim
                continue
            vis = stock.find_visual(b.get("visual", ""), used=used)
            if not vis:
                continue
            used.add(str(vis))
            inserts.append((at, secs, _broll_clip(vis, secs, tmp / f"b{len(inserts)}.mp4", W, H), vis.name))
    if inserts:
        inputs, graph, last = ["-i", str(timeline)], [], "[0:v]"
        for n, (at, secs, clip, _) in enumerate(inserts, 1):
            inputs += ["-i", str(clip)]
            graph.append(f"[{n}:v]setpts=PTS-STARTPTS+{at:.3f}/TB,fade=t=in:st={at:.3f}:d=0.25:alpha=1,"
                         f"format=yuva420p[b{n}]")
            graph.append(f"{last}[b{n}]overlay=enable='between(t,{at:.3f},{at + secs:.3f})':eof_action=pass[v{n}]")
            last = f"[v{n}]"
        with_broll = tmp / "broll.mp4"
        subprocess.run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", ";".join(graph),
                        "-map", last, "-map", "0:a", "-c:v", "libx264", "-preset", "veryfast", "-crf", "16",
                        "-c:a", "copy", str(with_broll)], check=True)
        timeline = with_broll
        result["steps"].append("imagens encaixadas: " + ", ".join(f"{v} aos {a:.0f}s" for a, _, _, v in inserts))

    stem = (files[0].stem if len(files) == 1 else f"montagem_{files[0].stem}")[:50]
    final = out_dir / f"{stem}_{W}x{H}.mp4"
    render(timeline, final, EditOptions(width=W, height=H, fill="crop", subtitles=subs,
                                        hook_text=(plan or {}).get("hook_text", ""), music=music,
                                        max_seconds=max_seconds))
    frame = best_frame(parts[0], out_dir / f"{stem}_frame.jpg", samples=10)
    result.update(video=str(final), cover_frame=str(frame), duration=round(probe(final).duration, 2),
                  pieces=[{"video": files[i].name, "de": round(s, 1), "ate": round(e, 1)} for i, s, e in pieces])
    shutil.rmtree(tmp, ignore_errors=True)
    return result
