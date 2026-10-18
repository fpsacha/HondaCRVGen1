r"""
Rig and export the baked parts (crv_kotris.blend, written by bake_atlas.py).

    blender -b blender\crv_kotris.blend --python scripts\run_export.py
"""
import importlib
import os
import sys

import bpy

ROOT = os.environ.get("CRV_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(globals().get("__file__") or os.path.join("scripts", "_"))))
SCRIPTS = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.append(SCRIPTS)
import export_fbx  # noqa: E402
import rig_vehicle  # noqa: E402

for m in (rig_vehicle, export_fbx):
    importlib.reload(m)
rig_vehicle.make_struts()                 # the glass's gas struts: built here, skinned by build(), then joined
arm = rig_vehicle.build()                 # the bake file carries no rig: rebuild it from the constants
rig_vehicle.join_struts()                 # into trunk_top, so the glass model draws them on the gate's track
for n in ["base"] + [o.name for o in bpy.data.objects if o.name.endswith("_hi")]:
    ob = bpy.data.objects.get(n)           # the kotris base and the v6 bake sources never ship
    if ob:
        bpy.data.objects.remove(ob, do_unlink=True)
GLASS = ("Vitre", "Vitre_noir")


PANE_DOT = 0.85                           # faces within ~32 degrees of a pane's mean normal belong to it
                                          # (0.92, 23 degrees, split the windscreen: its wrap at the A-pillars
                                          # turns ~25 degrees, so strips there, and any decimated sliver run
                                          # down to a lower corner, lit as pale streaks, 2026-10-13; the
                                          # windscreen and the quarter glass are still 50+ degrees apart)
PANE_MIN_AREA = 0.002                     # m2 (20 cm2): smaller clusters are slivers, not panes (the smallest
                                          # real pane, a rear quarter glass, is 0.26 m2)
PANE_DETAIL_AREA = 0.0012                 # m2: a small non-glass piece sitting on a pane (the gate glass's two
PANE_DETAIL_SIZE = 0.04                   # corner stops, 8 cm2, 2.8 cm across) shades with the pane
PANE_DETAIL_GAP = 0.025                   # (every vertex within 2.5 cm of the glass)


def _pane_normals(polys):
    """One normal per pane: glass faces of an object clustered by facing (greedy, area-weighted mean).
    kotris builds the windscreen and the rear glass from several unwelded shells (clear rings and a
    frit band) whose corner normals differ by a few degrees; under the game's 3-step light (and pzview's
    studio light) each shell lit as its own lighter or darker rectangle (planar repaint, 2026-10-12).
    A pane is a flat sheet of glass: one normal for all of it shades it as one."""
    clusters = []                         # [sum vector, [poly indices]]
    for p in sorted(polys, key=lambda q: -q.area):
        n = p.normal
        for c in clusters:
            m = c[0].normalized()
            if m.dot(n) >= PANE_DOT:
                c[0] += n * p.area
                c[1].append(p.index)
                break
        else:
            clusters.append([n * p.area, [p.index]])
    # 2026-10-14: a cluster too small to be a pane (a decimation sliver whose facing is off by more than
    # PANE_DOT: window_fl had one, 0.4 cm2, 46 degrees off) joins the pane of its nearest face instead of
    # shading on its own normal
    by = {p.index: p for p in polys}
    small = [c for c in clusters if sum(by[i].area for i in c[1]) < PANE_MIN_AREA]
    big = [c for c in clusters if c not in small]
    for c in small if big else []:
        ctr = [by[i].center for i in c[1]]
        near = min(big, key=lambda b: min((by[j].center - q).length for j in b[1] for q in ctr))
        near[1].extend(c[1])
        clusters.remove(c)
    out = {}
    for vec, ids in clusters:
        m = tuple(vec.normalized())
        for i in ids:
            out[i] = m
    return out


def _pane_details(me, names, pane):
    """Small non-glass pieces sitting ON a pane take that pane's normal ({poly index: normal}; faces turned
    away from the pane take it negated). The gate glass carries two 4-face black stops at its lower
    corners whose facets lit up as a ~10 px pale triangle at the lower right corner from the rear
    three-quarter views (2026-10-14: pzview probe trunk_top face 74, (0.533, -2.005, 1.211)) while every
    glass face round it already shaded with the pane."""
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    gl = [p for p in me.polygons if p.index in pane]
    if not gl:
        return {}
    tree = BVHTree.FromPolygons([v.co for v in me.vertices], [tuple(p.vertices) for p in gl])
    key = {v.index: tuple(round(c, 4) for c in v.co) for v in me.vertices}
    parent = {}

    def find(a):
        while parent.setdefault(a, a) != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    gen = me.attributes.get("gen")                    # kotris's own pieces only: prep's backing plates (gen 5,
    rest = [p for p in me.polygons if p.index not in pane and names[p.material_index] not in GLASS   # SeamBack)
            and names[p.material_index] not in ("SeamBack", "Dessous") and (gen is None or gen.data[p.index].value == 0)]
    for p in rest:                                     # components welded by position (kotris leaves duplicates)
        ks = [key[v] for v in p.vertices]
        for k in ks[1:]:
            ra, rb = find(ks[0]), find(k)
            if ra != rb:
                parent[ra] = rb
    comps = {}
    for p in rest:
        comps.setdefault(find(key[p.vertices[0]]), []).append(p)
    out = {}
    for ps in comps.values():
        if sum(p.area for p in ps) > PANE_DETAIL_AREA:
            continue
        co = [me.vertices[v].co for p in ps for v in p.vertices]
        if max(max(c[i] for c in co) - min(c[i] for c in co) for i in range(3)) > PANE_DETAIL_SIZE:
            continue
        hits = [tree.find_nearest(c) for c in co]
        if any(h[0] is None or h[3] > PANE_DETAIL_GAP for h in hits):
            continue
        m = pane[gl[min(hits, key=lambda h: h[3])[2]].index]
        for p in ps:
            out[p.index] = m if p.normal.dot(Vector(m)) >= 0 else tuple(-c for c in m)
    return out


def double_glass(ob):
    """Glass gets a back face (a flipped copy on the same UVs): vehicles are always back-face culled,
    so a single-sided pane vanished seen from inside: an open door's window, the far side's windows
    through the windscreen. Every glass corner takes its pane's single normal (_pane_normals), the
    copies its negation; every other corner keeps its normal."""
    import bmesh
    me = ob.data
    names = [m.name if m else "?" for m in me.materials]
    if not any(n in GLASS for n in names):
        return 0
    before = [tuple(c.vector) for c in me.corner_normals]
    pane = _pane_normals([p for p in me.polygons if names[p.material_index] in GLASS])
    for p in me.polygons:
        if p.index in pane:
            for li in p.loop_indices:
                before[li] = pane[p.index]
    details = _pane_details(me, names, pane)       # small pieces sitting on a pane shade with it (2026-10-14)
    for i, m in details.items():
        for li in me.polygons[i].loop_indices:
            before[li] = m
    if details:
        print("GLASS %s: %d faces of small pieces on a pane take its normal" % (ob.name, len(details)))
    at = {tuple(round(c, 5) for c in p.center): pane[p.index] for p in me.polygons if p.index in pane}
    bm = bmesh.new()
    bm.from_mesh(me)
    faces = [f for f in bm.faces if names[f.material_index] in GLASS]
    if not faces:
        bm.free()
        return 0
    means = {}                                     # pane normal -> itself, to match the copies by facing
    for m in pane.values():
        means[m] = m
    means = list(means)
    ret = bmesh.ops.duplicate(bm, geom=faces)
    new = [e for e in ret["geom"] if isinstance(e, bmesh.types.BMFace)]
    bmesh.ops.reverse_faces(bm, faces=new)
    bm.to_mesh(me)
    bm.free()
    me.update()
    n0 = len(before)
    normals = list(before)
    copies = me.polygons[len(me.polygons) - len(new):]
    for poly in copies:                            # a copy faces its pane's way reversed: take that pane's
        back = -poly.normal                        # normal, negated (duplicate() does not promise an order)
        own = at.get(tuple(round(c, 5) for c in poly.center))   # its original's pane, found by position (a
        if own is not None:                                     # merged sliver is off every mean by > PANE_DOT)
            normals.extend([tuple(-c for c in own)] * len(poly.loop_indices))
            continue
        m = max(means, key=lambda c: back.dot(c)) if means else None
        nrm = tuple(-c for c in m) if m is not None and back.dot(m) >= PANE_DOT else tuple(poly.normal)
        normals.extend([nrm] * len(poly.loop_indices))
    if len(normals) == len(me.loops) and all(i < n0 for p in me.polygons[:len(me.polygons) - len(new)] for i in p.loop_indices):
        me.normals_split_custom_set(normals)
    return len(new)


# Lamps (2026-10-14 review, "crack line and patchy facets on the left tail lamp lens"):
# 1. prep_parts._island_backing puts a SeamBack plate 6 mm behind every glass and lamp island, grown 1.5 cm
#    past its outline, so a hairline crack shows something instead of the cabin. Behind a lamp it showed
#    the dark block: kotris's lens is several unwelded pieces (the red lens, the down-facing chrome step
#    above the reverse lens), and between them the camera saw the step's plate as a dark 1-2 px line across
#    the red (pzview probe base faces 3501-3510, SeamBack, (-0.68, -1.90, 1.247)). A lens is lit glass all
#    through: each corner of a plate whose centre lies behind a lamp (the nearest backed face is a lamp's)
#    takes the UV of the nearest point of the lamps in front of it, so a crack shows the lens beside it
#    (its colour, its Mask zone: it lights with it).
# 2. The low lens's facets carry the normals transferred piece by piece from kotris's unwelded shells (some
#    corners 50+ degrees off their face, pointing up), and under the game's stepped light each piece shaded
#    as its own lighter or darker rectangle. A lens is one smooth surface: every lens corner takes the
#    area-weighted normal of the lens faces round it (LENS_R) within LENS_DOT of its own face (the lens
#    wraps the body corner smoothly; the chrome step stays apart).
LAMP_MATS = ("Phare", "Phare_vitre", "Phare_orange", "Feux_rouge", "Feux_orange", "Feux_blanc", "Feux_stop",
             "Reflect_red", "Reflect_orange", "Feux_chrome")       # prep_parts.BACKING_MATS less the glass
LAMP_LENS = ("Phare", "Phare_vitre", "Phare_orange", "Feux_rouge", "Feux_orange", "Feux_blanc", "Feux_stop")
LAMP_BACK_REACH = 0.03         # metres: a plate face maps to a lamp face within this of its centre (6 mm + 1.5 cm rim)
LENS_MATS = ("Feux_rouge", "Feux_orange", "Feux_blanc", "Feux_stop", "Reflect_red")
LENS_DOT = 0.5                 # 60 degrees: a fold sharper than that (the lens's step) keeps its edge
LENS_R = 0.05                  # metres: the neighbourhood a lens corner's normal is averaged over


def lamp_backing_uvs(ob):
    """SeamBack plates behind lamp islands sample the lamp in front of them (see above). Returns plates remapped."""
    from mathutils import Vector, geometry
    from mathutils.bvhtree import BVHTree
    me = ob.data
    names = [m.name if m else "?" for m in me.materials]
    if not me.uv_layers:
        return 0
    lamp = [p for p in me.polygons if names[p.material_index] in LAMP_MATS]
    backed = [p for p in me.polygons if names[p.material_index] in LAMP_MATS + GLASS]
    plates = [p for p in me.polygons if names[p.material_index] == "SeamBack"]
    if not lamp or not plates:
        return 0
    co = [v.co.copy() for v in me.vertices]
    t_lamp = BVHTree.FromPolygons(co, [tuple(p.vertices) for p in lamp])
    lens = [p for p in lamp if names[p.material_index] in LAMP_LENS]
    t_lens = BVHTree.FromPolygons(co, [tuple(p.vertices) for p in lens]) if lens else None
    t_back = BVHTree.FromPolygons(co, [tuple(p.vertices) for p in backed])
    uv = me.uv_layers[0].data
    k = 0
    for p in plates:
        h = t_back.find_nearest(p.center, LAMP_BACK_REACH)
        if h[0] is None or names[backed[h[2]].material_index] not in LAMP_MATS:
            continue                           # behind glass (the rubber's dark), or nothing in front
        # ONE lamp face per plate face (its corners on different lens pieces would span several charts and
        # sample the sheet between them): the nearest lens face (a crack in the red shows red, not the
        # chrome step beside it), else the nearest lamp face; each corner takes the UV of its closest point
        # on that face, so the plate stays inside the face's own UV triangle
        h = t_lens.find_nearest(p.center, LAMP_BACK_REACH) if t_lens is not None else (None,)
        q = lens[h[2]] if h[0] is not None else None
        if q is None:
            h = t_lamp.find_nearest(p.center, LAMP_BACK_REACH)
            if h[0] is None:
                continue
            q = lamp[h[2]]
        qv = [co[i] for i in q.vertices]
        qu = [Vector((uv[l].uv[0], uv[l].uv[1], 0.0)) for l in q.loop_indices]
        for li, vi in zip(p.loop_indices, p.vertices):
            best = None
            for j in range(1, len(qv) - 1):    # the fan triangle of the face closest to the corner
                cp = geometry.closest_point_on_tri(co[vi], qv[0], qv[j], qv[j + 1])
                d = (cp - co[vi]).length
                if best is None or d < best[0]:
                    best = (d, cp, j)
            _d, cp, j = best
            m = geometry.barycentric_transform(cp, qv[0], qv[j], qv[j + 1], qu[0], qu[j], qu[j + 1])
            uv[li].uv = (m[0], m[1])
        k += 1
    return k


def lens_normals(ob):
    """Lens corners take the smooth normal of the lens round them (see above): the area-weighted normals of
    the lens faces whose centres lie within LENS_R, tapering with distance, that face within LENS_DOT of
    the corner's own face. By distance, not by shared vertices: kotris's lens pieces meet in T-junctions,
    and a smoothing over welded corners left each piece its own flat tone. Returns corners set."""
    from mathutils import Vector, kdtree
    me = ob.data
    names = [m.name if m else "?" for m in me.materials]
    polys = [p for p in me.polygons if names[p.material_index] in LENS_MATS]
    if not polys:
        return 0
    kd = kdtree.KDTree(len(polys))
    for i, p in enumerate(polys):
        kd.insert(p.center, i)
    kd.balance()
    normals = [tuple(c.vector) for c in me.corner_normals]
    k = 0
    for p in polys:
        for li, vi in zip(p.loop_indices, p.vertices):
            s = Vector()
            for _co, i, d in kd.find_range(me.vertices[vi].co, LENS_R):
                q = polys[i]
                if q.normal.dot(p.normal) >= LENS_DOT:
                    s += q.normal * q.area * (1.0 - d / LENS_R)
            if s.length > 1e-12:
                normals[li] = tuple(s.normalized())
                k += 1
    for p in polys:
        p.use_smooth = True
    me.normals_split_custom_set(normals)
    return k


for o in list(bpy.data.objects):
    if o.type == 'MESH' and not o.name.startswith("acc_"):
        nb, nn = lamp_backing_uvs(o), lens_normals(o)
        if nb or nn:
            print("GLASS %s: %d lamp backing plates sample the lens in front, %d lens corners smoothed" % (o.name, nb, nn))

import backfill  # noqa: E402
importlib.reload(backfill)
backfill.fill(arm, skip_mats=GLASS + ("SeamBack",))   # every face the game camera can see from behind, shut or open
                                          # (SeamBack: prep's backing plates and gutter strips behind seams, one-sided
                                          # on purpose; skipping ALL gen-5 faces instead stripped the door bands and lips
                                          # of their backs and opened the doors and gate to the ground, v9)
                                          # (glass excluded: all of it is doubled next; a pane already
                                          # doubled has a coincident back the rays pick at random)
for o in list(bpy.data.objects):
    if o.type == 'MESH' and o.name in ("body", "trunk_top", "window_fl", "window_fr", "window_rl", "window_rr"):
        print("GLASS %s: %d panes doubled" % (o.name, double_glass(o)))

for name in ("body", "hood", "door_fl", "interior", "cabin", "wheel_FR"):
    ob = bpy.data.objects.get(name)
    print("UVCHECK", name, "uv_baked" in ob.data if ob else None, [u.name for u in ob.data.uv_layers] if ob else None)
export_fbx.export_all()
print("EXPORT RUN DONE")
