r"""
Swing every opening panel through its travel and report parts that pass through each other.

    blender -b blender\crv_kotris.blend --python scripts\collide_check.py

Builds the rig as run_export does, then for each clip (doors, hood, gate + glass; not the windows) poses
it at 25 / 50 / 75 / 100 % of its travel. Each mesh skinned to a bone the clip moves (or a child bone) is
tested against every other mesh with a BVH overlap. Contacts that already exist with everything shut
(seals, trims touching) are ignored. Prints one COLLIDE line per new pair with the overlap's centre in
metres, and COLLIDE NONE when the car is clear. Accessory variants that never coexist are skipped.
"""
import os
import sys

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

ROOT = os.environ.get("CRV_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(globals().get("__file__") or os.path.join("scripts", "_"))))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.append(SCRIPTS)
import rig_vehicle  # noqa: E402

FRACTIONS = (0.25, 0.5, 0.75, 1.0)
# never on the car together: the stock vs lift gate covers, the rack's cargo states, seats up vs folded
EXCLUSIVE = [{"acc_lift_gate_alloy", "acc_lift_gate_steel"}, {"acc_rack_load1", "acc_rack_load2", "acc_rack_load3"},
             {"acc_function_seats_up", "acc_function_seats_fold"}, {"acc_guard_rear", "acc_armour_rear_plate"}]


def exclusive(a, b):
    return any(a in g and b in g for g in EXCLUSIVE)


def world_tree(ob, dg):
    ev = ob.evaluated_get(dg)
    me = ev.to_mesh()
    M = ev.matrix_world
    verts = [M @ v.co for v in me.vertices]
    polys = [list(p.vertices) for p in me.polygons]
    centres = [sum((verts[i] for i in p), Vector()) / len(p) for p in polys]
    ev.to_mesh_clear()
    return BVHTree.FromPolygons(verts, polys, all_triangles=False), centres


def descendants(arm, bones):
    out = set(bones)
    for b in arm.data.bones:
        p = b.parent
        while p is not None:
            if p.name in out:
                out.add(b.name)
                break
            p = p.parent
    return out


def set_clip(arm, clip, frac):
    for c, specs in rig_vehicle.CLIPS.items():
        for bone, channel, value in specs:
            rig_vehicle._apply(arm.pose.bones[bone], channel, value * frac if c == clip else 0.0)
    for bone, e in rig_vehicle.strut_rotations(frac if clip == "trunk_opening" else 0.0).items():
        arm.pose.bones[bone].rotation_euler = e             # the gas struts aim with the glass
    bpy.context.view_layer.update()


def main():
    rig_vehicle.make_struts(report=lambda *a: None)     # kept separate (not joined): checked as their own parts
    arm = rig_vehicle.build()
    meshes = [o for o in bpy.data.objects if o.type == 'MESH' and not o.name.endswith(("_hi", "_full"))
              and o.name != "base" and len(o.data.polygons)]
    dg = bpy.context.evaluated_depsgraph_get()
    rig_vehicle.pose(arm, ())
    shut = {o.name: world_tree(o, dg)[0] for o in meshes}
    baseline = set()
    names = [o.name for o in meshes]
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if shut[a].overlap(shut[b]):
                baseline.add(frozenset((a, b)))
    found = {}
    for clip, specs in rig_vehicle.CLIPS.items():
        if clip.startswith("window"):
            continue
        bones = descendants(arm, {b for b, _c, _v in specs})
        if clip == "trunk_opening":
            bones |= set(rig_vehicle.STRUT_BONES)
        movers = [o for o in meshes if rig_vehicle.SKIN.get(o.name) in bones]
        for frac in FRACTIONS:
            set_clip(arm, clip, frac)
            dg = bpy.context.evaluated_depsgraph_get()
            trees = {o.name: world_tree(o, dg) for o in meshes}
            for m in movers:
                tm, cm = trees[m.name]
                for o in meshes:
                    if o is m or exclusive(m.name, o.name):
                        continue
                    if o in movers and not (m.name.endswith("_tube") and not o.name.startswith("strut_")):
                        continue                            # panels moving together; a strut tube vs the glass is kept
                    if frozenset((m.name, o.name)) in baseline:
                        continue
                    # a strut's eyes sit on its mounts (body at STRUT_B, glass at STRUT_G): read the centre printed
                    pairs = tm.overlap(trees[o.name][0])
                    if pairs:
                        key = (clip, m.name, o.name)
                        if key not in found or len(pairs) > found[key][1]:
                            c = sum((cm[i] for i, _j in pairs), Vector()) / len(pairs)
                            found[key] = (frac, len(pairs), c)
    rig_vehicle.pose(arm, ())
    for (clip, a, b), (frac, n, c) in sorted(found.items()):
        print("COLLIDE %-18s %-24s x %-24s at %3d%%: %4d face pairs around (%.2f, %.2f, %.2f) m"
              % (clip, a, b, frac * 100, n, c.x, c.y, c.z))
    if not found:
        print("COLLIDE NONE: no panel passes through another part anywhere in its travel")
    print("COLLIDE baseline: %d pairs already touching with everything shut (ignored)" % len(baseline))


main()
