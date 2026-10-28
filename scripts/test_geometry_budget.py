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


def _synthetic_wheel():
    """A stand-in for kotris's wheel_FR_hi: a 36-sided lathe of the stock profile (tyre Pneu, the lip and a dished
    alloy face Jante, numbers measured on wheel_FR_hi 2026-10-27), hub at the road wheel's place, axle +x."""
    import math
    me = bpy.data.meshes.new("w_hi")
    for n in ("Pneu", "Jante"):
        me.materials.append(bpy.data.materials.get(n) or bpy.data.materials.new(n))
    prof = [(-0.0885, 0.2086, 0), (-0.1038, 0.2826, 0), (-0.087, 0.3183, 0), (-0.0685, 0.3319, 0), (0.0685, 0.3319, 0),
            (0.087, 0.3183, 0), (0.1038, 0.2826, 0), (0.0885, 0.2086, 0), (0.093, 0.2046, 1), (0.0888, 0.172, 1),
            (0.0956, 0.105, 1), (0.0983, 0.068, 1)]
    c = Vector((0.756, 1.3226, 0.3415))
    bm = bmesh.new()
    seg = 36
    rings = [[bm.verts.new(c + Vector((t, r * math.cos(2 * math.pi * k / seg), r * math.sin(2 * math.pi * k / seg))))
              for k in range(seg)] for t, r, _m in prof]
    for j in range(len(rings) - 1):
        for k in range(seg):
            f = bm.faces.new((rings[j][k], rings[j][(k + 1) % seg], rings[j + 1][(k + 1) % seg], rings[j + 1][k]))
            f.material_index = prof[j + 1][2]
    tip = bm.verts.new(c + Vector((0.0983, 0.0, 0.0)))
    for k in range(seg):
        f = bm.faces.new((rings[-1][k], rings[-1][(k + 1) % seg], tip))
        f.material_index = 1
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new("w_hi", me)
    bpy.context.scene.collection.objects.link(ob)
    return ob, c


def test_alloy():
    """prep_parts._lathe_replace / _rim_face (2026-10-27, the crowned alloy): the road wheel within its budget (766 tris
    before: +316 for crowned arms, chamfered mouths and the lip's flange), every arm crowned (its flanks under the crest)
    and nothing standing proud of the old face (the spare cover and the off-road can fit round the spare's face), every
    rim corner carrying rim_tone (the bake's highlights), and no see-through: rays from outside the wheel at up to 80
    degrees off the axle meet a face that looks back at them (the game culls back faces)."""
    import math
    import numpy as np
    from mathutils.bvhtree import BVHTree
    import prep_parts as P
    src, c = _synthetic_wheel()
    me = src.data.copy()
    ob = bpy.data.objects.new("w_low", me)
    bpy.context.scene.collection.objects.link(ob)
    info = P._lathe_replace(ob, src, cap=True, rim=src, hub="HubCap")
    n = tris(ob)
    check(n <= 1100, "stock alloy wheel within its budget: %d tris <= 1100 (766 before 2026-10-27)" % n)
    check(info["chamfer"] == 5 * (len(P.RIM_WINDOW) + len(P.RIM_SLOT)), "every window and slot mouth chamfered (%d quads)" % info["chamfer"])
    names = [m.name for m in ob.data.materials]
    t_hub_tip = None
    over, crest_fall, on_face = 0.0, [], 0
    t_out = 0.0
    for p in ob.data.polygons:
        if names[p.material_index] == "HubCap":
            for i in p.vertices:
                t = ob.data.vertices[i].co.x - c.x
                t_hub_tip = t if t_hub_tip is None else max(t_hub_tip, t)
    gen = ob.data.attributes["gen"].data
    tone = ob.data.attributes.get("rim_tone")
    check(tone is not None and tone.domain == 'CORNER', "rim_tone is a corner attribute on the wheel")
    jante = [p for p in ob.data.polygons if names[p.material_index] == "Jante"]
    check(all(gen[p.index].value == P.RIM_GEN for p in jante), "every rim face is generated (gen %d: baked direct, with its tones)" % P.RIM_GEN)
    tones = [tone.data[li].value for p in jante for li in p.loop_indices]
    check(min(tones) >= 0.0 and abs(max(tones) - max(P.RIM_TONE.values())) < 1e-6,
          "rim_tone on the rim's corners spans 0 .. %.2f (the chamfers' bright band)" % max(P.RIM_TONE.values()))
    check(all(p.normal.x > 0.0 for p in jante), "every rim face looks out of the wheel")
    # the old face: the cone from the hub ring (t_hub - 2 mm at RIM_HUB_R) to the lip ring (RIM_FACE_R)
    ring = [ob.data.vertices[i].co for p in jante for i in p.vertices
            if abs(math.hypot(ob.data.vertices[i].co.y - c.y, ob.data.vertices[i].co.z - c.z) - P.RIM_FACE_R) < 1e-5]
    t_edge = sum(v.x - c.x for v in ring) / len(ring)
    t_ring = t_hub_tip - 0.004

    def t_face(r):
        k = min(max((r - P.RIM_HUB_R) / (P.RIM_FACE_R - P.RIM_HUB_R), 0.0), 1.0)
        return t_ring + (t_edge - t_ring) * k
    for p in jante:
        for i in p.vertices:
            co = ob.data.vertices[i].co
            r = math.hypot(co.y - c.y, co.z - c.z)
            if P.RIM_HUB_R <= r <= P.RIM_FACE_R:
                on_face += 1
                over = max(over, (co.x - c.x) - t_face(r))
                if 0.10 <= r <= 0.16:
                    crest_fall.append(t_face(r) - (co.x - c.x))
    check(over < 1e-5, "nothing on the spoke face stands proud of the old face (worst %+.2f mm)" % (over * 1000))
    check(crest_fall and max(crest_fall) >= P.RIM_CROWN - 1e-5 and min(crest_fall) < 1e-5,
          "the arms are crowned: crest on the old face, flanks falling %.1f mm and more to the chamfers" % (max(crest_fall) * 1000))
    xs = [v.co.x for v in ob.data.vertices]
    xs0 = [v.co.x for v in src.data.vertices]
    check(max(xs) <= max(xs0) + 1e-6, "the wheel's outer face no further out than the twin's (%.4f <= %.4f)" % (max(xs), max(xs0)))
    # see-through: rays at the rim face from outside, first hit must face the ray
    bvh = BVHTree.FromObject(ob, bpy.context.evaluated_depsgraph_get())
    ax, u, v = Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))
    rng = np.random.default_rng(7)
    bad = 0
    N = 20000
    for _ in range(N):
        r = 0.2 * math.sqrt(rng.random())
        a = rng.random() * 2 * math.pi
        tilt = math.radians(80.0) * math.sqrt(rng.random())
        b = rng.random() * 2 * math.pi
        d = -(ax * math.cos(tilt) + (u * math.cos(b) + v * math.sin(b)) * math.sin(tilt))
        target = c + ax * 0.06 + (u * math.cos(a) + v * math.sin(a)) * r
        hit, nrm, idx, dist = bvh.ray_cast(target - d * 1.0, d, 3.0)
        if hit is None or nrm.dot(d) > 0:
            bad += 1
    check(bad == 0, "no see-through in the rim: %d of %d rays from outside met nothing or a back face" % (bad, N))


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    test_lift()
    test_prune()
    test_alloy()
    if FAILS:
        print("GEOMETRY BUDGET TESTS: %d FAIL" % len(FAILS))
        sys.exit(1)
    print("GEOMETRY BUDGET TESTS OK")


main()
