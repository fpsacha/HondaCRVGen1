r"""
The roof-rack cargo's painted detail (2026-10-13). After the in-game round on the planar
build: "is it possible to have better texture, not resolution but just better texture with more
details?" His 32.png showed the rack's tote, duffel, bedroll and straps as flat colour blocks: the
cargo carried PolyHaven grain at a flat factor, its own AO and nothing drawn, at ~0.7 texels/cm.

    import cargo_paint; cargo_paint.paint(out_dir[, z0])      # writes the PNGs (build_accessories)
    TEXTURED.update(cargo_paint.layers())                      # the bake's layer stacks (bake_atlas)

What this module owns:
  * LAYOUT: where every piece of cargo sits and its sizes. build_accessories.build_rack_loads builds
    the three fill states from these numbers and the decals below project onto the same metres, so
    the two can never drift apart. Every piece sits in the same place in every state it appears in
    (2026-10-13; the duffel and the bedroll used to move between states), because a decal is pinned
    to model space and cannot follow a piece that moves.
  * paint(): one PNG per (material, view): a top view (u = x, v = y), a side view (u = y, v = z) and
    a front view (u = x, v = z), in model metres at PX_PER_M. Every feature is a function of the 3D
    point on the piece it belongs to (a seam at a height, a zip at an offset from the bag's centre
    line, a label on a wall panel), so two views agree wherever their normal gates meet, and nothing
    is hand-painted.
  * layers(): the TEXTURED stacks for AccCanvas, AccTarp, AccTote, AccLid and AccStrap: those views
    as "replace" decals gated by the face normal (and by y where two pieces of one material overlap
    in a view), then the cargo's own AO (acc_shade, build_accessories._shade).

How it is drawn (KI5's hand-painted rack and armour pieces, scratch ki5/: flat base, a light line on
upper edges, a dark line or soft shadow under overhangs, dark recesses with a light lower lip,
small dark dots for fixings): signed distance fields, anti-aliased over a pixel, then a Gaussian
prefilter. Sizes are for the game, not the PNG: the cargo bakes at ~1.4 texels/cm (TEXEL_W_SEEN on
the 2048 shell, build_accessories._texel_weights; it was 0.7), ~2.3 screen px a texel at the author's
326 px/m, and the default 512 cap box-quarters that to ~0.35 texels/cm. So the lines (piping, zips,
seams, rib edges, 4-7 mm) are soft one-texel lines at 2048 and fade at the cap, and the shapes that
carry the look (pocket, label, stacking pads, latches, handle pockets, the spiral, the straps'
labels) are >= ~1.5-3 cm; fabric grain is mottling at 1.5-5 cm, never per-texel noise (playbook:
grain that reads as fabric in a render reads as concrete at the game's zoom). Decals are
point-sampled by the colour bake (playbook), so the maps are drawn at 4x the destination density and
prefiltered to half a destination texel.

Runs inside Blender (numpy only; PIL is not in Blender's Python) and in any interpreter: the PNG
writer below is plain zlib.

Model space: metres, +X vehicle right, +Y forward, +Z up, ground at z 0.
"""
import math
import os
import struct
import zlib

import numpy as np

# ------------------------------------------------------------------------------------------------
# layout (build_accessories.build_rack_loads builds from these)

# top of the basket's floor tubes: acc_roofrack rack_floor 1.7554 (2026-10-13 build) + 0.0095 (the
# floor tubes' r 0.0075 sitting 2 mm over the frame centre). build_rack_loads writes the value it
# used into each load object as cargo_z0 and layers() reads it back, so a moved basket stays in register
Z0_DEFAULT = 1.7649
Z0_PROP = "cargo_z0"

# soft bags (build_accessories._bag): a flat-bottomed body lofted through BAG_STATIONS, each station
# the section BAG_PROF (v / w across, z / h up) scaled about mid-height; end panels at scale 0.78
BAG_PROF = [(0.30, 0.0), (0.50, 0.28), (0.47, 0.68), (0.20, 1.0),
            (-0.20, 1.0), (-0.47, 0.68), (-0.50, 0.28), (-0.30, 0.0)]          # counter-clockwise
BAG_END_S, BAG_RIM_S = 0.78, 0.97      # end panel / piped rim scale of the section
BAG_BIND = 0.012                       # the piped binding: the last 12 mm of the bag at each end
STRAP_U = 0.15                         # girth straps and handle ends at +-0.15 m along the bag


def bag_stations(L):
    """(u along the bag, section scale, sag of the top) from end to end."""
    return [(-L, BAG_END_S, 0.0), (-L + BAG_BIND, BAG_RIM_S, 0.0), (-STRAP_U, 1.0, 0.0), (0.0, 1.03, -0.012),
            (STRAP_U, 1.0, 0.0), (L - BAG_BIND, BAG_RIM_S, 0.0), (L, BAG_END_S, 0.0)]


# The duffel: olive canvas along y, two girth straps, a pair of carry handles joined by a wrap over
# a centre zip, a zip pocket on each side, piped end panels with a webbing loop. In every state.
DUFFEL = dict(xc=-0.24, yc=-1.245, along="y", length=0.60, w=0.30, h=0.25, zip_v=0.0, slider=True,
              straps=True, pocket=True, stripe=False, handles="wrap")
# The kit bag: charcoal nylon across the basket in front of the tote (load 3), no girth straps, two
# handles either side of the ratchet strap that runs down its middle, the zip on its front shoulder
# (the strap would hide a centre zip), a light reflective stripe along each side.
KITBAG = dict(xc=0.0, yc=-0.78, along="x", length=0.56, w=0.26, h=0.22, zip_v=-0.066, slider=False,
              straps=False, pocket=False, stripe=True, handles="pair")
# The tote: an 18-gallon ribbed storage tote (charcoal walls, mustard lid), long axis along y.
TOTE = dict(xc=0.20, yc=-1.245, a=0.20, b=0.29)
TOTE_TAPER, TOTE_R, TOTE_LIP = 0.018, 0.045, 0.018
TOTE_Z1, TOTE_Z2, TOTE_Z3, TOTE_SINK = 0.255, 0.268, 0.296, 0.008     # wall top, lid joint, rim top, sunk panel (above z0)
TOTE_RIM = 0.026                       # the lid's flat rim, inward from the lip; then an 8 mm slope down to the panel
TOTE_RIBS_X = (-0.19, 0.0, 0.19)       # ribs on the long walls (along y from the centre)
TOTE_RIBS_Y = (-0.12, 0.12)            # ribs on the end walls (along x)
TOTE_RIB_HALF, TOTE_RIB_OUT = 0.010, 0.012
TOTE_HANDLE = (0.08, 0.006, 0.035, 0.028, 0.002)   # half width, in / out of the end wall, below / above the lip
TOTE_LATCH_Y = (-0.10, 0.10)           # clip latches on each long side
TOTE_LATCH = (0.022, 0.006, 0.010, 0.012, 0.006)   # half width, into / out of the lip, below the lip, under the rim top
# The bedroll: a rolled blue foam mat across the front of the basket, cinched by two black straps
# with cam buckles. In loads 2 and 3 (at -0.66 in load 2 until 2026-10-13).
BEDROLL = dict(yc=-0.535, x0=-0.33, x1=0.33, r=0.10, sides=16)
BEDROLL_STRAPS = (-0.17, 0.17)
BEDROLL_PINCH = 0.93                   # the roll's scale under its straps
BEDROLL_END_S = 0.80                   # the rolled ends' rim, round the sunk core
BEDROLL_EDGE = 70.0                    # degrees from +y up: where the mat's last layer ends along the roll
FOAM_T = 0.015                         # the mat's thickness: the spiral's pitch at the ends
# Ratchet straps (load 3): (y, ratchet x). The first sits behind the duffel's girth strap and its
# handles (y -1.395 .. -1.095) so its orange band (y +-STRAP_BAND) holds nothing else in any state
# (it ran at -1.27 across the handles until 2026-10-13); the second runs down the kit bag's middle.
STRAPS = ((-1.455, 0.12), (-0.78, 0.15))
STRAP_HALF = 0.0175                    # 35 mm webbing
STRAP_BAND = 0.0185                    # the orange gate: the webbing and 1 mm
WEB_HALF = 0.016                       # the bags' and the bedroll's black webbing (32 mm)
RAIL_X = 0.47                          # the basket's top rail (build_accessories.RK_XW)
HOOK_IN = 0.030                        # the strap's stitched end loop stops this far inside the rail
# the ratchet (build_accessories._ratchet): a steel frame on the webbing, a spool of wound webbing
# across it SPOOL_DT along the run from the ratchet's centre, a steel handle folded over it
RATCHET_L, RATCHET_W = 0.100, 0.050
SPOOL_R, SPOOL_HALF, SPOOL_DT = 0.014, 0.020, -0.015

# ------------------------------------------------------------------------------------------------
# palette (sRGB): the old flat tints' levels (olive (86, 88, 54), blue (39, 63, 103), charcoal 82,
# mustard (188, 148, 42), orange (196, 92, 28)), which read right in game; the detail sits on them

C = {
    "canvas": (96, 98, 60), "canvas_base": (64, 62, 42), "canvas_pipe": (40, 41, 31),
    "zip": (33, 33, 30), "teeth": (132, 130, 120), "slider": (176, 176, 170), "tag": (182, 178, 162),
    "kit": (74, 76, 80), "kit_base": (46, 47, 50), "kit_pipe": (28, 28, 30), "kit_stripe": (158, 160, 158),
    "kit_patch": (150, 44, 38),
    "tote": (80, 82, 86), "tote_light": (108, 110, 114), "tote_dark": (52, 53, 56), "recess": (24, 24, 26),
    "paper": (216, 212, 198), "label_band": (170, 46, 38), "ink": (56, 56, 58),
    "lid": (198, 154, 42), "lid_light": (228, 188, 78), "lid_dark": (146, 108, 24),
    "foam": (42, 70, 116), "foam_cut": (68, 98, 144), "foam_gap": (16, 26, 46),
    "web": (36, 36, 38), "web_edge": (64, 64, 66), "orange": (210, 100, 28), "orange_edge": (160, 68, 18),
    "strap_label": (228, 228, 218), "strap_label_band": (42, 72, 152),
}

# texel weight of the cargo faces the game camera sees (build_accessories._texel_weights). Measured on
# the shell pack, 2026-10-13: weight 1 landed the sheet at scale 0.938 (panels 2.83 texels/cm, faces
# 52 %; the cargo ~1.4 texels/cm, ~2.3 screen px a texel at 326 px/m) and weight 2 at 0.833 (panels
# 2.51, the cargo ~2.6): the pack always fills the sheet, so weight 2 cost every panel of the car 9 %
# of its density for a crisper cargo that only shows with the rack loaded. The detail reads at 1.
TEXEL_W_SEEN = 1.0
DEST_TPC = 1.5 * 0.93 * TEXEL_W_SEEN   # planar_uv.FALLBACK_TPC x the pack's usual scale x the weight
PX_PER_M = 600                         # 6 px/cm: 4x the cargo's texels (the colour bake point-samples decals)
BAKE_SS = 2                            # bake_atlas.SUPERSAMPLE: the colour bake samples at 2x the sheet's density
BLUR_SIGMA = 0.5 * PX_PER_M / (100.0 * DEST_TPC * BAKE_SS)   # px: half a BAKE texel (playbook: dashed rings;
                                       # half a SHIPPED texel, 2.15 px, until the 2026-10-13 texture fix)


def _lin(c):
    c = np.asarray(c, dtype=np.float64) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def _srgb(c):
    c = np.clip(c, 0.0, 1.0)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1.0 / 2.4) - 0.055)


# ------------------------------------------------------------------------------------------------
# drawing


def _write_png(path, rgb8):
    """8-bit RGB PNG, rows top-down; plain zlib (no PIL in Blender's Python)."""
    h, w, _c = rgb8.shape
    raw = b"".join(b"\x00" + rgb8[r].tobytes() for r in range(h))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def _blur(a, sigma):
    if sigma <= 0:
        return a
    r = int(math.ceil(3 * sigma))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    for axis in (0, 1):
        pad = [(0, 0)] * a.ndim
        pad[axis] = (r, r)
        p = np.pad(a, pad, mode="edge")
        out = np.zeros_like(a)
        for i, kv in enumerate(k):
            sl = [slice(None)] * a.ndim
            sl[axis] = slice(i, i + a.shape[axis])
            out += kv * p[tuple(sl)]
        a = out
    return a


def _perm(seed):
    rng = np.random.RandomState(seed)
    return rng.permutation(256), rng.rand(256)


def noise(U, V, scale, seed, octaves=2):
    """Smooth value noise in -1..1 at `scale` metres a cell (octaves halve it), deterministic."""
    total, amp, norm = np.zeros_like(U), 1.0, 0.0
    for o in range(octaves):
        perm, val = _perm(seed * 7 + o)
        gu, gv = U / scale * 2 ** o + 17.3 * o, V / scale * 2 ** o + 5.1 * o
        iu, iv = np.floor(gu).astype(np.int64), np.floor(gv).astype(np.int64)
        fu, fv = gu - iu, gv - iv
        fu, fv = fu * fu * (3 - 2 * fu), fv * fv * (3 - 2 * fv)

        def h(i, j):
            return val[perm[(perm[i & 255] + j) & 255]]
        a = h(iu, iv) * (1 - fu) + h(iu + 1, iv) * fu
        b = h(iu, iv + 1) * (1 - fu) + h(iu + 1, iv + 1) * fu
        total += amp * (2.0 * (a * (1 - fv) + b * fv) - 1.0)
        norm += amp
        amp *= 0.5
    return total / norm


def sd_box(U, V, cu, cv, hu, hv, r=0.0):
    """Signed distance to a rounded box centred (cu, cv), half sizes hu, hv, corner radius r."""
    qx = np.abs(U - cu) - (hu - r)
    qy = np.abs(V - cv) - (hv - r)
    return np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0) - r


def sd_seg(U, V, a, b):
    """Distance to the segment a-b."""
    ax, ay = a
    dx, dy = b[0] - ax, b[1] - ay
    t = np.clip(((U - ax) * dx + (V - ay) * dy) / max(dx * dx + dy * dy, 1e-12), 0, 1)
    return np.hypot(U - ax - t * dx, V - ay - t * dy)


def sd_poly(U, V, pts):
    """Signed distance (exact inside, a little short outside the corners) to a convex
    counter-clockwise polygon."""
    d = np.full(U.shape, -1e9)
    n = len(pts)
    for i in range(n):
        (x0, y0), (x1, y1) = pts[i], pts[(i + 1) % n]
        ex, ey = x1 - x0, y1 - y0
        ln = math.hypot(ex, ey) or 1e-9
        d = np.maximum(d, ((U - x0) * ey - (V - y0) * ex) / ln)       # right of the edge = outside
    return d


def smooth(a, b, x):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


class Sheet:
    """One decal: u along model axis `au` from a0, v along `av` from b0, PX_PER_M pixels a metre,
    painted in linear RGB, row 0 at v = b0 (the bake samples (0, 0) at the image's bottom left)."""

    def __init__(self, name, au, a0, a1, av, b0, b1):
        self.name, self.au, self.av = name, au, av
        self.w = int(math.ceil((a1 - a0) * PX_PER_M))
        self.h = int(math.ceil((b1 - b0) * PX_PER_M))
        self.a0, self.b0 = a0, b0
        self.a1, self.b1 = a0 + self.w / PX_PER_M, b0 + self.h / PX_PER_M
        self.px = 1.0 / PX_PER_M
        self._grid = None
        self.rgb = None

    @property
    def png(self):
        return "cargo_%s.png" % self.name

    def axes(self):
        return (self.au, self.a0, self.a1), (self.av, self.b0, self.b1)

    def grid(self):
        if self._grid is None:
            u = self.a0 + (np.arange(self.w) + 0.5) * self.px
            v = self.b0 + (np.arange(self.h) + 0.5) * self.px
            self._grid = np.meshgrid(u, v)
        return self._grid

    def fill(self, col):
        self.rgb = np.empty((self.h, self.w, 3))
        self.rgb[:] = _lin(col)

    def cov(self, sdf, soft=0.0):
        """Anti-aliased coverage of sdf <= 0 (soft: extra feather in metres)."""
        return np.clip(0.5 - sdf / (self.px + soft), 0.0, 1.0)

    def _full(self, a):
        return np.broadcast_to(np.asarray(a, dtype=np.float64), (self.h, self.w))

    def put(self, mask, col, k=1.0):
        """Blend toward col by mask x k (masks: bool or 0..1 arrays, or scalars)."""
        m = self._full(np.asarray(mask, dtype=np.float64) * np.asarray(k, dtype=np.float64))[..., None]
        self.rgb = self.rgb * (1 - m) + _lin(col) * m

    def mul(self, mask, f):
        """Multiply by f where mask (1 + (f - 1) x mask)."""
        k = (np.asarray(f, dtype=np.float64) - 1.0) * np.asarray(mask, dtype=np.float64)
        self.rgb = self.rgb * (1.0 + self._full(k))[..., None]

    def scale(self, f):
        self.rgb = self.rgb * self._full(f)[..., None]

    def save(self, out_dir):
        rgb = _blur(self.rgb, BLUR_SIGMA)
        img = (np.round(_srgb(rgb) * 255.0)).astype(np.uint8)[::-1]      # row 0 of a PNG is the top
        path = os.path.join(out_dir, self.png)
        _write_png(path, np.ascontiguousarray(img))
        return path


def _fold(U, V, p0, p1, width, dark, light, offset):
    """Multiplier of a fabric fold from p0 to p1: a dark crease and a light ridge beside it,
    tapered at both ends."""
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    ln2 = dx * dx + dy * dy
    t = ((U - p0[0]) * dx + (V - p0[1]) * dy) / ln2
    perp = ((U - p0[0]) * -dy + (V - p0[1]) * dx) / math.sqrt(ln2)
    taper = np.where((t > 0) & (t < 1), np.sin(np.pi * np.clip(t, 0, 1)), 0.0)
    core = np.exp(-(perp / width) ** 2) * taper
    ridge = np.exp(-((perp - offset) / width) ** 2) * taper
    return (1 - dark * core) * (1 + light * ridge)


def _folds(U, V, seeds, spots):
    """Product of folds: spots = [(u0, u1, v0, v1, n, dir_u, spread, length range)], a cluster of n
    folds starting in the box (u0..u1, v0..v1), heading along dir_u (+1 / -1 in u) within +-spread
    radians, each a random length in the range."""
    f = np.ones_like(U)
    rng = np.random.RandomState(seeds)
    for u0, u1, v0, v1, n, du, spread, (l0, l1) in spots:
        for _k in range(n):
            pu, pv = rng.uniform(u0, u1), rng.uniform(v0, v1)
            ang = rng.uniform(-spread, spread)
            ln = rng.uniform(l0, l1)
            q = (pu + du * ln * math.cos(ang), pv + ln * math.sin(ang))
            f *= _fold(U, V, (pu, pv), q, rng.uniform(0.0045, 0.0065), rng.uniform(0.10, 0.17),
                       rng.uniform(0.04, 0.08), rng.choice((-1, 1)) * 0.010)
    return f


# ------------------------------------------------------------------------------------------------
# the sheets (extents in model metres; build them through sheets(z0) so paint() and layers() agree)


def _bag_half(bag):
    return bag["length"] / 2.0


def sheets(z0):
    d, k, t, b = DUFFEL, KITBAG, TOTE, BEDROLL
    Ld = _bag_half(d)
    ta, tb = t["a"] + TOTE_LIP + 0.04, t["b"] + TOTE_HANDLE[2] + 0.03
    S = [
        Sheet("canvas_top", "x", d["xc"] - 0.18, d["xc"] + 0.18, "y", d["yc"] - Ld - 0.02, d["yc"] + Ld + 0.02),
        Sheet("canvas_side", "y", d["yc"] - Ld - 0.02, d["yc"] + Ld + 0.02, "z", z0 - 0.01, z0 + d["h"] + 0.04),
        Sheet("canvas_front", "x", d["xc"] - 0.18, d["xc"] + 0.18, "z", z0 - 0.01, z0 + d["h"] + 0.04),
        # tote walls (y < -0.915) and the kit bag's ends (y > -0.915) share AccTote's side view
        Sheet("tote_side", "y", t["yc"] - tb, k["yc"] + k["w"] / 2 + 0.03, "z", z0 - 0.01, z0 + TOTE_Z3 + 0.01),
        Sheet("tote_front", "x", t["xc"] - ta, t["xc"] + ta, "z", z0 - 0.01, z0 + TOTE_Z3 + 0.01),
        Sheet("kit_front", "x", k["xc"] - _bag_half(k) - 0.02, k["xc"] + _bag_half(k) + 0.02, "z", z0 - 0.01, z0 + k["h"] + 0.04),
        Sheet("tote_top", "x", k["xc"] - _bag_half(k) - 0.02, t["xc"] + ta, "y", t["yc"] - tb, k["yc"] + k["w"] / 2 + 0.03),
        Sheet("lid_top", "x", t["xc"] - ta, t["xc"] + ta, "y", t["yc"] - tb, t["yc"] + tb),
        Sheet("lid_side", "y", t["yc"] - tb, t["yc"] + tb, "z", z0 + TOTE_Z1 - 0.03, z0 + TOTE_Z3 + 0.01),
        Sheet("lid_front", "x", t["xc"] - ta, t["xc"] + ta, "z", z0 + TOTE_Z1 - 0.03, z0 + TOTE_Z3 + 0.01),
        Sheet("tarp_top", "x", b["x0"] - 0.02, b["x1"] + 0.02, "y", b["yc"] - b["r"] - 0.02, b["yc"] + b["r"] + 0.02),
        Sheet("tarp_front", "x", b["x0"] - 0.02, b["x1"] + 0.02, "z", z0 - 0.01, z0 + 2 * b["r"] + 0.02),
        Sheet("tarp_side", "y", b["yc"] - b["r"] - 0.02, b["yc"] + b["r"] + 0.02, "z", z0 - 0.01, z0 + 2 * b["r"] + 0.02),
        Sheet("strap_top", "x", -RAIL_X - 0.05, RAIL_X + 0.05, "y", -1.62, -0.40),
        Sheet("strap_side", "y", -1.62, -0.40, "z", z0 - 0.03, z0 + 0.36),
        Sheet("strap_front", "x", -RAIL_X - 0.05, RAIL_X + 0.05, "z", z0 - 0.03, z0 + 0.36),
        Sheet("strap_orange", "x", -RAIL_X - 0.05, -RAIL_X - 0.04, "y", -1.62, -1.61),   # a flat swatch
    ]
    return {s.name: s for s in S}


# ------------------------------------------------------------------------------------------------
# bags


def bag_section(bag, s, sag=0.0):
    """The bag's section at scale s as (v, z above the floor), counter-clockwise."""
    w, h = bag["w"], bag["h"]
    return [(pv * w * s, h / 2 + (pz * h - h / 2) * s + (sag if pz > 0.9 else 0.0)) for pv, pz in BAG_PROF]


def _bag_cols(bag):
    if bag is DUFFEL:
        return dict(base=C["canvas"], low=C["canvas_base"], pipe=C["canvas_pipe"], zip=C["zip"], teeth=C["teeth"],
                    slider=C["slider"], web=C["web"], tag=C["tag"], seed=11)
    return dict(base=C["kit"], low=C["kit_base"], pipe=C["kit_pipe"], zip=C["zip"], teeth=C["teeth"],
                slider=C["slider"], web=C["web"], tag=C["kit_patch"], seed=23)


def _bag_v_at(bag, zz):
    """|v| of the bag's side at height zz (the section's right half at scale 1)."""
    w, h = bag["w"], bag["h"]
    return np.interp(zz, [0.0, 0.28 * h, 0.68 * h, h], [0.30 * w, 0.50 * w, 0.47 * w, 0.20 * w])


def _bag_z_at(bag, av):
    """Height of the bag's upper surface at |v|: the flat top panel, then the shoulder."""
    w, h = bag["w"], bag["h"]
    return np.interp(av, [0.0, 0.20 * w, 0.47 * w, 0.50 * w], [h, h, 0.68 * h, 0.28 * h])


def _bag_shading(bag, u, av, zz, seed):
    """Mottling and form of a bag's skin as a function of the 3D point (u along, |v| across, zz up),
    so the top and side views agree where their normal gates meet on the shoulders: fabric
    mottling at 5 and 1.5 cm (no per-texel grain), lighter toward the top (KI5's tops are lighter)."""
    f = 1 + 0.03 * noise(u, av, 0.05, seed) + 0.03 * noise(u, zz, 0.05, seed + 1) + 0.02 * noise(u, av + zz, 0.015, seed + 2)
    return f * (0.88 + 0.14 * smooth(0.0, bag["h"], zz))


def _bag_top(sh, bag, inside):
    """Top view of a bag (only where `inside`): bag frame u along, v across."""
    X, Y = sh.grid()
    if bag["along"] == "y":
        u, v = Y - bag["yc"], X - bag["xc"]
    else:
        u, v = X - bag["xc"], bag["yc"] - Y
    L, w = _bag_half(bag), bag["w"]
    c = _bag_cols(bag)
    rgb0 = sh.rgb.copy()
    sh.put(inside, c["base"])
    av = np.abs(v)
    f = _bag_shading(bag, u, av, _bag_z_at(bag, av), c["seed"])
    vt = 0.20 * w                                          # the top panel's edge (section point (0.20, 1.0))
    f *= 1 + 0.05 * (1 - smooth(vt - 0.012, vt, av))       # the flat top panel catches the light
    # folds where the girth straps cinch the canvas and where the body gathers into the end panels,
    # kept off the shoulders (|v| < 0.37 w) where the side view takes over
    spots = []
    if bag["straps"]:
        for su in (-STRAP_U, STRAP_U):
            for du in (-1, 1):
                spots.append((su + du * 0.022, su + du * 0.030, -0.30 * w, 0.30 * w, 4, du, 0.35, (0.04, 0.08)))
    else:
        for su in (-STRAP_U, STRAP_U):
            spots.append((su - 0.03, su + 0.03, -0.25 * w, 0.25 * w, 3, 1 if su < 0 else -1, 0.5, (0.04, 0.07)))
    for e in (-1, 1):
        spots.append((e * (L - 0.035), e * (L - 0.025), -0.28 * w, 0.28 * w, 4, -e, 0.25, (0.03, 0.06)))
    spots.append((-0.08, 0.08, -0.25 * w, 0.25 * w, 2, 1, 0.5, (0.06, 0.10)))   # the sag mid-length
    f *= _folds(u, v, c["seed"] + 5, spots)
    sh.rgb = np.where(inside[..., None], sh.rgb * f[..., None], sh.rgb)
    # piping along the top panel's edges: a dark cord with a light line on its inner side
    body = np.abs(u) < L - BAG_BIND
    for side in (-1, 1):
        d = np.abs(v - side * vt)
        sh.put(inside & body, c["pipe"], sh.cov(d - 0.003))
        sh.mul(inside & body, 1 + 0.10 * sh.cov(np.abs(v - side * (vt - 0.007)) - 0.0018))
    # the piped seams round the end panels (at the rim, BAG_BIND from each end), the rounded band
    # beyond them a shade darker
    sh.put(inside, c["pipe"], sh.cov(np.abs(np.abs(u) - (L - BAG_BIND)) - 0.0035))
    sh.mul(inside, 1 + 0.12 * sh.cov(np.abs(np.abs(u) - (L - BAG_BIND - 0.006)) - 0.0018))
    sh.mul(inside, 1 - 0.10 * sh.cov(L - BAG_BIND + 0.0035 - np.abs(u)))
    # zip: dark tape, a grey line of teeth, tape ends; the slider and its pull tab (geometry over them)
    zv = bag["zip_v"]
    if zv is not None:
        ue = L - 0.045
        tape = sd_box(u, v, 0.0, zv, ue, 0.011, 0.004)
        sh.put(inside, c["zip"], sh.cov(tape))
        sh.put(inside, c["teeth"], sh.cov(sd_box(u, v, 0.0, zv, ue - 0.012, 0.0028)))
        for e in (-1, 1):
            sh.put(inside, c["pipe"], sh.cov(sd_box(u, v, e * (ue - 0.006), zv, 0.008, 0.012, 0.002)))
        if bag["slider"]:
            us = L - 0.09
            sh.put(inside, c["pipe"], sh.cov(sd_box(u, v, us, zv, 0.0135, 0.0095, 0.003)))
            sh.put(inside, c["slider"], sh.cov(sd_box(u, v, us, zv, 0.011, 0.007, 0.003)))
            sh.put(inside, c["web"], sh.cov(sd_box(u, v, us + 0.030, zv, 0.018, 0.006, 0.003)))
    # handle patches where the kit bag's handles are sewn on (the duffel's ride its girth straps)
    if not bag["straps"]:
        for su in (-STRAP_U, STRAP_U):
            for sv in (-0.045, 0.045):
                box = sd_box(u, v, su, sv, 0.022, 0.018, 0.003)
                sh.put(inside, c["pipe"], sh.cov(box))
                thread = np.abs(sd_box(u, v, su, sv, 0.016, 0.012)) - 0.0018
                diag = np.minimum(sd_seg(u, v, (su - 0.016, sv - 0.012), (su + 0.016, sv + 0.012)),
                                  sd_seg(u, v, (su - 0.016, sv + 0.012), (su + 0.016, sv - 0.012))) - 0.0016
                sh.mul(inside, 1 + 0.9 * sh.cov(np.minimum(thread, diag)) * sh.cov(box))
    sh.rgb = np.where(inside[..., None], sh.rgb, rgb0)


def _bag_long(sh, bag, inside, uu, zz):
    """A bag's long side (only where `inside`): uu along the bag from its centre, zz above the floor."""
    L, h = _bag_half(bag), bag["h"]
    c = _bag_cols(bag)
    rgb0 = sh.rgb.copy()
    sh.put(inside, c["base"])
    f = _bag_shading(bag, uu, _bag_v_at(bag, zz), zz, c["seed"])
    spots = []                                             # folds below the shoulder (zz < 0.6 h)
    if bag["straps"]:
        for su in (-STRAP_U, STRAP_U):
            for du in (-1, 1):
                spots.append((su + du * 0.022, su + du * 0.028, 0.10 * h, 0.55 * h, 3, du, 0.45, (0.03, 0.06)))
    for e in (-1, 1):
        spots.append((e * (L - 0.035), e * (L - 0.025), 0.15 * h, 0.55 * h, 3, -e, 0.3, (0.03, 0.05)))
    f *= _folds(uu, zz, c["seed"] + 7, spots)
    sh.rgb = np.where(inside[..., None], sh.rgb * f[..., None], sh.rgb)
    # the reinforced base panel below the widest line, piped along its top
    zb = 0.28 * h
    sh.put(inside, c["low"], sh.cov(zz - zb))
    sh.put(inside, c["pipe"], sh.cov(np.abs(zz - zb) - 0.003))
    sh.mul(inside, 1 + 0.10 * sh.cov(np.abs(zz - zb - 0.007) - 0.0018))
    if bag["straps"]:                                      # the canvas in the girth straps' shadow
        for su in (-STRAP_U, STRAP_U):
            sh.mul(inside, 1 - 0.12 * smooth(0.032, WEB_HALF, np.abs(uu - su)))
    if bag["pocket"]:                                      # a zip pocket between the straps
        pz0, pz1 = zb + 0.012, 0.66 * h
        pocket = sd_box(uu, zz, 0.0, (pz0 + pz1) / 2, 0.105, (pz1 - pz0) / 2, 0.012)
        sh.mul(inside, 1 - 0.14 * sh.cov(np.abs(zz - pz0 + 0.008) - 0.006) * sh.cov(np.abs(uu) - 0.10))   # its shadow
        sh.mul(inside, 1 + 0.05 * sh.cov(pocket))
        sh.put(inside, c["pipe"], sh.cov(np.abs(pocket) - 0.0025))
        sh.put(inside, c["zip"], sh.cov(sd_box(uu, zz, 0.0, pz1 - 0.011, 0.09, 0.006)))
        sh.put(inside, c["teeth"], sh.cov(sd_box(uu, zz, 0.0, pz1 - 0.011, 0.085, 0.0018)))
        sh.put(inside, c["web"], sh.cov(sd_box(uu, zz, 0.07, pz1 - 0.030, 0.006, 0.016, 0.004)))
        sh.put(inside, c["slider"], sh.cov(sd_box(uu, zz, 0.07, pz1 - 0.011, 0.009, 0.006, 0.002)))
    if bag["stripe"]:                                      # reflective piping stripe, a rubber patch below it
        zs = 0.56 * h
        sh.put(inside & (np.abs(uu) < L - BAG_BIND), c["pipe"], sh.cov(np.abs(zz - zs) - 0.011))
        sh.put(inside & (np.abs(uu) < L - BAG_BIND - 0.004), C["kit_stripe"], sh.cov(np.abs(zz - zs) - 0.007))
        patch = sd_box(uu, zz, 0.13, 0.38 * h, 0.032, 0.015, 0.004)
        sh.put(inside, c["tag"], sh.cov(patch))
        sh.mul(inside, 1 - 0.30 * sh.cov(np.abs(patch) - 0.002))
        sh.put(inside, C["kit_stripe"], sh.cov(sd_box(uu, zz, 0.13, 0.38 * h, 0.018, 0.0035)))
    sh.put(inside, c["pipe"], sh.cov(np.abs(np.abs(uu) - (L - BAG_BIND)) - 0.0035))     # the end seams (see _bag_top)
    sh.mul(inside, 1 + 0.12 * sh.cov(np.abs(np.abs(uu) - (L - BAG_BIND - 0.006)) - 0.0018))
    sh.mul(inside, 1 - 0.10 * sh.cov(L - BAG_BIND + 0.0035 - np.abs(uu)))
    sh.rgb = np.where(inside[..., None], sh.rgb, rgb0)


def _bag_end(sh, bag, inside, vv, zz):
    """A bag's end panel (only where `inside`): vv across the bag, zz above the floor."""
    c = _bag_cols(bag)
    h = bag["h"]
    rgb0 = sh.rgb.copy()
    rim = sd_poly(vv, zz, bag_section(bag, BAG_RIM_S))
    end = sd_poly(vv, zz, bag_section(bag, BAG_END_S))
    sh.put(inside, c["base"])
    f = (1 + 0.04 * noise(vv, zz, 0.05, c["seed"] + 4)) * (0.88 + 0.14 * smooth(0.0, h, zz)) * 0.95   # a panel of its own, a shade darker
    sh.rgb = np.where(inside[..., None], sh.rgb * f[..., None], sh.rgb)
    # the piped seam where the end panel meets the body (the rim; the rounded band inside it is the
    # end panel's own cloth): a dark cord with a light line just inside it. The whole band painted
    # dark read as a heavy black octagon at the game's zoom (v1, 2026-10-13)
    sh.put(inside, c["pipe"], sh.cov(np.abs(rim + 0.003) - 0.0035))
    sh.mul(inside, 1 + 0.12 * sh.cov(np.abs(rim + 0.009) - 0.0018))
    sh.mul(inside, 1 - 0.10 * sh.cov(-end) * sh.cov(rim + 0.006))           # the rounded edge turning away
    # end panel: a webbing carry loop with stitched ends, and a small sewn tag below it
    zc0, zc1 = 0.32 * h, 0.70 * h
    sh.put(inside, c["web"], sh.cov(sd_box(vv, zz, 0.0, (zc0 + zc1) / 2, 0.015, (zc1 - zc0) / 2, 0.003)) * sh.cov(end))
    for zc in (zc0 + 0.014, zc1 - 0.014):
        thread = np.abs(sd_box(vv, zz, 0.0, zc, 0.011, 0.010)) - 0.0016
        sh.mul(inside, 1 + 1.2 * sh.cov(thread) * sh.cov(end))
    sh.put(inside, c["tag"], sh.cov(sd_box(vv, zz, 0.0, 0.20 * h, 0.026, 0.009, 0.002)) * sh.cov(end))
    sh.rgb = np.where(inside[..., None], sh.rgb, rgb0)


# ------------------------------------------------------------------------------------------------
# tote


def _tote_wall(sh, along, zz, ribs, half, label, wall_handle):
    """A tote wall seen straight on: `along` the wall from its centre, zz above the floor; ribs at
    those offsets; a paper label (True) or a moulded label plate; the recessed handle on the ends."""
    sh.fill(C["tote"])
    f = 1 + 0.03 * noise(along, zz, 0.04, 31) + 0.015 * noise(along, zz, 0.012, 32)
    f *= 0.92 + 0.12 * smooth(0.0, TOTE_Z1, zz)            # moulded plastic: lighter toward the rim
    sh.scale(f)
    # foot band and the moulded reinforcement band under the lip
    sh.put(1.0, C["tote_dark"], sh.cov(zz - 0.014))
    sh.mul(1.0, 1 + 0.25 * sh.cov(np.abs(zz - 0.016) - 0.002))
    sh.mul(1.0, 1 + 0.07 * sh.cov(-(zz - 0.215)) * sh.cov(zz - TOTE_Z1))
    sh.put(1.0, C["tote_dark"], sh.cov(np.abs(zz - 0.213) - 0.0025))
    sh.mul(1.0, 1 + 0.18 * sh.cov(np.abs(zz - (TOTE_Z1 - 0.004)) - 0.002))
    # the lip's outer face (above the wall top): a light upper edge
    sh.mul(1.0, 1 + 0.06 * sh.cov(-(zz - TOTE_Z1)))
    sh.mul(1.0, 1 + 0.22 * sh.cov(np.abs(zz - (TOTE_Z2 - 0.003)) - 0.002))
    # ribs: the proud face lighter, a highlight down one edge, a soft shadow beside the other
    for c in ribs:
        rib = sh.cov(np.abs(along - c) - TOTE_RIB_HALF) * sh.cov(zz - TOTE_Z1)
        sh.mul(1.0, 1 + 0.10 * rib)
        sh.mul(1.0, 1 + 0.25 * sh.cov(np.abs(along - (c - TOTE_RIB_HALF + 0.0025)) - 0.002) * sh.cov(zz - TOTE_Z1))
        sh.mul(1.0, 1 - 0.30 * smooth(0.010, 0.0, along - (c + TOTE_RIB_HALF)) * (along > c + TOTE_RIB_HALF)
               * sh.cov(zz - TOTE_Z1))
    # scuffs: a few light scratches low on the wall
    rng = np.random.RandomState(37 if label else 41)
    for _k in range(5):
        p = (rng.uniform(-half + 0.05, half - 0.05), rng.uniform(0.03, 0.17))
        a = rng.uniform(-0.5, 0.5)
        ln = rng.uniform(0.025, 0.06)
        q = (p[0] + ln * math.cos(a), p[1] + ln * math.sin(a))
        sh.mul(1.0, 1 + 0.18 * sh.cov(sd_seg(along, zz, p, q) - 0.0016))
    if label:                                              # printed paper label between two ribs
        cu, cz, hu, hz = 0.095, 0.135, 0.060, 0.040
        sh.put(1.0, C["tote_dark"], sh.cov(sd_box(along, zz, cu, cz - 0.003, hu + 0.002, hz + 0.002, 0.004)))   # its edge shadow
        sh.put(1.0, C["paper"], sh.cov(sd_box(along, zz, cu, cz, hu, hz, 0.003)))
        sh.put(1.0, C["label_band"], sh.cov(sd_box(along, zz, cu, cz + hz - 0.010, hu - 0.004, 0.0065, 0.002)))
        for i, (wu, dz) in enumerate(((0.085, 0.012), (0.065, -0.004), (0.075, -0.018))):
            sh.put(1.0, C["ink"], sh.cov(sd_box(along, zz, cu - hu + 0.008 + wu / 2, cz + dz, wu / 2, 0.0032)))
        sh.put(1.0, C["ink"], sh.cov(sd_box(along, zz, cu + hu - 0.018, cz - hz + 0.016, 0.010, 0.010, 0.002)))
        sh.put(1.0, C["paper"], sh.cov(np.abs(sd_box(along, zz, cu + hu - 0.018, cz - hz + 0.016, 0.0055, 0.0055)) - 0.0015))
    else:                                                  # moulded label plate: a sunk panel with a bevel
        plate = sd_box(along, zz, 0.0, 0.11, 0.07, 0.045, 0.008)
        sh.mul(1.0, 1 - 0.14 * sh.cov(plate))
        sh.mul(1.0, 1 - 0.30 * sh.cov(np.abs(plate) - 0.003) * (zz > 0.11))
        sh.mul(1.0, 1 + 0.28 * sh.cov(np.abs(plate) - 0.003) * (zz <= 0.11))
    if wall_handle:                                        # recessed handle: a dark pocket under the grip
        hw, _hin, _hout, hdown, hup = TOTE_HANDLE
        z_lo = TOTE_Z1 - hdown
        pocket = sd_box(along, zz, 0.0, z_lo - 0.017, hw - 0.006, 0.017, 0.010)
        sh.put(1.0, C["recess"], sh.cov(pocket))
        sh.mul(1.0, 1 + 0.6 * sh.cov(np.abs(zz - (z_lo - 0.035)) - 0.002) * sh.cov(np.abs(along) - (hw - 0.012)))
        grip = sd_box(along, zz, 0.0, TOTE_Z1 - (hdown - hup) / 2, hw, (hdown + hup) / 2)
        sh.put(1.0, C["tote"], sh.cov(grip))
        sh.mul(1.0, 1 + 0.20 * sh.cov(np.abs(zz - (TOTE_Z1 + hup - 0.003)) - 0.002) * sh.cov(grip))
        sh.mul(1.0, 1 - 0.35 * sh.cov(np.abs(zz - (z_lo + 0.003)) - 0.0022) * sh.cov(grip))
        for fx in (-0.045, -0.015, 0.015, 0.045):           # finger grooves
            sh.mul(1.0, 1 - 0.20 * sh.cov(np.abs(along - fx) - 0.002) * sh.cov(grip + 0.005))
    # latch shadows on the long walls, just under the lip
    return sh


def paint_tote(S, z0):
    t, k = TOTE, KITBAG
    # side view: the tote's long walls (y < -0.915) and the kit bag's ends (y > -0.915)
    sh = S["tote_side"]
    Y, Z = sh.grid()
    zz = Z - z0
    _tote_wall(sh, Y - t["yc"], zz, TOTE_RIBS_X, t["b"], True, False)
    for ly in TOTE_LATCH_Y:                                # the latches' shadows on the moulded band
        sh.mul(1.0, 1 - 0.30 * sh.cov(sd_box(Y - t["yc"], zz, ly, TOTE_Z1 - 0.020, TOTE_LATCH[0], 0.006, 0.004), 0.004))
    kit = (Y > -0.915)
    sh.put(kit, C["kit"])
    _bag_end(sh, k, kit, k["yc"] - Y, zz)
    # front view of the tote's ends
    sh = S["tote_front"]
    X, Z = sh.grid()
    _tote_wall(sh, X - t["xc"], Z - z0, TOTE_RIBS_Y, t["a"], False, True)
    sh.mul(1.0, 1 - 0.18 * sh.cov(np.abs(np.abs(X - t["xc"]) - (t["a"] + 0.006)) - 0.008))   # the long walls' rib sides
    # the kit bag's long sides
    sh = S["kit_front"]
    X, Z = sh.grid()
    sh.fill(C["kit"])
    _bag_long(sh, k, np.ones(X.shape, bool), X - k["xc"], Z - z0)
    # top view: the handle grips' tops, the kit bag's top
    sh = S["tote_top"]
    X, Y = sh.grid()
    sh.fill(C["tote"])
    hw, _hin, hout, _hd, _hu = TOTE_HANDLE
    for e in (-1, 1):
        yy = (Y - t["yc"]) * e - (t["b"] + TOTE_LIP)
        grip = sd_box(X - t["xc"], yy, 0.0, (hout - TOTE_LIP) / 2, hw, (hout - TOTE_LIP) / 2 + 0.002)
        sh.mul(1.0, 1 + 0.12 * sh.cov(grip))
        sh.mul(1.0, 1 + 0.25 * sh.cov(np.abs(yy - (hout - TOTE_LIP - 0.003)) - 0.002) * sh.cov(grip))
    kit = Y > -0.915
    _bag_top(sh, k, kit)


def paint_lid(S, z0):
    t = TOTE
    a, b = t["a"] + TOTE_LIP, t["b"] + TOTE_LIP
    r = TOTE_R + TOTE_LIP
    sh = S["lid_top"]
    X, Y = sh.grid()
    x, y = X - t["xc"], Y - t["yc"]
    sh.fill(C["lid"])
    d = sd_box(x, y, 0.0, 0.0, a, b, r)                    # the lid's outline (negative inside)
    f = 1 + 0.03 * noise(x, y, 0.05, 51) + 0.015 * noise(x, y, 0.015, 52)
    sh.scale(f)
    # rim: lighter, a bright outer edge, a dark inner edge, the slope down to the panel in shade
    sh.mul(1.0, 1 + 0.10 * sh.cov(-(d + TOTE_RIM)))
    sh.mul(1.0, 1 + 0.25 * sh.cov(np.abs(d + 0.003) - 0.002))
    sh.put(1.0, C["lid_dark"], sh.cov(d + TOTE_RIM) * sh.cov(-(d + TOTE_RIM + 0.008)) * 0.85)
    sh.put(1.0, C["lid_dark"], sh.cov(np.abs(d + TOTE_RIM + 0.0005) - 0.0015))
    panel = d < -(TOTE_RIM + 0.008)
    # sunk panel: dust in its edges, six raised stacking pads with a bevel, four corner lugs
    sh.mul(panel, 1 - 0.10 * smooth(-(TOTE_RIM + 0.030), -(TOTE_RIM + 0.008), d))
    for cx in (-0.085, 0.085):
        for cy in (-0.165, 0.0, 0.165):
            pad = sd_box(x, y, cx, cy, 0.055, 0.060, 0.012)
            sh.mul(panel, 1 + 0.07 * sh.cov(pad))
            sh.mul(panel, 1 + 0.30 * sh.cov(np.abs(pad) - 0.0022) * (((x - cx) + (y - cy)) > 0))
            sh.mul(panel, 1 - 0.30 * sh.cov(np.abs(pad) - 0.0022) * (((x - cx) + (y - cy)) <= 0))
    for cx in (-1, 1):
        for cy in (-1, 1):
            lug = np.hypot(x - cx * (a - 0.065), y - cy * (b - 0.065)) - 0.013
            sh.mul(panel, 1 + 0.10 * sh.cov(lug))
            sh.mul(panel, 1 - 0.35 * sh.cov(np.abs(lug) - 0.002))
    # latch tops beyond the lid's edge on each long side
    hw, _lin, lout, _lb, _lt = TOTE_LATCH
    for e in (-1, 1):
        for ly in TOTE_LATCH_Y:
            tab = sd_box(x * e, y, a + lout / 2, ly, lout / 2 + 0.001, hw)
            sh.put(1.0, C["lid_dark"], sh.cov(tab) * 0.6)
            sh.mul(1.0, 1 + 0.30 * sh.cov(np.abs(x * e - (a + lout - 0.002)) - 0.0018) * sh.cov(tab))
    # scuffs on the rim
    rng = np.random.RandomState(53)
    for _k in range(6):
        p = (rng.uniform(-a + 0.03, a - 0.03), rng.uniform(-b + 0.03, b - 0.03))
        ang = rng.uniform(0, math.pi)
        ln = rng.uniform(0.02, 0.05)
        sh.mul(1.0, 1 + 0.12 * sh.cov(sd_seg(x, y, p, (p[0] + ln * math.cos(ang), p[1] + ln * math.sin(ang))) - 0.0016))
    # skirt (side and front views): a bright top edge, a dark lower edge, the latch tabs on the long sides
    for name, au, half in (("lid_side", "y", t["b"]), ("lid_front", "x", t["a"])):
        sh = S[name]
        U, Z = sh.grid()
        along = U - (t["yc"] if au == "y" else t["xc"])
        zz = Z - z0
        sh.fill(C["lid"])
        sh.scale(1 + 0.03 * noise(along, zz, 0.05, 55))
        sh.mul(1.0, 1 + 0.28 * sh.cov(np.abs(zz - (TOTE_Z3 - 0.003)) - 0.0025))
        sh.mul(1.0, 1 - 0.30 * sh.cov(np.abs(zz - (TOTE_Z2 + 0.003)) - 0.0025))
        if au == "y":
            hw, _lin, _lout, lbelow, lunder = TOTE_LATCH
            for ly in TOTE_LATCH_Y:
                z_lo, z_hi = TOTE_Z1 - lbelow, TOTE_Z3 - lunder
                tab = sd_box(along, zz, ly, (z_lo + z_hi) / 2, hw, (z_hi - z_lo) / 2, 0.004)
                sh.put(1.0, C["lid"], sh.cov(tab))
                sh.mul(1.0, 1 - 0.40 * sh.cov(np.abs(tab) - 0.003))                         # its outline
                sh.mul(1.0, 1 + 0.25 * sh.cov(np.abs(zz - (z_hi - 0.005)) - 0.003) * sh.cov(tab + 0.003))
                sh.mul(1.0, 1 - 0.30 * sh.cov(np.abs(zz - (z_lo + 0.013)) - 0.004) * sh.cov(tab + 0.005))   # grip groove
                sh.mul(1.0, 1 - 0.30 * sh.cov(np.abs(zz - (TOTE_Z2 - 0.002)) - 0.002) * sh.cov(tab + 0.004))   # its hinge
        else:
            sh.mul(1.0, 1 - 0.15 * sh.cov(sd_box(along, zz, 0.0, TOTE_Z3 - 0.010, 0.04, 0.008, 0.004)))   # thumb notch


# ------------------------------------------------------------------------------------------------
# bedroll


def _roll_r(x):
    """The roll's radius at x (the loft: rim, full, pinched under the straps, full, rim)."""
    b = BEDROLL
    xs = [b["x0"], b["x0"] + 0.012, BEDROLL_STRAPS[0], BEDROLL_STRAPS[1], b["x1"] - 0.012, b["x1"]]
    ss = [BEDROLL_END_S, 1.0, BEDROLL_PINCH, BEDROLL_PINCH, 1.0, BEDROLL_END_S]
    return b["r"] * np.interp(x, xs, ss)


def bedroll_zc(z0):
    b = BEDROLL
    return z0 + b["r"] * math.cos(math.pi / b["sides"])


def _foam(x, elev):
    """Closed-cell foam skin as a function of x along the roll and the elevation round it (degrees,
    -90 under, 0 level, 90 on top; the same on the front and back halves, because the front view
    paints both and must meet the top view at its gate): mottling, the mat's ribs running round the
    roll every 3.2 cm (> 2 texels after the 512 cap, so no beat), the foam squeezed and creased
    beside the straps."""
    s = np.radians(elev) * BEDROLL["r"]                    # arc length from the level line
    f = 1 + 0.04 * noise(x, s, 0.05, 61) + 0.02 * noise(x, s, 0.015, 62)
    f *= 1 + 0.035 * np.cos(2 * np.pi * (x - BEDROLL["x0"]) / 0.032)
    for xs in BEDROLL_STRAPS:
        f *= 1 - 0.14 * smooth(0.045, WEB_HALF, np.abs(x - xs))
    rng = np.random.RandomState(63)
    for xs in BEDROLL_STRAPS:                              # creases running out from the strap
        for _k in range(7):
            side = rng.choice((-1, 1))
            p0 = (xs + side * 0.020, rng.uniform(-0.06, 0.14))
            ln = rng.uniform(0.03, 0.06)
            ang = rng.uniform(-0.5, 0.5)
            f *= _fold(x, s, p0, (p0[0] + side * ln * math.cos(ang), p0[1] + ln * math.sin(ang)), 0.005, 0.12, 0.05, 0.009)
    return f


def paint_bedroll(S, z0):
    b = BEDROLL
    zc = bedroll_zc(z0)
    # top view: the upper half; theta from the y offset
    sh = S["tarp_top"]
    X, Y = sh.grid()
    R = _roll_r(X)
    dy = np.clip((Y - b["yc"]) / np.maximum(R, 1e-6), -1, 1)
    theta = np.degrees(np.arccos(dy))                      # 0 front .. 180 back, over the top
    elev = 90.0 - np.abs(theta - 90.0)
    sh.fill(C["foam"])
    sh.scale(_foam(X, elev) * (0.90 + 0.12 * (np.sin(np.radians(elev)) + 1) / 2))   # the crown lighter
    # the mat's last layer ends along the roll, on the front of the crown (the top view owns it): its
    # cut edge lighter, the layer under it in shade
    d_edge = np.radians(theta - BEDROLL_EDGE) * R           # arc length from the edge (+ over the top)
    sh.mul(d_edge < 0, 1 - 0.30 * smooth(-0.016, 0.0, d_edge))
    sh.put(1.0, C["foam_cut"], sh.cov(np.abs(d_edge - 0.002) - 0.0025))
    # front view: the front and back halves
    sh = S["tarp_front"]
    X, Z = sh.grid()
    R = _roll_r(X)
    dz = np.clip((Z - zc) / np.maximum(R, 1e-6), -1, 1)
    sh.fill(C["foam"])
    sh.scale(_foam(X, np.degrees(np.arcsin(dz))) * (0.90 + 0.12 * (dz + 1) / 2))
    # side view: the rolled ends, a spiral of the mat round the sunk core
    sh = S["tarp_side"]
    Y, Z = sh.grid()
    dy, dz = Y - b["yc"], Z - zc
    rho = np.hypot(dy, dz)
    phi = np.arctan2(dz, dy)
    r_out = b["r"] * BEDROLL_END_S
    psi = np.mod(np.radians(BEDROLL_EDGE) - phi, 2 * np.pi)
    k = (r_out - rho) / FOAM_T - psi / (2 * np.pi)          # whole numbers on the mat's outer face
    fr = k - np.floor(k)
    sh.fill(C["foam_cut"])
    sh.scale(1 + 0.04 * noise(dy, dz, 0.03, 65))
    sh.scale(0.88 + 0.16 * fr)                             # each layer lighter toward its outer face
    gap = np.minimum(fr, 1 - fr) * FOAM_T                  # metres to the nearest layer joint
    sh.put(rho < r_out, C["foam_gap"], sh.cov(gap - 0.0014))
    sh.put(1.0, C["foam_gap"], sh.cov(rho - 0.010))          # the hollow core
    sh.put(rho > r_out - 0.001, C["foam"], sh.cov(r_out - rho))   # the rounded rim is the mat's skin
    sh.mul(rho > r_out - 0.001, 0.92)


# ------------------------------------------------------------------------------------------------
# webbing


def _web_mottle(U, V, seed):
    return 1 + 0.035 * noise(U, V, 0.03, seed) + 0.02 * noise(U, V, 0.01, seed + 1)


def _ratchet_strap(sh, along, across, start, end_label):
    """An orange ratchet strap in a view where `along` runs along it and `across` from its centre
    line: darker woven edges, a sewn end loop (box-X stitch) near each hook, a load label."""
    on = np.abs(across) < STRAP_BAND
    sh.put(on, C["orange"])
    sh.scale(np.where(on, _web_mottle(along, across, 81), 1.0))
    sh.put(on, C["orange_edge"], sh.cov((STRAP_HALF - 0.004) - np.abs(across)))   # the woven edges, 4 mm
    sh.mul(on, 1 + 0.06 * sh.cov(np.abs(across) - 0.004))     # the middle of the weave catching the light
    if start is not None:                                  # stitched end loops at the hooks
        for e in (-1, 1):
            c = e * (RAIL_X - HOOK_IN - 0.028)
            box = sd_box(along, across, c, 0.0, 0.026, STRAP_HALF - 0.004)
            sh.mul(on, 1 - 0.12 * sh.cov(box))
            thread = np.minimum(np.abs(box) - 0.0018,
                                np.minimum(sd_seg(along, across, (c - 0.024, -0.011), (c + 0.024, 0.011)),
                                           sd_seg(along, across, (c - 0.024, 0.011), (c + 0.024, -0.011))) - 0.0016)
            sh.mul(on, 1 - 0.35 * sh.cov(thread) * sh.cov(box - 0.001))
    if end_label is not None:                              # the sewn load label (no maker's name)
        lc = end_label
        lab = sd_box(along, across, lc, 0.0, 0.030, 0.0125, 0.002)
        sh.put(on, C["strap_label"], sh.cov(lab))
        sh.put(on, C["strap_label_band"], sh.cov(sd_box(along, across, lc - 0.022, 0.0, 0.007, 0.0115)))
        for k, (dv, wl) in enumerate(((0.0055, 0.034), (0.0, 0.026), (-0.0055, 0.030))):
            sh.put(on, C["ink"], sh.cov(sd_box(along, across, lc - 0.010 + wl / 2, dv, wl / 2, 0.0016)))


def _black_web(sh, along, across, half, mask):
    """Black webbing with lighter woven edges (along runs along it, across from its centre)."""
    sh.mul(mask, 1 + 0.5 * sh.cov(np.abs(np.abs(across) - (half - 0.003)) - 0.0018))


def paint_straps(S, z0):
    d, k, b = DUFFEL, KITBAG, BEDROLL
    # top view: every piece of webbing seen from above
    sh = S["strap_top"]
    X, Y = sh.grid()
    sh.fill(C["web"])
    sh.scale(_web_mottle(X, Y, 71))
    for su in (-STRAP_U, STRAP_U):                         # the duffel's girth straps (along x)
        across = Y - (d["yc"] + su)
        _black_web(sh, X, across, WEB_HALF, np.abs(X - d["xc"]) < d["w"] * 0.55)
    for xs in BEDROLL_STRAPS:                              # the bedroll's straps (along y)
        _black_web(sh, Y, X - xs, WEB_HALF, np.abs(Y - b["yc"]) < b["r"] * 1.2)
    # the duffel's handle wrap: a lighter grey hook-and-loop wrap with a stitched outline
    wrap = sd_box(X, Y, d["xc"], d["yc"], 0.030, 0.035, 0.005)
    sh.put(1.0, (58, 58, 60), sh.cov(wrap))
    sh.mul(1.0, 1 + 0.6 * sh.cov(np.abs(sd_box(X, Y, d["xc"], d["yc"], 0.024, 0.029)) - 0.0016))
    # box-X stitches where the duffel's handles are sewn to its girth straps
    for su in (-STRAP_U, STRAP_U):
        for sv in (-0.06, 0.06):
            c = (d["xc"] + sv, d["yc"] + su)
            box = sd_box(X, Y, c[0], c[1], 0.012, 0.014)
            thread = np.minimum(np.abs(box) - 0.0016,
                                np.minimum(sd_seg(X, Y, (c[0] - 0.012, c[1] - 0.014), (c[0] + 0.012, c[1] + 0.014)),
                                           sd_seg(X, Y, (c[0] - 0.012, c[1] + 0.014), (c[0] + 0.012, c[1] - 0.014))) - 0.0015)
            sh.mul(1.0, 1 + 1.4 * sh.cov(thread))
    # the ratchet straps (orange), the label on the left run, the ratchet's spool
    for ys, rx in STRAPS:
        _ratchet_strap(sh, X, Y - ys, True, -0.36)
        sp = rx + SPOOL_DT                                 # the ratchet's spool of wound webbing: round
        spool = sd_box(X, Y - ys, sp, 0.0, SPOOL_R, STRAP_BAND)
        sh.mul(spool < 0, 1 - 0.35 * np.clip(np.abs(X - sp) / SPOOL_R, 0, 1) ** 2)
        sh.mul(1.0, 1 - 0.30 * sh.cov(np.abs(np.abs(X - sp) - SPOOL_R + 0.002) - 0.002) * (np.abs(Y - ys) < STRAP_BAND))
    # side view: the girth straps' sides, the ratchet straps' drops to the rails
    sh = S["strap_side"]
    Y, Z = sh.grid()
    sh.fill(C["web"])
    sh.scale(_web_mottle(Y, Z, 73))
    for su in (-STRAP_U, STRAP_U):
        _black_web(sh, Z, Y - (d["yc"] + su), WEB_HALF, np.ones(Y.shape, bool))
    rail_top = z0 + 0.105 - 0.0095 + 0.011                 # build_accessories: rail centre = floor + RK_H
    for ys, _rx in STRAPS:
        across = Y - ys
        _ratchet_strap(sh, Z, across, None, None)
        on = np.abs(across) < STRAP_BAND                   # the sewn end loop just above the hook
        box = sd_box(Z, across, rail_top + 0.030, 0.0, 0.024, STRAP_HALF - 0.004)
        sh.mul(on, 1 - 0.12 * sh.cov(box))
        sh.mul(on, 1 - 0.35 * sh.cov(np.abs(box) - 0.0018))
    # front view: the bedroll straps' front and back runs, the bags' handles seen end on
    sh = S["strap_front"]
    X, Z = sh.grid()
    sh.fill(C["web"])
    sh.scale(_web_mottle(X, Z, 75))
    for xs in BEDROLL_STRAPS:
        _black_web(sh, Z, X - xs, WEB_HALF, np.ones(X.shape, bool))
    sh = S["strap_orange"]
    sh.fill(C["orange"])


# ------------------------------------------------------------------------------------------------
# the canvas duffel


def paint_canvas(S, z0):
    d = DUFFEL
    sh = S["canvas_top"]
    X, _Y = sh.grid()
    sh.fill(C["canvas"])
    _bag_top(sh, d, np.ones(X.shape, bool))
    sh = S["canvas_side"]
    Y, Z = sh.grid()
    sh.fill(C["canvas"])
    _bag_long(sh, d, np.ones(Y.shape, bool), Y - d["yc"], Z - z0)
    sh = S["canvas_front"]
    X, Z = sh.grid()
    sh.fill(C["canvas"])
    _bag_end(sh, d, np.ones(X.shape, bool), X - d["xc"], Z - z0)


# ------------------------------------------------------------------------------------------------
# entry points


def paint(out_dir, z0=Z0_DEFAULT, log=print):
    """Write every cargo PNG into out_dir (blender/bake in the build: the bake's decal folder)."""
    os.makedirs(out_dir, exist_ok=True)
    S = sheets(z0)
    paint_canvas(S, z0)
    paint_tote(S, z0)
    paint_lid(S, z0)
    paint_bedroll(S, z0)
    paint_straps(S, z0)
    for sh in S.values():
        sh.save(out_dir)
    log("  cargo_paint: %d maps at %d px/m (%s) for floor z %.4f"
        % (len(S), PX_PER_M, ", ".join("%s %dx%d" % (s.name, s.w, s.h) for s in S.values()), z0))
    return S


def _z0():
    """The floor the cargo was built on: build_rack_loads stores it on each load object."""
    try:
        import bpy
    except ImportError:
        return Z0_DEFAULT
    for name in ("acc_rack_load1", "acc_rack_load2", "acc_rack_load3"):
        ob = bpy.data.objects.get(name)
        if ob is not None and Z0_PROP in ob:
            return float(ob[Z0_PROP])
    return Z0_DEFAULT


def layers(z0=None):
    """TEXTURED layer stacks for the cargo materials. Faces take the view they look along (normal
    gates at 0.5: every unit normal passes at least one); later layers win where two gates pass
    (the top view last, it owns the shoulders). The material's base colour stays only on faces
    looking down (|x|, |y| < 0.5), which sit on the floor."""
    z0 = _z0() if z0 is None else z0
    S = sheets(z0)

    def dec(name, *gates):
        u, v = S[name].axes()
        return ("decal", S[name].png, u, v, "replace", list(gates))
    xp, xn = ("normal", "x", ">", 0.5), ("normal", "x", "<", -0.5)
    yp, yn = ("normal", "y", ">", 0.5), ("normal", "y", "<", -0.5)
    zp = ("normal", "z", ">", 0.5)
    tote_y, kit_y = ("range", "y", -2.0, -0.915), ("range", "y", -0.915, 0.0)
    shade = ("attr", "acc_shade")
    out = {
        "AccCanvas": [dec("canvas_side", xp), dec("canvas_side", xn), dec("canvas_front", yp), dec("canvas_front", yn),
                      dec("canvas_top", zp), shade],
        "AccTote": [dec("tote_side", xp), dec("tote_side", xn), dec("tote_front", yp, tote_y), dec("tote_front", yn, tote_y),
                    dec("kit_front", yp, kit_y), dec("kit_front", yn, kit_y), dec("tote_top", zp), shade],
        "AccLid": [dec("lid_side", xp), dec("lid_side", xn), dec("lid_front", yp), dec("lid_front", yn), dec("lid_top", zp), shade],
        "AccTarp": [dec("tarp_front", yp), dec("tarp_front", yn), dec("tarp_side", xp), dec("tarp_side", xn),
                    dec("tarp_top", zp), shade],
        # the ratchet straps' orange is gated by their y bands (STRAP_BAND) before the views, so a face
        # no view owns (a strap's 4 mm edge) is orange there and black webbing everywhere else
        "AccStrap": [dec("strap_front", yp), dec("strap_front", yn)]
                    + [("decal", S["strap_orange"].png, ("x", -10.0, 10.0), ("y", -10.0, 10.0), "replace",
                        [("range", "y", ys - STRAP_BAND, ys + STRAP_BAND)]) for ys, _rx in STRAPS]
                    + [dec("strap_side", xp), dec("strap_side", xn), dec("strap_top", ("normal", "z", ">", 0.3)), shade],
    }
    return out


if __name__ == "__main__":                                 # preview: python cargo_paint.py OUT_DIR
    import sys
    paint(sys.argv[1] if len(sys.argv) > 1 else ".")
