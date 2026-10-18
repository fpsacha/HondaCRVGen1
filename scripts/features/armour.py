r"""
Survival armour for the CR-V (spec/feature-roadmap.md "Survival armour", spec/feature-plugins.md).

Bare welded steel, built from the car's own panels (scripts/features/_armour_build.py has the
geometry and why each piece looks the way it does):
  * door plates   CRVArmourDoor<FrontLeft|...>  children of Door*, ride the door bones (shell sheet)
  * arch guards   CRVArmourArch<FrontLeft|...>  static steel bands round the wheel openings (shell)
  * window mesh   a SECOND item + model on each door window guard part (CRVGuardFrontLeft ...): the
                  window takes the bar grille OR the expanded-metal mesh (GUARD_VARIANTS below, read
                  by gen_scripts.accessory_parts; the Lua shows the model of the installed item)
  * rear plate    a second item + model on CRVGuardWindshieldRear (bars OR the plate with a slot),
                  riding trunkglass_bone like the bar guard

Protection (Lua, server side): every armour part registers with HondaCRVGen1.Acc (COVERS / WEAR /
FLOOR / Init): the door plate keeps its door's condition; the arch guard (the only bodywork at its
wheel, so zombies there thump it) absorbs its own thumps and its tyre's hits, never the tyre's driving
wear; the mesh and the rear plate keep their glass and hold weakened glass above a burst of thumps.
The armour wears through a fractional accumulator scaled by the ArmourStrength sandbox option (VERY
strong at 1). Armoured windows cannot be opened (the glass must stay up for the game to keep zombies'
arms out: AttackVehicleState only bites through a missing, broken or open window or an open door), and
a door with its plate on cannot be taken off. Everything bolts on with a wrench and a screwdriver
(the mesh and the rear plate share the window guard parts' tables: gen_scripts gives those both tools).
Weight: the items' Weight goes into BaseVehicle.updateTotalMass (heavier = slower, harder to stop).
Sources: crafted (Metalworking + Mechanics, recipes learned from the "Survival Armour" magazine),
rare loot (garages, mechanics, military, police).
"""
import math
import os

KEY = "armour"
DOORS = [("fl", "FrontLeft", "SeatFrontLeft", "Front"), ("fr", "FrontRight", "SeatFrontRight", "Front"),
         ("rl", "RearLeft", "SeatRearLeft", "Rear"), ("rr", "RearRight", "SeatRearRight", "Rear")]
ARCH_AREA = {"fl": "TireFrontLeft", "fr": "TireFrontRight", "rl": "TireRearLeft", "rr": "TireRearRight"}
LUA_NS = "HondaCRVGen1.Armour"

# ---------------------------------------------------------------------------------------------
# geometry


def BUILD(report):
    import importlib
    import sys
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    mod = importlib.import_module("features._armour_build")
    mod.build(report)


OBJECTS = {}
for _t, _p, _a, _fr in DOORS:
    OBJECTS["acc_armour_door_" + _t] = {"space": "shell", "bone": "door_%s_bone" % _t, "zone": "door_" + _t, "texel_w": True}
    OBJECTS["acc_armour_mesh_" + _t] = {"space": "shell", "bone": "door_%s_bone" % _t, "zone": "door_" + _t, "texel_w": True}
    # static: dents and greys with the fender / quarter it is bolted to (bake_atlas zone guard_<f|r><l|r>)
    OBJECTS["acc_armour_arch_" + _t] = {"space": "shell", "zone": "guard_" + _t, "texel_w": True}
OBJECTS["acc_armour_rear_plate"] = {"space": "shell", "bone": "trunkglass_bone", "zone": "body", "texel_w": True}

# ---------------------------------------------------------------------------------------------
# bake: bare hot-rolled steel (metal plate grain, a dark mill-scale grey a step under the light
# paints: silver / white / gold must not swallow it), a large mottle, rust and grime from painted maps
# (BAKE_PAINT) placed where steel rusts first (round every bolt and running down from it, along the
# plates' bottom edges, at their corners), the pieces' own occlusion (acc_shade: removables are
# invisible to the bake's rays). Bolt heads, the expanded-metal strands and the weld beads are a few
# screen pixels wide at the game's zoom: flat swatch cells (BAKE_SWATCH_MATS), no charts of their own.
RUST_PNG = "armour_rust.png"
RUST_BACK_PNG = "armour_rust_back.png"
RUST_SIDE = (("y", -2.45, 2.45), ("z", 0.15, 1.85))       # the side plates and arches, both sides
RUST_BACK = (("x", -0.80, 0.80), ("z", 0.95, 1.75))       # the rear plate
RUST_PX_CM = 2.0                                          # both maps: 2 px per cm


def _steel(tint, grain, rust=True):
    layers = [("box", "metal_plate_02_diffuse_1k.jpg", 0.30, tint, grain), ("noise", 6.0, 0.14), ("noise", 70.0, 0.06)]
    if rust:   # "over": rust is lighter and warmer than dark mill scale, a multiply could only darken it
        layers += [("decal", RUST_PNG, RUST_SIDE[0], RUST_SIDE[1], "over", [("normal", "x", ">", 0.45)]),
                   ("decal", RUST_PNG, RUST_SIDE[0], RUST_SIDE[1], "over", [("normal", "x", "<", -0.45)]),
                   ("decal", RUST_BACK_PNG, RUST_BACK[0], RUST_BACK[1], "over", [("normal", "y", "<", -0.45)])]
    return layers + [("attr", "acc_shade")]


# the box layer multiplies the tint by the grain (mean ~0.40 at flat 0.35): plate ~0.068 linear, sRGB ~73
# before rust and occlusion (2026-10-13; 0.36 gave sRGB ~105, the value of the lit silver and white panels)
BAKE_TEXTURED = {
    "AccArmourPlate": _steel((0.17, 0.17, 0.18), 0.35),
    "AccArmourBolt": _steel((0.10, 0.10, 0.105), 0.45, rust=False),
    "AccArmourMesh": _steel((0.14, 0.14, 0.145), 0.45),
    "AccArmourWeld": [("box", "metal_plate_02_diffuse_1k.jpg", 0.30, (0.085, 0.068, 0.052), 0.55), ("attr", "acc_shade")],
}
BAKE_MAT_WEIGHTS = {"AccArmourPlate": 0.5, "AccArmourBolt": 0.5, "AccArmourMesh": 0.5, "AccArmourWeld": 0.5}
BAKE_SWATCH_MATS = {"AccArmourBolt", "AccArmourMesh", "AccArmourWeld"}


def _rust_points(bpy):
    """Where the armour rusts, read from the built meshes (rest pose, model metres): bolt centres and
    every plate's outline box, per projection. Returns {"side": (bolts [(y, z)], boxes), "back": ...}."""
    out = {"side": ([], []), "back": ([], [])}
    for ob in bpy.data.objects:
        if not ob.name.startswith("acc_armour_") or ob.type != 'MESH' or ob.name.startswith("acc_armour_mesh_"):
            continue
        me = ob.data
        names = [m.name if m else "?" for m in me.materials]
        mw = ob.matrix_world
        back = ob.name == "acc_armour_rear_plate"
        bolts, boxes = out["back" if back else "side"]

        def uv(co):
            c = mw @ co
            return (c.x, c.z) if back else (c.y, c.z)
        plate = []
        parent = {}

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i
        for p in me.polygons:
            n = names[p.material_index] if p.material_index < len(names) else "?"
            if n == "AccArmourBolt":                     # bolt heads (12 vertices each) and stand-off tabs (8)
                vs = list(p.vertices)
                for i in vs:
                    parent.setdefault(i, i)
                for i in vs[1:]:
                    a, b = find(vs[0]), find(i)
                    if a != b:
                        parent[b] = a
            elif n == "AccArmourPlate":
                plate.append(uv(p.center))
        comps = {}
        for i in parent:
            comps.setdefault(find(i), []).append(i)
        for vs in comps.values():
            if len(vs) == 12:
                pts = [uv(me.vertices[i].co) for i in vs]
                bolts.append((sum(q[0] for q in pts) / 12.0, sum(q[1] for q in pts) / 12.0))
        if plate:
            us, vs_ = [q[0] for q in plate], [q[1] for q in plate]
            boxes.append((min(us), min(vs_), max(us), max(vs_), "arch" in ob.name))
    return out


def _paint_rust(np, W, H, box, bolts, boxes, seed):
    """A rust strength map (0..1, rows from the bottom) over box ((axis, lo, hi), (axis, lo, hi))."""
    rng = np.random.default_rng(seed)
    (_a, u0, u1), (_b, v0, v1) = box
    sx, sy = W / (u1 - u0), H / (v1 - v0)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float64)
    acc = np.zeros((H, W))

    def px(u, v):
        return (u - u0) * sx, (v - v0) * sy

    def disc(x0, y0, r, s):
        r = max(r, 0.8)
        x_lo, x_hi = int(max(0, x0 - r - 1)), int(min(W, x0 + r + 2))
        y_lo, y_hi = int(max(0, y0 - r - 1)), int(min(H, y0 + r + 2))
        if x_lo >= x_hi or y_lo >= y_hi:
            return
        d = np.hypot(xx[y_lo:y_hi, x_lo:x_hi] - x0, yy[y_lo:y_hi, x_lo:x_hi] - y0) / r
        a = acc[y_lo:y_hi, x_lo:x_hi]
        np.maximum(a, s * np.clip(1.0 - d * d, 0.0, 1.0), out=a)

    def streak(x0, y0, length, width, s):
        """running down from (x0, y0): the image's y grows upward"""
        n = int(length)
        wob = rng.uniform(0, 6.28)
        for k in range(n):
            f = s * (1.0 - k / max(n, 1)) ** 1.3
            disc(x0 + 0.6 * math.sin(k * 0.25 + wob), y0 - k, width / 2.0, f)

    cm = RUST_PX_CM
    # round every bolt (the plating's first rust) and a run down from most of them
    for u, v in bolts:
        x, y = px(u, v)
        if rng.random() < 0.85:
            disc(x, y, rng.uniform(2.2, 4.2) * cm, rng.uniform(0.60, 0.95))
        if rng.random() < 0.6:
            streak(x, y - 1.5 * cm, rng.uniform(6, 20) * cm, rng.uniform(1.6, 2.6) * cm, rng.uniform(0.40, 0.75))
    # every plate: grime and rust along the bottom edge, patches at the corners, a few runs off the bottom
    for bu0, bv0, bu1, bv1, arch in boxes:
        xa, ya = px(bu0, bv0)
        xb, yb = px(bu1, bv1)
        if not arch:
            band = rng.uniform(6, 11) * cm
            xs = np.arange(int(max(0, xa)), int(min(W, xb + 1)))
            if len(xs):
                k = np.cumsum(rng.normal(0, 1, len(xs)))
                k = (k - k.min()) / max(1e-6, k.max() - k.min())
                for x, kk in zip(xs, k):
                    h = band * (0.5 + 0.7 * kk)
                    y_lo, y_hi = int(max(0, ya - 2)), int(min(H, ya + h))
                    t = (yy[y_lo:y_hi, x] - ya) / max(h, 1.0)
                    col = acc[y_lo:y_hi, x]
                    np.maximum(col, (0.45 + 0.35 * kk) * np.clip(1.0 - t, 0.0, 1.0) ** 1.2, out=col)
            for cx, cy in ((xa, ya), (xb, ya), (xa, yb), (xb, yb)):
                low = cy == ya
                for _k in range(rng.integers(2, 5)):
                    disc(cx + rng.normal(0, 2.0 * cm) * (1 if cx == xa else -1) + (2 * cm if cx == xa else -2 * cm),
                         cy + (2 * cm if low else -2 * cm) + rng.normal(0, 1.5 * cm),
                         rng.uniform(2.5, 5.0 if low else 3.5) * cm, rng.uniform(0.45, 0.85 if low else 0.60))
        else:
            for x in (xa, xb):                                     # the band's ends, low on the arch
                disc(x, ya + 2 * cm, rng.uniform(3.0, 4.5) * cm, rng.uniform(0.50, 0.80))
        for _k in range(rng.integers(3, 7)):                       # runs off the bottom edge and scattered spots
            x = rng.uniform(xa + 3 * cm, max(xa + 3 * cm, xb - 3 * cm))
            streak(x, ya + 1 * cm, rng.uniform(3, 10) * cm, rng.uniform(1.4, 2.2) * cm, rng.uniform(0.35, 0.60))
        for _k in range(rng.integers(4, 9)):
            disc(rng.uniform(xa, xb), rng.uniform(ya, yb), rng.uniform(2.5, 6.0) * cm, rng.uniform(0.20, 0.45))
    return np.clip(acc, 0.0, 1.0)


def BAKE_PAINT(decal_dir):
    """armour_rust.png (the side plates and arches, RUST_SIDE) and armour_rust_back.png (the rear plate,
    RUST_BACK): rust laid "over" the steel (colour, alpha = how much rust; 2 px per cm) where steel rusts
    first, read from the built armour: a bloom round every bolt and a run down from most of them, rust
    and grime along each plate's bottom edge, patches at its corners. Its tone wanders between dark
    brown and orange. Our own procedural paint (seeded: every build the same)."""
    import bpy
    import numpy as np
    # a byte image's pixels are written as they are stored (sRGB): the bake reads them back as linear
    dark, orange = np.array((80, 46, 28)) / 255.0, np.array((150, 82, 40)) / 255.0
    pts = _rust_points(bpy)
    paths = []
    for key, png, box, seed in (("side", RUST_PNG, RUST_SIDE, 1997), ("back", RUST_BACK_PNG, RUST_BACK, 1998)):
        (_a, u0, u1), (_b, v0, v1) = box
        W, H = int(round((u1 - u0) * 100 * RUST_PX_CM)), int(round((v1 - v0) * 100 * RUST_PX_CM))
        a = _paint_rust(np, W, H, box, pts[key][0], pts[key][1], seed)
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float64)
        coarse = np.random.default_rng(seed + 5).random((H // 8 + 2, W // 8 + 2))     # value noise, 4 cm cells
        fy, fx = yy / 8.0, xx / 8.0
        iy, ix = fy.astype(np.int64), fx.astype(np.int64)
        ty, tx = fy - iy, fx - ix
        ty, tx = ty * ty * (3 - 2 * ty), tx * tx * (3 - 2 * tx)
        vn = (coarse[iy, ix] * (1 - tx) + coarse[iy, ix + 1] * tx) * (1 - ty) + (coarse[iy + 1, ix] * (1 - tx) + coarse[iy + 1, ix + 1] * tx) * ty
        tone = np.clip(0.15 + 0.85 * vn + 0.25 * (a - 0.5), 0.0, 1.0)
        px = np.zeros((H, W, 4))
        px[..., :3] = dark[None, None, :] + (orange - dark)[None, None, :] * tone[..., None]
        px[..., 3] = np.clip(a * 0.95, 0.0, 0.92)
        img = bpy.data.images.new(png[:-4], W, H, alpha=True)
        img.pixels.foreach_set(px.astype(np.float32).ravel())
        path = os.path.join(decal_dir, png)
        img.filepath_raw = path
        img.file_format = 'PNG'
        img.save()
        bpy.data.images.remove(img)
        paths.append(path)
    return paths


# ---------------------------------------------------------------------------------------------
# items, icons, mechanics overlay

ITEMS_SPEC = [
    # item, weight (kg: updateTotalMass adds it to the car), English name, icon mesh, azimuth, elevation
    ("CRVGen1_ArmourDoorFront", 22.0, "CRV Front Door Armour Plate", "acc_armour_door_fr", 0.0, 10.0),
    ("CRVGen1_ArmourDoorRear", 19.0, "CRV Rear Door Armour Plate", "acc_armour_door_rr", 0.0, 10.0),
    ("CRVGen1_ArmourArchFront", 6.0, "CRV Front Wheel Arch Guard", "acc_armour_arch_fr", 0.0, 10.0),
    ("CRVGen1_ArmourArchRear", 4.5, "CRV Rear Wheel Arch Guard", "acc_armour_arch_rr", 0.0, 10.0),
    ("CRVGen1_ArmourMeshFront", 9.0, "CRV Front Window Armour Mesh", "acc_armour_mesh_fr", 0.0, 8.0),
    ("CRVGen1_ArmourMeshRear", 8.0, "CRV Rear Window Armour Mesh", "acc_armour_mesh_rr", 0.0, 8.0),
    ("CRVGen1_ArmourRearPlate", 16.0, "CRV Rear Glass Armour Plate", "acc_armour_rear_plate", 270.0, 22.0),
]
MAGAZINE = "CRVGen1_ArmourMagazine"
RECIPE_OF = {item: "CRVGen1_Make" + item[len("CRVGen1_"):] for item, *_r in ITEMS_SPEC}

ITEMS = {}
for _item, _w, _name, _o, _az, _el in ITEMS_SPEC:
    ITEMS[_item] = {"DisplayCategory": "VehicleMaintenance", "Weight": _w, "ItemType": "base:normal",
                    "DisplayName": _name, "Icon": _item, "ConditionMax": 100, "ChanceToSpawnDamaged": 20,
                    "MechanicsItem": True, "Tags": "base:hasmetal"}
ITEMS[MAGAZINE] = {"DisplayCategory": "RecipeResource", "ItemType": "base:literature", "Weight": 0.5,
                   "DisplayName": "Survival Armour: Steel for Your CRV", "Icon": MAGAZINE,
                   "BoredomChange": -20, "StressChange": -15,
                   "LearnedRecipes": ";".join(RECIPE_OF[i] for i, *_r in ITEMS_SPEC),
                   "Tooltip": "Tooltip_CRV_Armour_Magazine", "StaticModel": "Magazine",
                   "WorldStaticModel": "MagazineMec1Ground", "Tags": "base:magazine",
                   "OnCreate": "ItemCodeOnCreate.onCreateRecipeMagazine"}   # literatureTitle: re-reads go on cooldown

# inventory icons (gen_icons): plates and guards in a 3/4 view (face-on they read as blank cards); the
# window meshes through gen_icons' big-diamond stand-in (their real 14 cm diamonds fill in at 32 px)
ICON_VIEW = {"door": (25.0, 22.0), "arch": (18.0, 20.0), "mesh": (22.0, 20.0)}
ICONS = {item: ((lambda ic, o=obj: ic.lattice_panel(o)) if "_mesh_" in obj else obj,
                *ICON_VIEW.get(obj.split("_")[2], (az, el))) for item, _w, _n, obj, az, el in ITEMS_SPEC}

# the overlay's top band (compose_overlays.TOP_BAND, full width, under the window's title bar; the armour
# feature's own): eight framed icons, left-side parts on the left, right-side parts on the right
OV_X = {"door_fl": 6, "door_rl": 37, "arch_fl": 68, "arch_rl": 99,
        "arch_rr": 135, "arch_fr": 166, "door_rr": 197, "door_fr": 228}
OV_W = 29


def _door_icon(img, tag):
    def draw(s, ov):
        OV_Y0, OV_Y1 = ov.TOP_BAND
        x0 = OV_X["door_" + tag]
        x1 = x0 + OV_W
        s.frame_box(x0, OV_Y0, x1, OV_Y1)
        left = tag[1] == "l"
        cx, cy = (x0 + x1) / 2.0, (OV_Y0 + OV_Y1) / 2.0
        # a door seen from its side, the plate on its lower part: the window frame line above it
        a, b = (-1, 1) if left else (1, -1)
        pts = [(cx + 11 * a, cy + 10), (cx + 11 * b, cy + 10), (cx + 11 * b, cy - 3), (cx + 7 * a, cy - 3), (cx + 11 * a, cy + 1)]
        ribs = [[(cx - 9, cy + 2), (cx + 9, cy + 2)], [(cx - 9, cy + 6), (cx + 9, cy + 6)]]
        frame = ("line", [(cx + 11 * b, cy - 4), (cx + 11 * b, cy - 10), (cx + 2 * a, cy - 10), (cx + 9 * a, cy - 4)], 1.6)
        s.cell([frame], None, fill=False)
        s.cell([("poly", pts)], img, details=ribs, dlw=1.1)
        return (x0, OV_Y0, x1, OV_Y1)
    return draw


def _arch_icon(img, tag):
    def draw(s, ov):
        OV_Y0, OV_Y1 = ov.TOP_BAND
        x0 = OV_X["arch_" + tag]
        x1 = x0 + OV_W
        s.frame_box(x0, OV_Y0, x1, OV_Y1)
        cx, cy = (x0 + x1 + 1) / 2.0, (OV_Y0 + OV_Y1 + 1) / 2.0 + 6.0
        # the tyre's top under a steel band round its opening; the band stays ~2 px inside the frame
        # (an outer radius of 15 in the 29 px cell merged it into the frame's sides)
        r0, r1 = 7.5, 12.0
        s.cell([("arc", cx, cy, 3.0, 5.5, 180.0, 360.0)], None)
        bolts = [[(cx + (r0 + 0.9) * math.cos(math.radians(a)), cy + (r0 + 0.9) * math.sin(math.radians(a))),
                  (cx + (r1 - 0.9) * math.cos(math.radians(a)), cy + (r1 - 0.9) * math.sin(math.radians(a)))]
                 for a in (215.0, 270.0, 325.0)]
        s.cell([("arc", cx, cy, r0, r1, 180.0, 360.0)], img, details=bolts, dlw=1.1)
        return (x0, OV_Y0, x1, OV_Y1)
    return draw


OVERLAYS = {}
for _t, _p, _a, _fr in DOORS:
    OVERLAYS["CRVArmourDoor" + _p] = {"img": "acc_armour_door_" + _t, "draw": _door_icon("acc_armour_door_" + _t, _t)}
    OVERLAYS["CRVArmourArch" + _p] = {"img": "acc_armour_arch_" + _t, "draw": _arch_icon("acc_armour_arch_" + _t, _t)}

# ---------------------------------------------------------------------------------------------
# scripts

# the window guard parts take a second item and a second model (gen_scripts.accessory_parts reads this):
# part -> [(item, model id, mesh)]. The Lua (HondaCRVGen1.Armour.showGuard) keeps only the model of the
# installed item visible.
GUARD_VARIANTS = {
    "CRVGuardFrontLeft": [("CRVGen1_ArmourMeshFront", "ArmourMesh", "acc_armour_mesh_fl")],
    "CRVGuardFrontRight": [("CRVGen1_ArmourMeshFront", "ArmourMesh", "acc_armour_mesh_fr")],
    "CRVGuardRearLeft": [("CRVGen1_ArmourMeshRear", "ArmourMesh", "acc_armour_mesh_rl")],
    "CRVGuardRearRight": [("CRVGen1_ArmourMeshRear", "ArmourMesh", "acc_armour_mesh_rr")],
    "CRVGuardWindshieldRear": [("CRVGen1_ArmourRearPlate", "ArmourPlate", "acc_armour_rear_plate")],
}


def MODELS(gen):
    out = []
    for t, _p, _a, _fr in DOORS:
        bone = "door_%s_bone" % t
        for geo in ("acc_armour_door_" + t, "acc_armour_mesh_" + t):
            out.append(gen.model_block(gen.acc_model_name(geo), "crvgen1_" + geo, static=False, bone=bone))
        out.append(gen.model_block(gen.acc_model_name("acc_armour_arch_" + t), "crvgen1_acc_armour_arch_" + t))
    out.append(gen.model_block(gen.acc_model_name("acc_armour_rear_plate"), "crvgen1_acc_armour_rear_plate",
                               static=False, bone="trunkglass_bone"))
    return out


# bolt-on heavy parts: a wrench AND a screwdriver, KI5-like times (door plates 25 s of game time at
# 1500, the arches 1000), Mechanics 4 / 3 with Basic Mechanics
TOOLS = (("base:wrench", "primary"), ("base:screwdriver", None))


def _table(kind, time, level, extra=()):
    t = "\t\t\t"
    verb = "Install" if kind == "install" else "Uninstall"
    lines = ["%stable %s" % (t, kind), "%s{" % t, "%s\titems" % t, "%s\t{" % t]
    for i, (tag, equip) in enumerate(TOOLS, 1):
        lines += ["%s\t\t%d" % (t, i), "%s\t\t{" % t, "%s\t\t\ttags = %s," % (t, tag), "%s\t\t\tcount = 1," % t,
                  "%s\t\t\tkeep = true," % t]
        if equip:
            lines.append("%s\t\t\tequip = %s," % (t, equip))
        lines.append("%s\t\t}" % t)
    lines += ["%s\t}" % t, "%s\ttime = %d," % (t, time), "%s\tskills = Mechanics:%d," % (t, level),
              "%s\trecipes = Basic Mechanics," % t, "%s\ttest = Vehicles.%sTest.Default," % (t, verb),
              "%s\tcomplete = %s.%sComplete," % (t, LUA_NS, verb)]
    lines += ["%s\t%s = %s," % (t, k, v) for k, v in extra]
    lines.append("%s}" % t)
    return "\n".join(lines)


def _part(gen, part, geo, item, area, parent, require, time, level, durability):
    lines = ["\t\tpart %s" % part, "\t\t{",
             "\t\t\tmodel %s" % part, "\t\t\t{", "\t\t\t\tfile = %s," % gen.acc_model_name(geo), "\t\t\t}",
             "\t\t\tarea = %s," % area, "\t\t\tcategory = bodywork,", "\t\t\tspecificItem = false,",
             "\t\t\titemType = Base.%s," % item, "\t\t\tmechanicRequireKey = false,", "\t\t\trepairMechanic = true,",
             "\t\t\tdurability = %s," % durability]
    if parent:
        lines.append("\t\t\tparent = %s," % parent)
    lines.append(_table("install", time, level, (("requireInstalled", require),) if require else ()))
    lines.append(_table("uninstall", time, level))
    lines += ["\t\t\tlua", "\t\t\t{", "\t\t\t\tcreate = %s.Create," % LUA_NS, "\t\t\t\tinit = %s.Init," % LUA_NS,
              "\t\t\t}", "\t\t}"]
    return "\n".join(lines)


def VEHICLE_PARTS(gen, vehicle):
    out = []
    for t, p, area, fr in DOORS:
        # a door plate is drawn by its door's AnimationPlayer (a child part): parent = the door
        out.append(_part(gen, "CRVArmourDoor" + p, "acc_armour_door_" + t, "CRVGen1_ArmourDoor" + fr, area,
                         "Door" + p, "Door" + p, 1500, 4, 25))
    for t, p, _area, fr in DOORS:
        out.append(_part(gen, "CRVArmourArch" + p, "acc_armour_arch_" + t, "CRVGen1_ArmourArch" + fr, ARCH_AREA[t],
                         None, None, 1000, 3, 20))
    return out


def _recipe(item, time, inputs, skills="MetalWelding:4;Mechanics:3", xp="MetalWelding:20;Mechanics:10"):
    lines = ["\tcraftRecipe %s" % RECIPE_OF[item], "\t{",
             "\t\ttimedAction = Welding_Surface,", "\t\ttime = %d," % time, "\t\tNeedToBeLearn = true,",
             "\t\tTags = AnySurfaceCraft,", "\t\tcategory = Metalworking,",
             "\t\tSkillRequired = %s," % skills, "\t\txpAward = %s," % xp,
             "\t\tinputs", "\t\t{"]
    lines += ["\t\t\t%s," % i for i in inputs]
    lines += ["\t\t\titem 1 tags[base:weldingmask] mode:keep,",
              "\t\t\titem 1 tags[base:wrench] mode:keep flags[MayDegradeLight],",
              "\t\t\titem 1 tags[base:hammer] mode:keep flags[MayDegradeVeryLight],",
              "\t\t}", "\t\toutputs", "\t\t{", "\t\t\titem 1 Base.%s," % item, "\t\t}", "\t}"]
    return "\n".join(lines)


RECIPES = [
    _recipe("CRVGen1_ArmourDoorFront", 900, ["item 3 [Base.SheetMetal]", "item 2 [Base.BlowTorch]", "item 4 [Base.Screws]"]),
    _recipe("CRVGen1_ArmourDoorRear", 800, ["item 3 [Base.SheetMetal]", "item 2 [Base.BlowTorch]", "item 4 [Base.Screws]"]),
    _recipe("CRVGen1_ArmourArchFront", 500, ["item 1 [Base.SheetMetal]", "item 1 [Base.BlowTorch]", "item 2 [Base.Screws]"],
            skills="MetalWelding:3;Mechanics:2"),
    _recipe("CRVGen1_ArmourArchRear", 450, ["item 1 [Base.SheetMetal]", "item 1 [Base.BlowTorch]", "item 2 [Base.Screws]"],
            skills="MetalWelding:3;Mechanics:2"),
    _recipe("CRVGen1_ArmourMeshFront", 600, ["item 1 [Base.SheetMetal]", "item 3 [Base.Wire]", "item 1 [Base.BlowTorch]",
                                              "item 2 [Base.Screws]"]),
    _recipe("CRVGen1_ArmourMeshRear", 550, ["item 1 [Base.SheetMetal]", "item 3 [Base.Wire]", "item 1 [Base.BlowTorch]",
                                             "item 2 [Base.Screws]"]),
    _recipe("CRVGen1_ArmourRearPlate", 800, ["item 2 [Base.SheetMetal]", "item 2 [Base.BlowTorch]", "item 4 [Base.Screws]"]),
]

SIDE_NAME = {"FrontLeft": "Front Left", "FrontRight": "Front Right", "RearLeft": "Rear Left", "RearRight": "Rear Right"}
TRANSLATIONS = {
    "IG_UI": dict([("IGUI_VehiclePartCRVArmourDoor" + p, "%s Door Armour Plate" % SIDE_NAME[p]) for _t, p, _a, _f in DOORS] +
                  [("IGUI_VehiclePartCRVArmourArch" + p, "%s Wheel Arch Guard" % SIDE_NAME[p]) for _t, p, _a, _f in DOORS] +
                  [("IGUI_CRV_Armour_WindowShut", "The armour holds this window shut"),
                   ("IGUI_CRV_Armour_PlateFirst", "Take the door's armour plate off first")]),
    "Tooltip": {"Tooltip_CRV_Armour_Magazine": "Welded plate, expanded-metal mesh and arch guards for the Honda CRV: "
                                               "teaches how to make every piece of CRV survival armour."},
    # 42.21 looks a craftRecipe's name up by its bare id (CraftRecipe.Load -> Translator.getRecipeName(name);
    # vanilla Recipes.json: "MakeMetalSheet": ...): no "Recipe_" prefix
    "Recipes": {RECIPE_OF[i]: "Make " + n for i, _w, n, *_r in ITEMS_SPEC},
}

SANDBOX = [
    {"name": "ArmourStrength", "type": "double", "default": 1.0, "min": 0.1, "max": 10.0,
     "label": "CRV armour strength",
     "tooltip": "How long the CRV's survival armour lasts. 1 = very strong (a door plate takes hundreds of "
                "zombie hits); 2 = twice as long; 0.5 = half."},
]

DISTRIBUTIONS = []
for _list, _w in (("GarageMechanics", 0.4), ("CrateMechanics", 0.4), ("MechanicSpecial", 0.6),
                  ("GarageMetalwork", 0.3), ("ArmyHangarMechanics", 0.8), ("PoliceStorageMechanics", 0.5)):
    for _item, *_r in ITEMS_SPEC:
        DISTRIBUTIONS.append({"list": _list, "item": "Base." + _item, "weight": round(_w * (0.5 if "Door" in _item or "Plate" in _item else 1.0), 2)})
for _list, _w in (("CarSupplyMagazines", 0.8), ("BookstoreAutomotive", 0.8), ("MagazineRackMixed", 0.1),
                  ("CrateMagazines", 0.3), ("ArmySurplusMisc", 0.5), ("ArmyHangarMechanics", 0.4)):
    DISTRIBUTIONS.append({"list": _list, "item": "Base." + MAGAZINE, "weight": _w})

LUA = ["shared/HondaCRVGen1_Armour.lua", "server/Vehicles/HondaCRVGen1_ArmourServer.lua"]
MEDIA = ["common/media/textures/Item_%s.png" % MAGAZINE]
