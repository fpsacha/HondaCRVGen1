r"""
The CR-V's own damage sheets (polish feature, spec/feature-roadmap.md "damage textures painted to our
own UV layout"): dents and scratches (light / heavy), rust, blood, painted in the game's damage space.

How the game draws them (vehicle_crvgen1_norandom.frag, vehicle_common.frag, BaseVehicle.checkDamage, 42.21):
  * every one is sampled through texCoords1 = the mesh's SECOND UV layer (bake_atlas "UVMap1", an even
    xatlas layout of the shell). The vanilla sheets (Veh_Damage1/2, Veh_Blood_*, Veh_Rust) are painted
    for VANILLA cars' second layout: on ours their grille, wheel well and green smears land anywhere.
  * a part zone (the Mask's colour at the FIRST UV) turns its damage on from the part's condition:
    TextureDamage1 at condition 40-59, TextureDamage2 under 40 (never both), so the heavy sheet carries
    the light damage too.
  * body zones mix the damage through addDamage: hue from the paint colour, S and V from the texture
    offset by the paint's (s_tex + S - 0.5, v_tex + V - 0.5), at alpha x 0.75. Our shader is the
    norandom variant: the paint colour is the skin TEXEL's own HSV (rgb2hsv(tex.rgb)), as in Project
    Viewpoint's NO_PAINT kind, so a texel with s 0.5 and v 0.5 + d draws the panel's own colour d
    brighter: dents shade in the car's colour on every skin (and on a decal or the black cladding in
    theirs), with no per-car state involved.
  * window, lamp, front (head zone) and tail zones mix the texture's RGB as it is ("noTint"): glass
    cracks, lens cracks and the bumper scuffs are painted in absolute colours.
  * rust: mix(col, rust.rgb, rust.a x the car's rust level 0..1): alpha is where and how soon it rusts.
  * blood (addBlood): Damage2Overlay = blood colour and coverage, Damage1Overlay alpha = the order it
    appears in: a texel shows once (1-(1-a)^3)(1-(1-m)^3) > 1 - the zone's blood intensity.

Everything is generated in 3D (model metres, +X right, +Y forward, +Z up, ground 0) and looked up per
texel through the triangle dump (_polish_uv2dump.py), so a dent or a rust run crosses island seams
and keeps its size on every panel. Deterministic (fixed seeds): the same sheets on every build.
"""
import colorsys
import os

import numpy as np
from PIL import Image
from scipy import ndimage
from scipy.spatial import cKDTree

import paint_pass as PP                    # rasterise (exact texel coverage + barycentrics), vnoise (3D value noise)

NAME = "Vehicles_HondaCRVGen1"
SHEETS = {"light": "DamageLight", "heavy": "DamageHeavy", "blood": "Blood", "blood_mask": "BloodMask", "rust": "RustPanels"}
SIZE = 1024                                 # shipped size (the Rust sheet's; the default Vehicle Texture Size caps at 512)
SS = 2                                      # painted at SS x SIZE, box-reduced like compose's sheets

# zone colours (bake_atlas.ZONE, 0..255) and what path the shader takes for them
WINDOW_Z = {(0, 128, 128), (128, 128, 0), (128, 0, 128), (0, 0, 128), (128, 0, 0), (0, 128, 0)}
LAMP_Z = {(64, 0, 0), (191, 0, 0), (0, 191, 0), (0, 64, 0), (128, 64, 0), (128, 191, 0)}
FRONT_Z, TAIL_Z = (255, 0, 0), (0, 255, 0)            # frontAlpha / tailAlpha with the lamp zones: noTint
GLOSS_PAINT, GLOSS_GLASS = 191, 255                   # compose's Mask alpha: paint 0.75, glass 1.0, trim ~0.12
PANELS = ("body", "door_", "hood", "trunk", "window_")   # bake_atlas shell objects a hit is centred on
WHEELS = [(sx * 0.72, wy, 0.334) for sx in (-1, 1) for wy in (1.31, -1.31)]   # hubs (script wheels: x, z, radius)
LIGHT = np.array([-0.35, 0.25, 0.90])                 # dent shading: light from above, a little left and front
LIGHT = LIGHT / np.linalg.norm(LIGHT)


def _rng(seed):
    return np.random.default_rng(seed)


STRETCH_X = 10.0                            # a triangle with this many times the median UVMap1 area per m2 ...
STRETCH_TEXELS = 200                        # ... over this many texels (at SIZE) in all: the mesh has no chart
                                            # of its own (a borrowed or broken UVMap1) and is left out


def screen(names, obj, pos, uv1, size=SIZE):
    """Objects whose UVMap1 spreads a little 3D over a lot of sheet (the decals' borrowed UVs crossing a
    host chart seam: 0.3 of the sheet for 0.36 m2): painting them would smear one spot over other
    panels' texels. Returns {name: excess texels at `size`} of the ones to leave out."""
    a3 = 0.5 * np.linalg.norm(np.cross(pos[:, 1] - pos[:, 0], pos[:, 2] - pos[:, 0]), axis=1)
    e1, e2 = uv1[:, 1] - uv1[:, 0], uv1[:, 2] - uv1[:, 0]
    a2 = 0.5 * np.abs(e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0])
    ok = a3 > 1e-6
    med = float(np.median(a2[ok] / a3[ok])) if ok.any() else 0.0
    excess = np.clip(a2 - STRETCH_X * med * a3, 0.0, None) * size * size
    per = np.bincount(obj, weights=excess, minlength=len(names))
    return {names[i]: float(per[i]) for i in range(len(names)) if per[i] > STRETCH_TEXELS}


class Field:
    """The per-texel geometry of the damage layout at the painting size."""

    def __init__(self, npz, mask_png, size, report=print):
        d = np.load(npz)
        self.size = size
        names = [str(n) for n in d["names"]]
        uv1, uv0 = d["uv1"].astype(np.float64), d["uv0"].astype(np.float64)
        pos, obj = d["pos"].astype(np.float64), d["obj"].astype(np.int64)
        self.dropped = screen(names, obj, pos, uv1)
        for n, px in sorted(self.dropped.items()):
            report("FEATURE polish: warning %s left out of the damage sheets: its UVMap1 spreads over %.0f texels "
                   "of other charts" % (n, px))
        keep = np.flatnonzero(~np.isin(obj, [names.index(n) for n in self.dropped]))
        uv1, uv0, pos, obj = uv1[keep], uv0[keep], pos[keep], obj[keep]
        nrm = d["nrm"][keep].astype(np.float64)
        # where two charts share texels the car's own panels win over a feature's mesh (acc_*)
        prio = np.array([1 if n.startswith("acc_") else 0 for n in names], dtype=np.int64)[obj]
        x, y = uv1[..., 0] * size, (1.0 - uv1[..., 1]) * size
        tri, bary = PP.rasterise(x, y, prio, size)
        self.cov = tri >= 0
        t = tri[self.cov]
        b = bary[self.cov].astype(np.float64)
        self.idx = np.flatnonzero(self.cov.ravel())               # flat texel index of every painted texel
        self.pos = np.einsum("nk,nkc->nc", b, pos[t])
        self.nrm = nrm[t]
        self.obj = np.array(names)[obj[t]]
        # metres per texel at the SHIPPED size (SIZE): what a line must cover to survive the box filter
        a3 = 0.5 * np.linalg.norm(np.cross(pos[t, 1] - pos[t, 0], pos[t, 2] - pos[t, 0]), axis=1)
        e1, e2 = uv1[t, 1] - uv1[t, 0], uv1[t, 2] - uv1[t, 0]
        a2 = 0.5 * np.abs(e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]) * SIZE * SIZE
        self.texel_m = np.sqrt(np.maximum(a3, 1e-12) / np.maximum(a2, 1e-12))
        u0 = np.einsum("nk,nkc->nc", b, uv0[t])
        mask = np.asarray(Image.open(mask_png).convert("RGBA"))
        ms = mask.shape[0]
        mx = np.clip((u0[:, 0] * ms).astype(np.int64), 0, ms - 1)
        my = np.clip(((1.0 - u0[:, 1]) * ms).astype(np.int64), 0, ms - 1)
        m = mask[my, mx]
        self.zone = m[:, :3].astype(np.int64)
        self.gloss = m[:, 3].astype(np.int64)
        code = self.zone[:, 0] * 65536 + self.zone[:, 1] * 256 + self.zone[:, 2]
        self.zcode = code
        zset = lambda s: np.isin(code, [r * 65536 + g * 256 + b_ for r, g, b_ in s])
        self.window = zset(WINDOW_Z) & (self.gloss >= 250)
        self.lamp = zset(LAMP_Z)
        self.notint = zset(WINDOW_Z) | self.lamp | zset({FRONT_Z, TAIL_Z})
        self.paint = (self.gloss >= 150) & (self.gloss < 220) & ~self.notint
        self.glass_body = (self.gloss >= 250) & ~self.notint          # quarter glass in a body zone: left clean
        self.trim = ~self.paint & ~self.notint & ~self.glass_body
        self.metal = self.paint | (zset({FRONT_Z, TAIL_Z}) & (self.gloss >= 150) & (self.gloss < 220))
        # the car's own outer panels: where a hit is CENTRED (a dent, a scrape, a splash). Feature meshes
        # (acc_*, usually not fitted) and the bay walls / arch liners only take what spreads onto them
        self.panel = np.zeros(len(self.obj), dtype=bool)
        for pre in PANELS:
            self.panel |= np.char.startswith(self.obj.astype(str), pre)
        self.tree = cKDTree(self.pos)
        self.n = len(self.pos)

    def near(self, c, r, normal=None, same_zone=True, min_dot=0.35):
        """Texels within r metres of c (3D), on the face side of `normal` and in c's zone."""
        ids = np.array(self.tree.query_ball_point(c, r), dtype=np.int64)
        if not len(ids):
            return ids
        if normal is not None:
            ids = ids[self.nrm[ids] @ normal > min_dot]
        if same_zone and len(ids):
            _d, k = self.tree.query(c)
            ids = ids[self.zcode[ids] == self.zcode[k]]
        return ids

    def image(self, values, fill=0.0):
        """(n, C) per-texel values -> (size, size, C) image, dilated into the gutters (bilinear sampling
        at an island's edge must not pull the empty sheet in)."""
        values = np.asarray(values, dtype=np.float32)
        if values.ndim == 1:
            values = values[:, None]
        img = np.full((self.size * self.size, values.shape[1]), fill, dtype=np.float32)
        img[self.idx] = values
        img = img.reshape(self.size, self.size, -1)
        _d, ind = ndimage.distance_transform_edt(~self.cov, return_indices=True)
        return img[ind[0], ind[1]]


def _reduce(img, k):
    h = img.shape[0] // k
    return img[:h * k, :h * k].reshape(h, k, h, k, -1).mean(axis=(1, 3))


def _save(img, path):
    a = np.clip(img * 255.0 + 0.5, 0, 255).astype(np.uint8)
    Image.fromarray(a, "RGBA").save(path)


def _pick(F, rng, n, weight):
    """n texels drawn with probability ~ weight (0 where nothing should land), on the outer panels."""
    w = np.clip(weight, 0, None) * F.panel
    if w.sum() <= 0:
        return np.zeros(0, dtype=np.int64)
    return rng.choice(F.n, size=n, replace=True, p=w / w.sum())


def _vulnerable(F):
    """Where a car in Knox County collects knocks: low and at the ends, the outer corners most."""
    x, y, z = F.pos.T
    low = np.clip((1.25 - z) / 0.9, 0.15, 1.0)
    ends = 0.5 + np.clip((np.abs(y) - 1.2) / 1.0, 0.0, 1.0)
    side = 0.6 + 0.4 * np.clip((np.abs(x) - 0.6) / 0.3, 0.0, 1.0)
    return low * ends * side


# ---------------------------------------------------------------------------------------------------
# the elements


def _dents(F, rng, n, rmin, rmax, depth, acc, where):
    """Shallow round dents: a depression whose slopes the LIGHT shades (darker where the panel turns
    away, a little lighter where it turns to the light), as a brightness offset `acc['dv']`."""
    for k in _pick(F, rng, n, where):
        c, nc = F.pos[k], F.nrm[k]
        r = rng.uniform(rmin, rmax)
        ids = F.near(c, r, nc)
        if not len(ids):
            continue
        d = F.pos[ids] - c
        d -= np.outer(d @ nc, nc)                                   # in the panel's plane
        dist = np.linalg.norm(d, axis=1) / r
        # height h = -depth (1 - s^2)^2: slope dh/ds = 4 depth s (1 - s^2) / r, pointing outward
        slope = 4.0 * depth * dist * (1.0 - dist ** 2) / r
        tang = d / np.maximum(np.linalg.norm(d, axis=1, keepdims=True), 1e-9)
        # the surface rises outward (dh/ds > 0), so its normal tilts INWARD, toward the dent's centre:
        # the wall under the light's side is shaded, the far wall lit (a + here drew bumps, not dents)
        nn = F.nrm[ids] - tang * slope[:, None]
        nn /= np.linalg.norm(nn, axis=1, keepdims=True)
        shade = nn @ LIGHT - F.nrm[ids] @ LIGHT
        crease = np.exp(-((dist - 0.92) / 0.05) ** 2) * 0.05 * rng.uniform(0.5, 1.5)   # the dent's rim catches light
        acc["dv"][ids] += 1.6 * shade + crease
        acc["cover"][ids] = np.maximum(acc["cover"][ids], (1.0 - dist ** 2) ** 0.5)


def _strokes(F, rng, n, length, width, strength, acc, where, key="dv", vertical=0.15, bundle=(1, 4)):
    """Scratches: bundles of near-parallel strokes along the panel, mostly horizontal (fore-aft), a
    few at random. Each stroke is a segment in 3D; a texel's value falls off with its distance to it."""
    for k in _pick(F, rng, n, where):
        c, nc = F.pos[k], F.nrm[k]
        ang = rng.normal(0.0, vertical) if rng.random() < 0.8 else rng.uniform(-1.4, 1.4)
        fwd = np.array([0.0, np.cos(ang), np.sin(ang)])
        if abs(nc[1]) > 0.7:                                        # a face looking fore or aft: strokes across
            fwd = np.array([np.cos(ang), 0.0, np.sin(ang)])
        fwd -= nc * (fwd @ nc)
        if np.linalg.norm(fwd) < 1e-6:
            continue
        fwd /= np.linalg.norm(fwd)
        side = np.cross(nc, fwd)
        L = rng.uniform(*length)
        ids = F.near(c, L * 0.5 + 0.03, nc)
        if not len(ids):
            continue
        d = F.pos[ids] - c
        along, across = d @ fwd, d @ side
        nb = rng.integers(bundle[0], bundle[1] + 1)
        for _ in range(nb):
            off = rng.normal(0.0, 0.012)
            a0, a1 = sorted(rng.uniform(-0.5, 0.5, 2) * L)
            a1 = max(a1, a0 + L * 0.3)
            w = rng.uniform(*width)
            bend = rng.normal(0.0, 0.004)
            dist = np.abs(across - off - bend * ((along - a0) / max(L, 1e-3)) ** 2 * 10)
            inside = (along > a0) & (along < a1)
            taper = np.clip(np.minimum(along - a0, a1 - along) / (0.15 * L + 1e-3), 0, 1)
            v = np.exp(-(dist / w) ** 2) * inside * taper * rng.uniform(0.5, 1.0)
            grain = 0.6 + 0.4 * np.sin(along * rng.uniform(150, 400) + rng.uniform(0, 6))   # broken, not ruled
            acc[key][ids] += strength * v * grain
            acc["cover"][ids] = np.maximum(acc["cover"][ids], v)


def _drag_frame(nc, rng, vertical=0.12):
    """(fwd, side) in the panel's plane: the direction a scrape is dragged (fore-aft on the sides,
    across the car on a face looking fore or aft, a little tilted), and the one across it."""
    ang = rng.normal(0.0, vertical)
    fwd = np.array([0.0, np.cos(ang), np.sin(ang)])
    if abs(nc[1]) > 0.7:
        fwd = np.array([np.cos(ang), 0.0, np.sin(ang)])
    fwd = fwd - nc * (fwd @ nc)
    n = np.linalg.norm(fwd)
    if n < 1e-6:
        return None, None
    fwd /= n
    return fwd, np.cross(nc, fwd)


def _scrape(F, rng, n, length, height, acc, where, seed):
    """Heavy scrapes: long low bands where the car was dragged along something, at the corners and the
    lower edges. Each is a band `length` x `height` (metres) along the drag direction with ragged ends
    and edges (noise at 6-10 cm, so no texel-sized stipple), its paint abraded (acc['scrape'], the
    primer / metal shows) and 3-6 parallel gouges inside it (acc['gouge'], each a few texels wide and
    running only part of the band, which is what reads as dragged). Every width is at least about a
    shipped texel (F.texel_m), so the box filter to 1024 / 512 keeps the lines."""
    for j, k in enumerate(_pick(F, rng, n, where)):
        c, nc = F.pos[k], F.nrm[k]
        fwd, side = _drag_frame(nc, rng)
        if fwd is None:
            continue
        L, H = rng.uniform(*length), rng.uniform(*height)
        ids = F.near(c, L * 0.55 + H, nc)
        if not len(ids):
            continue
        p = F.pos[ids]
        d = p - c
        along, across = d @ fwd, d @ side
        tm = float(np.median(F.texel_m[ids]))
        # the band's outline: half-height wanders along the band, the ends are ragged and taper
        hh = 0.5 * H * (1.0 + 0.45 * PP.vnoise(p, 0.10, seed + 3 * j))
        end = 0.5 * L * (1.0 + 0.25 * PP.vnoise(p, 0.07, seed + 3 * j + 1))
        u = np.abs(along) / np.maximum(end, 1e-3)
        taper = np.clip((1.0 - u) / 0.35, 0.0, 1.0)                 # the ends thin out
        body = np.clip((hh * (0.35 + 0.65 * taper) - np.abs(across)) / (1.2 * tm), 0.0, 1.0) * (u < 1.0)
        # abrasion inside: strong in the band's middle, broken in long streaks along the drag
        streak = 0.65 + 0.35 * PP.vnoise(np.column_stack([along / 0.25, across / (2.5 * tm), np.zeros(len(ids))]), 1.0, seed + 3 * j + 2)
        a = np.clip(body * streak * rng.uniform(0.75, 1.0), 0.0, 1.0)
        acc["scrape"][ids] = np.maximum(acc["scrape"][ids], a)
        # gouges: parallel lines along the drag, each over part of the band
        g = np.zeros(len(ids))
        for _ in range(rng.integers(3, 7)):
            off = rng.uniform(-0.45, 0.45) * H
            w = rng.uniform(0.7, 1.3) * tm
            a0 = rng.uniform(-0.5, 0.1) * L
            a1 = a0 + rng.uniform(0.35, 0.9) * L
            t = np.clip(np.minimum(along - a0, a1 - along) / (0.12 * L + 1e-3), 0.0, 1.0)
            wob = across - off - 0.25 * tm * np.sin(along * rng.uniform(4.0, 9.0) + rng.uniform(0, 6))
            g = np.maximum(g, np.exp(-(wob / w) ** 2) * t * rng.uniform(0.6, 1.0))
        acc["gouge"][ids] = np.maximum(acc["gouge"][ids], g * np.clip(body * 1.5, 0, 1))
        acc["cover"][ids] = np.maximum(acc["cover"][ids], a)


def _cracks(F, rng, centres, rays, rings, reach, acc):
    """Glass / lens cracks from impact points: a crushed spot, jagged radial lines and broken rings round
    it. The damage sheets are coarse (about 1.8 cm a texel at 1024, 3.6 at the default 512 cap), so a
    line is about a shipped texel wide (F.texel_m around the impact) and there are few of them, far
    enough apart that the box filter to 512 keeps separate lines instead of averaging a grey haze."""
    for k in centres:
        c, nc = F.pos[k], F.nrm[k]
        R = rng.uniform(*reach) if isinstance(reach, tuple) else reach
        ids = F.near(c, R, nc, same_zone=True, min_dot=0.2)
        if not len(ids):
            continue
        tm = float(np.median(F.texel_m[ids]))
        w = max(0.0022, 0.6 * tm)                                    # the line's gaussian width (FWHM ~1 texel)
        d = F.pos[ids] - c
        d -= np.outer(d @ nc, nc)
        e1 = np.cross(nc, [0.0, 0.0, 1.0])
        if np.linalg.norm(e1) < 1e-3:
            e1 = np.cross(nc, [1.0, 0.0, 0.0])
        e1 /= np.linalg.norm(e1)
        e2 = np.cross(nc, e1)
        u, v = d @ e1, d @ e2
        r = np.hypot(u, v)
        th = np.arctan2(v, u)
        line = np.zeros(len(ids))
        base = rng.uniform(-np.pi, np.pi)
        for i in range(rays):
            a0 = base + 2 * np.pi * (i + rng.uniform(-0.3, 0.3)) / rays   # spread round the impact
            L = rng.uniform(0.45, 1.0) * R
            kink = rng.uniform(0.06, 0.14)                           # a jagged line: kinks every 6-14 cm
            wob = a0 + rng.uniform(0.05, 0.12) * np.sin(r / kink * 2 * np.pi + rng.uniform(0, 6)) * np.clip(r / 0.05, 0, 1)
            dist = np.abs(np.angle(np.exp(1j * (th - wob)))) * np.maximum(r, 1e-3)
            line = np.maximum(line, np.exp(-(dist / w) ** 2) * (r < L) * np.clip(1.25 - r / L, 0, 1))
        for _ in range(rings):
            # a broken ring: short arcs between the rays (a spider web, not a target)
            rr = rng.uniform(0.18, 0.45) * R
            arc = np.cos(th * rng.integers(3, 6) + rng.uniform(0, 6)) > rng.uniform(0.35, 0.65)
            line = np.maximum(line, np.exp(-((r - rr - 0.3 * tm * np.sin(th * 7)) / w) ** 2) * arc * 0.6)
        star = np.clip(1.0 - r / max(2.2 * tm, 0.012), 0, 1) ** 0.7       # the crushed spot, ~2 texels
        acc["crack"][ids] = np.maximum(acc["crack"][ids], np.maximum(line, star))


# ---------------------------------------------------------------------------------------------------
# the sheets


def _encode(F, dv, a_rel, a_abs, rgb_abs, desat=None):
    """Per texel RGBA: body zones carry a brightness offset dv and a desaturation `desat` (0..1: paint
    ground down to primer / metal) for addDamage, noTint zones their absolute colour.

    addDamage mixes col -> hsv(paint h, s_tex + S - 0.5, v_tex + V - 0.5) at f = 0.75 a. So a texel
    with mix f, v_tex 0.5 + e and s_tex 0.5 + ds moves the panel's value by about f e = dv and its
    saturation by f ds (= -0.45 desat at full strength). e stays +0.30 / -0.36 where only dv is asked
    (the encoding of before), f grows where a desaturation needs more of the mix."""
    if desat is None:
        desat = np.zeros(F.n)
    emax = np.where(dv >= 0, 0.30, 0.36)
    f = np.clip(np.maximum(np.abs(dv) / emax, 0.75 * desat), 0.0, 0.75)
    fs = np.maximum(f, 1e-6)
    e = np.clip(dv / fs, -0.45, 0.45)
    ds = np.clip(-0.45 * 0.75 * desat / fs, -0.5, 0.0)
    v_t, s_t = np.clip(0.5 + e, 0.0, 1.0), np.clip(0.5 + ds, 0.0, 1.0)
    rel = np.column_stack([v_t, v_t * (1 - s_t), v_t * (1 - s_t)])   # hue 0: the shader only reads s and v
    a = f / 0.75 * a_rel
    out = np.zeros((F.n, 4))
    absolute = F.notint
    out[:, :3] = np.where(absolute[:, None], rgb_abs, rel)
    out[:, 3] = np.where(absolute, a_abs, a)
    return out


def paint_damage(F, heavy, seed=1997):
    rng = _rng(seed)
    acc = {k: np.zeros(F.n) for k in ("dv", "cover", "scrape", "gouge", "crack", "dark")}
    vul = _vulnerable(F)
    body = (F.paint | F.trim) & ~F.glass_body
    metal_like = F.metal | F.trim
    scale = 1.0 if not heavy else 1.7
    # light: small dents, scuffs, scratch bundles, stone chips at the front
    _dents(F, rng, int(70 * scale), 0.04, 0.12, 0.006 * scale, acc, vul * body)
    _strokes(F, rng, int(150 * scale), (0.12, 0.6), (0.002, 0.004), 0.32, acc, vul * metal_like)
    _strokes(F, rng, int(40 * scale), (0.3, 1.1), (0.0012, 0.0025), 0.16, acc, body * (F.pos[:, 2] > 0.6))   # keyed lines
    _strokes(F, rng, int(60 * scale), (0.05, 0.25), (0.002, 0.005), -0.30, acc, vul * metal_like, bundle=(1, 2))
    chips = (F.pos[:, 1] > 0.6) & (F.nrm[:, 1] > 0.2) & body
    for k in _pick(F, rng, int(500 * scale), chips.astype(float)):
        ids = F.near(F.pos[k], rng.uniform(0.003, 0.008), F.nrm[k])
        acc["dark"][ids] = np.maximum(acc["dark"][ids], rng.uniform(0.5, 1.0))
    # glass and lenses: a few chips (light), shattered from one to three impacts a pane (heavy)
    glass_w = F.window.astype(float) * (0.5 + 0.5 * (F.pos[:, 2] < 1.4))
    if not heavy:
        _cracks(F, rng, _pick(F, rng, 8, glass_w), 4, 0, (0.08, 0.16), acc)
    else:
        _cracks(F, rng, _pick(F, rng, 16, glass_w), 8, 1, (0.30, 0.55), acc)
    lamp_k = _pick(F, rng, 6 if not heavy else 12, F.lamp.astype(float))
    _cracks(F, rng, lamp_k, 4 if not heavy else 6, 0 if not heavy else 1, (0.05, 0.08) if not heavy else (0.10, 0.16), acc)
    if heavy:
        # crumples: big dents in clusters with fold lines, scraped bands with gouges, gouges alone
        crumple = vul ** 2 * body
        _dents(F, rng, 60, 0.12, 0.32, 0.03, acc, crumple)
        _dents(F, rng, 90, 0.05, 0.14, 0.02, acc, crumple)
        _strokes(F, rng, 70, (0.08, 0.35), (0.003, 0.006), -0.55, acc, crumple, vertical=0.9, bundle=(1, 2))   # fold creases
        _strokes(F, rng, 70, (0.08, 0.35), (0.002, 0.004), 0.20, acc, crumple, vertical=0.9, bundle=(1, 1))
        low = np.clip((1.05 - F.pos[:, 2]) / 0.5, 0, 1)                 # dragged along at bumper / sill height
        _scrape(F, rng, 28, (0.30, 0.90), (0.06, 0.18), acc, vul ** 2 * low * metal_like, seed + 7)
        _strokes(F, rng, 60, (0.15, 0.7), (0.012, 0.02), -0.40, acc, vul * metal_like, bundle=(1, 2))      # gouges
    # the brightness offset for the body: dents and strokes, chips dark
    dv = np.clip(acc["dv"], -0.45, 0.35)
    dv = np.where(acc["dark"] > 0, -0.40 * acc["dark"], dv)
    desat = np.zeros(F.n)
    if heavy:
        # a scrape grinds the paint to pale primer / metal (lighter, washed out), its gouges cut to bright
        # metal edged with dark grime; both in streaks along the drag, never texel-sized specks
        s, g = acc["scrape"], acc["gouge"]
        on = s > 0.02
        dv = np.where(on, np.maximum(dv, 0.22 * s) + 0.10 * g, dv)
        dv = np.where(on & (g > 0.25), np.maximum(dv, 0.28 * g), dv)
        desat = np.where(on, np.clip(0.75 * s + 0.25 * g, 0, 1), 0.0)
    # trim (cladding, rubbing strips) takes damage at half strength, but a scrape grinds it grey in full
    a_rel = np.where(F.paint | (acc["scrape"] > 0.05), 1.0, 0.55) * (~F.glass_body)
    # absolute colours where the shader takes them as they are
    rgb = np.zeros((F.n, 3))
    a_abs = np.zeros(F.n)
    glassy = F.window | F.lamp
    crack = acc["crack"]
    rgb[glassy] = np.array([0.86, 0.90, 0.92])
    a_abs[glassy] = np.clip(crack[glassy] * 0.88, 0, 1)
    bump = F.notint & ~glassy                                        # bumpers, grille, valance, tail panel
    primer = np.array([0.42, 0.43, 0.42])
    scuff = np.array([0.55, 0.55, 0.53])
    dark = np.array([0.07, 0.07, 0.07])
    dvb = dv[bump]
    rgb[bump] = np.where((dvb < 0)[:, None], dark, scuff)
    a_abs[bump] = np.clip(np.abs(dvb) * 2.2, 0, 0.9)
    if heavy:
        s, g = acc["scrape"][bump], acc["gouge"][bump]
        on = s > 0.05
        ib = np.flatnonzero(bump)[on]
        rgb[ib] = primer[None, :] * (1 - g[on, None]) + np.array([0.70, 0.70, 0.68])[None, :] * g[on, None]
        a_abs[ib] = np.clip(np.maximum(s[on] * 0.8, g[on]), 0, 0.95)
    out = _encode(F, dv, a_rel, a_abs, rgb, desat)
    # (armour fix) bare armour steel is never painted, but its texels sit in door / guard zones: a relative
    # dent there took the paint's hue (addDamage: hue = paint, s = s_tex + S - 0.5, v = v_tex + V - 0.5),
    # blue blotches on grey steel. v_tex 0 is black on every skin (paint V < 0.5): keep the dark dents and
    # gouges as neutral darkening, drop the light ones
    arm = np.char.startswith(F.obj.astype(str), "acc_armour") & ~F.notint
    if arm.any():
        dark = arm & (dv < 0)
        out[dark, :3] = 0.0
        out[dark, 3] *= 0.5
        out[arm & (dv >= 0), 3] = 0.0
    return out


def paint_rust(F, seed=1999):
    """Where rust grows first: sills and the lower door edges, round the wheel arches, the tailgate's
    and the hood's lower edges, the roof gutters; speckle elsewhere; runs down from the spots. Alpha
    is multiplied by the car's rust level, so it must stay low on the upper panels."""
    x, y, z = F.pos.T
    n = PP.vnoise(F.pos, 0.06, seed) * 0.6 + PP.vnoise(F.pos, 0.02, seed + 1) * 0.4
    fine = PP.vnoise(F.pos, 0.006, seed + 2)
    # the RD1's lower body is black plastic cladding up to ~0.7 m (measured on the Mask: no paint on the
    # sides under 0.55 m, 4 % at 0.55-0.7, 31 % at 0.7-0.85): rust shows on the painted metal's lowest
    # band just above it, round the arch lips and on the gate's and doors' lower edges
    sill = np.clip((0.95 - z) / 0.22, 0, 1)
    arch = np.zeros(F.n)
    for wx, wy, wz in WHEELS:
        side = np.sign(wx) == np.sign(x)
        r = np.hypot(y - wy, z - wz)
        arch = np.maximum(arch, side * (np.abs(x) > 0.55) * np.exp(-((r - 0.52) / 0.09) ** 2))
    door_low = np.isin(F.obj, ["door_fl", "door_fr", "door_rl", "door_rr"]) * np.clip((1.0 - z) / 0.25, 0, 1)
    gate_low = (F.obj == "trunk") * np.clip((0.95 - z) / 0.35, 0, 1)
    gutter = np.clip((z - 1.55) / 0.08, 0, 1) * np.clip((np.abs(x) - 0.55) / 0.1, 0, 1) * (np.abs(F.nrm[:, 2]) < 0.8)
    hood_edge = (F.obj == "hood") * np.clip((y - 1.55) / 0.15, 0, 1)
    core = np.maximum.reduce([sill, arch, door_low, gate_low, gutter * 0.7, hood_edge * 0.6])
    a = np.clip(core * (0.75 + 0.7 * n) + 0.3 * fine * core, 0, 1)
    speck = np.clip((n - 0.35) * 2.5, 0, 1) * np.clip((fine - 0.1) * 2, 0, 1) * 0.5
    a = np.maximum(a, speck)
    # runs: rust streaking down from what is above (sample the field 2-12 cm higher)
    for dz, k in ((0.03, 0.75), (0.07, 0.5), (0.12, 0.3)):
        up = F.pos + np.array([0.0, 0.0, dz])
        _d, j = F.tree.query(up, distance_upper_bound=0.02)
        ok = j < F.n
        streak = np.zeros(F.n)
        streak[ok] = a[j[ok]] * k * (PP.vnoise(F.pos[ok] * np.array([6.0, 6.0, 0.4]), 0.05, seed + 9) > 0.1)
        a = np.maximum(a, streak * (F.nrm[:, 2] < 0.5))
    a *= (F.metal | (F.trim & (F.gloss < 120) & (F.gloss > 60))) & ~F.window & ~F.lamp
    a = np.where(F.metal, a, a * 0.5)
    tone = np.clip(0.5 + 0.5 * n + 0.3 * fine, 0, 1)
    dark, mid, orange = np.array([0.20, 0.10, 0.05]), np.array([0.40, 0.19, 0.08]), np.array([0.60, 0.30, 0.11])
    rgb = np.where((tone < 0.5)[:, None], dark + (mid - dark) * (tone / 0.5)[:, None],
                   mid + (orange - mid) * ((tone - 0.5) / 0.5)[:, None])
    pit = fine > 0.55
    rgb[pit] *= 0.6
    return np.column_stack([rgb, a])


def _plane(nc, want):
    """`want` projected into the plane of normal nc, unit length (None when it is along the normal)."""
    v = np.asarray(want, dtype=np.float64) - nc * (nc @ want)
    n = np.linalg.norm(v)
    return v / n if n > 0.2 else None


def _drop(p, centre, along_dir, radius, stretch=1.0):
    """A droplet: 1 inside, 0 outside, soft over the last third; stretched `stretch` x along `along_dir`
    (a tadpole flung that way)."""
    d = p - centre
    if along_dir is not None and stretch != 1.0:
        a = d @ along_dir
        d = d - np.outer(a, along_dir) + np.outer(a / stretch, along_dir)
    return np.clip((1.0 - np.linalg.norm(d, axis=1) / radius) * 3.0, 0.0, 1.0)


def paint_blood(F, seed=2001):
    """Blood where the dead meet a car: splatters at body height, most on the front and the front
    doors, a few big sprays flung back from the front corners, drips running down from the big ones,
    smears on the side glass. Sizes follow a power law (many small spots, a few big ones) and no drop is
    smaller than about a shipped texel, so it never reads as even dots. Returns (colour, order) sheets."""
    rng = _rng(seed)
    x, y, z = F.pos.T
    height = np.exp(-((z - 0.85) / 0.45) ** 2)
    front = 0.5 + np.clip((y + 0.5) / 2.5, 0, 1)
    where = height * front * ~F.glass_body
    cov = np.zeros(F.n)
    order = np.zeros(F.n)
    tm0 = float(np.median(F.texel_m))
    back = np.array([0.0, -1.0, 0.35])                               # flung back along the car, a little up

    def put(ids, s, prio):
        cov[ids] = np.maximum(cov[ids], np.clip(s * 1.6, 0, 1))
        order[ids] = np.maximum(order[ids], s * prio)

    def drips(c, nc, r, prio):
        """1-4 runs down a near-vertical panel from the lower edge of a big spot."""
        down = _plane(nc, np.array([0.0, 0.0, -1.0]))
        if down is None or abs(nc[2]) > 0.6:
            return
        side = np.cross(nc, down)
        for _ in range(rng.integers(1, 5)):
            st = c + side * rng.uniform(-0.7, 0.7) * r + down * rng.uniform(0.2, 0.6) * r
            L = rng.uniform(0.06, 0.30)
            w = rng.uniform(0.55, 0.85) * tm0
            ids = F.near(st + down * L * 0.5, L * 0.5 + 4 * w, nc, same_zone=False, min_dot=0.3)
            if not len(ids):
                continue
            d = F.pos[ids] - st
            a, q = d @ down, d @ side
            q = q - 0.3 * w * np.sin(a * rng.uniform(25, 45))           # runs wander a little
            t = np.clip(a / L, 0.0, 1.0)
            run = np.exp(-(q / (w * (1.0 - 0.4 * t))) ** 2) * (a > -w) * (a < L)
            bulb = _drop(F.pos[ids], st + down * L, None, 1.3 * w)
            put(ids, np.maximum(run, bulb), prio * 0.9)

    # splatters: radius from a power law (3 cm up, a few over 15 cm); satellites flung round, none
    # under a texel
    for k in _pick(F, rng, 220, where):
        c, nc = F.pos[k], F.nrm[k]
        r = min(0.03 * (1.0 - rng.random()) ** (-1.0 / 1.2), 0.24)
        ids = F.near(c, r * 2.6, nc, same_zone=False, min_dot=0.2)
        if not len(ids):
            continue
        p = F.pos[ids]
        d = np.linalg.norm(p - c, axis=1)
        blob = np.clip(1.0 - d / r + 0.45 * PP.vnoise(p, max(r * 0.35, 1.5 * tm0), seed + k % 97), 0, 1)
        fling = _plane(nc, back)
        drops = np.zeros(len(ids))
        for _ in range(int(2 + 30 * r)):                             # satellite droplets, more round big spots
            off = rng.normal(0, r * 0.8, 3)
            if fling is not None:
                off += fling * abs(rng.normal(0, r * 0.9))
            dr = max(rng.uniform(0.12, 0.30) * r, 0.65 * tm0)
            drops = np.maximum(drops, _drop(p, c + off, fling, dr, rng.uniform(1.0, 2.2)))
        prio = rng.uniform(0.35, 0.85) + 0.15 * min(r / 0.1, 1.0)
        put(ids, np.maximum(blob, drops), prio)
        if r > 0.06:
            drips(c, nc, r, prio)
    # sprays from the front corners and the hood's front: a fan of drops flung back over the panel,
    # big near the hit and smaller with distance
    spray_w = where * np.clip((y - 1.3) / 0.5, 0, 1)
    for k in _pick(F, rng, 6, spray_w):
        c, nc = F.pos[k], F.nrm[k]
        fling = _plane(nc, back) if abs(nc[1]) < 0.7 else _plane(nc, np.array([0.0, 0.0, 1.0]))
        if fling is None:
            continue
        side = np.cross(nc, fling)
        R = rng.uniform(0.35, 0.6)
        ids = F.near(c + fling * R * 0.45, R * 0.65, nc, same_zone=False, min_dot=0.2)
        if not len(ids):
            continue
        p = F.pos[ids]
        s = np.clip(1.0 - np.linalg.norm(p - c, axis=1) / rng.uniform(0.05, 0.09)
                    + 0.4 * PP.vnoise(p, 0.03, seed + 500 + k % 89), 0, 1)
        for _ in range(rng.integers(14, 26)):                        # drops a few texels across, spaced
            t = min(rng.exponential(0.18), R)
            dc = c + fling * t + side * rng.normal(0, 0.05 + 0.35 * t)
            dr = max(rng.uniform(1.0, 2.4) * tm0 * np.exp(-t / 0.35), 0.8 * tm0)
            s = np.maximum(s, _drop(p, dc, fling, dr, 1.3 + 1.5 * t / R))
        prio = rng.uniform(0.75, 1.0)
        put(ids, s, prio)
        drips(c, nc, 0.06, prio)
    # smears on the glass: hands dragged down the windows
    for k in _pick(F, rng, 26, F.window.astype(float) * (z < 1.55)):
        c, nc = F.pos[k], F.nrm[k]
        ids = F.near(c, 0.2, nc, min_dot=0.2)
        if not len(ids):
            continue
        d = F.pos[ids] - c
        fwd = np.cross(nc, [0.0, 0.0, 1.0])
        fwd /= max(np.linalg.norm(fwd), 1e-6)
        across, down = d @ fwd, -d[:, 2]
        fingers = 0.5 + 0.5 * np.cos(across * 2 * np.pi / 0.022)
        s = (np.abs(across) < 0.045) * (down > -0.02) * (down < rng.uniform(0.08, 0.18)) * fingers
        s *= np.clip(1.0 - down / 0.2, 0, 1)
        cov[ids] = np.maximum(cov[ids], s * 0.9)
        order[ids] = np.maximum(order[ids], s * rng.uniform(0.4, 0.9))
    tone = np.clip(0.5 + 0.5 * PP.vnoise(F.pos, 0.03, seed + 2), 0, 1)
    rgb = np.column_stack([0.30 + 0.22 * tone, 0.02 + 0.03 * tone, 0.02 + 0.025 * tone])
    rgb *= (0.75 + 0.25 * cov)[:, None]
    blood = np.column_stack([rgb, np.clip(cov, 0, 1)])
    mask = np.column_stack([np.full((F.n, 3), 0.55), np.clip(order, 0, 1)])
    return blood, mask


def build(npz, mask_png, out_dir, report=print, size=SIZE, ss=SS):
    """Paint every sheet into out_dir; returns {key: path}."""
    F = Field(npz, mask_png, size * ss, report)
    report("FEATURE polish: damage space %d px, %d texels painted (%.0f%% of the sheet), %d glass, %d lamp, %d body paint"
           % (F.size, F.n, 100.0 * F.n / F.size ** 2, int(F.window.sum()), int(F.lamp.sum()), int(F.paint.sum())))
    sheets = {"light": paint_damage(F, False), "heavy": paint_damage(F, True), "rust": paint_rust(F)}
    sheets["blood"], sheets["blood_mask"] = paint_blood(F)
    out = {}
    for key, vals in sheets.items():
        img = _reduce(F.image(vals), ss)
        p = os.path.join(out_dir, "%s_%s.png" % (NAME, SHEETS[key]))
        _save(img, p)
        out[key] = p
        a = img[..., 3]
        report("FEATURE polish: %s -> %s (alpha > 0 on %.1f%%, mean %.3f)" % (key, os.path.basename(p), 100.0 * (a > 0.004).mean(), a.mean()))
    return out
