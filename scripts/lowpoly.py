r"""
Quadric edge-collapse decimation with the guards Blender's Decimate modifier lacks (v6, 2026-10).

Blender's collapse decimator, run on the kotris parts at KI5 budgets (7-25x fewer triangles),
left folded and flipped triangles: holes in the windscreen and the rear quarters once the game
culls back faces, dents where a face had turned against the surface. Its flip check compares a
face with its CURRENT normal, so many small turns add up to a flip. This one:

  * scores collapses with Garland-Heckbert quadrics (area-weighted face planes) plus constraint
    planes along open edges and material borders, so outlines and material splits stay put;
  * refuses a collapse that would turn any surviving face more than ~70 degrees from the ORIGINAL
    surface under it, or more than 60 degrees in one step, or make it degenerate;
  * keeps topology: link condition (no pinching into non-manifold edges), never collapses an
    interior edge between two border vertices, never shrinks a closed piece below a tetrahedron,
    border corners and junctions are locked;
  * a vertex on a border only moves along it (the other end of the edge comes to it).

Runs in Blender (bmesh). decimate(me, target_tris) works in place on a Mesh and returns the
triangle count reached; when the strict pass stalls above the target, a second pass lets material
borders move (open edges stay locked).
"""
import heapq
import math

import bmesh
from mathutils import Vector

BORDER_W = 40.0          # constraint-plane weight along open edges and material borders (x length^2)
REF_DOT = 0.34           # surviving faces stay within ~70 deg of the original surface normal
STEP_DOT = 0.5           # ... and within 60 deg of their current normal in one collapse
MIN_QUALITY = 0.02       # 2*area / longest_edge^2: refuse to create needles thinner than this
SEAM_TOL = 0.006         # outline vertices where another panel's outline meets this one (shut lines,
                         # bumper-to-quarter joints): a gap there shows the ground, so 3 mm
MAX_DEV = 0.012          # soft budget: no collapse may put a vertex or a new face's centre further than
                         # this from the original surface (a hard budget sank the roof by 25 cm)
BORDER_TOL = 0.010       # an open edge (panel outline, arch lip, rim edge) stays within 10 mm of the
                         # original: straightened outlines opened see-through gaps (pzview, v6 first pass)


def _seg_dist(p, a, b):
    ab = b - a
    L2 = ab.length_squared
    if L2 < 1e-14:
        return (p - a).length
    t = max(0.0, min(1.0, (p - a).dot(ab) / L2))
    return (p - (a + ab * t)).length


def _plane_q(n, p, w):
    a, b, c = n
    d = -(a * p[0] + b * p[1] + c * p[2])
    return [w * a * a, w * a * b, w * a * c, w * b * b, w * b * c, w * c * c, w * a * d, w * b * d, w * c * d, w * d * d]


def _qadd(q, r):
    return [x + y for x, y in zip(q, r)]


def _qcost(q, v):
    x, y, z = v
    return (q[0] * x * x + 2 * q[1] * x * y + 2 * q[2] * x * z + q[3] * y * y + 2 * q[4] * y * z + q[5] * z * z
            + 2 * (q[6] * x + q[7] * y + q[8] * z) + q[9])


def _qopt(q):
    a11, a12, a13, a22, a23, a33, b1, b2, b3, _c = q
    c11 = a22 * a33 - a23 * a23
    c12 = a13 * a23 - a12 * a33
    c13 = a12 * a23 - a13 * a22
    det = a11 * c11 + a12 * c12 + a13 * c13
    tr = a11 + a22 + a33
    if tr <= 0.0 or abs(det) < 1e-7 * tr * tr * tr:
        return None
    c22 = a11 * a33 - a13 * a13
    c23 = a12 * a13 - a11 * a23
    c33 = a11 * a22 - a12 * a12
    r1, r2, r3 = -b1, -b2, -b3
    return Vector(((c11 * r1 + c12 * r2 + c13 * r3) / det,
                   (c12 * r1 + c22 * r2 + c23 * r3) / det,
                   (c13 * r1 + c23 * r2 + c33 * r3) / det))


def _tri_normal(p0, p1, p2):
    n = (p1 - p0).cross(p2 - p0)
    return n


class _Decimator:
    def __init__(self, bm, lock_materials=True, border_tol=BORDER_TOL, seam_kd=None, hi_tree=None, max_dev=None,
                 hold=None):
        self.bm = bm
        self.hi_tree = hi_tree
        self.max_dev = max_dev
        self.lock_materials = lock_materials
        self.border_tol = border_tol
        # the original surface normal rides each face in a layer (adding a layer later would
        # invalidate every element wrapper, so it is created before anything is keyed on them)
        self.lay = bm.faces.layers.float_vector.get("lp_ref")
        if self.lay is None:
            bm.normal_update()
            self.lay = bm.faces.layers.float_vector.new("lp_ref")
            for f in bm.faces:
                f[self.lay] = f.normal
        bm.verts.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        bm.normal_update()
        self.Q = {v: [0.0] * 10 for v in bm.verts}
        for f in bm.faces:
            q = _plane_q(f.normal, f.verts[0].co, f.calc_area())
            for v in f.verts:
                self.Q[v] = _qadd(self.Q[v], q)
        self.border = {v: 0 for v in bm.verts}   # number of border edges at the vertex
        for e in bm.edges:
            if self._is_border(e):
                a, b = e.verts
                self.border[a] += 1
                self.border[b] += 1
                f = e.link_faces[0] if e.link_faces else None
                if f is None:
                    continue
                d = b.co - a.co
                L = d.length
                if L < 1e-9:
                    continue
                m = d.cross(f.normal)
                if m.length < 1e-12:
                    continue
                m.normalize()
                q = _plane_q(m, a.co, BORDER_W * L * L)
                self.Q[a] = _qadd(self.Q[a], q)
                self.Q[b] = _qadd(self.Q[b], q)
        self.locked = {v for v, k in self.border.items() if k not in (0, 2)}
        # held vertices (indices, resolved here: the layer above invalidates earlier wrappers; or the
        # BMVerts a previous pass held) keep their place, so the faces wholly among them keep the
        # original's exact shape (a neighbour outside may still collapse onto one)
        self.held = {bm.verts[v] if isinstance(v, int) else v for v in (hold or ())}
        self.locked |= self.held
        # original positions each open-outline vertex stands for (grows as outline vertices merge)
        self.bpts = {}
        for e in bm.edges:
            if len(e.link_faces) == 1:
                for v in e.verts:
                    if v in self.bpts:
                        continue
                    tol = border_tol
                    if seam_kd is not None and border_tol is not None and seam_kd.find(v.co)[2] is not None \
                            and seam_kd.find(v.co)[2] < 1e-5:
                        tol = min(border_tol, SEAM_TOL)
                    self.bpts[v] = [(v.co.copy(), tol)]
        self.ver = {v: 0 for v in bm.verts}
        self.heap = []
        self.seq = 0
        for e in bm.edges:
            self._push(e.verts[0], e.verts[1])

    def _is_border(self, e):
        lf = e.link_faces
        if len(lf) != 2:
            return True
        return self.lock_materials and lf[0].material_index != lf[1].material_index

    def _candidates(self, a, b):
        if a in self.locked and b in self.locked:
            return []
        ba, bb = self.border[a] > 0, self.border[b] > 0
        if a in self.locked:                # a held vertex off every border never pulls an outline in
            return [a.co.copy()] if ba or not bb else []
        if b in self.locked:
            return [b.co.copy()] if bb or not ba else []
        if ba and not bb:
            return [a.co.copy()]
        if bb and not ba:
            return [b.co.copy()]
        out = [a.co.copy(), b.co.copy(), (a.co + b.co) * 0.5]
        q = _qadd(self.Q[a], self.Q[b])
        o = _qopt(q)
        if o is not None:
            mid = (a.co + b.co) * 0.5
            if (o - mid).length <= (a.co - b.co).length:        # an optimum far off the edge is noise
                out.append(o)
        return out

    def _push(self, a, b):
        cands = self._candidates(a, b)
        if not cands:
            return
        q = _qadd(self.Q[a], self.Q[b])
        best = min(cands, key=lambda c: _qcost(q, c))
        cost = _qcost(q, best)
        self.seq += 1
        heapq.heappush(self.heap, (cost, self.seq, a, b, self.ver[a], self.ver[b], best))

    def _valid(self, a, b, co):
        e = self.bm.edges.get((a, b))
        if e is None:
            return False
        if self.border[a] > 0 and self.border[b] > 0 and not self._is_border(e):
            return False                                            # would pinch the surface
        na = {x.other_vert(a) for x in a.link_edges}
        nb = {x.other_vert(b) for x in b.link_edges}
        common = na & nb
        opp = {v for f in e.link_faces for v in f.verts if v is not a and v is not b}
        if common != opp:
            return False                                            # link condition
        if len((na | nb) - {a, b}) <= 2:
            return False                                            # closed piece at its minimum
        if self.border_tol is not None and len(e.link_faces) == 1:  # collapsing along an open outline:
            pa = [x.other_vert(a) for x in a.link_edges if len(x.link_faces) == 1 and x.other_vert(a) is not b]
            pb = [x.other_vert(b) for x in b.link_edges if len(x.link_faces) == 1 and x.other_vert(b) is not a]
            segs = [(pa[0].co, co)] if pa else []
            if pb:
                segs.append((co, pb[0].co))
            for p, tol in self.bpts.get(a, [(a.co, self.border_tol)]) + self.bpts.get(b, [(b.co, self.border_tol)]):
                d = min((_seg_dist(p, s0, s1) for s0, s1 in segs), default=(p - co).length)
                if d > tol:
                    return False                                    # it would pull the outline in
        gone = set(e.link_faces)
        if self.hi_tree is not None:
            md = self.max_dev
            if isinstance(md, dict):                                # per material index: the tightest
                md = min((md.get(f.material_index, md.get(None, MAX_DEV)) for v in (a, b) for f in v.link_faces),
                         default=md.get(None, MAX_DEV))
            hit = self.hi_tree.find_nearest(co)
            if hit[0] is not None and hit[3] > md:
                return False                                        # the vertex leaves the surface
            for v in (a, b):
                for f in v.link_faces:
                    if f in gone:
                        continue
                    ps = [co if (u is a or u is b) else u.co for u in f.verts]
                    hit = self.hi_tree.find_nearest((ps[0] + ps[1] + ps[2]) / 3.0)
                    if hit[0] is not None and hit[3] > md:
                        return False                                # a face cuts across a hollow
        for v in (a, b):
            for f in v.link_faces:
                if f in gone:
                    continue
                ps = [co if (u is a or u is b) else u.co for u in f.verts]
                n = _tri_normal(ps[0], ps[1], ps[2])
                L = n.length
                if L < 1e-12:
                    return False
                n = n / L
                if n.dot(f[self.lay]) < REF_DOT or n.dot(f.normal) < STEP_DOT:
                    return False
                longest = max((ps[0] - ps[1]).length_squared, (ps[1] - ps[2]).length_squared, (ps[2] - ps[0]).length_squared)
                if L / max(longest, 1e-12) < MIN_QUALITY:
                    old = [u.co for u in f.verts]
                    lo = _tri_normal(old[0], old[1], old[2]).length
                    lold = max((old[0] - old[1]).length_squared, (old[1] - old[2]).length_squared, (old[2] - old[0]).length_squared)
                    if L / max(longest, 1e-12) < lo / max(lold, 1e-12):
                        return False                                # a new or thinner needle
        return True

    def run(self, target):
        bm = self.bm
        nf = len(bm.faces)
        while self.heap and nf > target:
            cost, _s, a, b, va, vb, co = heapq.heappop(self.heap)
            if not (a.is_valid and b.is_valid) or self.ver[a] != va or self.ver[b] != vb:
                continue
            if not self._valid(a, b, co):
                continue
            q = _qadd(self.Q[a], self.Q[b])
            border = max(self.border[a], self.border[b])
            locked = a in self.locked or b in self.locked
            held = a in self.held or b in self.held
            pts = self.bpts.get(a, []) + self.bpts.get(b, [])
            bmesh.ops.pointmerge(bm, verts=[a, b], merge_co=co)
            s = a if a.is_valid else b
            if not s.is_valid:
                break
            if pts:
                self.bpts[s] = pts
            self.Q[s] = q
            self.border[s] = border
            if locked:
                self.locked.add(s)
            if held:
                self.held.add(s)
            self.ver[s] = self.ver.get(s, 0) + 1
            for f in s.link_faces:
                f.normal_update()
            for x in s.link_edges:
                o = x.other_vert(s)
                self._push(s, o)
            nf = len(bm.faces)
        return nf


def decimate(me, target, report=None, border_tol=BORDER_TOL, seam_kd=None, hi_tree=None, max_dev=MAX_DEV, hold=None):
    """Decimate a Mesh in place to about `target` triangles; returns the count reached.
    border_tol None: open outlines may straighten (parts whose gaps show nothing: interior, engine).
    hold: indices of vertices that never move (see _Decimator)."""
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.triangulate(bm, faces=bm.faces[:], quad_method='BEAUTY', ngon_method='BEAUTY')
    n0 = len(bm.faces)
    d = _Decimator(bm, lock_materials=True, border_tol=border_tol, seam_kd=seam_kd, hi_tree=hi_tree, max_dev=max_dev,
                   hold=hold)
    n = d.run(target)
    if n > target * 1.05:                         # material borders let go, open edges stay locked
        d = _Decimator(bm, lock_materials=False, border_tol=border_tol, seam_kd=seam_kd, hi_tree=hi_tree, max_dev=max_dev,
                       hold={v for v in d.held if v.is_valid})
        n = d.run(target)
    bmesh.ops.dissolve_degenerate(bm, dist=1e-7, edges=bm.edges[:])
    lay = bm.faces.layers.float_vector.get("lp_ref")
    if lay is not None:
        bm.faces.layers.float_vector.remove(lay)
    bm.to_mesh(me)
    bm.free()
    me.update()
    if report:
        report("    decimate %d -> %d tris" % (n0, len(me.polygons)))
    return len(me.polygons)


def transfer_normals(low, hi, inset=0.30, smooth_deg=50.0):
    """Shade the low mesh like the high one. Each corner takes the high surface's normal sampled
    30% of the way into its own face (sampling AT the corner picked up the hems and flanges that
    kotris curls under every panel edge, and one bad corner spreads a dark wedge across a big low
    triangle), then corners around a vertex whose faces meet within smooth_deg are averaged so
    smooth regions stay smooth and real creases stay crisp."""
    import bpy
    me = low.data
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.split_edges(bm, edges=bm.edges[:])
    for f in bm.faces:
        c = f.calc_center_median()
        for v in f.verts:
            v.co = v.co + (c - v.co) * inset
    pme = bpy.data.meshes.new("_probe")
    bm.to_mesh(pme)
    bm.free()
    if len(pme.loops) != len(me.loops) or len(pme.polygons) != len(me.polygons):
        bpy.data.meshes.remove(pme)
        raise RuntimeError("normal probe of %s lost its corner order" % low.name)
    probe = bpy.data.objects.new("_probe", pme)
    low.users_collection[0].objects.link(probe)
    probe.matrix_world = low.matrix_world
    m = probe.modifiers.new("n", 'DATA_TRANSFER')
    m.object = hi
    m.use_loop_data = True
    m.data_types_loops = {'CUSTOM_NORMAL'}
    m.loop_mapping = 'POLYINTERP_NEAREST'
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    probe.select_set(True)
    bpy.context.view_layer.objects.active = probe
    with bpy.context.temp_override(object=probe, active_object=probe, selected_objects=[probe], selected_editable_objects=[probe]):
        bpy.ops.object.modifier_apply(modifier=m.name)
    sampled = [Vector(c.vector) for c in pme.corner_normals]
    bpy.data.objects.remove(probe, do_unlink=True)
    bpy.data.meshes.remove(pme)
    for p in me.polygons:
        for li in p.loop_indices:
            if sampled[li].dot(p.normal) < 0.26:      # > 75 deg off: it sampled another surface
                sampled[li] = p.normal.copy()
    _group_normals(me, sampled, smooth_deg)


def smooth_normals(me, smooth_deg=40.0):
    """Custom normals from the faces themselves, smoothed within smooth_deg (generated meshes)."""
    sampled = [None] * len(me.loops)
    for p in me.polygons:
        for li in p.loop_indices:
            sampled[li] = p.normal.copy()
    _group_normals(me, sampled, smooth_deg)


def _group_normals(me, sampled, smooth_deg):
    cos_s = math.cos(math.radians(smooth_deg))
    fn = [p.normal.copy() for p in me.polygons]
    area = [max(p.area, 1e-10) for p in me.polygons]
    face_of = [0] * len(me.loops)
    for p in me.polygons:
        for li in p.loop_indices:
            face_of[li] = p.index
    by_vert = {}
    for li, lp in enumerate(me.loops):
        by_vert.setdefault(lp.vertex_index, []).append(li)
    out = [None] * len(me.loops)
    for lis in by_vert.values():
        groups = []
        for li in lis:
            n = fn[face_of[li]]
            for g in groups:
                if fn[face_of[g[0]]].dot(n) >= cos_s:
                    g.append(li)
                    break
            else:
                groups.append([li])
        for g in groups:
            acc = Vector()
            for li in g:
                acc += sampled[li] * area[face_of[li]]
            acc = acc.normalized() if acc.length > 1e-12 else fn[face_of[g[0]]]
            for li in g:
                out[li] = acc
    me.normals_split_custom_set([tuple(n) for n in out])


def seam_points(objs, reach=0.015):
    """KD-tree of the open-outline vertices that have another island's outline (any of objs) within
    `reach`: the joints between panels, where a gap would show through the car."""
    from mathutils.kdtree import KDTree
    pts = []                                       # (position, owner key)
    for ob in objs:
        bm = bmesh.new()
        bm.from_mesh(ob.data)
        bm.transform(ob.matrix_world)
        bm.faces.ensure_lookup_table()
        isl = {}
        k = 0
        for f in bm.faces:
            if f.index in isl:
                continue
            st = [f]
            isl[f.index] = k
            while st:
                g = st.pop()
                for e in g.edges:
                    for h in e.link_faces:
                        if h.index not in isl:
                            isl[h.index] = k
                            st.append(h)
            k += 1
        for e in bm.edges:
            if len(e.link_faces) == 1:
                key = (ob.name, isl[e.link_faces[0].index])
                for v in e.verts:
                    pts.append((v.co.copy(), key))
        bm.free()
    all_kd = KDTree(len(pts))
    for i, (co, _k) in enumerate(pts):
        all_kd.insert(co, i)
    all_kd.balance()
    seam = []
    for co, key in pts:
        for _c, i, _d in all_kd.find_range(co, reach):
            if pts[i][1] != key:
                seam.append(co)
                break
    kd = KDTree(max(1, len(seam)))
    for i, co in enumerate(seam):
        kd.insert(co, i)
    kd.balance()
    return kd, len(seam)


def drop_small_islands(me, diag):
    """Delete closed pieces smaller than `diag` metres (engine bolts and clips: the decimator cannot
    take a closed piece below four faces, and the bake paints them onto what lies behind)."""
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.faces.ensure_lookup_table()
    seen = set()
    kill = []
    for f in bm.faces:
        if f.index in seen:
            continue
        grp, st = [f], [f]
        seen.add(f.index)
        while st:
            g = st.pop()
            for e in g.edges:
                for h in e.link_faces:
                    if h.index not in seen:
                        seen.add(h.index)
                        grp.append(h)
                        st.append(h)
        vs = [v.co for g in grp for v in g.verts]
        d = (Vector((max(v.x for v in vs), max(v.y for v in vs), max(v.z for v in vs)))
             - Vector((min(v.x for v in vs), min(v.y for v in vs), min(v.z for v in vs)))).length
        if d < diag:
            kill.extend(grp)
    n = len(kill)
    if kill:
        bmesh.ops.delete(bm, geom=kill, context='FACES')
        bm.to_mesh(me)
    bm.free()
    return n

