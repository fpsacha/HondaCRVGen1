r"""
Lift feature: do the lifted car's tyres clear the body, the arch liners and every fitted accessory, at
rest, at full steer and with the suspension compressed? Assembles the car from the SHIPPED files the
way pzview does (pzview.find_script / build: the vehicle script, the FBX, every part's placement) and
measures, for each tyre, the smallest gap to anything that is not a tyre and the triangles of other
models the tyre cuts (BVH overlap), located in the wheel's frame: `out` across the car from the tyre's
mid-plane (+ = outside), `fore` along the car, `up` from the hub, metres. The stock car's front tyres
already cut the body's inner wheel-well walls (out < 0, hidden behind the tyre); what matters is a cut
on the outside (out > ~0.05: fender lip, bumper, a guard) or above the tyre's top.

    blender -b --factory-startup --python scripts\lift_check.py -- [--script HondaCRVGen1LiftAlloy] [--acc]
            [--steers 0,30,-30] [--bumps 0,0.05]

--bumps lifts the wheels that much (metres) against the body: a compressed spring. Prints one
`LIFTCHECK` line per tyre and case and `LIFTCHECK DONE`. CRV_ROOT picks the data root like every other script.
"""
import math
import os
import sys

import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
STEERS = [float(s) for s in (argv[argv.index("--steers") + 1] if "--steers" in argv else "0,30,-30").split(",")]
BUMPS = [float(s) for s in (argv[argv.index("--bumps") + 1] if "--bumps" in argv else "0,0.05").split(",")]
import pzview  # noqa: E402  (reads the same argv: --script, --acc, --mod)

TYRES = ("TireFrontLeft", "TireFrontRight", "TireRearLeft", "TireRearRight")


def _mesh(ob, mw=None):
    dg = bpy.context.evaluated_depsgraph_get()
    me = ob.evaluated_get(dg).to_mesh()
    m = mw if mw is not None else ob.matrix_world
    verts = [m @ v.co for v in me.vertices]
    polys = [tuple(p.vertices) for p in me.polygons]
    ob.evaluated_get(dg).to_mesh_clear()
    return BVHTree.FromPolygons(verts, polys), verts, polys


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    vm = pzview.find_script()
    drawn, _anims = pzview.build(vm)
    wheels = {w.name: w for w in vm.all("vehicle")[0].all("wheel")}
    tyres = [o for o in drawn if o.get("pz_part") in TYRES]
    others = [o for o in drawn if o.get("pz_part") not in TYRES]
    print("LIFTCHECK %s: %d tyres against %d other models (body, liners%s)" % (
        pzview.SCRIPT or "stock", len(tyres), len(others), ", accessories" if pzview.ACC else ""))
    world = [(o.get("pz_label", o.name),) + _mesh(o) for o in others]
    U = pzview.U
    worst_out = -1e9
    for o in tyres:
        part = o["pz_part"]
        front = pzview.truthy(wheels[pzview.TIRE_WHEEL[part]].get("front", "false"))
        c = o.matrix_world.translation.copy()
        side = 1.0 if c.x > 0 else -1.0                         # outward along Blender x
        for steer in (STEERS if front else [0.0]):
            for bump in BUMPS:
                m = (Matrix.Translation(c + Vector((0, 0, bump * U))) @ Matrix.Rotation(math.radians(steer), 4, 'Z')
                     @ Matrix.Translation(-c) @ o.matrix_world)
                hub = c + Vector((0, 0, bump * U))
                tb, verts, _p = _mesh(o, m)
                gap, near = 1e9, None
                for v in verts[::3]:
                    for label, t, _v, _pp in world:
                        hit = t.find_nearest(v)
                        if hit[0] is not None and hit[3] < gap:
                            gap, near = hit[3], label
                out_max, up_max, labels, n = -1e9, -1e9, set(), 0
                for label, t, wv, wp in world:
                    for _i, j in tb.overlap(t):
                        p = sum((wv[k] for k in wp[j]), Vector()) / len(wp[j])
                        d = (p - hub) / U
                        out_max = max(out_max, d.x * side)
                        up_max = max(up_max, d.z)
                        labels.add(label)
                        n += 1
                worst_out = max(worst_out, out_max)
                cut = (" cuts %d tris of %s, outermost out %+.3f, highest up %+.3f"
                       % (n, ", ".join(sorted(labels)), out_max, up_max)) if n else ""
                print("LIFTCHECK %-15s steer %+5.1f bump %.3f: gap %.3f m (to %s)%s" % (
                    part, steer, bump, gap / U, near, cut))
    print("LIFTCHECK DONE (outermost cut %+.3f m from the tyre mid-plane)" % worst_out)


main()
