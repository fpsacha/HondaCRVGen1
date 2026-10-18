"""Engine bay v2, group "engine": decals (spec/engine-bay-v2.md). System Python + Pillow.

Each image maps onto faces that are seen from +y (the front) or -x, with u along +x / +y: seen from
there the image's left runs to the viewer's right. Positions are drawn in u space; only lettering is
painted mirrored so it reads from the front.
"""
import math

from PIL import Image, ImageDraw, ImageFilter, ImageOps

from bay import painting as P
from bay.palette import srgb

PX = 40.0          # pixels per cm


# ----------------------------------------------------------------------------- cam cover front
# DecalCoverFront: x -0.34..0.13 (u), z 0.900..0.978 (v)
CX0, CX1, CZ0, CZ1 = -0.34, 0.13, 0.900, 0.978


def _cover_px(w, h):
    def at(x, z):
        u = (x - CX0) / (CX1 - CX0)
        return u * w, (1.0 - (z - CZ0) / (CZ1 - CZ0)) * h
    return at


def cover_front():
    w, h = int(47 * PX), int(7.8 * PX)
    base = srgb("CoverBlack")
    im = P.ground(w, h, base, grain=7, seed=3, blur=0.8)
    d = ImageDraw.Draw(im)
    at = _cover_px(w, h)
    hi = P.shade(base, 1.9)
    lo = P.shade(base, 0.45)
    # flange: the lower lip (z 0.900-0.914), a light edge where it turns up into the face
    _, yf = at(0, 0.914)
    _, yf2 = at(0, 0.920)
    d.rectangle([(0, yf), (w, h)], fill=P.shade(base, 0.85))
    d.line([(0, yf), (w, yf)], fill=hi, width=3)
    d.line([(0, yf2), (w, yf2)], fill=P.shade(base, 1.4), width=2)
    # the lobe's crest catches the light
    _, yc = at(0, 0.972)
    d.line([(0, yc), (w, yc)], fill=P.shade(base, 1.5), width=4)
    # cover bolts on the flange: steel heads with rubber washers
    for x in (-0.300, -0.200, -0.100, 0.000, 0.095):
        px, py = at(x, 0.907)
        d.ellipse([(px - 20, py - 14), (px + 20, py + 14)], fill=(22, 22, 22))
        P.bolt(d, px, py - 1, 12, rgb=(118, 118, 120), rim=(40, 40, 42))
    # cast lettering on the -x half of the sloped face: silver on black, raised (shadow below)
    fnt = P.font(46)
    text = "HONDA MOTOR CO."
    tw = int(d.textlength(text, font=fnt))
    th = 56
    lay = Image.new("RGBA", (tw + 8, th), (0, 0, 0, 0))
    ld = ImageDraw.Draw(lay)
    ld.text((3, 6), text, font=fnt, fill=(12, 12, 12, 255))
    ld.text((0, 2), text, font=fnt, fill=(150, 150, 146, 255))
    tw_target = int((0.205 - 0.035) * 100 * PX)          # x -0.205..-0.035: 17 cm long
    th_target = int(0.0150 / (CZ1 - CZ0) * h)            # 15 mm tall in z
    lay = lay.resize((tw_target, th_target), Image.LANCZOS)
    x_mid, z_mid = -0.120, 0.954
    px, py = at(x_mid, z_mid)
    # seen from the front the image runs right-to-left: the letters are painted mirrored
    lay = ImageOps.mirror(lay)
    im.paste(lay, (int(px - tw_target / 2), int(py - th_target / 2)), lay)
    # a few chips of paint off the crest (the photos' covers are worn) and soft grime low
    im = P.grime(im, strength=0.10, seed=11, scale=30)
    return im


# ----------------------------------------------------------------------------- heat shield
# DecalShield: x -0.275..0.085 (u), z 0.605..0.900 (v)
SX0, SX1, SZ0, SZ1 = -0.275, 0.085, 0.605, 0.900
SHIELD_ROWS = [(0.882, -0.262, 0.072), (0.800, -0.270, 0.080), (0.748, -0.222, 0.032),
               (0.690, -0.190, 0.000), (0.630, -0.168, -0.022)]


def shield():
    w, h = int(36 * PX), int(29.5 * PX)
    base = srgb("ShieldSteel")
    im = P.ground(w, h, base, grain=10, seed=5, blur=1.0)

    def at(x, z):
        return (x - SX0) / (SX1 - SX0) * w, (1.0 - (z - SZ0) / (SZ1 - SZ0)) * h

    # heat tint: brown-bronze low on the tongue and round the hole, multiplied in softly
    tint = Image.new("L", (w, h), 0)
    td = ImageDraw.Draw(tint)
    cx, cy = at(-0.095, 0.66)
    td.ellipse([(cx - 230, cy - 200), (cx + 230, cy + 260)], fill=150)
    hx, hy = at(-0.105, 0.815)
    td.ellipse([(hx - 120, hy - 90), (hx + 120, hy + 150)], fill=90)
    tint = tint.filter(ImageFilter.GaussianBlur(70))
    brown = Image.new("RGB", (w, h), (112, 84, 58))
    im = Image.composite(brown, im, tint.point(lambda a: int(a * 0.38)))
    hi = P.shade(base, 1.35)
    lo = P.shade(base, 0.62)

    # outline of the pressing, inset: the raised panel's edge
    def outline(inset):
        left, right = [], []
        for z, xl, xr in SHIELD_ROWS:
            zz = z - inset if z > 0.87 else (z + inset * 0.6 if z < 0.64 else z)
            left.append(at(xl + inset, zz))
            right.append(at(xr - inset, zz))
        return left + right[::-1]

    # soft stamped relief: every ridge lit from the upper left, shadowed lower right, blurred
    light = Image.new("L", (w, h), 0)
    dark = Image.new("L", (w, h), 0)
    ld, dd = ImageDraw.Draw(light), ImageDraw.Draw(dark)

    def ridge(pts, closed=False, width=16):
        pts = list(pts) + ([pts[0]] if closed else [])
        ld.line([(x - 5, y - 5) for x, y in pts], fill=255, width=width, joint="curve")
        dd.line([(x + 6, y + 6) for x, y in pts], fill=255, width=width, joint="curve")

    ridge(outline(0.020), closed=True, width=20)
    # the step across the upper band, the centre channel down into the tongue
    ridge([at(-0.245, 0.812), at(0.055, 0.812)])
    ridge([at(-0.175, 0.800), at(-0.155, 0.700), at(-0.140, 0.645)])
    ridge([at(-0.015, 0.800), at(-0.035, 0.700), at(-0.050, 0.645)])
    light = light.filter(ImageFilter.GaussianBlur(6))
    dark = dark.filter(ImageFilter.GaussianBlur(7))
    im = Image.composite(Image.new("RGB", (w, h), P.shade(base, 1.45)), im, light.point(lambda a: int(a * 0.75)))
    im = Image.composite(Image.new("RGB", (w, h), P.shade(base, 0.45)), im, dark.point(lambda a: int(a * 0.8)))
    d = ImageDraw.Draw(im)
    # the oxygen-sensor hole near the top centre: dark, with a light lower lip
    d.ellipse([(hx - 62, hy - 78), (hx + 62, hy + 78)], fill=(18, 16, 15), outline=lo, width=6)
    d.arc([(hx - 66, hy - 82), (hx + 66, hy + 82)], 20, 160, fill=hi, width=6)
    # the sensor's hex just visible inside
    P.bolt(d, hx, hy + 30, 26, rgb=(70, 66, 60), rim=(20, 18, 16))
    # the lower opening at the tongue (the downpipe flange behind)
    lx, ly = at(-0.095, 0.655)
    d.ellipse([(lx - 40, ly - 30), (lx + 40, ly + 30)], fill=(24, 22, 20), outline=lo, width=4)
    # bolts: two top corners, two at the shoulders, one low
    for x, z in ((-0.225, 0.858), (0.035, 0.858), (-0.150, 0.735), (-0.040, 0.735), (-0.095, 0.700)):
        bx, by = at(x, z)
        d.ellipse([(bx - 26, by - 26), (bx + 26, by + 26)], fill=P.shade(base, 0.7))
        P.bolt(d, bx, by, 18, rgb=(96, 88, 78), rim=(36, 32, 28))
    im = P.grime(im, strength=0.14, seed=17, scale=40)
    return im


# ----------------------------------------------------------------------------- timing cover (-x face)
# DecalTiming: y 1.26..1.50 (u), z 0.60..0.975 (v); seen from -x the image's left is the car's front
def timing():
    w, h = int(24 * 20), int(37.5 * 20)
    base = srgb("Plastic")
    im = P.ground(w, h, base, grain=5, seed=9, blur=0.7)
    d = ImageDraw.Draw(im)

    def at(y, z):
        return (y - 1.26) / 0.24 * w, (1.0 - (z - 0.60) / 0.375) * h

    hi, lo = P.shade(base, 1.8), P.shade(base, 0.5)
    # moulded horizontal stiffening ribs on the upper cover
    for z in (0.800, 0.835, 0.870, 0.905):
        a, b = at(1.29, z), at(1.47, z)
        d.line([a, b], fill=hi, width=4)
        d.line([(a[0], a[1] + 4), (b[0], b[1] + 4)], fill=lo, width=3)
    # the seam between the upper and lower covers
    a, b = at(1.27, 0.776), at(1.49, 0.776)
    d.line([a, b], fill=lo, width=6)
    # bolts on the covers
    for y, z in ((1.300, 0.940), (1.460, 0.940), (1.300, 0.760), (1.470, 0.700), (1.310, 0.640)):
        bx, by = at(y, z)
        P.bolt(d, bx, by, 9, rgb=(96, 96, 98), rim=(28, 28, 30))
    return im


IMAGES = {
    "bay_engine_cover_front.png": cover_front,
    "bay_engine_shield.png": shield,
    "bay_engine_timing.png": timing,
}
