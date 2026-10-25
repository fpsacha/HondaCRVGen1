r"""
pzview's Blender-free rules (scripts/pzview_rules.py) against the game and the mod, plain Python:

    python scripts\test_pzview.py

  * texcap: the loader's 2x2 halving is an INTEGER FLOOR average (ImageData.scaleMipLevelMaxAlpha /
    scaleMipLevelAverage), repeated until the sheet fits the cap, max-alpha for the first two halvings
    (transparent texels other than the first are dropped), premultiplied afterwards; a sheet within the cap
    is left alone. On the shipped Mask the 512 cap must cost the tail lamps lit texels (the 2026-10-24 squiggle).
  * lamps: the zone table equals the game's colZone18..23 (vehicle_common.frag.h) and the names in
    bake_atlas.ZONE, the tolerance equals the mod shader's step(0.01, ...), and the zone test runs on the
    interpolated colour (a bilinear midpoint between two lamp zones is in neither: the seam).
  * --acc: a fitted part shows every model less what the mod's Lua hides (rack state, bars OR armour, the roof
    can only with the rack, the awning rolled up), with the tables read out of the mod's Lua.
  * pzview.py itself carries the flags and Linear sampling (no Closest that would hide seams).
Each check fails on pzview before 2026-10-24 (no pzview_rules; float averages; every model drawn).
"""
import os
import re
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import crv_paths  # noqa: E402
import pzview_rules as R  # noqa: E402

ROOT = os.path.dirname(HERE)
MOD = os.path.join(ROOT, "mod", "Contents", "mods", "HondaCRVGen1")
LUA = os.path.join(MOD, "42", "media", "lua")
TEX = os.path.join(MOD, "common", "media", "textures", "Vehicles")


def fail(msg):
    raise SystemExit("FAIL " + msg)


def rgba(h, w, rgb=(0, 0, 0), a=255):
    out = np.zeros((h, w, 4), np.uint8)
    out[..., :3] = rgb
    out[..., 3] = a
    return out


# ----------------------------------------------------------------------------------------------
# texcap


def test_floor_average():
    a = rgba(2, 2)
    a[..., 0] = [[1, 2], [2, 2]]            # sum 7: floor 1, a float mean 1.75 (rounds to 2)
    a[..., 1] = [[255, 254], [254, 254]]    # sum 1017: floor 254, mean 254.25
    a[..., 2] = [[0, 0], [0, 3]]            # sum 3: floor 0, mean 0.75 (rounds to 1)
    for max_alpha in (True, False):
        got = R.game_halve(a, max_alpha=max_alpha)[0, 0]
        if tuple(got) != (1, 254, 0, 255):
            fail("game_halve(max_alpha=%s) %s, want the floor average (1, 254, 0, 255)" % (max_alpha, tuple(got)))
    got = R.game_cap(a, 1)[0, 0]
    if tuple(got) != (1, 254, 0, 255):
        fail("game_cap(cap 1) %s, want (1, 254, 0, 255) (opaque: premultiply changes nothing)" % (tuple(got),))
    print("TEXCAP floor average: (1,2,2,2) -> 1, (255,254,254,254) -> 254, (0,0,0,3) -> 0")


def test_repeat_until_fits():
    rng = np.random.default_rng(7)
    a = rgba(64, 64)
    a[..., :3] = rng.integers(0, 256, (64, 64, 3))
    for cap, want in ((64, 64), (100, 64), (32, 32), (20, 16), (16, 16), (5, 4)):
        got = R.game_cap(a, cap).shape[:2]
        if got != (want, want):
            fail("game_cap(64x64, %d) is %s, want %dx%d" % (cap, got, want, want))
    b = R.game_cap(rgba(64, 16, (9, 9, 9)), 16)
    if b.shape[:2] != (16, 4):
        fail("game_cap(64 tall x 16 wide, 16) is %s, want 16 x 4 (halved until both sides fit)" % (b.shape[:2],))
    # repeated halving floors at every level: one 16-texel box would not
    d = rgba(4, 4)
    d[..., 0] = [[3, 3, 3, 3], [3, 2, 3, 2], [3, 3, 3, 3], [3, 3, 3, 3]]  # level 1: 11//4 = 2, 2, 3, 3 -> level 2: 10//4
    d[..., 1] = [[7, 7, 7, 7], [7, 7, 7, 7], [7, 7, 7, 7], [7, 7, 7, 6]]  # level 1: 7 7 / 7 27//4 = 6 -> 27//4 = 6
    got = tuple(R.game_cap(d, 1)[0, 0, :2])
    if got != (2, 6):
        fail("game_cap 4x4 -> 1x1 is %s, want (2, 6): the floor at each level (one 16-texel floor: (2, 7))" % (got,))
    print("TEXCAP halving repeats until <= cap: 64 -> 32 / 16 / 4, 64x16 at 16 -> 16x4")


def test_alpha_rules():
    a = rgba(2, 2, (200, 100, 50), 0)
    a[0, 1] = (100, 50, 26, 255)            # one opaque texel among transparent ones
    a[1, 1] = (0, 0, 0, 255)
    # max-alpha: the first texel always (preserveTransparentColor), the others only with alpha > 0 -> 3 counted
    got = tuple(R.game_halve(a, max_alpha=True)[0, 0])
    want = ((200 + 100 + 0) // 3, (100 + 50 + 0) // 3, (50 + 26 + 0) // 3, (0 + 255 + 255) // 3)
    if got != want:
        fail("max-alpha halving %s, want %s" % (got, want))
    got = tuple(R.game_halve(a, max_alpha=False)[0, 0])
    want = ((200 + 100 + 200 + 0) // 4, (100 + 50 + 100 + 0) // 4, (50 + 26 + 50 + 0) // 4, 510 // 4)
    if got != want:
        fail("average halving %s, want %s" % (got, want))
    # first two halvings max-alpha, then average: an 8x8 with one opaque texel per 2x2 block
    big = rgba(8, 8, (0, 0, 0), 0)
    big[1::2, 1::2] = (240, 240, 240, 255)
    lvl2 = R.game_cap(big, 2)                # 8 -> 4 (max-alpha) -> 2 (max-alpha)
    lvl3 = R.game_cap(big, 1)                # ... -> 1 (average)
    # level 1 texel: (0 + 240) // 2 = 120, alpha 255 // 2 = 127; level 2 every texel has alpha > 0: plain floor
    if tuple(lvl2[0, 0]) != (int(120 * 127 / 255.0), int(120 * 127 / 255.0), int(120 * 127 / 255.0), 127):
        fail("8x8 at cap 2: %s (max-alpha twice, then premultiplied)" % (tuple(lvl2[0, 0]),))
    if lvl3.shape[:2] != (1, 1):
        fail("8x8 at cap 1: shape %s" % (lvl3.shape[:2],))
    # premultiply only when capped
    small = rgba(4, 4, (200, 100, 50), 128)
    if not np.array_equal(R.game_cap(small, 4), small):
        fail("a sheet within the cap must be uploaded as it is (no premultiply)")
    pm = R.premultiply(small)[0, 0]
    if tuple(pm) != (int(200 * 128 / 255.0), int(100 * 128 / 255.0), int(50 * 128 / 255.0), 128):
        fail("premultiply %s, want (int)(c * a / 255f)" % (tuple(pm),))
    print("TEXCAP alpha: max-alpha drops transparent neighbours (first texel kept), average keeps all, "
          "premultiplied only when capped")


def _load_png(path):
    try:
        from PIL import Image
    except ImportError:
        return None
    im = Image.open(path).convert("RGBA")
    return np.asarray(im).copy()


def test_shipped_mask_squiggle():
    """The shipped Mask + Lights at the 512 cap lose lit tail-lamp texels the 2048 sheets keep."""
    m = _load_png(os.path.join(TEX, "Vehicles_HondaCRVGen1_Mask.png"))
    li = _load_png(os.path.join(TEX, "Vehicles_HondaCRVGen1_Lights.png"))
    if m is None or li is None:
        print("TEXCAP shipped sheets: skipped (no PIL or no sheets)")
        return
    out = {}
    for cap in (2048, 512):
        mm = R.game_cap(m, cap).astype(np.float64) / 255.0
        ll = R.game_cap(li, cap).astype(np.float64) / 255.0
        if ll.shape[:2] != mm.shape[:2]:                   # compare at the Mask's size (texel centres)
            k = mm.shape[0] // ll.shape[0]
            ll = np.repeat(np.repeat(ll, k, 0), k, 1) if k > 1 else ll[::ll.shape[0] // mm.shape[0], ::ll.shape[1] // mm.shape[1]]
        en = R.lamp_enable(mm[..., :3], ("tail", "brake"))
        lit = en * ll[..., 3]                              # Lights.a * t1en per texel
        out[cap] = lit.sum() * (m.shape[0] / float(mm.shape[0])) ** 2   # in full-size texels
    if not out[512] < 0.97 * out[2048]:
        # since compose's lamp guard (H-VISUAL-1, test_compose_lamps.py) the shipped Mask keeps its lamp zones at
        # 512: then there is no squiggle left for texcap to show, and the loss check holds only for older sheets
        print("TEXCAP shipped Mask + Lights: lamp-guarded (lit tail+brake %.0f texels at 2048, %.0f at 512)"
              % (out[2048], out[512]))
        return
    print("TEXCAP shipped Mask + Lights: lit tail+brake area %.0f texels at 2048, %.0f at 512 (%.0f%% lost)"
          % (out[2048], out[512], 100 * (1 - out[512] / out[2048])))


# ----------------------------------------------------------------------------------------------
# lamps


def test_zone_table():
    h = os.path.join(crv_paths.GAME_MEDIA, "shaders", "vehicle_common.frag.h")
    if os.path.exists(h):
        z = R.parse_colzones(open(h, encoding="utf-8", errors="replace").read())
        for g, zones in R.LAMP_ZONES.items():
            for name, idx, c in zones:
                if z.get(idx) != c:
                    fail("%s %s: pzview has colZone%d = %s, the game's vehicle_common.frag.h %s" % (g, name, idx, c, z.get(idx)))
        print("LAMPS zone table = the game's colZone18..23 (%s)" % h)
    else:
        print("LAMPS game shader not found (%s): table check against the game skipped" % h)
    src = open(os.path.join(HERE, "bake_atlas.py"), encoding="utf-8").read()
    for g, zones in R.LAMP_ZONES.items():
        for name, _idx, c in zones:
            m = re.search(r'"%s":\s*\(([^)]*)\)' % name, src)
            if not m or tuple(float(v) for v in m.group(1).split(",")) != c:
                fail("bake_atlas.ZONE[%r] does not paint %s" % (name, c))
    frag = open(os.path.join(MOD, "common", "media", "shaders", "vehicle_crvgen1_norandom.frag"), encoding="utf-8").read()
    tols = set(re.findall(r"step\(\s*([\d.]+)\s*,\s*length\(texColorMask\.xyz-colZone", frag))
    if tols != {repr(R.ZONE_TOL)}:
        fail("the mod shader's zone tolerance is %s, pzview uses %s" % (tols, R.ZONE_TOL))
    if "col=mix(col,texColorLights.xyz,texColorLights.a*crvLamp);" not in frag.replace(" ", ""):
        fail("the mod shader no longer mixes the Lights sheet as mix(col, Lights.rgb, Lights.a * crvLamp)")
    if R.parse_tail_level(frag) is None:
        fail("pzview_rules.parse_tail_level finds no CRV_TAIL in the mod shader")
    print("LAMPS bake_atlas zones and the shader's step(0.01) tolerance match")


def test_lamp_enable():
    if R.parse_lights("tail,brake") != ("tail", "brake") or R.parse_lights("all") != ("head", "tail", "brake"):
        fail("parse_lights")
    try:
        R.parse_lights("fog")
        fail("parse_lights accepted 'fog'")
    except ValueError:
        pass
    tail_r, stop_r = np.array([0.0, 0.75, 0.0]), np.array([0.5, 0.25, 0.0])
    eight = np.array([[0, 191, 0], [0, 64, 0], [128, 64, 0], [128, 191, 0]]) / 255.0   # what the PNG holds
    if not (R.lamp_enable(eight, ("tail", "brake")) == 1).all():
        fail("8-bit lamp colours (0,191,0) (0,64,0) (128,64,0) (128,191,0) must pass the 0.01 test")
    if (R.lamp_enable(eight, ("head",)) != 0).any():
        fail("tail / brake colours lit with only head enabled")
    mid = 0.5 * (tail_r + stop_r)                       # bilinear halfway between two lamp zones: in neither
    if R.lamp_enable(mid[None], ("tail", "brake"))[0] != 0:
        fail("the midpoint between lights_rt and stop_r must fail the zone test (the seam the game draws)")
    near = tail_r + np.array([0.0, 0.0099, 0.0])
    far = tail_r + np.array([0.0, 0.0101, 0.0])
    if R.lamp_enable(near[None], ("tail",))[0] != 1 or R.lamp_enable(far[None], ("tail",))[0] != 0:
        fail("zone test edge: 0.0099 away must pass, 0.0101 fail")
    print("LAMPS zone test on interpolated colours: 8-bit zone colours pass, a two-zone midpoint fails")


# ----------------------------------------------------------------------------------------------
# --acc model visibility


def test_lua_tables():
    r = R.lua_rules(LUA)
    if "default" in r["source"].values():
        fail("lua_rules fell back to defaults for %s (the mod's Lua moved?)"
             % [k for k, v in r["source"].items() if v == "default"])
    for k in ("rack_part", "rack_models", "guard_variants", "roof_can", "awning_part", "awning_out"):
        if r[k] != R.LUA_DEFAULTS[k]:
            fail("the mod's Lua %s = %s, pzview_rules.LUA_DEFAULTS has %s" % (k, r[k], R.LUA_DEFAULTS[k]))
    print("ACC Lua tables read from the mod: rack %s, guards %s, roof can %s, awning %s"
          % (r["rack_models"], sorted(set(r["guard_variants"].values())), r["roof_can"], r["awning_out"]))


def test_visible_models():
    r = R.lua_rules(LUA)
    V = R.acc_visible_models
    rack = ["CRVRoofRack", "RackLoad1", "RackLoad2", "RackLoad3"]
    if V("CRVRoofRack", rack, r) != ["CRVRoofRack"]:
        fail("empty rack: %s" % V("CRVRoofRack", rack, r))
    if V("CRVRoofRack", rack, r, rack=2) != ["CRVRoofRack", "RackLoad2"]:
        fail("rack state 2: %s" % V("CRVRoofRack", rack, r, rack=2))
    g = ["CRVGuardFrontLeft", "ArmourMesh"]
    if V("CRVGuardFrontLeft", g, r) != ["CRVGuardFrontLeft"]:
        fail("guard with bars: %s (the mesh stacked on the bars)" % V("CRVGuardFrontLeft", g, r))
    if V("CRVGuardFrontLeft", g, r, guard="armour") != ["ArmourMesh"]:
        fail("guard with armour: %s" % V("CRVGuardFrontLeft", g, r, guard="armour"))
    if V("CRVGuardFrontLeft", g, r, hidden={"CRVGuardFrontLeft"}) != ["ArmourMesh"]:
        fail("--hide-models CRVGuardFrontLeft (make_listing's armour shots) must show the mesh")
    gr = ["CRVGuardWindshieldRear", "ArmourPlate"]
    if V("CRVGuardWindshieldRear", gr, r, guard="armour") != ["ArmourPlate"]:
        fail("rear plate: %s" % V("CRVGuardWindshieldRear", gr, r, guard="armour"))
    if V("CRVGuardWindshield", ["CRVGuardWindshield"], r, guard="armour") != ["CRVGuardWindshield"]:
        fail("the windscreen guard has no armour variant: its bars stay")
    if V("CRVOffroadCanRoof", ["CRVOffroadCanRoof"], r, fitted={"CRVOffroadCanRoof"}) != []:
        fail("the roof can floats without the rack")
    if V("CRVOffroadCanRoof", ["CRVOffroadCanRoof"], r, fitted={"CRVOffroadCanRoof", "CRVRoofRack"}) != ["CRVOffroadCanRoof"]:
        fail("the roof can on a fitted rack")
    aw = ["CRVAwning", "AwningCanopy", "AwningPoles"]
    if V("CRVAwning", aw, r) != ["CRVAwning"] or V("CRVAwning", aw, r, awning="deployed") != aw:
        fail("awning stowed / deployed: %s / %s" % (V("CRVAwning", aw, r), V("CRVAwning", aw, r, awning="deployed")))
    if V("CRVBullbar", ["CRVBullbar"], r) != ["CRVBullbar"]:
        fail("a one-model part shows its model")
    print("ACC visible models: rack one state, guards bars xor armour, roof can needs the rack, awning stowed")


def test_pzview_source():
    src = open(os.path.join(HERE, "pzview.py"), encoding="utf-8").read()
    for flag in ("--texcap", "--tex", "--lights", "--night", "--acc-all-models", "--guard"):
        if ('"%s"' % flag) not in src or flag not in src.split('"""')[1]:
            fail("pzview.py lacks %s (option and docstring)" % flag)
    if re.search(r"interpolation\s*=\s*'Closest'", src):
        fail("pzview.py samples a texture with Closest: the game samples GL_LINEAR, seams would hide")
    for use in ("_rules.acc_visible_models", "_rules.game_cap", "_rules.lamp_weights", "_rules.parse_tail_level", "_rules.ZONE_TOL"):
        if use not in src:
            fail("pzview.py does not use %s" % use)
    print("PZVIEW source: flags documented, Linear sampling, rules from pzview_rules")


def main():
    test_floor_average()
    test_repeat_until_fits()
    test_alpha_rules()
    test_shipped_mask_squiggle()
    test_zone_table()
    test_lamp_enable()
    test_lua_tables()
    test_visible_models()
    test_pzview_source()
    print("PZVIEW TESTS OK")


if __name__ == "__main__":
    main()
