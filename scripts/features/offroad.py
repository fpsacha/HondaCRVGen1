r"""
Off-road and rear parts for the CR-V (spec/feature-roadmap.md "Off-road", spec/feature-plugins.md):
a snorkel up the right A-pillar, a steel skid plate under the front, a rear steel bumper with a
receiver hitch, a ladder up the right rear quarter to the roof, and two jerry cans (one on the spare
on the tailgate, one in the roof rack basket). Every piece is a bolt-on part that fits any CR-V
script (VEHICLE_PARTS lands in the lifted ones too) and comes off again.

Where each piece sits (measured on the low parts, 2026-10-13, scratch offroad_research/probe*.py):
  * snorkel: the right A-pillar is the body strip between the windscreen and the front door frame;
    BUILD samples it with rays from the right at every 6 cm of height and runs a 84 mm tube 15 mm
    off its outer ridge (clear of the door frame and the mirror's sail), the intake head forward at
    roof height, the lower end bending forward and into the right front fender ahead of the door's
    front edge (y > 0.86: the door turns about x 0.845, y 0.80); two stand-off brackets with clamp
    bands run from the tube to the pillar's painted strip (z 1.24 and 1.46, ~8.5 cm), aimed at the
    strip's middle and refused on the glass (the windscreen's materials live on the body object);
  * skid plate: under the engine between the bull bar's legs (|x| 0.324 inner edge, z 0.28-0.35):
    |x| <= 0.30, flat at z 0.32 (the body's underside is at 0.37-0.39), a front lip standing ~60
    degrees up in front of the bumper's lower valance to z 0.406 (the only face the 30-degree camera
    sees of it: zinc, three slots between four bolts) and a rear kick-up;
  * rear bumper: the gate and the spare on it sweep everything above z 0.608 when the gate swings
    (rig_vehicle: 80 degrees about x 0.69, y -2.11), so the steel bumper is a box beam UNDER that,
    z 0.44-0.586, 12 mm off the plastic bumper's outline (sampled across the back, round the corners
    and along the sides) and wrapping forward round both corners to y -1.90 (13 cm behind the arch
    flares), where it tapers into an angled end cap; a valance plate under the gap to the plastic
    bumper (whose lower half curves away under the beam: ground showed through in side views); a
    diamond-plate step across the back; a 50 mm receiver under it with the ball at y -2.42 (the
    vehicle script's trailer attachment, z -2.42 in mesh metres) and 0.49 m up, two D-ring tabs on
    the rear face with the shackles hanging from their pins, safety chain loops, frame brackets;
  * ladder: the RIGHT rear quarter between the rear door (its trailing edge y -1.29 swings out, not
    back) and the tail lamp (y < -1.80), stiles at y -1.46 / -1.68 (LD_Y), a straight run 3.5-6 cm
    off the side from z 0.84 up, rungs at z 0.93 / 1.15 / 1.37, brackets bolted to the quarter at z
    0.88 and 1.10 on each stile (6.4 x 7 cm plates), its top bent over the roof edge onto the drip
    rail (rubber feet). Its footprint on the right quarter is y -1.712..-1.428 (bracket plates; the
    stiles -1.694..-1.446), z 0.84 up to the roof edge: painted decals there sit under the ladder, as a
    sticker would on the real car. Not the left side: the fuel door is
    there (GasTank area, y -1.55); not the gate: the flip-up glass and the spare would be blocked;
  * tailgate jerry can: the gate has no free space beside the spare (the licence plate recess is
    x -0.61..-0.11, z 0.81..1.08 with the pull handle on top), so the can sits in a holder bolted
    to the spare wheel's centre (the usual spare-mounted can holder), upright, in front of the tyre
    (and of the soft cover when that is fitted). It rides trunk_bone, on the shell sheet;
  * roof can: upright in a holder inside the basket, in its front left corner (2026-10-18): the free
    floor between the cargo's front (the bedroll of loads 2 and 3, y -0.433) and the floor tubes' curve-up
    (y > -0.40), its broad faces across the car; a tray on spacers over the rising floor tubes, a post at
    the outboard end U-clamped round the basket's left frame tube (z 1.755) and top rail (z 1.86), an
    upright at the inboard end, a band round the can. Far from the flip-up glass and the roof strip
    that lifts with it, and wholly inside the roof's outline (outside the left rail it overhung the
    roof edge by ~5 cm).

Texel weights on the Offroad sheet follow what the game camera can see of each face with the car round
it (_seen_weights), not the material alone.

The cans are the vanilla Base.JerryCan (20 L FluidContainer) as the part item: install keeps the
item object in the part, InventoryItem.save writes its FluidContainer (saveEntity), uninstall hands
the same object back (ISUninstallVehiclePart:complete), so the fuel rides along; refuelling stays
vanilla (take the can off, pour it).

Static pieces bake on this feature's own sheet ("offroad", Vehicles_HondaCRVGen1_Offroad.png,
vehiclewheel shader); the gate can rides a bone and bakes on the shell (static meshes only off it).
Accessories are invisible to the bake's rays, so every piece carries its own ambient occlusion as
the acc_shade corner attribute (build_accessories._shade), multiplied in by every material's stack.
"""
import math
import os

KEY = "offroad"
TEX_NAME = "Offroad"
# the feature's materials (one list for every object: material_index = position)
MATS = ["AccOffroadPlastic", "AccOffroadPowder", "AccOffroadBare", "AccOffroadAlu", "AccOffroadCan",
        "AccOffroadChrome", "AccOffroadRubber", "AccOffroadTread"]
PLASTIC, POWDER, BARE, ALU, CAN, CHROME, RUBBER, TREAD = range(len(MATS))
COLOURS = {                                   # linear base colours (the TEXTURED stacks below refine them)
    "AccOffroadPlastic": (0.030, 0.030, 0.032),   # UV-stable black snorkel plastic
    "AccOffroadPowder": (0.040, 0.041, 0.043),    # black powder-coated steel (bumper, holders)
    "AccOffroadBare": (0.26, 0.26, 0.27),         # zinc-plated steel skid plate
    "AccOffroadAlu": (0.40, 0.41, 0.43),          # anodised aluminium ladder
    "AccOffroadCan": (0.055, 0.070, 0.028),       # olive drab NATO can, like the game's own JerryCan.png
    "AccOffroadChrome": (0.55, 0.55, 0.57),       # hitch ball
    "AccOffroadRubber": (0.012, 0.012, 0.013),    # feet, seals, the intake's mesh
    "AccOffroadTread": (0.045, 0.046, 0.048),     # the bumper's tread-plate step
}

SNORKEL, SKID, BUMPER, LADDER = "acc_offroad_snorkel", "acc_offroad_skid", "acc_offroad_bumper", "acc_offroad_ladder"
CAN_GATE, CAN_ROOF = "acc_offroad_can_gate", "acc_offroad_can_roof"
NAMES = [SNORKEL, SKID, BUMPER, LADDER, CAN_GATE, CAN_ROOF]

# ---------------------------------------------------------------------------------------------
# measured placements (metres, model space: +x right, +y forward, +z up, ground 0)

# snorkel
SN_R = 0.045                   # tube radius (a 3.5 inch body)
SN_OFF = 0.015                 # air between the tube and the pillar's outer ridge
SN_Z = (1.12, 1.54)            # the pillar run, sampled every 6 cm (above 1.54 the scan finds the roof)
SN_DOOR_GAP = 0.010            # tube surface ahead of the door frame's front edge
SN_HEAD_Z = 1.68               # intake head centre
SN_FENDER = (0.985, 0.97)      # (y, z) where the body meets the fender side
SN_ENTRY = (1.04, 0.90)        # (y, z) where it goes into the fender
SN_BRACKETS = (1.24, 1.46)     # stand-off brackets to the pillar at these heights
SN_BRACKET_REACH = 0.12        # tube axis to the pillar skin: 8.9 cm measured at both heights (2026-10-14)
# skid plate
SK_X = 0.30
SK_Z = 0.320
SK_T = 0.005
# (y, z): rear kick, flat run, a short bend, then the front lip standing ~60 degrees up in front of the
# bumper's lower valance (its face is at y 1.984 / 2.024 / 2.048 at z 0.36 / 0.38 / 0.40 on the low body,
# the bull bar's legs from |x| 0.32 out): the lip's face is what the 30-degree camera sees of the plate
SK_PROFILE = [(1.04, 0.372), (1.13, SK_Z), (1.990, SK_Z), (2.025, 0.336), (2.066, 0.406)]
SK_BOLTS = (-0.24, -0.08, 0.08, 0.24)   # across the lip; the painted slots sit between them
# rear bumper
RB_Z = (0.440, 0.586)          # under the gate's sweep (0.608) with 2 cm to spare
RB_DEPTH = 0.075               # the beam's depth across the back ...
RB_END_DEPTH = 0.042           # ... and where it wraps forward along the sides (about flush with the arch flares)
RB_GAP = 0.012                 # off the plastic bumper
RB_CORNER = (0.62, -1.98)      # plan centre of the plastic bumper's rear corner (its radius ~0.2 m)
RB_WRAP_Y = -1.90              # the side wraps run forward to here, then taper into the end cap
RB_CAP = 0.032                 # the end cap's length (the beam tapers to RB_CAP_DEPTH over it, angled in)
RB_CAP_DEPTH = 0.010
RB_CHAMFER = (0.025, 0.010)    # the beam's lower and upper rear edge chamfers
RB_VALANCE_T = 0.010           # the plate under the gap between the beam and the plastic bumper
RB_TREAD_T = 0.003
RB_TREAD_X = 0.60              # the step's tread plate along the back
HITCH_Y, BALL_Z = -2.42, 0.490
BALL_R = 0.0254                # 2 inch ball
RECV = (0.0315, 0.383, 0.447)  # receiver half width, bottom, top (2.5 inch tube for a 2 inch shank)
# ladder
LD_Y = (-1.46, -1.68)          # clear of the rear crossbar (y -1.4275) and the tail lamp (y -1.75 at z 1.5)
LD_Z = (0.86, 1.60)
LD_RUNGS = (0.93, 1.15, 1.37)
LD_STILE = 0.028
LD_RUNG_R = 0.0135
LD_CLEAR = 0.035               # stile surface off the body side, at least
# jerry can (NATO 20 l): width, depth, body height, handle rise
JC_W, JC_D, JC_H, JC_HANDLE = 0.345, 0.165, 0.440, 0.030
# roof can (build_can_roof): upright in the basket's front left corner, its tray RC_LOAD_GAP in front of the
# front-most cargo of any load state (the bedroll, y -0.433, measured over x < RC_X_IN + 5 cm), a RC_LIP rim of
# tray round the can, RC_FLOOR_GAP over the floor tubes' highest point under it (they curve up from y -0.40);
# floor tube at the rack's rack_floor z 1.755, top rail at its rack_rail z ~1.860
RC_LOAD_GAP = 0.008
RC_LIP = 0.012
RC_X_IN = -0.07                    # the holder's inboard end, about (the can is 34.5 cm wide from x -0.43)
RC_FLOOR_GAP = 0.004
RC_TOP_RAIL = 1.860
RC_POST = 0.012
BA_TUBE_R = (0.014, 0.011)         # build_accessories.build_roofrack: the frame's floor tube and top rail radii
RC_JAW_GAP, RC_JAW_T = 0.0025, 0.005   # the U-clamps' jaws: air to the tube, plate thickness


def _vec(*a):
    from mathutils import Vector
    return Vector(a)


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
        b.inputs['Roughness'].default_value = 0.35 if name in ("AccOffroadChrome", "AccOffroadAlu") else 0.6
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


def _tree(names, skip_mats=()):
    from mathutils.bvhtree import BVHTree
    import bpy
    verts, polys, tags = [], [], []
    for n in names:
        ob = bpy.data.objects.get(n)
        if ob is None:
            continue
        me = ob.data
        mn = [m.name if m else "?" for m in me.materials]
        base = len(verts)
        verts.extend(ob.matrix_world @ v.co for v in me.vertices)
        for p in me.polygons:
            mat = mn[p.material_index] if mn else "?"
            if mat in skip_mats:
                continue
            polys.append([base + i for i in p.vertices])
            tags.append((n, mat))
    return BVHTree.FromPolygons(verts, polys), tags


def _metal_verts(names, mats=("Metal",)):
    """World positions of the vertices of the named objects' faces in mats (kotris's bare metal parts)."""
    import bpy
    out = []
    for n in names:
        ob = bpy.data.objects.get(n)
        if ob is None:
            continue
        mn = [m.name if m else "?" for m in ob.data.materials]
        ids = {i for p in ob.data.polygons if (mn[p.material_index] if mn else "?") in mats for i in p.vertices}
        out += [ob.matrix_world @ ob.data.vertices[i].co for i in ids]
    return out


def _ray(tree, o, d, dist=6.0):
    from mathutils import Vector
    return tree[0].ray_cast(Vector(o), Vector(d).normalized(), dist)


def _overlaps(ob, names):
    """'name n pairs, ...' for every named object whose faces intersect ob's (BVH overlap), '' if none."""
    import bpy
    from mathutils.bvhtree import BVHTree
    mine = BVHTree.FromPolygons([ob.matrix_world @ v.co for v in ob.data.vertices], [list(p.vertices) for p in ob.data.polygons])
    out = []
    for n in names:
        o = bpy.data.objects.get(n)
        if o is None:
            continue
        t = BVHTree.FromPolygons([o.matrix_world @ v.co for v in o.data.vertices], [list(p.vertices) for p in o.data.polygons])
        k = len(mine.overlap(t))
        if k:
            out.append("%s %d tri pairs" % (n, k))
    return ", ".join(out)


def _ellipse(a, b, n):
    return [(a * math.cos(2 * math.pi * (k + 0.5) / n), b * math.sin(2 * math.pi * (k + 0.5) / n)) for k in range(n)]


def _rrect(a, b, r, seg=2):
    """Rounded rectangle, half sizes a / b, counter-clockwise."""
    pts = []
    for cx, cy, a0 in ((a - r, -b + r, 270.0), (a - r, b - r, 0.0), (-a + r, b - r, 90.0), (-a + r, -b + r, 180.0)):
        for k in range(seg + 1):
            t = math.radians(a0 + 90.0 * k / seg)
            pts.append((cx + r * math.cos(t), cy + r * math.sin(t)))
    return pts


def _sphere(BA, bm, c, r, mat, rings=6, seg=10):
    """A UV sphere as a loft of latitude rings with apex tips (outward, closed)."""
    rs = []
    for i in range(1, rings):
        t = math.pi * i / rings - math.pi / 2
        rs.append([(c[0] + r * math.cos(t) * math.cos(2 * math.pi * k / seg),
                    c[1] + r * math.cos(t) * math.sin(2 * math.pi * k / seg), c[2] + r * math.sin(t)) for k in range(seg)])
    BA._loft(bm, rs, [mat] * (len(rs) - 1), smooth=True, cap_mats=(mat, mat),
             apex=((c[0], c[1], c[2] - r), (c[0], c[1], c[2] + r)))


def _frame_box(BA, bm, o, u, v, w, lo, hi, mat):
    """A box in the frame (o; u, v, w): lo / hi are (u, v, w) corner coordinates."""
    from mathutils import Vector
    pts = []
    for a, b, c in ((lo[0], lo[1], lo[2]), (hi[0], lo[1], lo[2]), (hi[0], hi[1], lo[2]), (lo[0], hi[1], lo[2]),
                    (lo[0], lo[1], hi[2]), (hi[0], lo[1], hi[2]), (hi[0], hi[1], hi[2]), (lo[0], hi[1], hi[2])):
        pts.append(bm.verts.new(Vector(o) + Vector(u) * a + Vector(v) * b + Vector(w) * c))
    quads = ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7))
    faces = [bm.faces.new([pts[i] for i in q]) for q in quads]
    for f in faces:
        f.smooth = False
        f.material_index = mat
    BA._outward(faces)
    return faces


# ---------------------------------------------------------------------------------------------
# the jerry can (NATO pattern) in a local frame: o = centre of its base, u across (width), v through
# (depth), w up. Body with rounded edges, the weld bead round its outline, the pressed X on both
# broad faces, three carry handles across the top and the spout at one top corner.


def _jerrycan(BA, bm, o, u, v, w):
    from mathutils import Vector
    o, u, v, w = Vector(o), Vector(u).normalized(), Vector(v).normalized(), Vector(w).normalized()

    def P(a, b, c):
        return tuple(o + u * a + v * b + w * c)
    a, b, h = JC_W / 2, JC_D / 2, JC_H
    rings = []
    for (inset, hh) in ((0.010, 0.0), (0.0, 0.012), (0.0, h - 0.014), (0.012, h)):
        rings.append([P(x, y, hh) for x, y in _rrect(a - inset, b - inset, 0.016 - inset * 0.6 if inset else 0.016)])
    BA._loft(bm, rings, [CAN, CAN, CAN], smooth=False)
    # weld bead round the outline (in the u-w plane at v = 0), a flat bar 9 mm across, 7 mm thick
    out = []
    for x, z in _rrect(a + 0.002, h / 2 + 0.002, 0.018, 2):
        out.append(P(x, 0.0, z + h / 2))
    BA._sweep(bm, out, BA._rect(0.009, 0.007), ups=[tuple(v)] * len(out), closed=True, smooth=False, mat=CAN)
    # the pressed X on both faces: two diagonal ribs 16 mm wide, standing 4 mm proud
    for s in (-1.0, 1.0):
        for (x0, z0, x1, z1) in ((-a + 0.045, 0.045, a - 0.045, h - 0.060), (a - 0.045, 0.045, -a + 0.045, h - 0.060)):
            pa, pb = P(x0, s * (b - 0.002), z0), P(x1, s * (b - 0.002), z1)
            BA._sweep(bm, [pa, pb], BA._rect(0.016, 0.012), ups=[tuple(v * s)] * 2, smooth=False, mat=CAN)
    # three carry handles across the top (along v), at the side away from the spout
    for x in (-0.115, -0.045, 0.025):
        pts = [P(x, -0.050, h - 0.004), P(x, -0.046, h + JC_HANDLE), P(x, 0.046, h + JC_HANDLE), P(x, 0.050, h - 0.004)]
        BA._sweep(bm, pts, BA._round(0.0085, 6), ups=[tuple(u)] * len(pts), smooth=True, mat=CAN)
    # the spout at the other top corner, leaning out, with its cap
    base = Vector(P(a - 0.060, 0.0, h - 0.010))
    lean = (w * 0.85 + u * 0.53).normalized()
    BA._sweep(bm, [tuple(base), tuple(base + lean * 0.040)], BA._round(0.022, 10), ups=[tuple(v)] * 2, smooth=True, mat=CAN)
    BA._sweep(bm, [tuple(base + lean * 0.036), tuple(base + lean * 0.058)], BA._round(0.026, 10), ups=[tuple(v)] * 2,
              smooth=True, mat=CAN)
    # the cam lever on the spout
    BA._sweep(bm, [tuple(base + lean * 0.050 - u * 0.020 + v * 0.012), tuple(base + lean * 0.020 - u * 0.050 + v * 0.012)],
              BA._rect(0.010, 0.008), ups=[tuple(v)] * 2, smooth=False, mat=CAN)


# ---------------------------------------------------------------------------------------------
# snorkel


def build_snorkel(BA, report):
    from mathutils import Vector
    car = _tree(["body", "door_fr"])
    glass = ("Vitre", "Vitre_noir")
    ridge = []
    for k in range(int(round((SN_Z[1] - SN_Z[0]) / 0.06)) + 1):
        z = SN_Z[0] + 0.06 * k
        # runs of body (not glass) hits from the front back to the door frame; the pillar is the last run
        runs, cur, door_y = [], None, None
        y = 1.05
        while y > -0.2:
            hit = _ray(car, (2.0, y, z), (-1, 0, 0))
            kind = None
            if hit[0] is not None:
                obj, mat = car[1][hit[2]]
                kind = "door" if obj == "door_fr" else ("glass" if mat in glass else "body")
            if kind == "body":
                if cur is None:
                    cur = []
                    runs.append(cur)
                cur.append((hit[0].x, y))
            else:
                cur = None
                if kind == "door" and runs:
                    door_y = y
                    break
            y -= 0.005
        if runs and door_y is not None:
            best = max(runs[-1])
            ymid = (runs[-1][0][1] + runs[-1][-1][1]) / 2.0          # the painted strip's middle (brackets)
            xmid = min(runs[-1], key=lambda q: abs(q[1] - ymid))[0]
            ridge.append((z, best[0], best[1], door_y, ymid, xmid))
            report("FEATURE offroad:   pillar z %.2f: ridge x %.3f at y %.3f (run y %.3f..%.3f), door frame from y %.3f"
                   % (z, best[0], best[1], runs[-1][0][1], runs[-1][-1][1], door_y))
    if len(ridge) < 3:
        raise RuntimeError("FEATURE offroad: the right A-pillar was not found (%d samples)" % len(ridge))
    # a straight run up the pillar: x(z) and y(z) by least squares, then pushed out / forward until the
    # tube clears the ridge by SN_OFF and the door frame's front edge by SN_DOOR_GAP everywhere
    n = len(ridge)
    zm = sum(r[0] for r in ridge) / n

    def fit(idx):
        vm = sum(r[idx] for r in ridge) / n
        sl = sum((r[0] - zm) * (r[idx] - vm) for r in ridge) / sum((r[0] - zm) ** 2 for r in ridge)
        return lambda z: vm + sl * (z - zm)
    fx, fy = fit(1), fit(2)
    dx = max(r[1] + SN_OFF + SN_R - fx(r[0]) for r in ridge)
    dy = max([(r[3] + SN_R + SN_DOOR_GAP) - fy(r[0]) for r in ridge if r[3] is not None] + [0.0])

    def axis(z):
        return Vector((fx(z) + dx, fy(z) + dy, z))
    bm = __import__("bmesh").new()
    z0, z1 = SN_Z[0], SN_HEAD_Z - 0.02
    # the lower end: from the pillar foot forward and down along the fender side, then into the fender
    fend = _tree(["body"], glass)
    hit = _ray(fend, (2.0, SN_FENDER[0], SN_FENDER[1]), (-1, 0, 0))
    fx_side = hit[0].x if hit[0] is not None else 0.84
    hit2 = _ray(fend, (2.0, SN_ENTRY[0], SN_ENTRY[1]), (-1, 0, 0))
    fx_entry = hit2[0].x if hit2[0] is not None else 0.85
    p_foot = axis(z0)
    p_side = Vector((fx_side + SN_R + 0.010, SN_FENDER[0], SN_FENDER[1]))   # (6 mm: the tube's inside lay on the
                                                                             # fender just above, 16 cm2 of z-fight)
    p_in = Vector((fx_entry + SN_R * 0.55, SN_ENTRY[0], SN_ENTRY[1]))
    p_end = Vector((fx_entry - 0.03, SN_ENTRY[0] + 0.02, SN_ENTRY[1] - 0.04))
    path = [p_end, p_in, p_side, p_foot.lerp(p_side, 0.35) + Vector((0.004, 0.0, 0.0)), p_foot]
    zs = [z0 + (z1 - z0) * k / 4 for k in range(1, 5)]
    path += [axis(z) for z in zs]
    prof = _ellipse(SN_R, SN_R * 0.82, 12)
    BA._sweep(bm, [tuple(p) for p in path], prof, smooth=True, mat=PLASTIC)
    # the flange where the body enters the fender: a thin oval plate on the panel
    # its face stands 4 mm off the outermost skin under it (the fender bulges round the entry point: with
    # the face 9 mm off the entry point alone, 14 cm2 of it lay within 1.5 mm of the skin, a z-fight;
    # 2026-10-17 review ACC-9)
    nrm = Vector((1.0, 0.0, 0.0))
    c = Vector((fx_entry + 0.003, SN_ENTRY[0] - 0.005, SN_ENTRY[1] + 0.012))
    skin = [fx_entry]
    for ey, ez in [(0.0, 0.0)] + [(f * 0.075 * math.cos(a), f * 0.060 * math.sin(a)) for f in (0.5, 1.0)
                                  for a in (2 * math.pi * k / 12 for k in range(12))]:
        h_ = _ray(fend, (2.0, c.y + ey, c.z + ez), (-1, 0, 0))
        if h_[0] is not None and abs(h_[0].x - fx_entry) < 0.05:
            skin.append(h_[0].x)
    x_face = max(c.x + 0.006, max(skin) + 0.004)
    BA._sweep(bm, [(fx_entry - 0.004, c.y, c.z), (x_face, c.y, c.z)], _ellipse(0.075, 0.060, 14), ups=[(0, 0, 1)] * 2,
              smooth=False, mat=RUBBER)
    # the intake head: a forward-facing ram head on top of the tube, its mouth recessed and dark
    top = axis(z1)
    hc = top + Vector((0.0, 0.035, SN_HEAD_Z - z1))
    hw, hh = 0.060, 0.050
    y_back, y_front = hc.y - 0.085, hc.y + 0.095
    ring = lambda y, s, dz=0.0: [(hc.x + x * s, y, hc.z + dz + z * s) for x, z in _rrect(hw, hh, 0.030, 3)]
    BA._loft(bm, [ring(y_back, 0.80), ring(y_back + 0.030, 1.0), ring(y_front - 0.012, 1.0), ring(y_front, 1.06),
                  ring(y_front + 0.004, 0.86), ring(y_front - 0.020, 0.80)],
             [PLASTIC, PLASTIC, PLASTIC, PLASTIC, RUBBER], cap_mats=(PLASTIC, RUBBER))
    # the tube's top elbow into the head's underside
    BA._sweep(bm, [tuple(top - Vector((0, 0, 0.02))), tuple(hc - Vector((0.0, 0.03, 0.0)))], prof, smooth=True, mat=PLASTIC)
    # stand-off brackets to the pillar: a 6 mm plate on edge (30 mm tall) from the tube's axis to the
    # pillar's painted strip, aimed at the strip's middle at that height (between the windscreen's frit
    # and the door frame), else at the ridge. The car tree holds the glass (it lives on the body object):
    # a hit on glass, on the door or further than SN_BRACKET_REACH drops the bracket; a pure -x ray from
    # the tube crossed the windscreen and laid two blades on the glass (2026-10-14 review). Each bracket
    # ends 6 mm inside the pillar skin, with a clamp band round the tube
    brackets, placed = 0, []
    for z in SN_BRACKETS:
        p = axis(z)
        aims = []
        lo = [r for r in ridge if r[0] <= z]
        hi = [r for r in ridge if r[0] >= z]
        if lo and hi:
            a_, b_ = lo[-1], hi[0]
            f = 0.0 if b_[0] == a_[0] else (z - a_[0]) / (b_[0] - a_[0])
            aims.append(Vector((a_[5] + (b_[5] - a_[5]) * f, a_[4] + (b_[4] - a_[4]) * f, z)))   # the strip's middle
        aims.append(Vector((fx(z), fy(z), z)))                                                   # the ridge fit
        for aim in aims:
            d = aim - p
            d.z = 0.0
            if d.length < 1e-6:
                continue
            d.normalize()
            hit = _ray(car, tuple(p), tuple(d), SN_BRACKET_REACH)
            if hit[0] is None:
                continue
            obj, mat = car[1][hit[2]]
            if obj != "body" or mat in glass:
                continue
            end = hit[0] + d * 0.006
            BA._sweep(bm, [tuple(p), tuple(end)], BA._rect(0.006, 0.030), ups=[(0, 0, 1)] * 2, smooth=False, mat=POWDER)
            t = (axis(z + 0.0125) - axis(z - 0.0125)).normalized()
            BA._sweep(bm, [tuple(p - t * 0.0125), tuple(p + t * 0.0125)], BA._round(SN_R + 0.004, 14), smooth=False,
                      mat=POWDER)
            placed.append("z %.2f -> (%.3f, %.3f) %s %.1f cm" % (z, hit[0].x, hit[0].y, mat, (hit[0] - p).length * 100))
            brackets += 1
            break
        else:
            report("FEATURE offroad: warning snorkel bracket at z %.2f found no pillar paint within %.0f cm"
                   % (z, SN_BRACKET_REACH * 100))
    ob = _obj(SNORKEL, bm)
    worst = min(r[1] for r in ridge)
    report("FEATURE offroad: %s %d tris, pillar sampled at %d heights (ridge x %.3f..%.3f, y %.3f..%.3f), tube pushed "
           "out %.3f / forward %.3f, %d brackets on the pillar (%s), fender entry x %.3f"
           % (SNORKEL, BA.tris(ob), n, worst, max(r[1] for r in ridge), min(r[2] for r in ridge), max(r[2] for r in ridge),
              dx, dy, brackets, "; ".join(placed), fx_entry))
    return ob


# ---------------------------------------------------------------------------------------------
# skid plate


def build_skid(BA, report):
    import bmesh
    from mathutils import Vector
    bm = bmesh.new()
    # the bent sheet: the (y, z) profile offset both ways along its normal by half the thickness (the lip
    # stands steep: a vertical offset would thin it to a sliver), swept across x
    top, bot = [], []
    m = len(SK_PROFILE)
    for i, (y, z) in enumerate(SK_PROFILE):
        ya, za = SK_PROFILE[max(0, i - 1)]
        yb, zb = SK_PROFILE[min(m - 1, i + 1)]
        ty, tz = yb - ya, zb - za
        ln = math.hypot(ty, tz)
        ny, nz = -tz / ln, ty / ln                        # the side facing up (into the car)
        k = 1.0
        if 0 < i < m - 1:                                 # mitre at the bends
            t1 = (y - ya, z - za)
            t2 = (yb - y, zb - z)
            c = (t1[0] * t2[0] + t1[1] * t2[1]) / (math.hypot(*t1) * math.hypot(*t2))
            k = 1.0 / max(0.5, math.sqrt((1.0 + c) / 2.0))
        top.append((y + ny * SK_T / 2 * k, z + nz * SK_T / 2 * k))
        bot.append((y - ny * SK_T / 2 * k, z - nz * SK_T / 2 * k))
    prof = [(y, z) for y, z in bot] + [(y, z) for y, z in reversed(top)]
    left = [bm.verts.new((-SK_X, y, z)) for y, z in prof]
    right = [bm.verts.new((SK_X, y, z)) for y, z in prof]
    faces = [bm.faces.new(left[::-1]), bm.faces.new(right)]
    m = len(prof)
    for i in range(m):
        faces.append(bm.faces.new((left[i], left[(i + 1) % m], right[(i + 1) % m], right[i])))
    for f in faces:
        f.material_index = BARE
        f.smooth = False
    BA._outward(faces)
    # folded side flanges along the flat run, 25 mm up
    for s in (-1.0, 1.0):
        x = s * (SK_X - 0.002)
        BA._slab(bm, [(x, 1.15, SK_Z), (x, 1.94, SK_Z), (x, 1.93, SK_Z + 0.025), (x, 1.16, SK_Z + 0.025)],
                 (1.0, 0.0, 0.0), 0.004, mat=BARE)
    # brackets up to the underside (hidden), bolt heads on the lip and along the sides
    for x in (-0.22, 0.22):
        for y in (1.22, 1.86):
            BA._box(bm, (x - 0.015, y - 0.015, SK_Z), (x + 0.015, y + 0.015, 0.392), mat=POWDER)
    # bolt heads across the standing lip (its outer face looks forward and down: the face the camera sees)
    (y0, z0), (y1, z1) = SK_PROFILE[-2], SK_PROFILE[-1]
    lip_n = Vector((0.0, (z1 - z0), -(y1 - y0))).normalized()
    if lip_n.y < 0:
        lip_n = -lip_n
    for x in SK_BOLTS:
        c = Vector((x, y0 + (y1 - y0) * 0.62, z0 + (z1 - z0) * 0.62)) + lip_n * (SK_T / 2)
        BA._sweep(bm, [tuple(c - lip_n * 0.002), tuple(c + lip_n * 0.005)], BA._round(0.009, 6), ups=[(1, 0, 0)] * 2,
                  smooth=False, mat=POWDER)
    ob = _obj(SKID, bm)
    report("FEATURE offroad: %s %d tris, |x| <= %.2f at z %.3f, y %.2f..%.2f, lip up to z %.3f at y %.3f (%.0f deg)"
           % (SKID, BA.tris(ob), SK_X, SK_Z, SK_PROFILE[0][0], SK_PROFILE[-1][0], z1, y1,
              math.degrees(math.atan2(z1 - z0, y1 - y0))))
    return ob


# ---------------------------------------------------------------------------------------------
# rear bumper and hitch


def _rear_outline(car, s):
    """The plastic bumper's plan outline on side s (+1 right, -1 left) pushed out by RB_GAP, as
    [(x, y, phi)] from the middle of the back round the corner and forward along the side to
    RB_WRAP_Y + RB_CAP (phi 0 along the back, 90 along the side, 91 the end cap's point). Every point
    is the outermost hit over the beam's height: rays from behind across the back, rays in toward the
    corner's centre every 7.5 degrees round it, rays from the side along it."""
    from mathutils import Vector
    zs = [RB_Z[0] + (RB_Z[1] + 0.010 - RB_Z[0]) * k / 8 for k in range(9)]
    cx, cy = s * RB_CORNER[0], RB_CORNER[1]

    def outermost(origin, d, keep=lambda h: True):
        best = None
        for z in zs:
            o = Vector((origin[0], origin[1], z))
            hit = _ray(car, tuple(o), tuple(d), 2.5)
            if hit[0] is None or not keep(hit[0]):
                continue
            if best is None or hit[3] < best[0]:
                best = (hit[3], hit[0])
        return best[1] if best else None
    out = []
    for k in range(8):                                    # the back, x 0 .. the corner
        x = cx * k / 8
        hit = outermost((x, -3.5), Vector((0.0, 1.0, 0.0)), lambda h: h.y < -1.85)
        y = hit.y if hit is not None else -2.10
        out.append((x, y - RB_GAP, 0.0))
    for k in range(13):                                   # round the corner
        phi = 7.5 * k
        d = Vector((s * math.sin(math.radians(phi)), -math.cos(math.radians(phi)), 0.0))
        hit = outermost((cx + d.x * 1.2, cy + d.y * 1.2), -d)
        if hit is None:
            continue
        r = Vector((hit.x - cx, hit.y - cy, 0.0)).dot(d) + RB_GAP
        out.append((cx + d.x * r, cy + d.y * r, phi))
    n = max(1, int(round((RB_WRAP_Y - cy) / 0.025)))
    side = []
    for y, phi in [(cy + (RB_WRAP_Y - cy) * k / n, 90.0) for k in range(1, n + 1)] + [(RB_WRAP_Y + RB_CAP, 91.0)]:
        hit = outermost((s * 2.0, y), Vector((-s, 0.0, 0.0)), lambda h: abs(h.x) > 0.6)   # along the side,
        if hit is not None:                                                                # then the end cap
            side.append((hit.x + s * RB_GAP, y, phi))
    # the back: keep it convex toward the rear (the bumper's facets would kink the beam)
    back = [p for p in out if p[2] == 0.0 and abs(p[0]) < abs(cx) - 1e-6]
    sm = [(x, min(back[j][1] for j in range(max(0, i - 1), min(len(back), i + 2))), 0.0) for i, (x, _y, _p) in enumerate(back)]
    return sm + [p for p in out if not (p[2] == 0.0 and abs(p[0]) < abs(cx) - 1e-6)] + side


def _plan_frames(path):
    """(side, mitre) per point of a horizontal plan path: side = up x the mitred tangent (toward the car
    on a path running anticlockwise round it seen from above), mitre = 1 / cos of half the bend, as in
    build_accessories._sweep."""
    from mathutils import Vector
    pts = [Vector(p) for p in path]
    up = Vector((0.0, 0.0, 1.0))
    out = []
    for i, p in enumerate(pts):
        a = (p - pts[i - 1]).normalized() if i > 0 else None
        b = (pts[i + 1] - p).normalized() if i < len(pts) - 1 else None
        a = a if a is not None else b
        b = b if b is not None else a
        t = (a + b).normalized() if (a + b).length > 1e-6 else b
        out.append((up.cross(t).normalized(), 1.0 / max(0.35, a.dot(t))))
    return out


def _plan_rings(path, sections):
    """World rings of a beam swept along a horizontal plan path with a section per point ([(side, up)]
    in _plan_frames' frame), mitred at every bend: build_accessories._loft makes the solid."""
    from mathutils import Vector
    up = Vector((0.0, 0.0, 1.0))
    return [[tuple(Vector(p) + side * (sa * k) + up * sb) for sa, sb in sec]
            for p, (side, k), sec in zip(path, _plan_frames(path), sections)]


def _interp(pts, x):
    """y at x on a polyline [(x, y)] sorted by x."""
    for (xa, ya), (xb, yb) in zip(pts, pts[1:]):
        if xa <= x <= xb:
            return ya + (yb - ya) * (x - xa) / max(1e-9, xb - xa)
    return pts[0][1] if x < pts[0][0] else pts[-1][1]


def build_bumper(BA, report):
    import bmesh
    from mathutils import Vector
    car = _tree(["body"], ("Vitre", "Vitre_noir"))
    h = RB_Z[1] - RB_Z[0]
    # the plan path: from the left end cap, back along the left side, round the corner, across the back
    # and round to the right end cap (anticlockwise seen from above: the section's side points at the car)
    left, right = _rear_outline(car, -1.0), _rear_outline(car, 1.0)
    plan = list(reversed(left)) + right[1:]
    path = [(x, y, RB_Z[0]) for x, y, _phi in plan]

    def depth(phi):
        if phi > 90.5:
            return RB_CAP_DEPTH
        return RB_DEPTH + (RB_END_DEPTH - RB_DEPTH) * min(1.0, phi / 90.0)

    def beam(d):
        c1, c2 = min(RB_CHAMFER[0], 0.4 * d), min(RB_CHAMFER[1], 0.3 * d)
        return [(-d, c1), (-d + c1, 0.0), (0.0, 0.0), (0.0, h), (-d + c2, h), (-d, h - c2)]
    bm = bmesh.new()
    BA._loft(bm, _plan_rings(path, [beam(depth(phi)) for _x, _y, phi in plan]), [POWDER] * (len(path) - 1))
    # the valance: a plate from inside the beam forward under the plastic bumper, which curves away
    # under the beam's front face (a 2-6 cm wedge to the ground in side views), so the gap between
    # them has a floor. Its front edge per point: where the body's underside comes down to within
    # 4 cm of the plate, plus 2 cm under it (walked in 1 cm steps toward the car)
    full = [i for i, (_x, _y, phi) in enumerate(plan) if phi <= 90.5]
    frames = _plan_frames(path)
    reach = []
    for i in full:
        f = 0.20
        side = frames[i][0]
        for k in range(1, 26):
            qx, qy = path[i][0] + side.x * 0.01 * k, path[i][1] + side.y * 0.01 * k
            hit = _ray(car, (qx, qy, 0.25), (0, 0, 1), 1.0)
            if hit[0] is not None and hit[0].z < RB_Z[0] + RB_VALANCE_T + 0.040:
                f = 0.01 * k + 0.020
                break
        reach.append(f)
    reach = [max(reach[max(0, j - 1):j + 2]) for j in range(len(reach))]
    vpath = [path[i] for i in full]
    BA._loft(bm, _plan_rings(vpath, [[(-0.012, 0.001), (f, 0.001), (f, 0.001 + RB_VALANCE_T), (-0.012, 0.001 + RB_VALANCE_T)]
                                     for f in reach]), [POWDER] * (len(vpath) - 1))
    # the step's tread plate across the back (to where the corners start), 4 mm in from the edges
    tread = [i for i, (_x, _y, phi) in enumerate(plan) if phi == 0.0]
    tp = [(path[i][0], path[i][1], RB_Z[1]) for i in tread]
    c2 = RB_CHAMFER[1]
    BA._loft(bm, _plan_rings(tp, [[(-RB_DEPTH + c2 + 0.004, -0.001), (-0.006, -0.001), (-0.006, RB_TREAD_T),
                                   (-RB_DEPTH + c2 + 0.004, RB_TREAD_T)]] * len(tp)), [TREAD] * (len(tp) - 1))
    # D-ring tabs standing on the rear face, a pin across each and the shackle hanging from it
    back = sorted((x, y) for x, y, phi in plan if phi == 0.0)
    ymid = min(back, key=lambda q: abs(q[0]))[1]
    zp = RB_Z[0] + 0.075
    for s in (-1.0, 1.0):
        x = s * 0.52
        yb = _interp(back, x) - RB_DEPTH
        BA._box(bm, (x - 0.006, yb - 0.045, RB_Z[0] + 0.040), (x + 0.006, yb + 0.012, RB_Z[0] + 0.110), mat=POWDER)
        BA._sweep(bm, [(x - 0.027, yb - 0.026, zp), (x + 0.027, yb - 0.026, zp)], BA._round(0.0075, 8), ups=[(0, 0, 1)] * 2,
                  smooth=False, mat=CHROME)
        bow = [(x - 0.021, yb - 0.026, zp), (x - 0.021, yb - 0.026, zp - 0.036), (x - 0.012, yb - 0.026, zp - 0.060),
               (x + 0.012, yb - 0.026, zp - 0.060), (x + 0.021, yb - 0.026, zp - 0.036), (x + 0.021, yb - 0.026, zp)]
        BA._sweep(bm, bow, BA._round(0.0075, 6), ups=[(0, 1, 0)] * len(bow), smooth=True, mat=POWDER)
    # frame brackets forward under the floor and the receiver's cross tube. Each is grown to wrap kotris's
    # stock tow loop there (a Metal ring round y -2.004) with 3 mm to spare: its faces lay within 1.5 mm
    # of the bracket's sides, 131 cm2 of z-fight (2026-10-17 review ACC-9)
    loop = _metal_verts(("body",))
    for s in (-1.0, 1.0):
        lo_, hi_ = [s * 0.45 - 0.022, -1.90, 0.432], [s * 0.45 + 0.022, ymid + 0.04, 0.470]
        ring = [p for p in loop if abs(p.x - s * 0.45) < 0.06 and abs(p.z - 0.451) < 0.05 and -2.06 < p.y < -1.88]
        if ring:
            lo_[0] = min(lo_[0], min(p.x for p in ring) - 0.003)
            hi_[0] = max(hi_[0], max(p.x for p in ring) + 0.003)
            lo_[2] = min(lo_[2], min(p.z for p in ring) - 0.003)
            hi_[2] = max(hi_[2], max(p.z for p in ring) + 0.003)
        BA._box(bm, tuple(lo_), tuple(hi_), mat=POWDER)
    BA._box(bm, (-0.47, -1.98, 0.405), (0.47, -1.92, 0.456), mat=POWDER)   # (top 0.462 lay 1.7 mm under the floor)
    # receiver: a square tube from under the floor out past the beam, its collar and the pin
    hw, zb, zt = RECV
    y_mouth = ymid - RB_DEPTH - 0.025
    BA._box(bm, (-hw, -1.95, zb), (hw, y_mouth, zt), mat=POWDER)
    BA._box(bm, (-hw - 0.006, y_mouth, zb - 0.006), (hw + 0.006, y_mouth + 0.030, zt + 0.006), mat=POWDER)
    BA._sweep(bm, [(-hw - 0.018, y_mouth + 0.050, (zb + zt) / 2), (hw + 0.018, y_mouth + 0.050, (zb + zt) / 2)],
              BA._round(0.008, 6), ups=[(0, 0, 1)] * 2, smooth=False, mat=CHROME)
    # safety chain loops under the beam beside the receiver
    for s in (-1.0, 1.0):
        x0, x1 = s * 0.060, s * 0.105
        loop = [(x0, ymid - 0.045, RB_Z[0] + 0.004), (x0, ymid - 0.045, RB_Z[0] - 0.030),
                (x1, ymid - 0.045, RB_Z[0] - 0.030), (x1, ymid - 0.045, RB_Z[0] + 0.004)]
        BA._sweep(bm, loop, BA._round(0.0065, 6), ups=[(0, 1, 0)] * 4, smooth=True, mat=POWDER)
    # ball mount: the shank in the receiver, the tongue, the ball on its neck with the nut under it
    sw = 0.025
    BA._box(bm, (-sw, y_mouth + 0.12, zb + 0.007), (sw, HITCH_Y + 0.040, zt - 0.007), mat=POWDER)
    BA._box(bm, (-0.038, HITCH_Y + 0.045, BALL_Z - 0.062), (0.038, HITCH_Y - 0.042, BALL_Z - 0.040), mat=POWDER)
    BA._sweep(bm, [(0, HITCH_Y, BALL_Z - 0.071), (0, HITCH_Y, BALL_Z - 0.060)], BA._round(0.021, 6), ups=[(0, 1, 0)] * 2,
              smooth=False, mat=CHROME)
    BA._sweep(bm, [(0, HITCH_Y, BALL_Z - 0.041), (0, HITCH_Y, BALL_Z - 0.012)], BA._round(0.016, 10), ups=[(0, 1, 0)] * 2,
              smooth=True, mat=CHROME)
    _sphere(BA, bm, (0.0, HITCH_Y, BALL_Z), BALL_R, CHROME, rings=7, seg=12)
    ob = _obj(BUMPER, bm)
    report("FEATURE offroad: %s %d tris, beam z %.3f..%.3f, rear face y %.3f at the middle (plastic bumper %.3f), "
           "receiver mouth y %.3f, ball (0, %.3f, %.3f) r %.4f"
           % (BUMPER, BA.tris(ob), RB_Z[0], RB_Z[1], ymid - RB_DEPTH, ymid + RB_GAP, y_mouth, HITCH_Y, BALL_Z, BALL_R))
    return ob


# ---------------------------------------------------------------------------------------------
# ladder


def build_ladder(BA, report):
    import bmesh
    from mathutils import Vector
    car = _tree(["body"])

    def side_x(y, z):
        hit = _ray(car, (2.0, y, z), (-1, 0, 0))
        return hit[0].x if hit[0] is not None else 0.0
    zs = [LD_Z[0] + (LD_Z[1] - LD_Z[0]) * k / 15 for k in range(16)]
    # a straight line x = a + b z in each stile's plane: through the side's offsets at the bottom and the top,
    # pushed out until every sample clears LD_CLEAR (+ half the stile)
    need = LD_CLEAR + LD_STILE / 2
    xb = max(side_x(y, zs[0]) for y in LD_Y) + need
    xt = max(side_x(y, zs[-1]) for y in LD_Y) + need
    b = (xt - xb) / (zs[-1] - zs[0])
    a = xb - b * zs[0]
    push = max(max(side_x(y, z) for y in LD_Y) + need - (a + b * z) for z in zs)
    a += max(0.0, push)

    def lx(z):
        return a + b * z
    bm = bmesh.new()
    roof = []
    for y in LD_Y:
        # top: bend over the roof edge onto the drip rail (the highest point of the roof edge band)
        rz, rx = 0.0, 0.56
        for x in (0.53, 0.55, 0.57, 0.59, 0.61):
            hit = _ray(car, (x, y, 3.0), (0, 0, -1))
            if hit[0] is not None and hit[0].z > rz:
                rz, rx = hit[0].z, x
        roof.append((rx, rz))
        ztop = LD_Z[1]
        pts = [(lx(LD_Z[0] - 0.02), y, LD_Z[0] - 0.02), (lx(ztop), y, ztop),
               (lx(ztop) - 0.020, y, ztop + 0.050), (rx + 0.050, y, rz + 0.050), (rx + 0.012, y, rz + 0.030)]
        BA._sweep(bm, pts, BA._rect(LD_STILE, LD_STILE), ups=[(0, 1, 0)] * len(pts), smooth=False, mat=ALU)
        # rubber foot on the rail and the end caps of the stile's bottom
        BA._box(bm, (rx - 0.012, y - 0.0185, rz - 0.004), (rx + 0.022, y + 0.0185, rz + 0.030), mat=RUBBER)   # (a side
                                                                     # at y -1.660 lay on the roof strip's end face)
        # brackets bolted to the quarter panel: bottom and under the glass
        for z in (LD_Z[0] + 0.02, 1.10):
            sx = side_x(y, z)
            # the plate on the outermost skin under its corners (the quarter curves: on the centre's alone a
            # corner lay within 1.5 mm of the skin, 22 cm2 of z-fight; 2026-10-17 review ACC-9)
            sxm = max([sx] + [side_x(y + dy, z + dz) for dy in (-0.032, 0.032) for dz in (-0.035, 0.035)])
            BA._box(bm, (sx - 0.004, y - 0.018, z - 0.022), (lx(z) - LD_STILE / 2 + 0.003, y + 0.018, z + 0.022), mat=POWDER)
            sxn = min([sx] + [side_x(y + dy, z + dz) for dy in (-0.032, 0.032) for dz in (-0.035, 0.035)])
            x_in, x_out = sxn - 0.004, sxm + 0.004        # (from the innermost: the skin dips under the plate too)
            xc_, th_ = (x_in + x_out) / 2, x_out - x_in
            BA._slab(bm, [(xc_, y - 0.032, z - 0.035), (xc_, y + 0.032, z - 0.035),
                          (xc_, y + 0.032, z + 0.035), (xc_, y - 0.032, z + 0.035)], (1, 0, 0), th_, mat=POWDER)
    # rungs: knurled round tube, ends inside the stiles
    for z in LD_RUNGS:
        x = lx(z)
        BA._sweep(bm, [(x, LD_Y[0] - 0.004, z), (x, LD_Y[1] + 0.004, z)], BA._round(LD_RUNG_R, 8),
                  ups=[(0, 0, 1)] * 2, smooth=True, mat=ALU)
    ob = _obj(LADDER, bm)
    clear = min(lx(z) - LD_STILE / 2 - max(side_x(y, z) for y in LD_Y) for z in zs)
    report("FEATURE offroad: %s %d tris, stiles at y %.2f / %.2f, x %.3f at z %.2f -> %.3f at z %.2f, min clearance %.1f cm, "
           "feet on the roof edge at z %.3f / %.3f" % (LADDER, BA.tris(ob), LD_Y[0], LD_Y[1], lx(LD_Z[0]), LD_Z[0], lx(LD_Z[1]),
                                                       LD_Z[1], clear * 100, roof[0][1], roof[1][1]))
    return ob


# ---------------------------------------------------------------------------------------------
# jerry cans and their holders


def build_can_gate(BA, report):
    import bmesh
    import bpy
    from mathutils import Vector
    trunk = bpy.data.objects.get("trunk")
    if trunk is None:
        raise RuntimeError("FEATURE offroad: no trunk object for the tailgate can")
    c, ax, _u, _v, tr = BA._spare_frame(trunk)
    face_t = max(t for t, r in tr)
    cover_t = face_t + 0.014                            # build_spare_cover's face (F)
    w = Vector((0.0, 0.0, 1.0)) - ax * ax.z
    w.normalize()
    u = ax.cross(w).normalized()
    t_back = cover_t + 0.030                            # the can's back face, clear of the cover
    bm = bmesh.new()
    # hub plate on the wheel's centre, under the cover's face when it is fitted (it ends 3 mm short of it and
    # 4 mm in front of the spare's centre cap, t 0.111: 6 mm short lay 1 mm off the cap),
    # and the arm out of the cover's middle to the back frame. The plate used to run 1 cm through the
    # cover's face, an 11 cm block spearing the vinyl (2026-10-17 review ACC-7); the 6 cm arm alone now
    # crosses it, as a post through the cover's centre hole
    _frame_box(BA, bm, c, u, ax, w, (-0.055, face_t + 0.002, -0.055), (0.055, cover_t - 0.003, 0.055), POWDER)
    _frame_box(BA, bm, c, u, ax, w, (-0.030, cover_t - 0.005, -0.030), (0.030, t_back - 0.006, 0.030), POWDER)
    _frame_box(BA, bm, c, u, ax, w, (-JC_W / 2 - 0.010, t_back - 0.006, -0.235), (JC_W / 2 + 0.010, t_back, 0.180), POWDER)
    base_h = -0.230                                      # the can's base below the wheel's centre
    # tray, side straps, the clamp bar across the handles
    _frame_box(BA, bm, c, u, ax, w, (-JC_W / 2 - 0.010, t_back - 0.006, base_h - 0.008),
               (JC_W / 2 + 0.010, t_back + JC_D + 0.012, base_h), POWDER)
    _frame_box(BA, bm, c, u, ax, w, (-JC_W / 2 - 0.010, t_back + JC_D, base_h - 0.008),
               (JC_W / 2 + 0.010, t_back + JC_D + 0.012, base_h + 0.050), POWDER)
    for s in (-1.0, 1.0):
        x0 = s * (JC_W / 2 + 0.002)
        x1 = s * (JC_W / 2 + 0.010)
        _frame_box(BA, bm, c, u, ax, w, (min(x0, x1), t_back - 0.006, base_h), (max(x0, x1), t_back + 0.025, base_h + 0.30), POWDER)
    hb = base_h + JC_H + JC_HANDLE * 0.6
    _frame_box(BA, bm, c, u, ax, w, (-JC_W / 2 - 0.010, t_back - 0.006, hb), (JC_W / 2 + 0.010, t_back + 0.030, hb + 0.012), POWDER)
    _frame_box(BA, bm, c, u, ax, w, (-0.012, t_back + 0.030, hb - 0.004), (0.012, t_back + 0.048, hb + 0.016), CHROME)
    o = c + ax * (t_back + JC_D / 2) + w * base_h
    _jerrycan(BA, bm, o, u, ax, w)
    ob = _obj(CAN_GATE, bm)
    report("FEATURE offroad: %s %d tris, on the spare (centre %.3f, %.3f, %.3f; axle %.2f, %.2f, %.2f), back face t %.3f "
           "(cover face %.3f), base z %.3f" % (CAN_GATE, BA.tris(ob), c.x, c.y, c.z, ax.x, ax.y, ax.z, t_back, cover_t,
                                                (c + w * base_h).z))
    return ob


def build_can_roof(BA, report):
    """The roof can stands INSIDE the basket, upright in its front left corner (2026-10-18, round 3): on a
    tray between the bedroll's front (the cargo states' front-most piece, y -0.433) and the floor tubes'
    curve-up, its broad faces across the car, a post at its outboard end U-clamped round the basket's left
    frame tube and top rail, an upright at its inboard end and a band round it. Outside the left rail
    (until round 3) it overhung the roof edge by ~5 cm: the can is 16.5 cm deep and only ~13 cm lie between
    the rail and the edge. Behind the basket (until 2026-10-17) the roof strip that lifts with the rear glass
    swung up through it. Every box is axis-aligned: the can's width runs along +x, its depth along +y."""
    import bmesh
    import bpy
    rack = bpy.data.objects.get("acc_roofrack")
    zf = (rack.get("rack_floor") if rack is not None else None) or 1.755
    zt = (rack.get("rack_rail") if rack is not None else None) or RC_TOP_RAIL    # the top rail's centre

    rtree = _tree(["acc_roofrack"])

    def tube_axis(zc, r):
        """The left side tube near height zc (radius r) where a clamp at y grips it, measured with rays across it:
        its centre (x, z) and half extents. The straight run is not quite parallel to the car (the top rail's
        axis x -0.475 at the front end, -0.464 at the back), so -RK_XW put a jaw through it."""
        def at(yy):
            def hit(o, d):
                h = _ray(rtree, o, d, 0.2)
                return h[0] if h[0] is not None else None
            xo = hit((-0.62, yy, zc), (1, 0, 0))
            xi = hit((-0.445, yy, zc), (-1, 0, 0))                # inboard of the tube, outboard of the floor's tubes
            if xo is None or xi is None:
                return -BA.RK_XW, zc, r, r
            xc_ = (xo.x + xi.x) / 2
            zu = hit((xc_, yy, zc + 0.08), (0, 0, -1))
            zd = hit((xc_, yy, zc - 0.08), (0, 0, 1))
            if zu is None or zd is None:
                return xc_, zc, (xi.x - xo.x) / 2, r
            return xc_, (zu.z + zd.z) / 2, (xi.x - xo.x) / 2, (zu.z - zd.z) / 2
        return at
    axes = (tube_axis(zf, BA_TUBE_R[0]), tube_axis(zt, BA_TUBE_R[1]))

    # where it stands: behind the floor tubes' curve-up, in front of the cargo. The front-most cargo is the
    # bedroll of loads 2 and 3 (y -0.433, x +-0.35); load 3's ratchet straps hook over the rails at y -0.78 and
    # -1.455, behind it. Measured on the built loads (any state), over the holder's width
    y_cargo = -0.433
    loads = [bpy.data.objects.get(n) for n in BA.LOAD_NAMES]
    ys = [(o.matrix_world @ v.co).y for o in loads if o is not None for v in o.data.vertices
          if (o.matrix_world @ v.co).x < RC_X_IN + 0.05]
    if ys:
        y_cargo = max(ys)
    y0 = y_cargo + RC_LOAD_GAP                                     # the tray's rear edge
    yc = y0 + RC_LIP + JC_D / 2                                    # the can's centre (and the clamps')
    y1 = yc + JC_D / 2 + RC_LIP                                    # the tray's front edge
    # the clamps stay off the basket's side posts (r 0.008) and the U-clamps on the crossbars (y +-0.032)
    posts = [BA.RK_Y0 + BA.RK_RC + (BA.RK_Y1 - BA.RK_Y0 - 2 * BA.RK_RC) * (k + 0.5) / 7 for k in range(7)]
    yk = yc
    for _i in range(20):
        bad = [p for p in posts if abs(p - yk) < 0.022] + [t for t in BA.TOWER_Y if abs(t - yk) < 0.045]
        if not bad:
            break
        yk += 0.005 if bad[0] < yk else -0.005
    clamps = []
    for axis, rt in zip(axes, BA_TUBE_R):
        xc, zc, hx, hz = axis(yk)                                  # the tube's centre and half extents at the clamp
        a = max(rt, hx, hz) + RC_JAW_GAP                           # the jaws' inner faces, off the tube's centre
        clamps.append((xc, zc, a))
    x_post = max(xc + a + RC_JAW_T for xc, _zc, a in clamps)       # the post's outboard face, on the clamps' plates
    xa = x_post + RC_POST + 0.002                                  # the can's outboard end
    xb = xa + JC_W + 0.002                                         # the inboard upright
    x1 = xb + 0.012
    # the floor under the tray: the tubes' tops, every 1 cm (they rise toward the front)
    zfl = zf
    n_x, n_y = int((x1 - x_post) / 0.01) + 1, int((y1 - y0) / 0.01) + 1
    for i in range(n_x + 1):
        for j in range(n_y + 1):
            h = _ray(rtree, (x_post + (x1 - x_post) * i / n_x, y0 + (y1 - y0) * j / n_y, 2.5), (0, 0, -1), 1.0)
            if h[0] is not None and h[0].z < zt - 0.02:
                zfl = max(zfl, h[0].z)
    zb = zfl + RC_FLOOR_GAP                                        # the tray's underside
    z0 = zb + 0.006                                                # the can's base
    zp = z0 + 0.32                                                 # the uprights' and the post's tops
    bm = bmesh.new()

    def box(lo, hi, mat=POWDER):
        BA._box(bm, lo, hi, mat=mat)
    # tray, with a lip along its front and rear edges, feet on the floor tubes under it (it stands level on the
    # rising floor: a spacer at the rear, one in the middle)
    box((x_post, y0, zb), (x1, y1, z0))
    for ya, yb in ((y0, y0 + 0.006), (y1 - 0.006, y1)):
        box((x_post + RC_POST, ya, z0), (xb, yb, z0 + 0.045))
    feet = 0
    for yf in (y0 + 0.004, yc - 0.010):
        top = zf
        for i in range(n_x + 1):
            for yy in (yf, yf + 0.020):
                h = _ray(rtree, (x_post + RC_POST + (x1 - x_post - RC_POST) * i / n_x, yy, 2.5), (0, 0, -1), 1.0)
                if h[0] is not None and h[0].z < zt - 0.02:
                    top = max(top, h[0].z)
        if zb - top > 0.006:
            box((x_post + RC_POST + 0.010, yf, top + 0.001), (x1 - 0.010, yf + 0.020, zb))   # (off the frame's U-clamps)
            feet += 1
    # the inboard upright and a band round the can at two thirds of its height, its latch on the front
    box((xb, yc - 0.016, z0), (x1, yc + 0.016, zp))
    xm = (xa + xb) / 2
    band = [(xm + a_, yc + b_, z0 + 0.300) for a_, b_ in _rrect(JC_W / 2 + 0.004, JC_D / 2 + 0.004, 0.018, 2)]
    BA._sweep(bm, band, BA._rect(0.004, 0.032), ups=[(0, 0, 1)] * len(band), closed=True, smooth=False, mat=POWDER)
    box((xm - 0.014, yc + JC_D / 2 + 0.004, z0 + 0.290), (xm + 0.014, yc + JC_D / 2 + 0.022, z0 + 0.312), CHROME)
    # the outboard post, from under the frame tube's clamp up past the top rail's to the band, and a U-clamp round
    # each tube: a jaw over and under it (RC_JAW_GAP clear), closed by a plate on each side, a bolt head on top.
    # The post is the clamps' inboard plate; nothing passes inside a tube (round 2, R2-WA-4: 90 tri pairs)
    w0, w1 = yk - RC_POST / 2 - 0.003, yk + RC_POST / 2 + 0.003
    zlo = min(zc - a - RC_JAW_T for _xc, zc, a in clamps)
    box((x_post, yc - RC_POST / 2, zlo), (x_post + RC_POST, yc + RC_POST / 2, zp))
    for xc, zc, a in clamps:
        box((xc + a, w0, zc - a - RC_JAW_T), (x_post, w1, zc + a + RC_JAW_T))                   # inboard plate
        box((xc - a, w0, zc + a), (xc + a, w1, zc + a + RC_JAW_T))                               # upper jaw
        box((xc - a, w0, zc - a - RC_JAW_T), (xc + a, w1, zc - a))                               # lower jaw
        box((xc - a - RC_JAW_T, w0, zc - a - RC_JAW_T), (xc - a, w1, zc + a + RC_JAW_T))         # outboard plate
        box((xc - 0.006, w0 + 0.002, zc + a + RC_JAW_T), (xc + 0.006, w1 - 0.002, zc + a + RC_JAW_T + 0.006), CHROME)
    if abs(yk - yc) > 1e-4:                                        # the clamps sit off the post's middle: a web to them
        box((x_post, min(yc, yk) - RC_POST / 2, zlo), (x_post + RC_POST, max(yc, yk) + RC_POST / 2, zp - 0.20))
    # the can: broad faces across the car, the handles along it, the spout at the inboard end
    _jerrycan(BA, bm, (xm, yc, z0), (1, 0, 0), (0, 1, 0), (0, 0, 1))
    ob = _obj(CAN_ROOF, bm)
    hit = _overlaps(ob, ["acc_roofrack", "body"] + list(BA.LOAD_NAMES))
    vs = [ob.matrix_world @ v.co for v in ob.data.vertices]
    report("FEATURE offroad: %s %d tris, in the basket's front left corner: x %.3f..%.3f, y %.3f..%.3f (cargo front %.3f), "
           "tray z %.3f (floor tubes under it to %.3f, %d feet), top z %.3f; clamps at y %.3f on the frame tube / top rail "
           "(x %.3f / %.3f); %s"
           % (CAN_ROOF, BA.tris(ob), min(v.x for v in vs), max(v.x for v in vs), min(v.y for v in vs), max(v.y for v in vs),
              y_cargo, z0, zfl, feet, max(v.z for v in vs), yk, clamps[0][0], clamps[1][0],
              ("WARNING intersects " + hit) if hit else "no intersection with the rack, the cargo or the body"))
    return ob


# texel weights on this feature's sheet, per face (the FLOAT face attribute texel_w that bake_atlas reads
# for OBJECTS with texel_w): what the game camera (VIS_ELEV down, any of VIS_AZ azimuths) can see of the
# face with the shut car round it. Seen faces get their material's weight (VIS_MAT_W, else 1), faces seen
# only edge-on half that, faces never seen W_HIDDEN (bake_atlas snaps to 0.25 .. 4). By material alone
# (AccOffroadBare 0.8) the skid plate's top under the engine and its bottom toward the road took ~18 % of
# the 1024 sheet for a part whose only visible face is its front lip (2026-10-14 review).
VIS_ELEV, VIS_AZ = 30.0, 24
W_HIDDEN = 0.25
GRAZE_COS = 0.25
VIS_MAT_W = {"AccOffroadRubber": 0.5, "AccOffroadTread": 2.0}   # the step's diamond pattern wants the density
VIS_BLOCKERS = ("body", "hood", "trunk", "trunk_top", "door_fl", "door_fr", "door_rl", "door_rr",
                "wheel_FL", "wheel_FR", "wheel_RL", "wheel_RR")


def _seen_weights(ob):
    """Write texel_w per face of ob (see VIS_ELEV); returns {weight: 3D area}."""
    import bpy
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    verts, polys = [], []
    for o in [ob] + [bpy.data.objects.get(n) for n in VIS_BLOCKERS]:
        if o is None or o.type != 'MESH':
            continue
        base = len(verts)
        verts.extend(o.matrix_world @ v.co for v in o.data.vertices)
        polys.extend([base + i for i in p.vertices] for p in o.data.polygons)
    tree = BVHTree.FromPolygons(verts, polys)
    e = math.radians(VIS_ELEV)
    dirs = [Vector((math.cos(e) * math.cos(a), math.cos(e) * math.sin(a), math.sin(e)))
            for a in (2 * math.pi * k / VIS_AZ for k in range(VIS_AZ))]
    me = ob.data
    names = [m.name if m else "?" for m in me.materials]
    mw = ob.matrix_world
    out, area = [], {}
    bary = ((1 / 3, 1 / 3, 1 / 3), (2 / 3, 1 / 6, 1 / 6), (1 / 6, 2 / 3, 1 / 6), (1 / 6, 1 / 6, 2 / 3),
            (0.45, 0.45, 0.10), (0.10, 0.45, 0.45), (0.45, 0.10, 0.45))
    for p in me.polygons:
        n = (mw.to_3x3() @ p.normal).normalized()
        vs = [mw @ me.vertices[i].co for i in p.vertices]
        # points spread over the face's fan triangles: a can's broad face is crossed by its pressed X,
        # whose ribs hide the centre and the corner diagonals but not the panels between them
        pts = [vs[0] * a + vs[k] * b + vs[k + 1] * c for k in range(1, len(vs) - 1) for a, b, c in bary]
        best = 0.0
        for d in sorted(dirs, key=lambda d: -n.dot(d)):
            cos = n.dot(d)
            if cos <= best:
                break
            if any(tree.ray_cast(q + n * 0.002, d, 6.0)[0] is None for q in pts):
                best = cos
                break
        w = VIS_MAT_W.get(names[p.material_index], 1.0)
        w = w if best >= GRAZE_COS else (0.5 * w if best > 0.0 else W_HIDDEN)
        out.append(w)
        area[w] = area.get(w, 0.0) + p.area
    attr = me.attributes.get("texel_w")
    if attr is not None:
        me.attributes.remove(attr)
    attr = me.attributes.new("texel_w", 'FLOAT', 'FACE')
    attr.data.foreach_set("value", out)
    return area


def BUILD(report):
    import build_accessories as BA
    made = [build_snorkel(BA, report), build_skid(BA, report), build_bumper(BA, report), build_ladder(BA, report),
            build_can_gate(BA, report), build_can_roof(BA, report)]
    for ob in made:
        # faces no camera sees out (BA.prune_hidden, optimization pass 2026-10-24): the can on the gate
        # against the gate, the rest against the body
        if ob.name == CAN_GATE:
            BA.prune_hidden(ob, ("trunk",), report, gate=True)
        else:
            BA.prune_hidden(ob, ("body",), report)
        mean = BA._shade(ob, 0.55)
        report("FEATURE offroad: %s shade mean %.2f" % (ob.name, mean))
        if OBJECTS[ob.name].get("texel_w"):
            area = _seen_weights(ob)
            tot = sum(area.values())
            report("FEATURE offroad: %s texel weights by area: %s" % (ob.name, ", ".join(
                "%.2f %.0f%%" % (w, 100.0 * a / tot) for w, a in sorted(area.items()))))
    report("FEATURE offroad: %d objects, %d tris with everything fitted" % (len(made), sum(BA.tris(o) for o in made)))


OBJECTS = {
    SNORKEL: {"space": KEY, "texel_w": True},
    SKID: {"space": KEY, "texel_w": True},
    BUMPER: {"space": KEY, "texel_w": True},
    LADDER: {"space": KEY, "texel_w": True},
    CAN_ROOF: {"space": KEY, "texel_w": True},
    # rides the side-hinged gate: the shell sheet (feature sheets are static only), dents with the boot
    CAN_GATE: {"space": "shell", "bone": "trunk_bone", "zone": "boot", "weight": 0.6},
}
SPACES = {KEY: {"size": 1024, "texture": TEX_NAME, "ao_k": 0.30, "gain": 1.0, "grime": ((96, 88, 74), 0.0)}}

# ---------------------------------------------------------------------------------------------
# bake: the materials' colour stacks (every face carries acc_shade, the pieces' own AO)

SKID_PNG = "offroad_skid.png"
TREAD_PNG = "offroad_tread.png"
TREAD_U, TREAD_V = 0.80, (-2.40, -2.00)       # the tread map's x half span and y range (the step's top face)
TREAD_PITCH = (0.034, 0.034)                  # one lug per cell (m), neighbours alternate +-31 deg: 11 px at 326 px/m
TREAD_FLAT = 0.45                             # the flat between the diamonds, against the diamonds' 1.0
SHADE = ("attr", "acc_shade")
BAKE_TEXTURED = {
    "AccOffroadPlastic": [("box", "fabric_leather_01_diffuse_1k.jpg", 0.10, (0.034, 0.034, 0.036), 0.55), SHADE],
    "AccOffroadPowder": [("box", "metal_plate_02_diffuse_1k.jpg", 0.40, (0.045, 0.046, 0.048), 0.45), ("noise", 90.0, 0.08), SHADE],
    # zinc-plated: light enough that the lip reads as a bright strip under the black valance at 326 px/m
    "AccOffroadBare": [("box", "metal_plate_02_diffuse_1k.jpg", 0.30, (0.40, 0.40, 0.41), 0.35), ("noise", 40.0, 0.06),
                       ("decal", SKID_PNG, ("x", -SK_X, SK_X), ("z", SK_PROFILE[-2][1], SK_PROFILE[-1][1] + SK_T), "multiply",
                        [("normal", "y", ">", 0.3)]), SHADE],
    "AccOffroadAlu": [("box", "metal_plate_02_diffuse_1k.jpg", 0.25, (0.42, 0.43, 0.45), 0.60), SHADE],
    "AccOffroadCan": [("box", "metal_plate_02_diffuse_1k.jpg", 0.30, (0.062, 0.078, 0.032), 0.55), ("noise", 60.0, 0.06), SHADE],
    "AccOffroadChrome": [("box", "metal_plate_02_diffuse_1k.jpg", 0.20, (0.55, 0.55, 0.57), 0.70), SHADE],
    "AccOffroadRubber": [("noise", 80.0, 0.05), SHADE],
    # bright diamond (tread) plate on the step: at the powder coat's 0.05 the multiplied pattern could not
    # show and the step read as one black slab with the beam (2026-10-14 review). The map keeps the raised
    # diamonds at the plate's colour and darkens the flat between them to TREAD_FLAT
    "AccOffroadTread": [("box", "metal_plate_02_diffuse_1k.jpg", 0.20, (0.22, 0.22, 0.23), 0.55),
                        ("decal", TREAD_PNG, ("x", -TREAD_U, TREAD_U), ("y", TREAD_V[0], TREAD_V[1]), "multiply"), SHADE],
}
# by material (the gate can on the shell uses its OBJECTS weight; the pieces on this sheet carry texel_w per
# face, which wins: _seen_weights)
BAKE_MAT_WEIGHTS = {"AccOffroadPlastic": 1.0, "AccOffroadPowder": 0.8, "AccOffroadBare": 0.8, "AccOffroadAlu": 1.0,
                    "AccOffroadCan": 1.0, "AccOffroadChrome": 1.0, "AccOffroadRubber": 0.5, "AccOffroadTread": 1.0}
BAKE_SWATCH_MATS = {"AccOffroadPowder"}     # the gate can's holder on the shell: flat black like AccSteel (armour fix)


def BAKE_PAINT(decal_dir):
    """The skid plate's lip (four slots between the bolts) and the bumper step's tread pattern, as
    multiply maps (Blender's float buffer is saved as sRGB, the bake reads it back linear)."""
    import bpy
    import numpy as np
    os.makedirs(decal_dir, exist_ok=True)
    ss = 4                                                      # samples per pixel side (box), then a 1-2-1 blur:

    def png(name, w, h, shade):                                 # the bake point-samples decals (playbook)
        u = (np.arange(w * ss) + 0.5) / (w * ss)
        v = (np.arange(h * ss) + 0.5) / (h * ss)
        g = shade(*np.meshgrid(u, v))                           # rows are v (Blender's pixel rows run bottom-up)
        g = g.reshape(h, ss, w, ss).mean(axis=(1, 3))
        for ax in (0, 1):
            g = 0.25 * np.roll(g, 1, ax) + 0.5 * g + 0.25 * np.roll(g, -1, ax)
        px = np.ones((h, w, 4), dtype=np.float32)
        px[..., 0] = px[..., 1] = px[..., 2] = np.clip(g, 0.0, 1.0)
        img = bpy.data.images.new(name, w, h, alpha=False)
        img.pixels.foreach_set(px.ravel())
        img.filepath_raw = os.path.join(decal_dir, name)
        img.file_format = 'PNG'
        img.save()
        bpy.data.images.remove(img)

    def skid(u, v):                                             # u: x -SK_X .. SK_X, v: up the lip
        x = (u - 0.5) * 2.0 * SK_X
        g = np.ones_like(u)
        for cx in (-0.16, 0.0, 0.16):                          # slots between the bolts (SK_BOLTS)
            dx = np.maximum(np.abs(x - cx) - 0.020, 0.0) / 0.015     # 7 cm long, rounded ends
            dv = (v - 0.50) / 0.21
            g = np.where(dx * dx + dv * dv < 1.0, 0.16, g)
        return g
    png(SKID_PNG, 256, 32, skid)

    def tread(u, v):                                            # raised lugs in a herringbone, like checker plate
        x = (u - 0.5) * 2.0 * TREAD_U
        y = TREAD_V[0] + v * (TREAD_V[1] - TREAD_V[0])
        cx, cy = TREAD_PITCH                                   # a cell holds one lug; neighbours alternate
        i, j = np.floor(x / cx), np.floor(y / cy)
        lx, ly = (x / cx - i - 0.5) * cx, (y / cy - j - 0.5) * cy
        sgn = np.where((i + j) % 2 == 0, 1.0, -1.0)
        ax, ay = math.cos(math.radians(31.0)), math.sin(math.radians(31.0)) * sgn
        p = lx * ax + ly * ay
        q = -lx * ay + ly * ax
        lug = np.abs(p) / 0.0110 + np.abs(q) / 0.0042         # 22 x 8.4 mm lozenge
        return np.where(lug < 1.0, 1.0, TREAD_FLAT)
    w = 1024
    png(TREAD_PNG, w, int(round(w * (TREAD_V[1] - TREAD_V[0]) / (2.0 * TREAD_U))), tread)
    return [os.path.join(decal_dir, SKID_PNG), os.path.join(decal_dir, TREAD_PNG)]


# ---------------------------------------------------------------------------------------------
# icons and the mechanics overlay (compose_overlays.BOTTOM_BAND, under the tank / muffler row, is this feature's)

ICONS = {
    # icon-only squat (gen_icons copy squash): at full length the snorkel is a stick with a dot at 32 px
    "CRVGen1_OffroadSnorkel": ((lambda ic: [ic.copy(SNORKEL, squash=0.45)]), 60.0, 20.0),
    "CRVGen1_OffroadSkidPlate": (SKID, 60.0, 32.0),
    # 3/4 from behind and above: the beam's top and face, the receiver and the ball fill the frame
    "CRVGen1_OffroadRearBumper": (BUMPER, 215.0, 35.0),
    "CRVGen1_OffroadLadder": (LADDER, 0.0, 10.0),
}

FRAMES = [(6, 46), (48, 88), (90, 130), (132, 172), (174, 214), (216, 256)]


def _frame(s, i, ov):
    """Frame i of the overlay's bottom band (compose_overlays.BOTTOM_BAND, clear of the window's status strip)."""
    x0, x1 = FRAMES[i]
    y0, y1 = ov.BOTTOM_BAND
    s.frame_box(x0, y0, x1, y1)
    return (x0, y0, x1, y1), (x0 + x1 + 1) / 2.0, (y0 + y1 + 1) / 2.0


def _icon_snorkel(s, ov):
    """The snorkel from the side: the body up the pillar, the ram head forward at the top."""
    box, cx, cy = _frame(s, 0, ov)
    tube = ("line", [(cx - 6, cy + 13), (cx - 6, cy + 3), (cx - 1, cy - 9)], 5.0)
    head = ("rrect", cx - 5, cy - 15, cx + 11, cy - 6, 3.0)
    foot = ("rrect", cx - 13, cy + 10, cx - 1, cy + 15, 2.0)
    s.cell([tube, head, foot], "acc_offroad_snorkel", details=[[(cx + 8, cy - 13), (cx + 8, cy - 8)]], dlw=1.2)
    return box


def _icon_skid(s, ov):
    """The skid plate from the side: the flat run, the lip up at the front, the kick-up behind, slots."""
    box, cx, cy = _frame(s, 1, ov)
    plate = ("poly", [(cx - 16, cy - 2), (cx - 12, cy + 4), (cx + 10, cy + 4), (cx + 16, cy - 4), (cx + 16, cy - 1),
                      (cx + 11, cy + 8), (cx - 13, cy + 8), (cx - 17, cy + 1)])
    s.cell([plate], "acc_offroad_skid", details=[[(cx - 6, cy + 6), (cx - 2, cy + 6)], [(cx + 2, cy + 6), (cx + 6, cy + 6)]], dlw=1.2)
    return box


def _icon_bumper(s, ov):
    """The rear bumper from behind: the beam, the receiver under it and the ball."""
    box, cx, cy = _frame(s, 2, ov)
    beam = ("rrect", cx - 17, cy - 9, cx + 17, cy - 1, 1.5)
    recv = ("rrect", cx - 3.5, cy - 1.5, cx + 3.5, cy + 6, 1.0)
    ball = ("ellipse", cx, cy + 10, 4.2, 4.2)
    neck = ("line", [(cx, cy + 5), (cx, cy + 8)], 2.6)
    s.cell([beam, recv, ball, neck], "acc_offroad_bumper", details=[[(cx - 14, cy - 5), (cx + 14, cy - 5)]], dlw=1.0)
    return box


def _icon_ladder(s, ov):
    """The ladder: two stiles, three rungs, the top bent over."""
    box, cx, cy = _frame(s, 3, ov)
    st = [("line", [(cx - 7, cy + 15), (cx - 7, cy - 11), (cx - 3, cy - 15)], 3.0),
          ("line", [(cx + 7, cy + 15), (cx + 7, cy - 11), (cx + 11, cy - 15)], 3.0)]
    rungs = [("line", [(cx - 7, cy + y), (cx + 7, cy + y)], 2.4) for y in (8, 0, -8)]
    s.cell(st + rungs, "acc_offroad_ladder")
    return box


def _can_shapes(cx, cy, g=0.0, k=1.0):
    """The jerry can's outline shapes (scaled by k, grown by g px: the cut-out of what it hides) and its X."""
    body = ("rrect", cx - 8 * k - g, cy - 9 * k - g, cx + 8 * k + g, cy + 13 * k + g, 2.0 * k + g)
    handles = ("rrect", cx - 8 * k - g, cy - 13 * k - g, cx + 2 * k + g, cy - 9 * k, 1.0 * k + g)
    spout = ("line", [(cx + 4 * k, cy - 9 * k), (cx + 8 * k, cy - 14 * k)], 3.4 * k + 2 * g)
    x = [[(cx - 5 * k, cy - 6 * k), (cx + 5 * k, cy + 10 * k)], [(cx + 5 * k, cy - 6 * k), (cx - 5 * k, cy + 10 * k)]]
    return [body, handles, spout], x


def _icon_can_gate(s, ov):
    """A jerry can in front of the tailgate's spare wheel: the whole tyre with its rim line, hidden where
    the can stands in front of its lower right (a bare arc beside the can read as a bracket)."""
    box, cx, cy = _frame(s, 4, ov)
    shapes, x = _can_shapes(cx + 10.0, cy + 3.5, k=0.78)
    hidden, _x = _can_shapes(cx + 10.0, cy + 3.5, g=2.4, k=0.78)
    tx, ty, r = cx - 4.5, cy - 2.5, 11.5
    rim = [(tx + 7.0 * math.cos(math.radians(a)), ty + 7.0 * math.sin(math.radians(a))) for a in range(0, 361, 12)]
    s.cell([("ellipse", tx, ty, r, r)], "acc_offroad_can_gate", sub=[("ellipse", tx, ty, 3.2, 3.2)] + hidden,
           details=[rim], dlw=1.2)
    s.cell(shapes, "acc_offroad_can_gate", details=x, dlw=1.2)
    return box


def _icon_can_roof(s, ov):
    """A jerry can standing in a roof rack basket, behind its rail."""
    box, cx, cy = _frame(s, 5, ov)
    shapes, x = _can_shapes(cx, cy - 2)
    rail = ("rrect", cx - 17, cy + 12, cx + 17, cy + 15, 1.0)
    posts = [("line", [(cx - 14, cy + 13), (cx - 14, cy + 4)], 2.0), ("line", [(cx + 14, cy + 13), (cx + 14, cy + 4)], 2.0)]
    s.cell(shapes + [rail] + posts, "acc_offroad_can_roof", details=x, dlw=1.2)
    return box


OVERLAYS = {
    "CRVOffroadSnorkel": {"img": "acc_offroad_snorkel", "draw": _icon_snorkel},
    "CRVOffroadSkidPlate": {"img": "acc_offroad_skid", "draw": _icon_skid},
    "CRVOffroadRearBumper": {"img": "acc_offroad_bumper", "draw": _icon_bumper},
    "CRVOffroadLadder": {"img": "acc_offroad_ladder", "draw": _icon_ladder},
    "CRVOffroadCanGate": {"img": "acc_offroad_can_gate", "draw": _icon_can_gate},
    "CRVOffroadCanRoof": {"img": "acc_offroad_can_roof", "draw": _icon_can_roof},
}

# ---------------------------------------------------------------------------------------------
# scripts

LUA_NS = "HondaCRVGen1.Offroad"
# part, mesh, item (Base.<item>), area, parent, requireInstalled, tool tag, time, Mechanics level, English name
PARTS = [
    ("CRVOffroadSnorkel", SNORKEL, "CRVGen1_OffroadSnorkel", "TireFrontRight", None, None, "base:screwdriver", 800, 2, "Snorkel"),
    ("CRVOffroadSkidPlate", SKID, "CRVGen1_OffroadSkidPlate", "Engine", None, None, "base:wrench", 900, 2, "Skid Plate"),
    ("CRVOffroadRearBumper", BUMPER, "CRVGen1_OffroadRearBumper", "TruckBed", None, None, "base:wrench", 1500, 3,
     "Rear Steel Bumper"),
    ("CRVOffroadLadder", LADDER, "CRVGen1_OffroadLadder", "TireRearRight", None, None, "base:wrench", 700, 1, "Roof Ladder"),
    # the cans: the vanilla petrol can is the part item; strapped in by hand, no tools or skill
    ("CRVOffroadCanGate", CAN_GATE, "JerryCan", "TruckBed", "TrunkDoor", "TrunkDoor", None, 150, 0, "Tailgate Jerry Can"),
    ("CRVOffroadCanRoof", CAN_ROOF, "JerryCan", "RoofRack", None, "CRVRoofRack", None, 200, 0, "Roof Rack Jerry Can"),
]


def MODELS(gen):
    out = []
    for _p, geo, _i, _a, parent, _r, _t, _tm, _sk, _n in PARTS:
        if geo == CAN_GATE:
            # skinned to the gate's bone on the shell sheet (the vehicle shader), drawn by TrunkDoor's player
            out.append(gen.model_block(gen.acc_model_name(geo), "crvgen1_" + geo, static=False, bone="trunk_bone"))
        else:
            out.append(gen.model_block(gen.acc_model_name(geo), "crvgen1_" + geo,
                                       texture="%s_%s" % (gen.TEX, TEX_NAME), shader="vehiclewheel"))
    return out


def VEHICLE_PARTS(gen, vehicle):
    out = []
    for part, geo, item, area, parent, req, tool, tm, sk, _n in PARTS:
        out.append(gen.accessory_part(part, geo, item, area, parent=parent, require_installed=req, tool=tool, time=tm,
                                      level=sk, lua=LUA_NS, repair=item != "JerryCan"))   # the can: vanilla's item, never altered
    return out


ITEMS = {
    "CRVGen1_OffroadSnorkel": {"DisplayCategory": "VehicleMaintenance", "Weight": 3.5, "ItemType": "base:normal",
                               "DisplayName": "CRV Snorkel", "Icon": "CRVGen1_OffroadSnorkel", "ConditionMax": 100,
                               "ChanceToSpawnDamaged": 20, "MechanicsItem": True},
    "CRVGen1_OffroadSkidPlate": {"DisplayCategory": "VehicleMaintenance", "Weight": 9.0, "ItemType": "base:normal",
                                 "DisplayName": "CRV Skid Plate", "Icon": "CRVGen1_OffroadSkidPlate", "ConditionMax": 100,
                                 "ChanceToSpawnDamaged": 20, "MechanicsItem": True, "Tags": "base:hasmetal"},
    "CRVGen1_OffroadRearBumper": {"DisplayCategory": "VehicleMaintenance", "Weight": 24.0, "ItemType": "base:normal",
                                  "DisplayName": "CRV Rear Steel Bumper", "Icon": "CRVGen1_OffroadRearBumper",
                                  "ConditionMax": 100, "ChanceToSpawnDamaged": 20, "MechanicsItem": True,
                                  "Tags": "base:hasmetal"},
    "CRVGen1_OffroadLadder": {"DisplayCategory": "VehicleMaintenance", "Weight": 6.0, "ItemType": "base:normal",
                              "DisplayName": "CRV Roof Ladder", "Icon": "CRVGen1_OffroadLadder", "ConditionMax": 100,
                              "ChanceToSpawnDamaged": 20, "MechanicsItem": True, "Tags": "base:hasmetal"},
}

RECIPES = """\tcraftRecipe CRVGen1_MakeOffroadSnorkel
\t{
\t\ttimedAction = Making,
\t\ttime = 400,
\t\tTags = AnySurfaceCraft,
\t\tcategory = Assembly,
\t\tSkillRequired = Mechanics:2,
\t\txpAward = Mechanics:15,
\t\tinputs
\t\t{
\t\t\titem 2 [Base.Pipe],
\t\t\titem 1 [Base.RubberHose],
\t\t\titem 1 [Base.SmallSheetMetal],
\t\t\titem 4 [Base.Screws],
\t\t\titem 1 tags[base:saw] mode:keep flags[MayDegradeLight],
\t\t\titem 1 tags[base:screwdriver] mode:keep flags[MayDegradeLight],
\t\t}
\t\toutputs
\t\t{
\t\t\titem 1 Base.CRVGen1_OffroadSnorkel,
\t\t}
\t}

\tcraftRecipe CRVGen1_MakeOffroadSkidPlate
\t{
\t\ttimedAction = Welding_Surface,
\t\ttime = 600,
\t\tTags = AnySurfaceCraft,
\t\tcategory = Metalworking,
\t\tSkillRequired = MetalWelding:3;Mechanics:2,
\t\txpAward = MetalWelding:20;Mechanics:10,
\t\tinputs
\t\t{
\t\t\titem 2 [Base.SheetMetal],
\t\t\titem 2 [Base.NutsBolts],
\t\t\titem 2 [Base.BlowTorch],
\t\t\titem 1 tags[base:weldingmask] mode:keep,
\t\t\titem 1 tags[base:wrench] mode:keep flags[MayDegradeLight],
\t\t}
\t\toutputs
\t\t{
\t\t\titem 1 Base.CRVGen1_OffroadSkidPlate,
\t\t}
\t}

\tcraftRecipe CRVGen1_MakeOffroadRearBumper
\t{
\t\ttimedAction = Welding_Surface,
\t\ttime = 1200,
\t\tTags = AnySurfaceCraft,
\t\tcategory = Metalworking,
\t\tSkillRequired = MetalWelding:5;Mechanics:3,
\t\txpAward = MetalWelding:30;Mechanics:15,
\t\tinputs
\t\t{
\t\t\titem 2 [Base.SheetMetal],
\t\t\titem 2 [Base.MetalPipe],
\t\t\titem 1 [Base.MetalBar],
\t\t\titem 3 [Base.NutsBolts],
\t\t\titem 4 [Base.BlowTorch],
\t\t\titem 1 tags[base:weldingmask] mode:keep,
\t\t\titem 1 tags[base:wrench] mode:keep flags[MayDegradeLight],
\t\t}
\t\toutputs
\t\t{
\t\t\titem 1 Base.CRVGen1_OffroadRearBumper,
\t\t}
\t}

\tcraftRecipe CRVGen1_MakeOffroadLadder
\t{
\t\ttimedAction = Welding_Surface,
\t\ttime = 700,
\t\tTags = AnySurfaceCraft,
\t\tcategory = Metalworking,
\t\tSkillRequired = MetalWelding:3;Mechanics:1,
\t\txpAward = MetalWelding:20;Mechanics:5,
\t\tinputs
\t\t{
\t\t\titem 4 [Base.MetalPipe],
\t\t\titem 1 [Base.SmallSheetMetal],
\t\t\titem 2 [Base.BlowTorch],
\t\t\titem 1 tags[base:weldingmask] mode:keep,
\t\t\titem 1 tags[base:wrench] mode:keep flags[MayDegradeLight],
\t\t}
\t\toutputs
\t\t{
\t\t\titem 1 Base.CRVGen1_OffroadLadder,
\t\t}
\t}"""

TRANSLATIONS = {
    "IG_UI": dict([("IGUI_VehiclePart" + p[0], p[9]) for p in PARTS]),
    # 42.21's Recipes.json keys are the bare craftRecipe names (vanilla "MakeMetalSheet")
    "Recipes": {"CRVGen1_MakeOffroadSnorkel": "Make CRV Snorkel",
                "CRVGen1_MakeOffroadSkidPlate": "Make CRV Skid Plate",
                "CRVGen1_MakeOffroadRearBumper": "Make CRV Rear Steel Bumper",
                "CRVGen1_MakeOffroadLadder": "Make CRV Roof Ladder"},
}

LUA = ["server/Vehicles/HondaCRVGen1_Offroad.lua"]

# rare loot in garages and auto shops; no "sandbox" key: the function feature's FunctionLootRarity scales every CR-V entry
DISTRIBUTIONS = [
    {"list": "GarageMechanics", "item": "Base.CRVGen1_OffroadSnorkel", "weight": 0.3},
    {"list": "StoreShelfMechanics", "item": "Base.CRVGen1_OffroadSnorkel", "weight": 0.4},
    {"list": "CrateMechanics", "item": "Base.CRVGen1_OffroadSnorkel", "weight": 0.4},
    {"list": "GarageMechanics", "item": "Base.CRVGen1_OffroadSkidPlate", "weight": 0.3},
    {"list": "MechanicShelfMufflers", "item": "Base.CRVGen1_OffroadSkidPlate", "weight": 0.3},
    {"list": "GarageMetalwork", "item": "Base.CRVGen1_OffroadSkidPlate", "weight": 0.2},
    {"list": "CrateMechanics", "item": "Base.CRVGen1_OffroadRearBumper", "weight": 0.3},
    {"list": "MechanicSpecial", "item": "Base.CRVGen1_OffroadRearBumper", "weight": 0.4},
    {"list": "GarageMechanics", "item": "Base.CRVGen1_OffroadRearBumper", "weight": 0.15},
    {"list": "GarageMechanics", "item": "Base.CRVGen1_OffroadLadder", "weight": 0.2},
    {"list": "GarageMetalwork", "item": "Base.CRVGen1_OffroadLadder", "weight": 0.2},
    {"list": "StoreShelfMechanics", "item": "Base.CRVGen1_OffroadLadder", "weight": 0.2},
]
