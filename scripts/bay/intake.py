"""Engine bay v2, group "intake" (spec/engine-bay-v2.md).

The late (1999-2001) B20B upper intake: a bare cast-aluminium box standing behind the cam cover, a raised
ribbed hump on its +x half, a lower ribbed -x half sloping to the front, and a front skirt with scallops
(bolt notches and the PCV hose's arch) over the runner stubs. The neck on its +x end carries the throttle
body (cam on its front face, idle air valve under it, the cable to the firewall: I9). The vacuum port I8
sticks out of the box's -x rear. The fat ribbed rubber duct arcs forward-right inboard of the right tower
into the air box's boss; the air box is the big black ribbed box at the car's right front, with a
two-level lid, clips and a snorkel dropping out of its front.

Reference: lhd_06 / b20b-rd1 (the plenum box), DSC_7913 and lhd_06 (the air box), lhd_03 (the duct).
"""
import math

from mathutils import Vector

from bay import kit

BUDGET = 1000

# plenum box extents (x) and its top decal
PX0, PX1 = -0.205, 0.095
DECALS = {
    "DecalIntakePlenumTop": ("bay_intake_plenum_top.png", ("x", PX0, PX1), ("y", 1.035, 1.225), "AluCast"),
    "DecalIntakeAirboxTop": ("bay_intake_airbox_top.png", ("x", 0.300, 0.570), ("y", 1.340, 1.680), "Plastic"),
    "DecalIntakeAirboxFront": ("bay_intake_airbox_front.png", ("x", 0.300, 0.570), ("z", 0.790, 0.950), "Plastic"),
}

# throttle body axis (x) and the duct's start
TB_C = Vector((0.0, 1.100, 0.958))          # y, z of the bore axis (x varies)
TB_X0, TB_X1 = 0.140, 0.212
BOSS_C = Vector((0.378, 1.398, 0.900))      # air box duct boss: base centre on the lid's rear inboard level
BOSS_AX = Vector((0.0, -0.42, 1.0)).normalized()


# ----------------------------------------------------------------------------- helpers
def _normal(vs):
    n = Vector()
    for i in range(len(vs)):
        a, b = vs[i], vs[(i + 1) % len(vs)]
        n.x += (a.y - b.y) * (a.z + b.z)
        n.y += (a.z - b.z) * (a.x + b.x)
        n.z += (a.x - b.x) * (a.y + b.y)
    return n.normalized() if n.length > 1e-12 else n


def faces_facing(data, axis, thresh=0.40):
    """face_mats {i: 1} for the faces of a closed solid whose outward normal leans along `axis` (a
    Vector) by more than thresh: the decal goes on those."""
    v, f = data
    V = [Vector(p) for p in v]
    cen = sum(V, Vector()) / len(V)
    out = {}
    for i, face in enumerate(f):
        vs = [V[k] for k in face]
        n = _normal(vs)
        fc = sum(vs, Vector()) / len(vs)
        if n.dot(fc - cen) < 0:
            n = -n
        if n.dot(axis) > thresh:
            out[i] = 1
    return out


def arch_outline(x0, x1, zb, zt, arches, arc_pts=3):
    """Front outline (x, z) of a skirt from x0 to x1, bottom zb, top zt, with round-topped notches cut
    up from the bottom: arches = [(xc, r, straight)]."""
    pts = [(x0, zt), (x0, zb)]
    for xc, r, hs in sorted(arches):
        pts += [(xc - r, zb), (xc - r, zb + hs)]
        for k in range(1, arc_pts + 1):
            a = math.pi - math.pi * k / (arc_pts + 1)
            pts.append((xc + r * math.cos(a), zb + hs + r * math.sin(a)))
        pts += [(xc + r, zb + hs), (xc + r, zb)]
    pts += [(x1, zb), (x1, zt)]
    return pts


def path_rings(ctrl, stations, seg=8, per=10, phase=0.5):
    """Rings for a tube along a Catmull-Rom path through ctrl. stations: [(s 0..1 of the length,
    radius)]. Parallel-transported frames, so the tube does not twist."""
    P = kit.catmull([Vector(p) for p in ctrl], per=per, closed=False)
    L = [0.0]
    for a, b in zip(P, P[1:]):
        L.append(L[-1] + (b - a).length)
    tot = L[-1]

    def at(s):
        d = max(0.0, min(tot, s * tot))
        for i in range(len(P) - 1):
            if L[i + 1] >= d:
                t = (d - L[i]) / max(1e-9, L[i + 1] - L[i])
                return P[i].lerp(P[i + 1], t), (P[i + 1] - P[i]).normalized()
        return P[-1], (P[-1] - P[-2]).normalized()

    rings = []
    u = None
    for s, r in stations:
        c, t = at(s)
        if u is None:
            ref = kit.Z if abs(t.z) < 0.9 else kit.X
            u = t.cross(ref).normalized()
        else:
            u = (u - t * u.dot(t)).normalized()
        w = t.cross(u)
        ring = []
        for i in range(seg):
            a = 2 * math.pi * (i + phase) / seg
            ring.append(tuple(c + r * (math.cos(a) * u + math.sin(a) * w)))
        rings.append(ring)
    return rings


# ----------------------------------------------------------------------------- the plenum
def build_plenum(b):
    # the main box, side profile (y, z) extruded along x; top sloping down to the front
    # (the hood's rear edge drops the limit to ~1.04 behind y 1.05: the rear face leans forward)
    # (its front is a lip over the skirt: the scallops open into a recess, back wall at y 1.175)
    prof = [(1.040, 0.925), (1.040, 0.995), (1.060, 1.028), (1.072, 1.035), (1.140, 1.035), (1.190, 1.020),
            (1.205, 1.005), (1.205, 0.988), (1.175, 0.988), (1.175, 0.925)]
    data = kit.prism_data(prof, "yz", PX0, PX1)
    b.add("plenum", data, ["AluCast", "DecalIntakePlenumTop"], sharp=40,
          face_mats=faces_facing(data, kit.Z, 0.45), bevel=0.005, segments=1)
    # the raised ribbed hump on the +x half, rear two thirds
    prof = [(1.064, 1.025), (1.064, 1.052), (1.077, 1.063), (1.110, 1.061), (1.134, 1.048), (1.140, 1.025)]
    data = kit.prism_data(prof, "yz", -0.045, PX1 - 0.006)
    b.add("plenum_hump", data, ["AluCast", "DecalIntakePlenumTop"], sharp=40,
          face_mats=faces_facing(data, kit.Z, 0.45))
    # the front skirt: two scallops, the big one the PCV hose comes through and a bolt notch at +x
    out = arch_outline(PX0 + 0.004, PX1 - 0.002, 0.946, 0.994,
                       [(-0.030, 0.020, 0.010), (0.052, 0.013, 0.006)], arc_pts=2)
    b.add("plenum_skirt", kit.prism_data(out, "xz", 1.196, 1.222), "AluCast", sharp=40)
    # lower manifold under the box, the runner stubs and the flange on the head
    b.box("plenum_lower", PX0 + 0.01, PX1 - 0.01, 1.050, 1.170, 0.872, 0.926, "AluCast")
    for k, x in enumerate((-0.240, -0.150, -0.060, 0.030)):          # engine.CYL_X
        x_top = max(x, PX0 + 0.02)
        b.cyl("runner_%d" % (k + 1), (x_top, 1.160, 0.922), (x, 1.229, 0.871), 0.017, "AluCast", seg=4)
    b.box("runner_flange", -0.300, 0.085, 1.220, 1.233, 0.848, 0.893, "AluCast")
    # I8: the booster's vacuum port on the -x rear, tip at (-0.22, 1.05, 0.95)
    b.cyl("vacuum_port_i8", (PX0 + 0.002, 1.050, 0.950), (-0.220, 1.050, 0.950), 0.006, "AluCast", seg=6)


def build_throttle(b):
    y, z = TB_C.y, TB_C.z
    # the neck from the box's +x end to the throttle body flange
    b.cyl("plenum_neck", (PX1 - 0.012, y, z), (TB_X0, y, z), 0.034, "AluCast", seg=8)
    b.box("tb_flange", TB_X0 - 0.004, TB_X0 + 0.006, y - 0.044, y + 0.044, z - 0.044, z + 0.044, "AluCast")
    # bore body with its inlet lip
    b.lathe("throttle_body", [(0.037, 0.0), (0.037, 0.050), (0.041, 0.053), (0.041, TB_X1 - TB_X0 - 0.006)],
            (TB_X0 + 0.006, y, z), (1, 0, 0), "AluCast", seg=8)
    # throttle cam / linkage on the front face, the cable bracket at I9
    # (2026-10-17, review BAY-8: a 6-sided bright steel disc read as a giant hex nut) the cam is a dull sector,
    # its arc on top where the cable wraps (the cable leaves it at ~60 degrees), the pivot at the centre
    cx, cz, cr = 0.176, z + 0.004, 0.028
    cam = [(cx, cz)] + [(cx + cr * math.cos(math.radians(a)), cz + cr * math.sin(math.radians(a)))
                        for a in (-15, 20, 55, 90, 125)]
    b.prism("throttle_cam", cam, "xz", y + 0.037, y + 0.045, "AluDull", sharp=40)
    b.box("cable_bracket", 0.168, 0.192, 1.054, 1.064, 0.958, 0.990, "Steel")
    # idle air control valve under the neck, its connector
    b.box("iacv", 0.098, 0.148, 1.112, 1.160, 0.902, 0.936, "AluCast")
    b.box("iacv_plug", 0.112, 0.136, 1.160, 1.176, 0.906, 0.928, "PlasticGrey")
    # throttle cable: cam, over the bore, through the bracket at I9, to the firewall (0.26, 0.995, 0.99)
    b.pipe("throttle_cable", [(0.192, y + 0.044, z + 0.030), (0.184, 1.090, 1.006), (0.180, 1.060, 0.980),
                              (0.260, 1.012, 0.990), (0.260, 0.9965, 0.990)],
           0.0035, "Rubber", sides=4, res=1)


def build_hoses(b):
    # PCV: out of the big scallop forward into the cam cover's rear
    b.pipe("pcv_hose", [(-0.030, 1.172, 0.962), (-0.030, 1.226, 0.958), (-0.030, 1.264, 0.948)],
           0.0075, "Rubber", sides=6, res=1)
    # purge / vacuum line: off the throttle body's rear, over to the firewall right of the cable
    b.pipe("vacuum_hose", [(0.152, 1.062, 0.930), (0.110, 1.020, 1.000), (0.090, 1.010, 1.004),
                           (0.090, 0.9975, 1.004)], 0.0055, "Rubber", sides=6, res=1)


# ----------------------------------------------------------------------------- duct and air box
def build_duct(b):
    ctrl = [(0.200, TB_C.y, TB_C.z), (0.262, 1.104, 0.960), (0.318, 1.150, 0.954), (0.348, 1.228, 0.942),
            (0.360, 1.300, 0.932), tuple(BOSS_C + BOSS_AX * 0.050)]
    R, Rb = 0.041, 0.048
    st = [(0.00, 0.046), (0.07, 0.046)]                     # the cuff over the throttle body's lip
    n_rib = 6
    a0, a1 = 0.22, 0.80
    for k in range(n_rib):
        s = a0 + (a1 - a0) * k / n_rib
        st += [(s, R), (s + (a1 - a0) / n_rib * 0.5, Rb)]
    st += [(a1, R), (0.92, 0.047), (1.00, 0.047)]
    b.add("intake_duct", kit.loft_data(path_rings(ctrl, st, seg=8)), "Rubber", sharp=70)


def build_airbox(b):
    # housing (lower half) and the lid's seam flange
    b.box("airbox_body", 0.306, 0.565, 1.346, 1.674, 0.800, 0.870, "Plastic",
          faces={"front": "DecalIntakeAirboxFront"})
    b.box("airbox_seam", 0.300, 0.569, 1.340, 1.680, 0.866, 0.878, "Plastic")
    # two-level lid: the long outboard section, the raised inboard front block, the low rear level
    prof = [(1.348, 0.876), (1.348, 0.916), (1.360, 0.922), (1.656, 0.904), (1.672, 0.895), (1.672, 0.876)]
    data = kit.prism_data(prof, "yz", 0.452, 0.563)
    fm = faces_facing(data, kit.Z, 0.5)
    fm.update({i: 2 for i in faces_facing(data, kit.Y, 0.7)})
    b.add("airbox_lid_out", data, ["Plastic", "DecalIntakeAirboxTop", "DecalIntakeAirboxFront"], sharp=40,
          face_mats=fm)
    prof = [(1.452, 0.876), (1.452, 0.930), (1.466, 0.942), (1.655, 0.940), (1.672, 0.928), (1.672, 0.876)]
    data = kit.prism_data(prof, "yz", 0.312, 0.446)
    fm = faces_facing(data, kit.Z, 0.5)
    fm.update({i: 2 for i in faces_facing(data, kit.Y, 0.7)})
    b.add("airbox_lid_in", data, ["Plastic", "DecalIntakeAirboxTop", "DecalIntakeAirboxFront"], sharp=40,
          face_mats=fm)
    b.box("airbox_lid_rear", 0.312, 0.450, 1.348, 1.454, 0.876, 0.902, "Plastic",
          faces={"top": "DecalIntakeAirboxTop"})
    # the duct boss on the rear inboard level
    b.lathe("airbox_boss", [(0.056, -0.006), (0.056, 0.018), (0.050, 0.040)],
            tuple(BOSS_C), tuple(BOSS_AX), "Plastic", seg=8)
    # spring clips: two on the front, two on the outboard side (dull zinc: bright steel read as stark light-grey
    # cubes, review BAY-14)
    for k, x in enumerate((0.360, 0.505)):
        b.box("airbox_clip_f%d" % (k + 1), x - 0.011, x + 0.011, 1.674, 1.6795, 0.852, 0.888, "AluDull")
    for k, y in enumerate((1.420, 1.600)):
        b.box("airbox_clip_s%d" % (k + 1), 0.565, 0.5695, y - 0.011, y + 0.011, 0.852, 0.888, "AluDull")
    # snorkel dropping out of the housing's front bottom, mouth facing forward
    prof = [(1.590, 0.802), (1.660, 0.802), (1.676, 0.770), (1.676, 0.722), (1.630, 0.722), (1.600, 0.750)]
    b.add("airbox_snorkel", kit.prism_data(prof, "yz", 0.330, 0.420), "Plastic", sharp=40)


def build(b):
    build_plenum(b)
    build_throttle(b)
    build_hoses(b)
    build_duct(b)
    build_airbox(b)
