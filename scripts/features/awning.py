r"""
Side awning (feature "awning", 2026-10-19): a roll-out awning on the car's RIGHT (passenger) side, like the
owner's reference photos of 1st-gen CR-Vs: a long black / grey bag on two brackets clamped to the stock
roof rail, which unrolls into a flat tan canvas canopy beside the car, held by two telescopic poles at its
outer corners. Two states, both drawn only while the part is installed:
  stowed    the bag (model Awning, the part's first model: shown by the game with the item)
  deployed  the bag + the canopy (AwningCanopy: canvas, rafters, the front bar and the valance) + the poles
            (AwningPoles; the lifted scripts draw a longer pair, their body stands LIFT_DROP higher)
The Lua (shared/HondaCRVGen1_Awning.lua) shows the canopy and the poles from the synced state
awning_deployed (HondaCRVGen1.State), like the rack's cargo; the timed action ISCRVAwning sets it on the
authoritative side; the car stows it itself when its engine runs or it moves; client/HondaCRVGen1_AwningRain
.lua keeps the rain off a player standing under it (see that file for what exactly it does).

Mounting (decided 2026-10-19): on the EX's stock roof rails, no roof rack needed. The rails are a level bar
each side (build_details: x 0.555, top z 1.700, y -1.66..0.10 on three feet); awning brackets clamp the bar
between the feet, as the aftermarket rail brackets for these awnings do. The rack, when fitted, sits inboard
(its crossbars end at x 0.57, the brackets clamp at y -1.20 / -0.25, clear of the crossbars at -1.40 / -0.42
and the towers), so the two never touch and either can come off alone.

Where it sits (measured on the low parts of the 2026-10-19 main build, scratch awning/measure.py):
  * roof edge: the body's side at the drip rail is x 0.57-0.59 (z 1.62); the door frames' tops reach z 1.614 /
    1.624 at x 0.58-0.68 and swing out below that, the windows and the guards stay under z 1.61;
  * the bag is clear of every other part that can be fitted on the right: the snorkel's ram head
    (x 0.58..0.72, y 0.14..0.38, z to 1.733), the ladder's top over the roof edge (x 0.52..0.68, y -1.70..
    -1.44, z to 1.769): BAG_Z0 1.79 stands over both; the flip-up glass (x to 0.624, hinge y -1.70): the
    bag starts at x 0.635, outboard of it however far it swings up; the rack (x to 0.57). The antenna is on
    the LEFT A-pillar;
  * the bag is 2.8 m long (y -2.12..0.68; 2026-10-20, 40 % longer than the first 2.0 m one): past the roof's
    rear end (y -1.80) over the gate to inside the bumper's line, and past the windscreen header (y 0.29) at
    the front, as the 2.5 m rail-mounted awnings on these cars sit;
  * the canopy runs from the bag's lower outer edge (x 0.785, z 1.83) to x 2.55 at z 2.04 (a 1.77 m reach,
    rising 7 degrees: the bag sits at roof height and a standing character is ~1.72 m tall, so the outer edge
    is the high one), y -2.09..0.65 (2.74 m), above the open doors (their tops at 1.62 m) and the swung-open
    gate, and clear of their swing (the front pole stands ~1.9 m from the front door's hinge, the door is
    1.1 m long; the rear pole ~1.8 m from the gate's hinge). Two poles at the outer corners, as the 2.5 m
    rail awnings have (no middle leg), and two rafters at the ends.

Triangle budget (FEATURE_RULES: lean): bag + brackets ~160, canopy ~180, poles ~150 (BUILD reports them).
Everything bakes on this feature's own 512 sheet ("awning", Vehicles_HondaCRVGen1_Awning.png, vehiclewheel
shader); each piece carries its own ambient occlusion (acc_shade) like the other accessories.
"""
import math

KEY = "awning"
TEX_NAME = "Awning"
PART = "CRVAwning"
ITEM_ID = "CRVGen1_Awning"
LUA_NS = "HondaCRVGen1.Awning"
STATE_KEY = "awning_deployed"
MODEL_BAG, MODEL_CANOPY, MODEL_POLES = PART, "AwningCanopy", "AwningPoles"   # HondaCRVGen1.Awning.MODELS

BAG, CANOPY, POLES, POLES_LIFT = "acc_awning_bag", "acc_awning_canopy", "acc_awning_poles", "acc_awning_poles_lift"
NAMES = [BAG, CANOPY, POLES, POLES_LIFT]

MATS = ["AccAwningBag", "AccAwningCanvas", "AccAwningAlu", "AccAwningSteel", "AccAwningRubber"]
BAGM, CANVAS, ALU, STEEL, RUBBER = range(len(MATS))
COLOURS = {                                   # linear base colours (BAKE_TEXTURED refines them)
    "AccAwningBag": (0.040, 0.041, 0.043),    # charcoal PVC bag (the reference photos: black / dark grey)
    "AccAwningCanvas": (0.36, 0.30, 0.21),    # tan poly-cotton canvas
    "AccAwningAlu": (0.40, 0.41, 0.43),       # anodised aluminium rafters and poles
    "AccAwningSteel": (0.030, 0.030, 0.032),  # black powder-coated brackets
    "AccAwningRubber": (0.012, 0.012, 0.013), # pole feet, the bag's end caps
}

# ---------------------------------------------------------------------------------------------
# measured placements (metres, model space: +x right, +y forward, +z up, ground 0)

RAIL_X, RAIL_W, RAIL_H = 0.555, 0.026, 0.022  # build_details.RAIL_X / RAIL_W / RAIL_H (BUILD measures the top)
RAIL_TOP = 1.700                              # fallback when the ray finds no rail
BRACKET_Y = (-1.20, -0.25)                    # clamps on the rail bar, between its feet (y 0.02 / -0.78 / -1.60)
BRACKET_W = 0.044                             # along y
BAG_X = (0.635, 0.795)                        # the bag's inner and outer faces
BAG_Z = (1.790, 1.910)                        # its underside and top
BAG_Y = (-2.12, 0.68)                         # 2.8 m long (2026-10-20, the owner: "40% longer"; was -1.62..0.38, 2.0
                                              # m): +0.50 m at the rear, +0.30 m at the front, so the brackets stay
                                              # centred under it (0.92 / 0.93 m overhangs) and it ends inside the
                                              # car's length (the bumper at y -2.24); the front end overhangs the
                                              # windscreen header (y 0.29 at the roof's right edge) like the 2.5 m
                                              # rail-mounted awnings on these cars; it clears the snorkel's head and
                                              # the ladder's top below it (BAG_Z[0]) and the flip-up glass inboard
BAG_R = 0.026                                 # section corner radius
CAP = 0.014                                   # the hard end caps' length (rubber)
STRAPS_Y = tuple(round(BAG_Y[0] + (BAG_Y[1] - BAG_Y[0]) * f, 3) for f in (0.09, 0.363, 0.637, 0.91))
                                              # the velcro straps round the bag (painted bands, BAKE_TEXTURED): 4
                                              # evenly spread on the 2.8 m bag (3 on the 2.0 m one)
STRAP_W = 0.045
# canopy
CAN_X = (0.785, 2.55)                         # the canvas root (inside the bag) and its outer edge
CAN_Z = (1.830, 2.040)
CAN_Y = (BAG_Y[0] + 0.03, BAG_Y[1] - 0.03)
CAN_T = 0.006                                 # canvas thickness (a slab: its top and its underside are both seen)
CAN_SAG = 0.055                               # between the rafters the canvas sags this much at its middle (0.045
                                              # over the 1.94 m canopy; its 2.74 m span sags a little more)
CAN_NU, CAN_NV = 6, 6                         # grid across the reach / along the car (round 5: was 4 x 2, whose
                                              # 1 m faces drew the sag as two flat planes and the per-corner shade
                                              # as dark diagonal blotches over the whole canvas; 6 along the 2.74 m
                                              # canopy keeps its faces ~0.46 m, as the 4 did along 1.94 m)
CAN_SHADE = (1.0, 0.90)                       # the slab's own shade, top / underside: smooth by construction (the
                                              # ray-cast acc_shade at 15 corners came out as triangles of 0.6-1.0)
SEAMS_U = (1.0 / 3.0, 2.0 / 3.0)              # the canvas's panel seams, parallel to the bag (fraction of the reach)
SEAM_W = 0.020
BINDING = 0.045                               # the dark edge binding along the front and rear edges (2.8 cm
                                              # baked to a 1-texel sliver on the chart's border)
VALANCE = 0.13                                # the flap hanging from the outer edge
BAR_R = 0.014                                 # the front tension bar along the outer edge (28 mm)
RAFTER = 0.022                                # square rafter tubes along the front and rear edges
# poles (telescopic): at the outer corners, ground to the tension bar
POLE_IN = 0.012                               # pole centre inboard of the bar's centre line
POLE_R = (0.016, 0.0125)                      # lower and upper tube radii
POLE_SPLIT = 1.05                             # where the upper tube leaves the lower one (the clamp collar)
FOOT = (0.075, 0.010)                         # foot plate side and thickness
LIFT_DROP = 0.075 + (0.381 - 0.334)           # lift.LIFT_M + its AT tyre's radius - the stock 0.334: the lifted
                                              # body stands this much higher, so its poles are this much longer


def footprint():
    """The ground the canopy covers (model metres, +x right): x0, x1, y0, y1. HondaCRVGen1.Awning.AREA."""
    return (CAN_X[0] - 0.05, CAN_X[1], CAN_Y[0], CAN_Y[1])


# ---------------------------------------------------------------------------------------------
# helpers (Blender only)


def _materials():
    import bpy
    out = []
    for name in MATS:
        m = bpy.data.materials.get(name)
        if m is None:
            m = bpy.data.materials.new(name)
            m.use_nodes = True
        b = next(n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
        b.inputs['Base Color'].default_value = COLOURS[name] + (1.0,)
        b.inputs['Roughness'].default_value = 0.35 if name == "AccAwningAlu" else 0.7
        out.append(m)
    return out


def _obj(name, bm):
    """A mesh object from bm with this feature's materials, in the body's collection."""
    import bmesh
    import bpy
    old = bpy.data.objects.get(name)
    if old is not None:
        bpy.data.objects.remove(old, do_unlink=True)
    me = bpy.data.meshes.get(name)
    if me is not None:
        bpy.data.meshes.remove(me)
    me = bpy.data.meshes.new(name)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    bm.normal_update()
    bm.to_mesh(me)
    bm.free()
    for m in _materials():
        me.materials.append(m)
    ob = bpy.data.objects.new(name, me)
    body = bpy.data.objects.get("body")
    coll = body.users_collection[0] if body is not None else bpy.context.scene.collection
    coll.objects.link(ob)
    return ob


def _rail_top(report):
    """The right roof rail's top (z) at the brackets, by rays down onto the body at RAIL_X."""
    import bpy
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    ob = bpy.data.objects.get("body")
    if ob is None:
        return RAIL_TOP
    tree = BVHTree.FromPolygons([ob.matrix_world @ v.co for v in ob.data.vertices], [list(p.vertices) for p in ob.data.polygons])
    tops = []
    for y in BRACKET_Y:
        h = tree.ray_cast(Vector((RAIL_X, y, 3.0)), Vector((0.0, 0.0, -1.0)))
        if h[0] is not None and h[0].z > 1.68:
            tops.append(h[0].z)
    if len(tops) < len(BRACKET_Y):
        report("FEATURE awning: warning the roof rail was not found at every bracket (%s): using z %.3f" % (tops, RAIL_TOP))
        return RAIL_TOP
    return max(tops)


def _in_clamp(mine, other, zr):
    """A contact of a bracket's rail clamp (mine: that face's centre) with the rail bar (other: the bar face's centre):
    the bar runs through the clamps, those contacts are the mount."""
    return (mine.x < BAG_X[0] - 0.011 and mine.z < zr + 0.007 and any(abs(mine.y - y) < BRACKET_W / 2.0 + 0.002 for y in BRACKET_Y)
            and abs(other.x - RAIL_X) < RAIL_W / 2.0 + 0.004 and other.z > zr - RAIL_H - 0.004)


def _overlaps(ob, names, ignore=None):
    """'name n pairs, ...' for every named object whose faces intersect ob's (BVH overlap), '' if none; a pair for
    which ignore(my face's centre, the other face's centre) holds is the mount and is not counted."""
    import bpy
    from mathutils.bvhtree import BVHTree
    mv = [ob.matrix_world @ v.co for v in ob.data.vertices]
    mine = BVHTree.FromPolygons(mv, [list(p.vertices) for p in ob.data.polygons])

    def centre(vs, p):
        return sum((vs[i] for i in p.vertices), vs[0] * 0.0) / len(p.vertices)
    out = []
    for n in names:
        o = bpy.data.objects.get(n)
        if o is None or o.type != 'MESH':
            continue
        vs = [o.matrix_world @ v.co for v in o.data.vertices]
        t = BVHTree.FromPolygons(vs, [list(p.vertices) for p in o.data.polygons])
        pairs = mine.overlap(t)
        if ignore is not None:
            pairs = [(a, b) for a, b in pairs
                     if not ignore(centre(mv, ob.data.polygons[a]), centre(vs, o.data.polygons[b]))]
        if pairs:
            out.append("%s %d tri pairs" % (n, len(pairs)))
    return ", ".join(out)


# ---------------------------------------------------------------------------------------------
# the bag and its brackets (model Awning: shown whenever the part is installed)


def build_bag(BA, report):
    import bmesh
    zr = _rail_top(report)
    bm = bmesh.new()
    a, b = (BAG_X[1] - BAG_X[0]) / 2.0, (BAG_Z[1] - BAG_Z[0]) / 2.0
    xc, zc = (BAG_X[0] + BAG_X[1]) / 2.0, (BAG_Z[0] + BAG_Z[1]) / 2.0

    def ring(y, d):                                           # the section (x, z) at y, inset by d
        return [(xc + x, y, zc + z) for x, z in BA._rr(a - d, b - d, BAG_R - d * 0.8, 2)]
    y0, y1 = BAG_Y
    # the bag: hard end caps (rubber, rounded off) on a PVC body
    rings = [ring(y0, 0.010), ring(y0 + CAP, 0.0), ring(y1 - CAP, 0.0), ring(y1, 0.010)]
    BA._loft(bm, rings, [RUBBER, BAGM, RUBBER], cap_mats=(RUBBER, RUBBER))
    # brackets: a clamp round the rail bar, an arm out over the roof edge, an upright plate on the bag's inner
    # face and a shelf under the bag (the bag rests on it, strapped to the upright)
    rx0, rx1 = RAIL_X - RAIL_W / 2.0, RAIL_X + RAIL_W / 2.0
    zb = zr - RAIL_H
    for yb in BRACKET_Y:
        w0, w1 = yb - BRACKET_W / 2.0, yb + BRACKET_W / 2.0
        # the clamp round the rail bar and the arm out to the upright, one block (the bar runs through it)
        BA._box(bm, (rx0 - 0.006, w0, zb - 0.006), (BAG_X[0] - 0.012, w1, zr + 0.006), mat=STEEL)
        BA._box(bm, (BAG_X[0] - 0.012, w0, zr - 0.006), (BAG_X[0] - 0.001, w1, BAG_Z[1] - 0.010), mat=STEEL)
        BA._box(bm, (BAG_X[0] - 0.012, w0, BAG_Z[0] - 0.010), (xc + 0.02, w1, BAG_Z[0] - 0.001), mat=STEEL)
    ob = _obj(BAG, bm)
    ob["rail_top"] = zr
    report("FEATURE awning: %s %d tris, bag x %.3f..%.3f z %.3f..%.3f y %.2f..%.2f, brackets on the rail (top z %.3f) at y %s"
           % (BAG, BA.tris(ob), BAG_X[0], BAG_X[1], BAG_Z[0], BAG_Z[1], y0, y1, zr, BRACKET_Y))
    return ob


# ---------------------------------------------------------------------------------------------
# the canopy (model AwningCanopy): canvas slab, rafters, the front bar and the valance


def _can_z(u, v):
    """The canvas's mid surface at u (0 bag .. 1 outer edge) and v (0 rear .. 1 front rafter)."""
    return CAN_Z[0] + (CAN_Z[1] - CAN_Z[0]) * u - CAN_SAG * math.sin(math.pi * u) * math.sin(math.pi * v)


def build_canopy(BA, report):
    import bmesh
    bm = bmesh.new()
    nu, nv = CAN_NU, CAN_NV
    top, bot = [], []
    for i in range(nu + 1):
        u = i / float(nu)
        x = CAN_X[0] + (CAN_X[1] - CAN_X[0]) * u
        rt, rb = [], []
        for j in range(nv + 1):
            v = j / float(nv)
            y = CAN_Y[0] + (CAN_Y[1] - CAN_Y[0]) * v
            z = _can_z(u, v)
            rt.append(bm.verts.new((x, y, z + CAN_T / 2.0)))
            rb.append(bm.verts.new((x, y, z - CAN_T / 2.0)))
        top.append(rt)
        bot.append(rb)
    faces = []
    for i in range(nu):
        for j in range(nv):
            faces.append(bm.faces.new((top[i][j], top[i + 1][j], top[i + 1][j + 1], top[i][j + 1])))
            faces.append(bm.faces.new((bot[i][j], bot[i][j + 1], bot[i + 1][j + 1], bot[i + 1][j])))
    # the rim: the slab's four edges
    loop = [(i, 0) for i in range(nu)] + [(nu, j) for j in range(nv)] + [(i, nv) for i in range(nu, 0, -1)] + \
           [(0, j) for j in range(nv, 0, -1)]
    for k, (i, j) in enumerate(loop):
        i2, j2 = loop[(k + 1) % len(loop)]
        faces.append(bm.faces.new((top[i][j], bot[i][j], bot[i2][j2], top[i2][j2])))
    nslab = 2 * nu * nv
    for k, f in enumerate(faces):
        f.material_index = CANVAS
        f.smooth = k < nslab                                  # the sagging cloth shades smooth, its rim flat
    BA._outward(faces)
    # the valance: a flap hanging from the outer edge, a hair outboard of the tension bar
    xo = CAN_X[1] + BAR_R + 0.002
    BA._box(bm, (xo, CAN_Y[0], CAN_Z[1] - VALANCE), (xo + 0.004, CAN_Y[1], CAN_Z[1] + 0.004), mat=CANVAS)
    # the front tension bar along the outer edge (the canvas's edge tucks into it)
    BA._sweep(bm, [(CAN_X[1], CAN_Y[0] - 0.012, CAN_Z[1]), (CAN_X[1], CAN_Y[1] + 0.012, CAN_Z[1])], BA._round(BAR_R, 6),
              ups=[(0, 0, 1)] * 2, smooth=True, mat=ALU)
    # rafters along the rear and front edges, from the bag's ends to the bar's, just under the canvas
    for y in (CAN_Y[0] + RAFTER / 2.0, CAN_Y[1] - RAFTER / 2.0):
        BA._sweep(bm, [(BAG_X[1] - 0.030, y, BAG_Z[0] + 0.035), (CAN_X[1] - BAR_R, y, CAN_Z[1] - CAN_T / 2.0 - RAFTER / 2.0)],
                  BA._rect(RAFTER, RAFTER), ups=[(0, 0, 1)] * 2, smooth=False, mat=ALU)
    ob = _obj(CANOPY, bm)
    report("FEATURE awning: %s %d tris, canvas x %.3f..%.3f, z %.3f -> %.3f (sag %.0f mm), y %.2f..%.2f, valance %.0f cm"
           % (CANOPY, BA.tris(ob), CAN_X[0], CAN_X[1], CAN_Z[0], CAN_Z[1], CAN_SAG * 1000, CAN_Y[0], CAN_Y[1], VALANCE * 100))
    return ob


def _slab_shade(ob):
    """The canvas slab's top and underside get a flat CAN_SHADE (see there); the rim, the valance, the bar and the
    rafters keep their ray-cast shade. Returns the object's new mean."""
    me = ob.data
    attr = me.attributes["acc_shade"]
    vals = [0.0] * len(me.loops)
    attr.data.foreach_get("value", vals)
    for p in me.polygons:
        c = p.center
        if (me.materials[p.material_index].name == MATS[CANVAS] and abs(p.normal.z) > 0.6
                and CAN_X[0] - 1e-4 <= c.x <= CAN_X[1] + 1e-4 and CAN_Y[0] <= c.y <= CAN_Y[1]):
            for li in p.loop_indices:
                vals[li] = CAN_SHADE[0] if p.normal.z > 0 else CAN_SHADE[1]
    attr.data.foreach_set("value", vals)
    return sum(vals) / max(1, len(vals))


def pole_points():
    """(x, y) of the two poles."""
    x = CAN_X[1] - POLE_IN
    return [(x, CAN_Y[0] + RAFTER), (x, CAN_Y[1] - RAFTER)]


def build_poles(BA, report, name, drop):
    """Two telescopic poles from the ground (z -drop: a lifted body stands that much higher) to the bar."""
    import bmesh
    bm = bmesh.new()
    zg = -drop
    ztop = CAN_Z[1] - 0.004
    for x, y in pole_points():
        BA._box(bm, (x - FOOT[0] / 2, y - FOOT[0] / 2, zg), (x + FOOT[0] / 2, y + FOOT[0] / 2, zg + FOOT[1]), mat=RUBBER)
        BA._sweep(bm, [(x, y, zg + FOOT[1] - 0.002), (x, y, POLE_SPLIT + 0.02)], BA._round(POLE_R[0], 8), smooth=True, mat=ALU)
        BA._sweep(bm, [(x, y, POLE_SPLIT - 0.02), (x, y, POLE_SPLIT + 0.025)], BA._round(POLE_R[0] + 0.004, 8), smooth=False,
                  mat=STEEL)                                                                   # the clamp collar
        BA._sweep(bm, [(x, y, POLE_SPLIT), (x, y, ztop)], BA._round(POLE_R[1], 6), smooth=True, mat=ALU)
    ob = _obj(name, bm)
    report("FEATURE awning: %s %d tris, poles at %s from z %.3f to %.3f" % (
        name, BA.tris(ob), ", ".join("(%.2f, %.2f)" % p for p in pole_points()), zg, ztop))
    return ob


def BUILD(report):
    import build_accessories as BA
    made = [build_bag(BA, report), build_canopy(BA, report), build_poles(BA, report, POLES, 0.0),
            build_poles(BA, report, POLES_LIFT, LIFT_DROP)]
    for ob in made:
        mean = BA._shade(ob, 0.55)
        if ob.name == CANOPY:
            mean = _slab_shade(ob)
        report("FEATURE awning: %s shade mean %.2f" % (ob.name, mean))
    # nothing of it may cut into the car or the other accessories present now (the off-road parts build after
    # this feature, sorted by name: their clearances are the measured ones in the docstring)
    others = ["body", "door_fr", "door_rr", "window_fr", "window_rr", "trunk_top", "trunk", "acc_roofrack",
              "acc_guard_fr", "acc_guard_rr", "acc_guard_rear"] + list(BA.LOAD_NAMES)
    zr = made[0]["rail_top"]
    for ob in made:
        hit = _overlaps(ob, others, ignore=(lambda a, b: _in_clamp(a, b, zr)) if ob.name == BAG else None)
        report("FEATURE awning: %s %s" % (ob.name, ("WARNING intersects " + hit) if hit else
                                          "clear of the car and the accessories" + (" (the clamps round the rail bar aside)"
                                                                                    if ob.name == BAG else "")))
    report("FEATURE awning: stowed %d tris, deployed %d tris (bag + canopy + poles)"
           % (BA.tris(made[0]), BA.tris(made[0]) + BA.tris(made[1]) + BA.tris(made[2])))


OBJECTS = {name: {"space": KEY} for name in NAMES}
SPACES = {KEY: {"size": 512, "texture": TEX_NAME, "ao_k": 0.30, "gain": 1.0, "grime": ((96, 88, 74), 0.0)}}

# ---------------------------------------------------------------------------------------------
# bake: the materials' colour stacks (every face carries acc_shade, the pieces' own AO)

SHADE = ("attr", "acc_shade")


def _straps():
    """The bag's velcro straps and its zip as tint layers (dark webbing bands round the bag at STRAPS_Y, the zip
    along its outer face)."""
    out = [("tint", (0.012, 0.012, 0.013), [("range", "y", y - STRAP_W / 2, y + STRAP_W / 2)]) for y in STRAPS_Y]
    zx = BAG_X[1]
    out.append(("tint", (0.016, 0.016, 0.017), [("normal", "x", ">", 0.6), ("range", "z", BAG_Z[1] - 0.034, BAG_Z[1] - 0.026),
                                                ("range", "x", zx - 0.02, zx + 0.01)]))
    return out


BAKE_TEXTURED = {
    "AccAwningBag": [("box", "fabric_leather_01_diffuse_1k.jpg", 0.20, (0.055, 0.056, 0.060), 0.55), ("noise", 70.0, 0.05)]
    + _straps() + [SHADE],
    # canvas: a fine weave over a tan base; panel seams parallel to the bag, a dark binding along the front and
    # rear edges, the outer valance's hem a shade darker (round 5: the plain slab read as a board)
    "AccAwningCanvas": [("box", "denim_fabric_03_diffuse_1k.jpg", 0.25, (0.40, 0.335, 0.235), 0.65), ("noise", 30.0, 0.04)]
    + [("tint", (0.25, 0.205, 0.140), [("range", "x", CAN_X[0] + (CAN_X[1] - CAN_X[0]) * u - SEAM_W / 2,
                                                CAN_X[0] + (CAN_X[1] - CAN_X[0]) * u + SEAM_W / 2),
                                      ("range", "z", CAN_Z[0] - 0.08, CAN_Z[1] + 0.02)]) for u in SEAMS_U]
    + [("tint", (0.050, 0.047, 0.042), [("range", "y", CAN_Y[0] - 0.01, CAN_Y[0] + BINDING),
                                        ("range", "x", CAN_X[0] + 0.02, CAN_X[1] + 0.05)]),
       ("tint", (0.050, 0.047, 0.042), [("range", "y", CAN_Y[1] - BINDING, CAN_Y[1] + 0.01),
                                        ("range", "x", CAN_X[0] + 0.02, CAN_X[1] + 0.05)]),
       ("tint", (0.30, 0.25, 0.17), [("range", "x", CAN_X[1] + 0.01, CAN_X[1] + 0.03),
                                     ("range", "z", CAN_Z[1] - VALANCE, CAN_Z[1] - VALANCE + 0.02)]),
       SHADE],
    "AccAwningAlu": [("box", "metal_plate_02_diffuse_1k.jpg", 0.25, (0.42, 0.43, 0.45), 0.60), SHADE],
    "AccAwningSteel": [("box", "metal_plate_02_diffuse_1k.jpg", 0.40, (0.040, 0.041, 0.043), 0.45), SHADE],
    "AccAwningRubber": [("noise", 80.0, 0.05), SHADE],
}
BAKE_MAT_WEIGHTS = {"AccAwningBag": 1.0, "AccAwningCanvas": 1.0, "AccAwningAlu": 0.7, "AccAwningSteel": 0.6,
                    "AccAwningRubber": 0.4}

# ---------------------------------------------------------------------------------------------
# icon and the mechanics overlay


ICON_SQUASH = 0.26          # the 2.8 m bag shortened to ~0.73 m: about 4.5 x its section, so it stays a fat roll in 32 px
# R2-VIS-2 (2026-10-25): drawn with the bag's sheet, the all-dark roll was lifted by gen_icons' levels (a part's
# brightest tenth is raised to MIN_HI) into a light blue-grey beam. The icon now paints the bag flat in its canvas
# colour (matte: no studio glint on the top) with the end caps black, and wraps it in light webbing straps at the
# model's STRAPS_Y: the straps carry the highlights the levels look for, so the canvas stays dark.
ICON_CANVAS = (0.12, 0.12, 0.13)        # stored sRGB: the bag's black PVC canvas (its top face ~0.18 in the icon)
ICON_CAPS = (0.06, 0.06, 0.065)         # the rubber end caps
ICON_STRAP = (0.62, 0.62, 0.60)         # grey webbing, read at 32 px
ICON_STRAP_W = 0.060                    # m on the squashed roll (~2.5 icon px)
ICON_STRAP_OUT = 0.005                  # m proud of the bag's skin


def _icon_scene(ic):
    """The item as it is carried: the rolled awning in its black canvas bag (the stowed model, brackets off),
    laid diagonally and shortened along its length so its section, end caps and straps survive the 32 px
    reduction. (The deployed canopy on its poles read as a second picnic table.)"""
    import bmesh
    import build_accessories as BA
    ob = ic.copy(BAG, squash=ICON_SQUASH)
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.material_index == STEEL], context='FACES')
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context='VERTS')
    bm.to_mesh(ob.data)
    bm.free()
    me = ob.data
    me.materials.clear()
    for i, _name in enumerate(MATS):                  # flat colours by the bag's own material slots
        mat = ic.flat_material("icon_awning_%d" % i, ICON_CAPS if i == RUBBER else ICON_CANVAS)
        mat.roughness, mat.metallic = 1.0, 0.0       # canvas, not paint: Workbench's specular reads these
        me.materials.append(mat)
    me.update()
    # the straps: bands round the bag's section at STRAPS_Y, built on the car and put through copy()'s own
    # transform (its centring and its squash along the parts' principal axis, which the brackets tilt off y)
    import bpy
    import numpy as np
    src = bpy.data.objects[BAG]
    pts = np.array([tuple(src.matrix_world @ v.co) for v in src.data.vertices])
    c = pts.mean(0)
    ax = np.linalg.eigh((pts - c).T @ (pts - c))[1][:, 2]
    m3 = np.eye(3) + (ICON_SQUASH - 1.0) * np.outer(ax, ax)
    a, b = (BAG_X[1] - BAG_X[0]) / 2.0, (BAG_Z[1] - BAG_Z[0]) / 2.0
    xc, zc = (BAG_X[0] + BAG_X[1]) / 2.0, (BAG_Z[0] + BAG_Z[1]) / 2.0
    sec = BA._rr(a + ICON_STRAP_OUT, b + ICON_STRAP_OUT, BAG_R + ICON_STRAP_OUT, 2)
    half = ICON_STRAP_W / 2.0 / ICON_SQUASH            # its width before the squash
    verts, faces, mids = [], [], []
    for ys in STRAPS_Y:
        base, n = len(verts), len(sec)
        for yy in (ys - half, ys + half):
            w = np.array([(xc + x, yy, zc + z) for x, z in sec])
            verts += [tuple(p) for p in (w - c) @ m3.T]
        mids.append(m3 @ (np.array([xc, ys, zc]) - c))
        faces += [(base + j, base + (j + 1) % n, base + n + (j + 1) % n, base + n + j) for j in range(n)]
    straps = ic._object("icon_awning_straps", verts, faces, ICON_STRAP)
    straps.data.materials[0].roughness = 1.0
    sm = bmesh.new()                                  # outward normals (the icons cull back faces)
    sm.from_mesh(straps.data)
    for f in sm.faces:
        fc = f.calc_center_median()
        m = mids[f.index // len(sec)]
        r = np.array(tuple(fc)) - m
        r -= ax * float(r @ ax)
        if float(np.array(tuple(f.normal)) @ r) < 0.0:
            f.normal_flip()
    sm.to_mesh(straps.data)
    sm.free()
    return [ob, straps]


ICONS = {ITEM_ID: (_icon_scene, 295.0, 40.0)}

# the right-hand column between the front wheel's frames and the front window guard's (sheet rows ~228-264, x
# 221-257 are free; the car's right is the sheet's right), a leader to the roof's right edge
OV_BOX = (221, 229, 257, 263)


def _overlay(s, ov):
    """The awning from the side: the bag at the top left, the canopy rising out of it to the right, the poles."""
    x0, y0, x1, y1 = OV_BOX
    s.frame_box(x0, y0, x1, y1)
    bag = ("rrect", x0 + 4, y0 + 8, x0 + 13, y0 + 15, 2.5)
    canvas = ("poly", [(x0 + 11, y0 + 10), (x1 - 4, y0 + 5), (x1 - 4, y0 + 9), (x0 + 12, y0 + 15)])
    poles = [("line", [(x1 - 6, y0 + 9), (x1 - 6, y1 - 4)], 2.0)]
    valance = ("rrect", x1 - 5, y0 + 5, x1 - 3, y0 + 13, 0.5)          # the flap hanging from the outer edge
    s.cell([bag, canvas, valance] + poles, "acc_awning", details=[[(x0 + 6, y0 + 11.5), (x0 + 11, y0 + 11.5)]], dlw=1.0)
    # leader from the frame's left edge to the roof's right edge at the bag's middle
    px, py = ov.px(0.62, (BAG_Y[0] + BAG_Y[1]) / 2.0)
    s.leader([(x0, (y0 + y1) // 2), (int(round(px)) + 2, (y0 + y1) // 2)])
    return (x0, y0, x1, y1)


OVERLAYS = {PART: {"img": "acc_awning", "draw": _overlay}}

# ---------------------------------------------------------------------------------------------
# scripts


def MODELS(gen):
    return [gen.model_block(gen.acc_model_name(geo), "crvgen1_" + geo, texture="%s_%s" % (gen.TEX, TEX_NAME),
                            shader="vehiclewheel") for geo in NAMES]


def _lifted(vehicle):
    """The lift feature's second scripts (their body stands LIFT_DROP higher): the longer poles."""
    try:
        from features import lift
        return vehicle in set(getattr(lift, "VEHICLES", {}).values())
    except ImportError:
        return False


def VEHICLE_PARTS(gen, vehicle):
    poles = POLES_LIFT if _lifted(vehicle) else POLES
    # installed and removed with a wrench from the right side (the rear door's area, under the bag's middle);
    # the canopy and the poles are extra models the Lua shows while deployed (the rack's cargo pattern)
    return gen.accessory_part(PART, BAG, ITEM_ID, "SeatRearRight", tool="base:wrench", time=700, level=1, lua=LUA_NS,
                              models=[(MODEL_CANOPY, CANOPY), (MODEL_POLES, poles)])


ITEMS = {
    ITEM_ID: {"DisplayCategory": "VehicleMaintenance", "Weight": 9.0, "ItemType": "base:normal",
           "DisplayName": "CRV Side Awning", "Icon": ITEM_ID, "ConditionMax": 100, "ChanceToSpawnDamaged": 15,
           "MechanicsItem": True, "Tooltip": "Tooltip_CRV_Awning_Item"},
}

RECIPES = """\tcraftRecipe CRVGen1_MakeAwning
\t{
\t\ttimedAction = SewingCloth,
\t\ttime = 600,
\t\tTags = AnySurfaceCraft,
\t\tcategory = Tailoring,
\t\tSkillRequired = Tailoring:3;Mechanics:1,
\t\txpAward = Tailoring:20;Mechanics:5,
\t\tinputs
\t\t{
\t\t\titem 2 [Base.Tarp],
\t\t\titem 2 [Base.MetalPipe],
\t\t\titem 1 [Base.Rope],
\t\t\titem 4 [Base.Screws],
\t\t\titem 2 tags[base:heavythread],
\t\t\titem 1 tags[base:sewingneedle] mode:keep flags[MayDegradeLight],
\t\t\titem 1 tags[base:screwdriver] mode:keep flags[MayDegradeLight],
\t\t}
\t\toutputs
\t\t{
\t\t\titem 1 Base.CRVGen1_Awning,
\t\t}
\t}"""

TRANSLATIONS = {
    "IG_UI": {
        "IGUI_VehiclePartCRVAwning": "Side Awning",
        "IGUI_CRV_Awning_Deployed": "Awning rolled out",
        "IGUI_CRV_Awning_Stowed": "Awning rolled up",
        "IGUI_CRV_Awning_AutoStowed": "The awning was rolled up for the drive",
        "IGUI_CRV_Awning_Torn": "The awning tore on the move",
    },
    "ContextMenu": {
        "ContextMenu_CRV_Awning_Deploy": "Roll out the awning",
        "ContextMenu_CRV_Awning_Stow": "Roll up the awning",
    },
    "Tooltip": {
        "Tooltip_CRV_Awning_Item": "A roll-out side awning for the CRV's roof rails.<br>Rolled out beside a parked car, it keeps "
                                   "the rain off whoever stands under it.",
        "Tooltip_CRV_Awning_EngineOn": "Turn the engine off first",
        "Tooltip_CRV_Awning_Moving": "The car must be standing still",
        "Tooltip_CRV_Awning_Broken": "The awning is too damaged",
        "Tooltip_CRV_Awning_Inside": "Get out of the car first",
    },
    "Recipes": {"CRVGen1_MakeAwning": "Make CRV Side Awning"},
}

LUA = ["shared/HondaCRVGen1_Awning.lua", "shared/TimedActions/ISCRVAwning.lua", "client/HondaCRVGen1_AwningMenu.lua",
       "server/HondaCRVGen1_AwningRain.lua"]

# camping and car-parts shops; the function feature's FunctionLootRarity scales every CR-V entry
DISTRIBUTIONS = [
    {"list": "CampingStoreTents", "item": "Base." + ITEM_ID, "weight": 1.0},
    {"list": "CampingStoreGear", "item": "Base." + ITEM_ID, "weight": 0.5},
    {"list": "CampingLockers", "item": "Base." + ITEM_ID, "weight": 0.2},
    {"list": "GarageMechanics", "item": "Base." + ITEM_ID, "weight": 0.2},
]
