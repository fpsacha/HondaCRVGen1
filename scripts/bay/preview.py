r"""
Fast look at the engine bay v2 while it is being modelled: builds the groups into the last built car
(parts_kotris.blend, opened read-only: never saved), audits the envelope and renders EEVEE views with
the hood off. Material colours as authored (no bake, no game lighting): judge shapes, placement,
proportions and values against the photos in blender/references/engine_bay.

    blender -b blender\import\parts_kotris.blend --python scripts\bay\preview.py -- --out <abs dir>
            [--groups engine,intake] [--solo] [--views photo,photo_r,photo_l,top,game_fr,game_fl,side_r,side_l]
            [--res 1000] [--samples 16]

--groups: the groups whose part list and triangle report are printed (default all). Every group is
built for context unless --solo (only --groups). A group whose module fails is skipped with its
traceback, so one module mid-edit never blocks another's preview.
Writes <out>/<view>.png. --out must be absolute.
"""
import importlib
import math
import os
import sys
import traceback

import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
S = os.path.dirname(HERE)
if S not in sys.path:
    sys.path.insert(0, S)
import bay  # noqa: E402
from bay import envelope, kit  # noqa: E402

ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def _arg(name, default=None):
    if name in ARGS:
        i = ARGS.index(name)
        return ARGS[i + 1] if i + 1 < len(ARGS) and not ARGS[i + 1].startswith("--") else True
    return default


OUT = _arg("--out")
WANT = [g for g in (_arg("--groups") or ",".join(bay.GROUPS)).split(",") if g]
SOLO = bool(_arg("--solo"))
VIEWS = (_arg("--views") or "photo,photo_r,photo_l,top,game_fr,game_fl").split(",")
RES = int(_arg("--res", 1000))
SAMPLES = int(_arg("--samples", 16))
TARGET = Vector((0.0, 1.32, 0.80))
# name -> (camera location, ortho scale or None, lens mm)
CAMS = {
    "photo":   (Vector((0.0, 2.70, 1.95)), None, 24),        # standing at the bumper, as samarins / jpc
    "photo_r": (Vector((1.00, 2.45, 1.85)), None, 26),       # front passenger corner (lhd_06)
    "photo_l": (Vector((-1.00, 2.45, 1.85)), None, 26),      # front driver corner
    "side_r":  (Vector((1.55, 1.32, 1.70)), None, 28),       # over the right fender
    "side_l":  (Vector((-1.55, 1.32, 1.70)), None, 28),
    "top":     (Vector((0.0, 1.40, 3.0)), 1.45, None),
    # close-ups (a 4th item: the point looked at): the distributor end, the tie bar from the bumper
    "dist":    (Vector((0.62, 1.95, 1.35)), None, 55, Vector((0.20, 1.38, 0.92))),
    "dist_top": (Vector((0.30, 1.75, 1.60)), None, 55, Vector((0.17, 1.38, 0.93))),
    "tiebar":  (Vector((0.0, 2.75, 1.50)), None, 40, Vector((0.0, 1.85, 0.86))),
}
for name, az in (("game_fr", 45.0), ("game_fl", 135.0), ("game_rr", -45.0), ("game_rl", -135.0)):
    a, el = math.radians(az), math.radians(30.0)              # PZ 2:1 dimetric, 30 degrees down
    CAMS[name] = (TARGET + 6.0 * Vector((math.cos(el) * math.cos(a), math.cos(el) * math.sin(a), math.sin(el))), 2.4, None)


def clear_old():
    for name in ("engine_block", "engine_block_hi", "engine_block_full"):
        ob = bpy.data.objects.get(name)
        if ob is not None:
            bpy.data.objects.remove(ob, do_unlink=True)
    for ob in bpy.data.objects:
        if ob.name.startswith("acc_") or ob.name.endswith("_hi") or ob.name.endswith("_full"):
            ob.hide_render = True
            ob.hide_set(True)


def stand_in_towers(col):
    walls = bpy.data.objects.get("bay_walls")
    if walls is not None and walls.get("towers"):
        return None
    mat = bpy.data.materials.get("Body") or kit.material("Grey")
    parts = []
    for tx, ty in envelope.TOWERS:
        parts.append(kit.lathe_data([(r, z - envelope.TOWER_PROFILE[0][1]) for r, z in envelope.TOWER_PROFILE],
                                    (tx, ty, envelope.TOWER_PROFILE[0][1]), (0, 0, 1), 16))
    v, f = kit.merge(*parts)
    me = bpy.data.meshes.new("_preview_towers")
    me.from_pydata(v, [], f)
    me.materials.append(mat)
    ob = bpy.data.objects.new("_preview_towers", me)
    col.objects.link(ob)
    return ob


def build(col):
    b = kit.Bay(col)
    kit.register_decals({"DecalHoodPad": ("hood_pad.png", ("x", -0.62, 0.62), ("y", 0.98, 1.86), "Grey")})
    built = []
    for g in bay.GROUPS:
        if SOLO and g not in WANT:
            continue
        try:
            mod = importlib.import_module("bay." + g)
            kit.register_decals(getattr(mod, "DECALS", {}))
            b.group = g
            n0 = len(b.objs)
            mod.build(b)
            built.append(g)
            budget = getattr(mod, "BUDGET", None)
            t = b.tris(g)
            print("GROUP %-7s %3d parts, %5d tris%s" % (g, len(b.objs) - n0, t,
                                                      "" if budget is None else " (budget %d%s)" % (budget, ", OVER" if t > budget else "")))
        except Exception:                                            # noqa: BLE001
            print("GROUP %s FAILED:" % g)
            traceback.print_exc()
            b.objs = [o for o in b.objs if o.get("bay_group") != g]
    b.report()
    for g in WANT:
        if g in built:
            b.report_parts(g)
    envelope.audit([o for o in b.objs if o.get("bay_group") in WANT])
    return b


def setup_render():
    sc = bpy.context.scene
    for eng in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
        try:
            sc.render.engine = eng
            break
        except TypeError:
            continue
    try:
        sc.eevee.taa_render_samples = SAMPLES
    except AttributeError:
        pass
    try:
        sc.view_settings.view_transform = 'Standard'
    except TypeError:
        pass
    sc.render.resolution_x = RES
    sc.render.resolution_y = int(RES * 0.68)
    sc.render.resolution_percentage = 100
    sc.render.film_transparent = False
    world = sc.world or bpy.data.worlds.new("preview")
    sc.world = world
    world.use_nodes = True
    bg = next((n for n in world.node_tree.nodes if n.type == 'BACKGROUND'), None)
    if bg is not None:
        bg.inputs[0].default_value = (0.42, 0.44, 0.47, 1.0)
        bg.inputs[1].default_value = 1.0
    for ob in list(bpy.data.objects):
        if ob.type == 'LIGHT' or ob.name.startswith("_preview_cam"):
            bpy.data.objects.remove(ob, do_unlink=True)
    sun = bpy.data.lights.new("_preview_sun", 'SUN')
    sun.energy = 2.2
    sun.angle = math.radians(8)
    so = bpy.data.objects.new("_preview_sun", sun)
    sc.collection.objects.link(so)
    so.rotation_euler = (math.radians(35), 0.0, math.radians(160))      # high, from the front left
    cam = bpy.data.cameras.new("_preview_cam")
    co = bpy.data.objects.new("_preview_cam", cam)
    sc.collection.objects.link(co)
    sc.camera = co
    return co


def render(co, view):
    loc, ortho, lens = CAMS[view][:3]
    aim = CAMS[view][3] if len(CAMS[view]) > 3 else TARGET
    cam = co.data
    co.location = loc
    look = (aim if view != "top" else Vector((loc.x, loc.y, 0.0))) - loc
    co.rotation_euler = look.to_track_quat('-Z', 'Y').to_euler()
    if ortho:
        cam.type = 'ORTHO'
        cam.ortho_scale = ortho
    else:
        cam.type = 'PERSP'
        cam.lens = lens
    cam.clip_start, cam.clip_end = 0.05, 50.0
    bpy.context.scene.render.filepath = os.path.join(OUT, view + ".png")
    bpy.ops.render.render(write_still=True)
    print("PREVIEW wrote", bpy.context.scene.render.filepath)


def main():
    if not OUT or not os.path.isabs(OUT):
        raise SystemExit("preview: --out must be an absolute directory")
    os.makedirs(OUT, exist_ok=True)
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    clear_old()
    ref = bpy.data.objects.get("body")
    col = ref.users_collection[0] if ref else bpy.context.scene.collection
    stand_in_towers(col)
    build(col)
    hood = bpy.data.objects.get("hood")
    if hood is not None:
        hood.hide_render = True
    co = setup_render()
    for v in VIEWS:
        if v in CAMS:
            render(co, v)
        else:
            print("preview: no view %r (%s)" % (v, ", ".join(CAMS)))


main()
