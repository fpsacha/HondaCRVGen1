r"""
Faces of the joined engine_block no camera can ever see (performance pass, 2026-10-19).

The bay is drawn every frame, even with the hood shut, and every part is a closed solid: the bottoms of
the boxes standing on the transmission, the faces pressed against the firewall, the walls buried inside
another part (the runners in the plenum, the boots in the spine), the undersides of the hoses under the
plenum. hidden_faces() casts rays from sample points on each face toward every camera the player can have
and keeps a face if any ray leaves the car; prune() deletes the rest. Conservative on purpose:
  * occluders: engine_block itself and bay_walls (OCCLUDERS) only. Not the hood (open in every view that
    shows the bay), and not the body: build_bay runs on the full-detail body, prep decimates it and refits
    the walls afterwards, so the shipped fenders could show a little more than the scanned ones (the body
    hid another ~100 triangles, measured on the 2026-10-18 build: not worth the risk);
  * cameras: parallel rays at the game's pitch (26-34 degrees) every 5 degrees of heading, the low and
    steep ones (third person, standing over the bay: 1.5 .. 89 degrees) every 10, and perspective eyes:
    every seat (backfill.eye_points) and rings of eyes round the car from knee to standing height, close
    to the bumper and further out;
  * samples: the face's centre and points 3/4 of the way to each corner, lifted 0.6 mm off the face.
A face seen through a slit narrower than the samples' spacing could be dropped: pzview's leak count and
the open-hood views are the acceptance check (the hole behind a dropped face shows the solid's culled
inside, which shows what lies behind the part).
"""
import math

import bmesh
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

# what may hide a bay face besides the bay itself (see the docstring)
OCCLUDERS = ("bay_walls",)
GLASS_MATS = ("Vitre", "Vitre_noir")
PARALLEL = [(e, 5) for e in (26.0, 30.0, 34.0)] + [(e, 10) for e in (1.5, 4.0, 10.0, 17.0, 45.0, 60.0, 75.0, 89.0)]
# (distance past the car's box, eye height) metres, every RING_AZ degrees: lying by the car (0.25 m: bug wave 3,
# IMP-VP-1, a Project Viewpoint camera low behind the car sees the strip under the rear off-road bumper and the
# hitch, which prune_hidden dropped with 0.5 m the lowest eye) and kneeling at the bumper to standing over the
# open bay, and further out
RING = [(d, h) for d in (0.25, 0.8, 2.0) for h in (0.25, 0.5, 0.95, 1.35, 1.70)]
RING_AZ = 10
LIFT = 0.0006


def _occluders(targets):
    """(BVH tree, car box (lo, hi)) of the targets (the bay's objects) and OCCLUDERS, panes left out. The box
    is the body's when there is one (the ring eyes stand round the car, not round the bay)."""
    dg = bpy.context.evaluated_depsgraph_get()
    verts, polys = [], []
    objs = list(targets) + [bpy.data.objects[n] for n in OCCLUDERS if bpy.data.objects.get(n) is not None]
    for o in objs:
        ev = o.evaluated_get(dg)
        me = ev.to_mesh()
        M = ev.matrix_world.copy()
        names = [m.name if m else "?" for m in o.data.materials]
        base = len(verts)
        verts.extend(M @ v.co for v in me.vertices)
        for p in me.polygons:
            if p.material_index < len(names) and names[p.material_index] in GLASS_MATS:
                continue
            polys.append([base + i for i in p.vertices])
        ev.to_mesh_clear()
    body = bpy.data.objects.get("body")
    pts = [body.matrix_world @ Vector(c) for c in body.bound_box] if body is not None else verts
    lo = Vector((min(v.x for v in pts), min(v.y for v in pts), min(v.z for v in pts)))
    hi = Vector((max(v.x for v in pts), max(v.y for v in pts), max(v.z for v in pts)))
    return BVHTree.FromPolygons(verts, polys, all_triangles=False), (lo, hi)


def _eyes(lo, hi):
    out = []
    try:
        import backfill
        out += [Vector(e) for e in backfill.eye_points()]
    except Exception as exc:                                         # noqa: BLE001
        print("engine_block visibility: no seat eyes (%s)" % exc)
    centre = (lo + hi) / 2
    half = (hi - lo) / 2
    for d, h in RING:
        for k in range(0, 360, RING_AZ):
            a = math.radians(k)
            r = half.x * abs(math.cos(a)) + half.y * abs(math.sin(a)) + d
            out.append(Vector((centre.x + math.cos(a) * r, centre.y + math.sin(a) * r, h)))
    return out


def hidden_faces(ob, occ=None):
    """Indices of ob's faces no camera sees (see the module docstring). ob: the joined engine_block; occ: an
    _occluders() result to reuse."""
    tree, (lo, hi) = occ or _occluders([ob])
    far = (hi - lo).length * 2
    dirs = []
    for el, step in PARALLEL:
        e = math.radians(el)
        for az in range(0, 360, step):
            a = math.radians(az)
            dirs.append(Vector((math.cos(e) * math.cos(a), math.cos(e) * math.sin(a), math.sin(e))))   # toward the camera
    eyes = _eyes(lo, hi)
    M = ob.matrix_world
    R = M.to_3x3()
    me = ob.data
    out = []
    for p in me.polygons:
        n = (R @ p.normal).normalized()
        c = M @ p.center
        pts = [c] + [c.lerp(M @ me.vertices[i].co, 0.75) for i in p.vertices]
        pts = [q + n * LIFT for q in pts]
        seen = False
        for q in pts:
            for d in dirs:
                if n.dot(d) <= 0.0:
                    continue
                if tree.ray_cast(q, d, far)[0] is None:
                    seen = True
                    break
            if seen:
                break
            for e in eyes:
                v = e - q
                L = v.length
                v /= L
                if n.dot(v) <= 0.0:
                    continue
                if tree.ray_cast(q, v, L)[0] is None:
                    seen = True
                    break
            if seen:
                break
        if not seen:
            out.append(p.index)
    return out


def prune(ob, report=print):
    """Delete the faces hidden_faces() finds (and the vertices left unused). Returns (faces, tris) removed."""
    idx = set(hidden_faces(ob))
    if not idx:
        return 0, 0
    me = ob.data
    tris = sum(len(me.polygons[i].vertices) - 2 for i in idx)
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.faces.ensure_lookup_table()
    bmesh.ops.delete(bm, geom=[bm.faces[i] for i in sorted(idx)], context='FACES_ONLY')
    loose = [v for v in bm.verts if not v.link_faces]
    if loose:
        bmesh.ops.delete(bm, geom=loose, context='VERTS')
    bm.to_mesh(me)
    bm.free()
    me.update()
    report("engine_block visibility: %d faces (%d tris) no camera sees removed" % (len(idx), tris))
    return len(idx), tris
