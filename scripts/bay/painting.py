"""Pillow helpers for the engine bay v2 decals (system Python; no bpy).

A group's paint module (bay/paint_<group>.py) defines IMAGES = {"bay_<group>_<what>.png": fn}, each fn()
returning a PIL RGB image; scripts/paint_bay_decals.py writes them into blender/bake, where the
group's DECALS entries (kit.register_decals) find them. Paint at ~40 px per cm of the real surface or
more: the bake samples these at its own density, so the image only has to be sharper than that.

Paint the GROUND in the palette colour of the part (srgb("CoverBlack")...), so the decal's faces match
the flat faces around them. Details are drawn, not photographed: cast lettering, labels, bolt heads,
ribs, seams. Keep contrast moderate: the bake multiplies AO on top and the game lights the bay bright.
"""
import os
import random

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from bay.palette import srgb  # noqa: F401  (re-exported for the paint modules)


def font(size, bold=True):
    for name in ("arialbd.ttf" if bold else "arial.ttf", "segoeuib.ttf", "verdanab.ttf"):
        p = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", name)
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def ground(w, h, rgb, grain=0, seed=1, blur=0.7):
    """A plain ground in rgb, with optional fine grain (crinkle paint, cast texture): +-grain levels."""
    im = Image.new("RGB", (w, h), rgb)
    if grain:
        rnd = random.Random(seed)
        px = im.load()
        for y in range(h):
            for x in range(w):
                n = rnd.randint(-grain, grain)
                px[x, y] = tuple(max(0, min(255, c + n)) for c in rgb)
        im = im.filter(ImageFilter.GaussianBlur(blur))
    return im


def shade(rgb, k):
    """rgb scaled by k (k < 1 darker), clamped."""
    return tuple(max(0, min(255, int(round(c * k)))) for c in rgb)


def cast_text(d, xy, text, fnt, fill, shadow, offset=2, anchor="la"):
    """Raised cast lettering: a dark offset shadow under the light letters."""
    x, y = xy
    d.text((x + offset, y + offset), text, font=fnt, fill=shadow, anchor=anchor)
    d.text((x, y), text, font=fnt, fill=fill, anchor=anchor)


def centred(d, cx, y, text, fnt, fill, shadow=None, offset=2):
    w = d.textlength(text, font=fnt)
    if shadow is not None:
        cast_text(d, (cx - w / 2, y), text, fnt, fill, shadow, offset)
    else:
        d.text((cx - w / 2, y), text, font=fnt, fill=fill)


def bolt(d, cx, cy, r, rgb=(120, 120, 124), rim=(30, 30, 32), hexagon=True):
    """A bolt head seen from above: hex (or round) with a dark rim and a light flat."""
    import math
    if hexagon:
        pts = [(cx + r * math.cos(math.radians(30 + 60 * k)), cy + r * math.sin(math.radians(30 + 60 * k))) for k in range(6)]
        d.polygon(pts, fill=rgb, outline=rim)
        d.ellipse([(cx - r * 0.45, cy - r * 0.45), (cx + r * 0.45, cy + r * 0.45)], fill=shade(rgb, 1.15))
    else:
        d.ellipse([(cx - r, cy - r), (cx + r, cy + r)], fill=rgb, outline=rim, width=max(1, int(r / 5)))


def ribs(d, box, n, rgb, dark, light, vertical=True, width_frac=0.45):
    """n moulded ribs across box (x0, y0, x1, y1): each a flat band, dark below/right, light above/left."""
    x0, y0, x1, y1 = box
    span = (x1 - x0) if vertical else (y1 - y0)
    step = span / n
    for k in range(n):
        a = (x0 if vertical else y0) + step * (k + 0.5 - width_frac / 2)
        b = a + step * width_frac
        if vertical:
            d.rectangle([(a, y0), (b, y1)], fill=rgb)
            d.line([(a, y0), (a, y1)], fill=light, width=2)
            d.line([(b, y0), (b, y1)], fill=dark, width=3)
        else:
            d.rectangle([(x0, a), (x1, b)], fill=rgb)
            d.line([(x0, a), (x1, a)], fill=light, width=2)
            d.line([(x0, b), (x1, b)], fill=dark, width=3)


def label(d, box, fill=(196, 190, 170), border=(60, 58, 52), lines=(), fnt=None, ink=(40, 38, 34)):
    """A printed label: a pale rectangle with a border and a few lines of small text."""
    x0, y0, x1, y1 = box
    d.rectangle(box, fill=fill, outline=border, width=2)
    if lines and fnt is not None:
        lh = (y1 - y0) / (len(lines) + 1)
        for i, t in enumerate(lines):
            d.text((x0 + 8, y0 + lh * (i + 0.5)), t, font=fnt, fill=ink)


def grime(im, strength=0.12, seed=7, scale=24):
    """Soft low-frequency darkening (dust settled in corners and low areas), multiplied in."""
    w, h = im.size
    rnd = random.Random(seed)
    small = Image.new("L", (max(2, w // scale), max(2, h // scale)))
    px = small.load()
    for y in range(small.size[1]):
        for x in range(small.size[0]):
            px[x, y] = int(255 * (1.0 - strength * rnd.random()))
    mask = small.resize((w, h), Image.BICUBIC).filter(ImageFilter.GaussianBlur(scale / 2))
    from PIL import ImageChops
    return ImageChops.multiply(im.convert("RGB"), Image.merge("RGB", (mask, mask, mask)))
