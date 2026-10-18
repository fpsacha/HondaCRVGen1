r"""
See-through audit: find every place the single-sided kotris skin lets the ground show through.

    blender -b blender\import\parts_kotris.blend --python scripts\leak_test.py -- [--out DIR] [--step 30] [--scale 6]

The game culls back faces, so any skin seen from its inner side vanishes (open hood: the fender
pocket, the lamp backs; open tailgate: the gate's inner face). Workbench renders the parts over a
magenta ground from the game's camera (30 degrees elevation, every --step degrees of azimuth),
once with back-face culling and once without. Magenta that shows only with culling on is ground
seen through the car: a leak. Two poses: everything shut, and hood + doors + tailgate open.

Writes leak_<pose>_<az>.png (culled render, leaks painted green) for every view with leaks and
prints one `LEAK pose=... az=... px=...` line per view plus `LEAK TOTAL ...`. Exit code 0 always;
the caller reads the totals.
"""
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Vector

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(globals().get("__file__") or os.path.join("scripts", "_"))))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.append(SCRIPTS)
import rig_vehicle  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def _arg(flag, default):
    return argv[argv.index(flag) + 1] if flag in argv else default


OUT = _arg("--out", os.path.join(ROOT, "blender", "leaks"))
STEP = int(_arg("--step", "30"))
ATTR = int(_arg("--attr", "0"))                  # >0: ray-cast up to this many leak pixels per view and name the culprits
ONLY = _arg("--views", "")                        # "open:210,shut:000" limits the run to those views
SCALE = float(_arg("--scale", "6.0"))
RES = (int(_arg("--res", "960")), int(int(_arg("--res", "960")) * 3 / 4))
ELEV = math.radians(30)          # PZ: 2:1 dimetric, the camera looks down at 30 degrees
TARGET = Vector((0.0, 0.0, 0.7))
OPEN_CLIPS = tuple(c for c in rig_vehicle.CLIPS if c.endswith("_opening") and not c.startswith("window"))
COLOURS = {                       # object colours in the diagnostic renders
    "body": (0.85, 0.85, 0.85), "hood": (0.9, 0.9, 0.95), "trunk": (0.9, 0.9, 0.95), "trunk_top": (0.3, 0.4, 0.5),
    "bay_walls": (0.55, 0.7, 0.9), "arch_liners": (0.45, 0.3, 0.2), "engine_block": (0.4, 0.4, 0.4),
    "interior": (0.75, 0.6, 0.4), "antenna": (0.2, 0.2, 0.2),
}
GROUND = (1.0, 0.0, 1.0)


def setup():
    scene = bpy.context.scene
    arm = rig_vehicle.build()
    for n in ("base",):
        ob = bpy.data.objects.get(n)
        if ob:
            bpy.data.objects.remove(ob, do_unlink=True)
    for ob in bpy.data.objects:
        if ob.type != 'MESH':
            continue
        key = ob.name if ob.name in COLOURS else ("hood" if ob.name.startswith(("door", "window")) else
                                                  "engine_block" if ob.name.startswith("wheel") else None)
        c = COLOURS.get(key, (0.6, 0.6, 0.6))
        ob.color = c + (1.0,)
        if ob.name.startswith("window_"):
            # door glass is drawn semi-transparent by the game from either side, so seeing the world
            # through a far window is not a leak: make the test copy double-sided (flipped duplicate)
            import bmesh
            bm = bmesh.new()
            bm.from_mesh(ob.data)
            ret = bmesh.ops.duplicate(bm, geom=list(bm.faces))
            bmesh.ops.reverse_faces(bm, faces=[g for g in ret["geom"] if isinstance(g, bmesh.types.BMFace)])
            bm.to_mesh(ob.data)
            bm.free()
    # ground: a big magenta plane at z 0 (tyres sit on z 0)
    me = bpy.data.meshes.new("leak_ground")
    me.from_pydata([(-30, -30, 0), (30, -30, 0), (30, 30, 0), (-30, 30, 0)], [], [(0, 1, 2, 3)])
    ground = bpy.data.objects.new("leak_ground", me)
    scene.collection.objects.link(ground)
    ground.color = GROUND + (1.0,)
    cam_data = bpy.data.cameras.new("leak_cam")
    cam_data.type = 'ORTHO'
    cam_data.ortho_scale = SCALE
    cam_data.clip_end = 200
    cam = bpy.data.objects.new("leak_cam", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.render.resolution_x, scene.render.resolution_y = RES
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGB'
    scene.display.render_aa = 'OFF'
    sh = scene.display.shading
    sh.light = 'FLAT'
    sh.color_type = 'OBJECT'
    sh.show_shadows = False
    sh.show_cavity = False
    sh.show_xray = False
    sh.background_type = 'VIEWPORT'
    sh.background_color = (0.0, 0.0, 0.0)
    scene.view_settings.view_transform = 'Standard'
    scene.view_settings.look = 'None'
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0
    return arm, cam


def aim(cam, az_deg):
    az = math.radians(az_deg)
    d = Vector((math.cos(ELEV) * math.cos(az), math.cos(ELEV) * math.sin(az), math.sin(ELEV)))
    cam.location = TARGET + d * 40.0
    cam.rotation_euler = (-d).to_track_quat('-Z', 'Y').to_euler()


def render(path, cull):
    scene = bpy.context.scene
    scene.display.shading.show_backface_culling = cull
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    img = bpy.data.images.load(path, check_existing=False)
    w, h = img.size
    a = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, 4)
    bpy.data.images.remove(img)
    return a


def magenta(a):
    return (a[..., 0] > 0.8) & (a[..., 1] < 0.2) & (a[..., 2] > 0.8)


def save(path, a):
    h, w = a.shape[:2]
    img = bpy.data.images.new("leak_out", w, h, alpha=True)
    img.pixels = a.ravel().tolist()
    img.filepath_raw = path
    img.file_format = 'PNG'
    img.save()
    bpy.data.images.remove(img)


def attribute(cam, leak, pose_name, az):
    """Name the culprits: cast the camera ray through a sample of leak pixels (scene.ray_cast ignores
    culling, so the first hit is the back-facing surface the game drops) and histogram them."""
    h, w = leak.shape
    js, is_ = np.nonzero(leak)
    if len(js) == 0:
        return
    pick = np.linspace(0, len(js) - 1, min(ATTR, len(js))).astype(int)
    rot = cam.matrix_world.to_3x3()
    fwd, right, up = rot @ Vector((0, 0, -1)), rot @ Vector((1, 0, 0)), rot @ Vector((0, 1, 0))
    s = cam.data.ortho_scale
    dg = bpy.context.evaluated_depsgraph_get()
    hist = {}
    for k in pick:
        i, j = is_[k], js[k]
        x = ((i + 0.5) / w * 2 - 1) * s / 2
        y = ((j + 0.5) / h * 2 - 1) * s / 2 * h / w
        origin = cam.location + right * x + up * y
        hit, loc, n, idx, ob, _m = bpy.context.scene.ray_cast(dg, origin, fwd)
        if not hit:
            key = ("-", "-", "miss")
        else:
            me = ob.evaluated_get(dg).to_mesh()
            mat = "-"
            if me and idx < len(me.polygons):
                mi = me.polygons[idx].material_index
                mat = me.materials[mi].name if mi < len(me.materials) and me.materials[mi] else "-"
            ob.evaluated_get(dg).to_mesh_clear()
            key = (ob.name, mat, "BACK" if n.dot(fwd) > 0 else "front")
        e = hist.setdefault(key, [0, None])
        e[0] += 1
        if e[1] is None and hit:
            e[1] = tuple(round(c, 2) for c in loc)
    for key, (cnt, at) in sorted(hist.items(), key=lambda kv: -kv[1][0])[:8]:
        print("LEAKSRC pose=%s az=%03d %-12s %-14s %-5s %4d  e.g. %s" % (pose_name, az, key[0], key[1], key[2], cnt, at))


def main():
    os.makedirs(OUT, exist_ok=True)
    arm, cam = setup()
    tmp_c = os.path.join(OUT, "_culled.png")
    tmp_o = os.path.join(OUT, "_open.png")
    total = 0
    worst = []
    only = {tuple(v.split(":")) for v in ONLY.split(",") if v}
    for pose_name, clips in (("shut", ()), ("open", OPEN_CLIPS)):
        rig_vehicle.pose(arm, clips)
        for az in range(0, 360, STEP):
            if only and (pose_name, "%03d" % az) not in only:
                continue
            aim(cam, az)
            culled = render(tmp_c, True)
            both = render(tmp_o, False)
            leak = magenta(culled) & ~magenta(both)
            n = int(leak.sum())
            total += n
            print("LEAK pose=%s az=%03d px=%d" % (pose_name, az, n))
            if n:
                out = culled.copy()
                out[leak] = (0.0, 1.0, 0.0, 1.0)
                save(os.path.join(OUT, "leak_%s_%03d.png" % (pose_name, az)), out)
                worst.append((n, pose_name, az))
                if ATTR:
                    attribute(cam, leak, pose_name, az)
    for p in (tmp_c, tmp_o):
        if os.path.exists(p):
            os.remove(p)
    worst.sort(reverse=True)
    print("LEAK TOTAL px=%d views=%d worst=%s" % (total, len(worst), worst[:5]))
    print("LEAK TEST DONE")


if __name__ == "__main__":
    main()
