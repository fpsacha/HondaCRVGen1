r"""
Wheel-arch liners: four half-drums inside the arches so the camera cannot see through the
fender into the engine bay or under the floor. The kotris shell has no inner arch geometry.

    exec(compile(open(r"scripts\build_liners.py").read(), "build_liners", "exec"))

Static, rides the body. Model metres: +Y nose, +Z up, +X right. Each liner is a half cylinder
(180 deg, open downward) around the wheel centre, closed by an inboard disc, so it reads as the
black plastic liner of the real car from any angle the game uses.
"""
import math
import bpy

NAME = "arch_liners"
MATERIAL = "ArchLiner"
WHEEL_Y = (1.31, -1.31)          # axle positions
WHEEL_Z = 0.334                  # axle height (tyre radius)
RADIUS = 0.46                    # liner radius: tyre 0.334 plus clearance, under the flare lip
X_OUT = 0.84                     # just inside the fender skin (0.87)
X_IN = 0.56                      # inboard wall, outside the engine block / floor pan
SEGMENTS = 12


def _material():
    mat = bpy.data.materials.get(MATERIAL)
    if mat is None:
        mat = bpy.data.materials.new(MATERIAL)
    mat.use_nodes = True
    bsdf = next((n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
    if bsdf:
        bsdf.inputs['Base Color'].default_value = (0.020, 0.020, 0.021, 1.0)
        bsdf.inputs['Roughness'].default_value = 0.95
    return mat


X_FLANGE = 0.855                 # flange ring, 1.5 cm inside the fender skin at the arch
R_FLANGE = 0.53                  # past the skin's arch cut, so the cut never shows the drum's edge
ARC_BELOW = math.radians(-26)    # barrel ends 20 cm above the axle: lower, its end quads showed in the arch opening below the rocker
DISC_BELOW = math.radians(5)     # the inboard disc runs on to 5 deg under the axle height (4 cm) at both ends (WHL-4)


def _oriented(verts, idx, want):
    """Return the quad/tri index tuple wound so its normal has a positive component along want."""
    a, b, c = (verts[i] for i in idx[:3])
    ab = (b[0] - a[0], b[1] - a[1], b[2] - a[2]); ac = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
    n = (ab[1] * ac[2] - ab[2] * ac[1], ab[2] * ac[0] - ab[0] * ac[2], ab[0] * ac[1] - ab[1] * ac[0])
    return idx if n[0] * want[0] + n[1] * want[1] + n[2] * want[2] >= 0 else tuple(reversed(idx))


def _drum(verts, faces, side, y, skin_x=None):
    """One liner, every face wound to face the WHEEL (the game culls back faces, and an inside-out
    drum is invisible from the road): a flange annulus just inside the skin from R_FLANGE down to
    RADIUS (closes the gap between the skin's arch cut and the drum), the barrel from X_OUT in to
    X_IN facing the axle, and the inboard disc facing outward."""
    xi = side * X_IN
    base = len(verts)
    ring = []
    for i in range(SEGMENTS + 1):
        # 0 = rear, pi = front, arc over the top; the barrel runs ARC_BELOW past the axle height at
        # both ends so its open ends sit down behind the bumpers and the tyre, out of the camera's view
        a = -ARC_BELOW + (math.pi + 2 * ARC_BELOW) * i / SEGMENTS
        ring.append((math.cos(a), math.sin(a)))

    def clip(x_want, cy, cz, margin):
        """Keep the ring inside the body skin: the rocker sits at |x| 0.82-0.84 while the flare is at
        0.87, and a ring at one radius poked out under the doors as black flaps."""
        if skin_x is None:
            return side * x_want
        xs = skin_x(side, cy, cz)
        return side * (min(x_want, xs - margin) if xs is not None else x_want)
    for c, s in ring:                                   # flange ring, kept above z 0.47: lower than that its
        cy, cz = y - R_FLANGE * c, WHEEL_Z + R_FLANGE * max(s, 0.26)               # end quads hung below the rocker and
        verts.append((clip(X_FLANGE, cy, cz, 0.012), cy, cz))                      # the bumper lips as black flaps
    for c, s in ring:                                   # outer barrel ring
        cy, cz = y - RADIUS * c, WHEEL_Z + RADIUS * s
        verts.append((clip(X_OUT, cy, cz, 0.02), cy, cz))
    for c, s in ring:                                   # inner barrel ring
        verts.append((xi, y - RADIUS * c, WHEEL_Z + RADIUS * s))
    for c, s in ring:                                   # second barrel, 2 mm out, wound the other way:
        cy, cz = y - (RADIUS + 0.002) * c, WHEEL_Z + (RADIUS + 0.002) * s           # the drum's outside shows
        verts.append((clip(X_OUT, cy, cz, 0.02), cy, cz))                          # under the bumpers and past
    for c, s in ring:                                   # the tyre from the game's camera
        verts.append((xi, y - (RADIUS + 0.002) * c, WHEEL_Z + (RADIUS + 0.002) * s))
    n = SEGMENTS + 1
    out = (side, 0.0, 0.0)
    for i in range(SEGMENTS):
        f0, f1, o0, o1, i0, i1 = base + i, base + i + 1, base + n + i, base + n + i + 1, base + 2 * n + i, base + 2 * n + i + 1
        faces.append(_oriented(verts, (f0, f1, o1, o0), out))                          # flange faces the road
        cm = [(verts[o0][k] + verts[o1][k] + verts[i0][k] + verts[i1][k]) / 4 for k in range(3)]
        to_axle = (0.0, y - cm[1], WHEEL_Z - cm[2])
        faces.append(_oriented(verts, (o0, o1, i1, i0), to_axle))                      # barrel faces the axle
        p0, p1, q0, q1 = o0 + 2 * n, o1 + 2 * n, i0 + 2 * n, i1 + 2 * n
        faces.append(_oriented(verts, (p0, p1, q1, q0), (0.0, -to_axle[1], -to_axle[2])))   # outer barrel faces away
    centre = len(verts)
    verts.append((xi, y, WHEEL_Z))
    for i in range(SEGMENTS):
        i0, i1 = base + 2 * n + i, base + 2 * n + i + 1
        faces.append(_oriented(verts, (centre, i1, i0), out))                          # disc faces the wheel
    # 2026-10-17 (WHL-4 / EXT-9): the barrel ends ARC_BELOW above the axle and the disc stopped with it, so
    # the sectors between the barrel's ends and the axle height were open: ahead of each rear tyre the
    # interior's side (faces at (+-0.55, -0.95..-0.99, 0.44..0.46)) showed through the arch. The disc alone
    # (inboard, out of the arch opening's view below the rocker) carries on DISC_BELOW past horizontal.
    for a0, a1 in ((-ARC_BELOW, -DISC_BELOW), (math.pi + ARC_BELOW, math.pi + DISC_BELOW)):
        k = max(2, int(math.ceil(abs(a1 - a0) / (math.pi / SEGMENTS))))
        prev = None
        for j in range(k + 1):
            a = a0 + (a1 - a0) * j / k
            idx = len(verts)
            verts.append((xi, y - RADIUS * math.cos(a), WHEEL_Z + RADIUS * math.sin(a)))
            if prev is not None:
                faces.append(_oriented(verts, (centre, prev, idx), out))
            prev = idx


ANTENNA = "antenna"


def _antenna_material():
    mat = bpy.data.materials.get("Antenna")
    if mat is None:
        mat = bpy.data.materials.new("Antenna")
        mat.use_nodes = True
        bsdf = next((n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
        if bsdf:
            bsdf.inputs['Base Color'].default_value = (0.035, 0.035, 0.037, 1.0)
            bsdf.inputs['Roughness'].default_value = 0.45
    return mat


# Where (2026-10-13, the mouse on the car in an in-game screenshot 15.png): the mast stands at
# the TOP of the LEFT A-pillar (driver's side, x < 0), where the pillar meets the roof: the North
# American RD1's pillar antenna. Reference photos (blender/references/commons): 1999 LX front left
# and 2000 EX rear left (postfacelift), the DC-area LX and the black LX "Honda CR-V EX.jpg"
# (unclear/): a small black boot on the pillar top just behind the windscreen's top-left corner,
# the mast sweeping back over the roof edge. Rake from the mast's slant in five views of known
# azimuth (least squares; azimuths from the car's front/side width ratios): 63 deg back from
# vertical, ~12 deg inboard of straight back; full length (ball tip seen on the 2000 EX) 0.6 m, the
# 1999 LX's cut-off mast at least 0.56 m. Before: at the pillar BASE by the mirror (2026-10-12),
# running up along the pillar where the game camera barely saw it; before that on the left fender
# by the headlamp, and kotris's (0.72, 1.05) on the hood's right edge. Everything is measured on the
# body as it is now (the low body at prep's refit): the windscreen is the body's glass facing
# forward (as build_accessories takes it), its left edge the outermost glass vertex per 3 cm of
# height; the top-left corner is the highest of those within 3 cm of the line fitted to the edge.
ANT_BACK, ANT_OUT = 0.030, 0.027  # boot centre behind / outboard of the windscreen's top-left corner: on the
                                  # pillar top between the glass edge (|x| 0.563) and the front door's
                                  # window frame (|x| 0.603-0.614 there), which swings out with the door
ANT_RAKE = 62.0                   # degrees back from vertical (photos: 63)
ANT_INBOARD = 0.0                 # degrees inboard of straight back, seen from above. The photos suggest ~12
                                  # (the least certain figure: it hangs on the azimuth estimates), but the
                                  # left rail's front foot ramps up 9 cm over the 10 cm right behind the boot
                                  # (build_details rails, |x| 0.539-0.571): any inboard lean runs the mast
                                  # into it; straight back passes 1.7 cm outboard of it
ANT_CLEAR = 0.012                 # the mast's axis stays this far off the body (roof, rails) and the hood
ANT_LIFT_MAX = 0.04               # the collar may stand this far above BOOT_H along the axis to get there: the
                                  # pillar top rises 1-6 cm into the roof edge behind the corner
PILLAR_FIT_TOP = 1.50             # metres: the edge points used for the pillar line (corner .. this)
BOOT_FOOT = (0.013, 0.034)        # elliptical foot half-axes: across the mast, along it (a ~7 cm black teardrop)
BOOT_TOP_R, BOOT_H = 0.010, 0.032 # collar radius; base housing length along the axis (4 mm of the foot sunk)
MAST_R, MAST_L = (0.005, 0.003), 0.60   # hexagonal rod, base -> tip radius, length along the same axis


def _pillar(body):
    """(top-left corner of the windscreen glass, unit direction up the left A-pillar edge)."""
    from mathutils import Vector
    names = [m.name if m else "?" for m in body.data.materials]
    mw = body.matrix_world
    pts = {}
    for p in body.data.polygons:
        if names[p.material_index] not in ("Vitre", "Vitre_noir"):
            continue
        n = (mw.to_3x3() @ p.normal).normalized()
        c = mw @ p.center
        if c.y < 0.25 or n.y < 0.3:
            continue
        for i in p.vertices:
            w = mw @ body.data.vertices[i].co
            if w.x < -0.3:
                pts[i] = w
    if not pts:
        return None
    rows = {}
    for w in pts.values():                       # outermost (min x) glass vertex per 3 cm of height
        k = int(w.z / 0.03)
        if k not in rows or w.x < rows[k].x:
            rows[k] = w
    edge = sorted(rows.values(), key=lambda w: w.z)
    import numpy as np
    # the decimated pane has no outline vertex in some bands, whose outermost vertex then lies 15-35 cm
    # inboard (along the top edge, too): fit x(z), drop points more than 3 cm inboard of it, fit again
    fit = [w for w in edge if w.z <= PILLAR_FIT_TOP + 0.15] or list(edge)
    b, a0 = 0.0, fit[0].x
    for _ in range(3):
        zs = np.array([w.z for w in fit])
        xs = np.array([w.x for w in fit])
        b, a0 = np.polyfit(zs, xs, 1) if len(fit) >= 2 else (0.0, xs.mean())
        keep = [w for w in fit if w.x <= a0 + b * w.z + 0.03]
        if len(keep) == len(fit) or len(keep) < 3:
            break
        fit = keep
    # the top-left corner: the highest edge point still on the pillar line (the band above it is the
    # top edge running inboard)
    on_line = [w for w in edge if abs(w.x - (a0 + b * w.z)) <= 0.03]
    corner = max(on_line or edge, key=lambda w: w.z)
    fit = [w for w in fit if w.z <= PILLAR_FIT_TOP] or fit[:3]
    a = np.array([tuple(w) for w in fit])
    c = a.mean(axis=0)
    _s, _v, vt = np.linalg.svd(a - c)
    d = Vector(vt[0]).normalized()
    if d.z < 0:
        d = -d
    return corner, d


def build_antenna():
    """Mast at the TOP of the LEFT A-pillar: an 8-sided boot (a low teardrop on the pillar top,
    capped at the collar) and a 6-sided mast (38 tris, Antenna, smooth) raked ANT_RAKE back from
    vertical and ANT_INBOARD inboard, over the roof edge. The boot's foot is cast down onto the body
    ANT_BACK / ANT_OUT from the windscreen's top-left corner and its collar raised until the whole
    mast clears the body (the roof edge, the rail's front foot) and the hood by ANT_CLEAR; the
    clearance is printed, and the clearance to the front door and the fitted accessories
    (windscreen guard, roof basket) as information."""
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    old = bpy.data.objects.get(ANTENNA)
    if old:
        bpy.data.objects.remove(old, do_unlink=True)
    body = bpy.data.objects.get("body")
    found = _pillar(body) if body is not None else None
    if found is None:                            # the 2026-10-12 low body's numbers
        corner = Vector((-0.563, 0.291, 1.542))
    else:
        corner = found[0]
    side = -1.0                                  # left
    r, i = math.radians(ANT_RAKE), math.radians(ANT_INBOARD)
    ax = Vector((-side * math.sin(r) * math.sin(i), -math.sin(r) * math.cos(i), math.cos(r))).normalized()
    solids = [o for o in (body, bpy.data.objects.get("hood")) if o is not None]
    dg = bpy.context.evaluated_depsgraph_get()
    trees = [BVHTree.FromObject(o, dg) for o in solids]       # parts sit at the identity (prep_parts)

    def surface_z(x, y, default):
        """Top of the body / hood at (x, y) near the corner's height: outboard of the pillar top the
        door frame (not a solid here) leaves a gap, and a ray through it hit the sill 1.2 m down."""
        zs = []
        for o in solids:
            inv = o.matrix_world.inverted()
            hit, loc, _n, _i = o.ray_cast(inv @ Vector((x, y, corner.z + 0.30)), Vector((0, 0, -1)), distance=0.45)
            if hit:
                zs.append((o.matrix_world @ loc).z)
        return max(zs) if zs else default

    def base_at(out):
        x, y = corner.x + side * out, corner.y - ANT_BACK
        z = surface_z(x, y, None)
        return Vector((x, y, z - 0.004)) if z is not None else None

    def clearance(top, tr_list):
        worst = 9.0
        for k in range(0, 31):                   # the mast's axis from the collar to the tip
            p = top + ax * (MAST_L * k / 30.0)
            for tr in tr_list:
                hit = tr.find_nearest(p)
                if hit[0] is not None:
                    worst = min(worst, (hit[0] - p).length)
        return worst
    base = base_at(ANT_OUT) or Vector((corner.x + side * ANT_OUT, corner.y - ANT_BACK, corner.z))
    # the foot stays on the skin; the collar rises until the whole mast clears the body (the pillar
    # top climbs into the roof edge right behind the corner, and the rail's front foot is 10 cm back)
    lift = 0.0
    top = base + ax * BOOT_H
    clear = clearance(top, trees)
    while clear < ANT_CLEAR and lift < ANT_LIFT_MAX:
        lift += 0.0025
        top = base + ax * BOOT_H + Vector((0.0, 0.0, lift))
        clear = clearance(top, trees)
    if clear < ANT_CLEAR:
        print("antenna: WARNING mast axis only %.1f cm off the body / hood (wanted %.1f)" % (clear * 100, ANT_CLEAR * 100))
    x, y, z = base.x, base.y, base.z + 0.004
    u = Vector((1.0, 0.0, 0.0))
    u = (u - ax * u.dot(ax)).normalized()                     # across the mast
    w = ax.cross(u).normalized()                              # along it
    verts, faces = [], []

    def ring(c, ru, rw, n, foot=False):
        i0 = len(verts)
        ww = w
        if foot:                                              # the foot lies on the skin, not square to the
            ww = Vector((w.x, w.y, 0.0)).normalized()         # leaning axis: each point is cast onto the body
        for k in range(n):
            a = 2 * math.pi * k / n
            p = c + u * (ru * math.cos(a)) + ww * (rw * math.sin(a))
            if foot:
                p = Vector((p.x, p.y, surface_z(p.x, p.y, p.z + 0.004) - 0.004))
            verts.append(tuple(p))
        return list(range(i0, i0 + n))
    r0 = ring(base, BOOT_FOOT[0], BOOT_FOOT[1], 8, foot=True)
    r1 = ring(top, BOOT_TOP_R, BOOT_TOP_R, 8)
    for i in range(8):
        j = (i + 1) % 8
        faces.append((r0[i], r0[j], r1[j], r1[i]))
    faces.append(tuple(reversed(r1)))                         # collar cap, the mast rises out of it
    m0 = ring(top - ax * 0.005, MAST_R[0], MAST_R[0], 6)
    m1 = ring(top + ax * MAST_L, MAST_R[1], MAST_R[1], 6)
    for i in range(6):
        j = (i + 1) % 6
        faces.append((m0[i], m0[j], m1[j], m1[i]))
    faces.append(tuple(reversed(m1)))                         # tip
    # every face wound outward (the game culls back faces): the caps along the axis, the mast's sides
    # away from the axis, the boot's sides away from the boot's own centre line (foot centre to
    # collar), which is not the mast's axis once the foot is spread along the skin
    foot_c = sum((Vector(verts[k]) for k in r0), Vector()) / len(r0)
    boot_ax = (top - foot_c).normalized()
    wound = []
    for n_f, f in enumerate(faces):
        pts = [Vector(verts[k]) for k in f]
        n = (pts[1] - pts[0]).cross(pts[2] - pts[0])
        c = sum(pts, Vector()) / len(pts)
        if len(f) > 4:
            want = ax
        elif n_f < 8:                                         # boot side
            v = c - foot_c
            want = v - boot_ax * v.dot(boot_ax)
        else:
            want = (c - top) - ax * ((c - top).dot(ax))
        wound.append(tuple(reversed(f)) if n.dot(want) < 0 else f)
    me = bpy.data.meshes.new(ANTENNA)
    me.from_pydata(verts, [], wound)
    me.validate()
    me.materials.append(_antenna_material())
    for poly in me.polygons:
        poly.use_smooth = True
    ob = bpy.data.objects.new(ANTENNA, me)
    (body.users_collection[0] if body else bpy.context.scene.collection).objects.link(ob)
    tip = top + ax * MAST_L
    print("antenna at x %.3f y %.3f z %.3f, windscreen top-left corner (%.3f, %.3f, %.3f), axis (%.2f, %.2f, %.2f) "
          "%.0f deg back from vertical, %.0f deg inboard, collar (%.3f, %.3f, %.3f) lifted %.1f cm, tip (%.3f, %.3f, %.3f), "
          "%.1f cm clear of body / hood, %d tris"
          % (x, y, z, corner.x, corner.y, corner.z, ax.x, ax.y, ax.z, math.degrees(math.acos(max(-1.0, min(1.0, ax.z)))),
             ANT_INBOARD, top.x, top.y, top.z, lift * 100, tip.x, tip.y, tip.z, clear * 100,
             sum(len(p.vertices) - 2 for p in me.polygons)))
    info = []
    for n in ("door_fl", "acc_guard_ws", "acc_roofrack"):     # doors swing, accessories come and go:
        o = bpy.data.objects.get(n)                           # reported, not placed against
        if o is not None and o.type == 'MESH':
            info.append("%s %.1f cm" % (n, clearance(top, [BVHTree.FromObject(o, dg)]) * 100))
    if info:
        print("antenna axis clearance to " + ", ".join(info))
    return ob


WALLS = "bay_walls"
LAMP_TOP = 0.882                 # 1.1 cm under the kotris headlamp housings' top (z 0.893)
HEAD_LAMP_MATS = ("Phare", "Phare_vitre", "Phare_orange", "Reflect_orange")   # bake_atlas.HEAD_LAMP_MATS
LENS_GAP = 0.012                 # the side panels stop this far behind the headlamp lens (2026-10-14)
TOWER_SEG = 20                   # sides of the strut tower lathe (BAY-7)
# The towers (centres |x| 0.50, r 0.09) reached |x| 0.59, through the arch liner's inboard wall (X_IN 0.56):
# a body-colour column stood in each front wheel well above the tyre (WHL-1 crouch views, 2026-10-17). Their
# outboard side is cut flat at TOWER_X_MAX.
TOWER_X_MAX = X_IN - 0.004
NO_BACKFILL = "no_backfill"      # INT face attribute: 1 = backfill never gives this face a back (backfill.NO_BACKFILL)
# The firewall top falls CROWN_FIREWALL x^2 toward the aprons, the hood's crown there (measured on the built
# hood 2026-10-17: the skin at y 1.05 falls 1.4 cm from the centre to |x| 0.43)
CROWN_FIREWALL = 0.075
# The header strips behind the grille (round 2, see build_bay_walls): the rear strip's top stands this far over
# the tie bar's bottom (bay.front.TIE_Z0), and every top vertex of both stays HEADER_COVER_GAP under the lowest
# hood / body surface over it, never lower than HEADER_MIN_H over the strip's bottom
HEADER_TIE_OVERLAP = 0.003
HEADER_COVER_GAP = 0.005
HEADER_MIN_H = 0.015
# Dash-end shields (round 2, R2-VP-5): from a crouch beside the front doors two slits in the door's front top
# corner (between the window frame's black front fin and the frame skin at y 0.62-0.64, z 1.13-1.15, and along
# the belt under the mirror foot) look straight at the cabin's dash end cap (cabin faces 646 / 67 at |x| 0.725,
# CabDash sRGB 64) and the A-pillar trim's lower foot: 40-105 px lines in the crouch views. No face on those
# rays is culled, so backfill cannot close them. A dark (Dessous) plate DASH_SHIELD_X out, facing outboard,
# covers the dash end where the rays land (a ray scan from 5 deg / 0.4-2.0 m eyes round each front corner,
# 2026-10-17: y 0.59-0.79, z 1.04-1.17 on the cap); its outline follows the cap's top (build_cabin's dash at
# the end station, measured on the 2026-10-17 build) 4 mm over it. Faces outboard and never backed: from the
# seats it is culled behind the dash and the pillar trim; with the door open the cap reads dark.
DASH_SHIELD_X = 0.729
DASH_SHIELD = [(0.560, 1.040), (0.790, 1.040), (0.790, 1.103), (0.704, 1.147), (0.590, 1.174), (0.560, 1.174)]


def _body_material():
    return bpy.data.materials.get("Body") or _material()


def _dessous_material():
    return bpy.data.materials.get("Dessous") or _material()


def _box(verts, faces, x0, x1, y0, y1, z0, z1):
    b = len(verts)
    verts += [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
              (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    faces += [tuple(b + i for i in f) for f in
              ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7))]


# Rear underbody (2026-10-17, WHL-5): the kotris cargo floor's spare-wheel tub (interior, Interieur_sol, a
# box x +-0.57, y -2.054..-1.860, z 0.440..0.765) hangs up to 4 cm under the body's rear floor (Dessous, z
# 0.435-0.485), so from behind and low its flat grey rear wall (y -2.054) and floor showed under the bumper,
# the body's own tailpipe (Metal, x 0.41-0.46) in front of it. A dark box (Dessous) wraps the part under the
# floor: VALANCE_PAD outside the tub, from just under its floor up to VALANCE_TOP (inside the body floor and
# the tub), slotted round the tailpipe (VALANCE_PIPE_GAP each side, a bridge over it). The tub is measured
# off the interior when it is there; in the build it is not yet at this point (both passes say so) and
# VALANCE_FALLBACK, measured on the 2026-10-17 crv_kotris.blend, places the box.
VALANCE_PAD = 0.005
VALANCE_TOP = 0.490
VALANCE_PIPE_GAP = 0.004
VALANCE_FALLBACK = ((-0.570, 0.570), (-2.054, -1.860), 0.440)      # tub x, y and floor z, when it is not found
VALANCE_PIPE_FALLBACK = (0.412, 0.462, 0.476)                       # tailpipe x range and top z
VALANCE_TUB_TOP = 0.765                                             # the tub's top (the cargo floor), 2026-10-17


def rear_valance(add):
    """Dark box round the part of the cargo floor's tub that hangs under the body (see VALANCE_*).
    add(mat_index, x0, x1, y0, y1, z0, z1) is build_bay_walls' box adder."""
    interior = bpy.data.objects.get("interior")
    tub = None
    if interior is not None and interior.type == 'MESH':
        M = interior.matrix_world
        pts = [M @ v.co for v in interior.data.vertices]
        pts = [p for p in pts if p.y < -1.80 and p.z < VALANCE_TOP and abs(p.x) < 0.60]
        if pts:
            tub = ((min(p.x for p in pts), max(p.x for p in pts)), (min(p.y for p in pts), max(p.y for p in pts)),
                   min(p.z for p in pts))
    if tub is None:
        print("bay_walls: no cargo tub under the floor yet: rear valance on VALANCE_FALLBACK")
        tub = VALANCE_FALLBACK
    (tx0, tx1), (ty0, ty1), tz = tub
    pipe = None
    body = bpy.data.objects.get("body")
    if body is not None:
        M = body.matrix_world
        names = [m.name if m else "?" for m in body.data.materials]
        xs, zs = [], []
        for p in body.data.polygons:
            if names[p.material_index] != "Metal":
                continue
            c = M @ p.center
            if c.y < ty0 + 0.02 or c.y > ty1 or c.z > VALANCE_TOP or not (tx0 < c.x < tx1):
                continue
            for i in p.vertices:
                w = M @ body.data.vertices[i].co
                xs.append(w.x)
                zs.append(w.z)
        if xs:
            pipe = (min(xs), max(xs), max(zs))
    if pipe is None:
        pipe = VALANCE_PIPE_FALLBACK
    x0, x1 = tx0 - VALANCE_PAD, tx1 + VALANCE_PAD
    y0, y1 = ty0 - VALANCE_PAD, ty1 + VALANCE_PAD
    z0 = tz - 0.003
    px0, px1, ptop = pipe[0] - VALANCE_PIPE_GAP, pipe[1] + VALANCE_PIPE_GAP, pipe[2] + VALANCE_PIPE_GAP
    if x0 < px0 < px1 < x1 and ptop < VALANCE_TOP - 0.004:
        add(1, x0, px0, y0, y1, z0, VALANCE_TOP)
        add(1, px1, x1, y0, y1, z0, VALANCE_TOP)
        add(1, px0, px1, y0, y1, ptop, VALANCE_TOP)
    else:
        add(1, x0, x1, y0, y1, z0, VALANCE_TOP)
    # round 2 (R2-VP-7): the tub's rear wall above the valance (Interieur_sol, interior face at (0.385, -2.054,
    # 0.664) facing back) showed as a thin line through the seam between the bumper top and the gate's bottom
    # edge from a crouch behind the car. A dark plate VALANCE_PAD behind it, up to just under the cargo floor
    # (VALANCE_TUB_TOP); with the gate open it is the dark rear face of the floor, as the wall itself read.
    add(1, x0, x1, y0, y0 + 0.003, VALANCE_TOP - 0.002, VALANCE_TUB_TOP - 0.004)
    print("bay_walls: rear valance x %.3f..%.3f y %.3f..%.3f z %.3f..%.3f, tailpipe slot x %.3f..%.3f under z %.3f"
          % (x0, x1, y0, y1, z0, VALANCE_TOP, px0, px1, ptop))


def build_bay_walls():
    """The kotris body has no engine bay: firewall, inner-fender aprons, radiator support and an
    undertray close it so the bay no longer reads as a hole through the car. Body colour on the
    sheet metal (paint mask picks it up), underside black on the tray."""
    old = bpy.data.objects.get(WALLS)
    if old:
        bpy.data.objects.remove(old, do_unlink=True)
    verts, faces, mats = [], [], []
    smooth = set()                                        # indices of smooth-shaded faces (the tower sides)
    # 2026-10-17 (WHL-1): faces backfill must never back (face attribute NO_BACKFILL): the aprons. Seen from
    # the front wheel well their backfill copies reused the bay-side texel and showed body colour inside the
    # arch; culled, the view goes on to the liner's dark inboard wall (X_IN 0.56) and barrel, as at the rear.
    no_back = set()
    def add(mat_index, *box):
        n0 = len(faces)
        _box(verts, faces, *box)
        mats.extend([mat_index] * (len(faces) - n0))
    # Stays clear of the front wheel wells (y 0.85..1.77, |x| > 0.56) and of the headlamp housings
    # (|x| > 0.44, y past 1.72..1.95 depending on |x|): the firewall and the tray stop at the aprons,
    # the aprons stop before the lamps, the support side panels sit behind the lamps.
    # Tops follow the hood skin (ray cast, like the insulator pad) 6 cm below it: a flat top poked
    # through the hood's crown at the outer corners. Falls back to a safe height off the skin.
    hood = bpy.data.objects.get("hood")
    from mathutils import Vector
    inv = hood.matrix_world.inverted() if hood else None

    def top_at(x, y, fallback):
        if hood is None:
            return fallback
        hit, loc, _n, _i = hood.ray_cast(inv @ Vector((x, y, 2.0)), Vector((0, 0, -1)))
        return min(fallback, (hood.matrix_world @ loc).z - 0.06) if hit else fallback

    def hood_z_early(x, y):
        if hood is None:
            return None
        hit, loc, _n, _i = hood.ray_cast(inv @ Vector((x, y, 2.0)), Vector((0, 0, -1)))
        return (hood.matrix_world @ loc).z if hit else None
    def crown(xs, caps, k):
        """Tops t(x) = t0 - k x^2 with t0 as high as every cap allows (t(x) <= cap(x) at every x)."""
        t0 = min(c + k * x * x for x, c in zip(xs, caps))
        return [t0 - k * x * x for x in xs]

    def face(idx, want, mi):
        """Append a face wound so its normal (Newell) points along `want`."""
        n = Vector((0.0, 0.0, 0.0))
        for i in range(len(idx)):
            p, q = Vector(verts[idx[i]]), Vector(verts[idx[(i + 1) % len(idx)]])
            n += Vector(((p.y - q.y) * (p.z + q.z), (p.z - q.z) * (p.x + q.x), (p.x - q.x) * (p.y + q.y)))
        faces.append(tuple(idx) if n.dot(Vector(want)) >= 0 else tuple(reversed(idx)))
        mats.append(mi)

    def extrude(xs, profile_at, mat, apex=0):
        """A wall along x with SHARED vertices: at every station x the same closed (y, z) profile
        (counter-clockwise with y to the right, z up), so neighbouring stations share their edges and
        nothing steps. mat(xa, xb, i) is the material of profile edge i between two stations (i = -1 for
        the end caps); caps are fans from profile point `apex` (the reflex corner of an L)."""
        profs = [profile_at(x) for x in xs]
        n = len(profs[0])
        base = len(verts)
        for x, pr in zip(xs, profs):
            verts.extend((x, y, z) for y, z in pr)
        for k in range(len(xs) - 1):
            a, b = base + n * k, base + n * (k + 1)
            for i in range(n):
                j = (i + 1) % n
                p, q = profs[k][i], profs[k][j]
                face([a + i, a + j, b + j, b + i], (0.0, q[1] - p[1], -(q[0] - p[0])), mat(xs[k], xs[k + 1], i))
        for k, sign in ((0, -1.0), (len(xs) - 1, 1.0)):
            a = base + n * k
            xa, xb = (xs[0], xs[1]) if k == 0 else (xs[-2], xs[-1])
            for i in range(n - 2):
                face([a + apex, a + (apex + 1 + i) % n, a + (apex + 2 + i) % n], (sign, 0.0, 0.0), mat(xa, xb, -1))

    # Firewall: ONE strip apron to apron whose top follows the hood skin 6 cm under it vertex by vertex
    # (2026-10-17, BAY-3: 12 boxes, each top taken at its own centre, stepped by up to 5.9 cm).
    FW_N = 16
    # The first hood face over each station is the insulator pad where it reaches (|x| < 0.48: 1.04-1.06)
    # and the skin's rear corner past it (1.12): capped station by station the top stepped 6 cm at |x| 0.47.
    # The top is the hood's crown (CROWN_FIREWALL x^2) hung from the lowest cap, so it stays under every cap
    # (6 cm under the pad / skin) and runs smooth from apron to apron.
    fw_x = [-0.58 + 1.16 * k / FW_N for k in range(FW_N + 1)]
    fw_top = dict(zip(fw_x, crown(fw_x, [top_at(x, 0.985, 1.12) for x in fw_x], CROWN_FIREWALL)))
    extrude(fw_x, lambda x: [(0.975, 0.55), (0.99, 0.55), (0.99, fw_top[x]), (0.975, fw_top[x])],
            lambda xa, xb, i: 0)
    print("bay_walls: firewall top %.3f..%.3f over %d stations (hood skin - 6 cm)" % (min(fw_top.values()), max(fw_top.values()), len(fw_x)))
    # Cowl plenum behind the firewall, under the hinges (they sit at z 0.995). 2026-10-17 (CAB-1): it was a
    # box y 0.87-0.975, whose rear face stood up to 9 cm inside the cabin (the kotris firewall is at
    # build_cabin.FIREWALL, y 0.958 at the centre) and showed as a body-colour wall in both footwells. Now its
    # full-height part starts PLENUM_GAP behind the cabin's firewall at every x, and only a thin shelf at the
    # top (inside the dash, whose underside is at z 0.80-0.84) still reaches back to y 0.87 under the cowl;
    # every face toward the cabin or the floor is Dessous.
    import build_cabin
    def firewall_y(ax):
        pts = build_cabin.FIREWALL
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            if x0 <= ax <= x1:
                return y0 + (y1 - y0) * (ax - x0) / (x1 - x0)
        return pts[-1][1] if ax > pts[-1][0] else pts[0][1]
    PLENUM_GAP = 0.008
    breaks = sorted({0.0, 0.58} | {x for x, _y in build_cabin.FIREWALL if x < 0.58})
    pl_x = [-x for x in reversed(breaks) if x > 0] + breaks
    SHELF_Y, SHELF_Z = 0.870, 0.975

    def plenum(x):                                        # L profile: full height behind the cabin firewall, shelf on top
        yr = min(firewall_y(abs(x)) + PLENUM_GAP, 0.968)
        ys = min(SHELF_Y, yr - 0.002)
        return [(yr, 0.55), (0.976, 0.55), (0.976, 0.99), (ys, 0.99), (ys, SHELF_Z), (yr, SHELF_Z)]
    # edges: 0 bottom, 1 front (inside the firewall), 2 top (seen from the bay over the firewall), 3 shelf
    # rear, 4 shelf underside, 5 rear (toward the cabin); the caps face the aprons
    extrude(pl_x, plenum, lambda xa, xb, i: 0 if i in (1, 2) else 1, apex=5)
    # Radiator support sides, the strip over the core and the header behind the grille top: their
    # tops follow the hood 3 cm below it. Flat tops at 0.93 stood above the hood's front corners (z 0.90
    # there) and showed as grey flaps between the hood edge and each headlamp.
    for sx in (-1, 1):
        add(0, min(sx * 0.46, sx * 0.66), max(sx * 0.46, sx * 0.66), 1.70, 1.715, 0.60, top_at(sx * 0.56, 1.71, 0.93) if hood else 0.90)
    # The header (y 1.93) keeps its span, but its last 3 cm each side (|x| 0.40-0.43) are Dessous
    # (2026-10-14): there its front face stands 0-6 mm proud of the body-colour filler between grille
    # and headlamp, in the gap under the hood's cut-back corner, and showed as a body-colour sliver at
    # each lamp's inner top corner (pzview probe (0.428, 1.940, 0.855)); dark it reads as that gap.
    # Shortening it instead opened the gap to the road in the open-hood views (+5 leak px).
    # 2026-10-17 (BAY-3): both strips are one wall each with shared vertices, the top following the hood's
    # front edge 3 cm under it at every station (6 boxes topped at their centres stepped 0.882..0.923).
    # 2026-10-17 (round 2, R2-BAY-1 / R2-VP-3 / R2-EXT-5 / R2-BAY-3): both strips are Dessous now and lower.
    #  * The rear strip (y 1.870-1.885) stood 12 cm tall to z 0.924 right in front of the black upper tie bar
    #    (bay.front: y 1.835-1.868, z 0.858 up to its arch, 0.872-0.896): from the bumper, a crouch and the
    #    game camera the open bay's front edge was a blank body-colour slab hiding the bar, its latch, the hood
    #    bumpers and the bar's decal (lhd_03: that edge is the black bar with the latch). Its top now stops
    #    HEADER_TIE_OVERLAP over the bar's bottom: the bar's own front face closes the bay from there up.
    #  * The front strip (y 1.930-1.940) took its top from the hood 1 cm AHEAD of it, and at |x| 0.40-0.43 that
    #    ray missed the hood's cut-back corner (fallback 0.88): its dark end stood 1.5 cm above the body filler
    #    (z 0.862) and through the hood's corner skin (z 0.863-0.873 there), the dark notch and tabs inboard of
    #    each headlamp top (pzview probe: base face 8451 at (0.430, 1.933, 0.876), in front of hood face 68). Every
    #    top vertex of both strips now also stays HEADER_COVER_GAP under the lowest hood or body surface over
    #    it (any material above HEADER_COVER_Z), at the strip's front, middle and back.
    #  * Dark (Dessous) along their whole length: lhd_03 shows the grille top and the bar black there, and with
    #    the hood shut the strips only show through the seams round the hood's front edge, which read dark.
    HD_N = 10
    hd_x = [-0.43, -0.40] + [-0.40 + 0.80 * k / HD_N for k in range(1, HD_N)] + [0.40, 0.43]
    from bay import front as bay_front

    def header_cap(x, y1):                                # 3 cm under the hood, and under the lamp tops past |x| 0.40
        hz = hood_z_early(x, y1 + 0.01)
        cap = min(0.93, hz - 0.03) if hz is not None else 0.88
        return min(cap, LAMP_TOP) if abs(x) > 0.40 + 1e-6 else cap

    def lowest_cover(x, y, zmin):
        """Lowest hood or body surface over (x, y) above zmin (every surface a vertical ray meets coming down,
        any material), or None."""
        zs = []
        for ob in (hood, body):
            if ob is None:
                continue
            iv = ob.matrix_world.inverted()
            z = 2.0
            for _ in range(12):
                hit, loc, _n, _i = ob.ray_cast(iv @ Vector((x, y, z)), Vector((0, 0, -1)))
                if not hit:
                    break
                wz = (ob.matrix_world @ loc).z
                if wz < zmin:
                    break
                zs.append(wz)
                z = wz - 1e-4
        return min(zs) if zs else None
    body = bpy.data.objects.get("body")
    for y0, y1, z0, tie in ((1.87, 1.885, 0.80, True), (1.93, 1.94, 0.78, False)):
        tops = {}
        for x in hd_x:                                    # the hood's front edge, station by station
            t = header_cap(x, y1)
            if tie:
                t = min(t, bay_front.TIE_Z0 + HEADER_TIE_OVERLAP)
            cov = [c for c in (lowest_cover(x, y, z0 + HEADER_MIN_H) for y in (y0, (y0 + y1) / 2, y1)) if c is not None]
            if cov:
                t = min(t, min(cov) - HEADER_COVER_GAP)
            tops[x] = max(t, z0 + HEADER_MIN_H - HEADER_COVER_GAP)
        extrude(hd_x, lambda x, y0=y0, y1=y1, z0=z0, t=tops: [(y0, z0), (y1, z0), (y1, t[x]), (y0, t[x])],
                lambda xa, xb, i: 1)
        print("bay_walls: header y %.2f top %.3f..%.3f (ends %.3f, %.3f), Dessous" % (
            y0, min(tops.values()), max(tops.values()), tops[hd_x[0]], tops[hd_x[-1]]))
    add(0, -0.43, 0.43, 1.87, 1.885, 0.55, 0.60)          # bottom strip under the core
    add(1, -0.66, 0.66, 0.99, 1.99, 0.545, 0.555)         # undertray, on under the grille cavity
    # Sides of the bay. The fender skin is single-sided: from the bay its back faces are culled and
    # the wheel-well pocket reads as a hole to the road, and from the game's 30-degree camera you
    # look under the fender's inner lip. One continuous inner-fender panel per side closes it: a
    # quad strip from the apron top (x 0.575) up to the fender lip (found by ray casting the body
    # skin outward from the bay edge) and 6 cm on under the skin, following the skin's height at
    # every station so nothing steps or pokes out. The apron is the matching vertical strip below it.
    body = bpy.data.objects.get("body")
    inv_b = body.matrix_world.inverted() if body else None

    def skin(x, y):
        """First body face under (x, y): (z, material) or None."""
        if body is None:
            return None
        hit, loc, _n, idx = body.ray_cast(inv_b @ Vector((x, y, 2.0)), Vector((0, 0, -1)))
        if not hit:
            return None
        return (body.matrix_world @ loc).z, body.data.materials[body.data.polygons[idx].material_index].name

    def lip(sx, y):
        """Inner edge of the fender top at station y: (|x|, z) of the first high Body hit going outboard."""
        x = 0.69
        while x < 0.80:
            s = skin(sx * x, y)
            if s and s[1] == "Body" and s[0] > 0.85:
                return x, s[0]
            x += 0.005
        return None

    def hood_z(x, y):
        if hood is None:
            return None
        hit, loc, _n, _i = hood.ray_cast(inv @ Vector((x, y, 2.0)), Vector((0, 0, -1)))
        return (hood.matrix_world @ loc).z if hit else None

    def quad(mat_index, pts, want):
        """One quad from four points, wound so its normal points along `want`. A corner pulled onto its
        neighbour (the side panels' lens stop, 2026-10-14) leaves a triangle; less than that, nothing."""
        pts = [p for i, p in enumerate(pts) if (Vector(p) - Vector(pts[i - 1])).length > 1e-5]
        if len(pts) < 3:
            return
        a, b, c = Vector(pts[0]), Vector(pts[1]), Vector(pts[2])
        if (b - a).cross(c - a).dot(Vector(want)) < 0:
            pts = pts[::-1]
        n0 = len(verts)
        verts.extend(tuple(p) for p in pts)
        faces.append(tuple(range(n0, n0 + len(pts))))
        mats.append(mat_index)

    X_APRON = 0.575
    apron_y0 = firewall_y(X_APRON) + PLENUM_GAP          # the cabin's firewall at the apron (y ~0.869) + the gap
    Y_SIDE = (0.80, 1.78)                               # cowl (the hood/fender seam is open back to here) to just behind the lamps
    N_ST = 18
    n_panels = 0
    # 2026-10-14: the side panels stop LENS_GAP behind the headlamp lens, never in front of it. Their
    # last stations ran to y 1.78 at the flange's |x| 0.70-0.76, where the lens of each lamp's outer
    # (corner) cell sits at y 1.72-1.79: the shelf, clamped flat to LAMP_TOP, stood up to 3 cm proud
    # of the lens and showed as a dark body-colour triangle in the upper outer cell (pzview probe:
    # bay_walls face at (0.738, 1.765, 0.882) in front of the lens). The stations stay as they were;
    # each point is only pulled back to just behind the lens (the first head-lamp face met coming in
    # from the front at its x and height), never behind the same column's previous row, so a quad that
    # loses its length becomes a triangle and nothing crosses. Every other point is where it was, so
    # the panel still closes the fender's underside up to the lamp (ending the panels on the lamp-back
    # plates or a row earlier opened slots to the road in the open-hood views, +9 to +21 leak px).
    def _y_stop(x, z):
        if body is None:
            return Y_SIDE[1]
        hit, loc, _n, idx = body.ray_cast(inv_b @ Vector((x, 2.6, min(z, LAMP_TOP))), Vector((0, -1, 0)))
        if hit and body.data.materials[body.data.polygons[idx].material_index].name in HEAD_LAMP_MATS:
            return min(Y_SIDE[1], (body.matrix_world @ loc).y - LENS_GAP)
        return Y_SIDE[1]

    # 2026-10-14: at the cowl end (y < 0.95) the panel sits under the windscreen's black cowl trim and
    # frit, which dip to z 1.08-1.11 between the hood's rear corner and the fender, below the fender
    # lip the row follows: the shelf poked through the trim as a dark-blue sliver at each windscreen
    # lower corner (pzview probe (0.698, 0.828, 1.104)). There every row point stays 1.2 cm under the
    # lowest cover (body or hood, any material, z > 0.95) across the row.
    def _cover(x, y):
        zs = []
        s = skin(x, y)
        if s and s[0] > 0.95:
            zs.append(s[0])
        h = hood_z(x, y)
        if h is not None and h > 0.95:
            zs.append(h)
        return min(zs) if zs else None
    for sx in (-1, 1):
        rows = []
        last = None
        for k in range(N_ST + 1):
            y = Y_SIDE[0] + (Y_SIDE[1] - Y_SIDE[0]) * k / N_ST
            L = lip(sx, y) or last
            if L is None:
                continue
            last = L
            xl, zl = L
            hz = hood_z(sx * X_APRON, y)
            z_in = min(zl - 0.03, hz - 0.04 if hz is not None else 9.0)
            s2 = skin(sx * (xl + 0.06), y)
            z_out = (s2[0] - 0.012) if (s2 and s2[1] == "Body" and s2[0] > 0.80) else zl - 0.03
            z_mid = zl - 0.012
            if y < 0.95:                                  # the cowl end: under the trim (see _cover)
                cov = [c for c in (_cover(sx * (X_APRON + (xl + 0.06 - X_APRON) * t / 10), y) for t in range(11))
                       if c is not None]
                if cov:
                    cap = min(cov) - 0.012
                    z_in, z_mid, z_out = min(z_in, cap), min(z_mid, cap), min(z_out, cap)
            row = ((sx * (X_APRON - 0.0025), y, z_in), (sx * (xl + 0.005), y, z_mid),
                   (sx * (xl + 0.06), y, z_out))
            prev = rows[-1] if rows else None             # each point just behind the lens, monotonic per column
            row = tuple((p[0], max(min(y, _y_stop(p[0], p[2])), prev[i][1] if prev else -9.0), p[2])
                        for i, p in enumerate(row))
            if prev:
                row = tuple(prev[i] if abs(p[1] - prev[i][1]) < 1e-5 else p for i, p in enumerate(row))
            rows.append(row)
        for r0, r1 in zip(rows, rows[1:]):
            quad(0, [r0[0], r0[1], r1[1], r1[0]], (0, 0, 1))          # shelf, apron to lip
            quad(0, [r0[1], r0[2], r1[2], r1[1]], (0, 0, 1))          # flange on under the skin
            # the apron starts behind the cabin's firewall (2026-10-17, CAB-1: its first 5 cm, y 0.80-0.854,
            # stood in the footwell at |x| 0.575 as a body-colour wall)
            y0a, y1a = r0[0][1], r1[0][1]
            za0, za1 = r0[0][2], r1[0][2]
            if y1a <= apron_y0:
                n_panels += 2
                continue
            if y0a < apron_y0:
                za0 = za0 + (za1 - za0) * (apron_y0 - y0a) / (y1a - y0a)
                y0a = apron_y0
            a0 = (sx * X_APRON, y0a, 0.55); a1 = (sx * X_APRON, y1a, 0.55)
            t0 = (sx * X_APRON, y0a, za0 + 0.004); t1 = (sx * X_APRON, y1a, za1 + 0.004)
            n_before = len(faces)
            quad(0, [a0, t0, t1, a1], (-sx, 0, 0))                     # apron, facing the bay
            no_back.update(range(n_before, len(faces)))
            n_panels += 3
    print("bay_walls: %d side-panel quads" % n_panels)
    for sx in (-1, 1):                                    # corners ahead of the wheel wells, under the lamps
        # Dessous (the dark block), not Body (2026-10-14): the top shows in the gap between each
        # headlamp's bottom edge and the bumper top (pzview probe (0.687, 1.857, 0.730)), where the real
        # RD1 has a dark shut line, and the outer side faces the wheel well (black liner on the car)
        add(1, min(sx * 0.575, sx * 0.70), max(sx * 0.575, sx * 0.70), 1.77, 1.87, 0.55, 0.73)
    # Lamp backs: the kotris headlamp housings are open shells, so from the bay you look through
    # them to the road ahead. A vertical strip 1.2 cm behind the measured rear profile of each lamp
    # (LAMP_BACK below), from the undertray up to just under the skin, facing the bay.
    prof = [(0.42, 1.951), (0.44, 1.951), (0.46, 1.895), (0.48, 1.866), (0.50, 1.841), (0.52, 1.822), (0.54, 1.814),
            (0.56, 1.809), (0.58, 1.802), (0.60, 1.799), (0.62, 1.803), (0.64, 1.803), (0.66, 1.802),
            (0.68, 1.801), (0.70, 1.744), (0.72, 1.728), (0.74, 1.738), (0.76, 1.716), (0.79, 1.717)]
    for sx in (-1, 1):
        def plate_top(ax, y):
            """Up to 1.2 cm under whatever covers this spot: the fender skin outboard, the hood inboard."""
            tops = []
            s = skin(sx * ax, y - 0.02)
            if s and s[1] == "Body" and s[0] > 0.80:
                tops.append(s[0])
            hz = hood_z(sx * ax, y - 0.02)
            if hz is not None:
                tops.append(hz)
            # capped under the lamp tops (0.893): at 0.91 the plates showed above each lamp through
            # the lamp / hood seam, and whenever the hood was open
            return min(min(tops) - 0.012, LAMP_TOP) if tops else 0.88
        for (x0, y0), (x1, y1) in zip(prof, prof[1:]):
            yb0, yb1 = y0 - 0.012, y1 - 0.012
            quad(0, [(sx * x0, yb0, 0.55), (sx * x1, yb1, 0.55), (sx * x1, yb1, plate_top(x1, yb1)),
                     (sx * x0, yb0, plate_top(x0, yb0))], (0, -1, 0))
    # audit against the headlamp housings (rear profile measured from the kotris lamps, |x| -> min y)
    LAMP_BACK = [(0.44, 1.951), (0.46, 1.895), (0.48, 1.866), (0.50, 1.841), (0.52, 1.822), (0.54, 1.814),
                 (0.56, 1.809), (0.58, 1.802), (0.60, 1.799), (0.62, 1.803), (0.64, 1.803), (0.66, 1.802),
                 (0.68, 1.801), (0.70, 1.744), (0.72, 1.728), (0.74, 1.738), (0.76, 1.716), (0.79, 1.717)]
    bad = 0
    for (x, y, z) in verts:
        ax = abs(x)
        for (x0, y0), (x1, y1) in zip(LAMP_BACK, LAMP_BACK[1:]):
            if x0 <= ax <= x1:
                back = y0 + (y1 - y0) * (ax - x0) / (x1 - x0)
                if 0.738 <= z <= 0.894 and y > back - 0.005:
                    bad += 1
                break
    print("bay_walls: %d vertices inside a headlamp housing" % bad if bad else "bay_walls: clear of the lamp housings")
    # nothing near the lamps rises above them: the side flanges' last stations followed the fender
    # top (0.93) and showed between the lamp top and the fender edge from the front
    low = 0
    for i, (x, y, z) in enumerate(verts):
        if y > 1.69 and abs(x) > 0.40 and z > LAMP_TOP:
            verts[i] = (x, y, LAMP_TOP)
            low += 1
    print("bay_walls: %d vertices near the lamps clamped to z %.3f" % (low, LAMP_TOP))
    # Engine bay v2 (spec/engine-bay-v2.md, 2026-10-17): the strut towers and the hood hinge bases are body
    # colour on the real car, and the engine sheet has no paint tint, so they are bay walls now. The towers
    # are a lathe of envelope.TOWER_PROFILE (flat top at z 0.962, where the bay's rubber mounts sit); their
    # outboard 1.5 cm hides in the apron.
    # 2026-10-17 (BAY-7): 20 sides (14 showed as flat bands), the sides smooth shaded, the flat top and
    # the bottom flat, so the rim between the side and the top stays sharp.
    from bay import envelope
    seg = TOWER_SEG
    z0 = envelope.TOWER_PROFILE[0][1]
    for tx, ty in envelope.TOWERS:
        n0 = len(verts)
        rings = []
        for r, z in envelope.TOWER_PROFILE:
            if r <= 0.0:
                rings.append([len(verts)])
                verts.append((tx, ty, z))
                continue
            ring = []
            for i in range(seg):
                a = 2 * math.pi * i / seg
                ring.append(len(verts))
                x = tx + r * math.cos(a)
                if abs(x) > TOWER_X_MAX:                        # flat outboard side, inboard of the liner's wall
                    x = math.copysign(TOWER_X_MAX, x)
                verts.append((x, ty + r * math.sin(a), z))
            rings.append(ring)
        for ra, rb in zip(rings, rings[1:]):
            for i in range(seg):
                j = (i + 1) % seg
                if len(rb) != 1:
                    smooth.add(len(faces))                          # a side: smooth (the top fan stays flat)
                faces.append((ra[i], ra[j], rb[0]) if len(rb) == 1 else (ra[i], ra[j], rb[j], rb[i]))
                mats.append(0)
        faces.append(tuple(reversed(rings[0])))                     # bottom cap, faces down
        mats.append(0)
        assert verts[n0][2] == z0
    for sx in (-1, 1):                                    # hinge bases on the cowl corners, under the arms
        hx = sx * 0.555
        add(0, hx - 0.02, hx + 0.02, 0.92, 1.00, 0.99, 1.025)
    rear_valance(add)
    for sx in (-1, 1):                                    # dash-end shields (DASH_SHIELD), never backed
        n0 = len(verts)
        verts.extend((sx * DASH_SHIELD_X, y, z) for y, z in DASH_SHIELD)
        face(list(range(n0, len(verts))), (sx, 0.0, 0.0), 1)
        no_back.add(len(faces) - 1)
    print("bay_walls: dash-end shields at |x| %.3f, y %.3f..%.3f, z %.3f..%.3f" % (
        DASH_SHIELD_X, min(p[0] for p in DASH_SHIELD), max(p[0] for p in DASH_SHIELD),
        min(p[1] for p in DASH_SHIELD), max(p[1] for p in DASH_SHIELD)))
    me = bpy.data.meshes.new(WALLS)
    me.from_pydata(verts, [], faces)
    me.validate()
    me.materials.append(_body_material())
    me.materials.append(_dessous_material())
    if len(me.polygons) != len(faces):
        print("bay_walls warning: validate() dropped faces (%d of %d): materials may be shifted" % (len(me.polygons), len(faces)))
    for k, (poly, mi) in enumerate(zip(me.polygons, mats)):
        poly.material_index = mi
        poly.use_smooth = k in smooth
    attr = me.attributes.new(NO_BACKFILL, 'INT', 'FACE')
    attr.data.foreach_set("value", [1 if k in no_back else 0 for k in range(len(me.polygons))])
    print("bay_walls: %d apron faces never backfilled (%s)" % (len(no_back), NO_BACKFILL))
    ob = bpy.data.objects.new(WALLS, me)
    ob["towers"] = 1                                      # bay/preview.py: no stand-in towers needed
    ref = bpy.data.objects.get("body")
    (ref.users_collection[0] if ref else bpy.context.scene.collection).objects.link(ob)
    print("bay_walls: %d faces" % len(me.polygons))
    return ob


def build():
    old = bpy.data.objects.get(NAME)
    if old:
        bpy.data.objects.remove(old, do_unlink=True)
    verts, faces = [], []
    body = bpy.data.objects.get("body")
    from mathutils import Vector

    def skin_x(side, cy, cz):
        """|x| of the body's outer skin at (y, z), cast from outside the car inward; None if nothing."""
        if body is None:
            return None
        inv = body.matrix_world.inverted()
        hit, loc, _n, _i = body.ray_cast(inv @ Vector((side * 1.6, cy, cz)), Vector((-side, 0.0, 0.0)))
        return abs((body.matrix_world @ loc).x) if hit else None
    for y in WHEEL_Y:
        for side in (1, -1):
            _drum(verts, faces, side, y, skin_x)
    me = bpy.data.meshes.new(NAME)
    me.from_pydata(verts, [], faces)
    me.validate()
    me.materials.append(_material())
    ob = bpy.data.objects.new(NAME, me)
    ref = bpy.data.objects.get("body")
    (ref.users_collection[0] if ref else bpy.context.scene.collection).objects.link(ob)
    for p in me.polygons:
        p.use_smooth = True
    print("arch_liners: %d faces" % len(me.polygons))
    build_antenna()
    build_bay_walls()
    return ob


build()
