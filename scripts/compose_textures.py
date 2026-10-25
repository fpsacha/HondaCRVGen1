r"""
Compose the Project Zomboid texture set from the bake_atlas.py passes (system Python + Pillow).

    python scripts\compose_textures.py [--bake blender\bake] [--out <mod textures dir>] [--preview <png>]

Inputs (blender/bake):  shell_color, shell_ao, shell_cavity, shell_gap, shell_rubber, shell_zone,
                        shell_lights, shell_lampmask, shell_trimmask, shell_grime, and per other
                        space <space>_color / _ao / _cavity / _cov / _grime; optional
                        shell_uvmesh.npz (uvmesh_dump.py: the shell layout's triangles)
Outputs (mod textures): Vehicles_HondaCRVGen1_Shell.png + one _Shell<skin> per paint, _Mask, _Lights,
                        _Rust, _Interior, _Wheel, _Engine

What the vehicle_multiuv shader expects (media/shaders/vehicle_multiuv.frag, vehicle.frag):
  Shell   opaque RGB. Alpha < 1 would be tinted with the vehicle's random paint HSV; KI5 ships opaque
          shells and one texture per colour, so do we.
  Mask    RGB part-zone map, compared with a 0.01 tolerance against the colZone table: white = body,
          doors / windows / hood / boot / guards / roof / lamp zones each their own colour. Drives
          uninstall greying, per-zone lights, damage and blood, and window reflections.
  Lights  RGBA at the shell's size; mixed in by ALPHA after the scene light where a zone's lights are
          on: the lit lens's picture (lights_lit), alpha on the lit lenses only, anti-aliased at the rim.
  Rust    RGBA sampled through UV set 2; mixed in by alpha times the vehicle's rust level.

Shading is colour x (1 - K + K * AO) x cavity x seam. Without shell_uvmesh.npz, skins recolour the
painted texels (zone-white texels of the Body material, taken from the bake colour) by the ratio
target / kotris-paint per channel: the compose of 2026-10-12, byte for byte.

With shell_uvmesh.npz, paint_pass.PaintPass (spec/planar-texture-plan.md Part B) takes over the
shell: the bake's flat paint shipped white at sRGB ~195 against KI5's 102-114, with every line a
fuzzy AO shadow. It levels each skin to KI5's absolute levels, puts the form in the texture (height
ramp, brighter tops), draws seams, creases, lamp bezels and glass seals from the triangles under
each texel, then weathering with a dirt that tints but never lifts (DIRT_REL) and the dark blocks
last.

What the game does with these files (2026-10-12, projectzomboid.jar B42): model textures are never
mipmapped (GL_LINEAR min and mag), and are box-halved at load until they fit the player's texture
size option (default 512 for vehicle* shaders). Every line drawn here must survive one halving:
nothing thinner than 2 texels, nothing that is only noise.

Anti-aliased bake (bake_atlas.SUPERSAMPLE, 2026-10-13): the bake images are SUPERSAMPLE x each sheet's
size and everything here runs at that size (Dilate, shading, the paint pass, lights, mask); each shipped
sheet is reduced to its sheet size (bake_atlas.SPACES) as its very last step (reduce_box: the mean of
every SS x SS block, the anti-aliasing; reduce_zones: the Mask's zones by majority, exact legal colours).
Texel-sized constants here (DECLUTTER) are in SHEET texels and scaled to the bake. A bake at the sheet
size (SS 1) composes as before.
"""
import argparse
import json
import os
import sys

import numpy as np
from PIL import Image, ImageFilter
from scipy import ndimage

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import paint_textures as PT                     # SKINS palette, rust(), NAME, TEX_DIR
import features                                 # scripts/features: the plugins' own sheets and COMPOSE hooks

ROOT = os.environ.get("CRV_ROOT") or os.path.dirname(HERE)
BAKE_DIR = os.path.join(ROOT, "blender", "bake")
# Shading depth (2026-10-12, measured on the shipped 2048 shell with scratch shell_measure.py):
# 13.9 % of the paint texels shipped below 0.60 of their clean colour and 17.8 % below 0.80, the
# large AO (0.45, gamma 0.8) and the 4 cm cavity (0.55) between them; KI5's paint is flat with a
# gentle gradient and its lines come from drawn seams, not from occlusion. Halved, and the gamma
# that deepened the AO dropped.
AO_K = 0.30
AO_GAMMA = 1.0
CAVITY = 0.25                                   # depth of the 4 cm cavity AO in the shading
# per sheet: how deep the AO shades (the bay's fine shadows are real and wanted but it sits in the
# hood's shadow in game: shallower AO and a lift), and a brightness gain applied before shading. The
# cabin's in-game brightness is GAIN["interior"], one compose run, no rebake: the first in-game look
# against KI5's Bronco (interior sheet mean sRGB 29) decides between 1.0 and ~1.3.
AO_K_SPACE = {"shell": AO_K, "interior": 0.50, "engine": 0.30, "wheel": AO_K}
GAIN = {"shell": 1.0, "interior": 1.0, "engine": 1.0, "wheel": 1.0}   # engine 1.18 read white in the game's lit bay (2026-10-17)
BODY_LINEAR = (0.573, 0.545, 0.486)             # kotris "Body" Principled base colour
PAINT_TOL = 14                                  # sRGB distance that still counts as the paint colour
KEY = np.array([255, 0, 255])                   # bake_atlas KEY: texel no island covers
KEY_TOL = 6
# Seam lines from the 1.2 cm gap pass (bake_atlas.GAP_DISTANCE): gap AO <= GAP_LO is a full seam,
# >= GAP_HI open surface; a seam darkens the texel by GAP_DARK. KI5's gaps are a 1-texel dark line
# at 0.6 texels/cm; at our ~1 texel/cm the 1.2 cm reach gives 1-2 texels a side.
LIGHTS_REDUCE = 2                              # the Lights sheet ships at shell size / this (2026-10-19)
GAP_DARK = 0.60
GAP_LO = 0.30
GAP_HI = 0.60
LAMP_GAP = 1.0                                  # share of GAP_DARK applied on lamp texels (their outline)
# window seals (bake_atlas.RUBBER_WIDTH, shell_rubber.png): near-black and matte, like KI5's
RUBBER_RGB = (24, 25, 27)
RUBBER_GLOSS = 0.12
# grey closing on AO and cavity: 3 texels at 1.9 texels/cm (2048) erased everything thinner than
# 1.6 cm, a drawn panel gap's width; 2 at ~1 texel/cm (1024) still drops the hood's dashed creases
DECLUTTER = 2
# Colour despeckle / deblotch per space: {space: luma levels} and {space: (levels, max alike)}; see
# despeckle(). Both were for the engine's v1 projection bake (a full-detail twin projected onto a coarse
# copy: flush faces picked texel by texel, 11.7 % salt-and-pepper texels, smudged clumps). The v2 bay
# (spec/engine-bay-v2.md, 2026-10-17) self-bakes its own flat colours, so neither runs on any sheet now.
DESPECKLE = {}
DEBLOTCH = {}


def coverage(cov):
    """True where the white coverage bake fully owns the texel (island or bake margin); partially
    covered edge texels (grey) and the background (black) are False."""
    return np.asarray(cov, dtype=np.uint8) >= COVER_MIN


COVER_MIN = 250


class Dilate:
    """Nearest-baked-texel fill for one UV space: build once from the coverage bake, apply to every
    image of that space so they stay in register."""

    def __init__(self, cov, colour=None):
        self.touched = np.asarray(cov, dtype=np.uint8) > 0         # any coverage (paint_pass's stale-dump check)
        cov = coverage(cov)
        keyed = 0.0
        if colour is not None:
            # texels the coverage bake owns but the colour bake never wrote still hold the KEY (a
            # projection ray that missed its twin, a margin the two passes drew differently): in
            # game they were magenta specks all over the cabin and the engine bay (2026-10-11).
            # Treat anything still purple as unbaked and fill it from the nearest real texel.
            c = np.asarray(colour.convert("RGB"), dtype=np.int32)
            r, g, b = c[..., 0], c[..., 1], c[..., 2]
            key = (r > g * 1.6 + 15) & (b > g * 1.6 + 15) & (r > 50)
            # ... and the bake margin's blends of the KEY into a real colour at an island edge, e.g.
            # (162, 108, 164) round the windowed rim's holes (2026-10-12: 144 purple texels on the
            # wheel sheet, ~460 on the shell before). Purple-tinted AND next to the KEY or the
            # background, so no real colour far from an edge is touched
            tint = (r - g > 30) & (b - g > 30) & (np.abs(r - b) < 40)
            edge = ndimage.binary_dilation(key | ~cov, iterations=2)
            key = key | (tint & edge)
            keyed = float((key & cov).mean() * 100.0)
            cov = cov & ~key
        self.cov = cov
        self.idx = ndimage.distance_transform_edt(~cov, return_distances=False, return_indices=True)
        print("dilate: %.0f%% of texels baked, filling the rest from the nearest island (%.2f%% keyed inside islands)"
              % (cov.mean() * 100.0, keyed))

    def __call__(self, img):
        a = np.asarray(img)
        out = a[self.idx[0], self.idx[1]]
        return Image.fromarray(np.ascontiguousarray(out))


def sheet_sizes():
    """{space: shipped sheet size} from bake_atlas.SPACES (a literal, read without importing bpy)."""
    import paint_pass
    return {k: int(v[1]) for k, v in features.spaces(paint_pass._bake_const("SPACES")).items()}


def bake_factor(space, bake, sheet):
    """The supersampling factor of a space's bake images: bake size / sheet size, a whole number. A
    bake smaller than the sheet (one from before the sheet grew, e.g. the 256 wheel) ships as baked."""
    if bake < sheet:
        print("reduce: warning %s baked at %d px, under its %d px sheet: shipped at %d (re-bake)" % (space, bake, sheet, bake))
        return 1
    if bake % sheet:
        raise ValueError("%s baked at %d px is no whole multiple of its %d px sheet" % (space, bake, sheet))
    return bake // sheet


def reduce_box(img, k):
    """The shipped sheet from a supersampled one: every k x k block's mean (per channel, in the stored
    sRGB values, as the game's own load-time halving averages them), rounded. k = 1 returns it as is."""
    if k == 1:
        return img if isinstance(img, Image.Image) else Image.fromarray(np.ascontiguousarray(img))
    a = np.asarray(img)
    h, w = a.shape[0] // k, a.shape[1] // k
    f = a[:h * k, :w * k].astype(np.float32).reshape((h, k, w, k) + a.shape[2:]).mean(axis=(1, 3))
    return Image.fromarray(np.clip(f + 0.5, 0, 255).astype(np.uint8))


def _zone_priority(codes):
    """Tie-break rank of zone colours (24-bit codes) in reduce_zones: lamp zones first (a lens rim
    texel that loses its zone stays dark while lit; on a body texel a lamp zone shows nothing, its
    Lights alpha is 0), window zones last (the shader discards a window's zone when that window is
    down or gone: a frame texel taking it would open a hole), everything else between."""
    import paint_pass
    rank = {}
    for name, rgb in paint_pass.ZONE.items():
        c = [int(np.clip(v * 255.0 + 0.5, 0, 255)) for v in rgb]
        code = (c[0] << 16) | (c[1] << 8) | c[2]
        rank[code] = 2 if name.startswith(("lights_", "stop_")) else 0 if name.startswith("window_") else 1
    u, inv = np.unique(codes, return_inverse=True)
    return np.array([rank.get(int(c), 1) for c in u], dtype=np.int32)[inv.reshape(-1)].reshape(codes.shape)


def reduce_zones(img, k):
    """The Mask's zone colours (RGB uint8, legal colours only) reduced k x k -> 1 by MAJORITY: the shader
    matches each zone within 0.01, so an average would invent colours that are no zone. Ties go by
    _zone_priority, then to the block's first texel."""
    a = np.asarray(img, dtype=np.uint8)[..., :3]
    if k == 1:
        return Image.fromarray(np.ascontiguousarray(a))
    h, w = a.shape[0] // k, a.shape[1] // k
    code = (a[..., 0].astype(np.int32) << 16) | (a[..., 1].astype(np.int32) << 8) | a[..., 2].astype(np.int32)
    blk = code[:h * k, :w * k].reshape(h, k, w, k).transpose(0, 2, 1, 3).reshape(h, w, k * k)
    votes = (blk[..., :, None] == blk[..., None, :]).sum(-1)                      # (h, w, k*k)
    score = votes * (8 * k * k) + _zone_priority(blk) * (2 * k * k) + (k * k - 1 - np.arange(k * k))
    best = np.take_along_axis(blk, score.argmax(-1)[..., None], -1)[..., 0]
    out = np.stack([(best >> 16) & 255, (best >> 8) & 255, best & 255], axis=-1).astype(np.uint8)
    return Image.fromarray(out)


# Lamp guard (bug wave 1, H-VISUAL-1, 2026-10-24). The game shrinks the 2048 Mask to the player's Vehicle
# Texture Size (256 / 512 default / 1024 / 2048) by repeated 2 x 2 integer averages (ImageData.generateMipMaps),
# then samples it bilinearly; the shader lights a fragment only where that sample lies within 0.01 of a lamp
# zone's colour. Every averaged block or bilinear footprint that straddles a lamp zone and anything else (the
# body round the lens, the tail / stop split inside the lens) is no zone: the lit tail lamps drew dark
# squiggles at 512 (85.5 % of lamp texels kept their zone; 68.5 % at 256). lamp_guard() makes the Mask round
# every lit lens whole LAMP_GUARD_CAP blocks (sheet / 256 = 8 texels at 2048): every block holding a lit
# texel, and the ring of blocks round it (the bilinear footprint at the coarsest cap), carries ONE lamp zone
# throughout. A pure block averages to itself at every cap, so the lens keeps its zone at 2048 down to 256.
#   * (wave 1, off since bug wave 3: LAMP_ONE_ZONE False) one lamp zone per lens: bake_atlas splits the D-pillar tail lens at TAIL_STOP_Z, upper half
#     stop_*, lower half lights_*t (2026-10-17, so braking lit the cluster). Any edge between two zones inside a
#     lit lens is dark at every cap (a bilinear sample between two zone colours matches neither); after the
#     guard it still drew a dark blotch across the lens at 512 and 256 (pzview --lights tail,brake --night).
#     So a lit lens (8-connected texels with alpha >= LAMP_GUARD_ALPHA) holding a tail zone takes that side's
#     tail zone on its stop texels too. The game has no zone lit by both (BaseVehicle lights stop_* from
#     stoplightsOn alone), so the mod's shader lights a tail zone as a combined stop / tail lamp: dimmed
#     (gen_shaders.TAIL_LEVEL) with the lights, full while braking (gen_shaders LAMP_RULE). The tail zone, not
#     the stop zone, because Project Viewpoint places the car's rear lamps from the tail zones and glows a lens
#     by its zone's game enables; the high stop lamp keeps its one stop zone. Bug wave 3 (H-VP-1): Viewpoint never
#     runs the mod's shader, so it lit that all-tail lens with the lights only and, braking in daylight, only the
#     high stop lamp (while still glowing red at the dark lenses). Now bake_atlas packs the lens's tail and stop
#     parts as separate islands planar_uv.GROUP_GAP apart (one rigid group per side), so each part's blocks are
#     pure without the merge: the game and Viewpoint light the tail part with the lights and the stop part on the
#     brake, and mark_combined_stop tags the stop part (stop_rc / stop_lc) for the mod's combined rule;
#   * the zone of a block is the alpha-weighted majority of the lamp zones under its lit texels; ring blocks
#     take the nearest lit block's zone;
#   * window zones are kept in the ring blocks (the shader discards a removed window's zone: a lamp texel
#     there would stop the hole), but taken inside a lit block: the high stop lamp's lens lies on the rear
#     glass's texels in places, and a mixed block is no zone at 256 (its top and bottom went dark); the rest of
#     the lens's own surface under the guard (the lamp's rim, the panel within LAMP_GUARD_NEAR) takes the lamp zone;
#   * Lights alpha below LAMP_GUARD_ALPHA counts as unlit (a 5 % mix missing is invisible; Project Viewpoint
#     places its beams from texels with alpha >= 0.1);
#   * only the lens's own surface (bug wave 2, R2-VIS-1, 2026-10-25): the blocks are UV squares, and on the packed
#     sheet they reached into neighbouring UV islands far from the lens on the car (hood front lip, front fender
#     top, rear quarter, D-pillar strips, specks by the mirrors and grille): a removed lamp greyed those panels and
#     damage / blood followed the lamp there (wave 1 put a lamp zone on 9k covered texels farther than 3 cm from
#     every lens). With the shell's triangle dump (shell_uvmesh.npz, lens_geometry) the guard rezones a COVERED
#     texel only when its point on the car lies within LAMP_GUARD_NEAR of a lens texel (covered, lit, and a lamp
#     zone in the bake); gutter texels (no triangle: never drawn, only averaged into the smaller caps) are all free to take
#     the zone, which keeps the lens's blocks pure across its gutter. Lit texels farther from every lens (Lights
#     alpha bled onto a neighbouring island: spare tyre tread, liners, accessories) are no lens: they neither seed
#     a block nor take a lamp zone. Where another island lies within a block of a lens across the 8 px gutter, its
#     texels keep their zones: the far panel wins, the lens edge there goes unlit at the 256 cap only (lit
#     fragments on the lens's surface 100 / 100 / 100 / 99.8 % at 2048 / 1024 / 512 / 256, lampcov --lens).
# The shipped Mask stays 2048 RGB (zone edges elsewhere keep their 2048 detail for players at 2048).
LAMP_GUARD_CAP = 256
LAMP_GUARD_ALPHA = 13
LAMP_GUARD_REACH = 3            # blocks: a ring block takes the zone of a lit block at most this far
# a lit lens with a tail zone is all tail (wave 1): still the rule for a bake whose layout has no rigid lens groups
# (planar_uv meta "rigid_groups" 0: the tail / stop edge runs inside one island), never for one that has them
# (lamp_guard's merge; compose's main reads the layout: lens_groups)
LAMP_ONE_ZONE = True
COMBINED_MIN_X = 0.15           # m off the centre line: stop texels beyond are the D-pillar lens (bake_atlas.STOP_BOX)
LAMP_GUARD_NEAR = 0.03          # m: the guard rezones only texels this close (on the car) to a lens texel
LAMP_ISLAND_SHARE = 0.5         # ... or texels of a UV island at least this share lens (the lens's own island)


def lens_geometry(npz_path, size):
    """(pos, covered, island) of the shell sheet at `size` from the triangle dump (uvmesh_dump.py): pos (size,
    size, 3) float32, every texel's point on the car (metres, the dump's frame; a texel no triangle covers takes
    the point of the nearest covered texel); covered (size, size) bool, a triangle covers the texel's centre;
    island (size, size) int, the UV island of that triangle (-1: the shared fallback charts). None when the dump
    is missing or empty."""
    if not npz_path or not os.path.exists(npz_path):
        return None
    import paint_pass
    D = np.load(npz_path)
    uv = D["tri_uv"].astype(np.float64)
    x, y = uv[..., 0] * size, (1.0 - uv[..., 1]) * size
    tri, bary = paint_pass.rasterise(x, y, np.ones(len(x), np.int64), size)
    covered = tri >= 0
    if not covered.any():
        return None
    _d, (ir, ic) = ndimage.distance_transform_edt(~covered, return_indices=True)
    t, b = tri[ir, ic], bary[ir, ic].astype(np.float64)
    pos = (D["tri_pos"].astype(np.float64)[t] * b[..., None]).sum(-2).astype(np.float32)
    # per UV island, the lowest centre height of its triangles (the split lens: bake_atlas cuts its faces at
    # TAIL_STOP_Z by their centres, so a stop island's lowest centre lies above it, a tail island's below)
    ti = D["tri_island"].astype(np.int64)
    cz = D["tri_pos"][..., 2].astype(np.float64).mean(-1)
    minz = np.full(max(1, int(ti.max()) + 1), np.inf)
    np.minimum.at(minz, np.maximum(ti, 0), np.where(ti >= 0, cz, np.inf))
    return pos, covered, ti[t], minz


def lens_surface(code, lit, lcodes, geo, near=LAMP_GUARD_NEAR):
    """(near, own), (H, W) bool each. near: the texel's point on the car (a gutter texel's: its nearest covered
    texel's) lies within `near` m of a lens texel (covered, lit and already a lamp zone): only such lit texels seed guard
    blocks. own: the texels the guard may rezone, near ones and every gutter texel. geo = lens_geometry(...) or
    None (every texel both: the wave-1 rule)."""
    if geo is None:
        return np.ones(code.shape, dtype=bool), np.ones(code.shape, dtype=bool)
    from scipy.spatial import cKDTree
    pos, covered = geo[0], geo[1]
    if pos.shape[:2] != code.shape or covered.shape != code.shape:
        raise ValueError("lamp_guard: lens geometry %s does not match the Mask %s" % (pos.shape[:2], code.shape))
    # covered texels only: a lit gutter texel carries the lens's dilated zone but the point of whichever covered
    # texel is nearest, often the next island's (a front fender top took the tail lamp's zone that way)
    seeds = lit & np.isin(code, lcodes) & covered
    close = np.zeros(code.shape, dtype=bool)
    if seeds.any():
        p = np.asarray(pos, dtype=np.float32)
        dd, _i = cKDTree(p[seeds]).query(p.reshape(-1, 3), distance_upper_bound=near * 1.0001, workers=-1)
        close = (dd <= near).reshape(code.shape)
    own = close | ~covered
    if len(geo) > 2 and seeds.any() and LAMP_ISLAND_SHARE < 1.0:
        # the lens's own UV islands (most of their texels lens) are its surface wherever they reach
        isl = np.asarray(geo[2])
        ids, n_seed = np.unique(isl[seeds], return_counts=True)
        n_cov = np.array([int(((isl == i) & covered).sum()) for i in ids])
        lens_isl = ids[(ids >= 0) & (n_seed >= LAMP_ISLAND_SHARE * n_cov)]
        own |= np.isin(isl, lens_isl) & covered
    return close, own


def _zone_codes(prefixes):
    import paint_pass
    out = {}
    for name, rgb in paint_pass.ZONE.items():
        if name.startswith(prefixes):
            c = [int(np.clip(v * 255.0 + 0.5, 0, 255)) for v in rgb]
            out[name] = (c[0] << 16) | (c[1] << 8) | c[2]
    return out


def lens_groups(meta):
    """How many rigid lens groups the shell layout packed (planar_uv meta "rigid_groups"; bake_atlas LENS_GROUPS):
    0 for a layout from before bug wave 3 (the D-pillar lens's tail / stop edge inside one island). meta: the
    layout meta dict, its JSON text, or a path to shell_layout_meta.json / shell_uvmesh.npz; 0 when unreadable."""
    try:
        if isinstance(meta, str) and meta.endswith(".npz"):
            meta = str(np.load(meta)["meta"])
        elif isinstance(meta, str) and os.path.exists(meta):
            meta = open(meta, encoding="utf-8").read()
        if isinstance(meta, str):
            meta = json.loads(meta)
        return int(meta.get("rigid_groups", 0))
    except (OSError, ValueError, KeyError, AttributeError, TypeError):
        return 0


def lamp_guard(zones, alpha, cap=LAMP_GUARD_CAP, thr=LAMP_GUARD_ALPHA, log=print, geo=None, near=LAMP_GUARD_NEAR,
               merge=None):
    """The Mask's zones (RGB uint8 image or array, the shipped size) with every lit lens wrapped in whole
    blocks of one lamp zone (see LAMP_GUARD_CAP). alpha: the shipped Lights alpha (uint8, any size that
    divides the Mask's). geo: lens_geometry at the Mask's size; with it the guard keeps to the lens's own
    surface (lens_surface; without it every texel of the blocks, the wave-1 rule). merge: a lit lens holding a
    tail zone takes it on its stop texels too (None: LAMP_ONE_ZONE; compose passes lens_groups(...) == 0).
    Returns (image, stats)."""
    z = np.array(np.asarray(zones, dtype=np.uint8)[..., :3])
    H, W = z.shape[:2]
    b = max(1, H // cap)
    a = np.asarray(alpha, dtype=np.uint8)
    k = H // a.shape[0]
    a = np.repeat(np.repeat(a, k, 0), k, 1)[:H, :W].astype(np.float32)
    code = (z[..., 0].astype(np.int64) << 16) | (z[..., 1].astype(np.int64) << 8) | z[..., 2]
    lamps = _zone_codes(("lights_", "stop_"))
    windows = set(_zone_codes(("window_",)).values())
    names, lcodes = list(lamps), np.array(list(lamps.values()), dtype=np.int64)
    nh, nw = H // b, W // b
    # one lamp zone per lens (LAMP_ONE_ZONE): a lit lens that holds a tail zone takes it on its stop texels too
    lit = a >= thr
    lab, n = ndimage.label(lit, structure=np.ones((3, 3), bool))
    merged = 0
    vcode = code                                       # the zones the blocks vote with
    if n and (LAMP_ONE_ZONE if merge is None else merge):
        for stop, tail in (("stop_r", "lights_rt"), ("stop_l", "lights_lt")):
            has_tail = np.zeros(n + 1, bool)
            has_tail[np.unique(lab[lit & (code == lamps[tail])])] = True
            has_tail[0] = False
            sel = (vcode == lamps[stop]) & has_tail[lab]
            merged += int(sel.sum())
            vcode = np.where(sel, lamps[tail], vcode)

    # split lens (bug wave 3): each UV island of the D-pillar lens is one part, tail or stop (bake_atlas LENS_GROUPS);
    # texels of the other part's zone on it (the zone bake projects the full-detail twin, whose faces split at
    # TAIL_STOP_Z on their own) take the island's part: stop when its lowest triangle centre lies above TAIL_STOP_Z
    # (lens_geometry's 4th array), else (no heights) its alpha-weighted majority
    stats_unified = 0
    if geo is not None and len(geo) > 2 and not (LAMP_ONE_ZONE if merge is None else merge):
        isl, cov = np.asarray(geo[2]), np.asarray(geo[1])
        minz = np.asarray(geo[3]) if len(geo) > 3 else None
        import paint_pass
        cut = float(paint_pass._bake_const("TAIL_STOP_Z"))
        for pa, pb in (("lights_rt", "stop_r"), ("lights_lt", "stop_l")):
            ca, cb = lamps[pa], lamps[pb]
            # covered texels decide; gutter texels (geo's island: their nearest covered texel's) follow, the Dilate
            # spread the wrong part into them and their lit Lights alpha voted it back into the guard's blocks
            sel = (isl >= 0) & ((code == ca) | (code == cb))
            sc = sel & cov
            if not sc.any():
                continue
            ids = isl[sc]
            k = int(isl[sel].max()) + 1
            wa = np.bincount(ids, weights=np.where(code[sc] == ca, a[sc] + 1e-3, 0.0), minlength=k)
            wb = np.bincount(ids, weights=np.where(code[sc] == cb, a[sc] + 1e-3, 0.0), minlength=k)
            mixed = (wa > 0) & (wb > 0)
            want = np.where(wa >= wb, ca, cb)
            if minz is not None and len(minz) >= k:
                # by height: every island that is mostly this lens (a whole island can carry the wrong part)
                n_cov = np.bincount(isl[cov & (isl >= 0)], minlength=k)[:k]
                mixed = np.bincount(ids, minlength=k) >= 0.5 * np.maximum(n_cov, 1)
                want = np.where(minz[:k] > cut, cb, ca)
            if not mixed.any():
                continue
            fix = sel & mixed[np.where(sel, isl, 0)] & (code != want[np.where(sel, isl, 0)])
            new = want[isl[fix]]
            code = code.copy()
            code[fix] = new
            vcode = vcode.copy()
            vcode[fix] = new
            z[fix] = np.stack([(new >> 16) & 255, (new >> 8) & 255, new & 255], -1).astype(np.uint8)
            stats_unified += int(fix.sum())

    # the lens's own surface (R2-VIS-1): lit texels near a lens seed the blocks; only `own` texels are rezoned
    close, own = lens_surface(code, lit, lcodes, geo, near)

    def blocks(x):
        return x[:nh * b, :nw * b].reshape(nh, b, nw, b).transpose(0, 2, 1, 3).reshape(nh, nw, b * b)
    cb, ab = blocks(vcode), blocks(a)
    litb = (ab >= thr) & blocks(close)
    lit_blk = litb.any(-1)
    votes = np.stack([(((cb == c) & litb) * ab).sum(-1) for c in lcodes], -1)
    assigned = votes.max(-1) > 0
    zone_blk = votes.argmax(-1)
    need = ndimage.binary_dilation(lit_blk, structure=np.ones((3, 3), bool))
    stats = {"block": b, "lit_blocks": int(lit_blk.sum()), "guard_blocks": 0, "changed": {}, "window_kept": 0,
             "unassigned_lit_blocks": 0, "merged_stop": merged, "unified": stats_unified, "far_kept": 0, "stray_lit": int((lit & ~close).sum())}
    if not assigned.any():
        return Image.fromarray(z), stats
    dist, idx = ndimage.distance_transform_edt(~assigned, return_indices=True)
    need &= dist <= LAMP_GUARD_REACH
    stats["unassigned_lit_blocks"] = int((lit_blk & ~need).sum())
    zi = zone_blk[idx[0], idx[1]]
    target = np.where(need, lcodes[zi], -1)
    tfull = np.repeat(np.repeat(target, b, 0), b, 1)
    tt = np.full(code.shape, -1, dtype=np.int64)
    tt[:nh * b, :nw * b] = tfull
    litfull = np.zeros(code.shape, dtype=bool)
    litfull[:nh * b, :nw * b] = np.repeat(np.repeat(lit_blk, b, 0), b, 1)
    win = np.isin(code, list(windows)) & ~litfull     # a lit block is all lamp: the high stop lamp sits on the rear glass
    write = (tt >= 0) & ~win & (code != tt) & own
    stats["far_kept"] = int(((tt >= 0) & ~win & (code != tt) & ~own).sum())
    stats["guard_blocks"] = int(need.sum())
    stats["window_kept"] = int(((tt >= 0) & win).sum())
    u, c = np.unique(code[write], return_counts=True)
    stats["changed"] = {"%06x" % int(uu): int(cc) for uu, cc in zip(u, c)}
    nc = tt[write]
    z[write] = np.stack([(nc >> 16) & 255, (nc >> 8) & 255, nc & 255], -1).astype(np.uint8)
    log("mask: lamp guard %d px blocks (cap %d): %d lit blocks, %d guarded, %d texels rezoned (%s), %d window "
        "texels kept, %d lit blocks out of reach, %d split-lens texels unified to their island's part; %s" % (
            b, cap, stats["lit_blocks"], stats["guard_blocks"], int(write.sum()),
            ", ".join("%s %d" % t for t in sorted(stats["changed"].items(), key=lambda t: -t[1])[:6]),
            stats["window_kept"], stats["unassigned_lit_blocks"], stats["unified"],
            "lens surface only (%.0f cm): %d texels of other islands kept, %d stray lit texels no lens"
            % (100 * near, stats["far_kept"], stats["stray_lit"]) if geo is not None else "no lens geometry (whole blocks)"))
    return Image.fromarray(z), stats


def mark_combined_stop(zones, geo, log=print):
    """The shipped Mask's D-pillar stop texels tagged as the combined stop / tail lens (bug wave 3, H-VP-1):
    stop_r / stop_l -> stop_rc / stop_lc (bake_atlas.ZONE: blue 2/255, still the stop zone within the 0.01 the
    game and Project Viewpoint match by) wherever the texel's point on the car (lens_geometry; a gutter texel's
    is its nearest covered texel's) lies more than COMBINED_MIN_X off the centre line. The high stop lamp (|x| <
    0.09) keeps plain stop_l. Run after lamp_guard: the guard's blocks round the lens are stop throughout and
    all lie by the lens, so they stay pure. Returns (image, texels tagged); geo None tags nothing."""
    z = np.array(np.asarray(zones, dtype=np.uint8)[..., :3])
    if geo is None:
        log("mask: no lens geometry, the combined stop / tail lens is not tagged (its stop part lights on the brake only)")
        return Image.fromarray(z), 0
    pos = np.asarray(geo[0])
    if pos.shape[:2] != z.shape[:2]:
        raise ValueError("mark_combined_stop: lens geometry %s does not match the Mask %s" % (pos.shape[:2], z.shape[:2]))
    codes = _zone_codes(("stop_",))
    code = (z[..., 0].astype(np.int64) << 16) | (z[..., 1].astype(np.int64) << 8) | z[..., 2]
    side = np.abs(pos[..., 0]) > COMBINED_MIN_X
    n = 0
    for plain, comb in (("stop_r", "stop_rc"), ("stop_l", "stop_lc")):
        sel = (code == codes[plain]) & side
        c = codes[comb]
        z[sel] = np.array([(c >> 16) & 255, (c >> 8) & 255, c & 255], dtype=np.uint8)
        n += int(sel.sum())
    log("mask: %d stop texels of the D-pillar lenses tagged as the combined stop / tail lamp (stop_rc / stop_lc)" % n)
    return Image.fromarray(z), n


def _lin2srgb(c):
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


PAINT_SRGB = np.array([255.0 * _lin2srgb(c) for c in BODY_LINEAR])   # ~ (198, 194, 183)


def _load(name, mode="RGB"):
    return Image.open(os.path.join(BAKE_DIR, name + ".png")).convert(mode)


def declutter(ao, size=None):
    """Grey closing: drops dark AO features thinner than `size` texels. The kotris hood creases are
    5 mm step faces, under one texel; their occlusion bakes as a dashed dark line that reads as a
    scratch. Broad occlusion (arches, footwells) is untouched. Never applied to the gap pass: the
    seam lines are exactly the thin features this removes."""
    a = np.asarray(ao, dtype=np.uint8)
    size = size or DECLUTTER
    return Image.fromarray(ndimage.grey_closing(a, size=(size, size)))


def despeckle(img, thresh, passes=2, size=3, like_max=2):
    """Isolated outlier texels of a supersampled colour bake -> their 3x3 median (per channel): a texel whose
    luma is more than `thresh` levels from its 3x3 median AND that at most 2 of its 8 neighbours resemble
    (within thresh). At 2x a shipped texel is a 2 x 2 block, so anything a shipped texel wide or more
    (lettering strokes, decal lines, part edges: every texel of them has >= 3 like neighbours) is kept,
    and specks, pairs and triplets, which the 2 x 2 reduction would only turn into grey mottling, go.
    Two passes (on the engine bake: 3.72 % then 0.69 %, a third would take 0.13 %).
    Returns (image, share of texels replaced)."""
    a = np.asarray(img, dtype=np.float32)
    w = np.array([0.299, 0.587, 0.114], dtype=np.float32)
    done = np.zeros(a.shape[:2], dtype=bool)
    for _ in range(passes):
        L = a[..., :3] @ w
        med = ndimage.median_filter(a, size=(size, size, 1))
        H, W = L.shape
        r = size // 2
        p = np.pad(L, r, mode="edge")
        like = np.zeros(L.shape, dtype=np.int32)
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                if dy or dx:
                    like += np.abs(p[r + dy:r + dy + H, r + dx:r + dx + W] - L) <= thresh
        iso = (np.abs(L - med[..., :3] @ w) > thresh) & (like <= like_max)
        a[iso] = med[iso]
        done |= iso
    return Image.fromarray(np.clip(a + 0.5, 0, 255).astype(np.uint8)), float(done.mean())


def shade(color, ao, cavity=None, ao_k=AO_K, gain=1.0, cavity_k=None):
    """ao_k and cavity_k: scalars, or per-texel arrays (the paint pass lightens the AO on paint)."""
    c = np.asarray(color, dtype=np.float32) * gain
    a = (np.asarray(ao, dtype=np.float32) / 255.0) ** AO_GAMMA
    out = c * (1.0 - ao_k + ao_k * a)[..., None]
    if cavity is not None:                     # short-range AO: 1 in the open, dark in gaps and creases
        cv = np.asarray(cavity, dtype=np.float32) / 255.0
        k = CAVITY if cavity_k is None else cavity_k
        out = out * (1.0 - k * (1.0 - cv))[..., None]
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


def seam_mask(gap, lamp=None):
    """0..1 seam strength per texel from the 1.2 cm gap AO (see GAP_LO / GAP_HI)."""
    g = np.asarray(gap, dtype=np.float32) / 255.0
    seam = np.clip((GAP_HI - g) / (GAP_HI - GAP_LO), 0.0, 1.0)
    if lamp is not None:
        seam = np.where(lamp, seam * LAMP_GAP, seam)
    return seam


def darken(img, seam, depth=GAP_DARK):
    c = np.asarray(img, dtype=np.float32)
    return Image.fromarray(np.clip(c * (1.0 - depth * seam)[..., None], 0, 255).astype(np.uint8))


def paint_rubber(img, rubber, rgb=RUBBER_RGB):
    """rubber: the baked map as a bool mask, or the paint pass's anti-aliased coverage 0..1."""
    if np.asarray(rubber).dtype == bool:
        c = np.asarray(img, dtype=np.uint8).copy()
        c[rubber] = rgb
        return Image.fromarray(c)
    a = np.asarray(rubber, dtype=np.float32)[..., None]
    c = np.asarray(img, dtype=np.float32) * (1.0 - a) + np.array(rgb, dtype=np.float32) * a
    return Image.fromarray(np.clip(c + 0.5, 0, 255).astype(np.uint8))


# weathering (bake_atlas._GrimeOverride): dirt colour and how far the grime map pushes towards it,
# plus grime collecting in the panel gaps (from the cavity pass)
# shell 0.5 -> 0.35 with the planar repaint (2026-10-12): next to KI5's clean Touran through the same
# camera, the white skin's lower body read grubby and mottled; the drawn sill ramp now carries most of
# the darkening KI5 paints there
# shell and wheel 0 (2026-10-13): chose a SHOWROOM CLEAN exterior; the baked dirt maps stay
# so a used variant is a number away (was shell 0.35, wheel 0.3)
GRIME = {"shell": ((96, 88, 74), 0.0), "interior": ((58, 54, 48), 0.0), "engine": ((52, 48, 42), 0.0), "wheel": ((110, 100, 85), 0.0)}
# the feature plugins' own sheets (features.new_spaces): composed like the interior / wheel / engine below
FEATURE_SHEETS = features.new_spaces()
for _sp, _spec in FEATURE_SHEETS.items():
    AO_K_SPACE[_sp], GAIN[_sp], GRIME[_sp] = float(_spec["ao_k"]), float(_spec["gain"]), tuple(_spec["grime"])
GAP_GRIME = 0.15
# With the paint pass the shell's levels are KI5's absolute ones (white belt ~100, black ~30), under
# the dirt's own luma (~89): an absolute dirt colour lifted every mid and dark skin (low doors x1.28-1.43
# on red, blue, green, black, 2026-10-12) and erased the height ramp. There the dirt is relative: its
# luma is at most DIRT_REL of the texel's, so it tints brown and darkens, never lifts. 0.7 keeps the
# strength the playbook measures (paint texels darkened by more than 5 %: 8.5-10 % on every skin, master
# 10-11 % on the light ones) with the lower body at 0.69-0.72 of the belt (KI5's low verticals x0.70-0.77);
# 0.85 left the dirt nearly invisible (0.6-3.8 %), 0.5 pulled the lower doors to 0.65-0.68.
DIRT_REL = 0.7


# feature paints (the decals feature: features.swatch_mats, scripts/planar_uv.py): their swatch cells take the
# material's exact colour on every skin as the skins' last step (after paint pass, rubber, weather and dark
# fill), the zone of their host panel in the Mask, a paint gloss, nothing lit. No feature paint: no change.
FEATURE_SWATCH = features.swatch_mats()
FEATURE_SWATCH_GLOSS = 0.60


def feature_cells(bake_size):
    """[(x0, y0, x1, y1, zone, rgb)] in bake texels: the shell layout's swatch cells of feature paints."""
    if not FEATURE_SWATCH:
        return []
    path = os.path.join(BAKE_DIR, "shell_layout_meta.json")
    if not os.path.exists(path):
        return []
    import json
    meta = json.load(open(path, encoding="utf-8"))
    k = bake_size // int(meta.get("size", bake_size))
    out = []
    for c in meta.get("swatches", []):
        rgb = FEATURE_SWATCH.get(c.get("material"))
        if rgb is None:
            continue
        x0, y0, x1, y1 = (int(v) * k for v in c["rect"])
        out.append((x0, y0, x1, y1, c.get("zone", "body"), rgb))
    return out


def grime_amount(space, grime, cavity=None):
    """0..1 per texel: the baked dirt field, plus the gaps."""
    g = np.asarray(grime, dtype=np.float32) / 255.0
    if cavity is not None:
        cv = np.asarray(cavity, dtype=np.float32) / 255.0
        g = np.clip(g + GAP_GRIME * (1.0 - cv) ** 2, 0.0, 1.0)
    return g


def weather(img, space, amount, relative=False):
    """Push towards the space's dirt colour by amount x depth; relative=True caps the dirt's luma at
    DIRT_REL of each texel's own (the paint pass's levels, see DIRT_REL)."""
    colour, depth = GRIME[space]
    c = np.asarray(img, dtype=np.float32)
    k = (amount * depth)[..., None]
    dirt = np.array(colour, dtype=np.float32)
    if relative:
        lc = c[..., 0] * 0.299 + c[..., 1] * 0.587 + c[..., 2] * 0.114
        ld = float(dirt[0] * 0.299 + dirt[1] * 0.587 + dirt[2] * 0.114)
        dirt = dirt * np.minimum(1.0, DIRT_REL * lc / ld)[..., None]
    out = c * (1.0 - k) + dirt * k
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


# soft edge wear (polish round 1, BAY-11): bake_atlas's <space>_edge pass (~1 within a few mm of every sharp edge)
# kept where it is a thin line (whole small faces inside the bevel radius read 1 all over: a grey opening of
# EDGE_THIN sheet texels takes those out) and convex (the 4 cm cavity open, EDGE_CONVEX), lifting the colour toward
# white by this share at full strength: a worn, lighter rim on the engine's castings, covers and brackets
EDGE_WEAR = {"engine": 0.20}
EDGE_THIN = 3
EDGE_CONVEX = (0.70, 0.90)


def edge_wear(img, edge, cavity, ss, lift):
    """(image, share of texels lifted) for the edge-wear term (EDGE_WEAR)."""
    e = np.asarray(edge, dtype=np.float32) / 255.0
    n = max(2, EDGE_THIN * ss)
    thin = np.clip(e - ndimage.grey_opening(e, size=(n, n)), 0.0, 1.0)
    cv = np.asarray(cavity, dtype=np.float32) / 255.0
    w = thin * np.clip((cv - EDGE_CONVEX[0]) / (EDGE_CONVEX[1] - EDGE_CONVEX[0]), 0.0, 1.0)
    c = np.asarray(img, dtype=np.float32)
    out = c + (255.0 - c) * (lift * w)[..., None]
    return Image.fromarray(np.clip(out + 0.5, 0, 255).astype(np.uint8)), float((w > 0.25).mean())


def _optional(name, mode="L"):
    path = os.path.join(BAKE_DIR, name + ".png")
    return Image.open(path).convert(mode) if os.path.exists(path) else None


def paint_mask(color):
    """Texels whose baked colour is the kotris paint: the surfaces a skin recolours."""
    c = np.asarray(color, dtype=np.float32)
    d = np.sqrt(((c - PAINT_SRGB) ** 2).sum(axis=-1))
    return (d < PAINT_TOL).astype(np.float32)


def recolour(shell, m, target):
    s = np.asarray(shell, dtype=np.float32)
    ratio = np.array(target, dtype=np.float32) / PAINT_SRGB
    painted = np.clip(s * ratio, 0, 255)
    return Image.fromarray((s * (1 - m[..., None]) + painted * m[..., None]).astype(np.uint8))


def snap_zones(zone):
    """Bake filtering can shade zone edges; snap every texel to the nearest legal level (0 .25 .5 .75 1).
    (Uncovered texels were already filled from the nearest island by Dilate.)"""
    z = np.asarray(zone, dtype=np.float32) / 255.0
    z = np.round(z * 4.0) / 4.0
    out = np.clip(z * 255.0 + 0.5, 0, 255).astype(np.uint8)
    return Image.fromarray(out)


# ------------------------------------------------------------------------------------------------
# Lights: the picture of a LIT lamp. The mod's shader (vehicle_multiuv.frag's line) mixes it in after
# the scene light: col = mix(col, Lights.rgb, Lights.a * enabled), enabled per Mask zone (lights_*h and
# lights_*t with the headlights on, stop_* while braking). Where alpha is 1 the player sees Lights.rgb
# itself, unlit by anything, so it must look like the lit lens, not a swatch. Until 2026-10-13 it was
# the bake's flat emission colour per material, binary alpha (max channel > 20), halved to 1024; the author's
# screenshots (lights on) showed flat orange-red and amber blocks, a flat grey headlamp, jagged black
# rims where the half-size binary alpha met the paint pass's lens bezel, and the amber turn signals
# glowing with the tail lamps ("the rear lights are weird", "the lights don't look good").
# KI5 (Lights of the Touran, XJ, Trooper, W460, all 512): tail lenses lit at (123-197, 16-31, 16-31),
# x2.2-2.6 their unlit lens with its pattern kept (luma correlation 0.97-0.99 on the Touran and XJ);
# head lenses neutral, median 128-195, p90 208-239, reflector detail kept (luma std 20-52); alpha
# anti-aliased (142-219 distinct levels); amber and reverse lenses never lit.
# Now, from the paint pass's triangles (lights_lit): what glows is the material (bake_atlas.LIGHT_MATS,
# its emission colour = the lit median), the picture is the lens's own detail (the shaded shell, or
# the lens decal the material's TEXTURED stack replaces it with), dimmer at the rim, alpha ramped over
# the outline's first texels, at the shell's full size.
LIGHT_EDGE_TX = (0.0, 1.25)      # alpha 0 -> 1 between these distances (texels) inside a lens outline: one
                                 # anti-aliased texel; the paint pass's x0.65 bezel (6 mm, ~1.7 texels)
                                 # shows as a thin dark rim (0.5 / 2.0 drew a 2-3 px black ring at 326 px/m)
LIGHT_DETAIL = (0.55, 1.35)      # lens detail = texel luma / the material's median, clamped ...
# ... and softened per source: the headlamp decal is drawn for the purpose (reflector bowls, bulb);
# the shell's tail-lens pattern is the bake's tail_ribs decal, whose vertical ribs are mapped by y and
# run diagonally across the rear-facing part of the lens: at 0.8 a lit tail lamp read as a hatched grille
LIGHT_DETAIL_GAMMA = {"decal": 0.8, "shell": 0.65}   # shell 0.45 -> 0.65 (2026-10-13): the lens-frame tail map has no diagonal hatching to hide; KI5 lit/unlit luma correlation 0.97-0.99
LIGHT_CORE = (0.80, 0.025)       # a lit lens is dimmer at its rim: x0.80 at the outline, x1 from 2.5 cm in
LIGHT_COVER = (0.003, 0.015)     # metres: an outline sample whose point 3 mm out of the lens (in its plane)
                                 # finds the same lens within 1.5 cm along the normal is no outline: the
                                 # headlamp's lens sits ~5 mm in front of its lit reflector, a small lens
                                 # piece (the 3 cm insert in its outer cell) lies on the reflector, and
                                 # kotris's lenses have T-junction seams; each drew a dark ring or dots
LIGHT_COVER_MATS = ("Feux_chrome",)  # kotris's low lamps show this "chrome" in front of a lens in places
                                 # (the high stop lamp's whole face, slivers of the tail lamps); the
                                 # projection bake puts the lens's colour (and stop zone) on it, so a face
                                 # of it with a lit lens within LIGHT_COVER[1] behind lights as that lens
# Lens cells that stay dark although their material lights (2026-10-14 review, "the amber corner cell glows
# white around an unlit dot"): the headlamp's outboard lower cell is the RD1's amber turn signal (its bulb
# painted on the lens decal, tyre_paint.HEAD_CELLS["turn"] / HEAD_TURN_BULB), but it is one Phare lens
# with the main bowl, so lights_lit lit it white with the headlights round its dark insert. The game has
# no indicator zone and amber lamps never light (feedback, 2026-10-13): {materials: (|x| from, z up to)}, the
# cell's edges at the middle of the walls round it (main cell ends 0.689, turn starts 0.699; turn top
# 0.837, side lamp bottom 0.845), the alpha ramped off over one texel at the edge.
LIGHT_DARK_CELLS = {("Phare", "Phare_vitre"): (0.694, 0.841)}
LIGHT_PLANE = 0.010              # outline samples count within 1 cm of a texel's tangent plane (paint_pass)
LIGHT_STEP = 0.0015              # metres between outline samples
LIGHT_KNN = 48                   # nearest outline samples examined per texel


def _decal_luma(spec, pos, bake_dir, footprint=None):
    """Luma 0..1 of a TEXTURED ("decal", png, u, v, mode) layer at world positions (N, 3), mapped as
    bake_atlas's _TexturedOverride maps it: u and v linear in one axis each (|axis| when flagged "abs"),
    image rows from the top, edges extended; footprint (metres): box-filtered to that size first. None
    when the png is missing."""
    path = os.path.join(bake_dir, spec[1])
    if not os.path.exists(path):
        return None
    img = np.asarray(Image.open(path).convert("L"), dtype=np.float32) / 255.0
    h, w = img.shape

    def coord(ax):
        s = pos[:, "xyz".index(ax[0])]
        if len(ax) > 3 and ax[3] == "abs":
            s = np.abs(s)
        return (s - ax[1]) / (ax[2] - ax[1])
    if footprint:                               # box-prefilter to one destination texel: the headlamp's 0.7 mm
        fu = footprint / abs(spec[2][2] - spec[2][1]) * w   # flutes point-sampled at ~3.5 mm a texel
        fv = footprint / abs(spec[3][2] - spec[3][1]) * h   # came out as dotted diagonals (moire)
        img = ndimage.uniform_filter(img, size=(max(1, int(round(fv))), max(1, int(round(fu)))), mode="nearest")
    col = np.clip(coord(spec[2]) * w - 0.5, 0, w - 1)
    row = np.clip((1.0 - coord(spec[3])) * h - 0.5, 0, h - 1)
    c0, r0 = np.floor(col).astype(np.int64), np.floor(row).astype(np.int64)
    c1, r1 = np.minimum(c0 + 1, w - 1), np.minimum(r0 + 1, h - 1)
    fc, fr = col - c0, row - r0
    top = img[r0, c0] * (1 - fc) + img[r0, c1] * fc
    bot = img[r1, c0] * (1 - fc) + img[r1, c1] * fc
    return top * (1 - fr) + bot * fr


def _smooth(a, b, x):
    t = np.clip((x - a) / (b - a), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _ray_hits(q, dn, V, reach):
    """Per point q (N, 3): index of a triangle of V (M, 3, 3) that the line q + s dn, |s| <= reach,
    passes through (Moller-Trumbore, both directions), -1 for none."""
    out = np.full(len(q), -1, dtype=np.int64)
    if not len(q) or not len(V):
        return out
    V0, E1, E2 = V[:, 0], V[:, 1] - V[:, 0], V[:, 2] - V[:, 0]
    for c0 in range(0, len(q), 2000):
        d = dn[c0:c0 + 2000][:, None, :]
        h = np.cross(d, E2[None])
        det = (E1[None] * h).sum(-1)
        ok = np.abs(det) > 1e-12
        inv = 1.0 / np.where(ok, det, 1.0)
        sv = q[c0:c0 + 2000][:, None, :] - V0[None]
        u = (sv * h).sum(-1) * inv
        qv = np.cross(sv, E1[None])
        v = (d * qv).sum(-1) * inv
        s = (E2[None] * qv).sum(-1) * inv
        hit = ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (np.abs(s) <= reach)
        out[c0:c0 + 2000] = np.where(hit.any(1), hit.argmax(1), -1)
    return out


def lights_lit(pp, shell, bake_dir, log=print):
    """The Lights sheet (RGBA uint8, the shell's size) from the paint pass's triangles. Lit texels are
    the faces of bake_atlas.LIGHT_MATS materials, and LIGHT_COVER_MATS faces lying over one of them;
    one lens = one emission colour (the headlamp's lens Phare_vitre and reflector Phare are one lens,
    no outline between them). Per lit texel:
      rgb   = colour x detail x core: colour the LIGHT_MATS emission in sRGB (the lit median), detail the
              lens's own pattern (the shaded shell's luma over the material's median; a material whose
              TEXTURED stack REPLACES its colour with a decal takes the decal's luma: the projection bake
              puts the high twin's dark lens on the low headlamp, luma p50 36 against the decal's 159,
              correlation 0.38), core the dimmer rim (LIGHT_CORE);
      alpha = smoothstep over LIGHT_EDGE_TX of the 3D distance to the lens outline, in texels.
    The outline is every half-edge of a lit face with no face of the same lens across it (welded by
    position), less what the same lens covers just beyond it (LIGHT_COVER).
    Texels outside the lenses get alpha 0 and the nearest lens colour (GL_LINEAR filters RGB and alpha
    apart: a dark RGB beside the lens would draw a dark fringe at half alpha); the padding takes its
    island's values through compose's fill, so a lens cut by the layout has no seam."""
    import paint_pass
    from scipy.spatial import cKDTree
    lm = paint_pass._bake_const("LIGHT_MATS")
    textured = paint_pass._bake_const("TEXTURED")
    names = pp.mat_names
    colours, group_of = [], np.full(len(names), -1, dtype=np.int64)
    for i, n in enumerate(names):
        if n in lm:
            c = tuple(round(float(v), 4) for v in lm[n])
            if c not in colours:
                colours.append(c)
            group_of[i] = colours.index(c)
    srgb = np.array([[255.0 * _lin2srgb(v) for v in c] for c in colours], dtype=np.float32).reshape(-1, 3)
    tg = group_of[pp.tri_mat]
    tg[pp.tri_ovr >= 0] = -1                              # faces the paint pass recolours (OVERRIDES: the headlamp
    P = pp.tri_pos                                        # floors, polish round 2) are no lens
    lens_t = np.nonzero(tg >= 0)[0]                       # the LIGHT_MATS faces themselves
    # faces that show a lens from the front (LIGHT_COVER_MATS over a lit lens) light as that lens
    covers = []
    cov_t = np.nonzero(np.isin(np.array(names)[pp.tri_mat], LIGHT_COVER_MATS))[0]
    if len(cov_t) and len(lens_t):
        Pc = P[cov_t]
        cen = Pc.mean(1)
        probe = np.concatenate([cen[:, None], 0.5 * cen[:, None] + 0.5 * Pc], axis=1)        # (C, 4, 3)
        nrm = np.repeat(pp.tri_fnrm[cov_t][:, None], 4, axis=1)
        hit = _ray_hits(probe.reshape(-1, 3), nrm.reshape(-1, 3), P[lens_t], LIGHT_COVER[1]).reshape(-1, 4)
        hg = np.where(hit >= 0, tg[lens_t][np.clip(hit, 0, None)], -1)
        for i, ti in enumerate(cov_t):
            gs = hg[i][hg[i] >= 0]
            if len(gs) >= 2:
                tg[ti] = np.bincount(gs).argmax()
                covers.append(ti)
    # --- outline half-edges
    T = len(tg)
    w = pp.tri_wid.astype(np.int64)
    a_i, b_i = np.array([0, 1, 2]), np.array([1, 2, 0])
    lo = np.minimum(w[:, a_i], w[:, b_i]).ravel()
    hi = np.maximum(w[:, a_i], w[:, b_i]).ravel()
    tri = np.repeat(np.arange(T), 3)
    ca, cb = np.tile(a_i, T), np.tile(b_i, T)
    g = tg[tri]
    keep = np.nonzero((g >= 0) & (lo != hi))[0]
    key = (lo[keep] * (int(w.max()) + 1) + hi[keep]) * (len(colours) + 1) + g[keep]
    _u, inv, cnt = np.unique(key, return_inverse=True, return_counts=True)
    e = keep[cnt[inv.reshape(-1)] == 1]
    A, B = P[tri[e], ca[e]], P[tri[e], cb[e]]
    eg, en = g[e], pp.tri_fnrm[tri[e]]
    L = np.linalg.norm(B - A, axis=1)
    k = np.maximum(1, np.ceil(L / LIGHT_STEP).astype(np.int64))
    seg = np.repeat(np.arange(len(A)), k + 1)
    t = (np.arange(len(seg)) - np.repeat(np.cumsum(k + 1) - (k + 1), k + 1)) / np.repeat(k, k + 1)
    pts = A[seg] + (B - A)[seg] * t[:, None]
    # covered samples (LIGHT_COVER): step out of the lens in its plane, look along the normal for the same
    # lens's own faces (a cover face's rim over its lens's rim is no outline either way)
    inner = np.zeros(len(pts), dtype=bool)
    if len(pts):
        out_d = np.cross((B - A) / np.maximum(L, 1e-12)[:, None], en)[seg]
        own_c = P[tri[e]].mean(1)[seg]                    # the sample's own triangle: step away from it
        out_d *= np.where(((own_c - pts) * out_d).sum(1) > 0.0, -1.0, 1.0)[:, None]
        q = pts + out_d * LIGHT_COVER[0]
        for gi in range(len(colours)):
            ss = np.nonzero(eg[seg] == gi)[0]
            tt = lens_t[tg[lens_t] == gi]
            inner[ss] = _ray_hits(q[ss], en[seg][ss], P[tt], LIGHT_COVER[1]) >= 0
    src, src_g, src_n = pts[~inner], eg[seg][~inner], en[seg][~inner]
    # --- per lit texel: distance to the outline, alpha, colour
    tc = pp.tri_mat[pp.t]
    gc = tg[pp.t]
    recv = np.nonzero(gc >= 0)[0]
    d = np.full(len(recv), np.inf)
    if len(src) and len(recv):
        tree = cKDTree(src)
        for s0 in range(0, len(recv), 100_000):
            r = recv[s0:s0 + 100_000]
            p, n = pp.pos[r], pp.fnrm[r]
            dd, nb = tree.query(p, k=min(LIGHT_KNN, len(src)), distance_upper_bound=LIGHT_CORE[1])
            dd, nb = dd.reshape(len(r), -1), nb.reshape(len(r), -1)
            valid = np.isfinite(dd)
            nbc = np.where(valid, nb, 0)
            plane = np.abs(((src[nbc] - p[:, None, :]) * n[:, None, :]).sum(-1)) < LIGHT_PLANE
            facing = (src_n[nbc] * n[:, None, :]).sum(-1) > -0.2
            same = src_g[nbc] == gc[r][:, None]
            d[s0:s0 + 100_000] = np.where(valid & plane & facing & same, dd, np.inf).min(1)
    rho = np.maximum(pp.rho[recv], 1.0)
    alpha = _smooth(LIGHT_EDGE_TX[0], LIGHT_EDGE_TX[1], d * rho)
    dark_n = 0
    for mats, (x0, z1) in LIGHT_DARK_CELLS.items():      # cells of a lit lens that stay dark (amber turn signal)
        sel = np.isin(np.array(names)[tc[recv]], mats)
        p = pp.pos[recv[sel]]
        inside = np.minimum(np.abs(p[:, 0]) - x0, z1 - p[:, 2]) * rho[sel]      # texels into the cell, < 0 outside
        k = 1.0 - _smooth(-0.6, 0.6, inside)
        alpha[sel] *= k
        dark_n += int((k < 0.5).sum())
    core = LIGHT_CORE[0] + (1.0 - LIGHT_CORE[0]) * _smooth(0.0, LIGHT_CORE[1], d)
    lum = np.asarray(shell, dtype=np.float32).reshape(-1, 3)[pp.cpix[recv]] @ np.array([0.299, 0.587, 0.114], np.float32)
    det = np.ones(len(recv))
    stats = []
    pair = tc[recv] * (len(colours) + 1) + gc[recv]
    for pv in np.unique(pair):
        sel = pair == pv
        name = names[int(pv) // (len(colours) + 1)]
        src_l = lum[sel] / 255.0
        how = "shell"
        dec = [s for s in textured.get(name, []) if s[0] == "decal" and len(s) > 4 and s[4] == "replace"]
        if dec:
            dl = _decal_luma(dec[-1], pp.pos[recv[sel]], bake_dir, 1.0 / float(np.median(rho[sel])))
            if dl is not None:
                src_l, how = dl, "decal " + dec[-1][1]
        body = alpha[sel] > 0.99
        med = float(np.median(src_l[body] if body.sum() >= 8 else src_l))
        det[sel] = np.clip(src_l / max(med, 1e-3), *LIGHT_DETAIL) ** LIGHT_DETAIL_GAMMA[how.split()[0]]
        stats.append((name, int(sel.sum()), how))
    rgb = np.clip(srgb[gc[recv]] * (det * core)[:, None], 0.0, 255.0)
    N = len(pp.t)
    a_c = np.zeros(N, dtype=np.float32)
    a_c[recv] = alpha
    rgb_c = np.zeros((N, 3), dtype=np.float32)
    rgb_c[recv] = rgb
    lit_c = np.zeros(N, dtype=bool)
    lit_c[recv] = True
    A_img = pp.full(a_c, 0.0)
    rgb_img = pp.full(rgb_c, 0.0)
    lit_img = pp.full(lit_c, False)
    if lit_img.any():
        idx = ndimage.distance_transform_edt(~lit_img, return_distances=False, return_indices=True)
        rgb_img = rgb_img[idx[0], idx[1]]
    out = np.dstack([np.clip(rgb_img + 0.5, 0, 255), np.clip(A_img * 255.0 + 0.5, 0, 255)]).astype(np.uint8)
    L_out = rgb @ np.array([0.299, 0.587, 0.114])
    log("paint: lights %d lens texels (%s; %d %s faces over a lens; %d in dark cells), outline %.1f m (%.1f m covered by "
        "the same lens dropped), alpha ramped on %.0f%%, lit luma p10/p50/p90 %.0f/%.0f/%.0f; unlit: %s"
        % (len(recv), ", ".join("%s %d %s" % s for s in stats), len(covers), "/".join(LIGHT_COVER_MATS), dark_n,
           (~inner).sum() * LIGHT_STEP, inner.sum() * LIGHT_STEP,
           100.0 * (alpha < 0.99).mean() if len(alpha) else 0.0,
           *(np.percentile(L_out, [10, 50, 90]) if len(L_out) else (0, 0, 0)),
           ", ".join(sorted(m for m in set(names) if m in paint_pass.LAMP_MATS and m not in lm)) or "none"))
    return out


def lights_rgba(lights):
    """Without the paint pass's triangles: the bake's emission colour (bake_atlas.LIGHT_MATS) with the
    alpha eroded and anti-aliased over the lens rim, and the colour carried past it (see lights_lit)."""
    l = np.asarray(lights, dtype=np.float32)
    on = l.max(axis=-1) > 20.0
    a = np.clip(2.0 * ndimage.uniform_filter(on.astype(np.float32), size=3) - 1.0, 0.0, 1.0) * on
    if on.any():
        idx = ndimage.distance_transform_edt(~on, return_distances=False, return_indices=True)
        l = l[idx[0], idx[1]]
    return Image.fromarray(np.dstack([np.clip(l + 0.5, 0, 255), a * 255.0 + 0.5]).astype(np.uint8))


def rust_rgba(size):
    rgb = PT.rust().resize((size, size), Image.BILINEAR)
    rng = np.random.default_rng(7)
    small = rng.random((size // 16, size // 16)).astype(np.float32)
    noise = np.asarray(Image.fromarray((small * 255).astype(np.uint8)).resize((size, size), Image.BICUBIC)
                       .filter(ImageFilter.GaussianBlur(2.0)), dtype=np.float32) / 255.0
    fine = rng.random((size, size)).astype(np.float32)
    # sparse: KI5's rust alpha is 0 on ~45% of texels and single digits on most of the rest; the game
    # multiplies it by the vehicle's rust level, so a dense alpha paints the whole car brown at spawn
    a = np.clip((noise - 0.72) * 5.0, 0, 1) * (0.5 + 0.5 * fine) * 0.35
    return Image.fromarray(np.dstack([np.asarray(rgb, dtype=np.uint8), (a * 255).astype(np.uint8)]))


def main():
    global BAKE_DIR
    ap = argparse.ArgumentParser()
    ap.add_argument("--bake", default=BAKE_DIR)
    ap.add_argument("--out", default=PT.TEX_DIR)
    ap.add_argument("--preview", default=None)
    a = ap.parse_args()
    BAKE_DIR = a.bake
    os.makedirs(a.out, exist_ok=True)
    written = []

    sheets = sheet_sizes()
    fill = Dilate(_load("shell_cov", "L"), _load("shell_color"))
    color = fill(_load("shell_color"))
    size = color.width                                    # the bake's size: everything below runs at it ...
    ss = bake_factor("shell", size, sheets["shell"])
    sheet = size // ss                                    # ... and the shipped sheets are reduced to this
    print("reduce: shell baked at %d px, shipped at %d (%dx%d box; Mask zones by majority)" % (size, sheet, ss, ss))
    gap_img = _optional("shell_gap")
    # the 2D paint pass (paint_pass.py, spec/planar-texture-plan.md Part B) when the bake dumped the
    # layout's triangles; without the dump everything below is the 2026-10-12 compose unchanged
    pp = None
    npz = os.path.join(BAKE_DIR, "shell_uvmesh.npz")
    if os.path.exists(npz):
        import paint_pass
        pp = paint_pass.PaintPass(npz, fill, np.asarray(color), PAINT_SRGB)
    cells = pp.dark_cells() if pp is not None else []
    fcells = feature_cells(size)                          # feature paints' swatch cells (decals)
    ao = np.asarray(declutter(fill(_load("shell_ao", "L")), DECLUTTER * ss), dtype=np.uint8)
    cav = np.asarray(declutter(fill(_load("shell_cavity", "L")), DECLUTTER * ss), dtype=np.uint8)
    lamp = np.asarray(fill(_load("shell_lampmask", "L")), dtype=np.uint8) > 127
    trim = np.asarray(fill(_load("shell_trimmask", "L")), dtype=np.uint8) > 127
    for x0, y0, x1, y1, _zone in cells:                   # dark blocks hold no lamp and no trim
        lamp[y0:y1, x0:x1] = False
        trim[y0:y1, x0:x1] = False
    ao = np.where(lamp, np.maximum(ao, 235), ao)          # lenses stay bright in their recesses
    cav = np.where(lamp, 255, cav)
    ao = np.where(trim, np.maximum(ao, 200), ao)          # tailgate / door cards sit in slots the AO reads black
    cav = np.where(trim, np.maximum(cav, 235), cav)
    if pp is None:
        shell = shade(color, Image.fromarray(ao), Image.fromarray(cav), ao_k=AO_K_SPACE["shell"], gain=GAIN["shell"])
    else:
        shell = shade(color, Image.fromarray(ao), Image.fromarray(cav), ao_k=pp.ao_k(AO_K_SPACE["shell"]),
                      gain=GAIN["shell"], cavity_k=pp.cavity(CAVITY))
        # the bay walls' deeper AO and contact cavity with their median shading held (paint_pass.bay_gain)
        shell = Image.fromarray(np.clip(np.asarray(shell, dtype=np.float32) * pp.bay_gain(ao, cav)[..., None] + 0.5,
                                        0, 255).astype(np.uint8))
    seam = None
    if gap_img is not None:                               # no declutter: the lines ARE the thin features
        seam = seam_mask(fill(gap_img), lamp)
        seam = np.where(trim, 0.0, seam)              # trims (door / gate cards) keep no gap-AO seams: the
                                                       # interior's rear wall intersecting the shut gate card
                                                       # drew a dark 2 cm square and wedges on it (2026-10-13)
        if pp is not None:                                # the drawn seams carry the lines now
            seam = seam * pp.gap_scale()
        shell = darken(shell, seam)
        print("seam: %.1f%% of texels carry a seam line (gap AO < %.2f), %.1f%% a full one"
              % (100.0 * (seam > 0).mean(), GAP_HI, 100.0 * (seam >= 1.0).mean()))
    rubber_img = _optional("shell_rubber")
    rubber = np.asarray(fill(rubber_img), dtype=np.uint8) > 127 if rubber_img is not None else None
    rubber_rgb = RUBBER_RGB
    if pp is not None:
        rubber = pp.rubber()                              # glued panes, from their true outlines
        rubber_rgb = pp.rubber_rgb(RUBBER_RGB)            # ... with the seal's lip and glass-edge highlights
        m = pp.paint_mask()
        base = pp.base(shell)
    else:
        m = paint_mask(color)
    grime_img = _optional("shell_grime")
    dirt = grime_amount("shell", fill(grime_img), Image.fromarray(cav)) if grime_img is not None else None
    if dirt is not None and pp is not None:
        dirt = dirt * pp.weather_scale()                  # no gap grime on the glass
    for suffix, colour in PT.SKINS.items():
        p = os.path.join(a.out, "%s_Shell%s.png" % (PT.NAME, suffix))
        skin = Image.fromarray(pp.skin(base, colour)) if pp is not None else recolour(shell, m, colour)
        if pp is not None and suffix == "":
            pp.debug(skin, os.path.join(BAKE_DIR, "paint_debug.png"))
        if rubber is not None:
            skin = paint_rubber(skin, rubber, rubber_rgb)
        if dirt is not None:
            skin = weather(skin, "shell", dirt, relative=pp is not None)
        if pp is not None:
            skin = Image.fromarray(pp.dark_fill(skin))
        if fcells:                                        # feature paints: exact, last (whole SS blocks: exact
            sa = np.asarray(skin, dtype=np.uint8).copy()  # after the reduction too)
            for x0, y0, x1, y1, _z, rgb in fcells:
                sa[y0:y1, x0:x1, :3] = rgb
            skin = Image.fromarray(sa)
        reduce_box(skin, ss).save(p)                     # the dark cells sit on whole blocks: still exact
        written.append(p)
    if pp is not None:
        print(pp.report())
    mask = snap_zones(fill(_load("shell_zone")))
    if cells:                                             # each dark block carries its zone exactly
        zm = np.asarray(mask, dtype=np.uint8).copy()
        for x0, y0, x1, y1, zone in cells:
            zm[y0:y1, x0:x1] = np.round(np.array(paint_pass.ZONE.get(zone, paint_pass.ZONE["body"])) * 255.0).astype(np.uint8)
        mask = Image.fromarray(zm)
    if fcells:                                            # feature paint cells carry their host panel's zone
        import paint_pass as _pp
        zm = np.asarray(mask, dtype=np.uint8).copy()
        for x0, y0, x1, y1, zone, _rgb in fcells:
            zm[y0:y1, x0:x1] = np.round(np.array(_pp.ZONE.get(zone, _pp.ZONE["body"])) * 255.0).astype(np.uint8)
        mask = Image.fromarray(zm)
    # alpha = gloss for the mod's shader (stock shaders ignore it): paint 0.75, glass 1.0, lamps 0.9,
    # rubber / plastics / everything else 0.12
    zm = np.asarray(mask, dtype=np.int16)
    is_window = np.zeros(zm.shape[:2], dtype=bool)
    for zc in ((0, 128, 128), (128, 128, 0), (128, 0, 128), (0, 0, 128), (128, 0, 0), (0, 128, 0)):
        is_window |= (np.abs(zm - np.array(zc)) <= 2).all(axis=-1)
    gloss = np.full(zm.shape[:2], 0.12, dtype=np.float32)
    gloss = np.where(m > 0.5, 0.75, gloss)
    gloss = np.where(lamp, 0.90, gloss)
    gloss = np.where(is_window, 1.0, gloss)
    if rubber is not None:
        gloss = np.where(np.asarray(rubber) > 0.5, RUBBER_GLOSS, gloss)
    if dirt is not None:
        gloss = gloss * (1.0 - 0.7 * dirt)                 # dust is matte
    for x0, y0, x1, y1, _zone in cells:                   # dark blocks are matte black, whatever baked there (the
        gloss[y0:y1, x0:x1] = RUBBER_GLOSS                # Body undersides of plan A1 bake the kotris paint)
    for x0, y0, x1, y1, _zone, _rgb in fcells:            # feature paints: a painted finish
        gloss[y0:y1, x0:x1] = FEATURE_SWATCH_GLOSS
    # zones by majority (exact legal colours), the gloss averaged like the colour
    zones = reduce_zones(mask, ss)
    gloss_s = reduce_box((gloss * 255.0).astype(np.float32), ss) if ss > 1 else Image.fromarray((gloss * 255).astype(np.uint8))
    # zone mask at the shell's full size (2026-10-13): the shader samples it bilinearly and matches a
    # zone within 0.01, so at half size every zone edge lost about a texel, which cut a dark notched rim
    # into each lit lamp (tail 1.4 % of lit fragments, 0.4 % at full size) and an unlit line down the
    # high stop lamp. 16 MB of video memory at the 2048 cap; nothing at the default 512.
    # The SHIPPED Mask is RGB, no alpha (2026-10-18): whenever the game shrinks a sheet to the player's vehicle
    # texture size (default 512) it multiplies the colour by the alpha (ImageData.getMipMapData ->
    # performPreMultipliedAlpha), and with the gloss in the alpha every zone colour left the shader's 0.01
    # match: no lamp lit and damage / blood / removed-part zones failed, in the game and in Project
    # Viewpoint, for everyone below the 2048 setting. The zones + gloss copy stays a build file for the
    # polish feature (damage art, skin HSV); the shader's gloss is a constant (gen_shaders.GLOSS).
    # Both are written after the Lights below: the lamp guard (lamp_guard) reads the shipped Lights alpha.
    mask_path = os.path.join(a.out, "%s_Mask.png" % PT.NAME)
    p = os.path.join(a.out, "%s_Lights.png" % PT.NAME)
    if pp is not None:
        lights = Image.fromarray(lights_lit(pp, shell, BAKE_DIR))
    else:
        lights = lights_rgba(fill(_load("shell_lights")))
    if cells:                                             # nothing glows in a dark block
        la = np.asarray(lights, dtype=np.uint8).copy()
        for x0, y0, x1, y1, _zone in cells:
            la[y0:y1, x0:x1, 3] = 0
        lights = Image.fromarray(la)
    if fcells:                                            # nor in a feature paint cell
        la = np.asarray(lights, dtype=np.uint8).copy()
        for x0, y0, x1, y1, _zone, _rgb in fcells:
            la[y0:y1, x0:x1, 3] = 0
        lights = Image.fromarray(la)
    if fcells:
        print("compose: %d feature paint cells filled exactly (%s)" % (len(fcells), ", ".join(sorted(FEATURE_SWATCH))))
    # full size, in register with the shell: at half size (LANCZOS) the binary lens edge came out a
    # 2-texel staircase with ringing, the jagged rim of the lit tail lamp (2026-10-13). RGB and
    # alpha averaged apart (the RGB beyond a lens already carries its colour: no dark fringe)
    # 2026-10-19 performance pass: shipped at HALF the shell (1024): the sheet is ~2 % lit texels, and at
    # 2048 it cost 16 MB of video memory per car for players on the 2048 setting (the default 512 shrinks it
    # anyway). Box-averaged, so the lens edge stays a clean ramp (not the LANCZOS staircase above)
    lights_s = reduce_box(lights, ss * LIGHTS_REDUCE)
    lights_s.save(p)
    written.append(p)
    # lit lenses keep their zone at every cap, on the lens's own surface only (lens_geometry: R2-VIS-1)
    lens_geo = lens_geometry(os.path.join(BAKE_DIR, "shell_uvmesh.npz"), zones.height)
    n_groups = lens_groups(os.path.join(BAKE_DIR, "shell_layout_meta.json"))
    if not n_groups:
        print("compose: warning the shell layout has no rigid lens groups (a bake from before bug wave 3): the D-pillar "
              "lens is made all tail (wave 1), so Project Viewpoint lights it with the lights only; rebake to split it")
    zones, _guard = lamp_guard(zones, np.asarray(lights_s)[..., 3], geo=lens_geo, merge=not n_groups)
    mask = Image.merge("RGBA", (*zones.split(), gloss_s))
    mask.save(os.path.join(BAKE_DIR, "shell_mask_gloss.png"))     # the build copy keeps the plain zones
    # the shipped Mask tags the D-pillar stop part for the mod's combined stop / tail rule (gen_shaders LAMP_RULE)
    shipped, _n = mark_combined_stop(zones, lens_geo)
    shipped.convert("RGB").save(mask_path)
    written.append(mask_path)
    p = os.path.join(a.out, "%s_Rust.png" % PT.NAME)
    rust_rgba(max(256, sheet // 2)).save(p)
    written.append(p)
    plain = [("interior", "Interior"), ("wheel", "Wheel"), ("engine", "Engine")]
    plain += [(sp, spec["texture"]) for sp, spec in FEATURE_SHEETS.items()]
    for space, tex in plain:
        p = os.path.join(a.out, "%s_%s.png" % (PT.NAME, tex))
        fill = Dilate(_load(space + "_cov", "L"), _load(space + "_color"))
        col = fill(_load(space + "_color"))
        k = bake_factor(space, col.width, sheets[space])
        if DESPECKLE.get(space) and k > 1:               # the engine's projection specks (see DESPECKLE)
            col, share = despeckle(col, DESPECKLE[space])
            print("reduce: %s despeckle, %.2f%% of the bake's texels were isolated specks, set to their 3x3 median"
                  % (space, 100.0 * share))
        if DEBLOTCH.get(space) and k > 1:
            t_, m_ = DEBLOTCH[space]
            col, share = despeckle(col, t_, 2, 5, m_)
            print("reduce: %s deblotch, %.2f%% of the bake's texels were small clumps, set to their 5x5 median"
                  % (space, 100.0 * share))
        ao = fill(_load(space + "_ao", "L"))
        if space != "engine":                        # the bay's fine shadows are real and wanted
            ao = declutter(ao, DECLUTTER * k)
        cav = fill(_load(space + "_cavity", "L"))
        if space != "engine":
            cav = declutter(cav, DECLUTTER * k)
        img = shade(col, ao, cav, ao_k=AO_K_SPACE[space], gain=GAIN[space])
        g = _optional(space + "_grime")
        if g is not None:
            img = weather(img, space, grime_amount(space, fill(g), cav))
        e = _optional(space + "_edge") if space in EDGE_WEAR else None
        if e is not None:
            img, share = edge_wear(img, fill(e), cav, k, EDGE_WEAR[space])
            print("reduce: %s edge wear on %.1f%% of the bake's texels" % (space, 100.0 * share))
        reduce_box(img, k).save(p)
        print("reduce: %s baked at %d px, shipped at %d" % (space, col.width, col.width // k))
        written.append(p)
    for p in written:
        print("WROTE", os.path.basename(p))
    for feat, _r in features.call("COMPOSE", print, {"out": a.out, "bake": BAKE_DIR, "sheets": dict(sheets)}):
        print("FEATURE %s: compose done" % feat)
    if a.preview:
        side = sheet // 4
        prev = Image.new("RGB", (sheet + side, sheet), (30, 30, 30))
        prev.paste(Image.open(written[0]).convert("RGB"), (0, 0))
        prev.paste(mask.resize((side, side)), (sheet, 0))
        prev.paste(Image.open(os.path.join(a.out, "%s_Lights.png" % PT.NAME)).convert("RGB").resize((side, side)), (sheet, side))
        prev.paste(Image.open(os.path.join(a.out, "%s_Interior.png" % PT.NAME)).resize((side, side)), (sheet, 2 * side))
        prev.paste(Image.open(os.path.join(a.out, "%s_Wheel.png" % PT.NAME)).resize((side, side)), (sheet, 3 * side))
        prev.save(a.preview)
        print("PREVIEW", a.preview)
    return written


if __name__ == "__main__":
    main()
