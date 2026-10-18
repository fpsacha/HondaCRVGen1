r"""
Accessories for the CR-V: a bull bar, a roof rack basket and steel window guards (windscreen, the
four door windows, the flip-up rear glass). Built after prep_parts from the LOW parts, so they
follow the glass outlines, the bumper and the roof that ship.

    blender -b blender\import\parts_kotris.blend --python scripts\build_accessories.py -- --save

Shapes follow the real parts (2026-10-11 pass):
  * bull bar: the 3-inch tube bars sold for the 97-01 CR-V (a wide hoop with big-radius top
    corners, legs that bend back under the bumper, a slotted skid plate) plus the brush-guard
    extras: two grille bars, closed cages around the headlamps, and two driving lamps on top whose
    lenses light with the headlights;
  * roof rack: a Yakima LoadWarrior-type basket: round tube, a floor of close-set tubes that curve
    up at the front, a wind fairing, clamped to two crossbars on towers at the roof edge;
  * window guards: welded flat-bar frames standing on short tabs over the sash, round vertical bars,
    one or two cross bars, gusset plates in the corners (police window-bar sets).

Every accessory is one object 'acc_*' with ten materials: AccSteel (powder-coated tube and bar),
AccPlate (bare plates: fairing, tabs, gussets, towers), AccSkid (the skid plate, slot decal),
AccLens (the driving lamps), AccCanvas, AccTarp, AccTote, AccLid and AccStrap (the roof rack's
cargo, below), AccVinyl (the soft spare-tyre cover on the gate, build_spare_cover). They are baked
on the shell sheet (bake_atlas SPACES) but are
invisible to every other part's rays there, and backfill / holecheck ignore them: they come off in
game, so the car must not carry their shadows or rely on them to hide anything. Each piece is a
closed solid or ends inside another piece: PZ culls back faces, and the door windows roll down
behind their guards.

Roof rack cargo (2026-10-12): three fill states as three static meshes, acc_rack_load1..3, extra
`model` blocks on part CRVRoofRack that HondaCRVGen1Accessories.lua shows one at a time by the
container's weight. One duffel; duffel + tote + bedroll; duffel + tote + kit bag + bedroll under two
ratchet straps hooked to the top rails. Second pass (feedback: "the shape and the texture of the box on
the roof rack need more work"; the full state was a tarped heap that read as a blue box): the tote
is a ribbed storage tote (tapered walls, rounded corners, a lip, a mustard lid with a raised rim,
clip latches, moulded end handles, ribs), the bags have piped end panels, girth straps, a handle and
a zip, the bedroll two buckled straps. Accessories are invisible to every ray in the bake, so the
cargo carries its own ambient occlusion as the corner attribute acc_shade (_shade), multiplied into
its colour by bake_atlas TEXTURED 'attr'. Third pass (2026-10-13, feedback: "better texture ... with
more details"; screenshot 32.png showed flat colour blocks): the detail is painted (cargo_paint.py: seams,
zips, pockets, folds, ribs, label, recessed handles, the lid's stacking pads, the roll's spiral,
webbing edges, stitching, the straps' load labels) on decals pinned to model space, so the pieces
sit where cargo_paint.LAYOUT says in every state; the webbing is AccStrap (it was AccSteel, a flat
swatch on the shell sheet); the ratchet straps hook round the rails on steel J-hooks and carry a
modelled ratchet; and each face gets its texel weight from what the game camera can see of it
(_texel_weights: ~1.4 texels/cm where it looks, against ~0.7 before).

Model space: metres, +X vehicle right, +Y forward, +Z up, ground at z 0.
"""
import math
import os
import sys

import bmesh
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

import cargo_paint as CP                         # the rack cargo's layout and painted maps (run_rebuild puts
                                                 # scripts/ on sys.path; so do build_table, export_fbx, render_tile)

ROOT = os.environ.get("CRV_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(globals().get("__file__") or os.path.join("scripts", "_"))))           # run_rebuild execs this file: no __file__
BAKE_PNG = os.path.join(ROOT, "blender", "bake")
MATS = ["AccSteel", "AccPlate", "AccSkid", "AccLens", "AccCanvas", "AccTarp", "AccVinyl", "AccTote", "AccLid", "AccStrap"]
STEEL, PLATE, SKID, LENS, CANVAS, TARP, VINYL, TOTE, LID, STRAP = range(10)
COLOURS = {"AccSteel": (0.055, 0.056, 0.060), "AccPlate": (0.19, 0.19, 0.20),       # linear; the bake's
           "AccSkid": (0.19, 0.19, 0.20), "AccLens": (0.50, 0.53, 0.56),             # TEXTURED layers refine them
           "AccCanvas": (0.094, 0.098, 0.038), "AccTarp": (0.021, 0.049, 0.136),     # rack cargo: olive canvas, blue bedroll,
           "AccTote": (0.083, 0.087, 0.093), "AccLid": (0.50, 0.30, 0.023),          # charcoal tote / kit bag, mustard lid,
           "AccStrap": (0.018, 0.018, 0.019),                                        # webbing: black (the ratchet straps'
                                                                                     # orange is painted in their y bands)
           "AccVinyl": (0.030, 0.030, 0.032)}                                        # the spare cover's black vinyl
GLASS = ("Vitre", "Vitre_noir")
PREFIX = "acc_"
CAR_CENTRE = Vector((0.0, -0.10, 1.00))

# window guards: object name -> (glass source object, face filter, parts the guard must clear,
# outline). "loop": the glass's boundary loop (the windscreen: one clean sheet whose lower edge is
# concave); "hull": convex hull of the glass, for panes split into unwelded islands (the hatch glass
# walked into a U of frit band) and the door windows (convex anyway)
GUARDS = {
    "acc_guard_ws": ("body", "windscreen", ("body", "hood"), "loop"),
    "acc_guard_rear": ("trunk_top", "all", ("trunk_top", "body"), "hull"),
    "acc_guard_fl": ("window_fl", "all", ("door_fl", "body"), "hull"),
    "acc_guard_fr": ("window_fr", "all", ("door_fr", "body"), "hull"),
    "acc_guard_rl": ("window_rl", "all", ("door_rl", "body"), "hull"),
    "acc_guard_rr": ("window_rr", "all", ("door_rr", "body"), "hull"),
}
DOOR_GUARDS = {"acc_guard_fl": "door_fl", "acc_guard_fr": "door_fr",
               "acc_guard_rl": "door_rl", "acc_guard_rr": "door_rr"}     # ride the door bones
LOAD_NAMES = ["acc_rack_load1", "acc_rack_load2", "acc_rack_load3"]   # roof rack cargo states
SPARE_COVER = "acc_spare_cover"                                       # rides the gate (trunk_bone)
NAMES = ["acc_bullbar", "acc_roofrack"] + LOAD_NAMES + list(GUARDS) + [SPARE_COVER]

# guard dimensions (metres). Heights are along the glass normal.
GUARD_OUT = 0.030                      # frame centre above the glass
FRAME_W, FRAME_T = 0.030, 0.010        # flat bar on the flat
BAR_R = 0.0065                         # round bar
CROSS_W, CROSS_T = 0.020, 0.007        # flat bar on edge
FRAME_OUT = 0.012                      # frame centre line OUTSIDE the glass outline: over the rubber / sash
# ... except on the windscreen, whose wrapped sides put a frame line 1.2 cm outside the glass behind the
# A-pillars' bulge as the game camera sees it: the frame's sides vanished there and the cross bars seemed to
# run on 3-4 cm past it onto the pillars (2026-10-17 review ACC-5). Its frame runs on the glass's edge (the
# frit band), in full view.
FRAME_OUT_OF = {"acc_guard_ws": 0.0}
BAR_SPACING = {"acc_guard_ws": 0.130, "acc_guard_rear": 0.115}
# The windscreen's lower edge runs under the hood's rear edge: a guard on the whole pane put its bottom rail
# at y 1.02 m, over the hood, and the hood swung up through it (collide_check.py, 2026-10-17). The hood's
# panel never reaches behind its hinge (y 0.86 m), so the outline is clipped on the glass at GUARD_Y_MAX:
# the frame, half its width and FRAME_OUT outside that line, still ends behind 0.855 m.
GUARD_Y_MAX = {"acc_guard_ws": 0.81}
# ... which left a bare glass strip from that frame down to the wipers (7-8 cm on the centre line; 2026-10-17 review
# ACC-6). A short lower section covers it (_guard_lower, same object: it installs and comes off with the guard): a
# flat-bar frame tucked LOWER_TUCK under the main frame's bottom rail, its bottom rail LOWER_GAP above whatever
# stands proud of the glass (the wipers' park line, the cowl) or the glass's end, the main guard's vertical bars
# carried on through it, tabs on the glass at its lower corners by the A-pillar bases and in the middle. Where the
# strip is narrower than LOWER_MIN_H (toward the pillars) it ends. Every point of it stays inside the circle the
# hood's rear edge swings on about its hinge (rig_vehicle: Y/Z_HOOD_HINGE, 62 degrees), LOWER_HOOD_CLEAR inside,
# or steeper above the hinge than any hood point gets (_hood_sweep): the hood's hinge straps ride the hood and are
# in its sample, the prop rod works at the front of the bay.
GUARD_LOWER = {"acc_guard_ws"}
LOWER_W, LOWER_T = 0.020, 0.008        # the lower section's flat bar
LOWER_TUCK = 0.008                     # its top rail runs this far under the main frame's bottom rail
LOWER_GAP = 0.012                      # bottom rail's lower edge above the wipers / the cowl / the glass's end
LOWER_MIN_H = 0.024                    # rail centre to rail centre, at least (the section ends where it is less):
                                       # 4 mm of glass between the rails, toward the pillars where the strip closes
LOWER_HOOD_CLEAR = 0.015               # metres inside the hood's swing circle (radially)
LOWER_HOOD_ANGLE = 6.0                 # degrees steeper than the hood's highest point at full swing
BAR_SPACING_DEFAULT = 0.100
TAB_EVERY = 0.45                       # stand-off tab spacing along the frame
TAB_W = 0.022
GUSSET = 0.055                         # gusset plate leg
MAX_SEG = 0.22                         # longest straight piece of the frame / cross bar (follows the glass)
MAX_SEG_BAR = 0.30                     # vertical bars: the glass hardly curves top to bottom
CLEAR = 0.004                          # air between a guard and the door sash / pillar under it
BAR_INTO_FRAME = 0.012                 # bars end this far inside the frame's centre line: 3 mm onto its inner edge
TALL = 0.05                            # anything standing higher off the glass is a mirror head the
                                       # frame passes behind (the left door's sail): not a reason to lift


# ----------------------------------------------------------------------------------------------
# helpers


def _materials():
    out = []
    for name in MATS:
        m = bpy.data.materials.get(name)
        if m is None:
            m = bpy.data.materials.new(name)
            m.use_nodes = True
        b = next(n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
        b.inputs['Base Color'].default_value = COLOURS[name] + (1.0,)
        b.inputs['Roughness'].default_value = 0.25 if name == "AccLens" else 0.55
        out.append(m)
    return out


def _round(r, sides, phase=None):
    ph = math.pi / sides if phase is None else phase
    return [(r * math.cos(ph + 2 * math.pi * k / sides), r * math.sin(ph + 2 * math.pi * k / sides))
            for k in range(sides)]


def _rect(w, h, dh=0.0):
    """(side, up) offsets, counter-clockwise about the path tangent."""
    return [(-w / 2, dh - h / 2), (w / 2, dh - h / 2), (w / 2, dh + h / 2), (-w / 2, dh + h / 2)]


def _sweep(bm, pts, profile, ups=None, closed=False, smooth=True, cap=True, mat=STEEL):
    """Sweep a closed profile [(side, up), ...] along the polyline pts, mitred at every bend.
    ups: one 'up' vector per point (a bar lying flat on the glass gets the glass normal), else a
    frame carried along the path. Returns the new faces (outward, checked by signed volume); when
    capped, the last face is the end cap."""
    pts = [Vector(p) for p in pts]
    n = len(pts)
    tans = []
    for i in range(n):
        if closed:
            a = (pts[i] - pts[i - 1]).normalized()
            b = (pts[(i + 1) % n] - pts[i]).normalized()
        else:
            a = (pts[i] - pts[i - 1]).normalized() if i > 0 else None
            b = (pts[i + 1] - pts[i]).normalized() if i < n - 1 else None
            a = a if a is not None else b
            b = b if b is not None else a
        t = a + b
        t = t.normalized() if t.length > 1e-6 else b
        tans.append((t, a, b))
    frames = []
    for i, (t, a, b) in enumerate(tans):
        if ups is not None:
            u = Vector(ups[i])
        elif i == 0:
            u = Vector((0.0, 0.0, 1.0)) if abs(t.z) < 0.9 else Vector((1.0, 0.0, 0.0))
        else:
            u = frames[-1][1]                                    # parallel transport
        u = u - t * u.dot(t)
        if u.length < 1e-6:
            u = Vector((1.0, 0.0, 0.0)) - t * t.x
        u.normalize()
        side = u.cross(t).normalized()                           # side x up = +t: profile CCW about t
        frames.append((side, u))
    rings = []
    for i in range(n):
        t, a, b = tans[i]
        side, up = frames[i]
        cos_half = max(0.35, a.dot(t))
        bend = b - a
        bn = bend - t * bend.dot(t)
        bn = bn.normalized() if bn.length > 1e-6 else None
        ring = []
        for sa, sb in profile:
            o = side * sa + up * sb
            if bn is not None:                                   # mitre: stretch across the bend
                o = o + bn * (o.dot(bn) * (1.0 / cos_half - 1.0))
            ring.append(bm.verts.new(pts[i] + o))
        rings.append(ring)
    faces = []
    m = len(profile)
    for i in range(n if closed else n - 1):
        r0, r1 = rings[i], rings[(i + 1) % n]
        for j in range(m):
            f = bm.faces.new((r0[j], r0[(j + 1) % m], r1[(j + 1) % m], r1[j]))
            f.smooth = smooth
            faces.append(f)
    if not closed and cap:
        for ring, start in ((rings[0], True), (rings[-1], False)):
            f = bm.faces.new(list(reversed(ring)) if start else list(ring))
            f.smooth = False
            faces.append(f)
    for f in faces:
        f.material_index = mat
    _outward(faces)
    return faces


def _outward(faces):
    """Flip a closed piece whose signed volume comes out negative."""
    vol = 0.0
    for f in faces:
        vs = [v.co for v in f.verts]
        for k in range(1, len(vs) - 1):
            vol += vs[0].dot(vs[k].cross(vs[k + 1]))
    if vol < 0:
        for f in faces:
            f.normal_flip()


def _box(bm, lo, hi, mat=STEEL):
    """Axis-aligned closed box, outward."""
    x0, y0, z0 = lo
    x1, y1, z1 = hi
    c = [bm.verts.new(p) for p in ((x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
                                     (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1))]
    quads = ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7))
    faces = [bm.faces.new([c[i] for i in q]) for q in quads]
    for f in faces:
        f.smooth = False
        f.material_index = mat
    _outward(faces)
    return faces


def _slab(bm, corners, normal, t, mat=PLATE):
    """A plate of thickness t from n corners (in order) offset both ways along normal."""
    nrm = Vector(normal).normalized() * (t / 2)
    lo = [bm.verts.new(Vector(p) - nrm) for p in corners]
    hi = [bm.verts.new(Vector(p) + nrm) for p in corners]
    k = len(corners)
    faces = [bm.faces.new(lo[::-1]), bm.faces.new(hi)]
    for i in range(k):
        faces.append(bm.faces.new((lo[i], lo[(i + 1) % k], hi[(i + 1) % k], hi[i])))
    for f in faces:
        f.smooth = False
        f.material_index = mat
    _outward(faces)
    return faces


def _new_object(name, bm):
    old = bpy.data.objects.get(name)
    if old is not None:
        bpy.data.objects.remove(old, do_unlink=True)
    me = bpy.data.meshes.get(name)
    if me is not None:
        bpy.data.meshes.remove(me)
    me = bpy.data.meshes.new(name)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    bm.to_mesh(me)
    bm.free()
    for m in _materials():
        me.materials.append(m)
    ob = bpy.data.objects.new(name, me)
    body = bpy.data.objects.get("body")
    coll = body.users_collection[0] if body is not None else bpy.context.scene.collection
    coll.objects.link(ob)
    return ob


def tris(ob):
    return sum(len(p.vertices) - 2 for p in ob.data.polygons)


def _tree(names, mats=None, invert=False):
    """BVH of the named objects in world space, optionally only faces whose material is (not) in mats."""
    verts, polys = [], []
    for name in names:
        ob = bpy.data.objects.get(name)
        if ob is None:
            continue
        me = ob.data
        mn = [m.name if m else "?" for m in me.materials]
        base = len(verts)
        verts.extend(ob.matrix_world @ v.co for v in me.vertices)
        for p in me.polygons:
            if mats is not None:
                hit = mn[p.material_index] in mats if mn else False
                if hit == invert:
                    continue
            polys.append([base + i for i in p.vertices])
    return BVHTree.FromPolygons(verts, polys) if polys else None


def _surface_y(tree, x, z, dz=0.0, n=5):
    """Forward-most body surface y at (x, z +- dz), cast from the front."""
    best = None
    for k in range(n):
        zz = z - dz + (2 * dz * k / (n - 1) if n > 1 else 0.0)
        hit = tree.ray_cast(Vector((x, 4.0, zz)), Vector((0.0, -1.0, 0.0)))
        if hit[0] is not None and (best is None or hit[0].y > best):
            best = hit[0].y
    return best


def _arc(cx, cy, r, a0, a1, n):
    """Points on a circle from angle a0 to a1 (degrees), n segments, endpoints included."""
    return [(cx + r * math.cos(math.radians(a0 + (a1 - a0) * k / n)),
             cy + r * math.sin(math.radians(a0 + (a1 - a0) * k / n))) for k in range(n + 1)]


def _png(name, w, h, shade):
    """Write blender/bake/<name> (a bake decal): shade(u, v) -> linear grey, u/v in 0..1 from the
    bottom-left. Blender encodes the float buffer to sRGB on save and the bake decodes it again."""
    os.makedirs(BAKE_PNG, exist_ok=True)
    img = bpy.data.images.new(name, w, h, alpha=False)
    px = []
    for j in range(h):
        for i in range(w):
            g = shade((i + 0.5) / w, (j + 0.5) / h)
            px += [g, g, g, 1.0]
    img.pixels[:] = px
    img.filepath_raw = os.path.join(BAKE_PNG, name)
    img.file_format = 'PNG'
    img.save()
    bpy.data.images.remove(img)


# ----------------------------------------------------------------------------------------------
# bull bar


XU, R_HOOP, Z_LEG, Z_TOP, RC_HOOP = 0.36, 0.036, 0.40, 0.99, 0.17
Z_UNDER = 0.315                        # the legs' run under the bumper (its lip is at z 0.36)
LAMP_X, LAMP_R = 0.20, 0.056
LAMP_SIDES, LAMP_TIP = 14, 0.011       # the driving lamps' lathe (build_bullbar) and the bulb shield's tip


def _lamp_profile(y0, y1, R):
    """The driving lamp's section from its back (y0) to its face (y1), as (y, radius, material of the band
    to the next station): rounded back, can, bezel ring 5 mm proud, lens 3 mm back in it and domed,
    the bulb shield."""
    return [(y0, 0.85 * R, STEEL), (y0 + 0.010, R, STEEL), (y1 - 0.002, R + 0.002, PLATE),
            (y1 + 0.003, R - 0.002, PLATE), (y1 - 0.003, R - 0.007, LENS), (y1 + 0.001, 0.55 * R, LENS),
            (y1 + 0.003, 0.014, STEEL), (y1 + 0.010, 0.012, STEEL)]


def _skid_decal():
    """Slotted skid plate: six rounded slots and four bolt heads, as a multiply layer."""
    def shade(u, v):
        g = 1.0
        for k in range(6):                                    # slots
            cu = (k + 0.5) / 6.0
            if abs(u - cu) < 0.028 and 0.17 < v < 0.83:
                g = 0.10
        for bu in (0.045, 0.955):                             # bolt heads
            for bv in (0.14, 0.86):
                if (u - bu) ** 2 * 7.1 + (v - bv) ** 2 < 0.0032:
                    g = 0.62
        return g
    _png("skidplate.png", 256, 96, shade)


def build_bullbar(report):
    front = _tree(["body", "hood"])
    nose = max(_surface_y(front, x, 0.62, 0.04) for x in (-0.1, 0.0, 0.1))
    y_bar = nose + 0.075

    def plan_y(x):                                            # the hoop follows the bumper's plan curve
        return y_bar - 0.03 * (x / XU) ** 2

    bm = bmesh.new()
    # hoop + legs as one tube: up the left leg, over the top with big-radius corners, down the right
    side = [(XU, Z_LEG), (XU, Z_TOP - RC_HOOP)] + _arc(XU - RC_HOOP, Z_TOP - RC_HOOP, RC_HOOP, 0, 90, 4)[1:]
    hoop = [(-x, z) for x, z in side] + [(x, z) for x, z in reversed(side)]   # left leg up, over, right leg down
    path = [(-XU, 1.74, Z_UNDER), (-XU, y_bar - 0.10, Z_UNDER), (-XU, y_bar - 0.045, Z_UNDER + 0.03)]
    path += [(x, plan_y(x), z) for x, z in hoop]
    path += [(XU, y_bar - 0.045, Z_UNDER + 0.03), (XU, y_bar - 0.10, Z_UNDER), (XU, 1.74, Z_UNDER)]
    _sweep(bm, path, _round(R_HOOP, 8))
    # cross tube and the two grille bars
    _sweep(bm, [(-XU, plan_y(-XU), 0.66), (0.0, plan_y(0.0), 0.66), (XU, plan_y(XU), 0.66)], _round(0.022, 6))
    for x in (-0.13, 0.13):
        _sweep(bm, [(x, plan_y(x), 0.58), (x, plan_y(x), Z_TOP)], _round(0.016, 6))
    # skid plate between the uprights, slot decal (AccSkid)
    _box(bm, (-0.32, y_bar - 0.018, 0.42), (0.32, y_bar - 0.006, 0.60), mat=SKID)
    # headlamp cages: a tube from the hoop over the lamp, down its outside and back under it
    for sgn in (-1.0, 1.0):
        top = [(0.46, 0.93), (0.60, 0.915), (0.715, 0.875), (0.785, 0.79), (0.79, 0.70), (0.785, 0.64)]
        back = [(0.70, 0.64), (0.55, 0.65)]
        pts = [(XU - 0.01, plan_y(XU), 0.93)]
        for x, z in top + back:
            ys = _surface_y(front, sgn * x, z, 0.09)
            pts.append((x, (ys if ys is not None else nose) + 0.055, z))
        pts.append((XU - 0.01, plan_y(XU), 0.66))
        _sweep(bm, [(sgn * x, y, z) for x, y, z in pts], _round(0.021, 6))
        # the middle rail at z 0.80 ends ON the cage's outer upright, where its centre line crosses that
        # height (2026-10-17 review ACC-3: its own surface sample put the end 2-4 cm off the cage, a tube
        # end standing in mid-air past the upright)
        end = None
        for (xa, ya, za), (xb, yb, zb) in zip(pts[1:], pts[2:]):
            if xa > 0.70 and xb > 0.70 and (za - 0.80) * (zb - 0.80) <= 0 and za != zb:
                f = (0.80 - za) / (zb - za)
                end = (xa + (xb - xa) * f, ya + (yb - ya) * f, 0.80)
                break
        mid = [(XU - 0.01, plan_y(XU), 0.80)]
        ys = _surface_y(front, sgn * 0.55, 0.80, 0.07)
        mid.append((0.55, (ys if ys is not None else nose) + 0.055, 0.80))
        if end is not None:
            mid.append(end)
        _sweep(bm, [(sgn * x, y, z) for x, y, z in mid], _round(0.015, 6))
    # driving lamps on top of the hoop (ACC-8, 2026-10-17: they were 8-sided cans with a flat grey lens):
    # one closed lathe each (LAMP_PROFILE) round the lamp's axis, LAMP_SIDES sided: the can (steel), a
    # bezel ring standing proud of the lens (plate), the lens (AccLens: it lights with the headlamps) set
    # back in the bezel and domed, a bulb shield in its middle; on a mounting stud (plate)
    zl = Z_TOP + R_HOOP + LAMP_R - 0.012
    for sx in (-1.0, 1.0):
        x = sx * LAMP_X
        y0, y1 = y_bar - 0.035, y_bar + 0.045
        rings, mats = [], []
        for yy, r, mat in _lamp_profile(y0, y1, LAMP_R):
            rings.append([(x + r * math.cos(2 * math.pi * (k + 0.5) / LAMP_SIDES), yy,
                           zl + r * math.sin(2 * math.pi * (k + 0.5) / LAMP_SIDES)) for k in range(LAMP_SIDES)])
            mats.append(mat)
        _loft(bm, rings, mats[:-1], smooth=True, cap_mats=(STEEL, STEEL), apex=(None, (x, y1 + LAMP_TIP, zl)))
        _box(bm, (x - 0.012, y_bar - 0.012, Z_TOP), (x + 0.012, y_bar + 0.012, zl), mat=PLATE)
    _skid_decal()
    ob = _new_object("acc_bullbar", bm)
    report("  acc_bullbar   %4d tris, hoop at y %.3f (nose %.3f), legs under the bumper at z %.3f, lamps at z %.2f"
           % (tris(ob), y_bar, nose, Z_UNDER, zl))
    return ob


# ----------------------------------------------------------------------------------------------
# roof rack


RK_XW, RK_Y0, RK_Y1, RK_RC = 0.47, -1.60, -0.10, 0.08
RK_H = 0.105                           # floor tube centre to top rail centre
TOWER_X, TOWER_Y, TOWER_H = 0.50, (-1.40, -0.42), 0.065
XBAR_W, XBAR_T, XBAR_X = 0.055, 0.024, 0.57   # aero crossbar section and half span
FLOOR_TUBES = 9


def _rounded_rect(xw, y0, y1, rc, z, n=3):
    pts = []
    pts += _arc(xw - rc, y0 + rc, rc, 270, 360, n)        # rear right corner
    pts += _arc(xw - rc, y1 - rc, rc, 0, 90, n)[1:]        # front right
    pts += _arc(-xw + rc, y1 - rc, rc, 90, 180, n)[1:]     # front left
    pts += _arc(-xw + rc, y0 + rc, rc, 180, 270, n)[1:-1]  # rear left (last point = first)
    return [(x, y, z) for x, y in pts]


def build_roofrack(report):
    top = _tree(["body"])

    def roof_z(x, y):
        hit = top.ray_cast(Vector((x, y, 4.0)), Vector((0.0, 0.0, -1.0)))
        return hit[0].z if hit[0] is not None else 1.65

    crown = max(roof_z(x, y) for x in (-0.2, 0.0, 0.2) for y in (-1.5, -1.0, -0.5, -0.1))
    bm = bmesh.new()
    # towers at the roof edge and two aero crossbars on them
    tower_top = []
    for yb in TOWER_Y:
        zs = []
        for sx in (-1, 1):
            x = sx * TOWER_X
            zb = roof_z(x, yb)
            zs.append(zb + TOWER_H)
            _box(bm, (x - 0.035, yb - 0.04, zb - 0.008), (x + 0.035, yb + 0.04, zb + TOWER_H), mat=PLATE)
        tower_top.append(max(zs))
    zx = max(tower_top) + XBAR_T / 2
    for yb in TOWER_Y:
        _sweep(bm, [(-XBAR_X, yb, zx), (XBAR_X, yb, zx)], _rect(XBAR_W, XBAR_T), ups=[(0, 0, 1)] * 2, smooth=False)
    zf = zx + XBAR_T / 2 + 0.014                                     # floor frame centre, on the crossbars
    zt = zf + RK_H
    # frame, top rail
    loop_f = _rounded_rect(RK_XW, RK_Y0, RK_Y1, RK_RC, zf)
    loop_t = _rounded_rect(RK_XW, RK_Y0, RK_Y1, RK_RC, zt)
    _sweep(bm, loop_f, _round(0.014, 6), ups=[(0, 0, 1)] * len(loop_f), closed=True)
    _sweep(bm, loop_t, _round(0.011, 6), ups=[(0, 0, 1)] * len(loop_t), closed=True)
    # posts: seven per side, three across the back (the front is closed by the curved floor)
    posts = [(sx * RK_XW, RK_Y0 + RK_RC + (RK_Y1 - RK_Y0 - 2 * RK_RC) * (k + 0.5) / 7) for sx in (-1, 1) for k in range(7)]
    posts += [(x, RK_Y0) for x in (-0.25, 0.0, 0.25)]
    for x, y in posts:
        _sweep(bm, [(x, y, zf), (x, y, zt)], _round(0.008, 5), ups=[(0, 1, 0)] * 2)
    # floor: close-set tubes that sweep up at the front to the top rail
    for k in range(FLOOR_TUBES):
        x = -0.40 + 0.80 * k / (FLOOR_TUBES - 1)
        pts = [(x, RK_Y0 + 0.012, zf + 0.002), (x, RK_Y1 - 0.30, zf + 0.002), (x, RK_Y1 - 0.18, zf + 0.022),
               (x, RK_Y1 - 0.085, zf + 0.060), (x, RK_Y1 - 0.012, zt - 0.014)]
        _sweep(bm, pts, _round(0.0075, 4))
    for y in (-1.15, -0.55):                                         # built-in crossbars under the floor
        _sweep(bm, [(-RK_XW, y, zf - 0.010), (RK_XW, y, zf - 0.010)], _round(0.010, 5))
    # wind fairing on the raised front
    _slab(bm, [(-0.40, RK_Y1 + 0.004, zf + 0.012), (0.40, RK_Y1 + 0.004, zf + 0.012),
               (0.40, RK_Y1 - 0.070, zt - 0.014), (-0.40, RK_Y1 - 0.070, zt - 0.014)], (0.0, 0.80, 0.60), 0.006)
    # U-clamps where the frame sits on the crossbars
    for yb in TOWER_Y:
        for sx in (-1, 1):
            x = sx * RK_XW
            _box(bm, (x - 0.022, yb - 0.032, zx + XBAR_T / 2 - 0.004), (x + 0.022, yb + 0.032, zf + 0.016), mat=PLATE)
    ob = _new_object("acc_roofrack", bm)
    ob["rack_floor"], ob["rack_rail"] = zf, zt                       # build_rack_loads sits its cargo on these
    report("  acc_roofrack  %4d tris, floor %.3f / rail %.3f m on crossbars at %.3f (roof crown %.3f, towers on %.3f..%.3f)"
           % (tris(ob), zf, zt, zx, crown, min(tower_top) - TOWER_H, max(tower_top) - TOWER_H))
    return ob


# ----------------------------------------------------------------------------------------------
# roof rack cargo: the three fill states (see the docstring). Built against the shipped basket
# (floor frame centre 1.755, rail 1.860): everything stays inside the frame tube's inner edge
# (x +-0.456), behind the floor tubes' curve-up and under z 2.12, and the states tell apart at 150 px/m.
# Real sizes: an 18-gallon tote is about 0.6 x 0.42 x 0.3 m, a duffel 0.6 m long and 0.3 m across.
# Where each piece sits and its sizes live in cargo_paint (LAYOUT), which also paints the pieces'
# detail from the same numbers (2026-10-13): a decal is pinned to model space, so every piece sits in
# the same place in every state it appears in.

LOAD_X_IN, LOAD_Y0, LOAD_Y1 = 0.44, -1.57, -0.42        # usable floor: inside the 14 mm frame tube, behind
                                                        # the curve-up of the floor tubes (y > -0.40)
SHADE_REACH, SHADE_RAYS = 0.12, 24                      # acc_shade: occlusion reach (m), rays per face corner
# texel weight per face (bake_atlas reads the attribute for acc_rack_load*): what the game camera
# (30 degrees down, any azimuth) can see of the face, against the cargo itself
TEXEL_W_ATTR = "texel_w"
VIS_ELEV, VIS_AZ = 30.0, 24
TEXEL_W_SEEN = CP.TEXEL_W_SEEN                          # 1: see cargo_paint (weight 2 cost the panels 9 %)
TEXEL_W_GRAZED, TEXEL_W_HIDDEN = 0.5, 0.25
GRAZE_COS = 0.25                                        # best n . view below this: seen edge-on only


def _face(bm, verts, mat, hint, smooth=False):
    """One face from BMVerts, wound so its normal points along hint (the open pieces: ribs, ribbons)."""
    f = bm.faces.new(verts)
    f.material_index = mat
    f.smooth = smooth
    f.normal_update()
    if f.normal.dot(Vector(hint)) < 0:
        f.normal_flip()
    return f


def _rr(a, b, r, seg=2):
    """Rounded rectangle with half sizes a (x) and b (y), corner radius r, seg segments a corner:
    counter-clockwise from above, from the rear-right corner. Its concentric offset by d is
    _rr(a + d, b + d, r + d) with the same point count, so rings of one outline loft into quads."""
    pts = []
    for cx, cy, a0 in ((a - r, -b + r, 270.0), (a - r, b - r, 0.0), (-a + r, b - r, 90.0), (-a + r, -b + r, 180.0)):
        for k in range(seg + 1):
            t = math.radians(a0 + 90.0 * k / seg)
            pts.append((cx + r * math.cos(t), cy + r * math.sin(t)))
    return pts


def _loft(bm, rings, mats, smooth=False, cap_mats=None, apex=(None, None)):
    """Closed solid through rings of equal length, all wound the same way: band i between rings i and
    i + 1 takes mats[i]; each end is an n-gon cap (cap_mats, default the end bands' materials) or,
    with an apex point, a fan to it (a sunk core). Outward."""
    vs = [[bm.verts.new(p) for p in ring] for ring in rings]
    m = len(rings[0])
    cap_mats = cap_mats or (mats[0], mats[-1])
    faces = []
    for i in range(len(vs) - 1):
        for j in range(m):
            f = bm.faces.new((vs[i][j], vs[i][(j + 1) % m], vs[i + 1][(j + 1) % m], vs[i + 1][j]))
            f.material_index, f.smooth = mats[i], smooth
            faces.append(f)
    for ring, mat, tip in ((vs[0][::-1], cap_mats[0], apex[0]), (vs[-1], cap_mats[1], apex[1])):
        if tip is None:
            caps = [bm.faces.new(ring)]
        else:
            c = bm.verts.new(tip)
            caps = [bm.faces.new((ring[j], ring[(j + 1) % m], c)) for j in range(m)]
        for f in caps:
            f.material_index, f.smooth = mat, False
        faces += caps
    _outward(faces)
    return faces


def _shade(ob, k):
    """The cargo's ambient occlusion on itself per face corner, stored as the float corner attribute
    acc_shade = 1 - k x the occluded share of SHADE_RAYS cosine-weighted rays within SHADE_REACH.
    The bake makes every accessory invisible to rays (the car must not keep their shadows), so
    without it the lid joint, the ribs, the handles, the straps and the gear's contacts bake flat;
    bake_atlas multiplies it into the cargo's colour (TEXTURED 'attr'). The floor is left out: the
    basket is open tubes, and the shell AO already darkens what faces the roof (a solid floor plane
    here took the bags' sides to sRGB ~37). A float attribute, not a colour attribute: the FBX
    exporter writes colour attributes out as vertex colours and the shipped meshes' vertex layout
    must not change. Returns the mean."""
    me = ob.data
    tree = BVHTree.FromPolygons([v.co.copy() for v in me.vertices], [list(p.vertices) for p in me.polygons])
    dirs = []
    for i in range(SHADE_RAYS):                                       # golden-angle spiral, cosine weighted
        u = (i + 0.5) / SHADE_RAYS
        dirs.append((math.sqrt(u) * math.cos(i * 2.399963), math.sqrt(u) * math.sin(i * 2.399963), math.sqrt(1.0 - u)))
    vals = [1.0] * len(me.loops)
    for p in me.polygons:
        nrm = p.normal.copy()
        t = nrm.orthogonal().normalized()
        b = nrm.cross(t)
        for li in p.loop_indices:
            co = me.vertices[me.loops[li].vertex_index].co
            to_c = p.center - co
            o = co + to_c * min(1.0, 0.01 / max(to_c.length, 1e-6)) + nrm * 0.0015    # 1 cm into the face, 1.5 mm off it
            hit = sum(1 for dx, dy, dz in dirs if tree.ray_cast(o, t * dx + b * dy + nrm * dz, SHADE_REACH)[0] is not None)
            vals[li] = 1.0 - k * hit / SHADE_RAYS
    attr = me.attributes.get("acc_shade")
    if attr is None:
        attr = me.attributes.new("acc_shade", 'FLOAT', 'CORNER')
    attr.data.foreach_set("value", vals)
    return sum(vals) / max(1, len(vals))


def _texel_weights(ob):
    """Texel weight per face from what the game camera can see of it (2026-10-13). The old flat 0.5
    (~0.7 texels/cm) drew every texel of the cargo as a 4-5 px blob at the in-game 326 px/m; the painted
    detail (cargo_paint) wants ~1.4 (TEXEL_W_SEEN, see cargo_paint for why not 2). Only what can be
    seen pays for it: a face looked at from any of VIS_AZ azimuths at VIS_ELEV whose centre or a
    point near a corner has a clear line to the camera (against the cargo) gets TEXEL_W_SEEN; one
    seen only edge-on TEXEL_W_GRAZED; one never seen (bottoms on the floor, the webbing's back
    layers, walls against a neighbour: ~25 % of the cargo's area) TEXEL_W_HIDDEN. Stored as the FLOAT
    face attribute texel_w (a float attribute does not change the FBX's vertex layout). Returns the
    3D area per weight."""
    me = ob.data
    tree = BVHTree.FromPolygons([v.co.copy() for v in me.vertices], [list(p.vertices) for p in me.polygons])
    e = math.radians(VIS_ELEV)
    dirs = [Vector((math.cos(e) * math.cos(a), math.cos(e) * math.sin(a), math.sin(e)))
            for a in (2 * math.pi * k / VIS_AZ for k in range(VIS_AZ))]
    out, area = [], {}
    for p in me.polygons:
        n, c = p.normal, p.center
        pts = [c] + [c.lerp(me.vertices[i].co, 0.7) for i in p.vertices]
        best = 0.0
        for d in sorted(dirs, key=lambda d: -n.dot(d)):
            cos = n.dot(d)
            if cos <= best:
                break
            if any(tree.ray_cast(q + n * 0.002, d, 3.0)[0] is None for q in pts):
                best = cos
                break
        w = TEXEL_W_SEEN if best >= GRAZE_COS else (TEXEL_W_GRAZED if best > 0.0 else TEXEL_W_HIDDEN)
        out.append(w)
        area[w] = area.get(w, 0.0) + p.area
    attr = me.attributes.get(TEXEL_W_ATTR)
    if attr is not None:
        me.attributes.remove(attr)
    attr = me.attributes.new(TEXEL_W_ATTR, 'FLOAT', 'FACE')
    attr.data.foreach_set("value", out)
    return area


def _tote(bm, z0):
    """The ribbed plastic storage tote (the HDX / Rubbermaid kind) at cargo_paint.TOTE, long axis along
    y, standing on z0, 0.30 m tall: charcoal walls tapered and rounded at the corners, ribs down every
    wall, a lip under the lid, a mustard lid with a raised rim round a sunk panel, two clip latches
    over the lip on each long side (lid plastic, flipped down over the lip), a moulded handle under
    the lip at each end. cargo_paint paints the ribs' light and shade, the label, the recessed handle
    pockets, the lid's stacking pads and the latches' grips onto the same metres."""
    xc, yc, a, b = CP.TOTE["xc"], CP.TOTE["yc"], CP.TOTE["a"], CP.TOTE["b"]
    taper, r, lip = CP.TOTE_TAPER, CP.TOTE_R, CP.TOTE_LIP
    z1, z2, z3 = z0 + CP.TOTE_Z1, z0 + CP.TOTE_Z2, z0 + CP.TOTE_Z3   # wall top (under the lip), lid joint, rim top
    z4 = z3 - CP.TOTE_SINK                                  # the lid's sunk panel

    def ring(d, z):
        return [(xc + x, yc + y, z) for x, y in _rr(a + d, b + d, r + d)]
    _loft(bm, [ring(-taper, z0), ring(0.0, z1), ring(lip, z1), ring(lip, z2), ring(lip, z3),
               ring(lip - CP.TOTE_RIM, z3), ring(lip - CP.TOTE_RIM - 0.008, z4)],
          [TOTE, TOTE, TOTE, LID, LID, LID])                # walls, lip underside, lip, lid skirt, rim, rim slope
    # ribs: 20 mm wide, 12 mm proud, open at the back (2 mm inside the wall), from the floor to the lip
    for axis, half, spots in (("x", a, CP.TOTE_RIBS_X), ("y", b, CP.TOTE_RIBS_Y)):
        for s in (-1.0, 1.0):
            outward = (s, 0.0, 0.0) if axis == "x" else (0.0, s, 0.0)
            along = (0.0, 1.0, 0.0) if axis == "x" else (1.0, 0.0, 0.0)
            for c in spots:
                pts = []
                for z in (z0, z1):
                    wall = half - taper * (1.0 - (z - z0) / (z1 - z0))
                    for depth, side in ((-0.002, -1), (CP.TOTE_RIB_OUT, -1), (CP.TOTE_RIB_OUT, 1), (-0.002, 1)):
                        n_, t_ = s * (wall + depth), c + side * CP.TOTE_RIB_HALF
                        pts.append((xc + n_, yc + t_, z) if axis == "x" else (xc + t_, yc + n_, z))
                lo = [bm.verts.new(p) for p in pts[:4]]
                hi = [bm.verts.new(p) for p in pts[4:]]
                _face(bm, (lo[0], lo[1], hi[1], hi[0]), TOTE, tuple(-v for v in along))
                _face(bm, (lo[1], lo[2], hi[2], hi[1]), TOTE, outward)
                _face(bm, (lo[2], lo[3], hi[3], hi[2]), TOTE, along)
    hw, h_in, h_out, h_down, h_up = CP.TOTE_HANDLE
    lw, l_in, l_out, l_below, l_under = CP.TOTE_LATCH
    for s in (-1.0, 1.0):
        y_in, y_out = s * (b - h_in), s * (b + h_out)       # moulded handle under the lip at each end
        _box(bm, (xc - hw, yc + min(y_in, y_out), z1 - h_down), (xc + hw, yc + max(y_in, y_out), z1 + h_up), mat=TOTE)
        x_in, x_out = s * (a + lip - l_in), s * (a + lip + l_out)
        for c in CP.TOTE_LATCH_Y:                           # clip latches hooked under the lip
            _box(bm, (xc + min(x_in, x_out), yc + c - lw, z1 - l_below), (xc + max(x_in, x_out), yc + c + lw, z3 - l_under), mat=LID)


def _bag(bm, z0, bag, mat):
    """A soft bag lying on the floor (cargo_paint.DUFFEL / KITBAG): a flat-bottomed body through
    cargo_paint.bag_stations that bulges and sags a little mid-length, piped end panels (the piping
    and the zip are painted: cargo_paint), webbing girth straps round the body when bag["straps"],
    carry handles: two that lean in to a hook-and-loop wrap over the zip ("wrap", the duffel) or two
    upright either side of the middle ("pair", the kit bag, whose middle a ratchet strap runs down),
    and the zip's steel slider and pull tab when bag["slider"]. All webbing is AccStrap (black;
    painted), no longer AccSteel: that is a swatch material on the shell sheet, flat colour with no
    texels to draw in."""
    L = bag["length"] / 2.0
    w, h, xc, yc = bag["w"], bag["h"], bag["xc"], bag["yc"]

    def T(u, v, z):                                         # bag frame (u along, v across, z up) -> model
        return (xc + v, yc + u, z) if bag["along"] == "y" else (xc + u, yc - v, z)

    def D(u, v, z):                                         # same rotation, for directions
        return (v, u, z) if bag["along"] == "y" else (u, -v, z)
    stations = CP.bag_stations(L)

    def section(u, s, sag):
        out = []
        for k, (pv, pz) in enumerate(CP.BAG_PROF):
            wob = 0.005 * math.sin(9.0 * u + 2.3 * k) if abs(u) < L - 0.05 else 0.0   # soft cloth: no two alike
            z = h / 2 + (pz * h - h / 2) * s + (sag if pz > 0.9 else 0.0) + 0.5 * wob
            out.append((pv * w * s + wob * pv, max(0.002, z)))
        return out
    secs = [section(*st) for st in stations]
    _loft(bm, [[T(u, v, z0 + z) for v, z in sec] for (u, _s, _g), sec in zip(stations, secs)],
          [mat] * 6, smooth=True, cap_mats=(mat, mat))     # the piped binding at each end is painted

    def normals(sec):                                       # outward 2D normals at the section's points
        out = []
        for k in range(len(sec)):
            p0, p1, p2 = sec[k - 1], sec[k], sec[(k + 1) % len(sec)]
            nv = (p1[1] - p0[1]) + (p2[1] - p1[1])
            nz = -(p1[0] - p0[0]) - (p2[0] - p1[0])
            ln = math.hypot(nv, nz) or 1.0
            out.append((nv / ln, nz / ln))
        return out
    for st in ((2, 4) if bag["straps"] else ()):            # girth straps at u -0.15 / +0.15, floor to floor over the top
        u, sec = stations[st][0], secs[st]
        nr = normals(sec)
        for off, sgn, hw in ((0.005, 1.0, CP.WEB_HALF), (0.005, -1.0, CP.WEB_HALF + 0.001)):   # webbing 5 mm proud + a back layer
            rails = [[bm.verts.new(T(u + du, v + off * nv, z0 + max(0.001, z + off * nz))) for (v, z), (nv, nz) in zip(sec, nr)]
                     for du in (-hw, hw)]       # PZ culls back faces: a band proud of the bag showed its back on the
                                                # silhouette (pzview leak px); coplanar and 1 mm wider: an inset or flush one left specks
            for k in range(len(sec) - 1):
                mv, mz = (nr[k][0] + nr[k + 1][0]) / 2, (nr[k][1] + nr[k + 1][1]) / 2
                _face(bm, (rails[0][k], rails[0][k + 1], rails[1][k + 1], rails[1][k]), STRAP, tuple(sgn * c for c in D(0.0, mv, mz)))
    tops = [(u, (sec[3][1] + sec[4][1]) / 2) for (u, _s, _g), sec in zip(stations, secs)]

    def top_z(u):
        for (ua, za), (ub, zb) in zip(tops, tops[1:]):
            if ua <= u <= ub:
                return za + (zb - za) * (u - ua) / (ub - ua)
        return tops[-1][1]
    su = CP.STRAP_U
    if bag["handles"] == "wrap":                            # two handles leaning in to a wrap over the zip
        for sv in (-1.0, 1.0):
            pts = [T(-su, sv * 0.060, z0 + top_z(-su) + 0.004), T(-0.075, sv * 0.038, z0 + top_z(-0.075) + 0.030),
                   T(0.0, sv * 0.013, z0 + top_z(0.0) + 0.045), T(0.075, sv * 0.038, z0 + top_z(0.075) + 0.030),
                   T(su, sv * 0.060, z0 + top_z(su) + 0.004)]
            _sweep(bm, pts, _rect(0.024, 0.005), smooth=False, mat=STRAP)
        zt = z0 + top_z(0.0) + 0.045
        lo, hi = T(-0.035, -0.030, zt - 0.010), T(0.035, 0.030, zt + 0.009)
        _box(bm, tuple(min(p, q) for p, q in zip(lo, hi)), tuple(max(p, q) for p, q in zip(lo, hi)), mat=STRAP)
    else:                                                   # two upright handles, sewn to the bag (patches painted)
        for sv in (-0.045, 0.045):
            pts = [T(-su, sv, z0 + top_z(-su) + 0.004), T(-0.08, sv, z0 + top_z(-0.08) + 0.028),
                   T(0.0, sv, z0 + top_z(0.0) + 0.035), T(0.08, sv, z0 + top_z(0.08) + 0.028),
                   T(su, sv, z0 + top_z(su) + 0.004)]
            _sweep(bm, pts, _rect(0.024, 0.005), smooth=False, mat=STRAP)
    if bag["slider"]:                                       # the zip's steel slider and its webbing pull tab
        us, zv = L - 0.09, bag["zip_v"]
        zt = z0 + top_z(us)
        for (u0, u1, hv, dz0, dz1, m) in ((us - 0.011, us + 0.011, 0.007, -0.002, 0.006, PLATE),
                                          (us + 0.012, us + 0.048, 0.006, 0.000, 0.004, STRAP)):
            lo, hi = T(u0, zv - hv, zt + dz0), T(u1, zv + hv, zt + dz1)
            _box(bm, tuple(min(p, q) for p, q in zip(lo, hi)), tuple(max(p, q) for p, q in zip(lo, hi)), mat=m)


def _bedroll(bm, z0):
    """The rolled foam mat (cargo_paint.BEDROLL) lying across the basket: rolled ends with the core
    sunk in, pinched under two black webbing straps with steel cam buckles on the front and the
    straps' tails hanging from them. The ribs, the mat's last edge and the spiral at the ends are
    painted (cargo_paint.paint_bedroll). 12 sides (8 until 2026-10-13: an octagon at the game's zoom)."""
    B = CP.BEDROLL
    yc, x0, x1, r, n = B["yc"], B["x0"], B["x1"], B["r"], B["sides"]
    zc = CP.bedroll_zc(z0)                                  # the lowest facet on the floor
    ang = [math.pi / n + 2 * math.pi * k / n for k in range(n)]

    def ring(x, s):
        return [(x, yc + r * s * math.cos(a), zc + r * s * math.sin(a)) for a in ang]
    xs0, xs1 = CP.BEDROLL_STRAPS
    _loft(bm, [ring(x0, CP.BEDROLL_END_S), ring(x0 + 0.012, 1.0), ring(xs0, CP.BEDROLL_PINCH), ring(xs1, CP.BEDROLL_PINCH),
               ring(x1 - 0.012, 1.0), ring(x1, CP.BEDROLL_END_S)],
          [TARP] * 5, smooth=True, apex=((x0 + 0.012, yc, zc), (x1 - 0.012, yc, zc)))
    rs = CP.BEDROLL_PINCH * r + 0.005
    for xs in CP.BEDROLL_STRAPS:
        for rad, sgn, hw in ((rs, 1.0, CP.WEB_HALF - 0.001), (rs, -1.0, CP.WEB_HALF)):    # the band and its back layer (see _bag)
            rails = [[bm.verts.new((xs + dx, yc + rad * math.cos(a), zc + rad * math.sin(a))) for a in ang] for dx in (-hw, hw)]
            for k in range(n):
                mid = ang[k] + math.pi / n
                _face(bm, (rails[0][k], rails[0][(k + 1) % n], rails[1][(k + 1) % n], rails[1][k]), STRAP,
                      (0.0, sgn * math.cos(mid), sgn * math.sin(mid)))
        a = math.radians(50.0)                              # cam buckle on the front-top of the strap
        nb = Vector((0.0, math.cos(a), math.sin(a)))
        tb = Vector((0.0, -math.sin(a), math.cos(a)))
        c = Vector((xs, yc, zc)) + nb * (rs + 0.006)
        _slab(bm, [c + Vector((-0.020, 0, 0)) - tb * 0.016, c + Vector((0.020, 0, 0)) - tb * 0.016,
                   c + Vector((0.020, 0, 0)) + tb * 0.016, c + Vector((-0.020, 0, 0)) + tb * 0.016], nb, 0.010, mat=PLATE)
        # the strap's tail out of the buckle: over the strap round the front, then hanging 4 cm
        tail = [(rs + 0.004, math.radians(a_)) for a_ in (44.0, 22.0, 0.0)]     # from under the buckle's lower end
        path = [(yc + rd * math.cos(t), zc + rd * math.sin(t)) for rd, t in tail] + [(yc + rs + 0.004, zc - 0.045)]
        for sgn, hw in ((1.0, 0.0135), (-1.0, 0.0145)):
            rails = [[bm.verts.new((xs + dx, py, pz)) for py, pz in path] for dx in (-hw, hw)]
            for k in range(len(path) - 1):
                (ya, za), (yb, zb) = path[k], path[k + 1]
                nrm = (0.0, (zb - za), -(yb - ya))          # the outward side of the run (front / down)
                if nrm[1] < 0 or (nrm[1] == 0 and nrm[2] < 0):
                    nrm = (0.0, -nrm[1], -nrm[2])
                _face(bm, (rails[0][k], rails[0][k + 1], rails[1][k + 1], rails[1][k]), STRAP, tuple(sgn * q for q in nrm))


def _hook(bm, s, y, rail_x, rail_z):
    """A flat steel J-hook round the top rail on side s (+1 right): from the strap's sewn end loop
    just inside the rail (HOOK_IN), over the 11 mm tube, down its outside and back under it."""
    R = 0.011 + 0.0035                                      # the strip's centre line round the tube
    pts = [(s * (rail_x - CP.HOOK_IN), y, rail_z + 0.018)]
    for a in (110.0, 50.0, -10.0, -70.0, -130.0):            # 60-degree steps: 44 tris a hook (68 at 35)
        t = math.radians(a)
        pts.append((s * (rail_x + R * math.cos(t)), y, rail_z + R * math.sin(t)))
    _sweep(bm, pts, _rect(0.003, 0.024), ups=[(0.0, 1.0, 0.0)] * len(pts), smooth=False, mat=PLATE)


def _ratchet(bm, c, t, n):
    """The ratchet lying on its run at c (on the webbing's top), t along the run, n off it: a steel
    frame and side plates, the spool of wound webbing across it (AccStrap: the orange band paints it,
    cargo_paint.SPOOL_*), the steel handle folded over beyond the spool with its grip roll."""
    b = Vector((0.0, 1.0, 0.0))
    L, W = CP.RATCHET_L, CP.RATCHET_W
    base = c + n * 0.003
    _slab(bm, [base - t * L / 2 - b * W / 2, base + t * L / 2 - b * W / 2, base + t * L / 2 + b * W / 2, base - t * L / 2 + b * W / 2],
          n, 0.004, mat=PLATE)
    for s in (-1.0, 1.0):                                   # side plates
        o = c + b * s * (W / 2 - 0.0015)
        _slab(bm, [o - t * L / 2 + n * 0.004, o + t * L / 2 + n * 0.004, o + t * (L / 2 - 0.015) + n * 0.026,
                   o - t * L / 2 + n * 0.030], b, 0.003, mat=PLATE)
    sc = c + t * CP.SPOOL_DT + n * (0.005 + CP.SPOOL_R)
    _sweep(bm, [sc - b * CP.SPOOL_HALF, sc + b * CP.SPOOL_HALF], _round(CP.SPOOL_R, 10), ups=[t, t], mat=STRAP)
    h0, h1 = CP.SPOOL_DT + CP.SPOOL_R + 0.003, L / 2 + 0.030
    hb = c + n * 0.024
    _slab(bm, [hb + t * h0 - b * 0.021, hb + t * h1 - b * 0.021, hb + t * h1 + b * 0.021, hb + t * h0 + b * 0.021], n, 0.004, mat=PLATE)
    g = c + t * h1 + n * 0.026
    _sweep(bm, [g - b * 0.024, g + b * 0.024], _round(0.007, 6), ups=[t, t], mat=PLATE)


def _ratchet_strap(bm, tree, y, rail_x, rail_z, ratchet_x):
    """A ratchet strap across the load at y: J-hooks round both top rails (centres at +-rail_x,
    rail_z, tube r 11 mm), the webbing pulled tight over the cargo (the upper hull of the load's top,
    sampled every 2 cm across the 35 mm webbing) from one hook's end loop to the other's, a ratchet on
    the run over ratchet_x. Its orange, edges, end-loop stitching and load label are painted
    (cargo_paint.paint_straps, gated to its y band)."""
    x0 = rail_x - CP.HOOK_IN
    top = rail_z + 0.018
    pts = [(-x0, top)]
    for i in range(1, 47):
        x = -x0 + 2.0 * x0 * i / 47
        hz = None
        for dy in (-0.017, 0.0, 0.017):
            hit = tree.ray_cast(Vector((x, y + dy, 3.0)), Vector((0.0, 0.0, -1.0)))
            if hit[0] is not None and (hz is None or hit[0].z > hz):
                hz = hit[0].z
        if hz is not None and hz + 0.004 > top:
            pts.append((x, hz + 0.004))
    pts.append((x0, top))
    hull = []
    for p in pts:                                           # upper hull: a pulled strap touches only the peaks
        while len(hull) >= 2 and ((hull[-1][0] - hull[-2][0]) * (p[1] - hull[-2][1])
                                  - (hull[-1][1] - hull[-2][1]) * (p[0] - hull[-2][0])) >= 0:
            hull.pop()
        hull.append(p)
    keep = [hull[0]]                                        # drop hull points within 4 mm of the line on: the
    for i in range(1, len(hull) - 1):                       # bags' round tops add a corner every 2 cm sample
        (xa, za), (xb, zb), (xc, zc) = keep[-1], hull[i], hull[i + 1]
        if abs((xc - xa) * (zb - za) - (zc - za) * (xb - xa)) / math.hypot(xc - xa, zc - za) > 0.004:
            keep.append(hull[i])
    hull = keep + [hull[-1]]
    _sweep(bm, [(x, y, z) for x, z in hull], _rect(2 * CP.STRAP_HALF, 0.004), smooth=False, mat=STRAP)
    for s in (-1.0, 1.0):
        _hook(bm, s, y, rail_x, rail_z)
    for (xa, za), (xb, zb) in zip(hull, hull[1:]):          # the ratchet, lying on its run
        if xa <= ratchet_x <= xb:
            t = Vector((xb - xa, 0.0, zb - za)).normalized()
            n = Vector((-t.z, 0.0, t.x))
            c = Vector((ratchet_x, y, za + (zb - za) * (ratchet_x - xa) / (xb - xa))) + n * 0.002
            _ratchet(bm, c, t, n)
            break
    return len(hull)


def build_rack_loads(report, rack=None, png_dir=None):
    """The three cargo meshes on the basket's floor, and the cargo's painted maps (cargo_paint.paint
    into png_dir, default blender/bake: the bake's decal folder). `rack` is the acc_roofrack object
    (its rack_floor / rack_rail properties, written by build_roofrack); without them the 2026-10-12
    build's floor height is used and said so."""
    rack = rack if rack is not None else bpy.data.objects.get("acc_roofrack")
    zf = rack.get("rack_floor") if rack is not None else None
    if zf is None:
        zf = 1.755
        report("  acc_rack_load*: acc_roofrack carries no rack_floor property, assuming floor %.3f" % zf)
    zt = (rack.get("rack_rail") if rack is not None else None) or (zf + RK_H)
    rail_top = zt + 0.011
    z0 = zf + 0.002 + 0.0075                                # top of the floor tubes (r 0.0075 at zf + 0.002)
    out = []
    bm = bmesh.new()                                        # 1: one duffel
    _bag(bm, z0, CP.DUFFEL, CANVAS)
    out.append(_new_object(LOAD_NAMES[0], bm))
    bm = bmesh.new()                                        # 2: duffel, tote, bedroll
    _bag(bm, z0, CP.DUFFEL, CANVAS)
    _tote(bm, z0)
    _bedroll(bm, z0)
    out.append(_new_object(LOAD_NAMES[1], bm))
    bm = bmesh.new()                                        # 3: + a charcoal kit bag across, ratchet strapped
    _bag(bm, z0, CP.DUFFEL, CANVAS)
    _tote(bm, z0)
    _bag(bm, z0, CP.KITBAG, TOTE)
    _bedroll(bm, z0)
    bm.normal_update()
    tree = BVHTree.FromBMesh(bm)
    for y, rx in CP.STRAPS:
        _ratchet_strap(bm, tree, y, RK_XW, zt, rx)
    out.append(_new_object(LOAD_NAMES[2], bm))
    for o in out:
        o[CP.Z0_PROP] = z0                                  # cargo_paint.layers() maps its decals from this floor
        shade = _shade(o, 0.6)
        area = _texel_weights(o)
        vs = o.data.vertices
        lo = Vector((min(v.co.x for v in vs), min(v.co.y for v in vs), min(v.co.z for v in vs)))
        hi = Vector((max(v.co.x for v in vs), max(v.co.y for v in vs), max(v.co.z for v in vs)))
        report("  %-14s %4d tris  x %.2f..%.2f  y %.2f..%.2f  z %.3f..%.3f (floor tubes %.3f, rail top %.3f), shade mean %.2f, "
               "texel weight m2 %s" % (o.name, tris(o), lo.x, hi.x, lo.y, hi.y, lo.z, hi.z, z0, rail_top, shade,
                                        " ".join("%.2f:%.2f" % (w, a) for w, a in sorted(area.items()))))
    CP.paint(png_dir or BAKE_PNG, z0, log=report)
    return out


# ----------------------------------------------------------------------------------------------
# spare-tyre cover (2026-10-12: chose both variants for the spare on the side-hinged gate;
# HondaCRVGen1Accessories.lua fits the cover on about half the cars). A soft black vinyl cover as
# sold for the RD1: a flat face with the CR-V print (tyre_paint.cover_map, mapped by bake_atlas from
# the decal_box stored here), a rounded edge pulled over the tread, and an elastic hem gathered in
# behind the tyre. A lathe on the spare's own frame (measured on the trunk's tyre faces, like
# prep_parts._wheel_frame), 24 segments like the spare, clear of the tyre by COVER_GAP and of the
# gate skin behind it by GATE_GAP.

COVER_SEG = 24
COVER_GAP = 0.010                      # vinyl over the tyre's crown and its outer face
GATE_GAP = 0.004                       # the hem stays this far off the gate skin
GATHERS = 12                           # puckers in the elastic hem (one per two segments)
LINED_FROM = 4                         # profile rings from here on (the wrap behind the tread) get a lining


def _spare_frame(trunk):
    """(centre, axle axis pointing out of the gate, radial u, radial v, tyre (t, r) points) of the
    spare on the trunk: the tyre faces' bounding-box centre and their direction of least spread."""
    import numpy as np
    names = [m.name if m else "?" for m in trunk.data.materials]
    vids = {i for p in trunk.data.polygons if names[p.material_index] == "Pneu" for i in p.vertices}
    pts = np.array([tuple(trunk.matrix_world @ trunk.data.vertices[i].co) for i in vids])
    c = (pts.min(axis=0) + pts.max(axis=0)) / 2.0
    _w, V = np.linalg.eigh(np.cov((pts - c).T))
    ax = Vector(V[:, 0]).normalized()
    if ax.dot(Vector(c) - Vector((0.0, 0.0, 0.8))) < 0:
        ax = -ax
    u = ax.orthogonal().normalized()
    v = ax.cross(u).normalized()
    spare = {i for p in trunk.data.polygons if names[p.material_index] in ("Pneu", "Jante") for i in p.vertices}
    tr = []
    for i in spare:
        d = trunk.matrix_world @ trunk.data.vertices[i].co - Vector(c)
        t = d.dot(ax)
        tr.append((t, (d - ax * t).length))
    return Vector(c), ax, u, v, tr


def _cover_clearance(prof, tr):
    """Smallest distance (metres) from a spare vertex to the cover's profile, negative if a vertex
    pokes through it. Only vertices the cover wraps count: those in front of the hem (t > its t)."""
    hem_t = prof[-1][0]
    poly = list(prof) + [(hem_t, 0.0)]

    def inside(t, r):
        n, k = len(poly), False
        for i in range(n):
            (t0, r0), (t1, r1) = poly[i], poly[(i + 1) % n]
            if (r0 > r) != (r1 > r) and t < t0 + (r - r0) * (t1 - t0) / (r1 - r0):
                k = not k
        return k

    def seg_dist(t, r):
        best = 9.0
        for (t0, r0), (t1, r1) in zip(prof, prof[1:]):
            dt, dr = t1 - t0, r1 - r0
            s = max(0.0, min(1.0, ((t - t0) * dt + (r - r0) * dr) / (dt * dt + dr * dr)))
            best = min(best, math.hypot(t - t0 - s * dt, r - r0 - s * dr))
        return best
    worst = 9.0
    for t, r in tr:
        if t <= hem_t:
            continue
        d = seg_dist(t, r)
        worst = min(worst, d if inside(t, r) else -d)
    return worst


def build_spare_cover(report):
    trunk = bpy.data.objects.get("trunk")
    if trunk is None:
        report("  %s: no trunk, skipped" % SPARE_COVER)
        return None
    c, ax, u, v, tr = _spare_frame(trunk)
    tyre_r = max(r for t, r in tr)
    face_t = max(t for t, r in tr)                       # rim / cap face, the outermost point
    back_t = min(t for t, r in tr if r > 0.25)           # the tyre's inner sidewall
    # the gate skin behind the tyre's upper sidewall: ray from just behind the tyre along -ax
    gate = _tree(["trunk"], ("Pneu", "Jante"), invert=True)
    gaps = []
    for k in range(COVER_SEG):
        a = 2 * math.pi * k / COVER_SEG
        for rr in (0.27, 0.30, 0.33):
            p = c + ax * (back_t + 0.02) + (u * math.cos(a) + v * math.sin(a)) * rr
            hit = gate.ray_cast(p, -ax, 0.30) if gate is not None else (None,)
            if hit[0] is not None:
                gaps.append(((hit[0] - c).dot(ax), rr))
    gate_t = max((t for t, _r in gaps), default=back_t - 0.10)
    hem_t = max(back_t - 0.012, gate_t + GATE_GAP)       # how far the vinyl may wrap behind the tyre
    # the tyre's back shoulder (the lathe's shoulder ring on the gate side): the vinyl follows it
    # COVER_GAP out and its elastic hem closes in just behind it. The spare sits against the gate
    # (its sidewall bulge reaches the skin), so the hem lands on the gate rather than behind the tyre
    sh_t, sh_r = min(((t, r) for t, r in tr if t < 0 and r > tyre_r - 0.02), key=lambda p: p[0])
    R = tyre_r + COVER_GAP
    F = face_t + 0.014
    # profile (t along the axle, r): the face, the rounded edge over the tread, the wrap behind it
    # the last point: a 4 mm skirt from the gathered hem down onto the gate skin. Without it the open
    # gate, seen edge-on, showed the ground through the slit between hem and gate (pzview --acc
    # rear_open: 45 leak px), the cover's inside and the tyre's back both being culled there
    prof = [(F, 0.0), (F, 0.24), (F - 0.004, 0.300), (F - 0.020, R - 0.008), (0.060, R), (-0.060, R),
            (max(sh_t - 0.004, hem_t + 0.003), sh_r + 0.009), (hem_t, sh_r - 0.004),
            (gate_t + 0.001, sh_r - 0.004)]
    bm = bmesh.new()
    rings = []
    for j, (t, r) in enumerate(prof[1:], 1):
        ring = []
        for k in range(COVER_SEG):
            a = 2 * math.pi * (k + 0.5) / COVER_SEG       # half a step off the spare's 24 segments
            rr, tt = r, t
            if j == len(prof) - 2:                         # gathered hem: alternate in / out, a crease forward
                rr += 0.007 * (1 if k % 2 else -1)
                tt += 0.004 * (1 if k % 2 else 0)
            elif j == len(prof) - 3:                       # the vinyl puckers above the hem
                rr += 0.004 * (1 if k % 2 else -1)
            ring.append(bm.verts.new(c + ax * tt + (u * math.cos(a) + v * math.sin(a)) * rr))
        rings.append(ring)
    centre = bm.verts.new(c + ax * F)
    faces = []
    for k in range(COVER_SEG):
        f = bm.faces.new((centre, rings[0][k], rings[0][(k + 1) % COVER_SEG]))
        faces.append((f, ax))
    # the back: a disc across the skirt's end ring, facing the gate. Below the gate's lower edge nothing
    # stands behind the hem, and with the gate open the camera looked up into the cover there, through its
    # culled inside to the ground (2026-10-17 review ACC-1: pzview --acc gate 180, 49 px at z 0.60). It
    # lies 1 mm off the gate skin (gate_t is the furthest-out skin point behind the tyre) and faces away
    # from it, so the two never fight; the carrier and the tyre's back stay behind it
    back_c = bm.verts.new(c + ax * prof[-1][0])
    back_r = [bm.verts.new(v.co + (v.co - c - ax * (v.co - c).dot(ax)).normalized() * 0.0005) for v in rings[-1]]
    for k in range(COVER_SEG):                         # (its own ring, 0.5 mm out: smooth shading stays radial on the skirt)
        f = bm.faces.new((back_c, back_r[(k + 1) % COVER_SEG], back_r[k]))
        faces.append((f, -ax))
    for j in range(len(rings) - 1):
        for k in range(COVER_SEG):
            k2 = (k + 1) % COVER_SEG
            f = bm.faces.new((rings[j][k], rings[j][k2], rings[j + 1][k2], rings[j + 1][k]))
            faces.append((f, None))
    # lining: the wrap behind the tyre again, 1.5 mm in, facing the tyre. The cover is an open shell
    # and PZ culls back faces: with the gate open the camera looked in past the hem, through the
    # culled vinyl and the tyre's far side, to the ground (pzview --acc rear_open: 115 leak px)
    inner = []
    for ring in rings[LINED_FROM:]:
        cp = []
        for vtx in ring:
            d = vtx.co - c
            radial = d - ax * d.dot(ax)
            cp.append(bm.verts.new(vtx.co - radial.normalized() * 0.0015))
        inner.append(cp)
    lining = []
    for j in range(len(inner) - 1):
        for k in range(COVER_SEG):
            k2 = (k + 1) % COVER_SEG
            lining.append(bm.faces.new((inner[j][k], inner[j + 1][k], inner[j + 1][k2], inner[j][k2])))
    bm.normal_update()
    t_mid = 0.5 * (F + hem_t)
    for f, want in faces:
        out = want if want is not None else f.calc_center_median() - (c + ax * t_mid)
        if f.normal.dot(out) < 0:
            f.normal_flip()
        f.material_index = VINYL
        f.smooth = True
    for f in lining:
        if f.normal.dot(f.calc_center_median() - (c + ax * t_mid)) > 0:
            f.normal_flip()                                # toward the tyre
        f.material_index = VINYL
        f.smooth = True
    bmesh.ops.triangulate(bm, faces=bm.faces[:], quad_method='BEAUTY', ngon_method='BEAUTY')
    ob = _new_object(SPARE_COVER, bm)
    # the face print's square in object x / z (bake_atlas._cover_layers); the spare faces -y
    half = 0.30
    ob["decal_box"] = (c.x - half, c.x + half, c.z - half, c.z + half)
    worst = _cover_clearance(prof, tr)
    report("  %-14s %4d tris, spare centre (%.3f, %.3f, %.3f) axle (%.2f, %.2f, %.2f), tyre r %.3f, face t %.3f, "
           "hem t %.3f (gate skin at t %.3f), min clearance to the spare %.1f mm"
           % (SPARE_COVER, tris(ob), c.x, c.y, c.z, ax.x, ax.y, ax.z, tyre_r, F, hem_t, gate_t, worst * 1000))
    return ob


# ----------------------------------------------------------------------------------------------
# window guards


def _glass(src, which):
    """bmesh (world space) of the glass faces of a window."""
    ob = bpy.data.objects[src]
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bm.transform(ob.matrix_world)
    mn = [m.name if m else "?" for m in ob.data.materials]
    drop = []
    for f in bm.faces:
        keep = mn[f.material_index] in GLASS if mn else True
        if keep and which == "windscreen":
            c = f.calc_center_median()
            keep = c.y > 0.25 and f.normal.y > 0.3
        if not keep:
            drop.append(f)
    bmesh.ops.delete(bm, geom=drop, context='FACES')
    bm.normal_update()
    return bm


def _outline(bm):
    """Longest boundary loop of the face set, as world points."""
    edges = [e for e in bm.edges if len(e.link_faces) == 1]
    nbr = {}
    for e in edges:
        a, b = e.verts
        nbr.setdefault(a, []).append(b)
        nbr.setdefault(b, []).append(a)
    seen, loops = set(), []
    for start in nbr:
        if start in seen:
            continue
        loop, prev, cur = [start], None, start
        seen.add(start)
        while True:
            nxt = [v for v in nbr[cur] if v is not prev and v not in seen]
            if not nxt:
                break
            prev, cur = cur, nxt[0]
            seen.add(cur)
            loop.append(cur)
        loops.append([v.co.copy() for v in loop])
    return max(loops, key=lambda L: sum((L[i] - L[i - 1]).length for i in range(len(L))))


def _hull(pts):
    """Convex hull (counter-clockwise) of 2D points."""
    pts = sorted(set((round(a, 5), round(b, 5)) for a, b in pts))
    if len(pts) < 3:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _plane(bm):
    area = sum(f.calc_area() for f in bm.faces)
    n = sum((f.normal * f.calc_area() for f in bm.faces), Vector()).normalized()
    c = sum((f.calc_center_median() * f.calc_area() for f in bm.faces), Vector()) / area
    if n.dot(c - CAR_CENTRE) < 0:
        n = -n                                                     # outward, away from the cabin
    axis = Vector((1.0, 0.0, 0.0)) if abs(n.x) < 0.7 else Vector((0.0, 1.0, 0.0))
    u = (axis - n * axis.dot(n)).normalized()
    v = n.cross(u)
    if v.z < 0:
        u, v = -u, -v
    return c, n, u, v


def _dp(poly, tol):
    """Douglas-Peucker on a closed 2D polygon."""
    def rec(pts):
        if len(pts) < 3:
            return pts
        a, b = pts[0], pts[-1]
        ab = (b[0] - a[0], b[1] - a[1])
        L = math.hypot(*ab) or 1e-9
        d = [abs(ab[0] * (p[1] - a[1]) - ab[1] * (p[0] - a[0])) / L for p in pts[1:-1]]
        k = max(range(len(d)), key=lambda i: d[i])
        if d[k] < tol:
            return [a, b]
        left = rec(pts[:k + 2])
        return left[:-1] + rec(pts[k + 1:])
    far = max(range(len(poly)), key=lambda i: (poly[i][0] - poly[0][0]) ** 2 + (poly[i][1] - poly[0][1]) ** 2)
    one = rec(poly[:far + 1])
    two = rec(poly[far:] + [poly[0]])
    return one[:-1] + two[:-1]


def _area2(poly):
    return sum(poly[i - 1][0] * poly[i][1] - poly[i][0] * poly[i - 1][1] for i in range(len(poly))) / 2.0


def _inset(poly, d):
    """Offset a counter-clockwise polygon inward by d (mitred corners); d < 0 offsets outward."""
    n = len(poly)
    lines = []
    for i in range(n):
        p, q = poly[i], poly[(i + 1) % n]
        ex, ey = q[0] - p[0], q[1] - p[1]
        L = math.hypot(ex, ey) or 1e-9
        nx, ny = -ey / L, ex / L                                  # left of the edge = inside (CCW)
        lines.append(((p[0] + nx * d, p[1] + ny * d), (ex / L, ey / L)))
    out = []
    for i in range(n):
        (p1, d1), (p2, d2) = lines[i - 1], lines[i]
        den = d1[0] * d2[1] - d1[1] * d2[0]
        if abs(den) < 1e-4:
            out.append(p2)
            continue
        t = ((p2[0] - p1[0]) * d2[1] - (p2[1] - p1[1]) * d2[0]) / den
        out.append((p1[0] + d1[0] * t, p1[1] + d1[1] * t))
    return out


def _span(poly, axis, value):
    """(lo, hi) of the polygon along the other axis on the line axis == value."""
    hits = []
    o = 1 - axis
    for i in range(len(poly)):
        p, q = poly[i - 1], poly[i]
        if (p[axis] - value) * (q[axis] - value) <= 0 and p[axis] != q[axis]:
            t = (value - p[axis]) / (q[axis] - p[axis])
            hits.append(p[o] + (q[o] - p[o]) * t)
    return (min(hits), max(hits)) if len(hits) >= 2 else None


def _densify(pts2, closed, step=MAX_SEG):
    out = []
    n = len(pts2)
    for i in range(n if closed else n - 1):
        p, q = pts2[i], pts2[(i + 1) % n]
        k = max(1, int(math.ceil(math.hypot(q[0] - p[0], q[1] - p[1]) / step)))
        for j in range(k):
            out.append((p[0] + (q[0] - p[0]) * j / k, p[1] + (q[1] - p[1]) * j / k))
    if not closed:
        out.append(pts2[-1])
    return out


def _clip_half(poly, a, b, k):
    """Sutherland-Hodgman against one half-plane: keep a*x + b*y <= k."""
    out = []
    for i, p in enumerate(poly):
        q = poly[(i + 1) % len(poly)]
        fp, fq = a * p[0] + b * p[1] - k, a * q[0] + b * q[1] - k
        if fp <= 0:
            out.append(p)
        if (fp < 0) != (fq < 0) and fp != fq:
            t = fp / (fp - fq)
            out.append((p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t))
    return out


def build_guard(name, report):
    src, which, panel, mode = GUARDS[name]
    gbm = _glass(src, which)
    glass = BVHTree.FromBMesh(gbm)
    c, n, u, v = _plane(gbm)
    if mode == "hull":
        poly = _hull([((p.co - c).dot(u), (p.co - c).dot(v)) for p in gbm.verts])
    else:
        poly = [((p - c).dot(u), (p - c).dot(v)) for p in _outline(gbm)]
    poly = _dp(poly, 0.006)
    if name in GUARD_Y_MAX:                    # world y = c.y + u.y * x + v.y * y on the glass plane
        poly = _clip_half(poly, u.y, v.y, GUARD_Y_MAX[name] - c.y)
    if _area2(poly) < 0:
        poly.reverse()
    frame2 = _inset(poly, -FRAME_OUT_OF.get(name, FRAME_OUT))
    # clearance: the sash, pillars and wipers that stand proud of the glass under the guard
    solid = _tree(panel, GLASS, invert=True)

    def lift(x, y):
        """Glass point under (x, y) and the height above the glass the guard needs there."""
        p = c + u * x + v * y
        hit = glass.ray_cast(p + n * 0.4, -n)
        if hit[0] is not None:
            s = hit[0]
        else:                                  # off the glass (the frame over the sash, a cut-out):
            near = glass.find_nearest(p)[0]    # keep (x, y), take the height of the nearest glass
            s = p + n * (near - p).dot(n)
        need = 0.0
        if solid is not None:
            h = solid.ray_cast(s + n * 0.12, -n, 0.12 + 0.01)
            if h[0] is not None:
                need = (h[0] - s).dot(n)
        return s, need

    def on_frame(px, py):
        """2D distance from (px, py) to the frame's line (a bar end on it is ~0)."""
        bd = 1e9
        m = len(fpts2)
        for i in range(m):
            (x0, y0), (x1, y1) = fpts2[i], fpts2[(i + 1) % m]
            ex, ey = x1 - x0, y1 - y0
            L2 = ex * ex + ey * ey
            f = 0.0 if L2 < 1e-12 else max(0.0, min(1.0, ((px - x0) * ex + (py - y0) * ey) / L2))
            bd = min(bd, math.hypot(x0 + ex * f - px, y0 + ey * f - py))
        return None, bd

    def bar(a, b, seg, h, t):
        """Points of a straight bar from a to b (2D) at height h over the glass, lifted as a whole
        over whatever stands under it (sampled every 2 cm: the hatch's brake lamp). An end on the
        frame's line stops BAR_INTO_FRAME short of it, just onto the frame's inner edge: on the
        windscreen's wrapped sides the A-pillar's bulge hides the frame's outer half from the game
        camera, and an end at its centre line stood out over the pillar past the visible frame
        (2026-10-17 review ACC-5, pzview probe: body faces at x 0.65-0.67 in front of the frame)."""
        ab = Vector((b[0] - a[0], b[1] - a[1]))
        if ab.length > 2 * BAR_INTO_FRAME:
            d_ = ab.normalized() * BAR_INTO_FRAME
            if on_frame(*a)[1] < 0.002:
                a = (a[0] + d_.x, a[1] + d_.y)
            if on_frame(*b)[1] < 0.002:
                b = (b[0] - d_.x, b[1] - d_.y)
        dense = [lift(px, py)[1] for px, py in _densify([a, b], False, 0.02)]
        low = [x for x in dense if x <= TALL]
        hh = max(h, max(low) + t / 2 + CLEAR) if low else h
        pts2 = _densify([a, b], False, seg)
        pts = [lift(px, py)[0] + n * hh for px, py in pts2]
        return pts, hh - h

    bm = bmesh.new()
    pieces = 0
    lifted = 0.0
    # frame
    pts2 = _densify(frame2, True)
    fpts2 = pts2                                       # (on_frame: the frame's 2D points, index for index)
    base = [lift(x, y) for x, y in pts2]
    needs = [need for _s, need in base]
    low = [x for x in needs if x <= TALL]
    out = max(GUARD_OUT, max(low) + FRAME_T / 2 + CLEAR) if low else GUARD_OUT
    out = min(out, 0.075)
    frame = [s + n * out for s, _need in base]
    _sweep(bm, frame, _rect(FRAME_W, FRAME_T), ups=[n] * len(frame), closed=True, smooth=False)
    pieces += 1
    # stand-off tabs: short square posts from the sash up to the frame, every TAB_EVERY along it
    coarse = _dp(frame2, 0.02)
    tabs = 0
    for i, p in enumerate(coarse):
        q = coarse[(i + 1) % len(coarse)]
        L = math.hypot(q[0] - p[0], q[1] - p[1])
        k = max(1, int(round(L / TAB_EVERY)))
        for j in range(k):
            t = (j + 0.5) / k
            x, y = p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t
            s, need = lift(x, y)
            need = min(need, TALL)
            if out - need < 0.008:
                continue
            _sweep(bm, [s + n * (need - 0.003), s + n * out], _rect(TAB_W, TAB_W), ups=[v] * 2, smooth=False, mat=PLATE)
            tabs += 1
    # gusset plates in the sharp corners of the frame
    gussets = 0
    m = len(coarse)
    for i in range(m):
        p0, p1, p2 = coarse[i - 1], coarse[i], coarse[(i + 1) % m]
        a = Vector((p0[0] - p1[0], p0[1] - p1[1]))
        b = Vector((p2[0] - p1[0], p2[1] - p1[1]))
        if a.length < 0.08 or b.length < 0.08:
            continue
        ang = math.degrees(a.angle(b))
        if ang > 150.0:
            continue
        leg = min(GUSSET, 0.4 * a.length, 0.4 * b.length)
        pa, pb = Vector(p1) + a.normalized() * leg, Vector(p1) + b.normalized() * leg
        tri = [lift(px, py)[0] + n * out for px, py in (p1, tuple(pa), tuple(pb))]
        _slab(bm, tri, n, 0.004)
        gussets += 1
    # round vertical bars, ends inside the frame
    us = [p[0] for p in frame2]
    lo_u, hi_u = min(us) + FRAME_W / 2, max(us) - FRAME_W / 2
    sp = BAR_SPACING.get(name, BAR_SPACING_DEFAULT)
    k = max(2, int(round((hi_u - lo_u) / sp)))
    bar_us = [lo_u + (hi_u - lo_u) * (i + 0.5) / k for i in range(k)]
    for x in bar_us:
        span = _span(frame2, 0, x)
        if span is None or span[1] - span[0] < 0.06:
            continue
        pts, up = bar((x, span[0]), (x, span[1]), MAX_SEG_BAR, out, 2 * BAR_R)
        lifted = max(lifted, up)
        _sweep(bm, pts, _round(BAR_R, 6), ups=[n] * len(pts), cap=True)
        pieces += 1
    # cross bars on edge: two on the tall panes, one on the short rear door windows
    vs = [p[1] for p in frame2]
    height = max(vs) - min(vs)
    for frac in ((0.36, 0.68) if height > 0.50 else (0.45,)):
        y = min(vs) + frac * height
        span = _span(frame2, 1, y)
        if span is None:
            continue
        pts, up = bar((span[0], y), (span[1], y), MAX_SEG, out + 0.0005, CROSS_T)
        lifted = max(lifted, up)
        _sweep(bm, pts, _rect(CROSS_W, CROSS_T), ups=[n] * len(pts), smooth=False, cap=True)
        pieces += 1
    lower = _guard_lower(bm, name, c, n, u, v, glass, lift, bar, out, bar_us) if name in GUARD_LOWER else ""
    gbm.free()
    ob = _new_object(name, bm)
    srt = sorted(needs)
    report("  %-13s %4d tris, %d bars, %d tabs, %d gussets, %d-point outline, %.1f cm off the glass (under the frame: "
           "median %.1f, 90%% %.1f, max %.1f cm; a bar lifted %.1f cm)%s" % (name, tris(ob), pieces, tabs, gussets, len(poly), out * 100,
                                                    srt[len(srt) // 2] * 100, srt[int(len(srt) * 0.9)] * 100, srt[-1] * 100,
                                                    lifted * 100, lower))
    return ob


def _hood_sweep():
    """The hood's swing as the lower guard section must clear it: hinge (y, z), swing (degrees), the highest angle
    above the hinge's +y of any hood point within 0.35 m of it, and r_min(x): the nearest hood point to the hinge
    axis (radially) within 5 cm of x. Sampled densely on the hood's faces and on its hinge straps (rig_vehicle
    builds them at export, riding hood_bone); without a hood, None."""
    hood = bpy.data.objects.get("hood")
    if hood is None or not len(hood.data.polygons):
        return None
    try:
        import rig_vehicle as RV
        yh, zh, ang = RV.Y_HOOD_HINGE, RV.Z_HOOD_HINGE, math.degrees(RV._hood_angle())
        strap = (RV.HOOD_STRAP_X, RV.HOOD_STRAP_PTS, RV.HOOD_STRAP_T)
    except Exception:                                      # (the 2026-10-17 rig)
        yh, zh, ang, strap = 0.86, 1.12, 62.0, (0.552, [(1.095, 0.0), (1.004, 0.0), (0.999, 0.020)], 0.009)
    M = hood.matrix_world
    me = hood.data
    pts = []
    for p in me.polygons:
        vs = [M @ me.vertices[i].co for i in p.vertices]
        for k in range(1, len(vs) - 1):
            a, b, cc = vs[0], vs[k], vs[k + 1]
            for i in range(7):
                for j in range(7 - i):
                    pts.append(a + (b - a) * (i / 6.0) + (cc - a) * (j / 6.0))
    tree = BVHTree.FromPolygons([M @ q.co for q in me.vertices], [list(p.vertices) for p in me.polygons])
    for sx in (-1.0, 1.0):
        for y, drop in strap[1]:
            hit = tree.ray_cast(Vector((sx * strap[0], y, 0.3)), Vector((0.0, 0.0, 1.0)))
            z = (hit[0].z if hit[0] is not None else 1.11) - 0.001 - drop
            pts += [Vector((sx * strap[0], y, z)), Vector((sx * strap[0], y, z - strap[2]))]
    bins, phi = {}, -90.0
    for q in pts:
        r = math.hypot(q.y - yh, q.z - zh)
        if r < 0.35:
            phi = max(phi, math.degrees(math.atan2(q.z - zh, q.y - yh)))
        b = int(round(q.x / 0.05))
        bins[b] = min(bins.get(b, 9.0), r)

    def r_min(x):
        b = int(round(x / 0.05))
        return min(bins.get(i, 9.0) for i in (b - 1, b, b + 1))
    return yh, zh, ang, phi, r_min


def _guard_lower(bm, name, c, n, u, v, glass, lift, bar, out, bar_us):
    """The windscreen guard's lower section (see GUARD_LOWER) into bm; returns the report's tail. (s, t): the glass
    plane's 2D frame turned so that t runs down the glass toward the hood (world y grows with it) and s across."""
    hs = _hood_sweep()
    g = Vector((u.y, v.y))
    gl = g.length
    gh = g / gl
    e = Vector((-gh.y, gh.x))
    if u.x * e.x + v.x * e.y < 0:
        e = -e

    def p2(s, t):
        return (e.x * s + gh.x * t, e.y * s + gh.y * t)

    def hood_ok(p):
        if hs is None:
            return True
        yh, zh, ang, phi, r_min = hs
        r = math.hypot(p.y - yh, p.z - zh)
        return (r < r_min(p.x) - LOWER_HOOD_CLEAR
                or math.degrees(math.atan2(p.z - zh, p.y - yh)) > phi + ang + LOWER_HOOD_ANGLE)
    out_l = out - FRAME_T / 2 - LOWER_T / 2 - 0.0015                 # just under the main frame's flat bar
    t_main = (GUARD_Y_MAX[name] - c.y) / gl                           # the main frame's bottom rail centre line
    t_top = t_main + FRAME_W / 2 - LOWER_TUCK + LOWER_W / 2

    def clean(s, t):
        """Glass under (s, t), nothing standing proud of it there, and the section's faces over it clear of the hood."""
        x2, y2 = p2(s, t)
        p = c + u * x2 + v * y2
        if glass.ray_cast(p + n * 0.4, -n)[0] is None:
            return False
        gp, need = lift(x2, y2)
        if need > 0.003:
            return False
        return all(hood_ok(gp + n * h) for h in (out_l - LOWER_T / 2, out_l + BAR_R + 0.002))

    x0 = (c + u * p2(0.0, t_top)[0] + v * p2(0.0, t_top)[1]).x
    x1 = (c + u * p2(1.0, t_top)[0] + v * p2(1.0, t_top)[1]).x
    s_mid = -x0 / (x1 - x0)                                           # world x = 0 on the top rail
    step = 0.02
    m = 40
    ss = [s_mid + step * i for i in range(-m, m + 1)]
    tb = []
    for s in ss:
        t = t_top - LOWER_W / 2
        if not clean(s, t):
            tb.append(None)
            continue
        while t < t_top + 0.30 and clean(s, t + 0.004):
            t += 0.004
        tb.append(t - LOWER_GAP - LOWER_W / 2)                        # the bottom rail's centre line
    # the same on both sides (the wipers park off-centre), eroded over its neighbours: no spikes between samples
    tb = [None if (a is None or b is None) else min(a, b) for a, b in zip(tb, tb[::-1])]
    tb = [None if any(tb[j] is None for j in range(max(0, i - 1), min(len(tb), i + 2)))
          else min(tb[j] for j in range(max(0, i - 1), min(len(tb), i + 2))) for i in range(len(tb))]
    i0 = i1 = m
    if tb[m] is None or tb[m] - t_top < LOWER_MIN_H:
        return "; no lower section (the strip under it is %s)" % ("blocked" if tb[m] is None else "%.1f cm" % ((tb[m] - t_top) * 100))
    while i0 > 0 and tb[i0 - 1] is not None and tb[i0 - 1] - t_top >= LOWER_MIN_H:
        i0 -= 1
    while i1 < len(ss) - 1 and tb[i1 + 1] is not None and tb[i1 + 1] - t_top >= LOWER_MIN_H:
        i1 += 1
    run = list(range(i0, i1 + 1))
    st = [(ss[i0], t_top), (ss[i1], t_top)] + [(ss[i], tb[i]) for i in reversed(run)]
    poly = _dp([p2(s, t) for s, t in st], 0.003)
    if _area2(poly) < 0:
        poly.reverse()
    pts2 = _densify(poly, True)
    frame = [lift(x, y)[0] + n * out_l for x, y in pts2]
    _sweep(bm, frame, _rect(LOWER_W, LOWER_T), ups=[n] * len(frame), closed=True, smooth=False)
    # the main guard's bars carried on through it, their ends 3 mm onto the rails' inner edges
    bars = 0
    for x in bar_us:
        span = _span(poly, 0, x)
        if span is None or span[1] - span[0] < LOWER_W + 0.010:
            continue
        a, b = (x, span[0] + LOWER_W / 2 - 0.003), (x, span[1] - LOWER_W / 2 + 0.003)
        pts, _up = bar(a, b, MAX_SEG_BAR, out_l, 2 * BAR_R)
        _sweep(bm, pts, _round(BAR_R, 6), ups=[n] * len(pts), cap=True)
        bars += 1
    # tabs from the glass to the bottom rail: at its two ends (the A-pillar bases) and in the middle
    tabs = 0
    for i in (i0, m, i1):
        si = ss[i] + (0.025 if i == i0 else (-0.025 if i == i1 else 0.0))
        k = min(run, key=lambda j: abs(ss[j] - si))
        sg, need = lift(*p2(si, tb[k]))
        _sweep(bm, [sg + n * (need - 0.003), sg + n * (out_l - LOWER_T / 2 + 0.001)], _rect(TAB_W, TAB_W),
               ups=[v] * 2, smooth=False, mat=PLATE)
        tabs += 1
    # bolt heads on the main frame's bottom rail over the tuck (the lower section is bolted up under it)
    for si in (ss[i0] + 0.04, s_mid, ss[i1] - 0.04):
        tc = t_main + FRAME_W / 2 - LOWER_TUCK / 2
        cs = []
        for ds, dt in ((-0.006, -0.006), (0.006, -0.006), (0.006, 0.006), (-0.006, 0.006)):
            sg, _need = lift(*p2(si + ds, tc + dt))
            cs.append(sg + n * (out + FRAME_T / 2 + 0.0015))
        _slab(bm, cs, n, 0.003)
    # the hood's clearance, for the report: the worst point of the frame
    worst = None
    if hs is not None:
        yh, zh, ang, phi, r_min = hs
        for p in frame:
            r = math.hypot(p.y - yh, p.z - zh)
            if math.degrees(math.atan2(p.z - zh, p.y - yh)) <= phi + ang + LOWER_HOOD_ANGLE:
                worst = min(worst if worst is not None else 9.0, r_min(p.x) - r)
    wy = [lift(*p2(ss[i], tb[i]))[0] for i in (i0, m, i1)]
    return ("; lower section x %.2f..%.2f, bottom rail at y %.3f / %.3f / %.3f (ends / centre), rails %.1f..%.1f cm apart, "
            "%d bars, %d tabs, %.1f cm off the glass, hood swing clearance %s"
            % (wy[0].x, wy[2].x, wy[0].y, wy[1].y, wy[2].y, min(tb[i] - t_top for i in run) * 100,
               max(tb[i] - t_top for i in run) * 100, bars, tabs, out_l * 100,
               "%.1f cm (radial, worst)" % (worst * 100) if worst is not None else "by angle only"))


# ----------------------------------------------------------------------------------------------


def build(report=print):
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    made = [build_bullbar(report), build_roofrack(report)]
    made += build_rack_loads(report, made[1])              # one state shows at a time; the total counts all three
    for name in GUARDS:
        made.append(build_guard(name, report))
    cover = build_spare_cover(report)
    if cover is not None:
        made.append(cover)
    report("ACCESSORIES %d objects, %d tris with everything fitted" % (len(made), sum(tris(o) for o in made)))
    return made


if __name__ in ("__main__", "run"):
    build()
    if "--save" in sys.argv:
        bpy.ops.wm.save_mainfile()
        print("ACCESSORIES saved", bpy.data.filepath)
