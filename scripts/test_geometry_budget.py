r"""
Blender unit test of the optimization pass's geometry budgets (2026-10-24), on synthetic scenes:

    blender -b --factory-startup --python scripts\test_geometry_budget.py

1. features/lift.py: the AT tyre and the steel rim built on the stock wheel's frame stay within their
   budgets (tyre 1952 tris: 26 pitches of four blocks, every block with its walls; steel rim 704: octagonal
   vent windows), and the tread keeps every wall (no block loses the faces that make it read).
2. build_accessories.prune_hidden: a plate pressed flat on a body box loses the face against the skin and
   keeps the rest; a plate standing 8 mm off the skin keeps its back (seen through the slit, the armour's
   round 5 leak); the occluders are only the ones named (a second part in the way hides nothing); gate True
   keeps a face that looks down.
Prints GEOMETRY BUDGET TESTS OK, or FAIL lines and exits 1.
"""
import os
import sys

import bmesh
import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

FAILS = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def box(name, lo, hi):
    """A closed box mesh object (outward faces) from corner lo to hi."""
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co = Vector(tuple(lo[k] + (v.co[k] + 0.5) * (hi[k] - lo[k]) for k in range(3)))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def tris(ob):
    return sum(len(p.vertices) - 2 for p in ob.data.polygons)


def test_lift():
    from features import lift
    fr = {"xc": 0.0, "yc": 0.0, "zc": 0.0, "r_lip": 0.2086, "t_out": 0.0885, "t_in": -0.0885}   # the stock wheel_FR
    mats = lift._materials()
    for kind in ("tyre", "rim"):
        me = bpy.data.meshes.new("t_" + kind)
        bm = bmesh.new()
        F = lift._Faces(bm, me, mats)
        hub = Vector((0.0, 0.0, lift.TYRE_R))
        if kind == "tyre":
            blocks = lift._tyre(F, hub, fr)
            n = F.made
            check(blocks == 4 * lift.PITCHES, "tyre: %d tread blocks, four a pitch (%d pitches)" % (blocks, lift.PITCHES))
            check(n <= 1952, "AT tyre within its budget: %d tris <= 1952 (2160 before 2026-10-24)" % n)
            # every block keeps all its walls: centre 10 tris, outer shoulder 18, inner shoulder 14
            tread = sum(len(f.verts) - 2 for f in bm.faces if me.materials[f.material_index].name == "LiftTread")
            check(tread == lift.PITCHES * (10 + 10 + 18 + 14), "every tread block keeps its walls (%d tread tris)" % tread)
        else:
            n = lift._steel_rim(F, hub, fr, "Lift")
            check(n <= 704, "steel rim within its budget: %d tris <= 704 (752 before 2026-10-24)" % n)
        bm.free()


def test_prune():
    import build_accessories as BA
    import backfill
    backfill.eye_points = lambda: []       # the seat eyes stand inside this test's solid body box
    body = box("body", (-0.9, -2.2, 0.3), (0.9, 2.2, 1.6))
    flush = box("acc_flush", (0.9, -0.3, 0.6), (0.906, 0.3, 1.0))          # pressed on the body's right side
    gap = box("acc_gap", (0.908, 0.6, 0.6), (0.914, 1.2, 1.0))             # 8 mm off it
    other = box("acc_other", (0.95, -1.4, 0.5), (1.2, -0.6, 1.1))          # another part
    behind = box("acc_behind", (0.9, -1.2, 0.7), (0.906, -0.8, 0.9))       # pressed on the body behind it
    down = box("acc_down", (-0.3, -0.2, 1.7), (0.3, 0.2, 1.75))            # a slab over the roof

    def faces_toward(ob, axis, sign):
        return [p for p in ob.data.polygons if p.normal[axis] * sign > 0.9]

    n0 = tris(flush)
    BA.prune_hidden(flush, ("body",), print)
    check(tris(flush) == n0 - 2 and not faces_toward(flush, 0, -1.0),
          "a plate flush on the skin loses its back (%d -> %d tris)" % (n0, tris(flush)))
    check(len(faces_toward(flush, 0, 1.0)) == 1, "... and keeps its face")
    n0 = tris(gap)
    BA.prune_hidden(gap, ("body",), print)
    check(tris(gap) == n0, "a plate 8 mm off the skin keeps its back: seen through the slit (%d -> %d)" % (n0, tris(gap)))
    n0 = tris(behind)
    BA.prune_hidden(behind, ("body",), print)
    check(len(faces_toward(behind, 0, 1.0)) == 1, "another part in front hides nothing: only the named occluders count")
    # faces met from behind are culled in game: a part inside a shell whose faces all look inward shows
    # through it (the 2026-10-24 scratch build dropped hitch / can-bracket faces seen past the shell's backs)
    shell = box("shell", (5.0, 5.0, 0.2), (6.0, 6.0, 1.6))        # a closed shell, far from every eye, seen from inside
    shell.data.flip_normals()
    behind_shell = box("acc_behind_shell", (5.4, 5.4, 0.8), (5.45, 5.6, 1.0))
    n0 = tris(behind_shell)
    BA.prune_hidden(behind_shell, ("shell",), print)
    check(tris(behind_shell) == n0, "a face seen through a culled back of its occluder stays (%d -> %d)" % (n0, tris(behind_shell)))
    BA.prune_hidden(down, ("body",), print, gate=True)
    check(len(faces_toward(down, 2, -1.0)) == 1, "gate True: the slab's underside, seen from below, stays")
    # IMP-VP-1 (bug wave 3): the strip under the rear off-road bumper / hitch, 3 cm above the body's floor line and
    # looking down, is seen only by an eye lower than it (a Project Viewpoint camera low behind the car): the
    # 0.25 m ring of bay.visibility.RING keeps it (with 0.5 m the lowest eye it was pruned)
    under = box("acc_under_bumper", (-0.2, -2.45, 0.33), (0.2, -2.25, 0.36))
    BA.prune_hidden(under, ("body",), print)
    check(len(faces_toward(under, 2, -1.0)) == 1, "a strip under the rear bumper, seen only from a low eye, stays")
    del other


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    test_lift()
    test_prune()
    if FAILS:
        print("GEOMETRY BUDGET TESTS: %d FAIL" % len(FAILS))
        sys.exit(1)
    print("GEOMETRY BUDGET TESTS OK")


main()
