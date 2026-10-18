"""Engine bay v2, group "sides" (spec/engine-bay-v2.md): everything round the edges of the bay.

LEFT REAR (-x, driver side): brake booster drum on the firewall, the master cylinder forward from it with
its translucent reservoir and black cap, two brake lines to the proportioning block, the fuse / relay box
outboard by the left tower (label decal on the lid). LEFT FRONT: power steering reservoir (red cap) and its
hose toward the engine, the washer filler neck (light blue cap). RIGHT REAR (+x): the battery on its tray
against the firewall (top and front label decals, red + boot), the hold-down bar with its J-bolt, the +
cable inboard and the - cable to the transmission (I12). BOTH TOWERS: strut mount plate (nut decal), rubber
puck and centre nut. FIREWALL: the harness loom along the top with its branch to the head (I11), the booster
vacuum hose from the plenum port (I8), and the hood hinge arms with their pins.

Layout from blender/references/engine_bay/web_lhd_bay lhd_03 / lhd_06 (LHD US cars). Mind the audit: the
towers are obstacles below z 0.97, so the mount plates start at 0.970 (8 mm over the tower top, read as a
shadow line); nothing goes behind y 0.995 (the firewall), so the hinge arms start at the firewall face.
"""
import math

from mathutils import Vector

from bay import kit

BUDGET = 1100

# The battery stands higher than the spec box (z 0.68..0.90): in lhd_03 / lhd_06 its lid is level with or
# above the strut mount and its front label shows over the tower; at 0.90 the tower hid it from every view.
BATT = dict(x0=0.340, x1=0.555, y0=1.003, y1=1.135, z0=0.760, z1=0.938)    # case body
LID = dict(x0=0.336, x1=0.559, y0=0.999, y1=1.139, z0=0.938, z1=0.956)     # lid (top decal)
FUSE_LID = dict(x0=-0.568, x1=-0.492, y0=1.002, y1=1.148, z0=0.961, z1=0.980)
TOWER_Z = 0.970          # mounts start here: envelope.audit treats the tower as solid below z 0.97
PLATE_R = 0.050

DECALS = {
    "DecalBattTop": ("bay_sides_battery_top.png", ("x", LID["x0"], LID["x1"]), ("y", LID["y0"], LID["y1"]), "Plastic"),
    "DecalBattFront": ("bay_sides_battery_front.png", ("x", BATT["x0"], BATT["x1"]), ("z", BATT["z0"], BATT["z1"]), "Plastic"),
    "DecalFuseLid": ("bay_sides_fuse_lid.png", ("x", FUSE_LID["x0"], FUSE_LID["x1"]), ("y", FUSE_LID["y0"], FUSE_LID["y1"]),
                     "Plastic"),
    "DecalTowerL": ("bay_sides_tower.png", ("x", -0.50 - PLATE_R, -0.50 + PLATE_R), ("y", 1.24 - PLATE_R, 1.24 + PLATE_R),
                    "BlackPaint"),
    "DecalTowerR": ("bay_sides_tower.png", ("x", 0.50 - PLATE_R, 0.50 + PLATE_R), ("y", 1.24 - PLATE_R, 1.24 + PLATE_R),
                    "BlackPaint"),
}


# ----------------------------------------------------------------------------- helpers
def tube_data(pts, r, sides=6, per=2, phase=None):
    """Closed tube through pts (Catmull-Rom, `per` samples per span; per 1 = the points themselves),
    parallel-transported rings, flat caps. Exactly (n-1)*sides*2 + 2*(sides-2) triangles for n rings."""
    P = [Vector(p) for p in pts]
    S = kit.catmull(P, per, closed=False) if per > 1 else P
    n = len(S)
    tang = []
    for i in range(n):
        a, b = S[max(i - 1, 0)], S[min(i + 1, n - 1)]
        tang.append((b - a).normalized())
    _ax, nrm, _w = kit.frame(tang[0])
    ph = (math.pi / sides) if phase is None else phase
    rings = []
    for i in range(n):
        t = tang[i]
        nrm = (nrm - t * nrm.dot(t)).normalized()
        bi = t.cross(nrm)
        ring = []
        for k in range(sides):
            a = ph + 2 * math.pi * k / sides
            ring.append(tuple(S[i] + r * (math.cos(a) * nrm + math.sin(a) * bi)))
        rings.append(ring)
    return kit.loft_data(rings, cap=True)


def tube(b, name, pts, r, mat, sides=6, per=2):
    return b.add(name, tube_data(pts, r, sides, per), mat, sharp=70)


def ngon(cx, cy, r, angles):
    return [(cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a))) for a in angles]


# ----------------------------------------------------------------------------- left rear
BOOSTER_C = Vector((-0.36, 0.996, 0.90))
MC_Z = 0.905
MC_X = -0.36


def build_brakes(b):
    # booster: tandem drum, rounded rear shell, flat front face; axis +y off the firewall
    b.lathe("brake_booster", [(0.070, 0.0), (0.104, 0.014), (0.119, 0.042), (0.117, 0.122), (0.092, 0.150)],
            BOOSTER_C, (0, 1, 0), "BlackPaint", seg=16, sharp=40)
    y_face = BOOSTER_C.y + 0.150
    # master cylinder: dull alloy body forward from the booster, reservoir on top, black cap
    b.cyl("master_cyl", (MC_X, y_face - 0.004, MC_Z), (MC_X, 1.229, MC_Z), 0.023, "AluDull", seg=8, r1=0.020)
    b.rbox("mc_reservoir", -0.390, -0.330, 1.150, 1.204, 0.925, 0.978, "Reservoir", bevel=0.007, segments=1)
    b.cyl("mc_reservoir_cap", (-0.360, 1.176, 0.976), (-0.360, 1.176, 0.996), 0.022, "Plastic", seg=8)
    # two steel lines from the cylinder's inboard ports back to the proportioning block on the firewall
    b.box("brake_prop_block", -0.250, -0.212, 0.997, 1.036, 0.792, 0.832, "AluDull")
    tube(b, "brake_line_1", [(MC_X + 0.020, 1.208, MC_Z + 0.004), (-0.300, 1.200, 0.884), (-0.243, 1.120, 0.848),
                             (-0.236, 1.036, 0.822)], 0.0032, "Steel", sides=4, per=1)
    tube(b, "brake_line_2", [(MC_X + 0.020, 1.176, MC_Z - 0.004), (-0.305, 1.168, 0.872), (-0.240, 1.095, 0.836),
                             (-0.224, 1.036, 0.806)], 0.0032, "Steel", sides=4, per=1)


def build_fuse_box(b):
    L = FUSE_LID
    b.box("fuse_box", L["x0"] + 0.004, L["x1"] - 0.004, L["y0"] + 0.004, L["y1"] - 0.004, 0.800, L["z0"], "Plastic")
    b.box("fuse_box_lid", L["x0"], L["x1"], L["y0"], L["y1"], L["z0"], L["z1"], "Plastic", faces={"top": "DecalFuseLid"})


# ----------------------------------------------------------------------------- left front
def build_left_front(b):
    # 2026-10-17 (review BAY-13): both stood so low by the apron that only their caps showed over the inner-fender
    # shelf (apron top ~0.94 at |x| 0.575): raised 3.5 cm and moved 1.3 cm inboard, under the hood limit (~0.97 /
    # ~0.93 there)
    c = Vector((-0.505, 1.505, 0.835))
    b.lathe("ps_reservoir", [(0.031, 0.0), (0.034, 0.050), (0.021, 0.068)], c, (0, 0, 1), "Reservoir", seg=8, sharp=50)
    b.cyl("ps_reservoir_cap", c + Vector((0, 0, 0.066)), c + Vector((0, 0, 0.082)), 0.024, "CapRed", seg=8)
    tube(b, "ps_hose", [(-0.481, 1.500, 0.847), (-0.459, 1.488, 0.806), (-0.448, 1.462, 0.752),
                        (-0.443, 1.430, 0.705)], 0.009, "Rubber", sides=6, per=1)
    # washer filler neck rising from the bottle below the shelf, light blue cap
    top = Vector((-0.527, 1.640, 0.893))
    b.cyl("washer_neck", (-0.535, 1.630, 0.705), top, 0.012, "Plastic", seg=6)
    b.cyl("washer_cap", top - Vector((0, 0, 0.004)), top + Vector((0, 0, 0.014)), 0.019, "CapBlue", seg=8)


# ----------------------------------------------------------------------------- right rear
def build_battery(b):
    B, L = BATT, LID
    b.box("battery_tray", B["x0"] - 0.010, B["x1"] + 0.010, 0.997, B["y1"] + 0.008, B["z0"] - 0.015, B["z0"], "BlackPaint")
    b.box("battery_tray_stay", 0.405, 0.495, 1.004, 1.110, 0.600, B["z0"] - 0.015, "BlackPaint")
    b.box("battery", B["x0"], B["x1"], B["y0"], B["y1"], B["z0"], B["z1"], "Plastic", faces={"front": "DecalBattFront"})
    b.box("battery_lid", L["x0"], L["x1"], L["y0"], L["y1"], L["z0"], L["z1"], "Plastic", faces={"top": "DecalBattTop"})
    zt = L["z1"]
    # + terminal: red boot over the post at the inboard rear corner, cable leaves inboard
    b.prism("battery_pos_boot", [(0.355, zt - 0.002), (0.398, zt - 0.002), (0.398, zt + 0.010), (0.389, zt + 0.024),
                                 (0.366, zt + 0.027), (0.352, zt + 0.014)], "xz", 1.012, 1.052, "CapRed", sharp=40)
    # - terminal: lead clamp on its post at the outboard rear corner
    b.box("battery_neg_clamp", 0.512, 0.538, 1.016, 1.046, zt - 0.002, zt + 0.014, "Steel")
    # hold-down: a bar across the lid front to back with the raised bracket, J-bolt down the front
    xh0, xh1 = 0.444, 0.462
    b.prism("battery_holddown", [(L["y0"] - 0.001, zt - 0.001), (L["y1"] + 0.004, zt - 0.001), (L["y1"] + 0.004, zt + 0.007),
                                 (1.092, zt + 0.007), (1.086, zt + 0.024), (1.054, zt + 0.024), (1.048, zt + 0.007),
                                 (L["y0"] - 0.001, zt + 0.007)], "yz", xh0, xh1, "BlackPaint", sharp=40)
    xj = 0.5 * (xh0 + xh1)
    # zinc-dull, not bright steel: the J-bolt tops read as stark light-grey cubes (review BAY-14)
    b.box("battery_jbolt", xj - 0.003, xj + 0.003, L["y1"] + 0.004, L["y1"] + 0.010, B["z0"] - 0.012, zt + 0.004, "AluDull")
    b.box("battery_jbolt_nut", xj - 0.007, xj + 0.007, L["y1"] - 0.006, L["y1"] + 0.012, zt + 0.007, zt + 0.016, "AluDull")
    b.box("battery_rear_nut", xj - 0.007, xj + 0.007, L["y0"], L["y0"] + 0.016, zt + 0.007, zt + 0.016, "AluDull")
    # cables: + inboard along the firewall and down to the starter; - over the lid and to the gearbox (I12)
    tube(b, "battery_pos_cable", [(0.362, 1.032, zt + 0.012), (0.322, 1.032, zt - 0.012), (0.282, 1.050, 0.840),
                                  (0.205, 1.150, 0.735)], 0.0085, "Rubber", sides=6, per=1)
    tube(b, "battery_neg_cable", [(0.525, 1.040, zt + 0.012), (0.470, 1.104, zt + 0.020), (0.388, 1.162, 0.885),
                                  (0.300, 1.200, 0.780)], 0.0070, "Rubber", sides=6, per=1)


# ----------------------------------------------------------------------------- towers
def build_tower_mounts(b):
    for side, (tx, ty) in (("L", (-0.50, 1.24)), ("R", (0.50, 1.24))):
        plate = ngon(tx, ty, PLATE_R, (65, 115, 185, 235, 305, 355))       # rounded triangle, a corner forward
        # the nut decal on the TOP cap only (prism face 1, at d1): cap_mat put it on the hidden bottom too (BAY-12)
        b.add("strut_plate_" + side, kit.prism_data(plate, "xy", TOWER_Z, TOWER_Z + 0.005),
              ["BlackPaint", "DecalTower" + side], sharp=30, face_mats={1: 1})
        z = TOWER_Z + 0.005
        b.cyl("strut_rubber_" + side, (tx, ty, z), (tx, ty, z + 0.017), 0.029, "Rubber", seg=8, r1=0.018)
        b.cyl("strut_nut_" + side, (tx, ty, z + 0.016), (tx, ty, z + 0.025), 0.0085, "Steel", seg=6)


# ----------------------------------------------------------------------------- firewall
def build_firewall(b):
    # harness loom: from the fuse box along the firewall top, over the booster's rear shoulder, to the
    # battery corner
    tube(b, "harness_loom", [(-0.505, 1.040, 0.955), (-0.468, 1.008, 0.993), (-0.365, 1.006, 1.004),
                             (-0.235, 1.007, 0.996), (0.120, 1.008, 0.988), (0.326, 1.012, 0.962)], 0.010, "Rubber",
         sides=6, per=1)
    # branch forward past the plenum's -x end to the head's rear (I11)
    tube(b, "harness_branch", [(-0.262, 1.008, 0.994), (-0.252, 1.150, 0.975), (-0.200, 1.234, 0.910),
                               (-0.050, 1.235, 0.900)], 0.0065, "Rubber", sides=6, per=1)
    # booster vacuum hose: plenum port (I8, facing -x) round the booster's inboard side into its front shell
    tube(b, "booster_vac_hose", [(-0.220, 1.050, 0.950), (-0.240, 1.056, 0.953), (-0.248, 1.152, 0.958),
                                 (-0.296, 1.140, 0.955)], 0.006, "Rubber", sides=6, per=1)
    # hood hinge arms: none here any more (2026-10-17, review BAY-9: static arms stayed put with the hood up,
    # pointing at empty air). The arms ride the hood: rig_vehicle.make_hood_riders builds a strap under each rear
    # corner on hood_bone, from the hood to the hinge axis at the cowl. The hinge bases are bay_walls.


def build(b):
    build_brakes(b)
    build_fuse_box(b)
    build_left_front(b)
    build_battery(b)
    build_tower_mounts(b)
    build_firewall(b)
