r"""
Planar "blueprint" unwrap of the shell sheet (spec/planar-texture-plan.md, Part A).

    import planar_uv
    res = planar_uv.unwrap(tris, run_job, size=2048)      # tris: see unwrap(); run_job: run_xatlas_job

Why. The shell used to be ~3k xatlas charts filled by a 3D bake: a panel outline was spread over
dozens of charts, so nothing could be drawn crisply along it, and the padding round every chart ate
the sheet. KI5 lays every panel out as ONE flat island projected along its own mean normal (a side
view, a top view, ...), so a shut line is one straight run of texels and a 2D paint pass can draw it
(Part B, scripts/paint_pass.py). This module builds that layout:

  A1 classes  dark: underbody and seam backing, one 16x16 cell per (object, zone), every face on one
              small triangle in its middle (compose fills the cell flat);
              swatch: tube steel and small black trim of the accessories (and any fallback chart
              under 8 px of those materials), and every chart, fallback or panel island, too thin
              to bake its own texels (starved: see STARVE_SHARE), one cell per (object, material,
              zone), keeping the bake's flat colour;
              fallback: generated faces, exterior details, the spare, door cards, liners, bay walls,
              accessories: xatlas charts at FALLBACK_TPC x the face's weight;
              planar: everything else (the kotris skin, the sills and lips).
  A2 islands  an axis per face (LEFT/RIGHT/TOP/FRONT/REAR, the sides favoured by SIDE_BIAS), made
              coherent over welded neighbours and smooth patches; an island is a welded component of
              one object, axis and layer class (glass / skin), projected along its area-weighted mean
              normal clamped to DIR_CLAMP of its axis; a face that folds over a face of its own
              island claimed before it (paint first, then by area; any overlap with another
              material, a little with its own) moves to a second or third layer (their own
              islands, same projection).
  A3 packing  xatlas packs everything in ONE add_uv_mesh call: islands, fallback charts and cells in
              texel units at texels_per_unit 1, so every scale is kept (up to xatlas rounding each
              chart's extents up to whole texels), 90-degree turns only (never rotate_charts_to_axis:
              panel islands stay axis-aligned), each chart its own material so touching charts are
              never welded. The page is a resizable atlas behind an L-shaped frame (xatlas_job pack
              mode: with a fixed resolution xatlas left a fifth of the page empty); if it does not
              fit, every input shrinks by PACK_STEP, then bisects to the largest scale that fits,
              never below TPC_FLOOR (then it fails loudly).

Pure numpy, so it runs inside Blender (bake_atlas) and in any interpreter (the layout harness, the
checks). xatlas itself runs out of process (it crashes inside blender.exe on Blender's MSVCP140):
run_job(payload) -> dict is run_xatlas_job bound to an interpreter that has tools/pylib.

Every adjacency, island and edge test keys vertices by position rounded to WELD_TOL per object:
kotris leaves unwelded duplicate vertices (65.9 m of the shell's edges are "open" by vertex id but
shared by position, design review 2026-10-12).

UV conventions: texel units while building (u right, v up); the result is normalised Blender UVs
(v up); texel column = u * size, row = (1 - v) * size; rects in the meta are pixels, rows from the top.
"""
import json
import os
import struct
import subprocess
import tempfile
import zlib

import numpy as np

import features  # scripts/features (stdlib only): the plugins' exact-colour swatch materials (SWATCH_MATS)

# --- densities and the sheet (Decision 1) -----------------------------------------------------------
SIZE = 2048
# in-game screenshots put the car at ~326 px per mesh metre (playbook): 3 texels/cm is ~1:1
# there and KI5's own density (~0.75 texels/cm) after the default 512 load cap
PLANAR_TPC = 3.0
FALLBACK_TPC = 1.5                    # at weight 1; details, the spare, cards ride their own weights
TPC_FLOOR = (2.4, 1.2)                # both shrink together (one factor) to no less than these
PACK_STEP = 0.95                      # shrink per failed packing attempt
# xatlas padding, texels round every chart at 2048 (on top of its 1-texel bilinear margin). The gap
# between two charts must stay >= 8 px, 2 texels after the 512 cap's two box-halvings, so their
# colours never meet in one capped texel; padding 4 measured a minimum gap of 8 px
# (see check_layout, 2026-10-12)
PACK_PADDING = 4
GAP_MIN = 8                           # px at 2048, the layout check's threshold
CELL = 16                             # dark / swatch cell, texels at 2048 (4 after the 512 cap)
CELL_TRI = ((4, 4), (12, 4), (4, 12))  # every face of a cell lands on this triangle (middle 8x8)
SWATCH_MAX_PX = 8                     # a fallback chart of a swatch material under this (longest side) is a swatch
# Starved charts. The shell bakes with margin 0 (A6), so a chart gets only the texels whose centres
# it covers, and compose's Dilate fills the rest of its footprint from the NEAREST covered texel,
# whatever chart that is. xatlas puts every chart's corners on texel centres and rounds its extents
# up to whole texels, so a chart one texel wide runs its edges through a row of centres and owns
# almost none: the antenna's five whip charts (1 x 46-50 px at weight 0.4) owned 0-2 of 94-102
# touched texels and read as roof, window_rl and hood after compose (verifier 2026-10-12: 62 % of
# the antenna's touched texels in a foreign Mask zone, 77 of them a window the shader discards).
# With Cycles' own centre rule 50 charts of that layout had more than a quarter of their touched
# texels filled from another chart: 31 fallback (antenna, trunk BodyInner strips, liner and paint
# slivers, AccStrap) and 19 panel islands of a few texels (trim and paint slivers). A touched texel
# is safe when its own chart owns a texel within STARVE_REACH (Chebyshev): every other chart's
# touched texels are >= GAP_MIN empty texels away, so its owned ones are >= 9 px off and the own one
# (<= 6 * sqrt 2 = 8.5 px) wins the Dilate. A chart with more than STARVE_SHARE of its touched
# texels unsafe becomes a swatch (one cell per object, material, zone: the bake's flat colour,
# never a neighbour's), predicted before the pack (as_packed) and checked again after it.
STARVE_REACH = 6
STARVE_SHARE = 0.25                   # the verifier's threshold: > 25 % of touched texels filled foreign
# Cycles' bake rasteriser (RE_bake_pixels_populate) shifts every UV by -(0.5 + 0.001, 0.5 + 0.002)
# texels before scan conversion: a texel is baked when its centre + (0.001, 0.002) (v up) is inside
# a triangle. Against the margin-0 coverage bake of 675fe78's layout this rule predicted 2,198,667
# texels with 128 wrong; centre + JITTER (row-down) got 987 wrong, the mirrored offsets 11-20k.
BAKE_JITTER = (0.001, 0.002)
# starvation is predicted before the pack at these scales: the shell's pack lands at 0.94-0.96
# (2026-10-12), and a sliver 1.05 texels wide at full scale is laid 2 wide at 1.0 (5 of 23 touched
# texels baked) but 1 wide at 0.95 (none of 18): predicted at 1.0 alone it starved only after the
# pack and cost a second one (15 s). The check after the pack stays the authority.
PREDICT_SCALES = (1.0, PACK_STEP)
WELD_TOL = 1e-4                       # metres: 0.1 mm, as bake_atlas._rubber_map keys pane edges

# --- A1 classes --------------------------------------------------------------------------------------
DARK_MATS = {"Dessous", "SeamBack"}
NOT_DARK_MATS = {"Pneu", "Jante", "RimWell", "Rotor"}   # the spare's underside is a tyre, not underbody
DARK_NZ = -0.6                        # face normal z below this ...
DARK_Z = 0.55                         # ... and centre below this (metres): only seen lying on the ground
SWATCH_MATS = {"AccSteel", "Metal", "Partie_noir", "Plastique_noir"}   # ~1,600 AccSteel charts before
# feature plugins' flat paints (the decals: features.swatch_mats): swatches like the above, but one cell per
# (material, zone) shared by every object, since compose fills it with the material's exact colour
FEATURE_SWATCH_MATS = set(features.swatch_mats())
# feature materials baked like any other but a few screen pixels wide on the shell (armour bolts, mesh
# strands, weld beads; the off-road powder coat): swatches per (object, material, zone) like AccSteel
SWATCH_MATS = SWATCH_MATS | FEATURE_SWATCH_MATS | features.bake_swatch_mats()
FEATURE_CELL = "features"             # the cell key's object for those shared cells (meta swatches[].object)
FALLBACK_OBJS = {"antenna", "arch_liners", "bay_walls"}
FALLBACK_GENS = {1, 2, 3, 4, 6, 7, 8}  # prep_parts: shells, rims, closures, rotor, hub cap, details, rim face
FALLBACK_MAT_PREFIX = ("DoorCard_", "Decal", "BodyInner")
SPARE_OBJ = "trunk"
SPARE_MATS = ("Pneu", "Jante")        # on the trunk these exist only on the spare
SPARE_PLATE_MAT = "Plastique_noir"    # the carrier plate behind it (gen 0)
SPARE_PLATE_REACH = 0.25              # metres along the axle from the tyre's centre plane
GLASS_MATS = {"Vitre", "Vitre_noir"}  # layer class: glass never shares an island with skin

# --- A2 axes and islands -----------------------------------------------------------------------------
AXES = ("LEFT", "RIGHT", "TOP", "FRONT", "REAR")
AXIS_D = np.array([(-1, 0, 0), (1, 0, 0), (0, 0, 1), (0, 1, 0), (0, -1, 0)], dtype=np.float64)
# u as close as possible to these, v = d x u (u x v = d: a face looking along d keeps its winding,
# nothing is mirrored)
AXIS_U = np.array([(0, -1, 0), (0, 1, 0), (0, -1, 0), (-1, 0, 0), (1, 0, 0)], dtype=np.float64)
# KI5 keeps roof edges, gutters and fender crowns on the side view up to ~49 degrees of elevation
SIDE_BIAS = 0.10
AXIS_BIAS = np.array([SIDE_BIAS, SIDE_BIAS, 0.0, 0.0, 0.0])
MIN_SCORE = 0.45                      # no face with a best (biased) score under this is planar
COHERE_ROUNDS = 3
COHERE_SLACK = 0.20                   # a face may take its neighbours' axis this far below its best
PATCH_DIHEDRAL = 35.0                 # degrees: smooth patches split at sharper edges
PATCH_SHARE = 0.80                    # a patch with this share of its area on one axis ...
PATCH_SCORE = 0.40                    # ... pulls every face scoring at least this for it
DIR_CLAMP = 30.0                      # degrees: island projection within this of its axis
ISLAND_MIN_DOT = 0.45                 # faces with n . d below this leave the island (fallback)
LAYER_RES = 2.0                       # fold test raster: samples per texel per axis
# a face sharing more than this of its samples with faces of ITS OWN material moves up a layer;
# against another material any shared sample moves it: the bake writes whichever face it draws
# last, so a black trim face left 3 % over the paint speckled 35 texels of door_fr's skin black
# (verifier 2026-10-12; 67 texels claimed twice inside one chart, all trim over paint but 7)
LAYER_OVERLAP = 0.03
LAYER_MIN_SAMPLES = 4                 # under this, the centroid sample decides
MAX_LAYERS = 3
# fold test order: paint first, then cladding, then everything else (each by descending area). By
# area alone the side moulding and the window rubber, whose decimated triangles are bigger than the
# skin's beside them and overhang it by a few mm (0.2-2.4 cm2, 3-21 % of a skin face), pushed skin
# triangles to layer 2 and cut door_fr's paint into three islands (2026-10-12): a chart border
# inside a panel. Ranked, the proud trim moves instead.
FOLD_RANK = {"Body": 0, "Body_plastique": 1}

ISLAND_FALLBACK, ISLAND_DARK, ISLAND_SWATCH = -1, -2, -3
KIND_PLANAR, KIND_FALLBACK, KIND_DARK, KIND_SWATCH = 0, 1, 2, 3
JITTER = (1.0 / 1031.0, 1.0 / 2053.0)  # sample offset: no sample sits exactly on a shared edge


# ------------------------------------------------------------------------------------------- helpers
def weld(pos, obj, tol=WELD_TOL):
    """Welded vertex id per triangle corner: positions rounded to tol, per object. (T, 3) int64."""
    q = np.round(pos.reshape(-1, 3) / tol).astype(np.int64)
    key = np.concatenate([np.repeat(np.asarray(obj, dtype=np.int64), 3)[:, None], q], axis=1)
    _u, inv = np.unique(key, axis=0, return_inverse=True)
    return inv.reshape(-1, 3)


def edge_pairs(wid):
    """(P, 2) triangle pairs that share a welded edge; every pair of the faces round a non-manifold
    edge (a skin face, a card face and the next skin face on one edge: the two skins must still
    be neighbours when the card is not in their class)."""
    t_count = len(wid)
    e = np.concatenate([wid[:, [0, 1]], wid[:, [1, 2]], wid[:, [2, 0]]])
    e.sort(axis=1)
    t = np.tile(np.arange(t_count), 3)
    ok = e[:, 0] != e[:, 1]
    e, t = e[ok], t[ok]
    key = e[:, 0].astype(np.int64) * (int(wid.max()) + 1) + e[:, 1]
    o = np.argsort(key, kind="stable")
    k, t = key[o], t[o]
    out = []
    d = 1
    while d < len(k):
        same = k[d:] == k[:-d]
        if not same.any():
            break
        out.append(np.stack([t[:-d][same], t[d:][same]], axis=1))
        d += 1
    p = np.concatenate(out) if out else np.zeros((0, 2), dtype=np.int64)
    return p[p[:, 0] != p[:, 1]]


def components(n, pairs):
    """Connected-component label (0..k-1) of n nodes under undirected pairs (hook + pointer jumping)."""
    lab = np.arange(n)
    pairs = np.asarray(pairs, dtype=np.int64).reshape(-1, 2)
    if len(pairs):
        a, b = pairs[:, 0], pairs[:, 1]
        while True:
            la, lb = lab[a], lab[b]
            diff = la != lb
            if not diff.any():
                break
            lo = np.minimum(la[diff], lb[diff])
            hi = np.maximum(la[diff], lb[diff])
            np.minimum.at(lab, hi, lo)                 # hi is always a root here: no cycles
            while True:
                nxt = lab[lab]
                if np.array_equal(nxt, lab):
                    break
                lab = nxt
    return np.unique(lab, return_inverse=True)[1].reshape(-1)


def _groups(labels):
    """{label: index array} for an int label array (labels < 0 skipped), in label order."""
    labels = np.asarray(labels)
    idx = np.nonzero(labels >= 0)[0]
    if not len(idx):
        return []
    o = idx[np.argsort(labels[idx], kind="stable")]
    lab = labels[o]
    cut = np.nonzero(lab[1:] != lab[:-1])[0] + 1
    return list(zip(lab[np.r_[0, cut]].tolist(), np.split(o, cut)))


def tri_area2d(p):
    """Signed area of (..., 3, 2) triangles."""
    return 0.5 * ((p[..., 1, 0] - p[..., 0, 0]) * (p[..., 2, 1] - p[..., 0, 1])
                  - (p[..., 2, 0] - p[..., 0, 0]) * (p[..., 1, 1] - p[..., 0, 1]))


def raster(p, w, h, conservative=False, jitter=(0.0, 0.0)):
    """Texels of a w x h grid covered by triangle p ((3, 2) pixel coordinates; texel (x, y) spans
    [x, x+1) x [y, y+1)): centre inside (the bake's own rule), or every texel the triangle touches.
    Returns (ys, xs)."""
    lo = np.floor(p.min(axis=0)).astype(int)
    hi = np.floor(p.max(axis=0)).astype(int)
    x0, y0 = max(lo[0], 0), max(lo[1], 0)
    x1, y1 = min(hi[0], w - 1), min(hi[1], h - 1)
    if x1 < x0 or y1 < y0:
        return np.zeros(0, int), np.zeros(0, int)
    a, b, c = p
    area2 = (b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1])
    if abs(area2) < 1e-12 and not conservative:
        return np.zeros(0, int), np.zeros(0, int)
    s = 1.0 if area2 >= 0 else -1.0
    xs = np.arange(x0, x1 + 1)
    ys = np.arange(y0, y1 + 1)
    gx = xs + 0.5 + jitter[0]
    gy = ys + 0.5 + jitter[1]
    inside = np.ones((len(ys), len(xs)), dtype=bool)
    for e0, e1 in ((a, b), (b, c), (c, a)):
        ex, ey = e1[0] - e0[0], e1[1] - e0[1]
        ln = (ex * ex + ey * ey) ** 0.5
        if ln < 1e-12:
            continue
        nx, ny = -ey * s / ln, ex * s / ln          # inward normal
        d = nx * (gx[None, :] - e0[0]) + ny * (gy[:, None] - e0[1])
        if conservative:
            d = d + 0.5 * (abs(nx) + abs(ny))
        inside &= d >= 0.0
    yy, xx = np.nonzero(inside)
    return yy + y0, xx + x0


def _dilate_box(m, r):
    """Boolean dilation of m by a (2r + 1)^2 square (Chebyshev radius r). m must keep r empty texels
    along its border (np.roll wraps round)."""
    out = m.copy()
    for ax in (0, 1):
        src = out.copy()
        for d in range(1, r + 1):
            out |= np.roll(src, d, axis=ax) | np.roll(src, -d, axis=ax)
    return out


def chart_starvation(px):
    """(owned, touched, starved) texel counts of one chart, px (k, 3, 2) its triangles in texels, v up,
    at their packed sub-texel position. owned: the texels Cycles bakes (BAKE_JITTER); touched: every
    texel a triangle reaches (what bilinear sampling reads); starved: touched texels with no owned
    texel of the chart within STARVE_REACH."""
    pad = STARVE_REACH + 2
    lo = np.floor(px.reshape(-1, 2).min(axis=0)) - pad
    q = px - lo
    hi = np.floor(q.reshape(-1, 2).max(axis=0)).astype(int) + pad + 1
    w, h = int(hi[0]), int(hi[1])
    touched = np.zeros((h, w), dtype=bool)
    owned = np.zeros((h, w), dtype=bool)
    for p in q:
        ys, xs = raster(p, w, h, conservative=True)
        touched[ys, xs] = True
        ys, xs = raster(p, w, h, jitter=BAKE_JITTER)
        owned[ys, xs] = True
    starved = touched & ~_dilate_box(owned, STARVE_REACH)
    return int(owned.sum()), int(touched.sum()), int(starved.sum())


def as_packed(px):
    """A chart's texel coordinates (k, 3, 2) as xatlas's pack lays it (measured 2026-10-12 on the
    shell: every chart's box has whole-texel extents, at least 1, stretched up from its own, and its
    lower corner on a texel centre). What it owns then does not depend on where it lands, nor on a
    90-degree turn (xatlas turns by transposing, and the centre offset is the same both ways)."""
    p = px.reshape(-1, 2)
    lo = p.min(axis=0)
    ext = p.max(axis=0) - lo
    whole = np.maximum(np.ceil(ext - 1e-6), 1.0)
    k = np.where(ext > 1e-9, whole / np.maximum(ext, 1e-9), 1.0)
    return (px - lo) * k + 0.5


def predicted_starvation(px):
    """chart_starvation of a chart (k, 3, 2) in texels at full scale, as the pack will lay it, at the
    worse of PREDICT_SCALES."""
    out = None
    for s in PREDICT_SCALES:
        c = chart_starvation(as_packed(px * s))
        if out is None or c[2] * out[1] > out[2] * c[1]:
            out = c
    return out


def starved_charts(px, chart):
    """Chart labels (of `chart`, one per face of px (F, 3, 2) texels, v up, where they landed) with
    more than STARVE_SHARE of their touched texels starved, as {label: (owned, touched, starved)}."""
    out = {}
    for c, idx in _groups(chart):
        o, t, s = chart_starvation(px[idx])
        if s > STARVE_SHARE * t:
            out[int(c)] = (o, t, s)
    return out


def run_xatlas_job(payload, python, job, pylib):
    """Run scripts/xatlas_job.py with `python` on payload (dict of arrays/scalars); dict of arrays back."""
    tmp = tempfile.mkdtemp(prefix="crv_xatlas_")
    src, dst = os.path.join(tmp, "in.npz"), os.path.join(tmp, "out.npz")
    np.savez(src, **payload)
    r = subprocess.run([python, job, src, dst, pylib], capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(dst):
        raise RuntimeError("xatlas job failed (%s): %s" % (r.returncode, (r.stdout + r.stderr)[-1500:]))
    with np.load(dst) as res:
        out = {k: res[k] for k in res.files}
    for f in (src, dst):
        try:
            os.remove(f)
        except OSError:
            pass
    try:
        os.rmdir(tmp)
    except OSError:
        pass
    return out


# ------------------------------------------------------------------------------------------ A1 classes
def _spare_masks(on, mn, gen, pos, cen):
    """(spare tyre / rim faces on the trunk, the carrier plate's faces): the plate is the trunk's
    gen-0 Plastique_noir within the tyre's radius of its axle and SPARE_PLATE_REACH of its plane."""
    spare = (on == SPARE_OBJ) & np.isin(mn, SPARE_MATS)
    plate = np.zeros(len(on), dtype=bool)
    if not spare.any():
        return spare, plate
    pts = pos[spare].reshape(-1, 3)
    c = (pts.min(axis=0) + pts.max(axis=0)) / 2.0
    _w, vec = np.linalg.eigh(np.cov((pts - c).T))
    ax = vec[:, 0]                                        # least spread: the axle
    d = pts - c
    r_max = float(np.linalg.norm(d - np.outer(d @ ax, ax), axis=1).max())
    dc = cen - c
    t = dc @ ax
    r = np.linalg.norm(dc - np.outer(t, ax), axis=1)
    plate = ((on == SPARE_OBJ) & (gen == 0) & (mn == SPARE_PLATE_MAT) & (r < r_max)
             & (np.abs(t) < SPARE_PLATE_REACH))
    return spare, plate


def classify(on, mn, gen, pos, fn, cen, w=None):
    """KIND_* per triangle and, for fallback faces, the reason (for the report). w (optional): the
    faces' texel weights; an acc_* face at weight 0 (its builder's texel_w: a back, a wall, a bar's
    side) is a swatch of its object's material, not a chart of its own."""
    n = len(on)
    dark = np.isin(mn, list(DARK_MATS)) | ((fn[:, 2] < DARK_NZ) & (cen[:, 2] < DARK_Z)
                                            & ~np.isin(mn, list(NOT_DARK_MATS)))
    acc = np.char.startswith(on, "acc_")
    swatch = ~dark & acc & np.isin(mn, list(SWATCH_MATS))
    if w is not None:
        swatch |= ~dark & acc & (np.asarray(w) <= 0)
    spare, plate = _spare_masks(on, mn, gen, pos, cen)
    reason = np.full(n, "", dtype=object)
    free = ~dark & ~swatch
    rules = [(np.isin(on, list(FALLBACK_OBJS)), lambda i: "obj " + on[i]),
             (acc, lambda i: "acc_* objects"),
             (np.isin(gen, list(FALLBACK_GENS)), lambda i: "gen %d" % gen[i]),
             (spare, lambda i: "spare tyre/rim"),
             (plate, lambda i: "spare carrier plate")]
    for prefix in FALLBACK_MAT_PREFIX:
        rules.append((np.char.startswith(mn, prefix), lambda i, p=prefix: "mat " + p + ("*" if p != "BodyInner" else "")))
    for mask, why in rules:
        for i in np.nonzero(free & mask & (reason == ""))[0]:
            reason[i] = why(i)
    kind = np.full(n, KIND_PLANAR, dtype=np.int8)
    kind[reason != ""] = KIND_FALLBACK
    kind[dark] = KIND_DARK
    kind[swatch] = KIND_SWATCH
    return kind, reason


# --------------------------------------------------------------------------------------------- A2 axes
def assign_axes(cand, glass, obj, fn, area, pairs):
    """Axis index per face (-1: none). Best of the five by n . d (+ SIDE_BIAS on the sides), then
    COHERE_ROUNDS of neighbour majority, then the smooth-patch pull (A2.1-2)."""
    n = len(fn)
    score = fn @ AXIS_D.T + AXIS_BIAS
    best = score.argmax(axis=1)
    smax = score.max(axis=1)
    ax = np.where(cand & (smax >= MIN_SCORE), best, -1)
    a, b = pairs[:, 0], pairs[:, 1]
    same = cand[a] & cand[b] & (obj[a] == obj[b]) & (glass[a] == glass[b])
    a, b = a[same], b[same]
    rows = np.arange(n)
    for _round in range(COHERE_ROUNDS):
        votes = np.zeros((n, len(AXES)))
        va = ax[b] >= 0
        np.add.at(votes, (a[va], ax[b][va]), 1.0)
        vb = ax[a] >= 0
        np.add.at(votes, (b[vb], ax[a][vb]), 1.0)
        maj = votes.argmax(axis=1)
        top = votes.max(axis=1)
        own = np.where(ax >= 0, votes[rows, np.maximum(ax, 0)], 0.0)
        sm = score[rows, maj]
        take = (ax >= 0) & (top > own) & (maj != ax) & (sm >= MIN_SCORE) & (sm >= smax - COHERE_SLACK)
        ax = np.where(take, maj, ax)
    # smooth patches: welded components of candidates (same object and layer class) split at
    # dihedral >= PATCH_DIHEDRAL
    smooth = (fn[a] * fn[b]).sum(axis=1) >= np.cos(np.radians(PATCH_DIHEDRAL))
    patch = components(n, np.stack([a[smooth], b[smooth]], axis=1))
    k = patch.max() + 1
    tot = np.bincount(patch[cand], weights=area[cand], minlength=k)
    by_ax = np.zeros((k, len(AXES)))
    has = cand & (ax >= 0)
    np.add.at(by_ax, (patch[has], ax[has]), area[has])
    dom = by_ax.argmax(axis=1)
    strong = by_ax.max(axis=1) >= PATCH_SHARE * np.maximum(tot, 1e-30)
    pd = dom[patch]
    pull = cand & strong[patch] & (score[rows, pd] >= PATCH_SCORE) & (ax != pd)
    ax = np.where(pull, pd, ax)
    return ax, score


def _island_frame(fn, area, axis):
    """Projection direction (area-weighted mean normal clamped to DIR_CLAMP of the axis), u, v."""
    a = AXIS_D[axis]
    m = (fn * area[:, None]).sum(axis=0)
    ln = np.linalg.norm(m)
    d = m / ln if ln > 1e-12 else a.copy()
    cmax = np.cos(np.radians(DIR_CLAMP))
    if d @ a < cmax:
        perp = d - (d @ a) * a
        pl = np.linalg.norm(perp)
        d = a.copy() if pl < 1e-12 else a * cmax + perp / pl * np.sin(np.radians(DIR_CLAMP))
    u0 = AXIS_U[axis]
    u = u0 - (u0 @ d) * d
    u /= np.linalg.norm(u)
    v = np.cross(d, u)
    return d, u, v


def fold_layers(uv, rank, mat):
    """Layer (0..MAX_LAYERS-1, -1: none left) per face of one island, uv (n, 3, 2) in texels: faces
    claim LAYER_RES x LAYER_RES samples per texel, by FOLD_RANK of their material, then descending
    projected area; a face tries the next layer (A2.4) when any of its samples is owned by a face of
    another material, or more than LAYER_OVERLAP of them by its own material (under
    LAYER_MIN_SAMPLES: when its centroid sample is owned). Panel triangles stay put, proud parts and
    fold-unders move. mat: material id per face."""
    n = len(uv)
    q = uv * LAYER_RES
    lo = q.reshape(-1, 2).min(axis=0) - 1.0
    hi = q.reshape(-1, 2).max(axis=0) + 1.0
    w, h = int(np.ceil(hi[0] - lo[0])) + 1, int(np.ceil(hi[1] - lo[1])) + 1
    bufs = [np.full((h, w), -1, dtype=np.int64) for _ in range(MAX_LAYERS)]   # owner's material, -1 free
    order = np.lexsort((-np.abs(tri_area2d(q)), rank))
    layer = np.full(n, -1, dtype=np.int64)
    for i in order:
        p = q[i] - lo
        ys, xs = raster(p, w, h, jitter=JITTER)
        cx, cy = np.clip(np.floor(p.mean(axis=0)).astype(int), 0, [w - 1, h - 1])
        m = mat[i]
        for k in range(MAX_LAYERS):
            buf = bufs[k]
            if len(ys) >= LAYER_MIN_SAMPLES:
                cur = buf[ys, xs]
                hit = bool(((cur >= 0) & (cur != m)).any()) or (cur == m).mean() > LAYER_OVERLAP
            else:
                hit = buf[cy, cx] >= 0
            if hit:
                continue
            layer[i] = k
            free = buf[ys, xs] < 0
            buf[ys[free], xs[free]] = m
            if len(ys) < LAYER_MIN_SAMPLES and buf[cy, cx] < 0:
                buf[cy, cx] = m
            break
    return layer


def build_islands(ax, glass, obj, fn, area, pos, pairs, tpc_px, rank, mat):
    """Islands (A2.3-4): list of dicts (faces, axis, dir, u, v, layer 1..3, object, glass), and the
    faces that leave for fallback with their reason. rank: FOLD_RANK per face; mat: material id."""
    n = len(ax)
    a, b = pairs[:, 0], pairs[:, 1]
    tie = (ax[a] >= 0) & (ax[a] == ax[b]) & (obj[a] == obj[b]) & (glass[a] == glass[b])
    lab = np.where(ax >= 0, components(n, np.stack([a[tie], b[tie]], axis=1)), -1)
    pa, pb = a[tie], b[tie]                      # pairs inside one first-cut island, grouped by it
    o = np.argsort(lab[pa], kind="stable")
    pa, pb = pa[o], pb[o]
    plab = lab[pa]
    islands, leave, why = [], [], []
    loc = np.full(n, -1, dtype=np.int64)

    def sub_components(faces, lo_hi):
        """Components of a face subset under the island's own pairs."""
        loc[faces] = np.arange(len(faces))
        sa, sb = loc[pa[lo_hi[0]:lo_hi[1]]], loc[pb[lo_hi[0]:lo_hi[1]]]
        ok = (sa >= 0) & (sb >= 0)
        c = components(len(faces), np.stack([sa[ok], sb[ok]], axis=1))
        loc[faces] = -1
        return c

    bounds = {}
    if len(plab):
        cut = np.nonzero(plab[1:] != plab[:-1])[0] + 1
        starts = np.r_[0, cut]
        ends = np.r_[cut, len(plab)]
        for s, e in zip(starts, ends):
            bounds[int(plab[s])] = (s, e)
    for label, faces in _groups(lab):
        axis = int(ax[faces[0]])
        d, u, v = _island_frame(fn[faces], area[faces], axis)
        tilt = fn[faces] @ d < ISLAND_MIN_DOT
        if tilt.any():
            leave.extend(faces[tilt].tolist())
            why.extend(["tilt (n.d < %.2f)" % ISLAND_MIN_DOT] * int(tilt.sum()))
            faces = faces[~tilt]
            if not len(faces):
                continue
        lh = bounds.get(label, (0, 0))
        for _c, sub in _groups(sub_components(faces, lh)):
            part = faces[sub]
            P = pos[part]
            uv = np.stack([P @ u, P @ v], axis=-1) * tpc_px
            layer = fold_layers(uv, rank[part], mat[part])
            if (layer < 0).any():
                leave.extend(part[layer < 0].tolist())
                why.extend(["fold (layer > %d)" % MAX_LAYERS] * int((layer < 0).sum()))
            for k in range(MAX_LAYERS):
                lay = part[layer == k]
                if not len(lay):
                    continue
                for _c2, sub2 in _groups(sub_components(lay, lh)):
                    piece = lay[sub2]
                    islands.append({"faces": piece, "axis": axis, "dir": d, "u": u, "v": v, "layer": k + 1,
                                    "object": int(obj[piece[0]]), "glass": bool(glass[piece[0]])})
    return islands, np.array(leave, dtype=np.int64), why


# ---------------------------------------------------------------------------------------- A3 packing
def match_corners(ind, vmap, oind):
    """Output vertex per input face corner (F, 3): xatlas keeps the face order but may rotate a
    face's corners; vmap maps an output vertex to its input vertex. Second value: unmatched corners."""
    src = vmap[oind]
    rows = np.arange(len(oind))
    out = np.zeros(ind.shape, dtype=np.int64)
    bad = 0
    for c in range(3):
        hit = src == ind[:, c:c + 1]
        ok = hit.any(axis=1)
        bad += int((~ok).sum())
        out[:, c] = oind[rows, np.where(ok, hit.argmax(axis=1), c)]
    return out, bad


def chart_fallback(faces, obj, w, wid, wpos, run_job, tpc_px):
    """xatlas charts of the fallback faces (A3.1): mesh groups by (object, quantised weight), positions
    x weight, resolution 0 at tpc_px texels per metre (charting and parametrisation only). Returns
    the chart vertices' texel UVs (V, 2), each face's corners as indices into them (n, 3), a chart
    label per face (charts never share a vertex) and the job's numbers."""
    payload = {"mode": "chart", "tpu": float(tpc_px)}
    groups = []
    key = obj[faces].astype(np.int64) * 1000 + np.round(w[faces] * 64).astype(np.int64)
    for _k, sel in _groups(np.unique(key, return_inverse=True)[1].reshape(-1)):
        fs = faces[sel]
        vids, ind = np.unique(wid[fs], return_inverse=True)
        payload["pos%d" % len(groups)] = (wpos[vids] * float(w[fs[0]])).astype(np.float32)
        payload["ind%d" % len(groups)] = ind.reshape(-1, 3).astype(np.uint32)
        groups.append((sel, ind.reshape(-1, 3)))
    payload["n"] = len(groups)
    if not groups:
        return np.zeros((0, 2)), np.zeros((0, 3), dtype=np.int64), np.zeros(0, dtype=np.int64), {}
    res = run_job(payload)
    verts = []
    corner = np.zeros((len(faces), 3), dtype=np.int64)
    chart = np.zeros(len(faces), dtype=np.int64)
    nv = 0
    base = 0
    bad = 0
    for k, (sel, ind) in enumerate(groups):
        vmap, oind, ouv = res["vmap%d" % k], res["ind%d" % k].astype(np.int64), res["uv%d" % k].astype(np.float64)
        if len(oind) != len(ind):
            raise RuntimeError("xatlas chart job returned %d faces for %d" % (len(oind), len(ind)))
        ov, b = match_corners(ind, vmap, oind)
        bad += b
        lab = components(len(ouv), np.concatenate([oind[:, [0, 1]], oind[:, [1, 2]]]))
        corner[sel] = ov + nv
        chart[sel] = lab[ov[:, 0]] + base
        verts.append(ouv)
        nv += len(ouv)
        base += int(lab.max()) + 1 if len(lab) else 0
    info = {"xatlas_charts": int(res.get("charts", base)), "groups": len(groups), "unmatched_corners": bad}
    return np.concatenate(verts), corner, chart, info


def _cells(kind, on, mn, zn):
    """Cells: dark per (object, zone), swatch per (object, material, zone); list of dicts (kind, key,
    faces)."""
    cells = []
    def swatch_key(i):
        if mn[i] in FEATURE_SWATCH_MATS:                       # feature paints: one cell per (material, zone)
            return (FEATURE_CELL, mn[i], zn[i])
        return (on[i], mn[i], zn[i])
    for kd, keyf in ((KIND_DARK, lambda i: (on[i], zn[i])), (KIND_SWATCH, swatch_key)):
        index = {}
        for i in np.nonzero(kind == kd)[0]:
            k = keyf(i)
            if k not in index:
                index[k] = len(cells)
                cells.append({"kind": kd, "key": k, "faces": []})
            cells[index[k]]["faces"].append(i)
    return cells


def _pack(islands, wid, wpos, tpc0, fb, fverts, fcorner, fchart, cells, n, size, planar_tpc, fallback_tpc, run_job):
    """One add_uv_mesh of the islands, the fallback charts and the cells (A3.4), vertex indices unique
    per chart. Returns uv (n, 3, 2) normalised (cells' faces on CELL_TRI, each cell's rect set),
    the chart id per face, the chart count, the scale the pack reached and xatlas's utilization."""
    uvs, inds, fixed = [], [], []
    face_slot = np.full(n, -1, dtype=np.int64)      # row of the face in the packed index array
    rows = 0
    nv = 0
    chart_id = np.full(n, -1, dtype=np.int64)
    nchart = 0
    for isl in islands:
        f = isl["faces"]
        vids, ind = np.unique(wid[f], return_inverse=True)
        p = wpos[vids]
        uv = np.stack([p @ isl["u"], p @ isl["v"]], axis=-1) * tpc0
        isl["uv_in"] = uv[ind.reshape(-1, 3)]
        uvs.append(uv)
        inds.append(ind.reshape(-1, 3) + nv)
        fixed.append(np.zeros(len(uv), dtype=bool))
        face_slot[f] = rows + np.arange(len(f))
        chart_id[f] = nchart
        rows += len(f)
        nv += len(uv)
        nchart += 1
    if len(fb):
        used, inv = np.unique(fcorner, return_inverse=True)        # the kept charts' own vertices
        uvs.append(fverts[used])
        inds.append(inv.reshape(-1, 3) + nv)
        fixed.append(np.zeros(len(used), dtype=bool))
        face_slot[fb] = rows + np.arange(len(fb))
        chart_id[fb] = nchart + np.unique(fchart, return_inverse=True)[1].reshape(-1)
        rows += len(fb)
        nv += len(used)
        nchart += len(np.unique(fchart))
    cell_rows = rows
    quad = np.array([(0, 0), (CELL, 0), (CELL, CELL), (0, CELL)], dtype=np.float64)
    for c in cells:
        uvs.append(quad.copy())
        inds.append(np.array([(0, 1, 2), (0, 2, 3)]) + nv)
        fixed.append(np.ones(4, dtype=bool))
        chart_id[c["faces"]] = nchart
        rows += 2
        nv += 4
        nchart += 1
    U = np.concatenate(uvs).astype(np.float64)
    I = np.concatenate(inds).astype(np.int64)
    FX = np.concatenate(fixed)
    # chart id per packed face: xatlas welds charts that merely touch by position (xatlas_job)
    M = np.zeros(len(I), dtype=np.int64)
    has_slot = face_slot >= 0
    M[face_slot[has_slot]] = chart_id[has_slot]
    for j, c in enumerate(cells):
        M[cell_rows + 2 * j:cell_rows + 2 * j + 2] = chart_id[c["faces"][0]]
    floor = max(TPC_FLOOR[0] / planar_tpc, TPC_FLOOR[1] / fallback_tpc)
    res = run_job({"mode": "pack", "uv": U.astype(np.float32), "ind": I.astype(np.uint32), "mat": M.astype(np.uint32),
                   "fixed": FX, "size": size, "padding": PACK_PADDING, "step": PACK_STEP, "min_scale": floor})
    pages, scale = int(res["pages"]), float(res["scale"])
    if pages != 1:
        raise RuntimeError("planar shell does not fit one %d page even at %.2f / %.2f texels/cm (%d pages)"
                           % (size, planar_tpc * scale, fallback_tpc * scale, pages))
    vmap, oind, ouv = res["vmap"], res["ind"].astype(np.int64), res["uv"].astype(np.float64)
    width, height = int(res["width"]), int(res["height"])
    if len(oind) != len(I):
        raise RuntimeError("xatlas returned %d packed faces for %d" % (len(oind), len(I)))
    ov, bad = match_corners(I, vmap, oind)
    if bad:
        raise RuntimeError("xatlas changed %d packed corners" % bad)
    puv = ouv[ov]                                          # (F, 3, 2) normalised, per input corner
    if width != size or height != size:                    # xatlas normalises by its own page size
        puv = puv * np.array([width / size, height / size])
    uv = np.zeros((n, 3, 2))
    uv[has_slot] = puv[face_slot[has_slot]]
    tri = np.array(CELL_TRI, dtype=np.float64)
    for j, c in enumerate(cells):
        q = puv[cell_rows + 2 * j:cell_rows + 2 * j + 2].reshape(-1, 2) * size     # texels, v up
        # xatlas puts a chart's corner on a texel centre (x.5): the cell is the 16 x 16 whole texels
        # from the one below-left of it, inside the footprint xatlas reserved round the quad
        x0, y0 = np.round(q.min(axis=0) - 0.5)
        c["rect"] = [int(x0), int(size - y0 - CELL), CELL, CELL]                    # x, row from top, w, h
        uv[c["faces"]] = ((np.array([x0, y0]) + tri) / size)[None]
    return uv, chart_id, nchart, scale, float(res.get("util", 0.0))


def unwrap(tris, run_job, size=SIZE, planar_tpc=PLANAR_TPC, fallback_tpc=FALLBACK_TPC, log=print):
    """The shell layout. tris (all triangles of the shell parts, triangulated):
        pos (T, 3, 3) world metres, obj (T,) + obj_names, mat (T,) + mat_names, gen (T,),
        zone (T,) + zone_names (bake_atlas.zone_of per face), w (T,) fallback texel weight.
    Returns a dict: uv (T, 3, 2) normalised (v up), island (T,) int (id, or ISLAND_*), kind (T,),
    chart (T,) packing chart id, meta (for uvmesh_dump), line (the build.py report line), lines
    (where the area goes), stats, plus what layout_image / check_layout need."""
    pos = np.asarray(tris["pos"], dtype=np.float64)
    obj = np.asarray(tris["obj"], dtype=np.int64)
    gen = np.asarray(tris["gen"], dtype=np.int64)
    w = np.asarray(tris["w"], dtype=np.float64)
    on = np.array(tris["obj_names"])[obj]
    mn = np.array(tris["mat_names"])[np.asarray(tris["mat"])]
    zn = np.array(tris["zone_names"])[np.asarray(tris["zone"])]
    n = len(pos)
    cr = np.cross(pos[:, 1] - pos[:, 0], pos[:, 2] - pos[:, 0])
    ln = np.linalg.norm(cr, axis=1)
    area = ln / 2.0
    fn = cr / np.maximum(ln, 1e-30)[:, None]
    cen = pos.mean(axis=1)
    glass = np.isin(mn, list(GLASS_MATS))
    wid = weld(pos, obj)
    wpos = np.zeros((int(wid.max()) + 1, 3))
    wpos[wid.reshape(-1)] = pos.reshape(-1, 3)
    pairs = edge_pairs(wid)

    kind, reason = classify(on, mn, gen, pos, fn, cen, w)
    cand = kind == KIND_PLANAR
    ax, _score = assign_axes(cand, glass, obj, fn, area, pairs)
    for i in np.nonzero(cand & (ax < 0))[0]:
        reason[i] = "no axis (best < %.2f)" % MIN_SCORE
    kind[cand & (ax < 0)] = KIND_FALLBACK

    tpc0 = planar_tpc * 100.0
    rank = np.array([FOLD_RANK.get(m, len(FOLD_RANK)) for m in mn.tolist()], dtype=np.int64)
    islands, leave, why = build_islands(np.where(kind == KIND_PLANAR, ax, -1), glass, obj, fn, area, pos, pairs, tpc0, rank,
                                        np.asarray(tris["mat"], dtype=np.int64))
    for i, r in zip(leave.tolist(), why):
        kind[i] = KIND_FALLBACK
        reason[i] = r
    starved = []                                    # (object, material, owned, touched, starved, chart kind, when)

    def to_swatch(faces, counts, what, when):
        kind[faces] = KIND_SWATCH
        reason[faces] = ""
        starved.append((str(on[faces[0]]), str(mn[faces[0]])) + tuple(counts) + (what, when))

    # starved panel islands (slivers, a few texels of trim) become swatches like fallback charts:
    # a flat colour of their own beats the neighbour's colour and zone Dilate would give them
    kept = []
    for isl in islands:
        p = wpos[wid[isl["faces"]]]
        counts = predicted_starvation(np.stack([p @ isl["u"], p @ isl["v"]], axis=-1) * tpc0)
        if counts[2] > STARVE_SHARE * counts[1]:
            to_swatch(isl["faces"], counts, "planar", "predicted")
        else:
            kept.append(isl)
    islands = kept

    # fallback charts; the tiny ones of swatch materials and the starved ones become swatches (A1),
    # starvation predicted where xatlas will put the chart (predicted_starvation)
    fb = np.nonzero(kind == KIND_FALLBACK)[0]
    fverts, fcorner, fchart, finfo = chart_fallback(fb, obj, w, wid, wpos, run_job, fallback_tpc * 100.0)
    n_tiny = 0
    if len(fb):
        fuv = fverts[fcorner]
        lo = np.full((fchart.max() + 1, 2), np.inf)
        hi = np.full((fchart.max() + 1, 2), -np.inf)
        np.minimum.at(lo, fchart, fuv.min(axis=1))
        np.maximum.at(hi, fchart, fuv.max(axis=1))
        longest = (hi - lo).max(axis=1)
        allsw = np.ones(len(lo), dtype=bool)
        np.logical_and.at(allsw, fchart, np.isin(mn[fb], list(SWATCH_MATS)))
        tiny = (longest < SWATCH_MAX_PX) & allsw
        starve = np.zeros(len(lo), dtype=bool)
        for c, idx in _groups(fchart):
            if tiny[c]:
                continue
            counts = predicted_starvation(fuv[idx])
            if counts[2] > STARVE_SHARE * counts[1]:
                starve[c] = True
                to_swatch(fb[idx], counts, "fallback", "predicted")
        to_sw = (tiny | starve)[fchart]
        kind[fb[to_sw]] = KIND_SWATCH
        reason[fb[to_sw]] = ""
        keep = ~to_sw
        fb, fcorner, fchart = fb[keep], fcorner[keep], fchart[keep]
        n_tiny = int(tiny.sum())

    # ---- one packing (A3.4); a chart that starves at the scale the pack reached anyway (the
    # prediction guessed the scale) goes to a swatch too, and the sheet is packed once more
    for attempt in (0, 1):
        island = np.full(n, ISLAND_FALLBACK, dtype=np.int64)
        for k, isl in enumerate(islands):
            island[isl["faces"]] = k
        island[kind == KIND_DARK] = ISLAND_DARK
        island[kind == KIND_SWATCH] = ISLAND_SWATCH
        cells = _cells(kind, on, mn, zn)
        uv, chart_id, nchart, scale, util = _pack(islands, wid, wpos, tpc0, fb, fverts, fcorner, fchart, cells, n, size,
                                                  planar_tpc, fallback_tpc, run_job)
        if attempt:
            break
        late = starved_charts(uv[fb] * size, fchart) if len(fb) else {}
        kept = []
        for isl in islands:
            counts = chart_starvation(uv[isl["faces"]] * size)
            if counts[2] > STARVE_SHARE * counts[1]:
                to_swatch(isl["faces"], counts, "planar", "after the pack")
            else:
                kept.append(isl)
        if not late and len(kept) == len(islands):
            break
        islands = kept
        for c, counts in late.items():
            to_swatch(fb[fchart == c], counts, "fallback", "after the pack")
        to_sw = np.isin(fchart, list(late))
        fb, fcorner, fchart = fb[~to_sw], fcorner[~to_sw], fchart[~to_sw]

    meta = {"islands": [], "dark_blocks": [], "swatches": [], "planar_tpc": round(planar_tpc * scale, 4),
            "fallback_tpc": round(fallback_tpc * scale, 4), "size": size}
    for k, isl in enumerate(islands):
        meta["islands"].append({"id": k, "axis": AXES[isl["axis"]], "dir": [round(float(x), 5) for x in isl["dir"]],
                                "layer": isl["layer"], "object": str(tris["obj_names"][isl["object"]]),
                                "glass": isl["glass"]})
    tri = np.array(CELL_TRI, dtype=np.float64)
    for c in cells:
        # the plan's A4 meta format is [x0, y0, x1, y1] (end exclusive, rows from the top), which
        # paint_pass._rect insists on; c["rect"] stays [x, y, w, h] for this module's own drawing
        cx, cy, cw, ch = c["rect"]                     # (w is the face-weight array below)
        rect = [int(cx), int(cy), int(cx + cw), int(cy + ch)]
        if c["kind"] == KIND_DARK:
            meta["dark_blocks"].append({"object": c["key"][0], "zone": c["key"][1], "rect": rect})
        else:
            meta["swatches"].append({"object": c["key"][0], "material": c["key"][1], "zone": c["key"][2], "rect": rect})

    # ---- measurements
    px_area = np.abs(tri_area2d(uv * size))
    plan = kind == KIND_PLANAR
    proj = np.zeros(n)
    for isl in islands:
        proj[isl["faces"]] = np.abs(tri_area2d(isl["uv_in"])) / tpc0 ** 2            # m2 projected
    P = (px_area[plan].sum() / max(proj[plan].sum(), 1e-30)) ** 0.5 / 100.0
    fbm = kind == KIND_FALLBACK
    Q = (px_area[fbm].sum() / max((area[fbm] * w[fbm] ** 2).sum(), 1e-30)) ** 0.5 / 100.0
    cell_px = len(cells) * abs(tri_area2d(tri))
    F = 100.0 * (px_area[plan | fbm].sum() + cell_px) / size ** 2
    layered = plan & (island >= 0)
    lay = np.zeros(n, dtype=np.int64)
    for isl in islands:
        lay[isl["faces"]] = isl["layer"]
    n_fb_charts = len(np.unique(fchart)) if len(fb) else 0
    n_dark = sum(1 for c in cells if c["kind"] == KIND_DARK)
    line = ("bake: shell planar %d islands (%d faces, %.2f m2, %d in layers 2-3), %d fallback charts, %d swatch/dark cells, "
            "faces %.0f%% of sheet, planar %.2f texels/cm, fallback %.2f texels/cm at weight 1"
            % (len(islands), int(plan.sum()), area[plan].sum(), int((layered & (lay > 1)).sum()), n_fb_charts, len(cells),
               F, P, Q))
    lines = []
    for k, name in enumerate(AXES):
        for g in (False, True):
            sel = [isl for isl in islands if isl["axis"] == k and isl["glass"] == g]
            if not sel:
                continue
            f = np.concatenate([isl["faces"] for isl in sel])
            up = np.concatenate([isl["faces"] for isl in sel if isl["layer"] > 1] or [np.zeros(0, dtype=np.int64)])
            lines.append("bake: shell planar %-5s %-5s %4d islands %5d faces %6.2f m2 %5.0f kpx; layers 2-3: %4d faces %.3f m2"
                         % (name, "glass" if g else "skin", len(sel), len(f), area[f].sum(), px_area[f].sum() / 1e3,
                            len(up), area[up].sum()))
    for r in sorted(set(reason[fbm].tolist())):
        sel = fbm & (reason == r)
        lines.append("bake: shell fallback %-24s %5d faces %6.2f m2 %5.0f kpx" % (r, int(sel.sum()), area[sel].sum(),
                                                                                 px_area[sel].sum() / 1e3))
    n_st_fb = sum(1 for s in starved if s[5] == "fallback")
    lines.append("bake: shell cells: %d dark (%d faces, %.2f m2), %d swatch (%d faces, %.2f m2; from %d tiny fallback charts, "
                 "%d starved fallback charts, %d starved planar islands)"
                 % (n_dark, int((kind == KIND_DARK).sum()), area[kind == KIND_DARK].sum(), len(cells) - n_dark,
                    int((kind == KIND_SWATCH).sum()), area[kind == KIND_SWATCH].sum(), n_tiny, n_st_fb, len(starved) - n_st_fb))
    if starved:
        by = {}
        for o, m, *_rest in starved:
            by[(o, m)] = by.get((o, m), 0) + 1
        lines.append("bake: shell starved charts -> swatches (%d predicted, %d after the pack): %s"
                     % (sum(1 for s in starved if s[6] == "predicted"), sum(1 for s in starved if s[6] != "predicted"),
                        ", ".join("%s/%s %d" % (o, m, k) for (o, m), k in sorted(by.items()))))
    lines.append("bake: shell packing: %d charts, scale %.3f, xatlas utilization %.0f%%, fallback charting %s"
                 % (nchart, scale, 100.0 * util, finfo))
    stats = {"P": P, "Q": Q, "F": F, "scale": scale, "islands": len(islands), "fallback_charts": n_fb_charts,
             "cells": len(cells), "starved": starved}
    return {"uv": uv, "island": island, "kind": kind, "chart": chart_id, "cells": cells, "islands": islands,
            "axis": np.where(island >= 0, ax, -1), "layer": lay, "meta": meta, "line": line, "lines": lines,
            "stats": stats, "size": size, "reason": reason, "area": area}


# ----------------------------------------------------------------------------------- preview + checks
AXIS_RGB = np.array([(232, 128, 60), (70, 150, 232), (90, 196, 90), (222, 200, 60), (60, 200, 200)], dtype=np.float64)
FALLBACK_RGB = (150, 150, 150)
BACKGROUND_RGB = (44, 46, 58)


def layout_image(res):
    """shell_layout.png (A4): islands tinted by axis (layer 2 / 3 darker, glass paler), fallback
    grey, dark cells black, swatch cells white. (H, W, 3) uint8, row 0 = top."""
    size = res["size"]
    img = np.empty((size, size, 3), dtype=np.uint8)
    img[:] = BACKGROUND_RGB
    px = res["uv"].copy() * size
    px[..., 1] = size - px[..., 1]
    for c in res["cells"]:
        x, y, w, h = c["rect"]
        img[int(round(y)):int(round(y + h)), int(round(x)):int(round(x + w))] = 0 if c["kind"] == KIND_DARK else 255
    for k, isl in enumerate(res["islands"]):
        col = AXIS_RGB[isl["axis"]] * (1.0, 0.62, 0.40)[isl["layer"] - 1]
        if isl["glass"]:
            col = col * 0.55 + 255 * 0.45
        for i in isl["faces"]:
            ys, xs = raster(px[i], size, size)
            img[ys, xs] = col.astype(np.uint8)
    for i in np.nonzero(res["kind"] == KIND_FALLBACK)[0]:
        ys, xs = raster(px[i], size, size)
        img[ys, xs] = FALLBACK_RGB
    return img


def write_png(path, rgb):
    """Minimal RGB PNG writer (stdlib zlib): row 0 = top."""
    rgb = np.ascontiguousarray(rgb, dtype=np.uint8)
    h, w = rgb.shape[:2]
    raw = np.concatenate([np.zeros((h, 1), dtype=np.uint8), rgb.reshape(h, w * 3)], axis=1).tobytes()

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def check_layout(res, gap_min=GAP_MIN):
    """The layout's own acceptance numbers (step 1 of the brief), all at the sheet's size:
    texels claimed by two charts (centre rule, every non-dark / non-swatch face), texels claimed
    twice inside one chart (fold residue), UVs outside [0, 1], the smallest gap between two charts'
    touched texels (cells as their whole 16x16 rect) and how many chart pairs come closer than
    gap_min, and panel islands that are not axis-aligned (rotation by a multiple of 90 degrees, or a
    transpose, of their projected layout)."""
    size = res["size"]
    uv = res["uv"]
    px = uv * size
    px[..., 1] = size - px[..., 1]
    kind, chart = res["kind"], res["chart"]
    out = {"uv_out_of_range": int(((uv < -1e-6) | (uv > 1 + 1e-6)).any(axis=(1, 2)).sum())}
    own = np.full((size, size), -1, dtype=np.int64)
    cross = 0
    inner = 0
    faces = np.nonzero((kind == KIND_PLANAR) | (kind == KIND_FALLBACK))[0]
    for i in faces:
        # jittered samples: xatlas puts chart corners on texel centres, so a 45-degree edge shared
        # by two triangles of one chart runs through a row of centres both would claim
        ys, xs = raster(px[i], size, size, jitter=JITTER)
        if not len(ys):
            continue
        cur = own[ys, xs]
        cross += int(((cur >= 0) & (cur != chart[i])).sum())
        inner += int((cur == chart[i]).sum())
        own[ys, xs] = np.where(cur >= 0, cur, chart[i])
    out["overlap_between_charts_px"] = cross
    out["overlap_inside_charts_px"] = inner
    # touched texels per chart, cells whole
    lab = np.full((size, size), -1, dtype=np.int64)
    clash = 0
    for i in faces:
        ys, xs = raster(px[i], size, size, conservative=True)
        cur = lab[ys, xs]
        clash += int(((cur >= 0) & (cur != chart[i])).sum())
        lab[ys, xs] = np.where(cur >= 0, cur, chart[i])
    for c in res["cells"]:
        x, y, w, h = c["rect"]
        cid = chart[c["faces"][0]]
        sl = (slice(int(np.floor(y)), int(np.ceil(y + h))), slice(int(np.floor(x)), int(np.ceil(x + w))))
        cur = lab[sl]
        clash += int(((cur >= 0) & (cur != cid)).sum())
        lab[sl] = np.where(cur >= 0, cur, cid)
    out["touched_clash_px"] = clash
    # gap: empty texels between two charts' touched texels (centre distance - 1), searched out to
    # gap_min + 4; chart pairs closer than gap_min counted
    r = gap_min + 5
    best = np.inf
    pairs = set()
    for dy in range(0, r):
        for dx in range(-r + 1, r):
            if dy == 0 and dx <= 0:
                continue
            dist = (dx * dx + dy * dy) ** 0.5
            if dist >= r:
                continue
            a = lab[0:size - dy, max(0, -dx):size - max(0, dx)]
            b = lab[dy:size, max(0, dx):size - max(0, -dx)]
            m = (a >= 0) & (b >= 0) & (a != b)
            if m.any():
                best = min(best, dist - 1.0)
                if dist - 1.0 < gap_min:
                    aa, bb = a[m], b[m]
                    lo, hi = np.minimum(aa, bb), np.maximum(aa, bb)
                    pairs.update(zip(lo.tolist(), hi.tolist()))
    out["min_gap_px"] = round(float(best), 2) if np.isfinite(best) else ">= %d" % (r - 1)
    out["chart_pairs_under_gap"] = len(pairs)
    # axis alignment of the panel islands: least-squares map from the projected layout
    bad = []
    transposed = 0
    for k, isl in enumerate(res["islands"]):
        f = isl["faces"]
        src = isl["uv_in"].reshape(-1, 2)
        dst = (uv[f] * size).reshape(-1, 2)
        src = src - src.mean(axis=0)
        dst = dst - dst.mean(axis=0)
        if np.abs(src).max() < 1e-9:
            continue
        A, *_ = np.linalg.lstsq(src, dst, rcond=None)
        # xatlas stretches every chart a little so its extents come out whole texels (measured
        # 2026-10-12: a 36.25 x 30.25 chart came out 37 x 31) and turns charts by transposing them:
        # aligned = a diagonal or an anti-diagonal map
        dg, off = abs(A[0, 0]) + abs(A[1, 1]), abs(A[0, 1]) + abs(A[1, 0])
        if min(dg, off) > 1e-3 * max(dg, off):
            bad.append((k, len(f), round(float(np.ptp(src[:, 0])), 2), round(float(np.ptp(src[:, 1])), 2)))
        if np.linalg.det(A) < 0:
            transposed += 1
    out["islands_not_axis_aligned"] = len(bad)
    out["not_aligned_examples"] = bad[:5]           # (island, faces, projected extent u, v in texels)
    out["islands_mirrored"] = transposed
    # starved charts where they landed (chart_starvation): unwrap made every starved fallback chart a
    # swatch, so any left is a bug; planar islands are only counted (a panel is never a swatch)
    upx = uv * size
    fbm, plan = kind == KIND_FALLBACK, kind == KIND_PLANAR
    out["starved_fallback_charts"] = len(starved_charts(upx[fbm], chart[fbm]))
    out["starved_planar_islands"] = len(starved_charts(upx[plan], chart[plan]))
    return out


def check_line(chk):
    """check_layout's numbers as the bake log line build.py gates (overlap, out of range, gap,
    starved fallback charts) plus the ones it only reports."""
    gap = chk["min_gap_px"]
    gap = ("%.1f" % gap) if isinstance(gap, float) else gap.replace(" ", "")
    return ("bake: shell layout check: overlap %d px, out of range %d, gap %s px (%d chart pairs under %d), starved "
            "fallback charts %d, planar islands %d; fold residue %d px, %d islands not axis-aligned, %d transposed"
            % (chk["overlap_between_charts_px"], chk["uv_out_of_range"], gap, chk["chart_pairs_under_gap"], GAP_MIN,
               chk["starved_fallback_charts"], chk["starved_planar_islands"], chk["overlap_inside_charts_px"],
               chk["islands_not_axis_aligned"], chk["islands_mirrored"]))


def save_result(path, res):
    """The arrays a later check or the harness needs, without Blender (npz + the meta as JSON)."""
    np.savez_compressed(path, uv=res["uv"], island=res["island"], kind=res["kind"], chart=res["chart"],
                        axis=res["axis"], layer=res["layer"], area=res["area"],
                        meta=json.dumps(res["meta"]), line=res["line"])
