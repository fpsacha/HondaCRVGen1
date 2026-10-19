"""Engine bay v2, group "engine" (spec/engine-bay-v2.md): the transverse B20B.

Block, oil pan, head, the black crinkle cam cover with its centre spine, plug wires and the loom clip,
the distributor at the +x end, the timing-belt covers, crank pulley, alternator and belt at the -x end,
transmission and bellhousing, exhaust manifold behind the big pressed heat shield with the dipstick
and its yellow loop, the thermostat housing with the two coolant necks (I3 / I4), the heater hoses to
the firewall and the upper engine mount. Model metres, +x the car's right, +y forward, +z up.

Detail is painted (paint_engine.py): the cast "HONDA MOTOR CO." and the cover bolts, the shield's
stamped ribs, hole and bolts.
"""
import math

from mathutils import Vector

from bay import kit

BUDGET = 1700
DECALS = {
    # the cover's front slope and flange: lettering, bolts, crinkle (painted mirrored: seen from +y)
    "DecalCoverFront": ("bay_engine_cover_front.png", ("x", -0.34, 0.13), ("z", 0.900, 0.978), "CoverBlack"),
    # the heat shield's front: stamped ribs, the sensor hole, bolts, heat tint (painted mirrored)
    "DecalShield": ("bay_engine_shield.png", ("x", -0.275, 0.085), ("z", 0.605, 0.900), "ShieldSteel"),
    # the upper timing cover's outboard (-x) face: moulded ribs and the bolt (u along y)
    "DecalTiming": ("bay_engine_timing.png", ("y", 1.26, 1.50), ("z", 0.60, 0.975), "Plastic"),
}

# cylinder centres along x (bore pitch ~9 cm), cylinder 1 at the timing end
CYL_X = (-0.240, -0.150, -0.060, 0.030)


# ----------------------------------------------------------------------------- helpers
def tube_data(pts, r, sides=4, phase=None, caps=True):
    """Closed tube along a polyline (parallel-transport frames): wires, hoses, the dipstick.
    r: one radius, or one per point (a wire swelling into its boot). caps=False leaves both ends open
    (only for ends buried inside another solid)."""
    P = [Vector(p) for p in pts]
    n = len(P)
    R = list(r) if isinstance(r, (list, tuple)) else [r] * n
    T = []
    for i in range(n):
        a, b = P[max(i - 1, 0)], P[min(i + 1, n - 1)]
        T.append((b - a).normalized())
    _ax, u, _w = kit.frame(T[0])
    phase = math.pi / sides if phase is None else phase
    v, f = [], []
    for i in range(n):
        t = T[i]
        u = (u - t * u.dot(t)).normalized()
        w = t.cross(u)
        # keep the section's width through a bend
        k = 1.0
        if 0 < i < n - 1:
            d0, d1 = (P[i] - P[i - 1]).normalized(), (P[i + 1] - P[i]).normalized()
            c = max(-1.0, min(1.0, d0.dot(d1)))
            k = 1.0 / max(0.5, math.cos(math.acos(c) / 2))
        for s in range(sides):
            a = phase + 2 * math.pi * s / sides
            v.append(tuple(P[i] + R[i] * (math.cos(a) * u * k + math.sin(a) * w)))
    for i in range(n - 1):
        for s in range(sides):
            s2 = (s + 1) % sides
            f.append((i * sides + s, i * sides + s2, (i + 1) * sides + s2, (i + 1) * sides + s))
    if caps:
        f.append(tuple(range(sides - 1, -1, -1)))
        f.append(tuple(range((n - 1) * sides, n * sides)))
    return v, f


def shrink(profile, d):
    """Pull a 2D outline toward its centroid by about d (the rounded end of an extrusion)."""
    cy = sum(p[0] for p in profile) / len(profile)
    cz = sum(p[1] for p in profile) / len(profile)
    out = []
    for y, z in profile:
        vy, vz = y - cy, z - cz
        ln = math.hypot(vy, vz) or 1.0
        k = max(0.0, 1.0 - d / ln)
        out.append((cy + vy * k, cz + vz * k))
    return out


def xloft(profile, stations):
    """A yz outline extruded along x through stations [(x, inset)]: an inset at an end rounds it.
    Returns (data, side_face_index(segment, point))."""
    rings = [[(x, y, z) for y, z in shrink(profile, d)] if d > 0 else [(x, y, z) for y, z in profile]
             for x, d in stations]
    m = len(profile)
    return kit.loft_data(rings), (lambda k, i: k * m + i)


def shell_data(rows, cols, thick):
    """A pressed sheet: rows of (z, x_left, x_right, y_centre, y_edge), top to bottom, `cols` points
    across with a forward bulge, offset back along its normal by `thick` into a closed solid.
    Returns (data, front face indices by row band)."""
    R = len(rows)
    F = []
    for z, xl, xr, yc, ye in rows:
        row = []
        for c in range(cols):
            t = c / (cols - 1)
            row.append(Vector((xl + (xr - xl) * t, ye + (yc - ye) * math.sin(math.pi * t), z)))
        F.append(row)
    B = []
    for r in range(R):
        brow = []
        for c in range(cols):
            dc = F[r][min(c + 1, cols - 1)] - F[r][max(c - 1, 0)]
            dr = F[min(r + 1, R - 1)][c] - F[max(r - 1, 0)][c]
            nrm = dc.cross(dr).normalized()
            if nrm.y < 0:
                nrm = -nrm
            brow.append(F[r][c] - nrm * thick)
        B.append(brow)
    v = [tuple(p) for row in F for p in row] + [tuple(p) for row in B for p in row]
    fi = lambda r, c: r * cols + c                       # noqa: E731
    bi = lambda r, c: R * cols + r * cols + c            # noqa: E731
    f, front = [], {}
    for r in range(R - 1):
        for c in range(cols - 1):
            front.setdefault(r, []).append(len(f))
            f.append((fi(r, c), fi(r, c + 1), fi(r + 1, c + 1), fi(r + 1, c)))
            f.append((bi(r, c), bi(r + 1, c), bi(r + 1, c + 1), bi(r, c + 1)))
    for c in range(cols - 1):
        f.append((fi(0, c), bi(0, c), bi(0, c + 1), fi(0, c + 1)))
        f.append((fi(R - 1, c), fi(R - 1, c + 1), bi(R - 1, c + 1), bi(R - 1, c)))
    for r in range(R - 1):
        f.append((fi(r, 0), fi(r + 1, 0), bi(r + 1, 0), bi(r, 0)))
        f.append((fi(r, cols - 1), bi(r, cols - 1), bi(r + 1, cols - 1), fi(r + 1, cols - 1)))
    return (v, f), front


# ----------------------------------------------------------------------------- parts
def build_bottom_end(b):
    # block: a yz section with the skirt pulled in, the full length of the head
    blk = [(1.250, 0.840), (1.472, 0.840), (1.482, 0.800), (1.470, 0.700), (1.450, 0.660),
           (1.272, 0.660), (1.252, 0.700), (1.240, 0.800)]
    b.prism("block", blk, "yz", -0.360, 0.140, "Iron")
    pan = [(1.285, 0.662), (1.445, 0.662), (1.432, 0.600), (1.405, 0.582), (1.305, 0.582)]
    b.prism("oil_pan", pan, "yz", -0.330, 0.105, "BlackPaint")
    # head: the bright band under the cover, a small lip at the front
    head = [(1.236, 0.840), (1.486, 0.840), (1.490, 0.868), (1.482, 0.902), (1.240, 0.902)]
    b.prism("head", head, "yz", -0.360, 0.140, "AluDull")


def build_cover(b):
    prof = [(1.468, 0.900), (1.471, 0.914), (1.461, 0.920), (1.455, 0.942), (1.445, 0.961),
            (1.429, 0.972), (1.411, 0.976), (1.399, 0.971), (1.393, 0.958), (1.336, 0.958),
            (1.330, 0.970), (1.312, 0.978), (1.291, 0.976), (1.273, 0.964), (1.263, 0.944),
            (1.257, 0.921), (1.250, 0.914), (1.252, 0.900)]
    data, idx = xloft(prof, [(-0.340, 0.007), (-0.332, 0.0), (0.122, 0.0), (0.130, 0.007)])
    fm = {idx(1, i): 1 for i in range(0, 6)}
    b.add("cover", data, ["CoverBlack", "DecalCoverFront"], sharp=40, face_mats=fm)
    # the raised centre spine the plug boots come out of
    b.box("cover_spine", -0.300, 0.092, 1.341, 1.366, 0.950, 0.969, "CoverBlack")
    for k, x in enumerate(CYL_X):
        b.cyl("plug_boot_%d" % (k + 1), (x, 1.3535, 0.966), (x, 1.3535, 0.981), 0.0095, "WireGrey", seg=6)
    # oil filler cap on the rear lobe, +x end
    b.lathe("oil_cap", [(0.024, 0.0), (0.024, 0.012), (0.019, 0.018), (0.0, 0.019)],
            (0.055, 1.300, 0.975), (0, 0, 1), "Plastic", seg=8)


# Plug wires (2026-10-17, review BAY-10): black and lying flat on the black cover they read as four short stubs.
# In lhd_06 / lhd_03 the LHD cars' wires are light grey and the most visible lines on the cover: they leave the
# boots up off the spine, run side by side over the cover's front flat in one flat bundle (the first cylinder's
# wire frontmost, so none cross), through the clip, and arc off the +x end down into the distributor cap.
# 2026-10-17 round 2 (R2-BAY-6: one flat grey ribbon with four hooked stubs ending flat on the cap's rim): four
# separate round wires (6 sides, a gap between lanes), each ending in a boot on the cap's end face. The B20B's cap
# faces +x (the distributor's axis is the camshaft's), its towers on the face round the rim: the wires leave the
# cover, arc over the cap and drop into boots that lean out from the face (lhd_06, the JDM photo).
WIRE_R = 0.0040
WIRE_LANES = (1.4035, 1.393, 1.3825, 1.372)          # bundle lane (y) of cylinder k's wire, front to rear
WIRE_LANE_Z = (0.9765, 0.9655, 0.9625, 0.9625)       # riding the flat (z 0.958) and the front lobe's slope
CAP_AXIS = (1.380, 0.875)                            # distributor cap axis (y, z); it runs along +x
TERM_R = 0.030                                       # towers on the cap's end face, this far off the axis
TERM_PHI = (40.0, 75.0, 110.0, 145.0)                # degrees from +y toward +z, cylinder 1 (front lane) first
BOOT_R, BOOT_LEN, BOOT_SINK = 0.0075, 0.020, 0.004
WIRE_OVER = ((0.940, 1.412), (0.950, 1.394), (0.950, 1.372), (0.942, 1.356))   # (z, y) over the cap at x 0.215


def wire_path(k):
    """(points, radii) of cylinder k's plug wire: from its boot on the spine forward into its bundle lane,
    along the cover past the clip, off the +x end over the cap, and down into its boot on the cap's end face
    (the last two points: the boot, swelling from the wire at the point before)."""
    x = CYL_X[k]
    lane, zl = WIRE_LANES[k], WIRE_LANE_Z[k]
    phi = math.radians(TERM_PHI[k])
    rad = Vector((0.0, math.cos(phi), math.sin(phi)))
    face = Vector((0.255 + 0.006 * (1.0 - TERM_R / 0.040), CAP_AXIS[0], CAP_AXIS[1])) + rad * TERM_R
    d = (Vector((0.35, 0.0, 0.0)) + rad * 0.937).normalized()   # the tower leans out from the face
    tip = face + d * BOOT_LEN
    zo, yo = WIRE_OVER[k]
    # from inside the spine boot (its top is z 0.981), sagging a little off the cover's end (M) before the cap
    pts = [(x, 1.3535, 0.975), (x + 0.024, lane, zl), (0.104, lane, zl),
           (0.160, 0.5 * (lane + yo), 0.5 * (zl + zo) - 0.004), (0.215, yo, zo),
           tuple(tip + d * 0.010), tuple(tip), tuple(face - d * BOOT_SINK)]
    return pts, [WIRE_R] * 6 + [BOOT_R] * 2


def build_ignition(b):
    for k in range(4):
        pts, radii = wire_path(k)
        # both ends are buried (the spine boot, the cap): no end caps. Four sides smooth-shaded (sharp 100: the
        # 90-degree edges stay smooth) read as the six-sided round wire at every zoom (2-5 px wide): 84 -> 56 tris
        # each (performance pass 2026-10-19)
        b.add("plug_wire_%d" % (k + 1), tube_data(pts, radii, 4, caps=False), "WireGrey", sharp=100)
    # the bundle clip straddles all four lanes
    b.box("loom_clip", 0.064, 0.077, 1.364, 1.410, 0.957, 0.982, "Steel")
    # distributor: grey housing out of the head's +x end, black cap
    b.lathe("distributor", [(0.036, 0.0), (0.036, 0.032), (0.044, 0.058)],
            (0.137, 1.380, 0.875), (1, 0, 0), "PlasticGrey", seg=10)
    b.lathe("distributor_cap", [(0.049, 0.0), (0.049, 0.040), (0.040, 0.060), (0.0, 0.066)],
            (0.195, 1.380, 0.875), (1, 0, 0), "Plastic", seg=10)


def build_timing_end(b):
    # upper cover: tall rounded black moulding at the head's -x end, rising past the cam cover
    up = [(1.268, 0.775), (1.495, 0.775), (1.498, 0.905), (1.486, 0.946), (1.455, 0.965),
          (1.380, 0.970), (1.310, 0.966), (1.282, 0.948), (1.266, 0.905)]
    data = kit.prism_data(up, "yz", -0.410, -0.360)
    # prism caps are faces 0 / 1: the -x one (face 0 at d0) carries the moulded-rib decal
    b.add("timing_cover_upper", data, ["Plastic", "DecalTiming"], sharp=40, face_mats={0: 1})
    lo = [(1.300, 0.600), (1.470, 0.600), (1.482, 0.640), (1.482, 0.775), (1.290, 0.775), (1.282, 0.640)]
    b.prism("timing_cover_lower", lo, "yz", -0.404, -0.360, "Plastic")
    # crank pulley, alternator and belt (one plane at x -0.428)
    # (against the left apron, under the mount: seg 12 / 10 / 10 -> 8, performance pass 2026-10-19)
    b.cyl("crank_pulley", (-0.442, 1.405, 0.650), (-0.411, 1.405, 0.650), 0.064, "Steel", seg=8)
    b.cyl("crank_hub", (-0.447, 1.405, 0.650), (-0.442, 1.405, 0.650), 0.024, "Iron", seg=6)
    b.cyl("alternator_pulley", (-0.440, 1.545, 0.785), (-0.414, 1.545, 0.785), 0.029, "Steel", seg=8)
    b.lathe("alternator", [(0.046, 0.0), (0.057, 0.012), (0.057, 0.088), (0.044, 0.106)],
            (-0.414, 1.545, 0.785), (1, 0, 0), "AluDull", seg=8)
    b.belt("alt_belt", [(Vector((-0.427, 1.405, 0.650)), 0.064), (Vector((-0.427, 1.545, 0.785)), 0.029)],
           width=0.016, thick=0.004, per=1)
    # upper engine mount: a bracket off the timing-end top, across the front of the left tower to
    # the frame bracket on the apron, with the rubber block in between
    b.box("mount_arm", -0.520, -0.385, 1.335, 1.359, 0.868, 0.890, "BlackPaint")
    b.box("mount_rubber", -0.548, -0.508, 1.335, 1.359, 0.852, 0.900, "Rubber")
    b.box("mount_bracket", -0.569, -0.548, 1.335, 1.359, 0.838, 0.905, "BlackPaint")


def build_exhaust(b):
    # manifold: a funnel of four runners merging into the downpipe, behind the shield
    man = [(-0.255, 0.868), (0.060, 0.868), (0.055, 0.800), (-0.020, 0.720), (-0.055, 0.660),
           (-0.145, 0.660), (-0.180, 0.720), (-0.250, 0.800)]
    b.prism("exhaust_manifold", man, "xz", 1.478, 1.535, "Iron")
    b.cyl("downpipe", (-0.100, 1.515, 0.668), (-0.100, 1.560, 0.575), 0.028, "Iron", seg=6)
    # the pressed heat shield: wide top across the head, stepping in to the lower tongue
    rows = [(0.893, -0.250, 0.060, 1.538, 1.534),
            (0.882, -0.262, 0.072, 1.566, 1.552),
            (0.800, -0.270, 0.080, 1.600, 1.558),
            (0.748, -0.222, 0.032, 1.604, 1.566),
            (0.690, -0.190, 0.000, 1.597, 1.565),
            (0.630, -0.168, -0.022, 1.574, 1.556),
            (0.612, -0.160, -0.030, 1.548, 1.542)]
    data, front = shell_data(rows, 5, 0.005)
    fm = {i: 1 for r in range(1, len(rows) - 1) for i in front[r]}
    b.add("heat_shield", data, ["ShieldSteel", "DecalShield"], sharp=45, face_mats=fm)
    # dipstick: tube up the front of the block behind the shield, the yellow loop on top
    b.add("dipstick_tube", tube_data([(-0.135, 1.478, 0.700), (-0.135, 1.520, 0.800),
                                      (-0.135, 1.541, 0.880), (-0.135, 1.546, 0.905)], 0.0055, 5), "Steel", sharp=80)
    b.torus("dipstick_loop", (-0.135, 1.550, 0.922), (0.0, 0.55, 0.84), 0.015, 0.0042, "CapYellow", seg=6, ring=3)


def build_transmission(b):
    # bellhousing flange then the long case under the air box
    b.lathe("bellhousing", [(0.112, 0.0), (0.112, 0.022), (0.094, 0.070)],
            (0.140, 1.330, 0.685), (1, 0, 0), "AluDull", seg=8)
    case = [(1.200, 0.602), (1.450, 0.602), (1.492, 0.640), (1.495, 0.735), (1.462, 0.780),
            (1.330, 0.785), (1.205, 0.780), (1.196, 0.700)]
    b.prism("transmission", case, "yz", 0.205, 0.398, "AluDull")
    # end cover of the case and the battery minus stud (I12)
    b.cyl("trans_end_cover", (0.398, 1.330, 0.690), (0.408, 1.330, 0.690), 0.075, "AluDull", seg=6)
    b.box("ground_stud", 0.292, 0.308, 1.204, 1.220, 0.770, 0.794, "Steel")


def build_cooling(b):
    # thermostat housing on the head's +x front, upper outlet neck I3
    b.box("thermostat_housing", 0.128, 0.208, 1.432, 1.482, 0.828, 0.888, "AluDull")
    b.cyl("upper_neck", (0.170, 1.478, 0.860), (0.170, 1.500, 0.860), 0.020, "AluDull", seg=6)
    # water inlet low on the +x end, lower neck I4
    b.box("water_inlet", 0.132, 0.204, 1.425, 1.452, 0.612, 0.668, "AluDull")
    b.cyl("lower_neck", (0.170, 1.450, 0.640), (0.170, 1.470, 0.640), 0.020, "AluDull", seg=6)
    # heater hoses: off the +x rear of the head / block, back under the throttle body to the firewall
    b.box("heater_outlet", 0.120, 0.160, 1.236, 1.255, 0.790, 0.875, "AluDull")
    # (mostly in the throttle body's shadow: four sides smooth-shaded, 56 -> 36 tris each, 2026-10-19)
    b.add("heater_hose_1", tube_data([(0.150, 1.245, 0.858), (0.180, 1.222, 0.858), (0.200, 1.140, 0.862),
                                      (0.180, 1.040, 0.870), (0.165, 1.000, 0.872)], 0.0095, 4), "Rubber", sharp=100)
    b.add("heater_hose_2", tube_data([(0.135, 1.245, 0.805), (0.170, 1.200, 0.808), (0.222, 1.110, 0.825),
                                      (0.228, 1.040, 0.838), (0.222, 1.000, 0.842)], 0.0095, 4), "Rubber", sharp=100)


def build(b):
    build_bottom_end(b)
    build_cover(b)
    build_ignition(b)
    build_timing_end(b)
    build_exhaust(b)
    build_transmission(b)
    build_cooling(b)
