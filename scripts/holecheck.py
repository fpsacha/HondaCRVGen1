r"""
Hole and bulge check of the low-poly parts against their full-detail twins, as the game draws
them: shut car, back faces culled, parallel rays from the game camera (30 degrees) every 45 degrees
of azimuth, plus 45 degrees from the four corners.

    blender -b blender\import\parts_kotris.blend --python scripts\holecheck.py -- [--step 0.012] [--top 10] [--png DIR]

For every ray: the first front-facing hit on the HIGH car (every '<name>_hi' twin plus the parts
that have none: glass, liners, antenna, bay walls) and on the LOW car as it ships (the low parts,
generated faces included, plus the same twinless parts).
  hole   the low hit lies more than TOL behind the high one, or the low ray finds nothing
  bulge  the low hit lies more than TOL in front of the high one
Prints `HOLECHECK <view> holes <n> bulges <n>` per view and the biggest clusters (10 cm cells) with
the high part/material there and what the low ray hit instead; --png writes one mask per view
(grey car, red holes, blue bulges).

The exterior details (build_details, gen 7) are built to the spec's shapes, not to kotris's: the
octagonal mirror housings differ from the sculpted ones by up to 4-5 cm (about 90 px of holes
and 80 px of bulges per housing, summed over the views) and the planar wiper blades lie 2-4 cm
under kotris's chunky arms (about 300 px of holes along the screen base). Those clusters are
expected; see-through must not move. The roof rails are left out of the low tree (GEN_SKIP).
"""
import math
import os
import sys
from collections import defaultdict

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
STEP = float(argv[argv.index("--step") + 1]) if "--step" in argv else 0.012
TOP = int(argv[argv.index("--top") + 1]) if "--top" in argv else 10
PNG = argv[argv.index("--png") + 1] if "--png" in argv else None
TOL = 0.04
VIEWS = [(30.0, az) for az in range(0, 360, 45)] + [(45.0, az) for az in (45, 135, 225, 315)]
# low faces left out of the low tree: gen 7 (build_details) above z 1.60 = the roof rails, 5.5 cm
# proud of the roof by design (the hub caps' precedent). The other gen-7 pieces (handle plates,
# mirrors, flap, wipers) stay in: a plate missing over a handle hole must still count as a hole
GEN_SKIP = {7: 1.60}
# Feature wheels (features OBJECTS with file 'wheel', wheel_<feature>_*) are parked beside the car (the
# lift's at x 4 m and 6 m: the wheel FBX is centred on its own hub) and have no twin: in `other` they
# fed both trees and stretched the ray grid's box, so HOLECHECK moved with no change to the car
# (2026-10-13: holes 3521 -> 3657 on identical low parts). Like acc_* they are no part of the car.
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
try:
    import features
    FEATURE_WHEELS = set(features.wheel_objects())
except Exception as _exc:                        # noqa: BLE001  (no plugin package: no feature wheels)
    print("HOLECHECK warning: feature plugins not loaded (%s)" % _exc)
    FEATURE_WHEELS = set()


def _sets():
    lows, his, other = [], [], []
    for o in bpy.data.objects:
        if (o.type != 'MESH' or o.name == "base" or o.name.startswith("_") or o.name.startswith("acc_")
                or o.name in FEATURE_WHEELS):
            continue
        if o.name.endswith("_hi"):
            his.append(o)
        elif bpy.data.objects.get(o.name + "_hi") is not None:
            lows.append(o)
        elif not o.hide_render:
            other.append(o)
    return lows, his, other


def _tree(objs, skip_gen=None):
    verts, polys, owner = [], [], []
    for o in objs:
        M = o.matrix_world
        names = [m.name if m else "?" for m in o.data.materials]
        base = len(verts)
        verts.extend(M @ v.co for v in o.data.vertices)
        gen = None
        attr = o.data.attributes.get("gen") if skip_gen else None
        if attr is not None:
            gen = [0] * len(o.data.polygons)
            attr.data.foreach_get("value", gen)
        for p in o.data.polygons:
            if gen is not None and gen[p.index] in skip_gen and (M @ p.center).z > skip_gen[gen[p.index]]:
                continue
            polys.append([base + i for i in p.vertices])
            owner.append((o.name, names[p.material_index] if names else "?"))
    return BVHTree.FromPolygons(verts, polys, all_triangles=False), owner


def _first_front(tree, o, d, far):
    for _ in range(24):
        loc, n, idx, dist = tree.ray_cast(o, d, far)
        if loc is None:
            return None, None, -1
        if n.dot(d) < 0.0:
            return loc, (o - loc).length, idx
        o = loc + d * 1e-4
    return None, None, -1


def main():
    lows, his, other = _sets()
    hi_tree, hi_owner = _tree(his + other)
    lo_tree, lo_owner = _tree(lows + other, GEN_SKIP)
    pts = [o.matrix_world @ v.co for o in his + other for v in o.data.vertices]
    lo_c = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi_c = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    centre = (lo_c + hi_c) / 2
    radius = (hi_c - lo_c).length / 2 + 0.05
    total_h = total_b = total_t = 0
    clusters = defaultdict(lambda: [0, 0, None, None])
    for el, az in VIEWS:
        e, a = math.radians(el), math.radians(az)
        d = -Vector((math.cos(e) * math.cos(a), math.cos(e) * math.sin(a), math.sin(e)))
        right = d.cross(Vector((0, 0, 1))).normalized()
        up = right.cross(d).normalized()
        n = int(2 * radius / STEP)
        holes = bulges = hits = through = 0
        mask = [0] * (n * n) if PNG else None
        for j in range(n):
            for i in range(n):
                o = centre + right * (-radius + (i + 0.5) * STEP) + up * (-radius + (j + 0.5) * STEP) - d * (radius + 1.0)
                hl, hd, hidx = _first_front(hi_tree, o, d, 2 * radius + 2.0)
                if hl is None:
                    continue
                hits += 1
                ll, ld, lidx = _first_front(lo_tree, o, d, 2 * radius + 2.0)
                kind = 0
                if ll is None or ld > hd + TOL:
                    kind = 1
                    holes += 1
                    if ll is None:
                        through += 1               # nothing at all behind: the ground shows in game
                elif ld < hd - TOL:
                    kind = 2
                    bulges += 1
                if mask is not None:
                    mask[j * n + i] = 1 + kind
                if kind:
                    key = (kind, round(hl.x / 0.1), round(hl.y / 0.1), round(hl.z / 0.1), hi_owner[hidx])
                    c = clusters[key]
                    c[0] += 1
                    c[2] = hl
                    c[3] = lo_owner[lidx] if lidx >= 0 else ("nothing", "-")
        total_h += holes
        total_b += bulges
        total_t += through
        print("HOLECHECK el%02d az%03d  car px %6d  holes %5d (see-through %4d)  bulges %5d" % (el, az, hits, holes, through, bulges))
        if PNG:
            os.makedirs(PNG, exist_ok=True)
            img = bpy.data.images.new("hc", n, n, alpha=False)
            cols = {0: (0.0, 0.0, 0.0, 1.0), 1: (0.6, 0.6, 0.6, 1.0), 2: (1.0, 0.0, 0.0, 1.0), 3: (0.0, 0.3, 1.0, 1.0)}
            px = []
            for k in mask:
                px.extend(cols[k])
            img.pixels[:] = px
            img.filepath_raw = os.path.join(PNG, "hc_el%02d_az%03d.png" % (el, az))
            img.file_format = 'PNG'
            img.save()
            bpy.data.images.remove(img)
    print("HOLECHECK TOTAL holes %d (see-through %d) bulges %d (rays %.1f mm apart, tolerance %d mm)" % (total_h, total_t, total_b, STEP * 1000, TOL * 1000))
    for kind, label in ((1, "hole"), (2, "bulge")):
        top = sorted(((k, v) for k, v in clusters.items() if k[0] == kind), key=lambda kv: -kv[1][0])[:TOP]
        for k, (cnt, _x, loc, lo) in top:
            print("HOLECHECK %-5s %5d px at (%5.2f, %5.2f, %4.2f) high %s/%s, low ray hit %s/%s"
                  % (label, cnt, loc.x, loc.y, loc.z, k[4][0], k[4][1], lo[0], lo[1]))


main()
