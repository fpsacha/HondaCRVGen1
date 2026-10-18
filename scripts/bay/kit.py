r"""
Engine bay v2 kit (spec/engine-bay-v2.md): mesh builders, the palette, decal materials and the Bay
object every group module draws into.

Coordinates are model metres: +x the car's right (passenger side, LHD), +y forward (nose), +z up.
Every part is built at its FINAL triangle count: nothing is decimated afterwards and there is no
full-detail twin, so the bake reads each part's own flat material colour (plus decals) and its own AO.

Shading: every face is smooth-shaded and edges sharper than an object's `sharp` angle (degrees) are
marked sharp, so a box stays crisp, a 6-sided hose reads round (sharp=70) and a chamfered casting
reads rounded (rbox: bevel + sharp 50). The game culls back faces: every part must be a closed solid
(the builders here are), or a sheet with real thickness.
"""
import math
import os

import bmesh
import bpy
from mathutils import Vector

ROOT = os.environ.get("CRV_ROOT") or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(globals().get("__file__") or os.path.join("scripts", "_")))))
BAKE = os.path.join(ROOT, "blender", "bake")
X, Y, Z = Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))

# the flat colours: palette.py (shared with the Pillow paint modules)
from bay.palette import PALETTE  # noqa: E402

# Decal materials: name -> (png in blender/bake, (u axis, u0, u1), (v axis, v0, v1), fallback palette
# name). u = (coord - u0) / (u1 - u0) in object space (the joined engine_block has an identity
# transform). Group modules declare theirs in their own DECALS dict; the builder registers them.
# Name them "Decal..." (bake_atlas gives Decal* faces 3x texel density). A missing png falls back to
# the flat colour, so a group builds before its paint module has run.
DECALS = {}
AXIS = {"x": 0, "y": 1, "z": 2}


def register_decals(table):
    for name, spec in table.items():
        if not name.startswith("Decal"):
            raise ValueError("decal material %s must be named Decal..." % name)
        DECALS[name] = spec


# ----------------------------------------------------------------------------- materials
def _flat_material(name, rgb, rough):
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = next((n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
    if bsdf:
        bsdf.inputs['Base Color'].default_value = tuple(rgb) + (1.0,)
        bsdf.inputs['Roughness'].default_value = rough
    mat.diffuse_color = tuple(rgb) + (1.0,)
    return mat


def _decal_material(name, png, u, v, fallback):
    path = os.path.join(BAKE, png)
    if not os.path.exists(path):
        print("bay: decal %s has no %s yet, flat %s" % (name, png, fallback))
        rgb, rough = PALETTE[fallback]
        old = bpy.data.materials.get(name)
        if old is not None and old.use_nodes:                 # an earlier run's image nodes: drop them
            for n in [n for n in old.node_tree.nodes if n.name.startswith("CRV_")]:
                old.node_tree.nodes.remove(n)
        return _flat_material(name, rgb, rough)
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        if n.name.startswith("CRV_"):
            nt.nodes.remove(n)
    bsdf = next((n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED'), None)
    if bsdf is None:
        return mat
    bsdf.inputs['Roughness'].default_value = PALETTE[fallback][1]
    img = bpy.data.images.load(path, check_existing=True)
    img.reload()
    coord = nt.nodes.new('ShaderNodeTexCoord'); coord.name = "CRV_COORD"
    sep = nt.nodes.new('ShaderNodeSeparateXYZ'); sep.name = "CRV_SEP"
    nt.links.new(coord.outputs['Object'], sep.inputs['Vector'])
    comb = nt.nodes.new('ShaderNodeCombineXYZ'); comb.name = "CRV_COMB"
    for slot, (axis, a0, a1) in (("X", u), ("Y", v)):
        m = nt.nodes.new('ShaderNodeMath'); m.name = "CRV_M" + slot; m.operation = 'MULTIPLY_ADD'
        nt.links.new(sep.outputs[AXIS[axis]], m.inputs[0])
        m.inputs[1].default_value = 1.0 / (a1 - a0)
        m.inputs[2].default_value = -a0 / (a1 - a0)
        nt.links.new(m.outputs[0], comb.inputs[slot])
    tex = nt.nodes.new('ShaderNodeTexImage'); tex.name = "CRV_TEX"; tex.image = img; tex.extension = 'EXTEND'
    nt.links.new(comb.outputs['Vector'], tex.inputs['Vector'])
    nt.links.new(tex.outputs['Color'], bsdf.inputs['Base Color'])
    mat.diffuse_color = tuple(PALETTE[fallback][0]) + (1.0,)
    return mat


def material(name):
    """The bpy material for a palette or decal name. Palette materials are created as "Bay<name>" so a
    generic name ("Plastic", "Steel") never recolours another script's material of the same name."""
    if name in DECALS:
        png, u, v, fallback = DECALS[name]
        return _decal_material(name, png, u, v, fallback)
    if name not in PALETTE:
        raise KeyError("bay: no palette colour %r (kit.PALETTE)" % name)
    rgb, rough = PALETTE[name]
    return _flat_material("Bay" + name, rgb, rough)


# ----------------------------------------------------------------------------- mesh data
# Every *_data function returns (verts, faces): a list of xyz tuples and a list of index tuples.
def box_data(x0, x1, y0, y1, z0, z1):
    v = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
         (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    # faces: 0 bottom, 1 top, 2 rear(-y), 3 right(+x), 4 front(+y), 5 left(-x)
    f = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    return v, f


BOX_FACE = {"bottom": 0, "top": 1, "rear": 2, "right": 3, "front": 4, "left": 5}


def hexa_data(bottom4, top4):
    """Six-sided solid from two matching 4-point rings (a twisted blade, a bracket, a wedge)."""
    v = list(bottom4) + list(top4)
    f = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    return v, f


def frame(ax):
    """Unit axis plus two perpendicular unit vectors (u, w)."""
    ax = Vector(ax).normalized()
    ref = Z if abs(ax.z) < 0.9 else X
    u = ax.cross(ref).normalized()
    return ax, u, ax.cross(u)


def cyl_data(p0, p1, r, seg, r1=None):
    """Closed cylinder (a cone if r1 is given) from p0 to p1."""
    r1 = r if r1 is None else r1
    d = Vector(p1) - Vector(p0)
    if d.length < 1e-6:
        return [], []
    ax, u, w = frame(d)
    v = []
    for p, rad in ((Vector(p0), r), (Vector(p1), r1)):
        for i in range(seg):
            a = 2 * math.pi * i / seg
            v.append(tuple(p + rad * (math.cos(a) * u + math.sin(a) * w)))
    f = [tuple(range(seg - 1, -1, -1)), tuple(range(seg, 2 * seg))]          # n-gon caps
    for i in range(seg):
        j = (i + 1) % seg
        f.append((i, j, seg + j, seg + i))
    return v, f


def lathe_data(profile, p0, axis, seg):
    """Solid of revolution. profile: [(radius, distance along axis from p0)], first to last; a radius
    of 0 at an end is a pole, otherwise the end is capped flat. Caps, reservoirs, pulleys, domes."""
    ax, u, w = frame(axis)
    p0 = Vector(p0)
    v, f, rings = [], [], []
    for r, t in profile:
        c = p0 + ax * t
        if r <= 1e-6:
            rings.append([len(v)])
            v.append(tuple(c))
            continue
        ring = []
        for i in range(seg):
            a = 2 * math.pi * i / seg
            ring.append(len(v))
            v.append(tuple(c + r * (math.cos(a) * u + math.sin(a) * w)))
        rings.append(ring)
    for ra, rb in zip(rings, rings[1:]):
        for i in range(seg):
            j = (i + 1) % seg
            if len(ra) == 1:
                f.append((ra[0], rb[j], rb[i]))
            elif len(rb) == 1:
                f.append((ra[i], ra[j], rb[0]))
            else:
                f.append((ra[i], ra[j], rb[j], rb[i]))
    if len(rings[0]) > 1:
        f.append(tuple(reversed(rings[0])))
    if len(rings[-1]) > 1:
        f.append(tuple(rings[-1]))
    return v, f


def sphere_data(c, r, seg, rings, scale=(1.0, 1.0, 1.0)):
    """UV sphere / ellipsoid (scale per axis), poles on Z."""
    c = Vector(c)
    v, f = [], []
    for j in range(1, rings):
        phi = math.pi * j / rings
        for i in range(seg):
            th = 2 * math.pi * i / seg
            v.append((c.x + scale[0] * r * math.sin(phi) * math.cos(th),
                      c.y + scale[1] * r * math.sin(phi) * math.sin(th),
                      c.z + scale[2] * r * math.cos(phi)))
    top = len(v); v.append((c.x, c.y, c.z + scale[2] * r))
    bot = len(v); v.append((c.x, c.y, c.z - scale[2] * r))
    for j in range(rings - 2):
        for i in range(seg):
            a, b = j * seg + i, j * seg + (i + 1) % seg
            f.append((a, b, b + seg, a + seg))
    base = (rings - 2) * seg
    for i in range(seg):
        f.append((top, (i + 1) % seg, i))
        f.append((bot, base + i, base + (i + 1) % seg))
    return v, f


def torus_data(c, axis, R, r, seg, ring):
    ax, u, w = frame(axis)
    c = Vector(c)
    v, f = [], []
    for i in range(seg):
        a = 2 * math.pi * i / seg
        d = math.cos(a) * u + math.sin(a) * w
        for k in range(ring):
            b = 2 * math.pi * k / ring
            v.append(tuple(c + R * d + r * (math.cos(b) * d + math.sin(b) * ax)))
    for i in range(seg):
        i2 = (i + 1) % seg
        for k in range(ring):
            k2 = (k + 1) % ring
            f.append((i * ring + k, i2 * ring + k, i2 * ring + k2, i * ring + k2))
    return v, f


PLANES = {"xy": (0, 1, 2), "xz": (0, 2, 1), "yz": (1, 2, 0)}


def prism_data(pts, plane, d0, d1):
    """An outline extruded straight: pts are 2D points in `plane` ("xy": (x, y) extruded along z from
    d0 to d1; "xz": (x, z) along y; "yz": (y, z) along x). Any simple polygon, either winding; concave
    caps are triangulated by Bay.add. Brackets, castings seen side-on, the plenum's profile."""
    a, b, c = PLANES[plane]
    n = len(pts)
    area = sum(pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1] for i in range(n))
    if area < 0:
        pts = pts[::-1]
    v = []
    for d in (d0, d1):
        for p in pts:
            q = [0.0, 0.0, 0.0]
            q[a], q[b], q[c] = p[0], p[1], d
            v.append(tuple(q))
    f = [tuple(range(n - 1, -1, -1)), tuple(range(n, 2 * n))]
    for i in range(n):
        j = (i + 1) % n
        f.append((i, j, n + j, n + i))
    return v, f


def loft_data(rings, cap=True, closed=True):
    """Surface through rings of equal point count (lists of xyz), capped flat at both ends. closed:
    each ring is a loop (a duct, a moulding's cross-section); otherwise an open strip."""
    m = len(rings[0])
    v = [tuple(p) for ring in rings for p in ring]
    f = []
    for k in range(len(rings) - 1):
        a, b = k * m, (k + 1) * m
        for i in range(m if closed else m - 1):
            j = (i + 1) % m
            f.append((a + i, a + j, b + j, b + i))
    if cap and closed:
        f.append(tuple(range(m - 1, -1, -1)))
        last = (len(rings) - 1) * m
        f.append(tuple(range(last, last + m)))
    return v, f


def merge(*parts):
    V, F = [], []
    for v, f in parts:
        b = len(V)
        V += v
        F += [tuple(b + i for i in face) for face in f]
    return V, F


def catmull(pts, per=6, closed=True):
    """Catmull-Rom samples through pts (Vectors)."""
    P = [Vector(p) for p in pts]
    n = len(P)
    out = []
    segs = n if closed else n - 1
    for i in range(segs):
        p0 = P[(i - 1) % n] if closed else P[max(i - 1, 0)]
        p1, p2 = P[i], P[(i + 1) % n]
        p3 = P[(i + 2) % n] if closed else P[min(i + 2, n - 1)]
        for k in range(per):
            t = k / per
            out.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t
                              + (-p0 + 3 * p1 - 3 * p2 + p3) * t * t * t))
    if not closed:
        out.append(P[-1])
    return out


def ribbon_data(samples, width, thick, plane_normal=X):
    """Closed flat band (a belt) swept along closed samples: width along plane_normal."""
    n = len(samples)
    v, f = [], []
    for i in range(n):
        t = (samples[(i + 1) % n] - samples[i - 1]).normalized()
        nrm = t.cross(plane_normal).normalized()
        c = samples[i]
        v += [tuple(c + plane_normal * width / 2 + nrm * thick / 2), tuple(c - plane_normal * width / 2 + nrm * thick / 2),
              tuple(c - plane_normal * width / 2 - nrm * thick / 2), tuple(c + plane_normal * width / 2 - nrm * thick / 2)]
    for i in range(n):
        a, b = 4 * i, 4 * ((i + 1) % n)
        for k in range(4):
            k2 = (k + 1) % 4
            f.append((a + k, a + k2, b + k2, b + k))
    return v, f


def belt_path(pulleys, per=3):
    """Closed path hugging pulleys [(centre Vector, radius)] lying in the YZ plane (an x-axis belt)."""
    cen = sum((p for p, _ in pulleys), Vector()) / len(pulleys)
    pts = []
    for p, r in pulleys:
        d = (p - cen)
        d.x = 0
        th = math.atan2(d.z, d.y)
        for da in (-0.95, -0.4, 0.0, 0.4, 0.95):
            a = th + da
            pts.append(p + Vector((0, math.cos(a), math.sin(a))) * (r + 0.004))
    return catmull(pts, per, closed=True)


def blade_data(centre, axis, r_hub, r_tip, blades, pitch=0.55, w_root=0.045, w_tip=0.06, thick=0.004, sweep=0.18):
    ax, u, w = frame(axis)
    c = Vector(centre)
    parts = []
    for k in range(blades):
        a = 2 * math.pi * k / blades
        rad = math.cos(a) * u + math.sin(a) * w
        tan = -math.sin(a) * u + math.cos(a) * w
        a2 = a + sweep
        rad2 = math.cos(a2) * u + math.sin(a2) * w
        tan2 = -math.sin(a2) * u + math.cos(a2) * w
        wr = tan * math.cos(pitch) + ax * math.sin(pitch)
        wt = tan2 * math.cos(pitch * 0.7) + ax * math.sin(pitch * 0.7)
        nr = rad.cross(wr).normalized()
        root0, root1 = c + rad * r_hub - wr * w_root / 2, c + rad * r_hub + wr * w_root / 2
        tip0, tip1 = c + rad2 * r_tip - wt * w_tip / 2, c + rad2 * r_tip + wt * w_tip / 2
        lo = [root0 - nr * thick / 2, root1 - nr * thick / 2, tip1 - nr * thick / 2, tip0 - nr * thick / 2]
        hi = [root0 + nr * thick / 2, root1 + nr * thick / 2, tip1 + nr * thick / 2, tip0 + nr * thick / 2]
        parts.append(hexa_data([tuple(p) for p in lo], [tuple(p) for p in hi]))
    return merge(*parts)


def tris_of(ob):
    return sum(len(p.vertices) - 2 for p in ob.data.polygons)


# ----------------------------------------------------------------------------- the bay
class Bay:
    """Collects one object per part. `group` is set by the builder before each group module runs and
    stamped on its objects (custom property bay_group) for the per-group triangle report."""

    def __init__(self, collection):
        self.col = collection
        self.objs = []
        self.group = "misc"

    # -- core
    def _shade(self, ob, sharp):
        me = ob.data
        bm = bmesh.new(); bm.from_mesh(me)
        for f in bm.faces:
            f.smooth = True
        lim = math.radians(180.0 if sharp is None else sharp)
        for e in bm.edges:
            if len(e.link_faces) != 2:
                e.smooth = False
            else:
                e.smooth = e.calc_face_angle(0.0) <= lim
        bm.to_mesh(me); bm.free()

    def _finish(self, ob, sharp, bevel=0.0, segments=1):
        if bevel > 0:
            mod = ob.modifiers.new("bevel", 'BEVEL')
            mod.width = bevel
            mod.segments = segments
            mod.limit_method = 'ANGLE'
            mod.angle_limit = math.radians(30)
            mod.material = -1
            with bpy.context.temp_override(object=ob, active_object=ob):
                bpy.ops.object.modifier_apply(modifier=mod.name)
        self._shade(ob, sharp)
        ob["bay_group"] = self.group
        self.objs.append(ob)
        return ob

    def add(self, name, data, mats, sharp=30, face_mats=None, bevel=0.0, segments=1):
        """Any (verts, faces) data as one part. mats: a palette / decal name or a list of them;
        face_mats: {face index: index into mats}. Normals are made consistent and outward, n-gons
        over four sides are triangulated (concave caps come out right)."""
        v, f = data
        if not f:
            return None
        me = bpy.data.meshes.new(name)
        me.from_pydata(v, [], f)
        me.validate()
        names = mats if isinstance(mats, (list, tuple)) else [mats]
        for n in names:
            me.materials.append(material(n))
        if face_mats:
            for i, poly in enumerate(me.polygons):
                poly.material_index = face_mats.get(i, 0)
        bm = bmesh.new(); bm.from_mesh(me)
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
        ngons = [fc for fc in bm.faces if len(fc.verts) > 4]
        if ngons:
            bmesh.ops.triangulate(bm, faces=ngons, quad_method='BEAUTY', ngon_method='BEAUTY')
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        bm.to_mesh(me); bm.free()
        ob = bpy.data.objects.new(name, me)
        self.col.objects.link(ob)
        return self._finish(ob, sharp, bevel, segments)

    def from_bmesh(self, name, bm, mats, sharp=30):
        """A part you built yourself in bmesh (material indices already set on its faces)."""
        me = bpy.data.meshes.new(name)
        bm.to_mesh(me)
        return self.add(name, ([tuple(vt.co) for vt in me.vertices], [tuple(p.vertices) for p in me.polygons]), mats,
                        sharp, {i: p.material_index for i, p in enumerate(me.polygons)})

    # -- primitives
    def box(self, name, x0, x1, y0, y1, z0, z1, mat, faces=None, bevel=0.0, segments=1, sharp=30):
        """Axis box. faces: {"top": mat, "front": mat, ...} for other materials on single faces (a decal)."""
        mats, fm = [mat], {}
        for side, m in (faces or {}).items():
            if m not in mats:
                mats.append(m)
            fm[BOX_FACE[side]] = mats.index(m)
        return self.add(name, box_data(x0, x1, y0, y1, z0, z1), mats, sharp, fm, bevel, segments)

    def rbox(self, name, x0, x1, y0, y1, z0, z1, mat, bevel=0.012, segments=2, faces=None):
        """Rounded box: a moulding or casting with a real radius on its edges (costs ~5x a box)."""
        return self.box(name, x0, x1, y0, y1, z0, z1, mat, faces, bevel, segments, sharp=50)

    def cyl(self, name, p0, p1, r, mat, seg=8, r1=None, bevel=0.0, segments=1):
        return self.add(name, cyl_data(p0, p1, r, seg, r1), mat, 60 if seg >= 6 else 30, None, bevel, segments)

    def lathe(self, name, profile, p0, axis, mat, seg=10, sharp=50):
        return self.add(name, lathe_data(profile, p0, axis, seg), mat, sharp)

    def sphere(self, name, c, r, mat, seg=12, rings=6, scale=(1.0, 1.0, 1.0)):
        return self.add(name, sphere_data(c, r, seg, rings, scale), mat, sharp=None)

    def torus(self, name, c, axis, R, r, mat, seg=12, ring=4):
        return self.add(name, torus_data(c, axis, R, r, seg, ring), mat, sharp=None)

    def prism(self, name, pts, plane, d0, d1, mat, bevel=0.0, segments=1, sharp=30, cap_mat=None):
        """Extruded outline (see prism_data). cap_mat: another material on both flat caps."""
        data = prism_data(pts, plane, d0, d1)
        mats, fm = [mat], {}
        if cap_mat:
            mats.append(cap_mat); fm = {0: 1, 1: 1}
        return self.add(name, data, mats, sharp, fm, bevel, segments)

    def loft(self, name, rings, mat, cap=True, sharp=50):
        return self.add(name, loft_data(rings, cap), mat, sharp)

    def pipe(self, name, pts, r, mat, sides=6, res=3, cyclic=False):
        """Bezier tube through pts (auto handles): hoses, wires, lines. res: samples per span."""
        cu = bpy.data.curves.new(name, 'CURVE')
        cu.dimensions = '3D'
        sp = cu.splines.new('BEZIER')
        sp.bezier_points.add(len(pts) - 1)
        for bp, p in zip(sp.bezier_points, pts):
            bp.co = p
            bp.handle_left_type = bp.handle_right_type = 'AUTO'
        sp.use_cyclic_u = cyclic
        cu.bevel_depth = r
        cu.bevel_resolution = max(0, sides // 2 - 2)          # sides = 4 + 2 * resolution
        cu.resolution_u = max(1, res)
        cu.use_fill_caps = not cyclic
        tmp = bpy.data.objects.new(name + "_curve", cu)
        self.col.objects.link(tmp)
        dg = bpy.context.evaluated_depsgraph_get()
        me = bpy.data.meshes.new_from_object(tmp.evaluated_get(dg))
        bpy.data.objects.remove(tmp, do_unlink=True)
        bpy.data.curves.remove(cu)
        data = ([tuple(vt.co) for vt in me.vertices], [tuple(p.vertices) for p in me.polygons])
        bpy.data.meshes.remove(me)
        return self.add(name, data, mat, sharp=70)

    def belt(self, name, pulleys, width=0.014, thick=0.003, mat="Rubber", per=3):
        return self.add(name, ribbon_data(belt_path(pulleys, per), width, thick), mat, sharp=70)

    def fan(self, name, centre, axis, r_hub, r_tip, blades, mat, **kw):
        return self.add(name, blade_data(centre, axis, r_hub, r_tip, blades, **kw), mat, sharp=None)

    # -- bookkeeping
    def tris(self, group=None):
        return sum(tris_of(o) for o in self.objs if group is None or o.get("bay_group") == group)

    def report(self):
        groups = {}
        for o in self.objs:
            g = o.get("bay_group", "misc")
            groups[g] = groups.get(g, 0) + tris_of(o)
        print("bay tris by group: " + ", ".join("%s=%d" % kv for kv in groups.items()) + "  (total %d)" % self.tris())
        return groups

    def report_parts(self, group=None, top=40):
        rows = sorted(((tris_of(o), o.name) for o in self.objs if group is None or o.get("bay_group") == group),
                      reverse=True)
        print("bay tris by part%s: %s" % (" (%s)" % group if group else "",
                                           ", ".join("%s=%d" % (n, t) for t, n in rows[:top])))

    def join(self, name):
        for o in bpy.data.objects:
            o.select_set(False)
        for o in self.objs:
            o.select_set(True)
        bpy.context.view_layer.objects.active = self.objs[0]
        bpy.ops.object.join()
        ob = bpy.context.view_layer.objects.active
        ob.name = name
        ob.data.name = name
        ob.select_set(False)
        self.objs = [ob]
        return ob
