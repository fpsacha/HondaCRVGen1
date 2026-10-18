r"""
Honda CR-V RD1 (2000 EX) body builder - Phase 2/3 geometry, generated from parameters.

    import sys; sys.path.append("scripts")
    import build_body, importlib; importlib.reload(build_body); build_body.build()

Method
  * Sides/roof: an 11-feature-line loft. Each cross-section ring is 20 verts (11 lines on +X,
    9 mirrored). Key profiles at a few Y stations, linear blend between; then wheel arches are
    cut by lifting the lower lines over the tyre, and both ends are rounded in plan by a
    circular width falloff (the RD1's headlamps and bumpers wrap its corners).
  * Nose and tail: real quad grids (rows = feature lines, columns across the width) with a
    depth function - deep bumpers standing proud, recessed grille and lamps, convex faces.
  * Faces get material slots by rule, so doors, glass, hood, lamps are already clean face groups
    for Phase 3 splitting and Phase 6 texturing.
  Rebuild from script, never hand-edit (PROJECT.md section 7).

Axes (Blender, right-handed): metres, +Y = front, +Z = up, and therefore +X = vehicle RIGHT.
Left-hand parts (wheel_FL, mirror_L) live at negative X. PZ script space has +X = left; the FBX
export is a proper rotation that flips X (spec/pz-conventions.md section 3).
Body origin = vehicle centre, ground level, midway between axles.

Numbers: book RD1 dimensions for absolutes (wheelbase 2.62, width 1.75, height 1.675, tyre
0.668, length 4.51 incl. spare) and photo-derived proportions for shape, corrected for lens
perspective (spec/measurements.md). Body ends at y=-2.15; the spare carries the rest.
"""

import math

import bmesh
import bpy

# ------------------------------------------------------------------ dimensions (metres)
WHEELBASE = 2.62
Y_AXF, Y_AXR = WHEELBASE / 2, -WHEELBASE / 2          # +1.31 / -1.31
TRACK_F, TRACK_R = 1.52, 1.51
TYRE_R, TYRE_W = 0.334, 0.205                          # 205/70R15
RIM_R = 0.19
R_ARCH = 0.40                                          # arch opening radius (tyre fills the arch)
FLARE = 0.05                                           # black plastic arch flare, outward

# Y landmarks
Y_NOSE, Y_TAIL = 2.16, -2.15
Y_COWL, Y_WSTOP = 0.78, 0.36                           # windscreen base / top  (~53 deg)
Y_A, Y_B, Y_C, Y_D = 0.75, -0.20, -0.98, -1.85         # door edges (A at the pillar base)
Y_LAMP = -1.95                                         # D-pillar tail lamp starts here
B_PILLAR = (-0.26, -0.16)                               # black pillar between the door windows
C_PILLAR = (-1.04, -0.94)                               # pillar between rear door and quarter glass
GLASS_RECESS = 0.02                                    # glass sits inside the pillar plane

# Plan-view corner rounding: (zone length, width factor at the face for lines 1-4 / 5-9)
NOSE_ROUND = (0.55, 0.66, 0.84)                        # bumper wraps more than the lamp face
TAIL_ROUND = (0.30, 0.78, 0.90)                        # tailgate is nearly full width

# ------------------------------------------------------------------ key profiles
# 11 feature lines per half-ring, bottom to top, as (half_width, height), BEFORE plan rounding:
#  0 floor centre  1 floor inner  2 sill bottom  3 cladding top  4 rub strip
#  5 max width     6 beltline     7 window mid   8 roof edge     9 roof flat  10 roof centre
# Hood: 0.95 lip -> 1.115 cowl with a 3-4 cm crown. Glass near vertical, wide flat roof.
KEYS = [
    # v8: beltline 1.06 (glass:door ~0.85 like the real car), lamps 0.66-0.83 at tyre-top height,
    # hood 0.89 lip -> 1.06 cowl, bumper 0.32-0.60 front / 0.37-0.70 rear.
    ( 2.16, [(0,.32),(.45,.32),(.72,.34),(.80,.47),(.82,.60),(.82,.66),(.81,.75),(.77,.83),(.64,.87),(.42,.885),(0,.89)]),
    ( 2.00, [(0,.31),(.52,.31),(.78,.33),(.84,.47),(.86,.61),(.865,.67),(.845,.77),(.80,.85),(.68,.895),(.44,.915),(0,.925)]),
    ( 1.80, [(0,.30),(.55,.30),(.80,.36),(.85,.50),(.87,.62),(.875,.70),(.85,.81),(.80,.88),(.69,.925),(.45,.945),(0,.955)]),
    ( 1.20, [(0,.30),(.55,.30),(.80,.41),(.85,.52),(.87,.64),(.875,.80),(.845,.91),(.80,.95),(.70,.965),(.46,.98),(0,.99)]),
    ( 0.78, [(0,.30),(.55,.30),(.80,.42),(.84,.52),(.86,.64),(.865,.80),(.80,.97),(.78,.995),(.75,1.01),(.52,1.02),(0,1.03)]),
    # cabin: belt 1.03 -> glass 0.57 tall over a 0.61 door panel (photo ratio ~0.9)
    ( 0.36, [(0,.30),(.55,.30),(.80,.42),(.84,.52),(.86,.64),(.865,.80),(.78,1.03),(.765,1.31),(.745,1.615),(.655,1.665),(0,1.675)]),
    (-0.98, [(0,.30),(.55,.30),(.80,.42),(.84,.52),(.86,.64),(.865,.80),(.78,1.03),(.765,1.31),(.745,1.615),(.655,1.665),(0,1.675)]),
    (-1.72, [(0,.31),(.55,.31),(.79,.43),(.83,.53),(.85,.65),(.855,.81),(.775,1.03),(.76,1.31),(.74,1.615),(.65,1.663),(0,1.672)]),
    # tail: roof flat to the back, tailgate a near-vertical full-width slab
    (-2.05, [(0,.34),(.54,.34),(.78,.45),(.83,.56),(.85,.67),(.855,.82),(.775,1.05),(.76,1.31),(.735,1.61),(.645,1.66),(0,1.67)]),
    (-2.15, [(0,.37),(.52,.37),(.76,.46),(.81,.58),(.83,.70),(.835,.84),(.765,1.05),(.75,1.31),(.72,1.59),(.63,1.645),(0,1.655)]),
]
N_LINES = 11
RING = 2 * N_LINES - 2          # 20 verts per ring
CAP_COLS = 10                   # columns across the nose / tail grids


def _profile_at(y):
    keys = sorted(KEYS, key=lambda k: k[0])
    if y <= keys[0][0]:
        return list(keys[0][1])
    if y >= keys[-1][0]:
        return list(keys[-1][1])
    for (ya, pa), (yb, pb) in zip(keys, keys[1:]):
        if ya <= y <= yb:
            t = (y - ya) / (yb - ya)
            return [(wa + (wb - wa) * t, za + (zb - za) * t) for (wa, za), (wb, zb) in zip(pa, pb)]
    return list(keys[-1][1])


def _plan_round(y, prof):
    """Round both ends in plan view: widths fall off on a circular arc towards the face."""
    prof = list(prof)
    for y_end, (zone, f_low, f_high), sign in ((Y_NOSE, NOSE_ROUND, 1), (Y_TAIL, TAIL_ROUND, -1)):
        d = (y_end - y) * sign                     # distance in from the end face
        if 0 <= d < zone:
            u = 1 - d / zone                        # 1 at the face, 0 at the zone start
            g = math.sqrt(max(0.0, 1 - u * u))      # 1 -> 0 along a quarter circle
            for i in range(1, N_LINES - 1):
                fmin = f_low if i <= 4 else f_high
                w, z = prof[i]
                prof[i] = (w * (fmin + (1 - fmin) * g), z)
    return prof


def _arch_lift(y, prof):
    """Cut the wheel arch: lift sill/cladding/rub lines onto the arch circle, add the flare."""
    prof = list(prof)
    for yc in (Y_AXF, Y_AXR):
        dy = y - yc
        if abs(dy) < R_ARCH:
            za = TYRE_R + math.sqrt(R_ARCH ** 2 - dy ** 2)
            zcap = prof[5][1] - 0.012                       # never fold over the max-width line
            for i, lip in ((2, 0.0), (3, 0.03), (4, 0.06)):
                w, z = prof[i]
                prof[i] = (w + FLARE, min(max(z, za + lip), zcap - (4 - i) * 0.006))
        elif abs(dy) < R_ARCH + 0.12:                      # flare fades out
            f = 1 - (abs(dy) - R_ARCH) / 0.12
            for i in (2, 3, 4):
                w, z = prof[i]
                prof[i] = (w + FLARE * f, z)
    return prof


def _stations():
    ys = {k[0] for k in KEYS} | {Y_A, Y_D, Y_LAMP, 0.55, 0.10, -0.55, -1.45}
    ys |= set(B_PILLAR) | set(C_PILLAR)                # pillar edges: proud, un-recessed rings
    ys |= {2.13, 2.08, 1.90, 1.61}                     # plan-rounding resolution, nose
    ys |= {-2.12, -2.08, -2.02, -1.95, -1.78}          # plan-rounding resolution, tail
    for yc in (Y_AXF, Y_AXR):
        for f in (-0.97, -0.82, -0.58, -0.30, 0.0, 0.30, 0.58, 0.82, 0.97):
            ys.add(round(yc + f * R_ARCH, 4))
    return sorted(ys, reverse=True)               # nose first


def _ring_verts(y, prof):
    right = [(w, y, z) for (w, z) in prof]                   # +X side, lines 0..10
    left = [(-w, y, z) for (w, z) in reversed(prof[1:-1])]   # lines 9..1 mirrored
    return right + left


def _line_of(k):
    return k if k < N_LINES else RING - k


# ------------------------------------------------------------------ materials
MATS = {
    "paint":     (0.78, 0.78, 0.80, 1),
    "cladding":  (0.22, 0.22, 0.23, 1),
    "glass":     (0.25, 0.32, 0.40, 1),
    "black":     (0.04, 0.04, 0.04, 1),
    "light_f":   (0.93, 0.92, 0.66, 1),
    "light_r":   (0.75, 0.08, 0.06, 1),
    "grille":    (0.08, 0.08, 0.08, 1),
    "rubber":    (0.05, 0.05, 0.05, 1),
    "rim":       (0.72, 0.72, 0.74, 1),
    "light_a":   (0.85, 0.42, 0.05, 1),
}
SLOT = {name: i for i, name in enumerate(MATS)}


def _ensure_mats():
    out = []
    for name, col in MATS.items():
        m = bpy.data.materials.get("crv_" + name)
        if m is None:
            m = bpy.data.materials.new("crv_" + name)
        m.use_nodes = True
        m.diffuse_color = col
        bsdf = m.node_tree.nodes.get("Principled BSDF")
        if bsdf:
            bsdf.inputs["Base Color"].default_value = col
            bsdf.inputs["Roughness"].default_value = 0.35 if name in ("paint", "rim", "glass") else 0.8
        out.append(m)
    return out


def _between(y, a, b):
    lo, hi = min(a, b), max(a, b)
    return lo < y < hi


def _side_material(lo, hi, ymid, xmid):
    """Material for a loft face by feature-line band (lo,hi) and position."""
    front = ymid > 2.02
    tail = ymid < -2.06
    near_arch = any(abs(ymid - yc) < R_ARCH + 0.06 for yc in (Y_AXF, Y_AXR))
    bumper_wrap = ymid > 1.60 or ymid < -1.75

    if hi <= 2:
        return "black"                                    # underbody + wheel wells, in shadow
    if hi <= 3:
        return "cladding"                                 # grey sill strip, full length
    if near_arch and hi <= 4:
        return "cladding"                                 # arch flare
    if (front or tail) and hi <= 4:
        return "cladding"                                 # bumper corners
    if front and lo in (5, 6) and hi <= 7:
        return "light_f"                                  # headlamps wrap the corner
    if tail and lo >= 6 and hi <= 8:
        return "light_r"                                  # tail lamps wrap the corner
    if lo >= 6 and hi <= 8:                               # side glass band
        if _between(ymid, Y_LAMP, -2.06):
            return "light_r"
        if _between(ymid, *B_PILLAR) or _between(ymid, *C_PILLAR):
            return "black"                                # real pillars between the windows
        front_door_glass = (lo == 6 and _between(ymid, B_PILLAR[1], 0.58)) or \
                           (lo == 7 and _between(ymid, B_PILLAR[1], 0.34))     # raked A-pillar
        if front_door_glass:
            return "glass"
        if _between(ymid, C_PILLAR[1], B_PILLAR[0]):
            return "glass"                                # rear door
        if _between(ymid, Y_D, C_PILLAR[0]):
            return "glass"                                # quarter
    if lo >= 8 and _between(ymid, Y_WSTOP, Y_COWL):
        return "glass"                                    # windscreen
    return "paint"


def _nose_cell(band, ax, w_row):
    """Front face: material + depth (positive = forward). The bumper is the forward-most part."""
    if band <= 1:
        return "cladding", 0.05
    if band == 2:
        return ("grille", 0.03) if ax < 0.30 else ("cladding", 0.07)     # lower intake in the bumper
    if band == 3:
        return ("light_f", 0.05) if 0.40 < ax < 0.60 else ("cladding", 0.07)   # fog lamps
    if band == 4:
        return "paint", 0.03                              # painted fascia above the bumper
    if band == 5:
        return ("light_f", -0.02) if ax > 0.30 else ("paint", 0.0)
    if band == 6:
        return ("light_f", -0.02) if ax > 0.30 else ("grille", -0.035)   # slot grille
    if band == 7:
        return "paint", 0.0                               # hood lip
    return "paint", 0.0


def _tail_cell(band, ax, w_row):
    """Rear face: material + depth (positive = rearward). Deep bumper, glass to the roof."""
    if band <= 3:
        return ("light_r", 0.07) if (band == 3 and 0.40 < ax < 0.58) else ("cladding", 0.08)
    if band in (4, 5):
        return "paint", 0.0                               # tailgate skin
    if band in (6, 7):
        return ("light_r", 0.0) if ax > w_row - 0.15 else ("glass", -0.02)
    if band == 8:
        return ("paint", 0.0) if ax > w_row - 0.15 else ("glass", -0.02)
    return "paint", 0.0


# ------------------------------------------------------------------ builders
def _coll(name):
    c = bpy.data.collections.get(name)
    if c is None:
        c = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(c)
    return c


def _purge(names):
    for n in names:
        o = bpy.data.objects.get(n)
        if o:
            bpy.data.objects.remove(o, do_unlink=True)
    for me in list(bpy.data.meshes):
        if me.users == 0:
            bpy.data.meshes.remove(me)


def _finish(me):
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-4)
    bmesh.ops.dissolve_degenerate(bm, dist=1e-4, edges=bm.edges)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    me.validate()
    me.update()


def _mesh_obj(name, verts, faces, mat_idx, coll, mats):
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    for m in mats:
        me.materials.append(m)
    for p, mi in zip(me.polygons, mat_idx):
        p.material_index = mi
        p.use_smooth = False
    _finish(me)
    ob = bpy.data.objects.new(name, me)
    coll.objects.link(ob)
    return ob


def _cap_grid(prof, y_face, sign, cell_fn, verts, faces, mats_idx, bulge):
    """Quad grid closing one end of the loft. Rows follow the feature lines, so the boundary
    column coincides with the end ring and merges on remove_doubles. sign=+1 nose, -1 tail.
    Depth = convex bulge (zero at the edges) + per-cell feature offsets (interior only)."""
    base = len(verts)
    n = CAP_COLS
    for i, (w, z) in enumerate(prof):
        for k in range(n + 1):
            t = -1 + 2 * k / n
            x = w * t
            d = bulge * (1 - t * t)
            if 0 < k < n and 0 < i < N_LINES - 1:
                _, feat = cell_fn(i, abs(x), w)
                d += feat
            verts.append((x, y_face + sign * d, z))
    for i in range(N_LINES - 1):
        w_row = prof[i + 1][0]
        for k in range(n):
            a = base + i * (n + 1) + k
            b = base + (i + 1) * (n + 1) + k
            faces.append((a, a + 1, b + 1, b))
            xc = (prof[i][0] + prof[i + 1][0]) / 2 * abs(-1 + 2 * (k + 0.5) / n)
            mat, _ = cell_fn(i, xc, w_row)
            mats_idx.append(SLOT[mat])


GLASS_SPANS = ((B_PILLAR[1], 0.34), (C_PILLAR[1], B_PILLAR[0]), (Y_D, C_PILLAR[0]))


def _glass_recess(y, prof):
    """Inside a window opening the glass line sits behind the pillar plane, so the pillars
    (rings at the span edges, left at full width) stand proud and each window reads as its own."""
    if any(lo < y < hi for lo, hi in GLASS_SPANS):
        prof = list(prof)
        w, z = prof[7]
        prof[7] = (w - GLASS_RECESS, z)
    return prof


def build_body(coll, mats):
    ys = _stations()
    profs = [_glass_recess(y, _arch_lift(y, _plan_round(y, _profile_at(y)))) for y in ys]
    rings = [_ring_verts(y, p) for y, p in zip(ys, profs)]

    verts, faces, mats_idx = [], [], []
    for r in rings:
        verts.extend(r)
    for s in range(len(rings) - 1):
        a, b = s * RING, (s + 1) * RING
        ymid = (ys[s] + ys[s + 1]) / 2
        for k in range(RING):
            k2 = (k + 1) % RING
            faces.append((a + k, a + k2, b + k2, b + k))
            lo, hi = sorted((_line_of(k), _line_of(k2)))
            xmid = (verts[a + k][0] + verts[a + k2][0] + verts[b + k][0] + verts[b + k2][0]) / 4
            mats_idx.append(SLOT[_side_material(lo, hi, ymid, xmid)])

    _cap_grid(profs[0], ys[0], +1, _nose_cell, verts, faces, mats_idx, bulge=0.04)
    _cap_grid(profs[-1], ys[-1], -1, _tail_cell, verts, faces, mats_idx, bulge=0.03)
    return _mesh_obj("body", verts, faces, mats_idx, coll, mats)


def _wheel_mesh(name, coll, mats):
    """Tyre + rim revolved around local X; rim face on local +X. Origin at axle centre."""
    prof = [
        (0.00, -0.055), (RIM_R, -0.075), (RIM_R + 0.02, -TYRE_W / 2), (TYRE_R - 0.03, -TYRE_W / 2),
        (TYRE_R, -0.06), (TYRE_R, 0.06), (TYRE_R - 0.03, TYRE_W / 2), (RIM_R + 0.02, TYRE_W / 2),
        (RIM_R, 0.085), (RIM_R * 0.55, 0.055), (0.00, 0.075),
    ]
    rim_band = {0, 7, 8, 9}
    seg = 16
    verts, faces, mi = [], [], []
    for (r, a) in prof:
        for i in range(seg):
            t = 2 * math.pi * i / seg
            verts.append((a, r * math.cos(t), r * math.sin(t)))
    for j in range(len(prof) - 1):
        for i in range(seg):
            i2 = (i + 1) % seg
            faces.append((j * seg + i, j * seg + i2, (j + 1) * seg + i2, (j + 1) * seg + i))
            mi.append(SLOT["rim"] if j in rim_band else SLOT["rubber"])
    return _mesh_obj(name, verts, faces, mi, coll, mats)


def _box(name, size, loc, mat, coll, mats):
    sx, sy, sz = [s / 2 for s in size]
    v = [(-sx, -sy, -sz), (sx, -sy, -sz), (sx, sy, -sz), (-sx, sy, -sz),
         (-sx, -sy, sz), (sx, -sy, sz), (sx, sy, sz), (-sx, sy, sz)]
    f = [(0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)]
    ob = _mesh_obj(name, v, f, [SLOT[mat]] * 6, coll, mats)
    ob.location = loc
    return ob


PART_NAMES = ["body", "wheel_FL", "wheel_FR", "wheel_RL", "wheel_RR", "spare",
              "mirror_L", "mirror_R", "roofrail_L", "roofrail_R"]


def build():
    mats = _ensure_mats()
    c_body, c_wheels, c_trim = _coll("body"), _coll("wheels"), _coll("trim")
    _purge(PART_NAMES)

    body = build_body(c_body, mats)

    # Left side is -X (see module docstring). Rim face is local +X, so left wheels turn 180.
    xf, xr = TRACK_F / 2, TRACK_R / 2
    for nm, x, y in (("wheel_FL", -xf, Y_AXF), ("wheel_FR", xf, Y_AXF),
                     ("wheel_RL", -xr, Y_AXR), ("wheel_RR", xr, Y_AXR)):
        w = _wheel_mesh(nm, c_wheels, mats)
        w.location = (x, y, TYRE_R)
        if x < 0:
            w.rotation_euler = (0, 0, math.pi)

    # Tailgate spare: mounted on the RIGHT half of the tailgate (+X), hinge side. Owner-confirmed.
    sp = _wheel_mesh("spare", c_trim, mats)
    sp.location = (0.28, Y_TAIL - TYRE_W / 2 - 0.09, 0.98)
    sp.rotation_euler = (0, 0, -math.pi / 2)              # local +X (rim face) -> world -Y

    _box("mirror_L", (0.21, 0.10, 0.13), (-0.87, 0.48, 1.13), "paint", c_trim, mats)
    _box("mirror_R", (0.21, 0.10, 0.13), (0.87, 0.48, 1.13), "paint", c_trim, mats)
    _box("roofrail_L", (0.06, 2.30, 0.045), (-0.52, -0.78, 1.684), "black", c_trim, mats)
    _box("roofrail_R", (0.06, 2.30, 0.045), (0.52, -0.78, 1.684), "black", c_trim, mats)

    bb = [body.matrix_world @ v.co for v in body.data.vertices]
    print("CRV body built: verts %d faces %d" % (len(body.data.vertices), len(body.data.polygons)))
    print("  body W %.3f  L %.3f  H %.3f (top %.3f)" % (
        max(p.x for p in bb) - min(p.x for p in bb), max(p.y for p in bb) - min(p.y for p in bb),
        max(p.z for p in bb) - min(p.z for p in bb), max(p.z for p in bb)))
    tot = sum(len(bpy.data.objects[n].data.vertices) for n in PART_NAMES if n in bpy.data.objects)
    print("  total verts all parts: %d" % tot)
    return body


if __name__ == "__main__":
    build()
