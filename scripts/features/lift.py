r"""
Lift conversion (spec/feature-roadmap.md "Off-road", the author 2026-10-13): a 3 inch (7.5 cm) suspension
lift on 30x9.50R15 all-terrain tyres with white raised letters, on the stock EX alloys or on black
steel wheels, the player's choice at conversion. Conversion only (no lifted spawns), reversible: a
mechanic action (shared/TimedActions/ISCRVLiftConvert.lua) swaps the car for one of the two second
vehicle scripts below and back, keeping every part, condition, container, fluid and mod data.

In PZ every car of one vehicle script shares its body and wheel positions, so the lifted car is a
second script. Both keep every part id of the stock car (gen.vehicle_script is the stock car with
what changes): the wheels drop LIFT_M below the body (wheel offset y; the body rides that much
higher, plus the bigger tyre's radius), and the tyre parts draw this feature's wheel models.

Meshes (BUILD, Blender): two wheels in the wheel FBX, centred on their own hub like the stock one:
  wheel_lift_alloy  the stock EX alloy's rim (wheel_FR's faces that are not tyre, copied) on the AT tyre
  wheel_lift_steel  a classic black 15 x 7 steel wheel: rolled lip with a lit edge, a flat face with
                    eight round vent windows onto the grey brake rotor, a raised hub with five chrome
                    nuts and a small cap, on the same tyre
  the AT tyre       a 24-sided lathe carcass (groove floors 13 mm under the tread) with an all-terrain
                    tread of our own (2026-10-14 review: the old two rows of big bricks read as a mud
                    or military tyre): 30 pitches of four staggered rows, two interlocking centre rows
                    of slanted ~4.5 x 4.5 cm blocks either side of a zig-zag centre groove, and two
                    shoulder rows whose blocks roll over the shoulder into moderate sidewall lugs (4-8 mm
                    proud, long / short; on the outer side only since 2026-10-19), every section convex
                    with its faces looking out of it
Both bake on this feature's own sheet "lift" (Vehicles_HondaCRVGen1_Lift.png, vehiclewheel shader, so
the Vehicle Texture Size option caps it). They are built far from the car (x 4 and 6 m) so the car
casts no AO on them and they none on it. The white letters are a painted decal (BAKE_PAINT,
lift_sidewall.png: KESTREL over the top and the bottom, TRAIL CLAW on both sides, bold and arced along
the sidewall, the stock tyre's made-up maker: no real brand) mapped flat over the outer sidewall.

The spare on the tailgate (2026-10-14 review: the lifted cars still carried the stock road tyre on the
silver alloy): the stock spare is part of the gate mesh, so each lifted script's TrunkDoor draws a gate of
its own (HondaCRVGen1Acc_lift_gate_alloy / _steel, the gate's FIRST model so trunk_opening plays on it):
the stock gate with its spare's tyre (alloy) or tyre and rim (steel) replaced by an AT spare of the same
make on the matching wheel. The spare keeps the stock spare's size (r 0.332, 0.207 wide): the carrier,
the spare cover (inside r 0.342, face 0.118) and the off-road gate jerry can (back face 0.106 out)
stay as they are, and a stock-size spare is what most lifted RD1s carry. The AT spare and the steel
spare rim are built far from the car (acc_lift_gate_*, x 8 and 10 m, riding trunk_bone), bake on the
shell sheet with their own AO (acc_shade), and EXPORT moves them onto the stock spare's hub and joins
each to a copy of the baked gate (its UVs, zones and back faces unchanged).

Numbers (the RD1's 205/70R15 is 0.334 m in the stock script): 30 x 9.50R15 LT = 762 mm across, 241 mm
wide, the common size on 3 in. lifted compact SUVs; with the 7.5 cm lift the body stands 12.2 cm higher
and the tyre top 9.4 cm higher, so the arches look filled, not empty.
"""
import math
import os

LIFT_M = 0.075                  # 3 in suspension lift (mesh metres, like every script position)
TYRE_R = 0.381                  # 30 x 9.50R15 LT
TYRE_W = 0.241
TYRE_HALF = 0.1205
SEG = 24                        # lathe segments (the stock wheel's 24)
PITCHES = 30                    # tread pitches (7.98 cm at the crown): four staggered blocks each
ALLOY_HUB = (4.0, 0.0, TYRE_R)  # where BUILD puts the wheels (object space = world, identity objects)
STEEL_HUB = (6.0, 0.0, TYRE_R)
STOCK_X, STEEL_X = "0.7200", "0.7350"   # wheel offset x: the alloy keeps the stock track, the steel wheel's
                                        # lower offset sets it 1.5 cm out (typical of lift steelies)
SIDEWALL_PNG = "lift_sidewall.png"
SPARE_SIDEWALL_PNG = "lift_spare_sidewall.png"
DECAL_R = 0.39                  # the decal square: +-DECAL_R about the hub in object y / z
BRAND, MODEL_LINE = "KESTREL", "TRAIL CLAW"   # made-up: no real brand
BRAND_H, MODEL_H = 0.034, 0.026                # cap heights (m): 11 and 8.5 px at the in-game 326 px/m
LETTER_RHO = (0.261, 0.295)                    # the lettering band on the outer sidewall (radius, m)

# the tailgate spare: the stock spare's tyre (trunk Pneu r 0.2082-0.3319, t -0.1033..+0.1042; BUILD
# measures it again), the AT spare built at SPARE_HUB, the steel spare rim at SPARE_STEEL_HUB (axle +x)
SPARE_R, SPARE_HALF = 0.3319, 0.1030
SPARE_HUB = (8.0, 0.0, 0.40)
SPARE_STEEL_HUB = (10.0, 0.0, 0.40)
GATE_GEO = {"alloy": "acc_lift_gate_alloy", "steel": "acc_lift_gate_steel"}
GATE_MATS = {"alloy": ("Pneu",), "steel": ("Pneu", "Jante", "RimWell", "Rotor")}   # stock spare faces each replaces

VEHICLES = {"alloy": "HondaCRVGen1LiftAlloy", "steel": "HondaCRVGen1LiftSteel"}
WHEEL_MODELS = {"alloy": "HondaCRVGen1LiftWheelAlloy", "steel": "HondaCRVGen1LiftWheelSteel"}
WHEEL_GEO = {"alloy": "wheel_lift_alloy", "steel": "wheel_lift_steel"}

# linear base colours of the feature's materials (the bake reads them; PALETTE covers the alloy's own).
# "Lift*" are the road wheels (lift sheet), "LiftSpare*" the same surfaces on the gate spare (shell
# sheet, x the spare's own AO)
_COLOURS = {
    "Tread": (0.024, 0.024, 0.024),         # block tops and walls (KI5 treads sRGB 18-52)
    "Groove": (0.010, 0.010, 0.010),        # groove floors between the blocks
    "Tyre": (0.020, 0.020, 0.020),          # outer sidewall (the decal replaces it with the lettering)
    "TyreIn": (0.017, 0.017, 0.017),        # inner sidewall and bead (towards the car: few texels)
    "Steel": (0.030, 0.030, 0.032),         # gloss black steel wheel, sRGB ~48: apart from the tyre's ~39
    "SteelLip": (0.060, 0.060, 0.063),      # the rolled lip and its edge: the wheel's lit outline
    "SteelWell": (0.014, 0.014, 0.014),     # vent window walls
    "Rotor": (0.110, 0.108, 0.104),         # the brake rotor seen through the windows (sRGB ~93)
    "Dark": (0.012, 0.012, 0.013),          # the wheel's back
    "Hidden": (0.009, 0.009, 0.009),        # faces nobody sees (the bead band): few texels
    "Chrome": (0.42, 0.42, 0.44),           # lug nuts, centre cap
}
MAT_COLOURS = {}
for _k, _c in _COLOURS.items():
    MAT_COLOURS["Lift" + _k] = _c
    MAT_COLOURS["LiftSpare" + _k] = _c

# ---------------------------------------------------------------------------------------------
# geometry (Blender)


RIM_MATS = ("Jante", "RimWell")   # the stock wheel's rim: its lip (Jante) and the back fan (RimWell since round 1)


def _stock_frame(src):
    """The stock wheel_FR: tyre mid-plane x, hub y / z, the rim lip's radius and its outer / inner
    planes relative to the mid-plane (where the new tyre's beads go).
    2026-10-17 (round 2, R2-WA-1): the inner plane is read off the back fan (inner bead to the axle).
    prep_parts._lathe_replace made that fan RimWell (round 1, WHL-6), and a Jante-only read then found
    the lip on the OUTER plane alone (t_in = t_out = +0.0885): every inner-side piece of the lifted
    wheels (bead band, the dark seal disc, the steel rim's back flange and disc) was built on the
    outside, facing in: a black disc over every lifted wheel face. Both materials now, and a check."""
    me = src.data
    names = [m.name if m else "" for m in me.materials]
    pv, jv = set(), set()
    for p in me.polygons:
        n = names[p.material_index]
        (pv if n == "Pneu" else jv if n in RIM_MATS else set()).update(p.vertices)
    if not pv or not jv:
        raise RuntimeError("lift: wheel_FR has no Pneu / Jante faces")
    co = [me.vertices[i].co for i in pv]
    xc = (min(c.x for c in co) + max(c.x for c in co)) / 2.0
    yc = (min(c.y for c in co) + max(c.y for c in co)) / 2.0
    zc = (min(c.z for c in co) + max(c.z for c in co)) / 2.0
    jr = [(me.vertices[i].co, math.hypot(me.vertices[i].co.y - yc, me.vertices[i].co.z - zc)) for i in jv]
    r_lip = max(r for _c, r in jr)
    lip = [c.x - xc for c, r in jr if r > r_lip - 0.004]
    t_out, t_in = max(lip), min(lip)
    if not (t_in < -0.03 and t_out > 0.03):
        raise RuntimeError("lift: wheel_FR's rim lip planes not found on both sides (t %+.4f / %+.4f): the inner "
                           "plane comes from the back fan (%s)" % (t_out, t_in, "/".join(RIM_MATS)))
    return {"xc": xc, "yc": yc, "zc": zc, "r_lip": r_lip, "t_out": t_out, "t_in": t_in}


def _materials():
    import bpy
    out = {}
    for name, col in MAT_COLOURS.items():
        m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
        m.use_nodes = True
        b = next(n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
        b.inputs['Base Color'].default_value = col + (1.0,)
        m.diffuse_color = col + (1.0,)
        out[name] = m
    hub = bpy.data.materials.get("HubCap")
    cap = bpy.data.materials.get("LiftHubCap")
    if cap is None:
        cap = hub.copy() if hub is not None else bpy.data.materials.new("LiftHubCap")
        cap.name = "LiftHubCap"
    out["LiftHubCap"] = cap
    return out


class _Faces:
    """bmesh face maker with material indices by name and an outward test."""

    def __init__(self, bm, me, mats):
        self.bm, self.me = bm, me
        self.idx = {}
        for i, m in enumerate(me.materials):
            if m is not None and m.name not in self.idx:
                self.idx[m.name] = i
        for name, m in mats.items():
            if name not in self.idx:
                me.materials.append(m)
                self.idx[name] = len(me.materials) - 1
        self.made = 0

    def face(self, verts, mat, away=None, toward=None, smooth=False):
        """A face; flipped so its normal points away from `away` (or toward `toward`)."""
        f = self.bm.faces.new(verts)
        f.material_index = self.idx[mat]
        f.normal_update()
        c = f.calc_center_median()
        if away is not None and f.normal.dot(c - away) < 0:
            f.normal_flip()
        if toward is not None and f.normal.dot(toward - c) < 0:
            f.normal_flip()
        f.smooth = smooth
        self.made += len(verts) - 2
        return f


def _ring(bm, hub, t, r, seg=SEG, phase=0.0):
    from mathutils import Vector
    if r <= 1e-6:
        return [bm.verts.new(hub + Vector((t, 0.0, 0.0)))]
    return [bm.verts.new(hub + Vector((t, r * math.cos(phase + 2 * math.pi * k / seg), r * math.sin(phase + 2 * math.pi * k / seg))))
            for k in range(seg)]


def _lathe(F, hub, prof, mats, closed=False, outward=None, smooth=True, seg=SEG):
    """Faces between consecutive profile points (t, r) round the axle (+x). mats[i] names segment i's
    material; outward(i, centre) gives the point its face must look away from (None: +x when t > 0)."""
    from mathutils import Vector
    rings = [_ring(F.bm, hub, t, r, seg) for t, r in prof]
    n = len(prof) if closed else len(prof) - 1
    for i in range(n):
        a, b = rings[i], rings[(i + 1) % len(prof)]
        for k in range(seg):
            if len(a) == 1:
                vs = (a[0], b[k], b[(k + 1) % seg])
            elif len(b) == 1:
                vs = (a[k], a[(k + 1) % seg], b[0])
            else:
                vs = (a[k], a[(k + 1) % seg], b[(k + 1) % seg], b[k])
            f = F.face(vs, mats[i], smooth=smooth)
            c = f.calc_center_median()
            ref = outward(i, c) if outward else None
            if ref is not None:
                if f.normal.dot(c - ref) < 0:
                    f.normal_flip()
            else:
                t_mid = (prof[i][0] + prof[(i + 1) % len(prof)][0]) / 2.0
                want = Vector((1.0 if t_mid >= 0 else -1.0, 0.0, 0.0))
                if f.normal.dot(want) < 0:
                    f.normal_flip()
    return rings


class _Scale:
    """The AT tyre's design (in full-size metres: section t across, r radius) mapped onto a tyre of
    outer radius R and half width H on the same 15 in. rim: radii scale between the bead (rb) and the
    crown, widths scale, the bead itself stays on the rim's lip planes."""

    def __init__(self, rb, R=TYRE_R, H=TYRE_HALF):
        self.rb, self.kr, self.kt = rb, (R - rb) / (TYRE_R - rb), H / TYRE_HALF

    def __call__(self, t, r):
        return t * self.kt, self.rb + (r - self.rb) * self.kr

    def rho(self, r):
        return self.rb + (r - self.rb) * self.kr


# the tread, design coordinates (t from the mid-plane, r): the carcass under it, its groove floor at r
# 0.368 (13 mm under the block tops), and the two block sections of one side (mirrored for the other):
# a centre block either side of the zig-zag centre groove and a shoulder block that rolls over the
# shoulder into a sidewall lug ending lug_r out (4-8 mm proud of the carcass). Both convex; their open
# edge (last vertex -> first) lies inside the carcass
CARCASS = [(0.110, 0.240), (TYRE_HALF, 0.300), (0.117, 0.338), (0.110, 0.358), (0.100, 0.368)]
# the inner side (towards the car or the gate) without the lower sidewall point (0.110, 0.240): the camera
# never sees that face from close enough for its 1.4 cm of curve to show (performance pass 2026-10-19: 48
# tris a tyre). Dropping the shoulder's (0.110, 0.358) as well lit the inner shoulder as a pale band (tried)
CARCASS_IN = [p for p in CARCASS if p != (0.110, 0.240)]
CENTRE_BLOCK = [(0.007, 0.364), (0.007, TYRE_R), (0.050, TYRE_R), (0.050, 0.364)]


def _shoulder_block(lug_r):
    return [(0.060, 0.364), (0.060, TYRE_R), (0.103, TYRE_R), (0.1145, 0.371), (0.1175, lug_r), (0.108, lug_r - 0.003)]


# the inner shoulder row's blocks (side -1) end at the shoulder: no sidewall lug on the side that faces the
# car (or the gate, on the spare), whose lugs nobody saw. The last point is 2 mm inside the carcass, the section
# stays convex, and the block top (slant reference SHOULDER_T1) is the outer row's mirror. 14 tris a block
# instead of 18 (performance pass 2026-10-19: 120 tris a tyre)
SHOULDER_PLAIN = [(0.060, 0.364), (0.060, TYRE_R), (0.103, TYRE_R), (0.1145, 0.371), (0.107, 0.359)]
SHOULDER_T1 = 0.1175


# rows: (side, section, angular length and phase in pitches, slant across the row in pitches): the two
# centre rows half a pitch apart (the centre groove zig-zags between them), each shoulder row a quarter
# pitch off its centre row, the blocks slanted so the crown reads as interlocking Z blocks
ROWS = [(1.0, "centre", 0.60, 0.00, 0.22), (-1.0, "centre", 0.60, 0.50, 0.22),
        (1.0, "shoulder", 0.72, 0.25, -0.10), (-1.0, "shoulder", 0.72, 0.75, -0.10)]


def _tyre(F, hub, fr, P="Lift", R=TYRE_R, H=TYRE_HALF):
    """The AT tyre round hub (axle +x, the cap side +x): carcass lathe + tread blocks, P the material
    prefix, R / H its outer radius and half width (the spare is a smaller tyre of the same make)."""
    from mathutils import Vector
    rb = fr["r_lip"] - 0.002                     # tucked behind the rim lip
    m = _Scale(rb, R, H)
    tbo, tbi = fr["t_out"] - 0.003, fr["t_in"] + 0.003
    outer = [m(t, r) for t, r in CARCASS]
    inner = [m(-t, r) for t, r in reversed(CARCASS_IN)]
    prof = [(tbo, rb)] + outer + inner + [(tbi, rb)]
    T, G, I, Hd = P + "Tyre", P + "Groove", P + "TyreIn", P + "Hidden"
    # sidewall out, shoulder + crown, sidewall in, the bead band
    mats = [T, T, T, G, G, G, G] + [I] * (len(CARCASS_IN) - 1) + [Hd]
    if len(mats) != len(prof):
        raise RuntimeError("lift: carcass profile %d points, %d materials" % (len(prof), len(mats)))
    mid = m.rho(0.29)

    def away(i, c):                               # the section's middle on this face's angle
        d = Vector((0.0, c.y - hub.y, c.z - hub.z))
        return hub + d.normalized() * mid if d.length > 1e-9 else hub
    rings = _lathe(F, hub, prof, mats, closed=True, outward=away)
    # the bead band again, facing out (away from the axle). The band closes the carcass facing the axle; the
    # rim's flange stops 3-4 mm short of the sidewall at the bead, and a ray slipping into that groove from
    # outside met the band's back and the rim's back faces: with the gate open the camera saw the ground
    # through the AT spare's inner side in a thin arc (2026-10-17 review WHL-7: 22 px on the alloy gate, 47
    # on the steel). Its own vertices: bmesh refuses a second face on the same ones
    a_ring, b_ring = rings[-1], rings[0]
    for k in range(SEG):
        k2 = (k + 1) % SEG
        vs = [F.bm.verts.new(v.co) for v in (a_ring[k], a_ring[k2], b_ring[k2], b_ring[k])]
        c = sum((v.co for v in vs), Vector()) / 4.0
        F.face(vs, Hd, away=Vector((c.x, hub.y, hub.z)))
    # ... and a dark disc across the bead band 1 cm in from the inner bead plane, facing the car / gate:
    # the probe's ray (2026-10-17, steel gate, gate open) slipped along the steel rim's back flange, within
    # 0.1 mm of it, into the corner where the flange's 24-gon meets the back disc's; the bead band's twin did
    # not stand in its way. Behind the rim's own back everywhere else, so nothing sees it but such a ray
    t_seal = tbi + 0.010
    seal = _ring(F.bm, hub, t_seal, rb - 0.001)
    centre = F.bm.verts.new(hub + Vector((t_seal, 0.0, 0.0)))
    for k in range(SEG):
        F.face((centre, seal[k], seal[(k + 1) % SEG]), Hd, toward=hub + Vector((t_seal - 1.0, 0.0, 0.0)))
    pitch = 2 * math.pi / PITCHES
    blocks = 0
    for p in range(PITCHES):
        lug_r = 0.350 if p % 2 == 0 else 0.358    # long and short shoulder lugs
        for side, kind, length, phase, slant in ROWS:
            if kind == "centre":
                sec = CENTRE_BLOCK
                t0, t1 = sec[0][0], max(t for t, _r in sec)
            else:
                sec = _shoulder_block(lug_r) if side > 0 else SHOULDER_PLAIN
                t0, t1 = sec[0][0], SHOULDER_T1
            ac = (p + phase) * pitch
            half = 0.5 * length * pitch

            def at(t, r, a):
                tt, rr = m(side * t, r)
                a = a + side * slant * pitch * ((t - t0) / (t1 - t0) - 0.5)
                return hub + Vector((tt, rr * math.cos(a), rr * math.sin(a)))
            ends = [[F.bm.verts.new(at(t, r, a)) for t, r in sec] for a in (ac - half, ac + half)]
            tc = sum(t for t, _r in sec) / len(sec)
            rc = sum(r for _t, r in sec) / len(sec)
            centre = at(tc, rc, ac)
            n = len(sec)
            for i in range(n - 1):                # the last edge (back to the first vertex) is inside the carcass
                F.face((ends[0][i], ends[0][i + 1], ends[1][i + 1], ends[1][i]), P + "Tread", away=centre)
            for e in ends:
                F.face(list(e), P + "Tread", away=centre)
            blocks += 1
    return blocks


def _alloy(src, fr, mats):
    """The stock alloy's rim on the AT tyre."""
    import bmesh
    import bpy
    from mathutils import Vector
    me = src.data.copy()
    me.name = "wheel_lift_alloy"
    ob = bpy.data.objects.new("wheel_lift_alloy", me)
    (src.users_collection[0] if src.users_collection else bpy.context.scene.collection).objects.link(ob)
    if "gen" in me.attributes:                    # generated-face tag of prep_parts: no twin here, all direct
        me.attributes.remove(me.attributes["gen"])
    # material slots: keep the rim's, the stock hub cap becomes LiftHubCap (its own hub decal on this sheet)
    names = [m.name if m else "" for m in me.materials]
    for i, n in enumerate(names):
        if n == "HubCap":
            me.materials[i] = mats["LiftHubCap"]
    bm = bmesh.new()
    bm.from_mesh(me)
    tyre = {i for i, n in enumerate(names) if n == "Pneu"}
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.material_index in tyre], context='FACES')
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context='VERTS')
    shift = Vector(ALLOY_HUB) - Vector((fr["xc"], fr["yc"], fr["zc"]))
    for v in bm.verts:
        v.co += shift
    rim_tris = sum(len(f.verts) - 2 for f in bm.faces)
    F = _Faces(bm, me, mats)
    blocks = _tyre(F, Vector(ALLOY_HUB), fr)
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    bm.to_mesh(me)
    bm.free()
    me.update()
    return ob, rim_tris, blocks


def _steel_rim(F, hub, fr, P):
    """A classic black 15 x 7 steel wheel round hub (axle +x): a rolled lip whose lit edge outlines the
    wheel, the dish down to a flat face with eight round vent windows (pockets onto the grey brake
    rotor: what makes the windows read as openings at game zoom), a raised hub with five chrome nuts
    and a small chrome cap; the back closed by a dark disc. Returns the faces made."""
    from mathutils import Vector
    from mathutils.geometry import tessellate_polygon
    bm = F.bm
    made0 = F.made
    r_lip, t_out, t_in = fr["r_lip"], fr["t_out"], fr["t_in"]
    S, L, W, Ro, D, C = P + "Steel", P + "SteelLip", P + "SteelWell", P + "Rotor", P + "Dark", P + "Chrome"
    # outer side: the rolled lip (its face and its inner bevel lit), the dish wall down to the face ring
    # (the dish was two rings until 2026-10-19: its middle point (0.060, 0.186) bent it by 3 degrees, 48 tris)
    outer = [(t_out + 0.003, r_lip + 0.002), (t_out - 0.002, r_lip - 0.005), (t_out - 0.009, r_lip - 0.011),
             (0.036, 0.170)]
    rings = _lathe(F, hub, outer, [L, L, S])
    face_out = rings[-1]
    # the raised hub: a step up to the flat hub face the nuts sit on, a small chrome cap (flat shaded:
    # smooth read as a dome)
    inner_hub = [(0.036, 0.112), (0.048, 0.100), (0.049, 0.044), (0.062, 0.0)]
    rings2 = _lathe(F, hub, inner_hub, [S, S, C], smooth=False)
    face_in = rings2[0]
    # the face between r 0.170 and 0.112 with eight round vent windows: one plane (a cone's sliver
    # triangles shaded as streaks across the face)
    n_holes, hole_r, hole_c, hole_n, t_face = 8, 0.024, 0.141, 10, 0.036
    holes = []
    for h in range(n_holes):
        a = 2 * math.pi * (h + 0.5) / n_holes
        cy, cz = hole_c * math.cos(a), hole_c * math.sin(a)
        loop = []
        for k in range(hole_n):
            b = 2 * math.pi * k / hole_n
            loop.append(bm.verts.new(hub + Vector((t_face, cy + hole_r * math.cos(b), cz + hole_r * math.sin(b)))))
        holes.append((loop, Vector((0.0, cy, cz))))
    polys = [face_out, face_in] + [lp for lp, _c in holes]
    flat = [v for poly in polys for v in poly]
    tris = tessellate_polygon([[(v.co.y - hub.y, v.co.z - hub.z, 0.0) for v in poly] for poly in polys])
    for a, b, c in tris:
        F.face((flat[a], flat[b], flat[c]), S, toward=hub + Vector((1.0, 0.0, 0.0)))
    # window walls straight back to the rotor disc at t 0, each looking into its window
    t_back = 0.0
    for loop, c in holes:
        back = [bm.verts.new(Vector((hub.x + t_back - 0.002, v.co.y, v.co.z))) for v in loop]
        axis = hub + c + Vector((0.02, 0.0, 0.0))
        for i in range(hole_n):
            j = (i + 1) % hole_n
            f = F.face((loop[i], loop[j], back[j], back[i]), W)
            mid = (loop[i].co + loop[j].co + back[i].co + back[j].co) / 4.0
            to_axis = Vector((0.0, axis.y - mid.y, axis.z - mid.z))
            if f.normal.dot(to_axis) < 0:
                f.normal_flip()
    # the rotor: the ring the windows show (r 0.117-0.165). Its dark centre went 2026-10-19 (16 tris): the
    # raised hub closes r < 0.112 in front, the back disc behind, the window walls stop at r 0.117
    rotor = [(t_back, 0.180), (t_back, 0.095)]
    _lathe(F, hub, rotor, [Ro], outward=lambda i, c: hub - Vector((1.0, 0.0, 0.0)), smooth=False, seg=16)
    # lug nuts: hex prisms on the hub face
    for k in range(5):
        a = 2 * math.pi * k / 5 + math.pi / 2
        cy, cz = 0.057 * math.cos(a), 0.057 * math.sin(a)
        base = [bm.verts.new(hub + Vector((0.044, cy + 0.0105 * math.cos(a + math.pi * j / 3), cz + 0.0105 * math.sin(a + math.pi * j / 3))))
                for j in range(6)]
        top = [bm.verts.new(v.co + Vector((0.020, 0.0, 0.0))) for v in base]
        c = hub + Vector((0.054, cy, cz))
        for j in range(6):
            F.face((base[j], base[(j + 1) % 6], top[(j + 1) % 6], top[j]), C, away=c)
        F.face(list(top), C, toward=hub + Vector((1.0, cy, cz)))
    # back side: the inner flange and a dark disc closing the wheel towards the car
    back = [(t_in - 0.003, r_lip + 0.002), (t_in + 0.004, r_lip - 0.010), (t_in + 0.004, 0.0)]
    _lathe(F, hub, back, [D, D])                  # t < 0: these look towards the car (-x)
    return F.made - made0


def _steel(fr, mats):
    """wheel_lift_steel: the steel wheel on the AT tyre."""
    import bmesh
    import bpy
    from mathutils import Vector
    me = bpy.data.meshes.new("wheel_lift_steel")
    ob = bpy.data.objects.new("wheel_lift_steel", me)
    bpy.context.scene.collection.objects.link(ob)
    me.materials.append(mats["LiftSteel"])
    bm = bmesh.new()
    F = _Faces(bm, me, mats)
    hub = Vector(STEEL_HUB)
    rim_tris = _steel_rim(F, hub, fr, "Lift")
    blocks = _tyre(F, hub, fr)
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    bm.to_mesh(me)
    bm.free()
    me.update()
    return ob, rim_tris, blocks


def _spare_dims(trunk):
    """The stock spare's tyre on the gate (its Pneu faces): outer radius, half width, hub, axle."""
    from mathutils import Vector
    me = trunk.data
    names = [m.name if m else "" for m in me.materials]
    vs = set()
    for p in me.polygons:
        if names[p.material_index] == "Pneu":
            vs.update(p.vertices)
    if not vs:
        return None
    co = [me.vertices[i].co for i in vs]
    lo = Vector((min(c.x for c in co), min(c.y for c in co), min(c.z for c in co)))
    hi = Vector((max(c.x for c in co), max(c.y for c in co), max(c.z for c in co)))
    c = (lo + hi) / 2.0
    span = hi - lo
    axis = min(range(3), key=lambda k: span[k])   # the axle: the direction of least spread
    rr = [math.sqrt(sum((v - c)[k] ** 2 for k in range(3) if k != axis)) for v in co]
    tt = [abs((v - c)[axis]) for v in co]
    return {"c": c, "axis": axis, "R": max(rr), "H": max(tt)}


def _spare(name, hub, fr, mats, R, H, steel):
    """An object of the gate spare, built at hub (axle +x) to be moved onto the gate by EXPORT: the AT
    spare tyre (steel False), or the steel spare rim (steel True). Its own AO as acc_shade (the bake
    keeps acc_ meshes out of every ray)."""
    import bmesh
    import bpy
    from mathutils import Vector
    import build_accessories as ba
    old = bpy.data.objects.get(name)
    if old is not None:
        bpy.data.objects.remove(old, do_unlink=True)
    me = bpy.data.meshes.new(name)
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    me.materials.append(mats["LiftSpareSteel" if steel else "LiftSpareTyre"])
    bm = bmesh.new()
    F = _Faces(bm, me, mats)
    if steel:
        n = _steel_rim(F, Vector(hub), fr, "LiftSpare")
    else:
        n = _tyre(F, Vector(hub), fr, "LiftSpare", R, H)
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    bm.to_mesh(me)
    bm.free()
    me.update()
    ob["lift_hub"] = tuple(hub)
    ob["lift_tyre"] = (R, H)
    shade = ba._shade(ob, 0.55)
    return ob, n, shade


def BUILD(report):
    import bpy
    src = bpy.data.objects.get("wheel_FR")
    if src is None:
        raise RuntimeError("lift: no wheel_FR to take the alloy rim from")
    for name in list(WHEEL_GEO.values()) + list(GATE_GEO.values()):    # a re-run replaces them
        old = bpy.data.objects.get(name)
        if old is not None:
            bpy.data.objects.remove(old, do_unlink=True)
    fr = _stock_frame(src)
    mats = _materials()
    alloy, a_rim, blocks = _alloy(src, fr, mats)
    steel, s_rim, _b = _steel(fr, mats)
    n = lambda ob: sum(len(p.vertices) - 2 for p in ob.data.polygons)   # noqa: E731
    report("FEATURE lift: wheel_lift_alloy %d tris (rim %d), wheel_lift_steel %d tris (rim %d), %d tread blocks; "
           "stock lip r %.4f at t %+.4f / %+.4f" % (n(alloy), a_rim, n(steel), s_rim, blocks, fr["r_lip"], fr["t_out"], fr["t_in"]))
    trunk = bpy.data.objects.get("trunk")
    dims = _spare_dims(trunk) if trunk is not None else None
    R, H = (dims["R"], dims["H"] - 0.0005) if dims else (SPARE_R, SPARE_HALF)
    tyre, _nt, sh_t = _spare(GATE_GEO["alloy"], SPARE_HUB, fr, mats, R, H, False)
    rim, _nr, sh_r = _spare(GATE_GEO["steel"], SPARE_STEEL_HUB, fr, mats, R, H, True)
    report("FEATURE lift: gate spare AT tyre %d tris (r %.4f, half width %.4f, own AO mean %.2f), steel spare rim %d tris "
           "(AO %.2f)%s" % (n(tyre), R, H, sh_t, n(rim), sh_r, "" if dims else "; NO stock spare found on the trunk: defaults"))


OBJECTS = {
    "wheel_lift_alloy": {"space": "lift", "file": "wheel"},
    "wheel_lift_steel": {"space": "lift", "file": "wheel"},
    # the gate spare's parts, baked on the shell, joined to copies of the gate at EXPORT
    GATE_GEO["alloy"]: {"space": "shell", "bone": "trunk_bone", "zone": "boot"},
    GATE_GEO["steel"]: {"space": "shell", "bone": "trunk_bone", "zone": "boot"},
}
# 1024: two wheels on one sheet get the stock wheel's per-wheel density (512) at the 512 Vehicle Texture
# Size cap most players run (the cap halves it), and twice that for those who raise the option
SPACES = {"lift": {"size": 1024, "texture": "Lift", "ao_k": 0.30, "gain": 1.0, "grime": ((96, 88, 74), 0.0)}}

# ---------------------------------------------------------------------------------------------
# bake (Blender, bake_atlas)


def _decal_axes(hub_z=TYRE_R):
    return ("y", -DECAL_R, DECAL_R), ("z", hub_z - DECAL_R, hub_z + DECAL_R)


def _stacks(P, png, hub_z, extra):
    """The material stacks of one wheel set: P the prefix, png its sidewall lettering, extra appended
    to every stack (the spare's own AO)."""
    out = {
        # the outer sidewall: the painted lettering replaces the rubber on the faces looking out (+x)
        P + "Tyre": [("decal", png) + _decal_axes(hub_z) + ("replace", [("normal", "x", ">", 0.45)]), ("noise", 90.0, 0.04)],
        P + "TyreIn": [("noise", 90.0, 0.04)],
        P + "Tread": [("noise", 140.0, 0.05)],
        P + "Groove": [("noise", 90.0, 0.04)],
        P + "Steel": [("noise", 160.0, 0.03)],
        P + "SteelLip": [("noise", 160.0, 0.03)],
        P + "SteelWell": [],
        P + "Rotor": [("noise", 220.0, 0.10)],
        P + "Dark": [],
        P + "Hidden": [],
        P + "Chrome": [("noise", 200.0, 0.04)],
    }
    return {k: v + list(extra) for k, v in out.items()}


BAKE_TEXTURED = dict(_stacks("Lift", SIDEWALL_PNG, TYRE_R, []),
                     **_stacks("LiftSpare", SPARE_SIDEWALL_PNG, SPARE_HUB[2], [("attr", "acc_shade")]))
BAKE_TEXTURED["LiftHubCap"] = [("hubdecal", "hubcap.png", 0.105)]     # the stock cap's H and nuts, on the alloy's hub
# texels where the game camera looks: the lettered outer sidewall most (its letters must survive the 512
# Vehicle Texture Size cap), the tread and the wheel face next, the inner side and hidden faces least
BAKE_MAT_WEIGHTS = {"LiftTyre": 2.4, "LiftTyreIn": 0.25, "LiftTread": 0.9, "LiftGroove": 0.5, "LiftHubCap": 1.6,
                    "LiftSteel": 1.0, "LiftSteelLip": 1.0, "LiftSteelWell": 0.4, "LiftRotor": 0.5, "LiftDark": 0.2,
                    "LiftChrome": 0.6, "LiftHidden": 0.05,
                    # the gate spare on the shell (fallback charts ~1.34 texels/cm at weight 1)
                    "LiftSpareTyre": 2.6, "LiftSpareTyreIn": 0.12, "LiftSpareTread": 0.7, "LiftSpareGroove": 0.35,
                    "LiftSpareSteel": 1.2, "LiftSpareSteelLip": 1.2, "LiftSpareSteelWell": 0.3, "LiftSpareRotor": 0.4,
                    "LiftSpareDark": 0.1, "LiftSpareChrome": 0.6, "LiftSpareHidden": 0.05}

LETTER_RGB = (0.74, 0.72, 0.66)          # linear: sRGB ~(224, 220, 211), white letters
RUBBER_RGB = MAT_COLOURS["LiftTyre"]


def _arc_text(img, text, font, height, rho, centre, inward, px_per_m, half):
    """Fill text on an arc into img (rows from the bottom, x right = object +y, y up = +z, hub at the
    centre): capitals `height` m tall, baseline at radius rho, centred on angle `centre`. inward False:
    reading clockwise with the letters' tops outward (the top of the tyre); True: reading
    counter-clockwise with the tops toward the hub (readable at the bottom). Every glyph point follows
    the arc (angle from its distance along the baseline, radius from its height)."""
    import numpy as np
    import tyre_paint
    tris = tyre_paint.text_tris(text, font)
    if not len(tris):
        return
    k = height / 0.716
    xs = tris[..., 0]
    x = (tris[..., 0] - (xs.min() + xs.max()) / 2.0) * k
    y = tris[..., 1] * k
    if inward:
        ang = centre + x / rho
        rad = rho - y
    else:
        ang = centre - x / rho
        rad = rho + y
    out = np.stack([np.cos(ang) * rad, np.sin(ang) * rad], axis=-1)
    out = (out + half) * px_per_m
    tyre_paint.fill_tris(img, out, 1.0)


def _paint_sidewall(path, scale):
    """One sidewall map: the outer sidewall seen from outside (+x), object y right, z up, the hub in the
    middle, rubber everywhere and the white raised lettering on the band LETTER_RHO, mapped onto the
    tyre `scale` (_Scale) builds: KESTREL over the top and under the bottom, TRAIL CLAW on both sides,
    all in the bold face, every word arced along the sidewall with its tops outward."""
    import numpy as np
    import tyre_paint
    size, ss = 2048, 2
    n = size * ss
    px_per_m = n / (2.0 * DECAL_R)
    mask = np.zeros((n, n), dtype=np.float32)
    big = tyre_paint._font(tyre_paint.BRAND_FONTS)
    lo, hi = scale.rho(LETTER_RHO[0]), scale.rho(LETTER_RHO[1])
    hb, hm = BRAND_H * scale.kr, MODEL_H * scale.kr
    mid = (lo + hi) / 2.0
    # every line reads with its letters' tops outward (toward the tread), as a moulded sidewall does: the
    # KESTREL under the hub is upside down to a standing reader. Until 2026-10-17 (review WHL-11) it was
    # turned to read from below, tops toward the hub, the one line on the tyre that did not
    _arc_text(mask, BRAND, big, hb, lo, math.pi / 2, False, px_per_m, DECAL_R)
    _arc_text(mask, BRAND, big, hb, lo, -math.pi / 2, False, px_per_m, DECAL_R)
    _arc_text(mask, MODEL_LINE, big, hm, mid - hm / 2.0, 0.0, False, px_per_m, DECAL_R)
    _arc_text(mask, MODEL_LINE, big, hm, mid - hm / 2.0, math.pi, False, px_per_m, DECAL_R)
    m = tyre_paint._down(mask, ss)
    m = tyre_paint._blur(m, 3, wrap_x=False)
    rgb = np.empty((size, size, 3), dtype=np.float64)
    for c in range(3):
        rgb[..., c] = RUBBER_RGB[c] + (LETTER_RGB[c] - RUBBER_RGB[c]) * m
    tyre_paint._save(rgb, path, srgb=True)
    print("bake: lift sidewall lettering -> %s (%d px, %.1f px/cm; letters r %.3f-%.3f, KESTREL %.1f cm)" % (
        path, size, size / (200.0 * DECAL_R), lo, hi, hb * 100))
    return path


def BAKE_PAINT(decal_dir):
    """lift_sidewall.png (the road wheels' 30 in. tyre) and lift_spare_sidewall.png (the gate spare's
    smaller one, its size read off the object BUILD made)."""
    rb = 0.2086 - 0.002
    spare = (SPARE_R, SPARE_HALF)
    try:
        import bpy
        src = bpy.data.objects.get("wheel_FR")
        if src is not None:
            rb = _stock_frame(src)["r_lip"] - 0.002
        ob = bpy.data.objects.get(GATE_GEO["alloy"])
        if ob is not None and "lift_tyre" in ob:
            spare = tuple(ob["lift_tyre"])
    except ImportError:
        pass
    _paint_sidewall(os.path.join(decal_dir, SIDEWALL_PNG), _Scale(rb))
    _paint_sidewall(os.path.join(decal_dir, SPARE_SIDEWALL_PNG), _Scale(rb, spare[0], spare[1]))
    return os.path.join(decal_dir, SIDEWALL_PNG)


# ---------------------------------------------------------------------------------------------
# export (Blender, export_fbx.export_all: after the rig and the back-face fill, before the FBX scaling)


def _link_copy(ob):
    import bpy
    c = ob.copy()
    c.data = ob.data.copy()
    for col in (ob.users_collection or [bpy.context.scene.collection]):
        col.objects.link(c)
    return c


def _gate_copy(trunk, mats, frame, cap):
    """A copy of the baked gate (UVs, zones, back faces, skin) without the stock spare's faces of mats
    (and, cap True, its centre cap) near its hub: the gate skin behind the spare stays."""
    import bmesh
    ob = _link_copy(trunk)
    me = ob.data
    names = [m.name if m else "" for m in me.materials]
    c = frame["c"]
    bm = bmesh.new()
    bm.from_mesh(me)
    kill = []
    for f in bm.faces:
        fc = f.calc_center_median()
        r = math.hypot(fc.x - c.x, fc.z - c.z)
        t = -(fc.y - c.y)                         # out of the gate (the spare looks rearward, -y)
        if r < 0.36 and -0.106 < t < 0.13:
            if names[f.material_index] in mats or (cap and r < 0.035 and t > 0.09):
                kill.append(f)
    bmesh.ops.delete(bm, geom=kill, context='FACES')
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context='VERTS')
    bm.to_mesh(me)
    bm.free()
    me.update()
    return ob, len(kill)


def _join(target, others):
    import bpy
    bpy.ops.object.select_all(action='DESELECT')
    for o in others + [target]:
        o.select_set(True)
    bpy.context.view_layer.objects.active = target
    bpy.ops.object.join()


def EXPORT(report, ctx):
    """The lifted gates: move the AT spare tyre and the steel spare rim from where BUILD made them onto
    the stock spare's hub (axle +x -> out of the gate, -y), then join acc_lift_gate_alloy = the gate
    without the stock spare's tyre + the AT tyre (the stock spare's own alloy stays: the lifted alloy car
    rides the same EX alloys), and acc_lift_gate_steel = the gate without the stock spare's tyre and rim
    + the AT tyre + the steel rim. Both keep the gate's skin (trunk_bone) and are exported in the body
    FBX like every acc_ mesh."""
    import bpy
    from mathutils import Matrix
    trunk = bpy.data.objects.get("trunk")
    tyre = bpy.data.objects.get(GATE_GEO["alloy"])
    rim = bpy.data.objects.get(GATE_GEO["steel"])
    if trunk is None or tyre is None or rim is None:
        raise RuntimeError("lift: the gate spare needs trunk, %s and %s" % (GATE_GEO["alloy"], GATE_GEO["steel"]))
    frame = _spare_dims(trunk)
    if frame is None or frame["axis"] != 1 or frame["c"].y > -1.5:
        raise RuntimeError("lift: no stock spare with its axle along y at the back of the gate (%r)" % (frame,))
    if trunk.matrix_world != Matrix.Identity(4) or tyre.matrix_world != Matrix.Identity(4):
        raise RuntimeError("lift: the gate and the spare must sit at the identity to be joined")
    tyre2 = _link_copy(tyre)
    for ob in (tyre, tyre2, rim):
        hub = ob["lift_hub"]
        m = (Matrix.Translation(frame["c"]) @ Matrix.Rotation(-math.pi / 2.0, 4, 'Z')
             @ Matrix.Translation((-hub[0], -hub[1], -hub[2])))
        ob.data.transform(m)
        ob.data.update()
    gate_a, ka = _gate_copy(trunk, GATE_MATS["alloy"], frame, False)
    gate_s, ks = _gate_copy(trunk, GATE_MATS["steel"], frame, True)
    _join(tyre, [gate_a])
    _join(rim, [gate_s, tyre2])
    n = lambda ob: sum(len(p.vertices) - 2 for p in ob.data.polygons)   # noqa: E731
    report("FEATURE lift: gates with the AT spare at (%.3f, %.3f, %.3f): %s %d tris (stock tyre's %d faces out), "
           "%s %d tris (stock tyre and rim's %d faces out); uv %s / %s" % (
               frame["c"].x, frame["c"].y, frame["c"].z, tyre.name, n(tyre), ka, rim.name, n(rim), ks,
               [u.name for u in tyre.data.uv_layers], [u.name for u in rim.data.uv_layers]))


def _kit_icon(ic):
    """The kit's inventory icon (gen_icons): a red lift spring and a yellow shock in front of a small AT
    tyre on its alloy (the tyre alone read as the vanilla Car Tire)."""
    return [ic.copy("wheel_lift_alloy", at=(0.06, 0.16, 0.20), rot=(0.0, 0.0, 90.0), scale=0.58),
            ic.coil("icon_kit_spring", (0.78, 0.10, 0.08), 0.085, 0.020, 4.5, 0.34, loc=(-0.12, -0.16, 0.0)),
            ic.cylinder("icon_kit_shock", (0.95, 0.74, 0.08), 0.036, 0.03, 0.27, loc=(0.13, -0.20, 0.0)),
            ic.cylinder("icon_kit_rod", (0.80, 0.80, 0.83), 0.013, 0.27, 0.40, loc=(0.13, -0.20, 0.0))]


ICONS = {"CRVGen1_LiftKit": (_kit_icon, 250.0, 20.0)}

# ---------------------------------------------------------------------------------------------
# scripts


def MODELS(gen):
    out = []
    for kind, name in WHEEL_MODELS.items():
        out.append("\tmodel %s\n\t{\n\t\tmesh = %s|crvgen1_%s,\n\t\tshader = vehiclewheel,\n\t\ttexture = %s_Lift,\n"
                   "\t\tscale = %s,\n\t\tinvertX = FALSE,\n\t}" % (name, gen.WHEEL_FBX, WHEEL_GEO[kind], gen.TEX, gen.SCALE))
    # the lifted gates: the stock gate's model block (both bones on its track: the rear glass and its
    # guard ride trunkglass_bone on TrunkDoor's player) on the gate-with-AT-spare geometry
    for kind, geo in GATE_GEO.items():
        out.append(gen.model_block(gen.acc_model_name(geo), "crvgen1_" + geo, static=False,
                                   bone=gen.GATE_BONES))
    return out


def _wheels(gen, x):
    """The stock WHEELS dropped LIFT_M, the track at x, the AT tyre's radius and width (gen_scripts
    wheel_blocks takes them as a 4th and 5th item)."""
    out = []
    for name, front, offset in [w[:3] for w in gen.WHEELS]:
        ox, oy, oz = (float(v) for v in offset.split())
        out.append((name, front, "%.4f %.4f %.4f" % (float(x) if ox > 0 else -float(x), oy - LIFT_M, oz),
                    "%.3ff" % TYRE_R, "%.3ff" % TYRE_W))
    return out


# The trade-off (roadmap): better off-road, a bit more body roll, slightly lower top speed. Bigger tyres
# gear the car taller (force at the wheel x 0.334 / 0.381), the kit and the tyres add ~40 kg, the longer
# springs and shocks travel further and roll more. Centre of mass, body boxes and extents are in the
# chassis frame, which rises with the body: they need no change. The springs keep the stock rate (38):
# the game draws a wheel at offset + restLength - the current suspension length (BaseVehicle.updateTransform,
# 42.21), so the ride height follows the static sag, which grows as 1 / suspensionStiffness. The softer 34
# sat the car ~1 cm lower than LIFT_M (and pzview / lift_check) model; rollInfluence carries the extra roll.
def _tuning(gen):
    # travel: the stock 10 cm is used up under a hard stop or turn while the lifted body hangs 7.5 cm higher,
    # and the chassis hit the road (2026-10-15): 15 cm of travel. Roll back at the stock value: the extra
    # roll was what let the body dip onto one side in a turn
    return gen.tuning_with(engineForce="4500", maxSpeed="88.0", rollInfluence="0.95",
                           suspensionRestLength="0.42", suspensionDamping="2.70", maxSuspensionTravelCm="15.0")


def _lift_gate(text, kind):
    """The lifted script's TrunkDoor draws the gate with the matching AT spare (its first and only model:
    the part's clip plays on its first model)."""
    import re
    new, n = re.subn(r"(part TrunkDoor\s*\{\s*model TrunkDoor\s*\{\s*file = )HondaCRVGen1Trunk,",
                     r"\g<1>HondaCRVGen1Acc_%s," % GATE_GEO[kind][len("acc_"):], text)
    if n != 1:
        raise RuntimeError("lift: the TrunkDoor model of %s was not found (%d)" % (VEHICLES[kind], n))
    return new


def _script(kind):
    def make(gen):
        return _lift_gate(gen.vehicle_script(VEHICLES[kind], off_road="1.35", mass=gen.MASS + 40,
                                             wheels=_wheels(gen, STOCK_X if kind == "alloy" else STEEL_X),
                                             tuning=_tuning(gen), wheel_model=WHEEL_MODELS[kind]), kind)
    return make


VEHICLE_SCRIPTS = {VEHICLES["alloy"]: _script("alloy"), VEHICLES["steel"]: _script("steel")}

ITEMS = {
    "CRVGen1_LiftKit": {"DisplayCategory": "VehicleMaintenance", "Weight": 25.0, "ItemType": "base:normal",
                        "DisplayName": "CRV Lift Kit (3 in.)", "Icon": "CRVGen1_LiftKit", "ConditionMax": 100,
                        "MechanicsItem": True, "Tags": "base:hasmetal", "Tooltip": "Tooltip_CRV_Lift_Kit"},
    "CRVGen1_LiftMagazine": {"DisplayCategory": "RecipeResource", "ItemType": "base:literature", "Weight": 0.5,
                             "DisplayName": "4x4 Off-Road: CRV Edition", "Icon": "CRVGen1_LiftMagazine", "BoredomChange": -20,
                             "StressChange": -15, "LearnedRecipes": "CRVGen1_MakeLiftKit",
                             "Tooltip": "Tooltip_CRV_Lift_Magazine", "StaticModel": "Magazine",
                             "WorldStaticModel": "MagazineMec1Ground", "Tags": "base:magazine",
                             "OnCreate": "ItemCodeOnCreate.onCreateRecipeMagazine"},   # re-reads go on cooldown
}

# the kit at a work surface: four coil springs (any car's suspension parts), spacer pipe and plate,
# four big tyres, welded up (craftRecipe format of 42.21's recipes_metalWelding.txt)
RECIPES = """\tcraftRecipe CRVGen1_MakeLiftKit
\t{
\t\ttimedAction = Welding_Surface,
\t\ttime = 1200,
\t\tNeedToBeLearn = true,
\t\tTags = AnySurfaceCraft,
\t\tcategory = Metalworking,
\t\tSkillRequired = MetalWelding:3;Mechanics:4,
\t\txpAward = MetalWelding:30;Mechanics:30,
\t\tinputs
\t\t{
\t\t\titem 4 [Base.NormalSuspension1;Base.NormalSuspension2;Base.NormalSuspension3;Base.ModernSuspension1;Base.ModernSuspension2;Base.ModernSuspension3],
\t\t\titem 4 tags[base:wholetire],
\t\t\titem 4 [Base.MetalPipe],
\t\t\titem 2 [Base.SheetMetal],
\t\t\titem 2 [Base.NutsBolts],
\t\t\titem 3 [Base.BlowTorch],
\t\t\titem 1 tags[base:weldingmask] mode:keep,
\t\t\titem 1 tags[base:wrench] mode:keep flags[MayDegradeLight],
\t\t}
\t\toutputs
\t\t{
\t\t\titem 1 Base.CRVGen1_LiftKit,
\t\t}
\t}"""

TRANSLATIONS = {
    "IG_UI": {
        "IGUI_VehicleNameHondaCRVGen1LiftAlloy": "Honda CRV (lifted, alloys)",
        "IGUI_VehicleNameHondaCRVGen1LiftSteel": "Honda CRV (lifted, steel wheels)",
        "IGUI_CRV_Lift_Lifted": "Lift kit fitted",
        "IGUI_CRV_Lift_Lowered": "Lift kit removed",
        "IGUI_CRV_Lift_Rewheeled": "Wheels swapped",
        "IGUI_CRV_Lift_Failed": "The conversion could not be finished",
    },
    "ContextMenu": {
        "ContextMenu_CRV_Lift_Menu": "Lift kit",
        "ContextMenu_CRV_Lift_Alloy": "Fit the 3 in. lift kit (EX alloys)",
        "ContextMenu_CRV_Lift_Steel": "Fit the 3 in. lift kit (black steel wheels)",
        "ContextMenu_CRV_Lift_Remove": "Remove the lift kit",
        "ContextMenu_CRV_Lift_ToSteel": "Swap to black steel wheels",
        "ContextMenu_CRV_Lift_ToAlloy": "Swap to the EX alloys",
    },
    "Tooltip": {
        "Tooltip_CRV_Lift_Kit": "A 3 in. suspension lift for the Honda CRV: longer springs, spacers, shocks, "
                                "four 30x9.50R15 all-terrain tyres and a set of black steel wheels.",
        "Tooltip_CRV_Lift_Magazine": "Teaches how to build a lift kit for a compact SUV.",
        "Tooltip_CRV_Lift_Needs": "Needs: ",
        "Tooltip_CRV_Lift_NeedKit": "a CRV lift kit",
        "Tooltip_CRV_Lift_NeedWrench": "a wrench",
        "Tooltip_CRV_Lift_NeedLugWrench": "a lug wrench",
        "Tooltip_CRV_Lift_NeedJack": "a jack",
        "Tooltip_CRV_Lift_NeedSkill": "Mechanics level %1",
        "Tooltip_CRV_Lift_Passengers": "Everybody out of the car first",
        "Tooltip_CRV_Lift_Trailer": "Unhitch the trailer first",
        "Tooltip_CRV_Lift_Key": "Take the key out of the ignition and off the door",
        "Tooltip_CRV_Lift_Engine": "Stop the engine first",
        "Tooltip_CRV_Lift_Ground": "Needs open ground or a parking spot",
        "Tooltip_CRV_Lift_Burnt": "The car is a wreck",
        "Tooltip_CRV_Lift_Busy": "Everybody else stand back from the car",
        "Tooltip_CRV_Lift_Time": "Takes a long time. The kit comes back when the lift is removed.",
    },
    # 42.21 looks recipe names up by the bare craftRecipe name (CraftRecipe.Load -> Translator.getRecipeName)
    "Recipes": {"CRVGen1_MakeLiftKit": "Make CRV Lift Kit"},
}

LUA = ["shared/HondaCRVGen1_Lift.lua", "shared/TimedActions/ISCRVLiftConvert.lua", "client/HondaCRVGen1_LiftMenu.lua"]
# the magazine's hand-made icon (scripts/lift_media.py draws it); the kit's comes from ICONS
MEDIA = ["common/media/textures/Item_CRVGen1_LiftMagazine.png"]

DISTRIBUTIONS = [
    # the kit: rare, in garages, auto shops and mechanic crates (MechanicsItem also follows the Mechanics loot slider)
    {"list": "GarageMechanics", "item": "Base.CRVGen1_LiftKit", "weight": 0.3},
    {"list": "CrateMechanics", "item": "Base.CRVGen1_LiftKit", "weight": 0.4},
    {"list": "MechanicShelfMisc", "item": "Base.CRVGen1_LiftKit", "weight": 0.2},
    {"list": "MechanicSpecial", "item": "Base.CRVGen1_LiftKit", "weight": 0.5},
    # the magazine: car-supply and automotive shelves, magazine racks
    {"list": "CarSupplyMagazines", "item": "Base.CRVGen1_LiftMagazine", "weight": 2.0},
    {"list": "BookstoreAutomotive", "item": "Base.CRVGen1_LiftMagazine", "weight": 1.0},
    {"list": "MagazineRackMixed", "item": "Base.CRVGen1_LiftMagazine", "weight": 0.2},
    {"list": "CrateMagazines", "item": "Base.CRVGen1_LiftMagazine", "weight": 0.2},
    {"list": "GarageMechanics", "item": "Base.CRVGen1_LiftMagazine", "weight": 0.2},
]
