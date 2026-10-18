r"""
Fast geometry check of the working parts (no bake): material-coloured Workbench renders with the
game's culling from the game's 30-degree camera, shut and open.

    blender -b blender\import\parts_kotris.blend --python scripts\geocheck.py -- [--out DIR]
            [--view name,pose,az,x,y,z,scale ...] [--only]

Colours: paint white, inner paint (BodyInner) pale blue, door/gate trim tan, carpet brown, seats
blue, black plastics dark grey, glass slate, lamps orange, chrome silver, GENERATED faces red
(solidify shells/rims, interior closures) so anything poking through shows at a glance. Prints
`GEOCHECK <view> red px <n>`: on the shut views red pixels mean generated geometry is visible on
the closed car, which must be zero.
"""
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Vector

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(globals().get("__file__") or os.path.join("scripts", "_"))))
S = os.path.join(ROOT, "scripts")
if S not in sys.path:
    sys.path.append(S)
import rig_vehicle  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
OUT = argv[argv.index("--out") + 1] if "--out" in argv else os.path.join(ROOT, "blender", "geocheck")
ELEV = math.radians(30.0)
RED = (1.0, 0.0, 0.0, 1.0)
COLOURS = {
    "Body": (0.92, 0.92, 0.92), "BodyInner": (0.62, 0.78, 0.95), "Interieur": (0.80, 0.68, 0.50),
    "Interieur_sol": (0.40, 0.30, 0.22), "Siege": (0.30, 0.42, 0.75), "Siege_2": (0.25, 0.55, 0.60),
    "Body_plastique": (0.35, 0.35, 0.37), "Plastique_noir": (0.20, 0.20, 0.22), "Partie_noir": (0.12, 0.12, 0.13),
    "Dessous": (0.15, 0.15, 0.15), "Vitre": (0.35, 0.45, 0.55), "Vitre_noir": (0.25, 0.30, 0.35),
    "Chrome": (0.75, 0.75, 0.78), "Jante": (0.60, 0.60, 0.62), "Pneu": (0.08, 0.08, 0.08),
    "HubCap": (0.85, 0.85, 0.88), "Rotor": (0.45, 0.45, 0.47), "RimWell": (0.30, 0.30, 0.32), "ArchLiner": (0.10, 0.10, 0.10),
    "AccSteel": (0.95, 0.72, 0.10),                      # accessories (build_accessories.py), yellow
    "AccPlate": (0.80, 0.80, 0.55), "AccSkid": (0.70, 0.70, 0.45), "AccLens": (0.60, 0.85, 1.0), "AccTable": (0.75, 0.75, 0.55), "AccChrome": (0.85, 0.85, 0.92),
    "AccCanvas": (0.75, 0.70, 0.35), "AccTarp": (0.45, 0.60, 0.95),   # rack cargo: still the accessory (yellow) family
    "AccVinyl": (0.70, 0.62, 0.30),                                    # the spare cover
    "AccTote": (0.55, 0.52, 0.30), "AccLid": (0.98, 0.85, 0.30), "AccStrap": (0.98, 0.55, 0.20),
}
LAMP = (1.0, 0.6, 0.1)


def colour_materials():
    """Split every mesh's generated faces onto a red material, colour the rest by material."""
    red = bpy.data.materials.new("GEN_RED")
    red.diffuse_color = RED
    for m in bpy.data.materials:
        if m is red:
            continue
        c = COLOURS.get(m.name)
        if c is None and (m.name.startswith("Feux") or m.name.startswith("Phare") or m.name.startswith("Reflect")):
            c = LAMP
        m.diffuse_color = (c or (0.55, 0.55, 0.55)) + (1.0,)
    for o in bpy.data.objects:
        if o.type != 'MESH':
            continue
        me = o.data
        g = me.attributes.get("gen")
        if g is None:
            continue
        vals = [0] * len(me.polygons)
        g.data.foreach_get("value", vals)
        if not any(v in (1, 2, 3) for v in vals):
            continue
        me.materials.append(red)
        ri = len(me.materials) - 1
        for p, v in zip(me.polygons, vals):
            if v in (1, 2, 3):
                p.material_index = ri


def setup():
    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.render.resolution_x, scene.render.resolution_y = 1400, 1008
    scene.render.image_settings.file_format = 'PNG'
    scene.display.render_aa = '8'
    sh = scene.display.shading
    sh.light = 'STUDIO'
    sh.color_type = 'MATERIAL'
    sh.show_backface_culling = True
    sh.show_shadows = False
    sh.background_type = 'VIEWPORT'
    sh.background_color = (0.30, 0.30, 0.30)
    scene.view_settings.view_transform = 'Standard'
    cam = bpy.data.objects.new("gc_cam", bpy.data.cameras.new("gc_cam"))
    cam.data.type = 'ORTHO'
    cam.data.clip_end = 300
    scene.collection.objects.link(cam)
    scene.camera = cam
    for n in ("base",):
        o = bpy.data.objects.get(n)
        if o:
            o.hide_render = True
    return cam


def aim(cam, az, target, scale):
    a = math.radians(az)
    d = Vector((math.cos(ELEV) * math.cos(a), math.cos(ELEV) * math.sin(a), math.sin(ELEV)))
    cam.location = Vector(target) + d * 40.0
    cam.rotation_euler = (-d).to_track_quat('-Z', 'Y').to_euler()
    cam.data.ortho_scale = scale


def probe(cam, px, py, tag):
    """Name the face the game would draw at pixel (px, py): first front-facing hit along the ray."""
    scene = bpy.context.scene
    w, h = scene.render.resolution_x, scene.render.resolution_y
    rot = cam.matrix_world.to_3x3()
    fwd, right, up = rot @ Vector((0, 0, -1)), rot @ Vector((1, 0, 0)), rot @ Vector((0, 1, 0))
    s = cam.data.ortho_scale
    origin = cam.location + right * (((px + 0.5) / w - 0.5) * s) + up * ((0.5 - (py + 0.5) / h) * s * h / w)
    dg = bpy.context.evaluated_depsgraph_get()
    for _ in range(16):
        hit, loc, n, idx, ob, _m = scene.ray_cast(dg, origin, fwd)
        if not hit:
            print("PROBE %s (%d,%d): nothing" % (tag, px, py))
            return
        if n.dot(fwd) > 0:
            origin = loc + fwd * 0.0005
            continue
        me = ob.evaluated_get(dg).to_mesh()
        mat = "-"
        island = None
        if me is not None and idx < len(me.polygons):
            mi = me.polygons[idx].material_index
            mat = me.materials[mi].name if mi < len(me.materials) and me.materials[mi] else "-"
        ob.evaluated_get(dg).to_mesh_clear()
        p = ob.data.polygons[idx] if idx < len(ob.data.polygons) else None
        rest = tuple(round(c, 3) for c in p.center) if p else None
        print("PROBE %s (%d,%d): %s face %d mat %s posed at (%.3f, %.3f, %.3f), rest centre %s"
              % (tag, px, py, ob.name, idx, mat, loc.x, loc.y, loc.z, rest))
        return


def red_pixels(path):
    img = bpy.data.images.load(path, check_existing=False)
    w, h = img.size
    a = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, 4)
    bpy.data.images.remove(img)
    return int(((a[..., 0] > 0.5) & (a[..., 1] < 0.12) & (a[..., 2] < 0.12)).sum())


def main():
    os.makedirs(OUT, exist_ok=True)
    arm = rig_vehicle.build()
    colour_materials()
    cam = setup()
    views = []
    if "--only" not in argv:
        for pose in ("shut", "open"):
            for az in range(0, 360, 45):
                views.append((pose, az, (0.0, 0.0, 0.8), 6.0, "%s_%03d" % (pose, az)))
    for i, a in enumerate(argv):
        if a == "--view" and i + 1 < len(argv):
            n, p, az, x, y, z, sc = argv[i + 1].split(",")
            views.append((p, float(az), (float(x), float(y), float(z)), float(sc), "view_" + n))
    opened = tuple(c for c in rig_vehicle.CLIPS if c.endswith("_opening") and not c.startswith("window"))
    cur = None
    for pose, az, tgt, sc, tag in views:
        if pose != cur:
            rig_vehicle.pose(arm, opened if pose == "open" else ())
            cur = pose
        aim(cam, az, tgt, sc)
        path = os.path.join(OUT, tag + ".png")
        bpy.context.scene.render.filepath = path
        bpy.ops.render.render(write_still=True)
        print("GEOCHECK %-24s red px %6d" % (tag, red_pixels(path)))
        for i, a in enumerate(argv):                    # --probe view_name,px,py
            if a == "--probe" and i + 1 < len(argv):
                vn, px, py = argv[i + 1].split(",")
                if vn == tag:
                    probe(cam, int(px), int(py), tag)
    print("GEOCHECK DONE")


main()
