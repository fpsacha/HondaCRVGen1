r"""
Cargo clutter (feature round 2026-10-19): what the player loads into the trunk shows in the cargo bay, through
the rear and quarter glass and with the gate open, and grows with how full the trunk is. Our own code.

The trunk is the vanilla SUV template's part TruckBed (template Trunk/part/TruckBed: item Base.NormalTrunk,
capacity from the vehicle's trunk item). Its fill (container weight over capacity) picks a state, like the roof
rack's cargo (HondaCRVGen1Accessories.lua, Acc.updateRack): 0 empty, 1 from FILL[0], 2 from FILL[1], 3 from
FILL[2]. The states are INCREMENTAL: model InteriorClutter<k> holds only what state k adds, and state n shows
models 1..n, so every piece sits in the same place in every state it appears in and the file carries each piece
once. Part CRVClutterCargo (no item, category nodisplay, setAllModelsVisible = false: the engine never shows or
resets its models) lists the models; shared/HondaCRVGen1_Clutter.lua shows them.

  1 (~10 %)  a faded olive duffel (girth straps, handles tied by a wrap, a zip) across the back left, a taped
             carton (bevelled, crossing tape, a shipping label) in the front right
  2 (~40 %)  + a picnic cooler (faded blue tub, off-white lid standing proud of it, end grips) in the back right,
             an open carton (one flap laid open against the side trim, the other closed) in the front left,
             a day pack leaning on the seat backs between the cartons
  3 (~75 %)  + a steel toolbox (lid ridge, latch, handle) on the closed carton, a dirty red gas can between the
             duffel and the cooler, a navy kit bag lying on the duffel and draped over the open carton's edge, a
             rolled wool blanket filling the gap between the carton and the cooler

Quality pass (2026-10-19, the owner: "the clutter should look better", it read as toy blocks): muted, slightly worn
colours; soft bags with rounded ends, a belly and a sag, webbing that reads as straps; bevelled cartons; every
piece turned a few degrees (built in its own frame, then placed), tallest at the seat backs, lower toward the gate,
gaps filled, the draped bag resting on what the ray casts find under it (nothing floats). Details that must follow
a turned piece are geometry (tape, label, flaps, latch, grips) and its own material; the bags lie along the car's
axes, so their zips and end panels can stay model-space tints. Contact shadows come from the pieces' own
occlusion (acc_shade, k 0.7) plus the car's AO in the bake.

Where (measured on the built car, 2026-10-19, scratch clutter/probe_bay.py, probe_glass.py on crv_kotris.blend):
  * floor: the cargo deck at z 0.766, the picnic table flush in it at 0.768 (|x| < 0.39, y -1.24..-1.92); pieces
    stand at FLOOR_Z 0.767 (their bottoms 1 mm into the table top, never seen);
  * front: the upright rear seat backs (acc_function_seats_up) at y -1.057 (z 0.8) leaning back to -1.114 (z 1.2):
    nothing forward of y -1.155;
  * back: the floor ends at y ~-1.97, the gate's inner skin is at y -2.10 (z 0.8) .. -2.065 (z 1.1) and the
    lift glass leans in over the deck above z 1.15 (y -2.03 at 1.2, -1.83 at its top), its gas struts at
    |x| 0.40-0.585, y ~-1.88, z 1.20-1.46: nothing behind y -1.905, nothing behind y -1.84 above z 1.135;
  * sides: the lower trims at |x| 0.552 (z 0.8, y -1.5..-1.8): everything inside |x| 0.525, except above z 0.95
    between y -1.53 and -1.17, where the trim stands at |x| 0.70 (the open flap leans out to ~0.59);
  * glass: the quarter glass starts at z ~1.17 (body Vitre at x 0.74), the gate glass at z ~1.17: the load
    stays under ~1.205 (1.135 at the gate), so it reads through the glass from the game camera (30 degrees
    down, the far half of the deck is in view through each quarter window) and never presses on it.

The table out (CRVPicnicTable without its item): the deck has the open well under it (rounded tub, flat bottom
z 0.526 at |x| < 0.25, y -1.35..-1.80, lip z 0.735 at |x| 0.40, y -1.25 / -1.90). Every piece above stands
partly over that hole, so with the table out the Lua also shows InteriorClutterWell, a grey wool blanket and
the soft stuff under it filling the well to just under the deck (WELL_TOP): the load rests on it, nothing
floats. One cheap mesh, not a second set of states.

Folded seats (HondaCRVGen1.Shared.isBed, State key function_folded): nothing shows (the bed builder's made bed
lies there). The lua says how it follows the fill on every side (State key clutter_load, derived on the
authoritative side on a 15-tick tick like the rack's; the game has no container-changed hook that reaches the
server or other clients: OnContainerUpdate is a client UI refresh, ItemContainer.addItem fires nothing).

Sheet: the feature's own 512 "clutter" sheet (vehiclewheel shader, like the offroad pieces), not the shell
(its layout gate) nor the interior (the cabin's density).
"""
import math

KEY = "clutter"
TEX_NAME = "Clutter"
PART = "CRVClutterCargo"                       # HondaCRVGen1.Clutter.PART
LUA_NS = "HondaCRVGen1.Clutter"
TIERS = ["acc_clutter_load1", "acc_clutter_load2", "acc_clutter_load3"]
WELL = "acc_clutter_well"
# model ids (HondaCRVGen1.Clutter.MODELS / .WELL); 'Interior' in the name: pzview's cabin ID pass paints them
# with the cabin (a slit that shows the cargo is a slit)
MODEL_IDS = ["InteriorClutter1", "InteriorClutter2", "InteriorClutter3"]
WELL_ID = "InteriorClutterWell"
FILL = (0.10, 0.40, 0.75)                      # HondaCRVGen1.Clutter.FILL (share of the trunk's weight capacity)
TRI_BUDGET = 1320                              # the full load (tiers 1-3); the well blanket on top (BUILD checks)
CORNER_SEG = 3                                 # the cooler's rounded corners (round 5: one chamfer a corner read as an
                                               # octagonal block at eye level); the gas can takes 2
SHADE_K = 0.70                                 # the pieces' own occlusion (build_accessories._shade)


def _lin(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


# ---------------------------------------------------------------------------------------------
# materials (this feature's own; index = position, the objects carry only these). sRGB, muted and a little worn
SRGB = {
    "AccClutterCanvas": (112, 108, 74),        # faded olive canvas duffel
    "AccClutterCard": (160, 126, 88),          # brown corrugated board
    "AccClutterFlap": (134, 104, 72),          # the flaps, a shade darker (handled, sun-faded edges)
    "AccClutterCardIn": (62, 48, 34),          # inside an open carton
    "AccClutterTape": (186, 160, 118),         # tan packing tape
    "AccClutterLabel": (212, 208, 196),        # a printed shipping label
    "AccClutterCooler": (92, 114, 134),        # faded blue cooler tub
    "AccClutterLid": (204, 201, 188),          # its off-white lid
    "AccClutterCan": (118, 42, 34),            # dirty dark red plastic gas can
    "AccClutterTool": (72, 82, 92),            # grey-blue enamelled steel toolbox
    "AccClutterSteel": (150, 150, 146),        # latch, toolbox handle
    "AccClutterBlack": (34, 34, 33),           # webbing, grips, the spout
    "AccClutterPack": (72, 84, 64),            # muted forest green day pack
    "AccClutterPackDk": (60, 70, 54),          # its front pocket (52, 60, 48 read as a dark hole at eye level)
    "AccClutterNylon": (54, 62, 80),           # faded navy kit bag
    "AccClutterRoll": (126, 82, 62),           # rust-brown wool blanket, rolled
    "AccClutterBlanket": (110, 100, 90),       # the grey-brown blanket in the well
}
MATS = list(SRGB)
(CANVAS, CARD, FLAP, CARDIN, TAPE, LABEL, COOLER, LID, CAN, TOOL, STEEL, BLACK, PACK, PACKDK, NYLON, ROLL,
 BLANKET) = range(len(MATS))
COLOURS = {k: tuple(_lin(c) for c in v) for k, v in SRGB.items()}       # linear, refined by BAKE_TEXTURED
ZIP = tuple(_lin(c) for c in (40, 40, 38))
END_DARK = 0.78                                # the bags' end panels: x this of the body colour

# ---------------------------------------------------------------------------------------------
# layout (metres, model space: +x right, +y forward, +z up, ground 0); yaw in degrees about +z
FLOOR_Z = 0.767
# soft bags: section (v / w across, z / h up, counter-clockwise): a flat bottom, full sides, a rounded top
BAG_PROF = [(0.32, 0.0), (0.49, 0.15), (0.50, 0.45), (0.40, 0.78), (0.16, 0.98),
            (-0.16, 0.98), (-0.40, 0.78), (-0.50, 0.45), (-0.49, 0.15), (-0.32, 0.0)]
DUFFEL = dict(xc=-0.270, yc=-1.745, along="x", length=0.46, w=0.30, h=0.25, mat=CANVAS, straps=True)
KITBAG = dict(xc=-0.330, yc=-1.605, along="y", length=0.50, w=0.26, h=0.11, mat=NYLON, straps=False)
# cartons: centre (x, y), half sizes (along x, along y), height, yaw
BOX_A = dict(c=(0.325, -1.312), ab=(0.170, 0.145), h=0.25, yaw=-4.0)        # closed, taped both ways, a label
BOX_B = dict(c=(-0.340, -1.335), ab=(0.160, 0.155), h=0.24, yaw=7.0)        # open: one flap out to the side trim
COOLER_ = dict(c=(0.325, -1.745), ab=(0.165, 0.135), h=(0.262, 0.322), yaw=-5.0)
CAN_ = dict(c=(0.040, -1.760), ab=(0.068, 0.130), h=0.262, yaw=6.0)
TOOLBOX = dict(c=(0.0, 0.020), ab=(0.150, 0.075), h=(0.095, 0.025), yaw=9.0)    # in BOX_A's frame, on its top
PACK_ = dict(c=(-0.015, -1.285), ab=(0.130, 0.080), h=0.385, yaw=-6.0, lean=0.10)
ROLL_ = dict(c=(0.320, -1.530), r=0.060, length=0.34, yaw=4.0)
# the well (table out): its flat bottom and lip, measured; the blanket's top
WELL_C_Y = -1.575
WELL_TOP = 0.759

# what each state adds (built in this order: the kit bag rests on what the earlier pieces put under it)
TIER_PIECES = [["duffel", "box_a"], ["cooler", "box_b", "pack"], ["toolbox", "can", "roll", "kitbag"]]

OBJECTS = {n: {"space": KEY, "texel_w": True} for n in TIERS + [WELL]}
SPACES = {KEY: {"size": 512, "texture": TEX_NAME, "ao_k": 0.30, "gain": 1.0, "grime": ((96, 88, 74), 0.0)}}


# ---------------------------------------------------------------------------------------------
# geometry helpers (Blender only)


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
        b.inputs['Roughness'].default_value = 0.5 if name in ("AccClutterLid", "AccClutterCooler", "AccClutterCan",
                                                             "AccClutterTape", "AccClutterSteel") else 0.8
        out.append(m)
    return out


def _obj(name, bm):
    """A mesh object from bm with this feature's materials only, in the body's collection."""
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


def _frame(x, y, z, yaw):
    from mathutils import Matrix
    return Matrix.Translation((x, y, z)) @ Matrix.Rotation(math.radians(yaw), 4, 'Z')


def _place(dst, build, M, lean=0.0):
    """Build a piece into its own bmesh (its frame: base centre at the origin, +z up), lean it (y += lean * z, a
    shear that keeps its bottom on the floor), move it by M and append it to dst."""
    import bmesh
    import bpy
    b = bmesh.new()
    build(b)
    if lean:
        for v in b.verts:
            v.co.y += lean * v.co.z
    bmesh.ops.transform(b, matrix=M, verts=b.verts)
    me = bpy.data.meshes.new("_clutter_tmp")
    b.to_mesh(me)
    b.free()
    dst.from_mesh(me)
    bpy.data.meshes.remove(me)


def _ring(xc, yc, a, b, r, z, BA, seg=1):
    return [(xc + x, yc + y, z) for x, y in BA._rr(a, b, r, seg)]


def _bag(BA, bm, bag, base):
    """A soft bag lying down, in model space along x or y: a flat-bottomed body lofted through BAG_PROF, ends
    pulled in and rounded, a belly and a sag mid-length, flat end panels; with straps, two webbing girth bands (the
    loft's own faces between station pairs, black) and two handles arched in to a wrap over the zip. base(u) is the
    height its bottom rests at, station by station (a bag lying over things). Returns its top height at the middle."""
    L = bag["length"] / 2.0
    w, h, xc, yc, mat = bag["w"], bag["h"], bag["xc"], bag["yc"], bag["mat"]

    def T(u, v, z):                                             # bag frame (u along, v across) -> model
        return (xc + u, yc + v, z) if bag["along"] == "x" else (xc - v, yc + u, z)
    if bag["straps"]:
        st = [(-L, 0.62, 0.0, mat), (-L + 0.035, 0.90, 0.0, mat), (-0.150, 1.02, -0.004, BLACK), (-0.115, 1.03, -0.008, mat),
              (0.0, 1.06, -0.015, mat), (0.115, 1.03, -0.008, BLACK), (0.150, 1.02, -0.004, mat), (L - 0.035, 0.90, 0.0, mat),
              (L, 0.62, 0.0, None)]
    else:
        st = [(-L, 0.62, 0.0, mat), (-L + 0.04, 0.92, 0.0, mat), (0.0, 1.04, -0.010, mat),
              (L - 0.04, 0.92, 0.0, mat), (L, 0.62, 0.0, None)]

    def section(u, s, sag):
        out = []
        for k, (pv, pz) in enumerate(BAG_PROF):
            wob = 0.004 * math.sin(7.0 * u + 2.1 * k + xc * 13.0) if abs(u) < L - 0.02 else 0.0   # soft cloth
            z = h / 2 + (pz * h - h / 2) * s + (sag * pz if pz > 0.5 else 0.0) + wob * pz
            out.append((pv * w * s + wob * pv, max(0.002, z)))
        return out
    secs = [section(u, s, g) for u, s, g, _m in st]
    BA._loft(bm, [[T(u, v, base(u) + z) for v, z in sec] for (u, _s, _g, _m), sec in zip(st, secs)],
             [m for _u, _s, _g, m in st[:-1]], smooth=True, cap_mats=(mat, mat))
    top = [(u, base(u) + (sec[4][1] + sec[5][1]) / 2) for (u, _s, _g, _m), sec in zip(st, secs)]

    def top_z(u):
        for (ua, za), (ub, zb) in zip(top, top[1:]):
            if ua <= u <= ub:
                return za + (zb - za) * (u - ua) / (ub - ua)
        return top[-1][1]
    if bag["straps"]:
        # two handles, each a rounded arch leaning in from its side of the zip to a hook-and-loop wrap over the zip
        # (one-bend handles read as a sharp ^ each, and the pair with the zip between them as a dark X)
        rise = 0.030
        for sv in (-1.0, 1.0):
            pts = [T(u, sv * (0.036 - 0.024 * k), top_z(u) - 0.002 + rise * k) for u, k in ((-0.11, 0.0), (-0.05, 0.9),
                                                                                            (0.05, 0.9), (0.11, 0.0))]
            BA._sweep(bm, pts, BA._rect(0.022, 0.005), ups=[(0.0, 0.0, 1.0)] * len(pts), smooth=False, mat=BLACK)
        zt = top_z(0.0) - 0.002 + rise * 0.9
        lo, hi = T(-0.030, -0.020, zt - 0.009), T(0.030, 0.020, zt + 0.007)
        BA._box(bm, tuple(min(p, q) for p, q in zip(lo, hi)), tuple(max(p, q) for p, q in zip(lo, hi)), mat=BLACK)
    else:
        # one carry handle along the bag beside the zip, a low rounded arch (across the zip it read as a dark +)
        sv = 0.032
        pts = [T(u, sv, top_z(u) - 0.004 + rise) for u, rise in ((-0.09, 0.0), (-0.04, 0.024), (0.04, 0.024), (0.09, 0.0))]
        BA._sweep(bm, pts, BA._rect(0.022, 0.005), ups=[(0.0, 0.0, 1.0)] * len(pts), smooth=False, mat=BLACK)
    return top_z(0.0)


def _bevel_box(BA, b, a, bb, h, mat, top_mat=None, bev=0.008, r=0.014):
    """A box with softened edges (a chamfer ring top and bottom, rounded corners): base centre at the origin."""
    BA._loft(b, [_ring(0, 0, a - bev, bb - bev, max(0.004, r - bev), 0.0, BA), _ring(0, 0, a, bb, r, bev, BA),
                 _ring(0, 0, a, bb, r, h - bev, BA), _ring(0, 0, a - bev, bb - bev, max(0.004, r - bev), h, BA)],
             [mat, mat, mat], cap_mats=(mat, top_mat if top_mat is not None else mat))


def _tape(BA, b, along, half, h, down, width=0.048, lift=0.0):
    """A strip of tape over the top of a box along x or y (half = the box's half size that way), down `down`
    on both end faces: a closed 2.5 mm strip lying 1 mm off the board."""
    t = 0.0025
    o = half + 0.001
    z = h + 0.001 + lift
    if along == "x":
        pts = [(-o, 0.0, h - down), (-o, 0.0, z), (o, 0.0, z), (o, 0.0, h - down)]
        ups = [(-1.0, 0.0, 0.0), (-0.7071, 0.0, 0.7071), (0.7071, 0.0, 0.7071), (1.0, 0.0, 0.0)]
    else:
        pts = [(0.0, -o, h - down), (0.0, -o, z), (0.0, o, z), (0.0, o, h - down)]
        ups = [(0.0, -1.0, 0.0), (0.0, -0.7071, 0.7071), (0.0, 0.7071, 0.7071), (0.0, 1.0, 0.0)]
    pts = [tuple(p[k] + ups[i][k] * t / 2 for k in range(3)) for i, p in enumerate(pts)]
    BA._sweep(b, pts, BA._rect(width, t), ups=ups, smooth=False, mat=TAPE)


def _carton_a(BA, b):
    a, bb = BOX_A["ab"]
    h = BOX_A["h"]
    _bevel_box(BA, b, a, bb, h, CARD, top_mat=FLAP)
    _tape(BA, b, "x", a, h, 0.07)                               # along the flaps' seam, then across it
    _tape(BA, b, "y", bb, h, 0.05, lift=0.0026)
    BA._box(b, (-0.11, -bb - 0.0015, 0.08), (0.0, -bb + 0.002, 0.16), mat=LABEL)    # shipping label to the gate


def _carton_b(BA, b):
    """An open carton: its top the dark inside, the right flap closed over half of it, the left one laid open
    outward (55 degrees up) toward the side trim."""
    from mathutils import Vector
    a, bb = BOX_B["ab"]
    h = BOX_B["h"]
    _bevel_box(BA, b, a, bb, h, CARD, top_mat=CARDIN)
    BA._slab(b, [(0.003, -bb + 0.012, h + 0.002), (a - 0.012, -bb + 0.012, h + 0.002), (a - 0.012, bb - 0.012, h + 0.002),
                 (0.003, bb - 0.012, h + 0.002)], (0, 0, 1), 0.004, mat=FLAP)
    L = a * 0.95
    ang = math.radians(55.0)
    hx, ox, oz = -a + 0.008, -a + 0.008 - L * math.cos(ang), h + L * math.sin(ang)
    n = Vector((-math.sin(ang), 0.0, -math.cos(ang))) * -1.0     # the flap's normal (up and out)
    BA._slab(b, [(hx, -bb + 0.012, h), (hx, bb - 0.012, h), (ox, bb - 0.012, oz), (ox, -bb + 0.012, oz)], tuple(n), 0.004, mat=FLAP)
    BA._box(b, (-0.05, -bb - 0.0015, 0.07), (0.05, -bb + 0.002, 0.13), mat=LABEL)


def _cooler(BA, b):
    """A 1990s picnic cooler: a faded blue tub with rounded corners, an off-white lid standing proud of it all round
    (its seam the shadow line under the overhang), a moulded black grip at each end."""
    a, bb = COOLER_["ab"]
    hb, hl = COOLER_["h"]
    k = CORNER_SEG
    BA._loft(b, [_ring(0, 0, a - 0.008, bb - 0.008, 0.030, 0.0, BA, k), _ring(0, 0, a, bb, 0.038, 0.012, BA, k),
                 _ring(0, 0, a, bb, 0.038, hb, BA, k)], [COOLER, COOLER])
    BA._loft(b, [_ring(0, 0, a + 0.007, bb + 0.007, 0.045, hb - 0.006, BA, k), _ring(0, 0, a + 0.007, bb + 0.007, 0.045, hb + 0.026, BA, k),
                 _ring(0, 0, a - 0.012, bb - 0.012, 0.030, hl, BA, k)], [LID, LID])
    for s in (-1.0, 1.0):
        x_in, x_out = s * (a - 0.004), s * (a + 0.015)
        BA._box(b, (min(x_in, x_out), -0.050, hb - 0.055), (max(x_in, x_out), 0.050, hb - 0.022), mat=BLACK)


def _gas_can(BA, b):
    """A dirty red plastic gas can, upright: a rounded body to a sloped shoulder, a carry handle moulded along its
    top, a black spout leaning out at the front shoulder."""
    a, bb = CAN_["ab"]
    h = CAN_["h"]
    BA._loft(b, [_ring(0, 0, a - 0.005, bb - 0.005, 0.024, 0.0, BA, 2), _ring(0, 0, a, bb, 0.028, 0.010, BA, 2),
                 _ring(0, 0, a, bb, 0.028, h - 0.040, BA, 2), _ring(0, -0.012, a - 0.022, bb - 0.035, 0.018, h, BA, 2)], [CAN, CAN, CAN])
    pts = [(0.0, -0.085, h - 0.008), (0.0, -0.065, h + 0.038), (0.0, 0.010, h + 0.038), (0.0, 0.030, h - 0.008)]
    BA._sweep(b, pts, BA._rect(0.024, 0.016), ups=[(1.0, 0.0, 0.0)] * len(pts), smooth=False, mat=CAN)
    BA._sweep(b, [(0.0, bb - 0.050, h - 0.020), (0.0, bb + 0.008, h + 0.040)], BA._round(0.013, 6), smooth=True, mat=BLACK)


def _toolbox(BA, b):
    """A grey-blue steel toolbox: a softened body, a lid a little proud of it with a ridge along the top, a steel
    handle over the ridge, a latch on the front."""
    a, bb = TOOLBOX["ab"]
    hb, hl = TOOLBOX["h"]
    BA._box(b, (-a, -bb, 0.0), (a, bb, hb), mat=TOOL)         # (the lid's overhang softens the top edge)
    BA._box(b, (-a - 0.004, -bb - 0.004, hb - 0.002), (a + 0.004, bb + 0.004, hb + hl), mat=TOOL)
    top = hb + hl
    BA._box(b, (-a + 0.012, -0.016, top - 0.001), (a - 0.012, 0.016, top + 0.010), mat=TOOL)
    pts = [(-0.070, 0.0, top + 0.006), (-0.050, 0.0, top + 0.036), (0.050, 0.0, top + 0.036), (0.070, 0.0, top + 0.006)]
    BA._sweep(b, pts, BA._rect(0.016, 0.010), ups=[(0.0, 1.0, 0.0)] * len(pts), smooth=False, mat=STEEL)
    BA._box(b, (-0.018, -bb - 0.010, hb - 0.030), (0.018, -bb + 0.002, hb + 0.012), mat=STEEL)


def _backpack(BA, b):
    """A day pack standing on the floor and leaning on the seat backs (the shear in _place): a rounded body
    tapering to its top, a darker front pocket on the side to the gate."""
    a, bb = PACK_["ab"]
    h = PACK_["h"]
    BA._loft(b, [_ring(0, 0, a - 0.015, bb - 0.015, 0.040, 0.0, BA), _ring(0, 0, a, bb, 0.050, 0.030, BA),
                 _ring(0, 0, a, bb, 0.050, h - 0.085, BA), _ring(0, 0, a - 0.035, bb - 0.020, 0.045, h - 0.025, BA),
                 _ring(0, 0, a - 0.080, bb - 0.040, 0.030, h, BA)], [PACK] * 4, smooth=True)
    py = -bb + 0.010
    BA._loft(b, [_ring(0, py, 0.095, 0.030, 0.025, 0.040, BA), _ring(0, py - 0.006, 0.100, 0.033, 0.028, 0.160, BA),
                 _ring(0, py, 0.085, 0.022, 0.018, 0.220, BA)], [PACKDK, PACKDK], smooth=True)
    # a webbing grab loop over the top (round 5: without it the pack read as a smooth green pod)
    pts = [(-0.032, 0.0, h - 0.012), (-0.020, 0.0, h + 0.016), (0.020, 0.0, h + 0.016), (0.032, 0.0, h - 0.012)]
    BA._sweep(b, pts, BA._rect(0.018, 0.005), ups=[(0.0, -1.0, 0.0)] * len(pts), smooth=False, mat=BLACK)
    # the main compartment's zip, an arch over the front above the pocket (on the flat of the front, |x| <= a - r)
    y = -bb - 0.0015
    pts = [(-0.080, y, 0.215), (-0.080, y, 0.262), (-0.052, y, 0.290), (0.052, y, 0.290), (0.080, y, 0.262), (0.080, y, 0.215)]
    BA._sweep(b, pts, BA._rect(0.010, 0.003), ups=[(0.0, -1.0, 0.0)] * len(pts), smooth=False, mat=BLACK)


def _roll(BA, b):
    """A wool blanket rolled up and held by two black straps (bands of the roll's own faces), lying along x."""
    r, L = ROLL_["r"], ROLL_["length"] / 2.0
    n = 8
    ang = [math.pi / n + 2 * math.pi * k / n for k in range(n)]

    def ring(x, s):
        return [(x, r * s * math.cos(t), r + r * s * math.sin(t)) for t in ang]
    xs = [(-L, 1.0, ROLL), (-0.11, 0.96, BLACK), (-0.08, 0.96, ROLL), (0.08, 0.96, BLACK), (0.11, 0.96, ROLL),
          (L, 1.0, None)]
    BA._loft(b, [ring(x, s) for x, s, _m in xs], [m for _x, _s, m in xs[:-1]], smooth=True, cap_mats=(ROLL, ROLL))


def _well(BA, bm):
    """The well's contents with the table out: a grey wool blanket over the soft stuff in the tub, its walls
    against the tub's (5 mm inside, measured: flat bottom at 0.526 |x| < 0.25, y -1.35..-1.80; x 0.35 at
    0.66; lip 0.735 at |x| 0.40, y -1.25 / -1.90), its top a lumpy rounded mound just under the deck."""
    yc = WELL_C_Y
    rings = [_ring(0.0, yc, 0.240, 0.215, 0.060, 0.531, BA, seg=2), _ring(0.0, yc, 0.330, 0.275, 0.080, 0.655, BA, seg=2),
             _ring(0.0, yc, 0.385, 0.310, 0.090, 0.734, BA, seg=2)]
    top = []
    for k, (x, y, _z) in enumerate(_ring(0.0, yc, 0.375, 0.300, 0.090, 0.0, BA, seg=2)):
        top.append((x, y, WELL_TOP - 0.006 + 0.004 * math.sin(2.7 * k)))
    rings.append(top)
    BA._loft(bm, rings, [BLANKET] * 3, smooth=True, apex=(None, (0.02, yc + 0.03, WELL_TOP)))


def _resting_base(bag, objs, sink=0.010, sag=0.028):
    """base(u) for a bag lying over the given objects: under each point of its centre line the highest surface a ray
    from above finds (the floor where there is nothing), sunk `sink` into soft things; across a gap the bag spans
    from support to support, sagging `sag` (it never drops to the floor between two supports)."""
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    trees = [BVHTree.FromPolygons([v.co.copy() for v in o.data.vertices], [list(p.vertices) for p in o.data.polygons])
             for o in objs]
    L = bag["length"] / 2.0
    us = [-L + 2 * L * i / 24 for i in range(25)]
    hits = []
    for u in us:
        x, y = (bag["xc"] + u, bag["yc"]) if bag["along"] == "x" else (bag["xc"], bag["yc"] + u)
        z = FLOOR_Z
        for dv in (-0.5 * bag["w"] * 0.4, 0.0, 0.5 * bag["w"] * 0.4):
            px, py = (x, y + dv) if bag["along"] == "x" else (x + dv, y)
            for t in trees:
                hit = t.ray_cast(Vector((px, py, 2.0)), Vector((0.0, 0.0, -1.0)))
                if hit[0] is not None:
                    z = max(z, hit[0].z)
        hits.append(z - sink if z > FLOOR_Z + 0.01 else z)
    hull = []                                                   # upper hull of the supports
    for p in zip(us, hits):
        while len(hull) >= 2 and ((hull[-1][0] - hull[-2][0]) * (p[1] - hull[-2][1])
                                  - (hull[-1][1] - hull[-2][1]) * (p[0] - hull[-2][0])) >= 0:
            hull.pop()
        hull.append(p)

    def hull_z(u):
        for (ua, za), (ub, zb) in zip(hull, hull[1:]):
            if ua <= u <= ub:
                return za + (zb - za) * (u - ua) / max(1e-9, ub - ua)
        return hull[-1][1]

    def base(u):
        i = min(range(len(us)), key=lambda k: abs(us[k] - u))
        return max(hits[i], hull_z(u) - sag)
    return base


def _build_tier(BA, k, built):
    import bmesh
    bm = bmesh.new()
    fa = _frame(BOX_A["c"][0], BOX_A["c"][1], FLOOR_Z, BOX_A["yaw"])
    for piece in TIER_PIECES[k]:
        if piece == "duffel":
            _bag(BA, bm, DUFFEL, lambda u: FLOOR_Z)
        elif piece == "box_a":
            _place(bm, lambda b: _carton_a(BA, b), fa)
        elif piece == "box_b":
            _place(bm, lambda b: _carton_b(BA, b), _frame(BOX_B["c"][0], BOX_B["c"][1], FLOOR_Z, BOX_B["yaw"]))
        elif piece == "cooler":
            _place(bm, lambda b: _cooler(BA, b), _frame(COOLER_["c"][0], COOLER_["c"][1], FLOOR_Z, COOLER_["yaw"]))
        elif piece == "can":
            _place(bm, lambda b: _gas_can(BA, b), _frame(CAN_["c"][0], CAN_["c"][1], FLOOR_Z, CAN_["yaw"]))
        elif piece == "toolbox":
            ft = fa @ _frame(TOOLBOX["c"][0], TOOLBOX["c"][1], BOX_A["h"] + 0.0008, TOOLBOX["yaw"])
            _place(bm, lambda b: _toolbox(BA, b), ft)
        elif piece == "pack":
            _place(bm, lambda b: _backpack(BA, b), _frame(PACK_["c"][0], PACK_["c"][1], FLOOR_Z, PACK_["yaw"]), lean=PACK_["lean"])
        elif piece == "roll":
            _place(bm, lambda b: _roll(BA, b), _frame(ROLL_["c"][0], ROLL_["c"][1], FLOOR_Z, ROLL_["yaw"]))
        elif piece == "kitbag":
            _bag(BA, bm, KITBAG, _resting_base(KITBAG, built))
        else:
            raise RuntimeError("clutter: unknown piece %s" % piece)
    return _obj(TIERS[k], bm)


def _check_box(ob, report):
    """Every vertex inside the cargo bay's clear box (the module docstring's measurements)."""
    bad = []
    for v in ob.data.vertices:
        x, y, z = v.co
        top = 1.205 if y > -1.84 else 1.135
        side = 0.62 if (-1.53 <= y <= -1.17 and z >= 0.95) else 0.525
        if abs(x) > side or y > -1.155 or y < -1.905 or z > top or z < 0.52:
            bad.append((round(x, 3), round(y, 3), round(z, 3)))
    if bad:
        raise RuntimeError("clutter: %s has %d vertices outside the cargo bay's clear box, e.g. %s" % (ob.name, len(bad), bad[:4]))


def BUILD(report):
    import bmesh
    import build_accessories as BA
    made = []
    for k in range(len(TIERS)):
        made.append(_build_tier(BA, k, list(made)))
    bm = bmesh.new()
    _well(BA, bm)
    made.append(_obj(WELL, bm))
    total = 0
    for ob in made:
        _check_box(ob, report)
        names = [m.name for m in ob.data.materials]
        if names != MATS:
            raise RuntimeError("clutter: %s carries materials %s" % (ob.name, names))
        shade = BA._shade(ob, SHADE_K)
        area = BA._texel_weights(ob)
        n = BA.tris(ob)
        if ob.name in TIERS:
            total += n
        vs = ob.data.vertices
        report("FEATURE clutter: %-18s %4d tris  x %.2f..%.2f  y %.2f..%.2f  z %.3f..%.3f  shade %.2f  area m2 %s" % (
            ob.name, n, min(v.co.x for v in vs), max(v.co.x for v in vs), min(v.co.y for v in vs), max(v.co.y for v in vs),
            min(v.co.z for v in vs), max(v.co.z for v in vs), shade, " ".join("%.2f:%.2f" % (w, a) for w, a in sorted(area.items()))))
    report("FEATURE clutter: full load %d tris (budget %d), well blanket %d" % (total, TRI_BUDGET, BA.tris(made[-1])))
    if total > TRI_BUDGET:
        raise RuntimeError("clutter: the full load is %d tris, over the %d budget" % (total, TRI_BUDGET))


# ---------------------------------------------------------------------------------------------
# bake: the base colours under a broad worn mottle and a finer grain, the bags' zips and end panels as model-space
# tints (they lie along the car's axes), every piece's own occlusion (acc_shade: removables are invisible to the
# bake's rays) for the contact shadows

SHADE = ("attr", "acc_shade")


def _bag_layers(bag, base):
    """A bag's zip (dark, 1.6 cm wide along its top) and its end panels a shade darker."""
    dark = tuple(c * END_DARK for c in base)
    L = bag["length"] / 2.0
    if bag["along"] == "x":
        zip_gate = [("normal", "z", ">", 0.85), ("range", "y", bag["yc"] - 0.008, bag["yc"] + 0.008),
                    ("range", "x", bag["xc"] - L + 0.05, bag["xc"] + L - 0.05)]
        ends = [[("normal", "x", ">", 0.85), ("range", "x", bag["xc"] + L - 0.03, bag["xc"] + L + 0.01)],
                [("normal", "x", "<", -0.85), ("range", "x", bag["xc"] - L - 0.01, bag["xc"] - L + 0.03)]]
    else:
        zip_gate = [("normal", "z", ">", 0.85), ("range", "x", bag["xc"] - 0.008, bag["xc"] + 0.008),
                    ("range", "y", bag["yc"] - L + 0.05, bag["yc"] + L - 0.05)]
        ends = [[("normal", "y", ">", 0.85), ("range", "y", bag["yc"] + L - 0.03, bag["yc"] + L + 0.01)],
                [("normal", "y", "<", -0.85), ("range", "y", bag["yc"] - L - 0.01, bag["yc"] - L + 0.03)]]
    out = [("tint", dark, g) for g in ends]
    out.append(("tint", ZIP, zip_gate))
    return out


def _worn(fine, a_fine, a_broad=0.10):
    """A broad mottle (4-5 cm: handling, sun, dust) and a finer grain."""
    return [("noise", 6.0, a_broad), ("noise", fine, a_fine)]


def _bake_textured():
    fabric = "poly_wool_herringbone_diffuse_1k.jpg"
    return {
        "AccClutterCanvas": _worn(60.0, 0.05) + _bag_layers(DUFFEL, COLOURS["AccClutterCanvas"]) + [SHADE],
        "AccClutterCard": _worn(25.0, 0.05, 0.08) + [SHADE],
        "AccClutterFlap": _worn(25.0, 0.05, 0.12) + [SHADE],
        "AccClutterCardIn": _worn(25.0, 0.04) + [SHADE],
        "AccClutterTape": [("noise", 30.0, 0.04), SHADE],
        "AccClutterLabel": [("noise", 70.0, 0.03), SHADE],
        "AccClutterCooler": _worn(40.0, 0.03, 0.08) + [SHADE],
        "AccClutterLid": _worn(40.0, 0.02, 0.07) + [SHADE],
        "AccClutterCan": _worn(50.0, 0.04, 0.14) + [SHADE],
        "AccClutterTool": _worn(70.0, 0.04, 0.10) + [SHADE],
        "AccClutterSteel": [("noise", 60.0, 0.05), SHADE],
        "AccClutterBlack": [("noise", 90.0, 0.04), SHADE],
        "AccClutterPack": _worn(50.0, 0.05) + [SHADE],
        "AccClutterPackDk": _worn(50.0, 0.05) + [SHADE],
        "AccClutterNylon": _worn(50.0, 0.05) + _bag_layers(KITBAG, COLOURS["AccClutterNylon"]) + [SHADE],
        "AccClutterRoll": [("box", fabric, 0.20, tuple(c / 0.55 for c in COLOURS["AccClutterRoll"]), 0.45), ("noise", 6.0, 0.08), SHADE],
        "AccClutterBlanket": [("box", fabric, 0.25, (0.28, 0.23, 0.18), 0.45), ("noise", 8.0, 0.08), SHADE],
    }


BAKE_TEXTURED = _bake_textured
BAKE_MAT_WEIGHTS = {m: 1.0 for m in MATS}


# ---------------------------------------------------------------------------------------------
# scripts


def MODELS(gen):
    return [gen.model_block(gen.acc_model_name(geo), "crvgen1_" + geo, texture="%s_%s" % (gen.TEX, TEX_NAME), shader="vehiclewheel")
            for geo in TIERS + [WELL]]


def _part(gen):
    t = "\t\t\t"
    lines = ["\t\tpart %s" % PART, "\t\t{"]
    for mid, geo in list(zip(MODEL_IDS, TIERS)) + [(WELL_ID, WELL)]:
        lines += ["%smodel %s" % (t, mid), "%s{" % t, "%s\tfile = %s," % (t, gen.acc_model_name(geo)), "%s}" % t]
    lines += ["%scategory = nodisplay," % t,
              "%ssetAllModelsVisible = false," % t,          # no item: the Lua alone shows the load
              "%slua" % t, "%s{" % t, "%s\tinit = %s.Init," % (t, LUA_NS), "%s}" % t, "\t\t}"]
    return "\n".join(lines)


def VEHICLE_PARTS(gen, vehicle):
    return [_part(gen)]


TRANSLATIONS = {"IG_UI": {"IGUI_VehiclePart" + PART: "Cargo Load"}}

LUA = ["shared/HondaCRVGen1_Clutter.lua"]
