"""Formatos de publicação por rede social e verificação do conteúdo antes de publicar.

Para cada publicação diz:
  - o tipo (uma imagem, várias imagens/carrossel, um vídeo, só texto);
  - o tamanho recomendado para a rede e o tipo escolhidos;
  - se cada ficheiro encaixa no ecrã/formato, se convém ajustar ou se tem de ser editado.

Veredictos: "ok" (pronto), "ajustar" (pode sair, mas fica melhor ajustado) e "editar"
(fora dos limites: bloqueia a aprovação e a publicação).

Limites validados nas páginas oficiais e na documentação das APIs a 16/11/2026 (ver docs/FORMATOS.md).
Os valores podem ser afinados sem mexer no código em config/strategy.yaml → formatos.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

VIDEO_EXT = (".mp4", ".mov", ".m4v", ".webm")

# tipos que a equipa escolhe no dashboard (sem emojis: no Chrome/Windows apareciam como quadrados)
KINDS = {
    "image": "Uma imagem",
    "carousel": "Várias imagens (carrossel)",
    "video": "Um vídeo",
    "text": "Só texto",
}
KIND_ICON = {"image": "📷", "carousel": "📷", "video": "🎬", "text": "✏️"}

# Especificações por plataforma e tipo.
#   size        tamanho recomendado (largura × altura)
#   ratio       proporções recomendadas (largura/altura). Fora delas:
#                 - dentro de hard_ratio (o que a API aceita) → "⚠ ajustar"
#                 - sem hard_ratio → "✕ editar"; com soft_ratio=True → só "⚠ ajustar"
#   count       n.º de ficheiros (carrossel)
#   seconds     duração aceite (mín., máx.); rec_seconds: duração recomendada
#   fps         imagens por segundo aceites (mín., máx.)
#   min_size    tamanho mínimo (largura, altura); sides: lado mínimo/máximo em px; max_width
#   max_mb/min_kb  tamanho do ficheiro; ext: extensões aceites
#   screen      "phone" (ecrã inteiro, ex.: Reels/TikTok) ou "feed" (imagem no feed)
#   info        notas informativas (não mudam o veredicto)
_FEED_IMG = {"size": (1080, 1350), "ratio": (0.8, 1.91), "screen": "feed", "name": "Imagem no feed"}
_REEL = {"size": (1080, 1920), "ratio": (0.5, 1.91), "screen": "phone"}
SPECS: dict[str, dict[str, dict]] = {
    "instagram": {
        # a app aceita até 3:4, mas a API (publicação automática) só até 4:5
        "image": {**_FEED_IMG, "api_note": "a app do Instagram aceita até 3:4, mas a publicação automática "
                                           "(API) só aceita até 4:5"},
        # a API atual permite até 20 itens; mantemos 10 até testar na conta real (config: formatos)
        "carousel": {**_FEED_IMG, "name": "Carrossel", "count": (2, 10),
                     "info": ["A 1.ª imagem define o corte das restantes: convém que todas tenham a mesma proporção."]},
        "video": {**_REEL, "name": "Reel", "hard_ratio": (0.01, 10.0), "seconds": (3, 900), "rec_seconds": 90,
                  "fps": (23, 60), "max_width": 1920, "max_mb": 300},
    },
    "facebook_profile": {
        "image": _FEED_IMG,
        "carousel": {**_FEED_IMG, "name": "Várias fotos", "count": (2, 10)},
        "video": {**_REEL, "name": "Reel", "seconds": (3, 90), "fps": (24, 60), "min_size": (540, 960)},
        "_info": ["Perfil pessoal: a Meta não deixa publicar em perfis por API (desde 2018). "
                  "Esta publicação é sempre enviada para o telemóvel, para publicar à mão."],
    },
    "facebook_page": {
        "image": _FEED_IMG,
        "carousel": {**_FEED_IMG, "name": "Várias fotos", "count": (2, 10)},
        # Reels de Página por API: 3–90 s (60 s se for story). As 4 h só valem para vídeo normal de Página.
        "video": {**_REEL, "name": "Reel", "seconds": (3, 90), "fps": (24, 60), "min_size": (540, 960)},
    },
    "tiktok": {
        # a duração máxima real depende da conta (3, 5 ou 10 min): confirmada na API (creator_info) ao publicar.
        # (a API também aceita posts de fotos, até 35, se um dia se quiser ativar)
        "video": {**_REEL, "name": "Vídeo", "seconds": (3, 600), "rec_seconds": 60, "fps": (23, 60),
                  "sides": (360, 4096),
                  "info": ["A duração máxima depende da conta (3, 5 ou 10 min): confirmada no TikTok antes de "
                           "publicar."]},
    },
    "linkedin_member": {
        # proporção/tamanho de imagem não confirmados em fonte oficial: só recomendação
        "image": {"size": (1200, 1500), "ratio": (0.75, 1.91), "soft_ratio": True, "screen": "feed",
                  "name": "Imagem"},
        "carousel": {"size": (1200, 1500), "ratio": (0.75, 1.91), "soft_ratio": True, "screen": "feed",
                     "name": "Várias imagens", "count": (2, 20)},
        "video": {"size": (1080, 1350), "ratio": (1 / 2.4, 2.4), "screen": "feed", "name": "Vídeo",
                  "seconds": (3, 1800), "rec_seconds": 90, "max_mb": 500, "min_kb": 75, "ext": (".mp4",)},
        "text": {"name": "Só texto"},
    },
    "youtube": {
        "video": {"size": (1080, 1920), "ratio": (0.4, 1.0), "screen": "phone", "name": "Short",
                  "seconds": (0, 180), "rec_seconds": 60,
                  "short_note": "com mais de 3 min ou na horizontal sai como vídeo normal, não como Short"},
    },
}
SPECS["linkedin_org"] = SPECS["linkedin_member"]

PLATFORM_NAMES = {"instagram": "Instagram", "facebook_profile": "Facebook (perfil pessoal)",
                  "facebook_page": "Facebook (página)", "tiktok": "TikTok", "linkedin_member": "LinkedIn",
                  "linkedin_org": "LinkedIn (empresa)", "youtube": "YouTube"}


def _overrides() -> dict:
    try:
        from ..config import strategy
        return strategy().get("formatos") or {}
    except Exception:  # noqa: BLE001
        return {}


def spec_for(platform: str, kind: str) -> dict:
    """Especificação com os ajustes de config/strategy.yaml → formatos (ex.: máximo do carrossel)."""
    spec = copy.deepcopy(SPECS.get(platform, {}).get(kind, {}))
    if spec:
        for k, v in ((_overrides().get(platform) or {}).get(kind) or {}).items():
            spec[k] = tuple(v) if isinstance(v, list) else v
    return spec


def kind_of(fmt: str | None) -> str:
    """Formato guardado na publicação → tipo (image/carousel/video/text)."""
    fmt = (fmt or "").lower()
    if fmt in ("reel", "video", "short", "story_video"):
        return "video"
    if fmt in ("carousel", "carrossel", "album"):
        return "carousel"
    if fmt == "text":
        return "text"
    return "image"  # image, text_image, quote, photo…


def format_for(kind: str, platform: str) -> str:
    """Tipo escolhido no dashboard → formato guardado (o Instagram chama 'reel' aos vídeos)."""
    if kind == "video":
        return "reel" if platform == "instagram" else "video"
    return kind


def kinds_for(platform: str) -> dict[str, str]:
    """Tipos que esta rede (e o nosso sistema) consegue publicar."""
    return {k: v for k, v in KINDS.items() if k in SPECS.get(platform, {})}


def is_video(path: str) -> bool:
    return str(path).lower().endswith(VIDEO_EXT)


def _ratio_name(r: float) -> str:
    known = {9 / 16: "9:16", 4 / 5: "4:5", 1.0: "1:1", 3 / 4: "3:4", 16 / 9: "16:9", 1.91: "1.91:1", 2 / 3: "2:3",
             3 / 2: "3:2", 4 / 3: "4:3", 0.5: "1:2", 2.4: "2.4:1", 1 / 2.4: "1:2.4", 0.01: "0.01:1", 10.0: "10:1"}
    for v, name in known.items():
        if abs(r / v - 1) <= 0.03:
            return name
    return f"{r:.2f}:1"


def _dur(s: float) -> str:
    s = int(round(s))
    if s >= 3600:
        return f"{s // 3600} h"
    return f"{s // 60}:{s % 60:02d}" if s >= 60 else f"{s} s"


def size_label(spec: dict) -> str:
    if "size" not in spec:
        return "sem imagem nem vídeo"
    w, h = spec["size"]
    txt = f"{w}×{h} px ({_ratio_name(w / h)})"
    if spec.get("seconds"):
        mn, mx = spec["seconds"]
        txt += f", {'até ' if not mn else f'{_dur(mn)} a '}{_dur(mx)}"
        if spec.get("rec_seconds"):
            txt += f" (recomendado até {_dur(spec['rec_seconds'])})"
    if spec.get("count"):
        txt += f", {spec['count'][0]} a {spec['count'][1]} imagens"
    return txt


@dataclass
class Item:
    path: str
    video: bool
    width: int = 0
    height: int = 0
    seconds: float = 0.0
    fps: float = 0.0
    bytes: int = 0
    verdict: str = "ok"
    notes: list[str] = field(default_factory=list)
    screen: str = ""

    @property
    def size(self) -> str:
        return f"{self.width}×{self.height}" if self.width else "?"

    @property
    def ratio(self) -> str:
        return _ratio_name(self.width / self.height) if self.width and self.height else "?"

    @property
    def duration(self) -> str:
        return _dur(self.seconds) if self.seconds else ""


@dataclass
class Report:
    platform: str
    kind: str
    spec: dict
    items: list[Item] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)   # bloqueiam ("editar")
    warnings: list[str] = field(default_factory=list)   # convém ajustar
    info: list[str] = field(default_factory=list)       # só informação

    @property
    def verdict(self) -> str:
        if self.problems or any(i.verdict == "editar" for i in self.items):
            return "editar"
        if self.warnings or any(i.verdict == "ajustar" for i in self.items):
            return "ajustar"
        return "ok"

    @property
    def verdict_label(self) -> str:
        return {"ok": "✓ Pronto a publicar: encaixa no formato",
                "ajustar": "⚠ Pode publicar, mas convém ajustar",
                "editar": "✕ Tem de ser editado antes de publicar"}[self.verdict]

    @property
    def target(self) -> str:
        name = PLATFORM_NAMES.get(self.platform, self.platform)
        return f"{name} · {self.spec.get('name', KINDS.get(self.kind, self.kind))}: {size_label(self.spec)}"

    @property
    def fixable(self) -> bool:
        """O botão 'Ajustar ao formato' resolve (proporção/resolução, sem cortar nada)."""
        return any(i.width and any(k in " ".join(i.notes) for k in ("proporção", "resolução", "pequeno", "largura",
                                                                 "imagens por segundo", "fora do aceite"))
                   for i in self.items if i.verdict != "ok")

    def _fixable_items(self) -> list[Item]:
        keys = ("proporção", "resolução", "pequeno", "largura", "imagens por segundo", "fora do aceite")
        return [i for i in self.items if i.verdict != "ok" and i.width and any(k in " ".join(i.notes) for k in keys)]

    @property
    def fixable_count(self) -> int:
        return len(self._fixable_items())

    @property
    def fixable_marks(self) -> str:
        """'⚠', '✕' ou '⚠/✕': o que têm as imagens que o botão vai ajustar."""
        v = {i.verdict for i in self._fixable_items()}
        return "/".join(m for k, m in (("ajustar", "⚠"), ("editar", "✕")) if k in v)

    def blocking(self) -> list[str]:
        out = list(self.problems)
        for n, i in enumerate(self.items, 1):
            if i.verdict == "editar":
                out.append(f"ficheiro {n}: {'; '.join(i.notes)}")
        return out


def measure(path: str) -> tuple[int, int, float, float]:
    """(largura, altura, segundos, fps) já com a rotação dos vídeos de telemóvel (guardado em cache)."""
    return _measure(str(path), Path(path).stat().st_mtime)


@lru_cache(maxsize=1024)
def _measure(path: str, mtime: float) -> tuple[int, int, float, float]:
    if is_video(path):
        from .video_editor import probe
        info = probe(path)
        return info.width, info.height, info.duration, info.fps
    from PIL import Image, ImageOps
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        return im.width, im.height, 0.0, 0.0


def _screen_note(r: float, spec: dict) -> str:
    if spec.get("screen") == "phone":
        if abs(r / (9 / 16) - 1) <= 0.03:
            return "No telemóvel ocupa o ecrã inteiro."
        if r > 9 / 16:
            return "No telemóvel não ocupa o ecrã todo: fica com faixas em cima e em baixo."
        return "Mais alto do que o ecrã: é cortado em cima e em baixo."
    w, h = spec["size"]
    t = w / h
    if abs(r / t - 1) <= 0.03:
        return f"No feed ocupa o máximo de espaço ({_ratio_name(t)})."
    if r > t:
        return f"No feed ocupa menos altura do que o ideal ({_ratio_name(t)}): passa mais despercebido."
    return f"Mais alto do que o feed mostra ({_ratio_name(t)}): fica cortado ou com faixas."


def check_item(path: str, spec: dict) -> Item:
    it = Item(path=path, video=is_video(path))
    if not Path(path).exists():
        it.verdict, it.notes = "editar", ["ficheiro não encontrado"]
        return it
    try:
        it.width, it.height, it.seconds, it.fps = measure(path)
        it.bytes = Path(path).stat().st_size
    except Exception as e:  # noqa: BLE001
        it.verdict, it.notes = "editar", [f"não consegui ler o ficheiro ({e})"]
        return it
    if not it.width or not it.height:
        it.verdict, it.notes = "editar", ["sem imagem"]
        return it
    level = {"ok": 0, "ajustar": 1, "editar": 2}
    worst = 0

    def flag(lvl: str, note: str):
        nonlocal worst
        worst = max(worst, level[lvl])
        it.notes.append(note)

    W, H = spec["size"]
    r, target = it.width / it.height, W / H
    lo, hi = spec["ratio"]
    it.screen = _screen_note(r, spec)
    # proporção
    if abs(r / target - 1) > 0.03:
        if lo * 0.99 <= r <= hi * 1.01:
            flag("ajustar", f"proporção {_ratio_name(r)} aceite, mas o ideal é {_ratio_name(target)}")
        elif spec.get("hard_ratio") and spec["hard_ratio"][0] <= r <= spec["hard_ratio"][1]:
            flag("ajustar", f"proporção {_ratio_name(r)}: a rede aceita, mas vai aparecer com faixas ou cortada "
                            f"(ideal {_ratio_name(target)})")
        elif spec.get("soft_ratio"):
            flag("ajustar", f"proporção {_ratio_name(r)} fora do recomendado ({_ratio_name(lo)} a "
                            f"{_ratio_name(hi)}; ideal {_ratio_name(target)})")
        else:
            note = (f"proporção {_ratio_name(r)} fora do que a rede aceita ({_ratio_name(lo)} a {_ratio_name(hi)})"
                    + (": " + spec["short_note"] if spec.get("short_note") else ": seria cortado ou recusado"))
            if spec.get("api_note") and 0.75 * 0.99 <= r < lo:
                note += f" ({spec['api_note']})"
            flag("editar", note)
    # resolução
    short_side, target_short = min(it.width, it.height), min(W, H)
    if spec.get("sides") and not (spec["sides"][0] <= it.width <= spec["sides"][1]
                                  and spec["sides"][0] <= it.height <= spec["sides"][1]):
        flag("editar", f"tamanho {it.size} fora do aceite ({spec['sides'][0]} a {spec['sides'][1]} px por lado)")
    elif spec.get("min_size") and (it.width < spec["min_size"][0] or it.height < spec["min_size"][1]):
        mw, mh = spec["min_size"]
        flag("editar", f"demasiado pequeno ({it.size}; mínimo {mw}×{mh})")
    elif short_side < 320:
        flag("editar", f"resolução demasiado baixa ({it.size})")
    elif short_side < target_short * 0.9:
        flag("ajustar", f"resolução abaixo do recomendado ({it.size}; ideal {W}×{H}): pode perder nitidez")
    if spec.get("max_width") and it.width > spec["max_width"]:
        flag("editar", f"largura {it.width} px acima do máximo ({spec['max_width']} px)")
    # vídeo: duração, fps, ficheiro
    if it.video:
        if spec.get("seconds"):
            mn, mx = spec["seconds"]
            if mn and it.seconds < mn:
                flag("editar", f"vídeo demasiado curto ({_dur(it.seconds)}; mínimo {_dur(mn)})")
            elif it.seconds > mx:
                extra = f": {spec['short_note']}" if spec.get("short_note") else ": tem de ser cortado"
                flag("editar", f"vídeo demasiado longo ({_dur(it.seconds)}; máximo {_dur(mx)}){extra}")
            elif spec.get("rec_seconds") and it.seconds > spec["rec_seconds"] * 1.05:
                flag("ajustar", f"vídeo longo ({_dur(it.seconds)}); o recomendado é até {_dur(spec['rec_seconds'])}")
        if spec.get("fps") and it.fps and not (spec["fps"][0] - 0.5 <= it.fps <= spec["fps"][1] + 0.5):
            flag("editar", f"{it.fps:.0f} imagens por segundo; a rede aceita {spec['fps'][0]} a {spec['fps'][1]}")
        if spec.get("ext") and not it.path.lower().endswith(spec["ext"]):
            flag("editar", f"tem de ser {', '.join(e[1:].upper() for e in spec['ext'])}")
    if spec.get("max_mb") and it.bytes > spec["max_mb"] * 1024 * 1024:
        flag("editar", f"ficheiro com {it.bytes / 1048576:.0f} MB; máximo {spec['max_mb']} MB")
    if spec.get("min_kb") and it.bytes < spec["min_kb"] * 1024:
        flag("editar", f"ficheiro demasiado pequeno ({it.bytes // 1024} KB; mínimo {spec['min_kb']} KB)")
    it.verdict = ["ok", "ajustar", "editar"][worst]
    if not it.notes:
        it.notes = ["encaixa no formato"]
    return it


def check(platform: str, fmt: str | None, paths: list[str]) -> Report:
    kind = kind_of(fmt)
    spec = spec_for(platform, kind)
    rep = Report(platform=platform, kind=kind, spec=spec)
    rep.info += SPECS.get(platform, {}).get("_info", [])
    if not spec:
        possible = ", ".join(v for v in kinds_for(platform).values()) or "nenhum"
        rep.problems.append(f"{PLATFORM_NAMES.get(platform, platform)} não aceita '{KINDS.get(kind, kind)}' "
                            f"por aqui (possível: {possible})")
        return rep
    rep.info += spec.get("info", [])
    if kind == "text":
        if paths:
            rep.warnings.append("escolheu 'Só texto', mas há ficheiros associados: não vão ser publicados")
        return rep
    videos = [p for p in paths if is_video(p)]
    images = [p for p in paths if not is_video(p)]
    if kind == "carousel":
        mn, mx = spec.get("count", (2, 10))
        if videos and platform != "instagram":
            rep.problems.append("o carrossel tem vídeos: nesta rede só leva imagens")
        if len(paths) < mn:
            rep.problems.append(f"um carrossel precisa de pelo menos {mn} imagens (tem {len(paths)})"
                                + (": mude o tipo para 'Uma imagem' ou acrescente imagens" if paths else ""))
        elif len(paths) > mx:
            rep.problems.append(f"um carrossel leva no máximo {mx} imagens (tem {len(paths)})")
    if not paths:
        rep.problems.append("ainda sem imagem/vídeo")
        return rep
    if kind == "video":
        if not videos:
            rep.problems.append("o tipo é 'Um vídeo', mas só há imagens: mude o tipo ou refaça o vídeo")
        elif len(paths) > 1:
            rep.problems.append(f"o tipo é 'Um vídeo', mas há {len(paths)} ficheiros")
    elif kind == "image":
        if videos:
            rep.problems.append("o tipo é 'Uma imagem', mas o ficheiro é um vídeo: mude o tipo para 'Um vídeo'")
        elif len(images) > 1:
            rep.problems.append(f"o tipo é 'Uma imagem', mas há {len(images)} imagens: "
                                "mude para 'Várias imagens (carrossel)'")
    for p in paths:
        s = spec
        if kind != "video" and is_video(p):
            s = spec_for(platform, "video") or spec
        rep.items.append(check_item(p, s))
    if kind == "carousel":
        ratios = {i.ratio for i in rep.items if i.width}
        if len(ratios) > 1:
            rep.warnings.append(f"as imagens têm proporções diferentes ({', '.join(sorted(ratios))}): "
                                "a rede corta todas pela proporção da primeira")
    return rep


# ------------------------------------------------------------------ ajustar sem cortar
def fit_image(src: str, out: str, size: tuple[int, int]) -> str:
    """Encaixa a imagem inteira no tamanho pedido, com fundo desfocado da própria imagem (nada é cortado)."""
    from PIL import Image, ImageFilter, ImageOps
    W, H = size
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        bg = ImageOps.fit(im, (W, H)).filter(ImageFilter.GaussianBlur(40))
        bg = Image.blend(bg, Image.new("RGB", (W, H), (0, 0, 0)), 0.35)
        fg = ImageOps.contain(im, (W, H), Image.LANCZOS)
        bg.paste(fg, ((W - fg.width) // 2, (H - fg.height) // 2))
        bg.save(out, quality=95)
    return out


def fit_video(src: str, out: str, size: tuple[int, int], fps: int | None = None) -> str:
    """Encaixa o vídeo inteiro no tamanho pedido, com fundo desfocado (nada é cortado; som mantido)."""
    import subprocess
    W, H = size
    rate = f",fps={fps}" if fps else ""
    vf = (f"[0:v]split=2[a][b];[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
          f"boxblur=30:3,eq=brightness=-0.08[bg];[b]scale={W}:{H}:force_original_aspect_ratio=decrease[fg];"
          f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1{rate},format=yuv420p[v]")
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", src, "-filter_complex", vf, "-map", "[v]", "-map", "0:a?",
           "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-c:a", "aac", "-b:a", "192k",
           "-movflags", "+faststart", out]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(res.stderr[-500:])
    return out
