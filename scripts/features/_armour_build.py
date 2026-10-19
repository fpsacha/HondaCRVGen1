r"""
Survival armour geometry for the CR-V (Blender side of scripts/features/armour.py; the loader skips
this module, armour.BUILD imports it inside Blender).

Bare welded steel built from the car's own panels, our own design (KI5's armour is a reference for
the feel only):

  * door plates acc_armour_door_<fl|fr|rl|rr>: 4 mm plate from just under the belt line to the sill,
    its outline the door's own (inset 3 cm, 6 cm at the hinge edge so it clears the fender when the
    door swings), notched round the outside handle and, on the rear doors, round the wheel arch. The
    plate stands 8 mm off the skin, following the door's shape (a max envelope bridges the side
    moulding and the cladding step). On it: a welded flat-bar border with its fillet weld bead, one
    or two pressed stiffener ribs tack-welded at both ends, hex bolt heads round the border. Rides
    the door bone (bake on the shell). Each cell of the plate is wound by its real normal, so the
    front sheet faces out on both sides (the left plates were built inside-out until 2026-10-13).
  * window mesh acc_armour_mesh_<fl|fr|rl|rr>: a flat-bar frame like the bar guards' (same glass
    outline, same sash clearance) holding EXPANDED METAL as real geometry: a diamond lattice of 14 mm
    strands (14 x 7 cm diamonds), built since 2026-10-19 as the lattice's two families of straight
    strands, each a front and a back sheet 0.5 mm apart (the far-side windows still read from inside
    the cabin; the closed 2.5 mm ring per diamond before it cost ~2.2k triangles a window). The second
    model of the guard part (an alternative to the bars).
  * rear glass plate acc_armour_rear_plate: a plate over the flip-up glass on the guard's frame line
    with a horizontal viewing slot, border, bolts, weld beads inside the border and round the slot
    lip. Rides trunkglass_bone (second model of CRVGuardWindshieldRear).
  * arch guards acc_armour_arch_<fl|fr|rl|rr>: a 7 cm steel band round each wheel opening following
    the flare, a rolled inner edge, bolt heads; tapered / cut where a door's edge would swing through
    it. Static.

Model space: metres, +X vehicle right, +Y forward, +Z up, ground 0. Left parts at -X.
"""
import math
import os

import bmesh
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

import build_accessories as BA
import build_details as BD                       # the door handles' bezels (HANDLE_AT, PLATE_A / PLATE_B)

# materials of our own (the bake gives them TEXTURED stacks, armour.BAKE_TEXTURED)
MAT_PLATE, MAT_BOLT, MAT_MESH, MAT_WELD = "AccArmourPlate", "AccArmourBolt", "AccArmourMesh", "AccArmourWeld"
OWN_MATS = [MAT_PLATE, MAT_BOLT, MAT_MESH, MAT_WELD]
COLOURS = {MAT_PLATE: (0.17, 0.17, 0.18), MAT_BOLT: (0.10, 0.10, 0.105), MAT_MESH: (0.14, 0.14, 0.145),
           MAT_WELD: (0.07, 0.065, 0.06)}
# face material indices while building: OUR slots, counted from 10. build_accessories.MATS has ten
# entries until build_table adds AccTable / AccChrome (run_rebuild runs it first): _new_object moves
# these onto the slots the materials really get, and build() fails if any face of ours ends up on a
# material that is not ours (2026-10-13: the integration build baked every plate as the picnic table)
PLATE, BOLT, MESH, WELD = 10, 11, 12, 13

# texel weights (FLOAT face attribute texel_w, bake_atlas reads it for OBJECTS with texel_w). Only the
# faces turned to the outside get texels; the backs (8 mm off the skin, facing in) and every wall, bar
# side and rib side (1-7 mm, 1-2 px on screen) weigh 0: a flat swatch cell of the object's material
# (planar_uv.classify), not a padded chart of their own (the feature charts' padding cost the panels
# 0.17 texels/cm, visual review 2026-10-13)
W_SEEN, W_SWATCH = 0.5, 0.0

# weld beads: a fillet along the inside edge of every welded flat bar (the border, the slot lip) and
# across the rib ends; dark heat-tinted weld metal (a swatch: armour.BAKE_SWATCH_MATS)
WELD_W, WELD_H = 0.011, 0.0035

SIDES = {"fl": -1.0, "fr": 1.0, "rl": -1.0, "rr": 1.0}

# door plates
PLATE_T = 0.004                           # plate thickness
PLATE_GAP = 0.008                         # off the door skin (envelope)
INSET = 0.030                             # outline inside the door's edges
INSET_HINGE = 0.060                       # at the hinge edge: the plate swings forward ~4 cm at 70 degrees
TOP_BELOW_BELT = 0.020                    # top edge under the belt weatherstrip
BOTTOM_Z = 0.42                           # bottom edge (the door's skin ends ~0.44, cladding 0.345)
GRID = 0.15                               # plate face grid (follows the door's curve)
BORDER_W, BORDER_T = 0.024, 0.005         # welded flat-bar border
RIB_W, RIB_T = 0.034, 0.007               # stiffener rib
BOLT_R, BOLT_H = 0.0095, 0.006            # hex bolt heads
BOLT_EVERY = 0.24
HANDLE_MARGIN = 0.028
ARCH_CLEAR = 0.035                        # plate edge off the wheel opening (rear doors)

# window mesh
STRAND = 0.014                            # expanded-metal strand width
DIAMOND = (0.14, 0.07)                    # long way (along the glass's u), short way
MESH_LAYER = 0.0025                       # the second strand family this far under the first
MESH_T = 0.0005                           # a strand's front / back sheets (no walls: build_window_mesh)
MESH_TOL = 0.0004                         # a strand bends where a straight run would leave the glass's curve
MESH_FRAME_W, MESH_FRAME_T = 0.034, 0.010

# rear plate
SLOT = (0.50, 0.050)                      # viewing slot width, height
SLOT_V = 0.62                             # slot centre, share of the plate's height from the bottom

# arch guards
ARCH_W = 0.075                            # band width (radial)
ARCH_T = 0.004
ARCH_GAP = 0.011                          # (0.008 until 2026-10-17: 12-15 cm2 of the band lay within 1.5 mm
                                          # of the flare between the sampled stations, review ACC-9)
ARCH_LIP_R = 0.007                        # rolled inner edge
ARCH_STEP = 8.0                           # degrees between band stations


# ----------------------------------------------------------------------------------------------
# helpers


def _materials():
    out = []
    for name in OWN_MATS:
        m = bpy.data.materials.get(name)
        if m is None:
            m = bpy.data.materials.new(name)
            m.use_nodes = True
        b = next(n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
        b.inputs['Base Color'].default_value = COLOURS[name] + (1.0,)
        b.inputs['Roughness'].default_value = 0.6
        out.append(m)
    return out


def _new_object(name, bm):
    """build_accessories._new_object (its MATS: ten, or twelve once build_table has added its two) plus
    our materials after them. The faces were built with our indices counted from PLATE (10): they are
    moved onto the slots our materials really got."""
    base = len(BA.MATS)
    ob = BA._new_object(name, bm)
    for m in _materials():
        ob.data.materials.append(m)
    if base != PLATE:
        me = ob.data
        idx = [0] * len(me.polygons)
        me.polygons.foreach_get("material_index", idx)
        me.polygons.foreach_set("material_index", [i - PLATE + base if i >= PLATE else i for i in idx])
        me.update()
    return ob


def _check_materials(objs):
    """Every face of every armour object on one of our own materials: the bake gives a face the stack of
    its slot's material, so a face on a core slot bakes as something else (raises)."""
    bad = []
    for ob in objs:
        names = [m.name if m else "?" for m in ob.data.materials]
        wrong = {}
        for p in ob.data.polygons:
            n = names[p.material_index] if p.material_index < len(names) else "?"
            if n not in OWN_MATS:
                wrong[n] = wrong.get(n, 0) + 1
        if wrong:
            bad.append("%s: %s" % (ob.name, ", ".join("%d faces on %s" % (c, n) for n, c in sorted(wrong.items()))))
    if bad:
        raise RuntimeError("armour: faces outside the armour's own materials %s (material slots shifted?): %s"
                           % (OWN_MATS, "; ".join(bad)))


def _texel_by_side(ob, inward, seen=W_SEEN):
    """texel_w per face: faces turned to the outside (normal against inward, the direction into the car)
    `seen`, every other face (backs, walls, bar and rib sides) W_SWATCH. inward(p) -> Vector for a polygon."""
    me = ob.data
    vals = [seen if p.normal.dot(inward(p)) < -0.5 else W_SWATCH for p in me.polygons]
    attr = me.attributes.get(BA.TEXEL_W_ATTR)
    if attr is not None:
        me.attributes.remove(attr)
    attr = me.attributes.new(BA.TEXEL_W_ATTR, 'FLOAT', 'FACE')
    attr.data.foreach_set("value", vals)


def _finish(name, bm, inward, shade_k=0.40, seen=W_SEEN):
    loose = [v for v in bm.verts if not v.link_faces]       # (the back sheets' inner vertices, now unused)
    if loose:
        bmesh.ops.delete(bm, geom=loose, context='VERTS')
    ob = _new_object(name, bm)
    _texel_by_side(ob, inward, seen)
    BA._shade(ob, shade_k)
    return ob


def _clip(poly, x0, y0, x1, y1):
    """Sutherland-Hodgman: poly (2D) clipped to the rectangle."""
    def cut(pts, inside, inter):
        out = []
        n = len(pts)
        for i in range(n):
            p, q = pts[i - 1], pts[i]
            ip, iq = inside(p), inside(q)
            if iq:
                if not ip:
                    out.append(inter(p, q))
                out.append(q)
            elif ip:
                out.append(inter(p, q))
        return out

    def ix(xv):
        return lambda p, q: (xv, p[1] + (q[1] - p[1]) * (xv - p[0]) / (q[0] - p[0]))

    def iy(yv):
        return lambda p, q: (p[0] + (q[0] - p[0]) * (yv - p[1]) / (q[1] - p[1]), yv)
    pts = list(poly)
    for inside, inter in ((lambda p: p[0] >= x0, ix(x0)), (lambda p: p[0] <= x1, ix(x1)),
                          (lambda p: p[1] >= y0, iy(y0)), (lambda p: p[1] <= y1, iy(y1))):
        if not pts:
            return []
        pts = cut(pts, inside, inter)
    return pts


def _area(poly):
    return BA._area2(poly)


def _point_in(poly, p):
    x, y = p
    inside = False
    n = len(poly)
    for i in range(n):
        (x1, y1), (x2, y2) = poly[i - 1], poly[i]
        if (y1 > y) != (y2 > y):
            if x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                inside = not inside
    return inside


def _grid_lines(lo, hi, step, extra=()):
    k = max(1, int(math.ceil((hi - lo) / step)))
    vals = [lo + (hi - lo) * i / k for i in range(k + 1)] + list(extra)
    vals = sorted(set(round(v, 6) for v in vals))
    return vals


def _sheet(bm, poly, us, vs, place, holes=(), mat=PLATE, t=PLATE_T, back=True):
    """A closed plate: the 2D polygon poly cut by the grid lines us x vs (holes: rectangles of whole
    cells dropped), every vertex placed by place(u, v) -> (outer point, outward unit normal); the back
    is the same sheet t further in, walls along every boundary edge. back=False leaves the back sheet out
    (a plate standing 8 mm off an opaque skin: its back faces the skin and no camera is ever between
    them). Returns the front faces."""
    key = {}

    def vert(u, v):
        k = (round(u, 5), round(v, 5))
        if k not in key:
            p, n = place(u, v)
            key[k] = (bm.verts.new(p), bm.verts.new(p - n * t))
        return key[k]

    fronts = []
    for i in range(len(us) - 1):
        for j in range(len(vs) - 1):
            x0, x1, y0, y1 = us[i], us[i + 1], vs[j], vs[j + 1]
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            if any(h[0] <= cx <= h[2] and h[1] <= cy <= h[3] for h in holes):
                continue
            piece = _clip(poly, x0, y0, x1, y1)
            # drop repeated points
            clean = []
            for p in piece:
                if not clean or abs(p[0] - clean[-1][0]) > 1e-6 or abs(p[1] - clean[-1][1]) > 1e-6:
                    clean.append(p)
            if len(clean) > 2 and abs(clean[0][0] - clean[-1][0]) < 1e-6 and abs(clean[0][1] - clean[-1][1]) < 1e-6:
                clean.pop()
            if len(clean) < 3 or abs(_area(clean)) < 1e-6:
                continue
            if _area(clean) < 0:
                clean.reverse()
            vv = [vert(u, v) for u, v in clean]
            if len(set(id(a) for a, _b in vv)) < len(vv):
                continue
            # counter-clockwise in (u, v) faces along place()'s normal only where u x v does (the right
            # side): wind each cell by its real normal, so the front sheet faces out on both sides
            _c, nc = place(cx, cy)
            pts3 = [a.co for a, _b in vv]
            nrm = Vector((0.0, 0.0, 0.0))
            for k in range(1, len(pts3) - 1):
                nrm += (pts3[k] - pts3[0]).cross(pts3[k + 1] - pts3[0])
            if nrm.dot(nc) < 0:
                vv.reverse()
            try:
                f = bm.faces.new([a for a, _b in vv])
            except ValueError:
                continue
            f.material_index = mat
            f.smooth = True                                  # one bent plate, not facets
            if back:
                g = bm.faces.new([b for _a, b in reversed(vv)])
                g.material_index = mat
                g.smooth = False
            fronts.append(f)
    # walls on the boundary edges of the front sheet
    pair = {}
    for k, (a, b) in key.items():
        pair[a] = b
    walls = []
    for f in fronts:
        for loop in f.loops:
            e = loop.edge
            if sum(1 for lf in e.link_faces if lf in set(fronts)) == 1:
                a, b = loop.vert, loop.link_loop_next.vert
                w = bm.faces.new((b, a, pair[a], pair[b]))
                w.material_index = mat
                w.smooth = False
                walls.append(w)
    return fronts


def _hex_bolt(bm, p, n, r=BOLT_R, h=BOLT_H):
    """A hex bolt head standing on point p along n: six sides and a top, its open base 1 mm inside
    the plate it sits on (PZ culls back faces; nothing can look into it)."""
    n = Vector(n).normalized()
    a = n.orthogonal().normalized()
    b = n.cross(a)
    lo, hi = [], []
    for k in range(6):
        t = 2 * math.pi * k / 6
        o = (a * math.cos(t) + b * math.sin(t)) * r
        lo.append(bm.verts.new(p - n * 0.001 + o))
        hi.append(bm.verts.new(p + n * h + o))
    faces = [bm.faces.new((lo[k], lo[(k + 1) % 6], hi[(k + 1) % 6], hi[k])) for k in range(6)]
    faces.append(bm.faces.new(hi))
    for f in faces:
        f.material_index, f.smooth = BOLT, False
        f.normal_update()
    top = faces[-1]
    if top.normal.dot(n) < 0:
        for f in faces:
            f.normal_flip()


def _weld(bm, ring, closed=True):
    """A weld bead along ring [(point on the plate surface, its outward normal)]: a low fillet WELD_W wide
    and WELD_H tall, its base 1 mm inside the plate. Since 2026-10-19 (performance pass) a smooth-shaded
    ridge (two slopes; the five-sided rounded section cost 464 of a door plate's ~1,200 triangles) with no
    base face: the base lies inside the plate, where no camera is."""
    if len(ring) < 2:
        return
    w, h = WELD_W / 2, WELD_H
    prof = [(-w, -0.001), (w, -0.001), (0.0, h)]
    faces = BA._sweep(bm, [p for p, _n in ring], prof, ups=[n for _p, n in ring], closed=closed, smooth=True,
                      cap=not closed, mat=WELD)
    m = len(prof)
    segs = len(ring) if closed else len(ring) - 1
    bmesh.ops.delete(bm, geom=[faces[i * m] for i in range(segs)], context='FACES_ONLY')   # profile edge 0: the base


def _bolts_along(bm, pts, every, offset=0.0):
    """Bolt heads every `every` metres along a closed list of (point, normal)."""
    total = 0.0
    segs = []
    for i in range(len(pts)):
        a, b = pts[i - 1][0], pts[i][0]
        segs.append((total, pts[i - 1], pts[i]))
        total += (b - a).length
    if total <= 0:
        return 0
    k = max(3, int(round(total / every)))
    n = 0
    for j in range(k):
        s = (j + 0.5) * total / k + offset
        for t0, (pa, na), (pb, nb) in segs:
            L = (pb - pa).length
            if t0 <= s <= t0 + L and L > 1e-6:
                f = (s - t0) / L
                _hex_bolt(bm, pa.lerp(pb, f), na.lerp(nb, f).normalized())
                n += 1
                break
    return n


# ----------------------------------------------------------------------------------------------
# door plates


def _door_tree(door):
    ob = bpy.data.objects[door]
    me = ob.data
    mn = [m.name if m else "?" for m in me.materials]
    keep = {"Body", "Body_plastique", "Partie_noir", "Plastique_noir", "Feux_chrome", "Chrome"}
    verts = [ob.matrix_world @ v.co for v in me.vertices]
    polys = [list(p.vertices) for p in me.polygons if (mn[p.material_index] if mn else "?") in keep]
    return BVHTree.FromPolygons(verts, polys), verts, me, mn


def _wheel_centres():
    out = []
    for name in ("wheel_FL", "wheel_FR", "wheel_RL", "wheel_RR"):
        ob = bpy.data.objects.get(name)
        if ob is None:
            continue
        cs = [ob.matrix_world @ Vector(c) for c in ob.bound_box]
        lo = Vector((min(c.x for c in cs), min(c.y for c in cs), min(c.z for c in cs)))
        hi = Vector((max(c.x for c in cs), max(c.y for c in cs), max(c.z for c in cs)))
        out.append((name, (lo + hi) / 2, (hi.z - lo.z) / 2))
    return out


def _lateral(tree, s, y, z):
    """|x| of the outermost door surface at (y, z), or None."""
    hit = tree.ray_cast(Vector((s * 1.6, y, z)), Vector((-s, 0.0, 0.0)), 1.2)
    return abs(hit[0].x) if hit[0] is not None else None


def build_door_plate(tag, report):
    s = SIDES[tag]
    door = "door_" + tag
    tree, verts, me, mn = _door_tree(door)
    # door extents on its outer skin between the sill and the belt
    ys = [verts[v].y for p in me.polygons if (mn[p.material_index] if mn else "?") in ("Body", "Body_plastique")
          and abs(p.normal.x) > 0.5 for v in p.vertices if 0.50 < verts[v].z < 1.00]
    y_lo, y_hi = min(ys), max(ys)
    belt = min((verts[v].z for p in me.polygons if (mn[p.material_index] if mn else "?") == "Plastique_noir"
                for v in p.vertices if verts[v].z > 0.95), default=1.08)
    hinge_front = True                                      # both doors hinge at their front edge
    y0 = y_lo + INSET
    y1 = y_hi - (INSET_HINGE if hinge_front else INSET)
    z0, z1 = BOTTOM_Z, belt - TOP_BELOW_BELT
    # raw lateral surface on a 2 cm lookup grid, then a max envelope (bridges the moulding / cladding step)
    STEP = 0.02
    ny, nz = int((y1 - y0) / STEP) + 3, int((z1 - z0) / STEP) + 3
    raw = [[_lateral(tree, s, y0 - STEP + i * STEP, z0 - STEP + j * STEP) for j in range(nz)] for i in range(ny)]
    valid = [x for col in raw for x in col if x is not None]
    base = max(valid) if valid else 0.87
    # handle: the bezel build_details puts on the door (its centre and plate size), not cells found standing
    # proud of the skin. The scan found a different box on each side (2026-10-17 review ACC-2: on the front
    # right door the box missed the door's rear 10 cm, the notch came out a slanted wedge in the middle of
    # the top edge, a concave outline the cell clipper cut into a face wound inward: the door showed
    # through the plate there)
    _s, hcy, hcz = BD.HANDLE_AT[door]
    handle = (hcy - BD.PLATE_A, hcz - BD.PLATE_B, hcy + BD.PLATE_A, hcz + BD.PLATE_B)
    hy0, hz0, hy1, hz1 = handle                              # the plate goes round the handle, not over it:
    for i in range(ny):                                      # its cells stay out of the envelope
        for j in range(nz):
            y = y0 - STEP + i * STEP
            z = z0 - STEP + j * STEP
            if hy0 - 0.015 <= y <= hy1 + 0.015 and hz0 - 0.015 <= z <= hz1 + 0.015:
                raw[i][j] = None
    env = [[0.0] * nz for _ in range(ny)]
    for i in range(ny):
        for j in range(nz):
            m = None
            for di in (-1, 0, 1):
                for dj in (-2, -1, 0, 1, 2):
                    a, b = i + di, j + dj
                    if 0 <= a < ny and 0 <= b < nz and raw[a][b] is not None:
                        m = raw[a][b] if m is None else max(m, raw[a][b])
            env[i][j] = m if m is not None else base
    def surf(y, z):
        fi = (y - (y0 - STEP)) / STEP
        fj = (z - (z0 - STEP)) / STEP
        i0 = max(0, min(ny - 2, int(math.floor(fi))))
        j0 = max(0, min(nz - 2, int(math.floor(fj))))
        tu, tv = max(0.0, min(1.0, fi - i0)), max(0.0, min(1.0, fj - j0))
        a = env[i0][j0] * (1 - tu) + env[i0 + 1][j0] * tu
        b = env[i0][j0 + 1] * (1 - tu) + env[i0 + 1][j0 + 1] * tu
        return a * (1 - tv) + b * tv

    # outline (y, z), counter-clockwise seen from outside the RIGHT side; chamfered corners; the handle
    # notch cut into the top edge as a rectangle with square sides (the RD1's handles sit at the doors'
    # rear edges: on every door it takes the plate's top rear corner)
    c = 0.025
    notch = None
    hy0, hz0, hy1, hz1 = handle
    ny0, ny1, nz0 = hy0 - HANDLE_MARGIN, hy1 + HANDLE_MARGIN, hz0 - HANDLE_MARGIN
    corner = ny0 < y0 + 0.10
    if corner:
        ny0 = y0 - 0.01
    top = [(y1 - c, z1), (y0 + c, z1), (y0, z1 - c)]
    if nz0 > z0 + 0.10 and ny1 < y1 - 0.05:
        notch = (ny0, nz0, ny1, z1)
        if corner:                                           # the top rear corner: an L-shaped outline
            top = [(y1 - c, z1), (ny1, z1), (ny1, nz0), (y0, nz0)]
        else:                                                # a slot in the top edge
            top = [(y1 - c, z1), (ny1, z1), (ny1, nz0), (ny0, nz0), (ny0, z1), (y0 + c, z1), (y0, z1 - c)]
    rect = [(y0 + c, z0), (y1 - c, z0), (y1, z0 + c), (y1, z1 - c)] + top + [(y0, z0 + c)]
    pts = BA._densify(rect, True, 0.01)
    # wheel openings: push outline points inside a wheel's clearance circle out onto it
    for _n, wc, wr in _wheel_centres():
        if (wc.x > 0) != (s > 0):
            continue
        d_door = min(((Vector((0, verts[v].y, verts[v].z)) - Vector((0, wc.y, wc.z))).length
                      for p in me.polygons if (mn[p.material_index] if mn else "?") in ("Body", "Body_plastique")
                      for v in p.vertices), default=9.0)
        R = max(wr + 0.06, d_door) + ARCH_CLEAR
        out = []
        for (y, z) in pts:
            d = Vector((y - wc.y, z - wc.z))
            if d.length < R:
                d = d.normalized() * R
                y, z = wc.y + d.x, wc.z + d.y
                if z < z0 or y < y0 or y > y1:
                    y, z = max(y0, min(y1, y)), max(z0, min(z1, z))
            out.append((y, z))
        pts = out
    pts = BA._dp(pts, 0.003)
    if _area(pts) < 0:
        pts.reverse()

    def place(y, z):
        x = surf(y, z) + PLATE_GAP + PLATE_T
        return Vector((s * x, y, z)), Vector((s, 0.0, 0.0))

    bm = bmesh.new()
    # grid lines on the notch's edges too: every cell the outline cuts is then convex
    us = _grid_lines(y0, y1, GRID, extra=[e for e in ((notch[0], notch[2]) if notch else ()) if y0 < e < y1])
    vs = _grid_lines(z0, z1, GRID, extra=[notch[1]] if notch else ())
    # with its back sheet: the perf pass (2026-10-19) left it out as "facing the door skin 8 mm away", but the
    # plate's lower edge stands off the skin where the door tucks under, and an open door shows the plate's
    # back edge-on: ground through the culled back at its bottom (round 5: close_door_open_left 20 -> 345 px)
    _sheet(bm, pts, us, vs, place)
    # border: flat bar along the outline inset by half its width, on the plate
    inner = BA._inset(pts, BORDER_W / 2)
    ring = [place(y, z) for y, z in BA._densify(inner, True, 0.15)]
    BA._sweep(bm, [p + n * (BORDER_T / 2 - 0.0008) for p, n in ring], BA._rect(BORDER_W, BORDER_T),
              ups=[n for _p, n in ring], closed=True, smooth=False, mat=PLATE)
    # the border's fillet weld along its inside edge
    _weld(bm, [place(y, z) for y, z in BA._densify(BA._inset(pts, BORDER_W), True, 0.10)])
    # stiffener ribs (horizontal), clear of the notch
    ribs = 0
    zs = [z0 + (z1 - z0) * f for f in ((0.36, 0.68) if (z1 - z0) > 0.45 else (0.5,))]
    for zr in zs:
        span = BA._span(pts, 1, zr)
        if span is None:
            continue
        ya, yb = span[0] + BORDER_W, span[1] - BORDER_W
        if notch and notch[1] - 0.03 < zr:
            continue
        if yb - ya < 0.15:
            continue
        line = [place(y, zr) for y in _grid_lines(ya, yb, 0.15)]
        BA._sweep(bm, [p + n * (RIB_T / 2 - 0.0008) for p, n in line], BA._rect(RIB_W, RIB_T, 0.0),
                  ups=[n for _p, n in line], smooth=False, cap=True, mat=PLATE)
        for ye, d in ((ya, -1.0), (yb, 1.0)):                # tack welds across both rib ends
            _weld(bm, [place(ye + d * 0.004, zr + dz) for dz in (-RIB_W / 2 - 0.004, 0.0, RIB_W / 2 + 0.004)],
                  closed=False)
        ribs += 1
    # bolts on the border
    bolts = _bolts_along(bm, [(p + n * (BORDER_T - 0.0008), n) for p, n in
                              [place(y, z) for y, z in BA._densify(inner, True, 0.02)]], BOLT_EVERY)
    ob = _finish("acc_armour_door_" + tag, bm, lambda p: Vector((-s, 0.0, 0.0)))
    report("  acc_armour_door_%s %4d tris: plate y %.2f..%.2f z %.2f..%.2f, %d-point outline, %d ribs, %d bolts, handle %s"
           % (tag, BA.tris(ob), y0, y1, z0, z1, len(pts), ribs, bolts,
              "notched" if notch else ("seen at %s, not notched" % (tuple(round(h, 3) for h in handle),) if handle else "none")))
    return ob


# ----------------------------------------------------------------------------------------------
# glass frames (window mesh, rear plate): the bar guards' frame line (build_accessories.build_guard)


def _glass_frame(src, panel, frame_w, frame_t):
    gbm = BA._glass(src, "all")
    glass = BVHTree.FromBMesh(gbm)
    c, n, u, v = BA._plane(gbm)
    poly = BA._hull([((p.co - c).dot(u), (p.co - c).dot(v)) for p in gbm.verts])
    gbm.free()
    poly = BA._dp(poly, 0.006)
    if _area(poly) < 0:
        poly.reverse()
    frame2 = BA._inset(poly, -BA.FRAME_OUT)
    solid = BA._tree(panel, BA.GLASS, invert=True)

    def lift(x, y):
        p = c + u * x + v * y
        hit = glass.ray_cast(p + n * 0.4, -n)
        if hit[0] is not None:
            sp = hit[0]
        else:
            near = glass.find_nearest(p)[0]
            sp = p + n * (near - p).dot(n)
        need = 0.0
        if solid is not None:
            h = solid.ray_cast(sp + n * 0.12, -n, 0.13)
            if h[0] is not None:
                need = (h[0] - sp).dot(n)
        return sp, need

    pts2 = BA._densify(frame2, True)
    base = [lift(x, y) for x, y in pts2]
    low = [nd for _s, nd in base if nd <= BA.TALL]
    out = max(BA.GUARD_OUT, max(low) + frame_t / 2 + BA.CLEAR) if low else BA.GUARD_OUT
    out = min(out, 0.075)
    return {"c": c, "n": n, "u": u, "v": v, "poly": poly, "frame2": frame2, "lift": lift, "out": out,
            "base": base, "pts2": pts2, "solid": solid}


def _frame_bar(bm, g, w, t, mat=PLATE):
    """The frame's flat bar along the frame line at g["out"] over the glass. Where a surface under it (the
    front doors' sail at the mirror) comes up within 3.5 mm of the bar's underside, the bar steps over it
    5 mm clear: between two frame points it is sampled every 2 cm and the clashing points join the path
    (the mesh's frame lay 1 mm on the sail, 35 cm2 of z-fight; 2026-10-17 review ACC-9)."""
    n, out = g["n"], g["out"]
    lift, pts2, base, solid = g["lift"], g["pts2"], g["base"], g["solid"]

    def height(sp):
        """The bar's height at glass point sp: out, or 5 mm over a surface that comes within 3.5 mm of its
        underside. The surface is found by a ray from just over the bar (lift's ray from 12 cm up meets
        the mirror head above the sail first)."""
        if solid is None:
            return out
        top = out + t / 2 + 0.006
        h = solid.ray_cast(sp + n * top, -n, top + 0.01)
        if h[0] is None:
            return out
        need = (h[0] - sp).dot(n)
        return need + t / 2 + 0.005 if need > out - t / 2 - 0.0035 else out   # (the frame's own CLEAR is 4 mm)
    frame = []
    m = len(base)
    for i in range(m):
        sp, _need = base[i]
        frame.append(sp + n * height(sp))
        (x0, y0), (x1, y1) = pts2[i], pts2[(i + 1) % m]
        k = int(math.hypot(x1 - x0, y1 - y0) / 0.02)
        for j in range(1, k):
            f = j / k
            sq, _nq = lift(x0 + (x1 - x0) * f, y0 + (y1 - y0) * f)
            hq = height(sq)
            if hq > out:
                frame.append(sq + n * hq)
    BA._sweep(bm, frame, BA._rect(w, t), ups=[n] * len(frame), closed=True, smooth=False, mat=mat)
    # stand-off tabs like the bar guards'
    coarse = BA._dp(g["frame2"], 0.02)
    tabs = 0
    for i, p in enumerate(coarse):
        q = coarse[(i + 1) % len(coarse)]
        L = math.hypot(q[0] - p[0], q[1] - p[1])
        k = max(1, int(round(L / BA.TAB_EVERY)))
        for j in range(k):
            f = (j + 0.5) / k
            x, y = p[0] + (q[0] - p[0]) * f, p[1] + (q[1] - p[1]) * f
            sp, need = g["lift"](x, y)
            need = min(need, BA.TALL)
            if g["out"] - need < 0.008:
                continue
            BA._sweep(bm, [sp + n * (need - 0.003), sp + n * g["out"]], BA._rect(BA.TAB_W, BA.TAB_W),
                      ups=[g["v"]] * 2, smooth=False, mat=BOLT)
            tabs += 1
    return tabs


def _clip_convex(poly, clipper):
    """Sutherland-Hodgman: 2D polygon poly clipped to the CONVEX counter-clockwise polygon clipper."""
    out = list(poly)
    m = len(clipper)
    for i in range(m):
        a, b = clipper[i], clipper[(i + 1) % m]
        ex, ey = b[0] - a[0], b[1] - a[1]
        pts, out = out, []
        for k in range(len(pts)):
            p, q = pts[k - 1], pts[k]
            sp = ex * (p[1] - a[1]) - ey * (p[0] - a[0])           # > 0: left of the edge, inside
            sq = ex * (q[1] - a[1]) - ey * (q[0] - a[0])
            if sq >= 0:
                if sp < 0:
                    t = sp / (sp - sq)
                    out.append((p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t))
                out.append(q)
            elif sp >= 0:
                t = sp / (sp - sq)
                out.append((p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t))
        if not out:
            return []
    return out


def _dp3(pts, tol):
    """Indices kept by Douglas-Peucker on an open 3D polyline (the ends always)."""
    keep = {0, len(pts) - 1}

    def rec(i, j):
        if j - i < 2:
            return
        a, b = pts[i], pts[j]
        ab = b - a
        L2 = max(ab.length_squared, 1e-12)
        best, k = -1.0, None
        for m in range(i + 1, j):
            t = max(0.0, min(1.0, (pts[m] - a).dot(ab) / L2))
            d = (pts[m] - (a + ab * t)).length
            if d > best:
                best, k = d, m
        if best > tol:
            keep.add(k)
            rec(i, k)
            rec(k, j)
    rec(0, len(pts) - 1)
    return sorted(keep)


def _ccw(poly):
    return poly if _area(poly) > 0 else poly[::-1]


def build_window_mesh(tag, report):
    """The frame bar and the expanded metal as its two families of straight strands (performance pass
    2026-10-19). The diamond lattice's strands lie on two families of parallel lines (the diamonds' edges):
    each line is one strand, a strip STRAND wide clipped to the clamp outline under the frame bar, bent only
    where the glass's curve needs it (stations kept by Douglas-Peucker at MESH_TOL along its centre line).
    The second family runs MESH_LAYER under the first (an expanded metal's strands step at every bond).
    Each strand is a front and a back sheet MESH_T apart with no walls: edge-on the gap is a tenth of a pixel
    at 326 px/m. The closed 2.5 mm ring per diamond it replaces (front, back and hole walls: 24 triangles a
    cell, ~90 cells) cost 2.2-2.3k triangles a window. Same diamonds, strand width, heights over the glass and
    the same 4 mm step over the front doors' sail (ACC-9)."""
    g = _glass_frame("window_" + tag, ("door_" + tag, "body"), MESH_FRAME_W, MESH_FRAME_T)
    n, out = g["n"], g["out"]
    bm = bmesh.new()
    tabs = _frame_bar(bm, g, MESH_FRAME_W, MESH_FRAME_T)
    L, S = DIAMOND
    a, b = L / 2, S / 2
    h = math.hypot(a, b)
    clamp_poly = _ccw(BA._inset(g["frame2"], -(MESH_FRAME_W / 2 - 0.006)))
    us = [p[0] for p in clamp_poly]
    vs = [p[1] for p in clamp_poly]
    u0, v0 = min(us) - L, min(vs) - S                       # the old lattice's origin: the same diamonds
    h_front = out - 0.0015
    w = STRAND / 2
    strands = pieces = 0
    # (direction along the strand, unit normal across it): the diamonds' two edge directions
    for fam, (du, dv), (nu, nv) in ((0, (-a / h, b / h), (b / h, a / h)), (1, (a / h, b / h), (-b / h, a / h))):
        h_fam = h_front - fam * MESH_LAYER
        cs = [nu * x + nv * y for x, y in clamp_poly]
        ts = [du * x + dv * y for x, y in clamp_poly]
        c0 = nu * (u0 + a) + nv * v0                         # through a diamond vertex; the lines are 2ab/h apart
        step = 2 * a * b / h
        k = int(math.floor((min(cs) - w - c0) / step))
        t_lo, t_hi = min(ts) - 0.1, max(ts) + 0.1
        while c0 + k * step <= max(cs) + w:
            c = c0 + k * step
            k += 1

            def at(t, s=0.0, c=c):
                return (nu * (c + s) + du * t, nv * (c + s) + dv * t)
            poly = _clip_convex(_ccw([at(t_lo, -w), at(t_hi, -w), at(t_hi, w), at(t_lo, w)]), clamp_poly)
            if len(poly) < 3 or abs(_area(poly)) < 1e-6:
                continue
            tp = [du * x + dv * y for x, y in poly]
            ta, tb = min(tp), max(tp)

            def height(p2, h_fam=h_fam):
                sp, need = g["lift"](p2[0], p2[1])
                hh = h_fam
                if h_front - MESH_LAYER - 0.004 < need < h_front + 0.004:   # a surface under the mesh (the front
                    hh = need + 0.004 + (h_fam - h_front + MESH_LAYER)       # doors' sail at the mirror) as high as
                return sp, hh                                               # its strands: 4 mm over it (ACC-9)
            nk = max(2, int(math.ceil((tb - ta) / 0.01)) + 1)
            tt = [ta + (tb - ta) * i / (nk - 1) for i in range(nk)]
            line = []
            for t in tt:
                sp, hh = height(at(t))
                line.append(sp + n * hh)
            st = [tt[i] for i in _dp3(line, MESH_TOL)]
            cache = {}

            def vert(p2, height=height, cache=cache):
                key = (round(p2[0], 6), round(p2[1], 6))
                if key not in cache:
                    sp, hh = height(p2)
                    cache[key] = (bm.verts.new(sp + n * hh), bm.verts.new(sp + n * (hh - MESH_T)))
                return cache[key]
            for i in range(len(st) - 1):
                # the piece between two stations: the clipped strand cut by the lines t = st[i] and st[i + 1]
                band = _ccw([at(st[i], -1.0), at(st[i + 1], -1.0), at(st[i + 1], 1.0), at(st[i], 1.0)])
                clean = []
                for p2 in _clip_convex(poly, band):
                    if not clean or math.hypot(p2[0] - clean[-1][0], p2[1] - clean[-1][1]) > 1e-5:
                        clean.append(p2)
                if len(clean) > 2 and math.hypot(clean[0][0] - clean[-1][0], clean[0][1] - clean[-1][1]) <= 1e-5:
                    clean.pop()
                if len(clean) < 3 or abs(_area(clean)) < 1e-7:
                    continue
                vv = [vert(p2) for p2 in clean]
                try:
                    f = bm.faces.new([fv for fv, _bv in vv])
                    gb = bm.faces.new([bv for _fv, bv in reversed(vv)])
                except ValueError:
                    continue
                for face, sgn in ((f, 1.0), (gb, -1.0)):
                    face.material_index, face.smooth = MESH, False
                    face.normal_update()
                    if face.normal.dot(n) * sgn < 0:
                        face.normal_flip()
                pieces += 1
            strands += 1
    ob = _finish("acc_armour_mesh_" + tag, bm, lambda p: -n, shade_k=0.35)
    report("  acc_armour_mesh_%s %4d tris: %d strands (%.0f x %.0f cm diamonds, %.0f mm wide, families %.1f mm apart), "
           "%d strand pieces, frame %.1f cm off the glass, %d tabs"
           % (tag, BA.tris(ob), strands, L * 100, S * 100, STRAND * 1000, MESH_LAYER * 1000, pieces, out * 100, tabs))
    return ob


def build_rear_plate(report):
    g = _glass_frame("trunk_top", ("trunk_top", "body"), BORDER_W, PLATE_T)
    n, u, v, c = g["n"], g["u"], g["v"], g["c"]
    poly = BA._inset(g["frame2"], -0.004)                 # just over the frame line (the sash under it)
    us_ = [p[0] for p in poly]
    vs_ = [p[1] for p in poly]
    ua, ub, va, vb = min(us_), max(us_), min(vs_), max(vs_)
    # height: over the glass, lifted wholesale over the brake lamp and the sash like the frame
    needs = []
    for x in _grid_lines(ua, ub, 0.05):
        for y in _grid_lines(va, vb, 0.05):
            if _point_in(poly, (x, y)):
                nd = g["lift"](x, y)[1]
                if nd <= BA.TALL:
                    needs.append(nd)
    h = max(g["out"], (max(needs) if needs else 0.0) + PLATE_T + BA.CLEAR)

    def place(x, y):
        sp, _nd = g["lift"](x, y)
        return sp + n * (h + PLATE_T / 2), n

    vm = va + (vb - va) * SLOT_V
    sw, sh = SLOT
    span = BA._span(poly, 1, vm)
    um = (span[0] + span[1]) / 2 if span else (ua + ub) / 2
    hole = (um - sw / 2, vm - sh / 2, um + sw / 2, vm + sh / 2)
    usl = _grid_lines(ua, ub, GRID, extra=[hole[0], hole[2]])
    vsl = _grid_lines(va, vb, GRID, extra=[hole[1], hole[3]])
    bm = bmesh.new()
    _sheet(bm, poly, usl, vsl, place, holes=[hole])
    inner = BA._inset(poly, BORDER_W / 2)
    ring = [place(x, y) for x, y in BA._densify(inner, True, 0.15)]
    BA._sweep(bm, [p + nn * (BORDER_T / 2 - 0.0008) for p, nn in ring], BA._rect(BORDER_W, BORDER_T),
              ups=[nn for _p, nn in ring], closed=True, smooth=False, mat=PLATE)
    # a lip round the slot (flat bar frame)
    slot_ring = [(hole[0] - 0.012, hole[1] - 0.012), (hole[2] + 0.012, hole[1] - 0.012),
                 (hole[2] + 0.012, hole[3] + 0.012), (hole[0] - 0.012, hole[3] + 0.012)]
    sr = [place(x, y) for x, y in BA._densify(slot_ring, True, 0.10)]
    BA._sweep(bm, [p + nn * (0.004 - 0.0008) for p, nn in sr], BA._rect(0.016, 0.008),
              ups=[nn for _p, nn in sr], closed=True, smooth=False, mat=PLATE)
    # fillet welds: inside the border, round the outside of the slot lip
    _weld(bm, [place(x, y) for x, y in BA._densify(BA._inset(poly, BORDER_W), True, 0.10)])
    lip_out = [(hole[0] - 0.020, hole[1] - 0.020), (hole[2] + 0.020, hole[1] - 0.020),
               (hole[2] + 0.020, hole[3] + 0.020), (hole[0] - 0.020, hole[3] + 0.020)]
    _weld(bm, [place(x, y) for x, y in BA._densify(lip_out, True, 0.10)])
    tabs = _frame_bar_tabs_only(bm, g, h)
    bolts = _bolts_along(bm, [(p + nn * (BORDER_T - 0.0008), nn) for p, nn in
                              [place(x, y) for x, y in BA._densify(inner, True, 0.02)]], BOLT_EVERY)
    ob = _finish("acc_armour_rear_plate", bm, lambda p: -n)
    report("  acc_armour_rear_plate %4d tris: %.0f x %.0f cm, %.1f cm off the glass, slot %.0f x %.0f cm, %d bolts, %d tabs"
           % (BA.tris(ob), (ub - ua) * 100, (vb - va) * 100, h * 100, sw * 100, sh * 100, bolts, tabs))
    return ob


def _frame_bar_tabs_only(bm, g, h):
    """The stand-off tabs under a plate whose underside is at height h over the glass."""
    n = g["n"]
    coarse = BA._dp(g["frame2"], 0.02)
    tabs = 0
    for i, p in enumerate(coarse):
        q = coarse[(i + 1) % len(coarse)]
        L = math.hypot(q[0] - p[0], q[1] - p[1])
        k = max(1, int(round(L / BA.TAB_EVERY)))
        for j in range(k):
            f = (j + 0.5) / k
            x, y = p[0] + (q[0] - p[0]) * f, p[1] + (q[1] - p[1]) * f
            sp, need = g["lift"](x, y)
            need = min(need, BA.TALL)
            if h - need < 0.008:
                continue
            BA._sweep(bm, [sp + n * (need - 0.003), sp + n * (h + 0.001)], BA._rect(BA.TAB_W, BA.TAB_W),
                      ups=[g["v"]] * 2, smooth=False, mat=BOLT)
            tabs += 1
    return tabs


# ----------------------------------------------------------------------------------------------
# arch guards


def build_arch(tag, report):
    s = SIDES[tag]
    wheel = {"fl": "wheel_FL", "fr": "wheel_FR", "rl": "wheel_RL", "rr": "wheel_RR"}[tag]
    wc = next(c for name, c, _r in _wheel_centres() if name == wheel)
    wr = next(r for name, _c, r in _wheel_centres() if name == wheel)
    tree = BA._tree(["body"])
    front = tag[0] == "f"
    # the door edge this arch must stay clear of (the door swings out through it)
    if front:
        door = bpy.data.objects["door_" + ("fl" if s < 0 else "fr")]
        ylim = max((door.matrix_world @ v.co).y for v in door.data.vertices) + 0.020
    else:
        door = bpy.data.objects["door_" + ("rl" if s < 0 else "rr")]
        ylim = min((door.matrix_world @ v.co).y for v in door.data.vertices) - 0.020

    def ok_y(y):
        return y > ylim if front else y < ylim

    def lateral(y, z):
        hit = tree.ray_cast(Vector((s * 1.6, y, z)), Vector((-s, 0.0, 0.0)), 1.2)
        if hit[0] is None or abs(hit[0].x) < 0.62:
            return None
        return abs(hit[0].x)

    stations = []
    th = -20.0
    while th <= 200.0:
        t = math.radians(th)
        dy, dz = math.cos(t), math.sin(t)
        edge = None
        r = wr + 0.005
        while r < wr + 0.30:
            if lateral(wc.y + dy * r, wc.z + dz * r) is not None:
                edge = r
                break
            r += 0.004
        if edge is not None and wc.z + dz * edge > 0.30:
            # radial extent allowed by the door edge
            rmax = edge + ARCH_W
            for k in range(1, 9):
                rr = edge + ARCH_W * k / 8
                if not ok_y(wc.y + dy * rr):
                    rmax = edge + ARCH_W * (k - 1) / 8
                    break
            if ok_y(wc.y + dy * edge) and rmax - edge >= 0.03:
                stations.append((th, dy, dz, edge, rmax))
        th += ARCH_STEP
    # keep the longest run of consecutive stations
    runs, cur = [], []
    for st in stations:
        if cur and abs(st[0] - cur[-1][0] - ARCH_STEP) > 1e-6:
            runs.append(cur)
            cur = []
        cur.append(st)
    if cur:
        runs.append(cur)
    run = max(runs, key=len) if runs else []
    bm = bmesh.new()
    if len(run) < 3:
        ob = _new_object("acc_armour_arch_" + tag, bm)
        report("  acc_armour_arch_%s: no arch found" % tag)
        return ob
    K = 3
    grid = []
    for th, dy, dz, e, rmax in run:
        row = []
        for k in range(K):
            r = e - 0.004 + (rmax - e + 0.004) * k / (K - 1)
            y, z = wc.y + dy * r, wc.z + dz * r
            lat = lateral(y, z)
            row.append([y, z, lat])
        grid.append(row)
    # the skin between the stations too (half way to each neighbour): the band's faces span 8 degrees, and
    # where the flare or the bumper corner bulges between two stations the band lay on the skin, its front
    # within 0.2-1.8 mm of the body's (2026-10-17 review ACC-9, arch fr / rr ends at z 0.38-0.47)
    for i in range(len(grid)):
        for k in range(K):
            for j in (i - 1, i + 1):
                if 0 <= j < len(grid):
                    y = (grid[i][k][0] + grid[j][k][0]) / 2
                    z = (grid[i][k][1] + grid[j][k][1]) / 2
                    lat = lateral(y, z)
                    if lat is not None and (grid[i][k][2] is None or lat > grid[i][k][2]):
                        grid[i][k][2] = lat
    # fill misses, envelope along the band (the flare lip), smooth along the arch
    for row in grid:
        known = [p[2] for p in row if p[2] is not None]
        m = max(known) if known else 0.88
        for p in row:
            p[2] = m if p[2] is None else max(p[2], m - 0.012)
    sm = []
    for i in range(len(grid)):
        row = []
        for k in range(K):
            vals = [grid[j][k][2] for j in (i - 1, i, i + 1) if 0 <= j < len(grid)]
            row.append(max(grid[i][k][2], sum(vals) / len(vals)))
        sm.append(row)
    # and every cell's middle: where the skin there comes within 4 mm of the band's back, the cell's
    # corners stand out by the shortfall (the arches' ends by the door edge and the bumper corners still lay
    # 0.6-1.5 mm off the body after the station and half-way samples; two passes for shared corners)
    for _pass in range(2):
        for i in range(len(grid) - 1):
            for k in range(K - 1):
                cy = sum(grid[a][b][0] for a in (i, i + 1) for b in (k, k + 1)) / 4
                cz = sum(grid[a][b][1] for a in (i, i + 1) for b in (k, k + 1)) / 4
                lat = lateral(cy, cz)
                if lat is None:
                    continue
                back = sum(sm[a][b] for a in (i, i + 1) for b in (k, k + 1)) / 4 + ARCH_GAP
                short = lat + 0.004 - back
                if short > 0:
                    for a in (i, i + 1):
                        for b in (k, k + 1):
                            sm[a][b] += short
    vf, vb_ = [], []
    for i, row in enumerate(grid):
        rf, rb = [], []
        for k, (y, z, _lat) in enumerate(row):
            x = sm[i][k] + ARCH_GAP
            rb.append(bm.verts.new((s * x, y, z)))
            rf.append(bm.verts.new((s * (x + ARCH_T), y, z)))
        vf.append(rf)
        vb_.append(rb)
    faces = []
    for i in range(len(grid) - 1):
        for k in range(K - 1):
            faces.append(bm.faces.new((vf[i][k], vf[i + 1][k], vf[i + 1][k + 1], vf[i][k + 1])))
            # the back sheet (~4 tris a station): the perf pass dropped it as "facing the fender 11 mm away", but the
            # band's outer edge stands past the fender's silhouette where the fender curves in (the bumper corner,
            # the flare lip), and the game camera looking across the car saw the ground through it (round 5,
            # 2026-10-19: shut_045 / shut_135 +65 / +46 px clusters, close_bay_open +291)
            faces.append(bm.faces.new((vb_[i][k + 1], vb_[i + 1][k + 1], vb_[i + 1][k], vb_[i][k])))
        faces.append(bm.faces.new((vb_[i][0], vb_[i + 1][0], vf[i + 1][0], vf[i][0])))
        faces.append(bm.faces.new((vf[i][K - 1], vf[i + 1][K - 1], vb_[i + 1][K - 1], vb_[i][K - 1])))
    for i in (0, len(grid) - 1):
        faces.append(bm.faces.new([vf[i][k] for k in range(K)] + [vb_[i][k] for k in reversed(range(K))]))
    for f in faces:
        f.material_index = PLATE
        f.smooth = False
    bmesh.ops.recalc_face_normals(bm, faces=faces)
    # the faces must point away from the car side on the front layer
    probe = faces[0]
    probe.normal_update()
    if probe.normal.x * s < 0:
        for f in faces:
            f.normal_flip()
    # rolled inner edge and bolts
    lip = [Vector((s * (sm[i][0] + ARCH_GAP + ARCH_T / 2), grid[i][0][0], grid[i][0][1])) for i in range(len(grid))]
    BA._sweep(bm, lip, BA._round(ARCH_LIP_R, 6), smooth=True, cap=True, mat=PLATE)
    nb = 0
    for i in range(1, len(grid) - 1, 3):
        y, z, _l = grid[i][K // 2]
        p = Vector((s * (sm[i][K // 2] + ARCH_GAP + ARCH_T), y, z))
        _hex_bolt(bm, p, Vector((s, 0.0, 0.0)))
        nb += 1
    ob = _finish("acc_armour_arch_" + tag, bm, lambda p: Vector((-s, 0.0, 0.0)), seen=1.0)   # a thin band: weight 1 so its charts own their texels
    report("  acc_armour_arch_%s %4d tris: %.0f..%.0f degrees, %d stations, %d bolts"
           % (tag, BA.tris(ob), run[0][0], run[-1][0], len(run), nb))
    return ob


# ----------------------------------------------------------------------------------------------


def build(report=print):
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    made = []
    for tag in ("fl", "fr", "rl", "rr"):
        made.append(build_door_plate(tag, report))
    for tag in ("fl", "fr", "rl", "rr"):
        made.append(build_window_mesh(tag, report))
    made.append(build_rear_plate(report))
    for tag in ("fl", "fr", "rl", "rr"):
        made.append(build_arch(tag, report))
    _check_materials(made)
    report("FEATURE armour: %d objects, %d tris with everything fitted, every face on %s"
           % (len(made), sum(BA.tris(o) for o in made), "/".join(OWN_MATS)))
    return made
