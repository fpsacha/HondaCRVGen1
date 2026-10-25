r"""
The owner's manual (v2, 2026-10-17): three open two-page spreads in the style of a 1990s Honda owner's manual,
drawn with PIL from our own renders and line art. Each spread is one print media texture, shown by vanilla's
print media window (PZAPI.UI.PrintMedia); the manual's own window adds page buttons (FunctionMenu.lua), and
features/function.py writes the Print_Media / Print_Text translations. In-universe throughout: what the car does
in the game, told the way the manual, a dealer's accessory sheet, and the last owner's notes would tell it.

    python scripts\manual_art.py     writes mod\...\common\media\textures\printMedia\CRVGen1_Manual.png, _2, _3
                                     and the page buttons' icons (common\media\textures\CRVGen1_ManualPrev/Next.png)

Spreads: 1 Welcome + Driving, 2 Load space, 3 Accessories and modifications (+ the previous owner's pages).
Format: 1616 x 1131 logical (vanilla's spread size), drawn at 2x (3232 x 2262), shipped at SHIP_W x SHIP_H
(2048 x 1433, LANCZOS from the 2x drawing). Video memory (optimization pass, 2026-10-24, projectzomboid.jar B42):
ImageData pads every loose texture to the next power of two per side and print media textures carry no size cap,
so a 3232 x 2262 spread was a 4096 x 4096 RGBA texture, 64 MB, resident from the first read; 2048 x 1433 is a
2048 x 2048 one, 16 MB. The print media window fits the spread to 0.8 x the screen height (1105 px tall at
1377, 1728 at 2160): 1433 source rows stay above 1:1 up to a 1790 px tall screen.
Sources: blender\manual_src\<set>\, pzview renders of the shipped car on a flat ground (2026-10-17):
    hero   --poses shut --az 135,45 --scale 5.4 --res 2400
    open   --poses open --az 45 --scale 5.8 --res 2800
    folded --folded --only --view load,open,215,0,-1.3,0.95,3.0 --res 2200
    offroad --script HondaCRVGen1LiftAlloy --acc --acc-parts (off-road parts, rack, bull bar) --rack 2 --az 135,315
    steel  --script HondaCRVGen1LiftSteel --poses shut --az 135 --res 1800
    armour --acc --acc-parts (armour, guards) --hide-models (bar guards: the mesh / plate show) --az 45,225
    accs   --acc --acc-parts (bull bar, rack, guards, spare cover) --rack 3 --az 135
all with --ground 0.96,0.93,0.86, out dirs given ABSOLUTE (Blender resolves relative ones against C:\).
Facts are the mod's own (seats fold into a good bed, the well is found by lifting the floor, the lift needs a jack,
a lug wrench, a wrench and Mechanics 5 and gives the kit back, armour holds windows shut and wears), told in-world.
Fonts: DejaVu (matplotlib's copy, free) for print; the handwritten notes use Windows' Ink Free when present
(rasterised into the texture; the font file never ships), else DejaVu Oblique.

Translatable text (H-SAVES-I5, 2026-10-24). The spreads ship WITHOUT their words: every string is laid over the art at
draw time from its own translation key, the way vanilla's B42 newspapers lay SDF text over their pictures (the print
media window's data string: <type:text, x, y, r, g, b, a, scaleX, scaleY, angle, font> elements, PZAPI PrintMedia.lua).
Each Page.text / wrap / vtext / note / handwriting call records its string with the box it may fill (where it starts,
its width, the room the English took: a longer translation re-wraps inside that box and shrinks to fit, never over the
art). build() writes
    mod\...\42\media\lua\client\HondaCRVGen1_ManualLayout.lua   the boxes, fonts and styles (generated; FunctionMenu.lua
                                                                lays the words out with the game's font metrics)
    scripts\features\manual_strings.json                        key -> English, for features/function.py's Print_Text
The game's own SDF fonts carry the words: Open Sans (SdfRegular / Bold / Italic / BoldItalic) for print, Caveat
(SdfCaveat) for the last owner's handwriting, rotated like the pen lines were. What stays in the art (not language):
the badge numbers and letters, the "kg" and "!" glyphs inside icons, the heading numbers, and the dealer's rubber
stamp (a distressed, rotated decal: "NOLAN'S USED CARS / MULDRAUGH - KENTUCKY / PRE-LOVED CARS - NO LEMONS").
CRV_MANUAL_BAKED_TEXT=1 draws every string into the art as before (comparisons only; never shipped).

    python scripts\manual_art.py --preview [--lang en|pseudo] [--screen 1080|1440|2160] [--out DIR]
        simulated screenshots: the shipped spreads as the game draws them (window scale 0.8 x the screen height, the
        overlay laid out by FunctionMenu.lua under lupa with the game's .fnt metrics, the SDF glyphs drawn with the
        game's sdf.frag threshold); --lang pseudo stretches every string ~40% (German-like) to show re-wrapping
"""
import json
import math
import os
import re

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("CRV_ROOT") or os.path.dirname(HERE)
SRC = os.path.join(ROOT, "blender", "manual_src")
TEX = os.path.join(ROOT, "mod", "Contents", "mods", "HondaCRVGen1", "common", "media", "textures")
OUTS = [os.path.join(TEX, "printMedia", n) for n in ("CRVGen1_Manual.png", "CRVGen1_Manual_2.png", "CRVGen1_Manual_3.png")]
NAV = {"prev": os.path.join(TEX, "CRVGen1_ManualPrev.png"), "next": os.path.join(TEX, "CRVGen1_ManualNext.png")}
LAYOUT_LUA = os.path.join(ROOT, "mod", "Contents", "mods", "HondaCRVGen1", "42", "media", "lua", "client",
                          "HondaCRVGen1_ManualLayout.lua")
STRINGS_JSON = os.path.join(ROOT, "scripts", "features", "manual_strings.json")
KEY_PREFIX = "Print_Text_CRVGen1_ManualPage_"   # + the string's id (FunctionMenu.lua M.MANUAL_KEY_PREFIX)
OVERLAY = os.environ.get("CRV_MANUAL_BAKED_TEXT") != "1"
SDF_FONTS = ("SdfRegular", "SdfBold", "SdfItalic", "SdfBoldItalic", "SdfCaveat")
HAND_SCALE = 1.22                            # Caveat is smaller on the body than Ink Free at one size
PRINT_SCALE = 1.06                           # Open Sans at 1.06 x a DejaVu size sets a line as wide
W, H, S = 1616, 1131, 2
SHIP_W = 2048                                # shipped width: the widest power of two the 4:2.8 spread fits whole
SHIP_H = int(round(H * SHIP_W / W))          # 1433: the spread's aspect; GPU size 2048 x 2048
PW = W // 2                                  # one page
GUT = 34                                     # inner margin at the gutter
MARG = 42                                    # outer margin
L0, L1 = MARG, PW - GUT                      # left page content
R0, R1 = PW + GUT, W - MARG                  # right page content

PAPER = (242, 235, 216)
PANEL = (249, 245, 233)
INK = (30, 33, 40)
MUTED = (108, 101, 88)
NAVY = (22, 42, 84)
NAVY_L = (214, 220, 232)
RED = (190, 24, 38)
RULE = (186, 176, 154)
STEEL = (120, 126, 136)
LIGHT = (214, 222, 230)
GREEN = (46, 120, 64)
PEN = (34, 48, 112)
CLIP = (236, 233, 226)                       # magazine paper, cooler than the manual's


def _font_dir():
    import matplotlib
    return os.path.join(matplotlib.get_data_path(), "fonts", "ttf")


_FONTS = {}


def font(size, bold=False, oblique=False, cond=False):
    name = "DejaVuSans" + ("Condensed" if cond else "")
    style = "-BoldOblique" if bold and oblique else "-Bold" if bold else "-Oblique" if oblique else ""
    key = (name + style, int(round(size * S)))
    if key not in _FONTS:
        _FONTS[key] = ImageFont.truetype(os.path.join(_font_dir(), name + style + ".ttf"), key[1])
    return _FONTS[key]


def hand_font(size):
    for p in (r"C:\Windows\Fonts\Inkfree.ttf", r"C:\Windows\Fonts\segoepr.ttf"):
        if os.path.exists(p):
            return ImageFont.truetype(p, int(round(size * S)))
    return font(size, oblique=True)


def sc(v):
    return int(round(v * S))


# ------------------------------------------------------------------------------------------- the words
_STRINGS = {}                                # string id -> English (insertion order = reading order)
_BY_TEXT = {}


def reset_strings():
    _STRINGS.clear()
    _BY_TEXT.clear()
    Page._flows = 0


def string_id(s):
    """A string's translation id: its first words in CamelCase (the same English is one key everywhere)."""
    if s in _BY_TEXT:
        return _BY_TEXT[s]
    words = re.findall(r"[A-Za-z0-9]+", s.replace("**", ""))
    base = "".join(w[:1].upper() + w[1:].lower() for w in words[:5]) or "Text"
    sid, n = base, 2
    while sid in _STRINGS:
        sid, n = "%s%d" % (base, n), n + 1
    _STRINGS[sid] = s
    _BY_TEXT[s] = sid
    return sid


def sdf_font(bold=False, oblique=False):
    return {(False, False): "SdfRegular", (True, False): "SdfBold", (False, True): "SdfItalic",
            (True, True): "SdfBoldItalic"}[(bool(bold), bool(oblique))]


def rot(dx, dy, angle):
    """PIL's rotate(angle) and AtomUI's angle (degrees, counter-clockwise on screen, y down) on an offset."""
    a = math.radians(angle)
    return math.cos(a) * dx + math.sin(a) * dy, -math.sin(a) * dx + math.cos(a) * dy


def rgba(fill, a=1.0):
    return [round(fill[0] / 255.0, 3), round(fill[1] / 255.0, 3), round(fill[2] / 255.0, 3),
            round(a if len(fill) < 4 else fill[3] / 255.0, 3)]


# ------------------------------------------------------------------------------------------- the page
class Page:
    def __init__(self, seed=1997):
        rng = np.random.default_rng(seed)
        base = np.zeros((H * S, W * S, 3), np.float32) + np.array(PAPER, np.float32)
        yy, xx = np.mgrid[0:H * S, 0:W * S].astype(np.float32)
        edge = np.minimum.reduce([xx, yy, W * S - xx, H * S - yy]) / (46.0 * S)     # a thumbed booklet's edges
        base *= (0.90 + 0.10 * np.clip(edge, 0, 1))[..., None]
        g = np.abs(xx - PW * S) / (26.0 * S)                                        # both pages curve into the spine
        base *= (0.74 + 0.26 * np.clip(g, 0, 1) ** 0.6)[..., None]
        base += rng.normal(0, 2.4, base.shape[:2])[..., None]                      # paper grain
        self.img = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8)).convert("RGBA")
        self.d = ImageDraw.Draw(self.img)
        self.items = []                      # the overlaid strings (OVERLAY): FunctionMenu.lua lays them out

    def redraw(self):
        self.d = ImageDraw.Draw(self.img)

    def record(self, english, **it):
        it["k"] = string_id(english)
        if it["f"] != "SdfCaveat":           # Open Sans is ~6% narrower and lighter than DejaVu: the same width, same pitch
            it["s"] = round(it["s"] * PRINT_SCALE, 3)
            if "ld" in it:
                it["ld"] = round(it["ld"] / PRINT_SCALE, 4)
        self.items.append(it)
        return len(self.items) - 1

    # -- text
    def text(self, x, y, s, size, fill=INK, bold=False, anchor="la", oblique=False, cond=False, tr=True, room=None,
             after=None, gap=6.0):
        """One line. Overlaid (translatable) unless tr=False: a translation may widen to `room` (default 1.25 x the
        English) and shrinks to fit beyond it; `after` = the index of an item this one follows on its line."""
        f = font(size, bold, oblique, cond)
        if not (OVERLAY and tr):
            self.d.text((sc(x), sc(y)), s, font=f, fill=fill, anchor=anchor)
            return None
        asc, desc = [v / S for v in f.getmetrics()]
        w = self.d.textlength(s, font=f) / S
        it = {"x": x, "s": size, "f": sdf_font(bold, oblique), "c": rgba(fill), "al": {"l": 0, "m": 0.5, "r": 1}[anchor[0]],
              "mw": round(room if room is not None else w * 1.25, 1)}
        if anchor[1] == "m":
            it["y"], it["vm"] = y, 1
        else:
            it["y"] = y + (asc if anchor[1] == "a" else 0.0)
        if after is not None:
            it["af"], it["g"] = after + 1, gap          # 1-based in Lua
        return self.record(s, **it)

    def flow(self, bottom):
        """with pg.flow(bottom): the wrapped strings recorded inside share one box down to `bottom` (gr / gh / gp):
        a longer paragraph pushes the next one down instead of shrinking alone."""
        pg = self

        class Flow:
            def __enter__(self):
                self.start = len(pg.items)
                return self

            def __exit__(self, *exc):
                its = [it for it in pg.items[self.start:] if "w" in it]
                if not its or not OVERLAY:
                    return False
                Page._flows = getattr(Page, "_flows", 0) + 1
                prev = None
                for it in its:
                    top = it["y"] - it["a0"]
                    it["gr"] = Page._flows
                    it["gp"] = 0 if prev is None else round(top - prev, 2)
                    prev = top + it["mh"]
                its[0]["gh"] = round(bottom - (its[0]["y"] - its[0]["a0"]), 1)
                return False
        return Flow()

    def tw(self, s, size, bold=False):
        return self.d.textlength(s, font=font(size, bold)) / S

    def wrap(self, x, y, s, size, width, fill=INK, bold=False, leading=1.36, oblique=False, maxh=None, extra=0.0):
        """Word-wrapped text; **word** runs are bold. Returns the y under the last line. Overlaid: the box is `width`
        wide and as tall as the English took (or `maxh`); a longer translation re-wraps in it and shrinks to fit."""
        words = []                                  # (word, bold, glued to the previous word)
        for i, chunk in enumerate(s.split("**")):
            for j, w in enumerate(chunk.split()):
                glue = j == 0 and bool(words) and not chunk[:1].isspace() and w[0] in ",.;:!?)'"
                words.append((w, i % 2 == 1 or bold, glue))
        lines, cur, curw = [], [], 0.0
        space = self.d.textlength(" ", font=font(size)) / S
        for w, b, glue in words:
            ww = self.d.textlength(w, font=font(size, b, oblique)) / S
            gap = 0.0 if glue else space
            if cur and curw + gap + ww > width and not glue:
                lines.append(cur)
                cur, curw = [], 0.0
                gap = 0.0
            cur.append((w, b, ww, glue))
            curw += (gap if len(cur) > 1 else 0) + ww
        if cur:
            lines.append(cur)
        if OVERLAY:
            asc = font(size, bold, oblique).getmetrics()[0] / S
            self.record(s, x=x, y=y + asc, a0=round(asc, 2), s=size, f=sdf_font(bold, oblique), c=rgba(fill), al=0,
                        w=round(width, 1), mh=round(max(maxh or 0, len(lines) * size * leading + extra) + 0.05, 1), ld=leading)
            return y + len(lines) * size * leading
        for i, ln in enumerate(lines):
            px = x
            for k, (w, b, ww, glue) in enumerate(ln):
                if k and not glue:
                    px += space
                self.d.text((sc(px), sc(y + i * size * leading)), w, font=font(size, b, oblique), fill=fill)
                px += ww
        return y + len(lines) * size * leading

    def vtext(self, x, y, s, size, fill, bold=True, room=None):
        f = font(size, bold)
        if OVERLAY:                        # the label reads upwards from (x, y): the baseline 0.1 size + ascent in
            asc = f.getmetrics()[0] / S
            w = self.d.textlength(s, font=f) / S
            return self.record(s, x=x + 0.1 * size + asc, y=y - 2, s=size, f=sdf_font(bold), c=rgba(fill), al=0, an=90,
                               mw=round(room if room is not None else w * 1.25, 1))
        tw_, th = int(self.d.textlength(s, font=f)) + sc(4), sc(size * 1.3)
        tile = Image.new("RGBA", (tw_, th), (0, 0, 0, 0))
        ImageDraw.Draw(tile).text((sc(2), sc(size * 0.1)), s, font=f, fill=fill)
        tile = tile.rotate(90, expand=True)
        self.img.alpha_composite(tile, (sc(x), sc(y) - tile.height))
        self.redraw()

    # -- furniture
    def rule(self, x0, y, x1, w=1.0, fill=RULE):
        self.d.line([sc(x0), sc(y), sc(x1), sc(y)], fill=fill, width=max(1, sc(w)))

    def heading(self, x, y, s, w, n=None, sub=None):
        """A section heading the Honda way: a numbered navy square, bold caps, a rule under it."""
        tx = x
        if n is not None:
            self.d.rounded_rectangle([sc(x), sc(y), sc(x + 19), sc(y + 19)], radius=sc(2.5), fill=NAVY)
            self.d.text((sc(x + 9.5), sc(y + 10)), str(n), font=font(11, True), fill=(255, 255, 255), anchor="mm")
            tx = x + 27
        subw = self.tw(sub, 8.5, True) if sub else 0.0
        self.text(tx, y + 0.5, s.upper(), 14, NAVY, True, room=x + w - tx - (subw * 1.2 + 14 if sub else 0))
        if sub:
            self.text(x + w, y + 4, sub, 8.5, MUTED, True, "ra", room=subw * 1.5)
        self.rule(x, y + 25, x + w, 1.5, NAVY)
        return y + 35

    def badge(self, cx, cy, n, r=10.5, fill=RED):
        self.d.ellipse([sc(cx - r - 1.5), sc(cy - r - 1.5), sc(cx + r + 1.5), sc(cy + r + 1.5)], fill=(255, 255, 255))
        self.d.ellipse([sc(cx - r), sc(cy - r), sc(cx + r), sc(cy + r)], fill=fill)
        self.d.text((sc(cx), sc(cy + 0.5)), str(n), font=font(r * 1.12, True), fill=(255, 255, 255), anchor="mm")

    def box(self, x, y, w, h, fill=PANEL, outline=RULE, r=5, width=1.1):
        self.d.rounded_rectangle([sc(x), sc(y), sc(x + w), sc(y + h)], radius=sc(r), fill=fill, outline=outline, width=max(1, sc(width)))

    def shadow(self, x, y, w, h, r=5, off=3, alpha=60):
        sh = Image.new("RGBA", self.img.size, (0, 0, 0, 0))
        ImageDraw.Draw(sh).rounded_rectangle([sc(x + off), sc(y + off), sc(x + w + off), sc(y + h + off)], radius=sc(r),
                                             fill=(60, 48, 30, alpha))
        self.img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(sc(3))))
        self.redraw()

    def paste(self, im, x, y):
        self.img.alpha_composite(im.convert("RGBA"), (sc(x), sc(y)))
        self.redraw()

    def arrow(self, pts, fill=RED, w=2.2, head=7):
        self.d.line([(sc(px), sc(py)) for px, py in pts], fill=fill, width=sc(w), joint="curve")
        (x0, y0), (x1, y1) = pts[-2], pts[-1]
        a = math.atan2(y1 - y0, x1 - x0)
        tri = [(x1, y1), (x1 - head * math.cos(a - 0.45), y1 - head * math.sin(a - 0.45)),
               (x1 - head * math.cos(a + 0.45), y1 - head * math.sin(a + 0.45))]
        self.d.polygon([(sc(px), sc(py)) for px, py in tri], fill=fill)

    def leader(self, x0, y0, x1, y1, fill=INK):
        """A callout's leader line with a dot at the thing it points at (x0, y0)."""
        self.d.line([sc(x0), sc(y0), sc(x1), sc(y1)], fill=fill, width=sc(0.9))
        self.d.ellipse([sc(x0 - 2.2), sc(y0 - 2.2), sc(x0 + 2.2), sc(y0 + 2.2)], fill=fill)

    def tab(self, label, y0=96, y1=330, left=True):
        x0, x1 = (0, 18) if left else (W - 18, W)
        self.d.rectangle([sc(x0), sc(y0), sc(x1), sc(y1)], fill=NAVY)
        self.vtext(x0 + 3, y1 - 8, label, 8.5, (255, 255, 255), room=y1 - y0 - 14)

    def head(self, left_title, right_title):
        y = 26
        half = (L1 - L0) / 2 - 10
        self.text(L0, y, "HONDA CRV", 9.5, INK, True, room=half)
        self.text(L1, y, left_title, 9.5, MUTED, True, "ra", room=half)
        self.rule(L0, y + 18, L1, 0.9, INK)
        self.text(R0, y, right_title, 9.5, MUTED, True, room=half)
        self.text(R1, y, "HONDA CRV", 9.5, INK, True, "ra", room=half)
        self.rule(R0, y + 18, R1, 0.9, INK)

    def folio(self, left_n, right_n, label):
        self.text(L0, H - 24, str(left_n), 9, INK, True, tr=False)
        self.text(L0 + 20, H - 23, label, 7.5, MUTED, room=300)
        self.text(R1, H - 24, str(right_n), 9, INK, True, "ra", tr=False)
        self.text(R1 - 20, H - 23, label, 7.5, MUTED, False, "ra", room=300)


# -------------------------------------------------------------------------------------------- renders
def src(path):
    return os.path.join(SRC, *path.split("/"))


def cutout(path, crop=None, thr=34):
    """A pzview render with its flat ground made transparent, cropped to what is left."""
    im = Image.open(src(path)).convert("RGB")
    if crop:
        im = im.crop(crop)
    a = np.asarray(im).astype(np.int32)
    ground = np.median(np.concatenate([a[:10, :10].reshape(-1, 3), a[:10, -10:].reshape(-1, 3),
                                       a[-10:, :10].reshape(-1, 3), a[-10:, -10:].reshape(-1, 3)]), axis=0)
    mask = (np.abs(a - ground).sum(axis=2) > thr).astype(np.uint8) * 255
    m = Image.fromarray(mask).filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.MinFilter(9))
    m = m.filter(ImageFilter.GaussianBlur(1.3))
    out = im.convert("RGBA")
    out.putalpha(m)
    return out.crop(out.getchannel("A").point(lambda v: 255 if v > 40 else 0).getbbox())


def lift(im, gain=1.18, gamma=0.88):
    """The renders are lit for the game's dark ground: brighten them for print, keep the alpha."""
    a = np.asarray(im.convert("RGBA")).astype(np.float32)
    rgb = np.clip(255.0 * (a[..., :3] / 255.0) ** gamma * gain, 0, 255)
    return Image.fromarray(np.dstack([rgb, a[..., 3]]).astype(np.uint8), "RGBA")


def fit(im, w, h):
    s = min(sc(w) / im.width, sc(h) / im.height)
    return im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))), Image.LANCZOS)


def put_fit(pg, im, x, y, w, h, ground_shadow=True):
    r = fit(im, w, h)
    ox, oy = x + (w - r.width / S) / 2, y + (h - r.height / S) / 2
    if ground_shadow:                                   # a soft contact shadow so a cut-out stands on the page
        sh = Image.new("RGBA", pg.img.size, (0, 0, 0, 0))
        cx, cy = sc(ox) + r.width // 2, sc(oy) + int(r.height * 0.86)
        ImageDraw.Draw(sh).ellipse([cx - int(r.width * 0.42), cy - int(r.height * 0.07), cx + int(r.width * 0.42),
                                    cy + int(r.height * 0.07)], fill=(70, 56, 36, 70))
        pg.img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(sc(9))))
        pg.redraw()
    pg.paste(r, ox, oy)
    return ox, oy, r.width / S, r.height / S


def photo(pg, im, x, y, w, h, caption=None, crop=None):
    """A render in a white print frame (cropped to fill it), a caption under it."""
    im = im.convert("RGB")
    ih = h - (16 if caption else 0)
    tw_, th = sc(w - 10), sc(ih - 10)
    s = max(tw_ / im.width, th / im.height)
    r = im.resize((int(im.width * s) + 1, int(im.height * s) + 1), Image.LANCZOS)
    cx = (r.width - tw_) // 2 if crop is None else int((r.width - tw_) * crop[0])
    cy = (r.height - th) // 2 if crop is None else int((r.height - th) * crop[1])
    r = r.crop((cx, cy, cx + tw_, cy + th))
    pg.shadow(x, y, w, ih, 1, 2.5, 55)
    pg.d.rectangle([sc(x), sc(y), sc(x + w), sc(y + ih)], fill=(255, 255, 255), outline=RULE, width=sc(0.8))
    pg.paste(lift(r), x + 5, y + 5)
    if caption:
        pg.text(x + w / 2, y + ih + 5, caption, 7.8, MUTED, False, "ma", True, room=w)


# -------------------------------------------------------------------------------------------- icons
def icon(pg, kind, cx, cy, s=1.0, fill=NAVY, bg=NAVY_L):
    """Small line icons (our own drawings): a disc with the glyph in navy."""
    d = pg.d
    r = 15 * s
    if bg:
        d.ellipse([sc(cx - r), sc(cy - r), sc(cx + r), sc(cy + r)], fill=bg)
    k = s
    lw = max(1, sc(1.6 * k))

    def P(x, y):
        return (sc(cx + x * k), sc(cy + y * k))
    if kind == "seat":
        d.line([P(-6, 7), P(5, 7)], fill=fill, width=lw)
        d.line([P(-6, 7), P(-8, -8)], fill=fill, width=lw)
        d.rounded_rectangle([P(-9, -11), P(-5, -7)], radius=sc(1), outline=fill, width=lw)
        d.line([P(5, 7), P(6, 9)], fill=fill, width=lw)
    elif kind == "engine":
        d.rectangle([P(-8, -5), P(7, 6)], outline=fill, width=lw)
        d.line([P(-4, -5), P(-4, -9), P(3, -9), P(3, -5)], fill=fill, width=lw)
        d.line([P(7, 0), P(10, 0)], fill=fill, width=lw)
        d.line([P(-8, 0), P(-11, 0)], fill=fill, width=lw)
    elif kind == "fuel":
        d.rectangle([P(-7, -8), P(3, 9)], outline=fill, width=lw)
        d.line([P(-5, -4), P(1, -4)], fill=fill, width=lw)
        d.line([P(3, -5), P(7, -2), P(7, 5), P(9, 6)], fill=fill, width=lw)
    elif kind == "4wd":
        for x in (-7, 7):
            for y in (-7, 7):
                d.rectangle([P(x - 2, y - 3), P(x + 2, y + 3)], fill=fill)
        d.line([P(-5, -7), P(5, -7)], fill=fill, width=lw)
        d.line([P(-5, 7), P(5, 7)], fill=fill, width=lw)
        d.line([P(0, -7), P(0, 7)], fill=fill, width=lw)
    elif kind == "box":
        d.polygon([P(-9, -3), P(0, -8), P(9, -3), P(0, 2)], outline=fill)
        d.line([P(-9, -3), P(-9, 6), P(0, 11), P(9, 6), P(9, -3)], fill=fill, width=lw)
        d.line([P(0, 2), P(0, 11)], fill=fill, width=lw)
    elif kind == "book":
        d.polygon([P(-10, -7), P(0, -5), P(0, 9), P(-10, 7)], outline=fill)
        d.polygon([P(10, -7), P(0, -5), P(0, 9), P(10, 7)], outline=fill)
        d.line([P(-7, -2), P(-3, -1)], fill=fill, width=max(1, sc(1.0 * k)))
        d.line([P(-7, 2), P(-3, 3)], fill=fill, width=max(1, sc(1.0 * k)))
    elif kind == "wrench":
        d.line([P(-7, 7), P(4, -4)], fill=fill, width=sc(3.2 * k))
        d.ellipse([P(2, -10), P(10, -2)], outline=fill, width=lw)
        d.rectangle([P(6, -8), P(11, -6)], fill=bg or PAPER)
    elif kind == "screwdriver":
        d.line([P(-8, 8), P(-2, 2)], fill=fill, width=sc(4.2 * k))
        d.line([P(-2, 2), P(8, -8)], fill=fill, width=lw)
    elif kind == "hand":
        d.rounded_rectangle([P(-6, -2), P(6, 9)], radius=sc(3 * k), outline=fill, width=lw)
        for i, x in enumerate((-5, -1.5, 2, 5.5)):
            d.line([P(x, -2), P(x, -9 + abs(i - 1.5))], fill=fill, width=lw)
        d.line([P(-6, 3), P(-10, -1)], fill=fill, width=lw)
    elif kind == "jack":
        d.polygon([P(-9, 8), P(9, 8), P(0, -2)], outline=fill)
        d.line([P(0, -2), P(0, -8)], fill=fill, width=lw)
        d.line([P(-5, -8), P(5, -8)], fill=fill, width=lw)
    elif kind == "lug":
        d.line([P(-9, 0), P(9, 0)], fill=fill, width=sc(2.6 * k))
        d.line([P(0, -9), P(0, 9)], fill=fill, width=sc(2.6 * k))
    elif kind == "check":
        d.line([P(-7, 0), P(-2, 6), P(8, -7)], fill=GREEN, width=sc(2.8 * k), joint="curve")
    elif kind == "cross":
        d.line([P(-6, -6), P(6, 6)], fill=RED, width=sc(2.8 * k))
        d.line([P(-6, 6), P(6, -6)], fill=RED, width=sc(2.8 * k))
    elif kind == "can":
        d.rounded_rectangle([P(-8, -7), P(8, 10)], radius=sc(2 * k), outline=fill, width=lw)
        d.line([P(-8, 1), P(8, 1)], fill=fill, width=max(1, sc(1.0 * k)))
        d.rectangle([P(-6, -11), P(1, -7)], outline=fill, width=lw)
        d.line([P(3, -7), P(7, -11)], fill=fill, width=lw)
    elif kind == "bed":
        d.line([P(-10, 6), P(10, 6)], fill=fill, width=lw)
        d.rounded_rectangle([P(-8, -1), P(9, 4)], radius=sc(1.5), outline=fill, width=lw)
        d.ellipse([P(-9, -6), P(-4, -1)], outline=fill, width=lw)
        d.line([P(-10, -6), P(-10, 9)], fill=fill, width=lw)
    elif kind == "lock":
        d.rounded_rectangle([P(-8, -1), P(8, 10)], radius=sc(2 * k), outline=fill, width=lw)
        d.arc([P(-5, -11), P(5, 3)], 180, 360, fill=fill, width=lw)
        d.ellipse([P(-1.6, 3), P(1.6, 6.2)], fill=fill)
    elif kind == "table":
        d.line([P(-10, -3), P(10, -3)], fill=fill, width=sc(2.4 * k))
        d.line([P(-7, -2), P(-9, 9)], fill=fill, width=lw)
        d.line([P(7, -2), P(9, 9)], fill=fill, width=lw)
        d.rectangle([P(-3, -9), P(1, -4)], outline=fill, width=max(1, sc(1.0 * k)))
    elif kind == "weight":
        d.polygon([P(-8, 9), P(8, 9), P(5, -4), P(-5, -4)], outline=fill)
        d.ellipse([P(-3, -10), P(3, -4)], outline=fill, width=lw)
        d.text(P(0, 3.5), "kg", font=font(6.2 * k, True), fill=fill, anchor="mm")


def tool_row(pg, x, y, kinds, labels, s=0.85):
    """Tool icons with a label under each; returns the row's width."""
    step = 64
    for i, (k, lab) in enumerate(zip(kinds, labels)):
        icon(pg, k, x + 16 + i * step, y + 16, s)
        pg.text(x + 16 + i * step, y + 34, lab, 7.2, INK, True, "ma", room=step - 4)
    return len(kinds) * step


# -------------------------------------------------------------------------------------------- drawings
def car_plan(pg, cx, top, bw, bh, front_on, rear_on, shaft_on, label):
    """A top view of the drivetrain: wheels, engine, propeller shaft, the rear differential."""
    d = pg.d
    d.rounded_rectangle([sc(cx - bw / 2), sc(top), sc(cx + bw / 2), sc(top + bh)], radius=sc(16), outline=INK, width=sc(1.4),
                        fill=(236, 230, 212))
    d.polygon([(sc(cx - 24), sc(top + 34)), (sc(cx + 24), sc(top + 34)), (sc(cx + 20), sc(top + 54)), (sc(cx - 20), sc(top + 54))],
              outline=INK, fill=LIGHT)
    fy, ry = top + 40, top + bh - 44
    for wy, on in ((fy, front_on), (ry, rear_on)):
        for wx in (cx - bw / 2 - 9, cx + bw / 2 - 1):
            d.rounded_rectangle([sc(wx), sc(wy - 15), sc(wx + 10), sc(wy + 15)], radius=sc(3), fill=RED if on else INK)
        d.line([sc(cx - bw / 2 - 4), sc(wy), sc(cx + bw / 2 + 4), sc(wy)], fill=INK, width=sc(1.6))
    d.rectangle([sc(cx - 20), sc(fy - 9), sc(cx + 20), sc(fy + 9)], fill=(255, 255, 255), outline=INK, width=sc(1.3))
    pg.text(cx, fy, "ENGINE", 5.2, INK, True, "mm", room=36)
    d.line([sc(cx), sc(fy + 11), sc(cx), sc(ry - 8)], fill=RED if shaft_on else STEEL, width=sc(2.6 if shaft_on else 2.0))
    d.ellipse([sc(cx - 7), sc(ry - 7), sc(cx + 7), sc(ry + 7)], outline=INK, width=sc(1.3), fill=RED if rear_on else (255, 255, 255))
    if rear_on:
        pg.arrow([(cx + 10, ry + 20), (cx + bw / 2 - 2, ry + 20)], RED, 1.8, 5)
        pg.arrow([(cx - 10, ry + 20), (cx - bw / 2 + 2, ry + 20)], RED, 1.8, 5)
    pg.text(cx, top + bh + 10, label, 8, NAVY, True, "ma", room=132)


def terrain(pg, x, y, w, h, kind, label, ok):
    """A small square scene: road, gravel, track, field, snow, rocks."""
    d = pg.d
    pg.box(x, y, w, h, (250, 247, 238), RULE, 4, 0.9)
    gy = y + h * 0.62
    sky = (232, 236, 240)
    d.rounded_rectangle([sc(x + 3), sc(y + 3), sc(x + w - 3), sc(gy)], radius=sc(3), fill=sky)
    rng = np.random.default_rng(len(label) * 31 + 7)
    if kind == "road":
        d.rectangle([sc(x + 3), sc(gy), sc(x + w - 3), sc(y + h - 18)], fill=(96, 98, 104))
        for i in range(4):
            d.rectangle([sc(x + 8 + i * (w - 16) / 4), sc(gy + 10), sc(x + 8 + i * (w - 16) / 4 + 10), sc(gy + 12)], fill=(240, 220, 120))
    elif kind == "gravel":
        d.rectangle([sc(x + 3), sc(gy), sc(x + w - 3), sc(y + h - 18)], fill=(176, 164, 140))
        for _ in range(60):
            px, py = x + 4 + rng.random() * (w - 8), gy + 2 + rng.random() * (h * 0.38 - 22)
            d.ellipse([sc(px), sc(py), sc(px + 2), sc(py + 1.6)], fill=(120, 110, 92))
    elif kind == "track":
        d.rectangle([sc(x + 3), sc(gy), sc(x + w - 3), sc(y + h - 18)], fill=(136, 158, 96))
        for o in (-12, 12):
            d.polygon([(sc(x + w / 2 + o - 2), sc(gy)), (sc(x + w / 2 + o + 2), sc(gy)), (sc(x + w / 2 + o * 2.4 + 6), sc(y + h - 18)),
                       (sc(x + w / 2 + o * 2.4 - 6), sc(y + h - 18))], fill=(150, 116, 78))
    elif kind == "field":
        d.rectangle([sc(x + 3), sc(gy), sc(x + w - 3), sc(y + h - 18)], fill=(120, 150, 80))
        for _ in range(26):
            px = x + 6 + rng.random() * (w - 12)
            py = gy + 4 + rng.random() * (h * 0.38 - 24)
            d.line([sc(px), sc(py + 4), sc(px + 1), sc(py)], fill=(70, 104, 50), width=sc(1))
    elif kind == "snow":
        d.rectangle([sc(x + 3), sc(gy), sc(x + w - 3), sc(y + h - 18)], fill=(246, 248, 252))
        for _ in range(16):
            px, py = x + 6 + rng.random() * (w - 12), y + 6 + rng.random() * (h * 0.5)
            d.ellipse([sc(px), sc(py), sc(px + 2), sc(py + 2)], fill=(255, 255, 255))
        d.line([sc(x + 3), sc(gy), sc(x + w - 3), sc(gy)], fill=(200, 208, 220), width=sc(1))
    elif kind == "rocks":
        d.rectangle([sc(x + 3), sc(gy), sc(x + w - 3), sc(y + h - 18)], fill=(150, 140, 120))
        for i in range(5):
            bx = x + 8 + i * (w - 20) / 5
            d.polygon([(sc(bx), sc(gy + 14)), (sc(bx + 6), sc(gy - 4 - (i % 2) * 6)), (sc(bx + 16), sc(gy + 2)), (sc(bx + 14), sc(gy + 14))],
                      fill=(110, 104, 96), outline=(80, 76, 70))
    pg.text(x + w / 2, y + h - 14, label, 7.6, INK, True, "ma", room=w - 6)
    icon(pg, "check" if ok else "cross", x + w - 12, y + 12, 0.7, bg=(255, 255, 255))


def diagram_seats(pg, x, y, w, h):
    """Three side views: the rear seat upright, its back folded down, the seat tumbled: a flat floor and a bed."""
    d = pg.d
    cw = w / 3
    floor = y + h - 24
    for i, (label, mode) in enumerate((("1  Seat up", "up"), ("2  Back folds down", "fold"), ("3  Seat tumbles: a flat floor", "tumble"))):
        ox = x + i * cw
        d.line([sc(ox + 6), sc(floor), sc(ox + cw - 8), sc(floor)], fill=INK, width=sc(1.4))
        deck = floor - 34
        d.line([sc(ox + 6), sc(deck), sc(ox + cw * 0.42), sc(deck)], fill=INK, width=sc(1.3))
        d.line([sc(ox + cw * 0.42), sc(deck), sc(ox + cw * 0.42), sc(floor)], fill=INK, width=sc(1.0))
        seat = (206, 214, 226)
        if mode == "up":
            d.rounded_rectangle([sc(ox + cw * 0.42), sc(deck), sc(ox + cw * 0.80), sc(deck + 11)], radius=sc(4), fill=seat, outline=INK, width=sc(1.2))
            back = [(ox + cw * 0.42, deck + 2), (ox + cw * 0.51, deck + 2), (ox + cw * 0.57, deck - 48), (ox + cw * 0.48, deck - 48)]
            d.polygon([(sc(px), sc(py)) for px, py in back], fill=seat, outline=INK)
            d.rounded_rectangle([sc(ox + cw * 0.48), sc(deck - 59), sc(ox + cw * 0.57), sc(deck - 50)], radius=sc(2), fill=seat, outline=INK)
            pg.arrow([(ox + cw * 0.63, deck - 46), (ox + cw * 0.75, deck - 32), (ox + cw * 0.82, deck - 13)], RED, 1.7, 5.5)
        elif mode == "fold":
            d.rounded_rectangle([sc(ox + cw * 0.42), sc(deck), sc(ox + cw * 0.80), sc(deck + 11)], radius=sc(4), fill=seat, outline=INK, width=sc(1.2))
            d.rounded_rectangle([sc(ox + cw * 0.42), sc(deck - 10), sc(ox + cw * 0.80), sc(deck)], radius=sc(4), fill=seat, outline=INK, width=sc(1.2))
            pg.arrow([(ox + cw * 0.84, deck - 14), (ox + cw * 0.92, deck - 32), (ox + cw * 0.90, deck - 46)], RED, 1.7, 5.5)
        else:
            d.line([sc(ox + cw * 0.42), sc(deck), sc(ox + cw * 0.78), sc(deck)], fill=INK, width=sc(1.3))
            d.rounded_rectangle([sc(ox + cw * 0.78), sc(deck - 34), sc(ox + cw * 0.88), sc(deck)], radius=sc(3), fill=seat, outline=INK, width=sc(1.2))
            d.line([sc(ox + 6), sc(deck + 3), sc(ox + cw * 0.78), sc(deck + 3)], fill=RED, width=sc(2.2))
            # a sleeping bag on the flat floor: what the floor is for at night
            d.rounded_rectangle([sc(ox + 12), sc(deck - 9), sc(ox + cw * 0.72), sc(deck - 1)], radius=sc(4), fill=(120, 140, 112), outline=INK, width=sc(1))
            d.ellipse([sc(ox + 12), sc(deck - 12), sc(ox + 24), sc(deck - 1)], fill=(232, 222, 200), outline=INK, width=sc(1))
        pg.text(ox + cw / 2 - 2, floor + 6, label, 7.6, NAVY, True, "ma", room=cw - 6)


def diagram_floor(pg, x, y, w, h):
    """The cargo floor: the panel lifted (the well under it), then the same panel standing on its legs as a table."""
    d = pg.d
    base = y + h - 18
    d.line([sc(x + 8), sc(base), sc(x + w - 8), sc(base)], fill=INK, width=sc(1.4))
    fl = base - 50
    # the well and the seat base behind it
    d.rectangle([sc(x + 26), sc(fl + 8), sc(x + 170), sc(base)], outline=INK, width=sc(1.2), fill=(232, 224, 203))
    for i in range(3):                                         # things kept out of sight
        bx = x + 40 + i * 40
        d.rounded_rectangle([sc(bx), sc(base - 16 - (i % 2) * 6), sc(bx + 26), sc(base - 2)], radius=sc(2), fill=(196, 188, 170), outline=INK, width=sc(0.8))
    pg.text(x + 98, fl + 22, "STORAGE WELL", 6.8, MUTED, True, "mm", room=136)
    d.rectangle([sc(x + 170), sc(fl), sc(x + 220), sc(base)], outline=INK, width=sc(1.2), fill=(226, 218, 198))
    panel = [(x + 170, fl), (x + 170, fl + 8), (x + 30, fl - 30), (x + 30, fl - 38)]
    d.polygon([(sc(px), sc(py)) for px, py in panel], fill=(196, 184, 156), outline=INK)
    pg.arrow([(x + 40, fl + 6), (x + 32, fl - 18)], RED, 1.7, 5.5)
    pg.badge(x + 14, fl - 46, "A", 8.5)
    pg.text(x + 26, fl - 52, "lift the floor: the well", 8.2, INK, True, room=210)
    # the panel as a table, on its legs, behind the open tailgate
    tx, ty = x + w - 150, base - 52
    d.rectangle([sc(tx), sc(ty), sc(tx + 120), sc(ty + 7)], fill=(196, 184, 156), outline=INK)
    for lx, dx in ((tx + 10, -5), (tx + 110, 5)):
        d.line([sc(lx), sc(ty + 7), sc(lx + dx), sc(base)], fill=INK, width=sc(1.8))
        d.line([sc(lx + dx * 0.5), sc(ty + 28), sc(lx + dx * 0.5 + (12 if dx < 0 else -12)), sc(ty + 28)], fill=INK, width=sc(1.0))
    for i, (cxp, h_) in enumerate(((tx + 30, 12), (tx + 76, 16))):          # a thermos and a mug on it
        d.rounded_rectangle([sc(cxp), sc(ty - h_), sc(cxp + 9), sc(ty)], radius=sc(1.5), fill=(170, 60, 50) if i == 0 else (230, 230, 226), outline=INK, width=sc(0.8))
    pg.badge(tx - 4, ty - 26, "B", 8.5)
    pg.text(tx + 8, ty - 32, "the same panel: a table", 8.2, NAVY, True, room=w - (tx - x) - 12)


# -------------------------------------------------------------------------------------------- handwork
def stamp(pg, cx, cy, angle=-9):
    """A dealer's rubber stamp, a little dry, at an angle (text only, our own)."""
    w, h = 250, 86
    tile = Image.new("RGBA", (sc(w), sc(h)), (0, 0, 0, 0))
    d = ImageDraw.Draw(tile)
    ink = (150, 30, 44, 205)
    d.rounded_rectangle([sc(2), sc(2), sc(w - 2), sc(h - 2)], radius=sc(6), outline=ink, width=sc(2.2))
    d.rounded_rectangle([sc(6), sc(6), sc(w - 6), sc(h - 6)], radius=sc(4), outline=ink, width=sc(0.9))
    d.text((sc(w / 2), sc(22)), "NOLAN'S USED CARS", font=font(15, True), fill=ink, anchor="mm")
    d.text((sc(w / 2), sc(44)), "MULDRAUGH  ·  KENTUCKY", font=font(9, True), fill=ink, anchor="mm")
    d.text((sc(w / 2), sc(64)), "PRE-LOVED CARS   ·   NO LEMONS", font=font(8), fill=ink, anchor="mm")
    rng = np.random.default_rng(93)
    a = np.asarray(tile).copy()
    hole = rng.random(a.shape[:2]) < 0.22
    a[..., 3] = np.where(hole, (a[..., 3] * 0.25).astype(np.uint8), a[..., 3])
    tile = Image.fromarray(a).filter(ImageFilter.GaussianBlur(0.6)).rotate(angle, expand=True, resample=Image.BICUBIC)
    pg.img.alpha_composite(tile, (sc(cx) - tile.width // 2, sc(cy) - tile.height // 2))
    pg.redraw()


def handwriting(pg, x, rules, lines, size=11.5, fill=PEN, tilt=-1.2, seed=7):
    """Ballpoint handwriting, one line per ruled line (y of each rule), each a little off it."""
    f = hand_font(size)
    rng = np.random.default_rng(seed)
    if OVERLAY:                          # each line on its rule, at its own tilt about the 560-wide tile's centre
        for ry, s in zip(rules, lines):
            ang = tilt + float(rng.normal(0, 0.5))
            oy = ry - size * 2.05 - 3 + float(rng.normal(0, 0.8))
            dx, dy = rot(size * 0.6 - 280, size * 2.05 - size * 1.6, ang)
            pg.record(s, x=round(x + 280 + dx, 2), y=round(oy + size * 1.6 + dy, 2), s=round(size * HAND_SCALE, 2),
                      f="SdfCaveat", c=rgba(fill, 0.92), al=0, an=round(ang, 2), mw=R1 - x - 6)
        return
    for ry, s in zip(rules, lines):
        tile = Image.new("RGBA", (sc(560), sc(size * 3.2)), (0, 0, 0, 0))
        ImageDraw.Draw(tile).text((sc(size * 0.6), sc(size * 2.05)), s, font=f, fill=fill + (235,), anchor="ls")
        tile = tile.rotate(tilt + float(rng.normal(0, 0.5)), resample=Image.BICUBIC)
        pg.img.alpha_composite(tile, (sc(x), sc(ry - size * 2.05 - 3 + float(rng.normal(0, 0.8)))))
    pg.redraw()


def note(pg, x, y, s, size=12, angle=-3, fill=PEN, width=None, room=None):
    """A free handwritten note (no rules), optionally wrapped to `width`."""
    f = hand_font(size)
    lines = [s]
    if width:
        lines, cur = [], ""
        for w in s.split():
            t = (cur + " " + w).strip()
            if pg.d.textlength(t, font=f) <= sc(width):
                cur = t
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
    tw_ = max(pg.d.textlength(l, font=f) for l in lines)
    if OVERLAY:                          # the first line's baseline, where the expanded rotated tile put it
        tw, th = tw_ / S + 20, size * 1.45 * len(lines) + size
        a = math.radians(angle)
        tw2, th2 = abs(tw * math.cos(a)) + abs(th * math.sin(a)), abs(tw * math.sin(a)) + abs(th * math.cos(a))
        asc = f.getmetrics()[0] / S
        dx, dy = rot(6 - tw / 2, size * 0.3 + asc - th / 2, angle)
        it = dict(x=round(x + tw2 / 2 + dx, 2), y=round(y + th2 / 2 + dy, 2), s=round(size * HAND_SCALE, 2), f="SdfCaveat",
                  c=rgba(fill, 0.92), al=0, an=angle)
        if width:
            it.update(w=width * 1.1, mh=round(len(lines) * size * 1.45 + size * 0.6, 1), ld=round(1.45 / HAND_SCALE, 3),
                      a0=round(asc * HAND_SCALE, 2))
        else:
            it.update(mw=round(room or tw_ / S * 1.3, 1))
        pg.record(s, **it)
        return
    tile = Image.new("RGBA", (int(tw_) + sc(20), sc(size * 1.45 * len(lines) + size)), (0, 0, 0, 0))
    td = ImageDraw.Draw(tile)
    for i, l in enumerate(lines):
        td.text((sc(6), sc(size * 0.3 + i * size * 1.45)), l, font=f, fill=fill + (235,))
    tile = tile.rotate(angle, expand=True, resample=Image.BICUBIC)
    pg.img.alpha_composite(tile, (sc(x), sc(y)))
    pg.redraw()


def coffee_ring(pg, cx, cy, r=44):
    ring = Image.new("RGBA", (sc(r * 2 + 20), sc(r * 2 + 20)), (0, 0, 0, 0))
    d = ImageDraw.Draw(ring)
    c = sc(r + 10)
    d.ellipse([c - sc(r), c - sc(r), c + sc(r), c + sc(r)], outline=(120, 78, 32, 70), width=sc(3.2))
    d.ellipse([c - sc(r - 2), c - sc(r - 2), c + sc(r - 2), c + sc(r - 2)], outline=(120, 78, 32, 28), width=sc(6))
    pg.img.alpha_composite(ring.filter(ImageFilter.GaussianBlur(1.1)), (sc(cx) - c, sc(cy) - c))
    pg.redraw()


def tape(pg, cx, cy, w=70, h=20, angle=-24):
    """A strip of yellowed clear tape."""
    tile = Image.new("RGBA", (sc(w), sc(h)), (236, 226, 178, 120))
    ImageDraw.Draw(tile).rectangle([0, 0, sc(w) - 1, sc(h) - 1], outline=(200, 186, 130, 120), width=sc(0.6))
    tile = tile.rotate(angle, expand=True, resample=Image.BICUBIC)
    pg.img.alpha_composite(tile, (sc(cx) - tile.width // 2, sc(cy) - tile.height // 2))
    pg.redraw()


def clipping(pg, x, y, w, h, angle=1.6):
    """A magazine clipping taped into the manual: its own paper, drawn on a tile, then placed at a slight angle.
    Returns a Page-like drawing target (the tile) and a function that pastes it."""
    class Clip(Page):
        def __init__(self):
            self.img = Image.new("RGBA", (sc(w), sc(h)), CLIP + (255,))
            rng = np.random.default_rng(42)
            a = np.asarray(self.img).astype(np.float32)
            a[..., :3] += rng.normal(0, 2.0, a.shape[:2])[..., None]
            self.img = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "RGBA")
            self.redraw()
            self.items = []

        def done(self):
            sh = Image.new("RGBA", (self.img.width + sc(16), self.img.height + sc(16)), (0, 0, 0, 0))
            ImageDraw.Draw(sh).rectangle([sc(9), sc(10), sc(9) + self.img.width, sc(10) + self.img.height], fill=(60, 48, 30, 80))
            sh = sh.filter(ImageFilter.GaussianBlur(sc(3)))
            sh.alpha_composite(self.img, (sc(6), sc(6)))
            t = sh.rotate(angle, expand=True, resample=Image.BICUBIC)
            pg.img.alpha_composite(t, (sc(x) - sc(6), sc(y) - sc(6)))
            pg.redraw()
            # its words: from the clipping's own corner to where the expanded rotated tile put them on the page
            sw, sh_ = w + 16, h + 16
            ar = math.radians(angle)
            sw2, sh2 = abs(sw * math.cos(ar)) + abs(sh_ * math.sin(ar)), abs(sw * math.sin(ar)) + abs(sh_ * math.cos(ar))
            for it in self.items:
                dx, dy = rot(it["x"] + 6 - sw / 2, it["y"] + 6 - sh_ / 2, angle)
                it["x"], it["y"] = round(x - 6 + sw2 / 2 + dx, 2), round(y - 6 + sh2 / 2 + dy, 2)
                it["an"] = round(it.get("an", 0) + angle, 2)
                it.pop("af", None)
                pg.items.append(it)
    return Clip()


# ---------------------------------------------------------------------------------------------- spread 1
def spread1():
    pg = Page(1997)
    pg.head("OWNER'S MANUAL", "DRIVING")
    pg.tab("WELCOME")
    # -- p.1: the car and what it does
    pg.text(L0, 54, "Your CRV", 34, NAVY, True, room=L1 - L0)
    pg.text(L0 + 2, 100, "1997 - 2001  ·  four seats  ·  Real Time 4WD  ·  a car that keeps going", 10, MUTED, room=L1 - L0)
    pg.box(L0, 124, L1 - L0, 362)
    hero = lift(cutout("hero/shut_135.png"))
    ox, oy, rw, rh = put_fit(pg, hero, L0 + 30, 132, L1 - L0 - 60, 330)
    calls = [(1, 0.16, 0.57, -34, 14), (2, 0.89, 0.59, 30, 24), (3, 0.57, 0.36, -10, -44), (4, 0.97, 0.40, 24, -14),
             (5, 0.80, 0.27, 6, -52), (6, 0.53, 0.12, -54, -26)]
    for n, fx, fy, dx, dy in calls:
        px, py = ox + rw * fx, oy + rh * fy
        pg.leader(px, py, px + dx, py + dy)
        pg.badge(px + dx, py + dy, n, 10.5)
    legend = [(1, "Engine", 2), (2, "Real Time 4WD", 2), (3, "Rear seats and bed", 3), (4, "Spare wheel", 3),
              (5, "Picnic table, storage well", 4), (6, "Roof rack", 4)]
    lx, ly = L0, 494
    colw = (L1 - L0) / 3
    for i, (n, s, p) in enumerate(legend):
        cx, cy = lx + (i % 3) * colw, ly + (i // 3) * 20
        pg.badge(cx + 8, cy + 8, n, 7.5)
        lab = pg.text(cx + 20, cy + 1.5, s, 8.6, INK, True, room=colw - 58)
        pg.text(cx + 20 + pg.tw(s, 8.6, True) + 6, cy + 2.2, "p. %d" % p, 8, MUTED, after=lab, gap=6)
    # welcome
    y = pg.heading(L0, 548, "Welcome", 438)
    welcome = pg.flow(750)
    welcome.__enter__()
    y = pg.wrap(L0, y, "Thank you for choosing Honda. Your CRV drives like a car on the highway and keeps going when the road "
                "gives out: **Real Time 4WD** sends power to the rear wheels the moment the front ones slip.", 9.6, 438)
    y = pg.wrap(L0, y + 8, "Inside it is more practical than it looks. The rear seats fold into a **flat floor and a bed**, the "
                "cargo floor lifts out as a **picnic table**, and under it is a **storage well** for the things you would rather "
                "keep out of sight.", 9.6, 438)
    y = pg.wrap(L0, y + 8, "Read this manual once, front to back. A driver who knows the car looks after it better, and **every job on "
                "a CRV teaches more** to someone who has read it. Keep it in the glove box.", 9.6, 438)
    welcome.__exit__(None, None, None)
    # at a glance
    gx = L0 + 456
    pg.shadow(gx, 548, L1 - gx, 300, 5, 2, 40)
    pg.box(gx, 548, L1 - gx, 300, (255, 252, 244), RULE)
    pg.text(gx + 14, 560, "AT A GLANCE", 10.5, NAVY, True, room=L1 - gx - 28)
    pg.rule(gx + 14, 577, L1 - 14, 1, NAVY)
    rows = [("seat", "Seats", "Four. Two in the back,\nwhen the seats are up"), ("engine", "Engine", "2.0 liters, twin cam"),
            ("4wd", "Drive", "Real Time 4WD"), ("fuel", "Fuel", "Regular, 58 liters;\nthe filler is on the left"),
            ("box", "Storage", "Cargo area, a well under\nthe floor, a roof rack")]
    yy = 590
    for k, t, v in rows:
        icon(pg, k, gx + 30, yy + 17, 0.95)
        pg.text(gx + 54, yy + 2, t.upper(), 7.2, MUTED, True, room=L1 - gx - 64)
        if OVERLAY:                      # one string a translator can re-break: two lines of room
            pg.wrap(gx + 54, yy + 13, v.replace("\n", " "), 8.8, L1 - gx - 64, INK, True, 12 / 8.8, maxh=25)
        else:
            for j, line in enumerate(v.split("\n")):
                pg.text(gx + 54, yy + 13 + j * 12, line, 8.8, INK, True)
        yy += 50
    # the last owner's note on the welcome page
    note(pg, L0 + 8, 760, "Glove box lid sticks - lift it and pull.  -  R.", 12.5, -2.5, room=425)
    pg.box(L0, 806, 438, 84, (238, 242, 248), NAVY_L, 5)
    icon(pg, "book", L0 + 30, 848, 1.1, bg=(255, 255, 255))
    pg.text(L0 + 58, 820, "KNOW YOUR CAR", 9.5, NAVY, True, room=438 - 72)
    pg.wrap(L0 + 58, 838, "Reading this manual teaches the basics of keeping a car running, and how the CRV goes together. "
            "A mechanic who has read it learns more from every part fitted, removed or repaired on a CRV.", 8.6, 438 - 72, maxh=46)
    # page 1 bottom: what this manual covers
    y = pg.heading(L0, 940, "In this manual", L1 - L0)
    cols = [("1 - 2", "Welcome and driving", "4wd"), ("3 - 4", "Seats and bed, a night in the car, picnic table, storage well, roof", "box"),
            ("5 - 6", "Accessories, off-road equipment, the lift kit, armor, notes", "wrench")]
    cw = (L1 - L0 - 24) / 3
    for i, (p_, s_, k) in enumerate(cols):
        cx = L0 + i * (cw + 12)
        pg.box(cx, y, cw, 74, (255, 252, 244), RULE)
        icon(pg, k, cx + 24, y + 26, 0.9)
        pg.text(cx + 48, y + 12, "PAGES " + p_, 8, RED, True, room=cw - 58)
        pg.wrap(cx + 48, y + 28, s_, 8.6, cw - 58, maxh=40)

    # -- p.2: driving
    y = pg.heading(R0, 54, "Real Time 4WD", R1 - R0, 1, "no lever, nothing to engage")
    car_plan(pg, R0 + 58, y + 6, 66, 150, True, False, False, "DRY ROAD")
    car_plan(pg, R0 + 196, y + 6, 66, 150, True, True, True, "FRONT WHEELS SLIP")
    sx = R0 + 290
    steps = [("Grip", "Most of the time your CRV drives its front wheels: light, quiet, easy on fuel."),
             ("Slip", "On ice, mud or loose gravel the front wheels start to spin."),
             ("All four", "Within moments the rear wheels pull too. When grip comes back, they let go again.")]
    yy = y + 4
    for i, (t, body) in enumerate(steps):
        pg.badge(sx + 9, yy + 9, i + 1, 8.5)
        pg.text(sx + 24, yy + 2, t, 10.5, INK, True, room=R1 - sx - 24)
        yy = pg.wrap(sx + 24, yy + 18, body, 9, R1 - sx - 24, extra=8 if i < 2 else 40) + 10
    y = pg.heading(R0, 300, "Where it goes", R1 - R0, 2, "ground clearance 8.1 in.")
    tiles = [("road", "Paved road", True), ("gravel", "Gravel", True), ("track", "Dirt track", True), ("field", "Field", True),
             ("snow", "Snow", True), ("rocks", "Rocks, deep mud", False)]
    tw_ = (R1 - R0 - 5 * 8) / 6
    for i, (k, lab, ok) in enumerate(tiles):
        terrain(pg, R0 + i * (tw_ + 8), y + 2, tw_, 96, k, lab, ok)
    pg.wrap(R0, y + 110, "The CRV is at home wherever a farm truck would go at a gentle pace. Slow down off the pavement: the springs "
            "are soft and the tires are road tires. For anything rougher, see the lift kit on page 6.", 9, R1 - R0, MUTED, False, 1.34, True,
            extra=50)
    y = pg.heading(R0, 520, "Engine", R1 - R0, 3, "B20B")
    bay = Image.open(src("open/open_045.png")).convert("RGB").crop((1560, 900, 2280, 1420))
    photo(pg, bay, R0, y, 330, 268, "Under the hood: 2.0 liters, four cylinders, twin camshafts.")
    tx = R0 + 348
    rows = [("Engine", "2.0-liter four, twin cam, 16 valves"), ("Fuel", "Regular unleaded, 58-liter tank"),
            ("Filler", "Left side, behind the rear door"), ("Sound", "Quiet at a cruise, a light whine when you rev it")]
    yy = y + 2
    for k, v in rows:
        pg.text(tx, yy, k.upper(), 7.2, MUTED, True, room=R1 - tx)
        yy = pg.wrap(tx, yy + 10, v, 9.2, R1 - tx, INK, True, 1.22) + 6
        pg.rule(tx, yy - 3, R1, 0.7)
    wy = yy + 8
    pg.box(tx, wy, R1 - tx, 74, (250, 232, 226), RED, 4, 1.3)
    pg.d.polygon([(sc(tx + 18), sc(wy + 10)), (sc(tx + 30), sc(wy + 30)), (sc(tx + 6), sc(wy + 30))], fill=RED)
    pg.d.text((sc(tx + 18), sc(wy + 22)), "!", font=font(10, True), fill=(255, 255, 255), anchor="mm")
    pg.text(tx + 40, wy + 9, "LOOK AFTER THE BELT", 9, RED, True, room=R1 - tx - 50)
    pg.wrap(tx + 40, wy + 25, "The timing belt drives the camshafts. If it breaks, the engine is ruined: a worn engine wants a "
            "mechanic before it wants a long trip.", 8.2, R1 - tx - 50, maxh=44)
    # the last owner, on driving
    note(pg, R0 + 10, 862, "Snow on the Louisville road, Jan.  4WD never even blinked.", 12, -1.8, room=R1 - R0 - 20)
    y = pg.heading(R0, 930, "In an emergency", R1 - R0)
    cw = (R1 - R0 - 24) / 3
    for i, (k, t, body) in enumerate((("jack", "Flat tire", "The spare is on the tailgate. You need a jack and a lug wrench."),
                                      ("engine", "Won't start", "Check the battery and the fuel first, then call a mechanic."),
                                      ("weight", "Heavy load", "A full roof and armor make the car slower to stop: brake early."))):
        bx = R0 + i * (cw + 12)
        pg.box(bx, y, cw, 92, (255, 252, 244), RULE)
        icon(pg, k, bx + 26, y + 26, 1.0)
        pg.text(bx + 50, y + 18, t, 10, INK, True, room=cw - 60)
        pg.wrap(bx + 14, y + 52, body, 8.6, cw - 28, maxh=36)
    pg.folio(1, 2, "Welcome  ·  Driving")
    return pg


# ---------------------------------------------------------------------------------------------- spread 2
def spread2():
    pg = Page(1998)
    pg.head("LOAD SPACE", "LOAD SPACE")
    pg.tab("LOAD SPACE")
    # -- p.3: seats and bed; tailgate
    y = pg.heading(L0, 54, "Rear seats: a flat floor and a bed", L1 - L0, 4)
    photo(pg, Image.open(src("folded/view_floor2.png")).convert("RGB").crop((300, 0, 2000, 1440)), L0, y, 300, 236, "The rear seats folded: one long floor.")
    sx = L0 + 318
    diagram_seats(pg, sx, y + 2, L1 - sx, 132)
    yy = pg.wrap(sx, y + 142, "Fold the seatbacks down and tumble the seats: the back of the cabin becomes **one long, flat floor**, "
                 "about twice the cargo area, and **a far better bed** than any back seat.", 9.2, L1 - sx, maxh=100)
    # before you fold: a checklist
    cy = y + 252
    pg.box(L0, cy, L1 - L0, 132, (255, 252, 244), RULE)
    pg.text(L0 + 14, cy + 12, "BEFORE YOU FOLD", 9.5, NAVY, True, room=L1 - L0 - 28)
    checks = [("check", "Both rear seats are in the car"), ("check", "Nothing left on the seats"), ("check", "Nobody sitting in the back"),
              ("cross", "Nobody rides in the back while the seats are folded"), ("check", "Clear the floor before you put them back up")]
    for i, (k, s) in enumerate(checks):
        cx = L0 + 16 + (i % 2) * ((L1 - L0) / 2)
        cyy = cy + 38 + (i // 2) * 30
        icon(pg, k, cx + 10, cyy + 8, 0.72, bg=(255, 255, 255))
        if OVERLAY:                      # a row is 30 tall: a longer translation takes a second line
            pg.wrap(cx + 28, cyy + 1.5, s, 9, (L1 - L0) / 2 - 34, INK, i == 3, 1.2, maxh=23)
        else:
            pg.text(cx + 28, cyy + 1.5, s, 9, INK, i == 3)
    icon(pg, "bed", L1 - 40, cy + 100, 1.15)
    note(pg, L0 + 360, cy + 140, "Slept in it three nights at the lake. Better than the cabin.", 12, -2, room=L1 - L0 - 372)
    y = pg.heading(L0, 610, "A night in your CRV", L1 - L0, 5)
    pg.box(L0, y, 300, 196)
    put_fit(pg, lift(cutout("hero/shut_045.png")), L0 + 12, y + 10, 276, 176)
    cw = (L1 - L0 - 314 - 12) / 2
    tips = [("bed", "Fold the seats", "The flat floor sleeps far better than any seat. Fold it flat before dark."),
            ("lock", "Lock up", "Doors locked, windows up. With armor fitted, the windows stay shut anyway."),
            ("table", "Supper on the table", "Take the picnic table out, and put it back before you drive on."),
            ("can", "Fuel for the morning", "A full jerry can on the rack is a full tank of second chances.")]
    for i, (k, t, body) in enumerate(tips):
        bx = L0 + 314 + (i % 2) * (cw + 12)
        by = y + (i // 2) * 102
        pg.box(bx, by, cw, 94, (255, 252, 244), RULE)
        icon(pg, k, bx + 24, by + 24, 0.95)
        pg.text(bx + 46, by + 17, t, 9.6, INK, True, room=cw - 52)
        pg.wrap(bx + 12, by + 46, body, 8.6, cw - 24, maxh=44)
    yy = y + 222
    pg.box(L0, yy, L1 - L0, 72, (238, 242, 248), NAVY_L, 5)
    icon(pg, "wrench", L0 + 28, yy + 36, 1.0, bg=(255, 255, 255))
    pg.text(L0 + 54, yy + 12, "THE SPARE", 9.5, NAVY, True, room=L1 - L0 - 70)
    pg.wrap(L0 + 54, yy + 30, "The full-size spare rides on the back, under a soft cover if you have one. A jack and a lug wrench "
            "change a wheel; keep the spare inflated.", 8.8, L1 - L0 - 70, maxh=38)
    # -- p.4: table and well; roof
    y = pg.heading(R0, 54, "Picnic table and storage well", R1 - R0, 6)
    diagram_floor(pg, R0, y + 4, R1 - R0, 200)
    y2 = y + 222
    colw = (R1 - R0 - 24) / 2
    pg.badge(R0 + 9, y2 + 9, "A", 8.5)
    pg.text(R0 + 24, y2 + 2, "The storage well", 10.5, INK, True, room=colw - 24)
    pg.wrap(R0 + 24, y2 + 20, "Open the tailgate and **lift the cargo floor**. Under it is a well for the small things you would "
            "rather keep out of sight. Once you know it is there, it is yours to use.", 9, colw - 24, maxh=82)
    bx = R0 + colw + 24
    pg.badge(bx + 9, y2 + 9, "B", 8.5)
    pg.text(bx + 24, y2 + 2, "The picnic table", 10.5, INK, True, room=colw - 24)
    pg.wrap(bx + 24, y2 + 20, "The cargo floor panel has folding legs. **Take it out**, set it up wherever you stop, and **put it "
            "back** before you drive on: it is the floor of your cargo area.", 9, colw - 24, maxh=82)
    note(pg, R0 + 20, y2 + 112, "Legs rattle on gravel - towel under them.", 12, -2.2, room=R1 - R0 - 40)
    y = pg.heading(R0, 470, "Roof rack and jerry cans", R1 - R0, 7)
    roof = Image.open(src("accs/shut_135.png")).convert("RGB")
    photo(pg, roof, R0, y, 340, 270, "The basket carries what will not fit inside.", (0.62, 0.15))
    tx = R0 + 358
    rows = [("weight", "Up to 50 kg in the basket", "Strap it down. What you load shows on the roof, so everyone can see you are "
             "traveling heavy."),
            ("can", "Two jerry cans", "One on the spare, one on the rack. They hold real fuel: a full can is a full tank's "
             "worth of second chances."),
            ("box", "Bolted on", "The rack bolts to the roof rails with a wrench, and comes off the same way.")]
    yy = y + 2
    for i, (k, t, body) in enumerate(rows):
        icon(pg, k, tx + 16, yy + 16, 0.95)
        pg.text(tx + 40, yy + 4, t, 9.6, INK, True, room=R1 - tx - 40)
        yy = pg.wrap(tx + 40, yy + 21, body, 8.6, R1 - tx - 40, extra=8 if i < 2 else 60) + 12
    note(pg, R0 + 6, 806, "Muldraugh to Louisville: half a tank with the roof loaded.", 12, -1.6, room=R1 - R0 - 20)
    y = pg.heading(R0, 870, "Load space at a glance", R1 - R0)
    cells = [("Cargo area", "behind the rear seats"), ("Load floor", "seats folded: about twice as much"),
             ("Storage well", "under the cargo floor"), ("Glove box", "this manual lives here"), ("Roof", "rack, up to 50 kg")]
    cw = (R1 - R0 - 32) / 5
    for i, (t, v) in enumerate(cells):
        cx = R0 + i * (cw + 8)
        pg.box(cx, y, cw, 80, (255, 252, 244), RULE)
        pg.text(cx + 10, y + 10, t, 9, NAVY, True, room=cw - 16)
        pg.wrap(cx + 10, y + 28, v, 8.4, cw - 20, INK, maxh=46)
    pg.folio(3, 4, "Load space")
    return pg


# ---------------------------------------------------------------------------------------------- spread 3
def spread3():
    pg = Page(1999)
    pg.head("ACCESSORIES", "MODIFICATIONS")
    pg.tab("ACCESSORIES")
    # -- p.5: genuine accessories, off-road equipment
    y = pg.heading(L0, 54, "Honda Genuine Accessories", L1 - L0, 8, "from your dealer")
    pg.box(L0, y, L1 - L0, 300)
    accs = lift(cutout("accs/shut_135.png"))
    ox, oy, rw, rh = put_fit(pg, accs, L0 + 20, y + 8, 420, 284)
    for n, fx, fy, dx, dy in (("1", 0.12, 0.70, -26, 22), ("2", 0.62, 0.12, 28, -24), ("3", 0.33, 0.37, -40, -26),
                              ("4", 0.58, 0.46, 30, 20)):
        px_, py_ = ox + rw * fx, oy + rh * fy
        pg.leader(px_, py_, px_ + dx, py_ + dy)
        pg.badge(px_ + dx, py_ + dy, n, 9.5)
    items = [("1", "Bull bar", "wrench"), ("2", "Roof rack", "wrench"), ("3", "Windshield guard", "screwdriver"),
             ("4", "Window guards", "screwdriver"), ("", "Rear glass guard", "screwdriver"), ("", "Spare tire cover", "hand")]
    tx = L0 + 460
    pg.text(tx, y + 12, "PART", 7.2, MUTED, True, room=120)
    pg.text(L1 - 12, y + 12, "FITS WITH", 7.2, MUTED, True, "ra", room=110)
    yy = y + 30
    for n, s, tool in items:
        if n:
            pg.badge(tx + 8, yy + 11, n, 7.5)
        pg.text(tx + 22, yy + 4, s, 9.2, INK, True, room=L1 - tx - 70)
        icon(pg, tool, L1 - 30, yy + 11, 0.62)
        yy += 36
        pg.rule(tx, yy - 6, L1 - 10, 0.6)
    pg.wrap(tx, yy + 2, "Guards keep the glass in one piece. Everything comes off again with the same tool.", 8.4, L1 - tx - 12, MUTED, False, 1.32, True,
            extra=14)
    y = pg.heading(L0, 420, "Off-road equipment", L1 - L0, 9, "aftermarket")
    pg.box(L0, y, L1 - L0, 330)
    off = lift(cutout("offroad/shut_135.png"))
    ox, oy, rw, rh = put_fit(pg, off, L0 + 10, y + 10, 400, 300)
    for n, fx, fy, dx, dy in (("1", 0.25, 0.33, -40, -34), ("2", 0.12, 0.88, -26, 18), ("5", 0.82, 0.12, 30, -14)):
        px_, py_ = ox + rw * fx, oy + rh * fy
        pg.leader(px_, py_, px_ + dx, py_ + dy)
        pg.badge(px_ + dx, py_ + dy, n, 9.5)
    back = lift(cutout("offroad/shut_315.png"))
    bx_ = L0 + 418
    ox2, oy2, rw2, rh2 = put_fit(pg, back, bx_, y + 12, L1 - bx_ - 10, 150)
    for n, fx, fy, dx, dy in (("3", 0.22, 0.86, -22, 12), ("4", 0.56, 0.62, 26, 14), ("5", 0.10, 0.62, -22, -12)):
        px_, py_ = ox2 + rw2 * fx, oy2 + rh2 * fy
        pg.leader(px_, py_, px_ + dx, py_ + dy)
        pg.badge(px_ + dx, py_ + dy, n, 8.5)
    rows = [("1", "Snorkel", "up the right pillar, the intake at the roof"), ("2", "Skid plate", "steel, under the engine"),
            ("3", "Rear steel bumper", "with a hitch for a trailer"), ("4", "Roof ladder", "up the right rear corner"),
            ("5", "Jerry cans", "on the spare and on the rack")]
    yy = y + 172
    for n, t, v in rows:
        pg.badge(bx_ + 8, yy + 8, n, 7.5)
        pg.text(bx_ + 22, yy + 1, t, 9, INK, True, room=L1 - bx_ - 30)
        pg.text(bx_ + 22, yy + 14, v, 7.8, MUTED, room=L1 - bx_ - 30)
        yy += 30
    pg.wrap(L0, y + 340, "Each piece **bolts on and comes off again**. The parts can be bought, found, or made at a workbench by "
            "anyone handy with a wrench.", 9, L1 - L0, extra=30)
    gy = 830
    y = pg.heading(L0, gy, "Getting the parts", L1 - L0)
    cw = (L1 - L0 - 24) / 3
    for i, (k, t, body) in enumerate((
            ("box", "Found", "Garages, mechanics' shelves and parts crates turn them up, and a CRV may come with some fitted."),
            ("wrench", "Made", "A workbench, scrap metal and the know-how. The off-road parts need only a little mechanics."),
            ("book", "Learned", "The plans are in the magazines: \"4x4 Off-Road: CRV Edition\" and \"Survival Armor\"."))):
        bx = L0 + i * (cw + 12)
        pg.box(bx, y, cw, 128, (255, 252, 244), RULE)
        icon(pg, k, bx + 26, y + 26, 1.0)
        pg.text(bx + 50, y + 18, t, 10, INK, True, room=cw - 60)
        pg.wrap(bx + 14, y + 52, body, 8.6, cw - 28, maxh=68)
    note(pg, L0 + 14, 1036, "Ladder: stand on the bumper, not the tire.", 12, -2, room=L1 - L0 - 30)

    # -- p.6: the lift kit ad, the armour clipping, the notes
    ax0, ay0, aw, ah = R0, 54, R1 - R0, 448
    pg.shadow(ax0, ay0, aw, ah, 3, 3, 55)
    pg.d.rectangle([sc(ax0), sc(ay0), sc(ax0 + aw), sc(ay0 + ah)], fill=(250, 248, 240), outline=INK, width=sc(1.2))
    pg.d.rectangle([sc(ax0), sc(ay0), sc(ax0 + aw), sc(ay0 + 62)], fill=NAVY)
    pg.text(ax0 + 18, ay0 + 10, "KESTREL TRAIL CLAW", 9, (200, 210, 230), True, room=aw - 200)
    pg.text(ax0 + 18, ay0 + 24, "3-INCH LIFT FOR THE CRV", 22, (255, 255, 255), True, room=aw - 190)
    pg.text(ax0 + aw - 16, ay0 + 20, "30 x 9.50 R15", 14, (240, 210, 120), True, "ra", room=140)
    pg.text(ax0 + aw - 16, ay0 + 40, "ALL-TERRAIN", 9, (200, 210, 230), True, "ra", room=140)
    alloy = lift(cutout("offroad/shut_135.png"))
    steel = lift(cutout("steel/shut_135.png"))
    put_fit(pg, alloy, ax0 + 10, ay0 + 72, aw / 2 - 10, 170)
    put_fit(pg, steel, ax0 + aw / 2, ay0 + 72, aw / 2 - 10, 170)
    pg.text(ax0 + aw / 4, ay0 + 246, "on the EX alloys", 9, NAVY, True, "ma", room=aw / 2 - 20)
    pg.text(ax0 + aw * 3 / 4, ay0 + 246, "or on black steel wheels", 9, NAVY, True, "ma", room=aw / 2 - 20)
    pg.rule(ax0 + 16, ay0 + 266, ax0 + aw - 16, 0.8)
    pg.wrap(ax0 + 18, ay0 + 276, "Longer springs, spacers and shocks lift the body **3 inches**, and four 30-inch **all-terrain** tires "
            "fill the arches. Ruts, fields and washed-out roads stop being a problem.", 9.2, aw / 2 + 30, maxh=96)
    kx = ax0 + aw / 2 + 64
    pg.text(kx, ay0 + 278, "FITTING TAKES", 7.6, MUTED, True, room=ax0 + aw - kx - 14)
    tool_row(pg, kx - 6, ay0 + 290, ["jack", "lug", "wrench"], ["Jack", "Lug wrench", "Wrench"], 0.85)
    pg.wrap(kx, ay0 + 346, "and an **experienced mechanic**. Engine off, everyone out, open ground.", 8.4, ax0 + aw - kx - 14, maxh=34)
    pg.box(ax0 + 16, ay0 + 382, aw - 32, 52, (255, 246, 214), (210, 180, 100), 3)
    pg.wrap(ax0 + 28, ay0 + 390, "**Changed your mind?** The lift comes off again and you keep the kit. **Build your own:** see "
            "\"4x4 Off-Road: CRV Edition\" on the magazine rack.", 8.8, aw - 56, maxh=40)
    # the armour clipping, taped in
    cx0, cy0, cw_, ch_ = R0 + 6, 530, 420, 326
    clip = clipping(pg, cx0, cy0, cw_, ch_, 1.4)
    clip.d.rectangle([0, 0, sc(cw_), sc(30)], fill=(40, 40, 44))
    clip.text(12, 6, "SURVIVAL ARMOR", 14, (230, 200, 90), True, room=230)
    clip.text(cw_ - 10, 9, "STEEL FOR YOUR CRV", 8, (220, 220, 220), True, "ra", room=150)
    arm = lift(cutout("armour/shut_045.png"))
    r = fit(arm, 220, 150)
    clip.paste(r, 10, 40)
    pts = [("Door plates", "welded steel over each door"), ("Window mesh", "expanded metal over the glass"),
           ("Arch guards", "bands round every wheel"), ("Rear glass plate", "with a slot to see out")]
    yy = 42
    for t, v in pts:
        clip.text(242, yy, t, 9, INK, True, room=cw_ - 252)
        clip.text(242, yy + 13, v, 7.6, MUTED, room=cw_ - 252)
        yy += 34
    clip.rule(10, 196, cw_ - 10, 0.8, (150, 150, 150))
    clip.wrap(12, 204, "**Armored windows stay shut**, and nothing gets an arm in. The steel takes the hits and **wears down** as it "
              "does; patch it before it goes. Every plate makes the car **heavier**: slower away, longer to stop.", 8.8, cw_ - 24, maxh=60)
    clip.wrap(12, 268, "Weld the pieces at a workbench (metalworking and some mechanics), bolt them on with a wrench and a "
              "screwdriver.", 8.2, cw_ - 24, MUTED, False, 1.3, True, maxh=46)
    clip.done()
    tape(pg, cx0 + 30, cy0 + 4, 74, 20, -28)
    tape(pg, cx0 + cw_ - 24, cy0 + ch_ - 6, 74, 20, -24)
    note(pg, R0 + 436, 560, "Plates done at Al's, Oct.", 12.5, 6, width=130)
    pg.arrow([(R0 + 470, 610), (R0 + 440, 640), (R0 + 420, 660)], PEN, 1.4, 5)
    note(pg, R0 + 432, 700, "check the plates after every run", 11.5, 4, width=130)
    # service record, short
    sy = 890
    pg.text(R0, sy, "SERVICE RECORD", 8.5, MUTED, True, room=R1 - R0 - 260)
    pg.rule(R0, sy + 14, R1, 0.9, INK)
    rules = [sy + 40 + i * 28 for i in range(5)]
    for ry in rules:
        pg.rule(R0, ry, R1, 0.6, (176, 184, 198))
    handwriting(pg, R0 + 4, rules, [
        "Oil + filter  -  87,340 mi  (Al's Auto Shop, Muldraugh)",
        "Timing belt + water pump at 84k  -  receipt in glove box",
        "Spare on the tailgate: check it too",
        "Storage well: spare keys, flashlight, the good tape",
        "If it ever won't start, the key sticks: jiggle, don't force.",
    ], 11.5)
    stamp(pg, R1 - 120, sy + 66, -8)
    coffee_ring(pg, R1 - 40, 790, 34)
    pg.text(R0, H - 23, "Part No. 31S10 G00   ·   Printed in Japan", 7, MUTED, room=360)
    pg.folio(5, 6, "Accessories  ·  Modifications")
    return pg


def nav_icons():
    """The page buttons' icons for the manual's window: a navy disc with an arrow (64 x 64, drawn at 4x)."""
    for name, sign in (("prev", -1), ("next", 1)):
        n = 256
        im = Image.new("RGBA", (n, n), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.ellipse([8, 8, n - 8, n - 8], fill=(232, 224, 200, 255), outline=(22, 42, 84, 255), width=14)
        cx = n / 2
        pts = [(cx + sign * 40, cx), (cx - sign * 26, cx - 56), (cx - sign * 26, cx + 56)]
        d.polygon(pts, fill=(22, 42, 84, 255))
        im.resize((64, 64), Image.LANCZOS).save(NAV[name])


# ---------------------------------------------------------------------------------------------- the game's fonts
def game_dir():
    for base in (ROOT, os.path.dirname(HERE)):
        try:
            with open(os.path.join(base, "local_paths.json"), encoding="utf-8") as f:
                g = json.load(f).get("game")
            if g and os.path.isdir(g):
                return g
        except (OSError, ValueError):
            pass
    return None


# the SDF fonts' common metrics (media/fonts/*.fnt, 42.21), used when the game is not installed here
FONT_DEFAULTS = {"SdfRegular": (32, 35, 45), "SdfBold": (32, 35, 45), "SdfItalic": (32, 35, 45),
                 "SdfBoldItalic": (32, 35, 45), "SdfCaveat": (32, 31, 41)}
FNT_FILES = {"SdfRegular": "sdfRegular", "SdfBold": "sdfBold", "SdfItalic": "sdfItalic", "SdfBoldItalic": "sdfBoldItalic",
             "SdfCaveat": "sdfCaveat"}


class Fnt:
    """An AngelCode .fnt as AngelCodeFont reads it: chars, kerning, pages (the SDF in the PNG's alpha)."""

    def __init__(self, name, gdir=None):
        gdir = gdir or game_dir()
        self.dir = os.path.join(gdir, "media", "fonts")
        self.chars, self.kern, self.pages, self._img = {}, {}, {}, {}
        with open(os.path.join(self.dir, FNT_FILES[name] + ".fnt"), encoding="utf-8") as f:
            for line in f:
                tag, _, rest = line.strip().partition(" ")
                kv = dict(re.findall(r'(\w+)=("[^"]*"|\S+)', rest))
                if tag == "info":
                    self.size = int(kv["size"])
                elif tag == "common":
                    self.line_height, self.base = int(kv["lineHeight"]), int(kv["base"])
                elif tag == "page":
                    self.pages[int(kv["id"])] = kv["file"].strip('"')
                elif tag == "char":
                    self.chars[int(kv["id"])] = tuple(int(kv[k]) for k in ("x", "y", "width", "height", "xoffset", "yoffset",
                                                                          "xadvance", "page"))
                elif tag == "kerning":
                    self.kern[(int(kv["first"]), int(kv["second"]))] = int(kv["amount"])

    def width(self, s):
        """AngelCodeFont.getWidth(s): kerning + advances, the last character's glyph width; the widest line."""
        best = cur = 0
        prev = None
        for i, ch in enumerate(s):
            c = ord(ch)
            if c == 10:
                cur = 0
                continue
            d = self.chars.get(c)
            if d is None:
                continue
            if prev is not None:
                cur += self.kern.get((prev, c), 0)
            prev = c
            cur += d[2] if i == len(s) - 1 else d[6]
            best = max(best, cur)
        return best

    def page(self, i):
        if i not in self._img:
            im = Image.open(os.path.join(self.dir, self.pages[i]))
            a = np.asarray(im.convert("RGBA"))[..., 3] if im.mode in ("RGBA", "LA", "P") else np.asarray(im.convert("L"))
            if a.max() == 0:
                a = np.asarray(im.convert("L"))
            self._img[i] = a.astype(np.float32) / 255.0
        return self._img[i]


def font_metrics():
    g = game_dir()
    out = {}
    for name in SDF_FONTS:
        if g:
            f = Fnt(name, g)
            out[name] = (f.size, f.base, f.line_height)
        else:
            out[name] = FONT_DEFAULTS[name]
    return out


# ---------------------------------------------------------------------------------------------- generated files
def _lua(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        v = round(float(v), 3)
        return str(int(v)) if v == int(v) else repr(v)
    if isinstance(v, str):
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(v, (list, tuple)):
        return "{ " + ", ".join(_lua(x) for x in v) + " }"
    return "{ " + ", ".join("%s = %s" % (k, _lua(v[k])) for k in sorted(v)) + " }"


def layout_lua(spreads):
    fm = font_metrics()
    out = ["-- GENERATED by scripts/manual_art.py (do not edit): the boxes the owner's manual's words are laid into",
           "-- over its art (client/HondaCRVGen1_FunctionMenu.lua, M.manualWords). Per string: k its translation id",
           "-- (Print_Text_CRVGen1_ManualPage_<k>), x / y where its first line's baseline starts (page px, 1616 x 1131),",
           "-- s its size, f the SDF font, c its colour, al 0 / 0.5 / 1 left / centre / right, an its angle (degrees),",
           "-- w the width it wraps to and mh the room it may fill (else one line, mw wide at the most), ld the line step,",
           "-- a0 the first line's ascent, vm: y is the line's middle, af / g: it follows string af on its line, g apart.",
           "HondaCRVGen1 = HondaCRVGen1 or {}",
           "HondaCRVGen1.ManualLayout = {",
           "    fonts = {"]
    for name in SDF_FONTS:
        em, base, lh = fm[name]
        out.append("        %s = { em = %d, base = %d, lh = %d }," % (name, em, base, lh))
    out.append("    },")
    out.append("    spreads = {")
    for items in spreads:
        out.append("        {")
        for it in items:
            out.append("            %s," % _lua(it))
        out.append("        },")
    out.append("    },")
    out.append("}")
    return "\n".join(out) + "\n"


def write_generated(spreads):
    os.makedirs(os.path.dirname(LAYOUT_LUA), exist_ok=True)
    with open(LAYOUT_LUA, "w", encoding="utf-8", newline="\n") as f:
        f.write(layout_lua(spreads))
    with open(STRINGS_JSON, "w", encoding="utf-8", newline="\n") as f:
        json.dump({KEY_PREFIX + k: v for k, v in _STRINGS.items()}, f, indent=4, ensure_ascii=False)
        f.write("\n")
    return [LAYOUT_LUA, STRINGS_JSON]


def draw_spreads():
    """The three spreads: (art at 2x, its overlaid strings)."""
    reset_strings()
    out = []
    for fn in (spread1, spread2, spread3):
        pg = fn()
        crease = Image.new("RGBA", pg.img.size, (0, 0, 0, 0))
        ImageDraw.Draw(crease).line([sc(W - 140), 0, sc(W), sc(120)], fill=(90, 80, 60, 26), width=sc(1.2))
        pg.img.alpha_composite(crease.filter(ImageFilter.GaussianBlur(1.0)))
        out.append((pg.img, pg.items))
    return out


def build():
    outs = []
    spreads = draw_spreads()
    for (img, _items), out in zip(spreads, OUTS):
        im = img.convert("RGB").resize((SHIP_W, SHIP_H), Image.LANCZOS)   # see Format: 16 MB, not 64
        os.makedirs(os.path.dirname(out), exist_ok=True)
        im.save(out, optimize=True)
        outs.append(out)
    if OVERLAY:
        outs += write_generated([items for _img, items in spreads])
    nav_icons()
    return outs


# ---------------------------------------------------------------------------------------------- the game, simulated
def pseudo(s):
    """A German-like pseudo-translation, ~40% longer: every word stretched, umlauts in, the **runs** kept."""
    def word(m):
        w = m.group(0)
        if len(w) <= 2 or not w.isalpha():
            return w
        ext = w + ("ung" if len(w) % 3 == 0 else "en" if len(w) % 3 == 1 else "lich")
        return ext.replace("a", "ä", 1).replace("o", "ö", 1).replace("u", "ü", 1)
    return re.sub(r"[A-Za-z]+", word, s)


def lua_words(lang="en", strings=None):
    """Run FunctionMenu.lua's layout under lupa (lua_harness: Kahlua's Lua 5.1, no next) with the game's .fnt metrics
    as TextManager.MeasureStringX: the data strings the window would get, one per spread."""
    import sys
    sys.path.insert(0, HERE)
    from lua_harness import Side
    strings = dict(strings if strings is not None else json.load(open(STRINGS_JSON, encoding="utf-8")))
    if lang == "pseudo":
        strings = {k: pseudo(v) for k, v in strings.items()}
    fonts = {n: Fnt(n) for n in SDF_FONTS}
    side = Side("sp")
    side.L.globals().PY_MEASURE = lambda name, s: fonts[name].width(s)
    side.L.globals().PY_TEXT = lambda k: strings.get(k, k)
    side.run("""
        getText = function(k) return PY_TEXT(k) end
        getTextManager = function() return { MeasureStringX = function(self, f, s) return PY_MEASURE(f, s) end,
                                             getFontHeight = function(self, f) return 20 end } end
        UIFont = { FromString = function(n) return n end }
        ISVehicleMenu = { FillMenuOutsideVehicle = function() end, showRadialMenuOutside = function() end }
        ISWorldObjectContextMenu = {}
        HondaCRVGen1 = { Function = { MANUAL_SPREADS = {}, KNOW_HOW = "K" }, Shared = {} }
    """)
    side.load("client/HondaCRVGen1_ManualLayout.lua", "client/HondaCRVGen1_FunctionMenu.lua")
    return [side.eval("HondaCRVGen1.Function.Menu.manualWords(%d)" % i) for i in (1, 2, 3)], fonts


def parse_elements(data):
    """Vanilla's PrintMedia.lua parse of the data string's text elements."""
    out = []
    for val in data.split("<"):
        if not val:
            continue
        head, _, text = val.partition(">")
        params = {}
        for kv in head.split(","):
            k, _, v = kv.partition(":")
            params[k.strip()] = v.strip()
        if params.get("type") == "text":
            out.append((params, text.replace("^", "\n")))
    return out


def draw_sdf(canvas, fonts, params, text, scale):
    """AtomUIText.drawText for one element on a float RGB canvas whose pixels are `scale` page px each: the glyph quads
    (pen + xoffset, yoffset, kerning, xadvance), the element's scale and angle, sdf.frag's smoothstep with the
    threshold getSdfThreshold gives (0.125 / screen px per font px), bilinear sampling of the SDF page."""
    f = fonts[params["font"]]
    k = float(params.get("scaleX", 1))
    ang = math.radians(float(params.get("angle", 0)))
    ca, sa = math.cos(ang), math.sin(ang)
    ex, ey = float(params["x"]), float(params["y"])
    col = np.array([float(params.get(c, 1)) for c in "rgb"], np.float32)
    alpha = float(params.get("a", 1))
    thr = 0.125 / (k * scale)
    H_, W_ = canvas.shape[:2]
    pen, prev = 0.0, None
    for ch in text:
        c = ord(ch)
        d = f.chars.get(c)
        if d is None:
            continue
        if prev is not None:
            pen += f.kern.get((prev, c), 0)
        prev = c
        gx, gy, gw, gh, xo, yo, xa, pg_ = d
        if gw > 0 and gh > 0:
            # the quad's corners in screen px
            def S_(lx, ly):
                lx, ly = lx * k, ly * k
                return ((ex + ca * lx + sa * ly) * scale, (ey - sa * lx + ca * ly) * scale)
            q = [S_(pen + xo, yo), S_(pen + xo + gw, yo), S_(pen + xo + gw, yo + gh), S_(pen + xo, yo + gh)]
            x0, x1 = int(max(0, math.floor(min(p[0] for p in q)))), int(min(W_ - 1, math.ceil(max(p[0] for p in q))))
            y0, y1 = int(max(0, math.floor(min(p[1] for p in q)))), int(min(H_ - 1, math.ceil(max(p[1] for p in q))))
            if x1 >= x0 and y1 >= y0:
                yy, xx = np.mgrid[y0:y1 + 1, x0:x1 + 1].astype(np.float32) + 0.5
                # screen -> element local -> glyph texel
                X, Y = xx / scale - ex, yy / scale - ey
                lx, ly = (ca * X - sa * Y) / k, (sa * X + ca * Y) / k
                u, v = lx - (pen + xo), ly - yo
                inside = (u >= 0) & (u < gw) & (v >= 0) & (v < gh)
                tex = f.page(pg_)
                tu, tv = np.clip(gx + u - 0.5, 0, tex.shape[1] - 1.001), np.clip(gy + v - 0.5, 0, tex.shape[0] - 1.001)
                iu, iv = np.floor(tu).astype(int), np.floor(tv).astype(int)
                fu, fv = tu - iu, tv - iv
                dist = (tex[iv, iu] * (1 - fu) * (1 - fv) + tex[iv, iu + 1] * fu * (1 - fv) + tex[iv + 1, iu] * (1 - fu) * fv
                        + tex[iv + 1, iu + 1] * fu * fv)
                t = np.clip((dist - (0.5 - thr)) / (2 * thr), 0, 1)
                a = (t * t * (3 - 2 * t)) * inside * alpha
                region = canvas[y0:y1 + 1, x0:x1 + 1]
                region[:] = region * (1 - a[..., None]) + col * a[..., None]
        pen += xa


def preview(lang="en", screen=1440, out_dir=None, before=False, crop=None):
    """Simulated screenshots of the three spreads as the print media window shows them on a `screen` px tall screen
    (PrintMedia.lua updateSize: the 1616 x 1131 spread fitted to 0.8 x the screen height). before=True: the art as
    master shipped it (git HEAD's textures, words baked in)."""
    out_dir = out_dir or os.path.join(ROOT, "build", "manual_preview")
    os.makedirs(os.path.dirname(out_dir + os.sep), exist_ok=True)
    scale = screen * 0.8 / H
    size = (int(round(W * scale)), int(round(H * scale)))
    paths = []
    datas, fonts = (None, None) if before else lua_words(lang)
    for i, tex in enumerate(OUTS):
        img = Image.open(tex if not before else before[i]).convert("RGB").resize(size, Image.BILINEAR)
        canvas = np.asarray(img).astype(np.float32) / 255.0
        if datas:
            for params, text in parse_elements(datas[i]):
                draw_sdf(canvas, fonts, params, text, scale)
        im = Image.fromarray(np.clip(canvas * 255 + 0.5, 0, 255).astype(np.uint8))
        name = "spread%d_%s_%d.png" % (i + 1, "before" if before else lang, screen)
        p = os.path.join(out_dir, name)
        im.save(p)
        paths.append(p)
    return paths


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--lang", default="en", choices=("en", "pseudo"))
    ap.add_argument("--screen", type=int, default=1440)
    ap.add_argument("--out")
    a = ap.parse_args()
    if a.preview:
        for p in preview(a.lang, a.screen, a.out):
            print("WROTE", p)
    else:
        for p in build():
            print("WROTE", p, "%.2f MB" % (os.path.getsize(p) / 1e6))
