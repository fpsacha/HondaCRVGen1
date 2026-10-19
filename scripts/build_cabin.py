r"""
Cabin furniture of the 1997-2001 Honda CR-V (RD1), generated: dash, instrument binnacle, steering
wheel and column, front seats, split rear bench, cup-holder tray, handbrake, pedals, mirror, visors.

    blender -b <parts blend> --python scripts\build_cabin.py -- [--low | --both] [--save <blend>] [--bake <dir>]

Why (2026-10-12, feedback: "the interior seems cheaply made", "something weird is sitting in the
passenger seat", an oversized black rectangle for a cluster): the shipped cabin was kotris's
furniture crushed to 1,000 triangles with no shape guard. The seats strayed up to 44 mm from their
originals, the 600-triangle steering wheel became a 43-triangle hexagon, every cabin material
baked at sRGB 119-156 and the cluster decal covered both the binnacle and the dash behind it.
KI5's Bronco cabin is ~950 triangles and gets its look from a painted texture; this does the same.
prep_parts._strip_furniture deletes kotris's seats, wheel, binnacle, dash, console and mirror from
`interior`; the shell, floor and firewall stay there.

Built twice from run_rebuild, like build_engine: the full-detail pass (rounded profiles, dash
vents, knobs, radio bezel, glovebox lid, the H on the hub, seat seams, cup wells)
becomes `cabin_full`, which prep_parts keeps as `cabin_hi`, the bake's projection source; the
coarse pass (CABIN_LOW in the exec globals, env CRV_CABIN_LOW=1 or --low) is the shipped `cabin`,
1,253 triangles since 2026-10-17 (the rear bench left to the function feature; the oval binnacle, the
rounded mirror, a 24-segment rim and a rounded hub pad added back 132) (+20 with the floor shifter). Both passes place the same pieces on the same centre lines, so the projection
maps 1:1. The full pass also paints the two decals the bake maps by object position
(bake_atlas.TEXTURED): blender/bake/cabin_dash.png (vents, radio, HVAC, glovebox, switch bank on
the dash face) and blender/bake/cabin_cluster.png (the three-pod cluster). The file name is not
cluster.png: paint_engine_decals.cluster() writes that one.

RD1 facts used (scratchpad references: Car and Driver 1999 EX press photo, a 1999 EX automatic
dealer photo; 2026-10-17 the Japanese Classics RD1 set, blender/references/engine_bay/web_jpc_other: DSC_7939
the dash and wheel, DSC_7904 the seats): the dash is ONE charcoal colour top and bottom; an oval binnacle as wide as the wheel
with three pods (tach left 0-8, larger speedo centre 0-120, temperature and fuel side by side
right), black faces, white marks, orange arcs; a 4-spoke wheel, spokes at 9 and 3 o'clock and two
close together at the bottom, a large hub pad with the H; twin centre vents over a DIN radio and
three rotary HVAC knobs, a tray below; rectangular vents at both dash ends; a LOW cup-holder tray
between the seats (no tall console) with the thin handbrake beside it; the automatic's shifter on
the column (SHIFTER); seats with plain charcoal bolsters round a striped insert.

Seated passengers (2026-10-12, feedback: feet through the floor and out under the car, buttocks sunk in
the cushion). The cushions and the footwells are placed from the passenger hip points in
gen_scripts.PASSENGERS (hips()): each cushion's insert top sits SIT_DROP under its hip, and each
passenger gets a footwell where the vanilla seated pose puts the soles (footwells(): an opening cut
in the carpet, walls straight down from the cut edge, a closed floor block at the soles). The wells
are cut in the DECIMATED interior by carve_footwells(), which prep_parts calls after
_interior_closures (whose floor slab leaves footwell_holes() open), so the walls start on the low
floor's own cut edge.

Measured from parts_kotris.blend (scratchpad interior_impl/survey*.py): kotris wheel PCA centre
(-0.387, 0.430, 1.033), diameter 0.394, plane 16.8 deg from vertical; firewall island y 0.958 at
x 0 curving to 0.830 at |x| 0.66; footwell floor z 0.481-0.524; the windscreen base and A-pillars
come down to z 1.09-1.14 at the dash ends (the dash top follows them, CLEAR below, by ray casts
against the body); headliner z 1.55-1.62 at y 0-0.30; cargo deck z 0.766 from y -1.05.
Model space: metres, +X passenger side, +Y nose, +Z up; the driver sits at x < 0.

Rear bench (2026-10-14): with the function feature active (scripts/features/function.py) the bench
ships as two models of its own (rear_seats: upright, and folded flat as the RD1 folds it), which the
feature's Lua switches on every client, and since 2026-10-17 the cabin does not build it at all (it used
to be built, tagged with the INT face attribute REAR_SEAT_ATTR and lifted out by the feature's BUILD
after prep had counted it against the cabin's budget); without the feature the bench stays in the
cabin, tagged, as before.
"""
import math
import os
import sys

import bmesh
import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

ROOT = os.environ.get("CRV_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(globals().get("__file__") or os.path.join("scripts", "_"))))
NAME = "cabin"


def _argv():
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def _opt(flag, default=None):
    a = _argv()
    return a[a.index(flag) + 1] if flag in a and a.index(flag) + 1 < len(a) else default


# exec'd by run_rebuild there are no "--" arguments: the decals go to blender/bake
BAKE = _opt("--bake") or os.path.join(ROOT, "blender", "bake")
LOW = bool(globals().get("CABIN_LOW")) or os.environ.get("CRV_CABIN_LOW") == "1" or "--low" in _argv()
# The dealer photo is a 1999 EX automatic (column shift, common on US 1999-2001 EX); the Car and
# Driver car is a 5-speed with a floor stalk. One switch: "column" | "floor".
SHIFTER = "column"
SMOOTH_ANGLE = math.radians(32)  # boxes and the dash: sharp corners, rounded only in the full twin
ROUND = math.radians(75)          # tubes and the rim: 6-8 sides meet at 45-60 deg and must shade round
SOFT = math.radians(60)           # seats: bolster slopes shade soft, the cushion's square edges stay crisp
BUDGET = 1300                    # coarse triangles; prep_parts.BUDGET["cabin"] decimates above it

# Principled base colours = bake_atlas.PALETTE (linear), so Workbench previews and direct bakes agree.
# The tints in bake_atlas.TEXTURED land them at sRGB 52 / 64 / 85 / 57 (KI5's Bronco sheet: mean 29).
MATERIALS = {
    "CabDark":     ((0.032, 0.032, 0.034), 0.70),   # dash top, binnacle, wheel, column, tray: charcoal
    "CabDash":     ((0.050, 0.050, 0.052), 0.75),   # dash face and centre stack (carries cabin_dash.png)
    "SeatCloth":   ((0.090, 0.092, 0.097), 0.95),   # striped seat insert
    "SeatBolster": ((0.040, 0.040, 0.042), 0.95),   # plain charcoal bolsters, sides, backs
    "SeatSeam":    ((0.013, 0.013, 0.014), 0.95),   # seam grooves, full twin only: dark lines the bake paints
    "Metal":       ((0.230, 0.230, 0.240), 0.40),   # headrest posts, handbrake button
    # the rear-view mirror's glass: dark and cool over the housing's charcoal (sRGB ~81-92 before the
    # bake's shading; 0.055-0.070 shipped at 54-60, barely off the housing's 52). Not in
    # bake_atlas.PALETTE: the colour bake takes this Principled colour as it is
    "CabMirror":   ((0.085, 0.095, 0.108), 0.15),
}
X, Y, Z = Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))

# ---- measured layout (metres)
C_WHEEL = Vector((-0.39, 0.43, 1.03))                    # kotris PCA centre (-0.387, 0.430, 1.033)
N_WHEEL = Vector((0.02, -0.96, 0.29)).normalized()        # wheel normal toward the driver: 16.8 deg from vertical
R_RIM, T_RIM = 0.190, 0.017                               # rim centre-line radius, tube radius (kotris diameter 0.394)
FIREWALL = [(0.00, 0.958), (0.10, 0.955), (0.22, 0.948), (0.30, 0.937), (0.38, 0.924), (0.46, 0.907),
            (0.54, 0.883), (0.62, 0.852), (0.66, 0.830), (0.725, 0.800)]   # kotris firewall y by |x| (body side past 0.66)
DASH_X = (-0.725, -0.62, -0.50, -0.38, -0.26, -0.14, 0.14, 0.26, 0.38, 0.50, 0.62, 0.725)
BROW_Y, BROW_Z = 0.590, 1.170     # front edge of the dash top (kotris: 1.20 driver side, 1.11 passenger side)
FACE_LOW = (0.615, 0.900)         # foot of the near-vertical face (kotris face y 0.58-0.61 for z 0.98-1.14)
DASH_FOOT = (0.700, 0.840)        # lower front edge; kotris's lower dash edge sits at z 0.86-0.90
DASH_BOTTOM = 0.800               # underside at the firewall
TOP_BACK_Z = 1.120                # dash top where it meets the windscreen base (centre: glass at 1.14 at y 0.95)
CLEAR = 0.020                     # the dash top and visors stay this far under the glass / A-pillars / headliner
STACK = (-0.14, 0.14, 0.568, 0.625, 0.845, 1.160)         # centre stack slab, 2 cm proud of the face
TONGUE = (-0.13, 0.13, 0.572, 0.860, 0.470, 0.880)        # the stack's lower part, down to the floor (z 0.48)
FLOOR = 0.481                     # footwell floor under the seats

# ---- seated passengers. The game draws a passenger with its hip (Bip01) at the `inside` offset of its
# vehicle-script block, in MESH metres from the FBX origin (export_fbx.ORIGIN_Z; the offset is not
# scaled by the model's 0.9), and the character at 1.5 / 0.9 = 1.667 mesh metres per character unit
# (Model.CharacterModelCameraBegin, BaseVehicle.updateTransform; vanilla Martin and SUV feet land on
# their floors with this mapping). MaleBody.x / FemaleBody.x skinned with Bob_IdleDriving (the
# vanilla seated pose; scratch footwells/pose.py), in mesh metres from the hip: lowest sole 0.404
# below (female 0.393), on the heels; toes tilted up to 0.22-0.28 below; buttocks 0.137 below
# (0.134); top of the head 0.780 above (0.759).
ORIGIN_Z = 0.80                   # export_fbx.ORIGIN_Z: the model height of the script origin
SOLE_DROP = 0.404                 # well floor under the hip: the lowest sole (MaleBody heel)
SIT_DROP = 0.140                  # cushion insert top under the hip (buttocks 0.137)
HEAD_RISE = 0.780                 # top of the head over the hip (the hip is chosen for >= 3 cm headroom)
FEET = (-0.163, 0.177, 0.470, 0.729)   # (dx, dy) box, model x and forward, of every vertex > 0.27 under the hip
WELL_MARGIN = 0.030               # well opening past that box
WELL_GAP = 0.010                  # the closure slab's holes stand this far outside the well walls
WELL_SLAB = 0.010                 # thickness of the closed well floor block
_HIPS = {}


def hips():
    """Passenger hip points in model space, {name: Vector}, from gen_scripts.PASSENGERS (PZ +x is the
    car's left, model +X its right; inside y is mesh metres above ORIGIN_Z; inside z is model y)."""
    if not _HIPS:
        import gen_scripts
        for name, inside, _outside in gen_scripts.PASSENGERS:
            px, py, pz = (float(v) for v in inside.split())
            _HIPS[name] = Vector((-px, pz, ORIGIN_Z + py))
    return _HIPS


def footwells():
    """[(name, x0, x1, y0, y1, floor z)]: each passenger's footwell opening (model space) and the
    height of its floor, the lowest sole of the seated pose."""
    dx0, dx1, dy0, dy1 = FEET
    return [(n, h.x + dx0 - WELL_MARGIN, h.x + dx1 + WELL_MARGIN, h.y + dy0 - WELL_MARGIN, h.y + dy1 + WELL_MARGIN,
             h.z - SOLE_DROP) for n, h in hips().items()]


def footwell_holes():
    """(x0, x1, y0, y1) the closure slab under the carpet leaves open round each well."""
    return [(x0 - WELL_GAP, x1 + WELL_GAP, y0 - WELL_GAP, y1 + WELL_GAP) for _n, x0, x1, y0, y1, _z in footwells()]


# ----------------------------------------------------------------------------------------------- materials
def _material(name):
    mat = bpy.data.materials.get(name)
    if mat is not None and name == "Metal":
        return mat                                         # kotris's own Metal: keep it as it is
    rgb, rough = MATERIALS[name]
    if mat is None:
        mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = next((n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
    if bsdf:
        bsdf.inputs['Base Color'].default_value = rgb + (1.0,)
        bsdf.inputs['Roughness'].default_value = rough
    mat.diffuse_color = rgb + (1.0,)
    return mat


def _mat(name):
    if name == "Interieur":                                 # the visors are in the headliner cloth
        return bpy.data.materials.get("Interieur") or _material("CabDash")
    if name == "Interieur_sol":                             # the rear backs' carpet: the cabin floor's own
        return bpy.data.materials.get("Interieur_sol") or _material("CabDark")
    return _material(name)


# ----------------------------------------------------------------------------------------------- mesh data
def _v(p):
    return Vector(p) if not isinstance(p, Vector) else p


def loft(rings, cap0=True, cap1=True):
    """Solid through equal-length rings of points: quads between ring i and i+1, an n-gon cap at each
    end. Returns verts, faces and a tag per face (ring segment k for band faces, 'cap0' / 'cap1')."""
    n = len(rings[0])
    V = [tuple(_v(p)) for r in rings for p in r]
    F, tag = [], []
    for b in range(len(rings) - 1):
        for k in range(n):
            k2 = (k + 1) % n
            F.append((b * n + k, b * n + k2, (b + 1) * n + k2, (b + 1) * n + k))
            tag.append(k)
    if cap0:
        F.append(tuple(reversed(range(n))))
        tag.append("cap0")
    if cap1:
        last = (len(rings) - 1) * n
        F.append(tuple(last + k for k in range(n)))
        tag.append("cap1")
    return V, F, tag


def obox(c, ax, ay, az, hx, hy, hz):
    """Oriented box: centre, three unit axes, half sizes. Face order: -z, +z, -y, +x, +y, -x."""
    c, ax, ay, az = _v(c), _v(ax), _v(ay), _v(az)
    v = []
    for sz in (-1, 1):
        for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            v.append(tuple(c + ax * (sx * hx) + ay * (sy * hy) + az * (sz * hz)))
    f = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    return v, f, list(range(6))


def box(x0, x1, y0, y1, z0, z1):
    return obox(((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2), X, Y, Z, (x1 - x0) / 2, (y1 - y0) / 2, (z1 - z0) / 2)


def hexa(corners):
    """Box from 8 corners: bottom ring (-y-x, -y+x, +y+x, +y-x) then the top ring; face order as obox."""
    f = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    return [tuple(_v(p)) for p in corners], f, list(range(6))


def _frame(axis):
    a = _v(axis).normalized()
    ref = Z if abs(a.z) < 0.9 else X
    u = a.cross(ref).normalized()
    return a, u, a.cross(u)


def tube(p0, p1, r, sides, cap0=True, cap1=True, r1=None, phase=0.0):
    """Prism / cylinder from p0 to p1 (cone if r1)."""
    p0, p1 = _v(p0), _v(p1)
    a, u, w = _frame(p1 - p0)
    rings = []
    for p, rad in ((p0, r), (p1, r if r1 is None else r1)):
        rings.append([p + rad * (math.cos(phase + 2 * math.pi * i / sides) * u + math.sin(phase + 2 * math.pi * i / sides) * w)
                      for i in range(sides)])
    return loft(rings, cap0, cap1)


def torus(c, h, up, R, r, seg, ring, t0=math.pi / 2):
    """Torus in the plane (h, up) around c; the first segment starts at angle t0 (top)."""
    c, h, up = _v(c), _v(h), _v(up)
    n = h.cross(up).normalized()
    V, F = [], []
    for i in range(seg):
        t = t0 + 2 * math.pi * i / seg
        d = math.cos(t) * h + math.sin(t) * up
        for k in range(ring):
            b = 2 * math.pi * k / ring
            V.append(tuple(c + R * d + r * (math.cos(b) * d + math.sin(b) * n)))
    for i in range(seg):
        i2 = (i + 1) % seg
        for k in range(ring):
            k2 = (k + 1) % ring
            F.append((i * ring + k, i2 * ring + k, i2 * ring + k2, i * ring + k2))
    return V, F, [0] * len(F)


def _round(prev, corner, nxt, r, n):
    """Points rounding the corner (quadratic Bezier between r before and r after it), n inner points."""
    prev, corner, nxt = Vector(prev), Vector(corner), Vector(nxt)
    a = corner + (prev - corner).normalized() * min(r, (prev - corner).length * 0.45)
    c = corner + (nxt - corner).normalized() * min(r, (nxt - corner).length * 0.45)
    pts = [a]
    for i in range(1, n + 1):
        t = i / (n + 1)
        pts.append((1 - t) ** 2 * a + 2 * t * (1 - t) * corner + t * t * c)
    pts.append(c)
    return pts


def _lerp_table(table, x):
    for (x0, y0), (x1, y1) in zip(table, table[1:]):
        if x0 <= x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return table[0][1] if x < table[0][0] else table[-1][1]


# ----------------------------------------------------------------------------------------------- the car around it
def _world_bvh(ob, skip_mats=()):
    M = ob.matrix_world
    names = [m.name if m else "?" for m in ob.data.materials]
    polys = [tuple(p.vertices) for p in ob.data.polygons if not names or names[p.material_index] not in skip_mats]
    return BVHTree.FromPolygons([M @ v.co for v in ob.data.vertices], polys)


class Env:
    """Ray probes into the car the cabin is fitted to (world space). In run_rebuild the parts are
    still full detail ("body", "interior"); on a prepped blend the full detail is "<name>_hi". The
    doors are taken as they ship: a prepped door_*_hi still carries kotris's trim that prep moved
    onto it and the low door drops."""

    def __init__(self):
        def pick(*names):
            for n in names:
                ob = bpy.data.objects.get(n)
                if ob is not None and ob.type == 'MESH' and len(ob.data.polygons):
                    return ob
            return None
        b = pick("body_hi", "body")
        # kotris's rear-view mirror glass is on the body ("Miroir"): the cabin's mirror covers it
        self.body = _world_bvh(b, skip_mats=("Miroir",)) if b else None
        lin = pick("interior_hi", "interior")
        self.lining = _world_bvh(lin) if lin else None
        self.doors = [_world_bvh(o) for o in (pick(n, n + "_hi") for n in ("door_fl", "door_fr", "door_rl", "door_rr")) if o]

    def ceiling(self, x, y, z0=1.0):
        """First body surface above (x, y, z0): windscreen, A-pillar, cowl."""
        if self.body is None:
            return None
        loc = self.body.ray_cast(Vector((x, y, z0)), Z, 1.0)[0]
        return loc.z if loc is not None else None

    def headliner(self, x, y):
        if self.lining is None:
            return None
        loc = self.lining.ray_cast(Vector((x, y, 1.30)), Z, 0.6)[0]
        return loc.z if loc is not None else None

    def outside(self, p):
        """How far p lies beyond the car's side walls or above its glass (metres, 0 = inside)."""
        worst = 0.0
        if self.body is None:
            return worst
        side = 1.0 if p.x >= 0 else -1.0
        start = Vector((0.0, p.y, p.z))
        reach = abs(p.x)
        for t in [self.body] + self.doors:
            loc = t.ray_cast(start, Vector((side, 0.0, 0.0)), reach)[0]
            if loc is not None:
                worst = max(worst, reach - abs(loc.x))
        if p.z > 1.0:
            loc = self.body.ray_cast(Vector((p.x, p.y, 1.0)), Z, p.z - 1.0)[0]
            if loc is not None:
                worst = max(worst, p.z - loc.z)
        return worst


def _cap(design, ceiling, clear=CLEAR):
    return design if ceiling is None else min(design, ceiling - clear)


# ----------------------------------------------------------------------------------------------- builder
class Cab:
    def __init__(self, collection, fine, env):
        self.col = collection
        self.fine = fine
        self.env = env
        self.objs = []
        self.pieces = {}

    def add(self, piece, name, data, mats, pick=None, bevel=0.0, segments=2, smooth=SMOOTH_ANGLE, keep=None):
        """data = (verts, faces, tags); mats = material names; pick(tag) -> index into mats.
        smooth: edges between faces turning more than this are sharp (radians; False = all sharp).
        keep(tag) False: the face is deleted AFTER the normals are made consistent on the closed
        solid (the coarse seats drop the faces nobody sees and must still face outward)."""
        V, F, tags = data
        if not F:
            return None
        me = bpy.data.meshes.new(name)
        me.from_pydata(V, [], F)
        me.validate()
        for n in mats:
            me.materials.append(_mat(n))
        for i, poly in enumerate(me.polygons):
            poly.material_index = pick(tags[i]) if pick else 0
        bm = bmesh.new()
        bm.from_mesh(me)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        # recalc orients a solid by one extreme face: a folded sliver there turns the whole piece inside
        # out (the rear headrests, CAB-3). A closed piece must enclose a positive volume
        if bm.edges and all(len(e.link_faces) == 2 for e in bm.edges):
            vol = sum(f.verts[0].co.dot(f.verts[i].co.cross(f.verts[i + 1].co))
                      for f in bm.faces for i in range(1, len(f.verts) - 1)) / 6.0
            if vol < 0.0:
                bmesh.ops.reverse_faces(bm, faces=bm.faces)
                print("CABIN normals: %s came out inside-out (volume %.1f cm3): flipped" % (name, vol * 1e6))
        if keep is not None:
            bm.faces.ensure_lookup_table()
            bmesh.ops.delete(bm, geom=[f for f in bm.faces if not keep(tags[f.index])], context='FACES')
        bm.to_mesh(me)
        bm.free()
        self._shade(me, smooth)
        ob = bpy.data.objects.new(name, me)
        self.col.objects.link(ob)
        if bevel > 0 and self.fine:
            mod = ob.modifiers.new("bevel", 'BEVEL')
            mod.width = bevel
            mod.segments = segments
            mod.limit_method = 'ANGLE'
            mod.angle_limit = math.radians(30)
            mod.material = -1
            for o in bpy.context.view_layer.objects:
                o.select_set(False)
            ob.select_set(True)
            bpy.context.view_layer.objects.active = ob
            with bpy.context.temp_override(active_object=ob, object=ob, selected_objects=[ob], selected_editable_objects=[ob]):
                bpy.ops.object.modifier_apply(modifier=mod.name)
            ob.select_set(False)
            self._shade(ob.data, smooth)
        self.objs.append(ob)
        self.pieces[piece] = self.pieces.get(piece, 0) + sum(len(p.vertices) - 2 for p in ob.data.polygons)
        return ob

    @staticmethod
    def _shade(me, angle):
        """Smooth faces, sharp edges where the surface turns more than `angle` (per piece, before the
        join: one angle for the whole cabin made the 6-sided rim and the column faceted, since their
        sides meet at 45-60 degrees; tubes pass ROUND, boxes the default)."""
        bm = bmesh.new()
        bm.from_mesh(me)
        for f in bm.faces:
            f.smooth = bool(angle)
        for e in bm.edges:
            if len(e.link_faces) != 2:
                e.smooth = True                           # open boundary: nothing to be sharp against
            else:
                e.smooth = bool(angle) and e.calc_face_angle(0.0) <= angle
        bm.to_mesh(me)
        bm.free()

    def join(self, name):
        for o in bpy.context.view_layer.objects:
            o.select_set(False)
        for o in self.objs:
            o.select_set(True)
        bpy.context.view_layer.objects.active = self.objs[0]
        with bpy.context.temp_override(active_object=self.objs[0], selected_objects=self.objs, selected_editable_objects=self.objs):
            bpy.ops.object.join()
        ob = bpy.context.view_layer.objects.active
        ob.name = name
        ob.data.name = name
        ob.select_set(False)
        self.objs = []
        return ob


def _by_tag(table, default=0):
    return lambda t: table.get(t, default)


# ----------------------------------------------------------------------------------------------- dash
def _firewall_y(x):
    return _lerp_table(FIREWALL, abs(x)) - 0.012


def _dash_ring(x, env, fine):
    """Profile of the dash at station x, as (point, material of the segment that starts there).
    Coarse: brow, face foot, lower front edge, underside at the firewall, top at the windscreen base,
    top middle. The top is held CLEAR under the glass and A-pillars by ray casts, so it bends down at
    the ends where the windscreen wraps round (glass at z 1.09-1.13 at |x| 0.6-0.7, y 0.85-0.90)."""
    yb = _firewall_y(x)
    zb = _cap(BROW_Z, env.ceiling(x, BROW_Y))
    z5 = _cap(TOP_BACK_Z, env.ceiling(x, yb))
    ym = (BROW_Y + yb) / 2 + 0.015
    z6 = _cap((zb + z5) / 2 + 0.008, env.ceiling(x, ym))
    P1, P2, P3 = (BROW_Y, zb), FACE_LOW, DASH_FOOT
    P4, P5, P6 = (yb, DASH_BOTTOM), (yb, z5), (ym, z6)
    if not fine:
        prof = [(P1, "CabDash"), (P2, "CabDash"), (P3, "CabDash"), (P4, "CabDark"), (P5, "CabDark"), (P6, "CabDark")]
    else:                                                  # rounded brow and lower edge (<= 7 mm off the coarse corners)
        brow = _round(P6, P1, P2, 0.028, 3)
        foot = _round(P2, P3, P4, 0.016, 2)
        knee = _round(P1, P2, P3, 0.012, 1)
        prof = [(p, "CabDark") for p in brow[:2]] + [(p, "CabDash") for p in brow[2:]]
        prof += [(p, "CabDash") for p in knee] + [(p, "CabDash") for p in foot]
        prof += [(P4, "CabDark"), (P5, "CabDark"), (P6, "CabDark")]
    return [((x, p[0], p[1]), m) for p, m in prof]


def _face_y(z):
    """y of the dash face (brow to face foot) at height z: where the face details sit."""
    t = (z - FACE_LOW[1]) / (BROW_Z - FACE_LOW[1])
    return FACE_LOW[0] + (BROW_Y - FACE_LOW[0]) * t


def dash(b):
    xs = list(DASH_X)
    if b.fine:                                             # 4 sub-stations per coarse interval
        xs = sorted({round(float(v), 4) for a, c in zip(DASH_X, DASH_X[1:]) for v in np.linspace(a, c, 5)})
    rings = [_dash_ring(x, b.env, b.fine) for x in xs]
    mats = ["CabDash", "CabDark"]
    seg = {k: mats.index(m) for k, (_p, m) in enumerate(rings[0])}
    seg["cap0"] = seg["cap1"] = 0
    b.add("dash", "dash_body", loft([[p for p, _m in r] for r in rings]), mats, _by_tag(seg))
    # coarse: no faces the cabin never shows (the slab's bottom sits in the tongue, its back in the
    # dash; the tongue's top is in the dash, its back faces the firewall, its bottom is under the floor)
    b.add("dash", "dash_stack", _box_without(STACK, (0, 4), b.fine), ["CabDash"], bevel=0.006, segments=2)
    b.add("dash", "dash_tongue", _box_without(TONGUE, (0, 1, 4), b.fine), ["CabDash"], bevel=0.008, segments=2)
    if b.fine:
        _dash_details(b)


def _box_without(spec, hidden, fine):
    """box() minus the faces `hidden` (face order -z, +z, -y, +x, +y, -x) in the coarse build; the
    full twin keeps the closed box so its bevels stay clean."""
    v, f, t = box(*spec)
    if fine:
        return v, f, t
    keep = [i for i in range(6) if i not in hidden]
    return v, [f[i] for i in keep], [t[i] for i in keep]


def _proud_box(b, piece, x0, x1, z0, z1, face, proud, mat="CabDash", name="detail"):
    """A small block standing `proud` off a face given as y(z): the detail's back sits 3 mm inside it."""
    yb0, yb1 = face(z0) + 0.003, face(z1) + 0.003
    yf0, yf1 = face(z0) - proud, face(z1) - proud
    corners = [(x0, yf0, z0), (x1, yf0, z0), (x1, yb0, z0), (x0, yb0, z0),
               (x0, yf1, z1), (x1, yf1, z1), (x1, yb1, z1), (x0, yb1, z1)]
    return b.add(piece, name, hexa(corners), [mat], smooth=False)


def _frame_boxes(b, piece, x0, x1, z0, z1, w, face, proud, name):
    for i, (a0, a1, c0, c1) in enumerate(((x0, x1, z1 - w, z1), (x0, x1, z0, z0 + w), (x0, x0 + w, z0, z1), (x1 - w, x1, z0, z1))):
        _proud_box(b, piece, a0, a1, c0, c1, face, proud, name="%s%d" % (name, i))


def _dash_details(b):
    """Full twin only: relief the bake turns into AO / cavity under the painted decal."""
    stack = lambda z: STACK[2]                              # noqa: E731  the slab face is vertical
    for i, (x0, x1) in enumerate(((-0.125, -0.025), (0.025, 0.125))):          # centre vents: frame + 3 slats
        _frame_boxes(b, "dash", x0, x1, 1.100, 1.155, 0.006, stack, 0.005, "cvent%d_" % i)
        for k in range(3):
            z = 1.111 + 0.0135 * k
            _proud_box(b, "dash", x0 + 0.006, x1 - 0.006, z, z + 0.004, stack, 0.004, name="cslat%d_%d" % (i, k))
    _frame_boxes(b, "dash", -0.092, 0.092, 0.972, 1.068, 0.006, stack, 0.005, "radio")   # radio bezel
    for i, x in enumerate((-0.075, 0.0, 0.075)):           # HVAC knobs, 1.2 cm proud
        b.add("dash", "knob%d" % i, tube((x, STACK[2] + 0.002, 0.915), (x, STACK[2] - 0.012, 0.915), 0.020, 16), ["CabDash"], smooth=ROUND)
    _frame_boxes(b, "dash", -0.110, 0.110, 0.758, 0.822, 0.006, stack, 0.006, "tray")    # tray lip
    _proud_box(b, "dash", 0.23, 0.65, 0.900, 1.060, _face_y, 0.004, name="glovebox")     # glovebox lid
    _proud_box(b, "dash", 0.415, 0.465, 1.032, 1.050, _face_y, 0.008, name="glove_latch")
    for sx in (-1, 1):                                     # side vents: frame + 2 slats
        x0, x1 = sorted((sx * 0.600, sx * 0.700))
        _frame_boxes(b, "dash", x0, x1, 1.060, 1.130, 0.006, _face_y, 0.005, "svent%+d_" % sx)
        for k in range(2):
            z = 1.078 + 0.020 * k
            _proud_box(b, "dash", x0 + 0.006, x1 - 0.006, z, z + 0.005, _face_y, 0.004, name="sslat%+d_%d" % (sx, k))
    for i, (x, z) in enumerate(((-0.685, 0.965), (-0.645, 0.965), (-0.685, 1.010), (-0.645, 1.010))):   # switch bank
        _proud_box(b, "dash", x - 0.012, x + 0.012, z - 0.012, z + 0.012, _face_y, 0.005, name="switch%d" % i)


# ----------------------------------------------------------------------------------------------- binnacle
# The RD1's cowl is an oval hood (DSC_7939: a broad arch over the three dials, its cheeks running down into
# the dash), not the sharp-cornered box of v8 (CAB-11, 2026-10-17). Section (x, z) at the lip: an outer and
# an inner superellipse arch (HOOD_N) on the same foot line, 2 cm cheeks and a 2.2 cm top between them;
# the cluster pod is the inner arch 1 mm in, closed along the bottom, so it fills the opening exactly.
HOOD_C, HOOD_Z0 = -0.390, 1.025   # arch centre x and foot height (the old box: x -0.605..-0.175, top 1.270)
HOOD_OUT, HOOD_IN = (0.215, 0.245), (0.195, 0.223)        # (half width, height) of the outer / inner arch
HOOD_N = 2.8                      # superellipse exponent: 2 = a half ellipse, higher = squarer shoulders
HOOD_Y = (0.478, 0.535, 0.665)    # lip, behind the pod, buried in the dash top (top lowered to 1.15)
HOOD_BURY = 1.150                 # the buried ring's top
POD_Z0 = 1.030                    # pod bottom (5 mm over the cheeks' feet)
POD_FACE = ((0.490, 1.030), (0.515, 1.226))                # (y, z): the tilted face's lean (y at two heights)
POD_BACK = 0.540
CLUSTER = (-0.575, -0.225, 1.035, 1.165)                   # decal box on the face (bake_atlas TEXTURED CabDark)


def _arch(half, height, n, z0=HOOD_Z0):
    """Superellipse arch from its right foot over the top to its left foot, n + 1 points."""
    e = 2.0 / HOOD_N
    out = []
    for i in range(n + 1):
        t = math.pi * i / n
        c, s = math.cos(t), math.sin(t)
        out.append((HOOD_C + half * math.copysign(abs(c) ** e, c), z0 + height * abs(s) ** e))
    return out


def _pod_face_y(z):
    (y0, z0), (y1, z1) = POD_FACE
    return y0 + (y1 - y0) * (z - z0) / (z1 - z0)


def binnacle(b):
    n = 30 if b.fine else 10                               # arch segments: 6 / 18 degrees (30 read as facets from the seat)
    outer = _arch(*HOOD_OUT, n)
    inner = _arch(*HOOD_IN, n)[::-1]                       # back from the left foot to the right one
    sect = outer + inner
    rings = []
    for i, y in enumerate(HOOD_Y):
        k = 1.0 if i < 2 else (HOOD_BURY - HOOD_Z0) / (HOOD_Z0 + HOOD_OUT[1] - HOOD_Z0)
        rings.append([(x, y, HOOD_Z0 + (z - HOOD_Z0) * k) for x, z in sect])
    b.add("binnacle", "hood", loft(rings, True, False), ["CabDark"], bevel=0.006, segments=2)   # rear end: inside the dash
    # the pod: the inner arch 1 mm in, its foot at POD_Z0; front = the cluster face (tilted), back at POD_BACK
    face = [(x, max(z, POD_Z0)) for x, z in _arch(HOOD_IN[0] - 0.001, HOOD_IN[1] - 0.001, n)]
    face = [face[0]] + [p for p in face[1:-1] if p[1] > POD_Z0 + 1e-4] + [face[-1]]
    front = [(x, _pod_face_y(z), z) for x, z in face]
    back = [(x, POD_BACK, z) for x, z in face]
    V, F, _t = loft([front, back])
    m = len(face)
    # loft band k runs from point k to k + 1: the last one (left foot back to the right foot) is the bottom;
    # the sides and top lie against the hood's inside and the back is under it: the coarse pod keeps the
    # cluster face and the bottom. (No raised dial bezels in the full twin: their side-facing faces fell
    # outside the decal's normal gate and baked as a dotted grey ring round each dial.)
    tags = list(range(m)) + ["face", "back"]                # loft's cap0 is the first ring (front), cap1 the back
    b.add("binnacle", "pod", (V, F, tags), ["CabDark"], smooth=False,
          keep=None if b.fine else (lambda t: t in ("face", m - 1)))


# ----------------------------------------------------------------------------------------------- wheel, column
def _wheel_frame():
    n = N_WHEEL
    h = (X - n * X.dot(n)).normalized()                    # in-plane right
    up = n.cross(h).normalized()                           # in-plane up (z-ish)
    if up.z < 0:
        up = -up
    return h, up, n


def wheel(b):
    h, up, n = _wheel_frame()
    c = C_WHEEL
    # rim: 24 segments coarse (2026-10-17: the 18-gon read as a polygon from the driver's seat, 0.45 m away)
    seg, ring = (36, 12) if b.fine else (24, 6)
    b.add("wheel", "rim", torus(c, h, up, R_RIM, T_RIM, seg, ring), ["CabDark"], smooth=ROUND)
    # hub pad: a rounded block over the airbag, 17 x 13 cm, 5.5 cm deep, standing 4.5 cm toward the driver;
    # a superellipse (the RD1's rounded-square pad, DSC_7939), 16 points in the full twin, 12 coarse (the
    # coarse octagon read as a stop sign from the seat)
    a, bb = 0.085, 0.065
    pts = [(a * math.copysign(abs(math.cos(t)) ** 0.6, math.cos(t)), bb * math.copysign(abs(math.sin(t)) ** 0.6, math.sin(t)))
           for t in np.linspace(0, 2 * math.pi, 16 if b.fine else 12, endpoint=False)]
    rings = [[c + h * px + up * py + n * off for px, py in pts] for off in (-0.012, 0.045)]
    b.add("wheel", "hub", loft(rings), ["CabDark"], bevel=0.012, segments=3, smooth=SOFT)
    # four spokes: 9 and 3 o'clock 8 deg low, two at the bottom 28 deg either side of straight down
    for i, deg in enumerate((-8.0, 188.0, 242.0, 298.0)):
        t = math.radians(deg)
        d = math.cos(t) * h + math.sin(t) * up
        s = -math.sin(t) * h + math.cos(t) * up
        rings = []
        for rad in (0.055, R_RIM - 0.004):
            p = c + d * rad
            rings.append([p + s * sx * 0.0175 + n * sz * 0.011 for sx, sz in ((-1, -1), (1, -1), (1, 1), (-1, 1))])
        b.add("wheel", "spoke%d" % i, loft(rings, False, False), ["CabDark"], bevel=0.004, segments=2)
    if b.fine:                                             # the H on the hub pad, 4 x 4 cm with 1 cm strokes, 2 cm above
        hc = c + n * 0.046 + up * 0.020                    # centre (5 mm strokes vanished at the sheet's ~3.6 texels/cm)
        # moulded into the pad, a shade lighter than it (DSC_7939): in "Metal" it was a light-grey block, the
        # brightest thing in the driver's view
        for (px, py, hx, hy) in ((-0.015, 0.0, 0.005, 0.020), (0.015, 0.0, 0.005, 0.020), (0.0, 0.0, 0.015, 0.005)):
            b.add("wheel", "h_logo", obox(hc + h * px + up * py, h, up, n, hx, hy, 0.0015), ["CabDash"], smooth=False)
        # the two horn buttons where the side spokes meet the pad (DSC_7939), 2.4 x 2.8 cm, 4 mm proud
        for side in (-1, 1):
            p = c + n * 0.045 + h * side * 0.064 - up * 0.004
            b.add("wheel", "horn", obox(p, h, up, n, 0.012, 0.014, 0.004), ["CabDark"], bevel=0.002)


def column(b):
    h, up, n = _wheel_frame()
    c = C_WHEEL
    sides = 16 if b.fine else 8
    p0, p1 = c, c - n * 0.24                               # from inside the hub to 4 cm inside the dash face (y 0.61)
    b.add("column", "shroud", tube(p0, p1, 0.050, sides, False, False, r1=0.045, phase=math.pi / sides), ["CabDark"], smooth=ROUND)
    pc = c - n * 0.050                                     # stalks 5 cm behind the wheel
    for i, side in enumerate((-1, 1)):                     # turn signals left, wipers right, 10 deg back
        d = (h * side * math.cos(math.radians(10)) - n * math.sin(math.radians(10))).normalized()
        b.add("column", "stalk%d" % i, tube(pc + d * 0.03, pc + d * 0.14, 0.009, 12 if b.fine else 6, False, True, r1=0.007),
              ["CabDark"], smooth=ROUND)
    if SHIFTER == "column":                                # automatic: right side, 25 deg down, a little toward the driver
        ps = c - n * 0.080 - up * 0.012
        d = (h * math.cos(math.radians(25)) - up * math.sin(math.radians(25)) + n * 0.15).normalized()
        tip = ps + d * 0.20
        b.add("column", "shifter", tube(ps + d * 0.03, tip, 0.0085, 12 if b.fine else 6, False, False), ["CabDark"], smooth=ROUND)
        b.add("column", "shift_knob", tube(tip - d * 0.01, tip + d * 0.035, 0.014, 12 if b.fine else 6), ["CabDark"], bevel=0.004, smooth=ROUND)
    else:                                                  # 5-speed: floor stalk out of the stack's foot, boot, knob
        base = Vector((-0.02, 0.52, FLOOR + 0.06))
        top = Vector((-0.02, 0.44, 0.80))
        lean = Vector((0, -0.08, 1)).normalized()
        b.add("column", "shift_boot", tube(base - Z * 0.07, base + Z * 0.03, 0.06, 12 if b.fine else 6, r1=0.025), ["CabDark"], smooth=ROUND)
        b.add("column", "shifter", tube(base, top, 0.009, 12 if b.fine else 6, False, False), ["Metal"], smooth=ROUND)
        b.add("column", "shift_knob", tube(top - lean * 0.01, top + lean * 0.045, 0.020, 12 if b.fine else 6), ["CabDark"],
              bevel=0.006, smooth=ROUND)


# ----------------------------------------------------------------------------------------------- seats
# v8 (2026-10-12, feedback: "the interior, the seats, they're nice, but I think you can make them
# better"). RD1 cloth buckets after the two photos (1999 EX press car, 1999 EX dealer car): a cushion
# with low rounded side bolsters, a striped insert from the bight to a plain front roll and a crease
# across it ahead of the pocket; a backrest with side wings, a slight lumbar, a plain band over the
# insert and a scooped lower back; a separate headrest on two posts; a dark plastic cover over the
# recliner on the outboard side; the riser on its rails. The split rear bench: two halves with the same
# sections, a bolster on the outboard side only, a seam between the centre seat and the outboard one.
#
# Every seat is built in its passenger's frame (s forward, h up, metres from the hip in
# gen_scripts.PASSENGERS), so the vanilla seated pose (Bob_IdleDriving; scratch seats/envelope.py)
# fits by construction:
#   * insert top 0.143 under the hip (SIT_DROP 0.140; the buttocks hang 0.137);
#   * the front roll ends 0.355 ahead of the hip: the pose's calves are 0.34 ahead at 6-12 cm under the
#     hip, 0.36 at 15 cm, 0.39 at 21 cm (the old cushions ran to 0.46: calves 4-5 cm in);
#   * the backrest face behind the pelvis and back (rearmost 0.125-0.146 at hip height, 0.174 at
#     +0.30), reclined ~13 deg like the pose's torso (the old 17-20 deg faces put the pelvis 6-7 cm in);
#   * the front backrest's lower back clear of the rear passenger's shins (their front 0.30 / 0.24 /
#     0.19 behind the front hip at 0 / 7 / 13 cm under it): 13 cm thick at the shoulders, 4.5 at the bight.
# The coarse build (what ships) is the chord of the full twin: the same key points, corners chamfered
# or square instead of rounded, fewer stations across, the faces nobody sees dropped. The full twin
# adds the rounding, the seams (SeatSeam grooves, 1.6 cm: two texels of the 1024 interior sheet) and
# the small parts the bake paints onto the coarse surfaces (rails, recline lever, post collars).
SEAT_MATS = ["SeatBolster", "SeatCloth", "SeatSeam", "CabDark", "Metal", "Interieur_sol"]   # carpet: the rear backs (_rear_back_mat)
SEAM_W, SEAM_D = 0.016, 0.005     # seam groove width and depth (full twin)
SEAT_RS = 0.025                   # rounding of the seats' side edges (full twin; the coarse side sits halfway in)
COARSE_DROP = ("bottom", "rear", "hidden")      # labels the coarse build drops by default (backrest bottoms, under the deck)
# cushions (front and bench): insert top (s, h), the front roll, the rear end under the backrest
SEAT_TOP = ((-0.160, -0.100), (-0.060, -0.143), (0.060, -0.143), (0.200, -0.130), (0.355, -0.120))
SEAT_NOSE = 0.355
F_BOTTOM, F_REAR = -0.255, -0.160                         # front: underside over the riser (front roll 14 cm)
B_BOTTOM, B_REAR = -0.285, -0.150                         # bench: skirt 2 cm over the carpet, rear end at y -0.95
F_W, F_I, F_CREST, F_RISE = 0.250, 0.135, 0.195, 0.042   # front cushion half-width, insert, bolster crest and rise
B_INNER, B_SEAMS, B_CREST, B_OUT, B_RISE = 0.012, (0.20, 0.52), 0.60, 0.70, 0.030   # bench half across |x|
# backrest side sections (s, h, corner radius [coarse, full], label of the segment starting there):
# up the face, over the top, down the back
F_BACK = ((-0.135, -0.135, 0.0, "front"),        # bight: meets the cushion top
          (-0.148, -0.040, 0.0, "front"),
          (-0.160, 0.100, 0.0, "front"),         # lumbar
          (-0.185, 0.260, 0.0, "front"),
          (-0.205, 0.360, 0.0, "upper"),         # plain band over the insert
          (-0.222, 0.465, (0.0, 0.040), "top"),
          (-0.325, 0.470, (0.0, 0.040), "back"),
          (-0.330, 0.320, 0.0, "back"),
          (-0.285, 0.100, 0.0, "back"),          # scooped: the rear passenger's knees and shins
          (-0.225, -0.040, 0.0, "back"),
          (-0.180, -0.140, 0.0, "bottom"))
F_BACK_COARSE = (0, 2, 5, 6, 7, 8, 10)
F_BW, F_BW_TOP, F_BI, F_WING, F_SEAM_H = 0.255, 0.235, 0.140, 0.050, 0.350
B_BACK = ((-0.135, -0.130, 0.0, "front"),
          (-0.148, -0.030, 0.0, "front"),
          (-0.160, 0.100, 0.0, "front"),
          (-0.190, 0.270, 0.0, "front"),
          (-0.208, 0.355, 0.0, "upper"),
          (-0.228, 0.425, (0.0, 0.035), "top"),
          (-0.315, 0.430, (0.0, 0.035), "back"),
          (-0.310, 0.300, 0.0, "back"),          # the back seen from the cargo bay
          (-0.250, -0.030, 0.0, "hidden"),       # meets the cargo deck (z 0.766) at y -1.05
          (-0.190, -0.150, 0.0, "hidden"))       # inside the floor's riser under the bench
B_BACK_COARSE = (0, 2, 5, 6, 7, 8, 9)
B_WING, B_SEAM_H = 0.035, 0.340
# outboard recliner cover (s, h): a strip along the cushion's lower edge, a hump over the pivot
COVER = ((-0.205, -0.267), (0.300, -0.267), (0.300, -0.212), (0.000, -0.205), (-0.055, -0.100), (-0.205, -0.090))


def _smooth01(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def _rounded(pts, fine, n=3):
    """[(s, h, r, label)] closed -> [(s, h, label)]. r (or (r_coarse, r_full)) > 0: the corner becomes a
    chamfer (coarse) or a quadratic arc with n inner points (full), so the coarse ring is the full
    ring's chord. The arc points carry the corner's label."""
    out = []
    N = len(pts)
    for i, (s, h, r, lab) in enumerate(pts):
        r = (r[1] if fine else r[0]) if isinstance(r, tuple) else r
        if r <= 0.0:
            out.append((s, h, lab))
            continue
        P = Vector((s, h))
        a, c = Vector(pts[i - 1][:2]) - P, Vector(pts[(i + 1) % N][:2]) - P
        A = P + a.normalized() * min(r, 0.98 * a.length)
        C = P + c.normalized() * min(r, 0.98 * c.length)
        k = n if fine else 0
        out.append((A.x, A.y, lab))
        for j in range(1, k + 1):
            t = j / (k + 1)
            q = (1 - t) ** 2 * A + 2 * t * (1 - t) * P + t * t * C
            out.append((q.x, q.y, lab))
        out.append((C.x, C.y, lab))
    return out


def _inset(ring, d):
    """The closed section moved d inward (rounded side edges, the seam grooves)."""
    if d <= 0.0:
        return ring
    P = [Vector((s, h)) for s, h, _l in ring]
    N = len(P)
    area = sum(P[i].x * P[(i + 1) % N].y - P[(i + 1) % N].x * P[i].y for i in range(N))
    sgn = 1.0 if area > 0 else -1.0                        # counter-clockwise: the left normal points in
    out = []
    for i in range(N):
        ns = [Vector((-e.y, e.x)).normalized() * sgn for e in (P[i] - P[i - 1], P[(i + 1) % N] - P[i]) if e.length > 1e-9]
        if not ns:
            out.append(ring[i])
            continue
        m = sum(ns, Vector((0.0, 0.0)))
        m = m.normalized() if m.length > 1e-9 else ns[0]
        q = P[i] + m * (d / max(0.5, min(m.dot(v) for v in ns)))
        out.append((q.x, q.y, ring[i][2]))
    return out


def _cushion_ring(fine, bottom, rear, rise=0.0, groove=False, crease=True, tuck=0.09):
    """Cushion side section at one station, closed: the rear end rising into the backrest, the top (full
    twin, insert stations: the crease ahead of the pocket and the seam to the front roll), the front
    roll, back along the underside. rise lifts the top (bolsters), fading to 40 % at the roll; crease
    False keeps the crease flat (the bench: its seams already cut the insert into panels); tuck = how far
    the underside rises to the rear end."""
    def up(s):
        fade = 1.0 if s <= 0.10 else 1.0 - 0.6 * min(1.0, (s - 0.10) / (SEAT_NOSE - 0.10))
        return _lerp_table(SEAT_TOP, s) + rise * fade
    d = SEAM_D if groove else 0.0
    pts = [(rear, up(rear), 0.0, "top")]
    if fine:
        pts += [(s, up(s), 0.0, "top") for s in (-0.12, -0.06, 0.0, 0.06)]
        for g, after in ((0.120, "top"), (0.289, "nose")):
            lab = "groove" if crease or after == "nose" else "top"
            pts += [(g - SEAM_W / 2, up(g - SEAM_W / 2), 0.0, lab), (g, up(g) - (d if lab == "groove" else 0.0), 0.0, lab),
                    (g + SEAM_W / 2, up(g + SEAM_W / 2), 0.0, after)]
            if after == "top":
                pts.append((0.20, up(0.20), 0.0, "top"))
    else:
        pts.append((-0.06, up(-0.06), 0.0, "top"))
    pts.append((SEAT_NOSE, up(SEAT_NOSE), 0.055, "nose"))                # the front roll
    pts.append((SEAT_NOSE - 0.005, bottom, (0.0, 0.025), "bottom"))
    if fine:
        pts.append((0.20, bottom, 0.0, "bottom"))
    # the underside rises behind s 0.10: the rear passengers' toes reach y -0.02 at z 0.55-0.58
    pts += [(0.10, bottom, 0.0, "bottom"), (rear, bottom + tuck, 0.0, "rear")]
    return _rounded(pts, fine)


def _back_ring(fine, sect, coarse, seam_h, wing=0.0, groove=False):
    """Backrest side section at one station. Full twin: the face resampled every ~8 cm with the
    insert's top seam at seam_h (a SEAM_D groove on insert stations); coarse: the `coarse` points of
    sect. wing pushes the face forward (bolster stations): 35 % at the bight, half at the top corner."""
    k_top = next(i for i, p in enumerate(sect) if p[3] == "top")
    knots = [(p[1], p[0]) for p in sect[:k_top + 1]]       # the face: s over h, bight .. top corner

    def at(h, lab, w, dd=0.0):
        return (_lerp_table(knots, h) + wing * w - dd, h, 0.0, lab)
    if fine:
        h0, h1, lo = sect[0][1], sect[k_top][1], seam_h - SEAM_W / 2
        pts = [at(h, "front", 0.35 if i == 0 else 1.0) for i, h in enumerate(np.linspace(h0, lo, 7)[:-1])]
        pts += [at(lo, "groove", 1.0), at(seam_h, "groove", 1.0, SEAM_D if groove else 0.0),
                at(seam_h + SEAM_W / 2, "upper", 1.0), at((seam_h + h1) / 2, "upper", 1.0)]
        rest = list(sect[k_top:])
    else:
        pts = [at(sect[i][1], sect[i][3], 0.35 if i == 0 else 1.0) for i in coarse if i < k_top]
        rest = [sect[i] for i in coarse if i >= k_top]
    s, h, r, lab = rest[0]
    rest[0] = (s + wing * 0.5, h, r, lab)
    return _rounded(pts + rest, fine)


def _headrest_ring(fine, t, hh):
    """Headrest section about its centre (s forward, h up): t thick, 2 hh tall, rounded. The two top
    corners' roundings share the top edge: on the rear headrest (t 0.09) their 0.045 + 0.040 overran the
    7.8 cm edge, the ring crossed itself over the top, and recalc_face_normals oriented the whole solid by
    that folded sliver: every rear headrest shipped 98 % inside-out (CAB-3, 2026-10-17). Where they
    overrun it they are scaled to 96 % of the edge; the front headrest (t 0.10, 8.5 of 8.8 cm) keeps its
    corners exactly (a 0.5 % trim of them uncovered a body back face at the A-pillar from the rear seat)."""
    p1, p2 = Vector((t / 2 - 0.012, hh)), Vector((-t / 2, hh - 0.005))
    r1, r2 = 0.045, 0.040
    edge = (p1 - p2).length
    k = 1.0 if r1 + r2 <= edge else 0.96 * edge / (r1 + r2)
    return _rounded([(t / 2, -hh, (0.0, 0.025), "front"), (p1.x, p1.y, r1 * k, "top"),
                     (p2.x, p2.y, r2 * k, "back"), (-t / 2 + 0.005, -hh, (0.0, 0.020), "under")], fine)


def _side_stations(u_edge, inward, rs, kind):
    """Stations rounding a side edge, in loft order: [(u, inset, kind)] from the cap (inset rs) to the
    full section rs further in (a quarter circle in the (u, inset) plane)."""
    out = [(u_edge + inward * rs * (1.0 - math.sin(math.radians(a))), rs * (1.0 - math.cos(math.radians(a))), kind)
           for a in (90, 60, 30, 0)]
    return out if inward > 0 else out[::-1]


def _seam_stations(u, inward, outer="edge_b"):
    """A seam groove across the loft at u: edge (outer side), floor (SEAM_D in), edge (insert side)."""
    return [(u - inward * SEAM_W / 2, 0.0, outer), (u, SEAM_D, "seam"), (u + inward * SEAM_W / 2, 0.0, "edge_i")][::int(inward)]


def _mirror(left):
    return [(-u, d, k) for u, d, k in reversed(left)]


def _cushion_mat(kind, lab):
    if kind == "cap":
        return "SeatBolster"
    if lab in ("bottom", "rear"):
        return "CabDark"                                   # the pan under the cushion
    if kind == "seam" and lab in ("top", "groove"):
        return "SeatSeam"
    if kind == "insert":
        return {"top": "SeatCloth", "groove": "SeatSeam"}.get(lab, "SeatBolster")
    return "SeatBolster"


def _back_mat(kind, lab):
    if kind == "seam" and lab in ("front", "groove"):
        return "SeatSeam"
    if kind == "insert":
        return {"front": "SeatCloth", "groove": "SeatSeam"}.get(lab, "SeatBolster")
    return "SeatBolster"


def _seat_loft(b, piece, name, stations, ring_of, place, mat_of, drop=COARSE_DROP):
    """Loft across x through side sections: stations [(u, inset, kind)] in order, ring_of(u, kind) ->
    [(s, h, label)] (the same length at every station), place(u, s, h) -> model point. Quads between
    neighbouring stations, an n-gon cap at both ends (the seat's sides). An interval is 'seam' if it
    touches a seam floor, 'insert' between insert stations, 'bolster' otherwise; mat_of(kind, label).
    The coarse build drops the COARSE_DROP faces (undersides, ends inside the backrest or the floor)."""
    rings = [(u, kind, _inset(ring_of(u, kind), inset)) for u, inset, kind in stations]
    n = len(rings[0][2])
    assert all(len(r) == n for _u, _k, r in rings), name
    V = [tuple(place(u, s, h)) for u, _k, r in rings for s, h, _l in r]
    F, tags = [], []
    for j in range(len(rings) - 1):
        ka, kb = rings[j][1], rings[j + 1][1]
        kind = "seam" if "seam" in (ka, kb) else ("insert" if {ka, kb} <= {"insert", "edge_i"} else "bolster")
        for k in range(n):
            k2 = (k + 1) % n
            F.append((j * n + k, j * n + k2, (j + 1) * n + k2, (j + 1) * n + k))
            tags.append((kind, rings[j][2][k][2]))
    last = (len(rings) - 1) * n
    F += [tuple(reversed(range(n))), tuple(last + k for k in range(n))]
    tags += [("cap", "cap"), ("cap", "cap")]
    keep = None if b.fine else (lambda t: t[1] not in drop)
    used = {mat_of(*t) for t in tags if keep is None or keep(t)}
    names = [m for m in SEAT_MATS if m in used]
    return b.add(piece, name, (V, F, tags), names, lambda t: names.index(mat_of(*t)) if mat_of(*t) in names else 0,
                 smooth=SOFT, keep=keep)


def _headrest(b, piece, hip, base, w, hh, t, posts, gap, recline=8.0, tilt=8.0, caps=False):
    """Headrest on two posts: base (s, h) where the posts enter the backrest top, the posts leaning
    back `recline` deg, the headrest turned `tilt` deg forward of them, gap = post showing. caps: close
    the posts' ends (a headrest out of its seat shows them)."""
    q = math.radians(recline)
    a = Vector((0.0, -math.sin(q), math.cos(q)))
    q = math.radians(recline - tilt)
    up, fw = Vector((0.0, -math.sin(q), math.cos(q))), Vector((0.0, math.cos(q), math.sin(q)))
    p0 = hip + Vector((0.0, base[0], base[1]))
    c = p0 + a * (gap + hh)
    if b.fine:
        stations = _side_stations(-w, 1.0, 0.02, "side") + _mirror(_side_stations(-w, 1.0, 0.02, "side"))
    else:
        stations = [(-w, 0.0, "side"), (w, 0.0, "side")]
    _seat_loft(b, piece, "headrest", stations, lambda u, kind: _headrest_ring(b.fine, t, hh),
               lambda u, s, h: c + Vector((u, 0.0, 0.0)) + fw * s + up * h, lambda kind, lab: "SeatBolster")
    for sx in (-1, 1):
        p = p0 + Vector((sx * posts, 0.0, 0.0))
        b.add(piece, "post", tube(p - a * 0.035, p + a * (gap + 0.035), 0.006, 8 if b.fine else 3, caps, caps), ["Metal"],
              smooth=ROUND)
        if b.fine:                                         # plastic collars where the posts enter the backrest
            b.add(piece, "post_collar", tube(p - a * 0.006, p + a * 0.008, 0.013, 12), ["CabDark"], smooth=ROUND)


def front_seat(b, hip):
    piece = "seat_driver" if hip.x < 0 else "seat_passenger"
    out = 1.0 if hip.x > 0 else -1.0                       # outboard
    if b.fine:
        left = (_side_stations(-F_W, 1.0, SEAT_RS, "side") + [(u, 0.0, "bolster") for u in (-0.215, -F_CREST, -0.175, -0.155)]
                + _seam_stations(-F_I, 1.0) + [(-0.07, 0.0, "insert")])
        stations = left + [(0.0, 0.0, "insert")] + _mirror(left)
    else:
        stations = [(-F_W, SEAT_RS / 2, "side"), (-F_CREST, 0.0, "bolster"), (-F_I, 0.0, "edge_i"),
                    (F_I, 0.0, "edge_i"), (F_CREST, 0.0, "bolster"), (F_W, SEAT_RS / 2, "side")]

    def rise(u):
        a = abs(u)
        if a <= F_I:
            return 0.0
        if a <= F_CREST:
            return F_RISE * _smooth01((a - F_I) / (F_CREST - F_I))
        return F_RISE - (F_RISE - 0.012) * ((a - F_CREST) / (F_W - F_CREST)) ** 2
    _seat_loft(b, piece, "cushion", stations,
               lambda u, kind: _cushion_ring(b.fine, F_BOTTOM, F_REAR, rise(u), kind in ("insert", "edge_i")),
               lambda u, s, h: hip + Vector((u, s, h)), _cushion_mat,
               drop=())                       # closed: the overhanging underside and the rear end show from low eyes
    # backrest: 51 cm at the bottom tapering to 47 at the top, wings 5 cm proud
    if b.fine:
        left = (_side_stations(-F_BW, 1.0, SEAT_RS, "side") + [(u, 0.0, "bolster") for u in (-0.215, -0.19, -0.165)]
                + _seam_stations(-F_BI, 1.0) + [(-0.07, 0.0, "insert")])
        stations = left + [(0.0, 0.0, "insert")] + _mirror(left)
    else:
        stations = [(-F_BW, SEAT_RS / 2, "side"), (-0.205, 0.0, "bolster"), (-F_BI, 0.0, "edge_i"),
                    (F_BI, 0.0, "edge_i"), (0.205, 0.0, "bolster"), (F_BW, SEAT_RS / 2, "side")]

    def taper(h):
        return 1.0 + (F_BW_TOP / F_BW - 1.0) * max(0.0, min(1.0, (h - 0.10) / 0.37))
    _seat_loft(b, piece, "backrest", stations,
               lambda u, kind: _back_ring(b.fine, F_BACK, F_BACK_COARSE, F_SEAM_H,
                                          F_WING * _smooth01((abs(u) - F_BI) / (F_BW - F_BI)), kind in ("insert", "edge_i")),
               lambda u, s, h: hip + Vector((u * taper(h), s, h)), _back_mat)
    _headrest(b, piece, hip, (-0.245, 0.467), 0.135, 0.095, 0.10, 0.075, 0.06)
    # outboard recliner cover: inner face 4 mm inside the cushion side, 1 cm proud of the backrest's
    x0, x1 = hip.x + out * (F_W - 0.004), hip.x + out * (F_BW + 0.010)
    V, F, tags = loft([[(x, hip.y + s, hip.z + h) for s, h in COVER] for x in (x0, x1)])
    b.add(piece, "recliner_cover", (V, F, tags), ["CabDark"], bevel=0.004, segments=2,
          keep=None if b.fine else (lambda t: t != "cap0"))     # the inner face is inside the seat
    if b.fine:                                             # the recline lever, painted onto the cover
        xa, xb = sorted((x1, x1 + out * 0.015))
        b.add(piece, "recline_lever", box(xa, xb, hip.y + 0.02, hip.y + 0.09, hip.z - 0.172, hip.z - 0.158), ["CabDark"],
              bevel=0.003)
    # the riser the cushion sits on (behind the front wells, clear of the rear passengers' toes at y -0.02)
    b.add(piece, "riser", _box_without((hip.x - 0.18, hip.x + 0.18, hip.y + 0.08, hip.y + 0.30, FLOOR - 0.005,
                                        hip.z + F_BOTTOM + 0.004), (0,), b.fine), ["CabDark"], bevel=0.006)
    if b.fine:                                             # seat rails, painted onto the riser's foot
        for sx in (-1, 1):
            xa = hip.x + sx * 0.17
            b.add(piece, "rail", box(xa - 0.015, xa + 0.015, hip.y - 0.02, hip.y + 0.36, FLOOR - 0.002, FLOOR + 0.030), ["Metal"],
                  bevel=0.004)


REAR_SEAT_ATTR = "rear_seat"      # INT face attribute: 1 on the rear bench's faces in `cabin` (see rear_seats)
# Fold-flat rear seats (function feature, 2026-10-14; chose fold-flat: folded must LOOK folded). The
# RD1's own procedure (2001 CR-V owner's manual pp. 82-83, "Folding the Rear Seat"): pull the strap and
# tilt the seat bottom forward, remove the head restraint and strap it behind the seat bottom, then pivot
# the seat-back forward. The back lies where the cushion was, its rear face a load floor level with the
# cargo deck; the tumbled cushion leans against the front seats. Each half is posed rigidly:
#   cushion   turned CUSHION_TUMBLE deg forward about its front-bottom edge (the floor hinge), leaning
#             back from vertical enough to clear the front seat backs (rear face at y -0.45..-0.55)
#   backrest  cut at the deck (h > BACK_CUT: what stood in the floor riser has nowhere to go folded),
#             turned BACK_FOLD deg forward about the point of its rear face at the deck edge (y -1.05,
#             BACK_HINGE_Z): its rear face is then the top, at the deck height
#   headrest  with its posts, face down against the tumbled cushion's rear face, HEAD_STORE up it
# 2026-10-18 (feedback, with photos of a real cargo bay: "i should see the seats"; chose "backs fold onto the
# cushions"): seen from the gate the tumbled cushions read as two black boxes with headrests on them, not as
# seats. FOLD_ONTO: the cushion stays where it is and the back pivots forward onto it about its front edge at
# the cut, its cloth face down on the cushion, its carpeted rear face up (the bed), the headrest taken off.
FOLD_ONTO = True
ONTO_DEG = 98.9                   # the front face leans 8.9 deg back upright (B_BACK 1 -> 4): this lays it flat
ONTO_FACE_H = -0.100              # the folded front face's height off the hip: just over the bolsters (-0.11)
CUSHION_TUMBLE = 76.0             # deg; the seat surface faces forward and 14 deg up
BACK_FOLD = 98.0                  # deg: the rear face leans 8 deg back upright, so 98 lays it flat
BACK_CUT = -0.030                 # backrest section kept for the folded back: h >= this (B_BACK points 1..8)
BACK_HINGE_Z = 0.768              # model z of the hinge: the folded top flush with the cargo deck (z 0.766)
HEAD_STORE = 0.40                 # headrest centre along the tumbled cushion's rear face from the floor hinge
FOLD_OUT_LOW = 0.53               # folded back: outboard edge where it lies over the wheel housing (y < -0.94)


def _rear_side(b, hip, pose):
    """One half of the split bench in `pose` ("up" | "fold"): each half from |x| 0.012 to 0.70, its
    passenger at the hip (|x| 0.36). Returns the objects it added."""
    n0 = len(b.objs)
    fold = pose == "fold"
    side = 1.0 if hip.x > 0 else -1.0
    piece = "bench_" + ("left" if side < 0 else "right")
    s0, s1 = B_SEAMS
    if b.fine:
        stations = (_side_stations(B_INNER, 1.0, 0.010, "insert") + [(0.10, 0.0, "insert")]
                    + _seam_stations(s0, 1.0, "edge_i") + [(u, 0.0, "insert") for u in (0.28, 0.36, 0.44)]
                    + _seam_stations(s1, -1.0) + [(u, 0.0, "bolster") for u in (0.56, B_CREST, 0.64)]
                    + _side_stations(B_OUT, -1.0, SEAT_RS, "side"))
    else:
        stations = [(B_INNER, 0.0, "insert"), (s1, 0.0, "edge_i"), (B_CREST, 0.0, "bolster"), (B_OUT, SEAT_RS / 2, "side")]

    def rise(u):
        if u <= s1:
            return 0.0
        if u <= B_CREST:
            return B_RISE * _smooth01((u - s1) / (B_CREST - s1))
        return B_RISE - (B_RISE - 0.010) * ((u - B_CREST) / (B_OUT - B_CREST)) ** 2
    k = len(b.objs)
    _seat_loft(b, piece, "cushion", stations,
               lambda u, kind: _cushion_ring(b.fine, B_BOTTOM, B_REAR, rise(u), kind in ("insert", "edge_i"), crease=False,
                                                       tuck=0.03),
               lambda u, s, h: Vector((side * u, hip.y + s, hip.z + h)), _cushion_mat,
               # upright: 2 cm over the carpet, the rear end in the floor riser; tumbled both show: closed;
               # under a back folded onto it, the rear end shows from the cargo bay
               drop=(("bottom",) if FOLD_ONTO else ()) if fold else ("bottom", "rear"))
    if fold and not FOLD_ONTO:
        pivot = Vector((0.0, hip.y + SEAT_NOSE, hip.z + B_BOTTOM))
        _pose(b.objs[k:], pivot, -CUSHION_TUMBLE)
    # backrest: its lower back corner pulled in to |x| 0.53 (the wheel housing behind y -0.95 below
    # z 0.75, side wall at |x| 0.536); the cushion hides that corner from the cabin. Folded, the part of
    # the back that lies over the housing (its lowest 12 cm, at y < -0.94) is pulled in the same way
    if b.fine:
        stations = (_side_stations(B_INNER, 1.0, 0.010, "insert") + [(0.10, 0.0, "insert")]
                    + _seam_stations(s0, 1.0, "edge_i") + [(u, 0.0, "insert") for u in (0.28, 0.36, 0.44)]
                    + _seam_stations(s1, -1.0) + [(u, 0.0, "bolster") for u in (0.58, 0.64)]
                    + _side_stations(B_OUT, -1.0, SEAT_RS, "side"))
    else:
        stations = [(B_INNER, 0.0, "insert"), (s1, 0.0, "edge_i"), (B_OUT, SEAT_RS / 2, "side")]

    def bx(u, s, h):
        if fold:
            outer = B_OUT - (B_OUT - FOLD_OUT_LOW) * _smooth01((0.13 - h) / 0.05)
        else:
            outer = B_OUT - (B_OUT - 0.53) * _smooth01((-0.155 - s) / 0.03) * _smooth01((-0.02 - h) / 0.05)
        return side * (B_INNER + (u - B_INNER) * (outer - B_INNER) / (B_OUT - B_INNER))
    if fold:                                               # cut at the deck: B_BACK 1..8, closed by the cut
        sect = [B_BACK[1][:3] + ("front",)] + list(B_BACK[2:8]) + [(B_BACK[8][0], BACK_CUT, 0.0, "bottom")]
        coarse = (0, 1, 4, 5, 6, 7)
    else:
        sect, coarse = B_BACK, B_BACK_COARSE
    k = len(b.objs)
    _seat_loft(b, piece, "backrest", stations,
               lambda u, kind: _back_ring(b.fine, sect, coarse, B_SEAM_H,
                                          B_WING * _smooth01((u - s1) / (B_OUT - s1)), kind in ("insert", "edge_i")),
               lambda u, s, h: Vector((bx(u, s, h), hip.y + s, hip.z + h)), _rear_back_mat,
               drop=() if fold else COARSE_DROP)
    if fold and FOLD_ONTO:
        hinge = Vector((0.0, hip.y + B_BACK[1][0], hip.z + BACK_CUT))       # the front edge of the cut
        _pose(b.objs[k:], hinge, -ONTO_DEG, lift=ONTO_FACE_H - BACK_CUT)
    elif fold:
        hinge = Vector((0.0, hip.y + B_BACK[8][0], hip.z + BACK_CUT))
        _pose(b.objs[k:], hinge, -BACK_FOLD, lift=BACK_HINGE_Z - hinge.z)
    if fold and FOLD_ONTO:                                 # the head restraint comes off to fold the back
        return b.objs[n0:]
    k = len(b.objs)
    _headrest(b, piece, hip, (-0.250, 0.428), 0.125, 0.085, 0.09, 0.065, 0.05, caps=fold)
    if fold:
        _store_headrest(b.objs[k:], hip, (-0.250, 0.428), 0.085, 0.09, 0.05)
    return b.objs[n0:]


def _rear_back_mat(kind, lab):
    """The rear bench's backs: cloth on the front and over the top, a carpeted rear face like the real car's
    (feedback photo 2026-10-18: dark carpet on the back, the grey cloth only on top). Folded, that face is the bed."""
    if lab in ("back", "hidden", "bottom"):
        return "Interieur_sol"
    return _back_mat(kind, lab)


def _pose(objs, pivot, deg, lift=0.0):
    """Turn the objects deg about the x axis through pivot (negative: the top goes forward), then lift."""
    from mathutils import Matrix
    m = (Matrix.Translation(Vector((0.0, 0.0, lift)) + pivot) @ Matrix.Rotation(math.radians(deg), 4, 'X')
         @ Matrix.Translation(-pivot))
    for ob in objs:
        ob.data.transform(m)
        ob.data.update()


def _store_headrest(objs, hip, base, hh, t, gap, recline=8.0, tilt=8.0):
    """The headrest (as _headrest built it, posts down) moved face-down onto the tumbled cushion's rear
    face, its centre HEAD_STORE up the face from the floor hinge, posts pointing to the floor."""
    from mathutils import Matrix
    q = math.radians(recline)
    a = Vector((0.0, -math.sin(q), math.cos(q)))
    q = math.radians(recline - tilt)
    up, fw = Vector((0.0, -math.sin(q), math.cos(q))), Vector((0.0, math.cos(q), math.sin(q)))
    c = hip + Vector((0.0, base[0], base[1])) + a * (gap + hh)       # the headrest's centre upright
    # the tumbled cushion: its underside line (before the turn: back along -y at h B_BOTTOM) and normal
    r = Matrix.Rotation(math.radians(-CUSHION_TUMBLE), 3, 'X')
    pivot = Vector((hip.x, hip.y + SEAT_NOSE, hip.z + B_BOTTOM))
    along = r @ Vector((0.0, -1.0, 0.0))                   # up the rear face (and a little back)
    out = r @ Vector((0.0, 0.0, -1.0))                     # off the rear face, toward the cargo bay
    centre = pivot + along * HEAD_STORE + out * (t / 2 + 0.004)
    src = Matrix((fw, up, Vector((1.0, 0.0, 0.0)))).transposed()      # columns: front, up, x
    dst = Matrix((-out, along, Vector((1.0, 0.0, 0.0)))).transposed()  # front against the cushion, up its face
    if dst.determinant() * src.determinant() < 0:          # keep it a rotation (no mirrored faces)
        dst = Matrix((-out, along, Vector((-1.0, 0.0, 0.0)))).transposed()
    rot = (dst @ src.inverted()).to_4x4()
    m = Matrix.Translation(centre) @ rot @ Matrix.Translation(-c)
    for ob in objs:
        ob.data.transform(m)
        ob.data.update()


def _function_active():
    """The function feature ships the bench as its own models (rear_seats): the cabin leaves it out."""
    try:
        import features
        return "function" in features.keys()
    except Exception as exc:  # noqa: BLE001  (a broken feature set must not lose the bench)
        print("CABIN warning: feature list unreadable (%s): the rear bench stays in the cabin" % exc)
        return False


def rear_bench(b, pose="up"):
    """The split bench in the cabin (upright), every face tagged REAR_SEAT_ATTR = 1. With the function
    feature (scripts/features/function.py) active the cabin does not build it at all (2026-10-17): the
    feature ships the bench as its own models, upright and folded (rear_seats), that its Lua switches,
    and the 192 coarse triangles it used to lift out after prep's decimation check counted against the
    cabin's BUDGET. The tag stays for a cabin built without the feature."""
    if _function_active():
        print("CABIN rear bench: left to the function feature's seat models")
        return
    for name, hip in hips().items():
        if not name.startswith("Rear"):
            continue
        for ob in _rear_side(b, hip, pose):
            me = ob.data
            attr = me.attributes.get(REAR_SEAT_ATTR) or me.attributes.new(REAR_SEAT_ATTR, 'INT', 'FACE')
            attr.data.foreach_set("value", [1] * len(me.polygons))


def rear_seats(pose, fine, name, collection=None):
    """Both halves of the rear bench in `pose` ("up" | "fold") as one object `name`, full detail (the
    bake's projection source) or coarse (what ships): the function feature's two seat models."""
    old = bpy.data.objects.get(name)
    if old is not None:
        bpy.data.objects.remove(old, do_unlink=True)
    if collection is None:
        ref = bpy.data.objects.get("cabin") or bpy.data.objects.get("body")
        collection = ref.users_collection[0] if ref else bpy.context.scene.collection
    b = Cab(collection, fine, None)
    for hname, hip in hips().items():
        if hname.startswith("Rear"):
            _rear_side(b, hip, pose)
    if pose == "up" and not fine:                          # the clearance audit the bench had in the cabin
        _audit(b.objs, Env())
    pieces = dict(b.pieces)
    ob = b.join(name)
    print("CABIN rear seats %-4s %-6s %5d tris (%s)" % (pose, "full" if fine else "coarse",
                                                        sum(len(p.vertices) - 2 for p in ob.data.polygons),
                                                        ", ".join("%s %d" % kv for kv in sorted(pieces.items()))))
    return ob


# ----------------------------------------------------------------------------------------------- small pieces
def tray(b):
    """The low cup-holder tray between the front seats (the photos: no tall console)."""
    x0, x1, y0, y1, z0, z1 = -0.09, 0.09, -0.06, 0.30, FLOOR - 0.005, 0.600
    if not b.fine:
        v, f, _t = box(x0, x1, y0, y1, z0, z1)
        b.add("tray", "tray", (v, f[1:], [0] * 5), ["CabDark"], smooth=False)       # no bottom
        return
    # full twin: two 5 cm deep cup wells (the bake darkens them through AO), walls round them
    zf = z1 - 0.05
    b.add("tray", "tray_base", box(x0, x1, y0, y1, z0, zf), ["CabDark"], bevel=0.008)
    cups = ((0.02, 0.10), (0.14, 0.22))
    walls = [(x0, x1, y0, cups[0][0]), (x0, x1, cups[0][1], cups[1][0]), (x0, x1, cups[1][1], y1)]
    for ya, yb in cups:
        walls += [(x0, -0.035, ya, yb), (0.035, x1, ya, yb)]
    for i, (a0, a1, c0, c1) in enumerate(walls):
        b.add("tray", "tray_wall%d" % i, box(a0, a1, c0, c1, zf - 0.002, z1), ["CabDark"], bevel=0.004)


def handbrake(b):
    """Thin lever between the tray and the driver's seat (tray edge x -0.09, cushion edge -0.13)."""
    p0, p1 = Vector((-0.110, -0.03, FLOOR + 0.01)), Vector((-0.110, -0.22, 0.630))
    sides = 12 if b.fine else 6
    b.add("tray", "brake_lever", tube(p0, p1, 0.012, sides, False, True), ["CabDark"], smooth=ROUND)
    d = (p1 - p0).normalized()
    b.add("tray", "brake_button", tube(p1 - d * 0.002, p1 + d * 0.010, 0.007, 8 if b.fine else 4, False, True), ["Metal"], smooth=ROUND)


def pedals(b):
    """Brake and accelerator (automatic: no clutch) in front of the driver; floor z 0.50-0.52 at y
    0.70-0.80, toe board rising to 0.69 at y 0.90."""
    t = math.radians(30)
    ax, fwd = Vector((0, math.sin(t), math.cos(t))), Vector((0, -math.cos(t), math.sin(t)))   # pad plane leans back 30 deg
    for name, c, w, l in (("brake", (-0.40, 0.765, 0.640), 0.075, 0.060), ("gas", (-0.255, 0.800, 0.600), 0.050, 0.140)):
        v, f, _t = obox(c, X, ax, fwd, w / 2, l / 2, 0.006)
        # faces: -z = toward the firewall (never seen): dropped
        b.add("pedals", name, (v, f[1:], [0] * 5), ["CabDark"], smooth=False)
    arm0, arm1 = Vector((-0.40, 0.785, 0.660)), Vector((-0.40, 0.82, 0.83))
    b.add("pedals", "brake_arm", tube(arm0, arm1, 0.008, 6 if b.fine else 4, False, False), ["CabDark"], smooth=ROUND)


# Rear-view mirror (CAB-12, 2026-10-17: v8's was a flat light-grey brick, its glass in kotris's "Metal").
# The RD1's is a black rounded housing round a dark glass, turned toward the driver. Sized to enclose
# what kotris left of his mirror on the body (faces at x -0.139..0.119, y 0.389..0.431, z 1.442..1.518,
# their face yawed 5.5 deg to the driver; pzview --probe, body faces 2890-2892 and 4302-4303).
MIRROR_C = Vector((-0.005, 0.400, 1.480))
MIRROR_HALF = (0.145, 0.018, 0.045)      # half length, depth, height
MIRROR_YAW = 5.5                         # deg: the glass turned toward the driver (x < 0)
MIRROR_R = 0.018                         # corner rounding of the section
MIRROR_TAPER = (0.97, 0.93)              # the back's length and height over the front's: a rounded shell, not a brick
MIRROR_RIM = 0.006                       # housing rim round the glass (full twin; the bake paints it on)


def _mirror_frame():
    q = math.radians(MIRROR_YAW)
    ax = Vector((math.cos(q), -math.sin(q), 0.0))           # along the mirror; its left end lies further back
    ay = Vector((math.sin(q), math.cos(q), 0.0))            # toward the windscreen: -ay faces the driver
    return ax, ay, Z


def _mirror_section(hx, hz, r, fine):
    """Rounded rectangle (u along, w up), counter-clockwise seen from the driver: chamfered corners
    (coarse) or quarter arcs (full twin)."""
    pts = []
    for cx, cz, a0 in ((hx - r, hz - r, 0), (-hx + r, hz - r, 90), (-hx + r, -hz + r, 180), (hx - r, -hz + r, 270)):
        steps = (0, 30, 60, 90) if fine else (0, 90)
        pts += [(cx + r * math.cos(math.radians(a0 + s)), cz + r * math.sin(math.radians(a0 + s))) for s in steps]
    return pts


def mirror(b):
    ax, ay, az = _mirror_frame()
    hx, hy, hz = MIRROR_HALF
    c = MIRROR_C

    def ring(scale, inset, dy):
        su, sw = scale
        return [c + ax * u + ay * dy + az * w for u, w in _mirror_section(hx * su - inset, hz * sw - inset,
                                                                         max(0.004, MIRROR_R * sw - inset), b.fine)]
    one = (1.0, 1.0)
    if b.fine:                                             # back, front rim, rim inner edge, the glass 2 mm in
        rings = [ring(MIRROR_TAPER, 0.0, hy), ring(one, 0.0, -hy), ring(one, MIRROR_RIM, -hy),
                 ring(one, MIRROR_RIM, -hy + 0.002)]
    else:
        rings = [ring(MIRROR_TAPER, 0.0, hy), ring(one, 0.0, -hy)]
    V, F, tags = loft(rings)
    # cap0 = the back (+ay, toward the windscreen), cap1 = the glass
    b.add("mirror", "mirror", (V, F, tags), ["CabDark", "CabMirror"], _by_tag({"cap1": 1}),
          bevel=0.004 if b.fine else 0.0, segments=2, smooth=SOFT)
    if b.fine:                                             # the day / night tab under the glass
        t = c - ay * (hy - 0.006) - az * (hz + 0.004)
        b.add("mirror", "mirror_tab", obox(t, ax, ay, az, 0.012, 0.006, 0.005), ["CabDark"], bevel=0.002)
    # the stem: from inside the housing's back to kotris's button on the glass (body, x 0, y 0.45, z 1.51)
    b.add("mirror", "mirror_stem", tube(c + ay * (hy - 0.006) + az * 0.012, (0.0, 0.446, 1.511), 0.008, 8 if b.fine else 4,
                                        False, False), ["CabDark"], smooth=ROUND)


def visors(b):
    """Sun visors folded up under the headliner, behind the windscreen header (headliner z 1.55-1.59
    at |x| 0.15-0.45, y 0.20-0.30; it drops to 1.46 at |x| 0.60, and the glass comes down to z 1.53
    at |x| 0.50, y 0.345: the visors stop at |x| 0.48, y 0.335, under both)."""
    for side in (-1, 1):
        x0, x1 = sorted((side * 0.11, side * 0.48))
        y0, y1 = 0.205, 0.335
        corners_top = []
        for (x, y) in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
            lim = [z for z in (b.env.headliner(x, y), b.env.ceiling(x, y, 1.30)) if z is not None]
            corners_top.append((x, y, (min(lim) - 0.008) if lim else 1.54))
        bottom = [(x, y, z - 0.014) for x, y, z in corners_top]
        v, f, _t = hexa(bottom + corners_top)
        b.add("visors", "visor", (v, f[:1] + f[2:], [0] * 5), ["Interieur"], bevel=0.005)   # no top: against the headliner


# ----------------------------------------------------------------------------------------------- decals
def _srgb(v):
    return np.array(v, np.float32) / 255.0 if isinstance(v, (tuple, list)) else np.float32(v / 255.0)


class Canvas:
    """sRGB image in metres: u along x0..x1, v along z0..z1, rows bottom-up (Blender's pixel order)."""

    def __init__(self, w, h, x0, x1, z0, z1, base):
        self.w, self.h = w, h
        self.X = (np.arange(w, dtype=np.float32) + 0.5) / w * (x1 - x0) + x0
        self.Z = (np.arange(h, dtype=np.float32) + 0.5) / h * (z1 - z0) + z0
        self.XX, self.ZZ = np.meshgrid(self.X, self.Z)
        self.img = np.empty((h, w, 3), np.float32)
        self.img[:] = _srgb(base)

    def fill(self, mask, colour):
        self.img[mask] = _srgb(colour) if not isinstance(colour, np.ndarray) else colour

    def rect(self, x0, x1, z0, z1, r=0.0):
        cx = np.clip(self.XX, x0 + r, x1 - r)
        cz = np.clip(self.ZZ, z0 + r, z1 - r)
        inside = (self.XX >= x0) & (self.XX <= x1) & (self.ZZ >= z0) & (self.ZZ <= z1)
        if r > 0:
            inside &= (self.XX - cx) ** 2 + (self.ZZ - cz) ** 2 <= r * r
        return inside

    def disc(self, cx, cz, r):
        return (self.XX - cx) ** 2 + (self.ZZ - cz) ** 2 <= r * r

    def ring(self, cx, cz, r0, r1):
        d2 = (self.XX - cx) ** 2 + (self.ZZ - cz) ** 2
        return (d2 >= r0 * r0) & (d2 <= r1 * r1)

    def arc(self, cx, cz, r0, r1, a0, a1):
        """Ring sector between angles a0..a1 (degrees, counter-clockwise from +x)."""
        ang = np.degrees(np.arctan2(self.ZZ - cz, self.XX - cx)) % 360.0
        a0, a1 = a0 % 360.0, a1 % 360.0
        sector = (ang >= a0) & (ang <= a1) if a0 <= a1 else (ang >= a0) | (ang <= a1)
        return self.ring(cx, cz, r0, r1) & sector

    def seg(self, p, q, w):
        px, pz = p
        qx, qz = q
        dx, dz = qx - px, qz - pz
        L2 = max(dx * dx + dz * dz, 1e-12)
        t = np.clip(((self.XX - px) * dx + (self.ZZ - pz) * dz) / L2, 0.0, 1.0)
        return (self.XX - (px + t * dx)) ** 2 + (self.ZZ - (pz + t * dz)) ** 2 <= (w / 2) ** 2

    def text(self, s, cx, cz, height, w, colour):
        """Stroke glyphs (seven-segment style: legible at the game's few pixels, no font needed)."""
        gw = height * 0.55
        adv = gw * 1.45
        x = cx - (len(s) * adv - (adv - gw)) / 2
        for ch in s:
            for line in GLYPHS.get(ch, []):
                for (a, c), (d, e) in zip(line, line[1:]):
                    self.fill(self.seg((x + a * gw, cz - height / 2 + c * height), (x + d * gw, cz - height / 2 + e * height), w), colour)
            x += adv

    def noise(self, amount, seed=7):
        rng = np.random.default_rng(seed)
        self.img *= (1.0 + amount * rng.standard_normal((self.h, self.w, 1))).astype(np.float32)

    def save(self, path):
        name = os.path.splitext(os.path.basename(path))[0]
        old = bpy.data.images.get(name)
        if old:
            bpy.data.images.remove(old)
        im = bpy.data.images.new(name, self.w, self.h, alpha=False, float_buffer=False)
        rgba = np.concatenate([np.clip(self.img, 0.0, 1.0), np.ones((self.h, self.w, 1), np.float32)], axis=2)
        im.pixels.foreach_set(rgba.ravel())               # 8-bit image: pixels are the stored sRGB bytes / 255
        im.filepath_raw = path
        im.file_format = 'PNG'
        im.save()
        bpy.data.images.remove(im)
        return path


GLYPHS = {
    "0": [[(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)]],
    "1": [[(0.5, 0), (0.5, 1), (0.25, 0.8)]],
    "2": [[(0, 1), (1, 1), (1, 0.5), (0, 0.5), (0, 0), (1, 0)]],
    "3": [[(0, 1), (1, 1), (1, 0), (0, 0)], [(0.25, 0.5), (1, 0.5)]],
    "4": [[(0, 1), (0, 0.5), (1, 0.5)], [(1, 1), (1, 0)]],
    "5": [[(1, 1), (0, 1), (0, 0.5), (1, 0.5), (1, 0), (0, 0)]],
    "6": [[(1, 1), (0, 1), (0, 0), (1, 0), (1, 0.5), (0, 0.5)]],
    "7": [[(0, 1), (1, 1), (0.4, 0)]],
    "8": [[(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)], [(0, 0.5), (1, 0.5)]],
    "9": [[(1, 0.5), (0, 0.5), (0, 1), (1, 1), (1, 0), (0, 0)]],
    "C": [[(1, 1), (0, 1), (0, 0), (1, 0)]],
    "H": [[(0, 0), (0, 1)], [(1, 0), (1, 1)], [(0, 0.5), (1, 0.5)]],
    "E": [[(1, 1), (0, 1), (0, 0), (1, 0)], [(0, 0.5), (0.8, 0.5)]],
    "F": [[(1, 1), (0, 1), (0, 0)], [(0, 0.5), (0.8, 0.5)]],
}
WHITE, ORANGE = (235, 235, 235), (220, 70, 20)


def _dial(cv, cx, cz, r, ticks, labels, needle_frac, red_from=None, sweep=(225.0, -45.0)):
    """Black face, white tick ring, orange arc inside it, white needle (angles clockwise from a0)."""
    a0, a1 = sweep
    cv.fill(cv.disc(cx, cz, r), (14, 14, 15))
    span = a0 - a1
    cv.fill(cv.arc(cx, cz, r * 0.70, r * 0.78, a1, a0), ORANGE)          # orange arc (both photos)
    for k in range(ticks + 1):
        a = math.radians(a0 - span * k / ticks)
        major = labels and k % (ticks // (len(labels) - 1)) == 0
        r0 = r * (0.80 if major else 0.86)
        col = (225, 50, 40) if red_from is not None and k >= red_from else WHITE
        cv.fill(cv.seg((cx + r0 * math.cos(a), cz + r0 * math.sin(a)), (cx + r * 0.95 * math.cos(a), cz + r * 0.95 * math.sin(a)),
                       0.0030 if major else 0.0018), col)
    if labels:
        for i, s in enumerate(labels):
            a = math.radians(a0 - span * i / (len(labels) - 1))
            cv.text(s, cx + r * 0.52 * math.cos(a), cz + r * 0.52 * math.sin(a), r * 0.24, 0.0024, WHITE)
    a = math.radians(a0 - span * needle_frac)
    cv.fill(cv.seg((cx, cz), (cx + r * 0.82 * math.cos(a), cz + r * 0.82 * math.sin(a)), 0.0022), (245, 245, 245))
    cv.fill(cv.disc(cx, cz, r * 0.10), (40, 40, 42))


def paint_cluster(path):
    """Three-pod cluster, 35 x 13 cm (CLUSTER), 544 x 208: tach 10 cm at u 0.16, speedo 11.5 cm at
    u 0.50, the right pod 7.5 cm at u 0.84 split temperature (C..H) | fuel (E..F). Numerals only at
    0 / 4 / 8 and 0 / 60 / 120: at the game's zoom the cluster is ~51 px wide, rings are the test."""
    x0, x1, z0, z1 = CLUSTER
    cv = Canvas(544, 208, x0, x1, z0, z1, 22)
    cv.fill(~cv.rect(x0 + 0.003, x1 - 0.003, z0 + 0.003, z1 - 0.003, 0.02), (48, 48, 50))   # bezel
    zc = (z0 + z1) / 2
    W = x1 - x0
    _dial(cv, x0 + 0.16 * W, zc, 0.050, 8, ["0", "4", "8"], 0.10, red_from=7)
    _dial(cv, x0 + 0.50 * W, zc, 0.0575, 12, ["0", "60", "120"], 0.0)
    cx, r = x0 + 0.84 * W, 0.0375
    cv.fill(cv.disc(cx, zc, r), (14, 14, 15))
    for side, (lo, hi), frac in ((-1, ("C", "H"), 0.45), (1, ("E", "F"), 0.70)):   # two half-dials side by side
        px = cx + side * r * 0.42
        a_lo, a_hi = (250.0, 110.0) if side < 0 else (290.0, 430.0)        # left half round 180, right half round 0
        cv.fill(cv.arc(px, zc, r * 0.40, r * 0.47, min(a_lo, a_hi), max(a_lo, a_hi)), ORANGE)
        for k in range(5):
            a = math.radians(a_lo + (a_hi - a_lo) * k / 4)
            cv.fill(cv.seg((px + r * 0.48 * math.cos(a), zc + r * 0.48 * math.sin(a)),
                           (px + r * 0.58 * math.cos(a), zc + r * 0.58 * math.sin(a)), 0.0018), WHITE)
        cv.text(lo, px + r * 0.10 * side, zc - r * 0.62, r * 0.26, 0.0022, WHITE)
        cv.text(hi, px + r * 0.10 * side, zc + r * 0.62, r * 0.26, 0.0022, WHITE)
        a = math.radians(a_lo + (a_hi - a_lo) * frac)
        cv.fill(cv.seg((px, zc), (px + r * 0.44 * math.cos(a), zc + r * 0.44 * math.sin(a)), 0.0020), (245, 245, 245))
    cv.fill(cv.ring(cx, zc, r * 0.97, r * 1.02), WHITE)
    return cv.save(path)


def paint_dash(path):
    """Dash face decal, 2048 x 1024 over x -0.72..0.72, z 0.48..1.21 (14 px/cm). On a 1024 interior
    sheet the scratch bake measured 1.2 texels/cm at weight 1; the dash face is weighted 2.0 (2.4
    texels/cm) and the centre stack 3.0 (bake_atlas TEXEL_WEIGHT_MAT, _face_weights), so every feature
    outside the stack is >= 1 cm (>= 2 sheet texels) and nothing is a 1 px groove."""
    cv = Canvas(2048, 1024, -0.72, 0.72, 0.48, 1.21, 64)
    cv.noise(0.025)
    cv.fill(cv.ZZ >= 1.10, (52, 52, 53))                   # the face's top band: the dash top's colour
    cv.fill(cv.ZZ <= 0.56, (50, 50, 51))                   # shadow band at the floor
    # centre stack panel and its contents (3x texels)
    cv.fill(cv.rect(-0.13, 0.13, 0.56, 1.16, 0.01), (58, 58, 59))
    for x0, x1 in ((-0.125, -0.025), (0.025, 0.125)):      # twin centre vents with three slats
        cv.fill(cv.rect(x0, x1, 1.100, 1.155, 0.004), (72, 72, 74))
        cv.fill(cv.rect(x0 + 0.006, x1 - 0.006, 1.106, 1.149), (18, 18, 19))
        for k in range(3):
            cv.fill(cv.rect(x0 + 0.006, x1 - 0.006, 1.111 + 0.0135 * k, 1.115 + 0.0135 * k), (50, 50, 52))
    cv.fill(cv.rect(-0.016, 0.016, 1.112, 1.143, 0.003), (34, 34, 36))      # clock between the vents
    cv.fill(cv.rect(-0.011, 0.011, 1.119, 1.136), (40, 52, 44))
    cv.fill(cv.rect(-0.092, 0.092, 0.972, 1.068, 0.004), (72, 72, 74))      # radio: bezel, face, display, slot, buttons
    cv.fill(cv.rect(-0.086, 0.086, 0.978, 1.062), (30, 30, 31))
    cv.fill(cv.rect(-0.050, 0.030, 1.030, 1.050, 0.002), (44, 58, 52))
    cv.fill(cv.rect(-0.070, 0.070, 1.004, 1.010), (14, 14, 15))
    for k in range(6):
        x = -0.070 + 0.028 * k
        cv.fill(cv.rect(x - 0.009, x + 0.009, 0.983, 0.993, 0.002), (78, 78, 80))
    cv.fill(cv.disc(0.068, 1.040, 0.010), (70, 70, 72))
    cv.fill(cv.rect(-0.120, 0.120, 0.858, 0.955, 0.006), (40, 40, 41))      # HVAC panel
    for x in (-0.075, 0.0, 0.075):                         # three rotary knobs: ring, centre, pointer
        cv.fill(cv.disc(x, 0.915, 0.022), (95, 95, 97))
        cv.fill(cv.disc(x, 0.915, 0.017), (45, 45, 47))
        cv.fill(cv.seg((x, 0.915), (x, 0.931), 0.004), (150, 150, 152))
    for x in (-0.090, -0.030, 0.030, 0.090):
        cv.fill(cv.rect(x - 0.0075, x + 0.0075, 0.866, 0.877, 0.002), (75, 75, 77))
    cv.fill(cv.rect(-0.110, 0.110, 0.758, 0.822, 0.006), (70, 70, 72))      # tray: lip, opening
    cv.fill(cv.rect(-0.104, 0.104, 0.764, 0.812, 0.004), (26, 26, 27))
    # passenger side: glovebox outline (1 cm), latch with its handle
    gb = cv.rect(0.23, 0.65, 0.885, 1.065, 0.02)
    cv.fill(gb & ~cv.rect(0.24, 0.64, 0.895, 1.055, 0.015), (40, 40, 41))
    cv.fill(cv.rect(0.405, 0.475, 1.025, 1.055, 0.004), (30, 30, 31))
    cv.fill(cv.rect(0.415, 0.465, 1.031, 1.043, 0.003), (82, 82, 84))
    for sx in (-1, 1):                                     # side vents at the dash ends: frame, two slats
        x0, x1 = sorted((sx * 0.600, sx * 0.700))
        cv.fill(cv.rect(x0, x1, 1.060, 1.130, 0.005), (70, 70, 72))
        cv.fill(cv.rect(x0 + 0.007, x1 - 0.007, 1.067, 1.123), (18, 18, 19))
        for k in range(2):
            cv.fill(cv.rect(x0 + 0.007, x1 - 0.007, 1.078 + 0.020 * k, 1.088 + 0.020 * k), (52, 52, 54))
    # driver side: switch bank left of the binnacle (2 x 2), coin box under it
    cv.fill(cv.rect(-0.705, -0.625, 0.945, 1.030, 0.005), (44, 44, 45))
    for x, z in ((-0.685, 0.965), (-0.645, 0.965), (-0.685, 1.010), (-0.645, 1.010)):
        cv.fill(cv.rect(x - 0.012, x + 0.012, z - 0.012, z + 0.012, 0.003), (80, 80, 82))
    cv.fill(cv.rect(-0.560, -0.460, 0.900, 0.950, 0.004), (40, 40, 41))
    cv.fill(cv.rect(-0.550, -0.470, 0.910, 0.940, 0.003), (30, 30, 31))
    return cv.save(path)


# ----------------------------------------------------------------------------------------------- build
def _audit(objs, env):
    bad = []
    for o in objs:
        worst, n = 0.0, 0
        M = o.matrix_world
        for v in o.data.vertices:
            d = env.outside(M @ v.co)
            if d > 0.003:
                n += 1
                worst = max(worst, d)
        if n:
            bad.append((worst, n, o.name))
    for worst, n, name in sorted(bad, reverse=True):
        print("CABIN CLEARANCE %-14s %3d vertices outside the car (max %.0f mm)" % (name, n, worst * 1000))
    if not bad:
        print("CABIN CLEARANCE ok: every vertex inside the body, under the glass, inside the doors")


def _passengers(env):
    """Per hip: the insert top under it, the front roll ahead of it and the headroom over the top of
    the head (the head's highest point is 4.5 cm ahead of the hip; the full-detail headliner, ~1 mm
    off the shipped one)."""
    for name, h in hips().items():
        roof = env.headliner(h.x, h.y + 0.045)
        room = "%.0f mm" % ((roof - h.z - HEAD_RISE) * 1000) if roof is not None else "?"
        print("CABIN PASSENGER %-10s hip (%.2f, %.2f, %.3f): insert top %.0f mm under it (SIT_DROP %.0f), roll %.0f mm ahead, "
              "headroom %s, well floor %.3f" % (name, h.x, h.y, h.z, -_lerp_table(SEAT_TOP, 0.0) * 1000, SIT_DROP * 1000,
                                                SEAT_NOSE * 1000, room, h.z - SOLE_DROP))


def carve_footwells(report=print, ob=None):
    """Footwells in the DECIMATED interior (prep_parts runs this after _interior_closures, whose slab
    under the carpet leaves footwell_holes() open). Per well: the carpet (kotris floor, gen 0) is
    bisected along the opening and the inside deleted; walls run from the cut edge's own vertices
    straight down to the well floor, so they meet the low carpet exactly; a closed floor block
    (WELL_SLAB thick) has its top at the soles. Generated faces (gen 3), baked direct like the cargo
    well. Reports how much of the outline the carpet's cut edge covers and the gap to the underbody."""
    it = ob or bpy.data.objects.get("interior")
    if it is None:
        report("  footwells: no interior object")
        return 0
    me = it.data
    names = [m.name if m else "?" for m in me.materials]
    if "Interieur_sol" not in names:
        report("  footwells: no carpet material on the interior")
        return 0
    mi = names.index("Interieur_sol")
    body = bpy.data.objects.get("body")
    under = _world_bvh(body) if body is not None else None
    bm = bmesh.new()
    bm.from_mesh(me)
    gl = bm.faces.layers.int.get("gen") or bm.faces.layers.int.new("gen")
    eps = 1e-4
    done = 0
    for name, x0, x1, y0, y1, zw in footwells():
        c = Vector(((x0 + x1) / 2, (y0 + y1) / 2, zw))

        def carpet():
            out = []
            for f in bm.faces:
                if not f.is_valid or f[gl] != 0 or f.normal.z < 0.5:
                    continue
                vs = [v.co for v in f.verts]
                if (all(0.43 < v.z < 0.62 for v in vs) and min(v.x for v in vs) < x1 and max(v.x for v in vs) > x0
                        and min(v.y for v in vs) < y1 and max(v.y for v in vs) > y0):
                    out.append(f)
            return out
        if any(f.is_valid and f[gl] == 3 and abs(f.calc_center_median().z - zw) < eps and abs(f.calc_center_median().x - c.x) < 0.01
               and abs(f.calc_center_median().y - c.y) < 0.01 for f in bm.faces):
            report("  footwell %-10s already cut (rerun on a prepared parts file)" % name)
            continue
        for co, no in (((x0, 0, 0), (1, 0, 0)), ((x1, 0, 0), (1, 0, 0)), ((0, y0, 0), (0, 1, 0)), ((0, y1, 0), (0, 1, 0))):
            geom = carpet()
            edges = {e for f in geom for e in f.edges}
            verts = {v for f in geom for v in f.verts}
            bmesh.ops.bisect_plane(bm, geom=list(verts) + list(edges) + geom, plane_co=co, plane_no=no, dist=1e-5)
        inside = [f for f in carpet() if all(x0 - eps <= v.co.x <= x1 + eps and y0 - eps <= v.co.y <= y1 + eps for v in f.verts)]
        bmesh.ops.delete(bm, geom=inside, context='FACES')

        def side(v):
            p = v.co
            iny, inx = y0 - eps <= p.y <= y1 + eps, x0 - eps <= p.x <= x1 + eps
            return {k for k, hit in (("x0", abs(p.x - x0) < eps and iny), ("x1", abs(p.x - x1) < eps and iny),
                                     ("y0", abs(p.y - y0) < eps and inx), ("y1", abs(p.y - y1) < eps and inx)) if hit}
        rim = [e for e in bm.edges if e.is_valid and len(e.link_faces) == 1 and e.link_faces[0][gl] == 0
               and side(e.verts[0]) & side(e.verts[1])]
        covered = sum((e.verts[0].co.xy - e.verts[1].co.xy).length for e in rim)
        ring = {}

        def foot(x, y):
            k = (round(x, 5), round(y, 5))
            if k not in ring:
                ring[k] = bm.verts.new((x, y, zw))
            return ring[k]
        corners = [foot(x, y) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
        new = []
        for e in rim:
            a, b2 = e.verts
            new.append(bm.faces.new((a, b2, foot(b2.co.x, b2.co.y), foot(a.co.x, a.co.y))))
        walls = len(new)
        # the well floor carries every wall foot (no T-junction where it shows); the block's bottom and
        # sides, never seen (slab round them, underbody under them), only the corners
        top = sorted(ring.values(), key=lambda v: math.atan2(v.co.y - c.y, v.co.x - c.x))
        zb = zw - WELL_SLAB
        low = [bm.verts.new((v.co.x, v.co.y, zb)) for v in corners]
        new.append(bm.faces.new(top))
        new.append(bm.faces.new(list(reversed(low))))
        for i in range(4):
            j = (i + 1) % 4
            new.append(bm.faces.new((corners[i], low[i], low[j], corners[j])))
        mid = Vector((c.x, c.y, zw + 0.05))
        for k, f in enumerate(new):
            f.normal_update()
            if k < walls:                                   # walls face into the well
                ok = f.normal.dot(mid - f.calc_center_median()) > 0
            elif k == walls:                                # well floor up, block bottom down, block sides out
                ok = f.normal.z > 0
            elif k == walls + 1:
                ok = f.normal.z < 0
            else:
                ok = f.normal.dot(Vector((c.x, c.y, zb + WELL_SLAB / 2)) - f.calc_center_median()) < 0
            if not ok:
                f.normal_flip()
            f.material_index = mi
            f.smooth = False
            f[gl] = 3
        gap = None
        if under is not None:
            for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1), (c.x, c.y)):
                loc = under.ray_cast(Vector((x, y, zb)), Vector((0, 0, -1)), 1.0)[0]
                g = (zb - loc.z) if loc is not None else -1.0
                gap = g if gap is None else min(gap, g)
        perim = 2 * ((x1 - x0) + (y1 - y0))
        report("  footwell %-10s x %.3f..%.3f y %.3f..%.3f floor %.3f: %d carpet faces cut, %d walls, cut edge %.0f%% of the "
               "outline, underbody %s below" % (name, x0, x1, y0, y1, zw, len(inside), walls, 100 * covered / perim,
                                                 "%.0f mm" % (gap * 1000) if gap is not None and gap >= 0 else "NOT FOUND"))
        if covered < 0.98 * perim:
            report("  footwell %-10s WARNING: the carpet does not reach the whole outline: open wall" % name)
        if gap is not None and gap < 0.003:
            report("  footwell %-10s WARNING: the well block reaches the underbody" % name)
        done += 1
    bm.to_mesh(me)
    bm.free()
    me.update()
    return done


def build(low=LOW):
    old = bpy.data.objects.get(NAME)
    if old is not None:
        bpy.data.objects.remove(old, do_unlink=True)
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    ref = bpy.data.objects.get("body") or bpy.data.objects.get("interior")
    col = ref.users_collection[0] if ref else bpy.context.scene.collection
    env = Env()
    b = Cab(col, not low, env)
    dash(b)
    binnacle(b)
    wheel(b)
    column(b)
    for name, hip in hips().items():
        if not name.startswith("Rear"):
            front_seat(b, hip)
    rear_bench(b)
    tray(b)
    handbrake(b)
    pedals(b)
    mirror(b)
    visors(b)
    _audit(b.objs, env)
    _passengers(env)
    pieces = dict(b.pieces)
    ob = b.join(NAME)
    level = "coarse" if low else "full"
    for piece, t in pieces.items():
        print("CABIN %s %-15s %6d tris" % (level, piece, t))
    total = sum(len(p.vertices) - 2 for p in ob.data.polygons)
    print("CABIN %s total %d tris, %d materials" % (level, total, len(ob.data.materials)))
    if low and total > BUDGET:
        print("CABIN warning: coarse build %d tris is over the %d budget (prep decimates it)" % (total, BUDGET))
    if not low:
        os.makedirs(BAKE, exist_ok=True)
        print("CABIN decal", paint_dash(os.path.join(BAKE, "cabin_dash.png")))
        print("CABIN decal", paint_cluster(os.path.join(BAKE, "cabin_cluster.png")))
    return ob, pieces


def main():
    if "--both" in _argv():                                # what run_rebuild does: full twin, then the coarse part
        full, fp = build(low=False)
        full.name = NAME + "_full"
        coarse, cp = build(low=True)
        for piece in cp:
            print("CABIN %-15s coarse %5d / full %6d tris" % (piece, cp[piece], fp.get(piece, 0)))
        print("CABIN coarse %d tris / full %d tris" % (sum(cp.values()), sum(fp.values())))
    else:
        build()
    save = _opt("--save")
    if save:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(save))
        print("CABIN saved", save)


if __name__ in ("__main__", "run"):
    main()
