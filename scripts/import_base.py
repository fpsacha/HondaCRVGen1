r"""
Bring a third-party CR-V mesh into the project's model space and PZ poly budget.

    blender.exe -b --python scripts/import_base.py -- <file.glb|.gltf|.fbx|.obj> [--target 9000]

Written for the CC BY 4.0 "Honda CR-V MK1 1995-2001" by Merc_TV (szymonpasterczyk) on Sketchfab
(uid 2519659e30544a4fb425d81c525bf7aa, 149k faces, 26 materials, no textures) - the base the
owner chose over the procedural loft on 2026-09-05 - but nothing here is specific to it.

What it does, in order:
  1. imports the file into an empty scene (glTF, FBX or OBJ),
  2. joins everything into one mesh, applies transforms, drops loose junk under 20 verts,
  3. re-orients to the project frame - metres, +Y front, +Z up, +X right, ground at z 0, origin
     midway between the axles - by measuring the bounding box and the two wheel-well centres
     (the front of the car is taken as the end with the lower, longer overhang; override with
     --front=+y/-y/+x/-x if it guesses wrong),
  4. scales to the real wheelbase (2.62 m) and reports L/W/H against the brochure (4.52/1.75/1.65),
  5. decimates to --target faces (planar first, then collapse), keeping material boundaries,
  6. saves blender/import/base_<name>.blend and writes a report to spec/import/<name>.md.

Splitting the shell into KI5-style opening parts, the rig and the export stay with the existing
scripts (build parts by bounding boxes: see `split_parts` below, driven by the same shut-line
numbers as build_body_hull.py).

Model space: metres, +Y front, +Z up, +X vehicle right, origin at ground level between the axles.
"""
import argparse
import math
import os
import sys

import bpy
from mathutils import Vector

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMPORT_DIR = os.path.join(ROOT, "blender", "import")
REPORT_DIR = os.path.join(ROOT, "spec", "import")

WHEELBASE = 2.62
REAL = {"L": 4.52, "W": 1.75, "H": 1.65}
TYRE_R = 0.334

# shut lines in model space, shared with build_body_hull.py (kept literal here so the importer
# can run without the loft module)
SHUT = {
    "hood": ((-0.74, 0.74), (0.96, 1.98), (0.86, 1.30)),          # (x range, y range, z range)
    "door_fl": ((-1.0, -0.5), (-0.28, 0.80), (0.52, 1.62)),
    "door_fr": ((0.5, 1.0), (-0.28, 0.80), (0.52, 1.62)),
    "door_rl": ((-1.0, -0.5), (-1.27, -0.28), (0.52, 1.62)),
    "door_rr": ((0.5, 1.0), (-1.27, -0.28), (0.52, 1.62)),
    "trunk": ((-0.70, 0.70), (-2.3, -2.0), (0.72, 1.15)),
    "trunk_top": ((-0.60, 0.60), (-2.3, -1.85), (1.15, 1.62)),
}


def _args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("path")
    p.add_argument("--target", type=int, default=9000, help="face budget after decimation")
    p.add_argument("--front", default="auto", help="+y (default guess) or -y: where the nose points after import")
    p.add_argument("--up", default="z", help="z (default), y or x: the file's up axis as it arrives in Blender")
    p.add_argument("--no-decimate", action="store_true")
    return p.parse_args(argv)


def _clear():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def _import(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=path)
    elif ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=path)
    elif ext == ".obj":
        bpy.ops.wm.obj_import(filepath=path)
    elif ext == ".dae":
        bpy.ops.wm.collada_import(filepath=path)
    else:
        raise SystemExit("unsupported: %s" % ext)
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    if not meshes:
        raise SystemExit("no meshes imported")
    return meshes


def _inventory(meshes, limit=60):
    """The author's own objects, largest first: the names are the part map for cutting."""
    rows = sorted(((len(o.data.polygons), o.name, [m.name for m in o.data.materials if m])
                   for o in meshes), reverse=True)
    lines = ["* %d objects, %d faces total" % (len(rows), sum(r[0] for r in rows))]
    for n, name, mats in rows[:limit]:
        lines.append("    %6d  %-40s %s" % (n, name[:40], ", ".join(mats)[:60]))
    if len(rows) > limit:
        lines.append("    ... %d more" % (len(rows) - limit))
    return lines


def _axles_from_names(meshes):
    """Axle y positions from named hub / wheel objects, in world space, if the file has them."""
    def centre(o):
        pts = [o.matrix_world @ Vector(c) for c in o.bound_box]
        return sum(p.y for p in pts) / 8, sum(p.z for p in pts) / 8
    f = [o for o in meshes if "hub_f" in o.name.lower()]
    r = [o for o in meshes if "hub_r" in o.name.lower()]
    if f and r:
        cf = [centre(o) for o in f]
        cr = [centre(o) for o in r]
        z_hub = (sum(c[1] for c in cf) + sum(c[1] for c in cr)) / (len(cf) + len(cr))
        return sum(c[0] for c in cf) / len(cf), sum(c[0] for c in cr) / len(cr), z_hub
    return None


def _join(meshes):
    bpy.ops.object.select_all(action='DESELECT')
    for o in meshes:
        o.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    # glTF and Collada files usually hang everything under a rotated / scaled root empty:
    # bake that into the meshes before joining or the geometry lands in local coordinates
    bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    bpy.ops.object.join()
    ob = bpy.context.view_layer.objects.active
    ob.name = "base"
    # drop tiny loose islands (screws, badges' back faces, stray verts)
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.delete_loose()
    bpy.ops.object.mode_set(mode='OBJECT')
    return ob


def _bbox(ob):
    xs = [v.co.x for v in ob.data.vertices]
    ys = [v.co.y for v in ob.data.vertices]
    zs = [v.co.z for v in ob.data.vertices]
    return (min(xs), max(xs)), (min(ys), max(ys)), (min(zs), max(zs))


def _orient(ob, front, up="z"):
    """Rotate so the long axis is Y, up is Z, nose is +Y; then centre and drop to the ground.
    Blender's glTF and Collada importers already turn the file's up axis into Z, so only the
    long axis and the nose direction are guessed; --up=y/x overrides the up axis if a file
    comes in lying on its side."""
    from mathutils import Euler, Matrix
    if up == "y":                                       # Y-up file that was not converted
        m = Matrix.Rotation(math.radians(90), 4, 'X')
        for v in ob.data.vertices:
            v.co = m @ v.co
    elif up == "x":
        m = Matrix.Rotation(math.radians(-90), 4, 'Y')
        for v in ob.data.vertices:
            v.co = m @ v.co
    (x0, x1), (y0, y1), (z0, z1) = _bbox(ob)
    if (x1 - x0) > (y1 - y0):                           # long axis along X: turn it onto Y
        m = Matrix.Rotation(math.radians(90), 4, 'Z')
        for v in ob.data.vertices:
            v.co = m @ v.co
    (x0, x1), (y0, y1), (z0, z1) = _bbox(ob)
    f = front.strip().lower()
    if f == "auto":
        # the CR-V carries its spare on the tail: the end with more low-down mesh is the back
        lo = [v.co for v in ob.data.vertices if v.co.z < z0 + 0.45 * (z1 - z0)]
        mid = (y0 + y1) / 2
        flip = sum(1 for c in lo if c.y > mid) > sum(1 for c in lo if c.y < mid)
    else:
        flip = f in ("-y",)
    _FLIPPED["v"] = bool(flip)
    if flip:
        m = Matrix.Rotation(math.pi, 4, 'Z')
        for v in ob.data.vertices:
            v.co = m @ v.co
    (x0, x1), (y0, y1), (z0, z1) = _bbox(ob)
    _Z0["v"] = z0
    for v in ob.data.vertices:
        v.co.x -= (x0 + x1) / 2
        v.co.z -= z0
    return _bbox(ob)


_FLIPPED = {"v": False}
_Z0 = {"v": 0.0}                                        # the raw frame's lowest z, removed by _orient


def _was_flipped(ob, py0, py1):
    return _FLIPPED["v"]


def _wheel_centres(ob):
    """Wheel-well centres from the lowest points: the two densest y-bands near the ground."""
    zs = sorted(v.co.z for v in ob.data.vertices)
    z_lo = zs[int(0.02 * len(zs))]
    low = [v.co for v in ob.data.vertices if v.co.z < z_lo + 0.12]
    if len(low) < 20:
        return None
    ys = sorted(c.y for c in low)
    # split at the largest gap
    gaps = [(ys[i + 1] - ys[i], i) for i in range(len(ys) - 1)]
    g, i = max(gaps)
    if g < 0.8:
        return None
    front = ys[i + 1:]
    back = ys[:i + 1]
    return sum(front) / len(front), sum(back) / len(back)


def _scale_to_wheelbase(ob, named_axles=None, flipped=False):
    """Scale so the axles are 2.62 m apart and put the origin midway between them. Named hubs
    (measured before the join, in the file's frame) win over the lowest-points guess."""
    (x0, x1), (y0, y1), (z0, z1) = _bbox(ob)
    wc = None
    if named_axles:
        yf, yr, z_hub = named_axles
        wb = abs(yf - yr)
        s = WHEELBASE / wb
        note = "wheelbase from named hubs %.3f -> scale %.4f; hubs set to z %.3f" % (wb, s, TYRE_R)
        mid = (yf + yr) / 2 * (-1.0 if flipped else 1.0)
        wc = ("named", mid * s)
        dz = TYRE_R - (z_hub - _Z0["v"]) * s           # ground: the hub centre sits one tyre radius up
        for v in ob.data.vertices:
            v.co.z += dz / s                            # applied before the scale below
    else:
        wc0 = _wheel_centres(ob)
        if wc0:
            yf, yr = wc0
            s = WHEELBASE / abs(yf - yr)
            note = "wheelbase measured from the lowest points %.3f -> scale %.4f" % (abs(yf - yr), s)
        else:
            s = REAL["L"] / (y1 - y0)
            note = "wheels not found; scaled by length -> %.4f" % s
    for v in ob.data.vertices:
        v.co *= s
    if wc and wc[0] == "named":
        shift = -wc[1]
    else:
        wc1 = _wheel_centres(ob)
        shift = -(wc1[0] + wc1[1]) / 2 if wc1 else 0.0
    for v in ob.data.vertices:
        v.co.y += shift
    return note


def _decimate(ob, target):
    n0 = len(ob.data.polygons)
    if n0 <= target:
        return "no decimation needed (%d faces)" % n0
    bpy.context.view_layer.objects.active = ob
    m = ob.modifiers.new("planar", 'DECIMATE')
    m.decimate_type = 'DISSOLVE'
    m.angle_limit = math.radians(3.0)
    m.delimit = {'MATERIAL', 'SHARP', 'UV'}
    bpy.ops.object.modifier_apply(modifier=m.name)
    n1 = len(ob.data.polygons)
    if n1 > target:
        m = ob.modifiers.new("collapse", 'DECIMATE')
        m.decimate_type = 'COLLAPSE'
        m.ratio = max(0.02, target / n1)
        m.use_collapse_triangulate = True
        bpy.ops.object.modifier_apply(modifier=m.name)
    return "decimated %d -> planar %d -> %d faces" % (n0, n1, len(ob.data.polygons))


def split_parts(ob):
    """Cut the opening panels out of the shell by the shut-line boxes (loose-part aware)."""
    out = {}
    bpy.context.view_layer.objects.active = ob
    for name, ((xa, xb), (ya, yb), (za, zb)) in SHUT.items():
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='DESELECT')
        bpy.ops.object.mode_set(mode='OBJECT')
        for p in ob.data.polygons:
            c = p.center
            p.select = (xa <= c.x <= xb) and (ya <= c.y <= yb) and (za <= c.z <= zb)
        if not any(p.select for p in ob.data.polygons):
            continue
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.separate(type='SELECTED')
        bpy.ops.object.mode_set(mode='OBJECT')
        new = [o for o in bpy.context.selected_objects if o != ob][-1]
        new.name = name
        out[name] = new
    ob.name = "body"
    return out


def main():
    a = _args()
    _clear()
    meshes = _import(a.path)
    inventory = _inventory(meshes)
    os.makedirs(IMPORT_DIR, exist_ok=True)
    name = os.path.splitext(os.path.basename(a.path))[0]
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(IMPORT_DIR, "raw_%s.blend" % name))   # untouched copy
    axles = _axles_from_names(meshes)
    ob = _join(meshes)
    (px0, px1), (py0, py1), (pz0, pz1) = _bbox(ob)
    bb = _orient(ob, a.front, a.up)
    # did _orient turn the car around? compare where the +y end went
    flipped = a.front.strip().lower() == "-y" or (a.front == "auto" and _was_flipped(ob, py0, py1))
    note_scale = _scale_to_wheelbase(ob, axles, flipped)
    (x0, x1), (y0, y1), (z0, z1) = _bbox(ob)
    dims = {"L": y1 - y0, "W": x1 - x0, "H": z1 - z0}
    note_dec = _decimate(ob, a.target) if not a.no_decimate else "decimation skipped"
    os.makedirs(REPORT_DIR, exist_ok=True)
    blend = os.path.join(IMPORT_DIR, "base_%s.blend" % name)
    bpy.ops.wm.save_as_mainfile(filepath=blend)
    lines = ["# Import report: %s" % os.path.basename(a.path), ""] + inventory + [
             "* %s" % note_scale,
             "* extents after orientation: L %.3f W %.3f H %.3f (real %.2f / %.2f / %.2f)" % (
                 dims["L"], dims["W"], dims["H"], REAL["L"], REAL["W"], REAL["H"]),
             "* y range %.3f .. %.3f, x range %.3f .. %.3f, z range %.3f .. %.3f" % (y0, y1, x0, x1, z0, z1),
             "* materials: %d" % len(ob.data.materials),
             "* %s" % note_dec,
             "* saved %s" % os.path.relpath(blend, ROOT)]
    with open(os.path.join(REPORT_DIR, "%s.md" % name), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
