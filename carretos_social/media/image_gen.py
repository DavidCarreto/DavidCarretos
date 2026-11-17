"""Criação de imagens de alta qualidade com a identidade da Carretos Group.

- cover():     capa de vídeo (Reel/TikTok/LinkedIn) a partir de um frame + texto forte
- quote_card(): frase/lição de liderança
- carousel():  carrossel (slide de capa, slides de conteúdo, slide final com CTA)
- photo_post(): fotografia da oficina com título e marca

Tudo é renderizado a 2x e reduzido no fim (antialiasing perfeito do texto).
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

from ..config import ROOT, brand

SS = 2  # supersampling


def _v() -> dict:
    return brand()["visual"]


def _hex(c: str, alpha: int = 255) -> tuple[int, int, int, int]:
    c = c.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16), alpha


def _font(bold: bool, size: int) -> ImageFont.FreeTypeFont:
    path = _v()["font_bold" if bold else "font_regular"]
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.truetype("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf", size)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> list[str]:
    lines, line = [], ""
    for word in text.split():
        test = f"{line} {word}".strip()
        if draw.textlength(test, font=font) <= max_w:
            line = test
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def _fit_text(draw, text: str, bold: bool, max_w: int, max_h: int, start: int, min_size: int = 20,
              spacing: float = 1.08):
    size = start
    while size > min_size:
        font = _font(bold, size)
        lines = _wrap(draw, text, font, max_w)
        h = len(lines) * size * spacing
        if h <= max_h and all(draw.textlength(l, font=font) <= max_w for l in lines):
            return font, lines, size
        size -= 4
    font = _font(bold, min_size)
    return font, _wrap(draw, text, font, max_w), min_size


def _draw_lines(draw, lines, font, size, x, y, fill, highlight_words=(), accent=None, align="left",
                width=None, spacing=1.08):
    for line in lines:
        lx = x
        if align == "center" and width:
            lx = x + (width - draw.textlength(line, font=font)) / 2
        for i, word in enumerate(line.split()):
            token = word + (" " if i < len(line.split()) - 1 else "")
            clean = word.strip(".,!?:;").lower()
            color = accent if accent and clean in highlight_words else fill
            draw.text((lx, y), token, font=font, fill=color)
            lx += draw.textlength(token, font=font)
        y += int(size * spacing)
    return y


def _logo(img: Image.Image, width_ratio: float = 0.18, pos: str = "top-right") -> None:
    p = _v().get("logo")
    path = (ROOT / p) if p and not Path(p).is_absolute() else Path(p or "")
    W, H = img.size
    m = int(W * 0.05)
    if p and path.exists():
        logo = Image.open(path).convert("RGBA")
        logo.thumbnail((int(W * width_ratio), int(W * width_ratio)), Image.LANCZOS)
        xy = (W - logo.width - m, m) if pos == "top-right" else (m, H - logo.height - m)
        img.alpha_composite(logo, xy)
    else:  # sem logótipo: marca em texto
        d = ImageDraw.Draw(img)
        f = _font(True, int(W * 0.032))
        text = (brand().get("signature") or brand()["company"]).upper()
        tw = d.textlength(text, font=f)
        if brand().get("themes", {}).get("pessoal", {}).get("signature") == brand().get("signature"):
            # assinatura pessoal: sempre discreta no canto inferior direito, a dourado
            d.text((W - tw - m, H - int(W * 0.03) - f.size), text, font=f, fill=_hex(_v()["colors"]["accent"], 235))
            return
        xy = (W - tw - m, m) if pos == "top-right" else (m, H - m - f.size)
        d.text(xy, text, font=f, fill=_hex(_v()["colors"]["text"], 230))


def _gradient(size, top_alpha=0, bottom_alpha=235, start=0.35) -> Image.Image:
    W, H = size
    grad = Image.new("L", (1, H))
    for y in range(H):
        t = max(0.0, (y / H - start) / (1 - start))
        grad.putpixel((0, y), int(top_alpha + (bottom_alpha - top_alpha) * (t ** 1.4)))
    grad = grad.resize((W, H))
    layer = Image.new("RGBA", (W, H), _hex(_v()["colors"]["primary"]))
    layer.putalpha(grad)
    return layer


def _background(photo: str | Path | None, size) -> Image.Image:
    W, H = size
    if photo and Path(photo).exists():
        img = Image.open(photo)
        img = ImageOps.exif_transpose(img).convert("RGB")
        img = ImageOps.fit(img, (W, H), Image.LANCZOS, centering=(0.5, 0.4))
        img = ImageEnhance.Contrast(img).enhance(1.08)
        img = ImageEnhance.Color(img).enhance(1.05)
        return img.convert("RGBA")
    # fundo de marca: preto com brilho azul subtil
    bg = Image.new("RGBA", (W, H), _hex(_v()["colors"]["primary"]))
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(glow)
    d.ellipse((-W * 0.4, -H * 0.3, W * 0.9, H * 0.6), fill=_hex(_v()["colors"]["accent"], 70))
    glow = glow.filter(ImageFilter.GaussianBlur(W // 5))
    bg.alpha_composite(glow)
    return bg


def _save(img: Image.Image, out: str | Path, final_size) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    img = img.convert("RGB").resize(final_size, Image.LANCZOS)
    if out.suffix.lower() in (".jpg", ".jpeg"):
        img.save(out, quality=95, subsampling=0, optimize=True)
    else:
        img.save(out, optimize=True)
    return out


def _accent_bar(draw, x, y, w, h):
    draw.rectangle((x, y, x + w, y + h), fill=_hex(_v()["colors"]["accent"]))


# ------------------------------------------------------------------ capa de vídeo
def cover(frame: str | Path | None, text: str, out: str | Path, size=(1080, 1920),
          subtitle: str = "", highlight: list[str] | None = None) -> Path:
    """Capa de vídeo: frame com gradiente, texto grande com palavra-chave destacada."""
    W, H = size[0] * SS, size[1] * SS
    img = _background(frame, (W, H))
    img.alpha_composite(_gradient((W, H), start=0.30))
    d = ImageDraw.Draw(img)
    margin = int(W * 0.07)
    max_w = W - 2 * margin
    # zona segura: Reels/TikTok cortam a grelha para 4:5/1:1 no perfil -> texto no centro-baixo
    font, lines, fs = _fit_text(d, text.upper(), True, max_w, int(H * 0.28), int(W * 0.14))
    block_h = len(lines) * int(fs * 1.08)
    y = int(H * 0.62) - block_h // 2
    _accent_bar(d, margin, y - int(fs * 0.45), int(W * 0.14), max(6, fs // 9))
    hl = {w.lower() for w in (highlight or [text.split()[-1]])}
    y = _draw_lines(d, lines, font, fs, margin, y, _hex(_v()["colors"]["text"]), hl,
                    _hex(_v()["colors"]["accent"]))
    if subtitle:
        sf = _font(False, int(fs * 0.36))
        for line in _wrap(d, subtitle, sf, max_w):
            d.text((margin, y + int(fs * 0.2)), line, font=sf, fill=_hex(_v()["colors"]["secondary"]))
            y += int(sf.size * 1.25)
    _logo(img)
    return _save(img, out, size)


# ------------------------------------------------------------------ frase / lição
def quote_card(text: str, out: str | Path, author: str | None = None, size=(1080, 1350),
               photo: str | Path | None = None) -> Path:
    W, H = size[0] * SS, size[1] * SS
    img = _background(photo, (W, H))
    if photo:
        img.alpha_composite(Image.new("RGBA", (W, H), _hex(_v()["colors"]["primary"], 170)))
    d = ImageDraw.Draw(img)
    margin = int(W * 0.09)
    qf = _font(True, int(W * 0.22))
    d.text((margin - int(W * 0.01), int(H * 0.12)), "“", font=qf, fill=_hex(_v()["colors"]["accent"]))
    font, lines, fs = _fit_text(d, text, True, W - 2 * margin, int(H * 0.5), int(W * 0.085))
    y = int(H * 0.30)
    y = _draw_lines(d, lines, font, fs, margin, y, _hex(_v()["colors"]["text"]), spacing=1.15)
    af = _font(False, int(W * 0.034))
    _accent_bar(d, margin, y + int(fs * 0.5), int(W * 0.08), max(4, SS * 3))
    d.text((margin, y + int(fs * 0.8)), (author or _v().get("quote_author") or brand()["owner"]).upper(), font=af,
           fill=_hex(_v()["colors"]["secondary"]))
    _logo(img, pos="top-right")
    return _save(img, out, size)


# ------------------------------------------------------------------ fotografia com título
def photo_post(photo: str | Path | None, title: str, out: str | Path, size=(1080, 1350),
               tag: str = "") -> Path:
    W, H = size[0] * SS, size[1] * SS
    img = _background(photo, (W, H))
    img.alpha_composite(_gradient((W, H), start=0.45))
    d = ImageDraw.Draw(img)
    margin = int(W * 0.07)
    font, lines, fs = _fit_text(d, title, True, W - 2 * margin, int(H * 0.25), int(W * 0.09))
    y = H - margin - len(lines) * int(fs * 1.08)
    if tag:
        tf = _font(True, int(W * 0.03))
        tw = d.textlength(tag.upper(), font=tf)
        pad = int(tf.size * 0.5)
        ty = y - tf.size - pad * 3
        d.rounded_rectangle((margin, ty, margin + tw + 2 * pad, ty + tf.size + 2 * pad), radius=pad,
                            fill=_hex(_v()["colors"]["accent"]))
        d.text((margin + pad, ty + pad * 0.8), tag.upper(), font=tf, fill=_hex("#FFFFFF"))
    _draw_lines(d, lines, font, fs, margin, y, _hex(_v()["colors"]["text"]))
    _logo(img)
    return _save(img, out, size)


# ------------------------------------------------------------------ carrossel
def carousel(slides: list[str], out_dir: str | Path, size=(1080, 1350), cover_photo: str | Path | None = None,
             cta: str | None = None, handle: str = "") -> list[Path]:
    """slides[0] = título de capa; restantes = conteúdo; acrescenta slide final com CTA."""
    cta = cta or _v().get("carousel_cta") or "Guarda e partilha com quem tem um Mercedes"
    out_dir = Path(out_dir)
    paths = []
    total = len(slides) + 1
    W, H = size[0] * SS, size[1] * SS
    margin = int(W * 0.08)
    for i, text in enumerate(slides):
        if i == 0:
            p = photo_post(cover_photo, text, out_dir / f"slide_{i + 1:02d}.jpg", size, tag="Desliza →")
            paths.append(p)
            continue
        img = _background(None, (W, H))
        d = ImageDraw.Draw(img)
        nf = _font(True, int(W * 0.16))
        d.text((margin, int(H * 0.08)), f"{i:02d}", font=nf, fill=_hex(_v()["colors"]["accent"]))
        title, _, body = text.partition("\n")
        font, lines, fs = _fit_text(d, title, True, W - 2 * margin, int(H * 0.3), int(W * 0.08))
        y = _draw_lines(d, lines, font, fs, margin, int(H * 0.30), _hex(_v()["colors"]["text"]))
        if body:
            bfont, blines, bfs = _fit_text(d, body, False, W - 2 * margin, int(H * 0.35), int(W * 0.05))
            _draw_lines(d, blines, bfont, bfs, margin, y + int(fs * 0.4),
                        _hex(_v()["colors"]["secondary"]), spacing=1.3)
        _progress(d, i, total, W, H, margin)
        _logo(img)
        paths.append(_save(img, out_dir / f"slide_{i + 1:02d}.jpg", size))
    # slide final
    img = _background(None, (W, H))
    d = ImageDraw.Draw(img)
    font, lines, fs = _fit_text(d, cta, True, W - 2 * margin, int(H * 0.35), int(W * 0.085))
    y = _draw_lines(d, lines, font, fs, margin, int(H * 0.35), _hex(_v()["colors"]["text"]),
                    align="center", width=W - 2 * margin)
    if handle:
        hf = _font(True, int(W * 0.045))
        hw = d.textlength(f"@{handle}", font=hf)
        d.text(((W - hw) / 2, y + fs), f"@{handle}", font=hf, fill=_hex(_v()["colors"]["accent"]))
    _progress(d, total - 1, total, W, H, margin)
    _logo(img)
    paths.append(_save(img, out_dir / f"slide_{total:02d}.jpg", size))
    return paths


def _progress(d, i, total, W, H, margin):
    bar_w = W - 2 * margin
    y = H - margin
    d.rectangle((margin, y, margin + bar_w, y + SS * 3), fill=_hex(_v()["colors"]["secondary"], 80))
    d.rectangle((margin, y, margin + int(bar_w * (i + 1) / total), y + SS * 3),
                fill=_hex(_v()["colors"]["accent"]))
