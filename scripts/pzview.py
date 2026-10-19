r"""
Game-faithful check renders: assemble the car from the SHIPPED files the way Project Zomboid does,
and render it with the game's culling from the game's camera.

    blender -b --factory-startup --python scripts/pzview.py -- [--out DIR] [--mod DIR]
            [--poses shut,open] [--az 0,45,...] [--scale 6.5] [--close] [--eye] [--res 1400]
            [--acc [--acc-parts CRVSpareCover,...]] [--rack N] [--decal retro_blue,script_white,...]
            [--gz 150] [--cap 512] [--script HondaCRVGen1LiftAlloy] [--folded]
            [--frac 0.15] [--eyes FILE.json] [--probe view,px,py [--probe-all]] [--bay full|low]
Poses: shut, open, left, right, front, gate, hood, fl / fr / rl / rr (one door), win / win_fl.. (windows
down), joined with '+' (left+win); --frac F poses every opening clip at F of its travel. --eye adds the
eye-level ring, the 'low' and crouch rings, the seats and (with --folded) the cargo bed; --eyes FILE.json
replaces them with a list [[name, pose, [lx,ly,lz], [tx,ty,tz], fov], ...] (metres above ground).

Texture sampling (2026-10-12, projectzomboid.jar B42): the game never mipmaps model textures
(ModelManager.setModelMetaData sets no TextureFlags.MIPMAPS, so TextureID uses GL_LINEAR for both
filters) and uploads a box-downscaled level until the sheet fits the player's option: Vehicle
Texture Size (engine default 512) for models whose shader name starts with "vehicle", Texture
Size (default 256) for every other shader. So: textures sample Linear here, --cap N scales every
texture down to N first (run 512 to see what most players get), and --gz PX_PER_M also saves each
view resampled to a game density (<tag>_gz.png; the author plays at ~326 px/m, playbook). Judge texture
at the _gz files, never at the 1400 px render (215 px/m).

Why this exists: every failed in-game round came from checking renders of the working .blend, which
is not what the game draws. This tool reads only what ships:
  * the vehicle script (mod/.../scripts/vehicles/*.txt): which model each part draws, its file,
    offset, rotate, scale, invertX, texture, and the anim clip each part plays;
  * the FBX files the script points at, re-imported (so export mistakes show);
  * the textures the script names.
Rules taken from the game's bytecode (projectzomboid.jar, B42, 2026-10):
  * Model.DrawVehicle always enables GL_CULL_FACE (a model script's `cullFace` is ignored on the
    vehicle path) and culls GL_FRONT, or GL_BACK when the model is invertX: the authored outward
    faces are drawn either way, the backs never. Blender's culling does the same for negative scale.
  * BaseVehicle.updateTransform: part models get TRS(-offset.x, offset.y, offset.z,
    rotationXYZ(rx, -ry, -rz) [degrees], scale * invertX); WHEEL models get rotationXYZ(rx, ry, rz)
    (no sign flip) at the wheel's position, then steering and spin. Nothing mirrors a wheel unless
    its model is invertX.
  * BaseVehicle.playPartAnim plays a part's clip on its FIRST model's AnimationPlayer only
    (getModelInfoForPart), masked by that model script's `boneWeight` list (no list = every bone,
    AnimationTrack.getBoneWeight returns 1). ModelInfo.getAnimationPlayer hands a child part
    (`parent =`) its parent's player, bones mapped by name, so a child's skinned model moves only
    through bones some track on that player weights; a second model on the same part gets its own
    player and never a track; and a bone no track weights gets an identity transform, i.e. the
    model is drawn nowhere (the parented rear glass, 2026-10-12). drive_map() rebuilds that tree
    from the script, a skinned model riding an unweighted bone is hidden with a warning, and pose()
    moves only the bones each track drives, so this tool fails the way the game fails.
  * Part CRVRoofRack lists its cargo states as extra models; the game shows the one the mod's Lua
    picks from the container's weight. `--rack N` draws state N (0 = empty basket) with `--acc`.
Mapping game render space to Blender space: (x, y, z)_game -> (x, z, y)_blender (game +x = Blender +x;
both put the vehicle's left at -x in model space). A rotation by t about game y is a rotation by -t
about Blender z.

Outputs per view: <pose>_<az>.png (textured, culled, magenta ground) and, when anything shows the
ground through the car, <pose>_<az>_leak.png with those pixels green. Prints one `PZVIEW` line per
view with the leak count, then `PZVIEW DONE`.
"""
import math
import os
import re
import sys

import bpy
import numpy as np
from mathutils import Matrix, Vector
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import crv_paths as _crv_paths  # noqa: E402  (machine paths: local_paths.json)

ROOT = os.environ.get("CRV_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(globals().get("__file__") or os.path.join("scripts", "_"))))
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def _arg(flag, default):
    return argv[argv.index(flag) + 1] if flag in argv else default


MOD = _arg("--mod", os.path.join(ROOT, "mod", "Contents", "mods", "HondaCRVGen1"))
OUT = _arg("--out", os.path.join(ROOT, "blender", "pzview"))
POSES = _arg("--poses", "shut,open").split(",")
AZIMUTHS = [float(a) for a in _arg("--az", "0,45,90,135,180,225,270,315").split(",")]
SCALE = float(_arg("--scale", "6.5"))                  # metres across the frame
RES = int(_arg("--res", "1400"))
ELEV = math.radians(30.0)          # PZ 2:1 dimetric: the camera looks down at 30 degrees
GROUND = tuple(float(c) for c in _arg("--ground", "1,0,1").split(","))   # magenta = leak test;
SKIN = _arg("--skin", None)        # --ground 0.3,0.3,0.31 --skin red --shadows: showcase renders
SHADOWS = "--shadows" in argv
ACC = "--acc" in argv              # draw the accessory parts (CRV*: bull bar, rack, guards); off by default so
                                   # the leak counts stay those of the bare car, which is what spawns most
ACC_ONLY = set(filter(None, _arg("--acc-parts", "").split(",")))   # with --acc: only these CRV parts
                                   # (e.g. CRVSpareCover), the others stay off as on a bare car
RACK = int(_arg("--rack", "0"))    # roof rack cargo state drawn with --acc: RackLoad<N> of part CRVRoofRack,
                                   # 0 = the empty basket (HondaCRVGen1Accessories.lua shows one at a time)
HIDE_MODELS = set(filter(None, _arg("--hide-models", "").split(",")))   # part model ids the Lua would hide (a
                                   # feature part's other variants, scripts/features): drawn by nobody here
DECALS = set(filter(None, _arg("--decal", "").split(",")))   # decals feature: the variants the Lua would show
                                   # (models of the CRVDecal* parts by id: retro_blue, pin_red, script_white,
                                   # logo_black ...); without it no decal is drawn, --acc or not (no car spawns
                                   # with one)
FOLDED = "--folded" in argv        # function feature: the rear bench folded flat. Part CRVFunctionSeats is the
                                   # car's own bench (no item, drawn bare or fitted); its Lua shows the upright
                                   # model (InteriorSeatsUp), or the folded one (*Folded) while folded
SEATS_PART = "CRVFunctionSeats"
# the engine bay (performance pass, 2026-10-19): part CRVEngineBay is the car's own bay (no item, drawn bare or
# fitted). HondaCRVGen1_EngineBay.lua shows EngineBay while the hood is open, opening or gone, and the shut
# bay's stand-in EngineBayLow otherwise: here every pose that opens EngineDoor (open, hood, at any --frac) draws
# the bay, every other pose the stand-in. --bay full|low forces one for every view.
BAY_PART = "CRVEngineBay"
BAY_MODELS = {"full": "EngineBay", "low": "EngineBayLow"}
BAY = _arg("--bay", "auto")
SHOW = _arg("--show", None)        # lights | mask | rust: draw that vehicle texture on the skinned
                                   # models instead of the paint (rust through the second UV set)
CAP = int(_arg("--cap", "0"))      # the loader's texture-size cap (see the docstring); 0 = none
GZ = float(_arg("--gz", "0"))      # also save each view at this many px per metre (<tag>_gz.png)
# --script NAME (lift feature, additive): draw that vehicle block (a feature's second vehicle script, which
# has no model blocks of its own: the model blocks of every vehicles/*.txt are global to the module, as in
# the game) instead of the first one found. Its body stands GROUND_DROP higher than the stock car's: the
# ground sits at (wheel y - radius) of its FrontLeft wheel against the stock script's, plus any change of
# the vehicle model offset (the wheels still stand on the ground, the views stay framed on the body)
SCRIPT = _arg("--script", None)
STOCK_VEHICLE = "HondaCRVGen1"
GROUND_DROP = 0.0
STEER = float(_arg("--steer", "0"))   # front wheels turned this many degrees (+ = left), to check arch clearance
# --damage N (0 none, 1 = TextureDamage1 on every zone, 2 = TextureDamage2), --rust R (the car's rust
# level 0..1), --blood I (blood intensity 0..1 on every zone), --paint h,s,v (a fixed dent paint HSV, as
# a multiuv shader would take it from the car's colour; default: each skin texel's own HSV, as our
# norandom shader does): the vehicle shader's rust / damage / blood mixing (vehicle_crvgen1_norandom.frag, vehicle_common.frag)
# replayed in numpy on the skin, in the SECOND UV layout they are sampled in (damage_composite). The
# sheets are the ones the script names, or the SUV template's vanilla ones when it names none.
DAMAGE = int(_arg("--damage", "-1")) if ("--damage" in argv or "--rust" in argv or "--blood" in argv) else None
DAMAGE = max(DAMAGE, 0) if DAMAGE is not None else None
RUST = float(_arg("--rust", "0"))
BLOOD = float(_arg("--blood", "0"))
PAINT = _arg("--paint", None)
GAME_MEDIA = os.path.join(_crv_paths.GAME, "media")
# Units. Everything is assembled in FBX units (the meshes ship at 10 per metre with script
# `scale = 0.1`; every model of this car uses the same scale, checked below). Script positions are
# in mesh metres: VehicleScript.Loaded multiplies them by the model block scale (0.9) and the body is
# drawn at that same 0.9, so the two stay registered (KI5's Bronco offsets are its mesh positions
# / 0.9 for that reason). The body FBX origin sits EXPORT_LIFT above the ground (export_fbx).
def _units():
    """FBX units per metre = 1 / the car's model script scale (export_fbx.UNITS_PER_M: 0.5 since 2026-10-18,
    10 before), read off the shipped vehicle script so old and new builds both view right."""
    import re
    d = os.path.join(MOD, "42", "media", "scripts", "vehicles")
    try:
        for fn in sorted(os.listdir(d)):
            txt = open(os.path.join(d, fn), encoding="utf-8", errors="replace").read()
            m = re.search(r"model\s+\w+Base\s*\{[^}]*?scale\s*=\s*([0-9.]+)", txt)
            if m:
                return 1.0 / float(m.group(1))
    except OSError:
        pass
    return 10.0


U = _units()
EXPORT_LIFT = 0.80


# ----------------------------------------------------------------------------------------------
# script parsing


class Block:
    def __init__(self, kind, name):
        self.kind, self.name, self.kv, self.children = kind, name, [], []

    def get(self, key, default=None):
        for k, v in self.kv:
            if k.lower() == key.lower():
                return v
        return default

    def getall(self, key):
        """Every value of a repeatable key (a model script's boneWeight lines)."""
        return [v for k, v in self.kv if k.lower() == key.lower()]

    def all(self, kind):
        return [c for c in self.children if c.kind.lower() == kind.lower()]


def parse_script(text):
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    root = Block("root", "")
    stack = [root]
    pending = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line == "{":
            kind, _, name = (pending or "").partition(" ")
            b = Block(kind.strip(), name.strip())
            stack[-1].children.append(b)
            stack.append(b)
            pending = None
            continue
        if line == "}":
            stack.pop()
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            stack[-1].kv.append((k.strip(), v.strip().rstrip(",").strip()))
            continue
        pending = line
    return root


def vec(s, n=3):
    vals = [float(t.rstrip("f")) for t in s.replace(",", " ").split()] if s else []
    return (vals + [0.0] * n)[:n]


def truthy(s):
    return str(s).strip().lower() == "true"


# ----------------------------------------------------------------------------------------------
# scene assembly


def _wheel_ground(veh):
    """--script: the ground under the physics origin (script y of the FrontLeft wheel minus its radius)
    and the vehicle model block's offset y, mesh metres."""
    w = next((b for b in veh.all("wheel") if b.name == "FrontLeft"), None)
    base = next((c for c in veh.children if c.kind.lower() == "model" and not c.name), None)
    moff = vec(base.get("offset"))[1] if base is not None else 0.0
    if w is None:
        return 0.0, moff
    return vec(w.get("offset"))[1] - float(w.get("radius", "0.33").rstrip("f")), moff


def _find_named_script(sdir, name):
    """--script: a module block holding every model block of every vehicles/*.txt and the vehicle block
    `name`; sets GROUND_DROP from its wheels and model offset against the stock vehicle's."""
    global GROUND_DROP
    models, vehicles = [], {}
    for fn in sorted(os.listdir(sdir)):
        if fn.lower().endswith(".txt"):
            root = parse_script(open(os.path.join(sdir, fn), encoding="utf-8").read())
            for mod_block in root.children:
                models += mod_block.all("model")
                vehicles.update({v.name: v for v in mod_block.all("vehicle")})
    if name not in vehicles:
        raise SystemExit("--script %s: no such vehicle block under %s (has %s)" % (name, sdir, ", ".join(sorted(vehicles))))
    out = Block("module", "Base")
    merge_parts(vehicles[name])                         # the lifted cars carry polish's door re-declarations too
    out.children = models + [vehicles[name]]
    if STOCK_VEHICLE in vehicles and name != STOCK_VEHICLE:
        g0, m0 = _wheel_ground(vehicles[STOCK_VEHICLE])
        g1, m1 = _wheel_ground(vehicles[name])
        GROUND_DROP = (g0 - g1) + (m1 - m0)
    print("PZVIEW script %s: body %.3f m higher than %s's" % (name, GROUND_DROP, STOCK_VEHICLE))
    return out


def merge_parts(veh):
    """A part declared twice is ONE part in the game (VehicleScript.LoadPart finds it by id and loads
    the second block into it; LoadAnim does the same for an anim by name): fold every later block of a
    part, and its anims, into the first. The polish feature re-declares the doors to add their sounds."""
    first, kept = {}, []
    for c in veh.children:
        if c.kind.lower() != "part" or c.name not in first:
            if c.kind.lower() == "part":
                first[c.name] = c
            kept.append(c)
            continue
        base = first[c.name]
        base.kv += c.kv
        for ch in c.children:
            same = next((b for b in base.children if b.kind.lower() == ch.kind.lower() and b.name == ch.name
                         and ch.kind.lower() == "anim"), None)
            if same is not None:
                same.kv = [kv for kv in same.kv if kv[0].lower() not in {k.lower() for k, _v in ch.kv}] + ch.kv
            else:
                base.children.append(ch)
    veh.children = kept


def find_script():
    sdir = os.path.join(MOD, "42", "media", "scripts", "vehicles")
    if SCRIPT:                                          # --script (lift feature): a named vehicle block
        return _find_named_script(sdir, SCRIPT)
    for fn in sorted(os.listdir(sdir)):
        if fn.lower().endswith(".txt"):
            root = parse_script(open(os.path.join(sdir, fn), encoding="utf-8").read())
            for mod_block in root.children:
                if mod_block.all("vehicle"):
                    for veh in mod_block.all("vehicle"):
                        merge_parts(veh)
                    return mod_block
    raise SystemExit("no vehicle script under %s" % sdir)


def fbx_path(mesh_ref):
    rel = mesh_ref.split("|")[0]
    for base in (os.path.join(MOD, "common", "media", "models_X"), os.path.join(MOD, "42", "media", "models_X")):
        p = os.path.join(base, *rel.split("/")) + ".fbx"
        if os.path.exists(p):
            return p
    raise SystemExit("mesh file not found for %s" % mesh_ref)


def tex_path(name):
    for base in (os.path.join(MOD, "common", "media", "textures"), os.path.join(MOD, "42", "media", "textures")):
        p = os.path.join(base, *name.split("/")) + ".png"
        if os.path.exists(p):
            return p
    return None


_imported = {}


def import_fbx(path):
    """Import an FBX once; return {geometry name: object}. The game resolves file|name against the
    FBX Geometry name, which Blender's importer keeps as the mesh datablock name."""
    if path in _imported:
        return _imported[path]
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=path)
    new = [o for o in bpy.data.objects if o not in before]
    geo = {}
    for o in new:
        if o.type == 'MESH':
            geo[o.data.name] = o
            geo.setdefault(o.name, o)
            o.hide_render = True                  # only what the script references is drawn
    arm = next((o for o in new if o.type == 'ARMATURE'), None)
    _imported[path] = (geo, arm)
    return _imported[path]


_mats = {}


def material(png, cap=True):
    if png in _mats:
        return _mats[png]
    mat = bpy.data.materials.new(os.path.basename(png))
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = next(n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED')
    tex = nt.nodes.new("ShaderNodeTexImage")
    img = bpy.data.images.load(png, check_existing=False)
    if cap and CAP and max(img.size) > CAP:       # what TextureID uploads under the player's size option
        # scaled in memory, saved and loaded back from the file: a scale that lives only in the
        # buffer cache was gone by render time (the first --cap runs drew the full sheets, 2026-10-12)
        k = CAP / float(max(img.size))
        img.scale(max(1, round(img.size[0] * k)), max(1, round(img.size[1] * k)))
        capped = os.path.join(OUT, "_tmp_cap%d_%s" % (CAP, os.path.basename(png)))
        img.filepath_raw = capped
        img.file_format = 'PNG'
        img.save()
        bpy.data.images.remove(img)
        img = bpy.data.images.load(capped, check_existing=False)
    tex.image = img
    tex.interpolation = 'Linear'                  # GL_LINEAR min and mag, no mipmaps: the game's sampling.
                                                  # 'Closest' (v6) showed texel edges the game never draws
    tex.image.alpha_mode = 'NONE'                 # alpha is data (shell: gloss for the mod's shader; lights /
                                                  # rust: masks), never transparency
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    nt.nodes.active = tex
    _mats[png] = mat
    return mat


def game_rot_to_blender(rx, ry, rz):
    """rotationXYZ(rx, ry, rz) in game render space, as a Blender-space 3x3 (radians in)."""
    rg = (Matrix.Rotation(rx, 3, 'X') @ Matrix.Rotation(ry, 3, 'Y') @ Matrix.Rotation(rz, 3, 'Z'))
    p = Matrix(((1, 0, 0), (0, 0, 1), (0, 1, 0)))          # swaps y and z, its own inverse
    return p @ rg @ p


_used = set()


# --cut-box name,x0,x1,y0,y1,z0,z1: debug only, deletes the faces of geometry `name` whose vertices all lie
# in the box (Blender world space, after the FBX import). Used to test which piece of geometry is a visual.
CUT = _arg("--cut-box", "")


def _cut_box(src):
    import bmesh
    parts = CUT.split(",")
    if parts[0] != "*" and parts[0] != src.data.name and parts[0] != src.name:
        return
    print("PZVIEW cut-box geometry %s" % src.data.name)
    x0, x1, y0, y1, z0, z1 = [float(v) for v in parts[1:7]]
    w = [src.matrix_world @ v.co for v in src.data.vertices]
    print("PZVIEW cut-box bounds %s min %s max %s" % (src.data.name,
          [round(min(p[i] for p in w), 3) for i in range(3)], [round(max(p[i] for p in w), 3) for i in range(3)]))
    bm = bmesh.new()
    bm.from_mesh(src.data)
    M = src.matrix_world
    def inside(v):
        w = M @ v.co
        return x0 <= w.x <= x1 and y0 <= w.y <= y1 and z0 <= w.z <= z1
    ins = [v for v in bm.verts if inside(v)]
    if ins:
        wi = [M @ v.co for v in ins]
        print("PZVIEW cut-box verts inside %d, bbox min %s max %s" % (len(ins),
              [round(min(p[i] for p in wi), 2) for i in range(3)], [round(max(p[i] for p in wi), 2) for i in range(3)]))
    seen = set()
    for v0 in ins:
        if v0.index in seen: continue
        comp = []; stack = [v0]; seen.add(v0.index)
        while stack:
            v = stack.pop(); comp.append(v)
            for e in v.link_edges:
                u = e.other_vert(v)
                if u.index not in seen and inside(u):
                    seen.add(u.index); stack.append(u)
        wc = [M @ v.co for v in comp]
        print("PZVIEW piece %d verts min %s max %s" % (len(comp),
              [round(min(p[i] for p in wc), 2) for i in range(3)], [round(max(p[i] for p in wc), 2) for i in range(3)]))
    doomed = [f for f in bm.faces if any(inside(v) for v in f.verts)]
    print("PZVIEW cut-box %s: %d faces removed of %d" % (src.data.name, len(doomed), len(bm.faces)))
    bmesh.ops.delete(bm, geom=doomed, context='FACES')
    bm.to_mesh(src.data)
    bm.free()
    src["_cut_done"] = True


def instance(model_name, models, skin_png, xform, label):
    """Draw one model: the mesh it names, with its texture, at xform (Blender space, FBX units).
    The first identity-placed use of a mesh draws the imported object itself (keeps its armature
    parenting, so the shipped clips move it); any other use draws a copy."""
    ms = models.get(model_name)
    if ms is None:
        print("PZVIEW warning: %s names model %s, not declared" % (label, model_name))
        return None
    mesh_ref = ms.get("mesh")
    path = fbx_path(mesh_ref)
    geo, arm = import_fbx(path)
    gname = mesh_ref.split("|")[1] if "|" in mesh_ref else None
    src = geo.get(gname)
    if src is not None and CUT and not src.get("_cut_done"):
        _cut_box(src)
    if src is None:
        print("PZVIEW warning: %s: geometry %s not in %s (has %s)" % (label, gname, os.path.basename(path), sorted(geo)))
        return None
    scale = float(ms.get("scale", "1").rstrip("f"))
    if abs(scale - 1.0 / U) > 1e-6:
        print("PZVIEW warning: %s: model scale %s, this tool assumes %.2f for every model" % (label, scale, 1.0 / U))
    inv = -1.0 if truthy(ms.get("invertX", "false")) else 1.0
    place = xform @ Matrix.Diagonal((inv, 1.0, 1.0, 1.0))
    identity = all(abs(place[i][j] - (1.0 if i == j else 0.0)) < 1e-9 for i in range(4) for j in range(4))
    if identity and src.name not in _used:
        ob = src
    else:
        ob = src.copy()
        ob.data = src.data
        bpy.context.scene.collection.objects.link(ob)
        ob.matrix_world = place @ src.matrix_world
    _used.add(src.name)
    ob.hide_render = False
    ob["pz_label"] = label
    ob["pz_file"] = model_name                    # the model script: check_driven reads its static / boneWeight
    png = tex_path(ms.get("texture")) if ms.get("texture") else skin_png
    if ms.get("shader") == "vehiclewheel" and len(ob.data.uv_layers) > 1:
        # The game binds vertex attributes by position in the mesh's element list; an FBX static
        # mesh is [position, normal, uv, uv2] and vehiclewheel_static.vert reads slot 3: the SECOND
        # UV layer (export_fbx mirrors the first into it). Draw with that layer, as the game does.
        ob.data.uv_layers.active_index = 1
        ob.data.uv_layers[1].active_render = True
    if SHOW and not ms.get("texture"):
        png = tex_path("Vehicles/Vehicles_HondaCRVGen1_" + SHOW.capitalize()) or png
        if SHOW == "rust" and ob.data.uv_layers and len(ob.data.uv_layers) > 1:
            ob.data.uv_layers.active_index = 1           # texCoords1 (rust / damage / blood)
            ob.data.uv_layers[1].active_render = True
    if png is None:
        print("PZVIEW warning: %s: texture %s not found in the mod" % (label, ms.get("texture") or "(vehicle skin)"))
    ob.data.materials.clear()
    if png:
        ob.data.materials.append(material(png))
    ob["pz_skin"] = 1 if (png and png == skin_png and not ms.get("texture") and not SHOW) else 0   # --damage redraws these
    return ob


TIRE_WHEEL = {"TireFrontLeft": "FrontLeft", "TireFrontRight": "FrontRight",
              "TireRearLeft": "RearLeft", "TireRearRight": "RearRight"}


def build(vehicle_mod):
    models = {b.name: b for b in vehicle_mod.all("model")}
    veh = vehicle_mod.all("vehicle")[0]
    skins = [s.get("texture") for s in veh.all("skin") if s.get("texture")]
    pick = next((t for t in skins if SKIN and t.lower().endswith("_" + SKIN.lower())), skins[0] if skins else None)
    skin_png = tex_path(pick) if pick else None
    drawn = []
    base = next(c for c in veh.children if c.kind.lower() == "model" and not c.name)
    drawn.append(instance(base.get("file"), models, skin_png, Matrix.Identity(4), "base"))
    wheels = {w.name: w for w in veh.all("wheel")}
    anims = {}
    for part in veh.all("part"):
        is_decal = part.name.startswith("CRVDecal")             # decals feature: drawn by --decal alone
        if is_decal:
            if not DECALS:
                continue
        elif (part.name.startswith("CRV") and part.name not in (SEATS_PART, BAY_PART)
              and (not ACC or (ACC_ONLY and part.name not in ACC_ONLY))):
            continue
        # tyre parts name their wheel through the vanilla Tire template (wheel = FrontLeft ...)
        wname = part.get("wheel") or TIRE_WHEEL.get(part.name)
        for pm in part.all("model"):
            f = pm.get("file")
            if not f:
                continue
            if pm.name.startswith("RackLoad") and pm.name != "RackLoad%d" % RACK:
                continue                                  # cargo states: the Lua shows one at a time (--rack)
            if pm.name in HIDE_MODELS:
                continue                                  # --hide-models: a variant the Lua keeps hidden
            if part.name == SEATS_PART and pm.name.endswith("Folded") != FOLDED:
                continue                                  # the rear bench: upright, or folded with --folded
            if is_decal and pm.name not in DECALS:
                continue                                  # --decal: only the chosen variants
            off = vec(pm.get("offset"))
            rot = [math.radians(a) for a in vec(pm.get("rotate"))]
            sc = float(pm.get("scale", "1").rstrip("f"))
            label = "%s.%s" % (part.name, pm.name)
            if wname and wname in wheels:
                w = wheels[wname]
                wo = vec(w.get("offset"))
                radius = float(w.get("radius", "0.33").rstrip("f"))
                # centre: script x is the vehicle's LEFT (mesh -x); height from the tyre radius on the
                # ground (the suspension settles it there in game)
                centre = Vector((-wo[0], wo[2], -EXPORT_LIFT - GROUND_DROP + radius)) * U   # (--script)
                r = game_rot_to_blender(rot[0], rot[1], rot[2]).to_4x4()      # wheels: no sign flip
                if STEER and truthy(w.get("front", "false")):                  # --steer DEG (lift feature): the
                    r = Matrix.Rotation(math.radians(STEER), 4, 'Z') @ r       # front wheels turned, + = left
                t = Matrix.Translation(centre + Vector((-off[0], off[2], off[1])) * U)
                xf = t @ r @ Matrix.Diagonal((sc, sc, sc, 1.0))
            else:
                r = game_rot_to_blender(rot[0], -rot[1], -rot[2]).to_4x4()    # parts: y, z negated
                t = Matrix.Translation(Vector((-off[0], off[2], off[1])) * U)
                xf = t @ r @ Matrix.Diagonal((sc, sc, sc, 1.0))
            ob = instance(f, models, skin_png, xf, label)
            if ob is not None:
                ob["pz_part"] = part.name
                ob["pz_model"] = pm.name
            drawn.append(ob)
        for a in part.all("anim"):
            anims.setdefault(part.name, {})[a.name] = (a.get("anim"), truthy(a.get("reverse", "false")))
    return [d for d in drawn if d], anims


# ----------------------------------------------------------------------------------------------
# the game's part / player tree (see the docstring)

TRACK_ANIMS = ("Open", "Close", "Closed", "Opened", "ClosedToOpen")   # anims playPartAnim is called with


def drive_map(vehicle_mod):
    """For every scripted part: its first model script, its OWNER (the part whose AnimationPlayer
    draws it: itself, or the top-most parent that has a model, as ModelInfo.getAnimationPlayer
    recurses), and per owner the tracks that player carries: one per part of its tree that plays a
    clip, (part, {anim: clip}, mask) with mask = the bone names of that part's first model script's
    boneWeight lines ([] = every bone)."""
    models = {b.name: b for b in vehicle_mod.all("model")}
    veh = vehicle_mod.all("vehicle")[0]
    parts = {p.name: p for p in veh.all("part")}
    first = {}
    for name, p in parts.items():
        pms = [pm for pm in p.all("model") if pm.get("file")]
        if pms:
            first[name] = models.get(pms[0].get("file"))

    def owner(name):
        seen = {name}
        while True:
            parent = parts[name].get("parent") if name in parts else None
            if not parent or parent not in first or parent in seen:   # no ModelInfo for the parent: own player
                return name
            seen.add(parent)
            name = parent

    owners = {name: owner(name) for name in parts}
    tracks = {}
    for name, p in parts.items():
        clips = {a.name: a.get("anim") for a in p.all("anim") if a.name in TRACK_ANIMS and a.get("anim")}
        if not clips:
            continue
        mask = []
        ms = first.get(name)
        for bw in (ms.getall("boneWeight") if ms is not None else []):
            toks = bw.split()
            try:
                w = float(toks[1]) if len(toks) > 1 else 1.0          # PZMath.tryParseFloat(.., 1.0)
            except ValueError:
                w = 1.0
            if toks and w > 0.001:
                mask.append(toks[0])
        tracks.setdefault(owners[name], []).append((name, clips, mask))
    return {"models": models, "first": first, "owner": owners, "tracks": tracks}


def check_driven(drawn, dm, arms):
    """Hide what the game draws nowhere: a skinned model (static = FALSE) whose vertex groups name a
    bone that no track on its owner's player weights. Returns the models the game does draw."""
    all_bones = {b.name for arm in arms if arm is not None for b in arm.data.bones}
    kept = []
    for ob in drawn:
        part, f = ob.get("pz_part"), ob.get("pz_file")
        ms = dm["models"].get(f) if f else None
        if not part or ms is None or str(ms.get("static", "true")).strip().lower() != "false":
            kept.append(ob)
            continue
        used = set()
        for v in ob.data.vertices:
            for g in v.groups:
                if g.weight > 0.0 and g.group < len(ob.vertex_groups):
                    used.add(ob.vertex_groups[g.group].name)
        own = dm["owner"].get(part, part)
        driven = set()
        for _p, _clips, mask in dm["tracks"].get(own, []):
            driven |= set(mask) if mask else all_bones
        missing = used - driven
        if missing:
            ob.hide_render = True
            print("PZVIEW warning: %s rides %s: no track on %s's player weights it, the game draws it nowhere"
                  % (ob.get("pz_label", ob.name), ", ".join(sorted(missing)), own))
            continue
        kept.append(ob)
    return kept


def glass_twins(drawn, vehicle_mod):
    """Flipped copies of the glass, used only for the leak count: glass is transparent in game, so
    the ground seen through a culled pane is not a hole. Side windows are glass-only models; on the
    body and the rear hatch the Mask texture's window zones (windscreen, rear glass) mark the glass."""
    veh = vehicle_mod.all("vehicle")[0]
    mask_png = tex_path(veh.get("textureMask")) if veh.get("textureMask") else None
    mask = None
    if mask_png:
        img = bpy.data.images.load(mask_png, check_existing=True)
        w, h = img.size
        mask = (np.array(img.pixels[:], dtype=np.float32).reshape(h, w, 4), w, h)
    glass_zones = [(0.0, 0.5, 0.0), (0.5, 0.0, 0.0)]          # window_h (windscreen), window_t (rear hatch)
    twins = []
    for ob in drawn:
        me = ob.data
        lab = ob.get("pz_label", "")
        whole = lab.startswith("Window") or "Window" in lab.split(".")[-1]
        keep = []
        if whole:
            keep = list(range(len(me.polygons)))
        elif mask is not None and me.uv_layers:
            a, w, h = mask
            uv = me.uv_layers[0].data
            for p in me.polygons:
                u = sum(uv[li].uv.x for li in p.loop_indices) / p.loop_total
                v = sum(uv[li].uv.y for li in p.loop_indices) / p.loop_total
                c = a[min(h - 1, max(0, int(v * h))), min(w - 1, max(0, int(u * w))), :3]
                if any(abs(c[0] - z[0]) < 0.06 and abs(c[1] - z[1]) < 0.06 and abs(c[2] - z[2]) < 0.06 for z in glass_zones):
                    keep.append(p.index)
        if not keep:
            continue
        import bmesh
        bm = bmesh.new()
        bm.from_mesh(me)
        bm.faces.ensure_lookup_table()
        ks = set(keep)
        bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.index not in ks], context='FACES')
        bmesh.ops.reverse_faces(bm, faces=list(bm.faces))
        tme = bpy.data.meshes.new("twin_" + ob.name)
        bm.to_mesh(tme)
        bm.free()
        for m in me.materials:
            tme.materials.append(m)
        tw = bpy.data.objects.new("twin_" + ob.name, tme)
        bpy.context.scene.collection.objects.link(tw)
        tw.parent = ob.parent
        tw.matrix_world = ob.matrix_world
        for mod in ob.modifiers:                       # ride the same bones
            if mod.type == 'ARMATURE':
                nm = tw.modifiers.new("arm", 'ARMATURE')
                nm.object = mod.object
                for g in ob.vertex_groups:
                    tw.vertex_groups.new(name=g.name)
        tw.hide_render = True
        twins.append(tw)
    print("PZVIEW glass twins: %d objects" % len(twins))
    return twins


# ----------------------------------------------------------------------------------------------
# posing from the shipped clips


def clip_pose(arm, clip, at_end=True, frac=1.0):
    """Evaluate one FBX clip and return {bone: (loc, quat)} for the bones it moves; at_end: at
    `frac` of the clip's travel (1 = its last frame)."""
    act = next((a for a in bpy.data.actions if a.name.endswith("|" + clip) or a.name == clip), None)
    if act is None:
        print("PZVIEW warning: clip %s not in the FBX (actions: %s)" % (clip, [a.name for a in bpy.data.actions][:12]))
        return {}
    f0, f1 = act.frame_range
    frame = (f0 + frac * (f1 - f0)) if at_end else f0
    out = {}
    curves = {}
    for fc in act.fcurves:
        m = re.match(r'pose\.bones\["(.+)"\]\.(location|rotation_quaternion)', fc.data_path)
        if m:
            curves.setdefault(m.group(1), {}).setdefault(m.group(2), {})[fc.array_index] = fc
    for bone, chans in curves.items():
        loc = [chans.get("location", {}).get(i).evaluate(frame) if i in chans.get("location", {}) else 0.0 for i in range(3)]
        q = [chans.get("rotation_quaternion", {}).get(i).evaluate(frame) if i in chans.get("rotation_quaternion", {}) else (1.0 if i == 0 else 0.0) for i in range(4)]
        loc0 = [chans.get("location", {}).get(i).evaluate(f0) if i in chans.get("location", {}) else 0.0 for i in range(3)]
        q0 = [chans.get("rotation_quaternion", {}).get(i).evaluate(f0) if i in chans.get("rotation_quaternion", {}) else (1.0 if i == 0 else 0.0) for i in range(4)]
        moved = max(abs(a - b) for a, b in zip(loc + q, loc0 + q0)) > 1e-4
        out[bone] = (loc, q, moved)
    return out


POSE_PARTS = {                     # --poses names besides shut / open (everything that opens)
    "left": ("DoorFrontLeft", "DoorRearLeft"), "right": ("DoorFrontRight", "DoorRearRight"),
    "front": ("DoorFrontLeft", "DoorFrontRight"), "gate": ("TrunkDoor",), "hood": ("EngineDoor",),
    "fl": ("DoorFrontLeft",), "fr": ("DoorFrontRight",), "rl": ("DoorRearLeft",), "rr": ("DoorRearRight",),
}
WINDOWS = {"fl": "WindowFrontLeft", "fr": "WindowFrontRight", "rl": "WindowRearLeft", "rr": "WindowRearRight"}
# --frac F (0..1): every opening clip evaluated at F of its travel, a panel part-way through its swing (the
# game draws every frame of it: R2-OC-8, 2026-10-17, ground lines along the doors' edges at ~15 % open that
# neither the shut nor the open pose shows). 1 = the Open clip's end, as before.
FRAC = float(_arg("--frac", "1"))


def pose(arms, dm, opened):
    """opened: False / "shut" = all shut, True / "open" = all open, a POSE_PARTS name, or several
    tokens joined by '+' (POSE_PARTS names, open, win = every window down, win_fl / win_fr / win_rl /
    win_rr one window down): e.g. "left+win". Each opened part's Open clip (a window's ClosedToOpen)
    is applied the way its track plays, at --frac of its travel: only to the bones the track's mask
    weights (every bone without a mask), on the owner's player (drive_map). A bone the clip keys
    but the mask leaves out stays at rest, as it does in game."""
    toks = str(opened).split("+") if isinstance(opened, str) else (["open"] if opened else ["shut"])
    parts_open = set()                            # None = every part
    wins = set()
    for t in toks:
        if t == "open":
            parts_open = None
        elif t in POSE_PARTS:
            if parts_open is not None:
                parts_open |= set(POSE_PARTS[t])
        elif t == "win":
            wins.add("*")
        elif t.startswith("win_") and t[4:] in WINDOWS:
            wins.add(WINDOWS[t[4:]])
        elif t != "shut":
            print("PZVIEW warning: pose token %r unknown (shut, open, win, win_fl.., %s)" % (t, ", ".join(POSE_PARTS)))
    for arm in arms:
        if arm is None:
            continue
        arm.animation_data_clear()
        for pb in arm.pose.bones:
            pb.location = (0, 0, 0)
            pb.rotation_mode = 'QUATERNION'
            pb.rotation_quaternion = (1, 0, 0, 0)
        all_bones = {b.name for b in arm.data.bones}
        for tracks in dm["tracks"].values():
            for part, clips, mask in tracks:
                if part.startswith("Window"):             # windows stay up unless asked for
                    clip = clips.get("ClosedToOpen") if ("*" in wins or part in wins) else None
                elif parts_open is None or part in parts_open:
                    clip = clips.get("Open")              # doors, hood, tailgate
                else:
                    clip = None
                if not clip:
                    continue
                driven = set(mask) if mask else all_bones
                for bone, (loc, q, moved) in clip_pose(arm, clip, at_end=True, frac=FRAC).items():
                    if moved and bone in driven and bone in arm.pose.bones:
                        pb = arm.pose.bones[bone]
                        pb.location = loc
                        pb.rotation_quaternion = q
    bpy.context.view_layer.update()


def hood_opened(opened):
    """Does this pose (pose()'s argument) open EngineDoor?"""
    toks = str(opened).split("+") if isinstance(opened, str) else (["open"] if opened else ["shut"])
    return any(t == "open" or "EngineDoor" in POSE_PARTS.get(t, ()) for t in toks)


def bay_models(drawn, opened):
    """Show the model of BAY_PART the mod's Lua would for this pose; returns its id."""
    want = BAY if BAY in BAY_MODELS else ("full" if hood_opened(opened) else "low")
    for ob in drawn:
        if ob.get("pz_part") == BAY_PART and ob.get("pz_model") in BAY_MODELS.values():
            ob.hide_render = ob.get("pz_model") != BAY_MODELS[want]
    return BAY_MODELS[want]


# ----------------------------------------------------------------------------------------------
# rendering


SUV_DAMAGE = {"textureRust": "Vehicles/Veh_Rust", "textureDamage1Shell": "Vehicles/Veh_Damage1",
              "textureDamage2Shell": "Vehicles/Veh_Damage2", "textureDamage1Overlay": "Vehicles/Veh_Blood_Mask",
              "textureDamage2Overlay": "Vehicles/Veh_Blood_Hvy"}       # vehicle_suv_template.txt, inherited


def _png(path):
    img = bpy.data.images.load(path, check_existing=False)
    w, h = img.size
    a = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(a)
    bpy.data.images.remove(img)
    return np.flipud(a.reshape(h, w, 4))                 # row 0 = top, as the PNG


def _rgb2hsv(c):
    r, g, b = c[..., 0], c[..., 1], c[..., 2]
    mx, mn = c.max(-1), c.min(-1)
    d = mx - mn
    h = np.zeros_like(mx)
    nz = d > 1e-6
    rr = nz & (mx == r)
    gg = nz & (mx == g) & ~rr
    bb = nz & ~rr & ~gg
    h[rr] = ((g - b)[rr] / d[rr]) % 6
    h[gg] = (b - r)[gg] / d[gg] + 2
    h[bb] = (r - g)[bb] / d[bb] + 4
    s = np.where(mx > 1e-6, d / np.maximum(mx, 1e-6), 0)
    return np.stack([h / 6.0, s, mx], -1)


def _hsv2rgb(hsv):
    h, s, v = hsv[..., 0] % 1.0, hsv[..., 1], hsv[..., 2]
    i = np.floor(h * 6).astype(int) % 6
    f = h * 6 - np.floor(h * 6)
    p, q, t = v * (1 - s), v * (1 - f * s), v * (1 - (1 - f) * s)
    sel = [(v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q)]
    out = np.zeros(h.shape + (3,))
    for k, (a, b, c) in enumerate(sel):
        m = i == k
        out[m] = np.stack([a[m], b[m], c[m]], -1)
    return out


def _sample(img, uv):
    """Bilinear sample of a (h, w, 4) image at UVs (n, 2), v up."""
    h, w = img.shape[:2]
    x = np.clip(uv[:, 0] * w - 0.5, 0, w - 1)
    y = np.clip((1.0 - uv[:, 1]) * h - 0.5, 0, h - 1)
    x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
    x1, y1 = np.minimum(x0 + 1, w - 1), np.minimum(y0 + 1, h - 1)
    fx, fy = (x - x0)[:, None], (y - y0)[:, None]
    return (img[y0, x0] * (1 - fx) * (1 - fy) + img[y0, x1] * fx * (1 - fy)
            + img[y1, x0] * (1 - fx) * fy + img[y1, x1] * fx * fy)


def _blood(col, b2, bm, intensity, alpha):
    a = 1 - (1 - b2[:, 3]) ** 3
    ma = 1 - (1 - bm[:, 3]) ** 3
    fa = a * ma
    i = min(max(intensity, 0.0), 1.0)
    if i < 1e-4:
        return col
    fa = np.clip((fa - (1 - i)) / i, 0, 1)
    k = (fa * b2[:, 3] * alpha)[:, None]
    return col * (1 - k) + b2[:, :3] * fa[:, None] * k


def damage_composite(drawn, vehicle_mod, size=2048):
    """Bake what the vehicle shader would draw on the skinned models with every zone damaged
    (--damage), rusted (--rust) and bloodied (--blood) into one texture in their SECOND UV layout,
    and draw them with it. The paint, Mask and lights stay sampled at the first UV per texel."""
    veh = vehicle_mod.all("vehicle")[0]
    obs = [o for o in drawn if o.get("pz_skin") and len(o.data.uv_layers) > 1]
    if not obs:
        print("PZVIEW damage: no skinned models with a second UV layer")
        return
    skin = obs[0].data.materials[0].node_tree.nodes.active.image.filepath
    skin_img = _png(bpy.path.abspath(skin))
    mask_img = _png(tex_path(veh.get("textureMask")))

    def sheet(key):
        name = veh.get(key) or SUV_DAMAGE[key]
        p = tex_path(name) or os.path.join(GAME_MEDIA, "textures", *name.split("/")) + ".png"
        print("PZVIEW damage: %s = %s" % (key, p))
        img = _png(p)
        while CAP and max(img.shape[:2]) > CAP:          # the game caps each texture (box-halved at load)
            h, w = img.shape[0] // 2 * 2, img.shape[1] // 2 * 2
            img = 0.25 * (img[0:h:2, 0:w:2] + img[1:h:2, 0:w:2] + img[0:h:2, 1:w:2] + img[1:h:2, 1:w:2])
        return img
    rust, d1, d2 = sheet("textureRust"), sheet("textureDamage1Shell"), sheet("textureDamage2Shell")
    bm, b2 = sheet("textureDamage1Overlay"), sheet("textureDamage2Overlay")
    # the dent paint: the skin texel's own HSV (vehicle_crvgen1_norandom, like the game's norandom
    # shader); --paint h,s,v forces a fixed one (what a multiuv shader with that car colour would draw)
    paint = [float(v) for v in PAINT.split(",")] if PAINT else None
    print("PZVIEW damage: level %d, rust %.2f, blood %.2f, paint HSV %s" % (DAMAGE, RUST, BLOOD, paint or "per texel"))
    # rasterise every skinned triangle into the UV2 grid: per texel its UV0
    tri_uv0, tri_uv1 = [], []
    for ob in obs:
        me = ob.data
        me.calc_loop_triangles()
        n = len(me.loop_triangles)
        loops = np.empty(n * 3, dtype=np.int32)
        me.loop_triangles.foreach_get("loops", loops)
        for layer, dst in ((me.uv_layers[0], tri_uv0), (me.uv_layers[1], tri_uv1)):
            d = np.empty(len(me.loops) * 2, dtype=np.float32)
            layer.data.foreach_get("uv", d)
            dst.append(d.reshape(-1, 2)[loops].reshape(n, 3, 2))
    uv0, uv1 = np.concatenate(tri_uv0).astype(np.float64), np.concatenate(tri_uv1).astype(np.float64)
    S = size
    X, Y = uv1[..., 0] * S, (1.0 - uv1[..., 1]) * S
    texel_uv0 = np.zeros((S * S, 2))
    cov = np.zeros(S * S, dtype=bool)
    c0, c1 = np.floor(X.min(1)).astype(int), np.ceil(X.max(1)).astype(int)
    r0, r1 = np.floor(Y.min(1)).astype(int), np.ceil(Y.max(1)).astype(int)
    for t in range(len(uv1)):
        cs, ce, rs, re_ = max(c0[t], 0), min(c1[t], S - 1), max(r0[t], 0), min(r1[t], S - 1)
        if ce < cs or re_ < rs:
            continue
        cc, rr = np.meshgrid(np.arange(cs, ce + 1) + 0.5, np.arange(rs, re_ + 1) + 0.5)
        x, y = X[t], Y[t]
        A = (x[1] - x[0]) * (y[2] - y[0]) - (x[2] - x[0]) * (y[1] - y[0])
        if abs(A) < 1e-12:
            continue
        w0 = ((x[1] - cc) * (y[2] - rr) - (x[2] - cc) * (y[1] - rr)) / A
        w1 = ((x[2] - cc) * (y[0] - rr) - (x[0] - cc) * (y[2] - rr)) / A
        w2 = 1 - w0 - w1
        ok = (w0 >= -1e-4) & (w1 >= -1e-4) & (w2 >= -1e-4)
        if not ok.any():
            continue
        pix = ((rr[ok] - 0.5).astype(int) * S + (cc[ok] - 0.5).astype(int))
        texel_uv0[pix] = (w0[ok, None] * uv0[t, 0] + w1[ok, None] * uv0[t, 1] + w2[ok, None] * uv0[t, 2])
        cov[pix] = True
    idx = np.flatnonzero(cov)
    u0 = texel_uv0[idx]
    u1 = np.column_stack([(idx % S + 0.5) / S, 1.0 - (idx // S + 0.5) / S])
    col = _sample(skin_img, u0)[:, :3]
    tex_hsv = _rgb2hsv(col)
    m = mask_img[np.clip(((1 - u0[:, 1]) * mask_img.shape[0]).astype(int), 0, mask_img.shape[0] - 1),
                 np.clip((u0[:, 0] * mask_img.shape[1]).astype(int), 0, mask_img.shape[1] - 1)]
    z = np.round(m[:, :3] * 255).astype(int)

    def zone_in(cols):
        out = np.zeros(len(z), dtype=bool)
        for c in cols:
            out |= (np.abs(z - np.array(c)).max(1) <= 2)
        return out
    window = zone_in([(0, 128, 128), (128, 128, 0), (128, 0, 128), (0, 0, 128), (128, 0, 0), (0, 128, 0)])
    front = zone_in([(255, 0, 0), (191, 0, 0), (64, 0, 0)])
    tail = zone_in([(0, 255, 0), (0, 191, 0), (0, 64, 0), (128, 64, 0), (128, 191, 0)])
    notint = window | front | tail
    rs = _sample(rust, u1)
    col = col * (1 - (rs[:, 3] * RUST)[:, None]) + rs[:, :3] * (rs[:, 3] * RUST)[:, None]
    B2, BM = _sample(b2, u1), _sample(bm, u1)
    col = _blood(col, B2, BM, BLOOD, window.astype(float))
    if DAMAGE in (1, 2):
        dm = _sample(d1 if DAMAGE == 1 else d2, u1)
        hsv = _rgb2hsv(dm[:, :3])
        ph = np.array(paint)[None, :] if paint else tex_hsv
        hsv[:, 0] = ph[:, 0]
        hsv[:, 1] = np.clip(hsv[:, 1] + ph[:, 1] - 0.5, 0, 0.9999)
        hsv[:, 2] = np.clip(hsv[:, 2] + ph[:, 2] - 0.5, 0, 0.9999)
        tinted = _hsv2rgb(hsv)
        k_body = (dm[:, 3] * 0.75 * ~notint)[:, None]
        col = col * (1 - k_body) + tinted * k_body
        k_abs = (dm[:, 3] * notint)[:, None]
        col = col * (1 - k_abs) + dm[:, :3] * k_abs
    col = _blood(col, B2, BM, BLOOD, (~window).astype(float))
    img = np.zeros((S * S, 4), dtype=np.float32)
    img[:, 3] = 1.0
    img[idx, :3] = col
    img = img.reshape(S, S, 4)
    filled = cov.reshape(S, S).copy()
    for _ in range(6):                                    # grow into the gutters (bilinear at island edges)
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            src = np.roll(np.roll(img, dy, 0), dx, 1)
            sf = np.roll(np.roll(filled, dy, 0), dx, 1)
            take = sf & ~filled
            img[take] = src[take]
            filled |= take
    path = os.path.join(OUT, "_damage_composite.png")
    out = bpy.data.images.new("pz_damage", S, S)
    out.pixels.foreach_set(np.flipud(img).ravel())
    out.filepath_raw = path
    out.file_format = 'PNG'
    out.save()
    mat = material(path, cap=False)                       # its inputs are capped like the game's; the
    for ob in obs:                                        # composite is pzview's, not a game texture
        ob.data.uv_layers.active_index = 1
        ob.data.uv_layers[1].active_render = True
        ob.data.materials.clear()
        ob.data.materials.append(mat)
    print("PZVIEW damage: composite %d px, %d texels, %d models" % (S, len(idx), len(obs)))


def setup_render():
    scene = bpy.context.scene
    try:
        scene.render.engine = 'BLENDER_WORKBENCH'
    except TypeError:
        pass
    scene.render.resolution_x, scene.render.resolution_y = RES, int(RES * 0.72)
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGB'
    scene.display.render_aa = '8'
    sh = scene.display.shading
    sh.light = 'FLAT' if "--flat" in argv else 'STUDIO'
    sh.color_type = 'TEXTURE'
    sh.show_shadows = SHADOWS
    if SHADOWS:
        scene.display.shadow_shift = 0.05
        scene.display.shadow_focus = 0.4
        sh.shadow_intensity = 0.45
        scene.display.light_direction = (0.45, -0.35, 0.82)
    sh.show_cavity = False
    sh.background_type = 'VIEWPORT'
    sh.background_color = GROUND
    scene.view_settings.view_transform = 'Standard'
    me = bpy.data.meshes.new("pz_ground")
    gz = -(EXPORT_LIFT + GROUND_DROP) * U                  # GROUND_DROP: --script (0 for the stock car)
    me.from_pydata([(-400, -400, gz), (400, -400, gz), (400, 400, gz), (-400, 400, gz)], [], [(0, 1, 2, 3)])
    g = bpy.data.objects.new("pz_ground", me)
    scene.collection.objects.link(g)
    gm = bpy.data.materials.new("ground")
    gm.diffuse_color = GROUND + (1.0,)
    me.materials.append(gm)
    cam = bpy.data.objects.new("pz_cam", bpy.data.cameras.new("pz_cam"))
    cam.data.type = 'ORTHO'
    cam.data.clip_end = 3000
    scene.collection.objects.link(cam)
    scene.camera = cam
    return cam


def aim(cam, az_deg, target, scale):
    cam.data.type = 'ORTHO'
    az = math.radians(az_deg)
    d = Vector((math.cos(ELEV) * math.cos(az), math.cos(ELEV) * math.sin(az), math.sin(ELEV)))
    t = Vector((target[0], target[1], target[2] - EXPORT_LIFT)) * U    # target given in metres above ground
    cam.location = t + d * 600.0
    cam.rotation_euler = (-d).to_track_quat('-Z', 'Y').to_euler()
    cam.data.ortho_scale = scale * U


def aim_eye(cam, loc, look, fov_deg):
    """Perspective camera at a point in space (metres above ground), for the first / third person
    camera mods (Project Viewpoint): eye level outside the car and seats inside it."""
    cam.data.type = 'PERSP'
    cam.data.sensor_fit = 'HORIZONTAL'
    cam.data.angle = math.radians(fov_deg)
    cam.data.clip_start = 0.02 * U
    l = Vector((loc[0], loc[1], loc[2] - EXPORT_LIFT)) * U
    t = Vector((look[0], look[1], look[2] - EXPORT_LIFT)) * U
    cam.location = l
    cam.rotation_euler = (t - l).to_track_quat('-Z', 'Y').to_euler()


# --eye: views a first / third person camera gets (Project Viewpoint and the like). Eye level 1.65 m
# round the car at 5.5 m every 30 deg, a crouch ring at 0.9 m, and the cabin from the driver's
# and a rear passenger's eyes (left-hand drive: driver at x < 0, car faces +y).
EYE_FOV = 70.0
CABIN_FOV = 100.0
DRIVER_EYE = (-0.38, 0.08, 1.46)
REAR_EYE = (0.36, -0.70, 1.46)


def _seated_eye(hip):
    """The seated eye over a hip point (metres above ground, Blender axes), from backfill.seated_eye,
    the one constant pzview and the back-face filler share (2026-10-17: pzview put the driver's eye
    at 1.54 m, in the headliner, backfill at 1.19 m, under the A-pillar slits it was meant to find)."""
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    try:
        import backfill
        return backfill.seated_eye(hip)
    except Exception as exc:                     # noqa: BLE001  (a copy of pzview run on its own)
        print("PZVIEW warning: backfill.seated_eye not importable (%s): eye 0.67 m over the hip, 0.10 ahead" % exc)
        return (hip[0], hip[1] + 0.10, hip[2] + 0.67)


def seat_eyes():
    """Driver's and a rear passenger's eye from the vehicle script's passenger blocks. The `inside`
    offset is the seated character's HIP (Bip01) in MESH metres from the FBX origin (PZ axes: x across,
    y up, z forward; the wheel FrontLeft offset tells which way x runs), and the FBX origin stands
    EXPORT_LIFT above the ground. Before 2026-10-17 the origin was taken from the wheels (0.90) and the
    eye put 0.65 over it: 1.54 m, in the headliner. Falls back to the constants above."""
    path = os.path.join(MOD, "42", "media", "scripts", "vehicles", "HondaCRVGen1.txt")
    eyes = {}
    try:
        txt = open(path, encoding="utf-8").read()
        m = re.search(r"wheel\s+FrontLeft\s*\{.*?offset\s*=\s*([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)", txt, re.S)
        sx = -1.0 if m and float(m.group(1)) > 0 else 1.0           # blender: left = -x, car faces +y
        for who in ("FrontLeft", "RearRight"):
            m = re.search(r"passenger\s+%s\s*\{.*?position\s+inside\s*\{.*?offset\s*=\s*([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)" % who, txt, re.S)
            if m:
                x, y, z = (float(v) for v in m.groups())
                eyes[who] = _seated_eye((sx * x, z, y + EXPORT_LIFT))
    except OSError:
        pass
    return eyes.get("FrontLeft", DRIVER_EYE), eyes.get("RearRight", REAR_EYE)


# Crouch ring (2026-10-17, round-2 Viewpoint review): a player crouched beside the car, eye CROUCH_H, CROUCH_OFF
# off the body's box (half extents BOX_HALF) every 30 deg, aimed at a point 0.45 of the way to the box edge
# at CROUCH_AIM. The 4.5 m 'low' views missed the slits under the mirror feet and at the hood's front corners.
BOX_HALF = (0.90, 2.25)
CROUCH_H, CROUCH_OFF, CROUCH_AIM = 0.95, 1.3, 0.65
# Folded-bed cargo views (with --folded): a player kneeling / sitting on the fold-flat bed (backfill.CARGO_EYES)
# looking round the cargo bay and forward over the folded bench (R2-OC-4 was only found with --folded).
CARGO_EYE = (0.0, -1.45, 1.35)
INSIDE_TAGS = set()                # views from inside the car (seats, cargo): no cabin-through-the-shell count


def _box_r(c, s):
    """Distance from the car's centre to its box edge along the unit direction (c, s)."""
    tx = BOX_HALF[0] / abs(c) if abs(c) > 1e-6 else 1e9
    ty = BOX_HALF[1] / abs(s) if abs(s) > 1e-6 else 1e9
    return min(tx, ty)


def custom_eyes(path):
    """--eyes FILE.json: [[name, pose, [lx, ly, lz], [tx, ty, tz], fov], ...] (metres above ground,
    Blender axes: +x the car's right, +y forward), the reviewers' format (review2_viewpoint/mkeyes.py)."""
    import json
    with open(path, encoding="utf-8") as f:
        rows = json.load(f)
    return [(p, 0.0, None, 0.0, "eye_" + name, (tuple(loc), tuple(look), float(fov))) for name, p, loc, look, fov in rows]


def eye_views(poses):
    out = []
    driver, rear = seat_eyes()
    print("PZVIEW eyes: driver (%.2f, %.2f, %.2f) m, rear (%.2f, %.2f, %.2f) m" % (tuple(driver) + tuple(rear)))
    for p in poses:
        for az in range(0, 360, 30):
            a = math.radians(az)
            out.append((p, 0.0, None, 0.0, "%s_eye_%03d" % (p, az),
                        ((5.5 * math.cos(a), 5.5 * math.sin(a), 1.65), (0.0, 0.0, 0.9), EYE_FOV)))
        for az in (45, 135, 225, 315):
            a = math.radians(az)
            out.append((p, 0.0, None, 0.0, "%s_low_%03d" % (p, az),
                        ((4.5 * math.cos(a), 4.5 * math.sin(a), 0.9), (0.0, 0.0, 0.7), EYE_FOV)))
        for az in range(0, 360, 30):
            c, s = math.cos(math.radians(az)), math.sin(math.radians(az))
            r = _box_r(c, s)
            d = r + CROUCH_OFF
            out.append((p, 0.0, None, 0.0, "%s_crouch_%03d" % (p, az),
                        ((d * c, d * s, CROUCH_H), (0.45 * r * c, 0.45 * r * s, CROUCH_AIM), EYE_FOV)))
        if FOLDED:
            e = CARGO_EYE
            for name, d in (("fwd", (0, 3, -0.4)), ("left", (-3, -0.3, -0.5)), ("right", (3, -0.3, -0.5)),
                            ("back", (0, -3, -0.5)), ("down", (0.3, -0.6, -3)), ("up", (0, -0.4, 3))):
                out.append((p, 0.0, None, 0.0, "%s_cargo_%s" % (p, name),
                            (e, (e[0] + d[0], e[1] + d[1], e[2] + d[2]), CABIN_FOV)))
                INSIDE_TAGS.add(out[-1][4])
        passenger = (-driver[0], driver[1], driver[2])      # the other front seat (the cars are symmetric)
        for who, e in (("driver", driver), ("passenger", passenger), ("rear", rear)):
            for name, d in (("fwd", (0, 3, -0.3)), ("left", (-3, 0.3, -0.4)), ("right", (3, 0.3, -0.4)),
                            ("back", (0, -3, -0.2)), ("up", (0, 0.6, 3)), ("down", (0.4, 0.6, -3))):
                out.append((p, 0.0, None, 0.0, "%s_%s_%s" % (p, who, name),
                            (e, (e[0] + d[0], e[1] + d[1], e[2] + d[2]), CABIN_FOV)))
                INSIDE_TAGS.add(out[-1][4])
    return out


def shoot(path, cull):
    scene = bpy.context.scene
    scene.display.shading.show_backface_culling = cull
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    img = bpy.data.images.load(path, check_existing=False)
    w, h = img.size
    a = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, 4)
    bpy.data.images.remove(img)
    return a


def shoot_cabin(path):
    """ID render of the same view: the interior model green, everything else grey, flat light,
    culled, glass opaque as Workbench draws it. In the SHUT pose no cabin texel can legitimately
    reach the camera (the windows are opaque here), so every green pixel is a slit in the shell
    that shows the cabin: dark in the real render, invisible to the ground test, and in game the
    place a character standing against the car shows through (the sill slit, 2026-10-11)."""
    scene = bpy.context.scene
    sh = scene.display.shading
    saved = (sh.color_type, sh.light, sh.show_shadows)
    sh.color_type, sh.light, sh.show_shadows = 'OBJECT', 'FLAT', False
    colours = {}
    for o in scene.objects:
        if o.type != 'MESH':
            continue
        colours[o.name] = tuple(o.color)
        o.color = (0.0, 1.0, 0.0, 1.0) if "Interior" in str(o.get("pz_label", "")) else (0.5, 0.5, 0.5, 1.0)
    a = shoot(path, True)
    for o in scene.objects:
        if o.name in colours:
            o.color = colours[o.name]
    sh.color_type, sh.light, sh.show_shadows = saved
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    hit = (g > 0.6) & (r < 0.3) & (b < 0.3)
    return int(hit.sum()), a


def is_ground(a):
    """Magenta at any shading (studio light darkens the ground plane): red and blue equal and well
    above green. Nothing on the car is purple."""
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    return (r > 0.25) & (b > 0.25) & (np.abs(r - b) < 0.08) & (g < 0.45 * r)


def _cast_drawn(scene, dg, origin, d, distance=1.0e9):
    """scene.ray_cast that only meets what the view draws. Blender's ray_cast also hits hide_render
    objects: every model the script does not reference, the parts --acc leaves out (the armour arch
    guards over the wheel arches, the bull bar over the bay) and the glass twins; a probe of a bare
    car's leak pixel named 'crvgen1_acc_armour_arch_fr' instead of the ground (2026-10-13)."""
    travelled = 0.0
    for _ in range(64):
        hit, loc, n, idx, ob, m = scene.ray_cast(dg, origin, d, distance=distance - travelled)
        if not hit or not ob.hide_render:
            return hit, loc, n, idx, ob, m
        step = (loc - origin).length + 1.0e-5
        travelled += step
        if travelled >= distance:
            break
        origin = loc + d * 1.0e-5
    return False, None, None, -1, None, None


def _front_twin(dg, loc, fwd, tol=0.004):
    """(label, face) of a drawn face facing the camera within tol (scene units, 0.4 mm) of loc, or None.
    A second ray cast from just before a culled face returns one of two coincident faces at random:
    the round-2 review read a hood corner's backfill copy (face 492, flipped f68) as a hole there."""
    from mathutils.bvhtree import BVHTree
    for ob in bpy.context.scene.objects:
        if ob.type != 'MESH' or ob.hide_render or ob.name == "pz_ground":
            continue
        M = ob.matrix_world
        tree = BVHTree.FromObject(ob, dg)
        nm = M.inverted().transposed().to_3x3()
        flip = -1.0 if M.to_3x3().determinant() < 0 else 1.0
        for _co, n, idx, _d in tree.find_nearest_range(M.inverted() @ loc, tol / max(M.to_scale().length / 1.7320508, 1e-9)):
            if idx is not None and flip * (nm @ n).dot(fwd) < 0:
                return ob.get("pz_label", ob.name), idx
    return None


def probe(cam, px, py, tag):
    """What does the game draw at pixel (px, py) of the last view? Ray through the pixel, skipping
    back faces (the game culls them). Reports the model, face, its position in metres above ground
    and its normal, so a stray piece can be found in the working .blend."""
    scene = bpy.context.scene
    w, h = scene.render.resolution_x, scene.render.resolution_y
    rot = cam.matrix_world.to_3x3()
    fwd, right, up = rot @ Vector((0, 0, -1)), rot @ Vector((1, 0, 0)), rot @ Vector((0, 1, 0))
    if cam.data.type == 'PERSP':
        sw = cam.data.sensor_width
        sx = ((px + 0.5) / w - 0.5) * sw
        sy = (0.5 - (py + 0.5) / h) * sw * h / w
        origin = cam.location.copy()
        fwd = (fwd * cam.data.lens + right * sx + up * sy).normalized()
    else:
        s = cam.data.ortho_scale
        sx = ((px + 0.5) / w - 0.5) * s
        sy = (0.5 - (py + 0.5) / h) * s * h / w
        origin = cam.location + right * sx + up * sy
    dg = bpy.context.evaluated_depsgraph_get()
    if "--probe-all" in argv:                  # every face along the ray, front (F) and back (B), to the ground
        hits, o2 = [], origin.copy()
        for _ in range(16):
            hit, loc, n, idx, ob, _m = _cast_drawn(scene, dg, o2, fwd)
            if not hit:
                break
            m = Vector((loc.x, loc.y, loc.z)) / U + Vector((0, 0, EXPORT_LIFT))
            hits.append("%s %s f%d (%.3f,%.3f,%.3f) n(%.2f,%.2f,%.2f)" % ("B" if n.dot(fwd) > 0 else "F",
                        ob.get("pz_label", ob.name), idx, m.x, m.y, m.z, n.x, n.y, n.z))
            if ob.name == "pz_ground":
                break
            o2 = loc + fwd * 0.0005
        print("PROBEALL %s (%d,%d): %s" % (tag, px, py, " | ".join(hits)))
    for _ in range(40):
        hit, loc, n, idx, ob, _m = _cast_drawn(scene, dg, origin, fwd)
        if not hit:
            print("PROBE %s (%d,%d): nothing" % (tag, px, py))
            return
        if n.dot(fwd) > 0:                     # back face: culled in game, look past it
            m = Vector((loc.x, loc.y, loc.z)) / U + Vector((0, 0, EXPORT_LIFT))
            # a backfill copy sits ON the culled face (or the culled face is the copy of a drawn one):
            # any drawn front face through this point means the game draws something here after all
            twin = ""
            tw = _front_twin(dg, loc, fwd)
            if tw:
                twin = "  [backfilled: %s face %d drawn here]" % tw
            print("PROBE %s (%d,%d):   culled back face %s face %d at (%.3f, %.3f, %.3f) m, normal (%.2f, %.2f, %.2f)%s"
                  % (tag, px, py, ob.get("pz_label", ob.name), idx, m.x, m.y, m.z, n.x, n.y, n.z, twin))
            if tw:                             # the coincident drawn face is what the game shows here
                print("PROBE %s (%d,%d): %s face %d at (%.3f, %.3f, %.3f) m (coincident with the culled face)"
                      % (tag, px, py, tw[0], tw[1], m.x, m.y, m.z))
                return
            origin = loc + fwd * 0.001
            continue
        lab = ob.get("pz_label", ob.name)
        m = Vector((loc.x, loc.y, loc.z)) / U + Vector((0, 0, EXPORT_LIFT))
        print("PROBE %s (%d,%d): %s face %d at (%.3f, %.3f, %.3f) m, normal (%.2f, %.2f, %.2f)"
              % (tag, px, py, lab, idx, m.x, m.y, m.z, n.x, n.y, n.z))
        return


def save(path, a):
    h, w = a.shape[:2]
    img = bpy.data.images.new("pz_out", w, h)
    img.pixels = a.ravel().tolist()
    img.filepath_raw = path
    img.file_format = 'PNG'
    img.save()
    bpy.data.images.remove(img)


def save_gz(src, dst, k):
    """The render resampled by k (game px/m over render px/m): what the player's screen gets."""
    img = bpy.data.images.load(src, check_existing=False)
    w, h = img.size
    img.scale(max(1, round(w * k)), max(1, round(h * k)))
    img.filepath_raw = dst
    img.file_format = 'PNG'
    img.save()
    bpy.data.images.remove(img)


def main():
    os.makedirs(OUT, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    vehicle_mod = find_script()
    drawn, _anims = build(vehicle_mod)
    arms = [arm for (_g, arm) in _imported.values()]
    dm = drive_map(vehicle_mod)                             # the game's part / player tree
    for own, tracks in sorted(dm["tracks"].items()):
        print("PZVIEW player %s: " % own + "; ".join("%s %s [%s]" % (p, "/".join(sorted(c)), ", ".join(m) or "all bones")
                                                       for p, c, m in tracks))
    drawn = check_driven(drawn, dm, arms)                   # hides what the game draws nowhere
    print("PZVIEW drawn:", ", ".join("%s<-%s" % (o.name, o.data.name) for o in drawn))
    print("PZVIEW textures: Linear sampling, cap %s, game zoom %s px/m; %s"
          % (CAP or "none", GZ or "off", ", ".join("%s %dx%d" % (os.path.basename(p), m.node_tree.nodes.active.image.size[0],
                                                                 m.node_tree.nodes.active.image.size[1]) for p, m in _mats.items())))
    if DAMAGE is not None:
        damage_composite(drawn, vehicle_mod)
    cam = setup_render()
    twins = glass_twins(drawn, vehicle_mod)
    views = []
    target = (0.0, 0.0, 0.75)
    for p in POSES:
        for az in AZIMUTHS:
            views.append((p, az, target, SCALE, "%s_%03d" % (p, int(az))))
    if "--close" in argv:                                   # close-ups the user's screenshots keep hitting
        for name, p, az, tgt, sc in (("wheel_front_right", "shut", 20, (0.85, 1.31, 0.35), 1.6),
                                    ("wheel_front_left", "shut", 160, (-0.85, 1.31, 0.35), 1.6),
                                    ("wheel_rear_left", "shut", 200, (-0.85, -1.31, 0.35), 1.6),
                                    ("wheel_rear_right", "shut", 340, (0.85, -1.31, 0.35), 1.6),
                                    ("bay_open", "open", 135, (0.0, 1.45, 0.85), 2.6),
                                    ("gate_open", "open", 250, (0.2, -2.4, 0.9), 3.2),
                                    ("door_open_left", "open", 200, (-1.0, 0.0, 0.9), 3.6),
                                    ("roof_left", "shut", 190, (-0.6, -0.3, 1.45), 2.6),
                                    ("rear_bumper", "open", 300, (0.3, -2.2, 0.6), 2.4)):
            views.append((p, az, tgt, sc, "close_" + name))
    # --view name,pose,az,x,y,z,scale  (target in metres above ground, repeatable); --only skips the
    # standard ring so a probe run is quick
    if "--only" in argv:
        views = []
    for i, a in enumerate(argv):
        if a == "--view" and i + 1 < len(argv):
            n, p, az, x, y, z, sc = argv[i + 1].split(",")
            views.append((p, float(az), (float(x), float(y), float(z)), float(sc), "view_" + n))
    views = [v + (None,) for v in views]
    if "--eyes" in argv:                                    # a custom list of perspective views (custom_eyes)
        views += custom_eyes(_arg("--eyes", ""))
    elif "--eye" in argv:                                   # first / third person camera mods
        views += eye_views(POSES)
    if FRAC != 1.0:
        print("PZVIEW --frac %.3f: every opening clip at %.0f %% of its travel" % (FRAC, FRAC * 100))
    current = None
    for p, az, tgt, sc, tag, eye in views:
        if p != current:
            pose(arms, dm, p)
            bay = bay_models(drawn, p)
            if any(ob.get("pz_part") == BAY_PART for ob in drawn):
                print("PZVIEW pose %s: engine bay %s" % (p, bay))
            current = p
        if eye is not None:
            aim_eye(cam, *eye)
        else:
            aim(cam, az, tgt, sc)
        path = os.path.join(OUT, tag + ".png")
        culled = shoot(path, True)                          # what the game draws
        if GZ and sc:                                       # orthographic views only: sc metres across RES px
            save_gz(path, os.path.join(OUT, tag + "_gz.png"), GZ * sc / RES)
        for tw in twins:
            tw.hide_render = False
        tmp_a = os.path.join(OUT, "_tmp_%s_a.png" % tag)       # one file per render: Windows can hold
        tmp_b = os.path.join(OUT, "_tmp_%s_b.png" % tag)       # a just-read PNG open for a moment
        culled_g = shoot(tmp_a, True)
        both = shoot(tmp_b, False)
        for t in (tmp_a, tmp_b):
            try:
                os.remove(t)
            except OSError:
                pass
        for tw in twins:
            tw.hide_render = True
        leak = is_ground(culled_g) & ~is_ground(both)
        n = int(leak.sum())
        if n:
            out = culled.copy()
            out[leak] = (0.0, 1.0, 0.0, 1.0)
            save(os.path.join(OUT, tag + "_leak.png"), out)
        print("PZVIEW %-28s leak px %6d" % (tag, n))
        inside = tag in INSIDE_TAGS                         # eye_views' seat and cargo views
        if p == "shut" and not inside:                      # cabin seen through the shut shell (from outside)
            tmp_c = os.path.join(OUT, "_tmp_%s_c.png" % tag)
            c, ida = shoot_cabin(tmp_c)
            try:
                os.remove(tmp_c)
            except OSError:
                pass
            if c:
                save(os.path.join(OUT, tag + "_cabin.png"), ida)    # green = cabin seen through the shell
            print("PZVIEW %-28s cabin px %5d" % (tag, c))
        for i, a in enumerate(argv):                    # --probe view_name,px,py (repeatable)
            if a == "--probe" and i + 1 < len(argv):
                vname, px, py = argv[i + 1].split(",")
                if vname == tag:
                    probe(cam, int(px), int(py), tag)
    for fn in os.listdir(OUT):
        if fn.startswith("_tmp"):
            try:
                os.remove(os.path.join(OUT, fn))
            except OSError:
                pass
    print("PZVIEW DONE")


if __name__ == "__main__":
    main()
