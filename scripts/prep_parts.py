r"""
Prepare the split kotris parts for the game (v5, 2026-10).

Runs inside Blender after split_base.py, build_engine.py, build_liners.py and build_cabin.py (run_rebuild).

What changed from v4 and why (each v4 step produced the artefacts seen in game):
  * NO decimation of the kotris parts. The collapse pass folded sliver triangles over their
    neighbours; their UVs overlapped the visible paint and the bake wrote black streaks into the
    doors, and the collapsed panels shaded lumpy. kotris's own triangles and custom normals are kept.
    (Only the generated engine bay is budgeted.)
  * NO generated door/tailgate cards and no offset "inner skins": they poked out of the paint
    (black strokes, a box through the B-pillar) and baked black blotches. Instead:
      - kotris's own door trim (the interior side wall behind each door, below its window sill,
        with the armrest) and the tailgate trim panel are cut out of the interior along each panel's
        outline (3 cm inside it) and MOVED onto the door / tailgate, so they swing with it;
      - the panels get a real inner side with Blender's Solidify (1 cm, rims), painted, so an open
        door, hood or gate is never see-through and its edges are closed;
      - every generated face (solidify shells and rims, interior closure boxes) is then tested
        against the shut car from the game's camera (30 +-10 degrees, every 15 degrees of azimuth)
        and DELETED if it can be seen from outside. Nothing generated can show on the closed car.
  * The tailgate no longer carries the tail-lamp bottoms and bumper slivers (split_base fix).

Face attribute "gen" marks generated geometry: 1 solidify shell, 2 solidify rim, 3 interior
closure, 4 wheel rotor, 5 rocker/sill meant to be seen, 6 hub cap disc, 7 exterior detail
(build_details: handles, mirrors, fuel flap, wipers, rails; baked flat, never pruned), 8 the
alloy's spoke face, window walls and the disc behind them (_rim_face; baked flat). Pruning
applies to 1-3; geocheck paints 1-3 red. Generated faces have no high twin: the bake paints them
directly.

v6 (2026-10-10): KI5 polygon parity. Every part is decimated to a budget (BUDGET) AFTER the trim
is moved and the hubs cleared, and BEFORE anything is generated, so the shells, closures and cap
are built on the low mesh. The full-detail part is kept as '<name>_hi' (hidden, not exported):
bake_atlas projects its colour, AO, cavity, lamps and masks onto the low mesh. v4's decimation
artefacts came from baking the folded low mesh itself; folds are now collapsed against the high
surface and the low mesh only receives what the high one looks like.

v7 cabin (2026-10-12): kotris's cabin furniture is stripped from the interior (_strip_furniture) and
replaced by build_cabin.py's generated `cabin` (prebuilt full + coarse, like the engine); the interior
shell keeps a FREE_DEV shape guard instead of none. Footwells (2026-10-12): the floor slab under the
carpet leaves build_cabin.footwell_holes() open and build_cabin.carve_footwells() cuts the low carpet
and builds a well where each seated passenger's soles land.

Windscreen corners (2026-10-13, feedback: "improve the connection between the A pillar and the
windshield"): the decimator's outline guard cut the frit band's 2-3 cm inner corner radius to one chord,
so each lower corner shipped chamfered, a wide dark wedge against the pillar base, with the moulding
notched beside it. Everything within WS_HOLD_R of those corners except the clear glass now keeps kotris's
own triangles (_held_verts, lowpoly.decimate(hold=)), paid on top of the body's budget.
"""
import math
import os

import bmesh
import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

import build_cabin
import build_details
import door_cards
import lowpoly

PARTS = ["body", "hood", "door_fl", "door_fr", "door_rl", "door_rr",
         "window_fl", "window_fr", "window_rl", "window_rr", "trunk", "trunk_top", "interior",
         "wheel_FR", "wheel_FL", "wheel_RR", "wheel_RL"]
ENGINE_BUDGET = 16000         # (v5; superseded by BUDGET in v6)
# v6 low-poly budgets (triangles), for parity with KI5 (their '89 Bronco: 5.6k body FBX, 356-tri
# wheel). Each part keeps a full-detail twin '<name>_hi' that the bake projects onto the low mesh:
# colour, AO, cavity, lamp light, lettering and lamp internals become texture.
# v7 cabin (2026-10-12): the interior keeps only kotris's shell, floor and firewall (520); the seats,
# wheel, dash and the rest are build_cabin's `cabin` (1,292 coarse since the v8 seats, prebuilt like
# the engine: it is decimated only if the coarse build comes out above its budget)
# The engine bay is not budgeted here since v2 (2026-10-17, spec/engine-bay-v2.md): build_bay.py builds it at
# its final triangle count with no twin, so it is neither decimated nor projected (the bake self-bakes it)
BUDGET = {"body": 3000, "hood": 380, "door_fl": 400, "door_fr": 400, "door_rl": 340, "door_rr": 340,
          "trunk": 720, "trunk_top": 330, "interior": 520, "cabin": 1300,
          "wheel_FR": 450, "wheel_FL": 450, "wheel_RR": 450, "wheel_RL": 450}
SMALL_PIECES = {}                       # part -> closed pieces under this size are dropped before decimating
# islands decimated on their own budget inside a part's: one budget for the gate and the spare let
# the decimator spend it on the flat gate and crush the spare tyre (holecheck: 3,000 px per rear view)
# (majority materials, budget, closed pieces under this size dropped first): the spare carries 166
# lug nuts, bolts and cap pieces under 6 cm; at four faces minimum each they ate the spare's budget
SUB_BUDGET = {"trunk": [({"Jante", "Pneu", "Chrome"}, 420, 0.06)],
              # the mirror housing and window rubber took 240 of the front door's 400 triangles and
              # left the paint skin 45 (feedback: "door panel looks weird"). Since 2026-10-12 the housing
              # is deleted before decimation and rebuilt by build_details: this is the window rubber alone
              "door_fl": [({"Plastique_noir"}, 70, 0.0)], "door_fr": [({"Plastique_noir"}, 70, 0.0)],
              "door_rl": [({"Plastique_noir", "Miroir"}, 60, 0.0)], "door_rr": [({"Plastique_noir", "Miroir"}, 60, 0.0)]}
# Wheels are rebuilt as a lathe of the original's profile (KI5's construction): a round 24-segment
# tyre and the rim lip. Decimated wheels came out polygonal with a see-through ring between tyre and
# rim. LATHE_SUB: the spare on the tailgate likewise.
LATHE_SEG = 24                # 18 sides showed as corners on the tyre in close-ups
SHOULDER_K = 0.89             # the shoulder ring's height in the tyre section (see _lathe_profile)
# The alloy's face (_rim_face, 2026-10-12, feedback: "add holes to the crv wheel rim, it looks like an
# image"). It was a closed dish with the spokes painted on by projection from kotris's twin (its
# dark inserts between the spokes); now the RD1's five split spokes are geometry: a spoke face with
# real windows, each a pocket whose walls run straight back onto a dark disc (brake rotor / hub
# face), so the camera sees depth and never the ground (every surface in a pocket faces out of it).
# Outlines are kotris's inserts, ray-cast along the axle on wheel_FR_hi (scratch rim/probe.py): big
# windows 0.0985-0.1665 m from the axle, 41 degrees wide at the rim; slots between each pair's two
# arms 0.1005-0.1658 m, ~2 cm wide; 36 degrees apart, the phase read off each twin (_window_phase).
RIM_GEN = 8
# 2026-10-17 review (WHL-2: "the EX alloy reads as a solid disc with slots"; S\review_wheels\
# cmp_alloy_real_vs_mod.png): the hub was ~45 % too big and the windows started 3 cm too far out.
# Measured on review_wheels\ref\ex_fr_wheel.jpg along the vertical (unforeshortened) axis, the lip's outer
# edge at r 0.195 m: the H cap r ~0.032, the five nuts on the 5 x 114.3 circle (r 0.057), each window's
# inner tip ~0.080 out, on the line of a nut (the spokes leave the hub between the nuts). The hub cone
# now just carries the cap and the nuts (the decal, paint_engine_decals.hubcap: RIM_LUG_R, RIM_CAP_R)
# and the windows reach in to RIM_WINDOW[0]; on the road wheels the windows are turned onto the decal's
# nuts (RIM_ROAD_PHASE), the spare keeps its twin's phase (its nuts are kotris's, projected).
RIM_HUB_R = 0.070             # the hub inside this (the decal's cap and nuts)
RIM_LUG_R, RIM_CAP_R = 0.057, 0.032   # the decal's lug circle (5 x 114.3 mm) and centre cap
RIM_FACE_R = 0.174            # the spoke face meets the lip's last lathe ring here
RIM_DEPTH = 0.050             # the disc behind the windows lies this far behind the face's rim edge
RIM_DISC_R = 0.180            # its 16-gon reaches past every window (inscribed radius 0.1765)
RIM_HUB_SEG = 16
RIM_SPOKES = 5
RIM_SHADE_DEEP = 0.22         # corner attribute rim_shade on the walls: 1 at the face, this at the disc
RIM_ROAD_PHASE = 90.0         # road wheels: a window centred straight up (object +z), 72 degrees apart, as the
                              # decal's nuts (paint_engine_decals.hubcap draws them at 90 + 72 k)
# (r, degrees off the window's centre line), counter-clockwise seen from outside: a rounded triangle from
# its tip just past the nut out to the lip (the old outline started at 0.0985), a little wider at the lip so
# each arm of a spoke pair is ~2.8 cm across (the photo's arms are slim)
# 2026-10-17 round 2 (R2-WA-5, S\review2_wheelsacc\EVID_alloy_vs_real.png: "the hub reads ~0.45 of the rim, the
# slots only the outer ~35 % of each spoke, real ~80 %: 10 slim arms"). Re-measured on review_wheels\ref\
# ex_fr_wheel.jpg (lip r 0.195 = 420 px vertically, 290 px across): each pair's slot runs from r ~0.080 (just past
# the nut ring) to ~0.16, ~1.2-1.5 cm wide; the arms ~2-2.5 cm at the lip, a pair ~5.5 cm (~20 deg) where it meets
# the lip; window tips ~0.075-0.085. So: the windows a little fuller (25 deg half width at the lip, tip at 0.076,
# 6 mm past the hub cone), the slot from 0.083 to the lip (85 % of the spoke), 1.0-1.4 cm wide: arms 2.5-3 cm.
# Same point counts (the wheel's triangle count is unchanged)
RIM_WINDOW = ((0.076, 0.0), (0.085, -9.0), (0.100, -15.5), (0.121, -20.5), (0.144, -23.5), (0.1655, -25.0),
              (0.1665, 0.0), (0.1655, 25.0), (0.144, 23.5), (0.121, 20.5), (0.100, 15.5), (0.085, 9.0))
RIM_SLOT = ((0.083, 0.0), (0.092, -3.0), (0.155, -2.7), (0.1650, 0.0), (0.155, 2.7), (0.092, 3.0))
MAT_DEV = {"Body": 0.005, "Body_plastique": 0.006}   # shape guard per material (default lowpoly.MAX_DEV,
                                                     # 12 mm): paint and cladding hold their roof ribs,
                                                     # arch flares and creases
WS_HOLD_R = 0.08              # metres round each lower windscreen corner (_windscreen_corners) left undecimated
# Other details held at full detail the same way, {part: (centres, radius)} (2026-10-14 review, "slit at the
# gate handle; dark shard crosses the V of the CR-V badge"): the gate's lock cylinder and the pull-handle
# slot beside it, in the top lip of the plate recess. kotris models the lock as a ~1.5 cm hole with the
# cylinder sunk in it (95 vertices within 3 cm); the decimator cut the hole's outline to a jagged notch
# that opened a slit into the gate (pzview probe: a gate face 15 cm inside the skin) and a dark shard over
# the painted CR-V, and the slot to a pale wedge. Centres measured on trunk_hi (the lock's densest point,
# and the slot 5.5 cm inboard of it); ~150 tris on top of the gate's budget
DETAIL_HOLD = {"trunk": (((-0.256, -2.130, 1.040), (-0.311, -2.130, 1.045)), 0.05),
               # body (2026-10-17 review): the rear bumper's step where its top meets the gate at each corner (EXT-16,
               # crumpled facets: body faces at (0.611, -2.075, 0.682), (0.645, -2.053, 0.728); ~90 tris both sides)
               # and the grille frame's ends round the rebuilt opening (EXT-3: an L bracket and shreds after decimation)
               # Round 2 (R2-EXT-8): the rear bumper's top where it meets each quarter beside the gate's corner (crumpled
               # facets: gview probes body faces 1237 / 499 / 875 at (0.73, -2.087, 0.756), (0.715, -2.026, 0.766),
               # (0.716, -2.129, 0.749), past the step's hold above; ~85 tris a side) and the rear arch's flare
               # where it leaves the quarter above each rear wheel (the decimator spanned it with one 40-degree facet,
               # body face 2300 at (0.849, -1.562, 0.810), a diagonal crease over the arch; ~45 tris a side)
               "body": (((0.63, -2.065, 0.71), (-0.63, -2.065, 0.71), (0.30, 2.0, 0.80), (-0.30, 2.0, 0.80),
                         (0.73, -2.07, 0.755), (-0.73, -2.07, 0.755),
                         (0.85, -1.56, 0.81), (-0.85, -1.56, 0.81), (0.85, -1.44, 0.835), (-0.85, -1.44, 0.835)), 0.065)}
# A band along one edge held the same way, {part: (axis, value)}: vertices beyond value on that axis. The hood's
# leading edge over the grille (EXT-15: it dipped and waved at (0.03, 1.97, 0.90) at the hood's 380-tri budget;
# kotris's edge roll is y 1.93-1.99, ~105 tris). Off since build 2 (2026-10-17): held, the raised hood's leading edge
# drew 1-px ground specks in every open-hood view (bay_open 8 -> 17-20, open_135 / open_180 +2..+4) with the top side
# alone held as well, and the low edge looked the same at the game's zoom. Kept for a later pass: {"hood": (1, 1.93)}
EDGE_HOLD = {}
EDGE_HOLD_UP = 0.2            # ... vertices whose every face looks up at least this much (normal z): the top side
# The hood's leading edge rebuilt instead (round 3, EXT-15, _hood_edge after the hood's decimation). The wave was the
# decimated skin's shading: a fan of long triangles from one vertex at (-0.03, 1.83, 0.98) across the roll to the nose
# (pzview with one flat colour showed the dip; the baked texture alone was straight). Every decimated Body face with a
# corner within HOOD_EDGE_CUT of arc (up the roll) from the nose crease and |x| <= HOOD_EDGE_X goes; the hole is
# refilled with a grid snapped onto kotris's full-detail skin: columns every ~HOOD_EDGE_COL, rows HOOD_EDGE_ROWS of arc
# from the crease (row 0 is the crease itself), each point cast onto hood_hi's Body faces in the plane x = const from a
# pivot under the roll. The hole's own boundary vertices (the low skin round it and the hood's outline, the under-lip
# edge against the black hem strip) stay where they were, so the seams to the hem, the body and the headlamps do not
# move; points are only added along the open outline. Faces >= ~1 cm (the 2-5 mm faces of the held edge were missed by
# backfill's 9 mm scan). ~+100 tris on the hood.
HOOD_EDGE_X = 0.60            # half width of the grid (the corners beyond keep the decimated skin)
HOOD_EDGE_CUT = 0.12          # metres of arc from the crease: faces touching this band are rebuilt
HOOD_EDGE_ROWS = (0.0, 0.015, 0.035, 0.065, 0.10)
HOOD_EDGE_COL = 0.075
HOOD_EDGE_MARGIN = 0.008      # grid points this close (in the unrolled plane) to the hole's boundary are left out
HOOD_EDGE_MAT = "Body"
HOOD_EDGE_TAG = "_hood_edge"  # temporary face attribute: the rebuilt faces (their normals come from the grid itself)
# Loose faces dropped outright, {part: ((x0,x1),(y0,y1),(z0,z1)) in metres}. The bar hanging from the raised
# tailgate glass down to the load floor (2026-10-15, "the molding is still there") is a thin piece of the
# interior mesh along the glass's lower edge, x -0.6..0.6 m (game probes at (-0.24, -1.99, 1.17) and (-0.54, -1.97, 1.18) m). Its faces go, with
# any face that touches them. Kept clear of the lock detail itself (DETAIL_HOLD, x -0.26..-0.31 at y -2.13).
DROP_BOX = {"interior": ((-0.65, 0.65), (-2.04, -1.91), (1.08, 1.30)),
            # the thin strip at the glass opening's lower edge (x -0.62..0.63, y -2.05..-1.98, z 1.16..1.18 m): with the
            # glass raised it draws as a dark outline across the load floor (probe: body faces at (-0.57, -2.0, 1.17))
            "body": ((-0.70, 0.70), (-2.08, -1.98), (1.15, 1.20))}
DROP_MAX = 200                    # verts: a loose group this small inside DROP_BOX is the piece to drop
FREE_OUTLINES = ("interior", "engine_block")   # seen through glass / under the hood: no outline guard
# ... but a shape guard all the same: with none (hi_tree None) the decimated kotris seats strayed up to
# 44 mm from their originals (p95 20.6 mm) and read as "something weird sitting in the passenger seat".
# Budgets yield to shape (playbook): the interior may stop above its budget rather than sink.
FREE_DEV = 0.015
# kotris's cabin furniture, deleted from `interior` before decimation (build_cabin.py makes the cabin):
# every island whose majority material is seat cloth, and every Interieur island whose bounding-box
# centre lies in one of these boxes (x0, x1, y0, y1, z0, z1), measured on interior_hi
# (2026-10-12 survey: island centres in the comments). First matching box names the island (the
# binnacle's centre sits 5 cm under the wheel's, inside the wheel's box: its box is tried first).
STRIP_SEATS = ("Siege", "Siege_2")
STRIP_BOXES = {
    "binnacle": (-0.65, -0.30, 0.35, 0.52, 0.85, 1.015),  # 227-tri hood c(-0.41, 0.43, 0.99)
    "wheel":    (-0.65, -0.18, 0.33, 0.52, 0.82, 1.26),   # 600-tri wheel c(-0.41, 0.43, 1.04), 38-tri stalks c(-0.27, 0.49, 1.00)
    # 210-tri dash c(0.00, 0.77, 0.81) and the 10-tri column c(-0.42, 0.71, 0.95). The firewall island
    # c(0.00, 0.89, 0.80) stays (it closes the footwells to the bay), and so do the small A-pillar and
    # window-corner trims at |x| 0.65-0.72 (the cabin's dash ends at |x| 0.725 under them)
    "dash":     (-0.60, 0.60, 0.46, 0.85, 0.40, 1.22),
    "console":  (-0.15, 0.15, -0.45, 0.70, 0.43, 0.68),   # 28-tri c(0.00, 0.09, 0.55)
    "mirror":   (-0.14, 0.14, 0.37, 0.45, 1.43, 1.53),    # 62-tri housing c(0.00, 0.41, 1.48), 18-tri stem c(0.00, 0.44, 1.50)
}
LATHE_PARTS = ("wheel_FR", "wheel_FL", "wheel_RR", "wheel_RL")
LATHE_SUB = {"trunk": {"Jante", "Pneu", "Chrome"}}
BADGE_MAT = "Chrome"
BADGE_MAX_SIZE = 0.10         # bbox diagonal, metres
CLUSTER_MIN = 100             # faces: a badge cluster smaller than this is lettering debris
LUG_Z = 0.50                  # metres: chrome this low is a wheel lug nut
GEN = "gen"
SKIN_MATS = ("Body", "Body_plastique", "Plastique_noir", "Partie_noir", "Dessous")
INNER_MAT = "BodyInner"       # painted inner side of the opening panels (bake: Body's colour)
SHELL_THICKNESS = 0.010       # metres
CARD_MARGIN = 0.03            # trim moved onto a panel stays this far inside its outline
CELL = 0.01                   # outline raster, metres
DOORS = {                     # door object -> (window object, side sign: -1 left, +1 right)
    "door_fl": ("window_fl", -1), "door_fr": ("window_fr", 1),
    "door_rl": ("window_rl", -1), "door_rr": ("window_rr", 1),
}


# ----------------------------------------------------------------------------------------------
# helpers


def tris(ob):
    return sum(len(p.vertices) - 2 for p in ob.data.polygons)


def _mat_index(me, name, factory=None):
    names = [m.name if m else "?" for m in me.materials]
    if name not in names:
        mat = bpy.data.materials.get(name) or (factory() if factory else bpy.data.materials.new(name))
        me.materials.append(mat)
        names.append(name)
    return names.index(name)


def _gen_layer(bm):
    return bm.faces.layers.int.get(GEN) or bm.faces.layers.int.new(GEN)


def _inner_material():
    mat = bpy.data.materials.get(INNER_MAT)
    if mat is None:
        mat = bpy.data.materials.new(INNER_MAT)
        mat.use_nodes = True
        b = next((n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
        src = bpy.data.materials.get("Body")
        sb = next((n for n in src.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None) if src and src.use_nodes else None
        if b is not None:
            b.inputs['Base Color'].default_value = tuple(sb.inputs['Base Color'].default_value) if sb else (0.573, 0.545, 0.486, 1.0)
            b.inputs['Roughness'].default_value = 0.6
    return mat


def _join(dst, tmp):
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    dst.select_set(True)
    tmp.select_set(True)
    bpy.context.view_layer.objects.active = dst
    with bpy.context.temp_override(active_object=dst, selected_editable_objects=[dst, tmp], selected_objects=[dst, tmp]):
        bpy.ops.object.join()


def _split_off(ob, face_ids, name):
    """Move the given faces of ob into a new object (same materials); return it."""
    keep = set(face_ids)
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bm.faces.ensure_lookup_table()
    cp = bm.copy()
    cp.faces.ensure_lookup_table()
    cp.faces.index_update()
    bmesh.ops.delete(cp, geom=[f for f in cp.faces if f.index not in keep], context='FACES')
    me = bpy.data.meshes.new(name)
    for m in ob.data.materials:
        me.materials.append(m)
    cp.to_mesh(me)
    cp.free()
    bmesh.ops.delete(bm, geom=[bm.faces[i] for i in sorted(keep)], context='FACES')
    bm.to_mesh(ob.data)
    bm.free()
    tmp = bpy.data.objects.new(name, me)
    ob.users_collection[0].objects.link(tmp)
    tmp.matrix_world = ob.matrix_world
    return tmp


def _bm_box(bm, mi, x0, x1, y0, y1, z0, z1, gen=3):
    gl = _gen_layer(bm)
    v = [bm.verts.new(p) for p in ((x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
                                   (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1))]
    for idx in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
        f = bm.faces.new([v[i] for i in idx])
        f.material_index = mi
        f.smooth = False
        f[gl] = gen


def _bm_loft(bm, mi, sx, x_in, stations, z0, z1, gen=3):
    """A closed prism on one side of the car (sx -1 / +1): inner wall at |x| = x_in, outer wall through
    stations [(y, |x| outer)] (any order along y), flat bottom z0 and top z1, both ends capped. Faces outward."""
    gl = _gen_layer(bm)
    st = sorted(stations)
    rings = []
    for y, xo in st:
        rings.append([bm.verts.new(p) for p in ((sx * x_in, y, z0), (sx * xo, y, z0), (sx * xo, y, z1), (sx * x_in, y, z1))])
    made = []
    for (ya, ra), (yb, rb) in zip(zip([s[0] for s in st], rings), zip([s[0] for s in st[1:]], rings[1:])):
        for i in range(4):
            j = (i + 1) % 4
            made.append(bm.faces.new((ra[i], ra[j], rb[j], rb[i])))
    made.append(bm.faces.new(rings[0]))
    made.append(bm.faces.new(rings[-1][::-1]))
    cy = sum(s[0] for s in st) / len(st)
    cx = sx * (x_in + sum(s[1] for s in st) / len(st)) / 2
    centre = Vector((cx, cy, (z0 + z1) / 2))
    bm.normal_update()
    for k, f in enumerate(made):
        f.material_index = mi
        f.smooth = False
        f[gl] = gen
        c = f.calc_center_median()
        if k >= len(made) - 2:
            out = Vector((0.0, -1.0 if k == len(made) - 2 else 1.0, 0.0))     # the end caps: along y
        else:
            out = c - Vector((cx if abs(f.normal.x) > 0.5 else c.x, c.y, centre.z if abs(f.normal.z) > 0.5 else c.z))
            if out.length < 1e-9:
                out = c - centre
        if f.normal.dot(out) < 0:
            f.normal_flip()
    return len(made)


RISER_X = 0.57                # the cargo riser's half width (_interior_closures)
HOUSE_X = 0.565               # the rear wheel housing's inner wall: 5 mm over the riser
SHELF_X = 0.552               # the shelf over the rear arch: just inboard of the arch liner's inner wall (build_liners.X_IN 0.56)


def _bm_slab(bm, mi, x0, x1, y0, y1, z0, z1, holes, gen=3):
    """_bm_box with rectangular holes (x0, x1, y0, y1) through it: one closed box per run of each
    y band between the hole edges (bands with the same runs merged). Boxes meet face to face inside
    the slab; nothing outside sees those faces."""
    ys = sorted({y0, y1} | {min(max(v, y0), y1) for h in holes for v in h[2:]})
    rows = []
    for ya, yb in zip(ys, ys[1:]):
        if yb - ya < 1e-6:
            continue
        cut = sorted((max(h[0], x0), min(h[1], x1)) for h in holes if h[2] < yb - 1e-6 and h[3] > ya + 1e-6)
        runs, x = [], x0
        for a, b in cut:
            if a > x + 1e-6:
                runs.append((x, a))
            x = max(x, b)
        if x < x1 - 1e-6:
            runs.append((x, x1))
        if rows and rows[-1][2] == runs and abs(rows[-1][1] - ya) < 1e-9:
            rows[-1][1] = yb
        else:
            rows.append([ya, yb, runs])
    n = 0
    for ya, yb, runs in rows:
        for a, b in runs:
            _bm_box(bm, mi, a, b, ya, yb, z0, z1, gen)
            n += 1
    return n


# ----------------------------------------------------------------------------------------------
# badges (unchanged from v4)


def _drop_badges(ob):
    me = ob.data
    names = [m.name if m else "?" for m in me.materials]
    badge_mats = {BADGE_MAT}
    wheel = ob.name.startswith("wheel")
    if wheel:
        badge_mats.add("Jante")
    if not badge_mats & set(names):
        return 0
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.faces.ensure_lookup_table()
    seen = [False] * len(bm.faces)
    kill = []
    small = []
    hub = None
    if wheel:
        ys = [v.co.y for v in me.vertices]; zs = [v.co.z for v in me.vertices]
        hub = ((min(ys) + max(ys)) / 2, (min(zs) + max(zs)) / 2)
    for f in bm.faces:
        if seen[f.index] or names[f.material_index] not in badge_mats:
            continue
        stack, grp = [f], []
        seen[f.index] = True
        while stack:
            g = stack.pop()
            grp.append(g)
            for e in g.edges:
                for h in e.link_faces:
                    if not seen[h.index]:
                        seen[h.index] = True
                        stack.append(h)
        cs = [g.calc_center_median() for g in grp]
        dx = max(c.x for c in cs) - min(c.x for c in cs)
        dy = max(c.y for c in cs) - min(c.y for c in cs)
        dz = max(c.z for c in cs) - min(c.z for c in cs)
        if wheel:
            diag = (dx * dx + dy * dy + dz * dz) ** 0.5
            c = sum(cs, Vector()) / len(cs)
            near_hub = ((c.y - hub[0]) ** 2 + (c.z - hub[1]) ** 2) ** 0.5 < 0.06
            if diag < BADGE_MAX_SIZE or (near_hub and diag < 0.20):
                kill.extend(grp)              # lettering, lug nuts, and the original centre cap
            continue
        if (dx * dx + dy * dy + dz * dz) ** 0.5 < BADGE_MAX_SIZE:
            small.append((grp, (dx * dx + dy * dy + dz * dz) ** 0.5, sum(cs, Vector()) / len(cs)))
    cells = {}
    for grp, diag, c in small:
        key = (round(c.x / 0.12), round(c.y / 0.12), round(c.z / 0.12))
        cells[key] = cells.get(key, 0) + len(grp)
    for grp, diag, c in small:
        key = (round(c.x / 0.12), round(c.y / 0.12), round(c.z / 0.12))
        lug = len(grp) >= 60 and diag < 0.02
        if lug or c.z < LUG_Z or cells[key] < CLUSTER_MIN:
            kill.extend(grp)
    n = len(kill)
    if kill:
        bmesh.ops.delete(bm, geom=kill, context='FACES')
        bm.to_mesh(me)
    bm.free()
    return n


# ----------------------------------------------------------------------------------------------
# kotris trim onto the panels


def _outline(ob, axes, mats=None):
    """Binary raster (CELL) of the object's faces projected on two world axes, and its origin.
    mats: only faces of these materials (the gate's skin, not the spare that sticks out of it)."""
    M = ob.matrix_world
    names = [m.name if m else "?" for m in ob.data.materials]
    polys = [p for p in ob.data.polygons if mats is None or names[p.material_index] in mats]
    used = {i for p in polys for i in p.vertices}
    pts = {i: M @ ob.data.vertices[i].co for i in used}
    lo = (min(p[axes[0]] for p in pts.values()) - 0.05, min(p[axes[1]] for p in pts.values()) - 0.05)
    hi = (max(p[axes[0]] for p in pts.values()) + 0.05, max(p[axes[1]] for p in pts.values()) + 0.05)
    shape = (int((hi[0] - lo[0]) / CELL) + 1, int((hi[1] - lo[1]) / CELL) + 1)
    mask = np.zeros(shape, dtype=bool)
    for p in polys:
        vs = [pts[i] for i in p.vertices]
        for k in range(1, len(vs) - 1):
            a, b, c = ((v[axes[0]], v[axes[1]]) for v in (vs[0], vs[k], vs[k + 1]))
            i0 = max(0, int((min(a[0], b[0], c[0]) - lo[0]) / CELL)); i1 = min(shape[0], int((max(a[0], b[0], c[0]) - lo[0]) / CELL) + 2)
            j0 = max(0, int((min(a[1], b[1], c[1]) - lo[1]) / CELL)); j1 = min(shape[1], int((max(a[1], b[1], c[1]) - lo[1]) / CELL) + 2)
            if i1 <= i0 or j1 <= j0:
                continue
            X, Y = np.meshgrid(lo[0] + (np.arange(i0, i1) + 0.5) * CELL, lo[1] + (np.arange(j0, j1) + 0.5) * CELL, indexing='ij')
            d = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
            if abs(d) < 1e-12:
                continue
            l1 = ((b[1] - c[1]) * (X - c[0]) + (c[0] - b[0]) * (Y - c[1])) / d
            l2 = ((c[1] - a[1]) * (X - c[0]) + (a[0] - c[0]) * (Y - c[1])) / d
            inside = (l1 >= -0.02) & (l2 >= -0.02) & (l1 + l2 <= 1.02)
            mask[i0:i1, j0:j1] |= inside
    return mask, lo


def _erode(mask, cells):
    m = mask.copy()
    for _ in range(cells):
        e = m.copy()
        e[1:, :] &= m[:-1, :]; e[:-1, :] &= m[1:, :]; e[:, 1:] &= m[:, :-1]; e[:, :-1] &= m[:, 1:]
        m = e
    return m


def _inside(mask, lo, u, v):
    i, j = int((u - lo[0]) / CELL), int((v - lo[1]) / CELL)
    return 0 <= i < mask.shape[0] and 0 <= j < mask.shape[1] and bool(mask[i, j])


def _bisect_grid(bm, pick, planes):
    """Cut the faces chosen by pick(face) on every plane (co, no); face set recomputed per plane."""
    for co, no in planes:
        faces = [f for f in bm.faces if pick(f)]
        if not faces:
            continue
        verts = list({v for f in faces for v in f.verts})
        edges = list({e for f in faces for e in f.edges})
        bmesh.ops.bisect_plane(bm, geom=verts + edges + faces, plane_co=co, plane_no=no, dist=1e-5)


def _move_trim(report):
    """kotris models the door trim and the tailgate trim as part of the interior shell; cut them out
    along each panel's outline and move them onto the panel."""
    it = bpy.data.objects.get("interior")
    if it is None:
        return
    names = [m.name if m else "?" for m in it.data.materials]
    if "Interieur" not in names:
        return
    ii = names.index("Interieur")
    bm = bmesh.new()
    bm.from_mesh(it.data)

    def side_wall(f):
        c = f.calc_center_median()
        return f.material_index == ii and abs(c.x) > 0.45 and abs(f.normal.x) > 0.3 and -1.40 < c.y < 0.95 and 0.30 < c.z < 1.35

    def rear_wall(f):
        c = f.calc_center_median()
        return f.material_index == ii and c.y < -1.80 and f.normal.y > 0.3 and 0.55 < c.z < 1.35

    cut = bm.faces.layers.int.get("cut") or bm.faces.layers.int.new("cut")
    for f in bm.faces:
        if side_wall(f) or rear_wall(f):
            f[cut] = 1                                       # split faces inherit it: merged back below
    planes = [((0.0, y, 0.0), (0.0, 1.0, 0.0)) for y in np.arange(-1.40, 0.95, 0.04)]
    planes += [((0.0, 0.0, z), (0.0, 0.0, 1.0)) for z in np.arange(0.40, 1.34, 0.04)]
    _bisect_grid(bm, side_wall, planes)
    planes = [((x, 0.0, 0.0), (1.0, 0.0, 0.0)) for x in np.arange(-0.76, 0.77, 0.04)]
    planes += [((0.0, 0.0, z), (0.0, 0.0, 1.0)) for z in np.arange(0.60, 1.34, 0.04)]
    _bisect_grid(bm, rear_wall, planes)
    bm.to_mesh(it.data)
    bm.free()

    me = it.data
    # islands (for the armrests and other loose trim: they move whole)
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.faces.ensure_lookup_table()
    island = [-1] * len(bm.faces)
    isl_faces = []
    for f in bm.faces:
        if island[f.index] >= 0:
            continue
        k = len(isl_faces)
        grp = [f.index]
        island[f.index] = k
        st = [f]
        while st:
            g = st.pop()
            for e in g.edges:
                for h in e.link_faces:
                    if island[h.index] < 0:
                        island[h.index] = k
                        grp.append(h.index)
                        st.append(h)
        isl_faces.append(grp)
    centres = [f.calc_center_median().copy() for f in bm.faces]
    normals = [f.normal.copy() for f in bm.faces]
    mats = [f.material_index for f in bm.faces]
    bm.free()

    per_target = {}
    for target, ids in _assignments(centres, normals, mats, ii, isl_faces).items():
        if ids:
            per_target[target] = ids
            report("  %-8s %4d trim faces moved from the interior" % (target, len(ids)))
        else:
            report("  %-8s no trim found behind it" % target)
    # split off from highest target to keep things simple: build all temp objects from one bmesh
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.faces.ensure_lookup_table()
    temps = {}
    for target, ids in per_target.items():
        cp = bm.copy()
        cp.faces.ensure_lookup_table()
        cp.faces.index_update()
        keep = set(ids)
        bmesh.ops.delete(cp, geom=[f for f in cp.faces if f.index not in keep], context='FACES')
        tme = bpy.data.meshes.new("trim_" + target)
        for m in me.materials:
            tme.materials.append(m)
        cp.to_mesh(tme)
        cp.free()
        tmp = bpy.data.objects.new("trim_" + target, tme)
        it.users_collection[0].objects.link(tmp)
        temps[target] = tmp
    allids = sorted({i for ids in per_target.values() for i in ids})
    bmesh.ops.delete(bm, geom=[bm.faces[i] for i in allids], context='FACES')
    bm.to_mesh(me)
    bm.free()
    for target, tmp in temps.items():
        if target == "trunk":                                # the flat rear wall: drop it
            bpy.data.objects.remove(tmp, do_unlink=True)
            continue
        _join(bpy.data.objects[target], tmp)
    for o in [it] + [bpy.data.objects[t] for t in temps if t != "trunk"]:
        n = _merge_cut(o)
        report("  %-8s grid cells merged back: %d faces" % (o.name, n))


def _merge_cut(ob):
    """Undo the 4 cm cutting grid where it is not needed: dissolve the edges between coplanar cells
    (faces still flagged 'cut'), per material, keeping the trim's outline and creases."""
    me = ob.data
    if me.attributes.get("cut") is None:
        return len(me.polygons)
    bm = bmesh.new()
    bm.from_mesh(me)
    cut = bm.faces.layers.int.get("cut")
    faces = [f for f in bm.faces if f[cut] == 1]
    edges = list({e for f in faces for e in f.edges if all(g[cut] == 1 for g in e.link_faces) and len(e.link_faces) == 2})
    verts = list({v for e in edges for v in e.verts})
    bmesh.ops.dissolve_limit(bm, angle_limit=math.radians(1.0), use_dissolve_boundaries=False,
                             verts=verts, edges=edges, delimit={'MATERIAL', 'NORMAL'})
    for f in bm.faces:
        f[cut] = 0
    bm.to_mesh(me)
    bm.free()
    return len(me.polygons)


def _strip_furniture(report):
    """Delete kotris's seats, steering wheel, binnacle, dash, console and mirror from `interior`
    (STRIP_SEATS / STRIP_BOXES); build_cabin.py's `cabin` replaces them. Runs before _make_low, so
    the `_hi` twin it copies is stripped too and the bake never projects the old furniture."""
    it = bpy.data.objects.get("interior")
    if it is None:
        return 0
    me = it.data
    names = [m.name if m else "?" for m in me.materials]
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.faces.ensure_lookup_table()
    seen = [False] * len(bm.faces)
    removed = {k: [0, 0] for k in ("seats",) + tuple(STRIP_BOXES)}     # islands, tris
    kill = []
    for f in bm.faces:
        if seen[f.index]:
            continue
        grp, st = [f], [f]
        seen[f.index] = True
        while st:
            g = st.pop()
            for e in g.edges:
                for h in e.link_faces:
                    if not seen[h.index]:
                        seen[h.index] = True
                        grp.append(h)
                        st.append(h)
        tri = {}
        for g in grp:
            m = names[g.material_index] if names else "?"
            tri[m] = tri.get(m, 0) + len(g.verts) - 2
        major = max(tri.items(), key=lambda kv: kv[1])[0]
        key = None
        if major in STRIP_SEATS:
            key = "seats"
        elif major == "Interieur":
            vs = [v.co for g in grp for v in g.verts]
            c = Vector(((min(v.x for v in vs) + max(v.x for v in vs)) / 2, (min(v.y for v in vs) + max(v.y for v in vs)) / 2,
                        (min(v.z for v in vs) + max(v.z for v in vs)) / 2))
            key = next((k for k, (x0, x1, y0, y1, z0, z1) in STRIP_BOXES.items()
                        if x0 < c.x < x1 and y0 < c.y < y1 and z0 < c.z < z1), None)
        if key is not None:
            kill.extend(grp)
            removed[key][0] += 1
            removed[key][1] += sum(tri.values())
    if kill:
        bmesh.ops.delete(bm, geom=kill, context='FACES')
        bm.to_mesh(me)
    bm.free()
    total = sum(t for _n, t in removed.values())
    for key, (n, t) in removed.items():
        report("  _strip_furniture: %-8s %3d islands, %5d tris removed from the interior" % (key, n, t))
    report("  _strip_furniture: %d tris removed, %d left (shell, floor, firewall, pillar trims)" % (total, tris(it)))
    return total


# kotris's belt-height ledge along the cabin side (2026-10-17 review OPEN-1 / CAB-4): the top of its interior
# door trim, part of the one big Interieur shell island, so split_base can only give it to the interior and
# _move_trim leaves it (it lies above each window's sill). It stayed when the doors opened, a rod floating
# across all four openings, and shut it stood 1-2 cm proud of the door caps. door_cards supplies the cards, so
# its faces go: Interieur faces centred in this band (|x|, y, z of the centre) that are no taller than RAIL_SPAN
# (the B- and C-pillar trims and the A-pillar base stay: they are tall, or face along y like the pillar sides).
RAIL_BOX = ((0.70, 0.78), (-1.07, 0.745), (1.06, 1.175))
RAIL_SPAN = 0.06              # metres of height: the ledge's top and its inner lip; pillar trims are taller
RAIL_NY = 0.75                # |normal y| above this: a pillar's front / back face or an end cap, kept


def _drop_belt_rail(report):
    it = bpy.data.objects.get("interior")
    if it is None:
        return 0
    me = it.data
    names = [m.name if m else "?" for m in me.materials]
    (x0, x1), (y0, y1), (z0, z1) = RAIL_BOX
    kill = []
    for p in me.polygons:
        if names[p.material_index] != "Interieur":
            continue
        c = p.center
        if not (x0 <= abs(c.x) <= x1 and y0 <= c.y <= y1 and z0 <= c.z <= z1) or abs(p.normal.y) > RAIL_NY:
            continue
        zs = [me.vertices[i].co.z for i in p.vertices]
        if max(zs) - min(zs) <= RAIL_SPAN:
            kill.append(p.index)
    if kill:
        _delete_faces(it, kill)
    report("  interior   belt rail: %d faces of kotris's belt-height ledge removed (the door cards replace it)" % len(kill))
    return len(kill)


def _assignments(centres, normals, mats, ii, isl_faces):
    """Which interior faces go to which panel: door card faces (inward-facing side wall below the
    window sill and inside the door outline less CARD_MARGIN), loose trim islands wholly behind a
    door (armrests), and the tailgate trim panel (forward-facing rear wall inside the gate outline)."""
    out = {}
    taken = set()
    for door, (win, side) in DOORS.items():
        dob = bpy.data.objects.get(door)
        wob = bpy.data.objects.get(win)
        if dob is None:
            continue
        mask, lo = _outline(dob, (1, 2))
        mask = _erode(mask, int(round(CARD_MARGIN / CELL)))
        sill = min((wob.matrix_world @ v.co).z for v in wob.data.vertices) if wob else 1.10
        pick = set()
        for i, c in enumerate(centres):
            if i in taken or c.x * side < 0.45 or c.z > sill - 0.005 or not _inside(mask, lo, c.y, c.z):
                continue
            if mats[i] == ii and abs(normals[i].x) > 0.3 and normals[i].x * side < 0:
                pick.add(i)
        for grp in isl_faces:
            if len(grp) > 300 or any(g in taken for g in grp):
                continue
            if sum(1 for g in grp if mats[g] == ii) < 0.8 * len(grp):
                continue                              # trim only: seat pieces stay with the seat
            c = sum((centres[g] for g in grp), Vector()) / len(grp)
            if c.x * side > 0.55 and c.z < sill and _inside(mask, lo, c.y, c.z):
                pick.update(grp)
        taken |= pick
        out[door] = pick
    tob = bpy.data.objects.get("trunk")
    if tob is not None:
        mask, lo = _outline(tob, (0, 2), mats=SKIN_MATS)
        mask = _erode(mask, int(round(CARD_MARGIN / CELL)))
        pick = set()
        for i, c in enumerate(centres):
            if i in taken or c.y > -1.80:
                continue
            if mats[i] == ii and normals[i].y > 0.3 and _inside(mask, lo, c.x, c.z):
                pick.add(i)
        taken |= pick
        out["trunk"] = pick
    return out


# ----------------------------------------------------------------------------------------------
# solidified panels


def _solidify(ob, thickness=SHELL_THICKNESS, shell_mat=None, strips=False):
    """Give the panel's skin a real inner side: Solidify 1 cm inward with rims, painted (BodyInner)
    or, with shell_mat, lined with that trim; faces tagged gen 1 (shell) / 2 (rim)."""
    me = ob.data
    names = [m.name if m else "?" for m in me.materials]
    bm = bmesh.new()
    bm.from_mesh(me)
    gl = _gen_layer(bm)
    bm.faces.ensure_lookup_table()
    ok = [names[f.material_index] in SKIN_MATS and f[gl] == 0 for f in bm.faces]
    ids = []
    seen = [False] * len(bm.faces)
    for f in bm.faces:                      # islands of skin faces; keep the big ones only: the
        if seen[f.index] or not ok[f.index]:  # skin, the window sash, the black edge strips. Handles,
            continue                          # mirrors and mouldings sit on the skin, whose own inner
        grp, st = [f], [f]                    # side hides their backs; solidifying them only added rims
        seen[f.index] = True
        while st:
            g = st.pop()
            for e in g.edges:
                for h in e.link_faces:
                    if not seen[h.index] and ok[h.index]:
                        seen[h.index] = True
                        grp.append(h)
                        st.append(h)
        vs = [v.co for g in grp for v in g.verts]
        span = [max(v[i] for v in vs) - min(v[i] for v in vs) for i in range(3)]
        # strips=True (doors): the black cladding along a door's lower edge IS that door's skin there;
        # left without an inner side, an open door showed the ground through its bottom (v6 showcase)
        thin_strip = not strips and names[grp[0].material_index] == "Body_plastique" and min(span) < 0.06
        if max(span) > 0.30 and not thin_strip:
            ids.extend(g.index for g in grp)
    bm.to_mesh(me)
    bm.free()
    if not ids:
        return 0
    tmp = _split_off(ob, ids, ob.name + "_skin")
    n0 = len(tmp.data.polygons)
    centres0 = [p.center.copy() for p in tmp.data.polygons]
    nv0 = len(tmp.data.vertices)
    verts0 = [v.co.copy() for v in tmp.data.vertices]
    m = tmp.modifiers.new("solid", 'SOLIDIFY')
    m.thickness = thickness
    m.offset = -1.0
    m.use_even_offset = True
    m.use_quality_normals = True
    m.use_rim = True
    m.use_flip_normals = False
    m.thickness_clamp = 1.0                 # even thickness pushes vertices far out at very sharp
    m.use_thickness_angle_clamp = True      # corners: the clamp stops the spikes
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    tmp.select_set(True)
    bpy.context.view_layer.objects.active = tmp
    with bpy.context.temp_override(active_object=tmp, object=tmp):
        bpy.ops.object.modifier_apply(modifier=m.name)
    tme = tmp.data
    # Solidify keeps the input faces first, in order; check it rather than trust it
    same = sum(1 for k in range(min(n0, 50)) if (tme.polygons[k].center - centres0[k]).length < 1e-6)
    if same < min(n0, 50):
        raise RuntimeError("solidify reordered the faces of %s (%d/%d matched)" % (ob.name, same, min(n0, 50)))
    # Solidify writes the input vertices first, then their shell copies in the same order. A vertex
    # with a degenerate normal (a fold at the rear door's arch corner) was thrown 38 cm out as a spike
    # in spite of the clamps: pull any shell vertex further than 1.5x the thickness back to 1x.
    tv = tme.vertices
    fixed = 0
    if len(tv) >= 2 * nv0 and all((tv[k].co - verts0[k]).length < 1e-6 for k in range(0, nv0, max(1, nv0 // 50))):
        for k in range(nv0):
            d = tv[nv0 + k].co - tv[k].co
            if d.length > 1.5 * thickness:
                tv[nv0 + k].co = tv[k].co + d.normalized() * thickness
                fixed += 1
    else:
        raise RuntimeError("solidify vertex order changed on %s; cannot check its shell for spikes" % ob.name)
    if fixed:
        print("    %s: %d shell vertices pulled back from a spike" % (ob.name, fixed))
    ki = _mat_index(tme, INNER_MAT, _inner_material)
    si = _mat_index(tme, shell_mat) if shell_mat else ki
    attr = tme.attributes.get(GEN) or tme.attributes.new(GEN, 'INT', 'FACE')
    vals = [0] * len(tme.polygons)
    for k, p in enumerate(tme.polygons):
        if k >= n0:
            shell = k < 2 * n0
            p.material_index = si if shell else ki
            vals[k] = 1 if shell else 2
    attr.data.foreach_set("value", vals)
    _join(ob, tmp)
    return len(tme.polygons) - n0


# ----------------------------------------------------------------------------------------------
# interior closures (v4, minus the B-pillar strips that poked through the glass line)


def _interior_closures(ob):
    me = ob.data
    names = [m.name if m else "?" for m in me.materials]
    if "Interieur" not in names:
        return 0
    si = names.index("Interieur_sol") if "Interieur_sol" in names else names.index("Interieur")
    ti = names.index("Interieur")
    bm = bmesh.new()
    bm.from_mesh(me)
    # cabin floor between the sills; behind y -0.80 the rear wheel wells start (liner drums from
    # y -0.84, inner wall x 0.56), so the floor narrows there or it shows through the arches. Open
    # where the passengers' footwells go down through it (build_cabin.carve_footwells builds them)
    _bm_slab(bm, si, -0.78, 0.78, -0.80, 0.84, 0.40, 0.475, build_cabin.footwell_holes())
    _bm_box(bm, si, -0.55, 0.55, -1.32, -0.80, 0.40, 0.475)
    # Rocker under the door openings: kotris hangs the black lower cladding on the doors and models
    # no rocker behind it, so with a door open the floor's edge floated over the ground. A charcoal
    # sill from the step down to the rocker line, kept inside the wrap of the doors' cladding (|x| 0.773..0.847): |x| <= 0.82.
    bi = names.index("Body_plastique") if "Body_plastique" in names else si
    for sx in (-1, 1):
        # gen 5: meant to be seen (a charcoal rocker sliver under a door reads as the car's rocker),
        # so the pruning leaves it whole; pruning half of it left an open box showing the ground
        _bm_box(bm, si, min(sx * 0.76, sx * 0.82), max(sx * 0.76, sx * 0.82), -0.86, 0.82, 0.40, 0.43, gen=5)
        # bottom flush with the doors' lower edge (z 0.370): any lower and its face shows under the
        # shut doors, is pruned, and the open box shows the ground in a strip under the car
        _bm_box(bm, bi, min(sx * 0.76, sx * 0.82), max(sx * 0.76, sx * 0.82), -0.86, 0.82, 0.375, 0.40, gen=5)
    body = bpy.data.objects.get("body")

    def skin_in(sx, y, zs, cap):
        best = cap
        for z in zs:
            if body is None:
                break
            hit, loc, _n, _i = body.ray_cast(Vector((sx * 1.6, y, z)), Vector((-sx, 0.0, 0.0)))
            if hit:
                best = min(best, abs(loc.x) - 0.03)
        return best

    def rear_face(sx, x, zs):
        """Most forward rear-skin y at this x (the tail lamps sit ahead of the gate plane). Only hits
        on the tail count: on the full-resolution body a ray through a gap in the rear bumper hit the
        FRONT bumper and stretched the cargo riser the length of the car."""
        y_min = -2.135
        for z in zs:
            if body is None:
                break
            hit, loc, _n, _i = body.ray_cast(Vector((sx * x, -3.0, z)), Vector((0.0, 1.0, 0.0)), distance=1.5)
            if hit and loc.y < -1.90:
                y_min = max(y_min, loc.y + 0.03)
        return min(y_min, -1.92)
    n = 0
    # cargo riser, deck edge to the gate: clipped at its OUTER edges too (the tail rounds off at the
    # corners, where a riser clipped near the centre showed its ends through the gate/bumper gap)
    ya = max(-2.135, *(rear_face(sx, x, (0.55, 0.70, 0.76)) for sx in (-1, 1) for x in (0.30, 0.57)))
    # The storage well under the picnic table (build_table.carve_well, after this) is cut out of the cargo floor
    # down to 14 cm under it; its rear wall stands at y -1.982. The riser ran forward to -1.86 across the
    # well's width, so with the table out its front face cut the well's rear 12 cm off as a dark wall and the
    # well's floor cut removed the riser's top there (2026-10-17 review CAB-13). Across the well the riser now
    # stops 3 mm behind the well's rear wall; beside it, outboard of the well's side walls, it runs on as before.
    import build_table
    wx = build_table.TOP_W / 2 + build_table.WELL_GAP + 0.003
    wy = build_table.CENTRE_Y - (build_table.TOP_L / 2 + build_table.WELL_GAP) - 0.003
    _bm_box(bm, si, -wx, wx, ya, min(wy, -1.86), 0.44, 0.765)         # down to the body's rear sill (0.475)
    for sx in (-1, 1):
        _bm_box(bm, si, min(sx * wx, sx * RISER_X), max(sx * wx, sx * RISER_X), ya, -1.86, 0.44, 0.765)
    # Behind the rear arch: the wheel housing (carpet, z 0.50-0.87) and above it the D-pillar trim (z 0.86-1.32),
    # one lofted prism each per side through stations every 5 cm, sharing one rear end plane (2026-10-17 review
    # OPEN-3: as 10 cm boxes each clipped on its own they stepped in x and y at the cargo opening's lower corners,
    # stepped black blocks, and their inner edge at |x| 0.60 left a 3 cm slot beside the riser (|x| 0.57) down to
    # the arch liner, a light face through the gap). The housing now overlaps the riser from |x| RISER_X - 0.005.
    for sx in (-1, 1):
        # -1.835 (front, the shelf's start) .. -2.035 (the old boxes' rear end: at -2.085 the end cap showed in the
        # gate's corner gap and was pruned, which opened the prism)
        ys = [-1.835 - 0.05 * i for i in range(5)]

        def x_house(y):
            return min(skin_in(sx, yy, (0.55, 0.70, 0.84), 0.82) for yy in (y - 0.025, y, y + 0.025))

        def x_trim(y):
            return min(skin_in(sx, yy, (0.90, 1.05, 1.20, 1.31), 0.81) for yy in (y - 0.025, y, y + 0.025))

        def end_house(xh):
            return max(rear_face(sx, xh, (0.55, 0.70, 0.84)), rear_face(sx, (HOUSE_X + xh) / 2, (0.55, 0.70, 0.84)))

        def end_trim(xt):
            return max(rear_face(sx, xt, (0.90, 1.10, 1.30)), rear_face(sx, (0.70 + xt) / 2, (0.90, 1.10, 1.30)))

        def stations(xf, endf, xmin):
            """[(y, |x|)] front to back while the skin leaves room (|x| > xmin), cut at the rear face clip; and
            the clip's y if that is where it stopped (else None)."""
            st = []
            for y in ys:
                x = xf(y)
                if x <= xmin:
                    if not st:
                        continue                                       # the skin closes in at the front: start later
                    return st, None
                ye = endf(x)
                if y < ye:
                    if st and ye < st[-1][0] - 0.01:
                        st.append((ye, xf(ye)))
                    return st, ye
                st.append((y, x))
            return st, ys[-1]
        sh, eh = stations(x_house, end_house, 0.62)
        stt, et = stations(x_trim, end_trim, 0.72)
        if eh is not None and et is not None and len(sh) >= 2 and len(stt) >= 2:
            ye = max(eh, et)                                           # one end plane at the opening
            for lst, xf in ((sh, x_house), (stt, x_trim)):
                if lst[-1][0] < ye - 1e-4:
                    while len(lst) > 1 and lst[-1][0] < ye - 1e-4:
                        lst.pop()
                    if lst[-1][0] > ye + 0.01:
                        lst.append((ye, xf(ye)))
        for lst, mi_, xin, z0, z1, tag in ((sh, si, HOUSE_X, 0.50, 0.87, "housing"), (stt, ti, 0.70, 0.86, 1.32, "D-pillar trim")):
            if len(lst) < 2:
                print("    cargo corner %s: no %s (skin too close)" % ("lr"[sx > 0], tag))
                continue
            _bm_loft(bm, mi_, sx, xin, lst, z0, z1)
            n += 1
            print("    cargo corner %s: %s y %.3f..%.3f, |x| %.3f..%.3f, %d stations"
                  % ("lr"[sx > 0], tag, lst[-1][0], lst[0][0], min(s[1] for s in lst), max(s[1] for s in lst), len(lst)))
    for k in range(9):                    # 10 cm slices (v6; 5 cm doubled the boxes for little gain)
        y0 = -2.135 + k * 0.10; y1 = min(y0 + 0.10, -1.30)
        ym = (y0 + y1) / 2
        for sx in (-1, 1):
            if ym >= -1.86:                                            # over the arch: a shelf above the drum
                x1 = skin_in(sx, ym, (0.87,), 0.82)
                if x1 > 0.62:
                    # inner edge over the arch liner's inner wall (|x| 0.56): at 0.60 the liner's top showed beside the
                    # floor; and down to the floor (was a 2 cm plate at z 0.86): from the open gate the eye looked under
                    # the plate's inner edge onto the liner's light top (z 0.79) at both front corners of the cargo floor
                    _bm_box(bm, si, min(sx * SHELF_X, sx * x1), max(sx * SHELF_X, sx * x1), y0, y1, 0.76, 0.88)
                    n += 1
                # and a trim plate just inside the quarter skin above it: from the open gate you looked
                # down the slot between the cargo side trim and the skin, through the skin's back
                xq = min(skin_in(sx, y, (0.90, 1.00, 1.08), 0.82) for y in (y0, ym, y1)) + 0.01
                if xq > 0.66:
                    _bm_box(bm, ti, min(sx * (xq - 0.012), sx * xq), max(sx * (xq - 0.012), sx * xq), y0, y1, 0.88, 1.08)
    _drop_shared_caps(bm)
    bm.to_mesh(me)
    bm.free()
    return n


# The cargo area's rear corners (round 2, 2026-10-17 review R2-OC-5). Between the D-pillar trim's lower edge (kotris
# interior, z >= 1.23), the wheel housing (z <= 0.87), the quarter trim plate (y >= -1.835) and the shut gate, the corner
# beside each tail lamp is open: from the rear seats the eye saw the backs of the quarter skin and the opening's jamb (blue,
# body faces at |x| 0.74-0.81, y -1.84..-2.0, z 0.89-1.13) and of the tail lamp's shell (red) and plates (above 1.16).
# _interior_closures' D-pillar loft never fits there ("skin too close": the lamp narrows the corner to |x| < 0.72), so the
# corner is lined instead: every kotris body face in LINING_BOX that turns its back to a seat or cargo eye gets a copy
# LINING_D in front of it on the interior, facing the cabin, in the D-pillar trim's material. From outside
# (gate open) the jamb's painted front still shows; its lining lies behind it.
LINING_BOX = ((0.56, 0.86), (-2.06, -1.80), (0.80, 1.40))   # |x|, y, z of the body face's centre
LINING_D = 0.005
LINING_BACK_Y = -1.90         # lined faces behind this also keep a dark back of their own (see _cargo_lining)


def LINING_LAMP(mat):
    """Materials whose faces in LINING_BOX are lined even when they face the cabin (the lamps' red inner sides)."""
    return mat == "SeamBack" or mat.startswith("Feux") or mat.startswith("Reflect")


def _cargo_lining(report):
    body = bpy.data.objects.get("body")
    it = bpy.data.objects.get("interior")
    if body is None or it is None:
        return 0
    me = body.data
    names = [m.name if m else "?" for m in me.materials]
    ga = me.attributes.get(GEN)
    gv = [0] * len(me.polygons)
    if ga is not None:
        ga.data.foreach_get("value", gv)
    (x0, x1), (y0, y1), (z0, z1) = LINING_BOX
    eyes = _eye_points()
    M = body.matrix_world
    R = M.to_3x3()
    picks = []
    backs = []
    for p in me.polygons:
        if gv[p.index] not in (0, 5) or names[p.material_index] in PANE_MATS:
            continue                                    # (5: the lamps' plates, whose slivers sampled the lamps' red)
        c = M @ p.center
        if not (x0 <= abs(c.x) <= x1 and y0 <= c.y <= y1 and z0 <= c.z <= z1):
            continue
        n = (R @ p.normal).normalized()
        vs = [M @ me.vertices[i].co for i in p.vertices]
        # every face whose back turns to an eye: a test of the face's own points missed the slivers between the lined
        # faces and the housing (teeth of open skin in a first build); lining a hidden back costs only its triangles
        if any((e - c).dot(n) < 0.0 for e in eyes):
            picks.append([v - n * LINING_D for v in reversed(vs)])
            if c.y < LINING_BACK_Y:
                backs.append([v - n * 0.0005 for v in reversed(vs)])
        elif LINING_LAMP(names[p.material_index]):
            picks.append([v + n * LINING_D for v in vs])  # a lamp's inner side or plate turned to the cabin: covered too
    if not picks:
        report("  interior   cargo corner lining: nothing seen from behind")
        return 0
    ime = it.data
    mi = _mat_index(ime, "Interieur")
    Wi = it.matrix_world.inverted()
    bm = bmesh.new()
    bm.from_mesh(ime)
    gl = _gen_layer(bm)
    k = 0
    for pts in picks:
        try:
            f = bm.faces.new([bm.verts.new(Wi @ q) for q in pts])
        except ValueError:
            continue
        f.material_index = mi
        f.smooth = False
        f[gl] = 5
        k += len(pts) - 2
    bm.to_mesh(ime)
    bm.free()
    ime.update()
    # By the opening (LINING_BACK_Y) the faces also get a dark back of their own on the body: with the lining in front
    # of them the seat scan no longer gave them backfill's backs, and from behind the open gate the eye saw past the
    # left tail lamp's inner edge to the road (cargo_left view, 10 px)
    nb = 0
    if backs:
        md = _mat_index(me, "SeamBack", _seamback_material)
        Mi = M.inverted()
        before = [tuple(c.vector) for c in me.corner_normals]
        n_old = len(me.polygons)
        bb = bmesh.new()
        bb.from_mesh(me)
        bgl = _gen_layer(bb)
        for pts in backs:
            try:
                f = bb.faces.new([bb.verts.new(Mi @ q) for q in pts])
            except ValueError:
                continue
            f.material_index = md
            f.smooth = False
            f[bgl] = 5
            nb += len(pts) - 2
        bb.to_mesh(me)
        bb.free()
        me.update()
        normals = list(before) + [None] * (len(me.loops) - len(before))
        for pg in me.polygons[n_old:]:
            for li in pg.loop_indices:
                normals[li] = tuple(pg.normal)
        if len(normals) == len(me.loops) and all(v is not None for v in normals):
            me.normals_split_custom_set(normals)
    report("  interior   cargo corner lining: %d tris, %d body faces turned away from the cargo's eyes in its rear corners lined "
           "(+%d dark back tris on the body by the opening)" % (k, len(picks), nb))
    return k


def _drop_shared_caps(bm):
    """Closure boxes built slice by slice touch end cap to end cap; both caps are hidden. Remove
    pairs of generated faces that cover the same rectangle with opposite normals."""
    gl = _gen_layer(bm)
    key = {}
    for f in bm.faces:
        if f[gl] != 3 or len(f.verts) != 4:
            continue
        k = tuple(sorted(tuple(round(c, 4) for c in v.co) for v in f.verts))
        key.setdefault(k, []).append(f)
    kill = [f for fs in key.values() if len(fs) == 2 and fs[0].normal.dot(fs[1].normal) < -0.99 for f in fs]
    if kill:
        bmesh.ops.delete(bm, geom=kill, context='FACES')
    return len(kill)


# ----------------------------------------------------------------------------------------------
# wheels


def _node_material(name, rgb, roughness=0.45):
    """A material with a Principled BSDF of that base colour (the bake's PALETTE overrides it)."""
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        b = next((n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
        if b:
            b.inputs['Base Color'].default_value = tuple(rgb) + (1.0,)
            b.inputs['Roughness'].default_value = roughness
    return mat


def _window_phase(src, c, ax, u, v, r=0.135):
    """Angle (degrees from u towards v) of the first big window's centre on the full-detail wheel:
    kotris's dark inserts (Partie_noir) seen along the axle at radius r, the runs wider than 20
    degrees, their centres folded onto one 72-degree period. 45 (the road wheels') if none."""
    names = [m.name if m else "?" for m in src.data.materials]
    tree = BVHTree.FromObject(src, bpy.context.evaluated_depsgraph_get())
    dark = []
    for k in range(360):
        a = math.radians(k)
        hit = tree.ray_cast(c + ax * 0.30 + (u * math.cos(a) + v * math.sin(a)) * r, -ax, 0.60)
        dark.append(hit[0] is not None and names[src.data.polygons[hit[2]].material_index] == "Partie_noir")
    if all(dark) or not any(dark):
        return 45.0
    start = dark.index(False)
    runs, k = [], 0
    while k < 360:
        if dark[(start + k) % 360]:
            a0 = k
            while k < 360 and dark[(start + k) % 360]:
                k += 1
            if k - a0 > 20:
                runs.append((start + a0 + (k - 1 - a0) / 2.0) % 360.0)
        else:
            k += 1
    if not runs:
        return 45.0
    period = 360.0 / RIM_SPOKES
    sx = sum(math.cos(math.radians(a) * RIM_SPOKES) for a in runs)
    sy = sum(math.sin(math.radians(a) * RIM_SPOKES) for a in runs)
    return (math.degrees(math.atan2(sy, sx)) / RIM_SPOKES) % period


def _rim_face(bm, c, ax, u, v, ring_out, t_hub, phase, hub_mat, hub_gen, mats):
    """The alloy's face inside the lip's last lathe ring `ring_out` (radius RIM_FACE_R): five spoke
    pairs with real windows (RIM_WINDOW between the pairs, RIM_SLOT between each pair's arms), every
    window a pocket whose walls run straight back past a disc RIM_DEPTH behind the face, and the hub
    (a 16-segment cone, tip t_hub + 2 mm: the old cap's height, so the wheel's bounding box and the
    spare cover's fit are unchanged). Face and walls are generated (gen RIM_GEN, baked flat: no ray
    from the twin's painted dish lands on them); the walls carry the float corner attribute
    rim_shade (1 at the face, RIM_SHADE_DEEP at the disc) that darkens them with depth in the colour
    bake. Every face looks out of its pocket, so with back faces culled nothing in a window is
    see-through. mats: material index by name (Jante, RimWell, Rotor). Returns face counts."""
    from mathutils.geometry import tessellate_polygon
    if hub_gen == 6:                        # road wheels: the windows onto the decal's nuts (RIM_ROAD_PHASE: an
        up = Vector((0.0, 0.0, 1.0))        # angle in the object's y / z plane, where bake_atlas maps the decal)
        up = up - ax * up.dot(ax)
        if up.length > 1e-6:
            a_up = math.degrees(math.atan2(up.dot(v), up.dot(u)))
            phase = (a_up + RIM_ROAD_PHASE - 90.0) % (360.0 / RIM_SPOKES)
    shade = bm.loops.layers.float.get("rim_shade") or bm.loops.layers.float.new("rim_shade")
    gl = _gen_layer(bm)                     # after the float layer: adding one invalidates layer wrappers
    t_out = sum((vt.co - c).dot(ax) for vt in ring_out) / len(ring_out)
    t_ring = t_hub - 0.002

    def t_face(r):                          # the spoke face: a shallow cone from the hub to the lip
        k = min(max((r - RIM_HUB_R) / (RIM_FACE_R - RIM_HUB_R), 0.0), 1.0)
        return t_ring + (t_out - t_ring) * k

    def at(r, deg, t=None):
        a = math.radians(deg)
        return c + ax * (t_face(r) if t is None else t) + (u * math.cos(a) + v * math.sin(a)) * r

    def flat(p):                            # 2D in the face plane
        d = p - c
        return (d.dot(u), d.dot(v))
    hub_ring = [bm.verts.new(at(RIM_HUB_R, 360.0 * k / RIM_HUB_SEG)) for k in range(RIM_HUB_SEG)]
    loops = []
    for s in range(RIM_SPOKES):
        for outline, centre in ((RIM_WINDOW, phase + 72.0 * s), (RIM_SLOT, phase + 36.0 + 72.0 * s)):
            loops.append([bm.verts.new(at(r, centre + d)) for r, d in outline])
    made = []
    # the face: the annulus between the lip ring and the hub ring with the windows as holes
    polys = [list(ring_out), hub_ring] + loops
    flat_v = [vt for poly in polys for vt in poly]
    tris_ = tessellate_polygon([[flat(vt.co) + (0.0,) for vt in poly] for poly in polys])
    for a, b, cc in tris_:
        f = bm.faces.new((flat_v[a], flat_v[b], flat_v[cc]))
        f.material_index = mats["Jante"]
        f[gl] = RIM_GEN
        made.append(f)
    face_set = set(made)
    # walls: each window outline straight back past the disc (2 mm under it: no hairline at the foot)
    t_back = t_out - RIM_DEPTH
    walls = []
    for loop in loops:
        n = len(loop)
        bottom = [bm.verts.new(vt.co - ax * ((vt.co - c).dot(ax) - t_back + 0.002)) for vt in loop]
        pts = [flat(vt.co) for vt in loop]
        for i in range(n):
            j = (i + 1) % n
            f = bm.faces.new((loop[i], loop[j], bottom[j], bottom[i]))
            f.material_index = mats["RimWell"]
            f[gl] = RIM_GEN
            # it must face into the window: a point just off the edge's middle along the normal lies inside
            mid = (loop[i].co + loop[j].co) * 0.5
            f.normal_update()
            probe = flat(mid + f.normal * 0.002)
            inside = False
            for p in range(n):
                (x1, y1), (x2, y2) = pts[p], pts[(p + 1) % n]
                if (y1 > probe[1]) != (y2 > probe[1]) and probe[0] < x1 + (probe[1] - y1) * (x2 - x1) / (y2 - y1):
                    inside = not inside
            if not inside:
                f.normal_flip()
            for lp in f.loops:
                lp[shade] = 1.0 if lp.vert in loop else RIM_SHADE_DEEP
            walls.append(f)
    # the disc behind the windows (brake rotor / hub face), facing out
    centre = bm.verts.new(c + ax * t_back)
    disc_ring = [bm.verts.new(c + ax * t_back + (u * math.cos(2 * math.pi * k / RIM_HUB_SEG)
                                                  + v * math.sin(2 * math.pi * k / RIM_HUB_SEG)) * RIM_DISC_R)
                 for k in range(RIM_HUB_SEG)]
    disc = [bm.faces.new((centre, disc_ring[k], disc_ring[(k + 1) % RIM_HUB_SEG])) for k in range(RIM_HUB_SEG)]
    for f in disc:
        f.material_index = mats["Rotor"]
        f[gl] = RIM_GEN
    # the hub: a shallow cone over the lug circle (HubCap: the wheel sheet paints the H and the nuts;
    # Jante on the spare: projected from its twin, kotris's own nuts)
    tip = bm.verts.new(c + ax * (t_hub + 0.002))
    hub = [bm.faces.new((tip, hub_ring[k], hub_ring[(k + 1) % RIM_HUB_SEG])) for k in range(RIM_HUB_SEG)]
    for f in hub:
        f.material_index = hub_mat
        f[gl] = hub_gen
    for f in made + disc + hub:
        f.normal_update()
        if f.normal.dot(ax) < 0:
            f.normal_flip()
    # tidy the face's triangulation (scanfill leaves slivers): rotate only edges inside the face
    inner = [e for e in bm.edges if len(e.link_faces) == 2 and all(g in face_set for g in e.link_faces)]
    if inner:
        bmesh.ops.beautify_fill(bm, faces=made, edges=inner, use_restrict_tag=False, method='AREA')
    face = 0
    for f in bm.faces:
        if f[gl] == RIM_GEN and f.material_index == mats["Jante"]:
            face += 1
            if f.normal.dot(ax) < 0:
                f.normal_flip()
    return {"face": face, "walls": len(walls), "disc": len(disc), "hub": len(hub),
            "depth": t_out - t_back, "phase": phase}


def _clear_hub(ob, r_clear=0.100):
    """kotris's own hub pieces (now on the wheel, see split_base.HUBS): the black centre cap would
    z-fight with our cap disc and the lug nuts and their seats sit under it. Remove every non-rim,
    non-tyre face within r_clear of the axle on the outer half; the dark inserts between the spokes
    (r ~0.13) stay: _window_phase reads the spokes' phase off them."""
    me = ob.data
    names = [m.name if m else "?" for m in me.materials]
    xs = [v.co.x for v in me.vertices]; ys = [v.co.y for v in me.vertices]; zs = [v.co.z for v in me.vertices]
    yc, zc = (min(ys) + max(ys)) / 2, (min(zs) + max(zs)) / 2
    xm = (min(xs) + max(xs)) / 2
    sign = 1 if xm > 0 else -1
    bm = bmesh.new()
    bm.from_mesh(me)
    kill = [f for f in bm.faces
            if names[f.material_index] not in ("Jante", "Pneu")
            and ((f.calc_center_median().y - yc) ** 2 + (f.calc_center_median().z - zc) ** 2) ** 0.5 < r_clear
            and (f.calc_center_median().x - xm) * sign > 0]
    n = len(kill)
    bmesh.ops.delete(bm, geom=kill, context='FACES')
    bm.to_mesh(me)
    bm.free()
    return n


def _wheel_rotor(ob):
    """What shows between the spokes: a brake rotor and hub, two-sided, at the wheel's mid plane
    (v4's dark copy of the back plate read as black holes in game)."""
    me = ob.data
    ri = _mat_index(me, "Rotor")
    xs = [v.co.x for v in me.vertices]; ys = [v.co.y for v in me.vertices]; zs = [v.co.z for v in me.vertices]
    yc, zc = (min(ys) + max(ys)) / 2, (min(zs) + max(zs)) / 2
    xo = max(xs) if (max(xs) + min(xs)) / 2 > 0 else min(xs)
    sign = 1 if xo > 0 else -1
    xm = (min(xs) + max(xs)) / 2
    bm = bmesh.new()
    bm.from_mesh(me)
    gl = _gen_layer(bm)
    seg = 16
    for x, r, facing in ((xm + sign * 0.002, 0.145, sign), (xm - sign * 0.002, 0.145, -sign),
                         (xm + sign * 0.030, 0.075, sign)):
        c = bm.verts.new((x, yc, zc))
        ring = [bm.verts.new((x, yc + r * math.cos(2 * math.pi * i / seg), zc + r * math.sin(2 * math.pi * i / seg))) for i in range(seg)]
        made = []
        for i in range(seg):
            f = bm.faces.new((c, ring[i], ring[(i + 1) % seg]))
            f.material_index = ri
            f.smooth = False
            f[gl] = 4
            made.append(f)
        bm.normal_update()
        for f in made:
            if f.normal.x * facing < 0:
                f.normal_flip()
    bm.to_mesh(me)
    bm.free()


# ----------------------------------------------------------------------------------------------
# low poly (v6)


def _apply_modifier(ob, m):
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob
    with bpy.context.temp_override(active_object=ob, object=ob, selected_objects=[ob], selected_editable_objects=[ob]):
        bpy.ops.object.modifier_apply(modifier=m.name)


def _fix_folds(ob, hi):
    """Collapse decimation folds faces over their neighbours; their UVs then overlap the visible
    surface and the bake writes garbage into it (v4's black door streaks). A low face whose normal
    opposes the nearest high surface is a fold: collapse its shortest edge, repeat."""
    dg = bpy.context.evaluated_depsgraph_get()
    tree = BVHTree.FromObject(hi, dg)
    total = 0
    for _ in range(8):
        bm = bmesh.new()
        bm.from_mesh(ob.data)
        bm.normal_update()
        bad = []
        for f in bm.faces:
            if f.calc_area() < 1e-9:
                bad.append(f)
                continue
            loc, n, _i, _d = tree.find_nearest(f.calc_center_median())
            if loc is None or f.normal.dot(n) >= -0.5:
                continue
            nb = Vector()
            for e in f.edges:
                for g in e.link_faces:
                    if g is not f:
                        nb += g.normal * g.calc_area()
            if nb.length < 1e-12 or f.normal.dot(nb.normalized()) < 0.0:
                bad.append(f)                 # flipped against the surface and against its neighbours
        if not bad:
            bm.free()
            break
        edges = list({min(f.edges, key=lambda e: e.calc_length()) for f in bad})
        bmesh.ops.collapse(bm, edges=edges, uvs=True)
        bm.to_mesh(ob.data)
        bm.free()
        total += len(bad)
    return total


SEAMS = None                 # lowpoly.seam_points over every part, set by prep() before decimating
SOLIDIFY_PARTS = ("trunk",)


# Gate hinge knuckles (2026-10-14 review, "jagged dark blades"): kotris models the side-hinged gate's two
# knuckles as small closed paint islands on its hinge edge (110 and 78 tris, 2.2 x 4.4 x 10-11 cm, at
# x 0.661-0.683, z 0.758-0.856 and 1.016-1.125). The trunk's decimation took them to 8 tris each, thin
# sheets with spiky tips that read as dark shards down the gate edge. They come off before decimation
# (their budget goes to the gate skin) and come back after the gate's solidify as closed boxes on their
# full-detail bounds (gen 7: baked flat in their own material, the paint, never pruned).
HINGE_PART = "trunk"
HINGE_X = 0.64                # an island wholly outboard of this on the hinge side (+x: the gate hinges right)
HINGE_SIZE = 0.15             # ... whose bounds stay under this in every axis, all of it paint
HINGE_BOXES = []              # (lo, hi) per knuckle, filled by _hinge_knuckles
# Round 3 (R2-OC-7 remainder): the lower knuckle's box (y -2.061..-2.017) stood 2 mm in front of the cargo closure
# beside the hinge (interior, Interieur_sol, y -2.019, x 0.565-0.690, z 0.50-0.87), and the swinging gate turned its
# front face through it at 4-8 deg. A box starting below HINGE_CLOSURE_Z ends at HINGE_FRONT_Y, behind the closure.
HINGE_FRONT_Y = -2.026
HINGE_CLOSURE_Z = 0.90
HINGE_BODY_Y = -2.010         # the body-side hinge leaf runs from the hinge line forward into the body's rear corner
                              # (its skin at x 0.70-0.72 lies at y -2.035..-1.998 over the knuckles' heights)
HINGE_BARREL_R = 0.011        # the hinge barrel on the rig's hinge line


def _hinge_knuckles(ob):
    """Delete the gate's hinge knuckle islands from the full-detail trunk before decimation; remember
    their bounds for _gate_hinges."""
    del HINGE_BOXES[:]
    ids, boxes = [], []
    for faces, lo, hi, _maj, mats in build_details.islands(ob):
        size = hi - lo
        if lo.x > HINGE_X and max(size) < HINGE_SIZE and mats == {"Body"}:
            boxes.append([lo.copy(), hi.copy()])
            ids.extend(faces)
    merged = True                           # kotris leaves pieces unwelded: one knuckle = the union of the
    while merged:                           # pieces whose bounds come within 5 mm of each other
        merged = False
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                a, b = boxes[i], boxes[j]
                if all(a[0][k] - 0.005 <= b[1][k] and b[0][k] - 0.005 <= a[1][k] for k in range(3)):
                    a[0] = Vector(tuple(min(a[0][k], b[0][k]) for k in range(3)))
                    a[1] = Vector(tuple(max(a[1][k], b[1][k]) for k in range(3)))
                    boxes.pop(j)
                    merged = True
                    break
            if merged:
                break
    HINGE_BOXES.extend((lo, hi) for lo, hi in boxes)
    if ids:
        _delete_faces(ob, ids)


def _gate_hinges(report):
    """Closed boxes where the gate's hinge knuckles were (HINGE_BOXES), on the low trunk, flat shaded."""
    ob = bpy.data.objects.get(HINGE_PART)
    if ob is None or not HINGE_BOXES:
        report("  %-10s hinge knuckles: none found (HINGE_X %.2f, HINGE_SIZE %.2f)" % (HINGE_PART, HINGE_X, HINGE_SIZE))
        return 0
    groups = []
    for lo, hi in HINGE_BOXES:
        if lo.z < HINGE_CLOSURE_Z and hi.y > HINGE_FRONT_Y > lo.y:     # round 3: behind the cargo closure (see below)
            hi.y = HINGE_FRONT_Y
        c = (lo + hi) / 2
        groups.append((build_details.PAINT, False, build_details.orient(build_details.box_faces(tuple(lo), tuple(hi)), tuple(c))))
    # 2026-10-18 (feedback: "why is the tailgate not attached to anything?"): the gate turns about the rig's hinge
    # line (rig_vehicle X/Y_TG_HINGE, 0.69 / -2.11), 5-8 cm behind the knuckles so its corner clears the body's
    # corner, and with the gate open nothing joined the two: the RD1's exposed hinges were missing. Each knuckle
    # gets its leaf back to the hinge line (on the gate, it swings), and the body gets the other half: a leaf from
    # its rear corner to the hinge line and the barrel on it. Both halves meet on the axis at every angle.
    import rig_vehicle
    px, py = rig_vehicle.X_TG_HINGE, rig_vehicle.Y_TG_HINGE
    body_groups = []
    for lo, hi in HINGE_BOXES:
        z0, z1 = lo.z + 0.008, hi.z - 0.008
        g_lo, g_hi = (lo.x + 0.003, py - 0.004, z0), (min(hi.x, px - 0.004), lo.y + 0.004, z1)
        groups.append((build_details.PAINT, False, build_details.orient(build_details.box_faces(g_lo, g_hi),
                                                                       tuple((Vector(g_lo) + Vector(g_hi)) / 2))))
        b_lo, b_hi = (px - 0.002, py - 0.006, z0), (px + 0.022, HINGE_BODY_Y, z1)     # into the body's corner
        body_groups.append((build_details.PAINT, False, build_details.orient(build_details.box_faces(b_lo, b_hi),
                                                                            tuple((Vector(b_lo) + Vector(b_hi)) / 2))))
        r = HINGE_BARREL_R                                   # the barrel, round enough as an octagon
        ring = [(px + r * math.cos(math.pi * i / 4), py + r * math.sin(math.pi * i / 4)) for i in range(8)]
        faces = [[(x, y, z0) for x, y in reversed(ring)], [(x, y, z1 + 0.004) for x, y in ring]]
        for i in range(8):
            (xa, ya), (xb, yb) = ring[i], ring[(i + 1) % 8]
            faces.append([(xa, ya, z0), (xb, yb, z0), (xb, yb, z1 + 0.004), (xa, ya, z1 + 0.004)])
        body_groups.append((build_details.PAINT, False, build_details.orient(faces, (px, py, (z0 + z1) / 2))))
    k = build_details.add_faces(ob, groups)
    body = bpy.data.objects.get("body")
    kb = build_details.add_faces(body, body_groups) if body is not None else 0
    report("  %-10s hinge knuckles: %d boxes + leaves to the hinge line, %d tris; body hinge halves %d tris (%s)"
           % (HINGE_PART, len(HINGE_BOXES), k, kb, "; ".join(
               "x %.3f..%.3f y %.3f..%.3f z %.3f..%.3f" % (lo.x, hi.x, lo.y, hi.y, lo.z, hi.z) for lo, hi in HINGE_BOXES)))
    return k


# The gate's bottom against the rear bumper (round 3, R2-OC-7 remainder). The gate swings rearward from its first
# degree, and its bottom rested 0-3 mm over the bumper: (1) the hinge-side corner (x 0.575-0.686) sits on the bumper's
# step (body Body_plastique, top z 0.735-0.741, EXT-16's held step) and its rim / skin corner faces at z 0.736-0.747
# scraped the step's top from 0.25 to 4.25 deg; (2) the inner shell's bottom (solidify, gen 1-2, and the card's band)
# at z 0.687-0.692 lies over the bumper's black lip (body Partie_noir, up to z 0.693 at y -2.07..-2.13) and cut it
# at 0.5-4.5 deg. Every gate vertex over the step (x >= GATE_STEP[0], y >= GATE_STEP[1], z between GATE_STEP[2] and
# GATE_STEP[3]) goes up to GATE_STEP[3], 6 mm over the step's top; every generated vertex (shell, rim, band) under
# GATE_INNER_Z goes up to it, 5 mm over the lip. The outer skin's own bottom edge elsewhere stays where it is.
# (Clearances as small as the sweep allows: every mm here is a slit in the shut pose. At the lower corners the slit
# looks onto the cargo closures: 0.747 / 0.698 there added cabin-pass slits in close_wheel_rear_left / right, 0.694
# at the sides (|x| >= GATE_SIDE_X) put the left one back to main's; the hinge-side corner still shows one, see the
# round-3 report.)
# Integration 2026-10-18: the hinge-side corner lift is OFF (top = bottom = 0.70). Its 2 mm over the step opened a
# cabin-pass slit in the SHUT pose (close_wheel_rear_right, 46 px); the contact it avoided lasts 0.25-4.25 deg of
# the swing, inside the bumper's step, and nobody sees it.
GATE_STEP = (0.572, -2.095, 0.70, 0.70)
GATE_INNER_Z = 0.698
GATE_SIDE_X, GATE_SIDE_Z = 0.55, 0.694      # ... and toward the side edges, over the lip's black corner pieces (0.692)
GATE_MATS = ("Body", "Body_plastique", INNER_MAT, "DoorCard_trunk")   # the spare and its carrier never move


def _gate_clearance(report):
    ob = bpy.data.objects.get("trunk")
    if ob is None:
        return 0
    me = ob.data
    names = [m.name if m else "?" for m in me.materials]
    ga = me.attributes.get(GEN)
    gv = [0] * len(me.polygons)
    if ga is not None:
        ga.data.foreach_get("value", gv)
    ours = set()
    other = set()
    gen_v = set()
    for p in me.polygons:
        (ours if names[p.material_index] in GATE_MATS and gv[p.index] != 7 else other).update(p.vertices)
        if gv[p.index] in (1, 2, 5):
            gen_v.update(p.vertices)
    skin_v = {i for p in me.polygons if gv[p.index] == 0 for i in p.vertices}
    step = inner = 0
    x0, y0, z0, z1 = GATE_STEP
    for i in ours - other:
        v = me.vertices[i]
        if v.co.x >= x0 and v.co.y >= y0 and z0 < v.co.z < z1:
            v.co.z = z1
            step += 1
        elif i in gen_v and i not in skin_v and abs(v.co.x) < 0.70:
            zmin = GATE_INNER_Z if abs(v.co.x) < GATE_SIDE_X else GATE_SIDE_Z
            if v.co.z < zmin:
                v.co.z = zmin
                inner += 1
    me.update()
    report("  trunk      gate clearance: %d vertices over the bumper step up to z %.3f, %d shell / rim / band vertices "
           "up to z %.3f (%.3f at the sides)" % (step, z1, inner, GATE_INNER_Z, GATE_SIDE_Z))
    return step + inner


def _drop_box(ob, box):
    """Delete the loose piece of faces inside box (x, y, z ranges, metres): the vertices inside are grouped by
    edges; a group of up to DROP_MAX verts is the piece, and every face touching it goes. Bigger groups stay."""
    (x0, x1), (y0, y1), (z0, z1) = box
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bm.verts.ensure_lookup_table()
    def inside(v):
        c = v.co
        return x0 <= c.x <= x1 and y0 <= c.y <= y1 and z0 <= c.z <= z1
    seen, piece = set(), set()
    for v0 in bm.verts:
        if v0.index in seen or not inside(v0):
            continue
        comp, stack = [], [v0]
        seen.add(v0.index)
        while stack:
            v = stack.pop()
            comp.append(v)
            for e in v.link_edges:
                u = e.other_vert(v)
                if u.index not in seen and inside(u):
                    seen.add(u.index)
                    stack.append(u)
        if len(comp) <= DROP_MAX:
            piece.update(v.index for v in comp)
    doomed = [f for f in bm.faces if any(v.index in piece for v in f.verts)]
    if doomed:
        bmesh.ops.delete(bm, geom=doomed, context='FACES')
        bm.to_mesh(ob.data)
    bm.free()
    print("  %-12s drop box: %d piece verts, %d faces removed" % (ob.name, len(piece), len(doomed)))


def _make_low(name, budget, report):
    """Keep the full-detail part as '<name>_hi' (bake source, not exported) and bring '<name>' down
    to its triangle budget: collapse decimation (mirror-symmetric where the part is), folds
    repaired against the high surface, custom normals transferred from it so the low mesh shades
    like the original."""
    ob = bpy.data.objects.get(name)
    if ob is None:
        return
    if name in DROP_BOX:
        for o in (ob, bpy.data.objects.get(name + "_full")):
            if o is not None:
                _drop_box(o, DROP_BOX[name])
    old = bpy.data.objects.get(name + "_hi")
    if old is not None:
        bpy.data.objects.remove(old, do_unlink=True)
    prebuilt = bpy.data.objects.get(name + "_full")      # a generator made both detail levels
    if prebuilt is not None:
        prebuilt.name = name + "_hi"
        prebuilt.data.name = name + "_hi"
        prebuilt.hide_render = True
        n_full = tris(prebuilt)
        if tris(ob) > budget:
            lowpoly.decimate(ob.data, budget, border_tol=None, max_dev=0.020,   # only seen with the hood up
                             hi_tree=BVHTree.FromObject(prebuilt, bpy.context.evaluated_depsgraph_get()))
        prebuilt.hide_set(True)
        report("  %-12s coarse build %5d tris (full detail %d kept as the bake source)" % (name, tris(ob), n_full))
        return
    hi = ob.copy()
    hi.data = ob.data.copy()
    hi.name = name + "_hi"
    hi.data.name = name + "_hi"
    ob.users_collection[0].objects.link(hi)
    hi.hide_render = True
    n0 = tris(ob)
    # decal islands (engine cover lettering, hood pad label) stay whole: they keep their own faces,
    # material and UV boost, and the bake projects the high decal onto them 1:1
    keep = _decal_islands(ob)
    protected = _split_off(ob, keep, name + "_keep") if keep else None
    n_keep = tris(protected) if protected else 0
    if name == HINGE_PART:                  # the gate's hinge knuckles come back as boxes (_gate_hinges)
        _hinge_knuckles(ob)
    n_rest = tris(ob)
    dropped = 0
    subs = []
    if name in DOORS:
        card = _islands_of(ob, {"Interieur"})
        if card:
            _delete_faces(ob, card)
        # the outside handle (one 383-tri island that fills a hole in the skin) and, on the front
        # doors, the mirror housing come off BEFORE decimation, so the hole rims are guarded as
        # outlines (lowpoly.BORDER_TOL) and the skin gets their budget; build_details rebuilds both
        # as clean gen-7 geometry once the panel is low. Decimated on their own budgets they shipped
        # as a 45-50 tri blob and a ~70 tri lump (second in-game look, 2026-10-12)
        handle = build_details.handle_islands(ob, name)
        if handle:
            _delete_faces(ob, handle)
        if name in build_details.MIRROR_DOORS:
            mirror = build_details.mirror_islands(ob)
            if mirror:
                _delete_faces(ob, mirror)
    if name in LATHE_PARTS:
        info = _lathe_replace(ob, hi, cap=True, rim=hi, hub="HubCap")
        lowpoly.smooth_normals(ob.data, 40.0)
        hi.hide_set(True)
        report("  %-12s lathe wheel %6d -> %5d tris (%s)" % (name, n0, tris(ob), _rim_report(info)))
        return
    if name in LATHE_SUB:
        ids = _islands_of(ob, LATHE_SUB[name])
        if ids:
            sub = _split_off(ob, ids, name + "_lathe")
            info = _lathe_replace(sub, sub, cap=True, rim=hi, hub="Jante")
            lowpoly.smooth_normals(sub.data, 40.0)
            ins = _spare_inserts(ob, *_wheel_frame(sub, ("Pneu",))[:2])
            if ins:
                _delete_faces(ob, ins)
            report("  %-12s spare lathe %d tris, %d insert faces out of its windows (%s)"
                   % (name, tris(sub), len(ins), _rim_report(info)))
            subs.append(sub)
            n_keep += tris(sub)
    for mats, sub_budget, small in ([] if name in LATHE_SUB else SUB_BUDGET.get(name, [])):
        ids = _islands_of(ob, mats)
        if ids:
            sub = _split_off(ob, ids, name + "_sub%d" % len(subs))
            if small:
                dropped += lowpoly.drop_small_islands(sub.data, small)
            if tris(sub) > sub_budget:
                lowpoly.decimate(sub.data, sub_budget)
                lowpoly.transfer_normals(sub, hi)
            subs.append(sub)
            n_keep += tris(sub)
    n_rest = tris(ob)
    if n_rest + n_keep > budget:
        if name in SMALL_PIECES:
            dropped += lowpoly.drop_small_islands(ob.data, SMALL_PIECES[name])
        free = name in FREE_OUTLINES
        tree = BVHTree.FromObject(hi, bpy.context.evaluated_depsgraph_get())   # always: the shape guard
        mnames = [m.name if m else "?" for m in ob.data.materials]
        devs = {i: MAT_DEV[n] for i, n in enumerate(mnames) if n in MAT_DEV}
        devs[None] = lowpoly.MAX_DEV
        if free:                            # no outline guard, but held to FREE_DEV of the original
            devs = FREE_DEV
        target = max(1, budget - n_keep)
        hold = set()
        if name == "body":                  # the windscreen's lower corners keep kotris's own triangles,
            corners = _windscreen_corners(ob)                            # paid on top of the budget so the
            hold = _held_verts(ob, corners, WS_HOLD_R)                   # rest of the body keeps its own
            held = sum(len(p.vertices) - 2 for p in ob.data.polygons if all(i in hold for i in p.vertices))
            target += held
            report("  %-12s held: %d vertices, %d tris within %.0f mm of %s" % (name, len(hold), held, WS_HOLD_R * 1000,
                   ", ".join("(%.3f, %.3f, %.3f)" % tuple(c) for c in corners)))
        if name in DETAIL_HOLD:             # small details read at the game's zoom: kotris's own triangles
            centres, r = DETAIL_HOLD[name]
            centres = [Vector(c) for c in centres]
            more = _held_verts(ob, centres, r) - hold                    # added to any hold above, never replacing it
            held = sum(len(p.vertices) - 2 for p in ob.data.polygons
                       if all(i in hold or i in more for i in p.vertices) and not all(i in hold for i in p.vertices))
            hold |= more
            target += held
            report("  %-12s held: %d vertices, %d tris within %.0f mm of %s" % (name, len(more), held, r * 1000,
                   ", ".join("(%.3f, %.3f, %.3f)" % tuple(c) for c in centres)))
        if name in EDGE_HOLD:               # a band along an edge, held the same way (the hood's leading edge)
            axis, above = EDGE_HOLD[name]
            # the top side of the edge only: held at full detail, the roll's 2-5 mm underside faces came out under
            # backfill's 9 mm scan grid and the raised hood's leading edge showed 1-px ground specks (bay_open)
            up = {}
            for p in ob.data.polygons:
                for i in p.vertices:
                    up[i] = min(up.get(i, 1.0), p.normal.z)
            more = {v.index for v in ob.data.vertices if v.co[axis] > above and up.get(v.index, -1.0) > EDGE_HOLD_UP} - hold
            held = sum(len(p.vertices) - 2 for p in ob.data.polygons
                       if all(i in hold or i in more for i in p.vertices) and not all(i in hold for i in p.vertices))
            hold |= more
            target += held
            report("  %-12s held: %d vertices, %d tris with %s > %.3f" % (name, len(more), held, "xyz"[axis], above))
        hold = hold or None
        lowpoly.decimate(ob.data, target, border_tol=None if free else lowpoly.BORDER_TOL,
                         seam_kd=SEAMS, hi_tree=tree, max_dev=devs, hold=hold)
    edge = _hood_edge(ob, hi, report) if name == "hood" else None     # EXT-15: the leading edge as a clean grid
    lowpoly.transfer_normals(ob, hi)
    if edge:
        _hood_edge_normals(ob, edge)
    for sub in subs:                        # lathe subs keep their own (generated) normals
        _join(ob, sub)
    if protected is not None:
        _join(ob, protected)
    hi.hide_set(True)
    dev = _deviation(ob, hi)
    report("  %-12s low poly %6d -> %5d tris (%d small-piece faces dropped; high-to-low distance p95 %.1f mm, max %.1f mm)"
           % (name, n0, tris(ob), dropped, dev[0] * 1000, dev[1] * 1000))


def _wheel_frame(ob, tyre_mats):
    """(centre, axis towards the wheel's outer face, radial unit u, radial unit v) from the tyre's
    vertices: the axle is the direction of least spread; outward points away from the car."""
    names = [m.name if m else "?" for m in ob.data.materials]
    vids = {i for p in ob.data.polygons if names[p.material_index] in tyre_mats for i in p.vertices}
    pts = np.array([tuple(ob.data.vertices[i].co) for i in vids])
    c = (pts.min(axis=0) + pts.max(axis=0)) / 2.0
    w, V = np.linalg.eigh(np.cov((pts - c).T))
    ax = Vector(V[:, 0]).normalized()
    if ax.dot(Vector(c) - Vector((0.0, 0.0, 0.8))) < 0:
        ax = -ax
    u = ax.orthogonal().normalized()
    v = ax.cross(u).normalized()
    return Vector(c), ax, u, v


def _lathe_profile(ob, c, ax, open_face=False):
    """(t, r, material) points from the inner bead round the tyre to the rim face, sampled from the
    original's envelope (t along the axle, outward positive; r from the axle), the bead's t and the
    hub's t (the face's height at r 0.105). open_face: the lathe stops at the lip's inner edge
    (RIM_FACE_R), where _rim_face takes over."""
    names = [m.name if m else "?" for m in ob.data.materials]
    tyre, rim = [], []
    for p in ob.data.polygons:
        m = names[p.material_index]
        for i in p.vertices:
            d = ob.data.vertices[i].co - c
            t = d.dot(ax)
            r = (d - ax * t).length
            if m == "Pneu":
                tyre.append((t, r))
            elif m in ("Jante", "Chrome"):
                rim.append((t, r))
    R = max(r for t, r in tyre)
    Rb = min(r for t, r in tyre)
    h = R - Rb

    def side(rr, sign, tol=0.012):          # outermost t of the tyre at radius rr on one side
        band = [t for t, r in tyre if abs(r - rr) < tol]
        if not band and tol < 0.012:
            band = [t for t, r in tyre if abs(r - rr) < 0.012]
        if not band:
            band = [t for t, r in tyre]
        return max(band) if sign > 0 else min(band)

    def tread(tt):                          # largest radius of the tyre near t = tt
        band = [r for t, r in tyre if abs(t - tt) < 0.012]
        return max(band) if band else R
    t_in, t_out = min(t for t, r in tyre), max(t for t, r in tyre)
    # 2026-10-12 (feedback: "the back tire also need more work"): the tyre had one 60-degree chamfer
    # from the tread edge to the upper sidewall on each side, which the 40-degree smoothing kept as
    # two hard edges: a boxy black drum, worst on the spare seen end-on. A ring on the shoulder
    # (0.89 of the section height, sampled in a 4 mm band so it lies ON the original's envelope)
    # splits it into steps of 34 / 32 / 35 degrees, all smoothed: a round shoulder for 48 tris a ring
    # (11 profile points x 24 segments: 544 tris with the caps; KI5's wheel 356, ours was 448)
    prof = []
    for k in (0.0, 0.6, SHOULDER_K):
        rr = Rb + k * h
        prof.append((side(rr, -1, 0.004 if k == SHOULDER_K else 0.012), rr, "Pneu"))
    for k in (0.17, 0.83):
        tt = t_in + k * (t_out - t_in)
        prof.append((tt, tread(tt), "Pneu"))
    for k in (SHOULDER_K, 0.6, 0.0):
        rr = Rb + k * h
        prof.append((side(rr, 1, 0.004 if k == SHOULDER_K else 0.012), rr, "Pneu"))
    outer = [(t, r) for t, r in rim if t > 0.0]

    def face_t(rr):
        band = [t for t, r in outer if abs(r - rr) < 0.012]
        return max(band) if band else prof[-1][0] - 0.02
    for rr in ((Rb - 0.004, RIM_FACE_R) if open_face else (Rb - 0.004, 0.5 * (Rb + 0.105), 0.105)):
        prof.append((face_t(rr), rr, "Jante"))
    return prof, t_in, face_t(0.105)


def _lathe_replace(ob, src, cap, rim=None, hub="Jante"):
    """Replace ob's mesh by a lathe of src's wheel (same object frame). cap: close the hub with a
    flat fan (the old closed dish). rim: the full-detail twin to read the spoke phase from; the
    lathe then stops at the lip and _rim_face builds the windowed spoke face, its pockets and the
    hub in `hub` material (HubCap on the road wheels: the decal, gen 6; Jante on the spare: its
    twin's projection). Returns the rim's face counts (or None)."""
    c, ax, u, v = _wheel_frame(src, ("Pneu",))
    prof, t_in, t_hub = _lathe_profile(src, c, ax, open_face=rim is not None)
    me = ob.data
    names = [m.name if m else "?" for m in me.materials]
    mi = {n: _mat_index(me, n) for n in ("Pneu", "Jante")}
    if rim is not None:
        mi["RimWell"] = _mat_index(me, "RimWell", lambda: _node_material("RimWell", (0.20, 0.20, 0.21), 0.6))
        mi["Rotor"] = _mat_index(me, "Rotor", lambda: _node_material("Rotor", (0.045, 0.045, 0.047), 0.7))
        mi["hub"] = _mat_index(me, hub, lambda: _node_material(hub, (0.26, 0.26, 0.27)))
    bm = bmesh.new()
    if rim is not None:                     # layers first: adding one later invalidates wrappers
        _gen_layer(bm)
        bm.loops.layers.float.new("rim_shade")
    rings = []
    for t, r, _m in prof:
        ring = []
        for k in range(LATHE_SEG):
            a = 2.0 * math.pi * k / LATHE_SEG
            ring.append(bm.verts.new(c + ax * t + (u * math.cos(a) + v * math.sin(a)) * r))
        rings.append(ring)
    ts = [t for t, r, m in prof if m == "Pneu"]
    t_mid = 0.5 * (min(ts) + max(ts))
    made = []                               # (face, expected outward direction or None = from the tyre's middle)
    for j in range(len(rings) - 1):
        lip = prof[j + 1][2] == "Jante"
        for k in range(LATHE_SEG):
            k2 = (k + 1) % LATHE_SEG
            f = bm.faces.new((rings[j][k], rings[j][k2], rings[j + 1][k2], rings[j + 1][k]))
            f.material_index = mi["Jante"] if lip else mi["Pneu"]
            made.append((f, ax if (lip and prof[j][2] == "Jante") else None))
    # the back of the wheel (inner bead to the axle), seen under the car from low: the dark well colour, not the
    # alloy's silver (2026-10-17 review WHL-6: "a flat silver disc")
    back_mi = mi["RimWell"] if "RimWell" in mi else _mat_index(me, "RimWell", lambda: _node_material("RimWell", (0.20, 0.20, 0.21), 0.6))
    back = bm.verts.new(c + ax * prof[0][0])
    for k in range(LATHE_SEG):
        f = bm.faces.new((back, rings[0][(k + 1) % LATHE_SEG], rings[0][k]))
        f.material_index = back_mi
        made.append((f, -ax))
    if cap and rim is None:
        centre = bm.verts.new(c + ax * prof[-1][0])
        for k in range(LATHE_SEG):
            f = bm.faces.new((centre, rings[-1][k], rings[-1][(k + 1) % LATHE_SEG]))
            f.material_index = mi["Jante"]
            made.append((f, ax))
    bm.normal_update()
    for f, want in made:
        out = want if want is not None else f.calc_center_median() - (c + ax * t_mid)
        if f.normal.dot(out) < 0:
            f.normal_flip()
    info = None
    if rim is not None:
        phase = _window_phase(rim, c, ax, u, v)
        info = _rim_face(bm, c, ax, u, v, rings[-1], t_hub, phase, mi["hub"], 6 if hub == "HubCap" else 0, mi)
    bmesh.ops.triangulate(bm, faces=bm.faces[:], quad_method='BEAUTY', ngon_method='BEAUTY')
    for f in bm.faces:
        f.smooth = True
    bm.to_mesh(me)
    bm.free()
    me.update()
    return info


def _rim_report(info):
    if not info:
        return "closed dish"
    return ("windowed rim: face %d, walls %d quads, disc %d, hub %d tris; pockets %.0f mm deep, phase %.1f deg"
            % (info["face"], info["walls"], info["disc"], info["hub"], info["depth"] * 1000, info["phase"]))


def _spare_inserts(ob, c, ax):
    """Faces of kotris's dark spoke inserts (Partie_noir) inside the spare's rim: behind the old
    closed dish they were hidden; in the windowed rim they would float in the pockets."""
    names = [m.name if m else "?" for m in ob.data.materials]
    out = []
    for p in ob.data.polygons:
        if names[p.material_index] != "Partie_noir":
            continue
        d = Vector(p.center) - c
        t = d.dot(ax)
        if t > 0.0 and (d - ax * t).length < RIM_FACE_R:
            out.append(p.index)
    return out


def _delete_faces(ob, ids):
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bm.faces.ensure_lookup_table()
    bmesh.ops.delete(bm, geom=[bm.faces[i] for i in sorted(set(ids))], context='FACES')
    bm.to_mesh(ob.data)
    bm.free()


def _components(mask):
    """Label 4-connected regions of a small boolean array (pure numpy/python)."""
    lab = np.zeros(mask.shape, dtype=np.int32)
    n = 0
    for i, j in np.argwhere(mask):
        if lab[i, j]:
            continue
        n += 1
        st = [(i, j)]
        lab[i, j] = n
        while st:
            a, b = st.pop()
            for da, db in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                x, y = a + da, b + db
                if 0 <= x < mask.shape[0] and 0 <= y < mask.shape[1] and mask[x, y] and not lab[x, y]:
                    lab[x, y] = n
                    st.append((x, y))
    return lab, n


def _fill_holes(mask):
    lab, n = _components(~np.pad(mask, 1))
    outside = lab[0, 0]
    filled = np.pad(mask, 1) | (lab != outside)
    return filled[1:-1, 1:-1]


def _trace(mask):
    """Boundary cells of the single filled region in mask, in order (Moore neighbour tracing)."""
    pad = np.pad(mask, 1)
    pts = np.argwhere(pad)
    if not len(pts):
        return []
    start = (int(pts[0][0]), int(pts[0][1]))
    dirs = [(0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1), (-1, 0), (-1, 1)]
    out, cur, d = [start], start, 6
    for _ in range(pad.size):
        for k in range(8):
            nd = (d + 5 + k) % 8
            r, c = cur[0] + dirs[nd][0], cur[1] + dirs[nd][1]
            if pad[r, c]:
                cur, d = (r, c), nd
                break
        else:
            break
        if cur == start:
            break
        out.append(cur)
    return [(r - 1, c - 1) for r, c in out]


def _row_outline(mask):
    """Outline of a region that is one run of cells in every row of the second axis (a door panel
    below its sill, arch cutout included): first cells going up, last cells coming back down."""
    rows = [j for j in range(mask.shape[1]) if mask[:, j].any()]
    if not rows:
        return []
    front = [(int(np.argmax(mask[:, j])), j) for j in rows]
    back = [(int(mask.shape[0] - 1 - np.argmax(mask[::-1, j])), j) for j in rows]
    return front + back[::-1]


def _simplify(poly, tol):
    """Douglas-Peucker on a closed polyline of (i, j) cells."""
    if len(poly) < 4:
        return poly

    def dp(pts):
        a, b = np.array(pts[0], float), np.array(pts[-1], float)
        ab = b - a
        L = float(np.hypot(*ab))
        best, k = -1.0, 0
        for i in range(1, len(pts) - 1):
            q = np.array(pts[i], float) - a
            dist = abs(ab[0] * q[1] - ab[1] * q[0]) / L if L > 1e-9 else float(np.hypot(*q))
            if dist > best:
                best, k = dist, i
        if best > tol:
            return dp(pts[:k + 1])[:-1] + dp(pts[k:])
        return [pts[0], pts[-1]]
    far = max(range(len(poly)), key=lambda i: (poly[i][0] - poly[0][0]) ** 2 + (poly[i][1] - poly[0][1]) ** 2)
    first = dp(poly[:far + 1])
    second = dp(poly[far:] + [poly[0]])
    return first[:-1] + second[:-1]


PLATE_INSET = 0.040           # the door card sits this far inside the door skin (a slim, real door:
                              # at kotris's card depth, ~9 cm, the open door read as a thick box)
PLATE_MARGIN = 1              # cells (1 cm) inside the door's outline: the strip outside it shows painted door edge
PLATE_SIMPLIFY = 0.8          # cells: Douglas-Peucker tolerance of the traced outline
# Jogs in the traced outline (2026-10-17 review OPEN-8, "two light-grey blocks low on each front door's rear
# edge"): where the door's rear edge steps 1-2 cm along y over a rise of a cell or two (the lower cladding stands
# 2 cm proud of the skin's edge at z 0.43, 1 cm more at 0.57), the painted edge band ran out along y for the
# step, an up-facing quad lit like a top: door_fr band faces at z 0.425-0.449 and 0.565-0.579. The outline is the
# door's true one (moving its corners uncovered the skin's back or ran the band past the door's edge: +4..+6 leak
# px in the open views), so only the shading changes: a short band quad facing up or down more than JOG_NZ takes
# the horizontal part of its own normal and lights like the band either side of it. The long top and bottom runs
# (over JOG_LEN) keep theirs.
JOG_NZ, JOG_LEN = 0.45, 0.06


def _jog_normal(poly, me):
    """The shading normal of an edge-band quad: its own, or for a jog its horizontal part."""
    n = poly.normal
    if abs(n.z) <= JOG_NZ or math.hypot(n.x, n.y) < 1e-6:
        return tuple(n)
    vs = [me.vertices[i].co for i in poly.vertices]
    if max((a - b).length for a in vs for b in vs) > JOG_LEN:
        return tuple(n)
    h = Vector((n.x, n.y, 0.0)).normalized()
    return tuple(h)


def _door_plate(name, report):
    """A clean trim panel on the inside of the door, below the window sill: the door's own outline
    (skin faces, raster) eroded 2 cm, traced, simplified to 1.5 cm and filled, each vertex 3.5 cm
    inside the skin. kotris's card was decimated into a sliver; the full-detail twin keeps it, so
    the bake projects its armrest, pull and speaker onto this plate."""
    ob = bpy.data.objects.get(name)
    if ob is None:
        return 0
    win_name, side = DOORS[name]
    win = bpy.data.objects.get(win_name)
    mask, lo = _outline(ob, (1, 2), mats=("Body", "Body_plastique"))
    sill = min((win.matrix_world @ v.co).z for v in win.data.vertices) if win else 1.10
    zs = lo[1] + (np.arange(mask.shape[1]) + 0.5) * CELL
    mask[:, zs > sill - 0.015] = False
    mask = _erode(_fill_holes(mask), PLATE_MARGIN)
    lab, n = _components(mask)
    if n == 0:
        return 0
    sizes = [(lab == k).sum() for k in range(1, n + 1)]
    mask = lab == (1 + int(np.argmax(sizes)))
    poly = _simplify(_row_outline(mask), PLATE_SIMPLIFY)
    if len(poly) < 3:
        return 0

    def skin_x(y, z):
        best = []
        for dy, dz in ((0, 0), (0.02, 0), (-0.02, 0), (0, 0.02), (0, -0.02)):
            hit, loc, _n, _i = ob.ray_cast(Vector((side * 1.5, y + dy, z + dz)), Vector((-side, 0.0, 0.0)))
            if hit:
                best.append(abs(loc.x))
        return min(best) if best else None
    pts = []
    for i, j in poly:
        y, z = lo[0] + (i + 0.5) * CELL, lo[1] + (j + 0.5) * CELL
        pts.append([y, z, skin_x(y, z)])
    known = [p[2] for p in pts if p[2] is not None]
    if not known:
        return 0
    for p in pts:
        if p[2] is None:
            p[2] = sum(known) / len(known)
    skins = [p[2] for p in pts]               # outer skin |x| at each outline point (the edge band)
    # depth: kotris's own card in the full-detail twin (the bake source), not the skin. A panel 3.5 cm
    # inside the skin lay ~8 cm outboard of the card: the bake rays missed the card and painted the
    # back of the skin onto it (mirrored paint and cladding stripes: the "misaligned" door)
    hi = bpy.data.objects.get(name + "_hi")
    card = None
    if hi is not None:
        hn = [m.name if m else "?" for m in hi.data.materials]
        cv = [hi.matrix_world @ v.co for v in hi.data.vertices]
        cp = [list(q.vertices) for q in hi.data.polygons if hn[q.material_index] == "Interieur"]
        if cp:
            card = BVHTree.FromPolygons(cv, cp, all_triangles=False)
    depths = []
    for p in pts:
        d = None
        if card is not None:
            for dy, dz in ((0, 0), (0.03, 0), (-0.03, 0), (0, 0.03), (0, -0.03)):
                hit = card.ray_cast(Vector((side * 0.2, p[0] + dy, p[1] + dz)), Vector((side, 0.0, 0.0)), 1.0)
                if hit[0] is not None:
                    d = max(d or 0.0, abs(hit[0].x))          # the card's outboard face
        depths.append(d)
    # (the card is painted from the RD1 photos and baked flat, so it no longer has to sit on kotris's
    # card for the bake: it follows the skin at PLATE_INSET; depths kept for the report only)
    me = ob.data
    mi = _mat_index(me, "DoorCard_" + name, lambda: door_cards.material(name))   # painted from the RD1 photos
    bi = _mat_index(me, INNER_MAT, _inner_material)
    before = [tuple(c.vector) for c in me.corner_normals]
    n_old = len(me.polygons)
    bm = bmesh.new()
    bm.from_mesh(me)
    gl = _gen_layer(bm)                       # before any element is made (a new layer invalidates them)
    vs = [bm.verts.new((side * (x - PLATE_INSET), y, z)) for y, z, x in pts]
    try:
        f = bm.faces.new(vs)
    except ValueError:
        bm.free()
        return 0
    f.material_index = mi
    f.smooth = False
    f[gl] = 5                                 # baked flat from door_cards' painted texture
    bm.normal_update()
    if f.normal.x * side > 0:                 # face the cabin
        f.normal_flip()
    res = bmesh.ops.triangulate(bm, faces=[f], quad_method='BEAUTY', ngon_method='BEAUTY')
    k = len(res["faces"])
    # the door's edge: a painted band from the panel's outline out to the skin all round, as the
    # real door's inner frame. Without it the panel floated 8 cm inside the skin as a loose board
    # (feedback: "this is fixed?"). gen 5: baked flat (inner paint), never pruned.
    cy = sum(p[0] for p in pts) / len(pts)
    cz = sum(p[1] for p in pts) / len(pts)
    # the band's outer edge runs out to the skin's true outline (the panel is PLATE_MARGIN cells
    # inside it): a 1 cm strip of skin left between them showed its back across the cabin
    area2 = sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts)))
    sgn = 1.0 if area2 > 0 else -1.0             # counter-clockwise in (y, z): outward = right of the edge
    outer = []
    for i, (p, sx) in enumerate(zip(pts, skins)):
        a, b = pts[i - 1], pts[(i + 1) % len(pts)]
        ny, nz = 0.0, 0.0
        for (y0_, z0_), (y1_, z1_) in (((a[0], a[1]), (p[0], p[1])), ((p[0], p[1]), (b[0], b[1]))):
            ey, ez = y1_ - y0_, z1_ - z0_
            L = math.hypot(ey, ez) or 1.0
            ny += sgn * ez / L
            nz += -sgn * ey / L
        L = math.hypot(ny, nz) or 1.0
        oy, oz = p[0] + ny / L * CELL * PLATE_MARGIN, p[1] + nz / L * CELL * PLATE_MARGIN
        ox = skin_x(oy, oz) or sx
        outer.append(bm.verts.new((side * (ox - 0.004), oy, oz)))
    band = 0
    for i in range(len(vs)):
        j = (i + 1) % len(vs)
        try:
            q = bm.faces.new((vs[i], vs[j], outer[j], outer[i]))
        except ValueError:
            continue
        q.material_index = bi
        q.smooth = False
        q[gl] = 5
        q.normal_update()
        mid = (pts[i][0] + pts[j][0]) / 2 - cy, (pts[i][1] + pts[j][1]) / 2 - cz
        if q.normal.y * mid[0] + q.normal.z * mid[1] < 0:          # face away from the panel's middle
            q.normal_flip()
        band += 2
    # the card's surface as a plane |x| = a*y + b*z + c (its corners sit at the original card's
    # depth), then the raised armrest and pocket lip on it, and the painted texture
    A = np.array([[p[0], p[1], 1.0] for p in pts])
    xs = np.array([p[2] - PLATE_INSET for p in pts])
    coef = np.linalg.lstsq(A, xs, rcond=None)[0]

    def plane(y, z):
        return float(coef[0] * y + coef[1] * z + coef[2])
    bbox = (min(p[0] for p in pts), max(p[0] for p in pts), min(p[1] for p in pts), max(p[1] for p in pts))
    relief = door_cards.relief(bm, gl, mi, name, bbox, plane, side)
    bm.to_mesh(me)
    bm.free()
    ob["card_bbox"] = list(bbox)
    door_cards.paint(name, bbox)
    # one normal for the whole panel: its corners follow the skin's curve, so its triangles are not
    # coplanar and flat shading lit each one differently (diagonal bands on the open door)
    n_avg = Vector()
    for poly in me.polygons[n_old:]:
        if poly.material_index == mi:
            n_avg += poly.normal * poly.area
    n_avg = n_avg.normalized() if n_avg.length > 1e-9 else Vector((-side, 0.0, 0.0))
    normals = list(before) + [None] * (len(me.loops) - len(before))
    for poly in me.polygons[n_old:]:
        flat = poly.material_index == mi and poly.normal.dot(n_avg) > 0.97     # the panel (and the
        nrm = tuple(n_avg) if flat else tuple(poly.normal)                    # armrest's front)
        jog = False
        if poly.material_index == bi:                                         # the edge band: jogs shade level
            nrm = _jog_normal(poly, me)
            jog = nrm != tuple(poly.normal)
        poly.use_smooth = flat or jog
        for li in poly.loop_indices:
            normals[li] = nrm
    if len(normals) == len(me.loops) and all(n is not None for n in normals):
        me.normals_split_custom_set(normals)
    report("  %-10s door card: %d outline points, %d tris, edge band %d, armrest + pocket %d, sill z %.2f"
           % (name, len(pts), k, band, relief, sill))
    return k


GATE_INSET = 0.035            # the tailgate's trim panel sits this far inside the gate skin
# Round 3 (R2-OC-7 remainder, the gate's swing, S\review2_opencab\collide2.py; ext3 sweep of the gate through 0-105 deg
# about its hinge with the glass on GLASS_ON_GATE). The card was a near-flat 8-point panel: its traced outline's
# corners sit GATE_INSET inside the skin where the skin curves forward, so the middle of its top edge hung 10 cm in
# front of the skin, right under the lifting glass's seam ring (trunk_top's SeamBack ring reaches down to z 1.149), and
# its bottom corner (0.574, -2.055, 0.743) stood in front of the bay walls' cargo riser (bay_walls: |x| <= 0.575,
# y -2.056..-2.059, top z 0.761) and the cargo closure beside the hinge (interior, y -2.019, x 0.565-0.690, z up to
# 0.87): the opening gate swept its card through all three at 0.5-4 deg. The card now spans GATE_CARD_Z only (its band
# still runs out to the traced outline, so the gate's inside stays closed), each corner GATE_INSET inside the skin,
# down to GATE_INSET_LOW at the bottom (GATE_INSET_Z ramp) so the bottom corners keep behind the riser and closure.
GATE_CARD_Z = (0.78, 1.135)
GATE_INSET_LOW = 0.012
GATE_INSET_Z = (0.82, 0.92)
GATE_CARD_STEP = 0.10         # metres between the traced outline's samples (card corners and band)
# Round 4 (seams4): with the card's top held at GATE_CARD_Z[1] the band along the gate's top edge no longer stands as a
# cap facing up (the card's old top edge at the outline, GATE_INSET in); it slants from the card's top up to the skin's
# edge, facing the cabin. Over the open gate's top edge the game camera meets that slant from behind, culled: an 8 x 1 px
# ground line along the edge in pzview open_045 (~(270, 301)). Every band quad with an end on the outline within this
# of GATE_CARD_Z[1] or above it also gets its back (a coincident reversed copy, BodyInner): nothing moves, so the
# swing's clearance (collide2: 0 gate / glass contacts) stays as it is.
GATE_TOP_BACKS = 0.005


def _gate_inset(z):
    t = max(0.0, min(1.0, (z - GATE_INSET_Z[0]) / (GATE_INSET_Z[1] - GATE_INSET_Z[0])))
    return GATE_INSET_LOW + (GATE_INSET - GATE_INSET_LOW) * t


def _gate_skin_ray(ob):
    """skin_y(x, z): the gate's outer skin as a ray from behind meets it (the most rearward of five rays 2 cm apart),
    on its gen 0 paint faces only: the spare, its carrier and the generated faces are not the skin."""
    me = ob.data
    names = [m.name if m else "?" for m in me.materials]
    ga = me.attributes.get(GEN)
    gv = [0] * len(me.polygons)
    if ga is not None:
        ga.data.foreach_get("value", gv)
    M = ob.matrix_world
    skin = BVHTree.FromPolygons([M @ v.co for v in me.vertices],
                                [list(p.vertices) for p in me.polygons
                                 if gv[p.index] == 0 and names[p.material_index] in ("Body", "Body_plastique")],
                                all_triangles=False)

    def skin_y(x, z):
        best = []
        for dx, dz in ((0, 0), (0.02, 0), (-0.02, 0), (0, 0.02), (0, -0.02)):
            hit = skin.ray_cast(Vector((x + dx, -4.0, z + dz)), Vector((0.0, 1.0, 0.0)), 4.0)
            if hit[0] is not None:
                best.append(hit[0].y)
        return min(best) if best else None
    return skin_y


def _gate_card_points(ob, pts):
    """The card's corners for the traced outline pts ([x, z, skin y]): z held inside GATE_CARD_Z, y from the gate's
    own skin (_gate_skin_ray) at that height plus _gate_inset; a corner the clamp put within 5 mm of the last one is
    dropped. Returns (corners, indices into pts kept)."""
    skin_y = _gate_skin_ray(ob)
    card = []
    for x, z, y in pts:
        zc = min(max(z, GATE_CARD_Z[0]), GATE_CARD_Z[1])
        sy = skin_y(x, zc)
        card.append((x, (sy if sy is not None else y) + _gate_inset(zc), zc))
    keep = []                                            # (collinear corners are fine: BEAUTY never fills them flat)
    for i, c in enumerate(card):
        if keep and math.hypot(c[0] - card[keep[-1]][0], c[2] - card[keep[-1]][2]) < 0.005:
            continue
        keep.append(i)
    if len(keep) > 3 and math.hypot(card[keep[0]][0] - card[keep[-1]][0], card[keep[0]][2] - card[keep[-1]][2]) < 0.005:
        keep.pop()
    return [card[i] for i in keep], keep


def _gate_plate(report):
    """A flat trim panel on the inside of the side-hinged tailgate: the doors' card done in the
    gate's x/z plane. The gate's outline seen from behind (skin faces, raster), eroded, traced and
    filled, each vertex GATE_INSET inside the skin, with a painted band from the panel's edge out to
    the skin. The solidified skin alone copied the wheel-carrier hole and the plate recess, so the
    open gate showed the spare tyre through its own inside (first in-game look, 2026-10-11)."""
    ob = bpy.data.objects.get("trunk")
    if ob is None:
        return 0
    mask, lo = _outline(ob, (0, 2), mats=("Body", "Body_plastique"))
    mask = _erode(_fill_holes(mask), PLATE_MARGIN)
    lab, n = _components(mask)
    if n == 0:
        return 0
    sizes = [(lab == k).sum() for k in range(1, n + 1)]
    mask = lab == (1 + int(np.argmax(sizes)))
    poly = _simplify(_row_outline(mask), 0.8)
    if len(poly) < 3:
        return 0
    # the outer skin: first thing a ray from behind meets (its paint faces only: the outline is now sampled along
    # the top and bottom edges too, where a ray could meet the spare)
    skin_y = _gate_skin_ray(ob)
    pts = []
    corners = [(lo[0] + (i + 0.5) * CELL, lo[1] + (j + 0.5) * CELL) for i, j in poly]
    for k, (x, z) in enumerate(corners):         # every GATE_CARD_STEP along the outline, so the card and its band
        x1, z1 = corners[(k + 1) % len(corners)]  # follow the skin's curve (an 8-corner card hung 10 cm in front of it)
        m = max(1, int(math.ceil(math.hypot(x1 - x, z1 - z) / GATE_CARD_STEP)))
        for s in range(m):
            px, pz = x + (x1 - x) * s / m, z + (z1 - z) * s / m
            pts.append([px, pz, skin_y(px, pz)])
    known = [p[2] for p in pts if p[2] is not None]
    if not known:
        return 0
    for p in pts:
        if p[2] is None:
            p[2] = sum(known) / len(known)
    card, keep = _gate_card_points(ob, pts)          # the card's own corners (GATE_CARD_Z); the band keeps the outline
    n_traced = len(pts)
    pts = [pts[i] for i in keep]
    me = ob.data
    mi = _mat_index(me, "DoorCard_trunk", lambda: door_cards.material("trunk"))
    bi = _mat_index(me, INNER_MAT, _inner_material)
    before = [tuple(c.vector) for c in me.corner_normals]
    n_old = len(me.polygons)
    bm = bmesh.new()
    bm.from_mesh(me)
    gl = _gen_layer(bm)
    vs = [bm.verts.new(c) for c in card]
    try:
        f = bm.faces.new(vs)
    except ValueError:
        bm.free()
        return 0
    f.material_index = mi
    f.smooth = False
    f[gl] = 5
    bm.normal_update()
    if f.normal.y < 0:                        # face the cabin (+y)
        f.normal_flip()
    res = bmesh.ops.triangulate(bm, faces=[f], quad_method='BEAUTY', ngon_method='BEAUTY')
    k = len(res["faces"])
    cx = sum(p[0] for p in pts) / len(pts)
    cz = sum(p[1] for p in pts) / len(pts)
    area2 = sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts)))
    sgn = 1.0 if area2 > 0 else -1.0
    outer = []
    for i, p in enumerate(pts):
        a, b = pts[i - 1], pts[(i + 1) % len(pts)]
        nx, nz = 0.0, 0.0
        for (x0_, z0_), (x1_, z1_) in (((a[0], a[1]), (p[0], p[1])), ((p[0], p[1]), (b[0], b[1]))):
            ex, ez = x1_ - x0_, z1_ - z0_
            L = math.hypot(ex, ez) or 1.0
            nx += sgn * ez / L
            nz += -sgn * ex / L
        L = math.hypot(nx, nz) or 1.0
        ox, oz = p[0] + nx / L * CELL * PLATE_MARGIN, p[1] + nz / L * CELL * PLATE_MARGIN
        oy = skin_y(ox, oz)
        oy = (oy if oy is not None else p[2]) + 0.004
        outer.append(bm.verts.new((ox, oy, oz)))
    # where GATE_CARD_Z lifted a corner off the bottom of the outline, the band starts at the traced corner itself
    # (_gate_inset deep there), and a strip of band runs up from it to the card: banded straight from the lifted
    # corner to the outline, the quads twisted and turned their faces away from the side gaps at the gate's lower
    # corners, which then showed the cargo closures behind (pzview's cabin pass, close_wheel_rear_*)
    inner = []
    for p, v in zip(pts, vs):
        if p[1] < GATE_CARD_Z[0]:
            sy = skin_y(p[0], p[1])
            inner.append(bm.verts.new((p[0], (sy if sy is not None else p[2]) + _gate_inset(p[1]), p[1])))
        else:
            inner.append(v)
    band = 0
    top_band = []                                  # the band quads along the lowered top edge (GATE_TOP_BACKS)
    for i in range(len(vs)):
        j = (i + 1) % len(vs)
        strip = [w for k, w in enumerate((vs[i], vs[j], inner[j], inner[i])) if k < 2 or w not in (vs[i], vs[j])]
        if len(strip) >= 3:
            try:
                q = bm.faces.new(strip)
            except ValueError:
                q = None
            if q is not None:
                q.material_index = bi
                q.smooth = False
                q[gl] = 5
                q.normal_update()
                if q.normal.y < 0:                      # faces the cabin, as the card
                    q.normal_flip()
                band += len(strip) - 2
        try:
            q = bm.faces.new((inner[i], inner[j], outer[j], outer[i]))
        except ValueError:
            continue
        q.material_index = bi
        q.smooth = False
        q[gl] = 5
        q.normal_update()
        mid = (pts[i][0] + pts[j][0]) / 2 - cx, (pts[i][1] + pts[j][1]) / 2 - cz
        if q.normal.x * mid[0] + q.normal.z * mid[1] < 0:        # face away from the panel's middle
            q.normal_flip()
        band += 2
        if pts[i][1] > GATE_CARD_Z[1] - GATE_TOP_BACKS or pts[j][1] > GATE_CARD_Z[1] - GATE_TOP_BACKS:
            top_band.append(q)
    n_top = 0
    if top_band:                                  # their backs, coincident copies (see GATE_TOP_BACKS)
        ret = bmesh.ops.duplicate(bm, geom=top_band)
        backs = [g for g in ret["geom"] if isinstance(g, bmesh.types.BMFace)]
        bmesh.ops.reverse_faces(bm, faces=backs)
        for q in backs:
            q.material_index = bi
            q.smooth = False
            q[gl] = 5
        n_top = len(backs)
        band += 2 * n_top
    bbox = (min(c[0] for c in card), max(c[0] for c in card), min(c[2] for c in card), max(c[2] for c in card))
    bm.to_mesh(me)
    bm.free()
    ob["card_bbox"] = list(bbox)
    ob["card_axis"] = "x"                     # bake_atlas maps the painted texture by x / z here
    door_cards.paint("trunk", bbox)
    n_avg = Vector()
    for pg in me.polygons[n_old:]:
        if pg.material_index == mi:
            n_avg += pg.normal * pg.area
    n_avg = n_avg.normalized() if n_avg.length > 1e-9 else Vector((0.0, 1.0, 0.0))
    normals = list(before) + [None] * (len(me.loops) - len(before))
    for pg in me.polygons[n_old:]:
        flat = pg.material_index == mi          # one normal over the whole card: it follows the gate's curve now
        nrm = tuple(n_avg) if flat else tuple(pg.normal)
        pg.use_smooth = flat
        for li in pg.loop_indices:
            normals[li] = nrm
    if len(normals) == len(me.loops) and all(n is not None for n in normals):
        me.normals_split_custom_set(normals)
    report("  %-10s gate card: %d outline points (%d sampled), %d tris, edge band %d (%d top-edge backs), card x %.2f..%.2f z %.2f..%.2f"
           % ("trunk", len(pts), n_traced, k, band, n_top, bbox[0], bbox[1], bbox[2], bbox[3]))
    return k


# the rocker between the rear door's rear edge and the front door's front edge. Rear end measured
# (2026-10-13, feedback: "rocker panel is too long, it extended to the rear wheel"): on MG 8767
# (perpendicular left side, hubs 826 px/m) the black sill ends flush with the rear arch flare at
# y -0.932, i.e. at the rear door's lower rear corner (the low door_rl's skin corner: y -0.929,
# z 0.372); the RD1 has no rocker across the wheel opening. -1.05 ran the wall 12 cm on past the
# door, a black flap across the gap and in front of the rear tyre (the tyre's front at y -0.98).
# The wall ends 1 cm behind that corner (within the photo's +-6 mm), so seen from the side the door's
# corner always has the wall behind it. (The old flap also hid a hairline along the door bottom's
# rear edge, (+-0.75, -0.928, 0.373): single pixels in a 1325 px/m close-up, +1 px over pzview's
# 57-view ring; covering it would take the wall back to y -1.0, the flap.)
# Front end unchanged: the photo's sill starts behind the mud flap at y +0.85, and 0.85..0.90 of the
# wall lies behind kotris's own flare plastic (body Body_plastique, |x| 0.846..0.878).
SILL_Y = (-0.94, 0.90)
SILL_STEP = 0.05              # metres between wall stations
SILL_Z = (0.33, 0.44)         # (25 cm read as an oversized rocker twice: the author 2026-10-12) the wall runs up behind the door lips (2.4 cm behind their plane) and alone covers the
                              # lip-less door ends and the B-pillar gap. 25 cm = the RD1 rocker's bottom; a taller
                              # band read as an oversized rocker panel (feedback, 2026-10-12). The "feet through the
                              # floor" were the SEATED character placed too low, not a standing one: see gen_scripts
                              # Top = LIP_TOP (2026-10-13): 2 cm under the straight lips it left a notch at the
                              # B-pillar gap, and from behind the 30-degree camera saw over it, between lip and
                              # cladding, onto the cabin's sill trim (|x| 0.820, flush with the door cladding)


# The rear end of the rocker (2026-10-17 review WHL-9): the sill wall (to y -0.94) and the rear doors' lips (to
# -0.92) ended square in front of the rear arch, a dark block with a lit end standing into the wheel opening; the
# RD1's rocker trim tapers up into the arch flare. Behind SILL_TAPER[0] both bottoms rise along one line, to
# SILL_TAPER[2] at y SILL_TAPER[1] (the lip's rear end; the door skin's own corner at the arch is y -0.94, z 0.45).
SILL_TAPER = (-0.86, -0.92, 0.428)


# The door apertures' shut faces (2026-10-17 review OPEN-2, from the textures team): the hinge pillar's face behind
# each front door, the B-pillar's fore and aft faces and the C-pillar's face behind each rear door are kotris
# Interieur, on the interior sheet that all eight paints share, so they could never be body colour; on the RD1 they
# are painted. The interior keeps them (moving them would open cracks wherever the interior's free outline
# drifts in its decimation); a painted copy (BodyInner, the opening panels' inner paint, gen 5: baked flat, never
# pruned) goes on the body APERTURE_LIFT in front of each, along its normal. Faces of the low interior facing along
# y (|n.y| > APERTURE_NY) in these |y| bands, at |x| 0.60-0.80 and z 0.45-1.50; the dash's end caps (y 0.51-0.55)
# and the trims facing into the cabin stay dark.
APERTURE_Y = ((0.80, 0.89), (-0.37, -0.17), (-1.09, -0.98))
APERTURE_NY = 0.75
APERTURE_LIFT = 0.0015
# Round 2 (2026-10-17 review R2-OC-1, a regression of the above): the copies lie on the interior's pillar faces, and
# most of those faces stand INBOARD of the shut doors' inner skin, i.e. in the cabin: the B-pillars' fore faces above the
# belt (|x| 0.55-0.77), the C-pillars' faces behind the rear doors and the kick panels' rear faces by the front footwells
# (|x| 0.61-0.69, the "hinge pillar" picks). From the seats they read as a ~10 cm blue stripe down each B-pillar, a strip
# on each C-pillar and a blue panel by the passenger's feet (S\review2_opencab\eye\shut_driver_back.png). Each copy is
# now split where the seat and cargo eyes (backfill.eye_points(), doors and gate shut) stop seeing it, front or back:
# painted from APERTURE_MARGIN past the outermost sample (every APERTURE_SAMPLE) an eye still reaches, re-checked on the
# painted part at half that spacing; the part the eyes see stays a copy, on the interior in its trim material (gen 5,
# baked flat like the closures): dropped, the copies had also been closing slits (a first build saw the road past each
# B-pillar's interior face, culled, from a front door opened on the other side). Most copies are seen whole (36 of 40):
# the painted strips that survive lie just inside the door gaps and only show with a door open.
APERTURE_SAMPLE = 0.01
APERTURE_MARGIN = 0.004
# What the eye test looks through: glass (the frit band, Vitre_noir, is opaque); and what can block a line of sight.
EYE_CLEAR = ("Vitre",)
EYE_OCCLUDERS = ("body", "hood", "door_fl", "door_fr", "door_rl", "door_rr", "window_fl", "window_fr", "window_rl",
                 "window_rr", "trunk", "trunk_top", "interior", "cabin")
EYE_TOL = 0.004               # a sight line that ends within this of its target reaches it (the copy's own face lies 1.5 mm off)


def _eye_points():
    """The seat and cargo eyes backfill casts from (metres above ground, the frame of this blend)."""
    try:
        import backfill
        return [Vector(p) for p in backfill.eye_points()]
    except Exception as exc:                     # noqa: BLE001
        print("  eye points: backfill.eye_points() failed (%s): stock seated eyes" % exc)
        return [Vector(p) for p in ((-0.38, 0.08, 1.46), (0.38, 0.08, 1.46), (-0.36, -0.70, 1.46), (0.36, -0.70, 1.46))]


def _eye_tree(skip=()):
    """BVH of everything that can block a seat eye's line of sight on the shut car (glass excluded)."""
    verts, polys = [], []
    for n in EYE_OCCLUDERS:
        ob = bpy.data.objects.get(n)
        if ob is None or ob.type != 'MESH' or n in skip:
            continue
        M = ob.matrix_world
        names = [m.name if m else "?" for m in ob.data.materials]
        base = len(verts)
        verts.extend(M @ v.co for v in ob.data.vertices)
        for p in ob.data.polygons:
            if p.material_index < len(names) and names[p.material_index] in EYE_CLEAR:
                continue
            polys.append([base + i for i in p.vertices])
    return BVHTree.FromPolygons(verts, polys, all_triangles=False)


def _seen(tree, eyes, q, tol=EYE_TOL):
    """True when some eye has a clear line of sight to point q (to within tol of it)."""
    for e in eyes:
        d = q - e
        L = d.length
        if L < 1e-6:
            return True
        if tree.ray_cast(e, d / L, max(0.0, L - tol))[0] is None:
            return True
    return False


def _tri_samples(a, b, c, step):
    """Points about `step` apart over triangle abc, its edges included (rows parallel to its longest edge)."""
    p, q, r = max(((a, b, c), (b, c, a), (c, a, b)), key=lambda t: (t[1] - t[0]).length)
    base = q - p
    L = base.length
    if L < 1e-9:
        return [a]
    u = base / L
    rx = (r - p).dot(u)
    hv = (r - p) - u * rx
    H = hv.length
    if H < 1e-6:
        return [p + u * (L * i / max(1, int(L / step))) for i in range(max(1, int(L / step)) + 1)]
    v = hv / H
    out = []
    nv = max(1, int(math.ceil(H / step)))
    for j in range(nv + 1):
        t = j / nv
        x0, x1 = rx * t, L + (rx - L) * t
        nu = max(1, int(math.ceil(abs(x1 - x0) / step)))
        for i in range(nu + 1):
            out.append(p + u * (x0 + (x1 - x0) * i / nu) + v * (H * t))
    return out


def _poly_samples(pts, step):
    out = []
    for i in range(1, len(pts) - 1):
        out.extend(_tri_samples(pts[0], pts[i], pts[i + 1], step))
    return out


def _clip_x(pts, side, x0):
    """The part of the planar polygon pts with side * x >= x0 (Sutherland-Hodgman)."""
    out = []
    n = len(pts)
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        ia, ib = side * a.x >= x0, side * b.x >= x0
        if ia:
            out.append(a)
        if ia != ib:
            t = (x0 - side * a.x) / (side * (b.x - a.x))
            out.append(a + (b - a) * t)
    return out


def _poly_area(pts):
    acc = Vector()
    for i in range(1, len(pts) - 1):
        acc += (pts[i] - pts[0]).cross(pts[i + 1] - pts[0])
    return acc.length / 2


def _unseen_part(pts, side, tree, eyes):
    """(painted, dark): pts split at an |x| outboard of which no eye sees it; either may be None."""
    seen = [s for s in _poly_samples(pts, APERTURE_SAMPLE) if _seen(tree, eyes, s)]
    if not seen:
        return pts, None
    x0 = max(side * s.x for s in seen) + APERTURE_MARGIN
    for _ in range(8):
        part = _clip_x(pts, side, x0)
        if len(part) < 3 or _poly_area(part) < 2e-6:
            return None, pts
        seen = [s for s in _poly_samples(part, APERTURE_SAMPLE / 2) if _seen(tree, eyes, s)]
        if not seen:
            dark = _clip_x(pts, -side, -x0)
            return part, (dark if len(dark) >= 3 and _poly_area(dark) >= 2e-6 else None)
        x0 = max(side * s.x for s in seen) + APERTURE_MARGIN
    return None, pts


# The front doors' hinge pillars (round 2, R2-OC-4 and the hinge half of R2-OC-1). kotris has no hinge pillar: between
# the kick panel's side (interior, |x| 0.70) and the fender skin (|x| ~0.86) the space ahead of each front door, y 0.80-
# 0.90, opens into the fender's upper cavity. With the gate open and the rear seats folded the eye at the cargo sill
# looked past the right front seat, along the door card, through that slot and out through the fender's culled back
# faces to the road (181 px, S\review2_opencab\crop_fold_leak.png); with a door open the slot showed the road too
# (540 px in an eye view onto the right hinge area, before). A wall facing rearward at y HINGE_Y (1.3 cm ahead of the
# doors' front ends, y <= 0.827 through their whole swing) from the kick panel out to HINGE_SKIN inside the fender skin,
# z HINGE_Z: painted (BodyInner) where no seat eye sees it (the hinge pillar seen with the door open), SeamBack where one
# does (the dark gap beside the dash end). Rows every HINGE_DZ, cells every HINGE_DX classed by 3 x 3 samples.
HINGE_Y = 0.840
HINGE_X_IN = 0.700
HINGE_SKIN = 0.002            # (8 mm left a slot at the fender's rear edge, seen across the cabin with a rear door open)
HINGE_Z = (0.39, 1.10)        # (from 0.46 the driver saw the road under the passenger-side wall, past the kick panel's foot)
HINGE_DZ = 0.04
HINGE_DX = 0.02


def _hinge_walls(bm, gl, mi_paint, mi_dark, tree, eyes, body_tree):
    """The two hinge-pillar walls into bm (see HINGE_*). Returns (painted tris, dark tris)."""
    made = [0, 0]

    def inside(x, z):
        """True when (x, HINGE_Y, z) lies under the body skin: something above it and something outboard of it."""
        p = Vector((x, HINGE_Y, z))
        return (body_tree.ray_cast(p, Vector((0.0, 0.0, 1.0)), 0.6)[0] is not None
                and body_tree.ray_cast(p, Vector((1.0 if x > 0 else -1.0, 0.0, 0.0)), 0.4)[0] is not None)
    for side in (-1, 1):
        z = HINGE_Z[0]
        while z < HINGE_Z[1] - 1e-6:
            z1 = min(z + HINGE_DZ, HINGE_Z[1])
            zm = (z + z1) / 2
            loc = body_tree.ray_cast(Vector((side * 1.6, HINGE_Y, zm)), Vector((-side, 0.0, 0.0)), 1.0)[0]
            x_out = min(abs(loc.x) - HINGE_SKIN, 0.86) if loc is not None else None
            if x_out is None or x_out < HINGE_X_IN + 0.01:
                z = z1
                continue
            cells = []
            x = HINGE_X_IN
            while x < x_out - 1e-6:
                xb = min(x + HINGE_DX, x_out)
                if not inside(side * (x + xb) / 2, zm):
                    cells.append(None)
                else:
                    pts = [Vector((side * (x + (xb - x) * i / 2), HINGE_Y, z + (z1 - z) * j / 2)) for i in range(3) for j in range(3)]
                    cells.append(1 if any(_seen(tree, eyes, q) for q in pts) else 0)
                x = xb
            # merge runs of one class into one quad
            xs = [HINGE_X_IN + HINGE_DX * i for i in range(len(cells))] + [x_out]
            i = 0
            while i < len(cells):
                j = i
                while j + 1 < len(cells) and cells[j + 1] == cells[i]:
                    j += 1
                if cells[i] is not None:
                    xa, xb = xs[i], xs[j + 1]
                    vs = [bm.verts.new((side * xa, HINGE_Y, z)), bm.verts.new((side * xb, HINGE_Y, z)),
                          bm.verts.new((side * xb, HINGE_Y, z1)), bm.verts.new((side * xa, HINGE_Y, z1))]
                    f = bm.faces.new(vs)
                    f.material_index = mi_dark if cells[i] else mi_paint
                    f.smooth = False
                    f[gl] = 5
                    f.normal_update()
                    if f.normal.y > 0:
                        f.normal_flip()                         # it faces the door opening (rearward)
                    made[1 if cells[i] else 0] += 2
                i = j + 1
            z = z1
    return made


def _aperture_paint(report):
    it = bpy.data.objects.get("interior")
    body = bpy.data.objects.get("body")
    if it is None or body is None:
        return 0
    ime = it.data
    inames = [m.name if m else "?" for m in ime.materials]
    picks = []
    for p in ime.polygons:
        c, n = p.center, p.normal
        if inames[p.material_index] != "Interieur" or abs(n.y) <= APERTURE_NY:
            continue
        if not (0.60 <= abs(c.x) <= 0.80 and 0.45 <= c.z <= 1.50 and any(a <= c.y <= b for a, b in APERTURE_Y)):
            continue
        picks.append(([ime.vertices[i].co + n * APERTURE_LIFT for i in p.vertices], 1 if c.x > 0 else -1))
    if not picks:
        report("  body       aperture paint: no shut faces found")
        return 0
    eyes = _eye_points()
    tree = _eye_tree()
    kept, darks, clipped, dropped = [], [], 0, 0
    for pts, side in picks:
        part, dark = _unseen_part(pts, side, tree, eyes)
        if part is None:
            dropped += 1
        elif dark is not None:
            clipped += 1
        if part is not None:
            kept.append(part)
        if dark is not None:
            darks.append(dark)
    me = body.data
    mi = _mat_index(me, INNER_MAT, _inner_material)
    md = _mat_index(me, "SeamBack", _seamback_material)
    bnames = [m.name if m else "?" for m in me.materials]
    body_tree = BVHTree.FromPolygons([v.co.copy() for v in me.vertices],
                                     [list(p.vertices) for p in me.polygons if bnames[p.material_index] not in PANE_MATS],
                                     all_triangles=False)
    before = [tuple(c.vector) for c in me.corner_normals]
    n_old = len(me.polygons)
    bm = bmesh.new()
    bm.from_mesh(me)
    gl = _gen_layer(bm)
    k = kd = 0
    for pts in kept:
        try:
            f = bm.faces.new([bm.verts.new(q) for q in pts])
        except ValueError:
            continue
        f.material_index = mi
        f.smooth = False
        f[gl] = 5
        k += len(pts) - 2
    walls = _hinge_walls(bm, gl, mi, md, tree, eyes, body_tree)
    bm.to_mesh(me)
    bm.free()
    me.update()
    normals = list(before) + [None] * (len(me.loops) - len(before))
    for pg in me.polygons[n_old:]:
        for li in pg.loop_indices:
            normals[li] = tuple(pg.normal)
    if len(normals) == len(me.loops) and all(v is not None for v in normals):
        me.normals_split_custom_set(normals)
    if darks:                                           # the seen parts: trim-coloured copies on the interior itself
        ti = _mat_index(ime, "Interieur")
        ibm = bmesh.new()
        ibm.from_mesh(ime)
        igl = _gen_layer(ibm)
        for pts in darks:
            try:
                f = ibm.faces.new([ibm.verts.new(q) for q in pts])
            except ValueError:
                continue
            f.material_index = ti
            f.smooth = False
            f[igl] = 5
            kd += len(pts) - 2
        ibm.to_mesh(ime)
        ibm.free()
        ime.update()
    report("  body       aperture paint: %d painted + %d trim (interior) tris on %d pillar shut faces of the interior (%d split at what the "
           "%d seat / cargo eyes see, %d seen whole: trim); hinge pillar walls %d painted + %d dark tris"
           % (k, kd, len(picks), clipped, len(eyes), dropped, walls[0], walls[1]))
    return k


def _taper_bottom(y, z):
    """The bottom z of the sill wall / door lip at y: z itself ahead of the taper, raised onto its line behind."""
    y0, y1, zt = SILL_TAPER
    if y >= y0:
        return z
    t = min(1.0, (y0 - y) / (y0 - y1))
    return max(z, SILL_Z[0] + (zt - SILL_Z[0]) * t)


def _sill_strips(report):
    """A black sill (rocker) wall on the body under each pair of doors. kotris's body has NO rocker:
    its side skin stops at the door bottoms (z ~0.40) and below that only the underbody exists,
    15-30 cm further in. Through the 1-3 cm slit between a door's bottom and nothing the 30-degree
    camera saw the cabin's sill trim (dark, so pzview's ground test never counted it) and, in game,
    a character standing against the car showed a foot through it (feedback, 2026-10-11: "Foot still
    there"). The wall hangs 1.2 cm inside the DOOR skin from 27 cm up to behind the door bottoms,
    so it closes the slit and reads as the car's black sill below the doors. gen 5 (baked flat)."""
    ob = bpy.data.objects.get("body")
    if ob is None:
        return 0
    doors = [d for d in (bpy.data.objects.get(n) for n in ("door_fl", "door_fr", "door_rl", "door_rr")) if d is not None]
    me = ob.data
    mi = _mat_index(me, "Body_plastique")
    before = [tuple(c.vector) for c in me.corner_normals]
    n_old = len(me.polygons)
    bm = bmesh.new()
    bm.from_mesh(me)
    gl = _gen_layer(bm)
    n = 0
    # stations on the SILL_STEP grid (multiples of it, so a new end moves only the end: the wall's
    # x samples elsewhere stay where the cabin and leak checks were last run) plus both ends, each
    # once (the old list repeated SILL_Y[1] and made a zero-width quad at the front of each wall)
    k0, k1 = math.ceil(SILL_Y[0] / SILL_STEP - 1e-6), math.floor(SILL_Y[1] / SILL_STEP + 1e-6)
    grid = [round(k * SILL_STEP, 4) for k in range(k0, k1 + 1)]
    ys = [SILL_Y[0]] + [y for y in grid if SILL_Y[0] + 0.005 < y < SILL_Y[1] - 0.005] + [SILL_Y[1]]
    if SILL_TAPER[0] not in ys and SILL_Y[0] < SILL_TAPER[0] < SILL_Y[1]:
        ys = sorted(ys + [SILL_TAPER[0]])                # the taper starts on a station

    def skin_x(side, y):
        """|x| of the outer skin just above the door bottoms (door or body), the outermost hit: the
        wall must sit OUTSIDE the cabin's own sill trim (|x| 0.82, a part model the game does not
        let occlude a character) and only overlaps the door lips over 3 cm of height."""
        best = None
        for o in doors + [ob]:
            for z in (0.43, 0.46, 0.50):
                hit, loc, _nn, _i = o.ray_cast(Vector((side * 1.5, y, z)), Vector((-side, 0.0, 0.0)))
                if hit and abs(loc.x) > 0.74:
                    best = abs(loc.x) if best is None else max(best, abs(loc.x))
        return best
    for side in (-1, 1):
        xs = []
        for y in ys:
            sx = skin_x(side, y)
            xs.append(sx - 0.012 if sx is not None else None)
        known = [x for x in xs if x is not None]
        if not known:
            continue
        xs = [x if x is not None else sum(known) / len(known) for x in xs]
        prev = None
        for y, x in zip(ys, xs):
            lo_v = bm.verts.new((side * x, y, _taper_bottom(y, SILL_Z[0])))
            hi_v = bm.verts.new((side * x, y, SILL_Z[1]))
            if prev is not None:
                try:
                    f = bm.faces.new((prev[0], lo_v, hi_v, prev[1]))
                except ValueError:
                    prev = (lo_v, hi_v)
                    continue
                f.material_index = mi
                f.smooth = False
                f[gl] = 5
                f.normal_update()
                if f.normal.x * side < 0:
                    f.normal_flip()
                n += 2
            prev = (lo_v, hi_v)
    bm.to_mesh(me)
    bm.free()
    me.update()
    normals = list(before) + [None] * (len(me.loops) - len(before))
    for pg in me.polygons[n_old:]:
        for li in pg.loop_indices:
            normals[li] = tuple(pg.normal)
    if len(normals) == len(me.loops) and all(v is not None for v in normals):
        me.normals_split_custom_set(normals)
    report("  %-10s sill strips: %d tris, 1.2 cm inside the rocker skin, z %.2f..%.2f" % ("body", n, SILL_Z[0], SILL_Z[1]))
    return n


LIP_Z = 0.345                 # the doors' lower lip reaches 2.5 cm below the lowest door bottom (0.37), enough to
                              # cover the slit at the 30-degree camera; the sill wall carries on 1.5 cm below
LIP_TOP = 0.44                # (round 2 had 0.46; back to 0.44 2026-10-13: the author found the band too tall twice, and
                              # 0.46 made it 13 cm; the ledge it hid is darkened in paint_pass, OVERHANG_DARK)
                              # and up to here: ONE straight top edge per door (see _door_lips). The door's
                              # lower cladding ends in an up-facing bevel and ledge at z 0.435-0.440, 2.2-3.2 cm
                              # inboard of the lip; a 30-degree camera ray that just clears the lip top drops
                              # tan 30 x 3.2 cm = 1.8 cm before it gets there, so at 0.44 the whole ledge showed
                              # above the lip as a light line along every door (lit as a top face); from 0.459
                              # the ray meets the door skin's own bottom edge (0.443) first
LIP_STEP = 0.03               # metres between lip stations along the door
LIP_TOL = 0.0015              # a station is dropped where the lip runs within this of the straight line past it


def _door_bottom(edges, y):
    """Lowest z of a door's outer skin in the plane at this y: the section of its gen-0 Body /
    Body_plastique faces (edges: (E, 2, 3) array), outer points only (|x| > 0.74). The door's true
    bottom edge, 0.370-0.373 m along the whole of every door."""
    a, b = edges[:, 0], edges[:, 1]
    da, db = a[:, 1] - y, b[:, 1] - y
    cut = (da < 0) != (db < 0)
    if not cut.any():
        return None
    t = da[cut] / (da[cut] - db[cut])
    q = a[cut] + (b[cut] - a[cut]) * t[:, None]
    q = q[np.abs(q[:, 0]) > 0.74]
    return float(q[:, 2].min()) if len(q) else None


def _lip_stations(samples):
    """The stations a straight lip needs: both ends and every station where the skin's x bends away
    from the straight line between its kept neighbours by more than LIP_TOL (Douglas-Peucker on
    (y, x)). A single station whose x stands out of both neighbours (a lone proud vertex the ray at
    z 0.48 hit: door_fl y 0.255, 1.2 cm) takes their mean first: the lip is a straight cladding."""
    s = [list(p) for p in samples]
    for i in range(1, len(s) - 1):
        lo, hi = sorted((s[i - 1][1], s[i + 1][1]))
        if s[i][1] > hi + LIP_TOL or s[i][1] < lo - LIP_TOL:
            s[i][1] = (s[i - 1][1] + s[i + 1][1]) / 2
    keep = {0, len(s) - 1}

    def dp(i0, i1):
        if i1 - i0 < 2:
            return
        (ya, xa), (yb, xb) = s[i0][:2], s[i1][:2]
        best, bi = 0.0, None
        for i in range(i0 + 1, i1):
            x = xa + (xb - xa) * (s[i][0] - ya) / ((yb - ya) or 1.0)
            if abs(s[i][1] - x) > best:
                best, bi = abs(s[i][1] - x), i
        if bi is not None and best > LIP_TOL:
            keep.add(bi)
            dp(i0, bi)
            dp(bi, i1)
    dp(0, len(s) - 1)
    return [tuple(s[i]) for i in sorted(keep)]


def _door_lips(report):
    """Extend each door's skin straight down from its bottom edge to LIP_Z, in the skin's own plane
    (black cladding). kotris's doors end 40-46 cm up and the body has no rocker, so between a door's
    bottom and nothing the camera saw the cabin's sill trim, flush with the door skin at |x| 0.82:
    the body wall of _sill_strips alone would sit BEHIND that trim. The lip closes the slit from
    the outside, as the real door does, and swings with the door. gen 5 (baked flat).

    One straight top per door (2026-10-13, screenshot 23.png: the lip's top rose in triangular peaks to
    0.49 m and showed the cladding ledge in the notches between them). The top used to be
    max(LIP_TOP, zb + 0.03) per 3 cm station, zb the lowest door VERTEX within 2.5 cm: on the
    decimated door the cladding's bottom edge has a vertex only every 20-30 cm, so between them zb
    was the skin's undercurl (0.41-0.46) and the top peaked. The door's real bottom, the section of
    its skin at each station (_door_bottom), is 0.370-0.373 m from end to end (0.44 only in the last
    2 cm before a door's edge, where the section meets the edge's rounding), so the top is one value
    per door, max(LIP_TOP, median bottom + 0.03): LIP_TOP on all four, 9 cm over the door bottom, so
    the slit stays closed, and high enough that the cladding ledge behind it never shows (LIP_TOP).
    Every station whose bottom is a door bottom counts, and the lip keeps only the stations its
    straight run needs (_lip_stations)."""
    total = 0
    for name in ("door_fl", "door_fr", "door_rl", "door_rr"):
        ob = bpy.data.objects.get(name)
        if ob is None:
            continue
        side = -1 if name.endswith("l") else 1
        me = ob.data
        names = [m.name if m else "?" for m in me.materials]
        skin = {i for i, m in enumerate(names) if m in ("Body", "Body_plastique")}
        ga = me.attributes.get(GEN)
        gv = [0] * len(me.polygons)
        if ga is not None:
            ga.data.foreach_get("value", gv)
        polys = [p for p in me.polygons if p.material_index in skin and gv[p.index] == 0]
        outer = [me.vertices[i].co for p in polys for i in p.vertices]
        outer = [v for v in outer if abs(v.x) > 0.74]
        if not outer:
            continue
        edges = np.array([(tuple(me.vertices[p.vertices[i]].co), tuple(me.vertices[p.vertices[(i + 1) % len(p.vertices)]].co))
                          for p in polys for i in range(len(p.vertices))], dtype=np.float64)
        y0, y1 = min(v.y for v in outer) + 0.01, max(v.y for v in outer) - 0.01
        samples = []
        y = y0
        while y <= y1 + 1e-6:
            zb = _door_bottom(edges, y)
            hit, loc, _nn, _i = ob.ray_cast(Vector((side * 1.5, y, 0.48)), Vector((-side, 0.0, 0.0)))
            sx = abs(loc.x) if hit and abs(loc.x) > 0.74 else None
            if zb is not None and sx is not None and LIP_Z + 0.02 < zb < 0.60:      # a door BOTTOM, not a window frame at the door's ends
                samples.append((y, sx, zb))
            y += LIP_STEP
        if len(samples) < 2:
            continue
        lip_top = max(LIP_TOP, float(np.median([s[2] for s in samples])) + 0.03)
        stations = _lip_stations(samples)
        if stations[0][0] < SILL_TAPER[0] - 0.005 < stations[1][0]:        # a station where the rear taper starts
            (ya, xa, za), (yb, xb, zb_) = stations[0], stations[1]
            t = (SILL_TAPER[0] - ya) / (yb - ya)
            stations.insert(1, (SILL_TAPER[0], xa + (xb - xa) * t, za + (zb_ - za) * t))
        mi = _mat_index(me, "Body_plastique")
        before = [tuple(c.vector) for c in me.corner_normals]
        n_old = len(me.polygons)
        bm = bmesh.new()
        bm.from_mesh(me)
        gl = _gen_layer(bm)
        prev = None
        k = 0
        for y, sx, zb in stations:
            # 1.2 cm proud of the skin: the cabin's sill trim sits flush with the door skin at the
            # B-pillar end, and the lip has to be the nearer surface (a door, not a part model)
            top = bm.verts.new((side * (sx + 0.012), y, lip_top))
            bot = bm.verts.new((side * (sx + 0.008), y, min(_taper_bottom(y, LIP_Z), lip_top - 0.01)))
            if prev is not None:
                try:
                    f = bm.faces.new((prev[0], top, bot, prev[1]))
                except ValueError:
                    prev = (top, bot)
                    continue
                f.material_index = mi
                f.smooth = False
                f[gl] = 5
                f.normal_update()
                if f.normal.x * side < 0:
                    f.normal_flip()
                k += 2
            prev = (top, bot)
        bm.to_mesh(me)
        bm.free()
        me.update()
        normals = list(before) + [None] * (len(me.loops) - len(before))
        for pg in me.polygons[n_old:]:
            for li in pg.loop_indices:
                normals[li] = tuple(pg.normal)
        if len(normals) == len(me.loops) and all(v is not None for v in normals):
            me.normals_split_custom_set(normals)
        total += k
        report("  %-10s door lip: %d tris, %d stations, y %.2f..%.2f, door bottom %.3f..%.3f, lip z %.3f..%.3f"
               % (name, k, len(stations), samples[0][0], samples[-1][0], min(s[2] for s in samples),
                  max(s[2] for s in samples), LIP_Z, lip_top))
    return total


# Sail backing (round 3, R2-VP-5 remainder). The black sail at each front door's window corner (kotris: a shell with
# the mirror on it) is open on both long sides after decimation: a 0.2-2.5 cm wedge between its front edge and the frame
# skin's rear edge (door_fr: sail face 386 against skin faces 220 / 98 / 219 / 218, x 0.73-0.80, y 0.53-0.67, z 1.08-1.26)
# and a crack where its rear wall meets the glass's front edge at (0.741, 0.520, 1.210). From a crouch or eye level 1.3 m
# off either front quarter the rays went straight through both, no face culled on the way, onto the A-pillar trim's
# foot (interior faces at x 0.69-0.72) and the dash end: 150-670 px clusters in 22-degree views of each mirror foot.
# A black plate (gen 7, the sail's Plastique_noir) now closes the sail on its cabin side: a ruled surface between the
# skin's open rear edge (SAIL_K_BOX) and the glass's front edge, SAIL_IN inboard of them, SAIL_OVER past the skin's
# edge under the skin and starting SAIL_GLASS_GAP forward of the glass edge. The window slides straight down
# (rig_vehicle, slide_z), so its front edge only ever moves rearward and inboard of where it sits shut: nothing on the
# window (glass or its ring, >= 6 mm inboard) reaches the plate. Faces outboard; from the seats it is the sail's
# black inner cover.
# |x|, y, z of the skin's open rear edge round the sail (door_fl's stays open on up to (-0.704, 0.450, 1.336) above the
# sail's top, door_fr's closes at z 1.26: the first build of round 3 left 50-160 px at the left sail's top) ...
SAIL_K_BOX = ((0.69, 0.805), (0.44, 0.665), (1.065, 1.345))
SAIL_G_BOX = ((0.69, 0.78), (0.42, 0.56), (1.08, 1.345))       # ... and of the glass's front edge
SAIL_IN = 0.004
SAIL_OVER = 0.003
# up the sail's front edge (skin edge above SAIL_FRONT_Z) the frame skin runs on 4-5 cm forward of its edge, and a 3 mm
# overlap 4 mm under it let grazing rays through between the two (20 px at z 1.26, 8 px at z 1.19 from 1.3 m off the
# right front quarter, third build of round 3); along the belt the skin turns down, so the plate stops 3 mm under it
SAIL_OVER_FRONT = 0.012
SAIL_FRONT_Z = 1.12
SAIL_GLASS_GAP = 0.001
SAIL_STATIONS = 16


def _open_chain(ob, mats, box, s):
    """The longest chain of open edges (position-keyed, 0.1 mm) of `ob`'s faces in `mats` with both ends in box
    ((x0, x1) on |x| for side s, (y0, y1), (z0, z1)), as a list of points ordered from its higher end."""
    me = ob.data
    M = ob.matrix_world
    names = [m.name if m else "?" for m in me.materials]
    cnt, pos = {}, {}
    mat_of = {}
    for p in me.polygons:
        vs = [M @ me.vertices[i].co for i in p.vertices]
        ks = [(round(v.x, 4), round(v.y, 4), round(v.z, 4)) for v in vs]
        for i in range(len(ks)):
            a, b = ks[i], ks[(i + 1) % len(ks)]
            if a == b:
                continue
            e = (a, b) if a < b else (b, a)
            cnt[e] = cnt.get(e, 0) + 1
            mat_of.setdefault(e, names[p.material_index])
            pos[a], pos[b] = vs[i], vs[(i + 1) % len(vs)]
    (x0, x1), (y0, y1), (z0, z1) = box

    def inb(k):
        return x0 <= s * k[0] <= x1 and y0 <= k[1] <= y1 and z0 <= k[2] <= z1
    opn = [e for e, c in cnt.items() if c == 1 and mat_of[e] in mats and inb(e[0]) and inb(e[1])]
    adj = {}
    for e in opn:
        adj.setdefault(e[0], []).append(e)
        adj.setdefault(e[1], []).append(e)
    used = set()
    best = []
    for e0 in opn:
        if e0 in used:
            continue
        used.add(e0)
        chain = [e0[0], e0[1]]
        for end in (0, 1):
            v = chain[0] if end == 0 else chain[-1]
            while True:
                nx = [e for e in adj.get(v, []) if e not in used]
                if not nx:
                    break
                used.add(nx[0])
                v = nx[0][1] if nx[0][0] == v else nx[0][0]
                if end == 0:
                    chain.insert(0, v)
                else:
                    chain.append(v)
        if len(chain) > len(best):
            best = chain
    pts = [pos[k].copy() for k in best]
    if pts and pts[0].z < pts[-1].z:
        pts.reverse()
    return pts


def _resample(pts, n):
    """n + 1 points at equal arc length along the polyline pts."""
    d = [0.0]
    for a, b in zip(pts, pts[1:]):
        d.append(d[-1] + (b - a).length)
    out = []
    j = 0
    for k in range(n + 1):
        t = d[-1] * k / n
        while j < len(d) - 2 and d[j + 1] < t:
            j += 1
        seg = d[j + 1] - d[j]
        f = (t - d[j]) / seg if seg > 1e-12 else 0.0
        out.append(pts[j].lerp(pts[j + 1], min(1.0, max(0.0, f))))
    return out


def _sail_backing(report):
    total = 0
    for door, window in (("door_fl", "window_fl"), ("door_fr", "window_fr")):
        ob, win = bpy.data.objects.get(door), bpy.data.objects.get(window)
        if ob is None or win is None:
            continue
        s = DOORS[door][1]
        K = _open_chain(ob, {"Body"}, SAIL_K_BOX, s)
        G = _open_chain(win, set(PANE_MATS), SAIL_G_BOX, s)
        if len(K) < 3 or len(G) < 2:
            report("  %-10s sail backing: no skin edge (%d points) or glass edge (%d points) found" % (door, len(K), len(G)))
            continue
        if K[0].z < G[0].z - 0.005:
            # the skin's edge closes below the glass edge's top (door_fr: z 1.26 against 1.333): the plate's top would
            # run on a slant from there to the glass's top and leave a slot under the frame skin (56 px from 1.3 m off
            # the right front quarter in the second build of round 3). Its top station is the glass edge's top moved
            # by the skin's offset from the glass where the skin's edge ends
            gk = G[-1]
            for a, b in zip(G, G[1:]):
                if b.z <= K[0].z <= a.z and a.z - b.z > 1e-9:
                    gk = a.lerp(b, (a.z - K[0].z) / (a.z - b.z))
                    break
            K.insert(0, G[0] + (K[0] - gk))
        n = SAIL_STATIONS
        k, g = _resample(K, n), _resample(G, n)
        # the plate's outward normal at each station: across (glass -> skin) x along the stations, turned outboard
        nrm = []
        for i in range(n + 1):
            along = (k[min(n, i + 1)] - k[max(0, i - 1)]) + (g[min(n, i + 1)] - g[max(0, i - 1)])
            nn = (k[i] - g[i]).cross(along)
            if nn.x * s < 0:
                nn = -nn
            nrm.append(nn.normalized() if nn.length > 1e-9 else Vector((s, 0.0, 0.0)))
        outer, inner = [], []
        for i in range(n + 1):
            across = (k[i] - g[i])
            L = across.length
            u = across / L if L > 1e-9 else Vector()
            over = SAIL_OVER_FRONT if k[i].z > SAIL_FRONT_Z else SAIL_OVER
            outer.append(k[i] + u * over - nrm[i] * SAIL_IN)                 # past the skin's edge, under the skin
            inner.append(g[i] + u * SAIL_GLASS_GAP - nrm[i] * SAIL_IN)       # just forward of the glass's edge
        me = ob.data
        Mi = ob.matrix_world.inverted()
        before = [tuple(c.vector) for c in me.corner_normals]
        n_old = len(me.polygons)
        bm = bmesh.new()
        bm.from_mesh(me)
        gl = _gen_layer(bm)
        mi = _mat_index(me, "Plastique_noir")
        vo = [bm.verts.new(Mi @ p) for p in outer]
        vi = [bm.verts.new(Mi @ p) for p in inner]
        made = 0
        for i in range(n):
            try:
                f = bm.faces.new((vi[i], vi[i + 1], vo[i + 1], vo[i]))
            except ValueError:
                continue
            f.material_index = mi
            f.smooth = False
            f[gl] = 7
            f.normal_update()
            if f.normal.x * s < 0:
                f.normal_flip()
            made += 2
        bm.to_mesh(me)
        bm.free()
        me.update()
        normals = list(before) + [None] * (len(me.loops) - len(before))
        for pg in me.polygons[n_old:]:
            for li in pg.loop_indices:
                normals[li] = tuple(pg.normal)
        if len(normals) == len(me.loops) and all(v is not None for v in normals):
            me.normals_split_custom_set(normals)
        width = max((a - b).length for a, b in zip(k, g))
        report("  %-10s sail backing: %d tris between the skin's rear edge (%d points, z %.3f..%.3f) and the glass's front "
               "edge (%d points), up to %.1f cm across" % (door, made, len(K), min(p.z for p in K), max(p.z for p in K),
                                                          len(G), width * 100))
        total += made
    return total


# Outer belt seal (round 4, seams4; round-3 cabinside3 eyes_mirror.json). Along each door's belt the skin's top turns
# down 0-2.5 cm outboard of the glass (door_fr faces 378 / 334 / 333 / 365: x 0.767-0.791, z 1.086-1.112, y -0.26..0.34)
# and the glass's bottom edge (window up: z 1.077-1.098, |x| 0.767) stands 1-3 cm over the card's top (z 1.065): from
# eye level or a crouch 2 m off the side a ray went down between skin and glass, under the glass and over the card, onto
# the dash and glove box (143 px in a 22-degree view of the right mirror). kotris's belt rail closed it once and went
# in round 1 (_drop_belt_rail). Over most of the belt kotris's black outer weatherstrip (Plastique_noir, z 1.10-1.11,
# |x| 0.770-0.790) covers the gap from above; the slits are decimation cracks 4-8 mm wide between it and the Body skin's
# edge (door_fr y 0.13: |x| 0.789-0.793, y 0.31: 0.780-0.788; rays straight down there meet only the card's band).
# The window slides straight down (rig_vehicle slide_z) and leans in 19 cm (tumblehome), so at belt height the glass
# sweeps |x| 0.58..0.77 over its travel: nothing may stand inboard of its outer face. Every BELT_STEP a row of rays
# straight down, every 2 mm from BELT_GAP outboard of the outermost window vertex (glass, frit, its seam ring) within
# BELT_NEAR of the station out to BELT_MAX_GAP, finds the cracks (no skin within the belt's z band); a dark plate
# (Plastique_noir, gen 7, like the sails) runs under them, BELT_TUCK under the lowest skin it spans, from the glass's
# side out BELT_OUT past the last crack (BELT_SPAN at least, under kotris's strip too where straight down finds no
# crack: the round-3 eyes look 25 degrees down; each run of stations grown half a step at both ends), and a wall at its inner edge stands up to BELT_RISE over the glass's bottom
# (kept 2 mm under kotris's strip where that reaches the glass). A reversed copy closes it from the cabin side.
# Stations closed from above, open past the scan, or where the glass's bottom stands BELT_MAX_RISE over the card (its
# slanted ends) are skipped; front doors stop at BELT_FRONT_Y (the sail and its backing take over there). The plate
# stays BELT_CARD_CLEAR over the card's top (its edge band rises 7-8 mm to the skin).
BELT_STEP = 0.02
BELT_NEAR = 0.08
BELT_GAP = 0.003
BELT_TUCK = 0.003
BELT_RISE = 0.008
BELT_OUT = 0.006
BELT_SPAN = 0.022             # the plate reaches at least this far out of the glass, cracks or not (oblique views)
BELT_BOTTOM = 0.05            # window vertices this close over its lowest one form its bottom edge
BELT_CARD_CLEAR = 0.010
BELT_MAX_GAP = 0.045
BELT_MAX_RISE = 0.06
BELT_END = 0.03               # stations stay this far inside the glass's own y extent
BELT_FRONT_Y = 0.42           # SAIL_G_BOX's rear end
BELT_SKIN_MATS = ("Body", "Body_plastique", "Plastique_noir", "Partie_noir")


def _belt_seal(report):
    total = 0
    for door, (window, s) in DOORS.items():
        ob, win = bpy.data.objects.get(door), bpy.data.objects.get(window)
        if ob is None or win is None:
            continue
        me = ob.data
        names = [m.name if m else "?" for m in me.materials]
        M = ob.matrix_world
        Mi = M.inverted()
        cards = [M @ me.vertices[i].co for p in me.polygons if names[p.material_index].startswith("DoorCard")
                 for i in p.vertices]
        if not cards:
            report("  %-10s belt seal: no door card" % door)
            continue
        ztop = max(v.z for v in cards)
        W = [win.matrix_world @ v.co for v in win.data.vertices]
        wy0, wy1 = min(v.y for v in W) + BELT_END, max(v.y for v in W) - BELT_END
        cy = [v.y for v in cards if v.z > ztop - 0.002]
        y0, y1 = max(min(cy), wy0), min(max(cy), wy1)
        if door in ("door_fl", "door_fr"):
            y1 = min(y1, BELT_FRONT_Y)
        skin_ids = [p.index for p in me.polygons if names[p.material_index] in BELT_SKIN_MATS]
        if not skin_ids:
            report("  %-10s belt seal: no skin faces" % door)
            continue
        skin = BVHTree.FromPolygons([M @ v.co for v in me.vertices],
                                    [list(me.polygons[i].vertices) for i in skin_ids], all_triangles=False)
        wz0 = min(v.z for v in W)
        bottom = sorted((v for v in W if v.z < wz0 + BELT_BOTTOM), key=lambda v: v.y)   # the glass's bottom edge

        def glass_bottom(y):
            """(z, |x|) of the glass's bottom edge at y: z interpolated between the edge's vertices either side, |x|
            the outermost of every edge vertex within 5 mm of those two (the decimated pane's bottom edge is a few
            long segments: door_fr has none between y 0.135 and 0.336)."""
            lo_ = [v for v in bottom if v.y <= y]
            hi_ = [v for v in bottom if v.y >= y]
            if not lo_ or not hi_:
                return None, None
            a, b = lo_[-1], hi_[0]
            t = (y - a.y) / (b.y - a.y) if b.y - a.y > 1e-9 else 0.0
            ends = [v for v in bottom if abs(v.y - a.y) <= 0.005 or abs(v.y - b.y) <= 0.005]
            return a.z + (b.z - a.z) * t, max(s * v.x for v in ends)
        rows = []                                  # (y, x_out, z_plate, x_glass, z_wall_top) per station, |x| metres
        n_st = int(math.floor((y1 - y0) / BELT_STEP)) + 1 if y1 > y0 else 0
        for k in range(n_st):
            y = y0 + k * BELT_STEP
            near = [v for v in W if abs(v.y - y) <= BELT_NEAR]
            gb, bx = glass_bottom(y)
            if not near or gb is None or gb > ztop + BELT_MAX_RISE:
                rows.append(None)
                continue
            gx = max(max(s * v.x for v in near), bx) + BELT_GAP
            hits = []                              # (|x|, z of the skin a ray straight down meets, or None)
            d = 0.0
            while d <= BELT_MAX_GAP + 1e-9:
                loc = skin.ray_cast(Vector((s * (gx + d), y, gb + 0.08)), Vector((0.0, 0.0, -1.0)), 0.2)[0]
                hits.append((gx + d, loc.z if loc is not None and loc.z <= gb + 0.05 else None))
                d += 0.002
            holes = [i for i, (_x, z) in enumerate(hits) if z is None]
            if holes and holes[-1] >= len(hits) - 3:
                rows.append(None)                  # open past the scan (not a crack)
                continue
            x_out = max(gx + BELT_SPAN, hits[holes[-1]][0] + BELT_OUT if holes else 0.0)
            zs = [z for x, z in hits if z is not None and x <= x_out + 0.002]
            if not zs:
                rows.append(None)
                continue
            zp = min(zs) - BELT_TUCK               # under the skin and the weatherstrip either side of the crack
            if zp < ztop + BELT_CARD_CLEAR:
                rows.append(None)                  # would meet the card's edge band
                continue
            zw = gb + BELT_RISE
            if hits[0][1] is not None:             # kotris's black strip already over the glass: the wall stays under it
                zw = min(zw, hits[0][1] - 0.002)
            rows.append((y, x_out, zp, gx, zw))
        bm = bmesh.new()
        bm.from_mesh(me)
        gl = _gen_layer(bm)
        mi = _mat_index(me, "Plastique_noir")
        before = [tuple(c.vector) for c in me.corner_normals]
        n_old = len(me.polygons)
        made = 0
        stations = 0
        prof = []
        for r in rows:
            if r is None:
                prof.append(None)
                continue
            y, x_out, zp, gx, zw = r
            p = [(x_out, zp), (gx, zp)]
            if zw - zp > 0.001:                    # the glass's bottom over the plate: a wall up past it
                p.append((gx, zw))
            prof.append((y, p))
            stations += 1
        runs, cur = [], []                         # runs of neighbouring stations, each grown half a step at both ends
        for r in prof + [None]:
            if r is None:
                if cur:
                    h = BELT_STEP / 2
                    runs.append([(cur[0][0] - h, cur[0][1])] + cur + [(cur[-1][0] + h, cur[-1][1])])
                cur = []
            else:
                cur.append(r)
        prof = []
        for run in runs:
            prof.extend([Vector((s * px, y, pz)) for px, pz in p] for y, p in run)
            prof.append(None)
        faces = []
        for a, b in zip(prof, prof[1:]):
            if a is None or b is None:
                continue
            n = min(len(a), len(b))
            if len(a) != len(b):                   # one station walls up, the next not: the wall's top meets the slope's
                a = a[:2] + ([a[2]] if len(a) > 2 else [a[1]])
                b = b[:2] + ([b[2]] if len(b) > 2 else [b[1]])
                n = 3
            for i in range(n - 1):
                quad = [a[i], b[i], b[i + 1], a[i + 1]]
                if (quad[2] - quad[1]).length < 1e-5 and (quad[3] - quad[0]).length < 1e-5:
                    continue
                if (quad[2] - quad[1]).length < 1e-5:
                    quad = [quad[0], quad[1], quad[3]]
                elif (quad[3] - quad[0]).length < 1e-5:
                    quad = [quad[0], quad[1], quad[2]]
                vv = [bm.verts.new(Mi @ q) for q in quad]
                try:
                    f = bm.faces.new(vv)
                except ValueError:
                    continue
                f.material_index = mi
                f.smooth = False
                f[gl] = 7
                f.normal_update()
                wn = M.to_3x3() @ f.normal
                up = i == 0                        # the slope faces up, the wall outboard
                if (up and wn.z < 0) or (not up and wn.x * s < 0):
                    f.normal_flip()
                faces.append(f)
                made += len(quad) - 2
        if faces:                                  # the cabin side: reversed coincident copies
            ret = bmesh.ops.duplicate(bm, geom=faces)
            backs = [g for g in ret["geom"] if isinstance(g, bmesh.types.BMFace)]
            bmesh.ops.reverse_faces(bm, faces=backs)
            for f in backs:
                f.material_index = mi
                f.smooth = False
                f[gl] = 7
            made += sum(len(f.verts) - 2 for f in backs)
        bm.to_mesh(me)
        bm.free()
        me.update()
        normals = list(before) + [None] * (len(me.loops) - len(before))
        for pg in me.polygons[n_old:]:
            for li in pg.loop_indices:
                normals[li] = tuple(pg.normal)
        if len(normals) == len(me.loops) and all(v is not None for v in normals):
            me.normals_split_custom_set(normals)
        report("  %-10s belt seal: %d tris over %d of %d stations, y %.2f..%.2f (card top z %.3f)"
               % (door, made, stations, len(rows), y0, y1, ztop))
        total += made
    return total


BACKING_MATS = {"Vitre", "Vitre_noir", "Phare", "Phare_vitre", "Phare_orange", "Feux_rouge", "Feux_orange",
                "Feux_blanc", "Feux_stop", "Reflect_red", "Reflect_orange", "Feux_chrome"}
BACKING_D, BACKING_GROW = 0.006, 0.015   # metres behind the skin; how far the plate reaches past the island's outline
RING_W = 0.025                # a glass island's ring reaches this far in from the pane's outline (_island_backing)
GUTTER_Z, GUTTER_W, GUTTER_D = 1.40, 0.025, 0.005   # roof-edge free seams: strip width and depth behind the skin
GUTTER_O, GUTTER_CLIP = 0.0005, 0.0015   # the exit test starts this far behind the edge; a strip stops this short of the face it would leave through
GUTTER_BACKED = 0.003         # a strip's inner corner counts as behind its panel when the panel is within GUTTER_D + this along its normal
PANE_MATS = ("Vitre", "Vitre_noir")
PANE_JOIN = 0.015             # glass shells of one pane whose borders run this close (kotris: 1-12 mm) are closed onto each other
PANE_DOT = 0.85               # ... when they face the same way


def _seamback_material():
    """Near-black matte: what shows through a hairline crack. Its own material so backfill can skip
    it (backs of these plates are never meant to draw) without touching the other closures."""
    mat = bpy.data.materials.get("SeamBack")
    if mat is None:
        mat = bpy.data.materials.new("SeamBack")
        mat.use_nodes = True
        b = next((n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
        if b is not None:
            b.inputs['Base Color'].default_value = (0.010, 0.010, 0.011, 1.0)
            b.inputs['Roughness'].default_value = 0.9
    return mat


def _seg_closest(p, a, b):
    """(distance, closest point, parameter from a) of point p on segment a-b."""
    d = b - a
    L2 = d.length_squared
    t = 0.0 if L2 < 1e-14 else max(0.0, min(1.0, (p - a).dot(d) / L2))
    q = a + d * t
    return (p - q).length, q, t


def _close_pane_cracks(name, report):
    """Close the cracks between the shells of one pane of glass. kotris builds the windscreen, the
    rear glass and the fixed quarter glass from concentric unwelded shells (clear rings and the
    black frit band: vertex-id islands, as _island_backing sees them) with 1-12 mm cracks between
    them. The plate behind each shell (_island_backing, 6 mm back, grown 1.5 cm) and the gutter
    strips above GUTTER_Z showed through those cracks as dotted dark lines inside the windscreen
    (round-1 probes at body (-0.33, 0.73, 1.26), (0.21, 0.54, 1.41), (0.09, 0.75, 1.26)): kotris's
    borders between its own shells are no pane outline, so nothing may show through them.
    Shells rank frit first, then by area. Each shell's border vertices within PANE_JOIN of a
    higher-ranked shell's border (facing the same way, PANE_DOT) move onto that border, and that
    border's vertices along the stretch are inserted into the shell's own border edges, so both
    borders run through the same points: the crack is gone, and the frit (the seal's line) and the
    larger clear ring never move. No vertex is merged, so _island_backing still backs each shell;
    what welds by position may now join a pane's touching shells (planar glass islands 16 -> 11;
    the paint pass already took them as one pane: same 8 panes, same 22.5 m of outline). Returns
    vertices moved."""
    ob = bpy.data.objects.get(name)
    if ob is None:
        return 0
    me = ob.data
    names = [m.name if m else "?" for m in me.materials]
    cn = me.corner_normals
    keep_n = {}
    for p in me.polygons:
        for li in p.loop_indices:
            keep_n[(p.index, me.loops[li].vertex_index)] = tuple(cn[li].vector)
    bm = bmesh.new()
    bm.from_mesh(me)
    gl = _gen_layer(bm)
    bm.faces.ensure_lookup_table()
    seen = set()
    shells = []
    for f0 in bm.faces:
        if f0 in seen:
            continue
        mem, st = [f0], [f0]
        seen.add(f0)
        while st:
            g = st.pop()
            for e in g.edges:
                for h in e.link_faces:
                    if h not in seen:
                        seen.add(h)
                        st.append(h)
                        mem.append(h)
        if all(f[gl] == 0 and names[f.material_index] in PANE_MATS for f in mem):
            shells.append(mem)
    if len(shells) < 2:
        bm.free()
        return 0

    def border(mem):
        ms = set(mem)
        return [(e, f) for f in mem for e in f.edges if sum(1 for h in e.link_faces if h in ms) == 1]
    frit = [all(names[f.material_index] == "Vitre_noir" for f in mem) for mem in shells]
    area = [sum(f.calc_area() for f in mem) for mem in shells]
    order = sorted(range(len(shells)), key=lambda k: (frit[k], area[k]), reverse=True)
    rank = {k: r for r, k in enumerate(order)}           # 0 = never moves

    def nearest(p, nrm, skip, segs):
        """(distance, point, shell) of the nearest border point of another shell facing the same way."""
        best = None
        for a, b, nt, k in segs:
            if k == skip or nt.dot(nrm) < PANE_DOT:
                continue
            d, q, _t = _seg_closest(p, a, b)
            if best is None or d < best[0]:
                best = (d, q, k)
        return best
    moved = inserted = 0
    worst = 0.0
    for i in range(1, len(order)):
        ka = order[i]
        mem = shells[ka]
        ms = set(mem)
        segs = [(e.verts[0].co.copy(), e.verts[1].co.copy(), f.normal.copy(), k)
                for k in range(len(shells)) for e, f in border(shells[k])]
        # 1. this shell's border vertices onto the border across the crack, if that border belongs
        # to a shell that has already been placed (a thin shell in between is the nearer border:
        # then nothing moves here, and that shell closes onto this one in its turn)
        for v in {v for e, f in border(mem) for v in e.verts}:
            nv = sum((f.normal for f in v.link_faces if f in ms), Vector())
            if nv.length < 1e-9:
                continue
            best = nearest(v.co, nv.normalized(), ka, segs)
            if best is not None and 1e-6 < best[0] < PANE_JOIN and rank[best[2]] < i:
                v.co = best[1]
                moved += 1
                worst = max(worst, best[0])
        # 2. the placed shells' border vertices along that stretch into this shell's border edges
        for k in order[:i]:
            for e0, f0 in border(shells[k]):
                for tv in e0.verts:
                    p = tv.co.copy()
                    near = nearest(p, f0.normal, k, [(e.verts[0].co.copy(), e.verts[1].co.copy(), f.normal.copy(), j)
                                                     for j in range(len(shells)) if j != k for e, f in border(shells[j])])
                    if near is None or near[2] != ka or not 1e-6 < near[0] < PANE_JOIN:
                        continue
                    best = None
                    for e, f in border(mem):
                        d, _q, t = _seg_closest(p, e.verts[0].co, e.verts[1].co)
                        if best is None or d < best[0]:
                            best = (d, e, t)
                    d, e, t = best
                    if min((p - e.verts[0].co).length, (p - e.verts[1].co).length) < 0.0005:
                        continue                         # an end of that edge is there already
                    if not 0.001 < t < 0.999:            # nearest at a corner of this shell: the corner
                        end = e.verts[0] if t <= 0.001 else e.verts[1]      # goes onto the placed corner
                        end.co = p
                        moved += 1
                        worst = max(worst, d)
                        continue
                    _ne, nvert = bmesh.utils.edge_split(e, e.verts[0], t)
                    nvert.co = p
                    inserted += 1
                    worst = max(worst, d)
    bm.normal_update()
    bm.to_mesh(me)
    bm.free()
    me.update()
    normals = []
    for p in me.polygons:
        got = [keep_n.get((p.index, me.loops[li].vertex_index)) for li in p.loop_indices]
        have = [g for g in got if g is not None]
        mean = tuple(sum(c[k] for c in have) / len(have) for k in range(3)) if have else tuple(p.normal)
        normals.extend(g if g is not None else mean for g in got)
    if len(normals) == len(me.loops):
        me.normals_split_custom_set(normals)
    report("  %-10s pane cracks: %d glass shells, %d border vertices moved onto the next shell, %d inserted, max %.1f mm"
           % (name, len(shells), moved, inserted, worst * 1000))
    return moved


def _front_clip(tree, o, p):
    """p pulled back toward o (halving) while it lies in front of the gen-0 face nearest to it: a
    strip corner that starts on the edge of a lens and runs over its face never crosses it (the
    black bar down the side of each amber tail lamp, a strip on the lamp bezel's edge 4.5-7.6 mm
    in front of the lens)."""
    for frac in (1.0, 0.5, 0.25, 0.0):
        q = o + (p - o) * frac
        if frac == 0.0:
            return q, True
        loc, nrm, _idx, _dist = tree.find_nearest(q)
        if loc is None or (q - loc).dot(nrm) <= 0.0:
            return q, frac < 1.0
    return p, False


def _exit_clip(tree, owner, skip, o, p):
    """p pulled back toward o so that the segment o -> p ends GUTTER_CLIP short of the first gen-0
    face it would LEAVE the car through (crossing it from its back to its front: hit normal along
    the segment), also when it only comes within GUTTER_CLIP of one. Faces it enters from the front
    are passed: past them the segment is hidden."""
    d = p - o
    L = d.length
    if L < 1e-6:
        return p, False
    u = d / L
    s0 = 0.0
    for _ in range(8):
        loc, nrm, idx, dist = tree.ray_cast(o + u * (s0 + 1e-4), u, L + GUTTER_CLIP - s0 - 1e-4)
        if loc is None:
            return p, False
        s = s0 + 1e-4 + dist
        if owner[idx] is not skip and nrm.dot(u) > 0.0:
            return o + u * max(0.0, min(L, s - GUTTER_CLIP)), True
        s0 = s
    return p, False


def _gutter_strips(name, report):
    """A black strip behind the long free seams at roof height: the kotris roof and side panels are
    unwelded islands, and after simplification their edges no longer meet, a crack the length of
    the drip rail that showed the cabin from every side view. The RD1 wears a black drip-rail
    moulding exactly there. gen 5, SeamBack.

    No strip leaves the car (2026-10-13): each corner is pulled back short of the first kotris face
    the strip would pass out through (_exit_clip) and out of the open air in front of the face
    nearest to it (_front_clip), and the inner half reaches only as far as its panel lies over it
    (GUTTER_BACKED). Every free edge above GUTTER_Z gets a strip, also ones on sliver faces and
    lamp bezels: the C-pillar's rear face beside each quarter window (body face 2320, a 15 cm
    triangle 0-5 mm wide, n (0.02, -0.89, 0.45)) took a strip whose inner half ran 12.5 mm on past
    it, out through the side skin at the top and into open air at the bottom, and its 15 cm of
    black read as a dark streak in front of the quarter glass (screenshot 22.png; pzview probe: body
    face 3712 at (-0.66, -1.16, 1.47)); strips on the tail lamps' bezel edges lay 4-8 mm in front
    of the amber lens and drew its black T marks (17.png). 152 of 275 strips are cut short."""
    ob = bpy.data.objects.get(name)
    if ob is None:
        return 0
    me = ob.data
    bm = bmesh.new()
    bm.from_mesh(me)
    gl = _gen_layer(bm)
    cand = [e for e in bm.edges if len(e.link_faces) == 1 and e.link_faces[0][gl] == 0
            and min(e.verts[0].co.z, e.verts[1].co.z) > GUTTER_Z]
    # a border between two shells of one pane that _close_pane_cracks closed is no seam: both shells'
    # edges run on the same line (an edge whose midpoint lies on another glass shell's border edge)
    names = [m.name if m else "?" for m in me.materials]
    glass = [e for e in cand if names[e.link_faces[0].material_index] in PANE_MATS]
    shut = set()
    for e in glass:
        m = (e.verts[0].co + e.verts[1].co) / 2
        for o in glass:
            if o is not e and o.link_faces[0] is not e.link_faces[0] and \
                    _seg_closest(m, o.verts[0].co, o.verts[1].co)[0] < 0.0003:
                shut.add(e)
                break
    cand = [e for e in cand if e not in shut]
    if not cand:
        bm.free()
        return 0
    bm.verts.index_update()
    owner = [f for f in bm.faces if f[gl] == 0]
    tree = BVHTree.FromPolygons([v.co.copy() for v in bm.verts], [[v.index for v in f.verts] for f in owner],
                                all_triangles=False)
    mi = _mat_index(me, "SeamBack", _seamback_material)
    before = [tuple(c.vector) for c in me.corner_normals]
    n_old = len(me.polygons)
    k = clipped = 0
    for e in cand:
        face = e.link_faces[0]
        n = face.normal.copy()
        if n.length < 1e-6:
            continue
        v1, v2 = e.verts[0].co.copy(), e.verts[1].co.copy()
        d = v2 - v1
        if d.length < 1e-5:
            continue
        t = n.cross(d).normalized()
        mid = (v1 + v2) / 2
        if t.dot(face.calc_center_median() - mid) < 0:
            t = -t                                   # t points INTO the panel this edge belongs to
        h = GUTTER_W / 2
        # inner half flat behind the panel; outer half (across the crack) slopes inward at 45 deg so
        # it never stands out past a neighbour that curves away (the roof-to-side corner, v10)
        a1, a2 = v1 - n * GUTTER_D + t * h, v2 - n * GUTTER_D + t * h
        b1, b2 = v1 - n * (GUTTER_D + h) - t * h, v2 - n * (GUTTER_D + h) - t * h
        ends = [[v1, a1, b1], [v2, a2, b2]]
        hit = False
        for end in ends:
            o = end[0] - n * GUTTER_O                # from just behind the edge, out to each corner
            end[1], ca = _exit_clip(tree, owner, face, o, end[1])
            end[2], cb = _exit_clip(tree, owner, face, o, end[2])
            # the inner half must lie behind the panel: kotris's sliver faces taper to nothing at a
            # corner, and 12.5 mm "into" a sliver is open air beside the car (no face to cross).
            # Skin panels only: a lamp lens's strips sit in the lamp's own gaps, where a shorter
            # inner half tilts the strip into view (the tail lamps' side gaps read wider)
            if names[face.material_index] in SKIN_MATS:
                base = end[0] - n * GUTTER_D
                for frac in (1.0, 0.5, 0.25, 0.0):
                    p = base + (end[1] - base) * frac
                    if frac == 0.0 or tree.ray_cast(p, n, GUTTER_D + GUTTER_BACKED)[0] is not None:
                        break
                if frac < 1.0:
                    end[1] = p
                    ca = True
            end[1], fa = _front_clip(tree, o, end[1])
            end[2], fb = _front_clip(tree, o, end[2])
            hit = hit or ca or cb or fa or fb
        (_v1, a1, b1), (_v2, a2, b2) = ends
        if hit:
            clipped += 1
            if ((a2 - a1).cross(b1 - a1).length + (b2 - b1).cross(a2 - b1).length) / 2 < 2e-6:
                continue                             # nothing left of it inside the car
        try:
            f = bm.faces.new((bm.verts.new(a1), bm.verts.new(a2), bm.verts.new(b2), bm.verts.new(b1)))
        except ValueError:
            continue
        f.material_index = mi
        f.smooth = False
        f[gl] = 5
        f.normal_update()
        if f.normal.dot(n) < 0:
            f.normal_flip()
        k += 2
    bm.to_mesh(me)
    bm.free()
    me.update()
    normals = list(before) + [None] * (len(me.loops) - len(before))
    for pg in me.polygons[n_old:]:
        for li in pg.loop_indices:
            normals[li] = tuple(pg.normal)
    if len(normals) == len(me.loops) and all(v is not None for v in normals):
        me.normals_split_custom_set(normals)
    report("  %-10s gutter strips: %d tris behind %d roof-edge seam edges, %d cut short where they left the car or their panel, "
           "%d closed pane borders skipped" % (name, k, len(cand), clipped, len(shut)))
    return k


def _island_backing(name, report):
    """A black plate 6 mm behind every glass or lamp island and behind every small free island of
    the skin (the fuel flap), each a copy of the island grown 1.5 cm past its outline in its own
    plane. The low-poly islands were simplified on their own, so their edges no longer meet the
    surround exactly: hairline cracks that showed the dark cabin ("weird pixels all over the car",
    "I can see through the tail lights", 2026-10-12). Behind a crack the plate reads as the window
    rubber or the flap's shut line. One plate per island costs what the island costs (a strip per
    seam edge cost 8,200 tris and leaked at odd angles). gen 5 (baked flat, Plastique_noir)."""
    ob = bpy.data.objects.get(name)
    if ob is None:
        return 0
    me = ob.data
    names = [m.name if m else "?" for m in me.materials]
    bm = bmesh.new()
    bm.from_mesh(me)
    gl = _gen_layer(bm)
    bm.faces.ensure_lookup_table()
    comp = [-1] * len(bm.faces)
    comps = []
    for f0 in bm.faces:
        if comp[f0.index] >= 0:
            continue
        comp[f0.index] = len(comps)
        members, stack = [f0], [f0]
        while stack:
            g = stack.pop()
            for e in g.edges:
                for h in e.link_faces:
                    if comp[h.index] < 0:
                        comp[h.index] = len(comps)
                        stack.append(h)
                        members.append(h)
        comps.append(members)
    chosen = []
    for members in comps:
        if any(f[gl] for f in members):
            continue
        mats = {names[f.material_index] for f in members}
        # glass and lamp islands only. Free skin islands (mud flaps, the fuel flap) got plates in v9
        # and the plates stuck out past the free-standing flaps (leak slivers at every arch, v10);
        # build_details replaces the fuel flap with its own seam ring.
        if mats <= BACKING_MATS:
            chosen.append(members)
    if not chosen:
        bm.free()
        return 0
    mi = _mat_index(me, "SeamBack", _seamback_material)
    before = [tuple(c.vector) for c in me.corner_normals]
    n_old = len(me.polygons)
    k = 0
    rings = 0
    # glass: a ring along the pane's outline, not a plate behind the whole pane (2026-10-17 review CAB-6). When
    # the game removes a window it discards the window-zone texels only; the plate (body zone, dark, facing out)
    # stayed and a black sheet replaced the view of the dash. Borders between two shells of one pane (closed by
    # _close_pane_cracks: an edge whose midpoint lies on another glass shell's border edge) are no outline.
    glass = [m for m in chosen if all(names[f.material_index] in PANE_MATS for f in m)]
    gborder = []
    for m in glass:
        ms = set(m)
        gborder.append([e for f in m for e in f.edges if sum(1 for g in e.link_faces if g in ms) == 1])
    gsegs = [(e.verts[0].co.copy(), e.verts[1].co.copy(), gi) for gi, es in enumerate(gborder) for e in es]
    for gi, members in enumerate(glass):
        mset = set(members)
        outline = []
        for e in gborder[gi]:
            mid = (e.verts[0].co + e.verts[1].co) / 2
            if any(oj != gi and _seg_closest(mid, a, b)[0] < 0.0003 for a, b, oj in gsegs):
                continue                                         # an inner border of the pane
            f = next(g for g in e.link_faces if g in mset)
            outline.append((e, f))
        if not outline:
            continue
        vn, tin = {}, {}
        for e, f in outline:
            d = e.verts[1].co - e.verts[0].co
            t = f.normal.cross(d)
            if t.length < 1e-9:
                continue
            t.normalize()
            if t.dot(f.calc_center_median() - (e.verts[0].co + e.verts[1].co) / 2) < 0:
                t = -t                                           # into the pane
            for v in e.verts:
                tin[v] = tin.get(v, Vector()) + t
                acc = Vector()
                for g in v.link_faces:
                    if g in mset:
                        acc += g.normal * g.calc_area()
                vn[v] = acc.normalized() if acc.length > 1e-9 else f.normal.copy()
        inner, outer = {}, {}
        for v, t in tin.items():
            t = t.normalized() if t.length > 1e-9 else t
            base = v.co - vn[v] * BACKING_D
            inner[v] = bm.verts.new(base + t * RING_W)
            outer[v] = bm.verts.new(base - t * BACKING_GROW - vn[v] * BACKING_GROW)
        for e, f in outline:
            a, b = e.verts
            if a not in inner or b not in inner:
                continue
            try:
                q = bm.faces.new((outer[a], outer[b], inner[b], inner[a]))
            except ValueError:
                continue
            q.material_index = mi
            q.smooth = False
            q[gl] = 5
            q.normal_update()
            if q.normal.dot(f.normal) < 0:
                q.normal_flip()
            k += 2
        rings += 1
    for members in chosen:
        if any(members is m for m in glass):
            continue
        mset = set(members)
        vs = {v for f in members for v in f.verts}
        c = sum((v.co for v in vs), Vector()) / len(vs)
        # per-vertex normal from the island's own faces (a lamp that wraps a body corner has no
        # single plane: an averaged plane pushed the plate's rim OUT through the side, v10)
        vn = {}
        for v in vs:
            acc = Vector((0.0, 0.0, 0.0))
            for f in v.link_faces:
                if f in mset:
                    acc += f.normal * f.calc_area()
            vn[v] = acc.normalized() if acc.length > 1e-9 else Vector((0.0, 0.0, 1.0))
        rim = {v for f in members for e in f.edges if sum(1 for g in e.link_faces if g in mset) == 1 for v in e.verts}
        ret = bmesh.ops.duplicate(bm, geom=list(members), use_select_history=False)
        new_faces = [g for g in ret["geom"] if isinstance(g, bmesh.types.BMFace)]
        vmap = ret["vert_map"]
        for v in vs:
            nv = vmap.get(v)
            if nv is None:
                continue
            n = vn[v]
            co = v.co - n * BACKING_D
            if v in rim:
                # the rim grows OUTWARD and INWARD at 45 degrees, so it stays behind any surround
                # that curves away by less than that
                t = (v.co - c) - n * (v.co - c).dot(n)
                if t.length > 1e-6:
                    co = co + t.normalized() * BACKING_GROW - n * BACKING_GROW
            nv.co = co
        for f in new_faces:
            f.material_index = mi
            f.smooth = False
            f[gl] = 5
            k += len(f.verts) - 2
    bm.to_mesh(me)
    bm.free()
    me.update()
    normals = list(before) + [None] * (len(me.loops) - len(before))
    for pg in me.polygons[n_old:]:
        for li in pg.loop_indices:
            normals[li] = tuple(pg.normal)
    if len(normals) == len(me.loops) and all(v is not None for v in normals):
        me.normals_split_custom_set(normals)
    report("  %-10s seam backing: %d tris, %d plates behind lamp islands, %d rings round glass outlines"
           % (name, k, len(chosen) - len(glass), rings))
    return k


# Round 2 (2026-10-17 review R2-OC-2): black jagged shards where each A-pillar trim meets the headliner, seen from both
# front seats. The windscreen's ring (above: grown BACKING_GROW out past the glass outline and as far back) runs 1-1.5 cm
# in FRONT of the interior's A-pillar trim at the windscreen's top corners (gview probes from the driver's eye: SeamBack
# body faces 3456 / 4025 at (-0.575, 0.299, 1.509), then the trim, interior face 256, at (-0.585, 0.311, 1.512)); backfill
# gave the ring's faces backs and they drew as dark shards over the grey trim. Every SeamBack vertex of the body that lies
# (the windscreen's and the lamps' plates, and since round 3 the roof's gutter strips in front of TUCK_STRIP_Y)
# on the cabin side of the nearest kotris interior face (within TRIM_REACH, over it or up to TRIM_SIDE beside its edge)
# moves onto that face's nearest point, TRIM_TUCK behind it, unless that crosses the body's skin: the ring still closes
# the crack along the glass, behind the trim now.
TRIM_REACH = 0.03
TRIM_TUCK = 0.003
TRIM_Z = 1.12                 # only above this (the hinge walls' dark cells, _hinge_walls, stop at 1.10)
TRIM_COVER = 0.0015           # a crossing plate face's trim-coloured cover lies this far in front of it, cabin side
TRIM_SIDE = 0.015            # a vertex up to this far beside the nearest trim face's edge still counts (the ring's corner
                              # vertex pokes through the 1 cm gap between the A-pillar trim's top and the headliner)
# Round 3 (R2-OC-2 remainder): the thin dark slivers left at both A-pillar tops were the roof's GUTTER strips, not the
# ring: _gutter_strips runs along every free edge above GUTTER_Z, and at the A-pillar top those are the edges of the body's
# own inner pillar faces beside the trim (body faces 4123 / 4228 of the round-2 build at (-0.59, 0.33, 1.50), facing the
# cabin 3 mm in front of the trim's plane; idpass from both front seats). The strips now exist before the tuck, and the
# tuck takes the ones in front of TUCK_STRIP_Y with the plates; the rear ones keep their place (the hatch's slit)
TUCK_STRIP_Y = 0.0
TRIM_COVER_GROW = 0.0015      # a seen strip's cover reaches this far past its outline (_trim_covers)
TRIM_SEEN_MIN = 3             # ... and a strip gets one when a seat sees at least this many of its 1 cm samples: the A-pillar
                              # front-edge strips (1-2 of 51 seen) took 15 cm covers that stood dark (AO) in front of the trim
                              # at the pillar's foot in the second build of round 3


def _tuck_plates_behind_trim(report, skip=(), strips=()):
    body = bpy.data.objects.get("body")
    it = bpy.data.objects.get("interior")
    if body is None or it is None:
        return 0
    ime = it.data
    iga = ime.attributes.get(GEN)
    igv = [0] * len(ime.polygons)
    if iga is not None:
        iga.data.foreach_get("value", igv)
    W = it.matrix_world
    tree = BVHTree.FromPolygons([W @ v.co for v in ime.vertices], [list(p.vertices) for p in ime.polygons if igv[p.index] == 0],
                                all_triangles=False)
    me = body.data
    names = [m.name if m else "?" for m in me.materials]
    ga = me.attributes.get(GEN)
    gv = [0] * len(me.polygons)
    if ga is not None:
        ga.data.foreach_get("value", gv)
    plate = set()
    other = set()
    skip = set(skip)
    for p in me.polygons:
        (plate if names[p.material_index] == "SeamBack" and gv[p.index] == 5 and p.index not in skip else other).update(p.vertices)
    M = body.matrix_world
    Mi = M.inverted()
    skin = BVHTree.FromPolygons([M @ v.co for v in me.vertices], [list(p.vertices) for p in me.polygons if gv[p.index] == 0],
                                all_triangles=False)
    gpolys = [list(p.vertices) for p in me.polygons if gv[p.index] == 0 and names[p.material_index] in PANE_MATS]
    glass = BVHTree.FromPolygons([M @ v.co for v in me.vertices], gpolys, all_triangles=False) if gpolys else None
    moved = 0
    worst = 0.0
    for i in plate - other:
        v = me.vertices[i]
        q = M @ v.co
        if q.z < TRIM_Z:
            continue                                    # the glass and lamp plates up the pillars, not the hinge walls
        loc, n, _idx, _d = tree.find_nearest(q, TRIM_REACH)
        if loc is None:
            continue
        s = (q - loc).dot(n)
        if s <= -TRIM_TUCK or ((q - loc) - n * s).length > TRIM_SIDE:
            continue                                    # behind the trim already, or well beside its edge
        t = loc - n * TRIM_TUCK                         # onto the trim, just behind it (over its face: straight back)
        d = t - q
        if d.length > 1e-6 and skin.ray_cast(q, d.normalized(), d.length + 0.002)[0] is not None:
            # that would cross the skin (the windscreen's frit, at the ring's top corners where the trim's top edge
            # meets the headliner behind the glass's line): back toward the glass instead, BACKING_D behind it
            g, gn, _gi, _gd = glass.find_nearest(q, TRIM_REACH) if glass is not None else (None, None, None, None)
            if g is None:
                continue
            t = g - gn * BACKING_D
            d = t - q
            if d.length > 1e-6 and skin.ray_cast(q, d.normalized(), d.length + 0.001)[0] is not None:
                continue
            nrm_t = tree.find_nearest(t, TRIM_REACH)
            if nrm_t[0] is not None and (t - nrm_t[0]).dot(nrm_t[1]) > -TRIM_TUCK \
                    and ((t - nrm_t[0]) - nrm_t[1] * (t - nrm_t[0]).dot(nrm_t[1])).length <= TRIM_SIDE:
                continue                                # still in the cabin there: leave it
        v.co = Mi @ t
        moved += 1
        worst = max(worst, d.length)
    me.update()
    # a plate face whose corners all lie behind the trim can still cut through the trim's curve in between (the ring's
    # quad from the glass edge to behind the A-pillar trim, across the trim's fold at the headliner): such faces go
    kill = []
    for p in me.polygons:
        if names[p.material_index] != "SeamBack" or gv[p.index] != 5 or (M @ p.center).z < TRIM_Z or p.index in skip:
            continue
        vs = [M @ me.vertices[i].co for i in p.vertices]
        c = sum(vs, Vector()) / len(vs)
        for q in [c] + [(vs[i] + vs[(i + 1) % len(vs)]) / 2 for i in range(len(vs))] + [(c + w) / 2 for w in vs]:
            loc, n, _idx, _d = tree.find_nearest(q, TRIM_REACH)
            if loc is None:
                continue
            s = (q - loc).dot(n)
            if s > 0.001 and ((q - loc) - n * s).length < 0.001:
                kill.append(p.index)
                break
    # gutter strips are judged by the seat eyes below, not by the crossing test: a crossing strip whose front looks at the
    # glass is passed from behind by backfill (backfill.SEAMBACK), and a cover would only lay a grey bar over the
    # windscreen's frit (the 4 cm bar at (-0.59, 0.39, 1.46) in the first build of round 3)
    strips = set(strips)
    bare = [i for i in kill if i in strips]
    kill = [i for i in kill if i not in strips]
    # they also close slots (deleted, a first build saw the sky through the left A-pillar top from the driver's
    # seat, and the road past a lamp plate at the cargo opening with the gate open): each stays, and gets a copy on
    # the interior in the trim's material TRIM_COVER in front of it, facing the cabin, which is what the seats see
    _trim_covers(body, it, kill)
    # a front gutter strip the tuck could not move (behind the trim it would cross the skin) whose FRONT a seat eye sees,
    # within TRIM_REACH of the trim, reads as a dark line where the trim meets the headliner (round 3: body face 4209,
    # 10 cm along the right A-pillar top at (0.50, 0.28, 1.55), from the passenger's seat): it gets a trim cover on its
    # own front. The eyes look past the covers just made
    eyes = _eye_points()
    etree = _eye_tree()
    seen = []
    look = {}
    for p in me.polygons:
        i = p.index
        if i not in strips or i in skip or names[p.material_index] != "SeamBack":
            continue
        c = M @ p.center
        nw = (M.to_3x3() @ p.normal).normalized()
        front = [e for e in eyes if nw.dot(e - c) > 0]                  # the eyes that see its front
        if c.z < TRIM_Z or not front or tree.find_nearest(c, TRIM_REACH)[0] is None:
            continue
        vs = [M @ me.vertices[j].co for j in p.vertices]
        pts = [q for k in range(1, len(vs) - 1) for q in _tri_samples(vs[0], vs[k], vs[k + 1], 0.01)]
        vis = [[e for e in front if _seen(etree, [e], q + nw * 0.0005, tol=0.0015)] for q in pts]
        who = {tuple(e) for es in vis for e in es}
        who = [Vector(e) for e in who]
        if sum(1 for es in vis if es) >= TRIM_SEEN_MIN:
            seen.append(i)
            look[i] = sum(((e - c).normalized() for e in who), Vector()).normalized()
    _trim_covers(body, it, seen, toward=look)
    bare = [i for i in bare if i not in set(seen)]
    report("  body       plates behind the trim: %d SeamBack vertices on the cabin side of the interior moved %.0f mm behind it "
           "(max move %.1f mm), %d plate faces still crossing it covered on the cabin side in trim colour; gutter strips: "
           "%d whose front a seat sees covered on their front, %d more crossing it left bare (no seat sees their front)"
           % (moved, TRIM_TUCK * 1000, worst * 1000, len(kill), len(seen), len(bare)))
    return moved


def _trim_covers(body, it, ids, toward=None):
    """A copy of each body face in ids on the interior, in the trim's material (gen 5), TRIM_COVER in front of it toward
    the middle of the cabin (see _tuck_plates_behind_trim). With toward ({face: unit direction to the seats that see
    it}) the copy faces the face's own front and moves TRIM_COVER along that direction, grown TRIM_COVER_GROW round its
    centre: a strip seen at a grazing angle (1-4 degrees) slid out from under a copy moved along its normal."""
    if not ids:
        return 0
    me, ime = body.data, it.data
    M = body.matrix_world
    W = it.matrix_world.inverted()
    polys = []
    for i in ids:
        vs = [M @ me.vertices[j].co for j in me.polygons[i].vertices]
        c = sum(vs, Vector()) / len(vs)
        nn = (vs[1] - vs[0]).cross(vs[2] - vs[0])
        front = (M.to_3x3() @ me.polygons[i].normal) if toward else Vector((0.0, 0.6 * c.y, 1.1)) - c
        if nn.dot(front) < 0:                                 # toward the middle of the cabin (or the face's front)
            vs.reverse()
            nn = -nn
        off = nn.normalized() * TRIM_COVER if nn.length > 1e-12 else Vector()
        if toward:
            off = toward[i] * TRIM_COVER
            vs = [c + (q - c) * (1.0 + TRIM_COVER_GROW / max((q - c).length, 1e-6)) for q in vs]
        polys.append([W @ (q + off) for q in vs])
    ti = _mat_index(ime, "Interieur")
    ibm = bmesh.new()
    ibm.from_mesh(ime)
    igl = _gen_layer(ibm)
    for vs in polys:
        try:
            f = ibm.faces.new([ibm.verts.new(q) for q in vs])
        except ValueError:
            continue
        f.material_index = ti
        f.smooth = False
        f[igl] = 5
    ibm.to_mesh(ime)
    ibm.free()
    ime.update()
    return len(ids)


def _islands_of(ob, mats):
    """Face ids of the islands whose majority material is one of `mats`."""
    names = [m.name if m else "?" for m in ob.data.materials]
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bm.faces.ensure_lookup_table()
    seen = [False] * len(bm.faces)
    out = []
    for f in bm.faces:
        if seen[f.index]:
            continue
        grp, st = [f.index], [f]
        seen[f.index] = True
        while st:
            g = st.pop()
            for e in g.edges:
                for h in e.link_faces:
                    if not seen[h.index]:
                        seen[h.index] = True
                        grp.append(h.index)
                        st.append(h)
        counts = {}
        for i in grp:
            m = names[bm.faces[i].material_index]
            counts[m] = counts.get(m, 0) + 1
        if max(counts.items(), key=lambda kv: kv[1])[0] in mats:
            out.extend(grp)
    bm.free()
    return out


def _decal_islands(ob):
    names = [m.name if m else "?" for m in ob.data.materials]
    if not any(n.startswith("Decal") for n in names):
        return []
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bm.faces.ensure_lookup_table()
    seen = [False] * len(bm.faces)
    out = []
    for f in bm.faces:
        if seen[f.index]:
            continue
        grp, st = [f.index], [f]
        seen[f.index] = True
        while st:
            g = st.pop()
            for e in g.edges:
                for h in e.link_faces:
                    if not seen[h.index]:
                        seen[h.index] = True
                        grp.append(h.index)
                        st.append(h)
        if any(names[bm.faces[i].material_index].startswith("Decal") for i in grp) and len(grp) < 400:
            out.extend(grp)
    bm.free()
    return out


def _windscreen_corners(ob):
    """The windscreen's two lower outer corners on the full-detail body: of the glass shells round the
    car's centre line in front of the B-pillars (frit band and clear rings), the outermost vertex
    each side among those within 15 cm of the lowest. kotris: (+-0.711, 0.789, 1.122)."""
    names = [m.name if m else "?" for m in ob.data.materials]
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bm.faces.ensure_lookup_table()
    seen = set()
    pts = []
    for f0 in bm.faces:
        if f0 in seen:
            continue
        grp, st = [f0], [f0]
        seen.add(f0)
        while st:
            g = st.pop()
            for e in g.edges:
                for h in e.link_faces:
                    if h not in seen:
                        seen.add(h)
                        grp.append(h)
                        st.append(h)
        if not all(names[f.material_index] in PANE_MATS for f in grp):
            continue
        vs = [v.co.copy() for f in grp for v in f.verts]
        cx = (min(v.x for v in vs) + max(v.x for v in vs)) / 2
        cy = (min(v.y for v in vs) + max(v.y for v in vs)) / 2
        if abs(cx) < 0.05 and cy > 0.2:
            pts.extend(vs)
    bm.free()
    if not pts:
        return []
    z0 = min(p.z for p in pts)
    low = [p for p in pts if p.z < z0 + 0.15]
    return [min(low, key=lambda p: p.x), max(low, key=lambda p: p.x)]


def _held_verts(ob, centres, r):
    """Indices of the vertices within r of any centre that lowpoly.decimate must not move: everything
    there (frit band, moulding, the small pillar-base trims, the pillar and cowl skin) except the clear
    glass's own vertices: _close_pane_cracks closes the clear ring's border onto the held frit anyway,
    and held, its corner only fanned long slivers into the pane."""
    me = ob.data
    names = [m.name if m else "?" for m in me.materials]
    clear = [True] * len(me.vertices)
    for p in me.polygons:
        if names[p.material_index] != "Vitre":
            for i in p.vertices:
                clear[i] = False
    return {v.index for v in me.vertices if not clear[v.index] and any((v.co - c).length <= r for c in centres)}


def _deviation(low, hi, n=4000):
    """How far the high surface strays from the low one (sampled high vertices): sizes the bake cage."""
    dg = bpy.context.evaluated_depsgraph_get()
    tree = BVHTree.FromObject(low, dg)
    vs = hi.data.vertices
    step = max(1, len(vs) // n)
    d = sorted(tree.find_nearest(vs[i].co)[3] or 0.0 for i in range(0, len(vs), step))
    return (d[int(0.95 * (len(d) - 1))], d[-1]) if d else (0.0, 0.0)


# ----------------------------------------------------------------------------------------------
# exterior pruning


def _prune_shell_behind_trim(ob):
    """Solidify shell faces (gen 1) that sit behind the panel's own trim card are never seen, shut
    or open: every ray from the face into the cabin side hits the panel itself within 25 cm."""
    attr = ob.data.attributes.get(GEN)
    if attr is None:
        return 0
    vals = [0] * len(ob.data.polygons)
    attr.data.foreach_get("value", vals)
    dg = bpy.context.evaluated_depsgraph_get()
    tree = BVHTree.FromObject(ob, dg)
    kill = []
    for p in ob.data.polygons:
        if vals[p.index] != 1:
            continue
        n = p.normal
        t = n.orthogonal().normalized()
        b = n.cross(t)
        covered = True
        for d in (n, (n + t * 0.7).normalized(), (n - t * 0.7).normalized(), (n + b * 0.7).normalized(), (n - b * 0.7).normalized()):
            hit = tree.ray_cast(p.center + n * 0.0015, d, 0.25)
            if hit[0] is None or hit[2] == p.index:
                covered = False
                break
        if covered:
            kill.append(p.index)
    if kill:
        bm = bmesh.new()
        bm.from_mesh(ob.data)
        bm.faces.ensure_lookup_table()
        bmesh.ops.delete(bm, geom=[bm.faces[i] for i in kill], context='FACES')
        bm.to_mesh(ob.data)
        bm.free()
    return len(kill)


def _prune(report):
    """Delete every generated face (gen 1-3) that the game camera can see on the SHUT car: ray-cast
    from 30 +-10 degrees elevation every 15 degrees of azimuth against all rendered geometry (glass
    counts as opaque, so trim seen through a window stays). Back-facing faces are skipped: the game
    culls them."""
    obs = [o for o in bpy.data.objects if o.type == 'MESH' and not o.hide_render and o.visible_get()]
    verts, polys, owner, offs = [], [], [], {}
    for o in obs:
        M = o.matrix_world
        base = len(verts)
        verts.extend(M @ v.co for v in o.data.vertices)
        offs[o.name] = len(polys)
        for p in o.data.polygons:
            polys.append([base + i for i in p.vertices])
    tree = BVHTree.FromPolygons(verts, polys, all_triangles=False)
    # A visible generated point is a poke-out only if it lies OUTSIDE the car: from a point inside
    # (the cabin floor seen through the gap under a door, the cargo riser under the gate) nearly every
    # ray hits the car; from a point outside the paint about half of them escape. 26 directions.
    probes = []
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for dz in (-1, 0, 1):
                if dx or dy or dz:
                    probes.append(Vector((dx, dy, dz)).normalized())

    hull_v, hull_p = [], []
    for o in obs:
        if o.name not in ("body", "hood", "door_fl", "door_fr", "door_rl", "door_rr", "trunk", "trunk_top",
                          "window_fl", "window_fr", "window_rl", "window_rr"):
            continue
        ga = o.data.attributes.get(GEN)
        gv = [0] * len(o.data.polygons)
        if ga is not None:
            ga.data.foreach_get("value", gv)
        M = o.matrix_world
        base = len(hull_v)
        hull_v.extend(M @ v.co for v in o.data.vertices)
        for p in o.data.polygons:
            if gv[p.index] == 0:
                hull_p.append([base + i for i in p.vertices])
    hull = BVHTree.FromPolygons(hull_v, hull_p, all_triangles=False)

    def outside_skin(pt):
        """Solidify pieces: a visible point on the outer side of the nearest skin face pokes out."""
        loc, n, _i, _d = hull.find_nearest(pt)
        return loc is not None and (pt - loc).dot(n) > 0.002

    def outside(pt):
        """Cabin closures: outside only if not enclosed by the car (floor seen through the gap
        under a door, riser under the gate: enclosed, kept)."""
        escapes = 0
        for d in probes:
            hit = tree.ray_cast(pt + d * 0.003, d, 30.0)
            if hit[0] is None:
                escapes += 1
        return escapes >= 9
    dirs = []
    for el in (20.0, 30.0, 40.0):
        e = math.radians(el)
        for az in range(0, 360, 15):
            a = math.radians(az)
            dirs.append(-Vector((math.cos(e) * math.cos(a), math.cos(e) * math.sin(a), math.sin(e))))
    total = 0
    for o in obs:
        attr = o.data.attributes.get(GEN)
        if attr is None:
            continue
        vals = [0] * len(o.data.polygons)
        attr.data.foreach_get("value", vals)
        M = o.matrix_world
        R = M.to_3x3()
        kill = []
        for p in o.data.polygons:
            if vals[p.index] not in (1, 2, 3):
                continue
            gid = offs[o.name] + p.index
            n = (R @ p.normal).normalized()
            c = M @ p.center
            pts = [c] + [c + ((M @ o.data.vertices[i].co) - c) * 0.7 for i in p.vertices[:3]]
            if p.area > 0.0009:                  # big faces: a 3 cm grid, a long box face can poke
                vs = [M @ o.data.vertices[i].co for i in p.vertices]   # out at one end only
                for k in range(1, len(vs) - 1):
                    a, b, cc = vs[0], vs[k], vs[k + 1]
                    steps = max(2, int(max((b - a).length, (cc - a).length) / 0.03))
                    for i in range(steps + 1):
                        for j in range(steps + 1 - i):
                            u, v = (i + 0.3) / (steps + 1), (j + 0.3) / (steps + 1)
                            if u + v < 1.0:
                                pts.append(a + (b - a) * u + (cc - a) * v)
            seen = False
            for d in dirs:
                if n.dot(d) >= 0:
                    continue
                for s in pts:
                    hit = tree.ray_cast(s - d * 10.0, d, 20.0)
                    if hit[2] == gid and (outside_skin(s) if vals[p.index] in (1, 2) else outside(s)):
                        seen = True
                        break
                if seen:
                    break
            if seen:
                kill.append(p.index)
        if kill:
            bm = bmesh.new()
            bm.from_mesh(o.data)
            bm.faces.ensure_lookup_table()
            bmesh.ops.delete(bm, geom=[bm.faces[i] for i in kill], context='FACES')
            bm.to_mesh(o.data)
            bm.free()
        total += len(kill)
        if kill:
            report("  prune %-12s %5d generated faces poking out of the skin, deleted" % (o.name, len(kill)))
    report("  prune: %d faces deleted" % total)
    return total


# ----------------------------------------------------------------------------------------------


# Headlamp surround (2026-10-17, feedback: "weird geometry black line around the headlights"): kotris wraps each
# headlamp in a strip of Partie_noir on the fender and on the hood's front corner, 1-4 cm wide and jagged after
# decimation; on the RD1 that metal is paint up to a thin shut line (which compose's gap pass draws). Faces of
# these parts whose centre lies in a box round either lamp go to Body. pzview probe, view (0.62, 1.85, 0.80) az 45:
# hood faces 97-130 and body faces 2457-2716 (0.48..0.78, 1.70..1.90, 0.86..0.91).
LAMP_SURROUND = ((0.40, 0.82), (1.62, 1.99), (0.80, 0.97))       # |x|, y, z of the face centre, metres
LAMP_SURROUND_PARTS = ("body", "hood")


def _lamp_surround(report):
    (x0, x1), (y0, y1), (z0, z1) = LAMP_SURROUND
    for name in LAMP_SURROUND_PARTS:
        ob = bpy.data.objects.get(name)
        if ob is None:
            continue
        me = ob.data
        names = [m.name if m else "?" for m in me.materials]
        if "Partie_noir" not in names:
            continue
        dark = names.index("Partie_noir")
        if "Body" not in names:
            me.materials.append(bpy.data.materials["Body"])
            names.append("Body")
        body = names.index("Body")
        M = ob.matrix_world
        n = 0
        for p in me.polygons:
            if p.material_index != dark:
                continue
            c = M @ p.center
            if x0 <= abs(c.x) <= x1 and y0 <= c.y <= y1 and z0 <= c.z <= z1:
                p.material_index = body
                n += 1
        report("  %-12s headlamp surround: %d Partie_noir faces painted Body" % (name, n))


# The grille (2026-10-17 review EXT-3, ref S\review_exterior\ref\ex_grille.jpg): the RD1's is four straight slats
# in a trapezoid frame. kotris models two slats, deep end pockets and ~50 loose 1-3 face shreds at each end; the
# decimator made an L bracket with a see-through void of the right end (culled face into the bay) and smeared
# triangles of the left one. Before decimation everything inside the frame's opening goes (slats, the dark backs
# of the openings, the end pockets, the shreds; the H badge and kotris's frame stay), and after it _grille_build
# puts in a dark back plate behind the whole opening and four slats whose ends tuck behind the frame.
# Measured on body_hi (scratch grille_scan, rays along -y every 1 cm x 5 mm): openings z 0.845-0.866, 0.802-0.821
# and 0.751-0.771; the frame's inner edge at |x| 0.305 (top, end pockets included) to 0.245 (bottom); the slats'
# fronts at y 2.012 (z 0.83) / 2.031 (z 0.785) on the centre line, 2.1-2.3 cm further back at |x| 0.28.
GRILLE_Z = (0.751, 0.866)                 # the opening, bottom and top
GRILLE_W = (0.245, 0.305)                 # its half width at the bottom and the top (a trapezoid, wider on top)
GRILLE_Y = (1.89, 2.045)                  # faces of the grille lie in this y range
GRILLE_MATS = ("Body_plastique", "Partie_noir")
GRILLE_SHRED = 4                          # loose islands of fewer faces in the grille box: kotris's end shreds (the
                                          # frame's own end pieces are 5-10 face islands: they stay)
GRILLE_SLATS = 4
GRILLE_SLAT_H = 0.013                     # slat height, metres (gaps: what is left of the opening, /5)
GRILLE_SLAT_D = 0.022                     # slat depth
GRILLE_TUCK = 0.012                       # slat ends run this far behind the frame's inner edge
GRILLE_PLATE_Y = 1.948                    # the dark plate behind the opening (kotris's opening backs: y 1.946-1.99)
GRILLE_SEG = 6                            # segments along each slat's curve


# The grille's bottom (round 2, 2026-10-17 review R2-EXT-7: "the bottom slat is ragged"). Under the fourth slat the
# frame's lower lip (kotris Body_plastique, top at z ~0.745) carries stubs of kotris's own fifth slat that _grille_strip's
# box (centres from z 0.748) cut through: steps and teeth 0.5-2 cm tall along its top edge, at full detail as well as low
# (scratch g_hi/cmp_lip.png). Faces of the lip whose centre lies in GRILLE_LIP (|x|, z) go with the slats, and
# _grille_build closes the lip's top with a straight bar: its top at the opening's bottom (GRILLE_Z[0]), GRILLE_BAR_H tall,
# its front GRILLE_BAR_Y on the centre line curving back like the slats, a top face back to GRILLE_BAR_BACK (one slat gap
# under the fourth slat, as between the slats).
GRILLE_LIP = (0.215, (0.740, 0.775))
GRILLE_BAR_H = 0.014
GRILLE_BAR_Y = 2.033
GRILLE_BAR_BACK = 1.995
GRILLE_BAR_W = 0.240          # half width: its ends run into the frame's rounded lower corners


# The mud flaps (round 2, R2-EXT-2: "all four taper to a curved point; the real ones are flat rectangles with a square
# bottom", S\review2_exterior\ref\blk_rl.jpg). kotris's flaps are wedges grown out of the rear bumper and the front arch
# flares (thick at the top, a curved point at the bottom from the side). Before decimation their faces (centre in
# FLAP_CUT, Body_plastique, either side) go from the body; after it each flap comes back as a flat closed plate (FLAPS:
# |x|, y, z extents, its top inside what is left of the bumper / flare), gen 7 like the other exterior details. Extents
# from kotris's flaps on body_hi (scratch flapdump: rear x 0.718-0.859, bottom z 0.279, y -1.716..-1.737 at the bottom;
# front x 0.665-0.882, bottom z 0.198-0.201, y 0.866..0.889).
FLAP_CUT = (((0.70, 0.89), (-1.80, -1.68), (0.0, 0.43)), ((0.66, 0.89), (0.83, 0.92), (0.0, 0.365)))
FLAPS = (((0.718, 0.862), (-1.735, -1.721), (0.279, 0.445)), ((0.668, 0.880), (0.872, 0.888), (0.200, 0.380)))


# kotris's tailgate lock (round 2, R2-EXT-6: "a ~2 cm dark blob over the hyphen of the gate's CR-V lettering"). kotris
# models the lock as a 1.3 cm octagonal hole through the garnish bar with a chrome cylinder in it; _drop_badges takes the
# chrome, so the hole looked into the gate (gview probe from behind: the gate card's back, trunk face 1242, at (-0.254,
# -2.006, 0.949)). The US cars carry the lock at the bar's RIGHT end (paint_pass.GATE_LOCK, painted) and the painted CR-V
# runs across this spot. A flat 12-gon of paint (Body, gen 0: it is decimated and projected like the skin, in the twin
# too) closes the hole flush with the bar: centred on the hole's walls (faces within LOCK_R of LOCK_HOLE whose normal
# lies across the bar's), radius the walls' reach + 3 mm, in the plane of the bar round it, LOCK_LIFT proud of it.
LOCK_HOLE = (-0.2535, -2.156, 1.039)
LOCK_R = 0.012               # the bar's skin round the hole is taken from this far out
LOCK_WALL = 0.009            # the hole's walls lie within this of LOCK_HOLE (the octagon is 1.3 cm across)
LOCK_DISC_MAX = 0.011        # the disc's radius never passes this (the bar is 6 cm tall)
LOCK_LIFT = 0.0004
LOCK_CUT = 0.0145            # faces whose centre lies this close to the lock's axis are the tube and its chamfer


def _gate_lock_cap(report):
    ob = bpy.data.objects.get("trunk")
    if ob is None:
        return 0
    me = ob.data
    names = [m.name if m else "?" for m in me.materials]
    if "Body" not in names:
        return 0
    C = Vector(LOCK_HOLE)
    near = [p for p in me.polygons if names[p.material_index] == "Body" and (p.center - C).length < 0.035]
    skin = [p for p in near if p.normal.y < -0.75 and LOCK_R <= (p.center - C).length]
    if not skin:
        report("  trunk      lock hole: no garnish skin round %s" % (LOCK_HOLE,))
        return 0
    nrm = sum((p.normal * p.area for p in skin), Vector()).normalized()
    d = sum(nrm.dot(p.center) * p.area for p in skin) / sum(p.area for p in skin)
    walls = [p for p in near if (p.center - C).length < LOCK_WALL and abs(p.normal.dot(nrm)) < 0.6]
    if not walls:
        report("  trunk      lock hole: no walls found at %s" % (LOCK_HOLE,))
        return 0
    wv = {i for p in walls for i in p.vertices}
    # the tube's axis through LOCK_HOLE (the wall vertices' mean sat 6 mm high: the chamfer is denser at its top)
    ctr = C - nrm * (nrm.dot(C) - d) + nrm * LOCK_LIFT              # onto the bar's plane, just proud of it
    r = min(max(((me.vertices[i].co - ctr) - nrm * (me.vertices[i].co - ctr).dot(nrm)).length for i in wv) + 0.003,
            LOCK_DISC_MAX)
    u = nrm.cross(Vector((0.0, 0.0, 1.0))).normalized()
    v = nrm.cross(u).normalized()
    mi = names.index("Body")
    # (kotris's lock is a 1 cm tube into the gate with a chamfered mouth, the chrome cylinder in it dropped as a badge):
    # every Body face within LOCK_CUT of the tube's axis goes, and the disc, its rim laid on the bar round the cut
    # (LOCK_LIFT proud), closes the opening flush with the bar
    sunk = set()
    for p in near:
        a = p.center - ctr
        if (a - nrm * a.dot(nrm)).length < LOCK_CUT:
            sunk.add(p.index)
    cut_v = {i for p in near if p.index in sunk for i in p.vertices}
    r = max([LOCK_CUT] + [((me.vertices[i].co - ctr) - nrm * (me.vertices[i].co - ctr).dot(nrm)).length for i in cut_v]) + 0.001
    rim_n = []
    rim = []
    skin_tree = BVHTree.FromPolygons([vv.co.copy() for vv in me.vertices],
                                     [list(p.vertices) for p in near if p.index not in sunk], all_triangles=False)
    for k in range(12):
        q = ctr + (u * math.cos(2 * math.pi * k / 12) + v * math.sin(2 * math.pi * k / 12)) * r
        hit, hn, _hi, _hd = skin_tree.ray_cast(q + nrm * 0.01, -nrm, 0.02)
        if hit is not None:
            q = hit + nrm * LOCK_LIFT
        rim.append(q)
        rim_n.append(hn.normalized() if hit is not None and hn.dot(nrm) > 0 else nrm.copy())
    ctr = sum(rim, Vector()) / len(rim)
    _delete_faces(ob, sorted(sunk))
    before = [tuple(c.vector) for c in me.corner_normals]
    n_old = len(me.polygons)
    bm = bmesh.new()
    bm.from_mesh(me)
    cv = bm.verts.new(ctr)
    ring = [bm.verts.new(q) for q in rim]
    for k in range(12):
        f = bm.faces.new((cv, ring[k], ring[(k + 1) % 12]))
        f.normal_update()
        if f.normal.dot(nrm) < 0:
            f.normal_flip()
        f.material_index = mi
        f.smooth = True
    bm.to_mesh(me)
    bm.free()
    me.update()
    # one normal over the disc, the mean of the skin's under its rim (per-corner normals lit it as a cone)
    mean_n = tuple(sum(rim_n, Vector()).normalized())
    normals = list(before) + [None] * (len(me.loops) - len(before))
    for pg in me.polygons[n_old:]:
        for li in pg.loop_indices:
            normals[li] = mean_n
    if len(normals) == len(me.loops) and all(x is not None for x in normals):
        me.normals_split_custom_set(normals)
    report("  trunk      lock hole: %d cup faces removed, closed by a %.1f cm disc of paint at (%.3f, %.3f, %.3f)"
           % (len(sunk), r * 200, ctr.x, ctr.y, ctr.z))
    return 1


def _flap_strip(report):
    ob = bpy.data.objects.get("body")
    if ob is None:
        return 0
    me = ob.data
    names = [m.name if m else "?" for m in me.materials]
    kill = []
    for p in me.polygons:
        if names[p.material_index] != "Body_plastique":
            continue
        c = p.center
        for (x0, x1), (y0, y1), (z0, z1) in FLAP_CUT:
            if x0 <= abs(c.x) <= x1 and y0 <= c.y <= y1 and z0 <= c.z <= z1:
                kill.append(p.index)
                break
    if kill:
        _delete_faces(ob, kill)
    report("  body       mud flaps: %d kotris flap faces removed (square plates built after decimation)" % len(kill))
    return len(kill)


def _flap_build(report):
    ob = bpy.data.objects.get("body")
    if ob is None:
        return 0
    me = ob.data
    mi = _mat_index(me, "Body_plastique")
    before = [tuple(c.vector) for c in me.corner_normals]
    n_old = len(me.polygons)
    bm = bmesh.new()
    bm.from_mesh(me)
    n = 0
    for (x0, x1), (y0, y1), (z0, z1) in FLAPS:
        for side in (-1, 1):
            _bm_box(bm, mi, min(side * x0, side * x1), max(side * x0, side * x1), y0, y1, z0, z1, gen=7)
            n += 1
    bm.to_mesh(me)
    bm.free()
    me.update()
    normals = list(before) + [None] * (len(me.loops) - len(before))
    for pg in me.polygons[n_old:]:
        for li in pg.loop_indices:
            normals[li] = tuple(pg.normal)
    if len(normals) == len(me.loops) and all(v is not None for v in normals):
        me.normals_split_custom_set(normals)
    report("  body       mud flaps: %d flat plates (%d faces), square bottoms at z %s" % (len(FLAPS) * 2, len(me.polygons) - n_old,
                                                                                         ", ".join("%.3f" % f[2][0] for f in FLAPS)))
    return n


def _grille_w(z):
    t = (z - GRILLE_Z[0]) / (GRILLE_Z[1] - GRILLE_Z[0])
    return GRILLE_W[0] + (GRILLE_W[1] - GRILLE_W[0]) * t


def _grille_front(x, z):
    """y of a slat's front at (x, z): leaning back with height like kotris's slats, curving back to the ends."""
    return 2.012 + (0.83 - z) * 0.42 - 0.29 * x * x


def _grille_strip(report):
    ob = bpy.data.objects.get("body")
    if ob is None:
        return 0
    me = ob.data
    names = [m.name if m else "?" for m in me.materials]
    gm = {i for i, n in enumerate(names) if n in GRILLE_MATS}
    kill = set()
    for p in me.polygons:
        if p.material_index not in gm:
            continue
        c = p.center
        if not (GRILLE_Y[0] <= c.y <= GRILLE_Y[1] and GRILLE_Z[0] - 0.003 <= c.z <= GRILLE_Z[1] + 0.006):
            continue
        w = _grille_w(min(max(c.z, GRILLE_Z[0]), GRILLE_Z[1]))
        dark = names[p.material_index] == "Partie_noir"
        if abs(c.x) <= w + (0.012 if dark else 0.004):
            kill.add(p.index)
    lip = 0
    for p in me.polygons:                                # the lower lip's top with the fifth slat's stubs (GRILLE_LIP)
        c = p.center
        if p.material_index in gm and abs(c.x) <= GRILLE_LIP[0] and GRILLE_LIP[1][0] <= c.z < GRILLE_LIP[1][1] \
                and GRILLE_Y[0] <= c.y <= GRILLE_Y[1] and p.index not in kill:
            kill.add(p.index)
            lip += 1
    shreds = 0
    for faces, lo, hi, _maj, mats in build_details.islands(ob):
        if len(faces) < GRILLE_SHRED and mats <= set(GRILLE_MATS) and max(abs(lo.x), abs(hi.x)) < 0.36 \
                and lo.y > 1.94 and hi.y < 2.05 and lo.z > 0.72 and hi.z < 0.875:
            kill.update(faces)
            shreds += len(faces)
    if kill:
        _delete_faces(ob, sorted(kill))
    report("  body       grille: %d faces inside the frame removed (%d of them loose shreds, %d the lower lip's top), rebuilt "
           "after decimation" % (len(kill), shreds, lip))
    return len(kill)


def _grille_build(report):
    """The back plate (SeamBack, gen 5) and GRILLE_SLATS slats (Body_plastique, gen 7: baked flat) on the low body."""
    ob = bpy.data.objects.get("body")
    if ob is None:
        return 0
    me = ob.data
    ps = _mat_index(me, "Body_plastique")
    pd = _mat_index(me, "SeamBack", _seamback_material)
    before = [tuple(c.vector) for c in me.corner_normals]
    n_old = len(me.polygons)
    bm = bmesh.new()
    bm.from_mesh(me)
    gl = _gen_layer(bm)
    made = []                                         # (face, outward direction)

    def quad(pts, mi, gen, out):
        f = bm.faces.new([bm.verts.new(p) for p in pts])
        f.material_index = mi
        f.smooth = False
        f[gl] = gen
        made.append((f, Vector(out)))
    # the plate reaches well past the opening: through the gaps at the slats' ends and under the lowest slat the
    # 30-degree camera looks down and back, past a plate cut to the opening, onto the radiator (rebuild probe)
    z0, z1 = GRILLE_Z[0] - 0.06, GRILLE_Z[1] + 0.004
    w0, w1 = _grille_w(GRILLE_Z[0]) + 0.045, _grille_w(z1) + 0.035
    y = GRILLE_PLATE_Y
    quad([(-w0, y, z0), (w0, y, z0), (w1, y, z1), (-w1, y, z1)], pd, 5, (0, 1, 0))
    h = GRILLE_SLAT_H
    g = (GRILLE_Z[1] - GRILLE_Z[0] - GRILLE_SLATS * h) / (GRILLE_SLATS + 1)
    for k in range(GRILLE_SLATS):
        zt = GRILLE_Z[1] - g - k * (h + g)
        zb = zt - h
        half = _grille_w(zt - h / 2) + GRILLE_TUCK
        xs = [-half + 2 * half * i / GRILLE_SEG for i in range(GRILLE_SEG + 1)]
        top = [(x, _grille_front(x, zt), zt) for x in xs]
        bot = [(x, _grille_front(x, zb), zb) for x in xs]
        topb = [(x, yy - GRILLE_SLAT_D, z) for x, yy, z in top]
        botb = [(x, yy - GRILLE_SLAT_D, z) for x, yy, z in bot]
        for i in range(GRILLE_SEG):
            quad([bot[i], bot[i + 1], top[i + 1], top[i]], ps, 7, (0, 1, 0))           # front
            quad([top[i], top[i + 1], topb[i + 1], topb[i]], ps, 7, (0, 0, 1))         # top
            quad([botb[i], botb[i + 1], bot[i + 1], bot[i]], ps, 7, (0, 0, -1))        # underside
        for e, sx in ((0, -1), (GRILLE_SEG, 1)):                                          # end caps (behind the frame)
            quad([bot[e], top[e], topb[e], botb[e]], ps, 7, (sx, 0, 0))
    # the lower lip's straight top (GRILLE_LIP / GRILLE_BAR_*): front, top back to the ledge, end caps
    zt, zb = GRILLE_Z[0], GRILLE_Z[0] - GRILLE_BAR_H
    xs = [-GRILLE_BAR_W + 2 * GRILLE_BAR_W * i / GRILLE_SEG for i in range(GRILLE_SEG + 1)]
    fy = [GRILLE_BAR_Y - 0.15 * x * x for x in xs]
    for i in range(GRILLE_SEG):
        x0, x1, y0, y1 = xs[i], xs[i + 1], fy[i], fy[i + 1]
        quad([(x0, y0, zb), (x1, y1, zb), (x1, y1, zt), (x0, y0, zt)], ps, 7, (0, 1, 0))
        quad([(x0, y0, zt), (x1, y1, zt), (x1, GRILLE_BAR_BACK, zt), (x0, GRILLE_BAR_BACK, zt)], ps, 7, (0, 0, 1))
    for e, sx in ((0, -1), (GRILLE_SEG, 1)):
        quad([(xs[e], fy[e], zb), (xs[e], fy[e], zt), (xs[e], GRILLE_BAR_BACK, zt), (xs[e], GRILLE_BAR_BACK, zb)], ps, 7, (sx, 0, 0))
    bm.normal_update()
    for f, out in made:
        if f.normal.dot(out) < 0:
            f.normal_flip()
    bm.to_mesh(me)
    bm.free()
    me.update()
    normals = list(before) + [None] * (len(me.loops) - len(before))
    for pg in me.polygons[n_old:]:
        for li in pg.loop_indices:
            normals[li] = tuple(pg.normal)
    if len(normals) == len(me.loops) and all(v is not None for v in normals):
        me.normals_split_custom_set(normals)
    report("  body       grille: back plate + %d slats (%d faces), slat %.0f mm, gap %.1f mm" % (GRILLE_SLATS, len(made),
                                                                                                 h * 1000, g * 1000))
    return len(made)


# The hood's leading edge (EXT-15, HOOD_EDGE_*). The skin round the edge is mapped to an unrolled plane (x, v): v is the
# arc length from the nose crease along the full-detail skin's profile in the plane x = const, measured on _he_table's
# columns (every _HE_DX): rays from a pivot under the roll (5 cm behind the crease, 40 % of the way up to the skin)
# onto hood_hi's Body faces every half degree, from the top of the hood round the nose to the outline.
_HE_DX = 0.01
_HE_R = 0.45                  # ray length from the pivot


def _he_table(hi):
    me = hi.data
    names = [m.name if m else "?" for m in me.materials]
    M = hi.matrix_world
    tree = BVHTree.FromPolygons([M @ v.co for v in me.vertices],
                                [list(p.vertices) for p in me.polygons if names[p.material_index] == HOOD_EDGE_MAT],
                                all_triangles=False)
    cols = {}
    n = int(round((HOOD_EDGE_X + 0.06) / _HE_DX))
    for i in range(-n, n + 1):
        x = i * _HE_DX
        best = None                                     # the crease: the skin's front-most point at this x
        for k in range(90):
            hit = tree.ray_cast(Vector((x, 2.6, 0.84 + 0.002 * k)), Vector((0, -1, 0)), 2.0)
            if hit[0] is not None and (best is None or hit[0].y > best.y + 1e-6):
                best = hit[0].copy()
        if best is None:
            continue
        top = tree.ray_cast(Vector((x, best.y - 0.05, 1.6)), Vector((0, 0, -1)), 1.5)[0]
        if top is None:
            continue
        piv = Vector((x, best.y - 0.05, best.z + 0.4 * (top.z - best.z)))
        th_f = math.degrees(math.atan2(best.z - piv.z, best.y - piv.y))
        samples = []
        th = 165.0
        while th > -120.0:                              # from the top round the nose, to the outline (the first miss)
            d = Vector((0.0, math.cos(math.radians(th)), math.sin(math.radians(th))))
            hit = tree.ray_cast(piv + d * _HE_R, -d, _HE_R)
            if hit[0] is not None:
                samples.append((th, hit[0].copy()))
            elif samples:
                break
            th -= 0.5
        if len(samples) < 10:
            continue
        samples.reverse()                               # theta ascending: from the outline up the roll
        arc = [0.0]
        for (_a, p), (_b, q) in zip(samples, samples[1:]):
            arc.append(arc[-1] + (q - p).length)
        a0 = arc[min(range(len(samples)), key=lambda k: abs(samples[k][0] - th_f))]
        cols[i] = (piv, [(t, p, a - a0) for (t, p), a in zip(samples, arc)])
    return tree, cols


def _he_lerp(xs, ys, x):
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    lo, up = 0, len(xs) - 1
    while up - lo > 1:
        m = (lo + up) // 2
        if xs[m] <= x:
            lo = m
        else:
            up = m
    return ys[lo] + (ys[up] - ys[lo]) * (x - xs[lo]) / max(1e-12, xs[up] - xs[lo])


def _he_col_v(col, th):
    """Arc of the profile point at theta, extrapolated (radius x angle) past the profile's ends."""
    piv, s = col
    if th > s[-1][0]:
        return s[-1][2] + math.radians(th - s[-1][0]) * (s[-1][1] - piv).length
    if th < s[0][0]:
        return s[0][2] - math.radians(s[0][0] - th) * (s[0][1] - piv).length
    return _he_lerp([a for a, _p, _v in s], [v for _a, _p, v in s], th)


def _he_cols_at(cols, x):
    i0 = math.floor(x / _HE_DX)
    t = x / _HE_DX - i0
    a, b = cols.get(i0), cols.get(i0 + 1)
    if a is None or b is None:
        return [(a or b, 1.0)] if (a or b) else None
    return [(a, 1.0 - t), (b, t)]


def _he_to2d(cols, p):
    cs = _he_cols_at(cols, p.x)
    if cs is None:
        return None
    return (p.x, sum(w * _he_col_v(col, math.degrees(math.atan2(p.z - col[0].z, p.y - col[0].y))) for col, w in cs))


def _he_to3d(tree, cols, x, v):
    cs = _he_cols_at(cols, x)
    if cs is None:
        return None
    th = sum(w * _he_lerp([w_ for _a, _p, w_ in col[1]], [a for a, _p, _w in col[1]], v) for col, w in cs)
    piv = sum((col[0] * w for col, w in cs), Vector())
    piv.x = x
    d = Vector((0.0, math.cos(math.radians(th)), math.sin(math.radians(th))))
    hit = tree.ray_cast(piv + d * _HE_R, -d, _HE_R)
    return hit[0].copy() if hit[0] is not None else None


def _he_pip(pt, poly):
    x, y = pt
    inside = False
    for i in range(len(poly)):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % len(poly)]
        if (y1 > y) != (y2 > y) and x1 + (y - y1) * (x2 - x1) / (y2 - y1) > x:
            inside = not inside
    return inside


def _he_segd(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = dx * dx + dy * dy
    t = 0.0 if L < 1e-18 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L))
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


def _he_cross(p, q, a, b):
    """Do segments p-q and a-b cross (touching ends excluded)?"""
    def orient(u, v, w):
        return (v[0] - u[0]) * (w[1] - u[1]) - (v[1] - u[1]) * (w[0] - u[0])
    return orient(a, b, p) * orient(a, b, q) < 0 and orient(p, q, a) * orient(p, q, b) < 0


def _he_largest(faces):
    """The largest edge-connected piece of a face list."""
    left = set(faces)
    best = []
    while left:
        f0 = left.pop()
        comp, st = [f0], [f0]
        while st:
            g = st.pop()
            for e in g.edges:
                for h in e.link_faces:
                    if h in left:
                        left.discard(h)
                        comp.append(h)
                        st.append(h)
        if len(comp) > len(best):
            best = comp
    return best


def _he_boundary(faces):
    """{vertex: [neighbours along the region's boundary]} (edges with exactly one region face)."""
    rset = set(faces)
    adj = {}
    for e in {e for f in faces for e in f.edges}:
        if sum(1 for g in e.link_faces if g in rset) == 1:
            a, b = e.verts
            adj.setdefault(a, []).append(b)
            adj.setdefault(b, []).append(a)
    return adj


def _he_fans(v, rset):
    """The region's faces round v, grouped into fans joined across edges at v."""
    left = [f for f in v.link_faces if f in rset]
    fans = []
    while left:
        fan = [left.pop()]
        st = [fan[0]]
        while st:
            g = st.pop()
            for e in g.edges:
                if v in e.verts:
                    for h in e.link_faces:
                        if h in left:
                            left.remove(h)
                            fan.append(h)
                            st.append(h)
        fans.append(fan)
    return fans


def _hood_edge(ob, hi, report):
    """EXT-15: the decimated hood's leading edge replaced by a clean grid on the full-detail skin (HOOD_EDGE_*).
    Returns the rebuilt faces' indices (for _hood_edge_normals), or None when it left the edge as decimated."""
    from mathutils import geometry as mgeo
    tree, cols = _he_table(hi)
    me = ob.data
    names = [m.name if m else "?" for m in me.materials]
    if HOOD_EDGE_MAT not in names or not cols:
        report("  hood       leading edge: no %s skin / profile, left as decimated" % HOOD_EDGE_MAT)
        return None
    mi = names.index(HOOD_EDGE_MAT)
    bm = bmesh.new()
    bm.from_mesh(me)
    tag = bm.faces.layers.int.new(HOOD_EDGE_TAG)     # bmesh reuses freed face slots: the new faces are no index range
    gl = bm.faces.layers.int.get(GEN)
    uv2 = {}
    for v in bm.verts:
        q = _he_to2d(cols, v.co)
        if q is not None:
            uv2[v] = q

    def in_band(v):
        q = uv2.get(v)
        return q is not None and abs(q[0]) <= HOOD_EDGE_X and -0.06 < q[1] < HOOD_EDGE_CUT
    region = [f for f in bm.faces if f.material_index == mi and (gl is None or f[gl] == 0)
              and any(in_band(v) for v in f.verts) and all(v in uv2 for v in f.verts)]
    if not region:
        report("  hood       leading edge: no skin in the band, left as decimated")
        bm.free()
        return None
    bmesh.ops.remove_doubles(bm, verts=list({v for f in region for v in f.verts}), dist=1e-5)   # kotris's duplicates
    region = _he_largest([f for f in region if f.is_valid])
    adj = {}
    for _it in range(8):                                # one simple boundary loop
        rset = set(region)
        adj = _he_boundary(region)
        bad = [v for v, nb in adj.items() if len(nb) != 2]
        if not bad:
            break
        # the region touching itself at a vertex: take in the skin round it ...
        grow = list(dict.fromkeys(f for v in bad for f in v.link_faces
                                  if f not in rset and f.material_index == mi and (gl is None or f[gl] == 0)))
        if grow:
            region = _he_largest(region + grow)
            continue
        # ... or, where the hood's own outline pinches (two fans of skin meet at one corner: (+-0.509, 1.880, 0.892)),
        # keep the fan reaching furthest into the band
        for v in bad:
            fans = sorted(_he_fans(v, rset), key=lambda fan: -sum(1 for f in fan for w in f.verts if in_band(w)))
            for fan in fans[1:]:
                rset.difference_update(fan)
        region = _he_largest([f for f in region if f in rset])
    loops, seen = [], set()
    if all(len(nb) == 2 for nb in adj.values()):
        for v0 in adj:
            if v0 in seen:
                continue
            loop, prev, cur = [v0], None, v0
            seen.add(v0)
            while True:
                nxt = next((w for w in adj[cur] if w is not prev), None)
                if nxt is None or nxt is v0:
                    break
                loop.append(nxt)
                seen.add(nxt)
                prev, cur = cur, nxt
            loops.append(loop)
    if len(loops) != 1:
        report("  hood       leading edge: the band's boundary is %s, left as decimated"
               % ("%d loops" % len(loops) if loops else "not a simple loop"))
        bm.free()
        return None
    loop = loops[0]
    n = int(math.floor(HOOD_EDGE_X / HOOD_EDGE_COL))
    xs = [i * HOOD_EDGE_X / n for i in range(-n, n + 1)]
    # the ring: the loop, with points added along its OPEN edges (the hood's outline: nothing on the other side) where
    # they cross a grid column or run longer than one, so the under-lip lines up with the grid
    ring = []                                   # BMVert, or (Vector, (x, v)) for a new outline point
    for j, a in enumerate(loop):
        b = loop[(j + 1) % len(loop)]
        ring.append(a)
        e = bm.edges.get((a, b))
        if e is None or len(e.link_faces) != 1:
            continue
        ts = [(x - a.co.x) / (b.co.x - a.co.x) for x in xs
              if abs(b.co.x - a.co.x) > 1e-6 and min(a.co.x, b.co.x) + 0.01 < x < max(a.co.x, b.co.x) - 0.01]
        L = (b.co - a.co).length
        if not ts and L > HOOD_EDGE_COL * 1.2:
            k = int(math.ceil(L / HOOD_EDGE_COL))
            ts = [i / k for i in range(1, k)]
        ua, ub = uv2[a], uv2[b]
        for t in sorted(ts):
            ring.append((a.co.lerp(b.co, t), (ua[0] + (ub[0] - ua[0]) * t, ua[1] + (ub[1] - ua[1]) * t)))
    poly = [r[1] if isinstance(r, tuple) else uv2[r] for r in ring]
    grid = {}
    pts2 = list(poly)
    for i, x in enumerate(xs):
        for k, v in enumerate(HOOD_EDGE_ROWS):
            q = (x, v)
            if _he_pip(q, poly) and min(_he_segd(q, poly[j], poly[(j + 1) % len(poly)])
                                        for j in range(len(poly))) >= HOOD_EDGE_MARGIN:
                grid[(i, k)] = len(pts2)
                pts2.append(q)
    # constraints: the hole's outline, and the grid's rows and columns wherever a segment stays clear of it (a crossing
    # would put a vertex on a hole edge another face shares). The rows keep every triangle on one side of the nose
    # crease (row 0): one spanning it from the under-lip to the front face cut a dark notch into the edge. The full
    # triangulation is filtered by the outline here: output type 2 decides "inside" by crossing parity, and the closed
    # grid cells came out alternately in and out. v is arc length and x metres: near isotropic triangles.
    edges = [(j, (j + 1) % len(poly)) for j in range(len(poly))]
    segs = [(poly[j], poly[(j + 1) % len(poly)]) for j in range(len(poly))]
    for (i, k), idx in grid.items():
        for nb in ((i + 1, k), (i, k + 1)):
            if nb in grid and not any(_he_cross(pts2[idx], pts2[grid[nb]], a, b) for a, b in segs):
                edges.append((idx, grid[nb]))
    o_verts, _oe, o_faces, o_orig, _o2, _o3 = mgeo.delaunay_2d_cdt([Vector(p) for p in pts2], edges, [], 0, 1e-7, True)
    o_faces = [f for f in o_faces if _he_pip(tuple(sum((o_verts[i] for i in f), Vector((0.0, 0.0))) / len(f)), poly)]
    # the region goes (faces, then the edges and vertices only it used; bmesh.ops.delete on the edges would take the
    # outline's vertices with them), then the grid is built in its place
    r_edges = {e for f in region for e in f.edges}
    inner = {v for f in region for v in f.verts} - set(loop)
    bmesh.ops.delete(bm, geom=region, context='FACES_ONLY')
    for e in [e for e in r_edges if e.is_valid and not e.link_faces]:
        bm.edges.remove(e)
    bmesh.ops.delete(bm, geom=[v for v in inner if v.is_valid and not v.link_faces], context='VERTS')
    ring_v = [bm.verts.new(r[0]) if isinstance(r, tuple) else r for r in ring]
    vmap = {}
    missed = 0
    for oi, co in enumerate(o_verts):
        orig = [j for j in o_orig[oi] if j < len(poly)]
        if orig:
            vmap[oi] = ring_v[orig[0]]
            continue
        p = _he_to3d(tree, cols, co.x, co.y)
        if p is None:                                   # (never seen: the nearest ring vertex's place)
            missed += 1
            p = ring_v[min(range(len(poly)), key=lambda k: (poly[k][0] - co.x) ** 2 + (poly[k][1] - co.y) ** 2)].co.copy()
        vmap[oi] = bm.verts.new(p)
    made = 0
    for f in o_faces:
        vv = [vmap[i] for i in f]
        if len(set(vv)) < 3:
            continue
        try:
            nf = bm.faces.new(vv)
        except ValueError:
            continue
        nf.material_index = mi
        nf.smooth = True
        nf.normal_update()
        c = nf.calc_center_median()
        cs = _he_cols_at(cols, c.x)
        piv = sum((col[0] * w for col, w in cs), Vector()) if cs else Vector((c.x, 1.9, 0.9))
        if nf.normal.dot(c - Vector((c.x, piv.y, piv.z))) < 0:     # outward, away from the pivot under the roll
            nf.normal_flip()
        if gl is not None:
            nf[gl] = 0
        nf[tag] = 1
        made += 1
    bm.to_mesh(me)
    bm.free()
    me.update()
    att = me.attributes.get(HOOD_EDGE_TAG)
    vals = [0] * len(me.polygons)
    att.data.foreach_get("value", vals)
    me.attributes.remove(att)
    report("  hood       leading edge: %d decimated faces in the band (%d boundary vertices, %d added along the outline) "
           "rebuilt as %d faces: %d grid points on %d columns x %d rows on the full-detail skin (%d missed)"
           % (len(region), len(loop), len(ring) - len(loop), made, len(grid), len(xs), len(HOOD_EDGE_ROWS), missed))
    return [i for i, k in enumerate(vals) if k]


def _hood_edge_normals(ob, faces, smooth_deg=40.0):
    """Custom normals of the rebuilt edge (after transfer_normals) from the grid's own faces, grouped within smooth_deg
    like lowpoly.smooth_normals: the grid lies on the full-detail skin, and that skin's smoothed normals, sampled near
    the crease, bent the crease corners down (light lumps along the edge). Every other corner keeps its normal."""
    me = ob.data
    cos_s = math.cos(math.radians(smooth_deg))
    cur = [Vector(c.vector) for c in me.corner_normals]
    by_vert = {}
    for p in (me.polygons[i] for i in faces):
        for li in p.loop_indices:
            by_vert.setdefault(me.loops[li].vertex_index, []).append((li, p))
    for lis in by_vert.values():
        groups = []
        for li, p in lis:
            for g in groups:
                if g[0][1].normal.dot(p.normal) >= cos_s:
                    g.append((li, p))
                    break
            else:
                groups.append([(li, p)])
        for g in groups:
            acc = sum((p.normal * max(p.area, 1e-10) for _li, p in g), Vector())
            nrm = acc.normalized() if acc.length > 1e-12 else g[0][1].normal.copy()
            for li, _p in g:
                cur[li] = nrm
    me.normals_split_custom_set([tuple(n) for n in cur])


# The front bumper's corners (2026-10-17 review EXT-10): two bay-wall boxes, fitted to the full-detail body, poke
# through the decimated bumper as thin black fins: the undertray's front corners (|x| 0.66, y 1.99, z 0.55) and the
# dark corner boxes under the headlamps (|x| 0.70, y 1.87, z 0.73). After build_liners' refit every bay-wall vertex
# in this region that lies in front of the low body's nearest face moves to TUCK_GAP behind it; the rest stay (a
# corner pulled further opened slits under the bumper). (|x|, y, z of the vertex.)
TUCK_BOX = ((0.50, 0.90), (1.70, 2.10), (0.50, 0.78))
TUCK_GAP = 0.003
TUCK_REACH = 0.06             # only vertices this close to the skin: further out is not a poke-through


def _tuck_bay_walls(report):
    walls = bpy.data.objects.get("bay_walls")
    body = bpy.data.objects.get("body")
    if walls is None or body is None:
        return 0
    bme = body.data
    ga = bme.attributes.get(GEN)
    gv = [0] * len(bme.polygons)
    if ga is not None:
        ga.data.foreach_get("value", gv)
    M = body.matrix_world
    tree = BVHTree.FromPolygons([M @ v.co for v in bme.vertices], [list(p.vertices) for p in bme.polygons if gv[p.index] == 0],
                                all_triangles=False)
    (x0, x1), (y0, y1), (z0, z1) = TUCK_BOX
    W = walls.matrix_world
    Wi = W.inverted()
    moved = 0
    worst = 0.0
    for v in walls.data.vertices:
        p = W @ v.co
        if not (x0 <= abs(p.x) <= x1 and y0 <= p.y <= y1 and z0 <= p.z <= z1):
            continue
        loc, n, _i, d = tree.find_nearest(p)
        if loc is None or d > TUCK_REACH:
            continue
        s = (p - loc).dot(n)
        if s > 0.0:
            v.co = Wi @ (loc - n * TUCK_GAP)
            moved += 1
            worst = max(worst, s + TUCK_GAP)
    walls.data.update()
    report("  bay_walls  bumper corners: %d vertices tucked %.0f mm behind the low body (max move %.1f mm)"
           % (moved, TUCK_GAP * 1000, worst * 1000))
    return moved


# The front wheelhouses' tops (round 2, R2-BAY-5): kotris's wheelhouse box (body, Dessous: its ring faces and an inboard
# wall at |x| 0.536, y 0.89-1.72, z 0.37-0.78) and the arch liners' barrel, clipped at refit to the first thing the
# skin ray met through the arch opening (that same box: |x| 0.516 at y 1.40-1.74), reach 4-6 cm inboard of the bay's
# aprons (bay_walls, |x| 0.575) and poke through them into the bay as a black sliver at (+-0.52, 1.48, 0.76) and a
# strip at z 0.65-0.78. Every such vertex in ARCH_BOX inboard of APRON_X moves out to it, behind the apron (the
# liner's own inboard wall, X_IN 0.56, stays: only its clipped outer ring is inboard of that).
ARCH_BOX = ((0.45, 0.578), (0.88, 1.80), (0.35, 0.85))       # |x|, y, z of a vertex
APRON_X = 0.578
ARCH_LINER_X = 0.556          # liner vertices inboard of this are the clipped outer ring (the inner wall is at 0.56)


def _tuck_arch_tops(report):
    out = []
    for name, mats, xmax in (("body", ("Dessous",), ARCH_BOX[0][1]), ("arch_liners", None, ARCH_LINER_X)):
        ob = bpy.data.objects.get(name)
        if ob is None:
            continue
        me = ob.data
        names = [m.name if m else "?" for m in me.materials]
        ga = me.attributes.get(GEN)
        gv = [0] * len(me.polygons)
        if ga is not None:
            ga.data.foreach_get("value", gv)
        ok = set()
        bad = set()
        for p in me.polygons:
            (ok if (mats is None or names[p.material_index] in mats) and gv[p.index] == 0 else bad).update(p.vertices)
        M = ob.matrix_world
        Mi = M.inverted()
        (x0, _x1), (y0, y1), (z0, z1) = ARCH_BOX
        n = 0
        for i in ok - bad:
            v = me.vertices[i]
            q = M @ v.co
            if x0 <= abs(q.x) < xmax and y0 <= q.y <= y1 and z0 <= q.z <= z1:
                q.x = APRON_X if q.x > 0 else -APRON_X
                v.co = Mi @ q
                n += 1
        me.update()
        out.append("%s %d" % (name, n))
    report("  front wheelhouse tops: vertices moved out to |x| %.3f behind the aprons: %s" % (APRON_X, ", ".join(out)))
    return out


def _decimate_engine(ob, target):
    n0 = tris(ob)
    if n0 > target:
        bpy.context.view_layer.objects.active = ob
        m = ob.modifiers.new("collapse", 'DECIMATE')
        m.decimate_type = 'COLLAPSE'
        m.ratio = max(0.02, target / n0)
        m.use_collapse_triangulate = True
        with bpy.context.temp_override(active_object=ob, object=ob):
            bpy.ops.object.modifier_apply(modifier=m.name)
    return n0, tris(ob)


def prep(report=print):
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for name in PARTS + ["engine_block", "engine_block_full", "cabin", "cabin_full"]:
        ob = bpy.data.objects.get(name)
        if ob is None:
            continue
        ob.hide_set(False)
        ob.location = (0.0, 0.0, 0.0)
        ob.rotation_euler = (0.0, 0.0, 0.0)
        ob.scale = (1.0, 1.0, 1.0)
    for name in PARTS:
        ob = bpy.data.objects.get(name)
        if ob is not None:
            n = _drop_badges(ob)
            if n:
                report("  %-10s badges -%d faces" % (name, n))
    _gate_lock_cap(report)                                              # kotris's lock hole under the CR-V lettering
    _move_trim(report)
    _strip_furniture(report)                                            # build_cabin's cabin replaces it
    _drop_belt_rail(report)                                             # before the _hi twins: gone from both
    _grille_strip(report)                                               # the grille's slats and end debris (rebuilt below)
    _flap_strip(report)                                                 # kotris's tapered mud flaps (square plates below)
    for name in ("wheel_FR", "wheel_FL", "wheel_RR", "wheel_RL"):      # kotris hub pieces off (high)
        ob = bpy.data.objects.get(name)
        if ob is not None:
            k = _clear_hub(ob)
            report("  %-10s hub: %d kotris cap/lug faces cleared" % (name, k))
    global SEAMS
    shell_parts = [bpy.data.objects[n] for n in ("body", "hood", "door_fl", "door_fr", "door_rl", "door_rr",
                                                  "trunk", "trunk_top", "window_fl", "window_fr", "window_rl", "window_rr")
                   if bpy.data.objects.get(n) is not None]
    SEAMS, n_seam = lowpoly.seam_points(shell_parts)
    report("  seams: %d outline vertices meet another panel (held to %d mm)" % (n_seam, round(lowpoly.SEAM_TOL * 1000)))
    for name, budget in BUDGET.items():                                 # v6: low poly + _hi twins
        _make_low(name, budget, report)
    for name, box in DROP_BOX.items():                                  # the decimated copy can re-grow it
        if bpy.data.objects.get(name) is not None:
            _drop_box(bpy.data.objects[name], box)
    _lamp_surround(report)
    for name in ("door_fl", "door_fr", "door_rl", "door_rr"):
        _door_plate(name, report)
    # the liners, antenna base and bay walls were fitted to the full-detail body: refit to the low one
    liners = os.path.join(os.path.dirname(os.path.abspath(lowpoly.__file__)), "build_liners.py")
    exec(compile(open(liners, encoding="utf-8").read(), "build_liners", "exec"), {"__name__": "refit"})
    _tuck_bay_walls(report)                                             # the boxes that poked through the bumper corners
    _tuck_arch_tops(report)                                             # front wheelhouse tops back behind the aprons
    _grille_build(report)                                               # back plate + four slats in kotris's frame
    _flap_build(report)                                                 # flat mud flaps with square bottoms
    # v6 optimisation: doors and hood get no Solidify shell any more; export's backfill.py gives them
    # a back face exactly where the game camera can see their inside (KI5 builds 178-tri doors that
    # way). The tailgate keeps its shell: its inside is the trim panel, not paint.
    for name in SOLIDIFY_PARTS:
        ob = bpy.data.objects.get(name)
        if ob is not None:
            # tailgate: painted inner shell; the trim panel is a flat card over it (_gate_plate),
            # as on the doors. (kotris's flat rear wall stood up to 18 cm off the curved gate and
            # hung beside it when open, so it was deleted; a fabric-lined shell copied the skin's
            # holes and read as mottled concrete in game.)
            k = _solidify(ob, shell_mat=None, strips=name.startswith("door"))
            hidden = 0          # _prune_shell_behind_trim deleted shell the trim card does not reach
                                # (the door bottoms): see-through doors when open. Not run since.
            report("  %-10s solidify: %d shell+rim faces, %d hidden behind its trim removed" % (name, k, hidden))
    _gate_plate(report)
    _door_lips(report)
    _sill_strips(report)
    _aperture_paint(report)                                             # painted pillar shut faces (copies)
    # exterior details on the low panels (gen 7). Before any seam backing: the kotris islands it
    # deletes (handles, mirrors, flap skin, roof stub, wiper slivers) must not get plates behind them
    build_details.build(report)
    _sail_backing(report)                                               # the front doors' sails closed on the cabin side
    _belt_seal(report)                                                  # the slit between belt skin and glass bottom
    _gate_hinges(report)                                                # after the gate's solidify: closed boxes
    _gate_clearance(report)                                             # the gate's bottom clear of the bumper's step and lip
    for name in ("body", "trunk_top"):                                  # before the plates copy the shells
        _close_pane_cracks(name, report)
    for name in ("body", "trunk", "trunk_top", "door_fl", "door_fr", "door_rl", "door_rr", "hood",
                 "window_fl", "window_fr", "window_rl", "window_rr"):     # the door glass is its own object
        _island_backing(name, report)
    body_ob = bpy.data.objects.get("body")
    n_before = len(body_ob.data.polygons) if body_ob is not None else 0
    _gutter_strips("body", report)
    strips = set(range(n_before, len(body_ob.data.polygons))) if body_ob is not None else set()
    rear_strips = {i for i in strips if body_ob.data.polygons[i].center.y < TUCK_STRIP_Y}
    _tuck_plates_behind_trim(report, skip=rear_strips, strips=strips)   # the windscreen ring and the front strips out of the
                                                                        # cabin (not the rear strips: one at the hatch opened a slit)
    it = bpy.data.objects.get("interior")
    if it is not None:
        report("  interior closures: %d housing slices" % _interior_closures(it))
        build_cabin.carve_footwells(report, it)                         # where the seated passengers' soles land
        _cargo_lining(report)                                           # the cargo's rear corners beside the lamps
    _prune(report)
    total = 0
    for name in PARTS + ["engine_block", "cabin"]:
        ob = bpy.data.objects.get(name)
        if ob is not None:
            t = tris(ob)
            total += t
            report("  %-12s %6d tris" % (name, t))
    report("TOTAL %d tris (four wheels in scene, one exported)" % total)
    return total


prep()
