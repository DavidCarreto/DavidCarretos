"""Música de fundo original gerada localmente (sem direitos de autor, custo zero).

Serve de reserva para nenhum vídeo sair mudo quando assets/music/ está vazio.
Estilos: "inspirador" (piano + pads, acordes Lá menor–Fá–Dó–Sol) e "energia" (mais rápido, com batida).
Para melhor qualidade, coloca faixas sem direitos em assets/music/ (têm prioridade).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

SR = 44100
# frequências (Hz) das notas usadas
N = {"A2": 110.0, "F2": 87.31, "C3": 130.81, "G2": 98.0,
     "A3": 220.0, "C4": 261.63, "E4": 329.63, "F3": 174.61, "A4": 440.0, "G3": 196.0, "B3": 246.94,
     "D4": 293.66, "G4": 392.0, "E3": 164.81}
PROGRESSION = [  # baixo, acorde (tríade), arpejo
    ("A2", ["A3", "C4", "E4"]), ("F2", ["F3", "A3", "C4"]),
    ("C3", ["E3", "G3", "C4"]), ("G2", ["G3", "B3", "D4"]),
]


def _env(n: int, attack: float, release: float) -> np.ndarray:
    a, r = int(attack * SR), int(release * SR)
    e = np.ones(n)
    if a:
        e[:a] = np.linspace(0, 1, a)
    if r:
        e[-r:] *= np.linspace(1, 0, r)
    return e


def _pad(freqs, seconds: float) -> np.ndarray:
    n = int(seconds * SR)
    t = np.arange(n) / SR
    out = np.zeros(n)
    for f in freqs:
        for detune in (-0.6, 0.0, 0.6):  # coro suave
            ff = f * (1 + detune / 1200 * 10)
            out += np.sin(2 * np.pi * ff * t) + 0.3 * np.sin(2 * np.pi * 2 * ff * t) + 0.12 * np.sin(2 * np.pi * 3 * ff * t)
    return out / (len(freqs) * 3) * _env(n, 0.8, 0.8)


def _piano(f: float, seconds: float) -> np.ndarray:
    n = int(seconds * SR)
    t = np.arange(n) / SR
    tone = sum(np.sin(2 * np.pi * f * k * t) * (0.6 ** (k - 1)) for k in range(1, 6))
    return tone * np.exp(-t * 3.2) * _env(n, 0.005, 0.05)


def _kick(seconds: float = 0.4) -> np.ndarray:
    n = int(seconds * SR)
    t = np.arange(n) / SR
    f = 110 * np.exp(-t * 18) + 45
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 9)


def _add(mix: np.ndarray, start: int, sig: np.ndarray) -> None:
    end = min(len(mix), start + len(sig))
    if end > start:
        mix[start:end] += sig[:end - start]


def generate(out: str | Path, seconds: float = 60.0, style: str = "inspirador") -> Path:
    bpm = 84 if style == "inspirador" else 112
    beat = 60 / bpm
    bar = beat * 4
    n = int(seconds * SR)
    mix = np.zeros(n + SR * 3)
    pos, i = 0.0, 0
    while pos < seconds:
        bass, chord = PROGRESSION[i % 4]
        s = int(pos * SR)
        pad = _pad([N[c] for c in chord], bar + 0.8) * 0.22
        _add(mix, s, pad)
        b = _pad([N[bass]], bar) * 0.35
        _add(mix, s, b)
        # arpejo de piano em colcheias
        notes = chord + [chord[1]]
        for k in range(8):
            f = N[notes[k % 4]] * (2 if (i // 4) % 2 and k % 2 else 1)
            p = _piano(f, beat * 1.5) * (0.16 if k % 2 == 0 else 0.11)
            ps = s + int(k * beat / 2 * SR)
            _add(mix, ps, p)
        if style != "inspirador" or i >= 4:  # batida entra depois da introdução
            for k in range(4):
                kk = _kick() * (0.35 if k % 2 == 0 else 0.2)
                ks = s + int(k * beat * SR)
                _add(mix, ks, kk)
        pos += bar
        i += 1
    mix = mix[:n]
    mix *= _env(n, 1.5, 2.5)
    mix /= max(1e-6, np.abs(mix).max()) / 0.8
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    raw = out.with_suffix(".raw.wav")
    import soundfile as sf  # type: ignore
    sf.write(raw, np.stack([mix, mix], 1).astype(np.float32), SR)
    # reverberação e equalização leves
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(raw), "-af",
                    "aecho=0.8:0.75:60|140:0.25|0.18,lowpass=f=9000,highpass=f=35,loudnorm=I=-18:TP=-2",
                    "-c:a", "aac", "-b:a", "192k", str(out)], check=True)
    raw.unlink(missing_ok=True)
    return out
