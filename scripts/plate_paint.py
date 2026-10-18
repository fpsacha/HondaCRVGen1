r"""
The rear licence plate (and small chrome badge lettering) the paint pass draws on the shell, as RGBA
pictures in metres. paint_pass._plate maps the plate onto the tailgate's recess (PLATE_AT there).

    python scripts\plate_paint.py [out.png]      # a preview of the plate at 100 px per inch

Kentucky, early 1990s (Project Zomboid's Knox County; Kentucky issues rear plates only). The 1988-97
passenger base (Wikipedia, "Vehicle registration plates of Kentucky", 2026-10-13): white reflective plate
(retro-reflective sheeting from 1988), embossed blue serial ABC 123, "Kentucky" screened in blue centred at
the top, the county name on a blue sticker between the state name and the serial, "Bluegrass State" screened
in blue centred at the bottom (the slogan ran 1988-93). Left out on purpose: the twin spires of Churchill
Downs either side of "Kentucky" (the track's trademark) and the light-blue mare and foal in the centre (a
photograph Kentucky withdrew under a copyright claim): generic period style, no logos. The serial is made up
and the year sticker generic. US plate 12 x 6 in with four mounting holes 7 in apart (bolts in the top two,
as on the black 2000 EX's bracket).

Colours are the shipped sRGB at KI5's level scale (paint_pass: white paint at the belt ~110, chrome badges
~180): the plate's white sheeting a step over the white paint, its blues dark enough to read after the
default 512 cap's 4x box. Text is rendered to its ink, then fitted to its box, so the layout does not
depend on a font's metrics; system fonts (Windows) with Pillow's own as the fallback.
"""
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

IN = 0.0254                       # metres per inch
PLATE_W, PLATE_H = 12.0, 6.0      # inches
CORNER = 0.30                     # inches
PX_IN = 100                       # picture pixels per inch
MARGIN = 0.016                    # metres round the plate for its contact shadow
SHADOW = (0.005, 0.004, 0.50)     # offset down (m), blur (m), strength: the plate stands ~1 cm off the recess floor

STATE = "Kentucky"
COUNTY = "KNOX"
SERIAL = "WDL 593"                # made up, in the base's ABC 123 format
SLOGAN = "Bluegrass State"
YEAR = "93"

WHITE = (184, 186, 188)           # reflective sheeting (170 read as grey paint on the white skin at 326 px/m)
SHEEN = (1.03, 0.95)              # top / bottom of the plate (lit from above)
BLUE = (26, 44, 110)              # serial, legends, rim
STICKER = (34, 62, 138)           # county sticker
STICKER_TXT = (196, 198, 202)
YEAR_BG = (196, 128, 34)          # validation sticker (generic)
YEAR_TXT = (40, 30, 20)
HOLE = (34, 34, 36)               # empty bottom slots
BOLT = (128, 130, 134)            # top bolts

SERIAL_FONTS = (("bahnschrift.ttf", b"Bold Condensed"), ("ARIALNB.TTF", None), ("arialbd.ttf", None), ("DejaVuSans-Bold.ttf", None))
STATE_FONTS = (("georgiab.ttf", None), ("timesbd.ttf", None), ("DejaVuSerif-Bold.ttf", None), ("arialbd.ttf", None))
SANS_FONTS = (("arialbd.ttf", None), ("bahnschrift.ttf", b"Bold"), ("DejaVuSans-Bold.ttf", None))
BADGE_FONTS = (("arialbd.ttf", None), ("bahnschrift.ttf", b"Bold"), ("DejaVuSans-Bold.ttf", None))


def _font(cands, px):
    for name, var in cands:
        try:
            f = ImageFont.truetype(name, px)
        except OSError:
            continue
        if var:
            try:
                f.set_variation_by_name(var)
            except Exception:                              # not a variable font, or no such instance
                pass
        return f
    try:
        return ImageFont.load_default(size=px)
    except TypeError:
        return ImageFont.load_default()


def ink(text, cands, px=200):
    """White-on-black coverage (float 0..1) of text, cropped tight to its ink."""
    f = _font(cands, px)
    probe = ImageDraw.Draw(Image.new("L", (8, 8)))
    x0, y0, x1, y1 = probe.textbbox((0, 0), text, font=f)
    img = Image.new("L", (x1 - x0 + 8, y1 - y0 + 8), 0)
    ImageDraw.Draw(img).text((4 - x0, 4 - y0), text, fill=255, font=f)
    a = np.asarray(img, dtype=np.float32) / 255.0
    rows, cols = np.nonzero(a.max(1) > 0.02)[0], np.nonzero(a.max(0) > 0.02)[0]
    return a[rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1]


def _place(layer, mask, cx, cy, h, max_w=None, squeeze=1.0):
    """Paste coverage `mask` into `layer` (float H x W) centred at (cx, cy) px, ink height h px; width keeps
    the aspect times `squeeze`, capped at max_w."""
    w = mask.shape[1] * h / mask.shape[0] * squeeze
    if max_w is not None:
        w = min(w, max_w)
    m = Image.fromarray((mask * 255).astype(np.uint8)).resize((max(1, int(round(w))), max(1, int(round(h)))), Image.LANCZOS)
    m = np.asarray(m, dtype=np.float32) / 255.0
    x0, y0 = int(round(cx - m.shape[1] / 2)), int(round(cy - m.shape[0] / 2))
    H, W = layer.shape
    xa, ya = max(0, x0), max(0, y0)
    xb, yb = min(W, x0 + m.shape[1]), min(H, y0 + m.shape[0])
    if xb > xa and yb > ya:
        layer[ya:yb, xa:xb] = np.maximum(layer[ya:yb, xa:xb], m[ya - y0:yb - y0, xa - x0:xb - x0])


def _rrect(W, H, x0, y0, x1, y1, r, ss=4):
    """Anti-aliased rounded rectangle coverage (float H x W)."""
    im = Image.new("L", (W * ss, H * ss), 0)
    ImageDraw.Draw(im).rounded_rectangle((x0 * ss, y0 * ss, x1 * ss - 1, y1 * ss - 1), radius=r * ss, fill=255)
    return np.asarray(im.resize((W, H), Image.LANCZOS), dtype=np.float32) / 255.0


def _blend(rgb, cov, colour):
    c = np.asarray(colour, dtype=np.float32)
    return rgb * (1.0 - cov[..., None]) + c * cov[..., None]


def plate_rgba():
    """The plate with its contact shadow: (float32 (h, w, 4): sRGB 0..255 and alpha 0..1, rows from the top;
    (width, height) in metres of the whole picture, the plate centred in it)."""
    m = int(round(MARGIN / IN * PX_IN))
    pw, ph = int(PLATE_W * PX_IN), int(PLATE_H * PX_IN)
    W, H = pw + 2 * m, ph + 2 * m
    P = PX_IN

    def X(x_in):
        return m + x_in * P

    def Y(y_in):
        return m + y_in * P
    plate = _rrect(W, H, m, m, m + pw, m + ph, CORNER * P)
    # the sheeting, a touch brighter at the top
    g = np.linspace(SHEEN[0], SHEEN[1], H, dtype=np.float32)[:, None, None]
    rgb = np.ones((H, W, 3), np.float32) * np.asarray(WHITE, np.float32) * g
    # embossed rim
    rim = _rrect(W, H, int(X(0.12)), int(Y(0.12)), int(X(PLATE_W - 0.12)), int(Y(PLATE_H - 0.12)), (CORNER - 0.08) * P)
    rim -= _rrect(W, H, int(X(0.19)), int(Y(0.19)), int(X(PLATE_W - 0.19)), int(Y(PLATE_H - 0.19)), (CORNER - 0.12) * P)
    rgb = _blend(rgb, np.clip(rim, 0, 1), BLUE)
    # "Kentucky" at the top, the county sticker under it, the serial, the slogan at the bottom
    legend = np.zeros((H, W), np.float32)
    _place(legend, ink(STATE, STATE_FONTS), X(6.0), Y(0.78), 0.62 * P, max_w=4.6 * P)
    sticker = _rrect(W, H, int(X(4.55)), int(Y(1.30)), int(X(7.45)), int(Y(1.78)), 0.06 * P)
    rgb = _blend(rgb, sticker, STICKER)
    county = np.zeros((H, W), np.float32)
    _place(county, ink(COUNTY, SANS_FONTS), X(6.0), Y(1.54), 0.30 * P, max_w=2.5 * P)
    rgb = _blend(rgb, county * sticker, STICKER_TXT)
    serial = np.zeros((H, W), np.float32)
    _place(serial, ink(SERIAL, SERIAL_FONTS), X(6.0), Y(3.42), 2.55 * P, max_w=10.2 * P)
    # embossed: a hair of shadow under each character, then the blue face
    emb = np.roll(serial, int(0.03 * P), axis=0) * (1.0 - serial)
    rgb = rgb * (1.0 - 0.25 * emb[..., None])
    legend = np.maximum(legend, serial)
    _place(legend, ink(SLOGAN, STATE_FONTS), X(6.0), Y(5.30), 0.36 * P, max_w=4.4 * P)
    rgb = _blend(rgb, legend, BLUE)
    # validation sticker, top right corner
    yr = _rrect(W, H, int(X(10.15)), int(Y(0.38)), int(X(11.35)), int(Y(1.05)), 0.05 * P)
    rgb = _blend(rgb, yr, YEAR_BG)
    yt = np.zeros((H, W), np.float32)
    _place(yt, ink(YEAR, SANS_FONTS), X(10.75), Y(0.715), 0.42 * P, max_w=0.9 * P)
    rgb = _blend(rgb, yt * yr, YEAR_TXT)
    # mounting: bolts in the top holes, empty slots below (7 in apart, 4.75 in between rows)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    for cx in (2.5, 9.5):
        for cy, col, rad in ((0.62, BOLT, 0.20), (5.37, HOLE, 0.13)):
            d = np.hypot((xx - X(cx)) / (1.6 if cy > 3 else 1.0), yy - Y(cy))
            cov = np.clip(rad * P - d + 0.5, 0.0, 1.0)
            rgb = _blend(rgb, cov, col)
            if cy < 3:                                     # the bolt head's slot
                slot = cov * np.clip(0.035 * P - np.abs(yy - Y(cy)) + 0.5, 0.0, 1.0) * np.clip(0.13 * P - np.abs(xx - X(cx)) + 0.5, 0, 1)
                rgb = _blend(rgb, slot, HOLE)
    # contact shadow on the recess floor
    off, blur, k = SHADOW
    sh = Image.fromarray((plate * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(blur / IN * P / 2.0))
    sh = np.roll(np.asarray(sh, dtype=np.float32) / 255.0, int(round(off / IN * P)), axis=0) * k
    alpha = plate + sh * (1.0 - plate)
    out = np.zeros((H, W, 4), np.float32)
    out[..., :3] = rgb * plate[..., None] / np.maximum(alpha, 1e-4)[..., None]
    out[..., 3] = alpha
    return out, (W / P * IN, H / P * IN)


def _chrome(m, height_m, outline_m, rgb, dark):
    """Coverage m (ink, tight) -> chrome RGBA with a dark rim of outline_m, lighter at the top (lit from above):
    (float32 (h, w, 4), (width, height) m) where height_m is the ink's height."""
    from scipy import ndimage
    r = outline_m / height_m * m.shape[0]
    pad = int(np.ceil(r)) + 2
    a = np.pad(m, pad)
    H, W = a.shape
    rim = ndimage.uniform_filter(ndimage.grey_dilation(a, size=(2 * int(round(r)) + 1,) * 2), size=3)
    grad = np.linspace(1.15, 0.78, H, dtype=np.float32)[:, None, None]
    col = np.asarray(rgb, np.float32)[None, None, :] * grad
    out = np.zeros((H, W, 4), np.float32)
    out[..., :3] = col * a[..., None] + np.asarray(dark, np.float32) * (1.0 - a[..., None])
    out[..., 3] = np.clip(np.maximum(a, 0.85 * rim), 0.0, 1.0)
    scale = height_m / m.shape[0]
    return out, (W * scale, H * scale)


BADGE_ITALIC = (("arialbi.ttf", None), ("DejaVuSans-BoldOblique.ttf", None), ("arialbd.ttf", None))


def badge_rgba(text, height_m, outline_m, rgb, dark, italic=False, width_m=None, px=160):
    """Chrome lettering with a dark rim (paint_pass's EX badge, the garnish's CR-V): ink height height_m,
    width as the font draws it or stretched to width_m. (float32 (h, w, 4), (width, height) m, rim included)."""
    m = ink(text, BADGE_ITALIC if italic else BADGE_FONTS, px)
    if width_m:
        w = max(1, int(round(m.shape[0] * width_m / height_m)))
        m = np.asarray(Image.fromarray((m * 255).astype(np.uint8)).resize((w, m.shape[0]), Image.LANCZOS), dtype=np.float32) / 255.0
    return _chrome(m, height_m, outline_m, rgb, dark)


def bars_rgba(length_m, count, height_m, outline_m, rgb, dark, px_m=4000):
    """`count` short horizontal chrome bars (the garnish's mark left of CR-V), bar and gap alike, over height_m."""
    h = max(count * 2 - 1, int(round(height_m * px_m)))
    w = max(1, int(round(length_m * px_m)))
    m = np.zeros((h, w), np.float32)
    unit = h / (2 * count - 1)
    for i in range(count):
        m[int(round(2 * i * unit)):int(round((2 * i + 1) * unit)), :] = 1.0
    return _chrome(m, height_m, outline_m, rgb, dark)


def main(path=None):
    path = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "blender", "bake", "plate_preview.png")
    rgba, (w, h) = plate_rgba()
    bg = np.ones(rgba.shape[:2] + (3,), np.float32) * 60.0
    img = rgba[..., :3] * rgba[..., 3:] + bg * (1.0 - rgba[..., 3:])
    Image.fromarray(np.clip(img + 0.5, 0, 255).astype(np.uint8)).save(path)
    print("WROTE %s (%.3f x %.3f m)" % (path, w, h))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
