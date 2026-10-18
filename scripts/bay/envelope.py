r"""
The space the engine bay v2 lives in (spec/engine-bay-v2.md "Envelope"), its audit, and the hood's
insulator pad. Model metres, +x right (passenger), +y forward, +z up.

The bay is closed by build_liners.build_bay_walls (painted, on the shell sheet): firewall face at
y 0.99, aprons at |x| 0.575, the radiator support's side panels at y 1.70-1.715 (|x| 0.46-0.66),
the header strips at y 1.87 and 1.93, the undertray top at z 0.555. The strut towers and the hinge
bases are body colour, so they are bay_walls too. Nothing in engine_block may cross those, come
within PAD_ZONE of the hood skin, or enter a headlamp housing.
"""
import bpy
from mathutils import Vector

X_APRON = 0.575          # inner face of the aprons
Y_FIREWALL = 0.99        # firewall face
Z_TRAY = 0.555           # undertray top
TOWERS = ((-0.50, 1.24), (0.50, 1.24))   # strut tower centres (x, y); radius TOWER_R, tops at z 0.966
TOWER_R = 0.090
# the towers' body-colour shell (bay_walls): (radius, z) bottom to top; the black rubber mount, its
# plate and three nuts sit on the flat top at z 0.962 (sides group, engine_block)
TOWER_PROFILE = [(0.090, 0.60), (0.090, 0.925), (0.080, 0.950), (0.062, 0.962), (0.0, 0.962)]
PAD_ZONE = 0.055         # metres under the hood skin the insulator pad occupies (3 cm gap + 2.2 cm pad)
PAD_Y0, PAD_Y1 = 1.07, 1.86   # the pad's rear and front rows (hood_pad)
# hood underside profile (centre) from the decimated hood mesh, metres: y -> z (the fallback where a
# ray misses; hood_limit ray casts the real skin)
HOOD_Z = [(0.98, 1.13), (1.10, 1.125), (1.30, 1.08), (1.50, 1.035), (1.65, 1.01), (1.78, 0.975), (1.86, 0.955)]
# headlamp housings: how far back (min y) the kotris lamp reaches per |x|; a bay vertex with y beyond
# that line inside the lamp's z band sits inside the housing
LAMP_BACK = [(0.44, 1.951), (0.46, 1.895), (0.48, 1.866), (0.50, 1.841), (0.52, 1.822), (0.54, 1.814),
             (0.56, 1.809), (0.58, 1.802), (0.60, 1.799), (0.62, 1.803), (0.64, 1.803), (0.66, 1.802),
             (0.68, 1.801), (0.70, 1.744), (0.72, 1.728), (0.74, 1.738), (0.76, 1.716), (0.79, 1.717)]
LAMP_Z = (0.738, 0.894)


def _hood_profile(y):
    for (y0, z0), (y1, z1) in zip(HOOD_Z, HOOD_Z[1:]):
        if y0 <= y <= y1:
            return z0 + (z1 - z0) * (y - y0) / (y1 - y0)
    return HOOD_Z[0][1] if y < HOOD_Z[0][0] else HOOD_Z[-1][1]


def hood_skin(x, y):
    """z of the hood's skin above (x, y): ray cast on the real hood, the profile where it misses."""
    hood = bpy.data.objects.get("hood")
    if hood is not None:
        inv = hood.matrix_world.inverted()
        down = (inv.to_3x3() @ Vector((0.0, 0.0, -1.0))).normalized()
        hit, loc, _n, _i = hood.ray_cast(inv @ Vector((x, y, 2.0)), down)
        if hit:
            return (hood.matrix_world @ loc).z
    return _hood_profile(y) - 0.20 * x * x


def hood_limit(x, y):
    """The highest z a part may reach at (x, y): the hood skin less the pad zone."""
    return hood_skin(x, y) - PAD_ZONE


def lamp_back(ax):
    for (x0, y0), (x1, y1) in zip(LAMP_BACK, LAMP_BACK[1:]):
        if x0 <= ax <= x1:
            return y0 + (y1 - y0) * (ax - x0) / (x1 - x0)
    return None


def audit(objs, quiet=False):
    """Every part that breaks the envelope: into the pad zone, a lamp housing, through an apron, the
    firewall or the undertray, or into a strut tower. Prints CLEARANCE lines; returns the problems."""
    hood = bpy.data.objects.get("hood")
    inv = hood.matrix_world.inverted() if hood else None
    down = (inv.to_3x3() @ Vector((0.0, 0.0, -1.0))).normalized() if hood else None
    problems = []
    for o in objs:
        pad = lamp = wall = tower = 0.0
        n_lamp = 0
        for v in o.data.vertices:
            p = o.matrix_world @ v.co
            if hood is not None:
                hit, loc, _n, _i = hood.ray_cast(inv @ Vector((p.x, p.y, 2.0)), down)
                if hit:
                    pad = max(pad, p.z - ((hood.matrix_world @ loc).z - PAD_ZONE))
            back = lamp_back(abs(p.x))
            if back is not None and LAMP_Z[0] <= p.z <= LAMP_Z[1] and p.y > back - 0.005:
                n_lamp += 1
            wall = max(wall, abs(p.x) - (X_APRON - 0.005), (Y_FIREWALL + 0.005) - p.y, (Z_TRAY + 0.005) - p.z)
            for tx, ty in TOWERS:
                d = ((p.x - tx) ** 2 + (p.y - ty) ** 2) ** 0.5
                if d < TOWER_R and p.z < 0.97:
                    tower = max(tower, TOWER_R - d)
        if pad > 0.0005:
            problems.append((o.name, "%.3f m into the hood pad zone" % pad))
        if n_lamp:
            problems.append((o.name, "%d vertices inside a headlamp housing" % n_lamp))
        if wall > 0.0005:
            problems.append((o.name, "%.3f m through an apron, the firewall or the undertray" % wall))
        if tower > 0.0005:
            problems.append((o.name, "%.3f m into a strut tower" % tower))
    if not quiet:
        for name, what in problems:
            print("CLEARANCE %-20s %s" % (name, what))
        if not problems:
            print("CLEARANCE ok: nothing in the pad zone, the lamps, the walls or the towers")
    return problems


def hood_pad(collection, material):
    """Grey fibre insulator following the hood underside, joined into the hood so it swings with it.
    material(name) -> bpy material (kit.material). Uses DecalHoodPad when registered."""
    hood = bpy.data.objects.get("hood")
    if hood is None:
        return None
    # 2026-10-17 (review OPEN-10): the pad started at y 0.98, and its rear 7 cm swept through the cowl's black
    # plastic and the washer nozzles' bodies under the hood's rear edge between 5 and 50 % open (up to 75 new
    # face pairs, every one a pad face). The rear rows' points swing back as the hood turns about the cowl
    # hinge; from y 1.07 on they move forward and up, clear of the cowl: the pad starts there
    ys = [PAD_Y0 + i * (PAD_Y1 - PAD_Y0) / 8 for i in range(9)]
    verts, faces = [], []
    t = 0.022
    GAP = 0.030
    xs = (-0.48, -0.32, -0.16, 0.0, 0.16, 0.32, 0.48)
    n = 2 * len(xs)
    misses = 0
    for y in ys:
        scale = 1.0 - 0.30 * max(0.0, (y - 1.30) / 0.56)             # narrows toward the nose
        top = []
        for x in xs:
            xw = x * scale
            z = hood_skin(xw, y)
            top.append((xw, y, z - GAP))
        verts += top
        verts += [(x, y2, z - t) for x, y2, z in top]
    nx = len(xs)
    for i in range(len(ys) - 1):
        a, b2 = i * n, (i + 1) * n
        for k in range(nx - 1):
            faces.append((a + k, a + k + 1, b2 + k + 1, b2 + k))                     # top
            faces.append((a + nx + k + 1, a + nx + k, b2 + nx + k, b2 + nx + k + 1))  # bottom, faces down
        faces.append((a + nx - 1, a + nx + nx - 1, b2 + nx + nx - 1, b2 + nx - 1))   # right edge
        faces.append((a + 0, b2 + 0, b2 + nx, a + nx))                              # left edge
    for k in range(nx - 1):
        faces.append((k + 1, k, nx + k, nx + k + 1))                                 # rear cap
        last = (len(ys) - 1) * n
        faces.append((last + k, last + k + 1, last + nx + k + 1, last + nx + k))      # front cap
    me = bpy.data.meshes.new("hood_pad")
    me.from_pydata(verts, [], faces)
    me.validate()
    me.materials.append(material("Grey"))
    me.materials.append(material("DecalHoodPad"))
    for poly in me.polygons:
        poly.use_smooth = False
        poly.material_index = 1 if poly.normal.z < -0.5 else 0          # decal on the downward faces only
    pad = bpy.data.objects.new("hood_pad", me)
    collection.objects.link(pad)
    for o in bpy.data.objects:
        o.select_set(False)
    pad.select_set(True)
    hood.select_set(True)
    bpy.context.view_layer.objects.active = hood
    bpy.ops.object.join()
    hood.select_set(False)
    print("hood_pad: %d grid points, %d off the skin" % (len(ys) * len(xs), misses))
    return hood
