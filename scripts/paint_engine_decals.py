r"""
Paint the small detail textures the engine bay samples by object position (no UVs needed).

    python scripts\paint_engine_decals.py

Writes into blender/bake/:
    cover_top.png    black wrinkle finish, "DOHC  B20B" cast lettering (the owner's touch)
    cover_front.png  the cover's front band: "HONDA MOTOR CO." as on the B18B1 reference photo
    radiator.png     horizontal fin pattern for the radiator core
    hood_pad.png     grey fibre insulator pad with its two cut-outs
    airbox.png       ribbed black plastic lid
    battery.png      black case with a label strip and the +/- marks
build_engine.py maps each across its surface with an Object-coordinate Mapping node, so the
atlas bake carries them like any other material colour. System Python + Pillow.
"""
import math
import os
import random

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "blender", "bake")


def _font(size, bold=True):
    for name in ("arialbd.ttf" if bold else "arial.ttf", "segoeuib.ttf", "verdanab.ttf"):
        p = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", name)
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def _wrinkle(w, h, base=(22, 22, 24), amp=9, seed=3):
    """Crinkle-finish black: fine random speckle, softened."""
    rnd = random.Random(seed)
    im = Image.new("RGB", (w, h), base)
    px = im.load()
    for y in range(h):
        for x in range(w):
            n = rnd.randint(-amp, amp)
            px[x, y] = tuple(max(0, min(255, c + n)) for c in base)
    return im.filter(ImageFilter.GaussianBlur(0.8))


def _text(d, xy, text, font, fill, shade, offset=3):
    x, y = xy
    d.text((x + offset, y + offset), text, font=font, fill=shade)
    d.text((x, y), text, font=font, fill=fill)


def cover_top():
    W, H = 1024, 448                              # cover top 0.50 x 0.22 m
    im = _wrinkle(W, H)
    d = ImageDraw.Draw(im)
    # raised centre channel (spark plug tubes) slightly lighter, four plug wells
    d.rectangle([(90, 150), (W - 90, 298)], fill=(34, 34, 36), outline=(60, 60, 62), width=3)
    for i in range(4):
        cx = 200 + i * 208
        d.ellipse([(cx - 30, 194), (cx + 30, 254)], fill=(12, 12, 13), outline=(70, 70, 72), width=3)
    # lettering along the front edge of the top
    f = _font(64)
    line = "DOHC      B20B"
    tw = d.textlength(line, font=f)
    _text(d, ((W - tw) / 2, 330), line, f, (150, 150, 154), (8, 8, 9))
    # oil cap ring, left end
    d.ellipse([(120, 44), (200, 124)], fill=(18, 18, 20), outline=(90, 90, 94), width=4)
    im = im.rotate(180)                           # read from the bumper
    im.save(os.path.join(OUT, "cover_top.png"))


def cover_front():
    W, H = 1024, 112                              # cover front band 0.50 x 0.055 m
    im = _wrinkle(W, H)
    d = ImageDraw.Draw(im)
    f = _font(58)
    line = "HONDA MOTOR CO."
    tw = d.textlength(line, font=f)
    _text(d, ((W - tw) / 2, 22), line, f, (160, 160, 164), (6, 6, 7), 2)
    # bolt heads along the band
    for x in range(64, W, 128):
        d.ellipse([(x - 9, 88), (x + 9, 106)], fill=(110, 110, 114), outline=(40, 40, 42), width=2)
    im.save(os.path.join(OUT, "cover_front.png"))


def radiator():
    W, H = 512, 256
    im = Image.new("RGB", (W, H), (28, 28, 30))
    d = ImageDraw.Draw(im)
    for y in range(0, H, 4):
        d.line([(0, y), (W, y)], fill=(52, 52, 55), width=1)
    for x in range(0, W, 48):
        d.line([(x, 0), (x, H)], fill=(20, 20, 22), width=2)
    im.save(os.path.join(OUT, "radiator.png"))


def hood_pad():
    W, H = 1024, 768                              # pad ~1.30 x 0.95 m
    rnd = random.Random(11)
    im = Image.new("RGB", (W, H), (58, 58, 60))
    px = im.load()
    for y in range(H):
        for x in range(W):
            n = rnd.randint(-14, 14)
            px[x, y] = (58 + n, 58 + n, 60 + n)
    im = im.filter(ImageFilter.GaussianBlur(1.2))
    d = ImageDraw.Draw(im)
    # two pressed cut-outs and a stitched border, like the B18B1 photo's hood liner
    for box in [(120, 150, 430, 520), (594, 150, 904, 520)]:
        d.rectangle(box, fill=(40, 40, 42), outline=(76, 76, 78), width=4)
    d.rectangle([(20, 20), (W - 20, H - 20)], outline=(84, 84, 86), width=6)
    im.save(os.path.join(OUT, "hood_pad.png"))


def airbox():
    W, H = 512, 512
    im = _wrinkle(W, H, base=(20, 20, 22), amp=5, seed=5)
    d = ImageDraw.Draw(im)
    for x in range(40, W - 40, 44):
        d.rectangle([(x, 60), (x + 18, H - 60)], fill=(34, 34, 36), outline=(10, 10, 11), width=2)
    d.ellipse([(W // 2 - 40, H // 2 - 40), (W // 2 + 40, H // 2 + 40)], fill=(14, 14, 15), outline=(60, 60, 62), width=3)
    im.save(os.path.join(OUT, "airbox.png"))


def battery():
    W, H = 512, 448
    im = Image.new("RGB", (W, H), (18, 18, 20))
    d = ImageDraw.Draw(im)
    d.rectangle([(40, 150), (W - 40, 300)], fill=(200, 196, 180))
    d.rectangle([(40, 150), (W - 40, 190)], fill=(150, 30, 30))
    f = _font(44)
    _text(d, (70, 210), "MAINTENANCE FREE", f, (30, 30, 34), (30, 30, 34), 0)
    f2 = _font(72)
    _text(d, (70, 40), "+", f2, (200, 40, 40), (200, 40, 40), 0)
    _text(d, (W - 130, 40), "-", f2, (200, 200, 200), (200, 200, 200), 0)
    im.save(os.path.join(OUT, "battery.png"))


def headlight():
    """RD1 composite headlamp seen through its clear lens: two reflector bowls (low beam inboard,
    high beam outboard), bulb caps, horizontal fluting, dark surround. u = |x| inboard->outboard.
    Brightened 2026-10-12: on the shipped sheet the lens averaged (89, 90, 93), a grey disc at the
    game's zoom next to KI5's lamps (Bronco 108, Hilux 86, both with a dark rim and a bright
    centre). The housing is now light silver, the bowls peak at 240 and a 10 px near-black frame
    gives the lamp the outline that makes it read as a lamp at 6-10 screen pixels."""
    W, H = 512, 224
    im = Image.new("RGB", (W, H), (150, 152, 160))       # silver housing seen through the lens
    d = ImageDraw.Draw(im)
    import math as _m
    for cx, rx, ry in ((150, 118, 88), (372, 104, 84)):
        for k in range(14, 0, -1):                        # concentric facets, bright bowl, darker rim
            t = k / 14.0
            g = int(240 - 90 * t ** 1.3)
            d.ellipse([(cx - rx * t, H / 2 - ry * t), (cx + rx * t, H / 2 + ry * t)], fill=(g, g, g + 5))
        for a in range(0, 360, 30):                       # facet spokes
            x1, y1 = cx + rx * _m.cos(_m.radians(a)), H / 2 + ry * _m.sin(_m.radians(a))
            d.line([(cx, H / 2), (x1, y1)], fill=(110, 112, 118), width=1)
        d.ellipse([(cx - 22, H / 2 - 22), (cx + 22, H / 2 + 22)], fill=(250, 250, 252), outline=(150, 150, 155), width=3)
        d.ellipse([(cx - 9, H / 2 - 9), (cx + 9, H / 2 + 9)], fill=(190, 190, 196))
    for y in range(6, H, 9):                              # lens fluting, light
        d.line([(0, y), (W, y)], fill=(196, 198, 206), width=1)
    d.rectangle([(0, 0), (W - 1, H - 1)], outline=(26, 27, 30), width=10)
    im = im.filter(ImageFilter.GaussianBlur(0.4))
    im.save(os.path.join(OUT, "headlight.png"))


def tail_ribs():
    """Vertical ribbing multiplied into the tail-lamp colours (grey 1.0 = no change). Lifted
    2026-10-12 (base 215 -> 232, ribs 150 -> 170, bars 120 -> 150) now that the lens palette itself
    is deep (bake_atlas.PALETTE Feux_*): the old ribs over the old pale kotris red gave (129, 62, 61).
    An 8 px border at 40 outlines the lens the way KI5's tail lamps carry a dark rim."""
    W, H = 128, 256
    im = Image.new("RGB", (W, H), (232, 232, 232))
    d = ImageDraw.Draw(im)
    for x in range(0, W, 8):
        d.line([(x, 0), (x, H)], fill=(170, 170, 170), width=2)
        d.line([(x + 4, 0), (x + 4, H)], fill=(255, 255, 255), width=1)
    for y in range(0, H, 64):
        d.line([(0, y), (W, y)], fill=(150, 150, 150), width=3)
    d.rectangle([(0, 0), (W - 1, H - 1)], outline=(40, 40, 40), width=8)
    im.save(os.path.join(OUT, "tail_ribs.png"))


def cluster():
    """Instrument binnacle for the driver's side of the dash: tach, speedo, two small gauges."""
    import math as _m
    W, H = 512, 232
    im = Image.new("RGB", (W, H), (30, 30, 32))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([(6, 6), (W - 6, H - 6)], radius=40, fill=(18, 18, 20), outline=(60, 60, 64), width=4)
    f = _font(20)
    for cx, r, ticks, red_from in ((150, 88, 8, 6), (362, 88, 12, None)):
        d.ellipse([(cx - r, H / 2 - r), (cx + r, H / 2 + r)], fill=(8, 8, 9), outline=(150, 150, 156), width=3)
        for k in range(ticks + 1):
            a = _m.radians(-225 + 270 * k / ticks)
            col = (230, 60, 50) if (red_from is not None and k >= red_from) else (225, 225, 230)
            x0, y0 = cx + (r - 14) * _m.cos(a), H / 2 + (r - 14) * _m.sin(a)
            x1, y1 = cx + (r - 4) * _m.cos(a), H / 2 + (r - 4) * _m.sin(a)
            d.line([(x0, y0), (x1, y1)], fill=col, width=3)
            tx, ty = cx + (r - 30) * _m.cos(a), H / 2 + (r - 30) * _m.sin(a)
            d.text((tx - 7, ty - 9), str(k * (1 if ticks == 8 else 10)), font=f, fill=(210, 210, 215))
        a = _m.radians(-225 + 270 * 0.12)
        d.line([(cx, H / 2), (cx + (r - 10) * _m.cos(a), H / 2 + (r - 10) * _m.sin(a))], fill=(240, 240, 245), width=4)
        d.ellipse([(cx - 8, H / 2 - 8), (cx + 8, H / 2 + 8)], fill=(40, 40, 44))
    for cx in (256, 256):
        pass
    for cx, cy in ((256, 62), (256, 170)):
        d.ellipse([(cx - 30, cy - 30), (cx + 30, cy + 30)], fill=(8, 8, 9), outline=(140, 140, 146), width=2)
        d.line([(cx, cy), (cx - 18, cy - 16)], fill=(240, 240, 245), width=3)
    d.text((228, 96), "F", font=f, fill=(200, 200, 205)); d.text((272, 96), "E", font=f, fill=(200, 200, 205))
    d.text((228, 200), "H", font=f, fill=(200, 200, 205)); d.text((272, 200), "C", font=f, fill=(200, 200, 205))
    im.save(os.path.join(OUT, "cluster.png"))


HUB_DECAL_R = 0.105        # the square's half size in metres (bake_atlas TEXTURED HubCap / lift.BAKE_TEXTURED)
HUB_LUG_R = 0.057          # prep_parts.RIM_LUG_R: the 5 x 114.3 mm lug circle
HUB_CAP_R = 0.032          # prep_parts.RIM_CAP_R: the H cap (review_wheels\ref\ex_fr_wheel.jpg)
HUB_ALLOY = 152            # sRGB of the alloy face round the cap (bake_atlas PALETTE Jante 0.32 linear)


def _honda_h(cx, cy, w, h):
    """The Honda H as two polygons and a bar (PIL coordinates, y down): uprights a little wider at the
    top and leaning out, the bar just above the middle."""
    up_t, up_b, lean = 0.25 * w, 0.21 * w, 0.03 * w
    left = [(cx - w / 2, cy - h / 2), (cx - w / 2 + up_t, cy - h / 2),
            (cx - w / 2 + lean + up_b, cy + h / 2), (cx - w / 2 + lean, cy + h / 2)]
    right = [(2 * cx - x, y) for x, y in left]
    bar = [(cx - w / 2 + up_t * 0.8, cy - 0.12 * h), (cx + w / 2 - up_t * 0.8, cy - 0.12 * h),
           (cx + w / 2 - up_t * 0.8, cy + 0.07 * h), (cx - w / 2 + up_t * 0.8, cy + 0.07 * h)]
    return [left, right, bar]


def hubcap():
    """Hub decal over the hub cone (prep_parts._rim_face, r RIM_HUB_R 0.070 m; the square spans
    +-HUB_DECAL_R): the alloy face, the five lug nuts in their seats on the 5 x 114.3 circle (r 0.057 m,
    straight up and every 72 degrees: the windows' phase on the road wheels, prep_parts.RIM_ROAD_PHASE)
    and the silver centre cap (r 0.032) with its embossed H, as on the real EX wheel
    (review_wheels\\ref\\ex_fr_wheel.jpg). 2026-10-17 review (WHL-3): the old cap was a dark badge with a
    white H inside a bright ring and white nuts, a black-and-white sticker at the game's zoom; now
    everything is silver and only the shading draws it: a dark hairline round the cap, the H raised in
    a slightly lighter silver with a shadow under it and a lit upper edge, the nuts' seats a shade darker
    than the face. Painted at 4x and box-reduced (an anti-aliased map: the colour bake point-samples).
    Mirror-symmetric about the vertical, so the left wheels (the same model turned 180 degrees) show the
    same face."""
    S = 4
    W = 512
    N = W * S
    c = N / 2
    k = N / (2 * HUB_DECAL_R)                             # pixels a metre
    a0 = HUB_ALLOY
    im = Image.new("RGB", (N, N), (a0, a0, a0 + 3))
    d = ImageDraw.Draw(im)
    for r in range(N // 2, 40, -28):                      # faint machining rings on the alloy face
        g = a0 - 3 + (r // 28) % 2 * 4
        d.ellipse([(c - r, c - r), (c + r, c + r)], outline=(g, g, g + 3), width=6)
    rn = HUB_LUG_R * k                                    # lug nuts: a darker seat, the hex face, the stud
    seat, hex_r, stud = 0.0125 * k, 0.0092 * k, 0.0038 * k
    for j in range(5):
        a = math.radians(90 + 72 * j)
        x, y = c + rn * math.cos(a), c - rn * math.sin(a)
        d.ellipse([(x - seat, y - seat), (x + seat, y + seat)], fill=(a0 - 42, a0 - 42, a0 - 39))
        d.ellipse([(x - seat + 0.002 * k, y - seat + 0.002 * k), (x + seat, y + seat)], fill=(a0 - 28, a0 - 28, a0 - 25))
        hexa = [(x + hex_r * math.cos(math.radians(60 * i)), y + hex_r * math.sin(math.radians(60 * i))) for i in range(6)]
        d.polygon([(px + 0.0012 * k, py + 0.0012 * k) for px, py in hexa], fill=(a0 - 60, a0 - 60, a0 - 57))   # shadow
        d.polygon(hexa, fill=(a0 + 18, a0 + 18, a0 + 22))
        d.ellipse([(x - stud, y - stud), (x + stud, y + stud)], fill=(a0 - 20, a0 - 20, a0 - 17))
    rc = HUB_CAP_R * k                                    # the cap: hairline gap, silver dome lit from the upper left
    gap = 0.0016 * k
    d.ellipse([(c - rc - gap, c - rc - gap), (c + rc + gap, c + rc + gap)], fill=(a0 - 72, a0 - 72, a0 - 69))
    base = 205                                            # 168 -> 205 (2026-10-17 round 2, R2-WA-5): the cap reads brighter than the spokes (~154)
    steps = 24
    for i in range(steps):
        t = i / (steps - 1)                               # 0 outside .. 1 at the highlight
        r = rc * (1.0 - 0.55 * t)
        off = 0.25 * rc * t
        g = int(base - 10 + 34 * t)
        d.ellipse([(c - r - off, c - r - off), (c + r - off, c + r - off)], fill=(g, g, g + 3))
    hw, hh = 1.05 * rc, 0.86 * rc                         # the H: ~3.4 x 2.8 cm on the 6.4 cm cap
    sh = 0.0014 * k
    polys = _honda_h(c, c, hw, hh)
    for p in polys:                                       # recessed outline round the raised H, its shadow
        d.polygon([(x + sh, y + sh) for x, y in p], fill=(86, 86, 90))
    for p in polys:
        d.polygon([(x - sh * 0.6, y - sh * 0.6) for x, y in p], fill=(246, 246, 248))   # the lit upper edge
    for p in polys:
        d.polygon(p, fill=(226, 226, 230))
    im = im.resize((W, W), Image.BOX)
    im.save(os.path.join(OUT, "hubcap.png"))


def paint(out=None):
    global OUT
    if out:
        OUT = out
    os.makedirs(OUT, exist_ok=True)
    for fn in (cover_top, cover_front, radiator, hood_pad, airbox, battery, headlight, tail_ribs, cluster, hubcap):
        fn()
        print("WROTE", fn.__name__ + ".png")


if __name__ == "__main__":
    import sys
    paint(sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else None)   # --out DIR: a scratch bake
