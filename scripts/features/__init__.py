r"""
Feature plugins: every CR-V feature (lift conversion, armour, off-road parts, decals, function...) lives
in its own module scripts/features/<key>.py, and the build finds it here. spec/feature-plugins.md is the
contract; scripts/features/_example.py shows every field.

    import features
    for feat in features.load(): ...              # sorted import of scripts/features/*.py (no leading _)

Discovery: every scripts/features/<key>.py whose name does not start with "_", imported in sorted
order. CRV_FEATURES restricts it for a test build: unset = all, "none" = none, "a,b" = only those
(an underscore module such as _example may be named there). features.activate([...]) does the same
from Python (tests).

A feature module must import only the standard library (and pure-Python siblings) at its top level:
the same module is imported by system Python (gen_scripts, compose, build.py, audit) and by Blender
(run_rebuild, bake_atlas, run_export, gen_icons, gen_overlays). bpy / bmesh imports go inside BUILD,
BAKE_PAINT and EXPORT.

Fields (all optional; see FIELDS for one line each and spec/feature-plugins.md for the shapes):
geometry BUILD, OBJECTS, SPACES; bake BAKE_TEXTURED, BAKE_MAT_WEIGHTS, BAKE_PAINT, SWATCH_MATS; textures COMPOSE;
export EXPORT; UI ICONS, OVERLAYS; scripts MODELS, VEHICLE_PARTS, VEHICLE_SCRIPTS, ITEMS, RECIPES;
TRANSLATIONS; LUA, MEDIA; SANDBOX; DISTRIBUTIONS.

With no feature module every merge here returns exactly what it was given: the build's output is
byte-identical to the build without this package (scripts/test_features.py checks it).
"""
import importlib
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))

FIELDS = {
    "BUILD": "callable(report): build the feature's meshes in Blender (run_rebuild, after build_accessories / build_table)",
    "OBJECTS": "{object name: {space, bone, zone, weight, texel_w, file}}: the meshes BUILD makes and how they bake / export",
    "SPACES": "{space: {size, texture, ao_k, gain, grime}}: a texture sheet of the feature's own (static meshes only)",
    "BAKE_TEXTURED": "{material: layer stack} or callable() -> dict: bake_atlas.TEXTURED entries for the feature's materials",
    "BAKE_MAT_WEIGHTS": "{material: texel weight}: bake_atlas.TEXEL_WEIGHT_MAT entries for the feature's materials",
    "BAKE_PAINT": "callable(decal_dir): write painted maps the bake reads (Blender, before any space bakes)",
    # decals feature (2026-10-13): flat-colour materials of shell meshes, each (material, Mask zone) one swatch
    # cell that compose fills with exactly this colour on every skin (planar_uv, compose_textures)
    "SWATCH_MATS": "{material: (r, g, b) sRGB}: exact flat colours on the shell, one swatch cell per (material, zone)",
    # armour fix, 2026-10-13: materials whose shell faces are a few screen pixels wide (bolt heads, mesh
    # strands, weld beads, powder-coated holders): baked like any material but laid as one swatch cell per
    # (object, material, zone) like the core AccSteel, not as padded charts (planar_uv.SWATCH_MATS)
    "BAKE_SWATCH_MATS": "{material} | [material]: the feature's baked materials laid as swatch cells on the shell (planar_uv)",
    "COMPOSE": "callable(report, ctx): extra textures after compose (system Python; ctx out / bake / sheets)",
    "EXPORT": "callable(report, ctx): extra FBX files before the car is exported (Blender, model metres; ctx out / world_items)",
    "ICONS": "{item: (object, azimuth, elevation)}: inventory icons rendered by gen_icons",
    "OVERLAYS": "{part id: {img, draw(sheet, ov), objects}}: the part's mechanics-window cell or framed icon (compose_overlays)",
    "MODELS": "str | [str] | callable(gen) -> str/[str]: model script blocks (module level, tab-indented like gen_scripts)",
    "VEHICLE_PARTS": "str | [str] | callable(gen, vehicle) -> str/[str]: part blocks added to EVERY CR-V vehicle script",
    "VEHICLE_SCRIPTS": "{vehicle name: callable(gen) -> file text}: a whole second vehicle script (the lifted car)",
    # polish feature, 2026-10-13: the vehicle block's own keys (damage / rust textures, the sound block)
    "VEHICLE_KEYS": "{key: value or {key: value}} | callable(gen, vehicle): vehicle-block keys (textureRust, "
                    "textureDamage1Shell..., sound = {engine, horn...}) replacing / added to the stock car's, every CR-V script",
    "ITEMS": "str | [str] | {item: {field: value}} | callable(gen): item script blocks (module Base)",
    "RECIPES": "str | [str] | callable(gen): craftRecipe blocks (module Base), written to scripts/recipes",
    "TRANSLATIONS": "{file: {key: text}}: EN translation entries (IG_UI, ItemName, ContextMenu, Tooltip, Recipes, Sandbox...)",
    "LUA": "[path under 42/media/lua]: the feature's Lua files (tracked in mod/, copied into a CRV_ROOT test build)",
    "MEDIA": "[path under mod/Contents/mods/HondaCRVGen1]: other hand-made files it ships (sound scripts, sounds, icons...)",
    "SANDBOX": "[{name, type, default, min, max, values, label, tooltip}]: sandbox options on the HondaCRVGen1 page",
    "DISTRIBUTIONS": "[{list, item, weight, sandbox}]: procedural loot entries (generated server/Items/HondaCRVGen1_Loot.lua)",
}
CORE_SPACES = ("shell", "interior", "wheel", "engine")
OBJECT_KEYS = {"space", "bone", "zone", "weight", "texel_w", "file"}
SPACE_KEYS = {"size", "texture", "ao_k", "gain", "grime"}
SANDBOX_TYPES = ("integer", "double", "boolean", "enum")
KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")
NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")

_active = None


class FeatureError(Exception):
    """A feature module breaks the contract (spec/feature-plugins.md)."""


def discovered():
    """Every feature key on disk (no leading underscore), sorted."""
    return sorted(f[:-3] for f in os.listdir(HERE)
                  if f.endswith(".py") and not f.startswith("_"))


def _wanted():
    env = os.environ.get("CRV_FEATURES")
    if env is None or env.strip() == "":
        return discovered()
    if env.strip().lower() == "none":
        return []
    return [n.strip() for n in env.split(",") if n.strip()]


def activate(names):
    """Use exactly these feature modules (tests); None goes back to discovery."""
    global _active
    _active = None if names is None else [_import(n) for n in names]
    if _active is not None:
        _validate(_active)
    return _active


def _import(name):
    if not KEY_RE.match(name.lstrip("_")):
        raise FeatureError("feature module name %r: lowercase letters, digits and _ only" % name)
    if not os.path.exists(os.path.join(HERE, name + ".py")):
        raise FeatureError("no feature module scripts/features/%s.py" % name)
    try:
        mod = importlib.import_module(__name__ + "." + name)
    except ImportError as exc:
        raise FeatureError("feature %s does not import outside Blender (%s): keep bpy / bmesh imports inside "
                           "BUILD / BAKE_PAINT / EXPORT" % (name, exc))
    mod.FEATURE = name.lstrip("_")
    return mod


def load():
    """The active feature modules, sorted by name (imported once)."""
    global _active
    if _active is None:
        _active = [_import(n) for n in _wanted()]
        _validate(_active)
    return list(_active)


def keys():
    return [m.FEATURE for m in load()]


# ---------------------------------------------------------------------------------------------
# validation: shapes and collisions, before anything is built from them


def _texts(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        if not all(isinstance(v, str) for v in value):
            raise FeatureError("a block list must hold strings")
        return list(value)
    raise FeatureError("want a string or a list of strings, got %r" % type(value).__name__)


def _validate(mods):
    seen = {}

    def claim(kind, name, feat):
        k = (kind, name)
        if k in seen and seen[k] != feat:
            raise FeatureError("%s %r is declared by both %s and %s" % (kind, name, seen[k], feat))
        seen[k] = feat

    for m in mods:
        f = m.FEATURE
        stems = {k.rstrip("S"): k for k in FIELDS}
        for attr in dir(m):
            if attr.isupper() and attr not in FIELDS and attr.rstrip("S") in stems:
                raise FeatureError("%s: %s is no feature field: did you mean %s?" % (f, attr, stems[attr.rstrip("S")]))
        for hook in ("BUILD", "BAKE_PAINT", "COMPOSE", "EXPORT"):
            if hasattr(m, hook) and not callable(getattr(m, hook)):
                raise FeatureError("%s: %s must be a function" % (f, hook))
        for name, spec in getattr(m, "OBJECTS", {}).items():
            if not isinstance(spec, dict) or set(spec) - OBJECT_KEYS:
                raise FeatureError("%s: OBJECTS[%r] keys are %s" % (f, name, sorted(OBJECT_KEYS)))
            if "space" not in spec:
                raise FeatureError("%s: OBJECTS[%r] needs a space" % (f, name))
            fil = spec.get("file", "body")
            if fil not in ("body", "wheel"):
                raise FeatureError("%s: OBJECTS[%r] file is 'body' or 'wheel'" % (f, name))
            want = "wheel_" if fil == "wheel" else "acc_"
            if not name.startswith(want + f + "_") and not name.startswith(want + f.split("_")[0] + "_"):
                raise FeatureError("%s: object %r must be named %s%s_<thing> (acc_: the bake, backfill and holecheck "
                                   "rules for removable meshes; wheel_: kept out of the car's scans and other sheets' "
                                   "bakes through wheel_objects())" % (f, name, want, f))
            if fil == "wheel" and spec.get("bone"):
                raise FeatureError("%s: wheel-file object %r cannot ride a bone" % (f, name))
            claim("object", name, f)
        for space, spec in getattr(m, "SPACES", {}).items():
            if space in CORE_SPACES:
                raise FeatureError("%s: space %r is a core sheet: put the objects on it with OBJECTS[...]['space']" % (f, space))
            if not isinstance(spec, dict) or set(spec) - SPACE_KEYS or "size" not in spec or "texture" not in spec:
                raise FeatureError("%s: SPACES[%r] needs size and texture (keys %s)" % (f, space, sorted(SPACE_KEYS)))
            claim("space", space, f)
            claim("texture", spec["texture"], f)
        for name, spec in getattr(m, "OBJECTS", {}).items():
            sp = spec["space"]
            if sp not in CORE_SPACES and not any(sp in getattr(o, "SPACES", {}) for o in mods):
                raise FeatureError("%s: OBJECTS[%r] bakes on space %r, which no SPACES declares" % (f, name, sp))
        for mat, rgb in getattr(m, "SWATCH_MATS", {}).items():          # decals feature: exact swatch colours
            if not (isinstance(mat, str) and isinstance(rgb, (tuple, list)) and len(rgb) == 3
                    and all(isinstance(c, int) and 0 <= c <= 255 for c in rgb)):
                raise FeatureError("%s: SWATCH_MATS[%r] is an (r, g, b) sRGB triple of 0-255 ints" % (f, mat))
            claim("swatch material", mat, f)
        bsw = getattr(m, "BAKE_SWATCH_MATS", ())
        if isinstance(bsw, str) or not all(isinstance(x, str) for x in bsw):
            raise FeatureError("%s: BAKE_SWATCH_MATS is a set or list of material names" % f)
        for mat in bsw:
            if mat in getattr(m, "SWATCH_MATS", {}):
                raise FeatureError("%s: %s is both a SWATCH_MATS paint and a BAKE_SWATCH_MATS material" % (f, mat))
            claim("baked swatch material", mat, f)
        for item, spec in getattr(m, "ICONS", {}).items():
            if not (isinstance(spec, (tuple, list)) and len(spec) == 3):
                raise FeatureError("%s: ICONS[%r] is (object, azimuth, elevation)" % (f, item))
            claim("icon", item, f)
        for part, spec in getattr(m, "OVERLAYS", {}).items():
            if not (isinstance(spec, dict) and set(spec) <= {"img", "draw", "objects"} and isinstance(spec.get("img"), str)
                    and callable(spec.get("draw")) and isinstance(spec.get("objects", []), (list, tuple))):
                raise FeatureError("%s: OVERLAYS[%r] is {img: name, draw: fn(sheet, ov) -> frame box or None, "
                                   "objects: [meshes] (optional)}" % (f, part))
            if not part.startswith("CRV"):
                raise FeatureError("%s: overlay part %r is not a CRV* part" % (f, part))
            claim("overlay part", part, f)
            claim("overlay image", spec["img"], f)
        for name in getattr(m, "VEHICLE_SCRIPTS", {}):
            if not NAME_RE.match(name) or not name.startswith("HondaCRVGen1"):
                raise FeatureError("%s: vehicle script %r must be named HondaCRVGen1<Something>" % (f, name))
            claim("vehicle script", name, f)
        items = getattr(m, "ITEMS", None)
        if isinstance(items, dict):
            for name in items:
                if not name.startswith("CRVGen1_"):
                    raise FeatureError("%s: item %r must be named CRVGen1_<Thing>" % (f, name))
                claim("item", name, f)
        for fname, table in getattr(m, "TRANSLATIONS", {}).items():
            if not NAME_RE.match(fname) or not isinstance(table, dict):
                raise FeatureError("%s: TRANSLATIONS[%r] is a {key: text} table for <file>.json" % (f, fname))
            for key in table:
                claim("translation %s" % fname, key, f)
        for path in getattr(m, "LUA", []):
            p = path.replace("\\", "/")
            if p.startswith("/") or ".." in p.split("/") or not p.endswith(".lua") or p.split("/")[0] not in ("client", "server", "shared"):
                raise FeatureError("%s: LUA path %r must be client/..., server/... or shared/... .lua under 42/media/lua" % (f, path))
            claim("lua file", p, f)
        for path in getattr(m, "MEDIA", []):
            p = path.replace("\\", "/")
            if p.startswith("/") or ".." in p.split("/") or p.split("/")[0] not in ("42", "common") or "/media/" not in "/" + p:
                raise FeatureError("%s: MEDIA path %r must be 42/media/... or common/media/... under the mod folder" % (f, path))
            if p.startswith("42/media/lua/"):
                raise FeatureError("%s: MEDIA path %r is Lua: list it in LUA" % (f, path))
            claim("media file", p, f)
        for opt in getattr(m, "SANDBOX", []):
            if not isinstance(opt, dict) or "name" not in opt or opt.get("type") not in SANDBOX_TYPES or "default" not in opt:
                raise FeatureError("%s: SANDBOX entries need name, type (%s) and default" % (f, ", ".join(SANDBOX_TYPES)))
            if not NAME_RE.match(opt["name"]):
                raise FeatureError("%s: sandbox option name %r" % (f, opt["name"]))
            if opt["type"] == "enum" and not opt.get("values"):
                raise FeatureError("%s: enum sandbox option %s needs values" % (f, opt["name"]))
            claim("sandbox option", opt["name"], f)
        for e in getattr(m, "DISTRIBUTIONS", []):
            if not isinstance(e, dict) or not {"list", "item", "weight"} <= set(e):
                raise FeatureError("%s: DISTRIBUTIONS entries need list, item and weight" % f)


# ---------------------------------------------------------------------------------------------
# meshes and the bake


def objects():
    """{object name: spec} over every active feature, specs completed with their defaults:
    space, bone None, zone "body", weight None, texel_w False, file "body", feature."""
    out = {}
    for m in load():
        for name, spec in getattr(m, "OBJECTS", {}).items():
            s = {"bone": None, "zone": "body", "weight": None, "texel_w": False, "file": "body"}
            s.update(spec)
            s["feature"] = m.FEATURE
            out[name] = s
    return out


def new_spaces():
    """{space: spec} of the sheets features add: size, texture (the shipped Vehicles_HondaCRVGen1_<texture>.png),
    ao_k, gain, grime, feature, and objects (the names that bake on it)."""
    out = {}
    for m in load():
        for space, spec in getattr(m, "SPACES", {}).items():
            s = {"ao_k": 0.30, "gain": 1.0, "grime": ((96, 88, 74), 0.0)}
            s.update(spec)
            s["feature"] = m.FEATURE
            s["objects"] = []
            out[space] = s
    for name, spec in objects().items():
        if spec["space"] in out:
            out[spec["space"]]["objects"].append(name)
    return out


def spaces(base):
    """bake_atlas.SPACES with every feature object added to its space's list and every feature sheet
    appended: {space: (names, size)}. base itself is not changed."""
    out = {k: (list(names), size) for k, (names, size) in base.items()}
    for name, spec in objects().items():
        sp = spec["space"]
        if sp in out:
            if name in out[sp][0]:
                raise FeatureError("object %s is already on the %s sheet" % (name, sp))
            out[sp][0].append(name)
    for space, spec in new_spaces().items():
        if space in out:
            raise FeatureError("space %s exists" % space)
        out[space] = (list(spec["objects"]), int(spec["size"]))
    return out


def skin():
    """{object: bone} for rig_vehicle.SKIN."""
    return {n: s["bone"] for n, s in objects().items() if s["bone"]}


def zones():
    """{object: Mask zone} for bake_atlas.zone_of (the zone it dents and greys with)."""
    return {n: s["zone"] for n, s in objects().items()}


def shell_weights():
    """{object: texel weight} for bake_atlas.SHELL_OBJ_WEIGHT (objects on the shell)."""
    return {n: float(s["weight"]) for n, s in objects().items() if s["weight"] is not None and s["space"] == "shell"}


def texel_weights():
    """{object: texel weight} for bake_atlas.TEXEL_WEIGHT_OBJ (objects on any other sheet)."""
    return {n: float(s["weight"]) for n, s in objects().items() if s["weight"] is not None and s["space"] != "shell"}


def texel_attr_objects():
    """Objects whose builder wrote the per-face FLOAT attribute texel_w (build_accessories._texel_weights)."""
    return {n for n, s in objects().items() if s["texel_w"]}


def body_objects():
    """Feature meshes exported into Vehicles_HondaCRVGen1_Body.fbx (export_fbx.ACCESSORIES)."""
    return [n for n, s in objects().items() if s["file"] == "body"]


def wheel_objects():
    """Feature meshes exported into Vehicles_HondaCRVGen1_Wheel.fbx (centred on their own hub)."""
    return [n for n, s in objects().items() if s["file"] == "wheel"]


def plain_shader():
    """Body-file feature meshes drawn with the vehiclewheel shader (any sheet but the shell): export_fbx
    mirrors their first UV layer into the second (export_fbx.PLAIN_SHADER)."""
    return [n for n, s in objects().items() if s["file"] == "body" and s["space"] != "shell"]


def bake_textured():
    out = {}
    for m in load():
        t = getattr(m, "BAKE_TEXTURED", None)
        t = t() if callable(t) else (t or {})
        for mat, layers in t.items():
            if mat in out:
                raise FeatureError("BAKE_TEXTURED material %s is declared twice" % mat)
            out[mat] = layers
    return out


def bake_mat_weights():
    out = {}
    for m in load():
        for mat, w in getattr(m, "BAKE_MAT_WEIGHTS", {}).items():
            if mat in out:
                raise FeatureError("BAKE_MAT_WEIGHTS material %s is declared twice" % mat)
            out[mat] = float(w)
    return out


def swatch_mats():
    """{material: (r, g, b)} of every active feature's SWATCH_MATS (decals feature): planar_uv makes their
    faces swatch cells keyed (material, zone) and compose_textures fills those cells with the colour."""
    out = {}
    for m in load():
        out.update({k: tuple(v) for k, v in getattr(m, "SWATCH_MATS", {}).items()})
    return out


def bake_swatch_mats():
    """Every active feature's BAKE_SWATCH_MATS: materials planar_uv lays as swatch cells on the shell (one per
    object, material and zone, baked like AccSteel's), not as charts of their own."""
    out = set()
    for m in load():
        out.update(getattr(m, "BAKE_SWATCH_MATS", ()))
    return out


def call(hook, *args):
    """Run hook(*args) of every active feature that has it, in order; [(feature, result)]."""
    out = []
    for m in load():
        fn = getattr(m, hook, None)
        if fn is not None:
            out.append((m.FEATURE, fn(*args)))
    return out


def icons():
    out = {}
    for m in load():
        out.update({k: tuple(v) for k, v in getattr(m, "ICONS", {}).items()})
    return out


def overlays():
    """{part id: {img, draw, objects}}: the mechanics-window image of each feature part. compose_overlays
    calls draw(sheet, ov) after drawing the car (ov = compose_overlays itself: px, to_px, sym, mirror,
    chaikin, outline_x, WHEEL_Y, the icon helpers, Sheet.cell / frame_box / leader); it returns the icon
    frame (x0, y0, x1, y1) in sheet px, or None for a cell on the car (its own bounds are the hit box).
    objects (optional): meshes gen_overlays renders top-down so the cell's place is checked (ON_CAR)."""
    out = {}
    for m in load():
        for k, v in getattr(m, "OVERLAYS", {}).items():
            out[k] = {"img": v["img"], "draw": v["draw"], "objects": list(v.get("objects", []))}
    return out


# ---------------------------------------------------------------------------------------------
# scripts, translations, Lua, sandbox, loot (gen_scripts)


def blocks(field, *args):
    """[(feature, text)] of a text field (MODELS, VEHICLE_PARTS, ITEMS in text form, RECIPES): a
    string, a list of strings, or a callable(*args) returning either."""
    out = []
    for m in load():
        v = getattr(m, field, None)
        if v is None or (field == "ITEMS" and isinstance(v, dict)):
            continue
        if callable(v):
            v = v(*args)
        for t in _texts(v):
            out.append((m.FEATURE, t.rstrip("\n")))
    return out


def item_tables():
    """[(feature, item, {field: value})] of the ITEMS given as tables."""
    out = []
    for m in load():
        v = getattr(m, "ITEMS", None)
        if isinstance(v, dict):
            out += [(m.FEATURE, name, dict(fields)) for name, fields in v.items()]
    return out


def vehicle_scripts():
    """{vehicle name: (feature, callable(gen) or text)}."""
    out = {}
    for m in load():
        for name, fn in getattr(m, "VEHICLE_SCRIPTS", {}).items():
            out[name] = (m.FEATURE, fn)
    return out


def vehicle_keys(gen, vehicle):
    """{key: value} of every feature's VEHICLE_KEYS for one vehicle script (polish feature, 2026-10-13): a
    string value is one `key = value,` line, a dict is a block (`sound { engine = ..., }`). gen_scripts
    replaces the stock line of a key it already writes (textureRust) and adds the others after the
    textures. The same key from two features stops the build."""
    out, owner = {}, {}
    for m in load():
        v = getattr(m, "VEHICLE_KEYS", None)
        if v is None:
            continue
        if callable(v):
            v = v(gen, vehicle)
        if not isinstance(v, dict):
            raise FeatureError("%s: VEHICLE_KEYS is a {key: value} table" % m.FEATURE)
        for key, val in v.items():
            if not NAME_RE.match(key) or not (isinstance(val, str) or (isinstance(val, dict) and all(
                    NAME_RE.match(k) and isinstance(x, str) for k, x in val.items()))):
                raise FeatureError("%s: VEHICLE_KEYS[%r] is a string or a {key: string} block" % (m.FEATURE, key))
            if key in owner:
                raise FeatureError("vehicle key %s is set by both %s and %s" % (key, owner[key], m.FEATURE))
            owner[key] = m.FEATURE
            out[key] = val
    return out


def translations():
    """{file: {key: text}} in feature order."""
    out = {}
    for m in load():
        for fname, table in getattr(m, "TRANSLATIONS", {}).items():
            out.setdefault(fname, {}).update(table)
    return out


def lua():
    """[(feature, path under 42/media/lua)]."""
    return [(m.FEATURE, p.replace("\\", "/")) for m in load() for p in getattr(m, "LUA", [])]


def media():
    """[(feature, path under the mod folder mod/Contents/mods/HondaCRVGen1)]: every tracked file a feature
    ships besides its Lua, its LUA files included as 42/media/lua/<path>."""
    out = [(f, "42/media/lua/" + p) for f, p in lua()]
    return out + [(m.FEATURE, p.replace("\\", "/")) for m in load() for p in getattr(m, "MEDIA", [])]


def sandbox():
    """[option dict + feature] in feature order."""
    out = []
    for m in load():
        for opt in getattr(m, "SANDBOX", []):
            o = dict(opt)
            o["feature"] = m.FEATURE
            out.append(o)
    return out


def distributions():
    return [dict(e, feature=m.FEATURE) for m in load() for e in getattr(m, "DISTRIBUTIONS", [])]
