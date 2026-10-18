r"""
Exterior details built clean on the LOW parts: door handles, mirrors, fuel flap, front wipers,
roof rails; kotris's roof antenna stub (not on the US car) is dropped. prep_parts.prep() calls
build() after the sill strips and before the seam backing, so every piece is made on the
decimated panels and nothing backs the islands deleted here.

    blender -b blender\import\parts_kotris.blend --python scripts\build_details.py -- [--save PATH]

(a re-run on an already prepped blend: build() deletes what is left of the kotris islands and
adds the details again; never saves unless --save names a file outside the repo.)

Why (second in-game look, 2026-10-12, feedback: the textures are "a tiny bit blurry ... pretty
basic"): every exterior detail was a decimated kotris island or a mis-placed generator part.
Each door handle was one 383-tri island shipped as a 45-50 tri blob; the mirrors ~70 tris sharing
a budget with the window rubber; the fuel flap a 6-tri island whose ragged outline read as a
ring; the antenna stood on the HOOD's right edge with a sub-pixel mast; the wipers were slivers;
there were no roof rails. The handle islands FILL A HOLE in the door skin (rays through the
full-detail door at the handle centre hit only Plastique_noir then Interieur), so the bezel plate
must overlap the hole rim; the margin is measured and the build fails under RIM_MIN.

Every face added here carries gen = GEN_DETAIL (7): bake_atlas bakes it directly (its own
material colour, no high twin to project from) at paint density (TEXEL_WEIGHT_GEN), _prune never
touches it, geocheck does not paint it red, holecheck leaves the rails out of the low tree.
Handles and mirrors are faces of the door meshes, so they ride the door bones with no rig or
export change.

Measurements: MG 8767 (blender/references/commons, perpendicular LEFT side, hubs 825.6 px/m):
front bezel 22.0 x 7.9 cm, rear 20.5 x 7.9, chrome grip 16.9 / 15.7 x 2.4 cm centred 1.1-1.6 cm
toward the nose, lock cylinder dia 1.7 cm 1 cm from the rear end (front doors only), mirror
housing 13 cm long x 12.3 cm tall on a 4-5 cm pedestal, fuel flap 17.4 x 17.0 cm with ~3 cm
corners, roof rails y +0.28..-1.67 on three feet. bp_side.png (289.6 px/m) puts the handles
within 2 cm of the kotris islands, so the generator uses the kotris centres: the holes are there.
Model space: metres, +X right, +Y nose, +Z up.
"""
import math
import sys

import bmesh
import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

GEN = "gen"
GEN_DETAIL = 7
DARK = "Plastique_noir"            # seam ring, wipers, rails (PALETTE 0.040, leather grain)
CHROME = "Chrome"                  # kotris's handle grips (matched when the old handle islands are deleted)
PAINT = "Body"                     # the kotris paint: bakes the paint colour, so the paint pass recolours it per skin
# EX trim (chosen, 2026-10-13; spec/paint-colours.md): body-colour door mirrors and door handles.
# The 1998 EX in Supermarine Blue (blender/references/commons, "1998 Honda CR-V EX 03": mirror housing,
# its base, the handle bezels and levers all blue) against the LX's black (1998 LX and 1999 LX in Sebring
# Silver); the parts catalogue lists the EX mirrors per paint colour. Bezel, grip, lock pad, mirror
# housing and pedestal take PAINT (gen 7 faces bake their own material colour, which is the kotris paint
# the paint pass levels and recolours); the mirror glass stays Miroir. The paint pass draws the lock
# cylinder and the dark finger pocket behind each grip (paint_pass HANDLE_POCKET). Until 2026-10-13 they
# were black (LX trim): the grip had been chrome on the JDM model and shipped as bright white bars.
BEZEL = PAINT
GRIP = PAINT
HOUSING = PAINT
MIRROR_DOORS = ("door_fl", "door_fr")


# ----------------------------------------------------------------------------------------------
# mesh helpers


def tris(ob):
    return sum(len(p.vertices) - 2 for p in ob.data.polygons)


def _mat_index(me, name):
    names = [m.name if m else "?" for m in me.materials]
    if name not in names:
        mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
        me.materials.append(mat)
        names.append(name)
    return names.index(name)


def islands(ob):
    """[(face ids, bbox lo, bbox hi, majority material, material set)] per connected island."""
    names = [m.name if m else "?" for m in ob.data.materials]
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bm.faces.ensure_lookup_table()
    seen = [False] * len(bm.faces)
    out = []
    for f in bm.faces:
        if seen[f.index]:
            continue
        grp, st = [f], [f]
        seen[f.index] = True
        while st:
            g = st.pop()
            for e in g.edges:
                for h in e.link_faces:
                    if not seen[h.index]:
                        seen[h.index] = True
                        grp.append(h)
                        st.append(h)
        vs = [v.co for g in grp for v in g.verts]
        lo = Vector((min(v.x for v in vs), min(v.y for v in vs), min(v.z for v in vs)))
        hi = Vector((max(v.x for v in vs), max(v.y for v in vs), max(v.z for v in vs)))
        cnt = {}
        for g in grp:
            m = names[g.material_index]
            cnt[m] = cnt.get(m, 0) + 1
        maj = max(cnt.items(), key=lambda kv: kv[1])[0]
        out.append(([g.index for g in grp], lo, hi, maj, set(cnt)))
    bm.free()
    return out


def _all_gen(ob, ids, value=GEN_DETAIL):
    """True when every face of ids carries gen == value (a detail this module built on an earlier run)."""
    attr = ob.data.attributes.get(GEN)
    if attr is None or not ids:
        return False
    vals = [0] * len(ob.data.polygons)
    attr.data.foreach_get("value", vals)
    return all(vals[i] == value for i in ids)


def delete_faces(ob, ids):
    if not ids:
        return 0
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bm.faces.ensure_lookup_table()
    bmesh.ops.delete(bm, geom=[bm.faces[i] for i in sorted(set(ids))], context='FACES')
    bm.to_mesh(ob.data)
    bm.free()
    ob.data.update()
    return len(set(ids))


def add_faces(ob, groups):
    """groups: [(material, smooth, [face as [(x, y, z), ...]])]. Faces of one group share vertices
    by (rounded) position; smooth True gets vertex-averaged normals within the group, "one" a
    single area-weighted normal for the whole group (a flat panel drawn as a fan), False the
    face normal. Existing corner normals are kept. Returns triangles added."""
    me = ob.data
    before = [tuple(c.vector) for c in me.corner_normals]
    n_old = len(me.polygons)
    bm = bmesh.new()
    bm.from_mesh(me)
    gl = bm.faces.layers.int.get(GEN) or bm.faces.layers.int.new(GEN)   # before any element is made
    smooth_of = {}
    k = 0
    for gid, (mat, smooth, faces) in enumerate(groups):
        mi = _mat_index(me, mat)
        vmap = {}
        start = len(bm.faces)
        for poly in faces:
            vs = []
            for p in poly:
                key = (round(p[0], 5), round(p[1], 5), round(p[2], 5))
                v = vmap.get(key)
                if v is None:
                    v = bm.verts.new(p)
                    vmap[key] = v
                vs.append(v)
            try:
                f = bm.faces.new(vs)
            except ValueError:          # degenerate or duplicate face: skip, never abort the build
                continue
            f.material_index = mi
            f.smooth = smooth is True
            f[gl] = GEN_DETAIL
            k += len(vs) - 2
        bm.faces.ensure_lookup_table()
        for i in range(start, len(bm.faces)):
            smooth_of[i] = (smooth, gid)
    bm.to_mesh(me)
    bm.free()
    me.update()
    normals = list(before) + [None] * (len(me.loops) - len(before))
    acc, one = {}, {}
    for pi in range(n_old, len(me.polygons)):
        sm, gid = smooth_of.get(pi, (False, None))
        pg = me.polygons[pi]
        if sm is True:
            for vi in pg.vertices:
                acc.setdefault((gid, vi), Vector()).__iadd__(pg.normal)
        elif sm == "one":
            one.setdefault(gid, Vector()).__iadd__(pg.normal * pg.area)
    for pi in range(n_old, len(me.polygons)):
        pg = me.polygons[pi]
        sm, gid = smooth_of.get(pi, (False, None))
        for li in pg.loop_indices:
            if sm == "one":
                n = one[gid]
                normals[li] = tuple(n.normalized()) if n.length > 1e-9 else tuple(pg.normal)
            elif sm is True:
                n = acc[(gid, me.loops[li].vertex_index)]
                normals[li] = tuple(n.normalized()) if n.length > 1e-9 else tuple(pg.normal)
            else:
                normals[li] = tuple(pg.normal)
    if len(normals) == len(me.loops) and all(v is not None for v in normals):
        me.normals_split_custom_set(normals)
    return k


def quad(a, b, c, d):
    return [tuple(a), tuple(b), tuple(c), tuple(d)]


def box_faces(lo, hi, skip=()):
    """Axis-aligned box faces wound outward; skip: subset of {'x-','x+','y-','y+','z-','z+'}."""
    x0, y0, z0 = lo
    x1, y1, z1 = hi
    F = {
        'x-': quad((x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0)),
        'x+': quad((x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)),
        'y-': quad((x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)),
        'y+': quad((x0, y1, z0), (x0, y1, z1), (x1, y1, z1), (x1, y1, z0)),
        'z-': quad((x0, y0, z0), (x0, y1, z0), (x1, y1, z0), (x1, y0, z0)),
        'z+': quad((x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)),
    }
    return [f for k, f in F.items() if k not in skip]


def orient(faces, inside_point):
    """Wind every face so its normal points AWAY from inside_point. The game culls back faces
    (Model.DrawVehicle forces GL_CULL_FACE), and Workbench previews draw both sides, so a plate
    wound inward looks fine in Blender and vanishes in game: the reference point must be inside
    the car (or inside the piece), never outboard of it."""
    out = []
    for f in faces:
        vs = [Vector(p) for p in f]
        n = (vs[1] - vs[0]).cross(vs[2] - vs[0])
        c = sum(vs, Vector()) / len(vs)
        if n.dot(c - Vector(inside_point)) < 0:
            f = list(reversed(f))
        out.append(f)
    return out


def _tree(ob):
    """BVH of the object's CURRENT mesh data (Object.ray_cast reads the evaluated copy, which can
    lag behind a bmesh edit made moments earlier)."""
    M = ob.matrix_world
    return BVHTree.FromPolygons([M @ v.co for v in ob.data.vertices],
                                [list(p.vertices) for p in ob.data.polygons], all_triangles=False)


def ray_x(tree, y, z, side, start=1.5):
    """x of the first hit casting inward from outside the car at (y, z); None if nothing."""
    loc, n, idx, dist = tree.ray_cast(Vector((side * start, y, z)), Vector((-side, 0.0, 0.0)), 3.0)
    return loc.x if loc is not None else None


def ray_down(tree, x, y, start=3.0):
    loc, n, idx, dist = tree.ray_cast(Vector((x, y, start)), Vector((0.0, 0.0, -1.0)), 4.0)
    return (loc.z, n) if loc is not None else (None, None)


# ----------------------------------------------------------------------------------------------
# door handles: body-colour bezel plate over the hole, body-colour grip, lock pad (front doors)

HANDLE_AT = {"door_fl": (-1, -0.047, 0.975), "door_fr": (1, -0.047, 0.975),   # (side, y, z): the kotris
             "door_rl": (-1, -1.040, 1.000), "door_rr": (1, -1.040, 1.000)}   # island centres (the holes)
PLATE_A, PLATE_B = 0.117, 0.049      # stadium half-length / half-height: 23.4 x 9.8 cm = the 20.9 x 7.7 cm
                                     # hole plus >= 7 mm all round (photo bezel 22.0 x 7.9 cm)
PLATE_MAX = (0.130, 0.058)           # how far the plate may grow to cover a rim the decimator pushed out
RIM_MARGIN, RIM_MIN = 0.006, 0.005   # wanted / fatal overlap of the plate past the hole rim (lowpoly
                                     # BORDER_TOL lets an outline vertex move 10 mm)
PLATE_OUT = 0.003                    # plate stands this far off the skin plane
GRIP_LEN = {"door_fl": 0.165, "door_fr": 0.165, "door_rl": 0.157, "door_rr": 0.157}   # MG 8767: 16.9 / 15.7 cm
GRIP_H, GRIP_OUT, GRIP_DY = 0.026, 0.014, 0.012   # 2.4 cm tall bar standing 1.4 cm proud, 1.2 cm toward the nose
LOCK = 0.016                         # lock cylinder, as a square 1 mm proud, 8.9 cm behind the centre
LOCK_DY = -0.089
HANDLE_REACH = (0.15, 0.08)          # an island counts as handle only this close (y, z) to the handle centre:
                                     # the front doors' belt-line moulding strips (y 0.14..0.60, z 1.08..1.10)
                                     # fell inside the old height-only rule; deleted, they left slits that
                                     # showed the door's inner paint from the game camera (holecheck 2026-10-12)


def handle_islands(ob, name):
    """Face ids of the door's outside handle: dark islands under 30 cm on the outer skin within
    HANDLE_REACH of HANDLE_AT[name]. On the full-detail door that is the 383-tri island plus 25
    small bezel / grip / lock pieces (418 faces); on a prepped low door whatever decimated slivers
    are left of them. prep_parts._make_low deletes these before decimation."""
    s, cy, cz = HANDLE_AT[name]
    out = []
    for ids, lo, hi, maj, mats in islands(ob):
        c = (lo + hi) / 2
        if ((hi - lo).length < 0.30 and abs(c.x) > 0.75 and abs(c.y - cy) < HANDLE_REACH[0] and abs(c.z - cz) < HANDLE_REACH[1]
                and (mats <= {DARK, "Partie_noir", CHROME}
                     or (mats <= {DARK, PAINT} and _all_gen(ob, ids)))):     # a body-colour handle of an earlier run
            out.extend(ids)
    return out


def _hole_rim(ob, cy, cz, box_y, box_z):
    """Vertices of every free-edge loop of gen-0 faces lying WHOLLY inside the box round the handle
    centre: the rim of the hole the kotris handle filled. The door's own outline runs out of the
    box and is ignored; generated faces (lips, cards) are not skin."""
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    gl = bm.faces.layers.int.get(GEN)
    free = [e for e in bm.edges if len(e.link_faces) == 1 and (gl is None or e.link_faces[0][gl] == 0)]
    adj = {}
    for e in free:
        for v in e.verts:
            adj.setdefault(v.index, []).append(e)
    seen, rim = set(), []
    for e0 in free:
        if e0.index in seen:
            continue
        seen.add(e0.index)
        st, pts = [e0], {}
        while st:
            g = st.pop()
            for v in g.verts:
                pts[v.index] = v.co.copy()
                for h in adj[v.index]:
                    if h.index not in seen:
                        seen.add(h.index)
                        st.append(h)
        if all(abs(p.y - cy) < box_y and abs(p.z - cz) < box_z and abs(p.x) > 0.75 for p in pts.values()):
            rim.extend(pts.values())
    bm.free()
    return rim


def _stadium_margin(rim, cy, cz, a, b):
    """Smallest distance from a rim vertex to the stadium outline, positive = inside the plate."""
    worst = None
    for p in rim:
        dy, dz = abs(p.y - cy), abs(p.z - cz)
        d = math.hypot(max(dy - (a - b), 0.0), dz) - b          # signed distance outside the stadium
        worst = d if worst is None else max(worst, d)
    return None if worst is None else -worst


def build_handle(name, report):
    ob = bpy.data.objects.get(name)
    if ob is None:
        return 0
    s, cy, cz = HANDLE_AT[name]
    removed = delete_faces(ob, handle_islands(ob, name))
    a, b = PLATE_A, PLATE_B
    rim = _hole_rim(ob, cy, cz, PLATE_MAX[0] + 0.02, PLATE_MAX[1] + 0.02)
    margin = _stadium_margin(rim, cy, cz, a, b)
    if margin is not None and margin < RIM_MARGIN:       # a rim vertex the decimator pushed out: grow the plate
        grow = min(RIM_MARGIN - margin, PLATE_MAX[0] - a, PLATE_MAX[1] - b)
        a, b = a + max(grow, 0.0), b + max(grow, 0.0)
        margin = _stadium_margin(rim, cy, cz, a, b)
    if margin is not None and margin < RIM_MIN:
        raise RuntimeError("%s: handle hole rim only %.1f mm inside the %.0f x %.0f mm plate (RIM_MIN %.0f mm)"
                           % (name, margin * 1000, 2 * a * 1000, 2 * b * 1000, RIM_MIN * 1000))
    # plate plane |x| = p*y + q*z + r through six skin probes clear of the hole, on the low door
    tree = _tree(ob)
    pts = []
    for dy, dz in ((0.13, 0.0), (-0.13, 0.0), (0.0, 0.06), (0.0, -0.06), (0.13, 0.05), (-0.13, -0.05)):
        x = ray_x(tree, cy + dy, cz + dz, s)
        if x is not None:
            pts.append((cy + dy, cz + dz, abs(x)))
    A = np.array([[p[0], p[1], 1.0] for p in pts])
    coef = np.linalg.lstsq(A, np.array([p[2] for p in pts]), rcond=None)[0]

    def P(y, z, out):
        return (s * (float(coef[0] * y + coef[1] * z + coef[2]) + out), y, z)
    inside = (0.0, cy, cz)                                # the car's centreline: plates face away from it
    outline = []
    for th in (-90, -45, 0, 45, 90):
        t = math.radians(th)
        outline.append((cy + (a - b) + b * math.cos(t), cz + b * math.sin(t)))
    for th in (90, 135, 180, 225, 270):
        t = math.radians(th)
        outline.append((cy - (a - b) + b * math.cos(t), cz + b * math.sin(t)))
    plate = orient([[P(y, z, PLATE_OUT) for y, z in outline]], inside)
    gl_ = GRIP_LEN[name]
    gy0, gy1 = cy + GRIP_DY - gl_ / 2, cy + GRIP_DY + gl_ / 2
    gz0, gz1 = cz - GRIP_H / 2, cz + GRIP_H / 2
    xi, xo = PLATE_OUT + 0.001, PLATE_OUT + GRIP_OUT
    grip = [
        [P(gy0, gz0, xo), P(gy1, gz0, xo), P(gy1, gz1, xo), P(gy0, gz1, xo)],      # outer face
        [P(gy0, gz1, xi), P(gy1, gz1, xi), P(gy1, gz1, xo), P(gy0, gz1, xo)],      # top
        [P(gy0, gz0, xi), P(gy0, gz0, xo), P(gy1, gz0, xo), P(gy1, gz0, xi)],      # bottom
        [P(gy1, gz0, xi), P(gy1, gz0, xo), P(gy1, gz1, xo), P(gy1, gz1, xi)],      # nose end
        [P(gy0, gz0, xi), P(gy0, gz1, xi), P(gy0, gz1, xo), P(gy0, gz0, xo)],      # tail end
    ]                                                                              # (no inner face: against the plate)
    grip = orient(grip, P((gy0 + gy1) / 2, cz, (xi + xo) / 2))
    groups = [(BEZEL, False, plate), (GRIP, False, grip)]
    if name in ("door_fl", "door_fr"):
        ly, h = cy + LOCK_DY, LOCK / 2
        lock = [[P(ly - h, cz - h, PLATE_OUT + 0.001), P(ly + h, cz - h, PLATE_OUT + 0.001),
                 P(ly + h, cz + h, PLATE_OUT + 0.001), P(ly - h, cz + h, PLATE_OUT + 0.001)]]
        groups.append((GRIP, False, orient(lock, (0.0, ly, cz))))
    k = add_faces(ob, groups)
    report("  %-10s handle: -%d kotris faces, +%d tris, plate %.0f x %.0f mm at |x| %.3f, hole rim %s"
           % (name, removed, k, 2 * a * 1000, 2 * b * 1000, abs(P(cy, cz, 0.0)[0]),
              ("%d verts, margin %.1f mm" % (len(rim), margin * 1000)) if margin is not None else "none (no free rim)"))
    return k


# ----------------------------------------------------------------------------------------------
# mirrors: a rounded housing lofted forward from the glass rim to a domed front, the glass
# recessed in a thin bezel, on a short arm down to the black sail at the window's front corner

MIRROR_G = (0.912, 0.516, 1.195)     # glass centre (|x|, y, z): the kotris Miroir island
MIRROR_TILT = 18.0                   # glass turned inboard from straight back (kotris: outboard end y 0.487, inboard 0.546)
# 2026-10-17 review (EXT-7: "flat octagonal boxes"; S\review_exterior\ref\lx_mirror.jpg, ex_mirror.jpg): the
# RD1 housing is a rounded pillow, its glass face a rounded rectangle, its sides running straight forward a
# little and then rolling round into a domed front; it stands on a short arm off the sail. Section: a
# superellipse (|u/a|^e + |w/b|^e = 1) of MIRROR_SEG points; loft rings (depth forward of the rim, scale
# along the glass, scale up, shift along the glass toward the car); the last ring closes on an apex.
RIM = (0.100, 0.068)                 # half-u (along the glass), half-w (up): 20 x 13.6 cm, the photo's 20 x 13
MIRROR_E = 3.4                       # superellipse exponent: 2 an ellipse, higher squarer; the photo's corners
                                     # are ~3 cm radii on a 20 x 13.6 cm face
MIRROR_SEG = 16                      # 168 tris a mirror with the bezel, glass and arm
MIRROR_LOFT = ((0.000, 1.00, 1.00, 0.000), (0.042, 0.99, 0.98, 0.0066558), (0.075, 0.90, 0.87, 0.020),
               (0.092, 0.68, 0.64, 0.026))
# The second ring is the housing's widest point, |x| 1.01173: exactly the old octagon's back plate tip. The
# mirrors are the car's widest parts, and backfill's ray grid is laid on the shut car's box: a 2.8 mm
# narrower car moved every ray, and the back faces it found shifted round the car (+7 leak px at 225 deg,
# +7 at the front right wheel in the first build of 2026-10-17).
MIRROR_APEX = 0.098                  # the dome's tip. Forward is also outboard (the glass looks back and in),
                                     # so the front rings shift toward the car (4th item): the housing stays
                                     # inside the kotris envelope (|x| <= 1.016, y <= 0.635) the window
                                     # guards were fitted to
GLASS_K, GLASS_IN = (0.93, 0.90), 0.004   # the glass: this share of the rim (a 7 mm bezel), recessed this far
DEPTH = MIRROR_APEX
# the arm: a tapered block from the sail (the kotris wedge, x 0.70..0.83, black) into the housing's
# inboard lower corner, (|x|, y, z) at its foot and its head
ARM_FOOT = ((0.806, 0.846), (0.505, 0.606), 1.088)   # its foot runs forward to y 0.505 as the old pedestal's did:
                                                     # it screens a slit at the sail's front corner (2 px from
                                                     # the front when it stopped at 0.548)
ARM_HEAD = ((0.818, 0.858), (0.556, 0.598), 1.158)


def _superellipse(a, b, e, n):
    out = []
    for k in range(n):
        th = 2.0 * math.pi * (k + 0.5) / n
        c, s_ = math.cos(th), math.sin(th)
        out.append((a * math.copysign(abs(c) ** (2.0 / e), c), b * math.copysign(abs(s_) ** (2.0 / e), s_)))
    return out


def mirror_islands(ob):
    """Face ids of the mirror housing and glass on a front door: islands with a dark or Miroir
    majority at mirror height, wider than 10 cm across the car (the sail wedge behind the glass,
    x 0.70..0.83, is a separate island and stays), plus every piece an earlier run of this module
    built there (gen 7: the housing, the glass, the arm). Catches the full-detail islands before
    decimation and the 24/32/10/4-tri remains on a prepped door alike."""
    out = []
    for ids, lo, hi, maj, mats in islands(ob):
        c = (lo + hi) / 2
        zone = abs(c.x) > 0.80 and 0.45 < c.y < 0.65 and 1.08 < c.z < 1.30
        if zone and (((maj in (DARK, "Miroir")) and (hi.x - lo.x) > 0.10)
                     or (mats <= {PAINT, DARK, "Miroir"} and _all_gen(ob, ids))):   # an earlier run's housing / arm
            out.extend(ids)
    return out


def build_mirror(name, report):
    ob = bpy.data.objects.get(name)
    if ob is None:
        return 0
    s = -1 if name.endswith("l") else 1
    removed = delete_faces(ob, mirror_islands(ob))
    t = math.radians(MIRROR_TILT)
    n = Vector((-math.sin(t) * s, -math.cos(t), 0.0))     # glass normal: rearward, turned inboard
    u = Vector((math.cos(t) * s, -math.sin(t), 0.0))      # along the glass, outboard
    w = Vector((0.0, 0.0, 1.0))
    G = Vector((s * MIRROR_G[0], MIRROR_G[1], MIRROR_G[2]))

    def pt(a, b, d, du=0.0):
        return tuple(G + u * (a - du) + w * b - n * d)        # d: forward of the rim (against the glass normal)
    sec = _superellipse(RIM[0], RIM[1], MIRROR_E, MIRROR_SEG)
    rings = [[pt(a * ku, b * kw, d, du) for a, b in sec] for d, ku, kw, du in MIRROR_LOFT]
    m = MIRROR_SEG
    inside = tuple(G - n * 0.05)                              # inside the housing
    shell = []
    for r0, r1 in zip(rings, rings[1:]):
        shell += [quad(r0[i], r1[i], r1[(i + 1) % m], r0[(i + 1) % m]) for i in range(m)]
    d_last, _ku, _kw, du_last = MIRROR_LOFT[-1]
    apex = pt(0.0, 0.0, MIRROR_APEX, du_last)
    shell += [[rings[-1][i], apex, rings[-1][(i + 1) % m]] for i in range(m)]
    gla = [pt(a * GLASS_K[0], b * GLASS_K[1], GLASS_IN) for a, b in sec]      # recessed: forward of the rim
    bezel = [quad(rings[0][i], rings[0][(i + 1) % m], gla[(i + 1) % m], gla[i]) for i in range(m)]
    gc = pt(0.0, 0.0, GLASS_IN)
    glass = [[gc, gla[i], gla[(i + 1) % m]] for i in range(m)]
    shell, bezel, glass = (orient(f, inside) for f in (shell, bezel, glass))
    # the arm: a tapered block from the sail into the housing, closed at both ends (the housing's rounded
    # lower corner leaves its head in view: open, the game camera looked down into it and through its
    # culled far side to the ground, 2 px in the first build of 2026-10-17)
    (fx0, fx1), (fy0, fy1), fz = ARM_FOOT
    (hx0, hx1), (hy0, hy1), hz = ARM_HEAD
    foot = [(s * fx0, fy0, fz), (s * fx1, fy0, fz), (s * fx1, fy1, fz), (s * fx0, fy1, fz)]
    head = [(s * hx0, hy0, hz), (s * hx1, hy0, hz), (s * hx1, hy1, hz), (s * hx0, hy1, hz)]
    arm = [quad(foot[i], foot[(i + 1) % 4], head[(i + 1) % 4], head[i]) for i in range(4)] + [list(foot), list(head)]
    arm = orient(arm, tuple((Vector(foot[0]) + Vector(foot[2]) + Vector(head[0]) + Vector(head[2])) / 4))
    k = add_faces(ob, [(HOUSING, True, shell), (HOUSING, False, bezel), ("Miroir", "one", glass), (HOUSING, False, arm)])
    allp = [p for r in rings for p in r] + [apex]
    report("  %-10s mirror: -%d kotris faces, +%d tris, tip |x| %.3f, front y %.3f"
           % (name, removed, k, max(abs(p[0]) for p in allp), max(p[1] for p in allp)))
    return k


# ----------------------------------------------------------------------------------------------
# fuel flap (left rear quarter only: the RD1 fills on the left)

FLAP_C = (-1.472, 0.9855)            # (y, z): the kotris well's centre (Partie_noir, y -1.563..-1.381, z 0.904..1.067)
FLAP_HALF = (0.097, 0.0875)          # 19.4 x 17.5 cm panel: the 18.2 x 16.3 cm well plus 6 mm (photo flap 17.4 x 17.0)
FLAP_R = 0.035                       # corner radius (photo ~3 cm); paint_pass.FLAP repeats C / HALF / R
# 2026-10-17 review (EXT-11: "a ~1 cm dark bevelled rim"): the panel stood 2.5 mm proud on a 7 mm dark ring
# sloping back to the skin, and its corners were three-point chamfers. The real flap is flush with a hairline
# shut line: the panel now stands 2 mm off the outermost of the low and full-detail skins, the dark ring is
# 4 mm wide (1.3 px at the in-game 326 px/m) and drops only 1 mm, and the corners take FLAP_CORNER points
FLAP_OUT = 0.002                     # panel proud of the quarter skin
SEAM_W = 0.004                       # dark ring round it: the shut line
SEAM_OUT = 0.001                     # the ring's outer edge off the skin
FLAP_CORNER = 5


def rounded_rect(cy, cz, hy, hz, r, per_corner=3):
    pts = []
    for (sy, sz, a0) in ((1, 1, 0.0), (-1, 1, 90.0), (-1, -1, 180.0), (1, -1, 270.0)):
        for k in range(per_corner):
            a = math.radians(a0 + 90.0 * k / (per_corner - 1))
            pts.append((cy + sy * (hy - r) + r * math.cos(a), cz + sz * (hz - r) + r * math.sin(a)))
    return pts


def build_fuel_flap(report):
    ob, hi = bpy.data.objects.get("body"), bpy.data.objects.get("body_hi")
    if ob is None or hi is None:
        return 0
    cy, cz = FLAP_C
    kill = []
    for ids, lo, hi_, maj, mats in islands(ob):            # the kotris flap skin: a small Body island in the well
        c = (lo + hi_) / 2
        if ((maj == "Body" or (mats <= {"Body", DARK} and _all_gen(ob, ids)))      # (an earlier run's panel and ring)
                and c.x < -0.78 and abs(c.y - cy) < 0.03 and abs(c.z - cz) < 0.03 and (hi_ - lo).length < 0.32):
            kill.extend(ids)
    removed = delete_faces(ob, kill)                         # (the dark well behind it stays)
    tree = _tree(hi)                                         # the full-detail quarter still carries its flap
    low = _tree(ob)                                          # what ships: the ring must clear it too

    def on_skin(y, z, out, trees=(tree, low)):
        # the outermost of five casts on each tree: a cast landing in the crack between the kotris flap and
        # the quarter (or in the low body's well) would hit the well 1-2 cm deep and dent the panel's corner
        xs = [ray_x(t, y + dy, z + dz, -1) for t in trees
              for dy, dz in ((0, 0), (0.004, 0), (-0.004, 0), (0, 0.004), (0, -0.004))]
        xs = [x for x in xs if x is not None]
        return (min(xs) - out, y, z)
    outer = rounded_rect(cy, cz, FLAP_HALF[0], FLAP_HALF[1], FLAP_R, FLAP_CORNER)
    seam = rounded_rect(cy, cz, FLAP_HALF[0] + SEAM_W, FLAP_HALF[1] + SEAM_W, FLAP_R + SEAM_W, FLAP_CORNER)
    centre = on_skin(cy, cz, FLAP_OUT, (tree,))              # (the low body has only the well there)
    ring = [on_skin(y, z, FLAP_OUT) for y, z in outer]
    sring = [on_skin(y, z, SEAM_OUT) for y, z in seam]
    n = len(ring)
    inside = (0.0, cy, cz)
    panel = orient([[centre, ring[i], ring[(i + 1) % n]] for i in range(n)], inside)
    seamf = orient([quad(ring[i], sring[i], sring[(i + 1) % n], ring[(i + 1) % n]) for i in range(n)], inside)
    k = add_faces(ob, [("Body", "one", panel), (DARK, False, seamf)])
    report("  %-10s fuel flap: -%d kotris faces, +%d tris, centre x %.3f" % ("body", removed, k, centre[0]))
    return k


# ----------------------------------------------------------------------------------------------
# roof antenna stub (kotris: 3 x 8 x 3 cm at the left rear of the roof; the US car has none)

ROOF_STUB = Vector((-0.564, 0.176, 1.596))


def drop_roof_stub(report):
    removed = 0
    for name in ("body", "body_hi"):                         # off the twin too, or the bake projects a dark spot
        ob = bpy.data.objects.get(name)
        if ob is None:
            continue
        kill = []
        for ids, lo, hi, maj, mats in islands(ob):
            # SeamBack: on a re-run over a prepped blend, the seam-backing strips a later prep step
            # laid behind the stub's own edges (5 mm inside it, i.e. still above the roof) go too
            if ((lo + hi) / 2 - ROOF_STUB).length < 0.05 and maj in (DARK, "Partie_noir", "SeamBack"):
                kill.extend(ids)
        k = delete_faces(ob, kill)
        removed += k
        report("  %-10s roof antenna stub: -%d faces" % (name, k))
    return removed


# ----------------------------------------------------------------------------------------------
# front wipers: two planar blades with a forward lip, and their arms, parked along the windscreen base

# Parked as on the US cars (ex_fr.jpg, lx_fl.jpg; LHD tandem): both blades lie along the bottom of the
# screen pointing to the passenger side, the arm of each lying along its blade, just in front of it, from
# its pivot on the cowl to the blade's middle. 2026-10-17 review (EXT-13: "the blades cross in an X with
# loose triangles at the cowl"): the driver blade ran across its own arm (the blade sloped 3 cm in plan,
# the arm stayed level) and kotris's pivot caps and blade joints were left standing round them. Now
# every kotris wiper piece goes (WIPER_ZONE), each blade is a straight bar whose middle is lifted onto
# the glass, its arm stays in front of it, and the pivots get caps of our own.
WIPERS = [  # (pivot (x, y), blade from (x, y) to (x, y)); the screen's base runs y 0.904 (x -0.545),
            # 0.948 (-0.359), 0.976 (-0.106), 0.969 (0.203), 0.932 (0.446), 0.877 (0.617) at z 1.10-1.12
    ((-0.505, 0.948), (-0.430, 0.905), (0.090, 0.944)),      # driver blade, 52 cm (21 in.)
    ((0.245, 0.982), (0.200, 0.934), (0.660, 0.836)),        # passenger blade, 47 cm (18-19 in.): its pivot is
                                                             # where the hood leaves the cowl open (kotris's cap)
]
BLADE_W, ARM_W, BLADE_UP, ARM_UP, BLADE_LIP = 0.022, 0.014, 0.012, 0.022, 0.014
ARM_AHEAD = 0.016                    # the arm's centre line this far in front of the blade's, in plan
PIVOT_R, PIVOT_H = 0.019, 0.026      # pivot cap
WIPER_ZONE = (0.62, (0.89, 1.005), (1.07, 1.19), 0.16)   # kotris wiper pieces: |x| under, y, z, size under


def build_wipers(report):
    ob = bpy.data.objects.get("body")
    if ob is None:
        return 0
    kill, zone = [], []
    isl = islands(ob)
    blades = 0
    zx, (zy0, zy1), (zz0, zz1), zsize = WIPER_ZONE
    for ids, lo, hi, maj, mats in isl:                       # the kotris wiper slivers on the low body
        c = (lo + hi) / 2
        if maj in (DARK, "Partie_noir") and abs(c.x) < 0.70 and 0.78 < c.y < 1.06 and 1.08 < c.z < 1.20 and (hi.x - lo.x) >= 0.09:
            kill.extend(ids)
            blades += 1
        elif (mats <= {DARK, "Partie_noir"} and max(abs(lo.x), abs(hi.x)) < zx and lo.y > zy0 and hi.y < zy1
              and lo.z > zz0 and hi.z < zz1 and (hi - lo).length < zsize):
            zone.append((ids, lo, hi))                       # pivot caps, blade joints (and an earlier run's caps)
    # ... except a piece that covers a slit in the cowl: rays down through its footprint, past the body
    # without every candidate and past the shut hood, would fall into the bay (kotris's passenger blade
    # joint lies over the cowl-to-hood slit at x 0.27-0.33)
    if zone:
        me = ob.data
        out_ids = set(kill) | {i for ids, _lo, _hi in zone for i in ids}
        polys = [list(p.vertices) for p in me.polygons if p.index not in out_ids]
        M = ob.matrix_world
        rest = BVHTree.FromPolygons([M @ v.co for v in me.vertices], polys, all_triangles=False)
        hood = bpy.data.objects.get("hood")
        htree = _tree(hood) if hood is not None else None
        for ids, lo, hi in zone:
            through = False
            for i in range(6):
                for j in range(6):
                    p = Vector((lo.x + (hi.x - lo.x) * (i + 0.5) / 6, lo.y + (hi.y - lo.y) * (j + 0.5) / 6, 3.0))
                    hits = [t.ray_cast(p, Vector((0.0, 0.0, -1.0)), 4.0)[0] for t in (rest, htree) if t is not None]
                    top = max((h.z for h in hits if h is not None), default=None)
                    if top is None or top < lo.z - 0.15:
                        through = True
            if not through:
                kill.extend(ids)
    # ... and the blade tips at the A-pillars: small dark pieces (under 4 cm, |x| over 0.65) touching a
    # blade (within 3 mm). The passenger blade's tip (x 0.683-0.686) rode door_fr until
    # split_base.WS_CORNER (2026-10-13) and stood 2.5 cm proud of the screen past the new blade: the
    # "spike".
    caps = 0
    if kill:
        me = ob.data
        blade = BVHTree.FromPolygons([v.co.copy() for v in me.vertices],
                                     [list(me.polygons[i].vertices) for i in kill], all_triangles=False)
        gone = set(kill)
        for ids, lo, hi, maj, mats in isl:
            if maj not in (DARK, "Partie_noir") or (hi - lo).length >= 0.04 or ids[0] in gone \
                    or min(abs(lo.x), abs(hi.x)) < 0.65 or lo.x * hi.x <= 0:
                continue
            near = (blade.find_nearest(me.vertices[vi].co, 0.003) for i in ids for vi in me.polygons[i].vertices)
            if any(h[0] is not None for h in near):
                kill.extend(ids)
                caps += 1
    removed = delete_faces(ob, kill)
    tree = _tree(ob)                                         # the low body without them: glass, frit or cowl top

    def surf_z(x, y):
        z, n = ray_down(tree, x, y)
        return z if z is not None else 1.13
    def strip(pts, half, z_of):
        """Top faces of a flat bar along the plan polyline pts (half its width), z per point."""
        out = []
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            d = Vector((x1 - x0, y1 - y0)).normalized()
            o = Vector((-d.y, d.x)) * half
            out.append([(x0 + o.x, y0 + o.y, z_of(x0, y0)), (x1 + o.x, y1 + o.y, z_of(x1, y1)),
                        (x1 - o.x, y1 - o.y, z_of(x1, y1)), (x0 - o.x, y0 - o.y, z_of(x0, y0))])
        return out

    groups = []
    for (px, py), (ax, ay), (bx, by) in WIPERS:
        d = Vector((bx - ax, by - ay)).normalized()
        fwd = Vector((-d.y, d.x))
        fwd = fwd if fwd.y > 0 else -fwd                                   # in front of the blade (toward the hood)
        st = [(ax + (bx - ax) * k / 4.0, ay + (by - ay) * k / 4.0) for k in range(5)]   # straight, five stations
        zb = {s: surf_z(*s) + BLADE_UP for s in st}                         # its middle lifted onto the curved glass
        bz = lambda x, y: zb[(x, y)]                                        # noqa: E731
        top = strip(st, BLADE_W / 2, bz)
        e = fwd * (BLADE_W / 2)                                             # the forward lip, down toward the glass
        lip = [[(x0 + e.x, y0 + e.y, bz(x0, y0) - BLADE_LIP), (x1 + e.x, y1 + e.y, bz(x1, y1) - BLADE_LIP),
                (x1 + e.x, y1 + e.y, bz(x1, y1)), (x0 + e.x, y0 + e.y, bz(x0, y0))] for (x0, y0), (x1, y1) in zip(st, st[1:])]
        mx, my = st[2]
        jx, jy = mx + fwd.x * ARM_AHEAD, my + fwd.y * ARM_AHEAD             # the arm's tip, in front of the blade
        zp = surf_z(px, py) + PIVOT_H
        zj = bz(mx, my) + 0.006
        arm_pts = [(px, py), (px + (jx - px) * 0.5, py + (jy - py) * 0.5), (jx, jy)]
        zarm = {arm_pts[0]: zp, arm_pts[2]: zj}
        zarm[arm_pts[1]] = max(0.5 * (zp + zj), surf_z(*arm_pts[1]) + BLADE_UP + 0.008)
        arm = strip(arm_pts, ARM_W / 2, lambda x, y: zarm[(x, y)])
        hook = strip([(jx, jy), (mx, my)], ARM_W / 2, lambda x, y: zj)    # the arm's tip clipped onto the blade
        a2 = Vector((jx - px, jy - py)).normalized()                        # the arm's front side (it stands 1 cm)
        af = Vector((-a2.y, a2.x))
        af = (af if af.y > 0 else -af) * (ARM_W / 2)
        aside = [[(x0 + af.x, y0 + af.y, zarm[(x0, y0)] - 0.010), (x1 + af.x, y1 + af.y, zarm[(x1, y1)] - 0.010),
                  (x1 + af.x, y1 + af.y, zarm[(x1, y1)]), (x0 + af.x, y0 + af.y, zarm[(x0, y0)])]
                 for (x0, y0), (x1, y1) in zip(arm_pts, arm_pts[1:])]
        # the pivot cap: an 8-sided post from 4 mm under the cowl to the arm's root, closed on top
        zc = surf_z(px, py)
        ring_lo = [(px + PIVOT_R * math.cos(2 * math.pi * k / 8), py + PIVOT_R * math.sin(2 * math.pi * k / 8), zc - 0.004)
                   for k in range(8)]
        ring_hi = [(x, y, zp + 0.002) for x, y, _z in ring_lo]
        cap = [quad(ring_lo[k], ring_lo[(k + 1) % 8], ring_hi[(k + 1) % 8], ring_hi[k]) for k in range(8)] + [list(ring_hi)]
        groups.append((DARK, False, orient(top, (mx, my, 0.0))))          # faces up
        groups.append((DARK, False, orient(lip, (mx - fwd.x, my - fwd.y, bz(mx, my)))))   # faces forward
        groups.append((DARK, False, orient(arm + hook, (px, py, 0.0))))
        groups.append((DARK, False, orient(aside, (px - af.x * 50, py - af.y * 50, zp))))
        groups.append((DARK, False, orient(cap, (px, py, zc + 0.005))))
    k = add_faces(ob, groups)
    report("  %-10s wipers: -%d kotris faces (%d blades, %d A-pillar tips), +%d tris" % ("body", removed, blades, caps, k))
    return k


# ----------------------------------------------------------------------------------------------
# rear wiper: on the flip-up glass (trunk_top, trunkglass_bone), so it lifts with the glass

# kotris modelled it as ~50 slivers lying within 1-2 cm of the glass (Plastique_noir, decimated to 1-11 faces an
# island), and the bake projected its twin's copy onto the pane: at game zoom a painted wiper, and in Project
# Viewpoint, which draws the glass's Mask zone at 40 %, a ghost (2026-10-17 round 2, R2-VP-4). Now a closed
# pivot cap, arm and blade of our own on the glass (gen 7), kotris's pieces gone from the low part and its twin.
# Layout kotris's, which matches the parked RD1 wiper (S\review2_wheelsacc\ref_rear.png, lower right: the blade
# along the bottom of the glass to the left of the pivot, the arm from the pivot to the blade's middle): pivot
# (x, z) on the glass's lower middle, blade (x0, x1) at z, its arm's tip over the blade's middle.
RW_PIVOT = (-0.064, 1.2225)
RW_BLADE = ((-0.495, -0.172), 1.2505)
RW_ZONE = ((-0.505, 0.0), (1.19, 1.27), -1.99, 0.40)   # kotris pieces: x range, z range, y under, bbox under
RW_CAP_R, RW_CAP_H = 0.019, 0.026                    # pivot cap (off the glass)
# arm width; (bottom, top) off the glass at the pivot, its middle and the tip: it drops onto the blade quickly, as
# the rear glass guard's bars (acc_guard_rear, ~2.5 cm off the glass) cross it at x -0.22
RW_ARM_W, RW_ARM_H = 0.013, ((0.017, 0.026), (0.0115, 0.0165), (0.0120, 0.0170))
RW_BLADE_W, RW_BLADE_H = (0.016, 0.008), (0.0010, 0.0115)        # blade (base, top) width; (base, top) off the glass


def build_rear_wiper(report):
    ob = bpy.data.objects.get("trunk_top")
    if ob is None:
        return 0
    (zx0, zx1), (zz0, zz1), zy, zsize = RW_ZONE
    removed = 0
    for name in ("trunk_top", "trunk_top_hi"):              # off the twin too, or the bake projects it onto the pane
        o = bpy.data.objects.get(name)
        if o is None:
            continue
        kill = [i for ids, lo, hi, _maj, mats in islands(o)
                if mats <= {DARK} and lo.x > zx0 and hi.x < zx1 and lo.z > zz0 and hi.z < zz1 and hi.y < zy
                and (hi - lo).length < zsize for i in ids]
        removed += delete_faces(o, kill)
    me = ob.data
    names = [m.name if m else "?" for m in me.materials]
    M = ob.matrix_world
    glass = BVHTree.FromPolygons([M @ v.co for v in me.vertices],
                                 [list(p.vertices) for p in me.polygons if names[p.material_index] == "Vitre"],
                                 all_triangles=False)

    def on_glass(x, z):                                      # the pane's outer surface and its normal (out, -y)
        loc, n, _i, _d = glass.ray_cast(Vector((x, -3.0, z)), Vector((0.0, 1.0, 0.0)), 2.0)
        if loc is None:
            raise RuntimeError("rear wiper: no glass at x %.3f z %.3f" % (x, z))
        n = n.normalized()
        return loc, (n if n.y < 0 else -n)

    def prism(path, w_of, h_of, inside_off):
        """A closed bar along the glass path [(x, z)]: at each station the section is a trapezoid across the
        path (base width w_of(k)[0] at height h_of(k)[0] off the glass, top w_of(k)[1] at h_of(k)[1])."""
        secs, mids = [], []
        for k, (x, z) in enumerate(path):
            p, n = on_glass(x, z)
            a = path[max(k - 1, 0)]
            b = path[min(k + 1, len(path) - 1)]
            pa, _na = on_glass(*a)
            pb, _nb = on_glass(*b)
            t = pb - pa
            t = (t - n * t.dot(n)).normalized()
            s = n.cross(t).normalized()
            (wb, wt), (hb, ht) = w_of(k), h_of(k)
            secs.append([p + n * hb - s * wb / 2, p + n * hb + s * wb / 2, p + n * ht + s * wt / 2, p + n * ht - s * wt / 2])
            mids.append(p + n * inside_off(k))
        faces = []
        for k in range(len(path) - 1):
            a, b = secs[k], secs[k + 1]
            c = (mids[k] + mids[k + 1]) / 2
            for i in range(4):
                j = (i + 1) % 4
                faces += orient([quad(a[i], a[j], b[j], b[i])], tuple(c))
        faces += orient([[tuple(v) for v in secs[0]]], tuple(mids[0] + (mids[0] - mids[1]).normalized() * -0.001))
        faces += orient([[tuple(v) for v in secs[-1]]], tuple(mids[-1] + (mids[-1] - mids[-2]).normalized() * -0.001))
        return faces

    (bx0, bx1), bz = RW_BLADE
    bpath = [(bx0 + (bx1 - bx0) * k / 4.0, bz) for k in range(5)]
    blade = prism(bpath, lambda k: RW_BLADE_W, lambda k: RW_BLADE_H, lambda k: 0.5 * sum(RW_BLADE_H))
    px, pz = RW_PIVOT
    tip = ((bx0 + bx1) / 2.0, bz)
    apath = [(px, pz), (px + (tip[0] - px) * 0.5, pz + (tip[1] - pz) * 0.5), tip]
    hs = RW_ARM_H
    arm = prism(apath, lambda k: (RW_ARM_W, RW_ARM_W * 0.8), lambda k: hs[k], lambda k: 0.5 * sum(hs[k]))
    # the pivot cap: an 8-sided post from just off the glass to the arm's root, closed on top
    p, n = on_glass(px, pz)
    u = Vector((1.0, 0.0, 0.0))
    u = (u - n * u.dot(n)).normalized()
    v = n.cross(u)
    lo_ = [p + n * 0.0008 + (u * math.cos(2 * math.pi * k / 8) + v * math.sin(2 * math.pi * k / 8)) * RW_CAP_R for k in range(8)]
    hi_ = [q + n * (RW_CAP_H - 0.0008) for q in lo_]
    mid = p + n * (RW_CAP_H / 2)
    cap = orient([quad(lo_[k], lo_[(k + 1) % 8], hi_[(k + 1) % 8], hi_[k]) for k in range(8)], tuple(mid))
    cap += orient([[tuple(q) for q in hi_]], tuple(mid))
    k = add_faces(ob, [(DARK, False, blade), (DARK, False, arm), (DARK, False, cap)])
    report("  %-10s rear wiper: -%d kotris faces (low + twin), +%d tris (cap at x %.3f z %.3f, blade %.0f cm, arm to x %.3f)"
           % ("trunk_top", removed, k, px, pz, (bx1 - bx0) * 100, tip[0]))
    return k


# ----------------------------------------------------------------------------------------------
# roof rails: a level bar each side on three feet (EX trim; book height 1710 mm with rails, 1675 without)

RAIL_X, RAIL_Y = 0.555, (-1.66, 0.10)      # |x| of the bar centre (roof edge rolls off at 0.58..0.60), rear..front end
RAIL_W, RAIL_H, RAIL_UP = 0.026, 0.022, 0.055   # bar section; bar top 5.5 cm above the roof crown (1.645 -> 1.700)
FEET = ((0.02, 0.16), (-0.78, 0.12), (-1.60, 0.12))   # (y centre, length): MG 8767's three feet
FOOT_W, FOOT_SLOPE = 0.032, 0.06           # the front foot's face slopes 6 cm down to the roof (a fairing)


def build_rails(report):
    ob, hi = bpy.data.objects.get("body"), bpy.data.objects.get("body_hi")
    if ob is None or hi is None:
        return 0
    tree = _tree(hi)
    groups = []
    top = None
    for s in (-1, 1):
        x = s * RAIL_X
        crown = max(ray_down(tree, x, y)[0] or 0.0 for y in (-1.6, -1.2, -0.75, -0.3, 0.0))
        top = crown + RAIL_UP
        xa, xb = x - RAIL_W / 2, x + RAIL_W / 2
        ya, yb = RAIL_Y
        bar = orient(box_faces((xa, ya, top - RAIL_H), (xb, yb, top), skip=('z-',)), (x, (ya + yb) / 2, top - RAIL_H / 2))
        groups.append((DARK, False, bar))
        for i, (yc, ln) in enumerate(FEET):
            y0, y1 = yc - ln / 2, yc + ln / 2
            y1b = y1 + (FOOT_SLOPE if i == 0 else 0.0)                 # the sloped front face reaches further forward at the roof

            def roof(y):
                z, _n = ray_down(tree, x, y)
                return (z if z is not None else crown) - 0.006           # sunk 6 mm into the roof skin
            zt = top - RAIL_H + 0.002
            xa_, xb_ = x - FOOT_W / 2, x + FOOT_W / 2
            foot = [
                quad((xa_, y0, roof(y0)), (xa_, y0, zt), (xa_, y1, zt), (xa_, y1b, roof(y1b))),   # inner / outer sides
                quad((xb_, y0, roof(y0)), (xb_, y1b, roof(y1b)), (xb_, y1, zt), (xb_, y0, zt)),
                quad((xa_, y0, roof(y0)), (xb_, y0, roof(y0)), (xb_, y0, zt), (xa_, y0, zt)),      # rear face
                quad((xa_, y1b, roof(y1b)), (xa_, y1, zt), (xb_, y1, zt), (xb_, y1b, roof(y1b))),  # front face (sloped on foot 0)
            ]
            groups.append((DARK, False, orient(foot, (x, (y0 + y1) / 2, (zt + roof(yc)) / 2))))
    k = add_faces(ob, groups)
    report("  %-10s roof rails: +%d tris, bar top z %.3f" % ("body", k, top))
    return k


# ----------------------------------------------------------------------------------------------


def build(report=print):
    """Run after the panels are low and the sill strips are on, before the seam backing. Returns
    the net triangle change over the body and doors."""
    names = ("body", "door_fl", "door_fr", "door_rl", "door_rr")
    t0 = sum(tris(bpy.data.objects[n]) for n in names if bpy.data.objects.get(n))
    for name in HANDLE_AT:
        build_handle(name, report)
    for name in MIRROR_DOORS:
        build_mirror(name, report)
    build_fuel_flap(report)
    drop_roof_stub(report)
    build_wipers(report)
    build_rear_wiper(report)
    build_rails(report)
    t1 = sum(tris(bpy.data.objects[n]) for n in names if bpy.data.objects.get(n))
    report("  details: body + doors %d -> %d tris (%+d)" % (t0, t1, t1 - t0))
    return t1 - t0


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    build()
    if "--save" in argv:
        bpy.ops.wm.save_as_mainfile(filepath=argv[argv.index("--save") + 1])
