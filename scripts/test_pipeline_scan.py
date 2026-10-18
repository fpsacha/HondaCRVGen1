r"""
Blender unit test of how the build's ray scans and bakes treat meshes that are not the bare car
(2026-10-13 integration regressions), on a synthetic scene:

    blender -b --factory-startup --python scripts\test_pipeline_scan.py

1. backfill: the lift's wheel_lift_alloy parked at x 4 m (as features/lift.py builds it) and a stray
   mesh 6 m away never join the car's scan: the car pool is the body, its scale is the body's alone
   (the regression: scale 1.05 -> 1.73, the grid 1.7x coarser, the seat eyes above the roof), and the
   faces a scan marks on the car are the same with or without them in the scene.
2. bake_atlas.quiet_removables: before ANY space bakes, every acc_* mesh (whatever sheet it bakes on)
   is invisible to the rays (the shell printed the off-road ladder and snorkel), and a feature's
   non-acc mesh is invisible while another space bakes and visible for its own; restore_rays undoes
   only the temporary part.
Prints PIPELINE SCAN TESTS OK, or FAIL lines and exits 1.
"""
import os
import sys

import bmesh
import bpy
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

FAILS = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def box(name, size, at, inward=False):
    """A closed box mesh at `at`, its faces flipped to look inward if asked (every face is then
    seen from behind from outside: what the backfill scan marks)."""
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0, matrix=Matrix.Diagonal(Vector(size).to_4d()))
    if inward:
        bmesh.ops.reverse_faces(bm, faces=list(bm.faces))
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    ob.location = at
    bpy.context.view_layer.update()
    return ob


def clear():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)


def scan(backfill, tree, owner, verts, marks, scale):
    """backfill._scan on a coarse grid (10 cm x scale, one elevation, four headings): the unit test's
    boxes are metres wide, and the full 9 mm grid would cast millions of rays."""
    backfill._scan(tree, owner, verts, marks, scale, elevations=(30.0,), grid=0.1)


def test_backfill():
    import backfill
    backfill.AZ_STEP = 90
    clear()
    body = box("body", (1.8, 4.5, 1.6), (0.0, 0.0, 0.85), inward=True)    # a 4.5 m car, every face seen from behind
    car, loose = backfill._meshes()
    check([o.name for o in car] == ["body"] and loose == [], "a lone body: the car pool is the body (%s / %s)"
          % ([o.name for o in car], [o.name for o in loose]))
    _t, owner, verts = backfill._tree(car)
    scale = backfill.car_scale(verts)
    check(abs(scale - (Vector((1.8, 4.5, 1.6))).length / 5.0) < 1e-6 and any(a <= scale <= b for a, b in backfill.CAR_SCALES),
          "the scale is the body's box diagonal / 5 (%.3f)" % scale)
    tree, owner, verts = backfill._tree(car)
    alone = set()
    scan(backfill, tree, owner, verts, alone, scale)
    check(len(alone) == 5, "the scan marks the 5 inward faces the camera can reach (all but the floor) (%d)" % len(alone))

    import features
    wheels = set(features.wheel_objects())
    check("wheel_lift_alloy" in wheels, "the lift feature declares wheel_lift_alloy as a wheel-file object (%s)" % sorted(wheels))
    box("wheel_lift_alloy", (0.24, 0.76, 0.76), (4.0, 0.0, 0.38), inward=True)    # parked as lift.ALLOY_HUB
    box("stray_part", (0.3, 0.3, 0.3), (0.0, 7.0, 0.5))                             # anything else away from the body
    box("acc_offroad_ladder", (0.1, 0.3, 0.9), (0.95, -1.55, 1.3))                  # removable: never in the scan
    car, loose = backfill._meshes()
    check([o.name for o in car] == ["body"], "car pool with a parked wheel, a stray mesh and an accessory: the body only (%s)"
          % [o.name for o in car])
    check(sorted(o.name for o in loose) == ["stray_part", "wheel_lift_alloy"], "the wheel and the stray mesh are loose (%s)"
          % sorted(o.name for o in loose))
    tree, owner, verts = backfill._tree(car)
    check(abs(backfill.car_scale(verts) - scale) < 1e-9, "the car's scale does not move with them")
    marks = set()
    scan(backfill, tree, owner, verts, marks, scale)
    check(marks == alone, "the car scan marks the same faces with them in the scene")
    # the old behaviour, for the record: the wheel in the pool stretches the box and the scale
    _t, _o, all_verts = backfill._tree(car + [o for o in loose if o.name == "wheel_lift_alloy"])
    print("     (with the wheel in the pool the scale would be %.3f instead of %.3f)" % (backfill.car_scale(all_verts), scale))
    w = bpy.data.objects["wheel_lift_alloy"]
    tree, owner, verts = backfill._tree([w])
    wm = set()
    scan(backfill, tree, owner, verts, wm, scale)
    check(len(wm) == 5 and all(n == "wheel_lift_alloy" for n, _i in wm), "a loose wheel scanned on its own gets its own backs (%d)" % len(wm))


def test_quiet_removables():
    import bake_atlas
    clear()
    shell = box("body", (1.8, 4.5, 1.6), (0.0, 0.0, 0.85))
    acc_shell = box("acc_bullbar", (1.6, 0.3, 0.8), (0.0, 2.1, 0.7))                 # on the shell sheet
    acc_other = box("acc_offroad_ladder", (0.1, 0.3, 0.9), (0.95, -1.55, 1.3))       # on the offroad sheet
    wheel = box("wheel_lift_alloy", (0.24, 0.76, 0.76), (4.0, 0.0, 0.38))            # on the lift sheet
    flags = bake_atlas.RAY_FLAGS

    def on(o):
        return all(getattr(o, a) for a in flags)

    def off(o):
        return not any(getattr(o, a) for a in flags)

    spaces = bake_atlas.SPACES
    check("acc_offroad_ladder" not in spaces["shell"][0] and "wheel_lift_alloy" not in spaces["shell"][0],
          "the ladder and the lift wheel bake on other sheets than the shell")
    saved = bake_atlas.quiet_removables(spaces["shell"][0])
    check(off(acc_shell) and off(acc_other), "shell bake: every acc_ mesh, the offroad ladder included, is out of the rays")
    check(off(wheel), "shell bake: the lift's wheel (another sheet) is out of the rays")
    check(on(shell), "shell bake: the body itself still casts and receives")
    bake_atlas.restore_rays(saved)
    check(on(wheel) and off(acc_other) and off(acc_shell), "after the shell: the wheel is back, the accessories stay out")
    lift = [n for n, (names, _s) in spaces.items() if "wheel_lift_alloy" in names]
    check(lift == ["lift"], "the lift wheel's sheet is 'lift' (%s)" % lift)
    saved = bake_atlas.quiet_removables(spaces["lift"][0])
    check(on(wheel), "lift bake: its own wheel keeps its rays (spoke and tyre occlusion)")
    bake_atlas.restore_rays(saved)
    check(on(wheel), "and after it")


def main():
    test_backfill()
    test_quiet_removables()
    if FAILS:
        print("%d FAIL(S)" % len(FAILS))
        sys.exit(1)
    print("PIPELINE SCAN TESTS OK")


main()
