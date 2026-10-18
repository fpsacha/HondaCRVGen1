r"""
Paint the CR-V texture sheets from the same landmark numbers the mesh is built from.

    python scripts/paint_textures.py

Writes into the mod's textures folder, at tex_layout.SIZE square:
    Vehicles_HondaCRVGen1_Shell.png  (+ one _Shell_<colour> per skin)
    Vehicles_HondaCRVGen1_Mask.png   white where the skin colour is applied
    Vehicles_HondaCRVGen1_Lights.png emissive lamps
    Vehicles_HondaCRVGen1_Rust.png
    Vehicles_HondaCRVGen1_Wheel.png  rim face (polar) and tread strip, tex_layout.WHEEL_SIZE

Everything is drawn in model metres through tex_layout's projections, so a door handle painted at
y -0.05, z 0.955 lands on the door the mesh has there. Painted at SS times the sheet size and
downsampled, so edges are anti-aliased, and with the shading a hand-painted sheet carries: soft
shadow along every shut line and under every strip, darkening into the arches and the sill,
a light catch on the shoulder crease, gradients on glass and lenses. This is the KI5 recipe -
the mesh is low-poly, the texture does the work. Hand painting goes on top of these files.

Model space: metres, +Y front, +Z up, +X vehicle right, origin at ground level between the axles.
"""
import math
import os
import random
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageChops

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tex_layout as L                                    # noqa: E402

ROOT = os.environ.get("CRV_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEX_DIR = os.path.join(ROOT, "mod", "Contents", "mods", "HondaCRVGen1",
                       "common", "media", "textures", "Vehicles")
NAME = "Vehicles_HondaCRVGen1"

SS = 2                                # supersample factor while painting
K = L.PXM * SS                        # pixels per metre while painting

# The skins are the RD1's North American factory paints (spec/paint-colours.md, chosen 2026-10-13):
# (file suffix, Honda code, name, finish, median sRGB, top sRGB). The median is the colour compose levels to
# KI5's vertical paint (paint_pass LEVEL_BASE / LEVEL_GAIN); the top is what a metallic or pearl lifts toward
# on up-facing panels instead of plain white (paint_pass.FINISH_LIFT): the chip photos' brighter value, so
# the greens and blues turn greener / bluer on the hood and roof and the silver and gold brighten. Nighthawk
# Black's chip shows no hue (#3E3D3F); its top is a chosen dark blue for the blue pearl the seller copy
# describes. Solid paints (Taffeta White, Milano Red) keep the plain lift (top None). Nighthawk's side colour
# is its swatch median (#18181E) with the blue taken down to (24, 24, 27): levelled to KI5's black (x1.43) the
# swatch's blue cast read as navy in pzview (2026-10-13), and the shade chip (#100F11) is neutral; the blue
# lives in its top. Its top hue is a soft one for the same reason (from (52, 60, 88) the tops shipped
# (81, 88, 123) and read blue-grey; now belt (36, 36, 41), tops (86, 89, 104)).
# The suffixes are the files the vehicle script already lists (gen_scripts.SKINS), so no texture is renamed:
# the old beige default (there is no beige RD1) became Electron Blue Pearl, the eighth paint.
PAINTS = [
    ("",        "B-95P",   "Electron Blue Pearl",      "pearl",    (49, 51, 121),  (77, 94, 143)),
    ("_white",  "NH-578",  "Taffeta White",            "solid",    (235, 237, 229), None),
    ("_black",  "B-92P",   "Nighthawk Black Pearl",    "pearl",    (24, 24, 27),   (60, 64, 76)),
    ("_red",    "R-81",    "Milano Red",               "solid",    (153, 25, 39),  None),
    ("_blue",   "B-84P",   "Supermarine Blue Pearl",   "pearl",    (27, 58, 95),   (56, 74, 97)),
    ("_green",  "G-95P",   "Clover Green Pearl",       "pearl",    (3, 58, 33),    (54, 83, 79)),
    ("_silver", "NH-552M", "Sebring Silver Metallic",  "metallic", (167, 167, 166), (202, 204, 204)),
    ("_gold",   "YR-524M", "Naples Gold Metallic",     "metallic", (182, 172, 156), (215, 208, 196)),
]
SKINS = {p[0]: p[4] for p in PAINTS}
# median sRGB -> (finish, top sRGB): paint_pass.skin() looks a skin's character up by the colour compose hands it
TOPS = {p[4]: (p[3], p[5]) for p in PAINTS}
PAINT = SKINS[""]
CLAD = (64, 64, 66)
CLAD_LT = (84, 84, 86)
CLAD_DK = (42, 42, 44)
BLACK = (16, 16, 16)
SEAL = (20, 20, 22)
GLASS = (44, 56, 70)
GLASS_HI = (92, 108, 126)
GLASS_LO = (30, 38, 48)
CHROME = (222, 224, 228)
CHROME_DK = (150, 152, 156)
LAMP = (226, 226, 210)
LAMP_DK = (150, 150, 140)
LAMP_HI = (250, 250, 240)
AMBER = (216, 122, 22)
AMBER_DK = (168, 84, 12)
RED = (176, 28, 24)
RED_DK = (122, 16, 14)
CLEAR = (208, 212, 216)
LINE = (52, 52, 56)
WHITE = (240, 240, 240)

Y_AXF, Y_AXR = 1.31, -1.31
ARCH = {Y_AXF: 0.42, Y_AXR: 0.40}
ARCH_Z, FLARE = 0.334, 0.065


def _font(px):
    for name in ("arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, max(8, int(px)))
        except OSError:
            continue
    return ImageFont.load_default()


def shade(colour, f):
    """Lighten (f > 1) or darken (f < 1) a colour."""
    return tuple(max(0, min(255, int(round(c * f)))) for c in colour)


class Sheet:
    """Shell, mask and lights painted together so they cannot drift apart; shading layers are
    accumulated and applied once at the end."""

    def __init__(self, paint, size=None):
        self.paint = paint
        S = (size or L.SIZE) * SS
        self.S = S
        self.shell = Image.new("RGB", (S, S), CLAD_DK)
        self.mask = Image.new("L", (S, S), 0)
        self.lights = Image.new("RGB", (S, S), (0, 0, 0))
        self.ao = Image.new("L", (S, S), 0)                 # darkening, blurred at the end
        self.hi = Image.new("L", (S, S), 0)                 # lightening, blurred at the end
        self.d = ImageDraw.Draw(self.shell)
        self.dm = ImageDraw.Draw(self.mask)
        self.dl = ImageDraw.Draw(self.lights)
        self.da = ImageDraw.Draw(self.ao)
        self.dh = ImageDraw.Draw(self.hi)

    # -- coordinate helpers ------------------------------------------------------------
    @staticmethod
    def P(fn, *a):
        x, y = fn(*a)
        return (x * SS, y * SS)

    def _box(self, fn, a, b):
        p0, p1 = self.P(fn, *a), self.P(fn, *b)
        return (min(p0[0], p1[0]), min(p0[1], p1[1]), max(p0[0], p1[0]), max(p0[1], p1[1]))

    # -- primitives in model space -----------------------------------------------------
    def rect(self, fn, a, b, colour, painted=False, light=None, outline=None, width=1):
        box = self._box(fn, a, b)
        if colour is not None:
            self.d.rectangle(box, fill=colour, outline=outline, width=width)
            self.dm.rectangle(box, fill=255 if painted else 0)
        elif outline is not None:
            self.d.rectangle(box, outline=outline, width=width)
        if light:
            self.dl.rectangle(box, fill=light)
        return box

    def poly(self, fn, pts, colour, painted=False, light=None, outline=None, width=1):
        px = [self.P(fn, *p) for p in pts]
        if colour is not None:
            self.d.polygon(px, fill=colour, outline=outline, width=width)
            self.dm.polygon(px, fill=255 if painted else 0)
        elif outline is not None:
            self.d.polygon(px, outline=outline, width=width)
        if light:
            self.dl.polygon(px, fill=light)
        return px

    def line(self, fn, a, b, colour, w=0.006):
        self.d.line([self.P(fn, *a), self.P(fn, *b)], fill=colour, width=max(1, int(w * K)))

    def ellipse(self, fn, c, rx, ry, colour, painted=False, light=None, outline=None, width=1):
        cx, cy = self.P(fn, *c)
        box = (cx - rx * K, cy - ry * K, cx + rx * K, cy + ry * K)
        self.d.ellipse(box, fill=colour, outline=outline, width=width)
        if colour is not None:
            self.dm.ellipse(box, fill=255 if painted else 0)
        if light:
            self.dl.ellipse(box, fill=light)
        return box

    def vgrad(self, fn, a, b, c_top, c_bot, painted=False):
        """Fill a model-space rectangle with a vertical gradient (top colour at the higher z)."""
        x0, y0, x1, y1 = [int(round(v)) for v in self._box(fn, a, b)]
        if x1 <= x0 or y1 <= y0:
            return
        g = Image.linear_gradient("L").resize((x1 - x0, y1 - y0))
        top = Image.new("RGB", (x1 - x0, y1 - y0), c_top)
        bot = Image.new("RGB", (x1 - x0, y1 - y0), c_bot)
        self.shell.paste(Image.composite(bot, top, g), (x0, y0))
        self.dm.rectangle((x0, y0, x1, y1), fill=255 if painted else 0)

    def dark(self, fn, a, b, strength=160):
        """Soft darkening over a model-space rectangle (blurred at finish)."""
        self.da.rectangle(self._box(fn, a, b), fill=strength)

    def light(self, fn, a, b, strength=120):
        self.dh.rectangle(self._box(fn, a, b), fill=strength)

    def shut(self, fn, a, b, w=0.008):
        """A shut line: dark groove with a soft shadow and a light catch beside it."""
        self.line(fn, a, b, LINE, w)
        self.da.line([self.P(fn, *a), self.P(fn, *b)], fill=140, width=max(1, int(0.03 * K)))
        (ay, az), (by, bz) = a, b
        self.dh.line([self.P(fn, ay + 0.010, az), self.P(fn, by + 0.010, bz)], fill=55,
                     width=max(1, int(0.005 * K)))

    def annulus(self, fn, c, r_in, r_out, colour, z_max=None, clip=None):
        cx, cy = self.P(fn, *c)
        layer = Image.new("L", (self.S, self.S), 0)
        dl = ImageDraw.Draw(layer)
        dl.ellipse((cx - r_out * K, cy - r_out * K, cx + r_out * K, cy + r_out * K), fill=255)
        dl.ellipse((cx - r_in * K, cy - r_in * K, cx + r_in * K, cy + r_in * K), fill=0)
        if z_max is not None:
            dl.rectangle((0, 0, self.S, self.P(fn, c[0], z_max)[1]), fill=0)
        if clip is not None:                                # keep the ring inside its own strip
            keep = Image.new("L", (self.S, self.S), 0)
            ImageDraw.Draw(keep).rectangle([v * SS for v in clip], fill=255)
            layer = ImageChops.multiply(layer, keep)
        self.shell.paste(Image.new("RGB", (self.S, self.S), colour), (0, 0), layer)
        self.mask.paste(0, (0, 0), layer)
        # inner lip of the opening reads darker, outer edge throws a shadow on the paint
        lip = Image.new("L", (self.S, self.S), 0)
        dl2 = ImageDraw.Draw(lip)
        ri = r_in + 0.012
        dl2.ellipse((cx - ri * K, cy - ri * K, cx + ri * K, cy + ri * K), fill=255)
        dl2.ellipse((cx - r_in * K, cy - r_in * K, cx + r_in * K, cy + r_in * K), fill=0)
        if z_max is not None:
            dl2.rectangle((0, 0, self.S, self.P(fn, c[0], z_max)[1]), fill=0)
        self.shell.paste(Image.new("RGB", (self.S, self.S), CLAD_DK), (0, 0), lip)
        ro = r_out + 0.03
        ring = Image.new("L", (self.S, self.S), 0)
        dr = ImageDraw.Draw(ring)
        dr.ellipse((cx - ro * K, cy - ro * K, cx + ro * K, cy + ro * K), fill=80)
        dr.ellipse((cx - r_out * K, cy - r_out * K, cx + r_out * K, cy + r_out * K), fill=0)
        if clip is not None:
            ring = ImageChops.multiply(ring, keep)
        self.ao = ImageChops.lighter(self.ao, ring)
        self.da = ImageDraw.Draw(self.ao)

    def glass(self, fn, pts, seal=0.022, hi_dir=1):
        """Black seal, dark glass with a top-to-bottom gradient and a diagonal reflection."""
        px = [self.P(fn, *p) for p in pts]
        cx = sum(p[0] for p in px) / len(px)
        cy = sum(p[1] for p in px) / len(px)
        xs = [p[0] for p in px]
        ys = [p[1] for p in px]
        w, h = max(xs) - min(xs), max(ys) - min(ys)
        fx, fy = 1 + 2 * seal * K / max(w, 1), 1 + 2 * seal * K / max(h, 1)
        outer = [(cx + (p[0] - cx) * fx, cy + (p[1] - cy) * fy) for p in px]
        self.d.polygon(outer, fill=SEAL)
        self.dm.polygon(outer, fill=0)
        x0, y0, x1, y1 = int(min(xs)), int(min(ys)), int(max(xs)) + 1, int(max(ys)) + 1
        g = Image.linear_gradient("L").resize((x1 - x0, y1 - y0))
        body = Image.composite(Image.new("RGB", (x1 - x0, y1 - y0), GLASS_LO),
                               Image.new("RGB", (x1 - x0, y1 - y0), GLASS), g)
        clip = Image.new("L", (x1 - x0, y1 - y0), 0)
        ImageDraw.Draw(clip).polygon([(p[0] - x0, p[1] - y0) for p in px], fill=255)
        self.shell.paste(body, (x0, y0), clip)
        hi = Image.new("RGBA", (x1 - x0, y1 - y0), (0, 0, 0, 0))
        dh = ImageDraw.Draw(hi)
        if hi_dir > 0:
            band = [(w * 0.10, h), (w * 0.48, 0), (w * 0.66, 0), (w * 0.28, h)]
        else:
            band = [(w * 0.34, h), (w * 0.72, 0), (w * 0.90, 0), (w * 0.52, h)]
        dh.polygon(band, fill=GLASS_HI + (80,))
        dh.rectangle((w * 0.02, h * 0.02, w * 0.98, h * 0.10), fill=GLASS_HI + (60,))
        hi = hi.filter(ImageFilter.GaussianBlur(2 * SS))
        hi.putalpha(ImageChops.multiply(hi.getchannel("A"), clip))
        self.shell.paste(hi, (x0, y0), hi)
        inner = [(cx + (p[0] - cx) * 0.985, cy + (p[1] - cy) * 0.985) for p in px]
        self.d.line(inner + [inner[0]], fill=shade(GLASS_HI, 0.9), width=max(1, int(0.004 * K)))

    def lamp(self, fn, a, b, colour, dark, light, ribs=0.02, vertical=True):
        """Lens with a darker inner field and fine ribs."""
        box = self.rect(fn, a, b, colour, light=light)
        x0, y0, x1, y1 = box
        inset = 0.01 * K
        self.d.rectangle((x0 + inset, y0 + inset, x1 - inset, y1 - inset), fill=shade(colour, 0.92))
        step = max(2, int(ribs * K))
        if vertical:
            for x in range(int(x0 + step), int(x1), step):
                self.d.line([(x, y0 + inset), (x, y1 - inset)], fill=dark, width=max(1, SS))
        else:
            for y in range(int(y0 + step), int(y1), step):
                self.d.line([(x0 + inset, y), (x1 - inset, y)], fill=dark, width=max(1, SS))
        self.d.rectangle(box, outline=SEAL, width=max(1, int(0.006 * K)))
        return box

    def text(self, fn, at, s, h_m, colour):
        f = _font(h_m * K)
        x, y = self.P(fn, *at)
        self.d.text((x, y), s, font=f, fill=colour, anchor="mm")

    # -- finish -----------------------------------------------------------------------
    def finish(self, out_size):
        r = 0.012 * K
        ao = self.ao.filter(ImageFilter.GaussianBlur(r))
        hi = self.hi.filter(ImageFilter.GaussianBlur(r * 0.6))
        dark = Image.new("RGB", (self.S, self.S), (0, 0, 0))
        light = Image.new("RGB", (self.S, self.S), (255, 255, 255))
        shell = Image.composite(dark, self.shell, ao.point(lambda v: int(v * 0.34)))
        shell = Image.composite(light, shell, hi.point(lambda v: int(v * 0.22)))
        # fine grain, the way a painted sheet reads
        noise = Image.effect_noise((self.S, self.S), 8).point(lambda v: 248 + (v - 128) // 8)
        shell = ImageChops.multiply(shell, Image.merge("RGB", (noise, noise, noise)).point(lambda v: min(255, int(v * 255 / 248))))
        self.shell = shell.resize((out_size, out_size), Image.LANCZOS)
        self.mask = self.mask.resize((out_size, out_size), Image.LANCZOS).convert("RGB")
        self.lights = self.lights.resize((out_size, out_size), Image.LANCZOS)
        return self


# ================================================================== regions
def paint_side(s):
    P = s.paint
    f = L.side_px
    s.vgrad(f, (L.Y_MAX, L.Z_MAX), (L.Y_MIN, 1.10), shade(P, 1.02), P, painted=True)
    s.vgrad(f, (L.Y_MAX, 1.10), (L.Y_MIN, 0.52), shade(P, 1.03), shade(P, 0.95), painted=True)
    s.rect(f, (L.Y_MAX, 0.52), (L.Y_MIN, L.Z_MIN), CLAD_DK)     # rocker underside and floor pan
    # black sill garnish along the rocker between the flare feet, bumpers at the ends
    s.rect(f, (0.87, 0.52), (-0.90, 0.42), BLACK)
    s.light(f, (0.87, 0.525), (-0.90, 0.515), 70)
    s.dark(f, (0.87, 0.60), (-0.90, 0.52), 120)
    # bumpers seen from the side: same bands as their end faces, so the corners carry no seam
    s.vgrad(f, (L.Y_MAX, 0.72), (1.75, 0.40), CLAD_LT, CLAD)
    s.rect(f, (L.Y_MAX, 0.40), (1.75, L.Z_MIN), CLAD_DK)
    s.line(f, (L.Y_MAX, 0.615), (1.75, 0.615), CLAD_DK, 0.008)         # front step
    s.line(f, (L.Y_MAX, 0.622), (1.75, 0.622), shade(CLAD_LT, 1.12), 0.003)
    s.light(f, (L.Y_MAX, 0.72), (1.75, 0.70), 80)
    s.dark(f, (L.Y_MAX, 0.74), (1.75, 0.72), 120)
    s.vgrad(f, (-1.77, 0.73), (L.Y_MIN, 0.40), CLAD_LT, CLAD)
    s.rect(f, (-1.77, 0.40), (L.Y_MIN, L.Z_MIN), CLAD_DK)
    s.line(f, (-1.77, 0.61), (L.Y_MIN, 0.61), CLAD_DK, 0.012)          # rear groove
    s.line(f, (-1.77, 0.632), (L.Y_MIN, 0.632), shade(CLAD_LT, 1.15), 0.003)
    s.light(f, (-1.77, 0.73), (L.Y_MIN, 0.71), 70)
    s.rect(f, (-2.13, 0.58), (-2.21, 0.50), RED, light=(255, 40, 30))   # corner reflector
    s.rect(f, (-2.135, 0.575), (-2.205, 0.505), None, outline=RED_DK, width=max(1, int(0.004 * K)))
    for yc, r in ARCH.items():
        s.annulus(f, (yc, ARCH_Z), r, r + FLARE, CLAD, z_max=0.95, clip=L.SIDE)
    # rub strips with ridges and a shadow under them
    for y0, y1 in ((0.78, -0.27), (-0.29, -0.88)):
        s.vgrad(f, (y0, 0.72), (y1, 0.62), CLAD_LT, CLAD_DK)
        for zz in (0.645, 0.67, 0.695):
            s.line(f, (y0, zz), (y1, zz), CLAD_DK, 0.004)
            s.line(f, (y0, zz + 0.006), (y1, zz + 0.006), shade(CLAD_LT, 1.12), 0.003)
        s.dark(f, (y0, 0.62), (y1, 0.595), 130)
    for yy in (0.80, -0.28, -1.27):
        s.shut(f, (yy, 1.10), (yy, 0.52))
    # belt: a light catch on the shoulder, a shadow under the step; drip rail
    s.light(f, (0.62, 1.105), (-2.05, 1.09), 110)
    s.dark(f, (0.62, 1.15), (-2.05, 1.11), 120)
    s.line(f, (0.42, 1.612), (-1.88, 1.612), LINE, 0.008)
    s.light(f, (0.42, 1.625), (-1.88, 1.614), 70)
    # the flanks catch light along the door bulge and fall into shadow above the sill
    s.light(f, (2.00, 1.03), (-1.90, 0.97), 40)
    s.dark(f, (1.90, 0.60), (-1.80, 0.53), 60)
    # door handles: recessed cup, black pull lever with a highlight
    for yc in (-0.05, -1.05):
        s.rect(f, (yc + 0.115, 0.99), (yc - 0.115, 0.92), shade(P, 0.84), painted=True)
        s.dark(f, (yc + 0.115, 0.99), (yc - 0.115, 0.92), 90)
        s.rect(f, (yc + 0.095, 0.978), (yc - 0.095, 0.942), BLACK)
        s.rect(f, (yc + 0.09, 0.974), (yc - 0.09, 0.948), (40, 40, 42))
        s.line(f, (yc + 0.085, 0.968), (yc - 0.085, 0.968), (96, 96, 98), 0.004)
    # fuel flap; US-spec amber side marker on the bumper corner (no fender repeater)
    s.rect(f, (-1.46, 1.00), (-1.56, 0.90), None, outline=LINE, width=max(1, int(0.004 * K)))
    s.dark(f, (-1.46, 0.90), (-1.56, 0.88), 60)
    s.rect(f, (2.00, 0.67), (1.91, 0.61), AMBER, light=(255, 150, 30))
    s.rect(f, (1.995, 0.665), (1.915, 0.615), None, outline=AMBER_DK, width=max(1, int(0.004 * K)))
    # pillars and the glass
    s.rect(f, (L.B_PILLAR[1], 1.61), (L.B_PILLAR[0], 1.10), BLACK)
    s.line(f, (L.B_PILLAR[1] - 0.012, 1.60), (L.B_PILLAR[1] - 0.012, 1.11), shade(BLACK, 2.2), 0.005)
    for pane in (L.PANE_FRONT, L.PANE_REAR, L.PANE_QUARTER):
        s.glass(f, [(y, z) for y, z, _ in pane], hi_dir=1)
    s.poly(f, list(L.SAIL), BLACK)

    # the tail lamps are on the rear sheet: the D-pillar chamfers they sit on project there
    # headlamp wrapping back along the fender: amber indicator at the rear, a short clear lens
    # with its reflector ahead of it, then the corner
    s.rect(f, (2.20, 0.90), (1.72, 0.72), LAMP, light=(255, 250, 220))
    s.vgrad(f, (2.20, 0.895), (1.835, 0.725), shade(LAMP, 1.0), shade(LAMP, 0.84))
    s.ellipse(f, (1.92, 0.81), 0.075, 0.07, LAMP_DK, light=(255, 250, 220))
    s.ellipse(f, (1.92, 0.81), 0.055, 0.052, shade(LAMP, 0.96))
    s.ellipse(f, (1.92, 0.81), 0.028, 0.026, LAMP_HI)
    s.rect(f, (1.83, 0.895), (1.72, 0.725), AMBER, light=(255, 150, 30))
    for z in (0.75, 0.78, 0.81, 0.84, 0.87):
        s.line(f, (1.825, z), (1.725, z), AMBER_DK, 0.004)
    s.line(f, (1.83, 0.895), (1.83, 0.725), SEAL, 0.005)
    s.rect(f, (2.20, 0.905), (1.715, 0.715), None, outline=SEAL, width=max(1, int(0.006 * K)))
    # hood / fender crease seen from the side
    s.line(f, (2.00, 1.00), (0.82, 1.13), LINE, 0.004)
    s.light(f, (2.00, 1.01), (0.82, 1.14), 60)


def paint_top(s):
    P = s.paint
    f = L.top_px
    s.rect(f, (L.Y_MAX, L.X_MAX), (L.Y_MIN, -L.X_MAX), P, painted=True)
    # hood: crown light, edges darker, outline, centre crease
    hb, hbs = L.hood_back(0.0), L.hood_back(0.78)          # hood rear edge: centre, sides
    s.vgrad(f, (1.98, 0.74), (hbs, 0.0), shade(P, 0.97), shade(P, 1.06), painted=True)
    s.vgrad(f, (1.98, 0.0), (hbs, -0.74), shade(P, 1.06), shade(P, 0.97), painted=True)
    ys_ = [hbs + (1.98 - hbs) * i / 30 for i in range(31)]
    for y0, y1 in zip(ys_, ys_[1:]):                      # side seams, rounding in at the front
        for sgn in (1, -1):
            s.shut(f, (y0, sgn * L.hood_side(y0)), (y1, sgn * L.hood_side(y1)))
    xs = [-0.74 + 1.48 * i / 20 for i in range(21)]
    for x0, x1 in zip(xs, xs[1:]):                        # the hood's curved rear seam
        s.shut(f, (L.hood_back(x0), x0), (L.hood_back(x1), x1))
    s.light(f, (1.96, 0.012), (hb + 0.03, -0.012), 60)
    s.vgrad(f, (L.Y_MAX, L.X_MAX), (2.02, -L.X_MAX), CLAD_LT, CLAD)
    # cowl grille between the hood's rear edge and the windscreen's base, both curved in plan
    s.poly(f, [(L.hood_back(x) - 0.006, x) for x in xs] + [(L.ws_base(x) - 0.004, x) for x in reversed(xs)], BLACK)
    for x in (-0.60, -0.36, -0.12, 0.12, 0.36, 0.60):     # grille slots
        s.line(f, (L.hood_back(x) - 0.016, x), (L.ws_base(x) + 0.008, x), (36, 36, 38), 0.012)
    s.glass(f, [(L.ws_base(x), x) for x in reversed(xs[1:-1])] + [(L.Y_WS_TOP, -0.60), (L.Y_WS_TOP, 0.60)], hi_dir=1)
    for x0 in (-0.48, 0.08):
        s.line(f, (0.90, x0), (0.66, x0 + 0.44), BLACK, 0.014)
        s.line(f, (0.88, x0 + 0.04), (0.68, x0 + 0.46), CLAD_LT, 0.004)
    # roof: light centre, drip rails, roof rails with feet
    rf = L.Y_WS_TOP - 0.02
    s.vgrad(f, (rf, 0.62), (-1.89, 0.0), shade(P, 1.0), shade(P, 1.04), painted=True)
    s.vgrad(f, (rf, 0.0), (-1.89, -0.62), shade(P, 1.04), shade(P, 1.0), painted=True)
    s.shut(f, (rf, 0.62), (-1.89, 0.62), w=0.006)
    s.shut(f, (rf, -0.62), (-1.89, -0.62), w=0.006)
    for x in (0.47, -0.47):
        s.rect(f, (0.20, x + 0.035), (-1.70, x - 0.035), BLACK)
        s.line(f, (0.20, x + 0.02), (-1.70, x + 0.02), shade(BLACK, 3.0), 0.004)
        s.dark(f, (0.24, x + 0.07), (-1.74, x - 0.07), 90)
        for yy in (0.10, -0.75, -1.60):
            s.rect(f, (yy + 0.06, x + 0.04), (yy - 0.06, x - 0.04), CLAD_DK)
    s.shut(f, (-1.89, 0.62), (-1.89, -0.62))
    s.rect(f, (-1.90, 0.57), (-2.11, -0.57), GLASS)       # only up-facing slivers land here
    s.light(f, (-2.06, 0.80), (-2.12, -0.80), 60)          # the ledge under the lamps, gate top


def paint_front(s):
    P = s.paint
    f = L.front_px
    s.vgrad(f, (L.X_MAX, L.Z_MAX), (-L.X_MAX, L.Z_MIN), shade(P, 1.03), shade(P, 0.94), painted=True)
    # bumper (1999-2001): smooth upper face with two tow slots, a step, the wide lower opening
    # with four upright bars, a lip below; no fog lamps, no plate
    s.vgrad(f, (L.X_MAX, 0.72), (-L.X_MAX, 0.40), CLAD_LT, CLAD)
    s.rect(f, (L.X_MAX, 0.40), (-L.X_MAX, L.Z_MIN), CLAD_DK)
    s.light(f, (L.X_MAX, 0.72), (-L.X_MAX, 0.70), 80)
    s.dark(f, (L.X_MAX, 0.74), (-L.X_MAX, 0.72), 120)
    s.line(f, (L.X_MAX, 0.615), (-L.X_MAX, 0.615), CLAD_DK, 0.008)
    s.line(f, (L.X_MAX, 0.622), (-L.X_MAX, 0.622), shade(CLAD_LT, 1.12), 0.003)
    for sgn in (1, -1):
        s.rect(f, (sgn * 0.56, 0.68), (sgn * 0.42, 0.65), CLAD_DK)
        s.dark(f, (sgn * 0.56, 0.70), (sgn * 0.42, 0.65), 90)
    s.rect(f, (0.62, 0.585), (-0.62, 0.40), BLACK)
    s.dark(f, (0.64, 0.60), (-0.64, 0.585), 120)
    for x in (-0.39, -0.13, 0.13, 0.39):
        s.rect(f, (x + 0.028, 0.585), (x - 0.028, 0.40), CLAD)
        s.line(f, (x - 0.02, 0.58), (x - 0.02, 0.405), shade(CLAD_LT, 1.1), 0.004)
        s.line(f, (x + 0.024, 0.58), (x + 0.024, 0.405), CLAD_DK, 0.004)
    s.rect(f, (0.62, 0.42), (-0.62, 0.40), CLAD)
    # headlamps: clear lens over a big reflector bowl, amber indicator at the outer end wrapping
    # the corner, rounded outer top corner under the brow
    for sgn in (1, -1):
        s.poly(f, [(sgn * 0.33, 0.72), (sgn * 0.33, 0.90), (sgn * 0.70, 0.90), (sgn * 0.75, 0.87),
                   (sgn * 0.76, 0.80), (sgn * 0.76, 0.72)], LAMP, light=(255, 250, 220))
        s.vgrad(f, (sgn * 0.34, 0.895), (sgn * 0.655, 0.725), shade(LAMP, 1.02), shade(LAMP, 0.86))
        for x in (0.36, 0.385, 0.41):                     # flutes at the inner end
            s.line(f, (sgn * x, 0.89), (sgn * x, 0.73), LAMP_DK, 0.004)
        s.ellipse(f, (sgn * 0.52, 0.81), 0.135, 0.082, LAMP_DK, light=(255, 250, 220))
        s.ellipse(f, (sgn * 0.52, 0.81), 0.105, 0.064, shade(LAMP, 0.96))
        s.ellipse(f, (sgn * 0.52, 0.81), 0.06, 0.04, LAMP_HI)
        s.ellipse(f, (sgn * 0.555, 0.835), 0.016, 0.012, WHITE)
        s.poly(f, [(sgn * 0.66, 0.725), (sgn * 0.66, 0.895), (sgn * 0.70, 0.895), (sgn * 0.745, 0.865),
                   (sgn * 0.755, 0.80), (sgn * 0.755, 0.725)], AMBER, light=(255, 150, 30))
        for x in (0.675, 0.695, 0.715, 0.735):
            s.line(f, (sgn * x, 0.885), (sgn * x, 0.73), AMBER_DK, 0.004)
        s.line(f, (sgn * 0.66, 0.895), (sgn * 0.66, 0.725), SEAL, 0.005)
        s.poly(f, [(sgn * 0.33, 0.72), (sgn * 0.33, 0.90), (sgn * 0.70, 0.90), (sgn * 0.75, 0.87),
                   (sgn * 0.76, 0.80), (sgn * 0.76, 0.72)], None, outline=SEAL, width=max(1, int(0.006 * K)))
    s.dark(f, (0.78, 0.92), (-0.78, 0.90), 110)
    # grille: black slot between the lamps, body-colour surround and two slats, chrome H
    s.rect(f, (0.32, 0.91), (-0.32, 0.75), shade(P, 0.92), painted=True)
    s.rect(f, (0.31, 0.90), (-0.31, 0.76), BLACK)
    for zz in (0.805, 0.86):
        s.rect(f, (0.30, zz + 0.011), (-0.30, zz - 0.011), P, painted=True)
        s.line(f, (0.30, zz + 0.007), (-0.30, zz + 0.007), shade(P, 1.12), 0.003)
        s.line(f, (0.30, zz - 0.009), (-0.30, zz - 0.009), shade(P, 0.75), 0.003)
    s.rect(f, (0.055, 0.895), (-0.055, 0.765), CHROME)
    s.rect(f, (0.042, 0.882), (-0.042, 0.778), BLACK)
    s.line(f, (0.03, 0.83), (-0.03, 0.83), CHROME, 0.014)
    s.line(f, (0.028, 0.875), (0.028, 0.785), CHROME, 0.012)
    s.line(f, (-0.028, 0.875), (-0.028, 0.785), CHROME, 0.012)
    s.rect(f, (0.78, 0.75), (-0.78, 0.72), shade(P, 1.0), painted=True)   # panel under lamps and grille
    s.shut(f, (0.58, 0.935), (-0.58, 0.935))


def paint_rear(s):
    P = s.paint
    f = L.rear_px
    s.vgrad(f, (-L.X_MAX, L.Z_MAX), (L.X_MAX, L.Z_MIN), shade(P, 1.03), shade(P, 0.94), painted=True)
    # bumper: lower lip, lower face, groove, upper face, top edge; corner reflectors
    s.vgrad(f, (-L.X_MAX, 0.73), (L.X_MAX, 0.40), CLAD_LT, CLAD)
    s.rect(f, (-L.X_MAX, 0.40), (L.X_MAX, L.Z_MIN), CLAD_DK)
    s.line(f, (-L.X_MAX, 0.61), (L.X_MAX, 0.61), CLAD_DK, 0.012)
    s.line(f, (-L.X_MAX, 0.632), (L.X_MAX, 0.632), shade(CLAD_LT, 1.15), 0.003)
    s.light(f, (-L.X_MAX, 0.73), (L.X_MAX, 0.71), 80)
    s.dark(f, (-L.X_MAX, 0.76), (L.X_MAX, 0.73), 110)
    s.dark(f, (-L.X_MAX, 0.40), (L.X_MAX, 0.37), 90)
    for sgn in (1, -1):
        s.rect(f, (sgn * 0.86, 0.58), (sgn * 0.78, 0.50), RED, light=(255, 40, 30))
    # lower gate: shut lines, the belt ledge, plate housing offset to the left, badges
    g = L.X_GATE - 0.005
    s.shut(f, (-g, 1.13), (-g, 0.73))
    s.shut(f, (g, 1.13), (g, 0.73))
    s.shut(f, (-g, 0.73), (g, 0.73))
    s.light(f, (-L.X_MAX, 1.145), (L.X_MAX, 1.13), 90)
    s.dark(f, (-0.57, 1.13), (0.57, 1.11), 100)
    s.rect(f, (-0.62, 1.06), (-0.16, 0.79), shade(P, 0.86), painted=True)
    s.dark(f, (-0.62, 1.06), (-0.16, 1.00), 120)
    s.dark(f, (-0.62, 1.06), (-0.58, 0.79), 100)
    s.rect(f, (-0.53, 0.975), (-0.20, 0.81), WHITE)
    s.rect(f, (-0.52, 0.965), (-0.21, 0.82), None, outline=(60, 60, 120), width=max(1, int(0.004 * K)))
    for x in (-0.60, -0.18):                              # plate lamps in the housing's top corners
        s.rect(f, (x - 0.015, 1.05), (x + 0.015, 1.02), CLEAR, light=(255, 255, 255))
    s.text(f, (-0.39, 1.035), "CR-V", 0.04, CHROME_DK)
    s.text(f, (-0.395, 1.038), "CR-V", 0.04, CHROME)
    s.rect(f, (-0.105, 1.125), (-0.035, 1.045), CHROME)   # the H, top left of the gate
    s.rect(f, (-0.097, 1.117), (-0.043, 1.053), BLACK)
    s.line(f, (-0.09, 1.085), (-0.05, 1.085), CHROME, 0.01)
    s.line(f, (-0.088, 1.113), (-0.088, 1.057), CHROME, 0.009)
    s.line(f, (-0.052, 1.113), (-0.052, 1.057), CHROME, 0.009)
    # tailgate glass: rounded top corners, high stop lamp, wiper parked along the bottom
    s.glass(f, L.glass_outline(), hi_dir=-1)
    s.rect(f, (-0.07, 1.565), (0.07, 1.535), RED, light=(255, 40, 30))
    s.line(f, (0.03, 1.19), (-0.34, 1.215), BLACK, 0.012)
    s.line(f, (0.02, 1.20), (-0.33, 1.222), CLAD_LT, 0.003)
    s.ellipse(f, (0.04, 1.185), 0.02, 0.02, BLACK)
    # tail lamps: on the D-pillar chamfers, from the glass seal out to the flank
    bands = ((L.LAMP_Z[0], L.LAMP_Z[1], CLEAR, (176, 180, 184), (255, 255, 255)),
             (L.LAMP_Z[1], L.LAMP_Z[2], RED, shade(RED, 0.82), (255, 40, 30)),
             (L.LAMP_Z[2], L.LAMP_Z[3], AMBER, shade(AMBER, 0.85), (255, 150, 30)))
    for sgn in (1, -1):
        for (z0, z1, col, dk, glow) in bands:
            s.poly(f, L.lamp_outline(sgn, z0, z1), col, light=glow)
            z = z0 + 0.02
            while z < z1 - 0.01:                          # fine horizontal ribs
                s.line(f, (sgn * (L.x_flat(z) + 0.012), z), (sgn * (L.rear_side(z) - 0.024), z), dk, 0.003)
                z += 0.02
            s.line(f, (sgn * (L.x_flat(z0) + 0.006), z0), (sgn * (L.rear_side(z0) - 0.017), z0), SEAL, 0.004)
        for z in (1.22, 1.32, 1.42, 1.50):                # a gloss streak up the inner third
            s.line(f, (sgn * (L.x_flat(z) + 0.03), z - 0.03), (sgn * (L.x_flat(z + 0.05) + 0.03), z + 0.02),
                   (255, 240, 225), 0.004)
        s.poly(f, L.lamp_outline(sgn, L.LAMP_Z[0], L.LAMP_Z[3]), None, outline=SEAL, width=max(1, int(0.006 * K)))
    s.shut(f, (-0.60, 1.612), (0.60, 1.612))
    # spare cover: painted disc with a rubber edge and a shaded centre dome
    s.ellipse(f, (0.28, 0.86), 0.35, 0.35, (30, 30, 32))
    s.ellipse(f, (0.28, 0.86), 0.32, 0.32, shade(P, 1.02), painted=True)
    s.ellipse(f, (0.28, 0.86), 0.29, 0.29, shade(P, 0.92), painted=True)
    s.ellipse(f, (0.28, 0.86), 0.275, 0.275, shade(P, 1.03), painted=True)
    s.ellipse(f, (0.24, 0.92), 0.10, 0.07, shade(P, 1.08), painted=True)
    s.text(f, (0.28, 0.86), "HONDA", 0.06, shade(P, 0.70))


def paint_patches(s):
    x0, y0, x1, y1 = [v * SS for v in L.PATCH_TYRE]
    s.d.rectangle((x0, y0, x1, y1), fill=(30, 30, 32))
    step = int(0.03 * K)
    for i in range(0, int(x1 - x0), step):
        s.d.rectangle((x0 + i, y0, x0 + i + step * 0.55, y1), fill=(42, 42, 44))
    s.dm.rectangle((x0, y0, x1, y1), fill=0)
    x0, y0, x1, y1 = [v * SS for v in L.PATCH_BLACK]
    s.d.rectangle((x0, y0, x1, y1), fill=BLACK)
    s.dm.rectangle((x0, y0, x1, y1), fill=0)
    x0, y0, x1, y1 = [v * SS for v in L.PATCH_CLAD]
    s.d.rectangle((x0, y0, x1, y1), fill=CLAD)
    s.dm.rectangle((x0, y0, x1, y1), fill=0)
    x0, y0, x1, y1 = [v * SS for v in L.PATCH_PAINT]
    s.d.rectangle((x0, y0, x1, y1), fill=s.paint)
    s.dm.rectangle((x0, y0, x1, y1), fill=255)


def paint(paint_colour):
    s = Sheet(paint_colour)
    paint_side(s)
    paint_top(s)
    paint_front(s)
    paint_rear(s)
    paint_patches(s)
    return s.finish(L.SIZE)


# ================================================================== wheel
def wheel_sheet():
    """Polar rim face: tyre sidewall, five-spoke alloy, centre cap with the H, lug nuts; tread strip."""
    W = L.WHEEL_SIZE * SS
    im = Image.new("RGB", (W, W), (30, 30, 32))
    d = ImageDraw.Draw(im)
    cx, cy, R = 256 * SS, 200 * SS, 196 * SS
    r_rim = R * (0.19 / 0.334)

    def circle(r, fill=None, outline=None, width=1):
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=fill, outline=outline, width=width)
    circle(R, fill=(26, 26, 28))
    circle(R * 0.93, fill=(34, 34, 36))
    circle(R * 0.80, outline=(58, 58, 60), width=max(2, int(R * 0.012)))
    circle(R * 0.72, fill=(30, 30, 32))
    circle(r_rim, fill=(150, 152, 156))
    circle(r_rim * 0.96, fill=(182, 184, 188))
    for i in range(5):
        a0 = math.radians(90 + i * 72 + 14)
        a1 = math.radians(90 + i * 72 + 58)
        pts = [(cx, cy)] + [(cx + math.cos(a0 + (a1 - a0) * k / 8) * r_rim * 0.86,
                             cy - math.sin(a0 + (a1 - a0) * k / 8) * r_rim * 0.86) for k in range(9)]
        d.polygon(pts, fill=(52, 52, 56))
    circle(r_rim * 0.42, fill=(170, 172, 176))
    for i in range(5):
        a = math.radians(90 + i * 72 - 4)
        d.line([(cx + math.cos(a) * r_rim * 0.42, cy - math.sin(a) * r_rim * 0.42),
                (cx + math.cos(a) * r_rim * 0.88, cy - math.sin(a) * r_rim * 0.88)],
               fill=(214, 216, 220), width=max(2, int(r_rim * 0.03)))
    for i in range(5):
        a = math.radians(90 + i * 72 + 36)
        nx, ny = cx + math.cos(a) * r_rim * 0.30, cy - math.sin(a) * r_rim * 0.30
        rr = r_rim * 0.045
        d.ellipse((nx - rr, ny - rr, nx + rr, ny + rr), fill=(96, 98, 102))
        d.ellipse((nx - rr * 0.6, ny - rr * 0.6, nx + rr * 0.6, ny + rr * 0.6), fill=(150, 152, 156))
    rc = r_rim * 0.16
    circle(rc, fill=(40, 40, 44))
    circle(rc * 0.9, fill=(200, 202, 206))
    d.line([(cx - rc * 0.45, cy), (cx + rc * 0.45, cy)], fill=(60, 60, 64), width=max(2, int(rc * 0.22)))
    d.line([(cx - rc * 0.4, cy - rc * 0.55), (cx - rc * 0.4, cy + rc * 0.55)], fill=(60, 60, 64), width=max(2, int(rc * 0.2)))
    d.line([(cx + rc * 0.4, cy - rc * 0.55), (cx + rc * 0.4, cy + rc * 0.55)], fill=(60, 60, 64), width=max(2, int(rc * 0.2)))
    x0, y0, x1, y1 = [v * SS for v in L.WHEEL_TREAD]
    d.rectangle((x0, y0, x1, y1), fill=(28, 28, 30))
    step = int(14 * SS)
    for i in range(0, x1 - x0, step):
        d.rectangle((x0 + i, y0, x0 + i + step * 0.6, y1), fill=(40, 40, 42))
        d.rectangle((x0 + i + step * 0.2, y0 + (y1 - y0) * 0.45, x0 + i + step * 0.4, y0 + (y1 - y0) * 0.55), fill=(24, 24, 26))
    d.line([(x0, y0 + (y1 - y0) * 0.5), (x1, y0 + (y1 - y0) * 0.5)], fill=(22, 22, 24), width=max(2, int(3 * SS)))
    return im.resize((L.WHEEL_SIZE, L.WHEEL_SIZE), Image.LANCZOS)


def rust():
    random.seed(11)
    small = Image.new("RGB", (L.SIZE // 4, L.SIZE // 4), (96, 58, 32))
    px = small.load()
    for y in range(small.size[1]):
        for x in range(small.size[0]):
            n = random.randint(-30, 30)
            r, g, b = px[x, y]
            px[x, y] = (max(0, min(255, r + n)), max(0, min(255, g + n // 2)), max(0, min(255, b + n // 3)))
    return small.resize((L.SIZE, L.SIZE), Image.BILINEAR).filter(ImageFilter.GaussianBlur(1.2))


def main(out_dir=None):
    out_dir = out_dir or TEX_DIR
    os.makedirs(out_dir, exist_ok=True)
    written = []
    for suffix, colour in SKINS.items():
        s = paint(colour)
        p = os.path.join(out_dir, "%s_Shell%s.png" % (NAME, suffix))
        s.shell.save(p)
        written.append(p)
        if suffix == "":
            s.mask.save(os.path.join(out_dir, "%s_Mask.png" % NAME))
            s.lights.save(os.path.join(out_dir, "%s_Lights.png" % NAME))
            written += [os.path.join(out_dir, "%s_Mask.png" % NAME), os.path.join(out_dir, "%s_Lights.png" % NAME)]
    wheel_sheet().save(os.path.join(out_dir, "%s_Wheel.png" % NAME))
    rust().save(os.path.join(out_dir, "%s_Rust.png" % NAME))
    written += [os.path.join(out_dir, "%s_Wheel.png" % NAME), os.path.join(out_dir, "%s_Rust.png" % NAME)]
    for p in written:
        print("WROTE", os.path.basename(p))
    return written


if __name__ == "__main__":
    main()
