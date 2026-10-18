r"""
Engine bay v2, group "front" (spec/engine-bay-v2.md): the radiator stack across the nose, its hoses to
the engine, the coolant overflow bottle at the car's right front corner, the upper tie bar with the hood
latch, the hood bumpers, the prop rod and the horn.

Model metres, +x the car's RIGHT (LHD passenger side), +y forward, +z up. Read from lhd_03 (straight
from the bumper: the cap right of centre, the bottle at the right corner, the long lower hose across
the front of the heat shield dropping to the bottom tank at the left) and the web_jpc close-up of the
top tank, cap and bottle.

Fixed around it (bay_walls): the body-colour radiator support side panels at y 1.70-1.715 for
|x| 0.46-0.66 (z 0.60-0.88), and the dark (Dessous) header strips at y 1.870-1.885 (top z 0.861 since
round 2, just under the tie bar so the bar and latch show) and y 1.93; the headlamp housings outboard of
|x| 0.44. The hood limit falls to ~0.90 over the tie bar
and ~0.88 at its ends, so the tie bar's top is a shallow arch.
"""
import math

from mathutils import Vector

from bay import kit

BUDGET = 900

# ---------------------------------------------------------------- layout
CORE_X = 0.380                     # core half width (the tanks' end walls cover its edges)
TANK_X = 0.385                     # tank half width
RAD_Y0, RAD_Y1 = 1.785, 1.828      # tank rear (I5a / I5b faces) / front
CORE_Y0, CORE_Y1 = 1.795, 1.815
CORE_Z0, CORE_Z1 = 0.626, 0.830
TOP_Z0, TOP_Z1 = 0.826, 0.878      # top tank
BOT_Z0, BOT_Z1 = 0.565, 0.630      # bottom tank
CAP = Vector((0.180, 1.806, 0.876))  # filler neck foot on the top tank (right of centre)
CAP_TOP = 0.899
SHROUD_Y0, SHROUD_Y1 = 1.748, 1.785
SHROUD_Z0, SHROUD_Z1 = 0.640, 0.826
FAN_Y = 1.736
FAN_Z = 0.733
TIE_Y0, TIE_Y1 = 1.835, 1.868     # behind the body-colour header strip at y 1.870
TIE_Z0 = 0.858
# the tie bar's top, an arch under the hood limit: (x, z) from the right end to the centre
TIE_TOP = [(0.43, 0.872), (0.36, 0.889), (0.20, 0.896)]
BOTTLE_X0, BOTTLE_X1 = 0.395, 0.555
BOTTLE_Y0, BOTTLE_Y1 = 1.722, 1.800   # ahead of the support side panel (y 1.715), behind the lamp
BOTTLE_Z0, BOTTLE_Z1 = 0.728, 0.882   # its top clears the header and lamp walls (z 0.88) as in lhd_03
BOTTLE_NECK = Vector((0.432, 1.758, 0.878))

# interface points (spec "Interface points")
I3 = Vector((0.17, 1.50, 0.86))
I4 = Vector((0.17, 1.47, 0.64))
I5A = Vector((0.26, 1.785, 0.855))
I5B = Vector((-0.30, 1.785, 0.60))
HOSE_R = 0.020

DECALS = {
    "DecalRadFins": ("bay_front_fins.png", ("x", -CORE_X, CORE_X), ("z", CORE_Z0, CORE_Z1), "RadCore"),
    # the cap reads from the bumper: u runs toward -x, the image top is the rear
    "DecalRadCap": ("bay_front_cap.png", ("x", CAP.x + 0.021, CAP.x - 0.021), ("y", CAP.y + 0.021, CAP.y - 0.021), "Steel"),
    # the bottle's level marks are on its inboard (-x) wall, the face the bay views see; u runs toward -y
    "DecalCoolantBottle": ("bay_front_bottle.png", ("y", BOTTLE_Y1, BOTTLE_Y0), ("z", BOTTLE_Z0, BOTTLE_Z1), "Reservoir"),
    "DecalTieBar": ("bay_front_tiebar.png", ("x", 0.43, -0.43), ("y", TIE_Y1, TIE_Y0), "BlackPaint"),
}


# ---------------------------------------------------------------- helpers
def tie_top(x):
    """z of the tie bar's top at x (the arch in TIE_TOP, symmetric)."""
    ax = abs(x)
    pts = TIE_TOP[::-1]
    if ax <= pts[0][0]:
        return pts[0][1]
    for (x0, z0), (x1, z1) in zip(pts, pts[1:]):
        if x0 <= ax <= x1:
            return z0 + (z1 - z0) * (ax - x0) / (x1 - x0)
    return pts[-1][1]


def sweep_points(ctrl, per):
    """Catmull-Rom through ctrl with per[i] samples on span i (few on the straights, more on bends)."""
    P = [Vector(p) for p in ctrl]
    n = len(P)
    out = []
    for i in range(n - 1):
        p0, p1, p2, p3 = P[max(i - 1, 0)], P[i], P[i + 1], P[min(i + 2, n - 1)]
        for k in range(per[i]):
            t = k / per[i]
            out.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t
                              + (-p0 + 3 * p1 - 3 * p2 + p3) * t * t * t))
    out.append(P[-1])
    return out


def tube_data(pts, r, sides):
    """Closed tube through pts (ring per point, parallel-transported frame, flat caps): a hose whose
    segment count is exactly len(pts) - 1, so a straight run costs one segment."""
    P = [Vector(p) for p in pts]
    n = len(P)
    T = []
    for i in range(n):
        a, b = P[max(i - 1, 0)], P[min(i + 1, n - 1)]
        T.append((b - a).normalized())
    _ax, u, _w = kit.frame(T[0])
    rings = []
    for i in range(n):
        if i:
            u = T[i - 1].rotation_difference(T[i]) @ u
        t = T[i]
        u = (u - t * u.dot(t)).normalized()
        w = t.cross(u)
        rings.append([tuple(P[i] + r * (math.cos(2 * math.pi * k / sides) * u + math.sin(2 * math.pi * k / sides) * w))
                      for k in range(sides)])
    return kit.loft_data(rings)


def hose(b, name, ctrl, per, r, mat="Rubber", sides=6):
    return b.add(name, tube_data(sweep_points(ctrl, per), r, sides), mat, sharp=70)


def clamp(b, name, p, d, r=HOSE_R + 0.0035, length=0.012):
    """A band clamp around a hose end: a short 6-sided collar centred at p along direction d."""
    d = Vector(d).normalized() * (length / 2)
    return b.cyl(name, tuple(Vector(p) - d), tuple(Vector(p) + d), r, "Steel", seg=6)


# ---------------------------------------------------------------- parts
def radiator(b):
    # core: fins painted front and back
    b.box("rad_core", -CORE_X, CORE_X, CORE_Y0, CORE_Y1, CORE_Z0, CORE_Z1, "RadCore",
          faces={"front": "DecalRadFins", "rear": "DecalRadFins"})
    # top tank: a long black moulding, chamfered section (yz) along x
    top = [(RAD_Y0, TOP_Z0 + 0.004), (RAD_Y1 - 0.006, TOP_Z0), (RAD_Y1, TOP_Z0 + 0.008), (RAD_Y1, TOP_Z1 - 0.010),
           (RAD_Y1 - 0.010, TOP_Z1), (RAD_Y0 + 0.006, TOP_Z1), (RAD_Y0, TOP_Z1 - 0.004)]
    b.prism("rad_tank_top", top, "yz", -TANK_X, TANK_X, "Plastic", sharp=40)
    # bottom tank
    bot = [(RAD_Y0, BOT_Z0 + 0.008), (RAD_Y0 + 0.008, BOT_Z0), (RAD_Y1 - 0.008, BOT_Z0), (RAD_Y1, BOT_Z0 + 0.008),
           (RAD_Y1, BOT_Z1), (RAD_Y0, BOT_Z1)]
    b.prism("rad_tank_bottom", bot, "yz", -TANK_X, TANK_X, "Plastic", sharp=40)
    # filler neck and the cap: pressed steel with the warning label on its flat top (decal)
    b.cyl("rad_filler_neck", (CAP.x, CAP.y, TOP_Z1 - 0.004), (CAP.x, CAP.y, CAP_TOP - 0.010), 0.015, "Steel", seg=6)
    b.cyl("rad_overflow_nipple", (CAP.x + 0.012, CAP.y, 0.885), (CAP.x + 0.032, CAP.y, 0.885), 0.0045, "Steel", seg=4)
    prof = [(0.025, 0.0), (0.025, 0.005), (0.019, 0.011)]
    v, f = kit.lathe_data(prof, (CAP.x, CAP.y, CAP_TOP - 0.011), (0, 0, 1), 10)
    b.add("rad_cap", (v, f), ["Steel", "DecalRadCap"], sharp=50, face_mats={len(f) - 1: 1})


def fans(b):
    # two shrouds on the back of the core, each with a 4-blade fan and its motor toward the engine
    for side, s in (("l", -1), ("r", 1)):
        xa, xb = sorted((s * 0.012, s * 0.375))
        b.box("fan_shroud_" + side, xa, xb, SHROUD_Y0, SHROUD_Y1, SHROUD_Z0, SHROUD_Z1, "Plastic")
        cx = s * 0.192
        b.fan("fan_blades_" + side, (cx, FAN_Y, FAN_Z), (0, 1, 0), 0.034, 0.086, 4, "Plastic",
              w_root=0.040, w_tip=0.060, pitch=0.45)
        b.cyl("fan_motor_" + side, (cx, FAN_Y + 0.004, FAN_Z), (cx, 1.700, FAN_Z), 0.038, "BlackPaint", seg=6)


def hoses(b):
    # upper: thermostat outlet (I3) forward to the top tank (I5a); x < 0.29 until y > 1.68 (the air box)
    hose(b, "hose_upper", [I3, I3 + Vector((0, 0.045, 0.002)), (0.215, 1.640, 0.866), (0.257, 1.738, 0.857), I5A],
         [1, 1, 2, 1], HOSE_R)
    clamp(b, "hose_upper_clamp_e", I3 + Vector((0, 0.014, 0)), (0, 1, 0))
    clamp(b, "hose_upper_clamp_r", I5A + Vector((0, -0.014, 0)), (0, 1, 0))
    # lower: from the lower neck (I4) forward past the transmission, up across the front of the heat
    # shield, then down the left side and under the left shroud into the bottom tank (I5b), as lhd_03
    hose(b, "hose_lower", [I4, I4 + Vector((0, 0.06, 0.004)), (0.140, 1.632, 0.760), (0.030, 1.664, 0.845),
                           (-0.225, 1.668, 0.845), (-0.300, 1.690, 0.725), (-0.300, 1.735, 0.608), I5B],
         [1, 2, 2, 1, 2, 1, 1], HOSE_R)
    clamp(b, "hose_lower_clamp_r", I5B + Vector((0, -0.014, 0)), (0, 1, 0))


def bottle(b):
    # side outline (x, z): square-ish, the shoulder rounded down toward the outboard corner (CCW)
    out = [(BOTTLE_X0, BOTTLE_Z0), (BOTTLE_X1 - 0.010, BOTTLE_Z0), (BOTTLE_X1, BOTTLE_Z0 + 0.014),
           (BOTTLE_X1, BOTTLE_Z1 - 0.042), (BOTTLE_X1 - 0.025, BOTTLE_Z1 - 0.014), (0.475, BOTTLE_Z1),
           (BOTTLE_X0 + 0.012, BOTTLE_Z1), (BOTTLE_X0, BOTTLE_Z1 - 0.014)]
    # prism faces: 0, 1 the caps, 2 + i the side on edge i; edge 7 is the inboard wall (level marks)
    b.add("coolant_bottle", kit.prism_data(out, "xz", BOTTLE_Y0, BOTTLE_Y1), ["Reservoir", "DecalCoolantBottle"],
          sharp=40, face_mats={9: 1})
    n = BOTTLE_NECK
    b.cyl("coolant_bottle_neck", (n.x, n.y, n.z - 0.004), (n.x, n.y, n.z + 0.010), 0.016, "Reservoir", seg=6)
    b.cyl("coolant_bottle_cap", (n.x, n.y, n.z + 0.008), (n.x, n.y, n.z + 0.024), 0.021, "Plastic", seg=8)
    # overflow hose: from the cap's side, arcing over the top tank to the nipple on the filler neck
    hose(b, "coolant_overflow_hose", [(n.x - 0.020, n.y, n.z + 0.016), (0.380, 1.775, 0.898), (0.300, 1.796, 0.895),
                                      (CAP.x + 0.030, CAP.y, 0.885)], [2, 2, 1], 0.0045, sides=4)


def tie_bar(b):
    # the black upper tie bar behind the header (an arch under the hood limit), the latch on it,
    # rubber hood stops on its ends, the prop rod stowed along its top
    arch = [(-0.43, TIE_Z0), (0.43, TIE_Z0)] + [(x, z) for x, z in TIE_TOP] + [(-x, z) for x, z in TIE_TOP[::-1]]
    # outline is CCW in (x, z); faces 2 + i for edges 2..6 are the top: the decal
    b.add("tie_bar", kit.prism_data(arch, "xz", TIE_Y0, TIE_Y1), ["BlackPaint", "DecalTieBar"],
          face_mats={4: 1, 5: 1, 6: 1, 7: 1, 8: 1})
    # hood latch: base plate and the jaw casting (outline seen from the front)
    zt = tie_top(0.0)
    b.box("latch_base", -0.065, 0.065, TIE_Y0 + 0.002, TIE_Y1 - 0.001, zt - 0.002, zt + 0.004, "Steel")
    jaw = [(-0.040, zt), (0.040, zt), (0.040, 0.903), (0.012, 0.911), (0.006, 0.903), (-0.006, 0.903),
           (-0.012, 0.911), (-0.040, 0.903)]
    b.prism("latch_jaw", jaw, "xz", TIE_Y0 + 0.008, TIE_Y1 - 0.006, "AluDull")
    for side, s in (("l", -1), ("r", 1)):
        x = s * 0.405
        b.cyl("hood_bumper_" + side, (x, 1.852, tie_top(x) - 0.002), (x, 1.852, 0.889), 0.014, "Rubber", seg=6)   # 0.892 sat 1 mm into the pad zone under the low hood
    # prop rod: only its pivot bracket at the bar's left end and the clip it rests in stay here. The rod itself
    # moves (2026-10-17, review OPEN-7): rig_vehicle.make_hood_riders builds it at export on its own bone, joined
    # into the hood, lying on the bar's top rear edge (y TIE_Y0 + 0.007, z tie top + r) with its bent end dropping
    # into this bracket at the bar's left end (rig_vehicle.PROP_PIVOT (-0.428, TIE_Y0 + 0.007, 0.880)), and
    # swinging up into the hood's slot. The bracket's top stays under the hood limit there (~0.885).
    y, r = TIE_Y0 + 0.007, 0.0045
    z = tie_top(0.0) + r
    b.box("prop_rod_pivot", -0.437, -0.419, TIE_Y0 + 0.001, TIE_Y0 + 0.014, tie_top(-0.43) - 0.012, 0.883, "BlackPaint")
    b.box("prop_rod_clip", 0.165, 0.177, TIE_Y0, TIE_Y0 + 0.016, zt - 0.002, z - r + 0.002, "Plastic")


def horn(b):
    # disc horn at the car's left front corner, facing forward, on a strap bracket
    c = Vector((-0.440, 1.790, 0.770))
    b.cyl("horn", (c.x, c.y - 0.012, c.z), (c.x, c.y + 0.012, c.z), 0.030, "BlackPaint", seg=8, r1=0.043)
    b.box("horn_bracket", c.x - 0.008, c.x + 0.008, c.y - 0.018, c.y - 0.012, c.z, 0.845, "Steel")


def build(b):
    radiator(b)
    fans(b)
    hoses(b)
    bottle(b)
    tie_bar(b)
    horn(b)
