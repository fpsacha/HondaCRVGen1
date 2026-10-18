"""Decals for the engine bay v2 group "sides" (Pillow only; run by scripts/paint_bay_decals.py).

Each image maps onto its faces as declared in bay/sides.py DECALS: u = x across the image (image right =
+x), v = y or z up the image (image top = the far end of the range). The battery and fuse lids are read
from the front of the car, so they are painted in the viewer's orientation and turned 180 degrees; the
battery's front face is mirrored (the viewer at the bumper sees +x on their left).
"""
import math

from PIL import Image, ImageDraw, ImageOps

from bay import painting as P
from bay.painting import srgb

PPC = 40   # pixels per cm


def _img(w_m, h_m, rgb):
    return P.ground(int(round(w_m * 100 * PPC)), int(round(h_m * 100 * PPC)), rgb)


def battery_top():
    """Lid top, 0.223 x 0.140 m. Viewer canvas: left = outboard (+x), top = the firewall side."""
    base = srgb("Plastic")
    im = _img(0.223, 0.140, base)
    W, H = im.size
    d = ImageDraw.Draw(im)

    def px(x, y):          # car (x, y) -> viewer canvas pixel
        return ((0.559 - x) / 0.223 * W, (y - 0.999) / 0.140 * H)

    edge = P.shade(base, 1.9)
    d.rectangle([(6, 6), (W - 7, H - 7)], outline=edge, width=5)                       # lid lip seam
    # moulded vent strip along the front edge
    x0, y0 = px(0.545, 1.118)
    x1, y1 = px(0.350, 1.128)
    d.rectangle([(x0, y0), (x1, y1)], fill=P.shade(base, 0.6), outline=P.shade(base, 2.0), width=2)
    for k in range(6):
        cx = x0 + (x1 - x0) * (k + 0.5) / 6
        d.ellipse([(cx - 9, y0 + 2), (cx + 9, y1 - 2)], fill=P.shade(base, 2.2))
    # printed label between the terminals and the hold-down (outboard half)
    lx0, ly0 = px(0.538, 1.058)
    lx1, ly1 = px(0.470, 1.108)
    P.label(d, (lx0, ly0, lx1, ly1), fill=(150, 146, 134), border=(52, 50, 46),
            lines=("MAINTENANCE FREE", "12V  CCA 525", "GROUP 51R"), fnt=P.font(26), ink=(32, 30, 28))
    # barcode strip on the label
    bx = lx0 + 12
    rnd = [3, 1, 2, 1, 3, 2, 1, 1, 2, 3, 1, 2, 1, 1, 3, 1, 2]
    for w in rnd * 2:
        d.rectangle([(bx, ly1 - 30), (bx + w * 2, ly1 - 10)], fill=(30, 30, 30))
        bx += w * 2 + 3
    # green "eye" test indicator, inboard of the hold-down
    ex, ey = px(0.405, 1.080)
    d.ellipse([(ex - 30, ey - 30), (ex + 30, ey + 30)], fill=P.shade(base, 2.5), outline=(20, 20, 20), width=4)
    d.ellipse([(ex - 16, ey - 16), (ex + 16, ey + 16)], fill=(30, 110, 50))
    # terminal markings moulded beside the posts
    f = P.font(54)
    for (x, y, t) in ((0.395, 1.030, "+"), (0.500, 1.030, "-")):
        cx, cy = px(x, y)
        P.centred(d, cx, cy - 30, t, f, P.shade(base, 3.5), shadow=(0, 0, 0))
    # posts' collars (the clamp and boot sit on top in geometry)
    for (x, y) in ((0.376, 1.032), (0.525, 1.031)):
        cx, cy = px(x, y)
        d.ellipse([(cx - 46, cy - 46), (cx + 46, cy + 46)], fill=P.shade(base, 1.6), outline=(10, 10, 10), width=3)
    im = P.grime(im, 0.10, seed=11)
    return im.rotate(180)


def battery_front():
    """Case front face (+y), 0.215 x 0.175 m. Painted as seen from the bumper, then mirrored."""
    base = srgb("Plastic")
    im = _img(0.215, 0.175, base)
    W, H = im.size
    d = ImageDraw.Draw(im)
    # moulded handle ledge near the top, and the foot ledge at the bottom
    d.rectangle([(0, 18), (W, 34)], fill=P.shade(base, 2.0))
    d.rectangle([(0, H - 36), (W, H - 20)], fill=P.shade(base, 1.8))
    # the sticker: muted silver-grey band with dark lettering, a dull red stripe
    x0, y0, x1, y1 = 40, 70, W - 40, int(H * 0.62)
    d.rectangle([(x0, y0), (x1, y1)], fill=(118, 116, 110), outline=(40, 40, 40), width=3)
    d.rectangle([(x0, y0 + 10), (x1, y0 + 48)], fill=(92, 24, 20))
    P.centred(d, W / 2, y0 + 12, "HEAVY DUTY", P.font(32), (200, 196, 186))
    P.centred(d, W / 2, y0 + 70, "12 VOLT", P.font(70), (26, 26, 26))
    P.centred(d, W / 2, y0 + 160, "525 COLD CRANKING AMPS", P.font(30), (26, 26, 26))
    P.centred(d, W / 2, y0 + 205, "RESERVE 90 MIN", P.font(26, bold=False), (36, 36, 36))
    # small white warning sticker lower left (as lhd_06)
    d.rectangle([(70, int(H * 0.68)), (300, int(H * 0.80))], fill=(150, 148, 140), outline=(40, 40, 40), width=2)
    for k in range(4):
        yy = int(H * 0.69) + 16 + k * 18
        d.line([(84, yy), (280 - 30 * (k % 2), yy)], fill=(50, 50, 50), width=4)
    im = P.grime(im, 0.12, seed=12)
    return ImageOps.mirror(im)


def fuse_lid():
    """Under-hood fuse / relay box lid, 0.076 x 0.146 m. Viewer canvas (from the front): left = +x."""
    base = srgb("Plastic")
    im = _img(0.076, 0.146, base)
    W, H = im.size
    d = ImageDraw.Draw(im)
    d.rectangle([(4, 4), (W - 5, H - 5)], outline=P.shade(base, 2.2), width=6)          # lid rim
    d.rectangle([(16, 16), (W - 17, H - 17)], outline=P.shade(base, 0.5), width=3)
    # moulded latch tabs at both ends
    for yy in (8, H - 22):
        d.rectangle([(W / 2 - 30, yy), (W / 2 + 30, yy + 14)], fill=P.shade(base, 2.4))
    # the fuse / relay layout label
    x0, y0, x1, y1 = 30, 60, W - 30, H - 120
    d.rectangle([(x0, y0), (x1, y1)], fill=(150, 146, 136), outline=(40, 40, 40), width=2)
    P.centred(d, W / 2, y0 + 8, "FUSE / RELAY", P.font(24), (28, 28, 28))
    gx0, gy0 = x0 + 14, y0 + 48
    cols, rows = 4, 12
    cw = (x1 - x0 - 28) / cols
    rh = (y1 - gy0 - 14) / rows
    for r in range(rows):
        for c in range(cols):
            if r in (4, 5) and c >= 2:
                continue
            cx0 = gx0 + c * cw
            cy0 = gy0 + r * rh
            d.rectangle([(cx0 + 3, cy0 + 3), (cx0 + cw - 3, cy0 + rh - 3)], outline=(40, 40, 40), width=2)
            d.text((cx0 + 8, cy0 + 4), str(r * cols + c + 1), font=P.font(14, bold=False), fill=(40, 40, 40))
    # two relay squares
    d.rectangle([(gx0 + 2 * cw + 3, gy0 + 4 * rh + 3), (gx0 + 4 * cw - 3, gy0 + 6 * rh - 3)], outline=(30, 30, 30), width=3)
    # moulded arrow / text near the front end
    P.centred(d, W / 2, H - 100, "HONDA", P.font(30), P.shade(base, 3.2), shadow=(0, 0, 0))
    im = P.grime(im, 0.10, seed=13)
    return im.rotate(180)


def tower():
    """Strut mount plate, 0.10 x 0.10 m round the tower centre: three stud nuts at the plate's corners."""
    base = srgb("BlackPaint")
    im = _img(0.10, 0.10, base)
    W, H = im.size
    d = ImageDraw.Draw(im)
    c = W / 2
    steel = srgb("Steel")
    for a in (90, 210, 330):                                        # corners: image up = +y (forward)
        x = c + 0.039 / 0.10 * W * math.cos(math.radians(a))
        y = c - 0.039 / 0.10 * H * math.sin(math.radians(a))
        d.ellipse([(x - 30, y - 30), (x + 30, y + 30)], fill=P.shade(base, 0.5))      # washer shadow
        P.bolt(d, x, y, 24, rgb=steel, rim=(30, 30, 32))
    d.ellipse([(c - 125, c - 125), (c + 125, c + 125)], outline=P.shade(base, 0.4), width=8)  # puck footprint
    return P.grime(im, 0.15, seed=14)


IMAGES = {
    "bay_sides_battery_top.png": battery_top,
    "bay_sides_battery_front.png": battery_front,
    "bay_sides_fuse_lid.png": fuse_lid,
    "bay_sides_tower.png": tower,
}
