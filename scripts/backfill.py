r"""
Close every hole the game's back-face culling would open, in every pose the player sees (v6).

    import backfill; backfill.fill(arm)          # run_export, after rig_vehicle.build()

Project Zomboid always culls back faces on vehicles. Most of the car is single-sided (kotris's
panels, our low parts), so anywhere the camera can see a surface from BEHIND, the game draws
nothing there and the ground shows through: an open door's window, the bottom of an open door,
an inner panel seen through a gap. This poses the rig shut and with every panel open, casts
parallel rays from the game camera (pitch ~30 degrees, every 20 degrees of heading) over a 2 cm
grid, and records each face whose BACK is the first thing a ray meets. Those faces get a back
face: a flipped copy on the same UVs (inner side shows the same texture), flat shaded; the backs
of a door's trim card and edge band, which only a crack can show, take the dark block instead
(DARK_BACK_MATS).
Camera mods add the seats and eye level: rays from every seat's seated eye (seated_eye(), shared with
pzview) in every pose that opens a panel, a ring of low perspective eyes round the car, and low parallel
rays. A ray passes the backs of the SeamBack plates behind the glass (never drawn from the cabin).
Panels part-way through their swing (PARTIAL_FRACS of the travel) get the game camera's scan too.
The ray grid follows the shut car's size alone; meshes that are not on the car as
it stands (feature wheels, anything parked away from the body) are scanned one by one on that grid
(see LOOSE_MARGIN). The first BACKFILL line prints the scan box and scale: 2.02 x 4.48 x 1.86 m, 1.051.
pzview's leak count is the acceptance check afterwards.
"""
import math

import bmesh
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

# rig_vehicle is imported inside fill(): pzview imports this module for seated_eye() alone

ELEVATIONS = (26.0, 30.0, 34.0)   # the game's camera pitch is fixed at ~30 degrees
AZ_STEP = 10
# 2026-10-17 (OPEN-6): the car turns to ANY heading under the fixed camera, and a slit can show for only a
# few degrees of it: the right front opening's lower front frame (body faces at (0.872, 0.919, 0.47)) shows
# its back through the open left front door and the cabin at heading 215 and nowhere at 210 or 220. The
# game's own pitch (30) is scanned every AZ_FINE degrees; the margin pitches keep AZ_STEP, staggered.
AZ_FINE = 5
GRID = 0.009                  # metres between rays (1.2 cm stepped over 1 cm strips at door edges)
SKIP = ("base",)
# First / third person camera mods (Project Viewpoint) also show the car from eye level outside
# and from the seats inside. Low parallel rays (third person at 1.65 m from 4-6 m, a crouch) on a
# coarser grid, and rays from the eye points in every direction (metres above ground, the car
# faces +y, the driver sits at x < 0; cargo eyes for the fold-flat bed).
EYE_VIEWS = True
LOW_ELEVATIONS = (1.5, 4.0, 10.0, 17.0)   # 1.5: under the car to the far sill (WHL-10)
LOW_GRID = 0.02
# Seated eyes (2026-10-17, CAB-14). The game seats a passenger with the hip (Bip01) at the script's
# `inside` offset (gen_scripts.PASSENGERS: mesh metres over the FBX origin, export_fbx.ORIGIN_Z above the
# ground). MaleBody skinned with the vanilla seated pose (Bob_IdleDriving; scratch footwells/posed.json)
# has the top of the head 0.780 over the hip (build_cabin.HEAD_RISE), the nose tip 0.59 over it and
# 0.146 ahead, the face at eye height ~0.13 ahead: the eye sits EYE_RISE over the hip, EYE_AHEAD in front
# of it. Before: fixed points at z 1.13 (x the car scale 1.05: 1.19 m), 0.27 m under the real eye, so
# the backs a seated player sees along the A-pillars and the kick panels were never found; pzview put its
# eye at 1.54 m (the headliner). Both read seated_eye() now.
EYE_RISE = 0.67
EYE_AHEAD = 0.10
ORIGIN_Z = 0.80               # export_fbx.ORIGIN_Z (the FBX origin above the ground), when it cannot be imported
# Each seat scans from its eye and a head turned / leaning: (dx outboard-signed, dy, dz) metres
EYE_SPREAD = ((0.0, 0.0, 0.0), (0.07, 0.0, 0.0), (-0.07, 0.0, 0.0), (0.0, 0.0, -0.06), (0.0, 0.08, -0.02))
# Cargo eyes: kneeling / sitting on the fold-flat bed (the headliner is ~1.6 m there)
CARGO_EYES = ((0.0, -1.55, 1.05), (0.0, -1.45, 1.35), (-0.35, -1.75, 1.30), (0.35, -1.75, 1.30))
# The eyes before 2026-10-17 as they were cast (x the car scale 1.051), kept so nothing they found loses
# its back: a slouched or short occupant's eye, and the slivers they caught on the way out of the car
LEGACY_EYES = ((-0.40, 0.053, 1.188), (0.40, 0.053, 1.188), (-0.378, -0.82, 1.188), (0.378, -0.82, 1.188),
               (0.0, -1.63, 1.104))
EYE_STEP = 0.5                # degrees between rays: 1.3 cm at 1.5 m (1.0 left 2-3 cm slits along the pillars)
# A ring of eyes round the car at crouch and knee height (third person low, a player kneeling by the car;
# WHL-10: the far sill seen under the car from a 0.5 m eye), rays only over the car's box
RING_EYES = ((1.5, 0.5), (1.5, 0.95), (3.0, 0.3), (3.0, 0.6))   # (distance past the car's box, height) metres
RING_AZ = 15                  # degrees between ring eyes
RING_STEP = 0.25              # degrees between rays from a ring eye (1.3 cm at 3 m)


def seated_eye(hip):
    """The seated eye over a hip point (x, y, z), metres above ground, Blender axes (+y forward)."""
    return (hip[0], hip[1] + EYE_AHEAD, hip[2] + EYE_RISE)


def seat_hips():
    """Hip points of every seat in model metres above ground, from gen_scripts.PASSENGERS (PZ +x is
    the car's LEFT, Blender +x its right; inside y is mesh metres over the FBX origin)."""
    try:
        import export_fbx
        oz = export_fbx.ORIGIN_Z
    except Exception:                            # noqa: BLE001
        oz = ORIGIN_Z
    try:
        import gen_scripts
        out = []
        for _name, inside, _outside in gen_scripts.PASSENGERS:
            px, py, pz = (float(v) for v in inside.split())
            out.append((-px, pz, oz + py))
        return out
    except Exception as exc:                     # noqa: BLE001
        print("BACKFILL warning: gen_scripts.PASSENGERS not readable (%s): stock seat hips" % exc)
        return [(-0.38, -0.02, 0.79), (0.38, -0.02, 0.79), (-0.36, -0.80, 0.79), (0.36, -0.80, 0.79)]


def eye_points():
    """Every eye the seat scan casts from (metres above ground): each seat's seated eye and its spread
    (lateral offsets signed outboard), then the cargo eyes."""
    pts = []
    for hx, hy, hz in seat_hips():
        ex, ey, ez = seated_eye((hx, hy, hz))
        side = 1.0 if hx >= 0 else -1.0
        for dx, dy, dz in EYE_SPREAD:
            pts.append((ex + side * dx, ey + dy, ez + dz))
    return pts + list(CARGO_EYES) + list(LEGACY_EYES)
# Backs that only ever show through a crack (2026-10-13). A door's trim card (DoorCard_*) and its
# painted edge band (BodyInner) face the cabin and close the door's inside into a box with the skin;
# the camera sees their BACK only through a slit in the skin: the 1-7 mm cracks along kotris's door
# mouldings, the open ends of the mouldings at the door gaps, the crease at the door bottoms. Their
# copies took the card's light grey (~133 sRGB) and drew "all the little white lines on the door"
# (screenshot 24.png, 27.webp; round-1 probes: door_rl face 687, the back of card face 349, at
# (-0.821, -0.296, 0.707)). A crack shows the dark inside of a door: those copies sample the door's
# dark block (the planar unwrap's 16 x 16 cell of hidden faces, face attribute uv_island = -2, which
# compose fills with the dark-block colour) instead of the card.
DARK_BACK_OBJECTS = ("door_fl", "door_fr", "door_rl", "door_rr")
DARK_BACK_MATS = ("DoorCard_", "BodyInner")      # material name prefixes
# The scan's ray spacing and eye points scale with the CAR's size (metres here, 10 units/m in an FBX
# scene), measured once on the shut car. Anything else in the pool stretched it: the lift feature's
# wheels, parked at x 4 m and 6 m (features/lift.py ALLOY_HUB, STEEL_HUB: the wheel FBX is centred on
# its own hub), took the box to 7.3 m, the scale from 1.05 to 1.73, the grid from 9.5 to 15.5 mm and
# the driver's eye to 1.95 m, above the roof: the 2026-10-13 integration build lost 450 backs and the
# bare car's leak count went 1041 -> 1697 px. Feature wheels and any mesh lying wholly outside the
# body's box (LOOSE_MARGIN) are LOOSE: scanned one by one on the car's grid, never part of its box.
LOOSE_MARGIN = 0.5            # metres around the body's box
# Faces that always get a back, {object or "*" for every car mesh: [((x0,x1),(y0,y1),(z0,z1)), ...]} in metres, face centres. Each front
# fender's inner top edge beside the headlamp: with the hood open, its back shows across the bay from the far
# side (pzview close_door_open_left: ~250 leak px through body faces at (0.48..0.59, 1.83..1.90, 0.89) m) yet
# the open-pose scan skips them: they are SeamBack backing plates behind the headlamp, which backfill never backs (2026-10-17). Mirrored for the left fender.
# 2026-10-17 (feedback: "weird geometry black line around the headlights"): the kotris headlamp housings are open
# shells; round their rim the game camera looks at the housing's inside, culls it, and sees through to the dark
# bay_walls corner blocks (0.70, 1.87, 0.73), the header strips' Dessous ends (0.43, 1.94, 0.86) and the bay
# (pzview probe, view (0.62, 1.85, 0.80) az 45). The second pair of boxes backs every face round each lamp.
# (EXT-17, 2026-10-17: the "three culled faces" a probe reports at each lamp's inner top corner, (0.42-0.43,
# 1.93-1.94, 0.86-0.87), are these boxes' backfill copies, coincident with the faces they back; the pixel draws
# the header's Dessous end, dark by design since 2026-10-14. Nothing there is see-through.)
FORCE_BACKS = {"*": [((0.42, 0.66), (1.76, 1.96), (0.82, 0.97)), ((-0.66, -0.42), (1.76, 1.96), (0.82, 0.97)),
                     ((0.40, 0.82), (1.66, 1.99), (0.70, 0.97)), ((-0.82, -0.40), (1.66, 1.99), (0.70, 0.97))]}
# Part-way poses (2026-10-17, R2-OC-8): the game draws every frame of a door's swing, and at ~15 % of it the
# doors' outer edge faces (door_fl faces at x -0.90..-0.93, z 0.66..0.74, door_fr, door_rl) show their backs to
# the game camera: 1-2 px ground lines along each door edge (121 px in one view) that neither the shut nor the
# open pose shows. Every opening panel is also posed at each of these fractions of its travel and scanned
# from the game camera (its own pitch, every AZ_FINE degrees, both grid offsets).
PARTIAL_FRACS = (0.07, 0.15, 0.3, 0.5)
CAR_SCALES = ((0.8, 1.3), (8.0, 13.0))   # what a 4.5 m car gives in metres / FBX units
OFFSETS = (0.0, 0.5)            # game-camera grid passes, as a fraction of a step (0.5: a second, staggered pass)


def _feature_wheels():
    """Feature wheel meshes (scripts/features OBJECTS with file 'wheel', named wheel_<feature>_*)."""
    try:
        import features
        return set(features.wheel_objects())
    except Exception as exc:                     # noqa: BLE001  (no plugin package: no feature wheels)
        print("BACKFILL warning: feature plugins not loaded (%s): feature wheels not known by name" % exc)
        return set()


def _box(obs):
    pts = [o.matrix_world @ Vector(c) for o in obs for c in o.bound_box]
    return (Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts))),
            Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts))))


def _meshes():
    """(car, loose). The car: everything it always carries. Accessories (acc_*) are closed solids that
    come off in game: they get no backs and must not hide the car's own holes from the scan. Loose:
    feature wheels and meshes parked away from the body (see LOOSE_MARGIN), scanned on their own."""
    wheels = _feature_wheels()
    pool = [o for o in bpy.data.objects if o.type == 'MESH' and not o.hide_render
            and not o.name.endswith("_hi") and o.name not in SKIP and not o.name.startswith("acc_")]
    car = [o for o in pool if o.name not in wheels]
    loose = [o for o in pool if o.name in wheels]
    body = bpy.data.objects.get("body")
    if body is not None and body in car:
        blo, bhi = _box([body])
        m = Vector((LOOSE_MARGIN,) * 3)
        blo, bhi = blo - m, bhi + m
        for o in list(car):
            lo, hi = _box([o])
            if any(hi[i] < blo[i] or lo[i] > bhi[i] for i in range(3)):
                print("BACKFILL warning: %s lies outside the body's box (%.2f..%.2f, %.2f..%.2f, %.2f..%.2f): scanned on its own"
                      % (o.name, lo.x, hi.x, lo.y, hi.y, lo.z, hi.z))
                car.remove(o)
                loose.append(o)
    return car, loose


def _tree(objs):
    dg = bpy.context.evaluated_depsgraph_get()
    verts, polys, owner = [], [], []
    glass = set()
    for o in objs:
        ev = o.evaluated_get(dg)
        me = ev.to_mesh()
        M = ev.matrix_world.copy()
        names = [m.name if m else "?" for m in o.data.materials]
        base = len(verts)
        verts.extend(M @ v.co for v in me.vertices)
        for p in me.polygons:
            if _INVISIBLE_BACKS and p.material_index < len(names) and names[p.material_index] in GLASS_MATS:
                glass.add(len(polys))
            polys.append([base + i for i in p.vertices])
            owner.append((o.name, p.index))
        ev.to_mesh_clear()
    tree = BVHTree.FromPolygons(verts, polys, all_triangles=False)
    if _INVISIBLE_BACKS:
        _PASS[id(tree)] = ({i for i, key in enumerate(owner) if key in _INVISIBLE_BACKS}, glass)
    return tree, owner, verts


# SeamBack (2026-10-17, CAB-2/7/8). prep_parts._island_backing puts a SeamBack plate 6 mm behind every glass
# and lamp island (drawn from outside, so a crack round it reads dark) and gutter strips behind the roof
# seams; until now every SeamBack mark was dropped, so the plates were invisible from the cabin AND the scan
# stopped on them: the A-pillar trims and lamp faces right behind them, seen from the seats, were never
# found, and the plates' rims hid real slits to the road. Now a SeamBack face seen from behind gets a back
# like any other face (dark: lamp plates, gutter strips), except a pane's plate seen THROUGH: a ray meeting
# one from behind goes on, and if the glass follows (the player looks through the window) nothing is
# marked; if it meets a face from behind, that face is; if it leaves the car (the slit between the glass
# edge and the pillar, 1-2 cm to the road from both front seats) the plate face is, and reads dark from the
# cabin like the rubber it stands for.
SEAMBACK = "SeamBack"
GLASS_MATS = ("Vitre", "Vitre_noir")
# A plate is a copy of one glass island 6 mm behind it, its rim grown 1.5 cm out and back; against the
# decimated panes its faces lie 3-24 mm behind the glass (measured 2026-10-17). A connected SeamBack island
# is a pane's plate when at least PANE_SHARE of its faces have a pane within PANE_GAP along their normal.
PANE_GAP = 0.040
PANE_SHARE = 0.25
_INVISIBLE_BACKS = set()
_PASS = {}                    # id(tree) -> (tree indices of pane plates, tree indices of glass faces)


def _pane_backings(objs):
    """{(object, face)} of the SeamBack faces of a pane's plate (see SEAMBACK), whole plates at a time."""
    dg = bpy.context.evaluated_depsgraph_get()
    gv, gp = [], []
    plates = {}                                   # object -> [(face, centre, normal, vertex ids)]
    for o in objs:
        ev = o.evaluated_get(dg)
        me = ev.to_mesh()
        M = ev.matrix_world.copy()
        R = M.to_3x3()
        names = [m.name if m else "?" for m in o.data.materials]
        base = len(gv)
        gv.extend(M @ v.co for v in me.vertices)
        for p in me.polygons:
            mn = names[p.material_index] if p.material_index < len(names) else "?"
            if mn in GLASS_MATS:
                gp.append([base + i for i in p.vertices])
            elif mn == SEAMBACK:
                plates.setdefault(o.name, []).append((p.index, M @ p.center, (R @ p.normal).normalized(), tuple(p.vertices)))
        ev.to_mesh_clear()
    if not gp:
        return set()
    glass = BVHTree.FromPolygons(gv, gp, all_triangles=False)
    out = set()
    for name, faces in plates.items():
        parent = {}

        def find(v):
            while parent.get(v, v) != v:
                parent[v] = parent.get(parent[v], parent[v])
                v = parent[v]
            return v
        for _i, _c, _n, vs in faces:
            r0 = find(vs[0])
            for v in vs[1:]:
                r = find(v)
                if r != r0:
                    parent[r] = r0
        islands = {}
        for f in faces:
            islands.setdefault(find(f[3][0]), []).append(f)
        for members in islands.values():
            hits = sum(1 for _i, c, n, _vs in members if glass.ray_cast(c - n * 0.001, n, PANE_GAP)[0] is not None)
            if hits >= PANE_SHARE * len(members):
                out.update((name, i) for i, _c, _n, _vs in members)
    return out


def _first_back(tree, origin, d, far):
    """The face index the ray shows from behind, or None. A pane plate (_PASS) met from behind is looked
    through: glass or a drawn face behind it -> None, a face seen from behind -> that face, nothing -> the
    plate itself (see SEAMBACK)."""
    sets = _PASS.get(id(tree))
    first = None
    for _ in range(12):
        loc, nrm, idx, dist = tree.ray_cast(origin, d, far)
        if loc is None:
            return first                          # out through the slit past the pane's edge: the plate shows
        back = nrm.dot(d) > 0.0
        if first is not None:                     # behind a pane plate: more plates, then what the player sees
            if idx in sets[1] or not back:
                return None                       # the window (glass is doubled after the scan) or a drawn face
            if idx not in sets[0]:
                return idx                        # another face seen from behind
        else:
            if not back:
                return None
            if not sets or idx not in sets[0]:
                return idx
            first = idx
        origin = loc + d * 1e-4
        far -= dist
    return first


def _bounds(verts):
    lo = Vector((min(v.x for v in verts), min(v.y for v in verts), min(v.z for v in verts)))
    hi = Vector((max(v.x for v in verts), max(v.y for v in verts), max(v.z for v in verts)))
    return lo, hi


def car_scale(verts):
    """~1 for the 4.5 m car in metres, ~10 in FBX units: the box diagonal / 5 of the SHUT car alone."""
    lo, hi = _bounds(verts)
    return (hi - lo).length / 5.0


def units(scale):
    """Scene units per metre: 1 for a car in metres, 10 in FBX units. The eye points are positions in
    metres and scale by this, never by car_scale() itself (1.051 for this car: before 2026-10-17 every
    eye sat 5 % too high, too far out and too far back)."""
    if scale > 5.0:
        return 10.0                    # FBX units of builds before 2026-10-18
    return 0.5 if scale < 0.75 else 1.0   # export_fbx.UNITS_PER_M 0.5 since 2026-10-18


def _cast_dirs(tree, eye, dirs, far, marks, owner):
    n = 0
    for d in dirs:
        idx = _first_back(tree, eye, d, far)
        if idx is not None:
            marks.add(owner[idx])
        n += 1
    return n


_SPHERE = {}


def _sphere(step):
    """Unit directions every `step` degrees of elevation, the azimuth step widened toward the poles
    (equal spacing on the sphere, ~step everywhere)."""
    if step not in _SPHERE:
        dirs = []
        el = -90.0 + step / 2
        while el < 90.0:
            e = math.radians(el)
            ce = math.cos(e)
            k = max(1, int(round(360.0 * ce / step)))
            for i in range(k):
                a = 2 * math.pi * i / k
                dirs.append(Vector((ce * math.cos(a), ce * math.sin(a), math.sin(e))))
            el += step
        _SPHERE[step] = dirs
    return _SPHERE[step]


def _scan_eyes(tree, owner, verts, marks, scale, eyes=None):
    """Rays from each eye point in every direction: whatever shows its back from a seat or the
    cargo floor gets a back face."""
    lo, hi = _bounds(verts)
    far = (hi - lo).length * 2
    u = units(scale)
    n = 0
    dirs = _sphere(EYE_STEP)
    for ex, ey, ez in (eye_points() if eyes is None else eyes):
        n += _cast_dirs(tree, Vector((ex, ey, ez)) * u, dirs, far, marks, owner)
    return n


def _scan_ring(tree, owner, verts, marks, scale):
    """Perspective eyes on a ring round the car (RING_EYES, every RING_AZ degrees), rays every
    RING_STEP degrees over the angles the car's box covers from each."""
    lo, hi = _bounds(verts)
    u = units(scale)
    centre = (lo + hi) / 2
    corners = [Vector((x, y, z)) for x in (lo.x, hi.x) for y in (lo.y, hi.y) for z in (lo.z, hi.z)]
    far = (hi - lo).length * 4
    n = 0
    step = math.radians(RING_STEP)
    half = (hi - lo) / 2
    for dist, h in RING_EYES:
        for k in range(0, 360, RING_AZ):
            a = math.radians(k)
            r = half.x * abs(math.cos(a)) + half.y * abs(math.sin(a)) + dist * u    # dist past the box's side
            eye = Vector((centre.x + math.cos(a) * r, centre.y + math.sin(a) * r, h * u))
            fwd = (Vector((centre.x, centre.y, eye.z)) - eye).normalized()
            right = fwd.cross(Vector((0, 0, 1))).normalized()
            hs, vs = [], []
            for c in corners:
                v = c - eye
                hs.append(math.atan2(v.dot(right), v.dot(fwd)))
                vs.append(math.atan2(v.z, math.hypot(v.dot(right), v.dot(fwd))))
            dirs = []
            el = min(vs)
            while el <= max(vs):
                ce, se = math.cos(el), math.sin(el)
                ha = min(hs)
                while ha <= max(hs):
                    dirs.append(fwd * (ce * math.cos(ha)) + right * (ce * math.sin(ha)) + Vector((0, 0, se)))
                    ha += step
                el += step
            n += _cast_dirs(tree, eye, dirs, far, marks, owner)
    return n


def _scan(tree, owner, verts, marks, scale, elevations=ELEVATIONS, grid=GRID, offset=0.0):
    """Parallel rays over the projected box of `verts`, `grid` x `scale` apart (the car's scale, never
    the box's own), the first row and column `offset` of a step in."""
    lo, hi = _bounds(verts)
    centre = (lo + hi) / 2
    radius = (hi - lo).length / 2 + 0.1
    step = grid * scale
    corners = [Vector((x, y, z)) for x in (lo.x, hi.x) for y in (lo.y, hi.y) for z in (lo.z, hi.z)]
    for el in elevations:
        e = math.radians(el)
        # every pitch keeps the AZ_STEP headings (staggering the margins instead lost slivers only they had
        # caught: +60 leak px at shut_045 in the 2026-10-17 test build); the game's own pitch adds AZ_FINE
        azimuths = range(0, 360, AZ_FINE if el == 30.0 else AZ_STEP)
        for az in azimuths:
            a = math.radians(az)
            d = -Vector((math.cos(e) * math.cos(a), math.cos(e) * math.sin(a), math.sin(e)))
            right = d.cross(Vector((0, 0, 1))).normalized()
            up = right.cross(d).normalized()
            us = [(c - centre).dot(right) for c in corners]       # only the car's projected box
            vs = [(c - centre).dot(up) for c in corners]
            far = 2 * radius + 2.0
            back = d * (radius + 1.0)
            v = min(vs) + offset * step
            while v <= max(vs):
                row = centre + up * v - back
                u = min(us) + offset * step
                while u <= max(us):
                    idx = _first_back(tree, row + right * u, d, far)
                    if idx is not None:
                        marks.add(owner[idx])
                    u += step
                v += step


def _dark_uv(me):
    """The centre of the UV triangle the planar unwrap gave this mesh's hidden (dark block) faces,
    or None: face attribute uv_island = -2, first UV layer."""
    isl = me.attributes.get("uv_island")
    if isl is None or not me.uv_layers or isl.domain != 'FACE':
        return None
    vals = [0] * len(me.polygons)
    isl.data.foreach_get("value", vals)
    uv = me.uv_layers[0].data
    for p in me.polygons:
        if vals[p.index] == -2:
            us = [uv[li].uv for li in p.loop_indices]
            return (sum(u[0] for u in us) / len(us), sum(u[1] for u in us) / len(us))
    return None


def _belt_band(ob, names):
    """(side, sill z, (y0, y1), max |x|) of a door's window slot: its BodyInner top band (the faces of the
    door's edge band facing up, under the window), or None."""
    M = ob.matrix_world
    R = M.to_3x3()
    tops = []
    for p in ob.data.polygons:
        mn = names[p.material_index] if p.material_index < len(names) else "?"
        if mn.startswith("BodyInner") and (R @ p.normal).normalized().z > 0.9:
            tops.append([M @ ob.data.vertices[i].co for i in p.vertices])
    if not tops:
        return None
    zmax = max(sum(v.z for v in t) / len(t) for t in tops)        # the top band only (the bottom edge band
    tops = [t for t in tops if sum(v.z for v in t) / len(t) > zmax - 0.08]   # faces up too, at the sill)
    pts = [v for t in tops for v in t]
    zs = sorted(v.z for v in pts)
    side = 1.0 if sum(v.x for v in pts) > 0 else -1.0
    return side, zs[len(zs) // 2], (min(v.y for v in pts), max(v.y for v in pts)), max(abs(v.x) for v in pts) + BELT_SKIN_OUT


# R2-OC-6 (2026-10-17): with a door window down, from the seats the window slot shows the BACK of the door's
# outer skin a few cm under the belt (door_fl back copies 783 / 807 / 816 of skin faces at (-0.835, 0.12..0.20,
# 1.04..1.07)): their copies shared the panel's paint texels and drew a blue line along the sill. The inside of
# a door is dark: the copies of outboard-facing skin faces (normal x outboard by more than BELT_SKIN_NX) from
# BELT_SKIN_BAND under the slot's sill (the door's BodyInner top band) to BELT_SKIN_UP over it, within the
# slot's length and BELT_SKIN_OUT outboard of the band (the mirror arm on the front doors stands further out),
# sample the door's dark block like the card / edge-band backs.
BELT_SKIN_BAND = 0.10
BELT_SKIN_UP = 0.03
BELT_SKIN_NX = 0.2
BELT_SKIN_OUT = 0.06


def _add_backs(ob, polys):
    """Flipped copies of the given faces (same UVs), flat normals; other corners keep theirs. On a
    door, the copies of trim-card and edge-band faces sample the dark block (DARK_BACK_MATS).
    Returns (copies, copies on the dark block)."""
    me = ob.data
    names = [m.name if m else "?" for m in me.materials]
    dark = _dark_uv(me) if ob.name in DARK_BACK_OBJECTS else None
    before = [tuple(c.vector) for c in me.corner_normals]
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.faces.ensure_lookup_table()
    faces = [bm.faces[i] for i in sorted(polys) if i < len(bm.faces)]
    ret = bmesh.ops.duplicate(bm, geom=faces)
    new = [g for g in ret["geom"] if isinstance(g, bmesh.types.BMFace)]
    bmesh.ops.reverse_faces(bm, faces=new)
    n_dark = 0
    if dark is not None and bm.loops.layers.uv:
        uvl = bm.loops.layers.uv[0]
        belt = _belt_band(ob, names)
        M = ob.matrix_world
        R = M.to_3x3()
        for f in new:
            mn = names[f.material_index] if f.material_index < len(names) else "?"
            inside_skin = False
            if belt is not None and not mn.startswith(DARK_BACK_MATS) and mn not in GLASS_MATS:
                c = M @ f.calc_center_median()
                n = (R @ f.normal).normalized()          # the copy's normal: the skin's, reversed
                side, sill, (y0, y1), xmax = belt
                inside_skin = (-n.x * side > BELT_SKIN_NX and sill - BELT_SKIN_BAND <= c.z <= sill + BELT_SKIN_UP
                               and y0 - 0.02 <= c.y <= y1 + 0.02 and abs(c.x) <= xmax)
            if mn.startswith(DARK_BACK_MATS) or inside_skin:
                for loop in f.loops:
                    loop[uvl].uv = dark
                n_dark += 1
    bm.to_mesh(me)
    bm.free()
    me.update()
    normals = list(before)
    for poly in me.polygons[len(me.polygons) - len(new):]:
        normals.extend([tuple(poly.normal)] * len(poly.loop_indices))
    if len(normals) == len(me.loops):
        me.normals_split_custom_set(normals)
    if ob.name in DARK_BACK_OBJECTS and dark is None:
        print("BACKFILL warning: %s has no dark block (uv_island -2): its card backs keep the card's texels" % ob.name)
    return len(new), n_dark


NO_BACKFILL = "no_backfill"   # INT face attribute set by a builder: 1 = never give this face a back (WHL-1:
                              # build_liners' bay aprons, whose copies showed body colour inside the front wheel wells)


def _never_backed(objs):
    """{object name: {face index}} of the faces marked NO_BACKFILL."""
    out = {}
    for o in objs:
        a = o.data.attributes.get(NO_BACKFILL)
        if a is None or a.domain != 'FACE' or a.data_type != 'INT':
            continue
        vals = [0] * len(o.data.polygons)
        a.data.foreach_get("value", vals)
        s = {i for i, v in enumerate(vals) if v}
        if s:
            out[o.name] = s
    return out


def poses(opened):
    """(name, clips, full) per scanned pose. Shut and everything open get every scan (full); each panel
    open on its own gets the seat eyes too (OPEN-4/5, 2026-10-17: a rear passenger sees the left D-pillar's
    inside with only the gate open, the driver both A-pillars with only the front doors open; with every
    panel open a swung door hides some of what one open panel shows)."""
    out = [("shut", (), True), ("open", tuple(opened), True)]
    singles = [c for c in opened if c.startswith("door_")]
    if "trunk_opening" in opened:
        singles.append("trunk_opening")
    fronts = tuple(c for c in opened if c in ("door_fl_opening", "door_fr_opening"))
    for c in singles:
        out.append((c.replace("_opening", ""), (c,), False))
    if len(fronts) == 2:
        out.append(("front doors", fronts, False))
    return out


def _pose_partial(arm, clips, frac):
    """Every clip in `clips` at `frac` of its travel (rig_vehicle.pose only knows shut and open): each channel
    at frac of its open value, the gate's struts and the hood's prop rod following their panel."""
    import rig_vehicle
    rig_vehicle.pose(arm, ())
    for clip in clips:
        for bone, channel, value in rig_vehicle.CLIPS[clip]:
            if bone in arm.pose.bones:
                rig_vehicle._apply(arm.pose.bones[bone], channel, value * frac)
    rots = {}
    if "trunk_opening" in clips:
        rots.update(rig_vehicle.strut_rotations(frac))
    if "hood_opening" in clips:
        try:
            lift = rig_vehicle._prop_lift(rig_vehicle._hood_angle() * frac, 0.0)
        except Exception as exc:                 # noqa: BLE001
            print("BACKFILL warning: prop rod lift at %.0f %% not computed (%s): stowed" % (frac * 100, exc))
            lift = 0.0
        rots.update(rig_vehicle.prop_rotations(lift))
    for bone, e in rots.items():
        if bone in arm.pose.bones:
            arm.pose.bones[bone].rotation_euler = e
    bpy.context.view_layer.update()


def fill(arm, report=print, skip_mats=()):
    import rig_vehicle
    objs, loose = _meshes()
    opened = tuple(c for c in rig_vehicle.CLIPS if c.endswith("_opening") and not c.startswith("window"))
    marks = set()
    rig_vehicle.pose(arm, ())
    _INVISIBLE_BACKS.clear()
    _PASS.clear()
    if SEAMBACK in skip_mats:                   # the pane backings only: every other SeamBack face gets its back
        _INVISIBLE_BACKS.update(_pane_backings(objs))
        report("BACKFILL %d SeamBack faces are pane plates (looked through from behind)" % len(_INVISIBLE_BACKS))
    _t, _o, shut_verts = _tree(objs)
    scale = car_scale(shut_verts)               # one scale for both poses: the grid and the eyes stay put
    lo, hi = _bounds(shut_verts)
    report("BACKFILL scan box %.2f x %.2f x %.2f, scale %.3f (game grid %.1f mm), %d car meshes, %d loose"
           % (hi.x - lo.x, hi.y - lo.y, hi.z - lo.z, scale, GRID * 1000, len(objs), len(loose)))
    if not any(a <= scale <= b for a, b in CAR_SCALES):
        report("BACKFILL warning: scale %.3f is not a car's (%s): is a mesh parked beside the car in the scan?"
               % (scale, CAR_SCALES))
    report("BACKFILL eyes: %d seat / cargo eyes every %.2f deg (driver (%.2f, %.2f, %.2f) m), ring of %d every %.2f deg"
           % (len(eye_points()), EYE_STEP, eye_points()[0][0], eye_points()[0][1], eye_points()[0][2],
              len(RING_EYES) * (360 // RING_AZ), RING_STEP))
    for pose_name, clips, full in poses(opened):
        rig_vehicle.pose(arm, clips)
        tree, owner, verts = _tree(objs)
        before = len(marks)
        game = low = cabin = 0
        if full:
            for off in OFFSETS:
                _scan(tree, owner, verts, marks, scale, offset=off)
            game = len(marks) - before
        if EYE_VIEWS:
            if full:
                n0 = len(marks)
                _scan(tree, owner, verts, marks, scale, LOW_ELEVATIONS, LOW_GRID)
                _scan_ring(tree, owner, verts, marks, scale)
                low = len(marks) - n0
            n0 = len(marks)
            _scan_eyes(tree, owner, verts, marks, scale)
            cabin = len(marks) - n0
        if full:
            report("BACKFILL %s pose: %d faces seen from behind by the game camera, +%d at eye level, +%d from the seats"
                   % (pose_name, game, low, cabin))
        else:
            report("BACKFILL %s pose: +%d from the seats" % (pose_name, cabin))
    for frac in PARTIAL_FRACS:                  # every panel part-way through its swing: the game camera
        _pose_partial(arm, opened, frac)
        tree, owner, verts = _tree(objs)
        before = len(marks)
        for off in OFFSETS:
            _scan(tree, owner, verts, marks, scale, elevations=(30.0,), offset=off)
        report("BACKFILL %.0f %% open pose: +%d faces seen from behind by the game camera" % (frac * 100, len(marks) - before))
    rig_vehicle.pose(arm, ())
    forced, forced_marks = {}, set()
    for name, boxes in FORCE_BACKS.items():
        targets = objs if name == "*" else [o for o in objs if o.name == name]
        def inside(c, boxes=boxes):
            return any(x0 <= c.x <= x1 and y0 <= c.y <= y1 and z0 <= c.z <= z1 for (x0, x1), (y0, y1), (z0, z1) in boxes)
        for ob in targets:
            M = ob.matrix_world
            vs = [M @ v.co for v in ob.data.vertices]
            for p in ob.data.polygons:
                if any(inside(vs[i]) for i in p.vertices):          # a big polygon's centre can lie outside
                    key = (ob.name, p.index)                         # already scanned or not: a SeamBack plate the
                    marks.add(key)                                   # scan met is dropped by skip_mats below
                    forced_marks.add(key)
                    forced[ob.name] = forced.get(ob.name, 0) + 1
    report("BACKFILL forced (FORCE_BACKS boxes): %s" % (", ".join("%s %d" % kv for kv in sorted(forced.items())) or "none"))
    for o in loose:                             # alone, on the car's grid: game camera and eye level (no seats)
        tree, owner, verts = _tree([o])
        before = len(marks)
        for off in OFFSETS:
            _scan(tree, owner, verts, marks, scale, offset=off)
        if EYE_VIEWS:
            _scan(tree, owner, verts, marks, scale, LOW_ELEVATIONS, LOW_GRID)
        report("BACKFILL loose %s: %d faces seen from behind, scanned on its own" % (o.name, len(marks) - before))
    by_obj = {}
    never = _never_backed(objs + loose)
    if never:
        report("BACKFILL %d faces carry %s (never backed): %s" % (sum(len(v) for v in never.values()), NO_BACKFILL,
               ", ".join("%s %d" % (k, len(v)) for k, v in sorted(never.items()))))
    for name, idx in marks:
        if idx in never.get(name, ()):
            continue
        ob = bpy.data.objects.get(name)
        if ob is not None and skip_mats and (name, idx) not in forced_marks:   # forced faces keep their backs (the SeamBack
                                                                             # plates behind a headlamp, seen from the bay)
            mi = ob.data.polygons[idx].material_index
            m = ob.data.materials[mi] if mi < len(ob.data.materials) else None
            if m is not None and m.name in skip_mats and m.name != SEAMBACK:   # SeamBack: see SEAMBACK
                continue
        by_obj.setdefault(name, set()).add(idx)
    _PASS.clear()
    total = 0
    for name, polys in sorted(by_obj.items()):
        ob = bpy.data.objects.get(name)
        if ob is None:
            continue
        k, kd = _add_backs(ob, polys)
        total += k
        report("BACKFILL %-14s %4d back faces added%s" % (name, k, ", %d card / edge-band backs on the dark block" % kd if kd else ""))
    report("BACKFILL TOTAL %d back faces" % total)
    return total
