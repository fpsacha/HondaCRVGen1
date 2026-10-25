r"""
Lit lamps keep their Mask zone at every Vehicle Texture Size cap (bug wave 1, H-VISUAL-1, 2026-10-24):

    python scripts\test_compose_lamps.py

The game shrinks the 2048 Mask by 2 x 2 integer averages (pzview_rules.game_cap) and the shader lights a
fragment only where the bilinear Mask sample is within 0.01 of a lamp zone. compose_textures.lamp_guard wraps
every lit lens in whole cap-256 blocks of one lamp zone.
  * synthetic: a lens with a diagonal tail / stop split on a body panel next to a window: without the guard
    lamp texels lose their zone at the coarse caps; with it 100 % keep one at every cap, every colour stays a
    legal zone, the window zone outside the lit blocks is untouched, and no lit fragment's bilinear footprint
    holds a non-lamp texel.
  * synthetic islands (bug wave 2, R2-VIS-1): a lens island, an 8 px gutter and a far island half a metre away
    on the car: the wave-1 rule rezoned the far island; with the lens geometry (compose_textures.lens_geometry)
    no far texel takes a lamp zone at any cap, stray lit texels there stay theirs, and the lens lights 100 %.
  * shipped sheets: the guard applied to the shipped Mask + Lights keeps >= 99 % of the lamp texels in a lamp
    zone at 2048 / 1024 / 512 / 256 (master: 95.3 / 95.3 / 82.1 / 62.6 %), and no lit fragment (alpha-weighted)
    reads a non-lamp texel beyond 0.5 % (the remaining fragment loss is the seam where two lamp zones meet).
    With the matching triangle dump (CRV_ROOT's, else the main checkout's blender\bake\shell_uvmesh.npz) the
    fragments are counted on the lens's own surface (>= 99.9 % at 2048-512, 99 % at 256), and no lamp zone
    lands outside the lens islands: no covered texel of another island farther than LAMP_GUARD_NEAR from every
    lens is rezoned, nor reads a lamp zone at any cap (the wave-1 rule rezoned ~9k).
  * compose wires it: main() guards the zones with the shipped Lights' alpha and the lens geometry before it
    writes the Mask and the polish gloss copy.
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import compose_textures as C  # noqa: E402
import lampcov as LC  # noqa: E402
import paint_pass  # noqa: E402
import pzview_rules as R  # noqa: E402

TEX = os.path.join(os.path.dirname(HERE), "mod", "Contents", "mods", "HondaCRVGen1", "common", "media", "textures", "Vehicles")


def fail(msg):
    raise SystemExit("FAIL " + msg)


def rgb(name):
    return np.array([int(np.clip(v * 255.0 + 0.5, 0, 255)) for v in paint_pass.ZONE[name]], np.uint8)


def synthetic(split_islands=True):
    """128 x 128 Mask (cap 16 -> 8 px blocks, as 2048 / 256), Lights at 64, on the body, the rear glass to the
    right. split_islands (the layout since bug wave 3): the lens's tail part (columns 16-44) and stop part
    (columns 72-100) are two islands 27 px apart (planar_uv.GROUP_GAP x the pack's scale); False: one lens with
    a diagonal tail / stop split (wave 1's layout). Returns (mask, lights, tail texels, stop texels)."""
    m = np.zeros((128, 128, 3), np.uint8)
    m[:] = rgb("body")
    m[:, 112:] = rgb("window_t")
    yy, xx = np.mgrid[0:128, 0:128]
    if split_islands:
        tail = ((yy - 61) / 30.0) ** 2 + ((xx - 30) / 14.0) ** 2 <= 1.0
        stop = ((yy - 61) / 30.0) ** 2 + ((xx - 86) / 14.0) ** 2 <= 1.0
    else:
        lens = ((yy - 61) / 33.0) ** 2 + ((xx - 57) / 21.0) ** 2 <= 1.0
        stop, tail = lens & (yy + 0.6 * xx < 95), lens & (yy + 0.6 * xx >= 95)
    lens = tail | stop
    m[stop] = rgb("stop_r")
    m[tail] = rgb("lights_rt")
    a = np.zeros((128, 128), np.float32)
    a[lens] = 255
    from scipy import ndimage
    a = ndimage.uniform_filter(a, 3)                       # an anti-aliased rim, partly over the body zone
    lights = np.zeros((64, 64, 4), np.uint8)
    lights[..., 0] = 190
    lights[..., 3] = a.reshape(64, 2, 64, 2).mean(axis=(1, 3)).astype(np.uint8)
    return m, lights, tail, stop


def legal_codes():
    return {(int(c[0]) << 16) | (int(c[1]) << 8) | int(c[2]) for c in (rgb(n) for n in paint_pass.ZONE)}


def code_of(a):
    a = np.asarray(a)
    return (a[..., 0].astype(int) << 16) | (a[..., 1].astype(int) << 8) | a[..., 2]


def zcode(name):
    return int(code_of(rgb(name)))


def test_synthetic_one_island_seam():
    """Why the parts are separate islands (bug wave 3): with a tail / stop edge inside one lens the guard without
    the merge leaves lit fragments between two lamp zones at the coarse caps: the dark seam wave 1 hid by making
    the whole lens tail (merge, still the rule for a bake without rigid lens groups), which Project Viewpoint
    lit with the lights only."""
    m, lights, tail, stop = synthetic(split_islands=False)
    seams = {}
    for merge in (False, True):
        g = np.asarray(C.lamp_guard(m, lights[..., 3], cap=16, log=lambda s: None, merge=merge)[0])
        worst = 0
        for cap in (64, 32, 16):
            mm = R.game_cap(g, cap)[..., :3].astype(np.float32) / 255.0
            a = LC._bilinear((R.game_cap(lights, cap).astype(np.float32) / 255.0)[..., 3:4], 128)[..., 0]
            worst = max(worst, int(((a > C.LAMP_GUARD_ALPHA / 255.0) & ~LC.is_lamp(LC._bilinear(mm, 128))).sum()))
        seams[merge] = (worst, set(code_of(g)[tail | stop].tolist()))
    if seams[False][0] == 0:
        fail("synthetic one island: a tail / stop edge inside one lens shows no seam (the split layout would be moot)")
    if seams[True][0] or seams[True][1] != {zcode("lights_rt")}:
        fail("synthetic one island: the legacy merge (old bakes) no longer makes the lens one tail zone without a seam")
    print("LAMPS synthetic one island: a tail / stop edge inside one lens leaves up to %d dark lit fragments; the legacy "
          "merge (bakes without lens groups) makes it all tail, no seam" % seams[False][0])


def test_synthetic():
    m, lights, tail, stop = synthetic()
    caps = (128, 64, 32, 16)
    before = [LC.coverage(m, lights, c, n_pts=128)[0] for c in caps]
    if min(before) >= 99.0:
        fail("synthetic: the unguarded Mask already keeps %s %% (the test lens shows no loss)" % before)
    g, st = C.lamp_guard(m, lights[..., 3], cap=16, log=lambda s: None, merge=False)
    g = np.asarray(g)
    after = [LC.coverage(g, lights, c, n_pts=128) for c in caps]
    if min(t for t, _f in after) < 100.0:
        fail("synthetic: guarded lamp texels keep a lamp zone %s %% at caps %s" % ([t for t, _f in after], caps))
    codes = set(((g[..., 0].astype(int) << 16) | (g[..., 1].astype(int) << 8) | g[..., 2]).ravel().tolist())
    if not codes <= legal_codes():
        fail("synthetic: the guard wrote colours that are no zone: %s" % sorted(codes - legal_codes()))
    lit_cols = (lights[..., 3] >= C.LAMP_GUARD_ALPHA).repeat(2, 0).repeat(2, 1).any(0)
    far_window = np.zeros(m.shape[:2], bool)
    far_window[:, 112:] = True
    far_window[:, :8 * (int(np.nonzero(lit_cols)[0].max()) // 8 + 1)] = False   # outside every lit block's columns
    if (g[far_window] != m[far_window]).any():
        fail("synthetic: the guard overwrote window texels outside the lit blocks")
    for cap in caps:                                       # no lit fragment reads a non-lamp texel
        mm = R.game_cap(g, cap)[..., :3].astype(np.float32) / 255.0
        ll = R.game_cap(lights, cap).astype(np.float32) / 255.0
        a = LC._bilinear(ll[..., 3:4], 128)[..., 0]
        foot = LC._bilinear(LC.is_lamp(mm).astype(np.float32)[..., None], 128)[..., 0]
        bad = (a > C.LAMP_GUARD_ALPHA / 255.0) & (foot < 0.999)
        if bad.any():
            fail("synthetic: at cap %d %d lit fragments read a non-lamp texel" % (cap, bad.sum()))
        frag = LC.is_lamp(LC._bilinear(mm, 128))           # no fragment between two lamp zones
        seam = (a > C.LAMP_GUARD_ALPHA / 255.0) & ~frag
        if seam.any():
            fail("synthetic: at cap %d %d lit fragments fall between two lamp zones (a seam through the lens)" % (cap, seam.sum()))
        # each part lights by its own zone at this cap: tail with the lights only, stop with the brake only (the
        # game's and Project Viewpoint's stock rule)
        on_t = R.lamp_enable(LC._bilinear(mm, 128), ("tail",))
        on_b = R.lamp_enable(LC._bilinear(mm, 128), ("brake",))
        lit = a > C.LAMP_GUARD_ALPHA / 255.0
        t_s, s_s = tail[::1, ::1] & lit, stop & lit
        if (on_t[t_s] < 1).any() or (on_b[s_s] < 1).any() or (on_t[s_s] > 0).any() or (on_b[t_s] > 0).any():
            fail("synthetic: at cap %d a part lights by the other part's switch (tail %d / %d, stop %d / %d)"
                 % (cap, int((on_t[t_s] >= 1).sum()), int(t_s.sum()), int((on_b[s_s] >= 1).sum()), int(s_s.sum())))
    code = code_of(g)
    if set(code[tail].tolist()) != {zcode("lights_rt")} or set(code[stop].tolist()) != {zcode("stop_r")}:
        fail("synthetic: the guard merged the lens's parts: tail %s, stop %s" % (
            sorted("%06x" % c for c in set(code[tail].tolist())), sorted("%06x" % c for c in set(code[stop].tolist()))))
    if st["merged_stop"]:
        fail("synthetic: the guard still merges stop texels into the tail zone (%d)" % st["merged_stop"])
    print("LAMPS synthetic: unguarded %s %%, guarded 100 %% at caps %s; tail and stop parts keep their own zones (tail "
          "lights with the lights, stop with the brake); %d texels rezoned, colours legal, far window kept"
          % (["%.1f" % b for b in before], caps, sum(st["changed"].values())))


def test_split_lens_unify():
    """The zone bake projects the full-detail twin, whose lens faces split at TAIL_STOP_Z by their own centres, so
    the low stop island came out with tail patches (and the Dilate spread them into its gutter, where lit Lights
    alpha voted them back into the guard's blocks: 0.4-2.5 % of the lens unlit at 1024-256 in the scratch build).
    With lens_geometry's island heights the guard gives every texel of a lens island (gutter included) its part."""
    m, lights, tail, stop = synthetic()
    yy, xx = np.mgrid[0:128, 0:128]
    m[stop & (yy > 70)] = rgb("lights_rt")                 # the twin's tail faces reached into the stop island
    gutter = ~(tail | stop)
    island = np.where(xx < 58, 0, 1)                       # every texel's (nearest covered texel's) island
    m[gutter & (island == 1) & (yy > 75) & (np.abs(xx - 86) < 18)] = rgb("lights_rt")
    pos = np.stack([xx * 0.003, np.zeros_like(xx, dtype=np.float64), yy * 0.003], -1).astype(np.float32)
    geo = (pos, tail | stop, island, np.array([1.20, 1.30]))   # tail island below TAIL_STOP_Z, stop island above
    g, st = C.lamp_guard(m, lights[..., 3], cap=16, log=lambda s: None, geo=geo, merge=False)
    code = code_of(np.asarray(g))
    if set(code[stop].tolist()) != {zcode("stop_r")} or st["unified"] == 0:
        fail("split lens: the stop island keeps %s after the guard" % sorted("%06x" % c for c in set(code[stop].tolist())))
    for cap in (64, 32, 16):
        mm = R.game_cap(np.asarray(g), cap)[..., :3].astype(np.float32) / 255.0
        a = LC._bilinear((R.game_cap(lights, cap).astype(np.float32) / 255.0)[..., 3:4], 128)[..., 0]
        on = (a > C.LAMP_GUARD_ALPHA / 255.0) & (tail | stop)
        if (on & ~LC.is_lamp(LC._bilinear(mm, 128))).any():
            fail("split lens: at cap %d lit lens fragments fall between the parts" % cap)
    print("LAMPS split lens: %d texels of the wrong part unified to their island's part; the lens lights fully at every cap"
          % st["unified"])


def test_mark_combined():
    """The shipped Mask tags the D-pillar stop part (|x| > COMBINED_MIN_X on the car) stop_rc / stop_lc and leaves the
    high stop lamp plain stop_l, and replayed with the mod's rule (pzview_rules.lamp_enable, CRV_TAIL) the whole lens
    glows at CRV_TAIL with the lights and fully on the brake at every cap, the high stop lamp only on the brake;
    the stock rule (the game's, Viewpoint's) still sees the tag as the stop zone."""
    m, lights, tail, stop = synthetic()
    yy, xx = np.mgrid[0:128, 0:128]
    # the high stop lamp, stop_l, on the centre line (lit blocks rows 14-15, its ring row 13; the lens's ring is row 12)
    high = ((yy - 122) / 4.0) ** 2 + ((xx - 40) / 30.0) ** 2 <= 1.0
    m[high] = rgb("stop_l")
    a = lights[..., 3].repeat(2, 0).repeat(2, 1).astype(np.float32)
    a[high] = 255
    lights[..., 3] = a.reshape(64, 2, 64, 2).mean(axis=(1, 3)).astype(np.uint8)
    pos = np.stack([np.where(yy < 104, 0.62, 0.0), yy * 0.003, xx * 0.003], -1).astype(np.float32)  # D-pillar at x 0.62
    geo = (pos, np.ones((128, 128), bool), np.zeros((128, 128), np.int64))
    g, _st = C.lamp_guard(m, lights[..., 3], cap=16, log=lambda s: None, merge=False)   # whole blocks (one island)
    out, n = C.mark_combined_stop(g, geo, log=lambda s: None)
    out = np.asarray(out)
    code = code_of(out)
    if n == 0 or set(code[stop].tolist()) != {zcode("stop_rc")} or set(code[high].tolist()) != {zcode("stop_l")}:
        fail("mark_combined_stop: D-pillar stop %s, high stop %s" % (sorted("%06x" % c for c in set(code[stop].tolist())),
                                                                   sorted("%06x" % c for c in set(code[high].tolist()))))
    if not set(code.ravel().tolist()) <= legal_codes():
        fail("mark_combined_stop wrote colours that are no zone")
    k = float(__import__("gen_shaders").TAIL_LEVEL)
    for cap in (128, 64, 32, 16):
        mm = LC._bilinear(R.game_cap(out, cap)[..., :3].astype(np.float32) / 255.0, 128)
        lit = LC._bilinear((R.game_cap(lights, cap).astype(np.float32) / 255.0)[..., 3:4], 128)[..., 0] > C.LAMP_GUARD_ALPHA / 255.0
        lens = (tail | stop) & lit
        for groups, w_lens, w_high in ((("tail",), k, 0.0), (("brake",), 1.0, 1.0), (("tail", "brake"), 1.0, 1.0)):
            on = R.lamp_enable(mm, groups, k)
            if np.abs(on[lens] - w_lens).max() > 1e-9 or np.abs(on[high & lit] - w_high).max() > 1e-9:
                fail("mark_combined_stop: at cap %d with %s the lens lights %s (want %.2f), the high stop %s (want %.2f)"
                     % (cap, "+".join(groups), np.unique(on[lens]), w_lens, np.unique(on[high & lit]), w_high))
        if (R.lamp_enable(mm, ("brake",))[stop & lit] < 1).any():
            fail("mark_combined_stop: at cap %d the stock rule no longer sees the tagged stop part as the stop zone" % cap)
    print("LAMPS combined tag: %d D-pillar stop texels stop_rc, the high stop lamp plain; mod rule: lens x%.2f with the lights, "
          "x1 on the brake, high stop on the brake only, at every cap; stock rule: the tag is the stop zone" % (n, k))


def synthetic_islands():
    """128 x 128 Mask (cap 16 -> 8 px blocks) packed like the shell sheet: the lens (stop_r) is its own island
    (0) in a gutter (no triangle); island 1 (columns 88-127, door_rr) lies 13 px right of the lens's edge across
    the gutter and half a metre away on the car; island 2 (columns 0-39, body) is the panel beside the lamp, in
    the lens's plane, 11 px (3.3 cm) from the lens. 3 mm per texel, so LAMP_GUARD_NEAR is 10 texels. Lights
    alpha bleeds 3 texels onto island 1's edge (stray lit texels, as the bake's dilation leaves them). Returns
    (mask, lights, geo)."""
    from scipy import ndimage
    m = np.zeros((128, 128, 3), np.uint8)
    m[:] = rgb("body")
    m[:, 88:] = rgb("door_rr")
    yy, xx = np.mgrid[0:128, 0:128]
    lens = ((yy - 64) / 30.0) ** 2 + ((xx - 62) / 12.0) ** 2 <= 1.0      # columns 50-74
    m[lens] = rgb("stop_r")
    a = np.zeros((128, 128), np.float32)
    a[lens] = 255
    a[40:90, 88:91] = 160                                    # bled onto island 1 (no lamp zone under it)
    lights = np.zeros((64, 64, 4), np.uint8)
    lights[..., 0] = 190
    lights[..., 3] = a.reshape(64, 2, 64, 2).mean(axis=(1, 3)).astype(np.uint8)
    lens_isl = ndimage.binary_dilation(lens)
    covered = lens_isl | (xx >= 88) | (xx < 40)
    island = np.where(lens_isl, 0, np.where(xx >= 84, 1, 2))
    pos = np.stack([xx * 0.003, yy * 0.003, np.where(island == 1, 0.5, 0.0)], -1).astype(np.float32)
    return m, lights, (pos, covered, island)


def test_synthetic_islands():
    """R2-VIS-1: the guard's blocks crossed the gutter into the next UV island (far away on the car), so a
    removed / damaged lamp greyed that panel. With the lens geometry no texel of island B takes a lamp zone,
    the stray lit texels on it stay its own zone, and the lens still keeps its zone at every cap."""
    m, lights, geo = synthetic_islands()
    island_b = geo[2] >= 1                                 # islands 1 and 2: every texel farther than 3 cm from the lens
    covered = geo[1]
    caps = (128, 64, 32, 16)
    old = np.asarray(C.lamp_guard(m, lights[..., 3], cap=16, log=lambda s: None)[0])
    old_hit = int(((old != m).any(-1) & island_b & covered).sum())
    if old_hit == 0:
        fail("synthetic islands: the wave-1 rule left island B alone (the test layout shows no bleed)")
    g, st = C.lamp_guard(m, lights[..., 3], cap=16, log=lambda s: None, geo=geo)
    g = np.asarray(g)
    hit = int(((g != m).any(-1) & island_b & covered).sum())
    if hit:
        fail("synthetic islands: the guard rezoned %d texels of the far island B (a removed lamp greys them)" % hit)
    if st["stray_lit"] == 0:
        fail("synthetic islands: the stray lit texels on island B were taken for lens")
    lensf = []
    for cap in caps:                                       # every lit fragment on the lens island lights
        mm = R.game_cap(g, cap)[..., :3].astype(np.float32) / 255.0
        ll = R.game_cap(lights, cap).astype(np.float32) / 255.0
        a = LC._bilinear(ll[..., 3:4], 128)[..., 0]
        on = (a > C.LAMP_GUARD_ALPHA / 255.0) & covered & (geo[2] == 0)
        ok = LC.is_lamp(LC._bilinear(mm, 128))
        lensf.append(100.0 * (ok & on).sum() / on.sum())
        far = ok & covered & island_b
        if far.any():
            fail("synthetic islands: at cap %d %d fragments of island B read a lamp zone" % (cap, far.sum()))
    if min(lensf) < 100.0:
        fail("synthetic islands: lit lens fragments keep a lamp zone only %s %% at caps %s" % (["%.1f" % f for f in lensf], caps))
    print("LAMPS synthetic islands: wave-1 rule rezoned %d texels of the far island, now 0; lens lights 100 %% at caps %s; "
          "%d stray lit texels left alone" % (old_hit, caps, st["stray_lit"]))


def _main_root():
    """The main checkout (a worktree's blender\\ is gitignored and empty): ...\\CRV_Gen1 above .claude\\worktrees."""
    root = os.path.dirname(HERE)
    parts = os.path.normpath(root).split(os.sep)
    if ".claude" in parts and "worktrees" in parts:
        root = os.sep.join(parts[:parts.index(".claude")])
    return root


def shipped_paths():
    """(textures dir, triangle dump) of one data root: CRV_ROOT (a scratch build) if set, else this checkout's
    sheets with the main checkout's dump."""
    if os.environ.get("CRV_ROOT"):
        r = os.environ["CRV_ROOT"]
        return (os.path.join(r, "mod", "Contents", "mods", "HondaCRVGen1", "common", "media", "textures", "Vehicles"),
                os.path.join(r, "blender", "bake", "shell_uvmesh.npz"))
    return TEX, os.path.join(_main_root(), "blender", "bake", "shell_uvmesh.npz")


def shipped_geo(mask, lights, npz):
    """lens_geometry for the shipped Mask, or None when the dump is missing or belongs to another layout
    (fewer than 85 % of the lit lamp texels within a gutter's width of a triangle)."""
    geo = C.lens_geometry(npz, mask.shape[0])
    if geo is None:
        return None
    from scipy import ndimage
    code = (mask[..., 0].astype(int) << 16) | (mask[..., 1].astype(int) << 8) | mask[..., 2]
    lc = np.array(list(C._zone_codes(("lights_", "stop_")).values()))
    k = mask.shape[0] // lights.shape[0]
    lit = np.repeat(np.repeat(lights[..., 3], k, 0), k, 1) >= C.LAMP_GUARD_ALPHA
    seeds = lit & np.isin(code, lc)
    near = ndimage.binary_dilation(geo[1], iterations=24)     # gutters >= 8 px; a lens group's up to its GROUP_GAP
    share = float((seeds & near).sum()) / max(1, int(seeds.sum()))
    return geo if share >= 0.85 else None         # matching dumps 0.93-0.94 (Lights and zones dilate into the gutters)


def test_shipped():
    tex, npz = shipped_paths()
    try:
        mask, lights = LC.load(tex)
    except OSError:
        print("LAMPS shipped: skipped (no sheets)")
        return
    geo = shipped_geo(mask, lights, npz)
    groups = C.lens_groups(npz) if geo is not None else 0       # what compose decides from the layout
    g, st = C.lamp_guard(mask, lights[..., 3], log=lambda s: None, geo=geo, merge=not groups)
    g = np.asarray(g)
    rows = ["layout %s" % ("with %d rigid lens groups" % groups if groups else "without lens groups (legacy merge)")]
    region = None
    if geo is not None:
        covered = geo[1]
        code = (mask[..., 0].astype(int) << 16) | (mask[..., 1].astype(int) << 8) | mask[..., 2]
        lc = np.array(list(C._zone_codes(("lights_", "stop_")).values()))
        k = mask.shape[0] // lights.shape[0]
        lit = lights[..., 3].repeat(k, 0).repeat(k, 1) >= C.LAMP_GUARD_ALPHA
        # counted on the lens's own surface (lampcov.lens_region): lit fragments over a neighbouring island's
        # texels are that panel's, and must NOT light (R2-VIS-1)
        region = LC.lens_region(mask, lights, npz)
    for cap in LC.CAPS:
        t0, _f0 = LC.coverage(mask, lights, cap, region=region)
        t, f = LC.coverage(g, lights, cap, region=region)
        if t < 99.0:
            fail("shipped: at cap %d only %.1f %% of the lamp texels keep a lamp zone with the guard" % (cap, t))
        mm = R.game_cap(g, cap)[..., :3].astype(np.float32) / 255.0
        ll = R.game_cap(lights, cap).astype(np.float32) / 255.0
        a = LC._bilinear(ll[..., 3:4], 2048)[..., 0]
        w = np.where(a > C.LAMP_GUARD_ALPHA / 255.0, a, 0.0)
        if region is not None:
            w = np.where(region, w, 0.0)
        foot = LC._bilinear(LC.is_lamp(mm).astype(np.float32)[..., None], 2048)[..., 0] < 0.999
        nonlamp = 100.0 * float((w * foot).sum()) / float(w.sum())
        if nonlamp > (1.0 if cap == 256 else 0.5):
            fail("shipped: at cap %d %.2f %% of the lit fragments read a non-lamp Mask texel" % (cap, nonlamp))
        if f < (99.0 if cap == 256 else 99.9) if geo is not None else f < (97.5 if cap == 256 else 99.0):
            fail("shipped: at cap %d only %.1f %% of the lit fragments (alpha-weighted) light" % (cap, f))
        rows.append("%d: %.1f -> %.1f %% (%s fragments %.2f %%, non-lamp %.2f %%)"
                    % (cap, t0, t, "lens surface" if geo is not None else "all", f, nonlamp))
    if geo is not None:
        # R2-VIS-1: no lamp zone outside the lens islands. A covered texel on an island that holds no lens texel,
        # farther than LAMP_GUARD_NEAR from every lens texel, never takes a lamp zone; the wave-1 rule (no
        # geometry) put one on thousands (hood lip, fender top, rear quarter, D-pillar strips)
        # (measured here on its own: the lens is the covered lit texels already in a lamp zone)
        from scipy.spatial import cKDTree
        lens = covered & lit & np.isin(code, lc)
        dist = cKDTree(geo[0][lens]).query(geo[0][covered], distance_upper_bound=0.5, workers=-1)[0]
        beyond = np.zeros(covered.shape, bool)
        beyond[covered] = dist > C.LAMP_GUARD_NEAR
        lens_isl = np.unique(geo[2][lens])
        far = beyond & ~np.isin(geo[2], lens_isl[lens_isl >= 0])
        changed = (g != mask).any(-1)
        if (changed & far).any():
            fail("shipped: the guard put a lamp zone on %d texels of other islands far from every lens" % (changed & far).sum())
        old = np.asarray(C.lamp_guard(mask, lights[..., 3], log=lambda s: None)[0])
        old_far = int(((old != mask).any(-1) & far).sum())
        caps_far = []
        for cap in LC.CAPS:   # nor at a smaller cap: (the bake's own lamp-zone texels there are the baseline)
            n0, n1, nw = (int((LC.is_lamp(LC._bilinear(R.game_cap(x, cap)[..., :3].astype(np.float32) / 255.0, 2048)) & far).sum())
                          for x in (mask, g, old))
            # a gutter texel the guard rezones can tint the edge texel of a far panel across it in the averaged
            # caps: allow a tenth of what the wave-1 rule added (it measured +2300 at 256), none at 2048
            if n1 - n0 > (0 if cap == 2048 else max(100, 0.1 * (nw - n0))):
                fail("shipped: at cap %d %d far texels read a lamp zone after the guard, %d before (wave-1 rule %d)"
                     % (cap, n1, n0, nw))
            caps_far.append("%d: %d -> %d (wave 1 %d)" % (cap, n0, n1, nw))
        rows.append("far islands rezoned 0 (wave-1 rule %d); far texels reading a lamp zone per cap %s; %d stray "
                    "lit texels no lens" % (old_far, ", ".join(caps_far), st["stray_lit"]))
    else:
        rows.append("no matching triangle dump at %s: wave-1 rule only" % npz)
    # the brake still lights something: the high stop lamp keeps its stop zone under lit texels
    code = (g[..., 0].astype(int) << 16) | (g[..., 1].astype(int) << 8) | g[..., 2]
    lit = lights[..., 3].repeat(2, 0).repeat(2, 1) >= C.LAMP_GUARD_ALPHA
    stops = [n for n in ("stop_r", "stop_l") if (lit & (code == ((int(rgb(n)[0]) << 16) | (int(rgb(n)[1]) << 8) | int(rgb(n)[2])))).sum() > 300]
    if not stops:
        fail("shipped: no lit texel keeps a stop zone after the guard (the brake would light nothing)")
    # bug wave 3 (H-VP-1): sheets built with the split lens carry the combined tag; then BOTH D-pillar lenses must have
    # lit stop texels (Project Viewpoint lights them on the brake) and lit tail texels (its rear lamps)
    sc = code_of(mask)
    tagged = {n: int((lit & (sc == zcode(n))).sum()) for n in ("stop_rc", "stop_lc", "lights_rt", "lights_lt")}
    if tagged["stop_rc"] or tagged["stop_lc"]:
        weak = [n for n, v in tagged.items() if v < 300]
        if weak:
            fail("shipped: lit texels per D-pillar zone %s: %s under 300 (each lens needs its tail and its stop part)"
                 % (tagged, weak))
        rows.append("split lens: lit texels %s" % ", ".join("%s %d" % t for t in tagged.items()))
    else:
        rows.append("sheets predate the split lens (no stop_rc / stop_lc): rebuild from the bake")
    print("LAMPS shipped Mask, lamp texels keeping their zone: " + "; ".join(rows) + "; brake lights %s" % stops)


def _xatlas_runner():
    """run_job for planar_uv.unwrap (Blender's bundled Python + tools\\pylib's xatlas), None when unavailable."""
    import planar_uv
    try:
        import crv_paths
        py = os.path.join(os.path.dirname(crv_paths.BLENDER), "%s" % next(
            d for d in os.listdir(os.path.dirname(crv_paths.BLENDER)) if d[:1].isdigit()), "python", "bin", "python.exe")
    except (OSError, StopIteration):
        return None
    pylib = next((p for p in (os.path.join(os.path.dirname(HERE), "tools", "pylib"), os.path.join(_main_root(), "tools", "pylib"))
                  if os.path.isdir(p) and any(f.startswith("xatlas") for f in os.listdir(p))), None)
    if not os.path.exists(py) or pylib is None:
        return None
    return lambda payload: planar_uv.run_xatlas_job(payload, py, os.path.join(HERE, "xatlas_job.py"), pylib)


def _lens_scene(grouped):
    """planar_uv.unwrap's input for a small sheet: twelve roof panels (TOP islands) and one D-pillar lens on the
    body facing back, its tail part (lights_rt, z 1.2-1.3) and stop part (stop_r, z 1.3-1.4) sharing an edge as
    on the car. grouped: the lens faces carry bake_atlas's group / split (LENS_GROUPS)."""
    rng = np.random.default_rng(7)
    pos, zone, mat = [], [], []

    def quad(p0, du, dv, z, m):
        p0, du, dv = (np.array(v, dtype=np.float64) for v in (p0, du, dv))
        a, b, c, d = p0, p0 + du, p0 + du + dv, p0 + dv
        pos.extend([(a, b, c), (a, c, d)])
        zone.extend([z, z])
        mat.extend([m, m])
    for k in range(12):
        s = rng.uniform(0.08, 0.35, 2)
        quad((k % 4 * 0.5, k // 4 * 0.5, 1.6), (s[0], 0, 0), (0, s[1], 0), 0, 0)
    for z0, zn in ((1.2, 1), (1.3, 2)):          # rear-facing: du x dv = -y
        for col in range(3):
            quad((0.60 + 0.03 * col, -1.9, z0), (0.03, 0, 0), (0, 0, 0.1), zn, 1)
    T = len(pos)
    zone = np.array(zone)
    tris = {"pos": np.array(pos), "obj": np.zeros(T, np.int64), "mat": np.array(mat), "gen": np.zeros(T, np.int64),
            "zone": zone, "w": np.ones(T), "obj_names": ["body"], "mat_names": ["Body", "Feux_rouge"],
            "zone_names": ["body", "lights_rt", "stop_r"]}
    if grouped:
        tris["group"] = np.where(zone > 0, 0, -1)
        tris["split"] = zone.copy()
    return tris


def test_lens_layout():
    """Bug wave 3 (H-VP-1): the D-pillar lens's tail and stop parts are separate UV islands at least 23 px apart on
    the sheet (no 8 px guard block, ring or 256-cap bilinear footprint holds both; planar_uv.GROUP_GAP), packed by
    xatlas as one rigid group. Without the group they are one island (wave 1 then had to make the lens all tail)."""
    import planar_uv
    from scipy.spatial import cKDTree
    job = _xatlas_runner()
    if job is None:
        print("LAMPS lens layout: skipped (no Blender Python / xatlas)")
        return
    quiet = lambda s: None                                             # noqa: E731
    out = {}
    for grouped in (False, True):
        tris = _lens_scene(grouped)
        res = planar_uv.unwrap(tris, job, size=512, log=quiet)
        zone = tris["zone"]
        isl_t, isl_s = set(res["island"][zone == 1].tolist()), set(res["island"][zone == 2].tolist())
        px = res["uv"] * 512
        pts = {}
        for zn in (1, 2):
            ys, xs = [], []
            for i in np.nonzero(zone == zn)[0]:
                y, x = planar_uv.raster(px[i], 512, 512, conservative=True)
                ys.append(y)
                xs.append(x)
            pts[zn] = np.stack([np.concatenate(xs), np.concatenate(ys)], -1).astype(np.float64)
        gap = float(cKDTree(pts[1]).query(pts[2])[0].min()) - 1.0
        out[grouped] = (isl_t, isl_s, gap, planar_uv.check_layout(res), res["stats"]["scale"])
    isl_t, isl_s, _gap, _chk, _sc = out[False]
    if not (isl_t & isl_s):
        fail("lens layout: without the group the tail and stop parts already lie on separate islands (the test shows nothing)")
    isl_t, isl_s, gap, chk, scale = out[True]
    if isl_t & isl_s or min(isl_t | isl_s) < 0:
        fail("lens layout: the tail and stop parts share an island or left the planar layout: %s / %s" % (isl_t, isl_s))
    if gap < 23.0:
        fail("lens layout: tail and stop parts only %.1f px apart (want >= 23: three 8 px blocks)" % gap)
    if chk["overlap_between_charts_px"] or chk["uv_out_of_range"] or chk["chart_pairs_under_gap"]:
        fail("lens layout: the grouped layout fails the layout check: %s" % planar_uv.check_line(chk))
    print("LAMPS lens layout: tail / stop parts one island before, separate islands %.0f px apart now (scale %.2f, "
          "layout check clean)" % (gap, scale))


def test_compose_wiring():
    src = open(os.path.join(HERE, "compose_textures.py"), encoding="utf-8").read()
    main = src[src.index("def main():"):]
    i_geo = main.find("lens_geo = lens_geometry(os.path.join(BAKE_DIR, \"shell_uvmesh.npz\")")
    i_guard = main.find("lamp_guard(zones")
    i_mark = main.find("shipped, _n = mark_combined_stop(zones, lens_geo)")
    i_mask = main.find("shipped.convert(\"RGB\").save(mask_path)")
    i_gloss = main.find("shell_mask_gloss.png\"))")
    i_lights = main.find("lights_s.save(p)")
    if min(i_geo, i_guard, i_mark, i_mask, i_gloss, i_lights) < 0 or not (
            i_lights < i_guard < i_gloss < i_mark < i_mask and i_geo < i_guard):
        fail("compose_textures.main must guard the zones (lamp_guard) with the saved Lights before writing "
             "shell_mask_gloss.png, then tag the combined lens (mark_combined_stop) and write the shipped Mask")
    if "geo=lens_geo" not in main[i_guard:i_gloss]:
        fail("compose_textures.main must pass the lens geometry to lamp_guard, or the guard rezones whole blocks across "
             "neighbouring UV islands (R2-VIS-1)")
    print("LAMPS compose: main guards the zones with the shipped Lights and the lens geometry, writes the gloss copy, then "
          "tags the combined lens on the shipped Mask")


def test_shader_combined_lamp():
    """The D-pillar lens is one tail zone lit as a combined stop / tail lamp by the mod's shader (gen_shaders
    LAMP_RULE): CRV_TAIL (35-45 %) with the tail lights, 1 while braking, the stop enables paired with colZone22/23
    and the tail zone flags with colZone20/21, the Lights mix by crvLamp. pzview_rules.lamp_weights replays it."""
    import re
    import gen_shaders as G
    import pzview_rules as PR
    frag = open(os.path.join(G.OUT, G.NAME + ".frag"), encoding="utf-8").read()
    flat = frag.replace(" ", "")
    k = PR.parse_tail_level(frag)
    if k is None or not 0.35 <= k <= 0.45 or abs(k - G.TAIL_LEVEL) > 1e-6:
        fail("shader: CRV_TAIL %s (gen_shaders.TAIL_LEVEL %s), want 0.35-0.45; regenerate with gen_shaders.py" % (k, G.TAIL_LEVEL))
    pair = {m.group(1) + m.group(2): int(m.group(3)) for m in re.finditer(r"texen2\[(\d)\]\[(\d)\]=\(1\.0-step\(0\.01,length\(texColorMask\.xyz-colZone(\d+)\)\)\);", flat)}
    if (pair.get("03"), pair.get("10"), pair.get("11"), pair.get("12")) != (20, 21, 22, 23):
        fail("shader: texen2 slots of the tail / stop zones moved: %s" % pair)
    mark = re.search(r"const\s+float\s+CRV_MARK\s*=\s*([\d.]+)", frag)
    if not mark or abs(float(mark.group(1)) - PR.COMBINED_MARK) > 1e-9 or not 1.0 / 255 > float(mark.group(1)) > 0.5 / 255:
        fail("shader: CRV_MARK %s, want pzview_rules.COMBINED_MARK %s (between 0.5 and 1 of 255: the tag is 2/255)"
             % (mark and mark.group(1), PR.COMBINED_MARK))
    tag = paint_pass.ZONE["stop_rc"]
    if abs(tag[2] * 255 - 2.0) > 1e-3 or np.linalg.norm(np.subtract(tag, paint_pass.ZONE["stop_r"])) >= R.ZONE_TOL:
        fail("bake_atlas.ZONE stop_rc %s: want stop_r with blue 2/255, inside the 0.01 zone match" % (tag,))
    for line in ("floatcrvMark=step(CRV_MARK,texColorMask.z);",
                 "floatcrvCombR=texen2[1][1]*crvMark;",
                 "floatcrvCombL=texen2[1][2]*crvMark;",
                 "t4en=max(t4en,step(0.5,crvCombR*TextureUninstall2[0][3]+crvCombL*TextureUninstall2[1][0]));",
                 "floatcrvTailZone=clamp(texen2[0][3]+texen2[1][0]+crvCombR+crvCombL,0.0,1.0);",
                 "floatcrvTailOn=step(0.5,(texen2[0][3]+crvCombR)*TextureLightsEnables2[0][3]+(texen2[1][0]+crvCombL)"
                 "*TextureLightsEnables2[1][0])*(1.0-t4en);",
                 "floatcrvBrake=step(0.5,TextureLightsEnables2[1][1]+TextureLightsEnables2[1][2])*(1.0-t4en);",
                 "floatcrvLamp=mix(t1en,max(CRV_TAIL*crvTailOn,crvBrake),crvTailZone);",
                 "col=mix(col,texColorLights.xyz,texColorLights.a*crvLamp);"):
        if line not in flat:
            fail("shader: the combined stop / tail rule lacks %r (run gen_shaders.py)" % line)
    if flat.index("floatt4en=") > flat.index("t4en=max(") or flat.index("t4en=max(") > flat.index("floatcrvBrake="):
        fail("shader: the combined lens's uninstall must join t4en after it is computed and before crvBrake reads it")
    if flat.index("t4en=max(") > flat.index("floatwindowAlpha="):
        fail("shader: t4en must be final before the window / grey terms use it")
    # the rule, replayed: tail zone x (lights, brake) -> factor
    tail = np.array([[0.0, 0.75, 0.0]])
    want = {("tail",): k, ("brake",): 1.0, ("tail", "brake"): 1.0, ("head",): 0.0}
    for groups, w in want.items():
        got = float(PR.lamp_enable(tail, groups, k)[0])
        if abs(got - w) > 1e-9:
            fail("lamp_weights: tail zone with %s lights at %.2f, want %.2f" % (groups, got, w))
    stop = np.array([[0.5, 0.75, 0.0]])
    if float(PR.lamp_enable(stop, ("tail",), k)[0]) != 0.0 or float(PR.lamp_enable(stop, ("brake",), k)[0]) != 1.0:
        fail("lamp_weights: the high stop lamp must light on the brake only")
    for name in ("stop_rc", "stop_lc"):                 # the combined lens's stop part (8-bit, as the PNG holds it)
        c = rgb(name)[None].astype(np.float64) / 255.0
        for groups, w in want.items():
            if abs(float(PR.lamp_enable(c, groups, k)[0]) - w) > 1e-9:
                fail("lamp_terms: %s with %s lights at %.2f, want %.2f" % (name, groups, PR.lamp_enable(c, groups, k)[0], w))
        if float(PR.lamp_enable(c, ("brake",))[0]) != 1.0 or float(PR.lamp_enable(c, ("tail",))[0]) != 0.0:
            fail("lamp_terms: the stock rule (game, Viewpoint) must see %s as the stop zone" % name)
    print("LAMPS shader: tail zones and the tagged stop part at CRV_TAIL %.2f with the lights, full on the brake; "
          "the high stop lamp stock" % k)


def main():
    test_shader_combined_lamp()
    test_synthetic_one_island_seam()
    test_synthetic()
    test_split_lens_unify()
    test_mark_combined()
    test_synthetic_islands()
    test_lens_layout()
    test_compose_wiring()
    test_shipped()
    print("LAMP TESTS OK")


if __name__ == "__main__":
    main()
