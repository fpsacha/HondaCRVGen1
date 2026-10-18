"""Engine bay v2 decals for the "intake" group (spec/engine-bay-v2.md). System Python + Pillow.

bay_intake_plenum_top.png   the cast plenum seen from above (x -0.205..0.095, y 1.035..1.225): the raised
                            hump's ribs and slots on the +x half, the lower -x half's ribs, cast grain.
bay_intake_airbox_top.png   the air box lid from above (x 0.30..0.57, y 1.34..1.68): deep moulded ribs on
                            the outboard and inboard sections, the rear level's ribs, the maker's lettering.
bay_intake_airbox_front.png the air box's front faces (x 0.30..0.57, z 0.79..0.95): the rib ends on the lid
                            skirts, the housing's stiffeners and its seam lip.

Image left = the u axis' low end, image top = the v axis' high end (kit DECALS).
"""
from PIL import Image, ImageDraw, ImageFilter

from bay import painting
from bay.painting import shade, srgb

PPM = 4000                                                  # pixels per metre (40 px / cm)


class Map:
    """Metres <-> pixels for one decal: u axis (u0, u1) -> image x, v axis (v0, v1) -> image y (top = v1)."""

    def __init__(self, u0, u1, v0, v1, ppm=PPM):
        self.u0, self.u1, self.v0, self.v1 = u0, u1, v0, v1
        self.w = int(round((u1 - u0) * ppm))
        self.h = int(round((v1 - v0) * ppm))

    def px(self, u, v):
        return ((u - self.u0) / (self.u1 - self.u0) * self.w, (1.0 - (v - self.v0) / (self.v1 - self.v0)) * self.h)

    def rect(self, u0, v0, u1, v1):
        (a, b), (c, d) = self.px(u0, v1), self.px(u1, v0)
        return (a, b, c, d)


def rib_set(d, m, x0, x1, y0, y1, n, base, depth=1.0, width_frac=0.42, along_v=True, slot=False):
    """n raised ribs between x0..x1, running y0..y1 (metres): the crest a touch lighter, a lit edge on
    the left and a cast shadow on the right (the preview's sun and the game's light come from the front
    left), rounded ends. along_v=False runs them along u instead."""
    light = shade(base, 1.0 + 0.55 * depth)
    crest = shade(base, 1.0 + 0.22 * depth)
    dark = shade(base, 1.0 - 0.55 * depth)
    if along_v:
        step = (x1 - x0) / n
        for k in range(n):
            a = x0 + step * (k + 0.5 - width_frac / 2)
            b = a + step * width_frac
            ax, ay = m.px(a, y1)
            bx, by = m.px(b, y0)
            r = (bx - ax) / 2
            sh = max(2, int(r * 0.6))
            d.rounded_rectangle([ax + sh, ay + sh, bx + sh, by + sh], r, fill=dark)          # shadow
            d.rounded_rectangle([ax, ay, bx, by], r, fill=crest)
            d.line([(ax + 1, ay + r), (ax + 1, by - r)], fill=light, width=max(2, int(r * 0.35)))
            if slot:
                cx = (ax + bx) / 2
                d.rounded_rectangle([cx - r * 0.45, ay + r * 0.4, cx + r * 0.45, ay + r * 2.0], r * 0.4,
                                    fill=shade(base, 1.0 + 0.9 * depth))
    else:
        step = (y1 - y0) / n
        for k in range(n):
            a = y0 + step * (k + 0.5 - width_frac / 2)
            b = a + step * width_frac
            ax, ay = m.px(x0, b)
            bx, by = m.px(x1, a)
            r = (by - ay) / 2
            sh = max(2, int(r * 0.6))
            d.rounded_rectangle([ax + sh, ay + sh, bx + sh, by + sh], r, fill=dark)
            d.rounded_rectangle([ax, ay, bx, by], r, fill=crest)
            d.line([(ax + r, ay + 1), (bx - r, ay + 1)], fill=light, width=max(2, int(r * 0.35)))


def edge(d, m, x0, y0, x1, y1, base, k_light=1.25, k_dark=0.70, w=6):
    """A raised panel's outline: lit on the left and rear, shaded on the right and front."""
    a, b, c, e = m.rect(x0, y0, x1, y1)
    d.line([(a, b), (a, e)], fill=shade(base, k_light), width=w)
    d.line([(a, b), (c, b)], fill=shade(base, k_light * 0.96), width=w)
    d.line([(c, b), (c, e)], fill=shade(base, k_dark), width=w)
    d.line([(a, e), (c, e)], fill=shade(base, k_dark), width=w)


# ----------------------------------------------------------------------------- the plenum
def plenum_top():
    m = Map(-0.205, 0.095, 1.035, 1.225)
    base = srgb("AluCast")
    im = painting.ground(m.w, m.h, base, grain=7, seed=11, blur=0.8)
    d = ImageDraw.Draw(im)
    # the box's top edge rounds off at the rear and the -x / +x ends
    edge(d, m, -0.203, 1.058, 0.093, 1.204, base, 1.12, 0.82, 8)
    # the raised hump (+x half): its outline and six ribs on its rear two thirds with slots at their ends
    edge(d, m, -0.043, 1.066, 0.087, 1.138, base, 1.18, 0.72, 7)
    rib_set(d, m, -0.035, 0.081, 1.072, 1.118, 6, base, depth=0.9, slot=True)
    # the lower -x half: five ribs at the rear, the front sloping off plain
    rib_set(d, m, -0.190, -0.060, 1.068, 1.124, 6, base, depth=0.8, slot=True)
    # the front slope down to the skirt, a little darker (it faces away from the light)
    a, b, c, e = m.rect(-0.203, 1.140, 0.093, 1.205)
    shadow = Image.new("L", im.size, 0)
    ImageDraw.Draw(shadow).rectangle([a, b, c, e], fill=40)
    im = Image.composite(Image.new("RGB", im.size, shade(base, 0.86)), im, shadow.filter(ImageFilter.GaussianBlur(10)))
    d = ImageDraw.Draw(im)
    # four cover bolts on the top's corners
    for x, y in ((-0.192, 1.066), (-0.192, 1.182), (0.082, 1.182)):
        cx, cy = m.px(x, y)
        painting.bolt(d, cx, cy, 16, rgb=shade(base, 1.18), rim=shade(base, 0.55))
    return painting.grime(im, strength=0.10, seed=5, scale=40)


# ----------------------------------------------------------------------------- the air box
def airbox_top():
    m = Map(0.300, 0.570, 1.340, 1.680)
    base = srgb("Plastic")
    im = painting.ground(m.w, m.h, base, grain=3, seed=21)
    d = ImageDraw.Draw(im)
    # outboard section: seven deep ribs front to back
    edge(d, m, 0.453, 1.349, 0.562, 1.671, base, 1.9, 0.5, 6)
    rib_set(d, m, 0.460, 0.558, 1.366, 1.652, 6, base, depth=1.7, width_frac=0.56)
    # inboard raised block: seven ribs, the maker's name moulded across its rear edge
    edge(d, m, 0.313, 1.453, 0.445, 1.671, base, 1.9, 0.5, 6)
    rib_set(d, m, 0.320, 0.440, 1.490, 1.654, 7, base, depth=1.7, width_frac=0.56)
    fnt = painting.font(26)
    x, y = m.px(0.318, 1.476)
    painting.cast_text(d, (x, y), "TOYO ROKI MFG. CO.,LTD.", fnt, shade(base, 1.9), shade(base, 0.5), offset=2)
    # the low rear level around the boss: short ribs either side of it
    edge(d, m, 0.313, 1.349, 0.449, 1.453, base, 1.6, 0.55, 5)
    rib_set(d, m, 0.316, 0.322, 1.356, 1.446, 1, base, depth=1.0)
    rib_set(d, m, 0.436, 0.447, 1.356, 1.446, 1, base, depth=1.0)
    rib_set(d, m, 0.330, 0.430, 1.442, 1.450, 1, base, depth=0.8, along_v=False)
    # the groove between the sections
    a, b, c, e = m.rect(0.446, 1.349, 0.453, 1.671)
    d.rectangle([a, b, c, e], fill=shade(base, 0.45))
    return painting.grime(im, strength=0.08, seed=9, scale=40)


def airbox_front():
    m = Map(0.300, 0.570, 0.790, 0.950)
    base = srgb("Plastic")
    im = painting.ground(m.w, m.h, base, grain=3, seed=31)
    d = ImageDraw.Draw(im)
    # lid skirts: the ribs' ends, vertical, above the seam
    rib_set(d, m, 0.460, 0.558, 0.880, 0.900, 6, base, depth=1.5, width_frac=0.56)
    rib_set(d, m, 0.320, 0.440, 0.880, 0.934, 7, base, depth=1.5, width_frac=0.56)
    # housing: a moulded lip under the seam, stiffeners down the face, the bottom edge
    a, b, c, e = m.rect(0.300, 0.856, 0.570, 0.866)
    d.rectangle([a, b, c, e], fill=shade(base, 1.35))
    d.line([(a, e), (c, e)], fill=shade(base, 0.45), width=4)
    rib_set(d, m, 0.312, 0.560, 0.808, 0.852, 9, base, depth=1.1, width_frac=0.30)
    a, b, c, e = m.rect(0.300, 0.800, 0.570, 0.806)
    d.rectangle([a, b, c, e], fill=shade(base, 0.6))
    return painting.grime(im, strength=0.08, seed=13, scale=30)


IMAGES = {
    "bay_intake_plenum_top.png": plenum_top,
    "bay_intake_airbox_top.png": airbox_top,
    "bay_intake_airbox_front.png": airbox_front,
}
