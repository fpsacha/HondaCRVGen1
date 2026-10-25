r"""
The game rules pzview replays that need no Blender: which models of a part the game shows (--acc), how the
loader shrinks a texture under the Vehicle Texture Size option (--texcap), and the lamp zones of the vehicle
shader (--lights). Plain Python + numpy, so scripts/test_pzview.py checks them without Blender.

Sources (projectzomboid.jar B42, read with javap 2026-10-24; the mod's own Lua):
  * VehiclePart.setInventoryItem(item) calls setAllModelsVisible(item != null) when the part script's
    setAllModelsVisible is true (the default): every model of a fitted part shows, nothing chooses a
    "first" one. Only Lua narrows it (VehiclePart.setModelVisible): the mod's roof rack shows one cargo
    state (HondaCRVGen1Accessories.lua Acc.showRack), a window guard shows the bars OR the armour of the
    installed item (HondaCRVGen1_Armour.lua Armour.showGuard), the roof jerry can shows only on a fitted
    rack (HondaCRVGen1_Offroad.lua showRoofCan), the awning's canopy and poles only rolled out
    (HondaCRVGen1_Awning.lua). acc_visible_models() replays those, reading the tables out of the Lua.
  * TextureID.limitMaxSize: a sheet wider or taller than the cap is replaced by the first mip level that
    fits (ImageData.getMipMapData), with preserveTransparentColor = true. generateMipMaps builds each level
    from the one above: levels 1 and 2 (the first two halvings) with scaleMipLevelMaxAlpha, deeper ones
    with scaleMipLevelAverage, then performPreMultipliedAlpha on every level. game_cap() does the same.
    A sheet already within the cap is uploaded as it is (no premultiply).
  * vehicle_common.frag.h colZone18..23: the lamp zones the Mask marks; the shader's t1en is 1 where the
    (bilinearly sampled) Mask colour lies within 0.01 (RGB length) of an enabled zone colour.
"""
import os
import re

import numpy as np

# ----------------------------------------------------------------------------------------------
# lamp zones (vehicle_common.frag.h; scripts/bake_atlas.py names them the same)

LAMP_ZONES = {
    "head": (("lights_rh", 18, (0.25, 0.0, 0.0)), ("lights_lh", 19, (0.75, 0.0, 0.0))),
    "tail": (("lights_rt", 20, (0.0, 0.75, 0.0)), ("lights_lt", 21, (0.0, 0.25, 0.0))),
    "brake": (("stop_r", 22, (0.5, 0.25, 0.0)), ("stop_l", 23, (0.5, 0.75, 0.0))),
}
ZONE_TOL = 0.01          # 1.0 - step(0.01, length(mask.rgb - colZone)): strictly closer than 0.01


def parse_colzones(text):
    """{index: (r, g, b)} from a shader's `const vec3 colZoneN = vec3(r, g, b);` lines."""
    out = {}
    for m in re.finditer(r"colZone(\d+)\s*=\s*vec3\(\s*([-\d.]+)\s*,\s*([-\d.]+)\s*,\s*([-\d.]+)\s*\)", text):
        out[int(m.group(1))] = (float(m.group(2)), float(m.group(3)), float(m.group(4)))
    return out


def parse_lights(spec):
    """'head,tail,brake' (any subset, 'all' = every one) -> a tuple of group names; raises ValueError."""
    groups = []
    for tok in filter(None, (t.strip().lower() for t in str(spec).split(","))):
        if tok == "all":
            groups += [g for g in LAMP_ZONES if g not in groups]
        elif tok in LAMP_ZONES:
            if tok not in groups:
                groups.append(tok)
        else:
            raise ValueError("--lights: %r is not one of %s (or all)" % (tok, ", ".join(LAMP_ZONES)))
    return tuple(groups)


def lamp_colours(groups):
    """The Mask colours of the enabled lamp groups."""
    return [c for g in groups for (_n, _i, c) in LAMP_ZONES[g]]


def parse_tail_level(frag_text):
    """CRV_TAIL from the mod's fragment shader (gen_shaders.TAIL_LEVEL: the combined stop / tail lens), None for a
    shader without it (the stock rule: a tail zone lights fully with the tail lights, never on the brake)."""
    m = re.search(r"const\s+float\s+CRV_TAIL\s*=\s*([\d.]+)", frag_text or "")
    return float(m.group(1)) if m else None


COMBINED_MARK = 0.0039   # gen_shaders CRV_MARK: a stop zone with Mask blue >= this is the combined lens's stop part


def lamp_terms(groups, tail_level=None):
    """[(zone colour, lamp factor, marked)] for the enabled groups: the shader's per-zone factor that multiplies
    Lights.a; marked True: the term needs Mask blue >= COMBINED_MARK as well. Stock (tail_level None): 1 for
    every zone of an enabled group. With the mod's combined stop / tail rule (gen_shaders LAMP_RULE): a tail zone,
    and a stop zone with the combined tag (the D-pillar lens's stop part, bug wave 3), give max(tail_level if
    tail, 1 if brake); head and plain stop zones as stock."""
    combined = max(tail_level if "tail" in groups else 0.0, 1.0 if "brake" in groups else 0.0) if tail_level is not None else 0.0
    out = []
    for g, zones in LAMP_ZONES.items():
        for _n, _i, c in zones:
            w = combined if g == "tail" and tail_level is not None else 1.0 if g in groups else 0.0
            if w > 0.0:
                out.append((c, w, False))
            if g == "brake" and combined > 0.0:
                out.append((c, combined, True))
    return out


def lamp_weights(groups, tail_level=None):
    """[(zone colour, lamp factor)] of lamp_terms without the combined stop terms (a plain zone match)."""
    return [(c, w) for c, w, marked in lamp_terms(groups, tail_level) if not marked]


def lamp_enable(mask_rgb, groups, tail_level=None):
    """The lamp factor per texel / fragment (t1en, or crvLamp with tail_level): the largest weight of the terms
    whose zone mask_rgb (..., 3 floats 0..1) lies within ZONE_TOL of (and, for a marked term, whose blue is >=
    COMBINED_MARK), 0 for none. The reference for pzview.lamp_material."""
    m = np.asarray(mask_rgb, dtype=np.float64)
    on = np.zeros(m.shape[:-1], dtype=np.float64)
    for c, w, marked in lamp_terms(groups, tail_level):
        hit = np.linalg.norm(m - np.array(c), axis=-1) < ZONE_TOL
        if marked:
            hit &= m[..., 2] >= COMBINED_MARK
        on = np.maximum(on, w * hit)
    return on


# ----------------------------------------------------------------------------------------------
# the loader's size cap (TextureID.limitMaxSize, ImageData.generateMipMaps)


def next_mip(n):
    """ImageData.getNextMipDimension."""
    return n >> 1 if n > 1 else n


def game_halve(a, max_alpha, preserve_transparent=True):
    """One mip level from the one above, as ImageData does it. a: (h, w, 4) uint8, rows as stored.
    Output texel (x, y) reads the 2x2 block at (2x, 2y), (2x+1, 2y), (2x, 2y+1), (2x+1, 2y+1); sums each
    channel over the texels it takes and divides by their count with Java int division (floor: all >= 0).
      max_alpha (scaleMipLevelMaxAlpha, levels 1-2): the first texel counts when preserveTransparentColor
        (TextureID.limitMaxSize sets it) or its alpha > 0; the other three only with alpha > 0 and inside
        the image; none counted -> (0, 0, 0, 0).
      average (scaleMipLevelAverage, deeper levels): the first texel always (clamped), the others whenever
        inside the image (getPixelDiscard discards nothing but out-of-range texels)."""
    a = np.asarray(a)
    if a.ndim != 3 or a.shape[2] != 4:
        raise ValueError("game_halve wants (h, w, 4) RGBA, got %s" % (a.shape,))
    h, w = a.shape[:2]
    nh, nw = next_mip(h), next_mip(w)
    src = a.astype(np.int64)
    ys, xs = np.arange(nh) * 2, np.arange(nw) * 2
    total = np.zeros((nh, nw, 4), dtype=np.int64)
    count = np.zeros((nh, nw), dtype=np.int64)
    for k, (dx, dy) in enumerate(((0, 0), (1, 0), (0, 1), (1, 1))):
        yy, xx = ys + dy, xs + dx
        inside = (yy < h)[:, None] & (xx < w)[None, :]
        px = src[np.clip(yy, 0, h - 1)][:, np.clip(xx, 0, w - 1)]
        if k == 0:
            take = np.ones((nh, nw), dtype=bool)          # getPixelClamped: always read
            if max_alpha and not preserve_transparent:
                take = px[..., 3] > 0
        else:
            take = inside & (px[..., 3] > 0) if max_alpha else inside
        total += px * take[..., None]
        count += take
    out = np.where(count[..., None] > 0, total // np.maximum(count, 1)[..., None], 0)
    return out.astype(np.uint8)


def premultiply(a):
    """ImageData.performPreMultipliedAlpha: rgb = (int)((float)(rgb * a) / 255f), alpha kept."""
    a = np.asarray(a)
    out = a.copy()
    alpha = a[..., 3].astype(np.float32)
    for c in range(3):
        out[..., c] = (a[..., c].astype(np.float32) * alpha / np.float32(255.0)).astype(np.int64).astype(np.uint8)
    return out


def game_cap(a, cap):
    """The sheet the game uploads under a texture size cap: (h, w, 4) uint8 in, (h', w', 4) uint8 out.
    Within the cap (or cap <= 0): unchanged. Otherwise repeated game_halve (the first two halvings
    max-alpha, then average) until both sides fit, then premultiplied."""
    a = np.asarray(a)
    if a.ndim == 3 and a.shape[2] == 3:
        a = np.concatenate([a, np.full(a.shape[:2] + (1,), 255, dtype=a.dtype)], axis=2)
    if not cap or cap <= 0 or (a.shape[0] <= cap and a.shape[1] <= cap):
        return a
    level, cur = 0, a.astype(np.uint8)
    while cur.shape[0] > cap or cur.shape[1] > cap:
        if cur.shape[0] <= 1 and cur.shape[1] <= 1:
            break
        cur = game_halve(cur, max_alpha=level < 2)
        level += 1
    return premultiply(cur)


# ----------------------------------------------------------------------------------------------
# which models of a fitted part the game shows (--acc)

# what the mod's Lua holds, used when its files cannot be read (a copy of pzview run on its own)
LUA_DEFAULTS = {
    "rack_part": "CRVRoofRack",
    "rack_models": ["RackLoad1", "RackLoad2", "RackLoad3"],
    "guard_variants": {"CRVGuardFrontLeft": "ArmourMesh", "CRVGuardFrontRight": "ArmourMesh",
                       "CRVGuardRearLeft": "ArmourMesh", "CRVGuardRearRight": "ArmourMesh",
                       "CRVGuardWindshieldRear": "ArmourPlate"},
    "roof_can": "CRVOffroadCanRoof",
    "awning_part": "CRVAwning",
    "awning_out": ["AwningCanopy", "AwningPoles"],
}


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def lua_rules(lua_dir):
    """The visibility tables out of the mod's Lua under lua_dir (42/media/lua); LUA_DEFAULTS for any it
    cannot find. Returns a dict shaped like LUA_DEFAULTS plus 'source': {key: file or 'default'}."""
    r = {k: (list(v) if isinstance(v, list) else dict(v) if isinstance(v, dict) else v) for k, v in LUA_DEFAULTS.items()}
    src = {k: "default" for k in LUA_DEFAULTS}
    acc = _read(os.path.join(lua_dir, "server", "Vehicles", "HondaCRVGen1Accessories.lua"))
    if acc:
        m = re.search(r'Acc\.RACK_PART\s*=\s*"(\w+)"', acc)
        if m:
            r["rack_part"], src["rack_part"] = m.group(1), "HondaCRVGen1Accessories.lua"
        m = re.search(r"Acc\.RACK_MODELS\s*=\s*\{([^}]*)\}", acc)
        if m:
            r["rack_models"], src["rack_models"] = re.findall(r'"(\w+)"', m.group(1)), "HondaCRVGen1Accessories.lua"
    arm = _read(os.path.join(lua_dir, "shared", "HondaCRVGen1_Armour.lua"))
    if arm:
        m = re.search(r"Armour\.VARIANTS\s*=\s*\{(.*?)\n\}", arm, re.S)
        if m:
            v = {}
            for pm in re.finditer(r'(\w+)\s*=\s*\{\s*\[\s*"[\w.]+"\s*\]\s*=\s*"(\w+)"', m.group(1)):
                v[pm.group(1)] = pm.group(2)
            if v:
                r["guard_variants"], src["guard_variants"] = v, "HondaCRVGen1_Armour.lua"
    off = _read(os.path.join(lua_dir, "server", "Vehicles", "HondaCRVGen1_Offroad.lua"))
    if off:
        m = re.search(r'Offroad\.ROOF_CAN\s*=\s*"(\w+)"', off)
        if m:
            r["roof_can"], src["roof_can"] = m.group(1), "HondaCRVGen1_Offroad.lua"
    awn = _read(os.path.join(lua_dir, "shared", "HondaCRVGen1_Awning.lua"))
    if awn:
        m = re.search(r"Awning\.MODELS\s*=\s*\{([^}]*)\}", awn)
        if m:
            r["awning_out"], src["awning_out"] = re.findall(r'"(\w+)"', m.group(1)), "HondaCRVGen1_Awning.lua"
        m = re.search(r'Awning\.PART\s*=\s*"(\w+)"', awn)
        if m:
            r["awning_part"], src["awning_part"] = m.group(1), "HondaCRVGen1_Awning.lua"
    r["source"] = src
    return r


def acc_visible_models(part, model_ids, rules, fitted=(), rack=0, guard="bars", awning=None, hidden=()):
    """The model ids of a FITTED accessory part the game shows: all of them (setAllModelsVisible), less
    what the mod's Lua hides for this state.
      rules   lua_rules() / LUA_DEFAULTS
      fitted  the accessory parts fitted on the car (the roof can shows only with the rack among them)
      rack    the roof rack's cargo state, 0 = the empty basket, N = rules['rack_models'][N-1] shown
      guard   'bars' (what spawns) or 'armour' (the mesh / plate item): a guard part shows its own model
              (the bars) or its variant, never both; `hidden` naming the bars' model also means armour
              (pzview's older --hide-models CRVGuard... calls)
      awning  'deployed' shows the canopy and poles, anything else rolls them up
      hidden  --hide-models: ids drawn by nobody"""
    ids = list(model_ids)
    shown = [m for m in ids if m not in hidden]
    if part == rules["rack_part"]:
        loads = rules["rack_models"]
        want = loads[rack - 1] if 1 <= rack <= len(loads) else None
        shown = [m for m in shown if m not in loads or m == want]
    variant = rules["guard_variants"].get(part)
    if variant is not None:
        armour = guard == "armour" or part in hidden
        want = variant if armour else part
        shown = [m for m in shown if m not in (part, variant) or m == want]
    if part == rules["roof_can"] and rules["rack_part"] not in set(fitted):
        shown = []
    if part == rules["awning_part"] and awning != "deployed":
        shown = [m for m in shown if m not in rules["awning_out"]]
    return shown
